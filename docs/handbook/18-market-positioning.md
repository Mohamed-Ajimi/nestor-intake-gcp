# 18 — Market positioning, benefits and differences

| | |
|---|---|
| **Audience** | Stakeholders, sales, product; engineers who need the "why does this exist" |
| **Type** | Explanation |
| **Source of truth** | `.planning/research/FRONTIER-COMPARISON.md` (2026-07-20), `.planning/RESEARCH-ENGINE-DECISIONS.md`, `docs/BACKEND-MAP.md` (the legacy aggregator), the measured run reports under `docs/tribunal-run-reports/`, the Perplexity assessment of 2026-09-01 |
| **Last verified** | commit `c8b8583`, 2026-09-03 |

## 18.1 What the product is, in one paragraph

Nestor Pulse turns a client's strategic question into a **defensible, verified research report**.
A client fills a structured intake; an operator applies AI skills and reviews every suggestion; the
client validates the resulting research questions; the system condenses everything into a context
pack; the Tribunal engine then researches those questions across three independent deep-research
providers, extracts every factual claim, merges and gates them, tries to **refute** the ones that
matter through an adversarial skeptic with live web access, and writes a cited report plus a
superadmin-only verification report; the operator crafts the client deliverable from that material
and delivers it. Every AI call is sealed into a tamper-evident audit chain, every client's data is
isolated to its own space, and every cost class the system can count is counted exactly.

The product is therefore **not** a chat assistant and **not** a search aggregator. It is a
pipeline whose design centre is *claim survival and auditability*, wrapped in a human-gated intake
and delivery workflow.

## 18.2 The categories it is compared against

There are four things a buyer might reasonably compare Nestor Pulse with.

### 18.2.1 Off-the-shelf deep-research products (OpenAI Deep Research, Gemini Deep Research, Perplexity)

These are the **components** Nestor Pulse uses, not its competitors. Each produces one long,
single-vendor report from one prompt. Nestor Pulse:

- runs **all three** on every research group and treats their disagreement as signal (D6, D9);
- does not trust any of their claims until they have been extracted into a structured fact list
  (D8), merged across providers, gated for materiality, and — for the material ones — attacked by a
  skeptic that commissions its own evidence (`group_skeptic.py`);
- records what each provider *could not find* and surfaces it ("What we could not establish", D14);
- degrades honestly when a provider fails (≥2-of-3 succeed; `completed_degraded` names what was lost);
- writes the client-facing citations from its own claim→source database rather than from a model's
  memory of what it read (D13, D-05).

A single deep-research product gives you one model's essay. Nestor Pulse gives you the essay's
claims after they have been cross-examined, and tells you which ones did not survive.

**Perplexity, specifically**, was assessed with a live key on 2026-09-01. Its Agent API presets
resolve to OpenAI models (`high` → `openai/gpt-5.6-sol`, the same model the engine's OpenAI stream
already runs), its own deep-research model is not available on that API, and its answers cite with
`[web:N]` markers rather than URLs — which this engine's citation extractor would read as no sources
at all. Adding it as a fourth stream would buy correlation, not coverage, so it was ruled out. Its
cheap index (`perplexity/sonar`: 39 s, 11 cited URLs, $0.009 on a real question) remains a
plausible replacement for the dropped `own` breadth stream, which is a different role.

### 18.2.2 AI-scientist systems (Google co-scientist, OpenAI GPT-Rosalind, Anthropic Claude Science)

The frontier comparison of 2026-07-20 concluded that **none of these is a competitor**: they are
wet-lab and life-sciences accelerators optimising for hypothesis generation and experimental
throughput. Nestor Pulse optimises for adversarial claim survival in business and market research.
What the comparison *did* find was a handful of transferable mechanisms, and the roadmap adopted
them deliberately:

