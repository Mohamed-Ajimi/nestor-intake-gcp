# 21-DENSITY-AUDIT — the per-site keep/cut verdict for the deep-research feed

**Measured:** 2026-08-10
**Tree:** `eac6f2b` (the density target is unchanged since `30443e8`)
**Target:** `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py`
**Why this document exists:** D-12 [OPERATOR] — *diagnose before trimming*. The operator declined
an immediate aggressive trim and asked for a specific list of what is noise versus signal first.
This is that list. No source file was changed to produce it.

---

## 1. What was measured, and how

Site inventory re-derived with the command named in the plan, not taken from any table:

```
grep -n "run_events.emit_safe" -A 4 tribunal/nestor_pulse_sdk/audit/audited_llm_client.py
```

| measurement | value |
|---|---|
| `run_events.emit_safe` sites in `audited_llm_client.py` | **13** |
| of those, carrying `stage="deep_research"` | **13 (all of them)** |
| `kind="thinking"` | **8** — lines 1408, 1436, 1495, 1594, 1710, 1824, 1866, 1942 |
| `kind="agent_fail"` | **5** — lines 1569, 1622, 1911, 1925, 1969 |
| any other kind | **0** |
| `build=lambda` thunks | **13** — parity with `emit_safe` holds at baseline |
| `_POLL_EVENT_STRIDE` | `10`, env-overridable via `NESTOR_RUN_EVENT_POLL_STRIDE`, clamped to ≥1 (`audited_llm_client.py:113-115`) |
| poll defaults, both providers | `max_attempts=70`, `poll_interval=30` → a 35-minute ceiling (`:1334-1335`, `:1650-1651`) |

CI registration confirmed: `nestor_pulse_sdk/tests/test_own_researcher.py` is named in
`tribunal/cloudbuild.test-engine.yaml:498` and `EXPECTED_FILES=44` at `:534`. This plan adds no
test file, so 44 does not move.

**Where my count differs from the plan's table, my number wins and is flagged ⚠ below.** Three
divergences were found. Two of them change what the options cost.

---

## 2. The per-site table

