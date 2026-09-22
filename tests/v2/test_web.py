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
    changed = client.post('/v2/actor/' + actor, {'state': 'like', 'csrf': CSRF}, status=303)
    assert changed.headers['Location'] == '/v2'
    assert 'actor_first' in client.get('/v2').text
    client.post('/v2/feedback/' + wid, {'value': '0', 'csrf': CSRF}, status=303)
    assert 'SYN-001' not in client.get('/v2').text
    assert store.rows('SELECT state FROM actor_preference')[0]['state'] == 'like'
    client.get('/v2?entry=local')
    client.get('/v2/status')
    client.get('/v2?entry=invalid', status=400)
    client.get('/v2?entry=local&page=abc', status=400)


def test_legacy_layout_still_renders_continuous_score():
    from types import SimpleNamespace
    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    item = SimpleNamespace(id=1, fanhao='SYN-001', release_date='2025-01-01',
                           add_date='2025-01-02', title='Synthetic', url='/SYN-001',
                           cover_img_url='', recommend_score=.75,
                           tags_dict={'genre': ['g'], 'star': ['a']})
    html = bottle.template('index', path='/recommend', msg='', filter_value=None,
                           items=[item], page_info=(1,1,1,10), like=1,
                           poster_src=lambda url: '', query_url=lambda page: '?page=1',
                           tag_url=lambda category, value: '?tag=test', bustag_layout='single')
    assert 'layout-single' in html
    assert '匹配分数 75' in html
    assert '个人推荐 V2' in html
    assert '/settings' in html
