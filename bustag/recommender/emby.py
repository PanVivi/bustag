"""Opt-in read-only Emby snapshot ingestion. No media mutation endpoints."""
import json
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

    def page(self, offset, size):
        from urllib.parse import quote
        return self.get('/Users/' + quote(self.user_id, safe='') + '/Items', {
            'ParentId': self.library_id, 'Recursive': 'true', 'IncludeItemTypes': 'Movie',
            'Fields': 'Path,People,Genres,Tags,ProviderIds,MediaSources,OriginalTitle',
            'EnableUserData': 'true',
            'StartIndex': offset, 'Limit': size, 'SortBy': 'SortName', 'SortOrder': 'Ascending'})


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
    if not 1 <= page_size <= 1000:
        raise ValueError('Invalid page size')
    try:
        public = client.get('/System/Info/Public')
    except Exception:
        with store.transaction():
            # Only this configured connection's previous inventories become stale.
            for old in store.rows('SELECT server FROM library_inventory'):
                if store.meta('emby_url:' + old['server']) == client.base:
                    store.conn.execute("UPDATE library_inventory SET stale=1,error='sync_failed' WHERE server=?", (old['server'],))
        raise ValueError('Emby sync failed; previous snapshot retained') from None
    server = str(public['Id'])
    # A scope change cannot resume a cursor from a different library/user/server URL.
    scope = encode([client.base, client.user_id, client.library_id])
    with store.transaction():
        store.conn.execute('INSERT OR IGNORE INTO library_inventory(server) VALUES (?)', (server,))
        state = store.rows('SELECT * FROM library_inventory WHERE server=?', (server,))[0]
        generation = state['pending_generation']
        if not generation or store.meta('emby_scope:' + server) != scope:
            generation = uuid.uuid4().hex
            store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
            store.conn.execute('UPDATE library_inventory SET pending_generation=?,cursor=0 WHERE server=?', (generation, server))
            store.set_meta('emby_scope:' + server, scope)
        store.set_meta('emby_url:' + server, client.base)
    try:
        while True:
            cursor = store.rows('SELECT cursor FROM library_inventory WHERE server=?', (server,))[0]['cursor']
            page = client.page(cursor, page_size)
            items = page['Items']
            total = int(page['TotalRecordCount'])
            if not isinstance(items, list) or total < cursor or (not items and cursor < total):
                raise ValueError('Incomplete Emby snapshot')
            with store.transaction():
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
            staged = store.rows('SELECT * FROM media_stage WHERE server=?', (server,))
            if len(staged) != total:
                raise ValueError('Library changed while paging; restart sync')
            for row in staged:
                item = json.loads(row['payload'])
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
            store.conn.execute('UPDATE library_inventory SET generation=?,synced_at=?,stale=0,pending_generation=NULL,cursor=0,error=NULL WHERE server=?', (generation, now(), server))
            store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
        return {'server': server, 'items': total}
    except Exception as error:
        with store.transaction():
            store.conn.execute("UPDATE library_inventory SET stale=1,error='sync_failed' WHERE server=?", (server,))
            if isinstance(error, (ValueError, KeyError, TypeError)):
                store.conn.execute('DELETE FROM media_stage WHERE server=?', (server,))
                store.conn.execute('UPDATE library_inventory SET pending_generation=NULL,cursor=0 WHERE server=?', (server,))
        # No exception details: transport URLs or payloads may contain private paths.
        raise ValueError('Emby sync failed; previous snapshot retained') from None
