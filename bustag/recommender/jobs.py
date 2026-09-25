"""Single-worker background jobs with a cross-process SQLite lease."""
import threading
import datetime
import uuid

from .store import Store, now


def submit(path, kind, operation):
    store = Store(path)
    owner = uuid.uuid4().hex
    try:
        with store.transaction():
            store.conn.execute('CREATE TABLE IF NOT EXISTS v2_job(id INTEGER PRIMARY KEY CHECK(id=1), kind TEXT, state TEXT, updated_at TEXT, message TEXT)')
            store.conn.execute("INSERT OR IGNORE INTO v2_job VALUES (1,'','idle',?,'')", (now(),))
            expired = (datetime.datetime.utcnow() - datetime.timedelta(minutes=2)).isoformat()
            changed = store.conn.execute("UPDATE v2_job SET kind=?,state='running',updated_at=?,message='' WHERE id=1 AND (state!='running' OR updated_at<?)", (kind, now(), expired)).rowcount
            if changed:
                store.set_meta('job_owner', owner)
        if not changed:
            return False
    finally:
        store.close()

    def run():
        worker = Store(path)
        stop = threading.Event()

        def heartbeat():
            lease = Store(path)
            try:
                while not stop.wait(10):
                    with lease.transaction():
                        if lease.meta('job_owner') != owner:
                            return
                        lease.conn.execute('UPDATE v2_job SET updated_at=? WHERE id=1', (now(),))
            finally:
                lease.close()
        threading.Thread(target=heartbeat, daemon=True).start()
        state, message = 'complete', '完成'
        try:
            operation(worker)
        except Exception as error:
            state, message = 'failed', type(error).__name__ + '；旧数据/模型保留，请检查私有诊断'
        finally:
            stop.set()
            with worker.transaction():
                if worker.meta('job_owner') == owner:
                    worker.conn.execute('UPDATE v2_job SET state=?,updated_at=?,message=? WHERE id=1', (state, now(), message))
            worker.close()
    threading.Thread(target=run, daemon=True).start()
    return True
