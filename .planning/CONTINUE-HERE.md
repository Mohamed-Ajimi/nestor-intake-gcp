# CONTINUE HERE — handoff 2026-08-10

**Supersedes the 2026-08-06 handoff entirely.** That one's central warning — *"the engine on disk is
NOT the engine that is deployed"* — **has been discharged.** Everything is deployed. Do not re-apply
it.

Branch `master`, HEAD `96564b4`, tree clean. **798 commits ahead of `origin/master` — still never
pushed.**

---

## The one fact that shapes everything below

**Three services are live at tag `20260806-175613`, and NOT ONE RUN HAS EXECUTED ON THEM.**

Re-verified 2026-08-10: newest audit write anywhere in the bucket is still `2026-08-05T19:21:31Z`,
run prefix count still **9**. So the deploy is real, and **every change in it is unexercised**. The
language wiring, the report-size directive and the widened gate context have never once run in
production.

| service | revision (verified live 2026-08-10) |
|---|---|
| `tribunal-api` | `tribunal-api-20260806-175613-180706` |
| `tribunal-worker` | `tribunal-worker-20260806-175613-180925` |
| `nestor-api` | `nestor-api-00045-hdw` |

Digests were verified built==deployed at deploy time (`status.imageDigest`, never
`containers[0].image` — G-1). Worker env carries `NESTOR_TRIBUNAL_UNCAPPED` as its **only**
`NESTOR_TRIBUNAL_*`, so the new gate caps (**4000/4000**) and the validated Wave-4 config are the
code defaults that actually run.

---

## ⛔ READ THIS BEFORE RUNNING ANY gcloud COMMAND

**The active account had silently switched to `mohamed.ajimi@agiliz.com`** between 08-06 and 08-10.
Four accounts exist on this machine. **Nestor Pulse = `tools@dotto.be` /
`project-cb01b861-cb4a-438d-b9a`.**

```bash
gcloud config list --format="value(core.account,core.project)"   # BOTH, every time
gcloud config set account tools@dotto.be                          # if wrong
```

⚠ **AND THE NEW HALF OF THIS TRAP, which cost real confusion today:**
**`--format='value(...)'` renders a PERMISSION ERROR as an EMPTY STRING.** Three services and a whole
bucket listing came back blank and read exactly like *"the resources are gone"*. They were fine; the
identity was wrong. **When a `value()` read comes back empty, re-run it without `--format` before
believing it.**

---

## ⛔ THE NEXT MEASURED RUN IS A NEW BASELINE, NOT A COMPARISON

Two independent dimensions of comparability with `368ff3a0` are gone:

- **`260806-lvt`** changed the report's **shape** (language directive + client-chosen length now
  reach synthesis);
- **`260806-o96`** changed **which claims reach paid verification** (the gate now sees whole
  questions, not 120-char join keys).

**Say this out loud before anyone builds a comparison table.** The right frame for the next run is
*"does the new behaviour appear at all"*, not *"is it better than 368ff3a0"*.

### What to look for in that first run, in priority order

