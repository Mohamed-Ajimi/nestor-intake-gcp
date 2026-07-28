---
quick_id: 260728-ftv
slug: seam-401-retry
date: 2026-07-28
type: execute
autonomous: true
files_modified:
  - backend/app/research/run_task.py
  - backend/tests/test_research_run_task.py
---

# Quick task 260728-ftv — a transient seam 401/403 must not finalize a run as failed

## The defect, with its live reproduction

`backend/app/research/run_task.py`'s poll driver classifies seam errors like this:

```python
except httpx.HTTPStatusError as exc:
    status_code = exc.response.status_code if exc.response else 0
    if status_code >= 500:
        consecutive_5xx += 1
        if consecutive_5xx > _MAX_METRICS_5XX_RETRIES:
            return (rid, {"status": "failed", ...}, None)
        time.sleep(POLL_SECONDS)
        continue
    raise  # a 4xx is a real error -> on_error finalizes failed
```

`5xx` is retried; **every** `4xx` is fatal. A `401` is a `4xx`.

**Observed live on 2026-07-28** during the 15.2 + 15.3 deploy:

| time (UTC) | event |
|---|---|
| 08:22:57 | `tribunal-worker` deploys, claims run `d6bb3aae`, engine starts executing |
| 08:23–08:24 | `tribunal-api` rolls out a new revision |
| 08:25:08 | `nestor-api` gets **401** on `GET /api/runs/{id}/metrics` -> run finalized `failed` |
| 08:33:14 | the same seam returns **200 OK** on `/api/runs/{id}/events` |
| 08:37:40 | engine writes its last heartbeat — it had been working the whole time |

No `401` ever reached `tribunal-api` (checked: zero `httpRequest.status=401` entries). Cloud Run
rejected it at the edge while traffic shifted between revisions. So the `401` was **transient
infrastructure**, not a client error.

**Why this matters beyond one incident:** as written, *any* deploy of `tribunal-api` while a run is
in flight marks that run `failed` in the operator's UI while the engine keeps spending money. That
is the dishonest-terminal-state class the D-12 work exists to prevent — the run was not failed.

## What to change

Extend the existing bounded-retry arm to cover **401 and 403 only**. `400`, `404`, `409` and every
other `4xx` MUST stay fatal — those are genuine client errors and retrying them would hide real bugs.

**Decide and state your reasoning on one point:** whether auth-shaped retries share
`_MAX_METRICS_5XX_RETRIES` or get their own budget. A revision rollout can take longer than a
typical `5xx` blip, so a shared counter may be too short. Whatever you choose, put the resulting
**maximum tolerated outage in wall-clock seconds** in a comment, so the next reader can tell whether
it covers a Cloud Run rollout without re-deriving `POLL_SECONDS x N`.

When the budget IS exhausted, finalize `failed` with a worded message naming the auth cause —
distinct from the existing `metrics 5xx after N retries` string, so the two are told apart in a
post-mortem.

## Tests (in `backend/tests/test_research_run_task.py`)

All must be `integration`-marked so they run in the committed `cloudbuild.test.yaml` gate.

1. A `401` that clears on retry -> the driver continues and the run reaches its real terminal
   state. **This is the regression test for the incident.**
2. A `403` behaves identically to the `401`.
3. `401` sustained past the budget -> finalized `failed`, with the auth-specific message asserted by
   its wording, not merely "some error".
4. **A `404` is still fatal on the FIRST occurrence** — no retry, no sleep. This is the guard that
   stops a later reader widening the arm to all `4xx`.
5. `5xx` behaviour is UNCHANGED — the existing test must still pass untouched.

## Constraints

- **No local Python or Docker.** Verify via
  `gcloud builds submit . --config=cloudbuild.test.yaml --project="$(gcloud config get-value project)"`.
  Confirm your new tests ran **by name** in the log; a green exit code alone proves nothing.
- `caplog` captures NOTHING in `backend/tests` (recorded as D24-1 during phase 15.2 — two
  independent capture routes were silent and no working counter-example exists in the suite). If you
  need to assert on a log line, use a logger double, not `caplog`, or you will write an assertion
  that cannot fail.
- Do not change the `5xx` path's behaviour or its message.
- Do not touch `tribunal_client.py`, the seam contract, or any Cloud Run configuration.
- This is `nestor-api` code — it ships in the `backend` image and will need a redeploy afterwards.
  Do NOT deploy: `tribunal-worker` is currently DELETED and run `d6bb3aae` is unresolved, so a
  deploy right now is unsafe and is being sequenced separately.

## Done when

- 401/403 retried within a stated, commented budget; 400/404/409 still fatal on first sight
- Five tests above green in a real Cloud Build run, confirmed by name
- The maximum tolerated outage is written down in seconds
- `git add -f` used for anything under `.planning/` (it is gitignored)
