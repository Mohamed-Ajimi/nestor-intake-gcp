---
status: complete
phase: quick-260731-dbo
plan: 01
date: 2026-07-31
files_modified:
  - .planning/ENGINE-REDESIGN-SPEC.md
  - .planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md
requirements: [QUICK-260731-dbo]
---

# Quick task 260731-dbo — Summary

Rewrote § 5 (Wave 4) of `.planning/ENGINE-REDESIGN-SPEC.md` against the 2026-07-31 local measurement,
and carried the same factual correction into the 15.7 ruling ledger. Doc-only; no source, test or
config file was touched.

## What changed, and why it matters to the 15.7 planner

**Four of the five headline Wave-4 diagnoses were disproved and are now marked superseded in place,
each with its measured replacement beside it.** The fifth (D-R9) is marked confirmed.

| # | Diagnosis | Outcome |
|---|---|---|
| 1 | "9 of 10 winners WEAK" is a quality signal | **Disproved** — truncation artefact of `_CANDIDATE_PROMPT_CHARS = 240` |
| 2 | The exit rule can never fire | **Disproved** — all three configs exit on all three criteria inside the cap |
| 3 | Population balloons; 10 rounds costs ~$3.00 | **Disproved for one global loop** — 23–41 population, $0.24 (exp11). Still true under brackets (122) |
| 4 | Newcomers must seed at the field median | **Disproved** — the seed is inert (byte-identical); replaced by a catch-up schedule |
| 5 | D-R9 — Elo-1200.0 ties are real | **CONFIRMED** — reproduced exactly; 4 rounds over 17 candidates = 3.76 matches each |

**The causal finding is stated explicitly:** the lever is the SELECTION RATIO, not the slot count.
exp10 and exp11 are presented as before/after (6 vs 12 generated per client question, identical slots),
never as a range — the range is what would have hidden the finding. exp10 carries the literal label
`SUPERSEDED — generation defect` with its cause named (the generation prompt states the count twice —
`Output EXACTLY 6 lines` and `<your 6 lines go here>` — and only the first was patched), recorded as a
Wave-4 implementation requirement and tied to the CR-01 defect class from Wave 3.

**The criterion-1/criterion-2 off-by-one was corrected in all three places it existed** — § 5's boxed
trap warning, § 8's Wave-4 verification row, and the ledger's trap bullet. The last one mattered most:
the ledger is the first file the 15.7 planner is instructed to read, so it was carrying a known-wrong
instruction ahead of the spec. The half-built Guard-2 gap (`workshop_rank.py:688` marks resurrected
candidates, `workshop_rank.py:708` does not) is recorded as a Wave-4 requirement.

**D-R10's admission test was inverted and is corrected:** it now verifies the PREMISE is real rather
than that a published answer already exists (as written it rejected all 4 invented angles), and the
evidence must be a real `groundingChunks` search result rather than the model's own output line (a
looser check admitted 2 of 3 angles with a literal `-` as the URL).

**Honest limits are stated in the document, not omitted:** n=1, temperature-1.0 run-to-run variance
(three runs of the *same* config exited at rounds 4, 6 and 6 — worded so it cannot be misread as the
config-to-config comparison), and the fact that harness-implemented stages test the DESIGN, not any
implementation, while stages lifted verbatim from `workshop_rank.py` do transfer.

**Ledger open items 1 and 2 are marked ANSWERED BY MEASUREMENT** with their original reasoning
preserved verbatim in block quotes; items 3 and 4 are explicitly flagged as still genuinely open, with
a boxed warning so two ticks are not read as closing the section. Every operator ruling in `## RULED`
and the `## Still owed at 15.8` section are byte-untouched.

## Gates run, and their actual results

All gates were run as written and their real output read. None were assumed green.

