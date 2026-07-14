# Phase 11: Internationalization (NL/FR/EN) - Context

**Gathered:** 2026-07-14
**Status:** Ready for planning

<domain>
## Phase Boundary

The UI supports **NL, FR, and EN** through react-i18next: all hardcoded Dutch strings on the
re-platform surfaces are externalized to i18n keys, a language switcher works from the login page
onward, and a default locale applies per user/space (I18N-01, I18N-02). Depends on Phase 6 (the
frontend runs against the GCP API seam).

Success criteria (ROADMAP § Phase 11):
1. The UI renders fully in NL, FR, and EN — all labels, banners, toasts, error messages, and date
   locale are externalized to i18n keys (no hardcoded Dutch strings remain).
2. A user can switch language and a default locale applies per user/space.

**In scope:**
- Frontend string externalization on the **re-platform surfaces**: intake form flow, client-facing
  views, admin Pulse lifecycle, space/user management, auth pages (login, /auth/action handler).
- The intake form's **content** — section titles, question labels, help texts, placeholders in the
  canonical template asset (`backend/app/data/pulse_intake_v1.json`) — translated in-place.
- **Client-facing mail templates** (validation, results, reminder, invite) rendered in the
  recipient's locale — closes the Phase 10 email-i18n deferral.
- Client-side **PDF exports** (ContextPackPDF, NestorBriefingPDF) using the same i18n catalog.
- **Date locale** follows the active language (central language → date-fns locale helper).
- Schema migration: `default_locale` on the space (organization) + per-user locale override;
  space-management UI field; auto-persisting switcher.
- **Error-code contract** for user-facing backend errors so toasts can translate them.
- CI guard against reintroduced hardcoded Dutch strings.

**Out of scope:**
- Sales routes (`admin.sales.*`) and coming-soon pages — sales track is outside the re-platform
  requirements; stays Dutch.
- `admin_validated` operator mail — goes to one configured Agenic address; stays Dutch.
- AI-generated content language (skill outputs, context packs, insights) — Phase 7 prompts
  untouched; deferred.
- Locales beyond NL/FR/EN.

</domain>

<decisions>
## Implementation Decisions

### Externalization Scope
- **D-01 (re-platform surfaces only):** Translate everything in the v1 GCP flow — intake form,
  client views, admin Pulse lifecycle, space/user management, auth pages. Sales routes and
  coming-soon placeholders are explicitly excluded (their future is unclear; effort would be
  wasted if the sales track is retired or reworked).
- **D-02 (client-facing mails ride along):** The validation/results/reminder/invite Jinja2
  templates get NL/FR/EN variants and render in the **recipient's** resolved locale. The
  `admin_validated` operator mail stays Dutch. This closes Phase 10's explicit deferral.
- **D-03 (PDF exports use the same keys):** ContextPackPDF and NestorBriefingPDF label strings
  come from the i18n catalog and render in the active UI language — they're React components, so
  the same translation function applies.
- **D-04 (date locale follows language):** One central helper maps active language → date-fns
  locale (`nl`/`fr`/`enUS`); all 9 files that hardcode `import { nl } from "date-fns/locale"`
  switch to it. I18N-01 names date locale explicitly.

### Intake Form Content
- **D-05 (translations live in the canonical JSON):** Every display string in
  `backend/app/data/pulse_intake_v1.json` (46 labels, 17 descriptions, 15 titles, 6 placeholders,
  help texts) carries nl/fr/en variants; the frontend picks the active locale at render. One
  source of truth stays with the in-repo canonical asset (D-CANON), so future template edits carry
  their translations with them. **nl is the guaranteed fallback** for any missing variant.
- **D-06 (AI output language deferred):** Skill outputs stay as the Phase 7 prompts produce them.
  Passing locale into prompts risks regressing validated AI behavior — deferred idea, not v1.

### Locale Default & Persistence
- **D-07 (space default + user override):** Migration adds `default_locale` on the space
  (organization) and a per-user locale override. Resolution chain everywhere (UI and email):
  **user pref → space default → nl**.
- **D-08 (switcher in header + login page):** One compact NL/FR/EN switcher component, reused in
  the authenticated app chrome (ProductShell for admin, form header for clients) AND on the login
  page — a French-speaking invitee must be able to switch before authenticating.
- **D-09 (browser → nl detection pre-login):** Before any preference is known: browser language if
  it's nl/fr/en, else nl. A pre-login switch persists to the user's profile once they log in. New
  spaces default to `nl` (current client base).
