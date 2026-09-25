import pytest
from bustag.recommender.store import Store


@pytest.fixture
def store(tmp_path):
    value = Store(tmp_path / 'test.db')
    value.migrate(tmp_path / 'before.db')
    yield value
    value.close()


def work(store, number, actor='a', genre='g'):
    with store.transaction():
        wid = store.work('fixture', str(number), 'Synthetic work', 'SYN-{:03}'.format(number))
        aid = store.add_actor(wid, 'fixture', actor, actor)
        tag = store.add_tag(wid, 'fixture', 'genre', genre, genre)
    return wid, aid, tag
