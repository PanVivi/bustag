"""Reproducible comparisons and runtime-checked, atomic model generations."""
import hashlib
import json
import os
import pickle
import platform
import tempfile
import uuid

import numpy as np
import sklearn
from sklearn.feature_extraction import DictVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import train_test_split
from sklearn.neighbors import KNeighborsClassifier

from .ranking import FEATURE_VERSION, features, auxiliary_score, collection_prototype
from .store import Store, encode, now


def runtime():
    return {'python': platform.python_version(), 'numpy': np.__version__, 'sklearn': sklearn.__version__}


def metrics(labels, scores, k=10):
    labels = np.asarray(labels)
    scores = np.asarray(scores)
    k = min(k, len(labels))
    top = labels[np.argsort(-scores, kind='stable')[:k]]
    precision = float(np.mean(top)) if k else 0
    # Wilson interval on labelled top-K only, not on unseen recommendations.
    denominator = 1 + 1.96**2 / max(k, 1)
    centre = (precision + 1.96**2 / (2*max(k, 1))) / denominator
    margin = 1.96 * np.sqrt(precision*(1-precision)/max(k, 1) + 1.96**2/(4*max(k, 1)**2)) / denominator
    return {'n': len(labels), 'positive': int(sum(labels)), 'k': k,
            'precision_at_k': precision, 'recall_at_k': float(sum(top)/sum(labels)) if sum(labels) else 0,
            'positive_recall': float(sum((scores >= .5) & (labels == 1)) / max(1, sum(labels))),
            'precision': float(sum((scores >= .5) & (labels == 1)) / max(1, sum(scores >= .5))),
            'precision_at_k_wilson95': [max(0, centre-margin), min(1, centre+margin)],
            'false_positive_count': int(sum((scores >= .5) & (labels == 0))),
            'false_negative_count': int(sum((scores < .5) & (labels == 1)))}


def classifier(algorithm, n):
    if algorithm in ('legacy_knn', 'canonical_knn'):
        return KNeighborsClassifier(n_neighbors=min(11, n))
    return LogisticRegression(solver='liblinear', class_weight='balanced', max_iter=1000, random_state=42)


def legacy_features(store, work_id, typed):
    """Reconstruct baseline metadata without canonical mapping/normalization."""
    result = {}
    for row in store.rows('''SELECT s.category,s.name FROM work_tag w JOIN source_tag s
       ON s.source=w.source AND s.category=w.category AND s.source_id=w.source_id WHERE w.work_id=?''', (work_id,)):
        result[(row['category'] + ':' if typed else '') + row['name']] = 1
    for row in store.rows('SELECT DISTINCT a.name FROM actor a JOIN work_actor w ON a.actor_id=w.actor_id WHERE work_id=?', (work_id,)):
        result[('star:' if typed else '') + row['name']] = 1
    code = store.rows('SELECT code FROM work_identity WHERE work_id=?', (work_id,))[0]['code']
    if typed and code:
        result['series:' + code.split('-')[0]] = 1
    return result


def training_data(store):
    rows = store.rows('SELECT * FROM explicit_work_feedback ORDER BY confirmed_at,work_id')
    counts = {v: sum(r['value'] == v for r in rows) for v in (0, 1)}
    if len(rows) < 40 or min(counts.values()) < 10:
        raise ValueError('需要至少40部独立人工打标作品，且正负各10部；继续使用演员优先保守排序')
    return rows