- **D-10 (space dialog + auto-persist):** Superadmin edits `default_locale` in the existing space
  create/edit UI. A logged-in user's switcher flip PATCHes their profile immediately — no separate
  save step. Email sends resolve each recipient's locale server-side via the D-07 chain.

### Backend Strings & Translation Authoring
- **D-11 (error-code contract):** User-facing endpoints return a stable machine code alongside
  `detail`; the frontend maps code → translated toast message, **falling back to raw server text
  for unmapped codes**. Planner scopes the code set to errors users actually see (not every
  internal 4xx/5xx).
- **D-12 (AI-drafted translations, user-reviewed):** Claude generates the FR/EN translations
  (UI catalog, form content, mail templates) during execution, committed with the phase; the user
  reviews/corrects tone in UAT. No external translation dependency.
- **D-13 (CI guard + sweep):** A CI check (Dutch-word regex scan over in-scope TSX/TS files,
  QA-02 `ci_no_permissive_rls.sh` style) plus a thorough manual sweep during execution keeps
  "no hardcoded Dutch strings" true after the phase ships.

### Claude's Discretion
- **Multi-locale shape inside the canonical JSON** — locale objects (`label: {nl, fr, en}`) vs
  parallel suffix keys (`label_fr`) — pick whatever FieldRenderer/FieldDisplay and
  `intake-types.ts` absorb most cleanly, with nl as guaranteed fallback.
- **Catalog organization** — react-i18next conventions; likely per-feature namespaces (intake,
  admin, auth, common) with JSON files per locale, following the codebase's module layout.
- Where exactly the per-user locale override column lives (membership row vs a user-profile
  surface), the PATCH endpoint shape, and how the switcher component is styled from existing
  shadcn primitives.
- SSR/initial-render locale mechanics (TanStack Start), i18next detection plugin choice, and how
  the mail templates select locale variants (per-locale template files vs one template with
  translated strings).
- Which specific backend errors get codes first (D-11 scoping) and the code naming convention.
- CI guard mechanics: word list, file globs, exemption mechanism for legitimately Dutch content.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase scope & requirements
- `.planning/ROADMAP.md` § Phase 11 — goal, depends-on (Phase 6), 2 success criteria, UI hint.
- `.planning/REQUIREMENTS.md` — **I18N-01** (line 76), **I18N-02** (line 77).
- `.planning/PROJECT.md` — "Multi-language UI: NL/FR/EN (i18n)" active requirement + Key Decision
  ("done now rather than retrofitted later").

### Form content source of truth
- `backend/app/intake_canonical.py` — D-CANON: ONE canonical template served to every caller;
  fixed template id; schema loaded from the in-repo asset.
- `backend/app/data/pulse_intake_v1.json` — the 14-section schema whose Dutch strings D-05
  translates in-place (~16 KB; 46 labels, 17 descriptions, 15 titles, 6 placeholders).
- `frontend/src/lib/intake-types.ts` — `IntakeField`/`IntakeSection`/`IntakeSchema` types that
  must absorb the multi-locale shape.
- `frontend/src/components/intake/FieldRenderer.tsx` + `FieldDisplay.tsx` — the dual-mode field
  rendering that consumes the schema strings.

### Mail templates this phase translates (Phase 10 handoff)
- `backend/app/mail/templates/` — `validation.html.j2`, `results.html.j2`, `invite.html.j2`
  (+ `_base.html.j2`) get locale variants; `admin_validated.html.j2` stays Dutch (D-02).
