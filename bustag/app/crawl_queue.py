import json
import os
import re
import threading
import time
from datetime import datetime

from bustag.util import APP_CONFIG, get_data_path

QUEUE_LOCK = threading.Lock()
FANHAO_IN_URL = re.compile(r'/([A-Za-z]{1,10}-\d{2,6})(?:[/?#]|$)')
_seq = 0


def _path():
    try:
        return get_data_path('crawl-queue.json')
    except Exception:
        return os.path.join(APP_CONFIG.get('download.data_path', '/app/data'), 'crawl-queue.json')


def _now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _empty():
    return {
        'current': None,
        'pending': [],
        'recent': [],
        'updated_at': _now(),
        'running': False,
        'day': datetime.now().strftime('%Y-%m-%d'),
        'day_count': 0,
    }


def _load():
    path = _path()
    try:
        with open(path) as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            return _empty()
        data.setdefault('current', None)
        data.setdefault('pending', [])
        data.setdefault('recent', [])
        data.setdefault('running', False)
        data.setdefault('day', datetime.now().strftime('%Y-%m-%d'))
        data.setdefault('day_count', 0)
        return data
    except (OSError, IOError, ValueError):
        return _empty()


def _save(data):
    data['updated_at'] = _now()
    path = _path()
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write('\n')
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _next_id():
    global _seq
    _seq += 1
    return '%d-%d' % (int(time.time() * 1000), _seq)


def label_for_url(url, fallback=''):
    match = FANHAO_IN_URL.search(url or '')
    if match:
        return match.group(1).upper()
    if '/search/' in (url or ''):
        return '搜索 ' + url.rstrip('/').split('/')[-1]
    if url and url.rstrip('/') == APP_CONFIG.get('download.root_path', '').rstrip('/'):
        return '站点更新'
    return fallback or (url or '')


def is_item_url(url):
    return bool(FANHAO_IN_URL.search(url or ''))


def make_item(url, kind='scheduled', source=''):
    return {
        'id': _next_id(),
        'url': url,
        'label': label_for_url(url),
        'kind': kind,
        'source': source,
        'created_at': _now(),
    }


def _known_urls(data):
    urls = set()
    if data.get('current') and data['current'].get('url'):
        urls.add(data['current']['url'])
    for item in data.get('pending') or []:
        if item.get('url'):
            urls.add(item['url'])
    return urls


def snapshot():
    with QUEUE_LOCK:
        data = _load()
        return json.loads(json.dumps(data))


def enqueue_front(items):
    if not items:
        return 0
    with QUEUE_LOCK:
        data = _load()
        known = _known_urls(data)
        added = []
        for item in items:
            url = item.get('url')
            if not url or url in known:
                continue
            known.add(url)
            added.append(item)
        data['pending'] = added + list(data.get('pending') or [])
        _save(data)
        return len(added)


def enqueue_back(items):
    if not items:
        return 0
    with QUEUE_LOCK:
        data = _load()
        known = _known_urls(data)
        added = []
        for item in items:
            url = item.get('url')
            if not url or url in known:
                continue
            known.add(url)
            added.append(item)
        data['pending'] = list(data.get('pending') or []) + added
        _save(data)
        return len(added)


def take_next():
    with QUEUE_LOCK:
        data = _load()
        today = datetime.now().strftime('%Y-%m-%d')
        if data.get('day') != today:
            data['day'] = today
            data['day_count'] = 0
        if data.get('current'):
            return json.loads(json.dumps(data['current']))
        pending = list(data.get('pending') or [])
        if not pending:
            data['running'] = False
            _save(data)
            return None
        try:
            limit = int(APP_CONFIG.get('download.daily_limit') or 40)
        except (TypeError, ValueError):
            limit = 40
        chosen = None
        remain = []
        for item in pending:
            if chosen is None and (item.get('kind') == 'custom' or data.get('day_count', 0) < limit):
                chosen = item
            else:
                remain.append(item)
        if chosen is None:
            data['running'] = False
            _save(data)
            return None
        data['pending'] = remain
        data['current'] = chosen
        data['running'] = True
        _save(data)
        return json.loads(json.dumps(chosen))


def finish_current(status, detail=''):
    with QUEUE_LOCK:
        data = _load()
        current = data.get('current')
        if current:
            rec = dict(current)
            rec['status'] = status
            rec['detail'] = detail or ''
            rec['finished_at'] = _now()
            recent = [rec] + list(data.get('recent') or [])
            data['recent'] = recent[:30]
            if status == 'ok':
                data['day_count'] = int(data.get('day_count') or 0) + 1
        data['current'] = None
        data['running'] = bool(data.get('pending'))
        _save(data)
