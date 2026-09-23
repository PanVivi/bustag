import numpy as np

from bustag.recommender.model import rescore_work_ids
from bustag.recommender.ranking import FEATURE_VERSION, legacy_card_details
from bustag.recommender.store import Store


def create_legacy_tables(store):
    store.conn.executescript('''
      CREATE TABLE item(id INTEGER PRIMARY KEY, fanhao TEXT UNIQUE, title TEXT, url TEXT);
      CREATE TABLE tag(id INTEGER PRIMARY KEY, type TEXT, value TEXT, url TEXT);
      CREATE TABLE item_tag(item_id INTEGER REFERENCES item(id), tag_id INTEGER REFERENCES tag(id));
      CREATE TABLE item_rate(id INTEGER PRIMARY KEY, item_id INTEGER REFERENCES item(id),
        rate_type INTEGER, rate_value INTEGER, rete_time TEXT);
      INSERT INTO item VALUES (1,'SYN-001','Existing','/SYN-001');
      INSERT INTO tag VALUES (1,'star','Actor A','/star/a');
      INSERT INTO item_tag VALUES (1,1);
    ''')


def test_sync_legacy_items_backfills_new_cards_idempotently_without_overwriting_feedback(tmp_path):
    path = tmp_path / 'legacy.db'
    store = Store(path)
    create_legacy_tables(store)
    store.migrate(tmp_path / 'before.db')
    existing = store.rows("SELECT work_id FROM source_item WHERE source='javbus' AND source_id='SYN-001'")[0]['work_id']
    store.feedback(existing, 1)

    # Simulate the legacy crawler adding a card and its actor/genre tags after V2 migration.
    store.conn.executescript('''
      INSERT INTO item VALUES (2,'SYN-002','New item','/SYN-002');
      INSERT INTO item VALUES (3,'SYN-003','Another new item','/SYN-003');
      INSERT INTO tag VALUES (2,'star','Actor B','/star/b');
      INSERT INTO tag VALUES (3,'genre','Drama','/genre/drama');
      INSERT INTO item_tag VALUES (2,2);
      INSERT INTO item_tag VALUES (2,3);
      INSERT INTO item_rate VALUES (1,2,1,0,'2026-09-23T10:00:00');
    ''')
    assert store.sync_missing_legacy_items(batch_size=1) == 2
    assert store.sync_legacy_items(['SYN-002']) == 0

    work_id = store.rows("SELECT work_id FROM source_item WHERE source='javbus' AND source_id='SYN-002'")[0]['work_id']
    assert store.rows('SELECT value FROM explicit_work_feedback WHERE work_id=?', (existing,))[0]['value'] == 1
    assert store.rows('SELECT value,source FROM explicit_work_feedback WHERE work_id=?', (work_id,)) == [
        {'value': 0, 'source': 'legacy_user'}]
    assert store.rows('SELECT count(*) AS n FROM feedback_event')[0]['n'] == 2
    details = legacy_card_details(store, ['SYN-002'])['SYN-002']
    assert len(details['actors']) == 1
    assert details['actors'][0]['name'] == 'Actor B'
    assert details['actors'][0]['state'] == 'pending'
    assert len(details['tags']) == 1 and details['tags'][0]['name'] == 'Drama'
    assert store.rows('SELECT count(*) AS n FROM actor_preference')[0]['n'] == 0

    version = 'b' * 32
    with store.transaction():
        store.set_meta('active_model', version)
    mapping_version = int(store.meta('mapping_version'))

    class Encoder:
        def transform(self, docs):
            return docs

    class Model:
        def predict_proba(self, docs):
            return np.asarray([[0.1, 0.9] for _ in docs])

    bundle = {'manifest': {'version': version, 'mapping_version': mapping_version},
              'encoder': Encoder(), 'model': Model()}
    assert rescore_work_ids(store, bundle, [work_id]) == 1
    rescored = legacy_card_details(store, ['SYN-002'])['SYN-002']
    assert rescored['model_current'] is True and rescored['match_score'] == 0.9
    assert rescored['auxiliary'] == 0.0
    store.close()


def test_sync_legacy_items_supports_fanhao_foreign_keys(tmp_path):
    store = Store(tmp_path / 'fanhao.db')
    store.conn.executescript('''
      CREATE TABLE item(id INTEGER PRIMARY KEY, fanhao TEXT UNIQUE, title TEXT, url TEXT);
      CREATE TABLE tag(id INTEGER PRIMARY KEY, type TEXT, value TEXT, url TEXT);
      CREATE TABLE item_tag(item_fanhao TEXT, tag_id INTEGER,
        FOREIGN KEY(item_fanhao) REFERENCES item(fanhao));
      CREATE TABLE item_rate(id INTEGER PRIMARY KEY, item_fanhao TEXT, rate_type INTEGER,
        rate_value INTEGER, rete_time TEXT,
        FOREIGN KEY(item_fanhao) REFERENCES item(fanhao));
      INSERT INTO item VALUES (1,'SYN-010','Fanhao keyed','/SYN-010');
      INSERT INTO tag VALUES (1,'genre','Drama','/genre/drama');
      INSERT INTO item_tag VALUES ('SYN-010',1);
      INSERT INTO item_rate VALUES (1,'SYN-010',1,1,'2026-09-23T11:00:00');
    ''')
    store.migrate(tmp_path / 'fanhao-backup.db')
    assert store.rows("SELECT value FROM explicit_work_feedback") == [{'value': 1}]
    code = store.rows("SELECT source_id FROM source_item WHERE source='javbus'")[0]['source_id']
    assert store.sync_legacy_items([code]) == 0
    store.close()