| Frontier mechanism | What Nestor Pulse did with it | Decision |
|---|---|---|
| Elo tournament ranking (co-scientist) | Adopted **at question level**: a Swiss-paired, Elo-scored pairwise tournament decides which sub-questions earn a paid research slot; judges must give a reason; ratings carry across rounds; newcomers get a catch-up schedule | D2, D-R9, D-W4-3 |
| Reflection / meta-review critique passes | Absorbed into the workshop: a critique stage (KEEP/WEAK/KILL) and a per-round meta-review feed the next generation round | S-02, D-R6 |
| Hypothesis evolution loop | Adopted in **bounded** form: generative evolve (combine/extend/invert/specialise/invent) inside a 10-round loop with saturation exit — but only after the discovery bracket gave it genuinely different ideas to rank | D-R6, D-R7, D-R10 |
| Proximity / diversity clustering | Declined; coverage is asserted deterministically in Python (`enforce_scope_guard`, `enforce_group_coverage`) | frontier verdict |
| Test-time compute self-play | Declined; it conflicts with cost governance and optimises a self-rated metric | frontier verdict |
| Domain tool/database ecosystems, rich artefact rendering | Irrelevant to market research; general web search/fetch is the right tool surface | frontier verdict |
| Draft tournament between competing reports | Dropped; single synthesis + operator shaping (the operator crafts the deliverable anyway) | S-03 |

### 18.2.3 The legacy Supabase `run-research` aggregator (what the product replaced)

The original application's research step was a shallow aggregator: per open question it called
SerpAPI, SearchAPI and an Apify browser actor, stored the raw JSON, embedded it, and left the
operator to assemble a report. It had no claim model, no verification, no audit trail, no cost
accounting, and — as documented in chapter 14 — no real tenant isolation. The research verdict of
2026-07-20 was that Tribunal supersedes it entirely, with only trivial edge-case losses (hard-coded
review-site crawls). It is barred from the new credentials by a CI guard.

### 18.2.4 Doing it by hand

The honest comparison for an agency is an analyst with a browser. The product's value against that
baseline is not that the machine is smarter; it is that the machine is **exhaustive, adversarial,
and accountable** in ways a person under time pressure is not: three providers instead of one
search history; several hundred claims extracted instead of the ones that caught the eye; each
material claim attacked rather than accepted; every source snapshotted; every step recorded.

## 18.3 Where Nestor Pulse leads

These are the properties that are rare or absent in the comparison set and that the design is
built around. Each is grounded in code and in the decision log.

1. **Adversarial refutation, not peer review.** The skeptic is a hand-written tool-use loop that
   must emit a verdict (`support` / `refute` / `insufficient` / `superseded`) after commissioning
   web evidence of its own. Frontier "reviewer" agents check quality; this one tries to break the
   claim.
2. **A published survival rule.** A claim drops only when a majority of verdicts refute it *and* at
   least one refutation cites an independent source. The rule is deterministic and testable; it is
   not a model's mood.
3. **Contradictions collide on purpose.** Same-fact claims from different providers are merged
   before verification so that "Aral 16%" and "Aral 21%" meet in one skeptic session instead of
   both shipping (D9, the fix for the run-4cbb5311 defect).
4. **A tamper-evident audit chain of every LLM call.** Each call's request, response, tokens and
   cost are sealed into a hash-chained `audit_log` with the full bodies retained in a 7-year GCS
   bucket. `verify_chain` is a hard gate on every deploy and on the completion path. This is the
   EU AI Act Article 12 story, and it is why the audit payload fields are frozen.
5. **Multi-provider independence.** Three vendors per research group, ≥2-of-3 succeed, no single
   vendor lock-in, and the degraded state is named rather than hidden.
6. **Cost truth.** Every countable cost class is counted from recorded usage × published prices;
   nothing is estimated; a missing price row writes NULL and flags `cost_pending` rather than
   inventing a number. (Chapter 11 records the three gaps that remain.)
