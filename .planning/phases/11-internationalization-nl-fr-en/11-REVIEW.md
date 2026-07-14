---
phase: 11-internationalization-nl-fr-en
reviewed: 2026-07-14T00:00:00Z
depth: standard
files_reviewed: 94
files_reviewed_list:
  - backend/app/api/admin_routes.py
  - backend/app/api/errors.py
  - backend/app/api/intake_routes.py
  - backend/app/api/me_routes.py
  - backend/app/data/pulse_intake_v1.json
  - backend/app/db/admin_repo.py
  - backend/app/db/alembic/versions/0010_locale_columns.py
  - backend/app/db/models/membership.py
  - backend/app/db/models/organization.py
  - backend/app/db/session.py
  - backend/app/mail/render.py
  - backend/app/mail/templates/en/invite.html.j2
  - backend/app/mail/templates/en/results.html.j2
  - backend/app/mail/templates/en/validation.html.j2
  - backend/app/mail/templates/fr/invite.html.j2
  - backend/app/mail/templates/fr/results.html.j2
  - backend/app/mail/templates/fr/validation.html.j2
  - backend/app/mail/templates/nl/invite.html.j2
  - backend/app/mail/templates/nl/results.html.j2
  - backend/app/mail/templates/nl/validation.html.j2
  - backend/app/main.py
  - backend/tests/test_admin_routes.py
  - backend/tests/test_error_codes.py
  - backend/tests/test_mail_locale.py
  - backend/tests/test_me_routes.py
  - backend/tests/test_schema_shape_locale.py
  - frontend/package.json
  - frontend/scripts/ci_no_hardcoded_dutch.sh
  - frontend/src/components/LanguageSwitcher.tsx
  - frontend/src/components/admin/ClientDetailDrawer.tsx
  - frontend/src/components/admin/ClientFormModal.tsx
  - frontend/src/components/admin/InviteUserDialog.tsx
  - frontend/src/components/admin/ProductShell.tsx
  - frontend/src/components/admin/SpaceFormModal.tsx
  - frontend/src/components/admin/SpaceSwitcher.tsx
  - frontend/src/components/intake/AIReviewPanel.tsx
  - frontend/src/components/intake/AISkillsPanel.tsx
  - frontend/src/components/intake/ContextPackBlock.tsx
  - frontend/src/components/intake/ContextPackPDF.tsx
  - frontend/src/components/intake/FieldDisplay.tsx
  - frontend/src/components/intake/FieldRenderer.tsx
  - frontend/src/components/intake/FinalReportBlock.tsx
  - frontend/src/components/intake/HandoffBlock.tsx
  - frontend/src/components/intake/IntakeForm.tsx
  - frontend/src/components/intake/IntakeWorkflowStepper.tsx
  - frontend/src/components/intake/NestorBriefingPDF.tsx
  - frontend/src/components/intake/NextStepBanner.tsx
  - frontend/src/components/intake/RecipientPicker.tsx
  - frontend/src/components/intake/ResearchArtifacts.tsx
  - frontend/src/components/intake/ResearchResultsPanel.tsx
  - frontend/src/lib/api/admin.ts
  - frontend/src/lib/api/client.ts
  - frontend/src/lib/api/me.ts
  - frontend/src/lib/auth-context.tsx
  - frontend/src/lib/i18n/date-locale.test.ts
  - frontend/src/lib/i18n/date-locale.ts
  - frontend/src/lib/i18n/detect.ts
  - frontend/src/lib/i18n/error-codes.test.ts
  - frontend/src/lib/i18n/error-codes.ts
  - frontend/src/lib/i18n/index.ts
  - frontend/src/lib/i18n/localizeSchema.test.ts
  - frontend/src/lib/i18n/localizeSchema.ts
  - frontend/src/lib/intake-phase.ts
  - frontend/src/lib/intake-types.ts
  - frontend/src/locales/en/admin.json
  - frontend/src/locales/en/auth.json
  - frontend/src/locales/en/common.json
  - frontend/src/locales/en/intake.json
  - frontend/src/locales/fr/admin.json
  - frontend/src/locales/fr/auth.json
  - frontend/src/locales/fr/common.json
  - frontend/src/locales/fr/intake.json
  - frontend/src/locales/nl/admin.json
  - frontend/src/locales/nl/auth.json
  - frontend/src/locales/nl/common.json
  - frontend/src/locales/nl/intake.json
  - frontend/src/routes/__root.tsx
  - frontend/src/routes/admin.index.tsx
  - frontend/src/routes/admin.pulse.clients.$id.tsx
  - frontend/src/routes/admin.pulse.clients.tsx
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/routes/admin.pulse.intakes.index.tsx
  - frontend/src/routes/admin.pulse.intakes.new.tsx
  - frontend/src/routes/admin.pulse.search.tsx
  - frontend/src/routes/admin.spaces.tsx
  - frontend/src/routes/admin.templates.tsx
  - frontend/src/routes/admin.users.tsx
  - frontend/src/routes/auth.action.tsx
  - frontend/src/routes/auth.login.tsx
  - frontend/src/routes/intake.$id.results.tsx
  - frontend/src/routes/intake.$id.tsx
  - frontend/src/routes/intake.index.tsx
  - frontend/tsconfig.json
