"""Run real route registration in a disposable configured workspace, no crawler."""
import os
import subprocess
import sys
from pathlib import Path


def test_existing_app_routes_return_to_legacy_and_https_origin(tmp_path):
    root = Path(__file__).parents[2]
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.ini').write_text('[download]\nroot_path=https://example.invalid/\ndata_path=' + data.as_posix() + '\n', encoding='utf-8')
    script = '''
from webtest import TestApp
from bustag.recommender.store import Store
store = Store('data/bus.db')
store.migrate('data/backup.db')
from bustag.recommender.ranking import FEATURE_VERSION
with store.transaction():
    work_id = store.work('javbus', 'SYN-025', 'Synthetic work', 'SYN-025')
    actor_id = store.add_actor(work_id, 'javbus', 'actor-1', 'Actor A')
    tag_id = store.add_tag(work_id, 'javbus', 'genre', 'genre-1', 'Drama')
    model_version = 'a' * 32
    store.set_meta('active_model', model_version)
    store.conn.execute('INSERT INTO v2_recommendation_score VALUES (?,?,?,?,?,?,?)',
                       (work_id, model_version, FEATURE_VERSION, int(store.meta('mapping_version')), .91, 0.0, '2026-01-01'))
store.close()
import bustag.app.index as main
class Connection:
    def connect(self, **kwargs): pass
    def is_closed(self): return True
main.dbconn = Connection()
from types import SimpleNamespace
main.RATE_TYPE = SimpleNamespace(SYSTEM_RATE=SimpleNamespace(value=0))
main.RATE_VALUE = SimpleNamespace(LIKE=SimpleNamespace(value=1))
item = SimpleNamespace(id=1, fanhao='SYN-025', release_date='2026-01-01',
                       add_date='2026-01-02', title='Synthetic work', url='/SYN-025',
                       cover_img_url='', tags_dict={'genre':['Drama'], 'star':['Actor A']})
main.get_items = lambda **kwargs: ([item], (1, 1, 1, 20))
class Counts:
    def get_today_update_count(self): return 0
    def get_today_recommend_count(self): return 0
main.db = Counts()
client = TestApp(main.app)
for path, target in [('/', '/tag'), ('/v2', '/tagit'), ('/model', '/v2/status'), ('/do-training', '/v2/status')]:
    response = client.get(path, status=303, extra_environ={'HTTP_HOST':'public.example:1023','wsgi.url_scheme':'https'})
    assert response.headers['Location'] == target
assert client.get('/recommend').status_int == 200
for path in ('/tagit', '/tag'):
    page = client.get(path)
    assert 'SYN-025' in page.text
    assert '匹配分数 0.910' in page.text
    assert '模型匹配分数 0.910' in page.text
    assert '/v2/actor/' in page.text and '/v2/tag/' in page.text
    assert 'action="/tag/SYN-025' in page.text
assert '个人推荐 V2' not in client.get('/v2/status').text
assert '训练' in client.get('/v2/status').text
assert client.get('/queue.json').json['pending'] == []
assert client.get('/settings').status_int == 200
'''
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, '-c', script], cwd=str(tmp_path), env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
