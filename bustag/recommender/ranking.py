"""One preference model, two candidate inventories, immutable manual priority."""
import json
import math
from collections import defaultdict
from urllib.parse import urlencode


FEATURE_VERSION = 'typed-normalized-1'


def features(store, work_id):
    groups = defaultdict(set)
    for row in store.rows('SELECT DISTINCT actor_id FROM work_actor WHERE work_id=?', (work_id,)):
        groups['actor'].add(row['actor_id'])
    tags = {r['tag_id']: r for r in store.rows('''SELECT DISTINCT c.* FROM canonical_tag c
        JOIN source_tag s ON s.tag_id=c.tag_id JOIN work_tag w
        ON (w.source=s.source AND w.category=s.category AND w.source_id=s.source_id)
        WHERE w.work_id=?''', (work_id,))}
    for row in store.rows('SELECT c.*,o.enabled FROM tag_override o JOIN canonical_tag c ON c.tag_id=o.tag_id WHERE o.work_id=?', (work_id,)):
        if row['enabled']:
            tags[row['tag_id']] = row
        else:
            tags.pop(row['tag_id'], None)
    for row in tags.values():
        groups['tag:' + row['category']].add(row['tag_id'])
    work = store.rows('SELECT code FROM work_identity WHERE work_id=?', (work_id,))[0]
    if work['code']:
        groups['series'].add(work['code'].split('-')[0])
    # L1 within category: one film with many actors/tags has no extra mass.
    result = {category + ':' + value: 1.0 / len(values)
              for category, values in groups.items() for value in values}
    # Missing metadata is not evidence of absence. Do not emit negative features.
    return result


def legacy_card_details(store, codes):
    """Attach V2 score and correction state to existing JavBus tag cards.

    The legacy /tagit rating buttons remain the sole work-feedback writer. This
    helper only reads the V2 projection keyed by the same JavBus code.
    """
    codes = list(dict.fromkeys(str(code) for code in codes if code))
    if not codes:
        return {}
    placeholders = ','.join('?' for _ in codes)
    works = store.rows('''SELECT si.source_id AS source_code,w.work_id,
           s.score,s.auxiliary,s.model_version,s.mapping_version
        FROM source_item si JOIN work_identity w ON w.work_id=si.work_id
        LEFT JOIN v2_recommendation_score s ON s.work_id=w.work_id
        WHERE si.source='javbus' AND si.source_id IN (''' + placeholders + ')', tuple(codes))
    if not works:
        return {}

    active_model = store.meta('active_model', '')
    mapping_version = int(store.meta('mapping_version', '0') or 0)
    details = {}
    codes_by_work = defaultdict(list)
    for row in works:
        current = bool(active_model and row['score'] is not None and
                       row['model_version'] == active_model and
                       row['mapping_version'] == mapping_version)
        model_score = float(row['score']) if current else None
        auxiliary = float(row['auxiliary'] or 0.0) if current else 0.0
        detail = {
            'work_id': row['work_id'],
            'has_score': row['score'] is not None,
            'model_current': current,
            'model_score': model_score,
            'auxiliary': auxiliary,
            'match_score': model_score + auxiliary if current else None,
            'actors': [],
            'tags': [],
        }
        details[row['source_code']] = detail
        codes_by_work[row['work_id']].append(row['source_code'])

    work_ids = list(codes_by_work)
    work_marks = ','.join('?' for _ in work_ids)
    actors = store.rows('''SELECT wa.work_id,a.actor_id,a.name,
           coalesce(p.state,'pending') AS state
        FROM work_actor wa JOIN actor a ON a.actor_id=wa.actor_id
        LEFT JOIN actor_preference p ON p.actor_id=a.actor_id
        WHERE wa.work_id IN (''' + work_marks + ') ORDER BY wa.work_id,a.name,a.actor_id',
        tuple(work_ids))
    for actor in actors:
        for code in codes_by_work[actor['work_id']]:
            details[code]['actors'].append({
                'actor_id': actor['actor_id'], 'name': actor['name'], 'state': actor['state']})

    tags = store.rows('''SELECT DISTINCT wt.work_id,c.tag_id,c.category,c.name,
           coalesce(o.enabled,1) AS enabled
        FROM work_tag wt JOIN source_tag s
          ON s.source=wt.source AND s.category=wt.category AND s.source_id=wt.source_id
        JOIN canonical_tag c ON c.tag_id=s.tag_id
        LEFT JOIN tag_override o ON o.work_id=wt.work_id AND o.tag_id=c.tag_id
        WHERE wt.work_id IN (''' + work_marks + ') ORDER BY wt.work_id,c.category,c.name,c.tag_id',
        tuple(work_ids))
    for tag in tags:
        for code in codes_by_work[tag['work_id']]:
            details[code]['tags'].append({
                'tag_id': tag['tag_id'], 'category': tag['category'],
                'name': tag['name'], 'enabled': bool(tag['enabled'])})
    return details


