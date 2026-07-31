---
phase: quick-260731-dbo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/ENGINE-REDESIGN-SPEC.md
  - .planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md
autonomous: true
requirements: [QUICK-260731-dbo]
must_haves:
  truths:
    - "A reader of § 5 can see which Wave 4 diagnoses were disproved, by what measurement, and what replaced each one."
    - "No superseded claim is deleted — each is marked superseded and carries its measured replacement beside it."
    - "Every number written into either document traces to a measurement stated in this plan AND names the run (exp7c / exp10 / exp11) that produced it; no figure is invented and no two runs are blended into a range."
    - "exp11 reads as THE validated configuration; exp10 reads as a superseded run with a named generation defect, never as an alternative result or as the cost of this design."
    - "The causal finding — the lever is the SELECTION RATIO, not the slot count — is stated explicitly, with exp10-vs-exp11 as its before/after evidence."
    - "§ 5 no longer contradicts the rulings in 15.7-OPEN-ITEMS.md (tournament stays, loop must DISCOVER, losers never barred)."
    - "§ 0's cost baseline, § 1's decision table, § 8's Wave-4 verification row and § 9's knob list agree with the rewritten § 5."
    - "The honest limits of the measurement (n=1, temperature variance, harness-implemented stages) are stated in the document, not omitted."
    - "The criterion-1/criterion-2 off-by-one is corrected in BOTH places it exists — the spec's boxed warning and the 15.7 ruling ledger — so the first file the 15.7 planner reads no longer carries a known-wrong instruction."
    - "15.7-OPEN-ITEMS.md open items 1 and 2 read as ANSWERED by measurement with their original reasoning preserved; items 3 and 4 remain open; no operator ruling in that file is altered."
    - "Nothing outside .planning/ changed — no tribunal/, backend/, frontend/ or infra/ file is touched."
  artifacts:
    - path: ".planning/ENGINE-REDESIGN-SPEC.md"
      provides: "Corrected Wave 4 section with the three-config measurement table and the validated configuration"
      contains: "exp11"
    - path: ".planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md"
      provides: "Ruling ledger with the criterion-2 fix and open items 1-2 marked answered by measurement"
      contains: "exit criterion 2"
  key_links:
    - from: ".planning/ENGINE-REDESIGN-SPEC.md § 5"
      to: ".planning/phases/15.7-*/15.7-OPEN-ITEMS.md"
      via: "ruling consistency — corrections change diagnoses and numbers, never operator rulings"
      pattern: "D-R9|D-R10|D-R11"
    - from: ".planning/ENGINE-REDESIGN-SPEC.md § 5"
      to: ".planning/ENGINE-REDESIGN-SPEC.md § 0 / § 8 / § 9"
      via: "shared cost and verification figures, all attributed to exp11"
      pattern: "exp11|SUPERSEDED"
    - from: ".planning/phases/15.7-*/15.7-OPEN-ITEMS.md open item 2"
      to: ".planning/ENGINE-REDESIGN-SPEC.md § 5 three-config table"
      via: "ledger cites the validated run's figures only; § 5 holds the full table"
      pattern: "ANSWERED BY MEASUREMENT"
---

<objective>
Rewrite § 5 (Wave 4 — the creative workshop loop) of `.planning/ENGINE-REDESIGN-SPEC.md` so its defect
diagnoses match what local measurement actually showed, record the validated Wave 4 configuration, and
carry the same factual correction into the 15.7 ruling ledger.

Purpose: this spec is the input to `/gsd-plan-phase 15.7`. Four of its five headline Wave-4 diagnoses
were disproved by a local harness (11 experiments, ~$3, scratchpad only — **no repo code was changed**)
that replayed the real V-01 run from the GCS audit log and then implemented the Wave 4 loop end-to-end.
If the spec is not corrected first, a planner will build fixes for problems that do not exist.

`15.7-OPEN-ITEMS.md` is in scope for one reason and one reason only: it is the **first file the 15.7
planner is instructed to read**, and it repeats the same criterion-1/criterion-2 factual error. Fixing
the spec while leaving a known-wrong instruction in the file read before it defeats the purpose.

Output: two edited planning documents, committed. No source, test or config change.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/ENGINE-REDESIGN-SPEC.md
@.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md

Section map of the spec (759 lines total):
- `## 0. Where this came from` — line 14; `### Measured cost baseline` — line 31
- `## 1. Decisions taken` — line 48 (the D-R1…D-R11 table)
- `## 5. Wave 4 — the creative workshop loop (D-R6, D-R9)` — line 395
  - boxed `⚠️ SIX OPEN AMBIGUITIES` — 397-443
  - `### What is wrong today, precisely` — 445
  - `### The loop` — 459
  - `### D-R10 — the loop must DISCOVER…` — 507
  - `### D-R11 — Elo carries, newcomers seed at the field median` — 540
  - `### The rejected register — bar on defect, not on defeat` — 560
  - `### Exit criteria — all three, or the cap` — 584 (boxed trap warning 593-599)
  - `### Why 10 rounds is affordable` — 608
  - `### Freeze and hand-off` — 626