| Gate | Result |
|---|---|
| Task 1 automated gate (10 literals + `245–373` regex + doc-only assertion) | **OK** |
| Task 2 automated gate (20 spec literals, 2 spec regexes, 1 negative range regex, 6 ledger literals, 1 ledger regex, 1 negative ledger regex, 4 ruling-preservation literals, recursive off-by-one check, doc-only assertion) | **OK** |
| Task 3 automated gate — content half (15 literals + stale-row negative + doc-only assertion) | **CONTENT-OK** |
| Task 3 automated gate — commit half (`git log -1 --name-only` contains both docs, no source paths) | **OK** |
| Gates 1 and 2 re-run after Task 3 edits (regression check, not required by the plan) | **OK / OK** |
| Non-vacuity check on the recursive off-by-one regex | Confirmed live — still matches the plan's 3 quoted copies, returns nothing for the 2 real locations |

The non-vacuity check is worth calling out: the plan's `<gate_integrity_note>` warned that an earlier
draft of this gate matched nothing at all. Dropping `--exclude-dir=quick` confirmed the regex does
match real text, so the empty result over the two corrected files is a real pass rather than a typo.

## Deviations

**1. [Plan-conflict resolution] The defective criterion-number string was corrected in place rather
than struck through.** House rule 2 says supersede rather than delete; the plan's verification step 3
requires the string `exclude them from ... criterion 1` to exist nowhere under `.planning/` outside the
plan directory. A strikethrough would have preserved the literal and failed the gate. Resolved as the
plan's own part (f)/(g) wording directs ("Correct it to **criterion 2**", "Change `exit criterion 1` to
`exit criterion 2`"): an in-place correction, plus an explicit dated note in both files recording what
the sentence previously said and why it was wrong. The audit trail is preserved; the defective literal
is not.

**2. [Rule 2 — missing critical correction] The ledger's preamble was updated from "Four items still
need an operator ruling" to two.** Not named in the plan, but leaving it would have made the file
contradict its own retitled section heading in the first paragraph a planner reads — reintroducing
exactly the say-two-different-things defect class this whole pass exists to remove. It is a factual
count, not a ruling.

**3. [Recorded, not resolved] The spec and the ledger now describe D-R11 differently, deliberately.**
The spec's D-R11 is superseded to the catch-up schedule; the ledger's `## RULED` D-R11 still records
the median-seed form because the plan marks that section read-only. Rather than silently leave the two
in conflict, the spec's D-R11 carries an explicit "Note on the ledger" paragraph saying the ledger was
left verbatim on purpose, that the spec is the current engineering form, and that **the substitution
must be routed to the operator when 15.7 is planned**. This is the one open thread this pass creates
and it is signposted in the document rather than only here.

**4. [Additive] One extra § 9 knob.** Alongside the two the plan names (catch-up match budget,
candidates-per-client-question), the candidate prompt-truncation cap was added — it is the single
setting the whole § 5 correction turns on, and § 9 is where a planner looks for it. Noted as needing
*a* value, not 240, because it is a real injection bound.

No architectural changes, no package installs, no checkpoints hit.

## Self-Check: PASSED

- `.planning/ENGINE-REDESIGN-SPEC.md` — FOUND (modified, 862 lines)
- `.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md` — FOUND (modified)
- `.planning/quick/260731-dbo-rewrite-engine-redesign-spec-section-5-w/260731-dbo-SUMMARY.md` — FOUND
- Commit contains both edited documents and no `tribunal/`, `backend/`, `frontend/` or `infra/` path — verified by the Task 3 gate

## Note for the executor's own record — stale-base trap fired again

This worktree was cut from `a3a0c96`, **534 commits behind** the required base
`16421a9` — the eighth consecutive occurrence, and a wider distance than the 486–524 range recorded in
phase 15.6. `git rev-list --count BASE..HEAD` would have read `0` (green) the whole time. Only the
merge-base assertion caught it. Reset performed and verified before any file was read or edited, so
every edit above was made against the correct revision of both documents.
