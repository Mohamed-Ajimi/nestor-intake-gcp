# CONTINUE HERE — handoff 2026-09-01

**Supersedes the 2026-08-10 handoff entirely.** Branch `master`, HEAD `300be1a`, tree clean apart
from untracked `.claude/`.

---

## The one fact that shapes everything below

**Everything on disk is deployed, and nothing has run on it.**

Six changes shipped across 2026-08-31 and 2026-09-01, in three deploys. The last one put two new
models into the engine. **No research run has executed since.** Every cost and quality number in this
file is arithmetic or replay — not observation.

The next real run is the first evidence. It costs ~$29, so it is a deliberate spend.

---

## Live state (all digest-proven)

| Service | Revision | Tag |
|---|---|---|
| `nestor-frontend` | `00035-zz2` | `20260901-…`/`20260831-160956` |
| `nestor-api` | `00047-ghp` | `20260831-124920` |
| `tribunal-api` | **`00023-bc6`** | `20260901-134253` |
| `tribunal-worker` | **`00009-fkm`** | `20260901-134253` |

Audit bucket: **10 run prefixes**, newest write `2026-08-31T08:43:24Z`. No run triggered by any deploy.

---

## What changed in the engine, and what deliberately did not

| Stage | Now runs |
|---|---|
| Skeptic, intake, workshop, grouping, evolve, admission | **`claude-sonnet-5`** ($2/$10) |
| Gates, grouping, report planner, rank, admission, evolve-meta | **`gemini-3.7-flash`** |
| **Claim distiller** | **`gemini-2.5-flash` — LEFT ON PURPOSE** |
| **`claude` deep-research stream** (`tools/claude_adapter.py`) | **`claude-sonnet-4-6` — LEFT ON PURPOSE** |

⛔ **Do not "finish the job" on either exception.**

- The **distiller** contributed ZERO of the 267 replayed prompts (it is the D-14 fallback; every
  stream returned its own fact list), and it feeds `_split_distiller_line` — the parser behind the
  V-01 incident where **278 well-formed claims were all dropped** because the model emitted the
  literal string `<TAB>`. `test_factlist_fallback.py:1739` pins the literal as a guard.
- The **claude DR adapter** drives every `low`-stakes angle plus the high-stakes redundancy copy.
  Moving it changes research OUTPUT, not just cost. Because it is unchanged, the UI label at
  `pipeline.py:4762` (`"Claude claude-sonnet-4-6 +web"`) is still TRUE — do not "fix" it.

---

## ⛔ WHAT THE NEXT RUN MUST CHECK

Projected total ≈ **$29** (was $27.79): −$2.62 from Sonnet 5, +$1.50 from Gemini 3.7.

1. **Is the rejected register EMPTY?** `workshop_rank.py:190` warns that thinking produces "a critic
   that rejects nothing". Replay measured the *opposite* (3.7 gave 6 KILLs where 2.5 gave 0), but
   3.7 **ignores `thinkingBudget=0` on real prompts**. If the register comes back empty, revert the
   Flash change — that is the failure the warning describes.
2. **`report_planner`** has the tightest ceiling (`_MAX_OUTPUT_TOKENS = 1536`) while 3.7 spends output
   on reasoning it will not disable. Truncated plans show there first.
3. **Cost.** If it lands far from $29 the token assumptions were wrong.
4. **Do the deep-research calls still write GCS audit blobs?** Run `3d29c936` (intake-side id;
   tribunal id `fb9484dd`) wrote 444 objects — confirm that still happens.

---

## Cost: what is known, and the three gaps

Full detail in the `run-cost-anatomy-and-gaps` memory. Headlines:

- **The skeptic stage is 79% of run cost**, and cost is **linear in claim-group count, ~$0.11/group**
  (73 groups → $8.49 … 178 groups → $35.44). Volume elsewhere is irrelevant: 267 Gemini Flash calls
  cost $0.22 while 4 Opus calls cost $4.51.
