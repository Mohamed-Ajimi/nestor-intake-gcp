---
phase: quick-260731-dbo
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - .planning/ENGINE-REDESIGN-SPEC.md
autonomous: true
requirements: [QUICK-260731-dbo]
must_haves:
  truths:
    - "A reader of § 5 can see which Wave 4 diagnoses were disproved, by what measurement, and what replaced each one."
    - "No superseded claim is deleted — each is marked superseded and carries its measured replacement beside it."
    - "Every number written into § 5 traces to a measurement stated in this plan; no figure is invented."
    - "§ 5 no longer contradicts the rulings in 15.7-OPEN-ITEMS.md (tournament stays, loop must DISCOVER, losers never barred)."
    - "§ 0's cost baseline, § 1's decision table, § 8's Wave-4 verification row and § 9's knob list agree with the rewritten § 5."
    - "The honest limits of the measurement (n=1, temperature variance, harness-implemented stages) are stated in the document, not omitted."
    - "Nothing outside .planning/ changed — no tribunal/, backend/, frontend/ or infra/ file is touched."
  artifacts:
    - path: ".planning/ENGINE-REDESIGN-SPEC.md"
      provides: "Corrected Wave 4 section with measured diagnoses and the validated configuration"
      contains: "_CANDIDATE_PROMPT_CHARS"
  key_links:
    - from: ".planning/ENGINE-REDESIGN-SPEC.md § 5"
      to: ".planning/phases/15.7-*/15.7-OPEN-ITEMS.md"
      via: "ruling consistency — corrections change diagnoses and numbers, never operator rulings"
      pattern: "D-R9|D-R10|D-R11"
    - from: ".planning/ENGINE-REDESIGN-SPEC.md § 5"
      to: ".planning/ENGINE-REDESIGN-SPEC.md § 0 / § 8 / § 9"
      via: "shared cost and verification figures"
      pattern: "SUPERSEDED"
---

<objective>
Rewrite § 5 (Wave 4 — the creative workshop loop) of `.planning/ENGINE-REDESIGN-SPEC.md` so its defect
diagnoses match what local measurement actually showed, and record the validated Wave 4 configuration.

Purpose: this spec is the input to `/gsd-plan-phase 15.7`. Four of its five headline Wave-4 diagnoses
were disproved by a local harness (11 experiments, ~$3, scratchpad only — **no repo code was changed**)
that replayed the real V-01 run from the GCS audit log and then implemented the Wave 4 loop end-to-end.
If the spec is not corrected first, a planner will build fixes for problems that do not exist.

Output: an edited `.planning/ENGINE-REDESIGN-SPEC.md`, committed. Nothing else.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
</execution_context>

<context>
@.planning/ENGINE-REDESIGN-SPEC.md
@.planning/phases/15.7-research-engine-redesign-creative-workshop-loop-wave-4/15.7-OPEN-ITEMS.md

Section map of the file being edited (759 lines total):
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
</context>

<house_rules>
These apply to all three tasks. Violating any one of them fails the plan.

1. **DOC-ONLY.** The single file modified is `.planning/ENGINE-REDESIGN-SPEC.md`. Do not edit, create or
   delete anything under `tribunal/`, `backend/`, `frontend/`, `infra/`, or any test or config file.
   Source line numbers are quoted as *evidence*; they are not edit targets.
2. **Supersede, never silently delete.** Where a claim is now wrong, keep the original text visible,
   mark it `**SUPERSEDED (measured 2026-07-31)**`, and put the measured replacement beside it. A future
   reader must be able to see what was believed and why it was wrong. Strikethrough (`~~…~~`) plus a
   replacement sentence is the established convention in this file (see § 8 lines 691-692) — reuse it.
3. **Do not relitigate operator rulings.** D-R9 (tournament stays, Elo retained), D-R10 (the loop must
   DISCOVER, not only sharpen) and the rejected-register table — including *"losers are NEVER barred"* —
   stay. Correct diagnoses and numbers, not rulings.
