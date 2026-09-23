from pathlib import Path
import bottle
from webtest import TestApp
from bustag.recommender.web import install, CSRF
from conftest import work


def test_v2_redirects_to_legacy_and_keeps_single_feedback_source(store, tmp_path):
    wid, actor, tag_id = work(store, 1)
    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    app = bottle.Bottle()
    install(app, store.path, str(tmp_path / 'models'))
    client = TestApp(app)

    page = client.get('/v2', status=303)
    assert page.headers['Location'] == '/tagit'
    local = client.get('/v2?entry=local', status=303)
    assert local.headers['Location'] == '/local'

    client.post('/v2/actor/' + actor, {'state': 'like'}, status=403)
    changed = client.post('/v2/actor/' + actor,
                          {'state': 'like', 'csrf': CSRF, 'return_to': '/tagit?page=2'},
                          status=303)
    assert changed.headers['Location'] == '/tagit?page=2'
    assert store.rows('SELECT state FROM actor_preference')[0]['state'] == 'like'
    filtered = client.post('/v2/actor/' + actor,
                           {'state': 'pending', 'csrf': CSRF,
                            'return_to': '/tagit?like=1&tag=genre%3Acomedy&page=3#form-7'},
                           status=303)
    assert filtered.headers['Location'] == '/tagit?like=1&tag=genre%3Acomedy&page=3#form-7'
    fallback = client.post('/v2/actor/' + actor,
                           {'state': 'dislike', 'csrf': CSRF, 'return_to': '//evil.example'},
                           status=303)
    assert fallback.headers['Location'] == '/tagit'

    client.post('/v2/feedback/' + wid, {'value': '0', 'csrf': CSRF}, status=410)
    assert store.rows('SELECT * FROM explicit_work_feedback') == []
    tag_change = client.post('/v2/tag/' + wid + '/' + tag_id,
                             {'enabled': '0', 'csrf': CSRF, 'return_to': '/tag?like=1'},
                             status=303)
    assert tag_change.headers['Location'] == '/tag?like=1'
    assert store.rows('SELECT enabled FROM tag_override')[0]['enabled'] == 0

    client.get('/v2/status')
    manage = client.get('/v2/manage')
    assert '作品人工反馈' not in manage.text
    assert '演员人工三态' not in manage.text
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
    assert '个人推荐 V2' not in html
    assert 'href="/tagit"' in html
    assert '/settings' in html


def test_legacy_tag_card_renders_v2_controls_in_original_style_without_nested_forms():
    from html.parser import HTMLParser
    from types import SimpleNamespace

    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    item = SimpleNamespace(id=1, fanhao='SYN-001', release_date='2025-01-01',
                           add_date='2025-01-02', title='Synthetic', url='/SYN-001',
                           cover_img_url='', tags_dict={'genre': ['g'], 'star': ['a']})
    detail = {
        'work_id': 'work-1', 'model_current': True, 'model_score': .99,
        'match_score': .99, 'actors': [{'actor_id': 'actor-1', 'name': 'Actor A', 'state': 'pending'}],
        'tags': [{'tag_id': 'tag-1', 'category': 'genre', 'name': 'Drama', 'enabled': True}],
    }
    html = bottle.template('tagit', path='/tagit', items=[item], page_info=(1,1,1,10),
                           like=None, poster_src=lambda url: '',
                           query_url=lambda page: '?page=1',
                           tag_url=lambda category, value: '?tag=test',
                           filter_label=None, filter_value=None, clear_url='?',
                           v2_items={'SYN-001': detail}, csrf='test-csrf', return_to='/tagit')
    assert '匹配分数 0.990' in html and '模型匹配分数 0.990' in html
    assert 'Actor A' in html and '/v2/actor/actor-1' in html
    assert '/v2/tag/work-1/tag-1' in html and '排除误标' in html
    assert 'btn btn-primary btn-sm' in html and 'btn btn-danger btn-sm' in html
    assert '个人推荐 V2' not in html

    class FormNesting(HTMLParser):
        def __init__(self):
            super().__init__(); self.depth = 0
        def handle_starttag(self, tag, attrs):
            if tag == 'form':
                assert self.depth == 0, 'forms must be siblings, not nested'
                self.depth += 1
        def handle_endtag(self, tag):
            if tag == 'form':
                self.depth -= 1
                assert self.depth == 0

    parser = FormNesting()
    parser.feed(html)
    assert parser.depth == 0