def collection_prototype(store):
    works = store.rows('''SELECT DISTINCT m.work_id FROM media_copy m
       JOIN library_inventory l ON l.server=m.server AND l.generation=m.generation
       LEFT JOIN explicit_work_feedback f ON f.work_id=m.work_id
       WHERE m.work_id IS NOT NULL AND m.confidence=1 AND f.work_id IS NULL AND l.stale=0''')
    counts = defaultdict(float)
    documents = [features(store, row['work_id']) for row in works]
    for doc in documents:
        for key in doc:
            counts[key] += 1
    # Suppress ubiquitous features and normalize per work. Duplicate copies do not vote.
    prototype = defaultdict(float)
    for doc in documents:
        for key, value in doc.items():
            if key.startswith('tag:'):
                tag_id = key.rsplit(':', 1)[1]
                verified = store.rows('SELECT 1 FROM source_tag WHERE tag_id=? AND verified=1 LIMIT 1', (tag_id,))
                if not verified:
                    continue
            prototype[key] += value * math.log((len(documents) + 1) / (counts[key] + 0.5))
    norm = math.sqrt(sum(v*v for v in prototype.values())) or 1
    return {key: value / norm for key, value in prototype.items()}


def auxiliary_score(doc, prototype):
    norm = math.sqrt(sum(v*v for v in doc.values())) or 1
    return sum(value * prototype.get(key, 0) for key, value in doc.items()) / norm


def rank(store, entry='discover', limit=20, offset=0, conflict='review', exploration=0.1):
    if entry not in ('discover', 'local', 'review') or conflict not in ('review', 'actor_first'):
        raise ValueError('Invalid candidate policy')
    if not 0 <= exploration <= 0.2:
        raise ValueError('Exploration quota must be between 0 and .2')
    queues = defaultdict(list)
    mapping = int(store.meta('mapping_version'))
    active = store.meta('active_model', '')
    for work in store.rows('''SELECT w.*,f.value AS feedback,s.score,s.auxiliary,s.model_version,s.mapping_version
         FROM work_identity w LEFT JOIN explicit_work_feedback f ON f.work_id=w.work_id
         LEFT JOIN v2_recommendation_score s ON s.work_id=w.work_id'''):
        if work['feedback'] == 0:
            continue
        copies = store.rows('''SELECT m.*,l.stale FROM media_copy m JOIN library_inventory l
           ON l.server=m.server AND l.generation=m.generation WHERE work_id=?''', (work['work_id'],))
        if entry == 'discover' and copies:
            continue
        playable = [c for c in copies if c['playable'] and not c['stale']]
        if entry == 'local' and not playable:
            continue
        actors = store.rows('''SELECT DISTINCT a.actor_id,a.name,coalesce(p.state,'pending') AS state
            FROM actor a JOIN work_actor w ON w.actor_id=a.actor_id
            LEFT JOIN actor_preference p ON p.actor_id=a.actor_id WHERE w.work_id=?''', (work['work_id'],))
        states = {a['state'] for a in actors}
        is_conflict = 'like' in states and 'dislike' in states
        if is_conflict and conflict == 'review':
            queue = 'review'
        elif 'like' in states:
            queue = 'actor_first'
        else:
            queue = 'general'
        if (entry == 'review') != (queue == 'review'):
            continue
        current = work['mapping_version'] == mapping and work['model_version'] == active
        score = work['score'] if current else 0.5
        auxiliary = work['auxiliary'] if current else 0
        doc = features(store, work['work_id'])
        if queue == 'general' and ('pending' in states or not actors or len(doc) <= 2 or abs(score - 0.5) < 0.1):
            queue = 'explore'
        reasons = []
        if queue == 'actor_first':
            reasons.append('人工喜欢演员：' + '、'.join(a['name'] for a in actors if a['state'] == 'like'))
        if queue == 'review':
            reasons.append('演员人工偏好冲突，待确认')
        reasons.append('模型匹配分数' if current else '保守排序：模型缺失或待重新训练')
        work.update(queue=queue, score=score, auxiliary=auxiliary, actors=actors, reasons=reasons,
                    media=sorted(playable, key=lambda c: (c['server'], c['item_id']))[:1])
        queues[queue].append(work)
    for values in queues.values():
        values.sort(key=lambda w: (-(w['score'] + w['auxiliary']), w['work_id']))
    if entry == 'review':
        ordered = queues['review']
    else:
        # Global deterministic slots preserve priority across pagination. Exploration is
        # a limited explicit exception; general scores can never overtake actor_first.
        primary = queues['actor_first'] + queues['general']
        explore = queues['explore']
        ordered = []
        stride = round(1 / exploration) if exploration else 0
        while primary:
            if stride and explore and (len(ordered) + 1) % stride == 0:
                ordered.append(explore.pop(0))
            else:
                ordered.append(primary.pop(0))
        ordered.extend(explore)
    return ordered[offset:offset+limit]


def emby_link(base, server_id, item_id):
    # Secrets never enter URLs. Server ID is Emby's public system identifier.
    return base.rstrip('/') + '/web/index.html#!/item?' + urlencode({'id': item_id, 'serverId': server_id})
