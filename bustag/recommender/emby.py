"""Opt-in read-only Emby snapshot ingestion. No media mutation endpoints."""
import json
import datetime
import os
import time
import uuid
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler

from .store import encode, normalize_code, now


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward an API key to a redirect host.
        return None


class Emby:
    def __init__(self, base, token, user_id, library_id):
        parsed = urlsplit(base)
        if parsed.scheme not in ('http', 'https') or not parsed.netloc or parsed.username or parsed.query or parsed.fragment:
            raise ValueError('Invalid Emby base URL')
        if not token or not user_id or not library_id:
            raise ValueError('Emby requires an explicit user and library scope')
        self.base = base.rstrip('/')
        self.token = token
        self.user_id = user_id
        self.library_id = library_id

    @classmethod
    def from_environment(cls):
        if os.environ.get('BUSTAG_EMBY_READ_ONLY_AUTHORIZED') != 'yes':
            raise ValueError('Emby read-only authorization is not configured')
        return cls(*(os.environ.get(key, '') for key in ('BUSTAG_EMBY_URL', 'BUSTAG_EMBY_TOKEN', 'BUSTAG_EMBY_USER_ID', 'BUSTAG_EMBY_LIBRARY_ID')))

    def get(self, path, params=None):
        req = Request(self.base + path + ('?' + urlencode(params) if params else ''),
                      headers={'X-Emby-Token': self.token, 'Accept': 'application/json'})
        with build_opener(NoRedirect()).open(req, timeout=30) as response:
            return json.load(response)

    def page(self, offset, size, fields='Path,People,Genres,Tags,ProviderIds,MediaSources,OriginalTitle'):
        from urllib.parse import quote
        return self.get('/Users/' + quote(self.user_id, safe='') + '/Items', {
            'ParentId': self.library_id, 'Recursive': 'true', 'IncludeItemTypes': 'Movie',
            'Fields': fields, 'EnableImages': 'false',
            'EnableUserData': 'true',
            'StartIndex': offset, 'Limit': size, 'SortBy': 'SortName', 'SortOrder': 'Ascending'})

    def incremental_page(self, offset, size, previous):
        """Reconcile membership each run; transfer full metadata only when changed.

        Etag is optional in Emby BaseItemDto. Servers omitting it safely fall back
        to full pages, rather than guessing unchanged metadata from a timestamp.
        """
        from urllib.parse import quote
        page = self.page(offset, size, fields='')
        if any(not item.get('Etag') for item in page['Items']):
            return self.page(offset, size)
        items = []
        for brief in page['Items']:
            old = previous.get(str(brief['Id']))
            if old and old.get('Etag') == brief['Etag']:
                item = dict(old)
                # User state and current availability may change independently of
                # metadata Etag; the current user-scoped listing wins.
                for key in ('UserData', 'IsOffline', 'IsVirtualItem'):
                    if key in brief:
                        item[key] = brief[key]
            else:
                item = self.get('/Users/' + quote(self.user_id, safe='') + '/Items/' + quote(str(brief['Id']), safe=''))
                if str(item.get('Id')) != str(brief['Id']):
                    raise ValueError('Emby detail identity mismatch')
            items.append(item)
        return dict(page, Items=items)


def match_work(store, item):
    # Only known source IDs or exact catalogue codes. Filename/title resemblance
    # never silently merges cuts/editions. A user may later resolve pending copies.
    providers = item.get('ProviderIds') or {}
    candidates = set()
    for source in ('javbus', 'javdb'):
        source_id = next((v for k, v in providers.items() if k.lower() == source), None)
        if source_id:
            candidates.update(r['work_id'] for r in store.rows('SELECT work_id FROM source_item WHERE source=? AND source_id=?', (source, source_id)))
    code = normalize_code(item.get('OriginalTitle') or item.get('Name') or '')
    if code:
        candidates.update(r['work_id'] for r in store.rows('SELECT work_id FROM work_identity WHERE code=?', (code,)))
    return next(iter(candidates)) if len(candidates) == 1 else None


