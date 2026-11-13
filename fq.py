import sqlite3, time, uuid, argparse, os, sys

DB_PATH = os.environ.get("FQ_DB", "queue.db")
LOCK_TIMEOUT = 10.0
WORK_SECONDS = 3

def get_conn():
    conn = sqlite3.connect(DB_PATH, timeout=10.0, isolation_level=None)
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=FULL;")
    return conn

def init_db():
    conn = get_conn()
    conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
        id TEXT PRIMARY KEY, payload TEXT, status TEXT DEFAULT 'pending',
        worker_id TEXT, locked_at REAL)""")
    conn.execute("""CREATE TABLE IF NOT EXISTS results (
        job_id TEXT PRIMARY KEY, output TEXT, completed_at REAL)""")
    conn.close()

def enqueue(payload):
    conn = get_conn()
    job_id = str(uuid.uuid4())
    conn.execute("INSERT INTO jobs (id, payload) VALUES (?, ?)", (job_id, payload))
    conn.close()
    print(f"Enqueued: {job_id}")

def claim(conn, worker_id):
    conn.execute("BEGIN IMMEDIATE")
    try:
        now = time.time()
        row = conn.execute("""
            SELECT id, payload, status FROM jobs
            WHERE status='pending' OR (status='running' AND locked_at < ?)
            ORDER BY rowid LIMIT 1""", (now - LOCK_TIMEOUT,)).fetchone()
        if not row:
            conn.execute("COMMIT")
            return None
        conn.execute("UPDATE jobs SET status='running', locked_at=?, worker_id=? WHERE id=?",
                     (now, worker_id, row[0]))
        conn.execute("COMMIT")
        return row[0], row[1], row[2], now
    except BaseException:
        conn.execute("ROLLBACK")
        raise

def finish(conn, job_id, worker_id, lease, output):
    conn.execute("BEGIN IMMEDIATE")
    try:
        cur = conn.execute("""UPDATE jobs SET status='done'
            WHERE id=? AND status='running' AND worker_id=? AND locked_at=?""",
            (job_id, worker_id, lease))
        if cur.rowcount != 1:
            conn.execute("ROLLBACK")
            return False
        conn.execute("INSERT INTO results (job_id, output, completed_at) VALUES (?, ?, ?)",
                     (job_id, output, time.time()))
        conn.execute("COMMIT")
        return True
    except BaseException:
        conn.execute("ROLLBACK")
        raise

def worker(name):
    worker_id = f"{name}:{os.getpid()}"
    conn = get_conn()
    print(f"Worker {worker_id} started.", flush=True)
    while True:
        job = claim(conn, worker_id)
        if not job:
            time.sleep(1); continue
        job_id, payload, prev, lease = job
        tag = " (RECLAIMED)" if prev == "running" else ""
        print(f"  [WORK] {payload} {job_id[:8]}{tag}", flush=True)
        time.sleep(float(os.environ.get("FQ_WORK", WORK_SECONDS)))
        if finish(conn, job_id, worker_id, lease, f"Processed: {payload}"):
            print(f"  [DONE] {payload} {job_id[:8]}", flush=True)
        else:
            print(f"  [LOST LEASE] {payload} {job_id[:8]} - discarded", flush=True)

def status():
    conn = get_conn()
    for s, n in conn.execute("SELECT status, COUNT(*) FROM jobs GROUP BY status"):
        print(f"{s:8} {n}")
    total = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    res = conn.execute("SELECT COUNT(*) FROM results").fetchone()[0]
    orphan = conn.execute("SELECT COUNT(*) FROM results r LEFT JOIN jobs j ON j.id=r.job_id WHERE j.status IS NOT 'done'").fetchone()[0]
    done = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='done'").fetchone()[0]
    print(f"jobs={total} results={res} done={done} mismatched={orphan}")
    print("PASS" if res == done == total and orphan == 0 else "NOT YET / FAIL")

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--init", action="store_true")
    p.add_argument("--enqueue")
    p.add_argument("--worker")
    p.add_argument("--status", action="store_true")
    a = p.parse_args()
    if a.init: init_db(); print("Database initialized.")
    elif a.enqueue: enqueue(a.enqueue)
    elif a.worker:
        try: worker(a.worker)
        except KeyboardInterrupt: print("\nstopped")
    elif a.status: status()
    else: p.print_help()
