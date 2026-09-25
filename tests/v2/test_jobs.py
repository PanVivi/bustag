import threading
import time
from bustag.recommender.jobs import submit


def test_single_worker_and_expired_lease_recovery(store):
    started, release = threading.Event(), threading.Event()

    def operation(worker):
        started.set()
        release.wait(5)
    assert submit(store.path, 'test', operation)
    assert started.wait(3)
    assert not submit(store.path, 'duplicate', operation)
    release.set()
    for _ in range(100):
        if store.rows('SELECT state FROM v2_job')[0]['state'] == 'complete':
            break
        time.sleep(.01)
    assert store.rows('SELECT state FROM v2_job')[0]['state'] == 'complete'
    with store.transaction():
        store.conn.execute("UPDATE v2_job SET state='running',updated_at='2000-01-01'")
    done = threading.Event()
    assert submit(store.path, 'recovered', lambda worker: done.set())
    assert done.wait(3)
    for _ in range(100):
        if store.rows('SELECT state FROM v2_job')[0]['state'] == 'complete':
            break
        time.sleep(.01)
