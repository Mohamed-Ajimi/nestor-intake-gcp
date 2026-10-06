---
phase: quick-261006-jgn
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/app/api/intake_routes.py
  - backend/tests/test_intake_project_name_seed.py
  - backend/tests/test_mail_greeting.py
  - .planning/phases/23.5-tester-remarks-round-1-superadmin-status-override-real-archi/deferred-items.md
  - frontend/src/lib/intake-display.ts
  - frontend/src/lib/intake-display.test.ts
  - frontend/src/components/intake/FieldDisplay.tsx
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/components/intake/NextStepBanner.tsx
  - frontend/src/components/admin/adminNav.ts
  - frontend/src/components/admin/ProductShell.tsx
  - frontend/src/routes/admin.pulse.tsx
  - frontend/src/routes/admin.users.tsx
  - frontend/src/routes/admin.spaces.tsx
autonomous: true
requirements: [QUICK-261006-JGN]

must_haves:
  truths:
    - "Creating an intake with a project name on the new-intake screen pre-fills the form answer project_name with that value (admin types it once)"
    - "The admin intake header reads '<organisation> — <project>', collapses to one value when equal or when one side is missing"
    - "Every client mail (intake, validation, reminder, results, report delivery) greets the first name of the contact_name answer, or the template's own fallback (team / équipe) when there is none"
    - "Stakeholder rows in the admin view show name, role and expectation; research questions render exactly as before (V1. text, kind, rationale)"
    - "The users and spaces manage pages show the full Pulse nav (new intake / intakes / clients / search) plus the Manage block, with no link rendered twice"
    - "On the intake detail page the next-step panel (banner + AI tools + search) is a full-width block under the step tracker; the sections content uses the full width"
    - "The sections nav stays in view while scrolling and scrolls internally when taller than the viewport"
  artifacts:
    - path: "frontend/src/lib/intake-display.ts"
      provides: "pure helpers objectListTextKey + deriveIntakeHeaderTitle"
      exports: ["objectListTextKey", "deriveIntakeHeaderTitle"]
    - path: "frontend/src/lib/intake-display.test.ts"
      provides: "vitest for both helpers"
    - path: "frontend/src/components/admin/adminNav.ts"
      provides: "shared PULSE_NAV const next to ADMIN_NAV"
      contains: "export const PULSE_NAV"
    - path: "backend/tests/test_mail_greeting.py"
      provides: "greeting tests (contact first name, fallback, localized, escaped)"
    - path: "backend/tests/test_intake_project_name_seed.py"
      provides: "project_name seeding tests"
  key_links:
    - from: "backend/app/api/intake_routes.py::_run_intake_send and ::_send_report_mail"
      to: "intake_answers.contact_name"
      via: "read answer row, resolve localized, first whitespace token -> first_name"
      pattern: "first_name=greeting"
    - from: "backend/app/api/intake_routes.py::create_intake"
      to: "intake_answers.project_name"
      via: "pg_insert ... on_conflict_do_nothing on uq_intake_answers_intake_field"
      pattern: "project_name"
    - from: "frontend/src/components/intake/FieldDisplay.tsx"
      to: "frontend/src/lib/intake-display.ts"
      via: "objectListTextKey(subFields)"
      pattern: "objectListTextKey"
    - from: "frontend/src/routes/admin.users.tsx, admin.spaces.tsx, admin.pulse.tsx"
      to: "PULSE_NAV"
      via: "items={PULSE_NAV}"
      pattern: "items=\\{PULSE_NAV\\}"
---

<objective>
Tester feedback round: six small admin UX + mail fixes (items 1, 2a, 2b, 3, 4, 6, 7 of the brief).
Code changes only; the orchestrator deploys to DEV (project-cb01b861-cb4a-438d-b9a) afterwards.
NO migration. NO edits under `frontend/src/components/ui/`. Use `npm ci`, never `npm install`.