- `## 8. Verification` — 674 (per-wave table 688-694, Wave 4 row at 693)
- `## 9. Environment knobs` — 720

Section map of the ledger (140 lines total):
- `## RULED — do not relitigate` — 25 (D-R9 at 27, D-R10 at 40, D-R11 at 65) — **read-only in this plan**
- `## OPEN — needs an operator ruling before planning` — 87 (item 1 at 89, item 2 at 98, item 3 at 104,
  item 4 at 109)
- `## Traps this phase inherits` — 115; the `WEAK`-winner coverage lie bullet — 118-121, whose last
  sentence at line 121 is the off-by-one being corrected
- `## Still owed at 15.8` — 136 — **read-only in this plan**
</context>

<measurement_ledger>
**This is the authoritative figure set for the whole plan. Every number below is attributed to the run
that produced it. Do not blend two runs into a range anywhere in either document.**

| run | config | generated per client question | slots | exits | cost | population |
|---|---|---|---|---|---|---|
| exp7c | global, no floor | 6 | 10 | round 6 | **$0.18** | peak **23** |
| exp10 | global + floor 5/question + 2 cross | 6 (**generation defect**) | 17 | round 9 | **$0.48** | peak **32** |
| **exp11** | **global + floor 5/question + 2 cross** | **12** | **17** | **round 4** | **$0.24** | **34–41, flat** |

**exp11 is THE VALIDATED CONFIGURATION.** Its figures are the primary ones everywhere.

**exp10 is a SUPERSEDED run with a named defect, not an alternative result.** It ran the same
architecture, but the real generation prompt states the candidate count **twice** — `Output EXACTLY 6
lines` and `<your 6 lines go here>` — and **only the first was patched**, so it still produced 6 per
client question. That made 5 slots a 5-of-6 choice — no selection at all — and the loop needed 9 rounds
and $0.48 to grind out a clean winner set. With 12 generated it is a real 5-of-12 choice, prefer-KEEP
always has KEEP candidates available, the winner set is clean from round 1, and it exits in round 4 for
$0.24.

**THE FINDING: the lever is the SELECTION RATIO, not the slot count.** Fixing the generation count
**halved the cost AND more than halved the rounds**. exp10-vs-exp11 is the evidence, and it only reads
as evidence if the two are presented as before/after, never as a range. A range hides the causal point.

**Population, stated honestly:** across all three global configs the population stays **between 23 and
41** and the largest prompt is **~9k chars** — against the section's feared *"round-9 prompt carrying 60
candidates"*. Per-client-question brackets **did** reach **122**, so the explosion is
**architecture-dependent, not inherent**.

**Do not conflate two different "round 4" statements.** The temperature-variance note in Task 1 (three
runs of the same configuration exiting at rounds 4, 6 and 6) is about **repeat runs of one config**;
exp11's round 4 is a **different-config** result. Both are true; write them so a reader cannot read one
as the other.
</measurement_ledger>

<house_rules>
These apply to all three tasks. Violating any one of them fails the plan.

1. **DOC-ONLY, and exactly two files.** The only files modified are
   `.planning/ENGINE-REDESIGN-SPEC.md` and
   `.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md`.
   Do not edit, create or delete anything under `tribunal/`, `backend/`, `frontend/`, `infra/`, or any
   test or config file. Source line numbers are quoted as *evidence*; they are not edit targets.
2. **Supersede, never silently delete.** Where a claim is now wrong, keep the original text visible,
   mark it `**SUPERSEDED (measured 2026-07-31)**`, and put the measured replacement beside it. A future
   reader must be able to see what was believed and why it was wrong. Strikethrough (`~~…~~`) plus a
   replacement sentence is the established convention in this file (see § 8 lines 691-692) — reuse it.
3. **Do not relitigate operator rulings.** D-R9 (tournament stays, Elo retained), D-R10 (the loop must
   DISCOVER, not only sharpen) and the rejected-register table — including *"losers must NEVER be
   barred"* — stay. In the ledger this is stricter still: the entire `## RULED` section and the
   `## Still owed at 15.8` section are **read-only**. Correct diagnoses and numbers, not rulings.
4. **No invented figures, and every figure carries its run.** Every number written into either document
   must come from `<measurement_ledger>` above and must name the run it came from (exp7c / exp10 /
   exp11). If a number is needed that is not there, write the qualitative claim without a number.
