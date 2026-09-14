from bustag.app.index import _build_query
from bustag.spider.db import get_items


def test_items_can_be_filtered_by_genre():
    items, _ = get_items(page=None, tag_type='genre', tag_value='高畫質')

    assert items
    assert all('高畫質' in item.tags_dict['genre'] for item in items)


def test_unknown_tag_returns_no_items():
    items, page_info = get_items(
        page=None, tag_type='star', tag_value='__missing_filter_value__')

    assert items == []
    assert page_info[0] == 0


def test_filter_query_preserves_rating_and_encodes_tag():
    query = _build_query(2, like=1, tag_type='star', tag_value='演员 A')

    assert query == '?page=2&like=1&tag_type=star&tag=%E6%BC%94%E5%91%98+A'
