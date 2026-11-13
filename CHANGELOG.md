# CHANGELOG - forge-queue

## [v1.0.0] - 2026-11-13

### Good
- `fq.py` implemented in ~4KB, stdlib only.
- Kill test passed on an S24 phone in Termux. End-to-end build
  time (spec to push): 40 minutes.
- 3 jobs enqueued, worker killed mid-work, restarted, all 3 reclaimed
  and completed exactly once. `jobs=3 results=3 done=3 mismatched=0`.
- Atomic claim via `BEGIN IMMEDIATE`, work outside lock, atomic
  finish with three-condition fencing (id + worker_id + locked_at).
- Every transaction in `try/except BaseException` with `ROLLBACK` -
  even KeyboardInterrupt leaves the connection clean.
- `flush=True` on every print so kill testing is observable.
- `worker_id = name:pid` - restarted worker is provably different.
- `INSERT` (not `OR IGNORE`) on results - surfaces bugs.

### Bad
- `LOCK_TIMEOUT` fixed at 10s. Long-running jobs (>10s) get
  reclaimed by a second worker while the first is still running.
  Fencing prevents double-commit but not double-work. Production
  needs lease heartbeat.
- Exactly-once execution is not guaranteed and cannot be. Honest
  claim: at-least-once delivery, effectively-once results.

### Ugly
- First kill test failed: 3-second work finished before `pkill -9`
  landed. Added `FQ_WORK` env var to stretch work for testing.
- `--sleep` flag was the obvious fix but the argparse patch got
  eaten by the terminal buffer twice. `FQ_WORK` env var shipped
  in one line. Choose boring solutions.
- README paste got killed by the buffer twice; kill test PASSED but
  took a third attempt to record. Lesson: write docs in small chunks,
  or via Python with chr(96) for fences.
- First CHANGELOG draft said "24 minutes" because that was the time at
  which the kill test PASSED. It took another ~16 minutes to write the
  docs, fix the buffer-broken files, and push. Corrected to 40 minutes
  before pushing. The "faster" number was flattering but wrong; the
  git timestamps would have caught it.