5. **`.planning/` is gitignored** in this repo. Both edited files need `git add -f`, as does this plan
   directory.
6. **One number set per file, no ranges across runs.** § 5 carries the full three-config table; the
   ledger cites **exp11's figures only** and points at § 5's table for the rest. Never write
   `$0.18–$0.48` or any other span that merges two runs — the span is the thing that hides the finding.
</house_rules>

<tasks>

<task type="auto">
  <name>Task 1: Record the measurement's provenance and correct the truncation artefact</name>
  <files>.planning/ENGINE-REDESIGN-SPEC.md</files>
  <action>
Edit § 5 lines 395-458 only.

**(a) Insert a new subsection immediately after the `## 5.` heading (line 395), before the boxed
ambiguities block**, titled `### What was measured on 2026-07-31, and what it overturns`. It records:
a local harness ran 11 experiments for ~$3, entirely in a scratchpad, changing **no repo code**; it
replayed the real V-01 run from the GCS audit log and then implemented the Wave 4 loop end-to-end;
**four of the five headline diagnoses in this section were disproved**. State that the corrections
below are marked inline and that the operator rulings in 15.7-OPEN-ITEMS.md are unchanged.

**(b) In that same new subsection, add a clearly-headed `**Honest limits of this measurement**`
paragraph** — this must not be buried or softened. It states all three limits:
  - every result is **n=1**: one client, three client questions, Dutch, 18 candidates;
  - Sonnet's evolve runs at **temperature 1.0**, so single runs vary — three runs of **the same
    configuration** exited at **rounds 4, 6 and 6**. Word this so it cannot be misread as the
    three-config comparison Task 2 adds: this is run-to-run variance, that is a config-to-config
    difference;
  - the loop stages that do not exist in the codebase yet — generative evolve, meta-review, the
    grounded lookup, judge reasons, carried Elo, the catch-up schedule, the exit checks — were
    **implemented by the harness author**, so those results test the **DESIGN, not any
    implementation**. The stages lifted verbatim from `workshop_rank.py` (critique + tournament
    prompts, both parsers, Swiss pairing, Elo, `winner_count`, the renderers) **do** transfer directly.

**(c) Correct the "9 of 10 winners WEAK" evidence at line 455-457 — it is an ARTEFACT, not a quality
signal.** Mark the existing symptom sentence superseded and write the measured explanation:
`workshop_rank.py:168` sets `_CANDIDATE_PROMPT_CHARS = 240`; the real V-01 candidates are 245–373
chars, so **17 of 18 reached the critic cut off mid-word** — 920 chars discarded, no ellipsis, no
question mark — while being asked whether each question is *"sharp and answerable AS IT STANDS"*.
Measured on the real prompt against the real candidates: at cap 240 the critique returns
`KEEP=1/WEAK=17` with only **2 distinct flaw clauses** (16× *"two questions in one"*); with the cap
raised it returns `KEEP=9/WEAK=9`. End-to-end (critique → tournament, rounds held at 4): **"9 of 10
winners WEAK" reproduces exactly at cap 240 and becomes 2 of 10 with the cap raised.**

State plainly that the truncation is **a real security control** — it bounds attacker-influenced text
so an injected candidate cannot forge another candidate's output line — so it needs *a* bound, just not
240. Note that the same cap truncates **both sides** in `_match_block`, so the tournament was judging
mutilated text too.

**(d) Retitle the boxed block** from `⚠️ SIX OPEN AMBIGUITIES — settle these BEFORE planning 15.7` to
reflect that items 3 and 4 are now closed by measurement (Task 2 rewrites their bodies); leave items
1, 2, 5 and 6 as they stand in this task.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && for s in "_CANDIDATE_PROMPT_CHARS = 240" "KEEP=1/WEAK=17" "KEEP=9/WEAK=9" "n=1" "temperature 1.0" "rounds 4, 6 and 6" "DESIGN, not any" "_match_block" "SUPERSEDED"; do grep -qF "$s" "$F" || { echo "MISSING: $s"; exit 1; }; done && { grep -qE "245[–-]373" "$F" || { echo "MISSING: 245-373 candidate length"; exit 1; }; } && git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; echo OK</automated>
  </verify>
  <done>§ 5 opens with a dated measurement-provenance subsection carrying the three honest limits verbatim, with the temperature-variance note worded so it cannot be confused with the config comparison; the "9 of 10 winners WEAK" line is marked superseded and explained as a cap-240 truncation artefact with both measured critique splits recorded; no file outside `.planning/` is modified.</done>
</task>

<task type="auto">
  <name>Task 2: Correct the exit rule and the cost/population estimate, record the validated configuration and the selection-ratio finding, and fix the criterion-1/2 off-by-one in BOTH files</name>
  <files>.planning/ENGINE-REDESIGN-SPEC.md, .planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md</files>
  <action>
