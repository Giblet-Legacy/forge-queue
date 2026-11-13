# forge-queue

A tiny job queue built only on Python's standard library (`sqlite3`,
`time`, `uuid`, `os`, `argparse`), built and tested on a phone in Termux.

## The challenge

Set by Yura Holovatyy on LinkedIn:

> Stdlib only: a tiny job queue on sqlite3. Enqueue from one terminal,
> run a worker in another. Kill the worker halfway through a job and
> restart it. Nothing should run twice and nothing should get lost.

Test procedure:

1. Enqueue jobs from terminal A.
2. Run a worker in terminal B.
3. `kill -9` the worker halfway through a job.
4. Restart the worker.
5. Verify: every job completes, none is lost, and none is recorded twice.

## The trap

"Nothing should run twice" can't be fully guaranteed, and that's the point.

A worker can be killed at any point, including **after the work is done
but before `done` is committed**. No queue can tell "died before the
work" apart from "died after the work, before the commit". Real systems
(SQS, Kafka, Celery) promise *at-least-once delivery* plus
*effectively-once results*, never exactly-once execution.

There's a second, quieter trap: a worker that's slow rather than dead.
Its lease runs out, another worker reclaims the job, and both try to
mark it done.

## What we guarantee

| Guarantee | How |
|---|---|
| **No job is lost** | A claimed job is always either `done` or reclaimable once its lease runs out (10s). |
| **Each result is recorded exactly once** | The result row and `status='done'` commit in the same transaction. |
| **A late worker can't double-commit** | Fencing: finish only commits if `worker_id` and `locked_at` still match. Otherwise `ROLLBACK` and log `[LOST LEASE]`. |
| **Execution is at-least-once** | Stated honestly. Side effects outside the DB must be idempotent on `job_id`. |

## Design

```sql
CREATE TABLE jobs (
    id TEXT PRIMARY KEY, payload TEXT,
    status TEXT DEFAULT 'pending',
    worker_id TEXT, locked_at REAL
);
CREATE TABLE results (
    job_id TEXT PRIMARY KEY, output TEXT, completed_at REAL
);
```

Worker loop:

1. **Claim:** `BEGIN IMMEDIATE`, pick oldest `pending` or `running`
   with expired lease, set `running` + `worker_id` + `locked_at`, `COMMIT`.
2. **Work:** outside any transaction.
3. **Finish:** `BEGIN IMMEDIATE`, ```UPDATE ... SET status='done'
   WHERE id=? AND worker_id=? AND locked_at=?```. 1 row → insert
   result, `COMMIT`. 0 rows → `ROLLBACK` (lost lease).

## Kill test - 2026-11-13 on the S24

Tested on a Samsung S24 running Termux. No laptop.

Terminal A:
```bash
$ python3 fq.py --init
$ python3 fq.py --enqueue "Test 1"
$ python3 fq.py --enqueue "Test 2"
$ python3 fq.py --enqueue "Test 3"
```

Terminal B - slow worker, 30s per job:
```bash
$ FQ_WORK=30 python3 fq.py --worker w1
Worker w1:21684 started.
  [WORK] Test 1 947d1522
```

Terminal A - kill mid-work:
```bash
$ pkill -9 -f "fq.py --worker"
Killed
```

Terminal B - restart:
```bash
$ FQ_WORK=3 python3 fq.py --worker w1
Worker w1:NEWPID started.
  [WORK] Test 1 947d1522 (RECLAIMED)
  [DONE] Test 1 947d1522
  [WORK] Test 2 dd910a90
  [DONE] Test 2 dd910a90
  [WORK] Test 3 465b761d
  [DONE] Test 3 465b761d
```

Terminal A - verify:
```bash
$ python3 fq.py --status
done     3
jobs=3 results=3 done=3 mismatched=0
PASS
```

40 minutes from "start the clock" to PASS, on a phone.

## Status

- [x] Spec and design
- [x] Implementation (`fq.py`)
- [x] kill -9 test on device, with output logged here
- [ ] Lost-lease test (job time > timeout, two workers)

## Honest limits

- `LOCK_TIMEOUT` (10s) must exceed worst-case job time, or the
  reaper reclaims a still-working job. Fencing prevents double-commit
  but not double-work. Production would add lease heartbeat renewal.
- At-least-once execution. Effectively-once results. Never
  exactly-once.


---

## Build Provenance

This project was built under a strict timebox and hardware constraint. 

**The Challenge:**
> "Stdlib only: a tiny job queue on sqlite3. Enqueue from one terminal, run a worker in another. Kill the worker halfway through a job and restart it. Nothing should run twice and nothing should get lost. Sounds easy until you actually try it" 
> — Yura Holovatyy, LinkedIn

**The Constraints:**
- **Time:** 40 minutes from "start the clock" to `git push`.
- **Hardware:** Samsung S24 (Android).
- **Environment:** Termux (no laptop, no IDE).
- **Dependencies:** Python 3 Standard Library only (`sqlite3`, `uuid`, `time`, `argparse`, `os`).
- **Process:** Pair-programmed with an AI assistant via a chat interface.

The entire architecture — from the initial spec to the SQLite fencing tokens and the `kill -9` test — was designed and typed on a mobile phone keyboard.


