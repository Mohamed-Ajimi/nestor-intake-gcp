# Phase 11: Internationalization (NL/FR/EN) - Research

**Researched:** 2026-07-14
**Domain:** Frontend i18n (react-i18next on React 19 + TanStack Start), backend locale resolution (FastAPI + Jinja2), schema-content multi-locale, date-fns v4 locale switching
**Confidence:** HIGH (stack + codebase facts verified in-repo; SSR pattern MEDIUM-HIGH)

## Summary

This phase adds react-i18next to a React 19 + TanStack Start (Nitro/Cloudflare) app that runs
**almost entirely client-side after Firebase auth**. Every in-scope surface (intake fill, admin
Pulse lifecycle, space/user management) is gated behind a client-side `authReady()` / `useAuth()`
settle, so the SSR-hydration-mismatch risk that dominates TanStack Start i18n advice is **largely
sidestepped**: these routes render their real content only after the browser has a Firebase session,
which never exists during SSR. The one genuinely SSR-rendered surface is the pre-login shell
(`__root.tsx` sets `<html lang="en" translate="no">`). The safe, minimal pattern is: initialize a
single i18next instance synchronously at module load with a deterministic default (nl), bundle all
catalogs (no async HTTP backend), and drive language changes through `i18n.changeLanguage` — never
detect-and-switch inside a `useEffect` that would flip language post-hydration on an SSR'd node.

The heaviest lifting is **string externalization**: ~56 distinct Dutch strings live in
`admin.pulse.intakes.$id.tsx` alone, with `ResearchResultsPanel.tsx` (45) next. The work is
naturally chunkable by file/feature namespace (intake, admin, auth, common). Four cross-cutting
mechanisms must land first as shared infrastructure before parallel externalization can proceed:
(1) the i18next init + provider, (2) a central `getDateLocale(lang)` helper replacing 9 hardcoded
`date-fns/locale` `nl` imports, (3) the backend error-code contract threaded through the single
`apiFetch` transport, and (4) a `/me`-style boot endpoint + locale-persistence PATCH (no such
endpoint exists today — the frontend learns identity only from the Firebase `role` claim).

**Primary recommendation:** Land shared i18n infra (init, provider, LanguageSwitcher, `getDateLocale`,
locale-boot/PATCH, error-code map) as Wave 0/1, then parallelize externalization by namespace with
the density map below as the conflict-avoidance guide. Bundle catalogs statically; do not add
i18next-http-backend or a language-detector plugin that runs post-hydration on SSR'd nodes.

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01 (re-platform surfaces only):** Translate the v1 GCP flow — intake form, client views, admin
  Pulse lifecycle, space/user management, auth pages. Sales routes and coming-soon placeholders are
  explicitly excluded.
- **D-02 (client-facing mails ride along):** validation/results/reminder/invite Jinja2 templates get
  NL/FR/EN variants, render in the **recipient's** resolved locale. `admin_validated` stays Dutch.
- **D-03 (PDF exports use the same keys):** ContextPackPDF and NestorBriefingPDF label strings come
  from the i18n catalog, render in the active UI language.
- **D-04 (date locale follows language):** One central helper maps active language → date-fns locale
  (`nl`/`fr`/`enUS`); all 9 files that hardcode `import { nl } from "date-fns/locale"` switch to it.
- **D-05 (translations live in the canonical JSON):** Every display string in `pulse_intake_v1.json`
  carries nl/fr/en variants; frontend picks the active locale at render. **nl is the guaranteed
  fallback** for any missing variant.
- **D-06 (AI output language deferred):** Skill outputs stay as Phase 7 prompts produce them.
- **D-07 (space default + user override):** Migration adds `default_locale` on the space
  (organization) + per-user locale override. Resolution chain everywhere: **user pref → space
  default → nl**.
- **D-08 (switcher in header + login page):** One compact NL/FR/EN switcher, reused in authenticated
  chrome (ProductShell for admin, form header for clients) AND on the login page.
- **D-09 (browser → nl detection pre-login):** Before any preference is known: browser language if
  nl/fr/en, else nl. A pre-login switch persists to profile once logged in. New spaces default to nl.
- **D-10 (space dialog + auto-persist):** Superadmin edits `default_locale` in the space create/edit
  UI. A logged-in user's switcher flip PATCHes their profile immediately (no separate save). Email
  sends resolve each recipient's locale server-side via the D-07 chain.
- **D-11 (error-code contract):** User-facing endpoints return a stable machine code alongside
  `detail`; frontend maps code → translated toast, **falling back to raw server text for unmapped
  codes**. Scope the code set to errors users actually see.
- **D-12 (AI-drafted translations, user-reviewed):** Claude generates FR/EN translations (UI catalog,
  form content, mail templates), committed with the phase; user reviews tone in UAT.
- **D-13 (CI guard + sweep):** A Dutch-word regex CI scan over in-scope TSX/TS (QA-02
  `ci_no_permissive_rls.sh` style) plus a manual sweep.

### Claude's Discretion
- Multi-locale shape inside the canonical JSON (locale objects `label: {nl,fr,en}` vs suffix keys
  `label_fr`) — pick what FieldRenderer/FieldDisplay/`intake-types.ts` absorb most cleanly; nl fallback.
- Catalog organization — react-i18next conventions; likely per-feature namespaces (intake, admin,
  auth, common) with JSON per locale.
- Where the per-user locale override column lives (membership row vs user-profile surface), the PATCH
  endpoint shape, and switcher styling from shadcn primitives.
- SSR/initial-render locale mechanics, i18next detection plugin choice, mail-template locale selection
  (per-locale files vs one template with translated strings).