findings:
  critical: 2
  warning: 9
  info: 9
  total: 20
status: fixed
fixed:
  critical_warning: 11
  info: 0
fixed_at: 2026-07-14T00:00:00Z
resolutions:
  CR-01: resolved   # 9d73e33 — admin detail localizes schema via useMemo(localizeSchema, i18n.language)
  CR-02: resolved   # 641d6ae — results page keeps raw schema in state, flattens in useMemo
  WR-01: resolved   # 86374a1 — _INVITE_SUBJECTS per-locale map, selected with the body's invite_locale
  WR-02: resolved   # 8a89f3d — switcher always writes localStorage; boot clears only on confirmed persist
  WR-03: resolved   # eac585f — active-only + space-scoped + ordered first(); regression test added
  WR-04: resolved   # 1b7dc94 — StatusPill/statusSummary read common:status.* (nl/fr/en parity)
  WR-05: resolved   # 66c6fd8 — shell/home externalized; guard stopwords extended; ValidationDiff copy externalized
  WR-06: resolved   # 37bef71 — /admin landing logout uses Firebase signOut(auth)
  WR-07: resolved   # f04ab30 — validateField reads validation.min_length ?? field.min_length
  WR-08: resolved   # 549dbc1 — PDF attachments render m.filename, raw-path fallback dropped
  WR-09: resolved   # 9e2ea50 — ClientFormModal + ClientDetailDrawer + clientPills deleted
  IN-01: not_fixed  # out of scope (Info)
  IN-02: not_fixed  # out of scope (Info)
  IN-03: not_fixed  # out of scope (Info)
  IN-04: not_fixed  # out of scope (Info)
  IN-05: not_fixed  # out of scope (Info)
  IN-06: not_fixed  # out of scope (Info)
  IN-07: not_fixed  # out of scope (Info)
  IN-08: not_fixed  # out of scope (Info)
  IN-09: not_fixed  # out of scope (Info)
---

# Phase 11: Code Review Report

**Reviewed:** 2026-07-14
**Depth:** standard
**Files Reviewed:** 94
**Status:** issues_found

## Summary

Phase 11 (Internationalization NL/FR/EN) was reviewed adversarially across the backend
(/me locale endpoints, locale columns, CodedError contract, per-locale mail rendering and
recipient-locale resolution) and the frontend (i18next wiring, localizeSchema flatten,
catalogs, switcher, error-code map, PDF label props, CI Dutch guard).