4. **No invented figures.** Every number written into the spec must be one stated in this plan. If a
   number is needed that is not here, write the qualitative claim without a number instead.
5. **`.planning/` is gitignored** in this repo. Any commit of these files must use `git add -f`.
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
  - Sonnet's evolve runs at **temperature 1.0**, so single runs vary — three runs of the same
    configuration exited at **rounds 4, 6 and 6**;
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
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && for s in "_CANDIDATE_PROMPT_CHARS = 240" "KEEP=1/WEAK=17" "KEEP=9/WEAK=9" "245–373" "n=1" "temperature 1.0" "rounds 4, 6 and 6" "DESIGN, not any" "_match_block" "SUPERSEDED"; do grep -qF "$s" "$F" || { echo "MISSING: $s"; exit 1; }; done && git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; echo OK</automated>
  </verify>
  <done>§ 5 opens with a dated measurement-provenance subsection carrying the three honest limits verbatim; the "9 of 10 winners WEAK" line is marked superseded and explained as a cap-240 truncation artefact with both measured critique splits recorded; no file outside `.planning/` is modified.</done>
</task>

<task type="auto">
  <name>Task 2: Correct the exit rule, the cost/population estimate, and record the validated configuration</name>
  <files>.planning/ENGINE-REDESIGN-SPEC.md</files>
  <action>
Edit the boxed items 3 and 4, `### Exit criteria` (584-606) including its boxed trap warning, `### Why
10 rounds is affordable` (608-624), and `### Freeze and hand-off` (626-628).

**(a) The exit rule fires; it needs NO change.** Boxed item 3 and open item 1 of 15.7-OPEN-ITEMS.md
both assume the loop hits the 10-round cap every run because criterion 2 can never be satisfied. Mark
that **resolved by measurement**: with the cap fixed, the implemented loop exits on all three criteria
in **round 6** (10-slot config) and **round 9** (17-slot config). WEAK winners went **3 → 3 → 0 → 0**;
the three criteria genuinely gate each other in turn. Record explicitly: **keep all three exit criteria
exactly as written** — the *"the cap is a ceiling, not a target"* sentence at line 619-620 is
**confirmed**, not contradicted.

**(b) Add a fourth exit-criteria action — the single highest-leverage rule found: PREFER KEEP OVER WEAK
WHEN FILLING A SLOT.** Explain why it matters: exit criterion 2 *checks* for WEAK winners but nothing
in the design ever *prevented* them. Adding the action took WEAK winners to **0** and made criterion 2
satisfiable by construction.

**(c) Add the compound-question exemption to criterion 2.** A cross-cutting question is **compound by
construction** — it joins two topics — so *"two questions in one"* must **not** count against it in the
exit check. Without the exemption, criterion 2 structurally penalises the highest-value questions.

**(d) The population does not balloon and the cost estimate is ~30× too high.** Mark the
`Why 10 rounds is affordable` table's **~$3.00 for 10 rounds** superseded. Measured in the global
design: population peaks at **23–32**, largest prompt **~9k chars**, total cost **$0.18–$0.48**. The
WEAK-after-two-passes pruning removes candidates faster than evolve adds them. Conclude that **the
spend ceiling and a population cap are not binding at this scale** — replace them with
**instrumentation** (log population and spend per round) rather than enforced caps, and rewrite boxed
item 4 accordingly.

**IMPORTANT NUANCE that must survive the edit:** the feared 60-candidate explosion **IS real**, but
only under **per-client-question brackets**, where the population peaks at **122**. It is
architecture-dependent, not inherent. Do not delete the warning — scope it.

