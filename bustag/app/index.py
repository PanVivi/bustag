from collections import defaultdict
import threading
import traceback
import sys
import os
import hashlib
import tempfile
import configparser
import json
import re as _re
import bottle
from urllib.request import Request, urlopen
from urllib.parse import urlencode, urljoin, urlparse
from bustag.util import APP_CONFIG
from bustag.app.crawl_queue import snapshot as queue_snapshot, enqueue_front, make_item
from multiprocessing import freeze_support
from bottle import route, run, template, static_file, request, response, redirect, hook

dirname = os.path.dirname(os.path.realpath(__file__))
if getattr(sys, 'frozen', False):
    dirname = sys._MEIPASS
POSTER_CACHE = os.path.join(APP_CONFIG["download.data_path"], "poster-cache") if "download.data_path" in APP_CONFIG else "/app/data/poster-cache"
os.makedirs(POSTER_CACHE, mode=0o700, exist_ok=True)
POSTER_CACHE_LOCK = threading.Lock()
bottle.BaseTemplate.defaults['bustag_layout'] = 'double'
print('dirname:' + dirname)
bottle.TEMPLATE_PATH.insert(0, dirname + '/views/')


def poster_src(url):
    """Convert stored relative or absolute JavBus cover URLs to local proxy URLs."""
    value = str(url or '')
    parsed = urlparse(value)
    path = parsed.path if parsed.scheme in ('http', 'https') and parsed.netloc else value
    path = path.lstrip('/')
    if not path.startswith('pics/cover/'):
        return ''
    return '/poster/' + path


FILTER_LABELS = {'genre': '分类', 'star': '演员'}


def _decode_query_value(value):
    if not value:
        return value
    try:
        return value.encode('latin-1').decode('utf-8')
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value


def _get_tag_filter():
    tag_type = request.query.get('tag_type')
    tag_value = _decode_query_value(request.query.get('tag'))
    if tag_type not in FILTER_LABELS or not tag_value:
        return None, None
    return tag_type, tag_value


def _build_query(page, like=None, tag_type=None, tag_value=None):
    params = [('page', page)]
    if like is not None:
        params.append(('like', like))
    if tag_type and tag_value:
        params.extend((('tag_type', tag_type), ('tag', tag_value)))
    return '?' + urlencode(params)


def _list_template_args(like, tag_type, tag_value):
    return {
        'query_url': lambda page: _build_query(page, like, tag_type, tag_value),
        'tag_url': lambda next_type, next_value: _build_query(
            1, like, next_type, next_value),
        'clear_url': _build_query(1, like),
        'filter_label': FILTER_LABELS.get(tag_type),
        'filter_value': tag_value,
    }


@route('/static/<filepath:path>')
def server_static(filepath):
    """Serve the packaged CSS, JavaScript, and image assets."""
    return static_file(filepath, root=os.path.join(dirname, 'static'))


def _safe_redirect(url):
    """Keep redirects on the current browser origin, including HTTPS ports."""
    if url.startswith('http://') or url.startswith('https://'):
        parsed = urlparse(url)
        url = parsed.path or '/'
        if parsed.query:
            url += '?' + parsed.query
        if parsed.fragment:
            url += '#' + parsed.fragment
    if not url.startswith('/'):
        url = '/' + url
    response.status = 303
    response.set_header('Location', url)
    return ''


@hook('before_request')
def _trust_proxy_origin():
    proto = request.environ.get('HTTP_X_FORWARDED_PROTO')
    if proto:
        request.environ['wsgi.url_scheme'] = proto.split(',')[0].strip()
    forwarded_host = request.environ.get('HTTP_X_FORWARDED_HOST')
    host = (forwarded_host or request.environ.get('HTTP_HOST') or '').split(',')[0].strip()
    forwarded_port = request.environ.get('HTTP_X_FORWARDED_PORT')
    if host and forwarded_port and ':' not in host.split(']')[-1]:
        host = host + ':' + forwarded_port.split(',')[0].strip()
    if host:
        request.environ['HTTP_HOST'] = host
        request.environ['SERVER_NAME'] = host.rsplit(':', 1)[0].strip('[]')
        if host.startswith('[') and ']:' in host:
            request.environ['SERVER_PORT'] = host.rsplit(']:', 1)[-1]
        elif host.count(':') == 1:
            request.environ['SERVER_PORT'] = host.rsplit(':', 1)[-1]


