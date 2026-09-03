# 16 — Operations runbook

| | |
|---|---|
| **Audience** | The operator (superadmin) and whoever is on call for a run |
| **Type** | How-to |
| **Source of truth** | `infra/DEPLOY-RUNBOOK.md` (the authoritative deploy procedure), `.planning/CONTINUE-HERE.md`, `.planning/phases/15.8-*/15.8-UAT.md` (the pre-flight gate set), `backend/app/api/research_routes.py`, `tribunal/nestor_pulse_sdk/runs/worker.py`, `tribunal/nestor_pulse_sdk/audit/*` |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

This chapter is the operator's view. It does not repeat the deploy procedure (chapter 13) or the
engine internals (chapters 09 and 10); it tells you what to do and what to expect at each moment
of a research run, how to read cost, and what the recurring incidents look like.

## 16.1 In one paragraph

A research run is a deliberate paid action: you trigger it from a `decomposed` intake, the engine
queues it, an always-on worker claims it within seconds, and for the next 30 to 70 minutes the run
page shows what the engine is doing. Long silences are normal. When it finishes, the verification
report tells you what was checked and what it cost, the raw bundle gives you the material for the
client PDF, and the Deliver act sends the client their report. Cost can be itemised from the audit
bucket without any database access.

## 16.2 Before any paid run: the pre-flight checklist

Every one of these is free, and each has caught a real problem at least once.

1. **Account and project.** Four Google accounts live on the operator machine and the gcloud
   configuration has silently switched mid-session more than once. Before any `gcloud` command:
   ```bash
   gcloud config get-value account   # must be tools@dotto.be
   gcloud config get-value project   # must be project-cb01b861-cb4a-438d-b9a
   ```
   Pin both on every command with `--account` and `--project` rather than trusting the config.
2. **The serving revisions are the ones you think.** Read `status.imageDigest` on each service's
   serving revision and compare with the deploy record in `infra/DEPLOY-RUNBOOK.md`. Revision
   *names* are not comparable; `containers[0].image` is a mutable tag.
3. **The queue is empty.** The worker claims first and sleeps last, so a queued run will start the
   moment a worker boots. The credential-free check is the audit bucket's newest write: if it is
   older than the last run you know about, nothing is running.
   ```bash
   BK=$(gcloud secrets versions access latest --secret=AUDIT_GCS_BUCKET --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a)
   gcloud storage ls -l gs://$BK/runs/ --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a
   ```
4. **Worker environment.** `NESTOR_TRIBUNAL_UNCAPPED=1` is expected (the budget governor is off by
   decision); `NESTOR_WORKER_STALE_MINUTES=60`; no `NESTOR_TRIBUNAL_WORKSHOP_*` overrides (the
   validated defaults must run). Read them from the revision, not from memory.
5. **Provider credit.** The Anthropic key in use must have headroom. On 2026-07-22 a monthly usage
   cap turned 776 skeptic calls into hard 400s in 55 seconds; the engine now trips a breaker and
   parks on that class of error, but a parked run still cost what it spent before the wall.

## 16.3 Triggering a run

1. Open the intake at `/admin/pulse/intakes/{id}`. The "Start research" action appears only in the
   `awaiting_research_start` phase (status `decomposed` with a context pack).
2. Read the banner: it names the three providers, says the run takes tens of minutes with silences
   of up to 35 minutes, and that it is a paid run not refunded on cancellation. There is deliberately
   no dollar figure in the UI (a quoted number rots into a false claim).
3. Confirm the dialog. The backend flips the intake to `in_research`, inserts a `research_runs`
   row with `attempt = n`, calls the engine (`ensure_org` → `ensure_project` → `create_run`), and
   starts a poll driver. The response is immediate (202).
4. Click **Open run** on the workflow card to go to `/admin/pulse/runs/{runId}`. That page is
   bookmarkable; note that login discards the destination, so bookmark it after signing in.

**What you cannot do:** trigger a second run on an intake whose latest run is `running`, `queued`
or `parked` (409); trigger a fourth attempt after three failures (the trigger returns
`needs_investigation` and does nothing); re-run a *completed* run (Phase 24, not built).

## 16.4 Reading the run page

The page has a status card, an actions block, a link to the verification report (once the run is
terminal) and the activity feed. The feed is grouped by stage; the current stage shows a live
cursor; finished stages collapse to their divider, summary and last two rows.

