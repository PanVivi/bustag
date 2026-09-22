"""Bottle routes; CSRF protection on all new manual mutations."""
import os
import secrets
import sqlite3
from contextlib import contextmanager

from bottle import abort, redirect, request, template

from .store import Store
from .ranking import emby_link, rank
from . import jobs

CSRF = secrets.token_urlsafe(32)


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
        redirect('/v2')

    @app.post('/v2/actor/<actor_id>')
    def actor(actor_id):
        csrf()
        try:
            with opened() as store:
                store.preference(actor_id, request.forms.get('state'))
        except (ValueError, sqlite3.IntegrityError):
            abort(400, 'Invalid actor preference')
        redirect('/v2')

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
        redirect('/v2')

    @app.get('/v2/status')
    def status():
        with opened() as store:
            tables = store.rows("SELECT name FROM sqlite_master WHERE name='v2_job'")
            state = store.rows('SELECT kind,state,updated_at,message FROM v2_job') if tables else []
            inventory = store.rows('SELECT synced_at,stale,error FROM library_inventory')
            manifest = store.rows('SELECT manifest_json FROM model_manifest WHERE version=?', (store.meta('active_model'),))
            return template('v2_status', path='/v2/status', stats=store.statistics(), jobs=state,
                            inventory=inventory, manifest=manifest, csrf=CSRF)

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