@hook('before_request')
def _connect_db():
    dbconn.connect(reuse_if_open=True)


@hook('after_request')
def _close_db():
    if not dbconn.is_closed():
        dbconn.close()


@route("/poster/<filepath:path>")
def poster(filepath):
    if not filepath.startswith("pics/cover/") or ".." in filepath or "\\" in filepath or "://" in filepath or filepath.startswith("/"):
        response.status = 400
        return "invalid poster path"
    key = hashlib.sha256(filepath.encode("utf-8")).hexdigest()
    cached = os.path.join(POSTER_CACHE, key + ".img")
    cache_root = os.path.realpath(POSTER_CACHE)
    if os.path.islink(cached) or os.path.realpath(cached).rsplit(os.sep, 1)[0] != cache_root:
        response.status = 404
        return "not found"
    with POSTER_CACHE_LOCK:
        if os.path.isfile(cached):
            with open(cached, "rb") as fh:
                data = fh.read(5242881)
            if data.startswith(b"\xff\xd8\xff"):
                response.content_type = "image/jpeg"
                return data
            if data.startswith(b"\x89PNG\r\n\x1a\n"):
                response.content_type = "image/png"
                return data
            os.unlink(cached)
        root = APP_CONFIG["download.root_path"].rstrip("/") + "/"
        target = urljoin(root, filepath)
        if not target.startswith("https://www.javbus.com/"):
            response.status = 502
            return "upstream rejected"
        req = Request(target, headers={"User-Agent": "Mozilla/5.0", "Referer": root})
        try:
            with urlopen(req, timeout=20) as upstream:
                content_type = upstream.headers.get_content_type()
                if content_type not in ("image/jpeg", "image/png"):
                    response.status = 502
                    return "upstream is not an image"
                data = upstream.read(5242881)
                if len(data) > 5242880 or not (data.startswith(b"\xff\xd8\xff") or data.startswith(b"\x89PNG\r\n\x1a\n")):
                    response.status = 502
                    return "invalid image"
            fd, temp = tempfile.mkstemp(prefix=".tmp-", dir=POSTER_CACHE)
            try:
                os.chmod(temp, 0o600)
                with os.fdopen(fd, "wb") as fh:
                    fh.write(data)
                    fh.flush()
                    os.fsync(fh.fileno())
                os.replace(temp, cached)
            finally:
                if os.path.exists(temp):
                    os.unlink(temp)
            response.content_type = content_type
            return data
        except Exception:
            response.status = 404
            return "not found"


def _remove_extra_tags(item):
    limit = 10
    tags_dict = item.tags_dict
    tags = ['genre', 'star']
    for t in tags:
        tags_dict[t] = tags_dict[t][:limit]


@route('/')
@route('/recommend')
def index():
    rate_type = RATE_TYPE.SYSTEM_RATE.value
    rate_value = int(request.query.get('like', RATE_VALUE.LIKE.value))
    page = int(request.query.get('page', 1))
    tag_type, tag_value = _get_tag_filter()
    items, page_info = get_items(
        rate_type=rate_type, rate_value=rate_value, page=page,
        tag_type=tag_type, tag_value=tag_value)
    for item in items:
        _remove_extra_tags(item)
    today_update_count = db.get_today_update_count()
    today_recommend_count = db.get_today_recommend_count()
    msg = f'今日更新 {today_update_count} , 今日推荐 {today_recommend_count}'
    return template('index', items=items, page_info=page_info, like=rate_value,
                    path=request.path, msg=msg, poster_src=poster_src,
                    **_list_template_args(rate_value, tag_type, tag_value))