**(e) Record the VALIDATED CONFIGURATION** as a new subsection before `### Freeze and hand-off`:
  - **ONE global loop**, NOT per-client-question brackets. Per-client-question brackets were tested and
    fail on four counts: they never converge, they hit the 10-round cap, they cost **3–4×** more, the
    population reaches **122**, and — the structural reason — inside one bracket evolve cannot
    **COMBINE across client questions**, which is where the best output came from.
  - Winners = a **floor of 5 per client question + 2 cross-cutting**, applied at the **CUT** rather than
    by splitting the pool.
  - Prefer KEEP over WEAK when filling a slot (from (b)).
  - Measured result of that configuration: **17 questions, none weak, converges in round 9, $0.48**.

**(f) Fix the two spec-internal defects while editing:**
  - The boxed trap warning at 593-599 says to exclude resurrected candidates from **"criterion 1"**.
    That is an off-by-one: criterion 1 is **COVERAGE** and criterion 2 is **QUALITY**; excluding them
    from coverage breaks the very guarantee resurrection exists to provide. Correct it to **criterion
    2**, and add a one-line note that the same off-by-one is present in `15.7-OPEN-ITEMS.md` and must be
    corrected there when that file is next touched (do **not** edit that file in this task).
  - Half of that guard is already built and half is missing: `workshop_rank.py:688` sets
    `entry["resurrected"] = True` for Guard 1, but **Guard 2 does not** — at `workshop_rank.py:708`,
    when critique kills everything, it rewrites every candidate to `KEEP` **unmarked**, so the one case
    where quality most needs to read as failed reads as a perfect pass. Record this as a Wave-4
    implementation requirement.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && for s in "round 6" "round 9" "3 → 3 → 0 → 0" "23–32" "9k chars" "0.18" "0.48" "122" "PREFER KEEP OVER WEAK" "compound by construction" "floor of 5 per client question" "criterion 2" "workshop_rank.py:708" "instrumentation"; do grep -qF "$s" "$F" || { echo "MISSING: $s"; exit 1; }; done && grep -qF "exclude resurrected candidates from criterion 1" "$F" && { echo "FAIL: off-by-one not corrected"; exit 1; }; git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; echo OK</automated>
  </verify>
  <done>Boxed items 3 and 4 are marked resolved by measurement; all three exit criteria are retained and joined by the prefer-KEEP action and the compound-question exemption; the ~$3.00 estimate is superseded by $0.18–$0.48 with the 122-peak bracket nuance preserved; the validated configuration is recorded; the criterion-1/2 off-by-one and the Guard-2 marking gap are both written down.</done>
</task>

<task type="auto">
  <name>Task 3: Replace D-R11 with the catch-up schedule, fix D-R10's admission test, and reconcile the citing sections</name>
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
rewrite:
  - **§ 0 cost baseline (31-44)** — the workshop-cost framing there predates the loop measurement. Add
    a line pointing to § 5's measured loop total of **$0.18–$0.48** so a reader does not carry the
    ~$3.00 loop estimate forward. Do not alter the V-01 per-stage measurements themselves — they are
    audit-log facts.
  - **§ 1 decision table (50-62)** — amend the **D-R11** row so it reads as the catch-up schedule with
    median-seeding marked superseded, and annotate **D-R10** with the premise-real admission test. Do
    not change their `agreed (operator)` status.
  - **§ 8 Wave-4 verification row (693)** — it currently says *"a resurrected candidate does not satisfy
    coverage"*. That is the same off-by-one Task 2 fixed: it must be **quality**, not coverage. Also add
    the catch-up-schedule newcomer test and the prefer-KEEP check to that row.
  - **§ 9 knobs (720-731)** — the new-knob list names a *"loop spend ceiling"*. Per Task 2 that becomes
    instrumentation rather than an enforced cap; adjust the entry and add a knob for the catch-up
    schedule's match budget.