**Security invariants hold.** Locale is never an authz input: `/me` derives identity solely
from the verified token (`identity.uid`), the PATCH write is scoped to the caller's own
membership row (proven by `test_locale_is_derived_from_token_not_body`), the error-code set
is a curated frozen enum with generic details, mail recipient-locale resolution stays inside
the intake's own space (`_active_members_stmt` gate reused; 422 on any foreign/deactivated
id), Jinja2 autoescape is ON for all nine locale template variants (no `| safe` anywhere),
and `apiFetch`/`ApiResult` were extended additively (raw string `detail` fallback preserved,
optional `code`). Catalog key parity across nl/fr/en was verified programmatically: all four
namespaces have identical key sets with no empty values, and all dynamically-constructed
keys (`intakeDetail.status.*`, `intakesList.filter.*`, `spaceForm.locale.*`, banners/hints)
resolve. The CI Dutch guard passes and its self-test mechanics are sound.

**However, the schema flatten was only wired into ONE of its three consumers.** The
canonical template (`pulse_intake_v1.json`) now serves every display string as a
`{nl, fr, en}` object, and `localizeSchema` is called only by `IntakeForm`. The admin
intake-detail page and the client results page render the raw multi-locale schema directly
— React throws "Objects are not valid as a React child" on the first section title, so both
pages crash outright. These are the two blockers below.

## Critical Issues

### CR-01: Admin intake-detail page renders the raw multi-locale schema — page crashes

**File:** `frontend/src/routes/admin.pulse.intakes.$id.tsx:370` (schema assigned raw), rendered at `:1103-1119` (sidebar `{s.title}`), `:1318-1322` (`{section.title}` / `{section.description}`), `:1348` / `:1367` (FieldRenderer/FieldDisplay `field.label`)
**Issue:** `load()` stores `tmpl.schema as unknown as IntakeSchema` without calling
`localizeSchema`. Since this phase converted `backend/app/data/pulse_intake_v1.json`
(served verbatim by `GET /intakes/templates` via `intake_canonical.py`) to the
`LocalizedString` shape, `section.title`, `section.description`, `field.label`,
`field.help`, option labels, etc. are now **objects** (`{nl, fr, en}`), not strings.
Rendering `{s.title}` in the sidebar (and `{section.title}` in the body, and every
`FieldDisplay`/`FieldRenderer` label) makes React throw
`Objects are not valid as a React child (found: object with keys {nl, fr, en})` —
the operator's primary work surface is broken for every intake. Only `IntakeForm`
(the `/intake/$id` fill route) received the flatten pass.
**Fix:**
```tsx
// admin.pulse.intakes.$id.tsx — flatten at load time and re-resolve on language change
import { localizeSchema } from "@/lib/i18n/localizeSchema";
import type { LocalizedIntakeSchema } from "@/lib/intake-types";

// in load(), replace:
//   schema: tmpl.schema as unknown as IntakeSchema
// with the raw source, then resolve where consumed:
const sections = useMemo(
  () =>
    intake?.template?.schema
      ? localizeSchema(
          intake.template.schema as unknown as LocalizedIntakeSchema,
          i18n.language,
        ).sections
      : [],
  [intake?.template?.schema, i18n.language],
);
```

### CR-02: Client results page (`/intake/$id/results`) renders the raw multi-locale schema — page crashes

**File:** `frontend/src/routes/intake.$id.results.tsx:110` (raw assignment), `:197-206` (`{section.title}` + `FieldDisplay field`)
**Issue:** Same defect as CR-01 on the client-facing surface:
`setSchema((template.schema ?? {}) as unknown as IntakeSchema)` skips `localizeSchema`,
so `section.title` and every `field.label` are `{nl, fr, en}` objects. The read-only
results view for any validated intake crashes with the React object-child error. This is
the page the results mail's CTA (`{app_base_url}/intake/{intake_id}/results`) links to,
so the emailed client lands on a broken page.
**Fix:**
```tsx
import { localizeSchema } from "@/lib/i18n/localizeSchema";
import type { LocalizedIntakeSchema } from "@/lib/intake-types";
// in the load effect:
setSchema(
  localizeSchema(
    (template.schema ?? {}) as unknown as LocalizedIntakeSchema,
    i18n.language,
  ),
);
// and add i18n to the useTranslation destructure + effect deps so a language
// switch re-resolves (mirror IntakeForm's useMemo pattern).
```