def sync(store, client, page_size=100, pause=.1):
    owner = uuid.uuid4().hex
    with store.transaction():
        store.conn.execute('BEGIN IMMEDIATE')
        if store.meta('emby_sync_until', '') > now():
            raise ValueError('Emby synchronization is already running')
        store.set_meta('emby_sync_owner', owner)
        store.set_meta('emby_sync_until', (datetime.datetime.utcnow() + datetime.timedelta(minutes=2)).isoformat())
    try:
        return _sync(store, client, page_size, pause, owner)
    finally:
        with store.transaction():
            store.conn.execute('BEGIN IMMEDIATE')
            if store.meta('emby_sync_owner') == owner:
                store.set_meta('emby_sync_until', '')


def _sync(store, client, page_size, pause, owner):
    if not 1 <= page_size <= 1000:
        raise ValueError('Invalid page size')
    try:
        public = client.get('/System/Info/Public')
        if not public.get('Id'):
            raise ValueError('Missing server ID')
        server = str(public['Id'])
    except Exception:
        with store.transaction():
            # Only this configured connection's previous inventories become stale.
            for old in store.rows('SELECT server FROM library_inventory'):
                if store.meta('emby_url:' + old['server']) == client.base:
                    store.conn.execute("UPDATE library_inventory SET stale=1,error='sync_failed' WHERE server=?", (old['server'],))
        raise ValueError('Emby sync failed; previous snapshot retained') from None
    # A scope change cannot resume a cursor from a different library/user/server URL.
    scope = encode([client.base, client.user_id, client.library_id])
    with store.transaction():
        store.conn.execute('INSERT OR IGNORE INTO library_inventory(server) VALUES (?)', (server,))
        state = store.rows('SELECT * FROM library_inventory WHERE server=?', (server,))[0]
        reuse = bool(state['generation']) and store.meta('emby_scope:' + server) == scope
        generation = state['pending_generation']
        if not generation or store.meta('emby_scope:' + server) != scope:
            generation = uuid.uuid4().hex
            store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
            store.conn.execute('UPDATE library_inventory SET pending_generation=?,cursor=0 WHERE server=?', (generation, server))
            store.set_meta('emby_scope:' + server, scope)
        store.set_meta('emby_url:' + server, client.base)
    previous = {r['item_id']: json.loads(r['raw_json']) for r in store.rows(
        'SELECT item_id,raw_json FROM media_copy WHERE server=? AND generation=?', (server, state['generation']))} if reuse else {}
    try:
        while True:
            with store.transaction():
                store.conn.execute('BEGIN IMMEDIATE')
                if store.meta('emby_sync_owner') != owner:
                    raise RuntimeError('Emby synchronization superseded')
                store.set_meta('emby_sync_until', (datetime.datetime.utcnow() + datetime.timedelta(minutes=2)).isoformat())
            cursor = store.rows('SELECT cursor FROM library_inventory WHERE server=?', (server,))[0]['cursor']
            page = (client.incremental_page(cursor, page_size, previous)
                    if reuse and hasattr(client, 'incremental_page') else client.page(cursor, page_size))
            items = page['Items']
            total = int(page['TotalRecordCount'])
            if not isinstance(items, list) or total < cursor or (not items and cursor < total):
                raise ValueError('Incomplete Emby snapshot')
            with store.transaction():
                store.conn.execute('BEGIN IMMEDIATE')
                if store.meta('emby_sync_owner') != owner:
                    raise RuntimeError('Emby synchronization superseded')
                for item in items:
                    if not item.get('Id'):
                        raise ValueError('Missing Emby item ID')
                    store.conn.execute('INSERT OR REPLACE INTO media_stage VALUES (?,?,?)', (server, str(item['Id']), encode(item)))
                store.conn.execute('UPDATE library_inventory SET cursor=? WHERE server=?', (cursor + len(items), server))
            if cursor + len(items) >= total:
                break
            time.sleep(pause)
        # Publish only a complete snapshot; a failed page never deletes old inventory.
        with store.transaction():
            store.conn.execute('BEGIN IMMEDIATE')
            if store.meta('emby_sync_owner') != owner:
                raise RuntimeError('Emby synchronization superseded')
            staged = store.rows('SELECT * FROM media_stage WHERE server=?', (server,))
            if len(staged) != total:
                raise ValueError('Library changed while paging; restart sync')
            source = 'emby:' + server
            before_actors = store.rows('SELECT * FROM work_actor WHERE source=? ORDER BY work_id,actor_id', (source,))
            before_tags = store.rows('SELECT * FROM work_tag WHERE source=? ORDER BY work_id,category,source_id', (source,))
            # Replace this source's current relationships, retaining raw observations
            # and manual overrides. Removed or corrected metadata must not linger.
            store.conn.execute('DELETE FROM work_actor WHERE source=?', (source,))
            store.conn.execute('DELETE FROM work_tag WHERE source=?', (source,))
            for row in staged:
                item = json.loads(row['payload'])
                store.conn.execute('INSERT OR IGNORE INTO source_observation(source,source_id,raw_json,observed_at) VALUES (?,?,?,?)',
                                   (source, str(item['Id']), row['payload'], now()))
                work_id = store.meta('media_match:' + encode([server, str(item['Id'])])) or match_work(store, item)
                code = normalize_code(item.get('OriginalTitle') or item.get('Name') or '')
                if work_id is None and code and not store.rows('SELECT 1 FROM work_identity WHERE code=?', (code,)):
                    work_id = store.work('emby:' + server, str(item['Id']), item.get('Name', ''), code, raw={'Name': item.get('Name'), 'ProviderIds': item.get('ProviderIds')})
                if work_id:
                    for person in item.get('People') or []:
                        if person.get('Type') == 'Actor' and person.get('Id'):
                            store.add_actor(work_id, 'emby:' + server, str(person['Id']), person.get('Name', ''))
                    for category, key in (('genre', 'Genres'), ('tag', 'Tags')):
                        for name in item.get(key) or []:
                            store.add_tag(work_id, 'emby:' + server, category, name, name)
                available = not item.get('IsVirtualItem', False) and not item.get('IsOffline', False)
                playable = available and any(s.get('Path') and (s.get('SupportsDirectPlay') or s.get('SupportsTranscoding'))
                                             for s in item.get('MediaSources', []))
                store.conn.execute('INSERT OR REPLACE INTO media_copy VALUES (?,?,?,?,?,?,?,?,?)',
                                   (server, str(item['Id']), work_id, item.get('Path'), int(playable),
                                    1 if work_id else 0, generation, now(), row['payload']))
            after_actors = store.rows('SELECT * FROM work_actor WHERE source=? ORDER BY work_id,actor_id', (source,))
            after_tags = store.rows('SELECT * FROM work_tag WHERE source=? ORDER BY work_id,category,source_id', (source,))
            if before_actors != after_actors or before_tags != after_tags:
                store.set_meta('mapping_version', int(store.meta('mapping_version')) + 1)
            store.conn.execute('UPDATE library_inventory SET generation=?,synced_at=?,stale=0,pending_generation=NULL,cursor=0,error=NULL WHERE server=?', (generation, now(), server))
            store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
        return {'server': server, 'items': total}
    except Exception as error:
        with store.transaction():
            store.conn.execute('BEGIN IMMEDIATE')
            if store.meta('emby_sync_owner') != owner:
                raise ValueError('Emby synchronization superseded; new snapshot retained') from None
            store.conn.execute("UPDATE library_inventory SET stale=1,error='sync_failed' WHERE server=?", (server,))
            if isinstance(error, (ValueError, KeyError, TypeError)):
                store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
                store.conn.execute('UPDATE library_inventory SET pending_generation=NULL,cursor=0 WHERE server=?', (server,))
        # No exception details: transport URLs or payloads may contain private paths.
        raise ValueError('Emby sync failed; previous snapshot retained') from None