7. **Structured human gating across the whole flow.** Operator accept/edit/reject on every
   AI-suggested field; a client validation round; a deliberate, confirmed, paid trigger; an
   operator-authored client deliverable. The frontier tools are chat surfaces with, at most, a
   plan-approval gate.
8. **Tenant isolation as a first-class deliverable.** Token claims → repository scoping → RLS →
   CI denial suites → seam re-verification → engine RLS. The class of bug that motivated the
   re-platform is structurally guarded at six layers (chapter 14).
9. **Honest terminal states.** `completed`, `completed_degraded` (with every reason named),
   `parked` (resumable, human-click only), `failed`. Silent-green was designed out after the first
   run produced one.
10. **Questions the client did not think to ask.** The discovery bracket admits evidence-anchored
    questions ("the brief assumes X, the world says Y"; "no source, no slot") and reports their
    provenance — the enrichment role the original design took from Google's foundational-context
    idea, made bounded and auditable.

## 18.4 Where others lead, stated plainly

- **Single-model reasoning depth.** A purpose-built reasoning model can out-think a pipeline on a
  single hard question. Nestor Pulse deliberately trades that for independence and auditability.
- **Tool ecosystems.** Domain-specific databases and connectors are irrelevant here; general web
  search/fetch is the correct surface for market research.
- **Rich artefacts.** The deliverable is a report; there is no need for figures-with-code.
- **Speed.** A run takes tens of minutes and, with three providers polled for up to 35 minutes
  per angle, can be silent for long stretches. A chat product answers in seconds.

## 18.5 What the benefits are, and what has been measured

The project's own rule is that no number is presented as observed unless it was. Applied here:

**Measured (from real runs, cited in the run reports):**

- The verification pipeline's gates concentrate spend where it matters: on the recorded
  1,162-claim fixture, materiality and error-likelihood gates kept 456 → 424 claims for checking;
  validation against actual verdicts found the dropped claims contained no material refutations.
- The engine's own defects have been caught and fixed by its audit trail, not by client complaints:
  a serialisation crash that silently discarded verdicts (run 4cbb5311), a separator mismatch that
  dropped 278 correct claims (run 7dcf51d5), a corroboration key that never matched (`both: 0`), a
  report language that was never set (run 368ff3a0). The trail is a working instrument.
- Prompt caching saved 14–30% of Anthropic spend across all six runs in the audit bucket.
- Skeptic verification is ~79% of a run's cost and scales linearly at roughly $0.11 per claim
  group (73 groups → $8.49; 178 → $35.44).
- The Flash-model swap of 2026-09-01 was justified by a replay of 267 real prompts: the pairwise
  judge picked the first-listed option 69.9% of the time on the old model and 58.4% on the new one.

**Projected, not yet observed (⛔):**

- The redesigned engine (question workshop loop, grouping, discovery bracket, yield instrumentation)
  was measured on local harnesses and replays; the live run that validates it end to end has not
  been executed since the five waves deployed on 2026-08-05.
- The two model moves of 2026-09-01 (Sonnet 5, Gemini 3.7 Flash) have never executed a run; the
  ≈$29 cost projection is arithmetic over replayed, truncated prompts.

## 18.6 Who benefits, and how

| Party | Benefit |
|---|---|
| The client | A report whose load-bearing statements survived an attempt to refute them, with graded, dated, snapshotted sources; a plain "what we could not establish" section; a deliverable written by a person, not a model; their data isolated to their own space; nothing visible until it is ready |
| The operator | A live feed of what the engine is doing and spending; a verification report that says what was checked, what was dropped, what shipped unverified and what it cost; a downloadable bundle that feeds the report-writing step; honest degraded/parked states instead of silent failures |
| The agency | A repeatable, auditable process on one GCP project with one login; per-run cost that can be itemised from the audit bucket without database access; a legal record of every AI decision |
| The next engineer | A decision log for every "why", gates that fail loudly, and a codebase whose comments record the incidents that shaped them |
