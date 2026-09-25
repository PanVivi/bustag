import hashlib
import sqlite3
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import threading

import pytest

from bustag.recommender.store import Store
from conftest import work


@pytest.mark.parametrize('fixture', ['data/bus.db', 'app/bus.db'])
def test_repository_database_migration_on_disposable_copy(tmp_path, fixture):
    path = Path(__file__).parents[2] / fixture
    if not path.exists():
        pytest.skip('Historical repository fixture not included in acceptance image')
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    source = sqlite3.connect('file:' + path.as_posix() + '?mode=ro', uri=True)
    store = Store(tmp_path / 'copy.db')
    source.backup(store.conn)
    source.close()
    tables = ['item', 'tag', 'item_tag', 'item_rate', 'local_item']
    available = {row['name'] for row in store.rows("SELECT name FROM sqlite_master WHERE type='table'")}
    tables = [table for table in tables if table in available]
    snapshot = {table: store.rows('SELECT * FROM ' + table) for table in tables}
    store.migrate(tmp_path / 'before-v2.db')
    assert store.enabled()
    for table in tables:
        assert store.rows('SELECT * FROM ' + table) == snapshot[table]
    assert store.rows('SELECT count(*) AS n FROM source_item')[0]['n'] == len(snapshot['item'])
    if fixture == 'data/bus.db':
        assert store.rows('SELECT count(*) AS n FROM work_actor')[0]['n'] > 0
    store.close()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == before


def test_integer_item_foreign_key_feedback_migration_and_trigger(tmp_path):
    store = Store(tmp_path / 'old.db')
    store.conn.executescript('''
      CREATE TABLE item(id INTEGER PRIMARY KEY,fanhao TEXT,title TEXT,url TEXT);
      CREATE TABLE tag(id INTEGER PRIMARY KEY,type TEXT,value TEXT,url TEXT);
      CREATE TABLE item_tag(item_id INTEGER REFERENCES item(id),tag_id INTEGER);
      CREATE TABLE item_rate(id INTEGER PRIMARY KEY,item_id INTEGER REFERENCES item(id),rate_type INTEGER,rate_value INTEGER,rete_time TEXT);
      INSERT INTO item VALUES (10,'SYN-001','sample','/a');
      INSERT INTO tag VALUES (20,'star','actor','/star/20');
      INSERT INTO item_tag VALUES (10,20);
      INSERT INTO item_rate VALUES (30,10,1,0,'2025-01-01');
    ''')
    store.migrate(tmp_path / 'backup.db')
    assert store.rows('SELECT value FROM explicit_work_feedback') == [{'value': 0}]
    assert len(store.rows('SELECT * FROM work_actor')) == 1
    with store.transaction():
        store.conn.execute('UPDATE item_rate SET rate_value=1 WHERE id=30')
    assert store.rows('SELECT value FROM explicit_work_feedback') == [{'value': 1}]
    store.close()


def test_concurrent_tag_mappings_increment_every_revision(store):
    wid, _, first = work(store, 1)
    with store.transaction():
        second = store.add_tag(wid, 'other', 'genre', 'second', 'second')
    barrier = threading.Barrier(2)

    def update(index):
        own = Store(store.path)
        try:
            barrier.wait()
            for _ in range(5):
                own.map_tag('other', 'genre', 'second', first if index else second)
        finally:
            own.close()
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(update, (0, 1)))
    assert int(store.meta('mapping_version')) == 11
    assert len(store.rows("SELECT * FROM feedback_event WHERE entity='mapping'")) == 10