- Which backend errors get codes first (D-11 scoping) + code naming convention.
- CI guard mechanics: word list, file globs, exemption mechanism.

### Deferred Ideas (OUT OF SCOPE)
- Locale-aware AI output (pass locale into Phase 7 prompts) — deferred (D-06).
- Sales routes i18n (`admin.sales.*`) — stays Dutch.
- `admin_validated` mail i18n — stays Dutch.
- Locales beyond NL/FR/EN (e.g. DE).

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| I18N-01 | UI supports NL/FR/EN via an i18n framework; all hardcoded Dutch strings (labels, banners, toasts, date locale) externalized | react-i18next stack (below) + density map for externalization chunking + `getDateLocale` helper for date locale + CI guard design |
| I18N-02 | A user can switch language; a default locale applies per user/space | LanguageSwitcher pattern (D-08/09), locale-persistence endpoint design (`/me` boot + PATCH), migration for `default_locale` + user override (D-07), resolution chain |

## Project Constraints (from CLAUDE.md)

- **Frontend chrome untouched:** `frontend/src/components/ui/` (shadcn) must NOT be modified directly.
  Build the LanguageSwitcher as a NEW component composed from existing primitives (`dropdown-menu` or
  `select`), not by editing a `ui/` file.
- **Never fork `apiFetch`/`ApiResult`:** the D-11 error-code fallback logic extends the existing
  transport (`frontend/src/lib/api/client.ts`) — add code-extraction there, keep the `{success,error}`
  return contract.
- **`routeTree.gen.ts` is generated** — never hand-edit.
- **Import style:** always `@/` alias, double quotes, semicolons, `printWidth: 100`, `trailingComma:
  "all"` (Prettier config). New catalog JSON + i18n modules follow existing `lib/` layout.
- **Return-no-throw convention:** async helpers return `{ success, error? }`, never throw (salesMail.ts
  pattern). The locale-PATCH seam function in `lib/api/` follows this.
- **Tenant isolation:** locale is UX/personalization state, NEVER an authorization input. The
  per-user locale PATCH must re-derive the user from the verified token server-side; a client-supplied
  locale value can only change display, never widen access.
- **GSD workflow:** all edits go through a GSD command.
- **Backend:** Alembic owns schema (next migration after 0009); ORM models in `backend/app/db/models/`
  with **explicit index naming** (matches migration, no schema prefix — keeps `alembic check` clean).
- **IaC drift:** any new env var/config → Terraform AND the deploy runbook (D-07 Phase 8 pattern).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| UI string translation | Browser (i18next runtime) | — | Client-rendered after Firebase auth; catalogs bundled client-side |
| Language switcher / changeLanguage | Browser | API (persist) | UI state flips instantly; PATCH persists async |
| Locale detection pre-login | Browser | — | `navigator.language` → nl/fr/en else nl; no server session exists yet |
| User locale persistence | API / DB | Browser (boot read) | Server is authority; column on membership/org; frontend reads at boot |
| Space `default_locale` | API / DB | Browser (admin UI) | Superadmin edits via space dialog → PATCH → DB |
| Recipient-locale email render | API (Jinja2) | DB (resolution chain) | Resolved server-side per recipient (user pref→space→nl); render layer picks variant |
| Intake form content (schema) translation | API (asset served) | Browser (picks locale) | Canonical JSON carries nl/fr/en; `GET /intakes/templates` serves it; frontend selects active locale |
| Error-code → translated toast | API (emits code) | Browser (maps code) | Backend emits stable code; frontend owns the translation |
| Date-locale rendering | Browser (`getDateLocale`) | — | Pure client formatting; follows active i18n language |
| PDF label translation | Browser (imperative `pdf()`) | — | Rendered outside React tree — needs resolved strings passed in (see Pitfall 3) |
| CI Dutch-string guard | CI | — | Static scan over in-scope TSX/TS, QA-02 style |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `i18next` | 26.3.6 | Core i18n engine (catalog store, interpolation, fallback chain) | The framework the roadmap goal names; ecosystem standard `[VERIFIED: npm registry]` `[ASSUMED name from roadmap+training]` |
| `react-i18next` | 17.0.9 | React bindings — `useTranslation`, `Trans`, `I18nextProvider` | Official React binding for i18next; React 19 compatible `[VERIFIED: npm registry]` `[ASSUMED]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `i18next-browser-languagedetector` | 8.2.1 | Browser-language / cookie / localStorage detection | OPTIONAL — only if you want its detection chain. See Pitfall 1: configure it to NOT run a post-hydration `changeLanguage` on SSR'd nodes. A hand-rolled `navigator.language` check (≈10 lines) is simpler and fully controllable for the nl/fr/en-else-nl rule (D-09), and avoids the SSR footgun. Recommend **hand-rolled** given the client-render-after-auth model. `[VERIFIED: npm registry]` `[ASSUMED]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| react-i18next | use-intl (~2kb) / Paraglide (compile-time) | Lighter and more SSR-friendly, BUT the roadmap goal **mandates react-i18next** (locked). Do not re-litigate — noted only for completeness. |
| Bundled catalogs | i18next-http-backend | HTTP backend adds async load + hydration/flash risk. With only 3 locales and Claude-authored catalogs committed to the repo (D-12), **bundle statically** — zero network, deterministic first render. |

**Installation:**
```bash
cd frontend && npm install i18next@^26 react-i18next@^17
# date-fns already present at ^4 (verified 4.4.0 latest); no install needed for the locale helper
```