## Warnings

### WR-01: Invite mail subject stays Dutch while its body is locale-resolved

**File:** `backend/app/api/admin_routes.py:52` (`_INVITE_SUBJECT`), used at `:334`
**Issue:** `send_invite_mail` resolves the body to the target space's `default_locale`
(D-07) and renders `fr/invite.html.j2` / `en/invite.html.j2`, but the subject is the
hard-coded Dutch constant `"Welkom bij Nestor Pulse — stel je wachtwoord in"`. An FR/EN
space's invitee receives a Dutch subject over a French/English body — exactly the
subject/body desync that `intake_routes.py`'s `_SUBJECTS` map (D-12) was built to prevent
for the other three mail types.
**Fix:** Mirror the `_SUBJECTS` pattern: a per-locale invite-subject dict keyed by
`invite_locale` with the NL constant as fallback, selected next to the
`mail_render.render_invite(..., locale=invite_locale)` call.

### WR-02: Superadmin locale choice is silently lost on every reload

**File:** `frontend/src/lib/auth-context.tsx:171-181`; `frontend/src/components/LanguageSwitcher.tsx:47-57`
**Issue:** The design (0010 migration docstring, Open Q1) says a superadmin with no
membership row "falls back to the browser-detected / stored preference (the localStorage
path)". The implementation breaks that: the boot reconciliation consumes and **clears**
`LOCALE_STORAGE_KEY` after calling `patchLocale(pending)` — which persists **nothing**
for a membership-less superadmin — and the post-login switcher (`persist=true`) only calls
`patchLocale`, never re-writing localStorage. On the next reload the chain resolves
`pending(null) ?? meLocale(null) ?? spaceDefault("nl")` and even `detectLocale()` is
unreachable (space_default is always non-null). Every superadmin reload resets the UI to
NL regardless of their choice.
**Fix:** Either (a) have the `persist=true` switcher path ALSO write
`LOCALE_STORAGE_KEY`, and in the boot only clear the pending key when `patchLocale`
returned a persisted (non-null) `locale`; or (b) treat the stored key as a standing
fallback between `meLocale` and `spaceDefault` instead of a consume-once value.

### WR-03: `GET /me` / `PATCH /me/locale` 500 when a uid has more than one membership row

**File:** `backend/app/api/me_routes.py:115-119` (`_load_membership`)
**Issue:** `_load_membership` selects on `provider_user_id == identity.uid` alone and
calls `.scalar_one_or_none()`. The schema's uniqueness is `(organization_id, user_id)` —
nothing prevents the same `provider_user_id` from holding membership rows in two spaces
(the test suites seed such rows directly, and an ops/manual seed of a superadmin into a
space plus a legacy row does the same). Two rows → SQLAlchemy `MultipleResultsFound` →
unhandled 500 on both `/me` endpoints; and `PATCH` would write to an arbitrary row. The
lookup also ignores `status`, so a deactivated membership's locale still resolves/writes.
**Fix:** Constrain the query — filter `status == "active"`, prefer
`organization_id == identity.space_id` when the identity carries a space, and use
`.limit(1)` / `.first()` with a deterministic ordering so a duplicate row can never 500
the endpoint:
```python
stmt = (
    select(OrganizationMembership)
    .where(
        OrganizationMembership.provider_user_id == identity.uid,
        OrganizationMembership.status == "active",
    )
    .limit(1)
)
```

### WR-04: Client-facing status labels are hardcoded Dutch (`_status.tsx` StatusPill)

