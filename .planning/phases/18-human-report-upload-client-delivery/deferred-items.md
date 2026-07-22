## Deferred (out of scope for 18-01)

- **ci_no_raw_db_access.sh flags `app/research/run_task.py:86` (`return get_engine()`)** —
  pre-existing at base commit ffb23c0 (last touched by 949463d, Phase 17 RUN-03). NOT caused by
  18-01. The bg-task driver legitimately fetches an engine; the guard's exclusion list does not
  name run_task.py. Either the CI config scopes the scan differently or this needs a guard
  exclusion. Do NOT fix under 18-01 (scope boundary). Flagged 2026-07-22.
