"""Additive SQLite storage. Legacy tables remain available for rollback."""
import datetime
import hashlib
import json
import os
import re
import sqlite3
import unicodedata
import uuid
from contextlib import contextmanager


def now():
    return datetime.datetime.utcnow().isoformat(timespec='microseconds')


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def normalize_code(value):
    value = unicodedata.normalize('NFKC', str(value)).strip().upper()
    match = re.fullmatch(r'([A-Z]{2,12})[-_ ]?(\d{2,8})', value)
    return '{}-{}'.format(*match.groups()) if match else None


SCHEMA = '''
CREATE TABLE IF NOT EXISTS v2_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS work_identity(
 work_id TEXT PRIMARY KEY, code TEXT, edition TEXT NOT NULL DEFAULT '', title TEXT NOT NULL,
 created_at TEXT NOT NULL, UNIQUE(code,edition));
CREATE TABLE IF NOT EXISTS source_item(
 source TEXT NOT NULL, source_id TEXT NOT NULL, work_id TEXT REFERENCES work_identity,
 url TEXT, raw_json TEXT NOT NULL, observed_at TEXT NOT NULL, status TEXT NOT NULL,
 PRIMARY KEY(source,source_id));
CREATE TABLE IF NOT EXISTS source_observation(
 id INTEGER PRIMARY KEY, source TEXT NOT NULL, source_id TEXT NOT NULL,
 raw_json TEXT NOT NULL, observed_at TEXT NOT NULL, UNIQUE(source,source_id,raw_json));
CREATE TABLE IF NOT EXISTS actor(actor_id TEXT PRIMARY KEY, name TEXT NOT NULL, ambiguous INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS actor_alias(
 source TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL,
 actor_id TEXT NOT NULL REFERENCES actor, PRIMARY KEY(source,source_id));
CREATE TABLE IF NOT EXISTS work_actor(
 work_id TEXT REFERENCES work_identity, actor_id TEXT REFERENCES actor, source TEXT NOT NULL,
 PRIMARY KEY(work_id,actor_id,source));
CREATE TABLE IF NOT EXISTS actor_preference(
 actor_id TEXT PRIMARY KEY REFERENCES actor, state TEXT NOT NULL CHECK(state IN ('like','dislike','pending')),
 updated_at TEXT NOT NULL, source TEXT NOT NULL CHECK(source='user'));
CREATE TABLE IF NOT EXISTS canonical_tag(
 tag_id TEXT PRIMARY KEY, category TEXT NOT NULL, name TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS source_tag(
 source TEXT NOT NULL, category TEXT NOT NULL, source_id TEXT NOT NULL, name TEXT NOT NULL,
 tag_id TEXT NOT NULL REFERENCES canonical_tag, verified INTEGER NOT NULL DEFAULT 0,
 mapping_version INTEGER NOT NULL, PRIMARY KEY(source,category,source_id));
CREATE TABLE IF NOT EXISTS work_tag(
 work_id TEXT REFERENCES work_identity, source TEXT NOT NULL, category TEXT NOT NULL, source_id TEXT NOT NULL,
 PRIMARY KEY(work_id,source,category,source_id));
CREATE TABLE IF NOT EXISTS tag_override(
 work_id TEXT REFERENCES work_identity, tag_id TEXT REFERENCES canonical_tag,
 enabled INTEGER NOT NULL CHECK(enabled IN (0,1)), updated_at TEXT NOT NULL,
 PRIMARY KEY(work_id,tag_id));
CREATE TABLE IF NOT EXISTS explicit_work_feedback(
 work_id TEXT PRIMARY KEY REFERENCES work_identity, value INTEGER NOT NULL CHECK(value IN (0,1)),
 confirmed_at TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS feedback_event(
 id INTEGER PRIMARY KEY, entity TEXT NOT NULL, entity_id TEXT NOT NULL,
 old_value TEXT, new_value TEXT NOT NULL, created_at TEXT NOT NULL, source TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS v2_recommendation_score(
 work_id TEXT PRIMARY KEY REFERENCES work_identity, model_version TEXT NOT NULL,
 feature_version TEXT NOT NULL, mapping_version INTEGER NOT NULL,
 score REAL NOT NULL, auxiliary REAL NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS library_inventory(
 server TEXT PRIMARY KEY, generation TEXT, synced_at TEXT, stale INTEGER NOT NULL DEFAULT 1,
 pending_generation TEXT, cursor INTEGER NOT NULL DEFAULT 0, error TEXT);
CREATE TABLE IF NOT EXISTS media_copy(
 server TEXT NOT NULL, item_id TEXT NOT NULL, work_id TEXT REFERENCES work_identity,
 path TEXT, playable INTEGER NOT NULL, confidence REAL NOT NULL,
 generation TEXT NOT NULL, observed_at TEXT NOT NULL, raw_json TEXT NOT NULL,
 PRIMARY KEY(server,item_id));
CREATE TABLE IF NOT EXISTS media_stage(
 server TEXT NOT NULL, item_id TEXT NOT NULL, payload TEXT NOT NULL,
 PRIMARY KEY(server,item_id));
CREATE TABLE IF NOT EXISTS model_manifest(
 version TEXT PRIMARY KEY, manifest_json TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS media_work ON media_copy(work_id);
CREATE INDEX IF NOT EXISTS source_work ON source_item(work_id);
'''