Purpose: remove double data entry (project name), make greetings address a person, stop dropping
stakeholder data in the admin view, and fix navigation/layout friction on the admin screens.
Output: one backend commit, two frontend commits, each atomic and code-only.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@./CLAUDE.md
@.planning/STATE.md

Executor runs in the MAIN tree (no worktree). Commit each task atomically (code only, `git add`
the listed code files explicitly). Do not deploy. `.planning/` is gitignored — the deferred-items
edit in Task 1 is left for the orchestrator to commit (do NOT include it in the code commit).

<interfaces>
<!-- Extracted from the codebase. Use directly; no exploration needed beyond the read_first lines. -->

backend/app/api/intake_routes.py
- `create_intake(body: IntakeCreate, space_id, repo: IntakeRepository, identity)` at ~585-619.
  `values = body.model_dump(exclude_unset=True)`; superadmin -> `repo.create_in_space(uuid.UUID(space_id), **values)`,
  user -> `repo.create(**values)`; returns `_view(intake)`. `values.get("client_name")` is the
  create-screen value (labelled "project name" since D-23.5-03).
- DB triggers on intake insert (alembic 0008): BEFORE INSERT sets `intakes.client_name := org name`
  when the body left it empty; AFTER INSERT seeds answer `client_name = org name`
  (`INSERT ... ON CONFLICT (intake_id, field_key) DO NOTHING`). So answer `client_name` = organisation.
  => Seed `project_name` from the BODY value only, never from `intake.client_name` (which may be the
  trigger-mirrored org name).
- Both create paths set the tx-local GUC `app.current_space_id` to the target space before insert
  (user repo by construction; `create_in_space` calls `set_space_context`), so a direct insert into
  `intake_answers` with `space_id=intake.space_id` passes RLS WITH CHECK on the same `repo.session`.
- Answer storage shape (frontend split + `IntakeAnswerRepository.upsert_batch`): a plain string goes
  in column `value` (Text), lists/objects go in `value_json` (JSONB). Unique constraint name:
  `uq_intake_answers_intake_field`. Model: `app.db.models.intake.IntakeAnswer`
  (`space_id`, `intake_id`, `field_key`, `value`, `value_json`).
- `app.intake_canonical.canonical_field(field_key: str) -> dict | None` (already imported module
  `app.intake_canonical` at line ~57) — the single canonical template (D-CANON); `canonical_field("project_name")`
  is non-None for `pulse_intake_v1.json`.
- `_run_intake_send(...)` ~1264-1370: `client = intake.client_name or "team"`; passes
  `first_name=client` to `mail_render.render_results` / `render_intake` / `render_validation`
  (~1343-1365). Session available as `repo.session`.
- `_send_report_mail(session, identity, intake, recipient_ids) -> bool` ~2212-2260: same
  `first_name=client` into `mail_render.render_results`.
- Comment block ~925-953 above `_SUBJECT_VALIDATION` documents the greeting defect as deferred.
- `app.research.brief._resolve_localized(value: Any, lang: str = "") -> str` — PURE, never raises:
  str passes through; dict -> value[lang] -> value["nl"] -> first non-empty variant; else "".
  brief.py imports only `re` / `typing` (safe to import from intake_routes).
- Mail templates (`app/mail/templates/{nl,fr,en}/{intake,validation,results}.html.j2`) render
  `{{ first_name or "team" }}` (nl/en) and `{{ first_name or "équipe" }}` (fr). Autoescape is ON
  (`tests/test_mail_locale.py::test_render_autoescape_on_in_every_variant`). render signature types
  `first_name: str` — pass `""` for "no name" so the template fallback applies.
- Subjects keep `client` (= intake.client_name) — DO NOT change `_subject_for(...)` calls or the
  `project_title=client` kwarg.
- Test patterns: `tests/test_mail_endpoints.py` (fixtures `engine`, `set_space`, `two_spaces`,
  `fake_resend`, `superadmin_engine`, helpers `_insert_intake`, `_insert_member`, `_build_intake_app`,
  `_patch_engine_factories`); `tests/test_intake_routes.py::test_create_and_list_intake_in_own_space`
  for the create route.

