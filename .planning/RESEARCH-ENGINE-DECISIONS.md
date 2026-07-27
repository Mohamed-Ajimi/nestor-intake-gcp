# Research engine redesign — brainstorm decisions

Running log of agreed decisions from the operator brainstorm (started 2026-07-24).
Plain language on purpose. One decision per line, dated when agreed.
Context: comparison with Replit deep-research + Google co-scientist, and the
run-4cbb5311 audit (docs/tribunal-run-reports/run-20260722-4cbb5311/).

## Area 1 — Who does the research

- **D1 (2026-07-24): Keep multiple research providers.** Their different coverage of
  the same question (observed in testing) is a feature, not a bug.

## Area 2 — The "question workshop" (new stage before dispatch)

- **D2 (2026-07-24): Build a question workshop stage before provider dispatch.**
  Steps: a few small real web searches (orientation) → generate many candidate
  sub-questions (30–50) → cluster near-duplicates → critique → **pairwise tournament**
  (co-scientist style: "which of these two questions matters more for THIS client's
  decision?") judged against the validated intake/context pack → evolve winners →
  final question list (10–15).
- **D3 (2026-07-24): Placement — the workshop consumes the context pack, it does not
  replace it.** Client answers → AI skills + operator + client validation → context
  pack + validated questions ALL STAY AS-IS (that's the client contract). The workshop
  replaces only the current one-call "adaptive intake" step at run start.
- **D4 (2026-07-24): The workshop can add depth but never change scope.** It may not
  drop, replace, or reinterpret client-validated questions. If its orientation
  searches contradict the brief (e.g. a law changed), it flags "brief assumes X,
  world says Y" — the flag travels into the report and the superadmin verification
  report. No silent rewrites.
- **D5 (2026-07-24): Fully automatic (option a).** No operator pause before dispatch;
  the chosen questions are visible live in the progress panel. Keeps the D-01
  no-pause-gates rule intact.

## Area 3 — Distribution across providers

- **D6 (2026-07-24): Distribute deliberately.** Different sub-questions go to
  different providers for coverage; the top few most important sub-questions go to
  ALL providers on purpose — agreement between providers = corroboration, difference
  = input for verification.

## Area 4 — Languages

- **D7 (2026-07-24): The workshop tags each sub-question with the languages worth
  searching in** (option a — automatic, per question, based on where the subject
  lives: German regulation → German+English, Russian company → Russian+English).
  Providers are instructed accordingly in their research prompts. Report output
  language stays single (from the intake) as today.

## Area 5 — What researchers hand back + how streams merge

- **D8 (2026-07-24): Every provider must end its report with a structured facts
  section** (each fact: source link, source quality, "certain" vs "found only once —
  double-check", plus a "couldn't find" list). That section is the primary claim
  source. A slimmed distiller stays as a per-provider safety net only: it compares
  the provider's essay against its own facts list and adds anything used in the
  story but missing from the list (option c). Claim CHECKING (skeptics) unchanged.
- **D9 (2026-07-24): Cross-provider merge step.** All facts from all streams get
  clustered ("same fact, said differently" — the canonical grouping already agreed
  for verification). Inside a cluster: all providers agree = corroboration, recorded
  on the claim, LOWERS its checking priority; found by one provider only = RAISES
  priority; providers contradict = the contradiction goes into ONE shared skeptic
  session that sees all variants (fix for Aral 16%-vs-21% / Zeeland shipping both
  versions). Note: clustering needs semantic matching — Phase 19's embeddings are
  the natural dependency.
- **D10 (2026-07-24): Add a fourth research stream: our own researcher agent fueled
  by SerpAPI** (role 2). It searches via SerpAPI, reads pages, and produces the same
  structured facts list as the others — fully transparent and metered. Deliberate
  new use inside Tribunal; does NOT resurrect the retired legacy run-research path
  (INTAKE-05 scope guard still stands).
- **D11 (2026-07-24): The verification gates apply AFTER the merge.** Funnel:
  collect facts lists → merge/cluster → materiality gate + stable-known-fact skip
  (agreed this morning in STAKEHOLDER-NOTES) → corroboration-based prioritization →
  skeptics run only on the short high-value list (~100–150 checks instead of ~950).

## Area 6 — What the superadmin sees during the run

- **D12 (2026-07-24): Live view at agent level WITH full drill-down (option b+c).**
  Inside each stage, one live row per working unit — each tournament round, each
  dispatched researcher ("Gemini — German regulation — searching — $0.42"), each
  skeptic check — with status and per-row cost ticking. The workshop's winning
  questions appear the moment they're chosen (fulfils D5's visibility promise).
  Clicking any row opens the actual prompts/answers, rendered from the audit
  records that are already written per call. Superadmin-only (D-08); the client
  user sees none of this. Complements the agreed post-run verification report.

## Area 7 — How the final report shows sources

- **D13 (2026-07-24): Numbered, graded, clickable citations (option c).** Every
  load-bearing statement carries [n]; the source list shows title, link,
  publication date, and quality tier (1 official / 2 serious press / 3 blog).
  Single-source statements are marked as such; verification-flagged outdated facts
  carry their temporal note inline. Clicking [n] in the app opens a source panel
  with title, date, tier AND our stored snapshot of the source text (survives dead
  links — snapshots already exist in the DB). Client-facing, so the quality bar is
  hard: numbering is GENERATED from the claim–source database, never left to the
  writing model (that is what produced last run's 28 stripped markers).

## Area 8 — Shape of the final report

- **D14 (2026-07-24): Keep the current skeleton + operator shaping step, add two
  sections (option b).** New: **"Disputed & changed"** (contradictions the skeptic
  settled with the winning source, facts that recently changed/are superseded,
  brief-vs-world flags from the workshop) and **"What we could not establish"**
  (merged from the researchers' "couldn't find" lists). Both sections are FED from
  pipeline data — the writing model presents them, it does not invent them. No
  fully-custom per-report structures: consistency across reports stays.

## Area 6b — The live view, made precise (sharpens D12)

- **D15 (2026-07-24): The live view is a chronological ACTIVITY FEED, Replit-style —
  not a status checklist.** Reference: `replit view.png` (repo root). The operator
  watches the engine work. Required elements:
  - **Agent cards appear the moment an agent is spun up**, each showing the task it
    was given (expandable to the full prompt, like Replit's subagent blocks).
  - **Per-agent live status**: spinner "working" → result line
    ("done · 14 facts · $0.12"). Never one anonymous stage bar.
  - **Narration lines** between blocks — one plain sentence about what the engine
    is doing/thinking next.
  - **A summary card after each work block**: "Worked for X · N actions ·
    M items read · $Y" — the professionalism signal.
  - **Collapse/expand everywhere** ("Show less"), calm by default, deep on demand;
    "scroll to latest" affordance.
  - **Errors shown as recovery, not hidden**: a card flips to "retry 2/3 —
    waiting 8s" and back to green. Reliability (R1–R6) becomes VISIBLE here.
  - After the run the feed stays, frozen and clickable (D12 drill-down) — a replay
    of what happened. Superadmin-only (D-08).

  Mockup agreed with operator:

  ```
  🧠 Analyzing the research brief
  ⚡ Question workshop started
     💭 "The brief assumes German prices change freely — checking..."
     🏆 Tournament round 3 of 4 — 18 questions remaining
     ✓ 12 winning questions chosen                    [show them ▾]

  ⚙ Worked for 1m 42s · 9 actions · $0.31

  🚀 Dispatching researchers
     ▸ Gemini — "German 12:00 pricing rule"     ⏳ searching (de+en)
     ▸ Claude — "ESL hardware costs"            ⏳ reading 3 sources
     ▸ Our agent — "competitor coffee prices"   ✓ done · 14 facts · $0.12
     ▸ OpenAI — "margin uplift benchmarks"      ⚠ retry 2/3 — waiting 8s…
       [Subagent task: Research margin uplift for fuel retailers...  ▾]

  ⚙ Worked for 6m 10s · 31 actions · 214 items read · $2.84
  ```

## Area 9 — Reliability & continuity (runs must finish; errors must retry)

Grounded in durable-execution / LLM-API best practices (sources in the 2026-07-24
session; see also docs/tribunal-run-reports/run-20260722-4cbb5311 for what went
wrong without these).

- **R1 (2026-07-24): Per-call retry policy.** Retry ONLY transient errors
  (429 / 500 / 502 / 503 / 504 / 529 / timeouts) with exponential backoff + jitter,
  honoring the provider's retry-after header. NEVER retry hard errors (the monthly
  usage-cap 400, auth errors). Max ~3–5 attempts.
- **R2 (2026-07-24): Circuit breaker per stage/provider.** A few consecutive
  IDENTICAL hard failures → stop dispatching that stage/provider immediately.
  (Last run: the cap should have been detected after ~5 failures, not sprayed 776×
  in one minute.) Plain 429s do not trip the breaker — they are retried instead.
- **R3 (2026-07-24): Checkpoint after every completed step — never pay twice.**
  Each stage/agent result is persisted as it completes (claims/sources/audit
  already are); a crash, restart, or wall resumes the run FROM THE CHECKPOINT,
  never from zero. Side effects (completion email) carry idempotency markers so a
  resumed run cannot repeat them.
- **R4 (2026-07-24): Park, don't die — and never fake-finish.** A hard wall
  (credits, monthly cap) parks the run: status "parked — waiting for X, will
  resume", operator notified, state fully preserved. No more manual DB cleanup of
  dead attempts; no more "completed green" with a gutted stage.
  *Open sub-decision: parked runs resume automatically when the wall lifts, or on
  a superadmin click — TBD.*
- **R5 (2026-07-24): Retries are visible in the feed** (see D15) — "retry 2/3 —
  waiting 8s" then green. Recovery in the open builds confidence; hidden errors
  destroy it.
- **R6 (2026-07-24): Every run ends in one of four honest terminal states:**
  `completed` / `completed-degraded` (finished, explicitly says what was skipped
  or partial) / `parked` (waiting, resumable) / `failed` (reason + one-click retry
  that resumes from checkpoint). Silent-green ceases to exist. Extends the
  fail-loud decision in STAKEHOLDER-NOTES.
- **R7 (2026-07-24): Use provider background/continuation modes where offered**
  (e.g. OpenAI deep-research background mode with continuation tokens) so a
  dropped connection cannot kill a 20-minute provider task — reconnect and resume.

## Area 10 — Cost transparency (every feed row shows a true number)

- **C1 (2026-07-24): Count every cost class.** The last run's panel said ~€5 vs
  ~$43–45 real. Fixes, verified against provider docs 2026-07-24:
  - **Anthropic calls**: count all four token classes — input, output, cache-READ,
    and cache-WRITE (cache-write is billed at a premium and is currently ignored:
    8.7M uncounted tokens ≈ $33 last run). Also price the per-search web_search /
    web_fetch tool fees (last run: 516 searches + 216 fetches).
  - **Gemini deep-research calls**: the API DOES return `usageMetadata` (input,
    output, thinking tokens — thinking bills at output rate); our adapter currently
    DROPS it (audit blobs store only status+report). Fix the adapter to record it.
  - **NO ESTIMATES — facts and correct calculations only (operator, 2026-07-24).**
    Every displayed number is computed from recorded usage × published prices:
    Anthropic tokens (all four classes) and Anthropic search/fetch fees (reported
    count × published per-search price) are exact and live; Gemini deep-research
    tokens are exact and live once the adapter records usageMetadata.
  - **Gemini search/grounding tool fees are not itemized live by Google** → the
    feed row shows "tool fees: pending". When the billing data (auto-labeled
    `is_deep_research`) lands, the EXACT amount is written back onto the run and
    the total updates. A run's cost is marked "final" only when nothing is
    pending. No placeholder or estimated numbers anywhere, ever.
  - **Reconciliation**: recorded totals are checked against provider invoices
    (Anthropic console, GCP billing per `is_deep_research`); any mismatch is a BUG
    to investigate, not a rate to tune.

---

Brainstorm completed 2026-07-24 — all areas decided (D1–D15, R1–R7, C1; one open
sub-decision under R4).
Related, agreed the same day in STAKEHOLDER-NOTES.md: the 7 verification-stage
changes + the superadmin-only post-run verification report.
Next step when ready: take this file + the STAKEHOLDER-NOTES entries into
/gsd-discuss-phase 15 (sequencing note: operator hold — engine work after
phases 18/19; no live runs before 2026-08-01 cap reset).

---

# Round 2 — OPEN QUESTIONS, raised 2026-07-27. NOT decided. For the next brainstorm.

Raised by the operator after reading the first live run (`d6bb3aae`, aborted) and the
workshop forensics. Nothing here is agreed; these are the four things to sit down with.
Each records what the code does TODAY, what the tension is, and what would settle it.

## Q1 — What is the tournament actually for?

**The operator's original intent, in their words (2026-07-27), because the rest of this
section is analysis and this is the actual goal:**

> "when we designed it the idea came from [Google Co-Scientist] and Foundational Context
> Agent to enrich these questions into ideas and angles the client didn't think of while
> also having their questions answered"

So the design target is **two things at once**: (a) answer what the client asked, and
(b) enrich those questions into ideas and angles they did not think of. Today's engine does
(a) only — see below. Q2 is where (b) actually lives.

**Today.** Three separate locks stop anything new entering the question pool:
the stage-A prompt ("deepening ONE client-validated question… never to change what is
being asked"), the evolve prompt ("Keep the SAME subject and the SAME scope… do NOT
broaden"), and the D4 scope guard (winners must be a superset of the client's question
labels). So every candidate is a narrower rewording of something the client already wrote.

**The tension.** D2 took the tournament from Google's Co-Scientist, where it applies
selection pressure across a large space of *novel generated hypotheses*. Ours ranks ~60
rewordings of ~11 things the client already said — and D4 then forces ~11 of the ~15
winners anyway. **At the operator's real question count the tournament only decides about
4 slots.** It has also never once run on valid input.

**What would settle it.** One clean run with real questions. Look at the ~4 discretionary
winners and ask: did the tournament choose better than "take them in order"? There is an
A/B switch already built for exactly this — `NESTOR_TRIBUNAL_WORKSHOP_TOURNAMENT=false`
ranks by index with zero calls. That is the baseline to measure against.

## Q2 — The "angles the client didn't think of" already exists, and has never worked

**Today.** The orientation step produces `brief_conflicts` — "the brief assumes X, the
world says Y", web-grounded, source-quoted, per question, with an explicit instruction not
to invent one. That IS the Foundational-Context-Agent behaviour the original design wanted.
It is NOT the tournament.

**The tension.** It has never reached a report. It was one of the two silent hand-off
losses plan 15.2-17 found and fixed on 2026-07-27 (`9c15c6e`) — the flags rendered as empty
strings and vanished. Fixed, but unproven.

**What would settle it.** Read the `brief_conflicts` on the next clean run. If they surface
things the operator would have missed, the novelty requirement is already met and Q1 becomes
purely a ranking question. If they are thin, then consider a second candidate population
(engine-proposed angles with NO client parent, capped at ~3 of 15, competing only for their
own quota). That path needs an operator gate before dispatch — D4's comment says why:
"A model asked nicely to respect scope is not a control: the candidate text it reads was
written by a model that had just read the open web."

## Q3 — Why cap questions at all?

**Today.** `_D6_MAX_WINNERS = 15`, `_MAX_ANGLES = 28`. The code is blunt about the reason:
"Every angle is a paid deep-research call and the budget governor is inert by decision
(`NESTOR_TRIBUNAL_UNCAPPED=1`), so the angle count is the only real spend control this
engine has left."

**The tension.** The caps are a proxy for a budget control that was deliberately switched
off. Tuning them is tuning spend, not research quality — and that is not obvious from
their names.

**What would settle it.** Decide whether to re-enable the budget governor (it was deferred
in 16-CONTEXT D-02, "uncapped for now", and Phase 20 is the latest it can slip). If it comes
back on, the winner/angle caps can be set for quality instead of doubling as the wallet.

## Q4 — Group questions per assignment instead of one-per-call, and "grouping needs to be smart"

**The operator's question, in their words (2026-07-27):**

> "why cap the questions and why run a deepresearch on one question, when we can group
> questions together, and grouping need to be smart"

**"Smart" is deliberately left OPEN here.** The grouping *criterion* is the actual open
question and must not be pre-decided — the assistant's first draft of this section collapsed
it to "group by client question" and presented that as the proposal, which is only one
candidate. Options worth weighing at the brainstorm, none chosen:

- **by client question** — one assignment per client question carrying its 3–6 sub-questions.
  Natural boundary, matches how the report is organised, attribution is trivially preserved.
- **by shared entity / subject** — e.g. every sub-question about coffee together, regardless
  of which client question spawned it. Maximises shared groundwork; attribution gets harder.
- **by shared source surface** — group questions likely to hit the same sources, which is
  where the duplicated searching actually lives.
- **by geography or time frame** — the D7 language tags already hint at this axis.
- **hybrid / model-decided** — let a cheap judge propose the grouping, with a cap and a
  scope assertion, the way the workshop already does for clustering.

Note the criteria pull in different directions: the cheapest grouping (shared sources) is not
the one with the cleanest attribution (client question). That trade-off is the decision.

**Today.** One sub-question per deep-research call, explicitly: "research ONLY this
sub-question; the sibling sub-questions are handled separately." At defaults, 15 winners
become ~24 angles — the top 3 go to all four streams, the rest to one each. The duplication
is the corroboration signal (`_D6_MIN_CORROBORATION = 2`): below two independent streams
`group_claims` has nothing to agree or disagree with, and the whole contradiction/skeptic
half of the engine goes quiet.

**The tension.** Fifteen angles about the same client each independently research the same
groundwork. That waste is invisible because it is spread across 15 paid calls.

**One worked example, to show the shape — NOT the chosen criterion.** Taking "by client
question": one assignment carrying that question's 3–6 sub-questions gives ~11 assignments
instead of ~24 angles. Attribution survives because the report is organised by client
question anyway; corroboration survives because the same GROUP goes to 2+ streams; shared
groundwork is searched once. Any of the other criteria above needs the same three things
checked — call count, attribution, corroboration — before it can be compared.

**The real risk, which nobody can predict from the code.** A provider given six
sub-questions may write one good report or six thin paragraphs. The current design's
"siblings handled separately" line exists to guard exactly that.

**What would settle it.** Two numbers off the next clean run: (a) how much of each angle's
searching duplicated a sibling angle's, and (b) how deep each answer actually was. If
duplication is high and depth is uniform, grouping is a clear win on both cost and quality.

**Naming trap for whoever implements it:** `grouping.py` already exists and groups CLAIMS
after research. This would be a different thing — grouping QUESTIONS before dispatch. Do
not overload the name.

---

**Sequencing agreed 2026-07-27:** none of Q1–Q4 blocks the gap phase. Ship plans 15.2-20..26,
get ONE clean run on real questions, then brainstorm these with that run's evidence in hand.
Redesigning now means designing against a run where 21 of 32 inputs were garbage.