D-13 class: `long-silence` / `money` / `guard` (the engine's own defensive machinery) /
`parser-defect` / `failure`. CI pins are the exact substrings asserted in
`test_own_researcher.py`.

| line | provider | what the line says | D-13 class | CI-pinned substrings | verdict |
|---|---|---|---|---|---|
| 1408 | google | a recorded job id was refused by the guard, so the angle is dispatched fresh and **paid for again** | money **AND** guard | `"refused"`, `"paid for again"` (`test_own_researcher.py:1392-1396`) | **KEEP-AS-IS** — ruled 2026-08-10, money wins |
| 1436 | google | rejoined the in-flight job — nothing charged twice; states the poll interval | money | `"Rejoined"`, `"job interaction_in_flight_42"`, `"charged twice"` (`:1368-1371`) | KEEP-AS-IS |
| 1495 | google | "Waiting on Google … A long silence here is the normal shape of this call." | long-silence | `text.startswith("Waiting on Google")` (`:1313`) | KEEP-AS-IS |
| 1569 | google | the provider reported the job `failed`/`error`/`cancelled`, with its reason | failure | none | KEEP-AS-IS |
| 1594 | google | the heartbeat — minutes elapsed, poll N of M, "THIS IS A WAIT, NOT A STALL" | long-silence | `startswith("Still waiting")`, `"5 min elapsed"`, `"poll 10 of 70"`, `"NOT A STALL"`, and the cardinality bound `2 <= len(thinking) <= 8` (`:1310-1322`) | KEEP-AS-IS |
| 1622 | google | gave up after the poll budget ran out — "not a crash" | failure | none | KEEP-AS-IS |
| 1710 | openai | the same response-id refusal, so the angle is **paid for again** | money **AND** guard | **none** ⚠ | **KEEP-AS-IS** — ruled 2026-08-10, money wins |
| 1824 | openai | rejoined the in-flight response — nothing charged twice | money | **none** ⚠ | KEEP-AS-IS |
| 1866 | openai | "Waiting on OpenAI … A long silence here is the normal shape of this call." | long-silence | **none** ⚠ | KEEP-AS-IS |
| 1911 | openai | the response reported `failed`/`cancelled`, with its reason | failure | none | KEEP-AS-IS |
| 1925 | openai | the response ended `incomplete` — "this angle contributes nothing" | failure | none | KEEP-AS-IS |
| 1942 | openai | the heartbeat, same wording contract as Google's | long-silence | **none** ⚠ | KEEP-AS-IS |
| 1969 | openai | gave up after the poll budget ran out — "not a crash" | failure | none | KEEP-AS-IS |

**1408 and 1710 were raised as NEEDS-RULING, deliberately — and have since been ruled.** D-13 says
CUT guard-refusal commentary and KEEP anything about money. Each of these two sentences is *both in
the same clause* — "refused by the job-id guard … so it is paid for again". D-13's rule as written
did not resolve which half governs, and resolving it by fiat is exactly what D-12 forbids.
**The operator ruled on 2026-08-10 that both are KEEP: where the money clause and the
guard-refusal clause collide, money is dominant.** See "Operator ruling" below — that is an
amendment to D-13, not an inference drawn here.

Zero of the eight `thinking` lines are parser-defect explanations. Zero are about the engine's
defensive machinery **alone**. The five `agent_fail` sites are exception-path by nature, but
`agent_fail` is a legitimate kind and a failure is precisely what a watcher wants to see.

### ⚠ Divergence 1 — FOUR sites are CI-pinned, not five

The plan states "five of the eight are pinned". Measured: **four** — 1408, 1436, 1495, 1594, all
on the **Google** path. `test_own_researcher.py` exercises `gemini_deep_research_raw` only.
`test_provider_resume.py` does call `openai_deep_research_raw` (`:296-355`) but never installs a
recorder, so it asserts nothing about feed-row text.

**Every OpenAI-side line in this file is unpinned and freely rewritable at zero test cost.** That
materially lowers the price of Option A, and it corrects Option D's premise — see Divergence 3.

### ⚠ Divergence 3 — the demotion is pre-paid at FOUR sites, not two

The plan says lines 1400-1405 and 1430-1435 already carry a matching `log.warning` beside their
emit. True, and the OpenAI path mirrors it: **1704-1708** sits beside site 1710 and **1817-1822**
sits beside site 1824. So D-14's demotion is already paid for at all four money sites, plus at
`agent_fail` sites 1569, 1622 and 1969. No new log call is needed at any of them.

---

## 3. The contradiction, stated plainly

**21-CONTEXT.md's premise for this file is contradicted by the measurement.**

That premise reads: *"most of its lines are exception-path commentary addressed to an engineer
rather than to a watcher."* The measurement says **eight of eight `thinking` lines are money or
long-silence — which are D-13's two KEEP classes.** The verbatim line 21-CONTEXT.md quotes as its
own evidence of noise ends with *"so it is paid for again"*: it is a money warning, which D-13
says to keep.

**Therefore, under D-13 as written, the correct trim of this file's `thinking` CONTENT is zero
cuts.**

Four of those lines are additionally pinned by a registered CI test whose own comment reads *"the
wording is the deliverable — this run was misread as a stall once"* (`test_own_researcher.py:1321`),
referring to the 2026-07-27 incident in which a 25-minute long poll was read as a hang and a paid
run was nearly re-executed from the start.

---

## 4. The volume finding

### ⚠ Divergence 2 — the multiplier is 8 calls, not 19

The plan's arithmetic multiplies by 19, "the sub-questions run `368ff3a0` dispatched". Re-derived
from `docs/tribunal-run-reports/run-20260805-368ff3a0-DISPATCH.md:6`, that is the wrong
multiplier. The report's own header reads **"4 groups × 3 providers = 12 angles"**, and the 19 is
the *member* count (7 + 6 + 5 + 1) **packed into** those angle queries — one deep-research call
carries a whole group's members, not one call per member.

Of the four peer streams (`degraded_parallel.py:101` — `gemini`, `claude`, `openai`, `own`), only
**gemini and openai** route through this file's emit sites. So the multiplier for
`audited_llm_client.py` is **4 groups × 2 deep-research providers = 8 calls**.

### The arithmetic

Per deep-research call, the `thinking` ceiling is:

- **1** "Waiting on …" line, emitted once before the poll begins.
- **≤ 7** heartbeats — `max_attempts=70` at `_POLL_EVENT_STRIDE=10` fires at polls 10, 20 … 70.
- rejoin/refusal lines fire **only on a resume**, which is the exception, not the run shape.

So **≤ 8 rows per call × 8 calls = 64 rows as a hard ceiling** for the whole deep-research phase.
A typical 20-25 minute completion uses 40-50 polls → 4-5 heartbeats → **roughly 40 rows**. A fast
angle contributes as few as 2.

**This is 24-64 rows, not "roughly a hundred".** The stride is already doing its job.

### The consequence

That number is not, on its own, a lot of rows for the longest phase of a 45-minute run. What made
it feel like a lot is that **deep_research was the only stage speaking at all** — 8 of 13 stages
emit nothing, so this file's 40-odd rows were ~100% of everything on the page, and the collapse
toggle above them (21-01) expanded to reveal nothing.

If the complaint is nonetheless volume, the lever is **cardinality** — one stage-level wait line
instead of one per angle — which is a different edit from shortening prose, in a different place,
with a different test impact (it moves the emit, and the pinned cardinality bound
`2 <= len(thinking) <= 8` has to be re-derived rather than deleted).

---

## 5. The three options, costed

### Option A — shorten in place

**Mechanism.** Rewrite all eight `thinking` lines as short phrases per D-13's *"the row is a 13px
monospace line in a feed, not a log entry"*, preserving every pinned substring verbatim on the
four Google sites. The four OpenAI sites are unpinned (Divergence 1) and can be rewritten freely.

**What breaks.** Nothing, if the pins survive. No test edit. Lowest risk of the three.

**What it does not fix.** It reduces CHARACTERS, not ROWS. Row count is unchanged at 24-64. If the
complaint was volume, this does not address it.

### Option B — collapse the cardinality

**Mechanism.** Emit the waiting line and the heartbeat **once for the deep-research stage** rather
than once per angle. Turns ~40 rows into a handful.

**What breaks.** A real engine change to where the emit lives, plus a matching edit to
`test_own_researcher.py`'s pinned assertions in the same commit — including re-deriving the
cardinality bound rather than deleting it. The emit currently lives inside two provider-specific
raw methods that share no coordinating scope, so "once per stage" needs a new owner for that state.

**What is lost.** Per-angle attribution — the operator can no longer see *which* angle is slow.
**What is gained.** The phase becomes readable at a glance.

⚠ Its premise is now weaker than when it was written: the measured driver is 8 calls, not 19, so
this buys back ~35 rows rather than ~90.

### Option C — no change to this file

**Mechanism.** Nothing is edited here. SC5 is satisfied by this audit: the diagnosis is that no cut
is warranted, recorded with its reasons so a later reader does not re-open it as an oversight.

**Why it is defensible.** All eight lines are KEEP-class under D-13's own rule; four are pinned as
deliverable wording tied to a real incident. The verbosity was plausibly **relative** — this was
the only stage saying anything while eight said nothing. Once 21-03, 21-05 and 21-06 give those
eight stages bodies, and 21-01 makes the collapse toggle actually collapse, deep_research stops
being the entire page without a single pinned string moving.

**What it costs.** One round trip if the operator re-runs and still finds the feed too noisy. It is
also the option most likely to look like inaction, which is why the reasoning is recorded here.

### Option D — A + C: shorten the guard-refusal pair only

**Mechanism.** Resolve the NEEDS-RULING pair (1408, 1710) by keeping the money clause and dropping
the guard mechanism to the `log.warning` that already sits beside each of them — D-14 is pre-paid
at both sites (Divergence 3). Leave every other line alone.

⚠ **This option's stated premise is wrong as written.** The plan describes 1408 and 1710 as "the
two unpinned guard-refusal lines". **Line 1408 IS pinned** — `"refused"` and `"paid for again"` are
both asserted at `test_own_researcher.py:1392-1396`. Only 1710 is unpinned. So Option D is either
(i) a one-line edit to 1710 with no test change, or (ii) a two-line edit that must keep both
pinned substrings in 1408 while dropping the guard clause around them — achievable, since "refused"
and "paid for again" can both survive a shorter sentence, but it is not free.

### Recommendation

**Option C** — because the measurement says the content is not noise (8 of 8 lines are D-13 KEEP
class), the volume is 24-64 rows rather than the ~100 assumed, and the other four plans in this
phase change what the operator is reacting to without touching a pinned string; re-reading the feed
after they land costs nothing and is the only way to tell whether any of this file was ever the
problem.

---

## Operator ruling

**Ruled: 2026-08-10.** Recorded verbatim from the operator's decision. This is a ruling, not an
inference drawn from the audit.

### (1) Option: `option-c` — no change to `audited_llm_client.py`

> The audit document IS the deliverable. The operator accepted your reasoning: the content is not
> noise by D-13's own rule, the real volume is roughly half what the plan assumed, and
> `deep_research` only read as overwhelming because it was the sole stage speaking while eight said
> nothing. Whether this file was ever the problem gets re-read after 21-01/21-03/21-05/21-06 land.

**Consequence:** no edit to `tribunal/nestor_pulse_sdk/audit/audited_llm_client.py` and no edit to
`tribunal/nestor_pulse_sdk/tests/test_own_researcher.py`. Nothing under `tribunal/` is modified by
plan 21-04. **This is a completed plan, not an abandoned one** — SC5 is satisfied by a diagnosis
the operator ruled on, which is what D-12 asked for.

**Re-read trigger:** the open question is not closed forever, it is *sequenced*. After 21-01
(collapse toggle actually collapses), 21-03, 21-05 and 21-06 (the eight silent stages get bodies)
land and one run executes, the feed is re-read. If `deep_research` still reads as too verbose then,
option-a and option-b remain available and this document holds their costing.

### (2) Classification of lines 1408 and 1710: both KEEP — money wins

> Where D-13's money clause and its guard-refusal-commentary clause collide, the money clause is
> dominant. This is an operator amendment to D-13 resolving the contradiction in favour of KEEP.

**This amends D-13 [ASSISTANT — CORRECTABLE] and is now [OPERATOR].** D-13's keep/cut rule
previously left a sentence that is simultaneously guard commentary and a money statement
unresolved. It is resolved: **money is dominant; such a line is KEPT.** The rule now reads, in
effect — CUT guard-refusal commentary, parser-defect explanations, and lines about the engine's own
defensive machinery, *unless the same line also states a cost*, in which case it is KEPT.

Applies to both sites, on both providers, and to any future line of the same shape.

---

*Ruling recorded 2026-08-10. Task 3 executed under it as a documented no-op — see
`21-04-SUMMARY.md`.*