- `.planning/phases/10-notifications/10-CONTEXT.md` — D-14 (Dutch Jinja2 ports, "email i18n is
  Phase 11's problem") and the Deferred Ideas entry this phase closes; D-05/D-08 recipient
  resolution the locale chain (D-07) extends.

### Locale persistence schema & surfaces
- `backend/app/db/models/membership.py` — `OrganizationMembership` (email/status/role), candidate
  host for the per-user locale override.
- `backend/app/db/models/` organization/space model — gets `default_locale` (D-07).
- `backend/app/api/admin_routes.py` — space create/edit endpoints the `default_locale` field
  extends (D-10); audit conventions.
- `frontend/src/lib/api/client.ts` — `apiFetch`/`ApiResult` transport; the error-code contract
  (D-11) surfaces here (never fork it).
- `frontend/src/lib/api/admin.ts` — space/member seam functions the locale fields extend.

### Date-locale call sites (D-04)
- `frontend/src/components/admin/ClientDetailDrawer.tsx`, `frontend/src/components/intake/
  ContextPackBlock.tsx`, `FieldDisplay.tsx`, `NextStepBanner.tsx`, `ResearchArtifacts.tsx`,
  `frontend/src/routes/admin.pulse.intakes.$id.tsx`, `intake.index.tsx` — hardcoded
  `date-fns/locale` `nl` imports to centralize. (`admin.sales.projects.*` are out of scope.)

### PDF exports (D-03)
- `frontend/src/components/intake/ContextPackPDF.tsx`, `NestorBriefingPDF.tsx` — Dutch labels move
  to the catalog.

### Patterns to follow
- `backend/scripts/ci_no_permissive_rls.sh` — the QA-02-style CI guard pattern D-13 mirrors.
- `.planning/phases/08-sse-skill-run-progress/08-CONTEXT.md` D-07 — infra/config changes go in
  Terraform AND the deploy runbook (applies if any new env/config appears).

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **No i18n framework exists yet** — react-i18next is a greenfield add (`frontend/package.json`
  has no i18n dependency); the roadmap goal names react-i18next explicitly.
- `frontend/src/lib/api/client.ts` `apiFetch`/`ApiResult` — the single transport where the D-11
  error-code fallback logic lands once.
- Space create/edit dialogs + member management UI (Phase 5) — `default_locale` field and
  per-member locale slot in beside existing fields.
- Phase 10 mail module (`backend/app/mail/`) — Jinja2 environment + render/send path already
  exists; locale selection extends it rather than rebuilding.
- shadcn `dropdown-menu`/`select` primitives — the switcher builds from these.

### Established Patterns
- ~138 frontend source files in scope-bearing dirs; Dutch strings concentrated in routes,
  intake/admin components, and toasts (`sonner` calls).
- `toast.error(error.message)` passes raw server text through today — D-11 replaces this with
  code-mapped translation + raw fallback.
- Alembic migrations own schema changes (next number after 0009); ORM models in
  `backend/app/db/models/` with explicit index naming.
- Tests authored by construction, run in Cloud Build (dev machine has no Python/Docker); frontend
  has no test runner — verification is UAT + CI guard.
- IaC drift is tracked: any new env var/config goes in Terraform AND the deploy runbook.

### Integration Points
- Language switcher → i18next `changeLanguage` + PATCH user locale → catalog swap + date-locale
  helper swap.
- Login page (pre-auth) → browser detection → post-login reconciliation with stored pref (D-09).
- `GET /intakes/templates` (canonical template) → multi-locale schema → FieldRenderer/FieldDisplay
  pick active locale with nl fallback.
- Mail send endpoints (Phase 10) → resolve recipient locale (user pref → space default → nl) →
  locale-variant Jinja2 render.
- CI pipeline → Dutch-string guard script alongside the existing QA-02 guard.

</code_context>

<specifics>
## Specific Ideas

- The switcher must work **before login** — an FR-speaking invitee clicking a mail link lands on
  the login page and needs to escape Dutch immediately (D-08/D-09).
- Email locale is resolved **server-side per recipient**, not from the sending admin's UI language
  — an NL admin sending to an FR client produces an FR mail (D-07/D-10).
- nl is the universal fallback at every level: missing catalog key, missing form-content variant,
  missing mail variant, unknown error code → raw server text.
- The CI guard should mirror the QA-02 grep-guard style the project already trusts (plant an
  offender in a negative test, assert non-zero exit).

</specifics>

<deferred>
## Deferred Ideas

- **Locale-aware AI output** — pass space/user locale into the Phase 7 skill prompts so research
  questions, context packs, and insights generate in the client's language. Deliberately excluded
  (D-06) to avoid re-opening validated AI behavior; strong v1.x candidate.
- **Sales routes i18n** (`admin.sales.*`) — translate if/when the sales track is re-platformed.
- **`admin_validated` mail i18n** — trivial to add later if the ops address ever serves
  non-Dutch operators.
- **Locales beyond NL/FR/EN** (e.g., DE) — the catalog/schema structure should make adding a
  locale mechanical, but no fourth locale ships in v1.

</deferred>

---

*Phase: 11-Internationalization (NL/FR/EN)*
*Context gathered: 2026-07-14*
