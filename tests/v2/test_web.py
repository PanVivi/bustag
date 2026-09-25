import json
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
    ajax = client.post('/v2/actor/' + actor,
                       {'state': 'dislike', 'csrf': CSRF, 'return_to': '/tagit?like=1'},
                       headers={'Accept': 'application/json'}, status=200)
    assert ajax.headers['Content-Type'].startswith('application/json')
    assert json.loads(ajax.text) == {'ok': True, 'actor_id': actor, 'state': 'dislike'}
    assert store.rows('SELECT state FROM actor_preference')[0]['state'] == 'dislike'
    assert store.rows('SELECT * FROM explicit_work_feedback') == []
    filtered = client.post('/v2/actor/' + actor,
                           {'state': 'pending', 'csrf': CSRF,
                            'return_to': '/tagit?like=1&tag=genre%3Acomedy&page=3#form-7'},
                           status=303)
    assert filtered.headers['Location'] == '/tagit?like=1&tag=genre%3Acomedy&page=3#form-7'
    fallback = client.post('/v2/actor/' + actor,
                           {'state': 'dislike', 'csrf': CSRF, 'return_to': '//evil.example'},
                           status=303)
    assert fallback.headers['Location'] == '/tagit'
    recommendation_return = client.post('/v2/actor/' + actor,
                           {'state': 'like', 'csrf': CSRF, 'return_to': '/recommend?like=1&page=2'},
                           status=303)
    assert recommendation_return.headers['Location'] == '/recommend?like=1&page=2'

    client.post('/v2/feedback/' + wid, {'value': '0', 'csrf': CSRF}, status=410)
    assert store.rows('SELECT * FROM explicit_work_feedback') == []
    tag_change = client.post('/v2/tag/' + wid + '/' + tag_id,
                             {'enabled': '0', 'csrf': CSRF,
                              'return_to': '/tagit?like=1&tag_type=star&tag=Actor%20A&page=3#form-7'},
                             status=303)
    assert tag_change.headers['Location'] == '/tagit?like=1&tag_type=star&tag=Actor%20A&page=3#form-7'
    assert store.rows('SELECT enabled FROM tag_override')[0]['enabled'] == 0

    mapping = client.post('/v2/map-tag',
                          {'csrf': CSRF, 'source': 'fixture', 'category': 'genre',
                           'source_id': 'g', 'tag_id': tag_id, 'return_to': '/v2/manage?page=4'},
                          status=303)
    assert mapping.headers['Location'] == '/v2/manage?page=4'

    client.get('/v2/status')
    manage = client.get('/v2/manage')
    assert '作品人工反馈' not in manage.text
    assert '演员人工三态' not in manage.text
    assert 'name="return_to" value="/v2/manage?page=1"' in manage.text
    client.get('/v2?entry=invalid', status=400)
    client.get('/v2?entry=local&page=abc', status=400)


def test_legacy_layout_still_renders_continuous_score():
    from html.parser import HTMLParser
    from types import SimpleNamespace
    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    item = SimpleNamespace(id=1, fanhao='SYN-001', release_date='2025-01-01',
                           add_date='2025-01-02', title='Synthetic', url='/SYN-001',
                           cover_img_url='', recommend_score=.75,
                           tags_dict={'genre': ['g'], 'star': ['a']})
    html = bottle.template('index', path='/recommend', msg='', filter_value=None,
                           items=[item], page_info=(1,1,1,10), like=1,
                           poster_src=lambda url: '', query_url=lambda page: '?page=1',
                           tag_url=lambda category, value: '?tag=test', bustag_layout='single',
                           v2_items={'SYN-001': {'model_current': True, 'match_score': .75,
                               'actors': [{'actor_id': 'actor-1', 'name': 'a', 'state': 'like'}]}},
                           csrf='test', return_to='/recommend')
    assert 'layout-single' in html
    assert '匹配分数 0.750' in html
    assert '模型匹配分数' not in html
    assert 'badge-warning actor-state-badge' in html and 'data-actor-state="like"' in html
    assert '/v2/actor/actor-1' in html and 'name="state" value="dislike"' in html
    assert 'name="return_to" value="/recommend#form-1"' in html
    class FormNesting(HTMLParser):
        def __init__(self):
            super().__init__(); self.depth = 0
        def handle_starttag(self, tag, attrs):
            if tag == 'form':
                assert self.depth == 0, 'recommendation forms must be siblings'
                self.depth += 1
        def handle_endtag(self, tag):
            if tag == 'form':
                self.depth -= 1
                assert self.depth == 0
    forms = FormNesting()
    forms.feed(html)
    assert forms.depth == 0
    assert '个人推荐 V2' not in html
    assert 'href="/tagit"' in html
    assert '/settings' in html