**Version verification:** `npm view` confirmed on 2026-07-14: `i18next` 26.3.6, `react-i18next`
17.0.9, `i18next-browser-languagedetector` 8.2.1, `date-fns` 4.4.0. Frontend already pins
`date-fns@^4.1.0` (package.json line 57) and `react@^19.2.0`.

## Package Legitimacy Audit

> slopcheck was NOT available in this research environment (no pip/Python on the dev machine per
> MEMORY.md). Per the graceful-degradation rule, the two NEW packages are tagged `[ASSUMED]` and the
> planner MUST gate each install behind a `checkpoint:human-verify` task. Registry existence was
> confirmed via `npm view`, but registry existence alone does not confer VERIFIED status.

| Package | Registry | Latest | Source Repo | slopcheck | Disposition |
|---------|----------|--------|-------------|-----------|-------------|
| `i18next` | npm | 26.3.6 | github.com/i18next/i18next (well-known, 8+ yrs, ~15M/wk) | unavailable | Approved — checkpoint:human-verify before install |
| `react-i18next` | npm | 17.0.9 | github.com/i18next/react-i18next (well-known, ~10M/wk) | unavailable | Approved — checkpoint:human-verify before install |
| `i18next-browser-languagedetector` | npm | 8.2.1 | github.com/i18next/i18next-browser-languageDetector | unavailable | OPTIONAL — recommend NOT installing (hand-roll detection); if used, checkpoint:human-verify |

**Packages removed due to slopcheck [SLOP] verdict:** none (slopcheck unavailable).
**Packages flagged [SUS]:** none — all three are the canonical, high-download i18next-org packages
with public GitHub repos. Planner should still add the checkpoint per the degradation rule.

## Architecture Patterns

### System Architecture Diagram

```
                          ┌──────────────────────────────────────────┐
  Browser language        │  APP BOOT (client, after Firebase auth)   │
  navigator.language ─────▶  1. i18n init (default = nl, static       │
  (nl/fr/en else nl)      │     bundled catalogs)                     │
                          │  2. GET /me → { locale, space_default }   │◀── NEW endpoint
                          │  3. i18n.changeLanguage(resolved)         │    (none today)
                          └───────────────┬──────────────────────────┘
                                          │
        ┌─────────────────────────────────┼─────────────────────────────┐
        ▼                                 ▼                             ▼
  ┌───────────┐                  ┌──────────────────┐          ┌────────────────┐
  │ UI render │                  │ LanguageSwitcher │          │ getDateLocale  │
  │ useTrans- │◀── catalog ──────│ changeLanguage() │          │ (lang→date-fns)│
  │ lation t()│    (namespaces)  │  + PATCH /me     │──────────▶│  format(...,   │
  └───────────┘                  └────────┬─────────┘   locale  │  { locale })   │
        │                                 │                     └────────────────┘
        │ error-code                      │ PATCH { locale }
        ▼                                 ▼
  ┌────────────────┐              ┌──────────────────┐
  │ apiFetch       │              │ Backend API      │
  │ extract `code` │◀── {detail,  │ membership.locale│──┐
  │ → t(errorKeys) │    code} ────│ org.default_locale│  │ persist
  └────────────────┘   on 4xx/5xx└─────────┬────────┘  ▼
                                            │      ┌──────────┐
  ┌─────────────────────┐                   │      │ Cloud SQL│
  │ Intake form content │◀─ GET /intakes/   │      └──────────┘
  │ FieldRenderer picks │   templates       │
  │ label[lang]∥label.nl│   (nl/fr/en asset)│
  └─────────────────────┘                   │
                                            ▼ mail send
                              ┌──────────────────────────────┐
                              │ resolve recipient locale      │
                              │ (user pref→space→nl) →         │
                              │ Jinja2 render locale variant   │
                              └──────────────────────────────┘
```

### Recommended Project Structure
```
frontend/src/
├── lib/
│   ├── i18n/
│   │   ├── index.ts            # i18next.init() — single instance, bundled catalogs, nl fallback
│   │   ├── detect.ts           # hand-rolled navigator.language → nl|fr|en else nl (D-09)
│   │   ├── date-locale.ts      # getDateLocale(lang): "nl"|"fr"|"enUS" (D-04) — replaces 9 imports
│   │   └── error-codes.ts      # code → i18n key map for D-11 toasts
│   └── api/
│       └── me.ts               # NEW: getMe() boot read + patchLocale() (return-no-throw)
├── locales/
│   ├── nl/{common,intake,admin,auth}.json
│   ├── fr/{common,intake,admin,auth}.json
│   └── en/{common,intake,admin,auth}.json
└── components/
    └── LanguageSwitcher.tsx    # NEW, composed from shadcn dropdown-menu/select (NOT in ui/)
```

### Pattern 1: Single synchronous i18n instance with bundled catalogs
**What:** Initialize one i18next instance at module import with all catalogs inlined and `nl` as
`fallbackLng`. Wrap the app in `I18nextProvider` (or rely on the default export + `initReactI18next`).
**When to use:** Always here — the app is client-rendered after auth, so a deterministic default at
first paint plus a single `changeLanguage` after `/me` resolves avoids flashes.
**Example:**
```typescript
// Source: react-i18next official docs pattern (CITED: react.i18next.com/latest/using-with-hooks)
import i18n from "i18next";
import { initReactI18next } from "react-i18next";
import nlCommon from "@/locales/nl/common.json";
// ...import all namespaces per locale (bundled, no HTTP backend)

void i18n.use(initReactI18next).init({
  resources: {
    nl: { common: nlCommon, intake: nlIntake, admin: nlAdmin, auth: nlAuth },
    fr: { /* ... */ },
    en: { /* ... */ },
  },
  lng: "nl",                 // deterministic default; changeLanguage after /me
  fallbackLng: "nl",         // D-05/D-09 universal fallback
  defaultNS: "common",
  interpolation: { escapeValue: false }, // React already escapes
  returnNull: false,
});
export default i18n;
```