frontend
- `frontend/src/lib/i18n/localizeSchema.ts`: `export function pick(value: unknown, lang: string): string | undefined`
  (type-only imports; safe in vitest `environment: "node"`, include `src/**/*.test.ts`).
- `frontend/src/lib/intake-types.ts`: `IntakeField` type (`key`, `type`, `label`, `item`, ...).
- Canonical object-list fields: `research_questions.questions` item fields `[text:longtext, kind:select]`;
  `stakeholders.stakeholders_list` item fields `[name:text, role:text, expectation:longtext]`.
  No other object lists exist.
- `FieldDisplay.tsx` ~159-210 `case "list"`: `const textKey = subFields.find((sf) => sf.key === "text" || sf.type === "longtext")?.key;`
  — the `|| sf.type === "longtext"` arm is the stakeholder bug. Sub-field labels are already localized
  by `localizeSchema` (it recurses into `item.fields`). `FieldDisplay` returns null for empty optional values.
  `isFieldDisplayEmpty` (line ~91) uses `isEmpty(value)` only — no heuristic; no other consumer of the
  longtext heuristic exists in `frontend/src` (grep confirmed: only FieldDisplay.tsx:165).
- `admin.pulse.intakes.$id.tsx`: answers resolved on read (`resolveAnswerValue(...)` ~494) into
  `answersMap: Map<string, {value}>`; `client` set ~478 as `{ name: v.client_name, ... }` (= intake.client_name).
  Header title ~1170-1177 (`projectNameAnswer`, `projectNameStr`, `headerTitle`); i18n key
  `admin:intakeDetail.unknownClient` exists (nl/fr/en) — may become unused, leave the key.
  Sticky page header ~1193-1196 (`sticky top-0 z-20 ... px-6 py-4`), ends with optional statusHint ~1329.
  Workflow card (IntakeWorkflowStepper + status banner + run history) ~1361-1407.
  2-col grid ~1410-1411 `grid grid-cols-1 xl:grid-cols-[1fr_272px] ...`, rail `<aside ... xl:sticky xl:top-[88px]>`
  ~1413-1493 containing: `<div className="border border-ink/15 bg-paper">` -> `NextStepBanner` (21 props),
  `AISkillsPanel intakeId intakeStatus`, and the `showSemanticSearch` search section (input, button, results).
  Content column `<div className="min-w-0 xl:col-start-1 xl:row-start-1">` ~1495 -> edit banner ->
  `grid lg:grid-cols-[240px_1fr]` -> `<aside className="hidden lg:block"><nav className="sticky top-28 space-y-1">` ~1502-1503.
- `ProductShell.tsx`: outer `flex min-h-screen overflow-x-clip`; right column `flex flex-1 flex-col overflow-hidden`
  holds `<TopBar />` (root `h-11`, 44px) and `<main className="flex-1 overflow-y-auto ...">` — `main` IS the scroll
  container, so `sticky` inside the page is relative to `main` (works; no other overflow ancestor in between).
  Manage block guard `{isSuperadmin && items !== ADMIN_NAV && (...)}` ~94.
- `NextStepBanner.tsx` (457 lines) root ~416-436: `<div className="border-t border-ink/10 border-l-4 bg-paperLight px-6 py-5" style={{borderLeftColor}}>`
  -> title div -> body div (`mb-4 ...`) -> `{actions && <div className="flex flex-wrap gap-2">{actions}</div>}` -> AlertDialog.
  Returns null in `default`. Also referenced from `admin.sales.projects.$id.tsx` — default layout must stay byte-identical in behaviour.
