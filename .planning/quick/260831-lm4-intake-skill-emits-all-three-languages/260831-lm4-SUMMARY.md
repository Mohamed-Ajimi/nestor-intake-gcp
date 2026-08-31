---
quick_id: 260831-lm4
date: 2026-08-31
status: complete
description: "intake skill emits nl+fr+en for every generated string; UI and brief resolve per language"
tasks_completed: 4
tasks_total: 4
commits:
  - a374923: "feat(260831-lm4): intake skill output contract requires nl+fr+en"
  - d47b22a: "feat(260831-lm4): raise the apply budget to 20000 and fail loudly on truncation"
  - a2904a3: "fix(260831-lm4): resolve localized AI text to a scalar before it becomes a research question"
  - 5e78394: "feat(260831-lm4): one shared resolver renders localized AI text on all four surfaces"
files_modified:
  - backend/app/ai/prompts.py
  - backend/app/ai/skills/apply.py
  - backend/app/research/brief.py
  - backend/tests/test_ai_apply_skill.py
  - backend/tests/test_research_brief.py
  - frontend/src/lib/i18n/localizeSchema.ts
  - frontend/src/lib/i18n/localizeSchema.test.ts
  - frontend/src/components/intake/FieldRenderer.tsx
  - frontend/src/components/intake/FieldDisplay.tsx
  - frontend/src/components/intake/AIReviewPanel.tsx
  - frontend/src/components/intake/NestorBriefingPDF.tsx
deployed: false
spend: none
---

# Quick 260831-lm4 — the intake skill now speaks all three languages

Closes defect 1 from the 2026-08-31 intake test: the client answered in English, asked for
a French report, and Nestor proposed its modifications **in Dutch**. The skill now emits
every string it AUTHORS as `{"nl", "fr", "en"}`; the UI renders the active language and
the research brief resolves to the client's `report_language`.

**NOT DEPLOYED. NO RUN TRIGGERED. ZERO SPEND.** A research run was in flight throughout —
nothing here touched it.

## What changed, per task

**Task 1 — the output contract (`prompts.py`, commit `a374923`).** `NESTOR_INTAKE_SKILL_PROMPT`
gained a `LANGUAGE CONTRACT` block immediately before the JSON contract, and every
generated field in that contract now shows the three-key object inline (13 occurrences).
`current` / `original` are called out three separate times as verbatim quotes that are
never translated, and `original_index` / `type` / `domain` stay scalar codes (D-2).

Per D-1 the tuned Dutch principles were NOT translated. That is provable rather than
asserted: `git diff -U0` on the file shows every hunk at or after old line 76, so lines
58–75 (the principles and the four-domain filter) are byte-identical, and
`CONTEXT_PACK_SKILL_PROMPT` — which starts at old line 134 — has an empty diff.

**Task 2 — the budget and the truncation gate (`apply.py`, commit `d47b22a`).**
`_APPLY_MAX_TOKENS` 8192 → 20000, with the `~21333` non-streaming SDK ceiling named in a
comment and in a second constant so the number is checkable rather than folklore.
`_APPLY_USER_PREFIX` is now English. `call_fn` returns an `{error}` naming the budget when
`stop_reason == "max_tokens"`, read via `getattr` so the shared fixture needed no new knob.

**Task 3 — the $45 path (`brief.py`, commit `a2904a3`).** New `_resolve_localized`
(str passthrough → `lang` → `nl` → first present variant → `""`) and
`derive_report_language_code`, derived FROM `derive_report_language` so the two can never
disagree about the client's choice. `_item_text` routes `text` through it; both call sites
in `questions_from_answers` pass the client's language.

**Task 4 — one resolver, four surfaces (commit `5e78394`).** `localizeSchema.pick` is now
exported. `grep -rn "function pick\|localizeValue\|resolveLocalized" frontend/src` returns
exactly one definition, as the plan required. Display resolves; **every write keeps the raw
object** — the proposal toggle spreads the item, the AIReviewPanel upserts persist
`sug.suggested` / `q.text` unresolved.

## Three things the plan did not anticipate

**1. The `[DECISION]` block was a second dict-repr path, and a worse one.** The plan scoped
task 3 to `_item_text`. But `AIReviewPanel` overwrites the `decision_or_goal` ANSWER with
the skill's `suggested` value on accept, and `derive_decision_statement` read that answer
through `_first_nonempty`, which does `str(value)`. So the string the engine's Swiss
tournament ranks every candidate sub-question's materiality against would itself have been
`"{'nl': 'Moeten we uitbreiden?', ...}"`. The RED run printed exactly that, inside
`[DECISION]`. Fixed under the plan's own "apply the same resolution anywhere else in this
module" instruction: `_first_nonempty` gained an **opt-in** `lang` parameter defaulting to
`None`, so the sector/goals callers keep `str()` behaviour byte-for-byte and only the
decision field resolves.

**2. `FieldDisplay`'s `list` case was a crash, not a cosmetic bug.** The plan listed only
the `proposal_list` case. But the `list` case is the `research_questions` render path, and
`submitReview` patches `research_questions[idx].text` straight from `q.suggested`.
Rendering a `{nl, fr, en}` object as a React child throws *"Objects are not valid as a
React child"* and blanks the intake detail page. Fixed (Rule 1).

**3. `pick`'s last-resort scan had to be narrowed to the three locale keys.** My first
version scanned every value of the object. `NestorBriefingPDF.asString` hands `pick`
ARBITRARY answer objects, so a stakeholder row `{name, role, email}` would have "resolved"
to a name and been printed where a decision belongs — a silent wrong answer instead of a
visible `undefined`. Restricted to `nl`/`fr`/`en`; there is a named test for it.