### Pattern 2: `Trans` for interpolated JSX
**What:** Use `<Trans>` when a translated string wraps JSX (links, `<strong>`, dynamic counts) that
plain `t()` string interpolation can't express.
**When to use:** Sentences with embedded elements — several intake banners and confirmation messages
interpolate `{{contact_email}}` etc. Simple `t("key", { email })` covers value interpolation; reserve
`<Trans>` for embedded elements.

### Pattern 3: Central date-locale helper (D-04)
```typescript
// Source: date-fns v4 locale API (CITED: date-fns.org/v4/docs/format) + repo convention
import { nl, fr, enUS, type Locale } from "date-fns/locale";
export function getDateLocale(lang: string): Locale {
  return lang.startsWith("fr") ? fr : lang.startsWith("en") ? enUS : nl; // nl fallback
}
// call sites: format(d, "d MMM yyyy", { locale: getDateLocale(i18n.language) })
```
The 9 files importing `{ nl } from "date-fns/locale"` (7 in-scope + 2 sales/out-of-scope) switch to
this helper. **In-scope (must change):** `ClientDetailDrawer.tsx`, `ContextPackBlock.tsx`,
`NextStepBanner.tsx`, `ResearchArtifacts.tsx`, `FieldDisplay.tsx`, `admin.pulse.intakes.$id.tsx`,
`intake.index.tsx`. **Out-of-scope (leave):** `admin.sales.projects.$id.tsx`,
`admin.sales.projects.index.tsx`.

### Pattern 4: Error-code contract threaded through apiFetch (D-11)
**Backend:** `HTTPException` today carries only a string `detail` (verified: every raise is
`HTTPException(status.HTTP_4xx, "string")`). Add a machine `code` WITHOUT breaking `detail`. Two
backward-compatible options for the planner to choose from:
- (a) Return a structured detail object `{"detail": {"code": "INTAKE_NOT_FOUND", "message": "..."}}`
  — but `apiFetch` currently reads `detail` as a string (client.ts line 68-75), so this needs the
  transport to handle both shapes.
- (b) Add a sibling top-level field: `{"detail": "Intake not found", "code": "INTAKE_NOT_FOUND"}`
  via a small custom exception + handler. **Recommended** — the existing `detail`-as-string path in
  `apiFetch` keeps working untouched (raw-text fallback per D-11), and `code` is read additively.
**Frontend:** extend `apiFetch` to also surface `code` on the failure branch, and map it in
`error-codes.ts`; the toast prefers `t(codeKey)` and falls back to the raw `error` string for unmapped
codes.

### Anti-Patterns to Avoid
- **`changeLanguage` inside a `useEffect` on an SSR'd node:** flips language after hydration → mismatch
  + flash (documented TanStack Start failure mode). Do the initial `changeLanguage` in the client boot
  path, before/at the auth-settle, not on a server-rendered element.
- **Editing `frontend/src/components/ui/*`:** the switcher is a new component composed from primitives.
- **Async HTTP catalog backend:** unnecessary for 3 bundled locales; adds flash/mismatch surface.
- **Reading locale from the client to gate access:** locale is display-only; never an authz input.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Interpolation, plural rules, fallback chain, nested keys | Custom string-map + `.replace()` | i18next | Handles nl/fr plural forms, `{{var}}` interpolation, namespace + fallback resolution correctly |
| JSX-embedded translations | Manual string-splicing around `<a>`/`<strong>` | `<Trans>` | Preserves element nesting + interpolation safely |
| Date/relative-time locale formatting | Custom month/day name maps | date-fns v4 `{ locale }` (already a dep) | Correct nl/fr/en names, no drift |
| Detection | (allowed to hand-roll the ≈10-line nl/fr/en-else-nl rule) | plain `navigator.language` check | Simpler + fully controllable than the detector plugin's post-hydration behavior |

**Key insight:** The framework choice (react-i18next) is locked; the value-add of the research is
telling the planner *what NOT to add around it* (no HTTP backend, no post-hydration detector switch)
and where the real work is (externalization volume + the 4 shared-infra seams).

## Runtime State Inventory

