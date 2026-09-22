from pathlib import Path
import bottle
from webtest import TestApp
from bustag.recommender.web import install, CSRF
from conftest import work


def test_dual_entry_ui_feedback_csrf_and_preferences(store, tmp_path):
    wid, actor, _ = work(store, 1)
    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    app = bottle.Bottle()
    install(app, store.path, str(tmp_path / 'models'))
    client = TestApp(app)
    page = client.get('/v2')
    assert '发现新片' in page.text and '本地片库推荐' in page.text
    client.post('/v2/actor/' + actor, {'state': 'like'}, status=403)
    client.post('/v2/actor/' + actor, {'state': 'like', 'csrf': CSRF}, status=303)
    assert 'actor_first' in client.get('/v2').text
    client.post('/v2/feedback/' + wid, {'value': '0', 'csrf': CSRF}, status=303)
    assert 'SYN-001' not in client.get('/v2').text
    assert store.rows('SELECT state FROM actor_preference')[0]['state'] == 'like'
    client.get('/v2?entry=local')
    client.get('/v2/status')
    client.get('/v2?entry=invalid', status=400)
    client.get('/v2?entry=local&page=abc', status=400)