In the spec, edit the boxed items 3 and 4, `### Exit criteria` (584-606) including its boxed trap
warning, `### Why 10 rounds is affordable` (608-624), and `### Freeze and hand-off` (626-628). Then
apply parts (g) and (h) to the ledger. All figures come from `<measurement_ledger>`; house rules 4 and
6 govern how they are written.

**(a) The exit rule fires; it needs NO change.** Boxed item 3 and open item 1 of 15.7-OPEN-ITEMS.md
both assume the loop hits the 10-round cap every run because criterion 2 can never be satisfied. Mark
that **resolved by measurement**: with the truncation cap fixed, **all three** global configurations
exit on all three criteria well inside the 10-round cap — **exp7c in round 6, exp10 in round 9, exp11
in round 4**. WEAK winners went **3 → 3 → 0 → 0**; the three criteria genuinely gate each other in
turn. Record explicitly: **keep all three exit criteria exactly as written** — the *"the cap is a
ceiling, not a target"* sentence at line 619-620 is **confirmed**, not contradicted.

**(b) Add a fourth exit-criteria action — the single highest-leverage rule found: PREFER KEEP OVER WEAK
WHEN FILLING A SLOT.** Explain why it matters: exit criterion 2 *checks* for WEAK winners but nothing
in the design ever *prevented* them. Adding the action took WEAK winners to **0** and made criterion 2
satisfiable by construction. Add the dependency exp10-vs-exp11 exposed: **prefer-KEEP only works if
there are KEEP candidates left to prefer**, which is a property of the selection ratio (part (e)), not
of the rule itself.

**(c) Add the compound-question exemption to criterion 2.** A cross-cutting question is **compound by
construction** — it joins two topics — so *"two questions in one"* must **not** count against it in the
exit check. Without the exemption, criterion 2 structurally penalises the highest-value questions.

**(d) The population does not balloon and the cost estimate is far too high.** Mark the
`Why 10 rounds is affordable` table's **~$3.00 for 10 rounds** superseded: the validated configuration
(exp11) costs **$0.24**. State the population result honestly and with its contrast: across **all three
global configs** the population stays **between 23 and 41** and the largest prompt is **~9k chars**,
against this section's feared *"round-9 prompt carrying 60 candidates"*. Conclude that **the spend
ceiling and a population cap are not binding at this scale** — replace them with **instrumentation**
(log population and spend per round) rather than enforced caps, and rewrite boxed item 4 accordingly.

**IMPORTANT NUANCE that must survive the edit:** the feared 60-candidate explosion **IS real**, but
only under **per-client-question brackets**, where the population reached **122**. It is
**architecture-dependent, not inherent**. Do not delete the warning — scope it.