> This phase is partly a rename/externalization sweep, so a state inventory applies.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `organization_memberships` rows + `organizations` rows exist; new `default_locale` (org) and per-user locale columns need a **default backfill** (`nl`) on migration. Superadmin memberships may not exist (superadmin is a DB role, cross-tenant — a superadmin can lack any membership row per `membership.py` docstring). | Migration adds columns with `server_default='nl'`; **investigate a locale home for superadmins with no membership row** — options: a nullable column that falls back to browser/nl, or a lightweight per-user preference store keyed by Firebase uid. Planner decides (Open Question 1). |
| Live service config | No i18n runtime config in any external service. Firebase custom claims carry only `role` (verified in `auth-context.tsx` / `session.py`) — locale is NOT a claim and should not become one (claims don't auto-refresh; a locale flip would need a token re-mint — wrong tool). | None — persist locale in Cloud SQL, not in claims. |
| OS-registered state | None. | None — verified: no OS-level string registration for i18n. |
| Secrets/env vars | Mail already uses `APP_BASE_URL`, `NESTOR_ADMIN_EMAIL`, `RESEND_API_KEY` (Phase 10). No NEW secret needed for i18n. If any new config appears (unlikely), it goes in Terraform + runbook (IaC-drift rule). | None expected. |
| Build artifacts | Frontend build bundles the new `locales/*.json` — no stale artifact risk (Vite re-bundles). `routeTree.gen.ts` regenerates on build; a new LanguageSwitcher component does not add a route. | None — do not hand-edit `routeTree.gen.ts`. |

**The canonical question — after every file is updated, what still carries Dutch?** Answer: the DB
default-locale columns (backfilled to `nl`), the intake canonical JSON (translated in-place, D-05),
the mail templates (locale variants, D-02), and the `admin_validated` mail + all `admin.sales.*`
routes (deliberately Dutch, out of scope). The CI guard (D-13) must exempt the last two.

## Common Pitfalls

### Pitfall 1: SSR/hydration language mismatch
**What goes wrong:** Server renders with one language (or the `<html lang>` default), client detects a
different one and `changeLanguage`s during hydration → React hydration error + content flash.
**Why it happens:** react-i18next detection plugins default to running detection + switch immediately,
including on server-rendered markup.
**How to avoid:** This app renders in-scope content **only after client-side Firebase auth settles**
(every in-scope route gates on `authReady()`/`useAuth().loading`), so the SSR'd DOM for those routes
is a loading shell, not translated content. Keep it that way: initialize i18next with `lng: "nl"`
deterministically, do the resolved `changeLanguage` in the client boot after `/me`, and do NOT wire a
detector that switches on the pre-login SSR shell. For the login page (genuinely SSR-able), the
pre-login `navigator.language` detection runs client-side only (`typeof window` guard, mirroring the
existing `active-space.tsx` `readPersisted()` pattern).
**Warning signs:** "Text content did not match" hydration warnings; a visible flash of Dutch→French on
the login page.

### Pitfall 2: The `/me` endpoint does not exist yet
**What goes wrong:** Plans assume the frontend can read the user's stored locale at boot — but there is
**no identity/profile endpoint today**. The frontend learns identity solely from the Firebase `role`
custom claim (`auth-context.tsx`); `apiFetch` has no `/me` or `/profile` call (verified — grep found
none).
**Why it happens:** Phase 3-6 only needed the `role` claim for UX gating; no server round-trip for
profile.
**How to avoid:** This phase must ADD a boot read (e.g. `GET /me` returning `{ locale, space_default_locale }`)
plus the persist PATCH. Both live under the default-deny `protected_router`. This is net-new backend
surface — the planner must budget a task for it, not assume it exists.
**Warning signs:** A plan task says "read user locale from context" with no endpoint to source it.

### Pitfall 3: `t()` inside PDF components won't work
**What goes wrong:** ContextPackPDF/NestorBriefingPDF are rendered **imperatively** via
`pdf(<Component/>).toBlob()` (verified: `ContextPackPDF.tsx:305`, `NestorBriefingPDF.tsx:321`) —
OUTSIDE the React tree / `I18nextProvider`. A `useTranslation()` hook inside them has no provider
context and will use defaults or throw.
**Why it happens:** `@react-pdf/renderer`'s `pdf()` renders a detached element tree.
**How to avoid:** Pass a resolved translator or pre-resolved label strings into the PDF component as
props from the calling component (which IS inside the provider). E.g. build a `labels` object with
`t()` at the call site and thread it in, OR pass `i18n.getFixedT(lang, ns)` and call that inside.
**Warning signs:** PDF labels render in the fallback language regardless of active UI language.

### Pitfall 4: Canonical JSON shape change breaks every consumer
**What goes wrong:** `GET /intakes/templates` serves ONE canonical asset to EVERY authenticated caller
(D-CANON). Changing `label: "..."` to `label: {nl,fr,en}` breaks `intake-types.ts`, `FieldRenderer`,
`FieldDisplay`, `IntakeForm`, and anywhere `.label/.title/.description/.help/.placeholder` is read,
unless all are updated in the same phase.
**Why it happens:** The type `IntakeField.label` is `string` today (intake-types.ts:31); a shape change
is a breaking type change.
**How to avoid:** Prefer a shape the consumers absorb with a single accessor. Recommended: keep scalar
keys but add a resolver — either (a) locale-object values (`label: {nl,fr,en}`) with a
`localize(field.label, lang)` helper used at every read site, or (b) parallel suffix keys
(`label`, `label_fr`, `label_en`) resolved by a `pick(field, "label", lang)` helper. Option (a) is
cleaner for "translations travel with the template" (D-05). Introduce ONE `localizeSchema(schema, lang)`
pass at load that flattens to the current scalar shape, so `FieldRenderer`/`FieldDisplay` stay almost
untouched — minimizes blast radius. Update `intake-types.ts` to the new source shape + a resolved shape.
**Warning signs:** Type errors across intake components; raw `{nl:...,fr:...}` objects rendering in the form.

### Pitfall 5: CI guard false positives
**What goes wrong:** A naive Dutch-word regex flags legitimate content — the locale catalogs
themselves (which are supposed to contain Dutch), sales routes (deliberately Dutch), `.gen.ts` files,
and Dutch substrings inside identifiers/URLs.
**How to avoid:** Scope the glob tightly and exempt: `src/locales/**`, `**/*.gen.ts`,
`admin.sales.*`, `**/coming-soon*`, `ui/**`, `admin_validated.html.j2`, the canonical JSON. Match only
Dutch words in JSX text or string literals (see CI guard design below). Mirror the QA-02 exit-code
contract exactly.

## Code Examples

### Boot read + persist (new seam, return-no-throw)
```typescript
// Source: repo convention (lib/api/admin.ts) + apiFetch transport
import { apiFetch, type ApiResult } from "@/lib/api/client";
export type Me = { locale: "nl" | "fr" | "en" | null; space_default_locale: "nl" | "fr" | "en" };
export function getMe(): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me", { method: "GET" });
}
export function patchLocale(locale: "nl" | "fr" | "en"): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me/locale", { method: "PATCH", body: JSON.stringify({ locale }) });
}
```

### Backend error-code (option b — additive, backward compatible)
```python
# Source: repo pattern (auth_routes.py exception handling) — additive `code` field
from fastapi import HTTPException, status
# Existing raises keep working (detail stays a string → apiFetch raw-text fallback).
# For user-visible errors, attach a code the frontend can translate:
raise HTTPException(
    status.HTTP_404_NOT_FOUND,
    detail="Intake not found",           # raw fallback (D-11)
    headers={"X-Error-Code": "INTAKE_NOT_FOUND"},  # OR a custom-exception+handler emitting {detail, code}
)
# Planner picks the transport (header vs body field); body field is more idiomatic — see Open Q 3.
```

### CI guard skeleton (D-13, QA-02 style)
```bash
#!/usr/bin/env bash
# scripts/ci_no_hardcoded_dutch.sh — exit 1 if any in-scope TSX/TS contains a Dutch stopword
# in a string literal / JSX text. Mirrors ci_no_permissive_rls.sh (exit code IS the gate).
set -euo pipefail
SCAN_DIR="${1:-frontend/src}"
# Low-false-positive Dutch stopwords that are NOT English/code identifiers:
PATTERN='\b(niet|geen|wordt|klant|ingelogd|opnieuw|versturen|bekijken|opslaan|verwijderen|annuleren|beschikbaar|vernieuwen|ruimte|gebruiker|verplicht|mislukt)\b'
# Exempt: catalogs, generated, shadcn, sales, coming-soon.
if grep -rEni --include='*.ts' --include='*.tsx' "$PATTERN" "$SCAN_DIR" \
     | grep -vE '(/locales/|\.gen\.ts|/ui/|admin\.sales\.|coming-soon|\.test\.)'; then
  echo "ERROR: hardcoded Dutch string found in in-scope source." >&2; exit 1
fi
echo "OK: no hardcoded Dutch in in-scope source."; exit 0
```
**Negative test (D-13):** plant an offender (`const x = "niet beschikbaar";`) in a temp file under a
non-exempt path, point the guard at it, assert non-zero exit — mirrors the QA-02 negative test.

## Dutch-String Density Map (externalization chunking guide)

> Counts = occurrences of a curated Dutch-stopword set per in-scope file (2026-07-14 scan). Use to
> chunk parallel externalization plans with minimal file-conflict. Highest-density files should be
> their own plan unit.

| File | ~Dutch hits | Suggested namespace | Notes |
|------|-------------|--------------------|-------|
| `routes/admin.pulse.intakes.$id.tsx` | 56 | admin/intake | **Highest** — its own plan unit; also a date-fns call site |
| `components/intake/ResearchResultsPanel.tsx` | 45 | intake | Own plan unit |
| `routes/intake.$id.results.tsx` | 18 | intake | |
| `components/admin/InviteUserDialog.tsx` | 18 | admin | |
| `routes/admin.users.tsx` | 17 | admin | |
| `components/intake/ResearchArtifacts.tsx` | 17 | intake | date-fns call site |
| `components/intake/AIReviewPanel.tsx` | 17 | intake | |
| `components/intake/IntakeForm.tsx` | 15 | intake | Renders the client form header (switcher mount, D-08) |
| `routes/intake.$id.tsx` | 14 | intake | |
| `components/intake/NextStepBanner.tsx` | 13 | intake | date-fns call site |
| `components/intake/RecipientPicker.tsx` | 11 | intake | |
| `components/intake/ContextPackBlock.tsx` | 11 | intake | date-fns call site |
| `routes/auth.login.tsx` | 10 | auth | Switcher mount pre-login (D-08) |
| `components/admin/ClientFormModal.tsx` | 9 | admin | |
| `components/intake/HandoffBlock.tsx` | 8 | intake | |
| `components/admin/ClientDetailDrawer.tsx` | 8 | admin | date-fns call site |
| `routes/auth.action.tsx` | 7 | auth | |
| `components/intake/FinalReportBlock.tsx` | 7 | intake | |
| `routes/intake.index.tsx` | 6 | intake | date-fns call site |
| `routes/admin.templates.tsx` | 6 | admin | |
| `routes/admin.spaces.tsx` | 6 | admin | Space dialog — hosts `default_locale` field (D-10) |
| `routes/admin.pulse.intakes.new.tsx` | 6 | admin | |
| `routes/admin.pulse.clients.$id.tsx` | 6 | admin | |
| `components/intake/FieldRenderer.tsx` | 6 | intake | Consumes canonical schema strings (D-05) |
| `routes/admin.pulse.clients.tsx` | 5 | admin | |
| `components/intake/AISkillsPanel.tsx` | 5 | intake | |
| `components/admin/SpaceSwitcher.tsx` | 5 | admin | |
| `components/intake/NestorBriefingPDF.tsx` | 4 | intake | PDF — Pitfall 3 (pass resolved strings) |
| `components/intake/FieldDisplay.tsx` | 4 | intake | date-fns call site + schema consumer |
| (14 more files, 1-3 hits each) | ~30 total | various | `common` namespace catch-all |

*Counts are approximate (stopword scan, not a full literal parse) — the manual sweep (D-13) is the
source of truth for completeness. ContextPackPDF.tsx did not hit the stopword scan but still has
labels to externalize (verify during the sweep).*

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Hardcoded Dutch strings inline | react-i18next catalogs | this phase | All in-scope UI text moves to `locales/*.json` |
| 9× `import { nl } from "date-fns/locale"` | central `getDateLocale(lang)` | this phase | Date formatting follows active language |
| `toast.error(error.message)` (raw server text) | code → `t()` with raw fallback | this phase (D-11) | User-facing errors translate |
| No profile round-trip (role claim only) | `GET /me` boot + `PATCH /me/locale` | this phase | First server identity read beyond claims |

**Deprecated/outdated:** i18next-xhr-backend (replaced by i18next-http-backend) — irrelevant here
since catalogs are bundled. Any training-era advice to use the language-detector plugin uncritically is
risky under SSR — see Pitfall 1.

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Package names `i18next` / `react-i18next` are the correct, non-slopsquatted packages (registry-confirmed but slopcheck unavailable) | Standard Stack | Low — canonical i18next-org packages, but planner must checkpoint:human-verify before install |
| A2 | react-i18next 17 is React 19-compatible | Standard Stack | Low-Med — verify peer deps at install; react-i18next has supported React 18+ hooks for years |
| A3 | Bundling catalogs (no HTTP backend) is the right call | Alternatives | Low — 3 small locales, committed per D-12; changing later is mechanical |
| A4 | A `GET /me`-style endpoint is the cleanest boot read for locale | Pitfall 2 / Code Examples | Med — endpoint shape is planner's discretion; the *need* for a new endpoint is verified (none exists) |
| A5 | Superadmins may lack a membership row (so their locale needs another home) | Runtime State / Open Q1 | Med — inferred from `membership.py` docstring ("superadmin is a DB role, not a row attribute"); verify with a superadmin account |
| A6 | Dutch-stopword counts approximate externalization volume | Density Map | Low — guide only; manual sweep is source of truth |
| A7 | date-fns v4 locale exports `fr` and `enUS` under `date-fns/locale` | Pattern 3 | Low — stable date-fns API; verify import at build |

## Open Questions (RESOLVED)

1. **Where does a superadmin's locale preference live?**
   - What we know: `default_locale` on org + per-user override on membership covers regular users.
     Superadmin is a DB role and may have no membership row (`membership.py` docstring).
   - What's unclear: the persistence home for a superadmin's own UI locale.
   - Recommendation: a nullable per-user locale keyed by Firebase uid (a tiny `user_preferences` table
     or a nullable column that tolerates no-membership), falling back to browser→nl. Confirm in
     discuss/plan; low effort either way.
   - RESOLVED: membership.locale is nullable; a superadmin with no membership row persists nothing and
     GET /me returns `locale: null` (client falls back browser→nl). (11-02 Task 1/Task 2)
2. **Canonical JSON shape — locale objects vs suffix keys?**
   - What we know: consumers read scalar `.label/.title/.description/.help/.placeholder`.
   - Recommendation: locale-object values + a single `localizeSchema(schema, lang)` load-time pass
     that flattens to today's scalar shape → near-zero change in FieldRenderer/FieldDisplay. (Planner's
     discretion per CONTEXT.)
   - RESOLVED: locale-object shape ({nl,fr,en}) in the canonical JSON + `localizeSchema(schema, lang)`
     load-time flatten to the scalar shape, nl fallback. (11-03 Task 1)
