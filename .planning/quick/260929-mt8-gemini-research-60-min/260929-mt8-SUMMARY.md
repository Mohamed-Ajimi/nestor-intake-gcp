---
quick_id: 260929-mt8
status: complete
commit: a5d0122
---
# Summary — Gemini deep research gets 60 minutes

- Code `a5d0122`: Gemini poll budget 60 min (env `NESTOR_GEMINI_DR_TIMEOUT_MIN`), gemini per-angle outer timeout 65 min
  (env `NESTOR_TRIBUNAL_GEMINI_TIMEOUT_S`). OpenAI and Claude unchanged (35 / 40 min).
- Tests: research suites 158 passed; full tribunal suite 204 failed / 24 errors = the known local-env baseline, 0 new; +2 tests.
- DEV: build `2bc8c7bd` → `tribunal-worker:a5d0122` `sha256:bd74d6c3…23ae`; idle gate `02056035` idle;
  `tribunal-worker-00019-gfd`, two `worker_started`, no errors. Env unchanged (ANGLE_CONCURRENCY 15, both 23.5 flags true).
- NOT on prod. Prod caveat: prod runs 4 research calls at a time, so 15 calls run in ~4 waves; with Gemini allowed 60 min a
  slow run can approach the 120-min run ceiling (NESTOR_WORKER_RUN_TIMEOUT_MINUTES). Raise it, or ship prod together with
  the 15-at-a-time concurrency.
- Not done: retry a status poll on a Google 5xx (today's 503 loss) — separate fix.
