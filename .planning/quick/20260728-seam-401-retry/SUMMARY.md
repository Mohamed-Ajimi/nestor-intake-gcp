---
quick_id: 260728-ftv
slug: seam-401-retry
date: 2026-07-28
status: complete
commit: 31a7f71
files_modified:
  - backend/app/research/run_task.py
  - backend/tests/test_research_run_task.py
---

# Quick task 260728-ftv — a transient seam 401/403 no longer finalizes a run as failed

> **Authorship note.** Written by the orchestrator from the executor's returned report. The
> executor's harness refused to create this file (the `Write` tool rejected it as a report file and
> the worktree Bash guard rejected the heredoc); it made one attempt each and stopped rather than
> route around a guard with `tee`, which was the right call. The code and tests in `31a7f71` are the
> executor's work.

## What shipped

`backend/app/research/run_task.py` — the poll driver's seam-error classification now retries
**exactly `401` and `403`** (`_METRICS_AUTH_RETRY_STATUS = frozenset({401, 403})`). Every other
`4xx` still reaches `raise` on first sight, so `400`/`404`/`409` remain fatal and genuine client
errors are not hidden.

## The budget decision, and why it is separate

**Separate budget: `_MAX_METRICS_AUTH_RETRIES = 200` × `POLL_SECONDS` 3.0s = 600s = 10 minutes.**

Sharing `_MAX_METRICS_5XX_RETRIES` (3) would have set auth tolerance to **9 seconds**, and the
incident's own numbers say that fails. The 401 was observed at 08:25:08 and the same seam answered
200 at 08:33:14 — **at least 8m06s**. That is a lower bound, not a measurement: the driver quit on
the first 401 and stopped sampling, so the true outage length is unknown.

A 9-second budget would have reintroduced the identical bug wearing a different number. The
asymmetry justifies erring long: a genuinely broken auth path costs 10 minutes of harmless GETs (the
engine runs whether or not the intake side watches), whereas too short costs the incident itself —
a `failed` badge over a run that is still spending money.

`_MAX_METRICS_AUTH_OUTAGE_SECONDS` is bound **at import** deliberately: `_fast_poll` collapses
`POLL_SECONDS` to `0.0`, so a lazily derived value would report "0s" under test and 600s in
production.

## Verification — Cloud Build `963eb505`, SUCCESS, `299 passed`

All five tests confirmed **by name** in the log, not inferred from the exit code. The count
reconciles: baseline 294 + 5 = 299.

| Test | Pins |
|---|---|
| `test_a_transient_401_is_retried_and_the_run_reaches_its_real_terminal` | the incident regression |
| `test_a_transient_403_behaves_exactly_like_the_401` | symmetry |
| `test_a_sustained_401_finalizes_failed_with_an_auth_specific_message` | exhaustion, message asserted by wording |
| `test_a_404_is_fatal_on_the_first_occurrence` | 1 seam call, `slept == []` |
| `test_the_5xx_budget_is_unchanged_by_the_auth_arm` | byte-exact message, 4 calls, 3 sleeps |

`test_a_404_is_fatal_on_the_first_occurrence` queues a **recovery entry behind the 404** — so if a
later reader widens the arm to all `4xx`, the run reaches `completed` and the test fails loudly
rather than passing by luck.

No `caplog` (D24-1: it captures nothing in `backend/tests`); the existing `warning_sink` logger
double was used. `_spy_sleep` counts `time.sleep` calls, because with `POLL_SECONDS=0.0` elapsed
time cannot distinguish "retried instantly" from "did not retry at all".

## Two deviations worth recording

**1. The "existing 5xx test" the plan told it not to break did not exist.** Searches for `5xx`,
`_MAX_METRICS_5XX_RETRIES`, `metrics 5xx` and poll-driver `HTTPStatusError` found nothing — that
path shipped **unpinned**. "5xx behaviour unchanged" would therefore have been an unverified claim,
so the executor wrote `test_the_5xx_budget_is_unchanged_by_the_auth_arm` from scratch and said so in
its docstring rather than letting the plan's assumption stand.

**2. The first edit severed a pre-existing test.** The append anchor was not end-of-file, which
orphaned the last assertion of `test_a_malformed_completed_at_falls_back_to_the_mirror_clock` onto
the new test, producing a `NameError`. Build `4da32159` caught it (1 failed / 298 passed); restored
and green. This is the "green proves nothing, confirm by name" discipline catching damage to a test
the executor never intended to touch.

## Still open, deliberately untouched

- **Nothing deployed.** This is `nestor-api` code and ships in the `backend` image. `tribunal-worker`
  is currently DELETED and run `d6bb3aae` is unresolved, so the redeploy is sequenced separately.
- `ci_no_raw_db_access.sh` remains red on the same single pre-existing `return get_engine()`
  (introduced by `f48ec06`, phase 16-02). It moved from line 211 to 247 — exactly the +36 lines added
  above it. Third independent confirmation that it is a stale-guard false positive, filed as D26-5.