class Store:
    def __init__(self, path):
        self.path = os.fspath(path)
        self.conn = sqlite3.connect(self.path, timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys=ON')
        self.conn.execute('PRAGMA busy_timeout=30000')

    def close(self):
        self.conn.close()

    def rows(self, sql, args=()):
        return [dict(r) for r in self.conn.execute(sql, args)]

    @contextmanager
    def transaction(self):
        # Callers perform short mutations; no network or fitting within transactions.
        with self.conn:
            yield

    def enabled(self):
        try:
            return self.meta('schema_version') == '1'
        except sqlite3.OperationalError:
            return False

    def meta(self, key, default=None):
        row = self.conn.execute('SELECT value FROM v2_meta WHERE key=?', (key,)).fetchone()
        return row[0] if row else default

    def set_meta(self, key, value):
        self.conn.execute('INSERT OR REPLACE INTO v2_meta VALUES (?,?)', (key, str(value)))

    def backup(self, destination):
        if os.path.exists(destination):
            raise ValueError('Backup destination must not already exist')
        target = sqlite3.connect(destination)
        try:
            self.conn.backup(target)
            if target.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise ValueError('Backup integrity check failed')
        finally:
            target.close()
        os.chmod(destination, 0o600)
        with open(destination, 'rb') as stream:
            return hashlib.sha256(stream.read()).hexdigest()

    def migrate(self, backup_path):
        checksum = self.backup(backup_path)
        self.conn.executescript('BEGIN IMMEDIATE;\n' + SCHEMA)
        try:
            self.set_meta('schema_version', 1)
            if self.meta('mapping_version') is None:
                self.set_meta('mapping_version', 1)
            self._import_legacy()
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        return {'backup_sha256': checksum, 'statistics': self.statistics()}

    def work(self, source, source_id, title, code=None, edition='', raw=None, url=None):
        previous = self.rows('SELECT work_id FROM source_item WHERE source=? AND source_id=?', (source, str(source_id)))
        normalized = normalize_code(code) if code else None
        if previous:
            work_id = previous[0]['work_id']
        else:
            match = self.rows('SELECT work_id FROM work_identity WHERE code=? AND edition=?', (normalized, edition)) if normalized else []
            work_id = match[0]['work_id'] if match else uuid.uuid4().hex
            self.conn.execute('INSERT OR IGNORE INTO work_identity VALUES (?,?,?,?,?)',
                              (work_id, normalized, edition, title, now()))
        payload = encode(raw or {})
        self.conn.execute('INSERT OR IGNORE INTO source_observation(source,source_id,raw_json,observed_at) VALUES (?,?,?,?)',
                          (source, str(source_id), payload, now()))
        self.conn.execute('INSERT OR REPLACE INTO source_item VALUES (?,?,?,?,?,?,?)',
                          (source, str(source_id), work_id, url, payload, now(), 'matched' if normalized else 'pending'))
        return work_id

    def add_actor(self, work_id, source, source_id, name):
        alias = self.rows('SELECT actor_id FROM actor_alias WHERE source=? AND source_id=?', (source, source_id))
        actor_id = alias[0]['actor_id'] if alias else uuid.uuid4().hex
        self.conn.execute('INSERT OR IGNORE INTO actor VALUES (?,?,?)', (actor_id, name, int(not source_id)))
        self.conn.execute('INSERT OR IGNORE INTO actor_alias VALUES (?,?,?,?)', (source, source_id, name, actor_id))
        self.conn.execute('INSERT OR IGNORE INTO work_actor VALUES (?,?,?)', (work_id, actor_id, source))
        return actor_id

    def add_tag(self, work_id, source, category, source_id, name):
        rows = self.rows('SELECT tag_id FROM source_tag WHERE source=? AND category=? AND source_id=?', (source, category, source_id))
        tag_id = rows[0]['tag_id'] if rows else uuid.uuid4().hex
        self.conn.execute('INSERT OR IGNORE INTO canonical_tag VALUES (?,?,?)', (tag_id, category, name))
        self.conn.execute('INSERT OR IGNORE INTO source_tag VALUES (?,?,?,?,?,?,?)',
                          (source, category, source_id, name, tag_id, 0, int(self.meta('mapping_version'))))
        self.conn.execute('INSERT OR IGNORE INTO work_tag VALUES (?,?,?,?)', (work_id, source, category, source_id))
        return tag_id

    def event(self, entity, entity_id, old, new, source='user', at=None):
        self.conn.execute('INSERT INTO feedback_event(entity,entity_id,old_value,new_value,created_at,source) VALUES (?,?,?,?,?,?)',
                          (entity, entity_id, encode(old), encode(new), at or now(), source))

    def feedback(self, work_id, value, source='user', at=None):
        if type(value) is not int or value not in (0, 1):
            raise ValueError('Feedback must be 0 or 1')
        with self.transaction():
            old = self.rows('SELECT value FROM explicit_work_feedback WHERE work_id=?', (work_id,))
            self.event('work', work_id, old[0]['value'] if old else None, value, source, at)
            self.conn.execute('INSERT OR REPLACE INTO explicit_work_feedback VALUES (?,?,?,?)', (work_id, value, at or now(), source))

    def preference(self, actor_id, state):
        if state not in ('like', 'dislike', 'pending'):
            raise ValueError('Unknown actor state')
        with self.transaction():
            actor_id = self.canonical_actor(actor_id)
            old = self.rows('SELECT state FROM actor_preference WHERE actor_id=?', (actor_id,))
            self.event('actor', actor_id, old[0]['state'] if old else 'pending', state)
            self.conn.execute('INSERT OR REPLACE INTO actor_preference VALUES (?,?,?,?)', (actor_id, state, now(), 'user'))

    def canonical_actor(self, actor_id):
        seen = set()
        while self.meta('actor_redirect:' + actor_id):
            if actor_id in seen:
                raise ValueError('Actor redirect cycle')
            seen.add(actor_id)
            actor_id = self.meta('actor_redirect:' + actor_id)
        if not self.rows('SELECT 1 FROM actor WHERE actor_id=?', (actor_id,)):
            raise ValueError('Unknown actor')
        return actor_id

    def correct_tag(self, work_id, tag_id, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled must be boolean')
        with self.transaction():
            self.event('tag', work_id, None, {'tag_id': tag_id, 'enabled': enabled})
            self.conn.execute('INSERT OR REPLACE INTO tag_override VALUES (?,?,?,?)', (work_id, tag_id, int(enabled), now()))
            self.set_meta('mapping_version', int(self.meta('mapping_version')) + 1)

    def map_tag(self, source, category, source_id, canonical_id):
        with self.transaction():
            old = self.rows('SELECT tag_id FROM source_tag WHERE source=? AND category=? AND source_id=?', (source, category, source_id))
            if not old:
                raise ValueError('Unknown source tag')
            version = int(self.meta('mapping_version')) + 1
            self.conn.execute('UPDATE source_tag SET tag_id=?,verified=1,mapping_version=? WHERE source=? AND category=? AND source_id=?',
                              (canonical_id, version, source, category, source_id))
            self.event('mapping', encode([source, category, source_id]), old[0]['tag_id'], canonical_id)
            self.set_meta('mapping_version', version)

    def resolve_media(self, server, item_id, work_id):
        with self.transaction():
            old = self.rows('SELECT work_id FROM media_copy WHERE server=? AND item_id=?', (server, item_id))
            if not old:
                raise ValueError('Unknown media copy')
            self.event('media_match', encode([server, item_id]), old[0]['work_id'], work_id)
            self.conn.execute('UPDATE media_copy SET work_id=?,confidence=1 WHERE server=? AND item_id=?', (work_id, server, item_id))
            self.set_meta('media_match:' + encode([server, item_id]), work_id)

    def merge_actor(self, source_actor, target_actor):
        source_actor = self.canonical_actor(source_actor)
        target_actor = self.canonical_actor(target_actor)
        if source_actor == target_actor:
            return
        with self.transaction():
            states = self.rows('SELECT actor_id,state FROM actor_preference WHERE actor_id IN (?,?)', (source_actor, target_actor))
            if len({r['state'] for r in states if r['state'] != 'pending'}) > 1:
                raise ValueError('Resolve conflicting manual actor states first')
            if not self.rows('SELECT 1 FROM actor WHERE actor_id=?', (target_actor,)):
                raise ValueError('Unknown target actor')
            self.conn.execute('INSERT OR IGNORE INTO work_actor SELECT work_id,?,source FROM work_actor WHERE actor_id=?', (target_actor, source_actor))
            self.conn.execute('DELETE FROM work_actor WHERE actor_id=?', (source_actor,))
            self.conn.execute('UPDATE actor_alias SET actor_id=? WHERE actor_id=?', (target_actor, source_actor))
            preferred = next((r['state'] for r in states if r['state'] != 'pending'), 'pending')
            self.conn.execute('INSERT OR REPLACE INTO actor_preference VALUES (?,?,?,?)', (target_actor, preferred, now(), 'user'))
            self.event('actor_merge', source_actor, source_actor, target_actor)
            self.set_meta('actor_redirect:' + source_actor, target_actor)
            self.set_meta('mapping_version', int(self.meta('mapping_version')) + 1)

    def _import_legacy(self):
        tables = {r['name'] for r in self.rows("SELECT name FROM sqlite_master WHERE type='table'")}
        if 'item' not in tables:
            return
        for item in self.rows('SELECT * FROM item'):
            work_id = self.work('javbus', item['fanhao'], item['title'], item['fanhao'], raw=item, url=item['url'])
            for tag in self.rows('SELECT t.* FROM tag t JOIN item_tag it ON t.id=it.tag_id WHERE it.item_id=?', (item['fanhao'],)):
                if tag['type'] == 'star':
                    # Missing actor IDs remain separate; never resolve by display name.
                    self.add_actor(work_id, 'javbus', tag['url'] or 'legacy-tag:{}'.format(tag['id']), tag['value'])
                else:
                    self.add_tag(work_id, 'javbus', tag['type'], tag['url'] or 'legacy-tag:{}'.format(tag['id']), tag['value'])
        # Most recent independent work judgement wins; retain all original rows.
        for row in self.rows('SELECT r.*,s.work_id FROM item_rate r JOIN source_item s ON s.source=\'javbus\' AND s.source_id=r.item_id WHERE rate_type=1 ORDER BY rete_time DESC,r.id DESC'):
            if not self.rows('SELECT 1 FROM explicit_work_feedback WHERE work_id=?', (row['work_id'],)):
                self.conn.execute('INSERT INTO explicit_work_feedback VALUES (?,?,?,?)', (row['work_id'], row['rate_value'], row['rete_time'], 'legacy_user'))
                self.event('work', row['work_id'], None, row['rate_value'], 'legacy_user', row['rete_time'])
        # Capture future legacy UI/import judgements in the same SQLite transaction.
        # SYSTEM_RATE never enters the explicit store, even after retraining.
        for operation in ('INSERT', 'UPDATE'):
            self.conn.execute('''CREATE TRIGGER IF NOT EXISTS v2_feedback_''' + operation.lower() + '''
              AFTER ''' + operation + ''' ON item_rate WHEN NEW.rate_type=1 BEGIN
              INSERT INTO feedback_event(entity,entity_id,old_value,new_value,created_at,source)
                SELECT 'work',s.work_id,NULL,CAST(NEW.rate_value AS TEXT),NEW.rete_time,'legacy_user'
                FROM source_item s WHERE s.source='javbus' AND s.source_id=NEW.item_id;
              INSERT OR REPLACE INTO explicit_work_feedback(work_id,value,confirmed_at,source)
                SELECT s.work_id,NEW.rate_value,NEW.rete_time,'legacy_user'
                FROM source_item s WHERE s.source='javbus' AND s.source_id=NEW.item_id;
              END''')

    def import_legacy(self):
        with self.transaction():
            self._import_legacy()

    def statistics(self):
        result = {table: self.conn.execute('SELECT count(*) FROM ' + table).fetchone()[0]
                  for table in ('work_identity', 'actor', 'source_tag', 'media_copy')}
        result['explicit'] = self.rows('SELECT value,count(*) AS count FROM explicit_work_feedback GROUP BY value')
        result['actor_coverage'] = self.conn.execute('SELECT count(DISTINCT work_id) FROM work_actor').fetchone()[0]
        result['matched_copies'] = self.conn.execute('SELECT count(*) FROM media_copy WHERE work_id IS NOT NULL').fetchone()[0]
        result['unverified_tags'] = self.conn.execute('SELECT count(*) FROM source_tag WHERE verified=0').fetchone()[0]
        return result