**(e) Record the VALIDATED CONFIGURATION** as a new subsection before `### Freeze and hand-off`. It has
three parts and the ordering matters — the table, then the defect, then the finding:

  1. **Reproduce the three-config table from `<measurement_ledger>` verbatim**, with exp11's row marked
     as the validated configuration and **exp10's row explicitly labelled `SUPERSEDED — generation
     defect`**. A future reader must not be able to take $0.48 / round 9 as the cost of this design.
  2. **Name exp10's defect precisely.** The generation prompt states the candidate count **twice** —
     `Output EXACTLY 6 lines` and `<your 6 lines go here>` — and **only the first was patched**, so it
     still produced 6 per client question. 5 slots over 6 candidates is a 5-of-6 choice, i.e. **no
     selection at all**; the loop then needed 9 rounds and $0.48 to grind out a clean winner set. Add
     this as a **Wave-4 implementation requirement**: when the generation count is raised in the real
     prompt, **both statements must be changed** — and note it is the same defect class as CR-01 in
     Wave 3, where one value was normalised in one place and compared in another.
  3. **State the finding explicitly: the lever is the SELECTION RATIO, not the slot count.** With 12
     generated per client question it is a real 5-of-12 choice, prefer-KEEP always has KEEP candidates
     available, the winner set is clean from round 1, and the loop exits in **round 4** for **$0.24**.
     **Fixing the generation count halved the cost AND more than halved the rounds.** Present exp10 and
     exp11 as before/after, never as a range.

  The configuration itself, recorded as the thing Wave 4 builds:
  - **ONE global loop**, NOT per-client-question brackets. Brackets were tested and fail on four
    counts: they never converge, they hit the 10-round cap, they cost **3–4×** more, the population
    reaches **122**, and — the structural reason — inside one bracket evolve cannot **COMBINE across
    client questions**, which is where the best output came from.
  - **12 candidates generated per client question** (the selection ratio, from (e)(3)).
  - Winners = a **floor of 5 per client question + 2 cross-cutting**, applied at the **CUT** rather than
    by splitting the pool.
  - Prefer KEEP over WEAK when filling a slot (from (b)).
  - Measured result: **17 questions, none weak, converges in round 4, $0.24** (exp11).

**(f) Fix the two spec-internal defects while editing:**
  - The boxed trap warning at 593-599 ends *"Mark resurrected candidates and exclude them from
    criterion 1."* That is an off-by-one: criterion 1 is **COVERAGE** and criterion 2 is **QUALITY**;
    excluding them from coverage breaks the very guarantee resurrection exists to provide. Correct it
    to **criterion 2**, and note that the identical error existed in `15.7-OPEN-ITEMS.md` and is
    corrected in the same commit (part (g)).
  - Half of that guard is already built and half is missing: `workshop_rank.py:688` sets
    `entry["resurrected"] = True` for Guard 1, but **Guard 2 does not** — at `workshop_rank.py:708`,
    when critique kills everything, it rewrites every candidate to `KEEP` **unmarked**, so the one case
    where quality most needs to read as failed reads as a perfect pass. Record this as a Wave-4
    implementation requirement.

**(g) Correct the SAME off-by-one in the ledger.** In `15.7-OPEN-ITEMS.md`, `## Traps this phase
inherits`, the `WEAK`-winner coverage lie bullet (lines 118-121), the final sentence reads *"Mark
resurrected candidates and exclude them from exit criterion 1."* Change `exit criterion 1` to
`exit criterion 2` and append a short parenthetical stating why — criterion 1 is coverage, criterion 2
is quality, and excluding a resurrected candidate from coverage would break the guarantee resurrection
exists to provide. **This is a criterion-number fix and nothing more.** Do not touch D-R9, D-R10,
D-R11, the rejected-register rules, the other trap bullets, or the `Still owed at 15.8` section.

**(h) Mark ledger open items 1 and 2 ANSWERED BY MEASUREMENT.** Keep both items and all their existing
reasoning in place (house rule 2) and prefix each with a bold `**✅ ANSWERED BY MEASUREMENT
2026-07-31 — see ENGINE-REDESIGN-SPEC § 5.**` line:
  - **Item 1** (*"the exit rule probably never fires — the expensive one"*): **void, because its
    premise was the cap-240 truncation artefact.** Its entire argument rests on *"V-01 had 9 of 10
    winners WEAK"*, which Task 1 established is a truncation artefact rather than a quality signal.
    With the cap fixed, the validated configuration (**exp11**) exits in **round 4**, so the 10-round
    cap is not the normal cost. No operator ruling is required.
  - **Item 2** (*"two unset numbers — decide together"*): **not binding at the measured scale.**
    Neither the spend ceiling nor the per-round grounded-lookup cap needs a value — the validated
    configuration costs **$0.24** against the ~$3 budget this section assumed, with the population
    **flat at 34–41**. Per house rule 6 cite **exp11's figures only** and point at § 5's three-config
    table for the rest; do not restate exp7c's or exp10's numbers here. Note that the correct
    replacement is instrumentation, not an enforced cap.
  - **Items 3 and 4 remain genuinely OPEN** — say so explicitly, so the next planner does not read the
    two ticks above and assume the whole section is closed. Retitle the section heading to reflect
    that two of the four are answered.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && L=".planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md" && for s in "exp7c" "exp10" "exp11" "round 4" "round 6" "round 9" "0.18" "0.24" "0.48" "122" "9k chars" "SELECTION RATIO" "generation defect" "Output EXACTLY 6 lines" "PREFER KEEP OVER WEAK" "compound by construction" "floor of 5 per client question" "criterion 2" "workshop_rank.py:708" "instrumentation"; do grep -qF "$s" "$F" || { echo "MISSING in spec: $s"; exit 1; }; done && { grep -qF "between 23 and 41" "$F" || { echo "MISSING in spec: population 23-41 statement"; exit 1; }; } && { grep -qE "34[–-]41" "$F" || { echo "MISSING in spec: exp11 population"; exit 1; }; } && { if grep -qE '0\.18[^0-9]{1,3}0\.48' "$F"; then echo "FAIL: a cross-run cost RANGE was written (house rule 6)"; exit 1; fi; } && for s in "exit criterion 2" "ANSWERED BY MEASUREMENT" "exp11" "round 4" "0.24" "ENGINE-REDESIGN-SPEC § 5"; do grep -qF "$s" "$L" || { echo "MISSING in ledger: $s"; exit 1; }; done && { grep -qE "34[–-]41" "$L" || { echo "MISSING in ledger: flat population"; exit 1; }; } && { if grep -qE '0\.18|0\.48|exp7c|exp10' "$L"; then echo "FAIL: ledger restates a non-exp11 run (house rule 6)"; exit 1; fi; } && for s in "D-R9 reaffirmed" "NEVER be barred" "must DISCOVER" "Still owed at 15.8"; do grep -qF "$s" "$L" || { echo "FAIL: a read-only ledger ruling was damaged: $s"; exit 1; }; done && { if grep -rniE "exclude (them|resurrected candidates) from (exit )?criterion 1" .planning/ --exclude-dir=quick; then echo "FAIL: off-by-one still present"; exit 1; fi; } && git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; echo OK</automated>
  </verify>
  <done>All three configs are recorded with their own figures and none are merged into a range; exp11 reads as validated and exp10 as superseded with its named generation defect; the selection-ratio finding is stated with exp10-vs-exp11 as before/after evidence; the population claim is the honest 23-to-41 span across global configs with the 122 bracket contrast preserved; exit criteria are retained and joined by prefer-KEEP and the compound-question exemption; the Guard-2 marking gap is recorded; the criterion-1/criterion-2 off-by-one no longer exists anywhere under `.planning/` outside this plan directory; ledger items 1-2 are answered citing exp11 only, 3-4 remain open, and every ledger ruling is intact.</done>
</task>

<task type="auto">
  <name>Task 3: Replace D-R11 with the catch-up schedule, fix D-R10's admission test, reconcile the citing sections, and commit</name>
  <files>.planning/ENGINE-REDESIGN-SPEC.md</files>
  <action>
Edit `### D-R10` (507-538), `### D-R11` (540-558), the `### Fix the arithmetic` paragraph (499-502),
plus § 0's cost baseline (31-44), § 1's decision table (50-62), § 8's Wave-4 verification row (693) and
§ 9's knob list (720-731).