def compare(store, rows):
    ids = np.arange(len(rows))
    y = np.array([r['value'] for r in rows])
    train_ids, test_ids = train_test_split(ids, test_size=.25, stratify=y, random_state=42)
    algorithms = ('legacy_knn', 'branch_v2', 'canonical_knn', 'final_lr')
    documents = {
        'legacy_knn': [legacy_features(store, r['work_id'], False) for r in rows],
        'branch_v2': [legacy_features(store, r['work_id'], True) for r in rows],
        'final_lr': [features(store, r['work_id']) for r in rows],
    }
    documents['canonical_knn'] = documents['final_lr']
    report = {'split_seed': 42, 'data_time': now(), 'sample_count': len(rows),
              'positive': int(sum(y)), 'negative': int(sum(1-y)), 'comparison': {},
              'limitations': ['当前元数据快照对照；不声称历史无泄漏回测。',
                '演员状态/标签映射/收藏缺少完整历史快照时，不报告其历史因果收益。',
                '收藏辅助默认0；真实时间点收藏快照消融通过前不得启用。'],
              'collection_weight': 0.0, 'temporal': {}}
    report['ablations'] = {}
    final_predictions = None
    for algorithm in algorithms:
        docs = documents[algorithm]
        encoder = DictVectorizer()
        X = encoder.fit_transform([docs[i] for i in train_ids])
        model = classifier(algorithm, len(train_ids))
        kwargs = {}
        if algorithm == 'branch_v2':
            from datetime import datetime
            reference = datetime.fromisoformat(now())
            kwargs['sample_weight'] = [max(.25, .5**(max(0, (reference-datetime.fromisoformat(rows[i]['confirmed_at'])).days)/365)) for i in train_ids]
        model.fit(X, y[train_ids], **kwargs)
        predictions = model.predict_proba(encoder.transform([docs[i] for i in test_ids]))[:, 1]
        report['comparison'][algorithm] = metrics(y[test_ids], predictions)
        if algorithm == 'final_lr':
            final_predictions = predictions
    # Same immutable split for feature ablations; these are current-snapshot
    # diagnostics, never retrospective evidence of a user's future preference.
    canonical = documents['final_lr']
    for name, transform in (
            ('without_actor', lambda d: {k: v for k, v in d.items() if not k.startswith('actor:')}),
            ('without_category_normalization', lambda d: {k: 1.0 for k in d})):
        docs = [transform(d) for d in canonical]
        encoder = DictVectorizer()
        X = encoder.fit_transform([docs[i] for i in train_ids])
        if X.shape[1]:
            fitted = classifier('final_lr', len(train_ids)).fit(X, y[train_ids])
            score = fitted.predict_proba(encoder.transform([docs[i] for i in test_ids]))[:, 1]
            report['ablations'][name] = metrics(y[test_ids], score)
    prototype = collection_prototype(store)
    auxiliary = np.array([auxiliary_score(canonical[i], prototype) for i in test_ids])
    report['ablations']['collection'] = {
        'status': 'diagnostic_only_not_authorized_for_activation',
        'eligible_feature_count': len(prototype),
        'weights': {str(weight): metrics(y[test_ids], final_predictions + weight*auxiliary)
                    for weight in (0.0, 0.05, 0.1, 0.2)}}
    liked = {r['actor_id'] for r in store.rows("SELECT actor_id FROM actor_preference WHERE state='like'")}
    actor_first = np.array([any(key[6:] in liked for key in canonical[i] if key.startswith('actor:')) for i in test_ids])
    order = sorted(range(len(test_ids)), key=lambda i: (not actor_first[i], -final_predictions[i]))
    top = order[:min(10, len(order))]
    report['ablations']['actor_priority_current_states'] = {
        'status': 'diagnostic_only_manual_states_have_no_historical_snapshot',
        'precision_at_k': float(np.mean(y[test_ids][top])),
        'liked_actor_candidates': int(sum(actor_first)),
        'liked_actor_top_k': int(sum(actor_first[top])),
        'without_priority': metrics(y[test_ids], final_predictions)}
    seen = {k for i in train_ids for k in canonical[i] if k.startswith('actor:')}
    unseen = np.array([not any(k in seen for k in canonical[i] if k.startswith('actor:')) for i in test_ids])
    report['actor_segments'] = {
        name: metrics(y[test_ids][mask], final_predictions[mask])
        for name, mask in (('new_or_missing_actor', unseen), ('seen_actor', ~unseen)) if any(mask)}
    # Time split is a current-metadata diagnostic only. Repeated feedback after the
    # cutoff or missing historical metadata makes strict historical claims invalid.
    cut = int(len(rows)*.75)
    if len(set(y[:cut])) == 2 and len(set(y[cut:])) == 2:
        encoder = DictVectorizer()
        X = encoder.fit_transform(documents['final_lr'][:cut])
        model = classifier('final_lr', cut).fit(X, y[:cut])
        report['temporal'] = metrics(y[cut:], model.predict_proba(encoder.transform(documents['final_lr'][cut:]))[:, 1])
        report['temporal']['status'] = 'diagnostic_current_metadata_not_historical_acceptance'
    else:
        report['temporal'] = {'status': 'insufficient_class_coverage'}
    # Selection must not use the held-out test results: choose in a separate inner split.
    inner_train, inner_valid = train_test_split(train_ids, test_size=.25, stratify=y[train_ids], random_state=17)
    selection = {}
    for algorithm in ('final_lr', 'canonical_knn'):
        encoder = DictVectorizer()
        X = encoder.fit_transform([documents[algorithm][i] for i in inner_train])
        model = classifier(algorithm, len(inner_train)).fit(X, y[inner_train])
        score = model.predict_proba(encoder.transform([documents[algorithm][i] for i in inner_valid]))[:, 1]
        selection[algorithm] = metrics(y[inner_valid], score, k=max(1, len(inner_valid)//3))['precision_at_k']
    winner = max(selection, key=selection.get)
    report['selection'] = selection
    report['selected'] = winner
    return report, documents[winner]


def _atomic_json(path, value):
    fd, temporary = tempfile.mkstemp(dir=os.path.dirname(path), prefix='.tmp-')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as stream:
            json.dump(value, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def train(store, directory):
    snapshot = Store(':memory:')
    store.conn.backup(snapshot.conn)
    try:
        return _train_snapshot(store, snapshot, directory)
    finally:
        snapshot.close()


def _train_snapshot(store, snapshot, directory):
    rows = training_data(snapshot)
    mapping = int(snapshot.meta('mapping_version'))
    previous = snapshot.meta('active_model')
    version = uuid.uuid4().hex
    report, documents = compare(snapshot, rows)
    encoder = DictVectorizer()
    X = encoder.fit_transform(documents)
    model = classifier(report['selected'], len(rows)).fit(X, [r['value'] for r in rows])
    manifest = {'version': version, 'runtime': runtime(), 'mapping_version': mapping,
                'feature_version': FEATURE_VERSION, 'data_sha256': hashlib.sha256(encode(rows).encode()).hexdigest(),
                'created_at': now(), 'report': report, 'parameters': model.get_params()}
    os.makedirs(directory, mode=0o700, exist_ok=True)
    artifact = os.path.join(directory, version + '.pkl')
    # One immutable generation holds model, encoder and mapping contract. The small
    # pointer is switched only after readback, checksum and DB score transaction.
    with open(artifact, 'xb') as stream:
        pickle.dump({'model': model, 'encoder': encoder, 'manifest': manifest,
                     'mapping': snapshot.rows('SELECT * FROM source_tag'),
                     'corrections': snapshot.rows('SELECT * FROM tag_override')}, stream)
        stream.flush()
        os.fsync(stream.fileno())
    with open(artifact, 'rb') as stream:
        payload = stream.read()
    manifest['sha256'] = hashlib.sha256(payload).hexdigest()
    checked = pickle.loads(payload)
    checked['model'].predict_proba(checked['encoder'].transform(documents[:1]))
    if mapping != int(store.meta('mapping_version')):
        raise ValueError('标签映射已变化，保留旧模型，请重新训练')
    _atomic_json(os.path.join(directory, version + '.json'), manifest)
    scored = _score_rows(snapshot, checked)
    with store.transaction():
        store.conn.execute('BEGIN IMMEDIATE')
        if mapping != int(store.meta('mapping_version')) or store.meta('active_model') != previous:
            raise ValueError('Model or mapping changed while fitting; old generation retained')
        _write_scores(store, scored)
        store.conn.execute('INSERT INTO model_manifest VALUES (?,?,?)', (version, encode(manifest), now()))
        store.set_meta('previous_model', previous or '')
        store.set_meta('active_model', version)
    return report


def load(store, directory, version=None):
    version = version or store.meta('active_model')
    if not version or not all(c in '0123456789abcdef' for c in version) or len(version) != 32:
        raise ValueError('No validated active model')
    with open(os.path.join(directory, version + '.json'), encoding='utf-8') as stream:
        manifest = json.load(stream)
    # Check runtime before unpickling, including old sklearn/numpy combinations.
    if manifest['runtime'] != runtime():
        raise ValueError('Model runtime mismatch; retrain in this runtime')
    with open(os.path.join(directory, version + '.pkl'), 'rb') as stream:
        payload = stream.read()
    if hashlib.sha256(payload).hexdigest() != manifest['sha256']:
        raise ValueError('Model checksum mismatch')
    if manifest['mapping_version'] != int(store.meta('mapping_version')):
        raise ValueError('Mapping changed; retrain required')
    return pickle.loads(payload)


def _score_rows(store, bundle):
    manifest = bundle['manifest']
    works = store.rows('SELECT work_id FROM work_identity ORDER BY work_id')
    docs = [features(store, w['work_id']) for w in works]
    if not works:
        return []
    scores = bundle['model'].predict_proba(bundle['encoder'].transform(docs))[:, 1]
    return [(work['work_id'], manifest['version'], FEATURE_VERSION, manifest['mapping_version'], float(score), 0, now()) for work, score in zip(works, scores)]


def _write_scores(store, rows):
    store.conn.executemany('INSERT OR REPLACE INTO v2_recommendation_score VALUES (?,?,?,?,?,?,?)', rows)


def rescore(store, bundle):
    snapshot = Store(':memory:')
    store.conn.backup(snapshot.conn)
    try:
        rows = _score_rows(snapshot, bundle)
    finally:
        snapshot.close()
    with store.transaction():
        store.conn.execute('BEGIN IMMEDIATE')
        manifest = bundle['manifest']
        if (store.meta('active_model') != manifest['version'] or
                int(store.meta('mapping_version')) != manifest['mapping_version']):
            raise ValueError('Stale scoring task; active generation retained')
        _write_scores(store, rows)
    return len(rows)


def rollback(store, directory):
    previous = store.meta('previous_model')
    if not previous:
        raise ValueError('No previous model generation')
    bundle = load(store, directory, previous)
    active = store.meta('active_model')
    rows = _score_rows(store, bundle)
    with store.transaction():
        store.conn.execute('BEGIN IMMEDIATE')
        if store.meta('active_model') != active or int(store.meta('mapping_version')) != bundle['manifest']['mapping_version']:
            raise ValueError('Model or mapping changed during rollback')
        _write_scores(store, rows)
        store.set_meta('previous_model', active)
        store.set_meta('active_model', previous)
