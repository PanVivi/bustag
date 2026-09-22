import sys
import asyncio
import re
from datetime import datetime, timedelta
from urllib.request import Request, urlopen
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.date import DateTrigger
from aspider import aspider
from aspider.routeing import get_router
from bustag.spider import bus_spider
from bustag.spider.db import Item
from bustag.util import logger, APP_CONFIG
from bustag.app.crawl_queue import (
    enqueue_front, enqueue_back, take_next, finish_current, make_item,
    is_item_url, snapshot)

scheduler = None
loop = None
FANHAO_RE = re.compile(r'/([A-Za-z]{1,10}-\d{2,6})(?:[\"\'/?#]|$)')


def download(loop, no_parse_links=False, urls=None):
    print('start download')
    sys.argv = sys.argv[:1]
    if not urls:
        logger.warning('no links to download')
        return
    count = APP_CONFIG['download.count']
    if no_parse_links:
        count = len(urls)
    extra_options = APP_CONFIG.get('options', {})
    options = {'no_parse_links': no_parse_links,
               'roots': urls, 'count': count,
               'max_tasks': int(APP_CONFIG.get('download.max_tasks', 1) or 1),
               'max_tries': 2}
    extra_options.update(options)
    aspider.download(loop, extra_options)
    try:
        import bustag.model.classifier as clf
        clf.recommend()
    except FileNotFoundError:
        print('还没有训练好的模型, 无法推荐')


def _cookie_header():
    path = '/app/data/javbus-cookies.txt'
    cookies = {'dv': '1', 'age': 'verified', 'existmag': 'all'}
    try:
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, value = line.split('=', 1)
                cookies[key.strip()] = value.strip()
    except (OSError, IOError):
        pass
    return '; '.join('%s=%s' % (key, cookies[key]) for key in cookies)


def _discover_new_fanhao(limit):
    root = APP_CONFIG['download.root_path']
    req = Request(root, headers={
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Cookie': _cookie_header(),
        'Referer': root,
        'Accept-Language': 'zh-CN,zh;q=0.9',
    })
    html = urlopen(req, timeout=25).read().decode('utf-8', 'replace')
    found = []
    seen = set()
    for match in FANHAO_RE.finditer(html):
        fanhao = match.group(1).upper()
        if fanhao in seen:
            continue
        seen.add(fanhao)
        if Item.get_by_fanhao(fanhao) is not None:
            continue
        found.append(fanhao)
        if len(found) >= limit:
            break
    return found


def enqueue_scheduled_batch():
    try:
        limit = int(APP_CONFIG.get('download.count') or 20)
    except (TypeError, ValueError):
        limit = 20
    try:
        fanhaos = _discover_new_fanhao(limit)
    except Exception as ex:
        logger.exception(ex)
        fanhaos = []
    items = [make_item(bus_spider.get_url_by_fanhao(item), 'scheduled', 'interval')
             for item in fanhaos]
    if not items:
        root = APP_CONFIG['download.root_path']
        items = [make_item(root, 'scheduled', 'interval')]
    added = enqueue_back(items)
    logger.warning('scheduled enqueue %s items', added)


async def _run_one(item):
    urls = (item['url'],)
    no_parse = is_item_url(item['url'])
    download(loop, no_parse, urls)
    router = get_router()
    try:
        await asyncio.wait_for(router.quit_event.wait(), timeout=900)
        finish_current('ok')
    except Exception as ex:
        logger.exception(ex)
        finish_current('fail', str(ex)[:200])


async def _worker():
    while True:
        item = take_next()
        if not item:
            await asyncio.sleep(1)
            continue
        logger.warning('queue run %s %s', item.get('kind'), item.get('label'))
        try:
            await _run_one(item)
        except Exception as ex:
            logger.exception(ex)
            finish_current('fail', str(ex)[:200])
        await asyncio.sleep(0.2)


def start_scheduler():
    global scheduler, loop
    interval = int(APP_CONFIG.get('download.interval', 1800))
    loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(event_loop=loop)
    t1 = datetime.now() + timedelta(seconds=2)
    scheduler.add_job(enqueue_scheduled_batch, trigger=DateTrigger(run_date=t1))
    scheduler.add_job(enqueue_scheduled_batch, trigger=IntervalTrigger(seconds=interval))
    scheduler.start()
    asyncio.set_event_loop(loop)
    loop.create_task(_worker())
    loop.run_forever()


def add_download_job(urls):
    items = [make_item(url, 'custom', 'manual') for url in urls or ()]
    enqueue_front(items)
