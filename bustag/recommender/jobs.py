"""Single-worker background jobs with a cross-process SQLite lease."""
import threading

from .store import Store, now


def submit(path, kind, operation):
    store = Store(path)
    try:
        with store.transaction():
            store.conn.execute('CREATE TABLE IF NOT EXISTS v2_job(id INTEGER PRIMARY KEY CHECK(id=1), kind TEXT, state TEXT, updated_at TEXT, message TEXT)')
            store.conn.execute("INSERT OR IGNORE INTO v2_job VALUES (1,'','idle',?,'')", (now(),))
            changed = store.conn.execute("UPDATE v2_job SET kind=?,state='running',updated_at=?,message='' WHERE id=1 AND state!='running'", (kind, now())).rowcount
        if not changed:
            return False
    finally:
        store.close()

    def run():
        worker = Store(path)
        state, message = 'complete', '完成'
        try:
            operation(worker)
        except Exception as error:
            state, message = 'failed', type(error).__name__ + '；旧数据/模型保留，请检查私有诊断'
        finally:
            with worker.transaction():
                worker.conn.execute('UPDATE v2_job SET state=?,updated_at=?,message=? WHERE id=1', (state, now(), message))
            worker.close()
    threading.Thread(target=run, daemon=True).start()
    return True
