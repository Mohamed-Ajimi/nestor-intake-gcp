# Phase 11: Internationalization (NL/FR/EN) - Pattern Map

**Mapped:** 2026-07-14
**Files analyzed:** 22 new/modified file groups
**Analogs found:** 21 / 22 (react-i18next init is the one greenfield with no repo analog)

This phase is mostly a **string-externalization sweep** plus **4 shared-infra seams** (i18n init +
provider, `getDateLocale`, error-code contract, `/me` boot + PATCH). The externalization files
(density map in RESEARCH) all share ONE pattern: introduce `useTranslation()` and replace Dutch
literals with `t("ns:key")`. This map focuses on the NEW infrastructure files (where planners need
concrete analogs) and the schema/mail/migration changes; the ~30 pure-externalization files are
covered by the single "Shared Pattern: string externalization" below rather than one section each.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/db/alembic/versions/0010_locale_columns.py` | migration | transform | `0006_user_space_audit.py` (col-add + server_default) / `0007` (minimal ALTER) | exact |
| `backend/app/db/models/organization.py` (MOD: `default_locale`) | model | CRUD | its own existing `status` column (server_default) | exact (self) |
| `backend/app/db/models/membership.py` (MOD: `locale` override) | model | CRUD | its own existing `status` column | exact (self) |
| `backend/app/api/me_routes.py` (NEW `GET /me` + `PATCH /me/locale`) | route | request-response | `admin_routes.py` `update_space` (PATCH+Pydantic) + `auth_routes.py` (protected_router) | exact |
| `backend/app/api/errors.py` (NEW custom exc + handler) | middleware | event-driven | `main.py` exception-handler wiring + `auth_routes.py` raise patterns | role-match |
| `backend/app/mail/render.py` (MOD: locale param) | service | transform | its own `render_validation`/`render_invite` | exact (self) |
| `backend/app/mail/templates/{validation,results,invite}.*.j2` (locale variants) | config | file-I/O | `_base.html.j2` + `validation.html.j2` | exact |
| `backend/app/api/intake_routes.py` `_run_intake_send` (MOD: resolve recipient locale) | service | request-response | `_run_intake_send` itself + `_resolve_active_member_emails` | exact (self) |
| `backend/app/data/pulse_intake_v1.json` (MOD: multi-locale strings) | config | transform | its own scalar shape (D-05 in-place) | exact (self) |
| `backend/scripts/ci_no_hardcoded_dutch.sh` (NEW) | test | batch | `ci_no_permissive_rls.sh` | exact |
| `frontend/src/lib/i18n/index.ts` (NEW i18next init) | provider | event-driven | (none — greenfield; RESEARCH Pattern 1) | no-analog |
| `frontend/src/lib/i18n/detect.ts` (NEW browser detect) | utility | transform | `active-space.tsx` `readPersisted()` (`typeof window` guard) | role-match |
| `frontend/src/lib/i18n/date-locale.ts` (NEW `getDateLocale`) | utility | transform | `utils.ts` `cn()` (pure helper) + `FieldDisplay.tsx` call site | exact |
| `frontend/src/lib/i18n/error-codes.ts` (NEW code→key map) | utility | transform | `salesLabels.ts` label-map style + `client.ts` failure branch | role-match |
| `frontend/src/lib/api/me.ts` (NEW `getMe`/`patchLocale`) | service | request-response | `admin.ts` seam functions over `apiFetch` | exact |
| `frontend/src/lib/api/client.ts` (MOD: extract `code`) | service | request-response | `client.ts` itself (failure branch, lines 66-98) | exact (self) |
| `frontend/src/components/LanguageSwitcher.tsx` (NEW) | component | event-driven | `SpaceSwitcher.tsx` (composed dropdown + persist-on-select) | exact |
| `frontend/src/lib/i18n/LocaleProvider` wiring in `__root.tsx` (MOD) | provider | event-driven | `__root.tsx` `AuthProvider`/`AuthRedirector` nesting | exact (self) |
| `frontend/src/lib/intake-types.ts` (MOD: multi-locale shape) | model | transform | its own `IntakeField`/`IntakeSchema` types | exact (self) |
| `frontend/src/lib/i18n/localizeSchema.ts` (NEW resolver) | utility | transform | `research-question.ts` pure string helpers | role-match |
| `frontend/src/locales/{nl,fr,en}/*.json` (NEW catalogs) | config | file-I/O | (none — greenfield data) | no-analog (data) |
| ~30 externalization files (routes/components/PDFs) | component/route | — | Shared Pattern below | n/a |
| `frontend/src/lib/i18n/date-locale.test.ts` + `error-codes.test.ts` (NEW) | test | — | `intake-phase.test.ts` (vitest) | exact |

## Pattern Assignments

### `backend/app/db/alembic/versions/0010_locale_columns.py` (migration, transform)

**Analog:** `backend/app/db/alembic/versions/0006_user_space_audit.py` (column-add with
`server_default` backfill) and `0007_intake_answers_id_default.py` (minimal `op.execute` ALTER).

**Revision frontmatter pattern** (`0007` lines 22-27) — next number is `0010`, revises `0009`:
```python
revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA = "nestor"
```

**Column-add-with-server_default pattern** — mirror how `0006` backfilled `status` non-null. The
research (Runtime State) requires a `server_default='nl'` backfill so existing org/membership rows
are non-null on apply. Add `organizations.default_locale` (NOT NULL DEFAULT 'nl') and a per-user
locale override on `organization_memberships` (nullable — the user-pref layer, D-07; `null` means
"no override → fall back to space default"). Use `op.add_column` with
`sa.String(...)` + `server_default=sa.text("'nl'")`, matching the model's `server_default="user"`
convention (membership.py:41). Downgrade drops the columns.

**GOTCHA (from Open Q1 / A5):** a superadmin may have NO membership row, so the per-user override
column on membership cannot host a superadmin's locale. Planner decides the superadmin locale home
(nullable column tolerating no-membership → browser/nl fallback, or a tiny keyed store).

---

### `backend/app/db/models/organization.py` + `membership.py` (model, CRUD) — MODIFY

**Analog:** the existing `status` column on each model — the exact pattern to copy for the new
locale column.

**Organization `default_locale`** (mirror `organization.py:32-36` `status`):
```python
# D-10 space default_locale; app-level set {"nl","fr","en"} (enforced in code, NOT a PG enum
# — avoids alembic enum-alter friction, matching the status column rationale).
default_locale: Mapped[str] = mapped_column(
    String, nullable=False, server_default="nl"
)
```

**Membership per-user override** (mirror the same file's nullable columns like `email`,
membership.py:39) — nullable so `null` = "inherit space default" (D-07 chain user→space→nl):
```python
locale: Mapped[str | None] = mapped_column(String, nullable=True)
```

**CRITICAL (CLAUDE.md / RESEARCH):** ORM index/column names must match the migration exactly and
carry NO schema prefix (keeps `alembic check` clean — see membership.py:54-63 `__table_args__`
comment). No new index needed for a scalar locale column.

---

### `backend/app/api/me_routes.py` (route, request-response) — NEW

**Analog:** `admin_routes.py` `update_space` (the PATCH+Pydantic+404 pattern) and `auth_routes.py`
(the `protected_router` default-deny mount). Identity source is `get_current_identity` →
`Identity` (auth/identity.py — `uid`, `email`, `role`, `space_id`).

**Router + mount pattern** — this router mounts UNDER `protected_router` in `main.py` (inherits
`Depends(get_current_identity)`), exactly like `admin_router` (main.py:134) and `intake_router`
(main.py:141). Add one line: `protected_router.include_router(me_router)`.

**Pydantic request/response + PATCH handler** (copy the shape from `admin_routes.py:406-433`
`update_space`, with V5 input validation on the enum per Security Domain):
```python
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from app.auth.dependencies import get_current_identity
from app.auth.identity import Identity

me_router = APIRouter(tags=["me"])

_ALLOWED = {"nl", "fr", "en"}  # V5: reject arbitrary values (Security Domain)

class Me(BaseModel):
    locale: str | None          # user override (null => inherit)
    space_default_locale: str    # resolved from the org

class LocalePatchBody(BaseModel):
    locale: str

@me_router.get("/me")
def get_me(
    identity: Identity = Depends(get_current_identity),
    repo=Depends(...),  # planner: the session/repo dep that reads membership+org
) -> Me:
    # Re-derive the user from the VERIFIED token (identity.uid) — NEVER from request input.
    ...

@me_router.patch("/me/locale")
def patch_locale(
    body: LocalePatchBody,
    identity: Identity = Depends(get_current_identity),
    repo=Depends(...),
) -> Me:
    # V4/V5: locale is display-only; PATCH re-derives the user server-side (identity.uid),
    # a client-supplied locale can only change display, never widen access.
    if body.locale not in _ALLOWED:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid locale")
    ...
```

**Sync `def` (not `async def`):** pg8000 is blocking; FastAPI runs sync handlers in a threadpool
(every handler in `admin_routes.py`/`intake_routes.py`/`auth_routes.py` is sync `def` — see the
module docstring rationale at admin_routes.py:28-29).

**Audit (optional):** `admin_routes.py` writes an `audit.log` row per mutation on the same session
(admin_routes.py:426-432). A self-service locale flip is low-value for the audit trail — planner's
call whether to audit it.

---

### `backend/app/api/errors.py` + `main.py` wiring (middleware, event-driven) — NEW

**Analog:** `main.py`'s `readyz` returns a `JSONResponse` with an explicit status (main.py:184-187);
`auth_routes.py` shows the `raise HTTPException(status, "detail")` string-only pattern used
everywhere today.

**Recommended shape (RESEARCH Pattern 4, option b + Open Q3):** a small custom exception + a FastAPI
exception handler emitting `{"detail": "<raw>", "code": "<CODE>"}` so `apiFetch`'s existing
string-`detail` path (client.ts:67-75) stays untouched and `code` is read additively:
```python
class CodedError(Exception):
    def __init__(self, status_code: int, code: str, detail: str):
        self.status_code, self.code, self.detail = status_code, code, detail

# registered in main.py alongside app = FastAPI(...):
@app.exception_handler(CodedError)
def _coded_handler(_req, exc: CodedError):
    return JSONResponse(
        {"detail": exc.detail, "code": exc.code},  # detail stays a string → raw fallback
        status_code=exc.status_code,
    )
```
Wire the handler in `main.py` next to the router includes (main.py:134-157). Existing
`raise HTTPException(status, "string")` calls keep working (raw-text fallback per D-11); only
user-visible errors migrate to `CodedError`. **Security (Info Disclosure):** the `code` set is a
curated user-facing enum — internal 4xx/5xx keep generic messages, no stack/detail leak.

---

### `backend/app/mail/render.py` + templates (service + config, transform/file-I/O) — MODIFY

**Analog:** `render.py`'s own `render_validation`/`render_results`/`render_invite` functions
(render.py:36-113) and `_base.html.j2` / `validation.html.j2`.

**Locale-select pattern (Open Q4 — planner's discretion):** two shapes:
- **(a) per-locale template dir** `templates/{nl,fr,en}/validation.html.j2` — the render function
  picks the path by resolved locale. `_base.html.j2` stays structural-only (colors/layout, no prose)
  so it is shared across locales; `admin_validated.html.j2` stays Dutch (D-02).
- **(b) one template, translated strings passed in** — Jinja2 `{{ t.greeting }}` style.

Recommended (a): keeps the existing thin `render_*` signature, just add a `locale: str` param and
resolve the template path. **Autoescape MUST stay ON** in every variant (render.py:30-33 —
`select_autoescape` — the T-10-01 XSS guard; T-11 mail carries it forward). nl is the fallback
variant when a locale file is missing.

**Signature change** (extend render.py:36-56 `render_validation`):
```python
def render_validation(*, first_name, project_title, cta_url, is_reminder,
                      app_base_url=None, locale: str = "nl") -> str:
    tmpl = f"{locale}/validation.html.j2"  # (a) per-locale dir; nl on miss
    return _env.get_template(tmpl).render(...)
```

---

### `backend/app/api/intake_routes.py` `_run_intake_send` (service, request-response) — MODIFY

**Analog:** `_run_intake_send` itself (intake_routes.py:731-815) + `_resolve_active_member_emails`
(intake_routes.py:591). Today it resolves recipient EMAILS from active memberships; T-11 must ALSO
resolve each recipient's LOCALE via the D-07 chain (user pref → space default → nl) **server-side**
(Specific Idea: an NL admin sending to an FR client produces an FR mail — never from the sending
admin's UI language).

**Where the change lands:** at the render call (intake_routes.py:772 / :787) — thread the resolved
locale into `mail_render.render_results(..., locale=resolved)`. The resolution reads
`membership.locale` (new col) with `organization.default_locale` fallback then `"nl"` — extend the
existing `_resolve_active_member_emails` (or add a sibling `_resolve_recipient_locale`) rather than
forking the send body. Per-recipient locale means a mixed-locale recipient list needs a render+send
per distinct locale (planner scopes: today it's `mail_resend.send(to=emails, ...)` one shot at
:799 — may become a loop keyed by locale).

**Discipline to preserve (D-16 / Pitfall 1):** send FIRST, stamp+audit on 2xx only
(intake_routes.py:797-814). Do not regress the `{"success": False}` no-stamp/no-audit failure path.

---

### `backend/scripts/ci_no_hardcoded_dutch.sh` (test, batch) — NEW

**Analog:** `backend/scripts/ci_no_permissive_rls.sh` — copy its structure verbatim (the project
trusts this exact shape, D-13).

**Exit-code contract** (ci_no_permissive_rls.sh:22-51) — the EXIT CODE is the gate; rely on grep's
own exit code, never a `grep -c == 0`:
```bash
set -euo pipefail
SCAN_DIR="${1:-frontend/src}"   # overridable so the negative test points at a temp offender
PATTERN='\b(niet|geen|wordt|klant|ingelogd|opnieuw|versturen|opslaan|verwijderen|annuleren|beschikbaar|vernieuwen|ruimte|gebruiker|verplicht|mislukt)\b'
if grep -rEni --include='*.ts' --include='*.tsx' "$PATTERN" "$SCAN_DIR" \
     | grep -vE '(/locales/|\.gen\.ts|/ui/|admin\.sales\.|coming-soon|\.test\.)'; then
  echo "ERROR: hardcoded Dutch string found in in-scope source." >&2; exit 1
fi
echo "OK: no hardcoded Dutch in in-scope source."; exit 0
```

**Exemptions (Pitfall 5):** `src/locales/**`, `**/*.gen.ts`, `ui/**`, `admin.sales.*`,
`coming-soon*`, `.test.` — the catalogs and deliberately-Dutch surfaces MUST be excluded or every
run is a false positive. **Negative test (D-13):** plant `const x = "niet beschikbaar";` in a temp
non-exempt file, point the guard at it, assert non-zero exit — mirror ci_no_permissive_rls.sh's
positive-match behavior (the guard's `if grep ...; then exit 1`).

---

### `frontend/src/lib/api/me.ts` (service, request-response) — NEW

**Analog:** `frontend/src/lib/api/admin.ts` — one thin function per backend route over `apiFetch`,
returning the `ApiResult<T>` union, never forking the transport (admin.ts:1-9 header comment).

**Seam functions** (copy admin.ts:52-107 style; RESEARCH Code Example):
```typescript
import { apiFetch, type ApiResult } from "@/lib/api/client";

export type Me = { locale: "nl" | "fr" | "en" | null; space_default_locale: "nl" | "fr" | "en" };

export function getMe(): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me", { method: "GET" });
}
export function patchLocale(locale: "nl" | "fr" | "en"): Promise<ApiResult<Me>> {
  return apiFetch<Me>("/me/locale", { method: "PATCH", body: JSON.stringify({ locale }) });
}
```
Types mirror the backend `Me` response model (me_routes.py). `locale` here is DISPLAY-ONLY — no
authz decision from this client value (admin.ts:8-9 T-5-18 convention).

---

### `frontend/src/lib/api/client.ts` `apiFetch` (service, request-response) — MODIFY

**Analog:** `client.ts` itself — the failure branch (client.ts:66-98) already extracts `detail`;
add additive `code` extraction WITHOUT changing the `{success, error}` contract (CLAUDE.md: never
fork this transport).

**Where the change lands** (client.ts:66-97): after computing `message` from `detail`, also read a
top-level `code` field from `body` and surface it on the failure branch. The `ApiResult` failure
variant (client.ts:16) may gain an optional `code?: string`:
```typescript
// after line 75, additively:
const code =
  body && typeof body === "object" && "code" in body
    ? (body as { code?: unknown }).code
    : undefined;
// return { success: false, error: message, code: typeof code === "string" ? code : undefined };
```
The existing `detail`-as-string raw-fallback path is untouched (D-11 raw fallback). The toast
call sites then prefer `t(errorCodes[code])` and fall back to the raw `error` string for unmapped
codes (error-codes.ts).

---

### `frontend/src/components/LanguageSwitcher.tsx` (component, event-driven) — NEW

**Analog:** `frontend/src/components/admin/SpaceSwitcher.tsx` — the closest existing
"compact switcher composed from shadcn primitives that persists the selection on select". Build a
NEW component (NOT in `ui/` — CLAUDE.md/RESEARCH anti-pattern); compose from `dropdown-menu` or the
`Popover`+`Command` primitives SpaceSwitcher already uses.

**Composed-dropdown + select-handler pattern** (copy SpaceSwitcher.tsx:104-152 structure, simpler —
3 fixed options nl/fr/en, no async list):
```typescript
// on select: flip i18n language instantly + persist async (D-10 auto-persist)
function handleSelect(lang: "nl" | "fr" | "en") {
  void i18n.changeLanguage(lang);       // instant UI flip (RESEARCH Architecture)
  void patchLocale(lang);               // async persist (return-no-throw; ignore failure)
  setOpen(false);
}
```
**Mount points (D-08):** ProductShell chrome (admin — mount beside/like SpaceSwitcher at
ProductShell.tsx:59-63), the client form header (IntakeForm), AND the login page (`auth.login.tsx`)
— pre-login the switcher drives `i18n.changeLanguage` + localStorage only (no PATCH; no session
yet), reconciling to the stored pref after login (D-09).

**Styling:** reuse SpaceSwitcher's `TRIGGER_CLASS` (SpaceSwitcher.tsx:29-31) and `cn()` for the
project's mono/uppercase chrome look.

---

### `frontend/src/lib/i18n/detect.ts` (utility, transform) — NEW

**Analog:** `active-space.tsx` `readPersisted()` (active-space.tsx:64-72) — the `typeof window`
SSR-guard + try/catch localStorage pattern to mirror for pre-login detection (Pitfall 1 — detection
runs client-side only, never on the SSR shell):
```typescript
export function detectLocale(): "nl" | "fr" | "en" {
  if (typeof window === "undefined") return "nl";           // SSR → deterministic default
  const lang = navigator.language?.slice(0, 2).toLowerCase();
  return lang === "fr" || lang === "en" ? lang : "nl";      // D-09: nl/fr/en else nl
}
```

---

### `frontend/src/lib/i18n/date-locale.ts` (utility, transform) — NEW

**Analog:** `utils.ts` `cn()` (pure single-purpose helper) + the call site it replaces at
`FieldDisplay.tsx:2-3,33` (`import { nl } from "date-fns/locale"; ... format(d, "dd MMM yyyy",
{ locale: nl })`).

**Helper** (RESEARCH Pattern 3, D-04):
```typescript
import { nl, fr, enUS, type Locale } from "date-fns/locale";
export function getDateLocale(lang: string): Locale {
  return lang.startsWith("fr") ? fr : lang.startsWith("en") ? enUS : nl; // nl fallback
}
```
**7 in-scope call sites to switch** (RESEARCH Pattern 3 / CONTEXT canonical_refs): `FieldDisplay.tsx`,
`ClientDetailDrawer.tsx`, `ContextPackBlock.tsx`, `NextStepBanner.tsx`, `ResearchArtifacts.tsx`,
`admin.pulse.intakes.$id.tsx`, `intake.index.tsx`. Each swaps `{ locale: nl }` →
`{ locale: getDateLocale(i18n.language) }`. **Leave** `admin.sales.projects.*` (out of scope).

---

### `frontend/src/lib/i18n/error-codes.ts` (utility, transform) — NEW

**Analog:** `salesLabels.ts` label-map style (SCREAMING_SNAKE constant maps) + the `client.ts`
failure branch it partners with. A plain `code → i18n-key` record:
```typescript
export const ERROR_CODES: Record<string, string> = {
  INTAKE_NOT_FOUND: "common:errors.intakeNotFound",
  // ... curated user-visible codes only (D-11 scoping)
};
// consumer: toast.error(code && ERROR_CODES[code] ? t(ERROR_CODES[code]) : rawError);
```

---

### `frontend/src/lib/intake-types.ts` + `localizeSchema.ts` (model + utility, transform) — MODIFY/NEW

**Analog:** `intake-types.ts` itself (the `IntakeField.label: string` type at intake-types.ts:31)
and `research-question.ts` (pure string-resolver helpers).

**Shape decision (Pitfall 4 / Open Q2 — recommended):** locale-object values in the source JSON
(`label: {nl, fr, en}`) + a single `localizeSchema(schema, lang)` LOAD-TIME pass that flattens to
today's scalar shape, so `FieldRenderer`/`FieldDisplay` stay almost untouched (they keep reading
`field.label` as a string). This minimizes blast radius across every schema consumer
(`IntakeForm`, `FieldRenderer`, `FieldDisplay`). Update `intake-types.ts` to carry BOTH the source
multi-locale shape and the resolved scalar shape. **nl is the guaranteed fallback** for any missing
variant (D-05).

**GOTCHA:** `GET /intakes/templates` serves ONE canonical asset to EVERY caller (intake_routes.py:380
`list_templates` → `intake_canonical`). Changing the JSON shape breaks every consumer unless they're
all updated in the same phase — the `localizeSchema` flatten-at-load pass is the mechanism to keep
the change contained.

---

### `frontend/src/lib/i18n/*.test.ts` (test) — NEW

**Analog:** `frontend/src/lib/intake-phase.test.ts` — the existing vitest structure
(`import { describe, it, expect } from "vitest"`, intake-phase.test.ts:1-7). Cover: `getDateLocale`
maps lang→locale with nl fallback; `error-codes` resolves + falls back to raw (RESEARCH Wave 0).

---

## Shared Patterns

### String externalization (applies to ~30 route/component/PDF files)
**Sources:** the density map (RESEARCH — `admin.pulse.intakes.$id.tsx` 56 hits highest,
`ResearchResultsPanel.tsx` 45, etc.). ONE mechanical pattern per file:
```typescript
import { useTranslation } from "react-i18next";
// inside the component:
const { t } = useTranslation("intake"); // or admin/auth/common per namespace
// replace:  <Button>Opslaan</Button>
// with:     <Button>{t("save")}</Button>
// replace:  toast.error("Klant niet geladen")
// with:     toast.error(t("errors.clientLoad"))
```
**PDF EXCEPTION (Pitfall 3):** `ContextPackPDF.tsx` / `NestorBriefingPDF.tsx` render imperatively via
`pdf(<Component/>).toBlob()` OUTSIDE the provider — `useTranslation()` inside them has no context.
Pass PRE-RESOLVED label strings (or `i18n.getFixedT(lang, ns)`) in as props from the calling
component (which IS inside the provider). Verified call sites: `ContextPackPDF.tsx:305`,
`NestorBriefingPDF.tsx:321`.

### i18n init + provider wiring
**Source:** `__root.tsx` `AuthProvider`/`AuthRedirector` nesting (__root.tsx:103-117) — the
`I18nextProvider` (or the default-export `initReactI18next` singleton) wires in at the SAME shell,
inside `QueryClientProvider`. Do the resolved `changeLanguage` in the client boot after `/me`
resolves, NEVER in a `useEffect` on an SSR'd node (Pitfall 1 / anti-pattern). The `<html lang>` is
set at __root.tsx:66 — keep it deterministic.
**Apply to:** `frontend/src/lib/i18n/index.ts` (init) + `__root.tsx` (provider mount).

### Protected-router mount (backend)
**Source:** `main.py:134-157` — every feature router mounts UNDER `protected_router`
(`protected_router.include_router(me_router)`) so it inherits `Depends(get_current_identity)`
(auth_routes.py:57). No second `app.include_router` for it.
**Apply to:** `me_routes.py` and any new backend router this phase adds.

### Return-no-throw seam (frontend)
**Source:** `client.ts` header (client.ts:6-9) + `admin.ts` — every `lib/api` function returns
`ApiResult<T>` and NEVER throws (CLAUDE.md / salesMail.ts). The `patchLocale` seam follows this;
the switcher ignores the failure (best-effort auto-persist, D-10).
**Apply to:** `me.ts`, LanguageSwitcher's `handleSelect`.

### Migration server_default backfill
**Source:** `0006_user_space_audit.py:5-8` (status columns) — a `server_default` on `add_column`
backfills every existing row non-null on apply. **Apply to:** `0010_locale_columns.py`
(`default_locale` NOT NULL DEFAULT 'nl'; the per-user override is nullable).

### Autoescape XSS guard (mail + i18n interpolation)
**Source:** `render.py:30-33` `select_autoescape` (T-10-01). Mail locale variants keep it ON.
Frontend: `interpolation.escapeValue:false` is SAFE only because React auto-escapes — NEVER
`dangerouslySetInnerHTML` a catalog value (Security Domain / Known Threats).
**Apply to:** all mail template variants + i18n init config.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/lib/i18n/index.ts` | provider | event-driven | react-i18next is greenfield — no i18n framework exists in-repo. Follow RESEARCH Pattern 1 (single synchronous instance, bundled catalogs, nl fallback), NOT a repo analog. |
| `frontend/src/locales/{nl,fr,en}/*.json` | config (data) | file-I/O | Net-new translation catalogs (Claude-drafted, D-12). No structural analog — organize per-feature namespace (common/intake/admin/auth) per RESEARCH structure. |

## Metadata

**Analog search scope:** `backend/app/{api,db,mail,scripts,data}/`, `backend/app/db/alembic/versions/`,
`frontend/src/{lib,lib/api,components,components/admin,routes}/`.
**Files scanned:** ~24 (migrations 0006/0007, models organization/membership/`__init__`,
auth_routes/admin_routes/intake_routes/main, mail render/`__init__`/templates, ci_no_permissive_rls,
client/admin/templates seams, auth-context/active-space/intake-types/utils, ProductShell/SpaceSwitcher,
__root, FieldDisplay, pulse_intake_v1.json, identity, intake-phase.test).
**Pattern extraction date:** 2026-07-14