**(a) D-R11 (newcomers seed at the field median) is INERT — replace it with a CATCH-UP SCHEDULE.**
Mark the median-seed rule superseded and give the measured reason: `workshop_rank.py:1524` sorts
`(-wins, -elo, index)`, and `_apply_elo`'s own docstring (`workshop_rank.py:878`) says **"ELO IS THE
TIE-BREAK, NOT THE PRIMARY KEY"**. A newcomer's problem is fewer **wins**, not a lower rating, so the
seed value changes nothing — median-seed and flat-1200 produce **byte-identical** results. Measured
with a perfect judge, 8 rounds, newcomer entering round 6: a best-in-field newcomer reaches the top N
**1.5%** of the time. Raw win-rate over-corrects — it admits a mediocre newcomer **93.8%** of the time
versus a strong one **95.5%**.

The replacement: **a new candidate plays up to the field's median match count on entry.** Measured
scores **99.8% / 29.5% / 1.8%** for strong / median / weak newcomers, **with the ranking code
completely unchanged**, at a cost of ~**5 extra flash judgements**. Note that this is Co-Scientist's own
approach — *"newer and top-ranking hypotheses are prioritized for participation in tournament
matches"*. Keep D-R11's **required test** (a strong newcomer introduced in a late round can still reach
the top N) — the catch-up schedule is what makes it passable.

**(b) D-R9 is CONFIRMED and stays.** In `### Fix the arithmetic`, record that the harness reproduced
V-01's exact symptom — three candidates finishing at **Elo exactly 1200.00 with 2 wins each**,
straddling the top-10 cut so one lost its slot to index order — and that **4 rounds over 17 candidates
gives only 3.76 matches each**. Carried Elo + **5 Swiss rounds** + the catch-up schedule eliminated the
ties entirely (**zero at exactly 1200 in every round**). Add the interaction that was previously
unnoticed: **more rounds deepen the incumbency advantage in raw win counts, so D-R9 makes D-R11's
problem worse** — which is precisely why the catch-up schedule matters. Leave the already-REJECTED
ranked-list-plus-run-off option marked rejected.

**(c) D-R10's admission rule inverts its own purpose and must change.** As specified — *"no source, no
slot"* read as *is there a published answer?* — **all 4 invented angles were rejected** and zero
survived, including *"what minimum network density is required for algorithmic pricing to pay off"*,
exactly the kind of question a mid-sized player weighing expansion needs. The rule as written admits
angles that are **already documented** (already known, low research value) and rejects **novel** ones
(nobody has published it, high research value). Change the test to verify the **PREMISE is real** — do
the named entities, markets, mechanisms and metrics exist, and could desk research settle it — rather
than that an answer already exists. The operator ruling (the loop must DISCOVER) is unchanged; only the
admission test changes.

**CRITICAL implementation note that must be recorded:** the admission evidence must come from a **real
search result (`groundingChunks`)**, never from the model's own output line. A looser check admitted
**2 of 3** angles with a literal `-` as the URL, "evidenced" by the model tautologically restating that
its own entities exist.

