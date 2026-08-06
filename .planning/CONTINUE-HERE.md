# CONTINUE HERE — session handoff 2026-08-06

Supersedes the 2026-07-29 handoff entirely. That one said *"no deploy and no live run until the
whole engine redesign is built."* **That condition has been met and discharged:** all five waves
were built, deployed at SHA `20260805-111647`, and **the ONE measuring run has happened**
(`368ff3a0`, 2026-08-05). Do not re-apply the old hold — it is spent.

Branch `master`, tree clean, HEAD `fd707b2`.
⚠️ **789 commits ahead of `origin/master` — nothing has ever been pushed.** Not urgent, but if this
machine dies the entire engine redesign goes with it. Decide whether to push.

---

## The two things to know before touching anything

**1. The engine on disk is NOT the engine that is deployed.**
Today's work (quick `260806-dn8`) moved report synthesis to `claude-opus-5`. It is committed and
locally green but **NOT built and NOT deployed**. The live revisions still run Gemini synthesis at
the 2026-08-05 SHA. Any claim about "what the engine does" must say *which* engine.

**2. That rebuild voids the digest baseline.** The Tribunal digests verified 2026-08-06 and
15.8-14's deploy record go stale the moment you rebuild. **All five 15.8 pre-flight gates must be
re-run before any subsequent measured run**, and the engine gate now expects **44 of 44** files
(was 43).

---

## Where the phase actually stands

**Phase 15.8 is 14/15.** The only incomplete plan is `15.8-15`, and within it only **Task 3 — the
combined Phase-15\* browser UAT + operator sign-off**. Tasks 1 and 2 are done: the run was
triggered, measured, and the V-01 comparison table is filled per wave.

`verify_chain` is **GREEN** on run `368ff3a0`'s own audit data (359 rows, 0 chain breaks, 0 seq
gaps, `gcs_uri` on every row), so the Art. 12 hard-stop is clear. Task 3 is the last thing blocking
phase closure.

### Run `368ff3a0` — the measurement, one line each
- 44.5 min (V-01: 65.1), `completed_degraded` (benign — 36 candidates clustered to 35;
  `verification_degraded: false`), `reclaim_count` 0, fresh `lukoil` intake.