**File:** `frontend/src/components/intake/_status.tsx:11-20, 43` — consumed by `frontend/src/routes/intake.index.tsx:208`, `frontend/src/routes/intake.$id.results.tsx:193`, `frontend/src/routes/admin.pulse.intakes.index.tsx`, `admin.pulse.clients.tsx:38` (`STATUS_LABEL` in `statusSummary`)
**Issue:** `STATUS_LABEL` ("Concept", "Ingediend", "Gereviewd", "Gevalideerd",
"In onderzoek", "Geleverd", "Gearchiveerd") is rendered verbatim by `StatusPill` on the
CLIENT-facing intake list and results header. An EN/FR client sees a fully translated page
with Dutch status pills. The admin detail page localized its own copy of this map
(`t("intakeDetail.status.*")`) but the shared atom was skipped. None of these words are in
the CI guard's stopword list, so the guard cannot catch this class.
**Fix:** Convert `StatusPill` to `useTranslation` with the existing
`admin:intakeDetail.status.*` keys (or add a `common:status.*` group so the intake
namespace surfaces can use it), and replace the raw `STATUS_LABEL` interpolation in
`admin.pulse.clients.tsx#statusSummary` the same way.

### WR-05: Persistent admin chrome and admin landing page still hardcoded Dutch

**File:** `frontend/src/components/admin/ProductShell.tsx:43` ("← Terug naar overzicht"), `:100` ("Beheer"), `:129` ("Uitloggen"); `frontend/src/routes/admin.index.tsx:22-68` (Dutch product descriptions), `:90` ("kies een product"), `:151` ("Uitloggen"); also `frontend/src/routes/admin.users.tsx:165` / `admin.spaces.tsx:116` / `admin.templates.tsx:109` (`product="beheer"`) and `admin.spaces.tsx:121` (heading "spaces" vs localized siblings)
**Issue:** The sidebar shell rendered on EVERY admin page (back-link, "Beheer" section
header, logout) and the product-chooser landing page (`/admin`) were missed by the
externalization sweep. These strings evade `ci_no_hardcoded_dutch.sh` because none of the
words match the stopword pattern ("terug", "overzicht", "beheer", "uitloggen", "kies",
"onderzoek" are absent from `PATTERN`). An EN/FR admin gets a mixed-language shell around
every localized screen.
**Fix:** Externalize to `admin.json` (e.g. `shell.backToOverview`, `shell.manage`,
`shell.logout`, `home.*`) and extend the guard's stopword list with at least
`uitloggen|terug|overzicht|beheer` so this class regresses loudly.

### WR-06: Logout on `/admin` landing page uses the retired Supabase client — logout silently fails

**File:** `frontend/src/routes/admin.index.tsx:75-79`
**Issue:** `handleLogout` calls `supabase.auth.signOut()` (guarded by
`if (!supabase) return;`). Auth moved to Firebase in Phase 3 — every other surface calls
`signOut(auth)` from `firebase/auth`. Two failure modes: (a) with no Supabase env vars the
guard returns and nothing happens at all; (b) even if the legacy client exists, the
Firebase session survives, and `AuthRedirector` (`__root.tsx:98-104`) immediately bounces
`/auth/login` back to the role landing page. The admin home's logout button is therefore
non-functional, and this file still imports the legacy `@/lib/supabase` module the phase
is supposed to be retiring.
**Fix:**
```tsx
import { signOut } from "firebase/auth";
import { auth } from "@/lib/firebase";
async function handleLogout() {
  await signOut(auth);
  navigate({ to: "/auth/login" });
}
```

### WR-07: `min_length` validation never fires — canonical schema and validator disagree on shape

**File:** `frontend/src/components/intake/IntakeForm.tsx:46-49`; `backend/app/data/pulse_intake_v1.json:172` (`company_intro` `"min_length": 100`)
**Issue:** `validateField` reads `field.validation?.min_length`, but the canonical schema
stores `min_length` at the FIELD level (`IntakeField.min_length` exists in the type for
exactly this reason, and `localizeSchema` passes it through in `...rest`). No field in the
canonical schema has a nested `validation` object, so the required 100-char minimum on
`company_intro` (and any future min_length) is dead — the client can submit a one-character
company intro through a "required, min 100 chars" field.
**Fix:**
```tsx
const minLen = field.validation?.min_length ?? field.min_length;
if (field.type === "longtext" && minLen) {
  if (typeof value === "string" && value.length < minLen)
    return t("validation.minChars", { count: minLen });
}
```