| You see | It means | Do |
|---|---|---|
| `queued`, no feed rows | The worker has not claimed it yet | Wait up to `NESTOR_WORKER_POLL_INTERVAL` (2 s) plus boot; if it stays queued for minutes, the worker is down |
| `workshop` rows: orientation, candidates, tournament rounds, winners | The question workshop is running (cents, about a minute) | Read the winners; they are what the money is spent on |
| `research_division` then `deep_research` dispatch rows, then silence | Three providers are researching in parallel. Each poll budget is 35 minutes per angle | **Do nothing.** The feed no longer narrates the wait (removed 2026-08-31 on operator request). Up to 35 minutes of silence is the normal shape |
| `agent_retry` rows | A transient provider error is being retried with backoff | Nothing; recovery is shown on purpose |
| `agent_fail` rows | An angle failed; the run continues if ≥2 of 3 providers succeed | Note it; the run will report `completed_degraded` with the reason |
| `distill`, `merge`, `gate` rows | Claims are being extracted, clustered and gated (cheap) | |
| `verify` rows, many of them | The group skeptic is running. **This is 79% of the cost** and scales at about $0.11 per claim group | Watch the cost figure in the header |
| `adjudicate`, `coverage`, `conflict`, `synthesize` | Verdicts applied, coverage re-entry, contradictions, report writing (Opus 5) | |
| `completed` | Done; chain verified; bundle written | Open the verification report |
| `completed_degraded` | Done, but the output fell short and every reason is listed on the card | Read the reasons before delivering |
| `parked` | A hard wall (credits, cap) stopped the run with its state preserved | Fix the cause, then **Resume** (free, does not count as an attempt); nobody else can resume it |
| `failed` | The run could not continue; the error is on the card | Read the error; **Retry** starts a fresh attempt (counts toward the cap of 3) |
| The chain block says **locked / broken** | `verify_chain` failed at completion; the download is blocked | **Re-verify** once; if still broken, investigate before anything leaves the system |

**Stopping a run.** The Stop button (only while the run is not terminal) opens a confirmation and
calls the engine's cancel. Spend already made is not refunded. Cancelling is not an attempt.

## 16.5 After the run

1. **Read the verification report** at `/admin/pulse/runs/{runId}/verification`: the stat strip
   (claims, verdicts, refuted, unverified, sources, cost), the gate funnel with business labels and
   tooltips, the verdict sections (refuted with their effect on the report, supported, insufficient,
   superseded, reconciled contradictions), the count of claims that shipped unverified, the citations
   list (collapsed) and the cost line. The section titled "True itemized cost" currently renders a
   total and a pending flag only (chapter 19).
2. **Download the raw bundle** from the run page once the chain reads verified: `report.md`, one
   `research/<name>.md` per provider report (with refuted passages already scrubbed), and
   `sources.json` (the claim → source trail). The rejected-claims ledger is deliberately not in it.