@route('/tagit')
def tagit():
    rate_value = request.query.get('like', None)
    rate_value = None if rate_value == 'None' else rate_value
    rate_type = None
    if rate_value:
        rate_value = int(rate_value)
        rate_type = RATE_TYPE.USER_RATE
    tag_type, tag_value = _get_tag_filter()
    page = int(request.query.get('page', 1))
    items, page_info = get_items(
        rate_type=rate_type, rate_value=rate_value, page=page,
        tag_type=tag_type, tag_value=tag_value)
    for item in items:
        _remove_extra_tags(item)
    return template('tagit', items=items, page_info=page_info, like=rate_value,
                    path=request.path, poster_src=poster_src,
                    **_list_template_args(rate_value, tag_type, tag_value))


@route('/tag/<fanhao>', method='POST')
def tag(fanhao):
    if request.POST.submit:
        formid = request.POST.formid
        item_rate = ItemRate.get_by_fanhao(fanhao)
        rate_value = request.POST.submit
        if not item_rate:
            rate_type = RATE_TYPE.USER_RATE
            ItemRate.saveit(rate_type, rate_value, fanhao)
            logger.debug(f'add new item_rate for fanhao:{fanhao}')
        else:
            item_rate.rate_value = rate_value
            item_rate.save()
            logger.debug(f'updated item_rate for fanhao:{fanhao}')
    page = int(request.query.get('page', 1))
    like = request.query.get('like')
    tag_type, tag_value = _get_tag_filter()
    url = f'/tagit{_build_query(page, like, tag_type, tag_value)}'
    if formid:
        url += f'#{formid}'
    return _safe_redirect(url)


@route('/correct/<fanhao>', method='POST')
def correct(fanhao):
    if request.POST.submit:
        formid = request.POST.formid
        is_correct = int(request.POST.submit)
        item_rate = ItemRate.get_by_fanhao(fanhao)
        if item_rate:
            item_rate.rate_type = RATE_TYPE.USER_RATE
            if not is_correct:
                rate_value = item_rate.rate_value
                rate_value = 1 if rate_value == 0 else 0
                item_rate.rate_value = rate_value
            item_rate.save()
            logger.debug(
                f'updated item fanhao: {fanhao}, {"and correct the rate_value" if not is_correct else ""}')
    page = int(request.query.get('page', 1))
    like = int(request.query.get('like', 1))
    tag_type, tag_value = _get_tag_filter()
    url = f'/recommend{_build_query(page, like, tag_type, tag_value)}'
    if formid:
        url += f'#{formid}'
    return _safe_redirect(url)


@route('/model')
def other_settings():
    try:
        _, model_scores = clf.load()
    except FileNotFoundError:
        model_scores = None
    return template('model', path=request.path, model_scores=model_scores)


@route('/do-training')
def do_training():
    error_msg = None
    model_scores = None
    try:
        _, model_scores = clf.train()
    except ValueError as ex:
        logger.exception(ex)
        error_msg = ' '.join(ex.args)
    return template('model', path=request.path, model_scores=model_scores, error_msg=error_msg)


@route('/local_fanhao', method=['GET', 'POST'])
def update_local_fanhao():
    msg = ''
    if request.POST.submit:
        fanhao_list = request.POST.fanhao
        tag_like = request.POST.tag_like == '1'
        missed_fanhao, local_file_count, tag_file_count = add_local_fanhao(
            fanhao_list, tag_like)
        if len(missed_fanhao) > 0:
            urls = [bus_spider.get_url_by_fanhao(
                fanhao) for fanhao in missed_fanhao]
            add_download_job(urls)
            msg = f'上传 {len(missed_fanhao)} 个番号, {local_file_count} 个本地文件'
            if tag_like:
                msg += f', {tag_file_count} 个打标为喜欢'
    return template('local_fanhao', path=request.path, msg=msg)


