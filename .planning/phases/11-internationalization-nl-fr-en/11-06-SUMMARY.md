---
phase: 11-internationalization-nl-fr-en
plan: 06
subsystem: frontend-auth-i18n
tags: [i18n, auth, react-i18next, locale-boot, pre-login-switcher]
requires:
  - "11-01: i18n runtime (i18n.changeLanguage), detectLocale, LanguageSwitcher (persist prop, LOCALE_STORAGE_KEY), me seam (getMe/patchLocale)"
  - "11-02: backend GET/PATCH /me endpoint"
provides:
  - "Login page externalized (NL/FR/EN) with a working pre-login LanguageSwitcher (persist=false)"
  - "Auth-action set-password flow externalized (NL/FR/EN)"
  - "Boot-locale reconciliation in auth-context: resolve + apply UI language once per authenticated session, persist a pending pre-login choice"
  - "auth.json catalogs populated (login.* + action.*) in nl/fr/en"
affects:
  - "frontend/src/routes/auth.login.tsx"
  - "frontend/src/routes/auth.action.tsx"
  - "frontend/src/lib/auth-context.tsx"
  - "frontend/src/locales/{nl,fr,en}/auth.json"
tech-stack:
  added: []
  patterns:
    - "String externalization via useTranslation(\"auth\") + t(\"login.*\") / t(\"action.*\")"
    - "Module-level error mapper takes TFunction and returns localized copy (authErrorMessage(t, code))"
    - "Once-per-session boot effect with a useRef uid guard, gated on session+role settle (client-only, SSR-safe)"
    - "Return-no-throw ApiResult consumption (getMe/patchLocale) with graceful fallback"
key-files:
  created: []
  modified:
    - "frontend/src/routes/auth.login.tsx"
    - "frontend/src/routes/auth.action.tsx"
    - "frontend/src/lib/auth-context.tsx"
    - "frontend/src/locales/nl/auth.json"
    - "frontend/src/locales/fr/auth.json"
    - "frontend/src/locales/en/auth.json"
decisions:
  - "auth.login pre-login language initializes from detectLocale() only when no pending localStorage choice exists (respects an explicit prior choice)"
  - "dutchAuthError -> authErrorMessage(t, code): the module-level Firebase-error mapper now takes the auth-namespace TFunction and returns a translated message, keeping the switch out of the component while staying localized"
  - "Boot reconciliation is gated on session && role settle (matches AuthRedirector's settle signal); role is not used to pick the locale, only to confirm the auth boot has settled"
  - "auth-context re-uses LOCALE_STORAGE_KEY exported from LanguageSwitcher (single source of truth for the pre-login key) rather than redefining the literal"
metrics:
  duration: ~25 min
  completed: 2026-07-14
  tasks: 3
  files: 6
---

# Phase 11 Plan 06: Auth i18n + Boot-Locale Reconciliation Summary

Externalized the two auth pages (login + set-password action) into the NL/FR/EN `auth`
catalog, mounted the pre-login `LanguageSwitcher` on the login page (so an FR/EN invitee
can escape Dutch before authenticating), and wired the boot-locale reconciliation in
`auth-context` — a once-per-authenticated-session, SSR-safe resolve + `i18n.changeLanguage`
after `/me` resolves, with a pending pre-login choice persisted to the profile via
`patchLocale`.

## What Was Built

### Task 1 — auth.login externalized + pre-login switcher (commit 9dbf25a)
- Added `useTranslation("auth")`; replaced all 10 Dutch literals (heading, placeholders,
  button labels, `SyncError` messages, the credential/generic/toast error copy, and the
  "no account" footer) with `t("login.*")`.
- Mounted `<LanguageSwitcher persist={false} />` in the login-page chrome (D-08). Pre-login
  the switcher writes only localStorage (no session to PATCH yet).
- On first client render, when no pending pre-login choice exists in localStorage, the
  display language initializes from `detectLocale()` (browser → nl/fr/en else nl, D-09).
  This runs client-side only (detectLocale is `typeof window`-guarded; the effect never
  runs on the SSR shell — Pitfall 1).