def test_legacy_tag_card_renders_v2_controls_in_original_style_without_nested_forms():
    from html.parser import HTMLParser
    from types import SimpleNamespace

    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    item = SimpleNamespace(id=1, fanhao='SYN-001', release_date='2025-01-01',
                           add_date='2025-01-02', title='Synthetic', url='/SYN-001',
                           cover_img_url='', tags_dict={'genre': ['g'], 'star': ['Actor A', 'Actor C']})
    item2 = SimpleNamespace(id=2, fanhao='SYN-002', release_date='2025-01-01',
                            add_date='2025-01-02', title='Synthetic 2', url='/SYN-002',
                            cover_img_url='', tags_dict={'genre': [], 'star': ['Actor B']})
    detail = {
        'work_id': 'work-1', 'model_current': True, 'model_score': .99,
        'match_score': .99, 'actors': [
            {'actor_id': 'actor-1', 'name': 'Actor A', 'state': 'pending'},
            {'actor_id': 'actor-3', 'name': 'Actor C', 'state': 'like'}],
        'tags': [{'tag_id': 'tag-1', 'category': 'genre', 'name': 'Drama', 'enabled': True}],
    }
    detail2 = {
        'work_id': 'work-2', 'model_current': True, 'model_score': .75,
        'match_score': .75, 'actors': [{'actor_id': 'actor-2', 'name': 'Actor B', 'state': 'dislike'}],
        'tags': [],
    }
    html = bottle.template('tagit', path='/tagit', items=[item, item2], page_info=(1,1,1,10),
                           like=None, poster_src=lambda url: '',
                           query_url=lambda page: '?page=1',
                           tag_url=lambda category, value: '?tag=test',
                           filter_label=None, filter_value=None, clear_url='?',
                           v2_items={'SYN-001': detail, 'SYN-002': detail2},
                           csrf='test-csrf', return_to='/tagit')
    assert '匹配分数 0.990' in html and '模型匹配分数' not in html
    assert 'form-1' in html and 'form-2' in html
    assert 'data-actor-state="like"' in html and 'badge-warning actor-state-badge' in html
    assert 'data-actor-state="pending"' in html and 'badge-secondary actor-state-badge' in html
    assert 'data-actor-state="dislike"' in html and 'badge-danger actor-state-badge' in html
    assert html.count('<article') == 2 and html.count('</article>') == 2
    class CardNesting(HTMLParser):
        def __init__(self):
            super().__init__(); self.depth = 0; self.nested = False
        def handle_starttag(self, tag, attrs):
            if tag == 'article' and 'tag-card' in dict(attrs).get('class', '').split():
                if self.depth:
                    self.nested = True
                self.depth += 1
        def handle_endtag(self, tag):
            if tag == 'article':
                self.depth -= 1
    cards = CardNesting()
    cards.feed(html)
    assert not cards.nested and cards.depth == 0
    assert 'Actor A' in html and '/v2/actor/actor-1' in html
    assert 'class="actor-quick-form" data-actor-id="actor-1"' in html
    assert html.count('class="actor-quick-btn ') == 2
    assert 'name="state" value="like"' in html and 'name="state" value="dislike"' in html
    assert 'actor-quick-form" data-actor-id="actor-2"' not in html
    assert 'actor-quick-form" data-actor-id="actor-3"' not in html
    assert 'name="return_to" value="/tagit#form-1"' in html
    assert '/v2/tag/work-1/tag-1' in html and '排除误标' in html
    assert 'btn btn-primary btn-sm' in html and 'btn btn-danger btn-sm' in html
    assert '个人推荐 V2' not in html
    assert '<div class="tag-code-row">' in html
    assert html.count('匹配分数 0.990') == 1

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
