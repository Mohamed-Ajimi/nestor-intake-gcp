# CONTINUE HERE — session handoff 2026-07-29

Top-level handoff. The per-phase `.continue-here.md` files under `.planning/phases/15.2/`, `15.3/`
and `16/` are **superseded for deploy purposes** — the deploy they describe is now COMPLETE.

## Where things stand in one paragraph

The combined 15.2 + 15.3 deploy is **finished**: all four services are live, `tribunal-worker` was
recreated and unpaused after the 2026-07-28 incident, and `DEPLOY-RUNBOOK` § 15.2.k's dangerous
ordering has been corrected. **V-01 has run** (`7dcf51d5`, 2026-07-28, 65.1 min, $53.48, 396 claims,
`completed_degraded`) and has been analysed end to end. The full forensics are in
**`docs/tribunal-run-reports/run-20260728-7dcf51d5-V01-FINDINGS.md`** — read that before forming any
view about the engine. Nothing is in flight; the tree is clean.

## The next actions, in order (the order is load-bearing)

Full detail in the memory note `engine-fix-sequence-post-v01`.

0. **TIME-LIMITED — preserve V-01's citations.** Gemini's grounding redirects expire ~30 days from
   2026-07-28, i.e. **around late August 2026**. All 225 resolved cleanly on 2026-07-29. Resolve and
   store the real publisher URLs or the forensics doc's evidence base becomes unverifiable.
1. **Two diagnostics — these gate everything else.**
   a. Why did gemini omit the `FACTS_START/FACTS_END` block on 2 of 5 reports? (The two without one
      are its longest — 40k and 57k chars — so truncation is the prime suspect.)
   b. Why did the distiller return ZERO claims for the coffee focus area while producing 186 from
      other focus areas in the same pass?
   **A truncation cause and a tagging cause need OPPOSITE fixes**, and one of them makes the Q4
   grouping change dangerous. Do not design before these are answered.
2. **Operator decision: Q1 + Q4 together** (see memory `engine-design-open-questions`). Q4 is
   supported by V-01 evidence but gated on 1a.
3. **Then plan the phase**: writer reads the research (not only claims) → extraction fix → resolve
   redirects at ingest → `corroboration_key` + `as_of` date on claims → claim clustering LAST.

## The finding that survived every check

**The report is written from claims only, and ~89% of the research never reaches the claim layer.**
Gemini's two coffee angles returned 98,148 chars of on-target research — Shell Café, Circle K
dropping Illy, LUKOIL's own Costa/Douwe Egberts model — and produced **zero** claims. The delivered
coffee section has no Benelux content and tells the client the Benelux data "geeft geen volledig
beeld": a gap of our own making, reported as a limitation of the evidence.

## READ THIS BEFORE JUDGING THE ENGINE

**Read the delivered report (`output` row, `format='markdown'`), not the claim table or the logs.**
Four claims in the findings doc were written from intermediate artifacts and had to be withdrawn or
corrected — each time assuming a capability was missing when it was working:

- D-V01-4 ("a contradiction shipped unflagged") — **WITHDRAWN**. The report has 34 settled
  contradictions with live re-fetching; De Haan was entry 34, settled better than the analysis was.
- `brief_conflicts` "never reaches the report" — **false**, it renders in full.
- gemini's redirects blamed for the extraction failure — **false**, they are known and handled since
  plan 15.2-04/05.
- gemini's link label as publisher domain — true only in the bibliography, not inline.

**The verification stage works. Do not touch it.**

## Also still owed

Operator's no-engine-behaviour-change attestation (the D-03 gate — a person must write it), 15.3
plan 09's two operator checkpoints (now testable against run `7dcf51d5`), the D-L elapsed clock
check, and the five standing deploy debts — headed by **rotating `Nestor_Claude_Temp`**, which
transited a chat in plaintext on 2026-07-27 and is still live on both Tribunal services.