- **$18.90 — A FLOOR, not a total.** See G-7.
- 128 verification verdicts reconcile three ways (DB rows = 128; `checked` 113 +
  `checked_incidentally` 15 = 128; the report's own Verification block says 128). The report
  narrates the run that actually happened.
- Certainty `null` = **0** (V-01 had 175, 44%). Facets **3, zero null** (V-01 fractured into 4 from
  a typo — D-V01-5 did not recur).
- Claims with no source **13 (5.4%)** vs V-01's **84 (21%)**.
- `comparison_id` NULL — positive finding: no second paid A/B run was spent.

Full narrative: `.planning/phases/15.8-*/15.8-SESSION-REPORT.md` (392 lines).
**`15.8-UAT.md` remains authoritative where the two differ.**

---

## What landed today — quick `260806-dn8`

Operator decision: synthesis → Opus 5, and uncap `_SECTION_MAX_TOKENS` + `_LABEL_MAX_CHARS`.
Scope changed twice during grounding; both changes were surfaced and operator-approved.

Commits `74cdf94` (model) · `5e6425c` (price row) · `70f9f11` (G-10) · `fd707b2` (docs).
Local suite **1809 → 1850 passed / 0 failed** (+41 = exactly the new `test_synthesis_opus5.py`).
Nine files, +971/−88.

### ⛔ The trap worth carrying forward: max_tokens is bounded by the SDK, not the model

`anthropic 0.104.1` `_base_client.py:731` raises
`ValueError: Streaming is required for operations that may take longer than 10 minutes`
when `3600 * max_tokens / 128_000 > 600` → **last passing value is 21333**, not the model's 128K.

Gated at `messages.py:984` on three conditions, **all true in production**: non-streaming · no
`timeout` kwarg · `self._client.timeout == DEFAULT_TIMEOUT` — and `build_audited_client`
(`audited_llm_client.py:2043`) builds a bare `AsyncAnthropic()`. `claude-opus-5` is **absent** from
`MODEL_NONSTREAMING_TOKENS` (a per-model dict), so only the time clause applies.

**Raising the caps to 64000 "for headroom" would have thrown on EVERY synthesis call** and taken
down the whole report stage — worse than the truncation being fixed. Both caps are `20_000` under a
named `_ANTHROPIC_NONSTREAMING_MAX_TOKENS = 21_333`. If more is ever needed the escape is
**streaming** (lifts to 128K) — but `anthropic_messages` is non-streaming by construction and reads
`resp.usage` for the audit row, so that is a real change, not a flag flip.

### `_LABEL_MAX_CHARS` was NOT widened — and the note calling it safe was wrong

The parked memory called it *"safe to remove"*. Its own comment (`workshop.py:166`) calls it
*"a dict key and the join key plan 15.2-11's D4 superset assertion compares on"*; it also keys
`_propagate_stakes` facets, `_gate_decision_context`, and `assignment_identity.client_question`.
Operator picked the **CR-08 pattern** instead — which needed no new plumbing at all, because
`focus_areas[*].research_prompt` **already carried the full untruncated question**.
`_LABEL_MAX_CHARS` is byte-identical, as are `_GATE_DECISION_CONTEXT_CHARS`, `_QUESTION_MAX_CHARS`
and `_DECISION_MAX_CHARS`.

**Generalise: a parked note's "safe / not safe" verdicts decay faster than the code. Read the
constant's own comment before acting on a note about it — in this repo the load-bearing ones say
so in place.**

### Opus 5 API facts now baked into `steps.py`
- `temperature` / `top_p` / `top_k` / `budget_tokens` → **HTTP 400**. `temperature=0.2` was dropped,
  not ported. Do not "restore" it as a lost setting.
- **Thinking is ON by default** (unlike Opus 4.8/4.7) and bills as **output**.
- Read text by joining **every** `type == "text"` block — never `content[0]`; thinking blocks come
  first.
- **Check `stop_reason == "refusal"` BEFORE reading content** (HTTP 200, empty or partial body).
- Prompt-cache minimum is **512 tokens** on Opus 5 (1024 on Opus 4.8). Caching the repeated
  `reports_concatenated` block is the obvious cost lever and is **not** implemented; the price row's
  cache fields exist so it prices correctly the day it lands instead of silently.
- Cost: synthesis ~$1.04 → **~$4–7/run**.

### Judgment call already made
The section **prompt** now quotes the full question back to the model (`"{title}"`), not only the
heading directive — so Opus 5 sees the untruncated question while writing. Arguably the larger
quality effect of the change. One line, trivially revertible.

---

## Open decisions — the ball is with the operator

| # | Decision | State |
|---|---|---|
| 1 | **Deploy timing** — rebuild + 5 pre-flight gates now, or after the browser UAT? | **OPEN** |
| 2 | **Task 3** — Phase-15\* browser UAT + sign-off; the only thing left in 15.8 | **OPEN** |
| 3 | **`_GATE_DECISION_CONTEXT_CHARS = 1200`** — untouched by design; changing it changes which claims reach paid verification and **breaks comparability with `368ff3a0`**. Measure **G-5** first | **NEEDS RULING** |
| 4 | Revoke `roles/logging.logWriter` on `nestor-run@` (granted 2026-08-06, accepted as reversible) | **OPEN** |
| 5 | Commit the § 15.2.k queue-check config (runbook books it as *prose only*; scratchpad only so far) | **OPEN** |
| 6 | Push 789 commits to `origin/master` | **OPEN** |

---

## Gaps still open

**G-10 is CLOSED in code** (not yet deployed). The rest stand:

| id | Gap |
|---|---|
| **G-7** | **Deep research bills at exactly $0.00, so the `cost_usd IS NULL` guard no longer detects the floor. Highest priority.** ⚠️ Today's price row did **NOT** fix this — it prevented a *new* instance of the same class on the Opus 5 synthesis calls. G-7 itself is untouched. |
| **G-5** | Is the 1200-char gate decision context actually binding? **UNMEASURED** — the most interesting open measurement, and it gates decision 3 |
| G-1 | `containers[0].image` is a mutable **TAG**, not a digest — read `status.imageDigest` off the revision. Runbook digest-pin proofs (~2311, 2688) flagged, not edited |
| G-2 | `nestor-frontend` had **no** digest baseline; `nestor-api`'s was truncated to 8 hex chars |
| G-3 | § 15.2.k queue recipe materialised for the first time; scratchpad only |
| G-4 | `DATABASE_URL_WORKER` parse — strip the query string BEFORE the last path segment (db is `nestor`) |
| G-6 | Discovery section has a quote but **0 URLs / 0 citations** → provenance FAIL |
| G-8 | `assignment_yield.cost_usd` NULL on all 12 → D-R8 unanswerable |
| G-9 | Source `resolution_status` 2% resolved; `unresolved_anchors` 1 → 19 |
| G-11 | `own` still listed in "Configured streams" though D-R5 removed it (0 rows dispatched) |
| — | **Refuted claims are unreadable** — deleted from `claim`, only orphaned verdicts survive |
| — | **Corroboration merge key is still normalised exact text** — the V-01 defect, unfixed. `_dedupe_claims` is why `both: 0` recurred |

---

## Carried forward — a real finding, deliberately not fixed

`_parse_distiller_response` calls `line.strip()` **before** splitting, so a leading empty facet
column is reachable via `<TAB>`/`|||`/`|` but a **real tab is eaten and every column shifts left**.
Found by running the parser, asserted as recorded behaviour with a named test, and left alone:
changing `line.strip()` would alter how every already-working tab response parses, including V-01's
43 and 143. It deserves its own decision, not a drive-by fix.

---

## Standing cautions

- **Judge the engine from the delivered report** (`output` row, `format='markdown'`) — not the claim
  table, not the logs.
- **The verification stage works. Do not touch it.**
- **`tribunal/cloudbuild.test-engine.yaml`** — its script is one single-quoted `bash -c '…'` block
  capped by Cloud Build at **10,000 chars** (~5,300 today). **No apostrophes anywhere inside it** —
  one closes the string and the build dies with exit 127. Cost a build once already. Its
  `EXPECTED_FILES` and the test path must move in **one** edit; it is now **44**.
- **The agent HAS a working read-only gcloud session.** Plans asserting otherwise are wrong.
  `describe`/`list` work; `add-iam-policy-binding` and `logging read` are blocked by the **Claude
  Code permission classifier** — not GCP, not credentials.
- **Verify account AND project every time.** Four accounts on this machine; `auth login` has
  silently picked the wrong identity and overwritten a fix seconds later.
  Nestor Pulse = `tools@dotto.be` / `project-cb01b861-cb4a-438d-b9a`.
- **`options.logging: CLOUD_LOGGING_ONLY` is required** to see query output — the `logging.logWriter`
  grant alone is not enough. 15.8-14 used `NONE`, which is why its answers rode in exit status only.
- **The empty queue is POINT-IN-TIME.** `minScale = 1`; the worker polls every 2.0s and **claims
  before it sleeps**. Re-run the check immediately before any trigger — it is free (~50s).
- **`nestor-run@` holds `secretAccessor` at SECRET scope**, not project scope. A project-level check
  reads as a false negative.
- **Never pipe a build or test command through `tail`** — that returns the pipe's exit code, so a
  FAILED build reports 0.
- **Tenant binding is mandatory** for `run_event`, `assignment_yield`, `workshop_round_yield`:
  `SET LOCAL app.tenant_id` in the SAME transaction. An unbound query **RAISES** — do not read an
  error as an empty table.
- **`.planning/` is gitignored** (`.gitignore:32`). New files under it need `git add -f`;
  already-tracked ones (STATE.md, phase docs) are unaffected, which is why a naive check reads clean.
- **Worktrees have failed here repeatedly** — stale base 23×, CWD drift on merge, and (combined with
  the ignore rule above plus `commit_docs=false`) an executor that receives **no PLAN.md at all**.
  For single-plan work, run sequentially on master.
- **Local test runner:** `Nestor\.venv\Scripts\python.exe` (Python 3.11.9), versions matching
  `tribunal/requirements.txt` exactly. Full engine gate ~50s. **Docker is absent.** The 6 errors from
  the Windows `PYTEST_CURRENT_TEST` 32767-char limit are present at every commit and are not yours.
- **A stdlib-only Python** exists at
  `C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe` (3.14.4 — `ast`,
  `py_compile`, `json`; **no** pytest/sqlalchemy). Useful for lifting a pure function out and driving
  it. ⛔ **Never use the `ast`-lift harness for name resolution — it manufactures missing names.**
- **Parallel executors race STATE.md/ROADMAP.md.** Let them skip it and roll up centrally.

---

## Suggested next action

Close 15.8 first: **Task 3 browser UAT + sign-off** costs nothing and clears the phase. Then decide
deploy timing with a clean slate — the rebuild forces the five-gate re-run either way, and there is
no benefit to spending it while an unrelated UAT is still open.