### WR-08: Briefing PDF attachments table reads `m.name` but uploads store `filename`

**File:** `frontend/src/components/intake/NestorBriefingPDF.tsx:208-212, 321`
**Issue:** `materials_files` values are written by `FieldRenderer.uploadOne` as
`{ path, filename, size, uploaded_at }`, but the PDF types the array as
`{ name?, size?, path? }` and renders `m.name || m.path || labels.fileFallback`. `name`
is always undefined, so the attachments page of the handoff PDF prints the raw GCS
storage path (e.g. `intakes/<uuid>/materials/...`) instead of the human filename — noisy
and it leaks internal object-key structure into a client-adjacent document.
**Fix:** Type the array as `{ filename?: string; name?: string; size?: number; path?: string }`
and render `m.filename || m.name || labels.fileFallback` (drop the raw path fallback).

### WR-09: Dead legacy-Supabase write components still shipped (`ClientFormModal`, `ClientDetailDrawer`)

**File:** `frontend/src/components/admin/ClientFormModal.tsx:85-106`; `frontend/src/components/admin/ClientDetailDrawer.tsx:82-113`
**Issue:** Both components are exported but referenced nowhere (verified by grep — only
their own definitions match). They still perform DIRECT Supabase writes to
`public.clients` and call the legacy `list_client_intakes` RPC — the exact
"writes not mediated by the backend" pattern the project constraints forbid, plus
`ClientDetailDrawer` renders the hardcoded-Dutch `STATUS_NL` map from `clientPills.tsx`.
They were touched this phase (t() strings added), which spends effort localizing dead code
and keeps a resurrectable bypass of the tenant-isolation write path in the tree.
**Fix:** Delete both components (and the now-orphaned `clientPills.tsx` exports they pull
in), or at minimum strip the Supabase write paths before the Supabase retirement gate.

## Info

### IN-01: Hardcoded Dutch fallback "Onbekende fout" in the shared transport

**File:** `frontend/src/lib/api/client.ts:127`
**Issue:** The `apiFetch` catch-all returns `error: "Onbekende fout"` — the network-error
toast every screen shows stays Dutch in EN/FR sessions. Evades the CI guard ("fout" is not
a stopword).
**Fix:** Return a stable code (`code: "NETWORK_ERROR"`) mapped in `ERROR_CODES`, or the
English literal that other transport fallbacks use, and let call sites translate.

### IN-02: `examples` (good/bad) in the canonical schema are NL-only scalars

**File:** `backend/app/data/pulse_intake_v1.json:198-205`; rendered by `frontend/src/components/intake/FieldRenderer.tsx:42-61`
**Issue:** `decision_or_goal`'s good/bad examples are Dutch strings, not `LocalizedString`
maps; `localizeSchema` passes `examples` through untouched, so FR/EN clients see Dutch
example sentences under a localized field.
**Fix:** Localize the `examples` arrays in the canonical JSON (and teach
`localizeSchema`/`IntakeField` the localized shape), or drop them for non-NL until
translated.

### IN-03: Residual hardcoded `nl-BE`/`nl-NL` date formatting

**File:** `frontend/src/components/intake/FieldDisplay.tsx:44-53` (`formatEditedAt`, `Intl "nl-BE"`); `frontend/src/components/intake/IntakeWorkflowStepper.tsx:32` (`toLocaleDateString("nl-NL")`); `frontend/src/components/intake/ResearchResultsPanel.tsx:426` (`"nl-BE"` + literal "Onderzoek:")
**Issue:** Three date/label call sites bypass the new `getDateLocale`/`i18n.language`
helpers, so edited-at stamps and stepper dates render Dutch month names in EN/FR UIs
(the ResearchResultsPanel one is gated-off post-decomposed UI).
**Fix:** Route through `i18n.language` (Intl) or `getDateLocale` like the surrounding code.