- `admin.pulse.tsx` passes an inline 4-item array (nav.pulseNewIntake exact, nav.pulseIntakes, nav.pulseClients, nav.pulseSearch exact).
  `admin.users.tsx:165` / `admin.spaces.tsx:116`: `<ProductShell product={t("shell.productManage")} items={ADMIN_NAV}>`.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Backend — seed project_name on create (2a) + greet contact first name in every client mail (3)</name>
  <files>backend/app/api/intake_routes.py, backend/tests/test_intake_project_name_seed.py, backend/tests/test_mail_greeting.py, .planning/phases/23.5-tester-remarks-round-1-superadmin-status-override-real-archi/deferred-items.md</files>
  <read_first>backend/app/api/intake_routes.py lines 585-619, 925-953, 1264-1370, 2212-2260; backend/tests/test_mail_endpoints.py lines 1-230 (fixtures/helpers); backend/tests/test_intake_routes.py around test_create_and_list_intake_in_own_space (~190); backend/app/research/brief.py lines 237-275</read_first>
  <behavior>
    - Seed: POST /intakes with client_name="Marktintrede Benelux" -> an intake_answers row field_key="project_name", value="Marktintrede Benelux", value_json NULL, space_id = intake.space_id.
    - Seed: POST /intakes with no client_name (or blank/whitespace) -> NO project_name row (never seeds the trigger-mirrored org name).
    - Seed: superadmin create (?space_id=...) also seeds; the existing client_name answer (org name from the 0008 trigger) is untouched.
    - Seed: an existing project_name row is never overwritten (ON CONFLICT DO NOTHING).
    - Greeting pure helper: "Sam De Smet" -> "Sam"; "  Sam  " -> "Sam"; {"nl":"Jan Peeters","fr":"Jean","en":"John"} -> "Jan" (nl-first resolution); None / "" / "   " / {} / 42 -> "".
    - Greeting endpoint: validation mail for an intake whose contact_name answer is "Sam De Smet" -> sent html contains "Hi Sam" and does NOT contain "Hi <intake.client_name>"; subject still contains intake.client_name.
    - Greeting endpoint: no contact_name answer -> html contains "Hi team" (nl/en) / "Bonjour équipe" (fr recipient).
    - Greeting endpoint: contact_name "<b>x</b> Doe" -> html contains "&lt;b&gt;x&lt;/b&gt;" and not "<b>x</b>".
    - Report delivery (`_send_report_mail`) uses the same greeting (one test via the existing report-delivery fixture pattern in tests/test_report_delivery.py, or a direct call with fake_resend).
  </behavior>
  <action>
    (2a) In `create_intake`, after the intake row is created on either path, seed the form answer `project_name`
    from the create-screen value. Add a module helper `_seed_project_name_answer(session, intake, project_name: str | None) -> None`:
    strip the value; return if empty; return if `canonical_field("project_name")` is None (template has no such field);
    otherwise execute a postgres `insert(IntakeAnswer)` (sqlalchemy.dialects.postgresql `insert`, already the pattern in
    app/db/repository.py) with `space_id=intake.space_id`, `intake_id=intake.id`, `field_key="project_name"`,
    `value=<stripped str>`, `value_json=None`, `.on_conflict_do_nothing(constraint="uq_intake_answers_intake_field")`,
    on `repo.session`, then flush. Pass `values.get("client_name")` (the BODY value) — NEVER `intake.client_name`
    (the BEFORE-INSERT trigger may have mirrored the org name into it). String goes in `value`, matching the
    answers API split (string -> value). Do not route through `check_answer_batch` (server-side seed, not a client write).
    Import `IntakeAnswer` from `app.db.models.intake` and `canonical_field` from `app.intake_canonical` if not already imported.

    (3) Add a PURE helper `_greeting_first_name(raw: Any) -> str`: resolve with
    `from app.research.brief import _resolve_localized` (reuse, do not re-implement), strip, return the first
    whitespace token or "" when nothing remains. Add `_contact_first_name(session, intake) -> str`: select the
    `IntakeAnswer` row where `intake_id == intake.id AND space_id == intake.space_id AND field_key == "contact_name"`;
    raw = `value_json` if not None else `value`; return `_greeting_first_name(raw)`; return "" when no row.
    The contact is the form answer "Naam primaire contactpersoon" — NOT the invited user/recipient name.
    In `_run_intake_send` compute `greeting = _contact_first_name(repo.session, intake)` once (before the locale loop)
    and replace the three `first_name=client` kwargs with `first_name=greeting`. In `_send_report_mail` do the same with
    its `session`. Keep `project_title=client` and every `_subject_for(..., client)` unchanged (subjects and list keep
    intake.client_name per brief). Passing "" makes the templates' own `or "team"` / `or "équipe"` fallback apply.
    Keep autoescape; never add `| safe` or Markup. Do not edit the templates.

    Rewrite the last paragraph of the comment block ~945-952 ("They also pass `first_name=client` ... deferred, see
    deferred-items.md") to state: bodies now greet the first name of the `contact_name` form answer (quick 261006-jgn),
    falling back to the template's team/équipe word when the answer is empty.
    In `.planning/phases/23.5-.../deferred-items.md` section `DEF-23.5-03-03`, change `**Status:**` to
    "FIXED 2026-10-06 by quick 261006-jgn — greets the first name of the contact_name answer; template fallback when empty."
    (leave the rest of the entry as history). Do NOT git-add this file (orchestrator commits docs).

    Tests: create `tests/test_intake_project_name_seed.py` (copy fixture/app-building pattern from
    test_intake_routes.py / test_mail_endpoints.py) and `tests/test_mail_greeting.py` (pure-helper tests need no DB;
    endpoint tests use `fake_resend` and assert on the captured html). Write tests first (RED), then implement (GREEN).
  </action>
  <verify>
    <automated>cd backend && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest tests/test_mail_greeting.py tests/test_intake_project_name_seed.py tests/test_mail_endpoints.py tests/test_mail_locale.py tests/test_mail_render.py tests/test_report_delivery.py tests/test_intake_routes.py -q</automated>
    Then the FULL backend suite (Docker Desktop must be up — testcontainers): `cd backend && ~/AppData/Local/Programs/Python/Python312/python.exe -m pytest -q` — report passed/failed/skipped counts. Pre-existing unrelated failures (e.g. DEF-23.5-04-01 is tribunal-side, not in this suite) must be named, not hidden.
    Gate: `grep -v '^\s*#' backend/app/api/intake_routes.py | grep -c "first_name=client"` == 0 and `grep -c "first_name=greeting" backend/app/api/intake_routes.py` >= 4.
  </verify>
  <done>New tests pass; full backend suite green (counts reported); no `first_name=client` left in code; subjects unchanged; commit `fix(261006-jgn): seed project_name answer on create; greet contact first name in client mails` containing only the backend files.</done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Frontend — stakeholder rows render all sub-fields (4) + header "organisation — project" (2b)</name>
  <files>frontend/src/lib/intake-display.ts, frontend/src/lib/intake-display.test.ts, frontend/src/components/intake/FieldDisplay.tsx, frontend/src/routes/admin.pulse.intakes.$id.tsx</files>
  <read_first>frontend/src/components/intake/FieldDisplay.tsx lines 155-215; frontend/src/routes/admin.pulse.intakes.$id.tsx lines 1165-1180; frontend/src/lib/i18n/localizeSchema.ts lines 30-60</read_first>
  <behavior>
    - objectListTextKey([{key:"text",type:"longtext"},{key:"kind",type:"select"}]) === "text" (research questions — unchanged path).
    - objectListTextKey([{key:"name",type:"text"},{key:"role",type:"text"},{key:"expectation",type:"longtext"}]) === undefined (stakeholders fall through to all-sub-field render).
    - objectListTextKey([]) === undefined.
    - deriveIntakeHeaderTitle({organisation:"Acme NV", project:"Marktintrede", intakeClientName:"x", fallback:"F", lang:"nl"}) === "Acme NV — Marktintrede".
    - organisation missing/blank -> "Marktintrede"; project answer missing -> falls back to intakeClientName; both equal case-insensitively after trim ("nestor" / " Nestor ") -> "nestor" (organisation's spelling) shown once.
    - localized organisation {nl:"Acme NL",fr:"Acme FR",en:"Acme EN"} with lang "fr" -> "Acme FR"; with lang "de" -> nl variant (pick's fallback).
    - neither organisation, project, nor intakeClientName -> fallback.
  </behavior>
  <action>
    Create `frontend/src/lib/intake-display.ts` (pure, no React; file comment says so like intake-phase.ts) exporting:
    `objectListTextKey(subFields: Pick<IntakeField, "key">[]): string | undefined` — returns "text" only when a sub-field
    with key "text" exists (per brief item 4: the question-style path is for rows whose sub-fields include key `text`);
    and `deriveIntakeHeaderTitle(input: { organisation: unknown; project: unknown; intakeClientName: string | null | undefined; fallback: string; lang: string }): string`
    — resolve organisation/project via `pick(value, lang)` from `@/lib/i18n/localizeSchema` (handles plain string and {nl,fr,en});
    trim; project falls back to trimmed intakeClientName; if both present and equal case-insensitively return organisation once;
    both -> `${organisation} — ${project}` (em dash, same as today); one -> that one; none -> fallback.
    Write `intake-display.test.ts` with the behavior cases first (RED), then implement.

    FieldDisplay.tsx: replace the inline `subFields.find((sf) => sf.key === "text" || sf.type === "longtext")?.key` with
    `objectListTextKey(subFields)`. Leave the research-question render block untouched (V{i+1}., pick text, kind, rationale) so
    questions render exactly as before. Stakeholder rows now fall through to the existing per-sub-field `FieldDisplay`
    branch; give each fallthrough row a light separator so rows are distinguishable (e.g. add `border-l-2 border-ink/15 pl-3`
    to the existing `space-y-1` wrapper) — no new copy. `isFieldDisplayEmpty` needs no change (it has no heuristic; grep confirmed
    FieldDisplay.tsx:165 is the only consumer of the longtext heuristic).

    admin.pulse.intakes.$id.tsx ~1170-1177: replace `projectNameAnswer`/`projectNameStr`/`headerTitle` with
    `deriveIntakeHeaderTitle({ organisation: answersMap.get("client_name")?.value, project: answersMap.get("project_name")?.value, intakeClientName: client?.name, fallback: intake.title || intake.product?.name || "", lang: i18n.language })`.
    Organisation = form answer `client_name` (seeded with the org name by the 0008 trigger); project = answer `project_name`
    falling back to intake.client_name. Do NOT change the intake LIST page or any mail subject. If `projectNameStr` is used
    elsewhere in the file, keep a local equivalent so nothing else changes. No new i18n keys expected; if any copy is added,
    add nl/fr/en keys.
  </action>
  <verify>
    <automated>cd frontend && npx vitest run src/lib/intake-display.test.ts && npx tsc --noEmit</automated>
    Gate: `grep -c 'sf.type === "longtext"' frontend/src/components/intake/FieldDisplay.tsx` == 0; `grep -c "objectListTextKey" frontend/src/components/intake/FieldDisplay.tsx` >= 1; `grep -c "deriveIntakeHeaderTitle" "frontend/src/routes/admin.pulse.intakes.\$id.tsx"` >= 1.
  </verify>
  <done>Helper tests pass; tsc 0 errors; commit `fix(261006-jgn): admin stakeholder rows show all fields; header shows organisation — project` with only these 4 frontend files.</done>
</task>

<task type="auto">
  <name>Task 3: Frontend layout — full Pulse nav on manage pages (1), next-step panel full-width under tracker (6), sticky sections nav (7)</name>
  <files>frontend/src/components/admin/adminNav.ts, frontend/src/components/admin/ProductShell.tsx, frontend/src/routes/admin.pulse.tsx, frontend/src/routes/admin.users.tsx, frontend/src/routes/admin.spaces.tsx, frontend/src/routes/admin.pulse.intakes.$id.tsx, frontend/src/components/intake/NextStepBanner.tsx</files>
  <read_first>frontend/src/routes/admin.pulse.intakes.$id.tsx lines 1190-1200 and 1358-1530 (find the closing tags of the xl grid and the content column before editing); frontend/src/components/intake/NextStepBanner.tsx lines 1-60 and 410-457</read_first>
  <action>
    (1) adminNav.ts: add `export const PULSE_NAV: AdminNavItem[]` with the exact 4 items currently inline in admin.pulse.tsx
    (same `to`, `labelKey`, `exact`, same order). admin.pulse.tsx uses `items={PULSE_NAV}`. admin.users.tsx and admin.spaces.tsx
    switch to `items={PULSE_NAV}` (import PULSE_NAV; drop the now-unused ADMIN_NAV import there). Keep `product={t("shell.productManage")}`
    on the manage pages (sensible label). ProductShell then renders PULSE_NAV as primary nav and, since `items !== ADMIN_NAV`,
    the superadmin Manage block below it — PULSE_NAV and ADMIN_NAV share no `to`, so no link renders twice. Keep the guard (it
    still protects any caller passing ADMIN_NAV) and update its comment plus the adminNav.ts header comment to describe the
    new arrangement (manage pages pass PULSE_NAV; Manage block supplies users/spaces).

    (6) NextStepBanner.tsx: add optional prop `layout?: "stacked" | "horizontal"` (default "stacked" — the default render must be
    unchanged for every caller, incl. admin.sales.projects.$id.tsx). In "horizontal", lay the root out as text left / actions right at
    md+ (e.g. wrap title+body in a `min-w-0 flex-1` column and put the actions div in a `md:shrink-0 md:justify-end` column inside
    a `md:flex md:items-start md:gap-6` row; drop the body's bottom margin on md+); below md it stacks as today. The AlertDialog and
    all props/handlers stay as-is.
    admin.pulse.intakes.$id.tsx: remove the 2-col wrapper `grid grid-cols-1 xl:grid-cols-[1fr_272px] ...` and the
    `<aside ... xl:sticky xl:top-[88px]>`; render the bordered card (`border border-ink/15 bg-paper`) as a full-width block placed
    DIRECTLY AFTER the workflow card (stepper + status banner + run history, ends ~1407) and BEFORE the edit banner / sections grid,
    in every phase (no new phase gating — NextStepBanner already returns null where it has nothing). Inside the card:
    `<NextStepBanner layout="horizontal" ...all 21 existing props unchanged... />`, then a responsive row (e.g.
    `border-t border-ink/10 md:flex md:items-start` or a `md:grid md:grid-cols-[auto_1fr]`) holding `AISkillsPanel` and, when
    `showSemanticSearch`, the existing search section (input, button, results) — move the JSX verbatim, drop no control, keep
    every handler/state. Remove the content column's `xl:col-start-1 xl:row-start-1` wrapper (or keep a plain `min-w-0` div) so
    content uses the full width. Update the "2-col layout" comment to describe the new structure. Match closing tags carefully —
    tsc catches JSX imbalance.

    (7) Sections nav: the scroll container is ProductShell's `<main className="flex-1 overflow-y-auto">` under a 44px TopBar, and
    the page header is `sticky top-0` inside main with variable height (title wraps; statusHint optional). Attach a ref to the sticky
    page header div (~1193) and measure its height with a ResizeObserver into state `headerH` (initial 0; disconnect on unmount; guard
    `typeof ResizeObserver !== "undefined"`). On the section `<nav>` (~1503) replace `sticky top-28` with `sticky overflow-y-auto` plus
    inline style (dynamic value -> inline style is the codebase convention) `top: headerH + 16` and
    `maxHeight: calc(100vh - 44px - ${headerH}px - 32px)`; add `pr-1` so the scrollbar does not overlap labels. The `<aside>` stays a
    grid item stretched to the content height (grid default `align-items: stretch`) — do not add `self-start` to the aside, or sticky
    has no travel. Confirm no ancestor between `main` and the nav sets `overflow` hidden/auto (the removed xl grid was the only
    candidate wrapper; the header's `-mx-6` does not matter). Optional, only if trivial: when `activeSection` changes, call
    `scrollIntoView({ block: "nearest" })` on the active nav link via a ref map — skip if it needs more than a few lines.
  </action>
  <verify>
    <automated>cd frontend && npx tsc --noEmit && npx vitest run && node scripts/i18n-audit.mjs</automated>
    Gates: `grep -c "items={ADMIN_NAV}" frontend/src/routes/admin.users.tsx frontend/src/routes/admin.spaces.tsx` -> 0 each;
    `grep -c "items={PULSE_NAV}" frontend/src/routes/admin.pulse.tsx frontend/src/routes/admin.users.tsx frontend/src/routes/admin.spaces.tsx` -> 1 each;
    `grep -c "1fr_272px" "frontend/src/routes/admin.pulse.intakes.\$id.tsx"` == 0; `grep -c "top-28" "frontend/src/routes/admin.pulse.intakes.\$id.tsx"` == 0;
    `git diff --stat -- frontend/src/components/ui/` empty. Report tsc error count, vitest passed/failed counts, i18n-audit result.
    Optional human check (not blocking): `/admin/users` sidebar shows new intake / intakes / clients / search + Beheer block once; intake detail shows the next-step block under the tracker and the section nav stays visible while scrolling.
  </verify>
  <done>Manage pages show full Pulse nav + Manage block with no duplicates; next-step card (banner + AI tools + search) full-width under the tracker with every control present; section nav sticky and internally scrollable; tsc 0, vitest all green, i18n audit passes; commit `feat(261006-jgn): full nav on manage pages; next-step panel above content; sticky sections nav` with only these 7 frontend files.</done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| form answers -> mail HTML | `contact_name` is admin/client-authored text rendered into an outbound email |
| create body -> intake_answers | create-screen `client_name` is written into another tenant-scoped table |
| answers -> admin header | answer values (possibly AI-written localized objects) rendered in React |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-jgn-01 | Tampering (HTML injection) | mail greeting from contact_name | mitigate | Jinja autoescape stays ON, no `| safe`/Markup; test asserts `<b>` arrives as `&lt;b&gt;` |
| T-jgn-02 | Information disclosure (cross-tenant) | `_contact_first_name` answer read | mitigate | query filters `intake_id` AND `space_id == intake.space_id`; intake already 404-gated by `repo.get` before the read |
| T-jgn-03 | Tampering / Elevation (cross-tenant write) | `_seed_project_name_answer` | mitigate | `space_id` taken from the created intake row (never the body); runs on the same session/GUC as the create so RLS WITH CHECK applies; ON CONFLICT DO NOTHING never overwrites |
| T-jgn-04 | Denial of service (render crash) | header + FieldDisplay with localized objects | mitigate | resolve via `pick()` before render (object never reaches JSX); questions path unchanged |
| T-jgn-05 | Information disclosure | Pulse nav on manage pages | accept | nav links only; every route keeps its own server-side role gate |
</threat_model>

<verification>
- Backend: full pytest green (counts reported), new greeting + seed tests included.
- Frontend: `npx tsc --noEmit` 0 errors, `npx vitest run` all green, `node scripts/i18n-audit.mjs` passes.
- No changes under `frontend/src/components/ui/`; no alembic migration; no `npm install` (lockfile untouched — `git diff --stat frontend/package-lock.json` empty).
- Three atomic code commits; deferred-items.md edited but left uncommitted for the orchestrator.
</verification>

<success_criteria>
- Project name typed once on create appears as the form's project_name answer.
- Header shows "<organisation> — <project>" with the collapse rules.
- Client mails greet the contact's first name, else team/équipe.
- Stakeholders show name/role/expectation; research questions unchanged.
- Manage pages navigable back to intakes; next-step panel above content; sections nav always visible.
</success_criteria>

<output>
Create `.planning/quick/261006-jgn-tester-feedback-admin-ux-and-mail-greeti/261006-jgn-SUMMARY.md` when done (gate counts: backend pytest, tsc, vitest, i18n audit; commit hashes).
</output>
