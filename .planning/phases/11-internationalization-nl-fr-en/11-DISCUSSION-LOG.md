# Phase 11: Internationalization (NL/FR/EN) - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-07-14
**Phase:** 11-Internationalization (NL/FR/EN)
**Areas discussed:** Externalization scope, Intake form content, Locale default & persistence, Backend strings & translation authoring

---

## Externalization Scope

### Which parts of the app are in scope?

| Option | Description | Selected |
|--------|-------------|----------|
| Re-platform surfaces only | Intake form, client views, admin Pulse lifecycle, space/user management, auth pages; sales + coming-soon excluded | ✓ |
| Everything in the frontend | All 138 files including sales routes | |
| Client-facing only | Only intake form/results/login; admin stays Dutch | |

### Email templates (Phase 10 deferral)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, client-facing mails | Validation/results/reminder/invite in recipient locale; admin_validated stays Dutch | ✓ |
| Yes, all five templates | Including the operator mail | |
| No — scope out explicitly | Emails stay Dutch in v1 | |

### PDF exports

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — same keys | ContextPackPDF/NestorBriefingPDF render in active UI language from the same catalog | ✓ |
| No — PDFs stay Dutch | Deliverables keep Dutch labels | |
| You decide | | |

### Date/number formatting

| Option | Description | Selected |
|--------|-------------|----------|
| Locale follows language | Central language → date-fns locale helper; 9 hardcoded `nl` call sites switch | ✓ |
| Keep Dutch date format | Only text translates | |
| You decide | | |

---

## Intake Form Content

### Translate the canonical template's Dutch content?

| Option | Description | Selected |
|--------|-------------|----------|
| Yes — in canonical JSON | nl/fr/en variants inside `backend/app/data/pulse_intake_v1.json`; one source of truth | ✓ |
| Yes — frontend catalog by field_key | Template stays Dutch; frontend maps keys (desync risk) | |
| No — form stays Dutch | Only app chrome translates | |

### Multi-locale shape in the JSON

| Option | Description | Selected |
|--------|-------------|----------|
| You decide | Claude picks (locale objects vs suffix keys) weighing consumer impact, nl fallback | ✓ |
| Locale objects | `label: {nl, fr, en}` — uniform but breaking | |
| Parallel suffix keys | `label_fr`/`label_en` beside Dutch `label` — non-breaking but noisy | |

### AI-generated content language

| Option | Description | Selected |
|--------|-------------|----------|
| Out of scope — defer | Phase 7 prompts untouched; noted as deferred idea | ✓ |
| In scope — pass locale to skills | Prompts answer in client's language | |
| You decide | | |

---

## Locale Default & Persistence

### Where does the preference live?

| Option | Description | Selected |
|--------|-------------|----------|
| Space default + user override | `default_locale` on organization + per-user override; user → space → nl | ✓ |
| Space default only | Per-session localStorage for users | |
| Browser-only (localStorage) | No DB change | |

### Switcher placement

| Option | Description | Selected |
|--------|-------------|----------|
| Header + login page | One component in app chrome AND on login | ✓ |
| Header only | Login follows defaults | |
| You decide | | |

### Pre-preference default

| Option | Description | Selected |
|--------|-------------|----------|
| Browser → nl fallback | Browser lang if nl/fr/en else nl; login-page switch persists post-login; new spaces nl | ✓ |
| Always nl pre-login | Dutch until explicit switch | |
| You decide | | |

### Space-default management & persistence

| Option | Description | Selected |
|--------|-------------|----------|
| Space dialog + auto-persist | Superadmin edits in space create/edit UI; switcher PATCHes immediately; email locale via chain | ✓ |
| Space fixed at creation only | Not editable after create | |
| You decide | | |

---

## Backend Strings & Translation Authoring

### Backend-originated errors

| Option | Description | Selected |
|--------|-------------|----------|
| Error-code contract | Stable machine codes; frontend maps to translations; raw text fallback for unmapped | ✓ |
| Status-based generic messages | Translated generic per HTTP status | |
| Leave backend strings as-is | Server text passes through | |

### Translation authoring

| Option | Description | Selected |
|--------|-------------|----------|
| AI drafts + your review | Claude generates FR/EN; user reviews tone in UAT | ✓ |
| Professional/native translation | External dependency, blocks execution | |
| AI drafts, EN only reviewed | FR ships unreviewed | |

### Enforcement of "no hardcoded Dutch"

| Option | Description | Selected |
|--------|-------------|----------|
| CI guard + sweep | Dutch-word regex scan (QA-02 style) + manual sweep | ✓ |
| Manual sweep + UAT only | No lasting guard | |
| You decide | | |

### Catalog organization

| Option | Description | Selected |
|--------|-------------|----------|
| You decide | react-i18next conventions; likely per-feature namespaces | ✓ |
| Single file per language | One flat nl/fr/en.json | |
| Per-route namespaces | Mirrors routes/ tree | |

---

## Claude's Discretion

- Multi-locale shape inside the canonical JSON (locale objects vs suffix keys)
- Catalog/namespace organization and key naming
- Per-user locale column placement + PATCH endpoint shape; switcher styling
- SSR/initial-render locale mechanics; i18next detection plugin; mail-template locale-variant mechanics
- D-11 error-code scoping and naming convention
- CI guard mechanics (word list, globs, exemptions)

## Deferred Ideas

- Locale-aware AI output (pass locale into Phase 7 skill prompts)
- Sales routes i18n (if/when the sales track is re-platformed)
- `admin_validated` mail i18n
- Locales beyond NL/FR/EN (e.g., DE)
