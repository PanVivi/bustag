from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace

import bottle

from bustag.recommender.ranking import FEATURE_VERSION, legacy_card_details
from bustag.recommender.store import now


def test_legacy_tag_cards_read_v2_scores_preferences_and_tag_overrides(store):
    with store.transaction():
        work_id = store.work('javbus', 'SYN-001', 'Synthetic work', 'SYN-001')
        actor_id = store.add_actor(work_id, 'javbus', 'actor-1', 'Actor A')
        tag_id = store.add_tag(work_id, 'javbus', 'genre', 'genre-1', 'Drama')
    store.preference(actor_id, 'like')

    version = 'a' * 32
    with store.transaction():
        store.set_meta('active_model', version)
        store.conn.execute(
            'INSERT INTO v2_recommendation_score VALUES (?,?,?,?,?,?,?)',
            (work_id, version, FEATURE_VERSION, int(store.meta('mapping_version')),
             .99, 0.0, now()))

    details = legacy_card_details(store, ['SYN-001', 'MISSING'])
    card = details['SYN-001']
    assert details.keys() == {'SYN-001'}
    assert card['model_current'] is True
    assert card['match_score'] == .99 and card['model_score'] == .99
    assert card['actors'] == [{'actor_id': actor_id, 'name': 'Actor A', 'state': 'like'}]
    assert card['tags'] == [{'tag_id': tag_id, 'category': 'genre', 'name': 'Drama', 'enabled': True}]

    store.correct_tag(work_id, tag_id, False)
    corrected = legacy_card_details(store, ['SYN-001'])['SYN-001']
    assert corrected['model_current'] is False  # mapping changes require a retrain/rescore
    assert corrected['tags'][0]['enabled'] is False


def test_legacy_tag_template_embeds_v2_controls_without_nested_forms():
    bottle.TEMPLATE_PATH.insert(0, str(Path(__file__).parents[2] / 'bustag/app/views'))
    item = SimpleNamespace(id=1, fanhao='SYN-001', release_date='2025-01-01',
                           add_date='2025-01-02', title='Synthetic', url='/SYN-001',
                           cover_img_url='', tags_dict={'genre': ['Drama'], 'star': ['Actor A']})
    detail = {
        'work_id': 'work-1', 'model_current': True, 'model_score': .99,
        'match_score': .99, 'actors': [{'actor_id': 'actor-1', 'name': 'Actor A', 'state': 'pending'}],
        'tags': [{'tag_id': 'tag-1', 'category': 'genre', 'name': 'Drama', 'enabled': True}],
    }
    page = bottle.template(
        'tagit', path='/tagit', items=[item], page_info=(1, 1, 1, 20), like=None,
        poster_src=lambda url: '', query_url=lambda page: '?page=1',
        tag_url=lambda category, value: '?tag=test', filter_label=None,
        filter_value=None, clear_url='?', v2_items={'SYN-001': detail},
        csrf='test-csrf', return_to='/tagit')

    assert '匹配分数 0.990' in page and '模型匹配分数 0.990' in page
    assert 'href="/tagit"' in page
    assert 'action="/tag/SYN-001?page=1"' in page
    assert 'action="/v2/actor/actor-1"' in page
    assert 'action="/v2/tag/work-1/tag-1"' in page
    assert 'btn btn-primary btn-sm' in page and 'btn btn-danger btn-sm' in page
    assert '个人推荐 V2' not in page

    class NoNestedForms(HTMLParser):
        def __init__(self):
            super().__init__()
            self.depth = 0

        def handle_starttag(self, tag, attrs):
            if tag == 'form':
                assert self.depth == 0
                self.depth += 1

        def handle_endtag(self, tag):
            if tag == 'form':
                self.depth -= 1
                assert self.depth == 0

    parser = NoNestedForms()
    parser.feed(page)
    assert parser.depth == 0