3. **Error-code transport — response body field vs custom exception/handler?**
   - Recommendation: a small custom exception + FastAPI exception handler emitting
     `{"detail": "<raw>", "code": "<CODE>"}`, so `apiFetch`'s existing string-`detail` path is
     untouched and `code` is read additively. Scope codes to user-visible errors only (D-11).
   - RESOLVED: a `CodedError` custom exception + a FastAPI exception handler emitting
     `{"detail": "<raw>", "code": "<CODE>"}`; apiFetch reads `code` additively. (11-02 Task 3)
4. **Does `admin_validated.html.j2` share `_base.html.j2` with the localized mails?**
   - If mail locale variants are done as per-locale template files, the shared `_base` must stay
     Dutch-neutral or be parameterized. Recommendation: one template per mail with translated *strings*
     passed in (or a `{locale}/` subdir), keeping `_base` structural-only. Planner's discretion (D-02).
   - RESOLVED: per-locale template dirs `templates/{nl,fr,en}/`; `_base.html.j2` stays structural-only;
     `admin_validated.html.j2` stays top-level Dutch. (11-08 Task 1)

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| npm (frontend install) | i18next/react-i18next install | ✓ | — | — |
| Node build (Vite) | catalog bundling | ✓ | — | — |
| date-fns | date-locale helper | ✓ (dep) | 4.1.0 pinned (4.4.0 latest) | — |
| Python/Docker (backend local run) | migration + /me + mail render tests | ✗ | — | Author by construction; run via Cloud Build (MEMORY.md) |
| gcloud / Cloud Build | run backend tests, deploy | ✓ | — | — |
| Frontend test runner | verify externalization | vitest present (package.json:13,98) but MEMORY says "no test runner" — reconcile | 3.2.4 | UAT + CI guard (D-13) is the safety net |

