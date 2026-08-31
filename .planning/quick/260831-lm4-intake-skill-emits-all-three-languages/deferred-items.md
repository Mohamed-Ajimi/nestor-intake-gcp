# Deferred Items — quick-260831-lm4

## DEF-QK-01 — the context-pack skill still hard-orders Dutch

**The same defect this task fixed, on a DIFFERENT skill.** Declared out of scope by the
plan: the operator reported the intake PROPOSALS, and the context pack is a separate
skill with a separate output shape (strict markdown, not JSON).

**Evidence**, `backend/app/ai/prompts.py:168` (`CONTEXT_PACK_SKILL_PROMPT`, principles
block):

```
- Schrijf in vloeiend Nederlands, niet in bulletted lijstjes per veld. Maak er
  prozaïsche, leesbare tekst van — behalve waar de structuur een lijst vereist
  (concurrenten, stakeholders).
```

This is an **explicit** language instruction, which makes it a stronger defect than the
one just fixed on `NESTOR_INTAKE_SKILL_PROMPT` — that prompt carried no language
instruction at all and merely produced Dutch because it was *written* in Dutch. Here the
model is *told* to write Dutch, so a French-report client's context pack is Dutch by
construction no matter what the intake says.

After this task, `grep -n "Nederlands" backend/app/ai/prompts.py` returns **exactly one
hit — this line**. That grep is the standing check for whether DEF-QK-01 is still open.

**Why it is not a copy-paste of this fix.** The context pack's output is markdown prose,
not a JSON object of fields, so there is no per-field object to localize. Fixing it means
choosing between (a) generating the pack in the client's `report_language` only —
cheapest, and the pack is an internal working document that also feeds
`brief.py::_decision_from_context_pack`, whose `_DECISION_LINE_RE` already tolerates the
English label `what must be decided` — or (b) three full packs. That is a decision, not
an edit. Note `assemble_brief` folds the FULL pack text into the brief verbatim, so
whichever language the pack is written in is the language the engine reads as context.

**Impact today:** the operator's context pack, and the `[CONTEXT PACK]` section of every
research brief, are Dutch for every client regardless of their chosen report language.

---

## Pre-existing backend test failures (out of scope, NOT caused by this task)

`python -m pytest tests/ -q` on this dev box reports **4 failed, 450 passed, 1 skipped**.
All four are pre-existing and none touches a file this task changed —
`git diff --name-only d1ee1bc..HEAD` lists only `app/ai/prompts.py`,
`app/ai/skills/apply.py`, `app/research/brief.py`, their two test modules, and six
frontend files.

| Test | Failure | Subject file (untouched here) |
|---|---|---|
| `test_ci_guard_raw_db::test_guard_passes_on_clean_app_tree` | D-03 raw-DB guard trips on `return get_engine()` | `app/research/run_task.py:247` |
| `test_mail_render::test_invite_carries_link` | rendered invite HTML lacks the expected action URL | `app/mail/` templates |
| `test_research_runs_migration::test_carries_grants` | GRANT string not found in the 0011 migration SOURCE | `alembic/versions/0011_*` |
| `test_research_runs_migration::test_0012_no_server_default_on_new_columns` | `server_default` matched **inside the migration's own docstring**, which explains why the column has none | `alembic/versions/0012_*` |

The last one is the documented "windowed grep matches prose *about* the thing" trap: the
assertion greps the raw module text, and the docstring sentence "with NO ``server_default``"
contains the very substring the test forbids. Whether these four are also red in Cloud
Build (vs. only under this box's Python 3.14 / local env) is unverified — this run is the
first full-suite execution recorded for them in this session.

---

## Stale docstring in `backend/tests/conftest.py` (trivial, deliberately not fixed)

`conftest.py:435` and `:456` still say the AI contract suites assert
`calls[0]["max_tokens"] == 8192`. That number is now **20000**. It is illustrative prose
in a fixture docstring, not an assertion, and `conftest.py` is outside this task's
declared file list — left alone rather than widened the change surface. Worth a one-line
fix in any future pass that touches that file.

---

## OPERATOR RULING 2026-08-31 — DEF-QK-01 is CLOSED: the context pack STAYS DUTCH

**Ruling, verbatim:** *"context pack should stay in dutch as the nestor admins are dutch speakers
anyways"*.

**The premise was checked and holds.** `ContextPackBlock` has exactly ONE render site —
`routes/admin.pulse.intakes.$id.tsx:1348`, an admin route. It is never rendered on a client route
(the `intake.$id.results.tsx:21` occurrence is a COMMENT, not a render). So the pack is an internal
artifact read by Dutch-speaking operators, and `CONTEXT_PACK_SKILL_PROMPT:168`'s explicit
*"Schrijf in vloeiend Nederlands"* is CORRECT rather than defective. **Do not "fix" it** — a future
reader who finds that line while grepping for the language defect will think it was missed.

**The one consequence, accepted:** `brief.py:648` folds `context_pack_text` into the engine prompt
**verbatim and untruncated**, and `derive_decision_statement` → `_decision_from_context_pack`
(`:448-505`) extracts the DECISION STATEMENT from it. That statement is what the engine's tournament
ranks claim materiality against. So on a `report_language: fr` run, the decision statement the engine
reasons against is Dutch while the report it writes is French — mixed-language input to a directive
that says *"Write EVERYTHING in {lang} and ONLY {lang} … Never mix languages"*. Judged workable and
mildly lossy, NOT a blocker. If a future run shows Dutch leaking into a non-Dutch report, this is the
first place to look.
