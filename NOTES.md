# NOTES - forge-queue

This document explains *why* the queue is built this way, and *what* we chose to guarantee (and what we chose not to).

## The illusion of exactly-once

Yura's challenge: *"Nothing should run twice."*

This is the classic distributed systems trap. You cannot guarantee exactly-once execution. If a worker is killed after it does the external side effect (e.g., sending an email, charging a card) but before it commits `done` to the database, the queue has no way of knowing whether the side effect happened. 

If we retry, the email sends twice.
If we don't retry, the job is lost.

Because we cannot solve this inside the queue, we choose the industry-standard alternative:

- **At-least-once delivery:** Every job will eventually be processed.
- **Effectively-once results:** The database state will only reflect the job as `done` exactly once.

We state this honestly in the README rather than pretending we solved an unsolvable problem.

## Design decisions

### 1. SQLite WAL mode
`PRAGMA journal_mode=WAL` allows multiple readers to read from the database while a writer is writing. Without WAL, two workers checking for jobs at the same time would block each other constantly. 

### 2. Atomic claims with `BEGIN IMMEDIATE`
When a worker wants a job, it cannot just `SELECT` then `UPDATE`. If it did, two workers could select the same pending job before either had a chance to update it.

We use `BEGIN IMMEDIATE` to grab the write lock. We select the job, update it to `running`, and `COMMIT` in a single, uninterruptible transaction.

### 3. Work happens *outside* the lock
We do not hold the database lock while the job is running. If we did, the entire queue would freeze for `FQ_WORK` seconds per job. We commit the claim (which contains the lease timestamp), release the lock, do the work, and then grab the lock again to finish.

### 4. Fencing tokens and the Reaper
If a worker is killed with `kill -9`, it leaves a job stuck in `running`. We use the `locked_at` timestamp as a **lease**. If a worker tries to claim a job and sees a `running` job whose lease is older than `LOCK_TIMEOUT` (10s), the Reaper reclaims it.

But what if the original worker wasn't actually dead, just slow? It might finish its work and try to mark it `done` *after* the Reaper gave it to someone else. 

We prevent this with **fencing**. The finish step is:
`UPDATE jobs SET status='done' WHERE id=? AND status='running' AND worker_id=? AND locked_at=?`

If the Reaper reassigned the job, the old worker's `locked_at` timestamp no longer matches the row, the `UPDATE` affects 0 rows, and the old worker rolls back.

### 5. `worker_id = name:pid`
If we just used `worker_id = "w1"`, and we killed worker `w1` and restarted it, the new worker would have the *same* ID as the old one. By appending the PID, `w1:19114` and `w1:21684` are provably different workers. This guarantees fencing works across restarts.

### 6. `try/except BaseException` for rollbacks
In Python, `KeyboardInterrupt` inherits from `BaseException`, not `Exception`. If the worker is stopped with `Ctrl+C` mid-transaction, catching `Exception` wouldn't roll it back. We catch `BaseException` to guarantee the connection is clean.

### 7. `flush=True` on print
When testing with `kill -9`, standard output is buffered. If the process dies instantly, the print buffer is lost, making it look like the worker never started. `flush=True` forces the output immediately, proving the work actually began before the kill.

### 8. `FQ_WORK` env var over CLI arguments
The simplest way to test a kill mid-work is to stretch the work duration. The "proper" way is to add `--sleep` to `argparse`. However, adding it required patching three different sections of the code, and the terminal buffer kept eating the paste. Setting `FQ_WORK=30` before invoking the script required exactly one line of change. Choose boring solutions under pressure.

## Honest limits (The "Bad")

- **Lease expiry:** If a job legitimately takes longer than `LOCK_TIMEOUT` (10s), the Reaper will reclaim it while the first worker is still working. Fencing prevents double-*commit*, but the work still runs twice.
- **The fix for v2:** Implement a heartbeat. While the job runs, a background thread updates `locked_at` every few seconds so the lease never expires.

- **Side effects:** The queue guarantees the database state, but it cannot guarantee external side effects. The caller must ensure external actions are idempotent.