**(d) Reconcile the sections that cite the same numbers.** Each edit is a short superseding note, not a
rewrite. House rules 4 and 6 apply — name the run, never write a cross-run range:
  - **§ 0 cost baseline (31-44)** — the workshop-cost framing there predates the loop measurement. Add
    a line pointing to § 5's validated loop total of **$0.24 (exp11)** and to the three-config table,
    so a reader does not carry the ~$3.00 loop estimate forward. Do not alter the V-01 per-stage
    measurements themselves — they are audit-log facts.
  - **§ 1 decision table (50-62)** — amend the **D-R11** row so it reads as the catch-up schedule with
    median-seeding marked superseded, and annotate **D-R10** with the premise-real admission test. Do
    not change their `agreed (operator)` status.
  - **§ 8 Wave-4 verification row (693)** — it currently says *"a resurrected candidate does not satisfy
    coverage"*. That is the same off-by-one Task 2 fixed: it must be **quality**, not coverage. Also add
    the catch-up-schedule newcomer test, the prefer-KEEP check, and an assertion that the generation
    count is raised in **both** places the prompt states it (Task 2 (e)(2)).
  - **§ 9 knobs (720-731)** — the new-knob list names a *"loop spend ceiling"*. Per Task 2 that becomes
    instrumentation rather than an enforced cap; adjust the entry, add a knob for the catch-up
    schedule's match budget, and add one for **candidates generated per client question (default 12)**.

**(e) Commit.** `.planning/` is gitignored, so `git add -f` **all three paths**: the spec, the ledger
(`15.7-OPEN-ITEMS.md`, edited in Task 2), and this plan directory. Commit message:
`docs(15.7): correct ENGINE-REDESIGN-SPEC § 5 and the 15.7 ledger against local Wave 4 measurement`.
Verify before committing that `git status --porcelain -- tribunal backend frontend infra` is empty, and
after committing that the commit contains both edited documents and no source file.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && for s in "catch-up schedule" "byte-identical" "1.5%" "93.8%" "95.5%" "99.8%" "29.5%" "1.8%" "3.76" "5 Swiss rounds" "groundingChunks" "PREMISE" "workshop_rank.py:878" "workshop_rank.py:1524" "exp11"; do grep -qF "$s" "$F" || { echo "MISSING: $s"; exit 1; }; done && grep -qF "a resurrected candidate does **not** satisfy coverage" "$F" && { echo "FAIL: stale wave-4 verification row"; exit 1; }; git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; C=$(git log -1 --name-only --format=) && echo "$C" | grep -q "ENGINE-REDESIGN-SPEC" && echo "$C" | grep -q "15.7-OPEN-ITEMS" && ! echo "$C" | grep -qE "^(tribunal|backend|frontend|infra)/" && echo OK</automated>
  </verify>
  <done>D-R11 is replaced by the catch-up schedule with the inertness proof and all six measured percentages recorded; D-R9 is confirmed with the 3.76-matches figure and the D-R9/D-R11 interaction noted; D-R10's admission test tests the premise and mandates `groundingChunks` evidence; §§ 0/1/8/9 no longer contradict § 5 and § 0 cites exp11's $0.24 rather than a range; one commit contains both edited documents, force-added, and no source file.</done>
</task>

</tasks>

<gate_integrity_note>
Every literal these gates grep for was either checked against the files **as they exist today**, or is a
string this plan explicitly instructs the executor to write. Three gate defects were found and fixed
while writing this plan; all three would have read green while being useless.

1. **A vacuous negative gate.** An earlier draft gated on `exclude resurrected candidates from
   criterion 1` — a phrasing that appears in **neither** file. The real strings are spec line 598
   `Mark resurrected candidates and exclude them from criterion 1.` and ledger line 121
   `Mark resurrected candidates and exclude them from exit criterion 1.` The gate would have passed
   whether or not the fix landed. Task 2 now runs one recursive check over all of `.planning/`
   (`--exclude-dir=quick`, because this plan legitimately quotes the defective string), **verified to
   match both occurrences today** — so the two locations cannot be fixed in one spot and forgotten in
   the other, which is exactly how this defect reached two files.
2. **A false-failing positive gate.** An earlier draft asserted the ledger still contains `never
   barred`; the ledger actually says `NEVER be barred`, and `grep -F` is case-sensitive, so a correct
   edit would have failed the task. Corrected, and all four ruling-preservation literals
   (`D-R9 reaffirmed`, `NEVER be barred`, `must DISCOVER`, `Still owed at 15.8`) were confirmed present
   before being used as gates.