1. **Does the report come out in ONE named language?** The strong directive (*"Write EVERYTHING in
   {lang} and ONLY {lang} … Never mix languages"*) has **never fired in production**. Confirm the
   dispatch assignments now say *"Report all findings in Dutch."* rather than *"…in the language of
   the assignment above."* — readable straight from the audit bucket.
2. **Did the client's chosen report size take effect?** `368ff3a0` delivered **356,352 chars**
   against a form whose largest option offers *"approx. 10-20 pages"*. Expect materially shorter for
   a `compact`/`standard` intake — but it is a **target, not a cap** (see G-17).
3. **Did the gate see whole questions?** Pull one gate call and check the decision context is
   ~1165 chars of full sentences, not 576 chars of mid-word cuts.
4. Everything else.

---

## Where the phase stands

**Phase 15.8 is 14/15.** The only incomplete plan is `15.8-15`, and within it only **Task 3 — the
combined Phase-15\* browser UAT + operator sign-off.** It costs nothing and closes the phase.
`verify_chain` is GREEN on `368ff3a0`, so the Art. 12 hard-stop is clear.

---

## What shipped 2026-08-06 (all live, all unexercised)

| commit | |
|---|---|
| `74cdf94` `5e6425c` `70f9f11` | `260806-dn8` — report synthesis → `claude-opus-5`, caps 8192→20000, price row, G-10 |
| `39fec86` `1de2346` `911318c` | `260806-lvt` — intake report **language + size** wired through to synthesis |
| `85c3aa9` | `260806-o96` — the claim gate gets the **whole question**; both gate caps → 4000 |

Full narrative: **`.planning/SESSION-260806.md`**. Run evidence:
**`docs/tribunal-run-reports/run-20260805-368ff3a0-DISPATCH.md`** (all 19 dispatched sub-questions +
the gate context verbatim).

### Two off switches were found, not one

`260806-lvt` began as "wire the language through". While grounding it, `pipeline.py`'s zero-touch
path turned out to hardcode `report_spec=None`, so `_spec_directives` returned `""` on every seam run
and the `REPORT SHAPING (client-chosen — honor these)` block **the engine already knew how to emit**
reached zero prompts. The intake had asked *"Gewenste omvang van het rapport"* all along; the answer
died on that line.

---

## Open decisions — the ball is with the operator

| # | Decision | State |
|---|---|---|
| 1 | **Trigger the first run on the new code.** Nothing validates any of it until then | **OPEN** |
| 2 | **Task 3** browser UAT + sign-off — the only thing left in 15.8 | **OPEN** |
| 3 | **G-13** — should `brief_conflicts` be *researched* at all, or only *reported*? Its content had real value (the void-premise finding was the run's headline), so the fix is to reshape it into a question, not to suppress it | **NEEDS RULING** |
| 4 | Revoke `roles/logging.logWriter` on `nestor-run@` (granted 2026-08-06, accepted as reversible) | **OPEN** |
| 5 | Commit the § 15.2.k queue-check config (G-3) — **but see the cheaper canary method below** | **OPEN** |
| 6 | **Push 798 commits to `origin/master`** | **OPEN** |

---

## Gaps

**Closed since the last handoff:** G-10 (deployed) · **G-5** (answered by measurement, fixed,
deployed — the cap everyone suspected was innocent; `_LABEL_MAX_CHARS = 120` was the defect).

| id | Gap |
|---|---|
| **G-7** | **Deep research bills at exactly $0.00, so the `cost_usd IS NULL` guard no longer detects the floor. Highest priority — now the oldest open gap.** The Opus 5 price row did NOT fix it; it prevented a *new* instance of the same class |
| **G-12** | **19 members dispatched vs 15 winners recorded** (7+6+5+1). ⛔ **Measure before fixing** — `research_division.py` already logs the per-group member count at dispatch; read that first. Fixing before measuring risks correcting the right number |
| **G-13** | **A `brief_conflicts` entry was dispatched as a paid research sub-question**, cut mid-URL at exactly 600 chars (`_SUBQ_CHARS`). Needs decision 3 above |
| **G-14** | The `cross_cutting` flag is stamped on the winner dict and **never persisted**, so "were both cross-cutting slots filled" is permanently unmeasurable |
| **G-15** | **Group 1 sat at the 7-member cap with two near-duplicates.** Cheap fix: dedup *inside* the assembled group, where the cap actually binds — not a tighter global threshold |
| **G-16** | **`output_form` (Notion / PDF / other) is asked on the intake and read by nothing.** Same four touch points as the size wiring |
| **G-17** | **The report-length directive is a TARGET, NOT A CAP.** The real ceiling is the per-section token budget × one section per client question — that is what produced 356,352 chars. If reports still overshoot after the first run, this is the next lever |
| G-1 | `containers[0].image` is a mutable **TAG** — read `status.imageDigest`. Runbook digest-pin proofs still flagged, not edited |
| G-2 | `nestor-frontend` had **no** digest baseline; `nestor-api`'s was truncated to 8 hex chars |
| G-3 | § 15.2.k queue recipe still uncommitted — **but no longer the cheapest queue check** (see canary below) |
| G-4 | `DATABASE_URL_WORKER` parse — strip the query string BEFORE the last path segment (db is `nestor`) |
| G-6 | Discovery section has a quote but **0 URLs / 0 citations** → provenance FAIL |
| G-8 | `assignment_yield.cost_usd` NULL on all 12 → D-R8 unanswerable |
| G-9 | Source `resolution_status` 2% resolved; `unresolved_anchors` 1 → 19 |
| G-11 | `own` still listed in "Configured streams" though D-R5 removed it (0 rows dispatched) |
| — | **Refuted claims are unreadable** — deleted from `claim`, only orphaned verdicts survive |
| — | **Corroboration merge key is still normalised exact text.** V-01 failed with keys too GRANULAR (396→396); `368ff3a0` failed with keys too COARSE (241→4). Opposite errors, same zero merges |

---

## Three generalisations worth more than the specifics

- **When a cap is suspected, measure what reaches the CONSUMER, not the cap.** G-5's suspected cap
  had 52% headroom; a constant nobody listed as a suspect was the entire defect.
- **Which services a change touches is a MEASUREMENT WITH AN EXPIRY DATE, not a fact.** D-W5-16 said
  "two services"; it was right when written and wrong on 08-06. Re-derive from the diff **every**
  deploy — skipping `nestor-api` would have left the whole fix inert while reading as deployed.
- **When a truncated identifier reaches a reader, resolve it on the READ path instead of widening the
  identifier.** Second time this has paid off (G-10, then G-5). Widening an identity key renames
  every stored value.

---

## Standing cautions

**Reading a run — cheap and underused**
- ⭐ **The GCS audit bucket IS a read surface and the agent can read it.** `gcloud storage ls`/`cat`
  on `gs://…-nestor-audit/runs/<run_id>/`. **`request.query` is the FULL untruncated assignment.**
  Read-only, no Cloud Build, no spend. D-W5-18's "no read surface" is true of the **yield tables**
  and false of the **bucket**.
- ⚠ A `for f in $(gcloud storage ls …); do gcloud storage cat "$f" > out; done` loop **silently
  produced 0-byte files for 3 of 4**. Always `ls -la` after — a 0-byte blob reads like an empty
  audit record.
- ⚠ The 2000-char audit truncation in the `d6bb3aae` forensics applies to **`gemini-2.5-flash`**
  calls, NOT to deep-research dispatch payloads.
- ⭐ **`gcloud builds log <id>` WORKS and is not classifier-blocked** — that is how to read test
  counts when `builds submit` streams nothing because the config logs to Cloud Logging.
- **Judge the engine from the delivered report** (`output` row, `format='markdown'`) — not the claim
  table, not the logs.

**Spend safety**
- ⭐ **The always-on worker is its own canary.** At `minScale=1` polling every 2s, any claimable row
  would ALREADY have been claimed and would be writing audit blobs. So listing the audit bucket for
  the newest write answers *"is anything running or claimable"* **read-only, ~30s, no DB credential,
  no Cloud Build.** Used twice on the 08-06 deploy; cheaper and stronger than § 15.2.k.
- **`min-instances=0` does NOT stop a worker booting — the loop CLAIMS FIRST, SLEEPS LAST.**
- **The verification stage works. Do not touch it.**

**Tests + CI**
- **`tribunal/cloudbuild.test-engine.yaml`** — one single-quoted `bash -c '…'` block capped at
  10,000 chars. **No apostrophes anywhere inside it.** `EXPECTED_FILES` and the test path move in
  **one** edit; it is **44**.
- ⛔ **`test_synthesize_report.py` is NOT in the gate's `WANTED` list.** Tests written there never run
  in CI. **Extract the real 44-file list from the config; never trust a filename.**
- **Never pipe a build or test command through `tail`** — that returns the pipe's exit code.
- Local runner: `Nestor\.venv\Scripts\python.exe` (3.11.9). `pipeline.py` DOES import there.
  Full 44-file gate ~60s. **Docker absent.** The 6 `PYTEST_CURRENT_TEST` 32767-char errors are
  present at every commit and are not yours.
- A stdlib-only Python at `C:/Users/ajimimo/google-cloud-sdk/platform/bundledpython/python.exe`
  (3.14). ⛔ **Never use the `ast`-lift harness for name resolution — it manufactures missing names.**

**Code traps**
- ⚠ **THREE similarly-named caps exist**: `pipeline._GATE_DECISION_CONTEXT_CHARS` (4000) ·
  `gates._CONTEXT_MAX_CHARS` (4000) · `workshop._CONTEXT_MAX_CHARS` (2000, unrelated). **Grep by
  module, never by name.** The first two truncate the same string **in series** — raising one alone
  is inert, and a test now pins the relationship.
- ⚠ **`FieldRenderer` stores an `allow_text` radio as `{choice, text}`**, a plain radio as a bare
  string. `_first_nonempty` would `str()` the dict into its repr and report the answer as **unset**.
- **`_LABEL_MAX_CHARS = 120` is an IDENTITY key, not a size guard.** Never widen it. A parked note
  once called it "safe to remove"; that note was wrong.

**Ops**
- **Tenant binding is mandatory** for `run_event`, `assignment_yield`, `workshop_round_yield`:
  `SET LOCAL app.tenant_id` in the SAME transaction. An unbound query **RAISES** — do not read an
  error as an empty table.
- **`options.logging: CLOUD_LOGGING_ONLY`** is required for query output; the `logging.logWriter`
  grant alone is not enough.
- **`nestor-run@` holds `secretAccessor` at SECRET scope**, not project scope. A project-level check
  reads as a false negative.
- **`--set-secrets` in the deploy SCRIPTS is CORRECT** — they compose the full set on purpose.
  The `--update-secrets` rule governs hand-typed `gcloud run services update`.
- **`.planning/` is gitignored** (`.gitignore:32`) — new files need `git add -f`, and so does any
  path under it even when tracked.
- **Worktrees have failed here repeatedly.** For single-plan work, run sequentially on master.
- The agent HAS read-only gcloud; `add-iam-policy-binding` and `logging read` are blocked by the
  **Claude Code permission classifier**. The artifact-producing `builds submit` was blocked once and
  went through on retry after the operator said to proceed.

---

## Suggested next action

**Close 15.8 with Task 3 (free), then trigger one run.** Nothing about the three deployed changes is
validated until something executes — and the first run is a **new baseline**, so treat it as
"does the new behaviour appear", not "is it better".

Before triggering: re-check the queue with the canary method (30s, free), and **verify the gcloud
account** — it drifted once already.
