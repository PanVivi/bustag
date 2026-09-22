import json
import sqlite3

import pytest

from bustag.recommender.store import Store, normalize_code
from bustag.recommender.ranking import features, rank, collection_prototype, auxiliary_score, emby_link
from bustag.recommender.emby import sync, match_work
from conftest import work


def test_actor_priority_survives_wrong_genre_low_score_and_single_dislike(store):
    preferred, actor, _ = work(store, 1, 'preferred', 'unwanted')
    unknown, _, _ = work(store, 2, 'unknown', 'favoured')
    store.preference(actor, 'like')
    with store.transaction():
        store.set_meta('active_model', 'test')
        for wid, score in ((preferred, .01), (unknown, .99)):
            store.conn.execute('INSERT INTO v2_recommendation_score VALUES (?,?,?,?,?,?,?)', (wid, 'test', 'v', 1, score, 0, 'now'))
    assert rank(store)[0]['work_id'] == preferred
    store.feedback(preferred, 0)
    assert preferred not in [r['work_id'] for r in rank(store)]
    assert store.rows('SELECT state FROM actor_preference')[0]['state'] == 'like'


def test_multi_actor_conflict_review_not_cancellation(store):
    wid, liked, _ = work(store, 1)
    with store.transaction():
        other = store.add_actor(wid, 'fixture', 'b', 'b')
    store.preference(liked, 'like')
    store.preference(other, 'dislike')
    assert rank(store) == []
    assert rank(store, 'review')[0]['work_id'] == wid
    assert rank(store, conflict='actor_first')[0]['queue'] == 'actor_first'


def test_identity_and_actors_never_merge_on_name(store):
    wid, aid, _ = work(store, 1, 'Alice')
    with store.transaction():
        assert store.work('second', 'id', 'other title', 'syn001') == wid
        assert store.work('second', 'cut', 'same title', 'SYN-001', edition='directors-cut') != wid
        other = store.add_actor(wid, 'other-site', 'Alice', 'Alice')
    assert other != aid
    assert normalize_code('SYN-001 4K') is None
    assert match_work(store, {'Name': 'SYN-001'}) is None  # different editions ambiguous


def test_semantic_dedup_missing_and_correction(store):
    wid, _, tag = work(store, 1)
    before = features(store, wid)
    with store.transaction():
        other = store.add_tag(wid, 'second', 'theme', 'same', 'g')
    assert other != tag  # same display name is not proof of semantic identity
    store.map_tag('second', 'theme', 'same', tag)
    assert features(store, wid) == before
    store.correct_tag(wid, tag, False)
    assert 'tag:genre:' + tag not in features(store, wid)
    assert store.rows('SELECT * FROM work_tag')  # raw evidence retained
    assert not any('unknown' in k for k in features(store, wid))


class Client:
    base = 'http://emby.invalid'
    user_id = 'user'
    library_id = 'library'

    def __init__(self, items):
        self.items = items
        self.fail_at = None
        self.offline = False

    def get(self, path):
        if self.offline:
            raise OSError('private-secret-must-not-escape')
        return {'Id': 'server'}

    def page(self, offset, size):
        if self.fail_at is not None and offset >= self.fail_at:
            raise OSError('secret-path')
        return {'Items': self.items[offset:offset+size], 'TotalRecordCount': len(self.items)}


def media(item_id, code):
    return {'Id': item_id, 'Name': code, 'Path': '/private/' + item_id,
            'MediaSources': [{'Path': '/private/' + item_id, 'SupportsDirectPlay': True}]}