3. **Craft the client PDF** externally (Claude Design is the operator's tool of choice) from
   `report.md`. The generated report's `[n]` markers and snapshot panel exist to make this fast
   and safe; they are not the client's citation style.
4. **Stage and deliver.** On the intake page, upload the PDF (staging only, nothing is
   client-visible yet), then **Deliver**: pick recipients from the space's active members; the
   intake flips to `delivered` and the client gets a notification-only mail with a link to their
   report page. **Replace** is available afterwards, with or without re-notifying. Delivery is
   one-way in the UI.

## 16.6 Reading cost

### On the page

The run header shows `cost_usd_total` as the engine reports it. Treat it as a **floor**: the nine
deep-research calls carry no usage metadata and are priced at $0.00; a model missing from the price
table writes NULL; a failed angle emits no yield row. `cost_pending` means at least one row could
not be priced.

### From the audit bucket, without a database

Every LLM call writes one JSON blob named `{audit_id}_{provider}_{model}.json` under
`runs/{run_id}/`. The file names alone give the per-model call counts; each blob carries the usage
block (`response.usage` for Anthropic and OpenAI, `response.usage_metadata` for Google).

```bash
BK=$(gcloud secrets versions access latest --secret=AUDIT_GCS_BUCKET --account=tools@dotto.be --project=project-cb01b861-cb4a-438d-b9a)
gcloud storage ls gs://$BK/runs/                                   # find the prefix
gcloud storage cp -r "gs://$BK/runs/<RUN_ID>/*" "$SCRATCH/"        # ~58 MB for a 444-call run
```

Price the usage with the engine's own table, `tribunal/nestor_pulse_sdk/audit/cost_prices.json`,
through `cost_table.compute()` (it takes cached tokens positionally; verify any new price row through
the real function with a negative control that returns `None` for an invented model). Two traps:

- The run id in the UI URL (`/admin/pulse/runs/3d29c936…`) is the intake-side mirror id, not the
  engine run id (`fb9484dd…`). Match by newest write time.
- `request` bodies in the blobs are truncated at 2,000 characters. Fine for replay experiments,
  not the live prompt.

### What a run looks like

Run `fb9484dd` (2026-08-31), 444 calls, $27.79 recorded:

| Line | Cost | Share |
|---|---|---|
| Anthropic prompt-cache creation (3.99M tokens) | $14.98 | 55% |
| `claude-opus-5`, 4 synthesis calls | $4.51 | 17% |
| Anthropic web search, 301 calls | $3.01 | 11% |
| Sonnet completion, prompt and cache reads | $4.69 | 17% |
| `gemini-2.5-pro`, 2 calls | $0.36 | 1% |
| `gemini-2.5-flash`, 267 calls | $0.22 | <1% |
| The 9 deep-research angles | $0.00 recorded | unpriced |

Volume is not cost: 267 Flash calls cost 22 cents; 4 Opus calls cost $4.51. Across all six runs,
prompt caching **saved** 14–30% against sending the same tokens uncached; a create-to-read ratio
near 1:1 is the best observed, not a leak. Cost is linear in claim groups at roughly $0.11 each.

## 16.7 Incident playbook

| Symptom | Likely cause | What to do |
|---|---|---|
| The feed has been silent for 20+ minutes during `deep_research` | Normal: providers are polled for up to 35 minutes per angle | Nothing. On 2026-07-27 this silence was misread as a stall, cost an hour and nearly re-executed a paid run |
| A run started that nobody triggered, right after a deploy | A worker boot claimed a queued run (claims first, sleeps last) | Prevent: deploy the worker last, after proving the queue empty. Cure: Stop the run from the UI |
| A run re-executes itself every hour | The stale-run reclaim window is below the real run length | Confirm `NESTOR_WORKER_STALE_MINUTES=60` on the worker revision; the heartbeat liveness (Phase 15.2 gap plan) makes an active run un-reclaimable |
| Hundreds of failures in seconds, then `parked` | A provider hard wall (monthly cap, credits) | Top up or wait for the reset; then Resume from the run page. Do not retry: it would start a new attempt and re-spend the stages before the wall |
| `cost_pending` never clears | A model id has no price row, or a fee class is not itemised by the provider | Add the row (with the four token-class prices) and prove it through `compute()`; never a null-rate row, which prices as a confident $0.00 |
| The verification report shows a suspiciously round or low cost | The price table is stale (Flash output was 4× understated until 2026-09-01) or a NULL row was skipped by `SUM` | Reconcile against the provider console; a mismatch is a bug, not a rate to tune |
| Download locked, chain broken | An audit row or blob changed, or a frozen payload field was touched | Re-verify once; if still broken, treat as an incident. Nothing leaves the system on a broken chain |
| Intake AI skill returns Dutch for a French client | Fixed 2026-08-31 (three-language output); if seen again, check the deployed `nestor-api` revision | |
| Two runs from different clients interfere | The per-run advisory lock is missing | Should not occur since Phase 13; report it |

## 16.8 Deploying a fix (pointer)

The full procedure is chapter 13. The rules that matter most in the moment: pin account and
project; derive which services actually changed from the diff by import; build in Cloud Build;
deploy by image digest and prove it; run migrations and require the literal `Running upgrade`
line; worker last after an empty-queue check; never `--set-secrets` on a hand-typed deploy (it drops
bindings); use `--update-secrets`.

## 16.9 Standing operator rulings that constrain operations

| Ruling | Date | Effect on operations |
|---|---|---|
| Budget stays uncapped | 2026-07-20, reaffirmed 2026-09-01 | The $25 governor never fires; the question caps are the only spend control; two of six runs exceeded $25 |
| One combined browser UAT against a live run, not piecemeal | 2026-07-24 | UAT ledgers wait for a run |
| Nothing is measured until all changes are built | 2026-07-29 | One deploy, one measuring run; attribution of surprises to a single change is accepted as lost |
| The context pack stays Dutch | 2026-08-31 | Operators are Dutch speakers; the client report language is a separate, client-chosen field |
| No cost figure in UI copy | 2026-08-13 / 2026-08-31 | A quoted figure would be a fabricated fact; the banner says "tens of dollars" |
| Waiting lines removed from the feed | 2026-08-31 | Long silences are accepted and documented |
| `Nestor_Claude_Temp` rotation deferred to go-live | 2026-08-03 | A key that transited a chat is live on the engine services by decision; rotate at go-live |
| No Perplexity as a fourth stream | 2026-09-01 | It resells the OpenAI model already in use |

## 16.10 What to check on the next run (the open evidence)

The engine models deployed on 2026-09-01 have never executed a run. When one is triggered:

1. **Is the rejected register empty?** `workshop_rank.py` warns that thinking-enabled models can
   produce "a critic that rejects nothing". Replay measured the opposite for `gemini-3.7-flash`, but
   that model ignores `thinkingBudget=0` on real prompts. An empty register means the warning
   transferred: revert the Flash change.
2. **Are any report plans truncated?** The report planner has the tightest ceiling
   (`_MAX_OUTPUT_TOKENS = 1536`) while 3.7 spends output on reasoning.
3. **Cost near $29?** The projection is −$2.62 from Sonnet 5 and +$1.50 from Gemini 3.7 against
   $27.79. A figure far from it means the token assumptions were wrong.
4. **Did the deep-research calls still write audit blobs?** Run `fb9484dd` wrote 444 objects.

Everything else in chapter 19 is blocked on that evidence.
