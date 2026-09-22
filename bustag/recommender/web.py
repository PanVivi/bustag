"""Bottle routes; CSRF protection on all new manual mutations."""
import os
import secrets
import sqlite3
from contextlib import contextmanager

from bottle import abort, HTTPResponse, request, template

from .store import Store
from .ranking import emby_link, rank
from . import jobs

CSRF = secrets.token_urlsafe(32)


def redirect(path, status=303):
    # Preserve the browser's public HTTPS origin/port behind the NAS proxy.
    # Bottle's absolute redirects can use the internal HTTP host instead.
    raise HTTPResponse(status=status, headers={'Location': path})


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
        with opened() as store:
            items = rank(store, entry, 20, (page-1)*20)
            for work in items:
                for media in work['media']:
                    media['link'] = emby_link(store.meta('emby_url:' + media['server']), media['server'], media['item_id'])
                work['tags'] = store.rows('''SELECT DISTINCT c.*,coalesce(o.enabled,1) AS enabled FROM canonical_tag c
                    JOIN source_tag s ON c.tag_id=s.tag_id JOIN work_tag w
                    ON w.source=s.source AND w.category=s.category AND w.source_id=s.source_id
                    LEFT JOIN tag_override o ON o.tag_id=c.tag_id AND o.work_id=w.work_id WHERE w.work_id=?''', (work['work_id'],))
            return template('v2', path='/v2', items=items, entry=entry, page=page, csrf=CSRF)

    @app.post('/v2/feedback/<work_id>')
    def feedback(work_id):
        csrf()
        try:
            with opened() as store:
                store.feedback(work_id, int(request.forms.get('value', '-1')))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid feedback')
        redirect('/v2', 303)

    @app.post('/v2/actor/<actor_id>')
    def actor(actor_id):
        csrf()
        try:
            with opened() as store:
                store.preference(actor_id, request.forms.get('state'))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid actor preference')
        redirect('/v2', 303)

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
        redirect('/v2', 303)

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
            actors = store.rows("SELECT a.*,coalesce(p.state,'pending') AS state FROM actor a LEFT JOIN actor_preference p USING(actor_id) WHERE NOT EXISTS(SELECT 1 FROM v2_meta m WHERE m.key='actor_redirect:' || a.actor_id) ORDER BY a.name,a.actor_id LIMIT 50 OFFSET ?", ((page-1)*50,))
            tags = store.rows('SELECT s.*,c.category AS canonical_category,c.name AS canonical_name FROM source_tag s JOIN canonical_tag c USING(tag_id) ORDER BY s.source,s.category,s.source_id LIMIT 50 OFFSET ?', ((page-1)*50,))
            pending = store.rows('SELECT server,item_id FROM media_copy WHERE work_id IS NULL LIMIT 50 OFFSET ?', ((page-1)*50,))
            feedback = store.rows('SELECT w.work_id,w.code,w.title,f.value FROM explicit_work_feedback f JOIN work_identity w USING(work_id) ORDER BY f.confirmed_at DESC,w.work_id LIMIT 50 OFFSET ?', ((page-1)*50,))
            return template('v2_manage', path='/v2/manage', actors=actors, tags=tags, pending=pending, feedback=feedback, csrf=CSRF, page=page)

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
