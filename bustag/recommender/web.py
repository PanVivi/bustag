"""Bottle routes; CSRF protection on all new manual mutations."""
import secrets
import sqlite3
from contextlib import contextmanager
from urllib.parse import urlsplit

from bottle import abort, HTTPResponse, request, template

from .store import Store
from . import jobs

CSRF = secrets.token_urlsafe(32)


def redirect(path, status=303):
    # Preserve the browser's public HTTPS origin/port behind the NAS proxy.
    # Bottle's absolute redirects can use the internal HTTP host instead.
    raise HTTPResponse(status=status, headers={'Location': path})


def _safe_return_to(default):
    path = request.forms.get('return_to', '')
    parsed = urlsplit(path)
    if (not path.startswith('/') or path.startswith('//') or parsed.scheme or parsed.netloc or
            parsed.path not in ('/tag', '/tagit', '/v2/manage') or '\\' in path or
            any(ord(char) < 32 for char in path)):
        return default
    return path


def install(app, database, models):
    @contextmanager
    def opened():
        store = Store(database)
        try:
            if not store.enabled():
                abort(503, 'V2 尚未迁移；请先执行私有备份和 migrate 命令')
            yield store
        finally:
            store.close()

    def csrf():
        if not secrets.compare_digest(request.forms.get('csrf', ''), CSRF):
            abort(403, 'Invalid form token')

    @app.get('/v2')
    def listing():
        entry = request.query.get('entry', 'discover')
        if entry not in ('discover', 'local', 'review'):
            abort(400, 'Invalid entry')
        try:
            page = max(1, int(request.query.get('page', '1')))
        except ValueError:
            abort(400, 'Invalid page')
        target = '/local' if entry == 'local' else '/tagit'
        if page > 1:
            target += '?page={}'.format(page)
        redirect(target, 303)

    @app.post('/v2/feedback/<work_id>')
    def feedback(work_id):
        # Ratings now go through the legacy /tagit form, whose item_rate write
        # and V2 trigger keep one shared source of truth.
        csrf()
        abort(410, '作品打标已合并到原版页面，请返回 /tagit 使用同一组按钮。')

    @app.post('/v2/actor/<actor_id>')
    def actor(actor_id):
        csrf()
        try:
            with opened() as store:
                store.preference(actor_id, request.forms.get('state'))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid actor preference')
        redirect(_safe_return_to('/tagit'), 303)

    @app.post('/v2/tag/<work_id>/<tag_id>')
    def tag(work_id, tag_id):
        csrf()
        if request.forms.get('enabled') not in ('0', '1'):
            abort(400, 'Invalid tag correction')
        try:
            with opened() as store:
                store.correct_tag(work_id, tag_id, request.forms.get('enabled') == '1')
        except sqlite3.IntegrityError:
            abort(400, 'Unknown work or tag')
        redirect(_safe_return_to('/tagit'), 303)

    @app.get('/v2/status')
    def status():
        with opened() as store:
            tables = store.rows("SELECT name FROM sqlite_master WHERE name='v2_job'")
            state = store.rows('SELECT kind,state,updated_at,message FROM v2_job') if tables else []
            inventory = store.rows('SELECT synced_at,stale,error FROM library_inventory')
            manifest = store.rows('SELECT manifest_json FROM model_manifest WHERE version=?', (store.meta('active_model'),))
            return template('v2_status', path='/v2/status', stats=store.statistics(), jobs=state,
                            inventory=inventory, manifest=manifest, csrf=CSRF)

    @app.get('/v2/manage')
    def manage():
        try:
            page = max(1, int(request.query.get('page', '1')))
        except ValueError:
            abort(400, 'Invalid page')
        with opened() as store:
            tags = store.rows('SELECT s.*,c.category AS canonical_category,c.name AS canonical_name FROM source_tag s JOIN canonical_tag c USING(tag_id) ORDER BY s.source,s.category,s.source_id LIMIT 50 OFFSET ?', ((page-1)*50,))
            pending = store.rows('SELECT server,item_id FROM media_copy WHERE work_id IS NULL LIMIT 50 OFFSET ?', ((page-1)*50,))
            return template('v2_manage', path='/v2/manage', tags=tags, pending=pending, csrf=CSRF, page=page)

    @app.post('/v2/map-tag')
    def map_tag():
        csrf()
        try:
            with opened() as store:
                store.map_tag(*(request.forms.get(k, '') for k in ('source', 'category', 'source_id', 'tag_id')))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid mapping')
        redirect('/v2/manage', 303)

    @app.post('/v2/resolve-media')
    def resolve_media():
        csrf()
        try:
            with opened() as store:
                store.resolve_media(*(request.forms.get(k, '') for k in ('server', 'item_id', 'work_id')))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid media match')
        redirect('/v2/manage', 303)

    @app.post('/v2/merge-actor')
    def merge_actor():
        csrf()
        try:
            with opened() as store:
                store.merge_actor(request.forms.get('source_actor', ''), request.forms.get('target_actor', ''))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid actor mapping or conflicting explicit preferences')
        redirect('/v2/manage', 303)

    @app.post('/v2/job/<kind>')
    def job(kind):
        csrf()
        from . import model
        from .emby import Emby, sync
        if kind == 'train':
            operation = lambda store: model.train(store, models)
        elif kind == 'rescore':
            def operation(store):
                with store.transaction():
                    model.rescore(store, model.load(store, models))
        elif kind == 'sync':
            # Explicit UI action plus private environment consent is required.
            try:
                client = Emby.from_environment()
            except ValueError:
                abort(400, 'Emby 只读授权或私有配置尚未就绪')
            operation = lambda store: sync(store, client)
        else:
            abort(404)
        with opened():
            jobs.submit(database, kind, operation)
        redirect('/v2/status')