**(e) Commit.** `.planning/` is gitignored, so use `git add -f` for the spec and this plan directory.
Commit message: `docs(15.7): correct ENGINE-REDESIGN-SPEC § 5 against local Wave 4 measurement`.
Verify before committing that `git status --porcelain -- tribunal backend frontend infra` is empty.
  </action>
  <verify>
    <automated>cd "$(git rev-parse --show-toplevel)" && F=.planning/ENGINE-REDESIGN-SPEC.md && for s in "catch-up schedule" "byte-identical" "1.5%" "93.8%" "95.5%" "99.8%" "29.5%" "1.8%" "3.76" "5 Swiss rounds" "groundingChunks" "PREMISE" "workshop_rank.py:878" "workshop_rank.py:1524"; do grep -qF "$s" "$F" || { echo "MISSING: $s"; exit 1; }; done && grep -qF "a resurrected candidate does **not** satisfy coverage" "$F" && { echo "FAIL: stale wave-4 verification row"; exit 1; }; git status --porcelain -- tribunal backend frontend infra | grep . && { echo "FAIL: non-doc files changed"; exit 1; }; git log -1 --name-only --format=%s | grep -q "ENGINE-REDESIGN-SPEC" && echo OK</automated>
  </verify>
  <done>D-R11 is replaced by the catch-up schedule with the inertness proof and all six measured percentages recorded; D-R9 is confirmed with the 3.76-matches figure and the D-R9/D-R11 interaction noted; D-R10's admission test tests the premise and mandates `groundingChunks` evidence; §§ 0/1/8/9 no longer contradict § 5; the spec is committed with `git add -f` and no source file is in the commit.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| planning doc → 15.7 planner | This file is the input prompt to `/gsd-plan-phase 15.7`; a wrong number here becomes built code |
| none (runtime) | Doc-only change — no code, no request path, no new dependency, no package install |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-QDBO-01 | Tampering | `.planning/ENGINE-REDESIGN-SPEC.md` content | mitigate | House rule 4 forbids invented figures; every task's `<automated>` gate greps for the exact measured literals so a paraphrased or drifted number fails the gate |
| T-QDBO-02 | Repudiation | superseded claims | mitigate | House rule 2 forbids silent deletion — the original claim stays visible beside its replacement, so the change is auditable |
| T-QDBO-03 | Elevation of Privilege | scope creep into `tribunal/` source | mitigate | Every task's gate asserts `git status --porcelain -- tribunal backend frontend infra` is empty; cited source line numbers are evidence, not edit targets |
| T-QDBO-SC | Tampering | npm/pip/cargo installs | accept | No package-manager install occurs in this plan — the legitimacy gate is not applicable |
</threat_model>

<verification>
1. All three task gates pass.
2. `git status --porcelain -- tribunal backend frontend infra` is empty — the doc-only constraint held.
3. The rulings survive: `grep -c "we are not killing tournament\|never barred\|must DISCOVER"` still
   matches in `.planning/ENGINE-REDESIGN-SPEC.md` — corrections changed diagnoses, not rulings.
4. Spot-read § 5 end to end: a reader who knows nothing of the harness can tell, for each of the five
   headline diagnoses, whether it survived, what measurement decided it, and what replaced it.
</verification>

<success_criteria>
- `.planning/ENGINE-REDESIGN-SPEC.md` § 5 states its measurement provenance, its three honest limits,
  and the validated configuration (one global loop, 5+2 floor at the cut, prefer KEEP over WEAK).
- The four disproved diagnoses — WEAK-winner quality signal, the never-firing exit rule, the balloon
  population/$3.00 cost, and median Elo seeding — are each marked superseded with their measured
  replacement, and D-R9 is marked confirmed.
- D-R10's admission test verifies the premise is real and requires `groundingChunks` evidence.
- The criterion-1/criterion-2 off-by-one is fixed in both § 5's boxed warning and § 8's Wave-4 row, and
  the Guard-2 (`workshop_rank.py:708`) unmarked-resurrection gap is recorded.
- §§ 0, 1, 8, 9 agree with the rewritten § 5.
- One commit, force-added, containing only `.planning/` files.
</success_criteria>

<output>
Create `.planning/quick/260731-dbo-rewrite-engine-redesign-spec-section-5-w/260731-dbo-SUMMARY.md` when done
</output>