def test_inventory_duplicates_weak_signal_and_dual_entries(store):
    first, _, _ = work(store, 1, 'a', 'g')
    second, _, _ = work(store, 2, 'b', 'different')
    candidate, _, _ = work(store, 3, 'a', 'g')
    client = Client([media('1', 'SYN-001'), media('copy', 'SYN-001'), media('2', 'SYN-002')])
    sync(store, client, page_size=1, pause=0)
    prototype = collection_prototype(store)
    assert auxiliary_score(features(store, candidate), prototype) > 0
    client.items.pop(1)
    sync(store, client, pause=0)
    assert collection_prototype(store) == prototype
    assert {r['work_id'] for r in rank(store)} == {candidate}
    assert {r['work_id'] for r in rank(store, 'local')} == {first, second}
    store.feedback(first, 0)
    assert first not in {r['work_id'] for r in rank(store, 'local')}
    assert collection_prototype(store) != prototype
    assert 'api_key' not in emby_link(client.base, 'server', '1')
    assert 'id=1' in emby_link(client.base, 'server', '1')


def test_emby_failure_keeps_snapshot_resumes_and_offline_stales(store):
    first, _, _ = work(store, 1)
    client = Client([media('1', 'SYN-001')])
    sync(store, client, pause=0)
    client.items.append(media('2', 'SYN-002'))
    client.fail_at = 1
    with pytest.raises(ValueError, match='previous snapshot retained'):
        sync(store, client, page_size=1, pause=0)
    assert store.rows('SELECT count(*) AS n FROM media_copy')[0]['n'] == 1
    assert rank(store, 'local') == []
    assert not rank(store)  # stale owned work still excluded from discovery
    client.fail_at = None
    sync(store, client, page_size=1, pause=0)
    assert store.rows('SELECT count(*) AS n FROM media_copy')[0]['n'] == 2
    client.offline = True
    with pytest.raises(ValueError) as caught:
        sync(store, client, pause=0)
    assert 'secret' not in str(caught.value)
    assert store.rows('SELECT stale FROM library_inventory')[0]['stale'] == 1


def test_migration_backup_latest_feedback_and_idempotence(tmp_path):
    store = Store(tmp_path / 'legacy.db')
    store.conn.executescript('''
      CREATE TABLE item(id INTEGER PRIMARY KEY,fanhao TEXT,title TEXT,url TEXT);
      CREATE TABLE tag(id INTEGER PRIMARY KEY,type TEXT,value TEXT,url TEXT);
      CREATE TABLE item_tag(item_id TEXT,tag_id INTEGER);
      CREATE TABLE item_rate(id INTEGER PRIMARY KEY,item_id TEXT,rate_type INTEGER,rate_value INTEGER,rete_time TEXT);
      INSERT INTO item VALUES(1,'SYN-001','sample','/a'),(2,'SYN001','sample copy','/b');
      INSERT INTO item_rate VALUES(1,'SYN-001',1,1,'2025-01-01'),(2,'SYN001',1,0,'2025-02-01');
    ''')
    result = store.migrate(tmp_path / 'backup.db')
    assert len(result['backup_sha256']) == 64
    assert store.rows('SELECT value FROM explicit_work_feedback') == [{'value': 0}]
    assert store.rows('SELECT count(*) AS n FROM item')[0]['n'] == 2
    store.migrate(tmp_path / 'backup2.db')
    assert store.rows('SELECT count(*) AS n FROM work_identity')[0]['n'] == 1
    with store.transaction():
        store.conn.execute("UPDATE item_rate SET rate_value=1,rete_time='2026-01-01' WHERE id=2")
    assert store.rows('SELECT value FROM explicit_work_feedback') == [{'value': 1}]
    restored = sqlite3.connect(tmp_path / 'backup.db')
    assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert restored.execute('SELECT count(*) FROM item').fetchone()[0] == 2
    restored.close()
    store.close()


def test_failed_migration_rolls_back(tmp_path):
    store = Store(tmp_path / 'broken.db')
    store.conn.execute('CREATE TABLE item(unexpected TEXT)')
    store.conn.execute("INSERT INTO item VALUES ('retained')")
    store.conn.commit()
    with pytest.raises(KeyError):
        store.migrate(tmp_path / 'backup.db')
    assert not store.enabled()
    assert store.rows('SELECT * FROM item')[0]['unexpected'] == 'retained'
    store.close()