@route('/local')
def local():
    page = int(request.query.get('page', 1))
    tag_type, tag_value = _get_tag_filter()
    items, page_info = get_local_items(
        page=page, tag_type=tag_type, tag_value=tag_value)
    for local_item in items:
        LocalItem.loadit(local_item)
        _remove_extra_tags(local_item.item)
    return template('local', items=items, page_info=page_info,
                    path=request.path, poster_src=poster_src,
                    **_list_template_args(None, tag_type, tag_value))


@route('/local_play/<id:int>')
def local_play(id):
    local_item = LocalItem.update_play(id)
    file_path = local_item.path
    logger.debug(file_path)
    redirect(file_path)


@route('/load_db', method=['GET', 'POST'])
def load_db():
    msg = ''
    errmsg = ''
    if request.POST.submit:
        upload = request.files.get('dbfile')
        if upload:
            logger.debug(upload.filename)
            name = get_data_path('uploaded.db')
            upload.save(name, overwrite=True)
            logger.debug(f'uploaded file saved to {name}')
            try:
                tag_file_added, missed_fanhaos = load_tags_db()
            except DBError:
                errmsg = '数据库文件错误, 请检查文件是否正确上传'
            else:
                urls = [bus_spider.get_url_by_fanhao(
                        fanhao) for fanhao in missed_fanhaos]
                add_download_job(urls)
                msg = f'上传 {tag_file_added} 条用户打标数据, {len(missed_fanhaos)} 个番号, '
                msg += '  注意: 需要下载其他数据才能开始建模, 请等候一定时间'
        else:
            errmsg = '请上传数据库文件'
    return template('load_db', path=request.path, msg=msg, errmsg=errmsg)


FANHAO_RE = _re.compile(r'[A-Za-z]{1,10}-\d{2,6}')


def _int_cfg(key, default):
    try:
        return int(APP_CONFIG.get(key, default))
    except (TypeError, ValueError):
        return default


def _current_layout():
    layout = APP_CONFIG.get('display.layout') or 'double'
    if layout not in ('single', 'double'):
        layout = 'double'
    return layout


def _save_config_section(section, values):
    path = get_data_path('config.ini')
    conf = configparser.ConfigParser()
    conf.read(path)
    if not conf.has_section(section):
        conf.add_section(section)
    for key, value in values.items():
        conf.set(section, key, str(value))
        APP_CONFIG[section + '.' + key] = str(value)
    tmp = path + '.tmp'
    with open(tmp, 'w') as fh:
        conf.write(fh)
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _save_download_config(values):
    _save_config_section('download', values)


def _apply_layout(layout):
    if layout not in ('single', 'double'):
        layout = 'double'
    _save_config_section('display', {'layout': layout})
    bottle.BaseTemplate.defaults['bustag_layout'] = layout
    response.set_cookie('bustag_layout', layout, path='/', max_age=86400 * 365)
    return layout


def _safe_back_url():
    nxt = request.query.get('next') or ''
    if nxt.startswith('/') and not nxt.startswith('//'):
        return nxt
    referer = request.get_header('Referer') or ''
    parsed = urlparse(referer)
    path = parsed.path or '/tagit'
    if not path.startswith('/') or path.startswith('//'):
        return '/tagit'
    if parsed.query:
        path = path + '?' + parsed.query
    return path


@hook('before_request')
def _inject_layout():
    layout = _current_layout()
    bottle.BaseTemplate.defaults['bustag_layout'] = layout