3. **Number-literal gates are the same shape, so they are hardened two ways.** Every dashed numeric
   pair is matched with `grep -E` accepting **either** an en dash or a hyphen (`245[–-]373`,
   `34[–-]41`), because a typographic slip would otherwise fail a correct edit. And house-rule-6
   violations are gated **negatively**, not only positively: Task 2 fails if a blended cost range
   (`0.18` near `0.48`) appears in the spec, and fails if the ledger mentions `exp7c`, `exp10`, `0.18`
   or `0.48` at all. A positive gate on `0.24` alone would have happily passed a document that still
   carried the blended range beside it — which is the exact failure being corrected.
</gate_integrity_note>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| planning docs → 15.7 planner | Both files are input prompts to `/gsd-plan-phase 15.7`; a wrong number, a blended range or a wrong criterion index here becomes built code |
| none (runtime) | Doc-only change — no code, no request path, no new dependency, no package install |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-QDBO-01 | Tampering | spec + ledger content | mitigate | House rule 4 forbids invented figures and requires each number to name its run; each task's `<automated>` gate greps for the exact measured literals so a paraphrased or drifted number fails the gate |
| T-QDBO-02 | Repudiation | superseded claims | mitigate | House rule 2 forbids silent deletion — the original claim stays visible beside its replacement, so the change is auditable |
| T-QDBO-03 | Elevation of Privilege | scope creep into `tribunal/` source | mitigate | Every task's gate asserts `git status --porcelain -- tribunal backend frontend infra` is empty; cited source line numbers are evidence, not edit targets |
| T-QDBO-04 | Tampering | operator rulings in the ledger | mitigate | House rule 3 marks `## RULED` and `## Still owed at 15.8` read-only; the Task 2 gate positively asserts four ruling strings still exist, so an over-broad ledger rewrite fails |
| T-QDBO-05 | Spoofing | a defective run passing as a valid result | mitigate | exp10 must carry the literal label `generation defect` and its named cause; Task 2's gate asserts both that literal and `SELECTION RATIO`, and negatively asserts no blended cost range survives |
| T-QDBO-SC | Tampering | npm/pip/cargo installs | accept | No package-manager install occurs in this plan — the legitimacy gate is not applicable |
</threat_model>

<verification>
1. All three task gates pass.
2. `git status --porcelain -- tribunal backend frontend infra` is empty — the doc-only constraint held.
3. `grep -rniE "exclude (them|resurrected candidates) from (exit )?criterion 1" .planning/ --exclude-dir=quick`
   returns nothing — the off-by-one is gone from both locations.
4. The rulings survive in both files: `we are not killing tournament`, `NEVER be barred`,
   `must DISCOVER` still match — corrections changed diagnoses, not rulings.
5. Read the validated-configuration subsection cold: a reader who has never seen this plan can tell
   which run is validated, which is superseded and why, and that the causal lever is the selection
   ratio rather than the slot count.
6. Spot-read the ledger: items 1-2 read as answered citing exp11 only, items 3-4 read as open, and a
   planner following its "read this first" instruction is no longer misdirected.
</verification>

<success_criteria>
- `.planning/ENGINE-REDESIGN-SPEC.md` § 5 states its measurement provenance, its three honest limits,
  the three-config table, and the validated configuration (one global loop, 12 generated per client
  question, 5+2 floor at the cut, prefer KEEP over WEAK).
- exp11 (**round 4, $0.24, 17 questions, none weak**) is the primary figure set everywhere; exp10 is
  labelled `SUPERSEDED — generation defect` with its cause named; no cross-run range appears.
- The selection-ratio finding is explicit, with exp10-vs-exp11 as before/after evidence, and the
  double-statement prompt defect is recorded as a Wave-4 implementation requirement.
- The four disproved diagnoses — WEAK-winner quality signal, the never-firing exit rule, the balloon
  population/$3.00 cost, and median Elo seeding — are each marked superseded with their measured
  replacement, and D-R9 is marked confirmed.
- D-R10's admission test verifies the premise is real and requires `groundingChunks` evidence.
- The criterion-1/criterion-2 off-by-one is fixed in all three places it exists: § 5's boxed warning,
  § 8's Wave-4 row, and `15.7-OPEN-ITEMS.md`'s trap bullet. The Guard-2 (`workshop_rank.py:708`)
  unmarked-resurrection gap is recorded.
- `15.7-OPEN-ITEMS.md` open items 1 and 2 are marked answered by measurement citing exp11 only, with
  their original reasoning preserved; items 3 and 4 remain open; every ruling in that file is untouched.
- §§ 0, 1, 8, 9 agree with the rewritten § 5.
- One commit, force-added, containing both edited documents and only `.planning/` files.
</success_criteria>

<output>
Create `.planning/quick/260731-dbo-rewrite-engine-redesign-spec-section-5-w/260731-dbo-SUMMARY.md` when done
</output>
