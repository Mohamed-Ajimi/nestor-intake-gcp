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