**Missing dependencies with no fallback:** none.
**Missing dependencies with fallback:** backend tests authored-by-construction, executed in Cloud
Build; frontend verification leans on the CI Dutch-string guard + UAT per project norms.

## Validation Architecture

> `.planning/config.json` not inspected for `nyquist_validation`; included conservatively. Note the
> project reality: backend tests run in Cloud Build only (no local Python/Docker), and the frontend
> historically has no runner (vitest IS in package.json but MEMORY.md says none is used) — verification
> is primarily the CI guard + UAT.

### Test Framework
| Property | Value |
|----------|-------|
| Framework (frontend) | vitest 3.2.4 (present; `npm test` → `vitest run`) — but effectively unused per MEMORY.md |
| Framework (backend) | pytest (existing 150-test suite, run via Cloud Build) |
| Quick run command | `cd frontend && npm run test` (frontend); Cloud Build config (backend) |
| Full suite command | Cloud Build (backend); CI Dutch-string guard for i18n coverage |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| I18N-01 | No hardcoded Dutch in in-scope source | CI guard | `bash scripts/ci_no_hardcoded_dutch.sh` | ❌ Wave 0 |
| I18N-01 | CI guard catches a planted offender | unit (bash) | negative-test invocation (QA-02 style) | ❌ Wave 0 |
| I18N-01 | `getDateLocale` maps lang→locale w/ nl fallback | unit | `vitest` on `lib/i18n/date-locale.test.ts` | ❌ Wave 0 |
| I18N-01 | Error-code map resolves + falls back to raw | unit | `vitest` on `error-codes.test.ts` | ❌ Wave 0 |
| I18N-02 | Locale PATCH persists + is re-read at boot | integration (backend) | pytest via Cloud Build | ❌ Wave 0 |
| I18N-02 | Mail renders in recipient's resolved locale | unit (backend) | pytest render tests (extend Phase 10) | ❌ Wave 0 |
| I18N-02 | Switcher visible + functional pre-login | manual/UAT | UAT checklist | manual-only |
| I18N-01/02 | UI renders fully NL/FR/EN, no flash | manual/UAT | UAT checklist (D-12 tone review) | manual-only |