- Added `login.*` keys to nl/fr/en `auth.json` (nl verbatim, fr/en drafted — D-12).

### Task 2 — auth.action externalized (commit 693d08b)
- Added `useTranslation("auth")`; replaced all 7 Dutch literals (heading, verifying /
  unsupported / invalid copy, "to login" link, set-password-for label, placeholders,
  submit/submitting labels, mismatch inline error, success toast).
- Refactored the module-level `dutchAuthError(code)` into `authErrorMessage(t, code)` so
  the Firebase-error → message mapping stays out of the component body but is now localized
  (takes the `auth`-namespace `TFunction`, returns translated copy).
- Added `action.*` keys (incl. `action.errors.*`) to nl/fr/en `auth.json`.

### Task 3 — boot-locale reconciliation in auth-context (commit 501cd96)
- Added a post-auth-settle `useEffect` gated on `!loading && session && role`, guarded by a
  `bootedLocaleUidRef` so it runs exactly once per authenticated session (ref reset to null
  on sign-out). Runs client-only, post-auth — never on the SSR'd node (Pitfall 1).
- Resolution order (first hit wins): pending pre-login localStorage choice → `/me` `locale`
  → `/me` `space_default_locale` → `detectLocale()` → `"nl"`, then `i18n.changeLanguage`
  ONCE.
- If a pending pre-login choice exists, it is persisted via `patchLocale(it)` and the
  localStorage flag cleared, so the pre-login FR/EN escape survives the first login (D-09).
- `getMe`/`patchLocale` are return-no-throw (`ApiResult`); on failure the resolution falls
  back to the detected/nl language. Locale is never read from a Firebase claim (RESEARCH
  Runtime State — it lives in Cloud SQL, not the token).

## Deviations from Plan

None — plan executed exactly as written. (Two minor, in-scope refinements documented as
decisions above: consolidating the duplicate `LanguageSwitcher` import into one line, and
re-using the exported `LOCALE_STORAGE_KEY` constant rather than redefining the key literal
in auth-context.)

## Verification

- `npx tsc --noEmit` — clean (EXIT 0) after each of the 3 tasks.
- Grep guard (in-scope files): no hardcoded Dutch stopword literals remain in
  `auth.login.tsx` or `auth.action.tsx` (Dutch appears only inside code comments, which
  the phase Dutch-guard exempts). Full CI Dutch scan runs at the phase gate.
- Grep: no locale read from any Firebase custom claim in `auth-context.tsx` (the only
  `claim`+`locale` co-occurrence is an explanatory comment).
- Threat register: T-11-03 (pre-login choice never widens access — persistence goes through
  the token-derived PATCH after auth), T-11-09 (changeLanguage only in the client post-auth
  settle; pre-login detect is `typeof window`-guarded) — both satisfied by Tasks 1/3.

## Known Stubs

None. FR/EN catalog values are Claude-drafted translations (D-12), not placeholders; nl is
the guaranteed fallback for any missing key.

## Manual/UAT (deferred to phase gate)

- Switch language on the login page before auth; confirm the login + action pages render in
  the chosen locale.
- Log in and confirm the pre-login choice persists to the profile (survives reload; a fresh
  login on another device reflects the stored `/me` locale).

## Self-Check: PASSED

- FOUND: frontend/src/routes/auth.login.tsx
- FOUND: frontend/src/routes/auth.action.tsx
- FOUND: frontend/src/lib/auth-context.tsx
- FOUND: frontend/src/locales/nl/auth.json (login.* + action.*)
- FOUND: frontend/src/locales/fr/auth.json (login.* + action.*)
- FOUND: frontend/src/locales/en/auth.json (login.* + action.*)
- FOUND commit: 9dbf25a (Task 1)
- FOUND commit: 693d08b (Task 2)
- FOUND commit: 501cd96 (Task 3)