### IN-04: `<html lang="en">` is static while the default UI language is nl

**File:** `frontend/src/routes/__root.tsx:66`
**Issue:** The SSR shell deterministically renders Dutch (`lng: "nl"`) under
`lang="en"`, and the attribute never updates on `changeLanguage` — screen readers and
UA heuristics get the wrong language for the whole session.
**Fix:** Set `lang="nl"` in the shell and update `document.documentElement.lang` on
i18next's `languageChanged` event (client-only effect).

### IN-05: Dead Dutch `SIMPLE_LABELS` export and unused `aiReview.label*` catalog keys

**File:** `frontend/src/components/intake/AIReviewPanel.tsx:215-219`; `frontend/src/locales/*/intake.json` (`aiReview.labelDecisionOrGoal|labelAudience|labelCompanyIntro`)
**Issue:** `SIMPLE_LABELS` (hardcoded Dutch) is exported but unreferenced; the catalog
keys apparently added to replace it are also unreferenced. Dead code on both sides.
**Fix:** Delete `SIMPLE_LABELS`; either wire the `aiReview.label*` keys where field titles
are needed or remove them from all three catalogs (keeping parity).

### IN-06: Discarded `resolve_existing_uid` call in the duplicate-invite path

**File:** `backend/app/api/admin_routes.py:160-164`
**Issue:** In the `EmailAlreadyExistsError` branch, `admin_users.resolve_existing_uid(body.email)`
is called and its result immediately discarded before raising the 409 — a leftover from a
reconcile design that no longer exists (the docstring still claims "we reconcile to the
existing uid"). Wasted IdP round-trip; misleading comment.
**Fix:** Remove the call (and fix the docstring), or actually use the uid in the 409 body
if reconciliation is intended.

### IN-07: Dutch search suggestions hardcoded on the admin search page

**File:** `frontend/src/routes/admin.pulse.search.tsx:12-18`
**Issue:** The `SUGGESTIONS` chips ("merk strategie", "concurrenten benchmarken", …) are
Dutch literals on an otherwise-localized screen; evades the stopword guard.
**Fix:** Move to `admin.json` (`search.suggestions` array) or drop them.

### IN-08: Malformed UUID input to intake create returns 500 instead of 422

**File:** `backend/app/api/intake_routes.py:365, 373`
**Issue:** `uuid.UUID(values["template_id"])` and `uuid.UUID(space_id)` are called on raw
client input with no `ValueError` handling — a malformed `template_id` body field or
`?space_id=` query param yields an unhandled 500 (generic body, no leak) rather than a
validation 422. `AdminRepo._as_uuid`'s docstring assumes handlers map this to 422/400,
but these two call sites do not.
**Fix:** Wrap in `try/except ValueError: raise HTTPException(422, "Invalid id")`, or type
the fields as `uuid.UUID` in the Pydantic model / query param so FastAPI 422s them.

### IN-09: Test app builders mutate the shared module-level `protected_router`

**File:** `backend/tests/test_mail_locale.py:320-340`; `backend/tests/test_me_routes.py:210-229`
**Issue:** `_build_intake_app`/`_build_admin_app`/`_build_app` call
`protected_router.include_router(...)` on the SHARED `app.api.auth_routes.protected_router`
every invocation. Routes accumulate across tests within a session (duplicate route entries;
first-match wins so assertions still pass), and an app built for the intake surface also
carries admin/me routes included by earlier tests — cross-test coupling that can mask
routing regressions and makes route-count assertions impossible later. (Established idiom
in older suites, propagated here.)
**Fix:** Build each test app from a FRESH `APIRouter` that re-attaches
`Depends(get_current_identity)`, or include routers onto a per-test copy
(`APIRouter(dependencies=protected_router.dependencies)`).

---

_Reviewed: 2026-07-14_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