### Sampling Rate
- **Per task commit:** `npm run test` (any new frontend unit tests) + the Dutch-string guard.
- **Per wave merge:** backend pytest via Cloud Build; full CI guard.
- **Phase gate:** CI guard green + UAT sign-off (translations reviewed, D-12).

### Wave 0 Gaps
- [ ] `frontend/scripts/ci_no_hardcoded_dutch.sh` (+ negative test) — covers I18N-01
- [ ] `frontend/src/lib/i18n/date-locale.test.ts` — covers I18N-01 date locale
- [ ] `frontend/src/lib/i18n/error-codes.test.ts` — covers I18N-01 error toasts
- [ ] backend: `/me` + locale-PATCH tests; mail recipient-locale render tests (extend Phase 10) — I18N-02
- [ ] i18n init + provider + LanguageSwitcher (shared infra, blocks parallel externalization)

## Security Domain

> `security_enforcement` assumed enabled (project has heavy tenant-isolation focus). i18n is
> low-security-surface but two controls matter.

### Applicable ASVS Categories
| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | Unchanged — Firebase auth untouched |
| V4 Access Control | yes | Locale is display-only; PATCH re-derives user from verified token — a client-supplied locale can never widen access (tenant-isolation invariant) |
| V5 Input Validation | yes | Validate `locale ∈ {nl,fr,en}` on the PATCH (reject arbitrary values); error `code` set is a fixed enum |
| V6 Cryptography | no | — |
| V14 Config | yes | Any new env/config → Terraform + runbook (IaC-drift rule) |

### Known Threat Patterns
| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| XSS via translated string interpolation | Tampering | React auto-escapes; `<Trans>` for JSX; `interpolation.escapeValue:false` is SAFE only because React escapes. Never `dangerouslySetInnerHTML` a catalog value. Mail Jinja2 keeps `autoescape=True` (T-10-01) in locale variants. |
| Locale param as authz input | Elevation of Privilege | Locale never gates access; PATCH re-derives user server-side (V4) |
| Error `detail` leaking internals via new `code` path | Info Disclosure | Codes are a curated user-facing enum; internal 4xx/5xx keep generic messages, no stack/detail leak |

## Sources

### Primary (HIGH confidence)
- Codebase (verified in-repo, 2026-07-14): `client.ts`, `auth-context.tsx`, `active-space.tsx`,
  `ProductShell.tsx`, `intake-types.ts`, `render.py`, `intake_routes.py` (mail send + error raises),
  `membership.py`, `organization.py`, `ci_no_permissive_rls.sh`, `pulse_intake_v1.json`,
  `ContextPackPDF.tsx`/`NestorBriefingPDF.tsx` (`pdf().toBlob()` call sites), date-fns import scan,
  Dutch-string density scan.
- npm registry (`npm view`, 2026-07-14): i18next 26.3.6, react-i18next 17.0.9,
  i18next-browser-languagedetector 8.2.1, date-fns 4.4.0.

### Secondary (MEDIUM confidence)
- TanStack Start i18n / SSR-hydration guidance — nikuscs.com/blog/13-tanstackstart-i18n,
  tanstack.com/start docs (hydration-errors), better-i18n docs. Used to derive the "init synchronously,
  don't post-hydration-switch" rule; cross-checked against this app's client-render-after-auth reality.

### Tertiary (LOW confidence)
- General react-i18next `useTranslation`/`Trans`/init API — training knowledge, marked `[ASSUMED]`
  where not doc-verified; planner should confirm exact init options against react.i18next.com at build.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — versions registry-verified; react-i18next mandated + confirmed present-able.
- Architecture / codebase facts: HIGH — every integration point read in-repo.
- SSR pattern: MEDIUM-HIGH — general TanStack Start risk verified via web + neutralized by this app's
  client-render-after-auth model (verified in code).
- Externalization volume: MEDIUM — stopword scan approximates; manual sweep is authoritative.
- Backend error-code + /me shape: MEDIUM — the *need* is verified; the exact shape is planner's discretion.

**Research date:** 2026-07-14
**Valid until:** 2026-08-14 (30 days — stable stack; re-verify react-i18next React-19 peer deps at install)
