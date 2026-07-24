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

---

Brainstorm completed 2026-07-24 — all 8 areas decided (D1–D14).
Related, agreed the same day in STAKEHOLDER-NOTES.md: the 7 verification-stage
changes + the superadmin-only post-run verification report.
Next step when ready: take this file + the STAKEHOLDER-NOTES entries into
/gsd-discuss-phase 15 (sequencing note: operator hold — engine work after
phases 18/19; no live runs before 2026-08-01 cap reset).