Also fixed in the PDF: `asString` previously fell through to `JSON.stringify` for any
object it did not recognise, so an accepted `decision_or_goal` would have reached the
**client's** briefing PDF as a raw JSON blob (Rule 1).

## Proof of RED before GREEN

The plan required the task-3 test be proven RED against the pre-fix `_item_text`. It was,
twice — once mid-flight and once cleanly after I repaired the test-file damage described
below:

```
FAILED test_item_text_resolves_a_localized_question_to_a_scalar
FAILED test_item_text_falls_back_to_any_present_variant
FAILED test_localized_questions_reach_the_brief_in_the_clients_report_language
FAILED test_a_localized_decision_answer_never_reaches_the_decision_block_as_a_repr
4 failed, 22 passed in 0.14s
```

Exactly the 4 new tests failed and all 22 pre-existing tests passed in that same run —
which is also what proves I had not weakened the existing suite. After restoring the fix:
26 passed.

I did the same for task 2 even though the plan did not ask: with the guard surgically
removed, `test_apply_skill_truncated_response_fails_loudly` failed with
`a truncated response must terminate 'failed', got 'succeeded'` — i.e. a truncated
response was being recorded as a **successful** skill run.

## A mistake I made and caught

My first insertion into `test_research_brief.py` split a pre-existing test in half. I had
read the file only to line 394 and anchored my edit on `assert field["required"] is True`,
not knowing line 395 carried a second assertion — which my insertion pushed to the end of
the file, where it became an orphan referencing an out-of-scope `field` and raised
`NameError`. Caught because the test that "failed" reported an error that had nothing to do
with what it was testing. Repaired by restoring the line from `git show HEAD:` and
re-verifying: `git diff --stat` on that file now reports **123 insertions, 0 deletions** —
a pure addition, no existing line touched.

## Verification

| Check | Result |
|---|---|
| `pytest tests/ -q` (backend, full) | **450 passed**, 1 skipped, 4 pre-existing failures (below) |
| `pytest tests/test_research_brief.py` | 26 passed (22 + 4 new) |
| `pytest tests/test_ai_apply_skill.py` | 3 passed (2 + 1 new) — real Postgres via testcontainers |
| `npx tsc --noEmit` | **exit 0**, 0 errors |
| `npx vitest run` | **140 passed** (135 at HEAD + 5 new `pick` tests) |
| `node scripts/i18n-audit.mjs` | **PASS** (exit 0) — A/B/C clean, 107 pre-existing CHECK-D advisories, none in a file this task touched |
| `grep -n "Nederlands" backend/app/ai/prompts.py` | **one hit**, line 168 — the context-pack line (DEF-QK-01) |

Docker was available on this box, so the DB-backed suites really ran rather than skipping.

**The 4 backend failures are pre-existing and none is in a file this task changed** —
`test_ci_guard_raw_db` (trips on `app/research/run_task.py:247`), `test_mail_render`, and
two `test_research_runs_migration` cases that grep migration SOURCE text (one of them
matches `server_default` inside the migration's own docstring — the "grep matches prose
*about* the thing" trap). Detailed in `deferred-items.md`. ⚠️ I have not verified whether
these are also red in Cloud Build or only under this box's Python 3.14 — this appears to be
the first full-suite run recorded for them.

## Out of scope, recorded

**DEF-QK-01** — `CONTEXT_PACK_SKILL_PROMPT` (`prompts.py:168`) still carries an explicit
`Schrijf in vloeiend Nederlands`. That is a **stronger** form of the same defect than the
one just fixed: the intake prompt carried no language instruction at all and merely
produced Dutch because it was written in Dutch; the context pack is *told* to write Dutch.
Since `assemble_brief` folds the full pack into the brief verbatim, the `[CONTEXT PACK]`
section of every research brief is Dutch today regardless of the client's choice. Not a
copy-paste of this fix — the pack's output is markdown prose, so it needs a decision
between one pack in `report_language` or three packs. Full evidence in `deferred-items.md`.

Also unchanged per plan: no backfill of existing intakes (scalar passthrough is the
compatibility story, and it has named tests on both sides), and the
`structure_answers` / `extract_insights` skills.

## Known limitation

A `manual` operator edit in the AI review panel is persisted as a **plain string**, so it
carries only the language the operator typed in. That is deliberate and matches how `kept`
persists the client's own `current`: it is the operator's authorship, not a translation the
model produced, and inventing the other two variants would be putting words in their mouth.
Worth an operator ruling if per-language manual edits are ever wanted.

## Self-Check: PASSED

Files verified present:

- `backend/app/ai/prompts.py`, `backend/app/ai/skills/apply.py`, `backend/app/research/brief.py`
- `backend/tests/test_ai_apply_skill.py`, `backend/tests/test_research_brief.py`
- `frontend/src/lib/i18n/localizeSchema.ts`, `frontend/src/lib/i18n/localizeSchema.test.ts`
- `frontend/src/components/intake/{FieldRenderer,FieldDisplay,AIReviewPanel,NestorBriefingPDF}.tsx`
- `.planning/quick/260831-lm4-intake-skill-emits-all-three-languages/deferred-items.md`

Commits verified in `git log`: `a374923`, `d47b22a`, `a2904a3`, `5e78394`.

## Next

The operator's research run must finish first. Deploying `nestor-api` is what makes the
prompt + brief changes live; the frontend deploy is what makes the four render surfaces
live. **Both need the operator's explicit go-ahead** — the plan bans redeploying
`nestor-api` while a run is in flight. Nothing in this task is observable until then.