- ⛔ **Prompt caching is NOT waste.** It saved 14–30% in all six runs. A ~1:1 create/read ratio looks
  like a leak and is the BEST observed. Never infer waste from a ratio without pricing the alternative.
- **The $25 budget governor has never fired** — `NESTOR_TRIBUNAL_UNCAPPED=1` (Phase 13 decision D-07)
  makes `over_budget()` return `False` before it queries. **2 of 6 runs exceeded $25.** Operator
  ruling 2026-09-01: **leave it uncapped**; surface cost on the run page instead.

**Three gaps — any "run cost" figure is incomplete:**

1. The **9 deep-research angles are unpriced** (they return `{status, report}` with no usage) — the
   most expensive calls contribute $0.00.
2. The **backend has a second, non-reconciling cost system**: `skill_runs.cost_estimate_usd` from a
   hardcoded `in*3 + out*15` legacy Sonnet rate, applied whatever model ran.
3. **Embeddings and Whisper are uncosted entirely.**

Plus: the UI section titled **"True itemized cost"** can only render a total — its payload is
`{cost_usd_total, cost_pending}`, and the total excludes the research calls.

---

## Open items, in the order I would take them

1. **Trigger a run** and check the four things above. Everything else is blocked on evidence.
2. **Earn the distiller evidence** — replay `test_distiller_separators.py`'s four recorded responses
   through 3.7 and check the separator format survives. Cheap, and it closes the last model gap.
3. **Build the real cost breakdown into the app** — the rows exist (`provider · model · tokens ·
   cost_usd`, one per call) at `GET /api/audit/runs/{run_id}/calls`. Group by provider/model behind
   that section so the "itemized" label stops lying.
4. **Price the deep-research calls** (gap 1), then point the backend at `cost_prices.json` (gap 2).
5. **RAG for research questions** — still waiting on the proposal from the last stakeholder meeting.
   This is the one item blocked on THEM, and it is the natural agenda for the workshop.

---

## Standing decisions taken this session

- **Budget stays uncapped.**
- **Do not add Perplexity as a 4th research stream.** Measured: its Agent API preset `high` returns
  `openai/gpt-5.6-sol` — the model `NESTOR_OPENAI_DR_MODEL` already runs. It would buy correlation,
  not coverage. Its citations are `[web:N]` markers with no raw URLs, so `_extract_urls` would
  silently extract nothing. (`perplexity/sonar` as a cheap replacement for the dropped `own` stream
  is still an open idea — 39 s, 11 cited URLs, $0.009, versus `own`'s 2 URLs per run.)
- **The context pack stays Dutch** (operator ruling 2026-08-31).
- A **stakeholder email** was drafted 2026-09-01 covering status, the cost-reporting gap, the pending
  RAG proposal, and a demo + workshop request once Yanick is back. Not yet sent.

---

## Traps confirmed again this session

- **A repo-root `grep -rn` is unsound.** `.claude/worktrees/agent-af281d695d9b34c35/` is an orphaned
  stale copy of the whole repo (not a registered worktree). Scope every gate to an explicit path with
  `-I --exclude-dir=__pycache__`. It made a correct deletion read as incomplete twice today.
- **A grep gate matches prose ABOUT the thing.** Two verify gates I wrote were unsatisfiable because
  the mandated explanatory comment quotes the string it forbids. Settle counts by **AST**.
- **The `>=3.12` floor is `backend/`'s only.** `tribunal/pyproject.toml` says `>=3.11` and the local
  interpreter is 3.11.9 — the engine suite DOES run locally. Read the pyproject of the package you
  are testing.
- **`gcloud builds submit` was NOT classifier-blocked** this session (it was on 2026-08-13).
- **The gcloud account drifts to `tools@epicimpact.be` mid-session** — pin `--account=tools@dotto.be`
  on every command.
- **The run id in the UI URL is not the tribunal run id.** `/admin/pulse/runs/3d29c936…` ↔ audit
  prefix `fb9484dd…`. Match by newest write time.