@route('/settings', method=['GET', 'POST'])
def settings():
    msg = ''
    errmsg = ''
    if request.POST.submit == 'layout':
        layout = 'double' if request.POST.layout == 'double' else 'single'
        _apply_layout(layout)
        msg = '显示布局已保存'
    elif request.POST.submit == 'crawler':
        values = {
            'count': max(1, min(100, int(request.POST.get('count') or 20))),
            'interval': max(3600, min(604800, int(request.POST.get('interval') or 43200))),
            'max_tasks': max(1, min(5, int(request.POST.get('max_tasks') or 1))),
            'delay': max(1, min(30, int(request.POST.get('delay') or 4))),
            'daily_limit': max(1, min(500, int(request.POST.get('daily_limit') or 40))),
        }
        _save_download_config(values)
        msg = '爬虫设置已保存，下一轮抓取生效'
    elif request.POST.submit == 'fetch':
        kind = request.POST.get('fetch_type') or 'fanhao'
        query = (request.POST.get('fetch_query') or '').strip()
        if not query:
            errmsg = '请输入番号、系列或演员'
        else:
            root = APP_CONFIG['download.root_path'].rstrip('/')
            urls = []
            if kind == 'fanhao':
                found = FANHAO_RE.findall(query.upper())
                urls = [bus_spider.get_url_by_fanhao(item) for item in found]
            elif kind == 'series':
                series = query.upper()
                matched = FANHAO_RE.match(series)
                if matched:
                    series = matched.group(0).split('-')[0]
                else:
                    series = _re.sub(r'[^A-Za-z0-9]+', '', series)
                urls = [root + '/search/' + series]
            else:
                urls = [root + '/search/' + query]
            if not urls:
                errmsg = '没有可抓取的地址'
            else:
                added = enqueue_front([make_item(url, 'custom', kind) for url in urls])
                msg = '已插入队列头部 %s 条' % added
    layout = _current_layout()
    return template('settings', path=request.path, msg=msg, errmsg=errmsg,
                    layout=layout, cfg={
                        'count': _int_cfg('download.count', 20),
                        'interval': _int_cfg('download.interval', 43200),
                        'max_tasks': _int_cfg('download.max_tasks', 1),
                        'delay': _int_cfg('download.delay', 4),
                        'daily_limit': _int_cfg('download.daily_limit', 40),
                    })


@route('/layout')
def switch_layout():
    mode = request.query.get('mode') or ''
    if mode not in ('single', 'double'):
        mode = 'single' if _current_layout() == 'double' else 'double'
    _apply_layout(mode)
    # Keep the redirect relative to the current origin.  An absolute Bottle
    # redirect can lose the public reverse-proxy port (for example :1023).
    response.status = 303
    response.set_header('Location', _safe_back_url())
    return ''


@route('/queue.json')
def queue_status():
    response.content_type = 'application/json; charset=utf-8'
    response.set_header('Cache-Control', 'no-store')
    return json.dumps(queue_snapshot(), ensure_ascii=False)


@route('/about')
def about():
    return template('about', path=request.path)


app = bottle.default_app()


def start_app():
    t = threading.Thread(target=start_scheduler)
    t.start()
    run(host='0.0.0.0', server='paste', port=8000, debug=True)
    # run(host='0.0.0.0', port=8000, debug=True, reloader=False)


if __name__ == "__main__":
    try:
        freeze_support()
        from bustag import __version__
        print(f"Bustag server starting: version: {__version__}\n\n")
        import bustag.model.classifier as clf
        from bustag.util import logger, get_cwd, get_now_time, get_data_path
        from bustag.spider.db import (get_items, get_local_items, RATE_TYPE, RATE_VALUE, ItemRate,
                                      Item, LocalItem, DBError, db as dbconn)
        from bustag.spider import db
        from bustag.app.schedule import start_scheduler, add_download_job
        from bustag.spider import bus_spider
        from bustag.app.local import add_local_fanhao, load_tags_db
        start_app()
    except Exception as e:
        print('system error')
        traceback.print_exc()
    finally:
        print("Press Enter to continue ...")
        input()
        os._exit(1)
