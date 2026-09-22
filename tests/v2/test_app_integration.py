"""Run real route registration in a disposable configured workspace, no crawler."""
import os
import subprocess
import sys
from pathlib import Path


def test_existing_app_routes_keep_v2_and_https_origin(tmp_path):
    root = Path(__file__).parents[2]
    data = tmp_path / 'data'
    data.mkdir()
    (data / 'config.ini').write_text('[download]\nroot_path=https://example.invalid/\ndata_path=' + data.as_posix() + '\n', encoding='utf-8')
    script = '''
from webtest import TestApp
from bustag.recommender.store import Store
store = Store('data/bus.db')
store.migrate('data/backup.db')
store.close()
import bustag.app.index as main
class Connection:
    def connect(self, **kwargs): pass
    def is_closed(self): return True
main.dbconn = Connection()
client = TestApp(main.app)
for path, target in [('/', '/v2'), ('/recommend', '/v2'), ('/model', '/v2/status'), ('/do-training', '/v2/status')]:
    response = client.get(path, status=303, extra_environ={'HTTP_HOST':'public.example:1023','wsgi.url_scheme':'https'})
    assert response.headers['Location'] == target
assert '个人推荐 V2' in client.get('/v2').text
assert '训练' in client.get('/v2/status').text
assert client.get('/queue.json').json['pending'] == []
assert client.get('/settings').status_int == 200
'''
    environment = dict(os.environ, PYTHONPATH=str(root), PYTHONUTF8='1')
    result = subprocess.run([sys.executable, '-c', script], cwd=str(tmp_path), env=environment,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
    assert result.returncode == 0, (result.stdout + result.stderr).decode('utf-8', 'replace')
