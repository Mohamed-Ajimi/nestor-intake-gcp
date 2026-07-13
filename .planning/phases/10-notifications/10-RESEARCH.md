# Phase 10: Notifications - Research

**Researched:** 2026-07-13
**Domain:** Transactional email (Resend) from FastAPI, Firebase Auth action-code password flow, Jinja2 email templating, recipient resolution from memberships
**Confidence:** HIGH (all seams read in-repo; external contracts verified against official docs)

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Events & Triggers**
- **D-01 (manual CTA sends):** Validation-ready, results-ready, and reminder mails are sent by explicit admin action — the already-wired NextStepBanner CTAs (currently stubbed with "komt in Phase 10" toasts). No automatic sends on status transitions. Legacy parity; no surprise emails.
- **D-02 (reminders manual-only):** The reminder is the existing "send reminder" button (legacy `validation_reminder`). No Cloud Scheduler, no auto-reminder infra in v1.
- **D-03 (keep `admin_validated`, automatic):** When a client validates their questions, the backend automatically mails the operator — the one auto-triggered mail (the client's action fires it; no admin CTA possible). It's how the operator knows to generate the context pack.
- **D-04 (invitation mail is a separate action):** `POST /admin/users` (invite) keeps its current behavior — create the IdP user, return the action link. A **distinct** "send invitation mail" action/endpoint sends (and re-sends) the email. The copy-link fallback in the invite response stays.

**Recipients (login-only model)**
- **D-05 (picker at send time):** For client-facing mails the admin picks recipient(s) when clicking the CTA — a member picker listing the intake's space **active memberships** (`organization_memberships.email` is the source; there is no `primary_contact_email`).
- **D-06 (members only, no free address):** No free-text override address (legacy `override_email` dropped). "Log in to view" — a non-member cannot log in, so a free address is a dead end and undermines NOTIF-01.
- **D-07 (preselect all; block if empty):** All active members pre-checked (one click = legacy behavior). Zero active members → send CTA disabled with a hint to invite someone first.
- **D-08 (configurable admin address):** `admin_validated` goes to a single ops address from config/env (Settings, like legacy `NESTOR_ADMIN_EMAIL` but not hardcoded) — not to all superadmins.

**Invitation Email & NOTIF-01 Interpretation**
- **D-09 (action link allowed — documented interpretation):** NOTIF-01's target is the legacy **never-expiring data bearer links** (`client_validation_token` etc.). The invite mail MAY carry the one-time, short-lived Firebase set-password action link — an auth-bootstrap credential, not a data-access token. All other mails carry zero tokens.
- **D-10 (send/resend surfaces):** "Send invitation mail" lives in BOTH the InviteUserDialog success state (next to copy-link) AND as a per-member resend action in the space-management member list. One endpoint serves both; each send regenerates a fresh action link.
- **D-11 (custom in-app handler route):** The action link lands on a branded frontend route that consumes the oobCode (`confirmPasswordReset`) so the first-run flow stays in the app's look and language — not Firebase's hosted page.
- **D-12 (one handler, both flows):** That route serves invite set-password AND forgot-password — mechanically the same Firebase operation. Wording stays neutral ("Kies je wachtwoord"). The forgot-password entry point UI is out of scope but lands later without rework.

**Provider, Templates & Delivery**
- **D-13 (keep Resend):** Same provider — `agenic.be` sender domain already verified, one HTTPS POST. `RESEND_API_KEY` moves server-side into Secret Manager (Phase 7 secrets pattern). Sender stays `Nestor Pulse <nestor@agenic.be>`.
- **D-14 (port legacy HTML to Jinja2):** Recreate the Dutch HTML mails (inline CSS) as Jinja2 templates in the backend — visual parity minus the token links (CTAs now point to authenticated app routes). Email i18n is Phase 11.
- **D-15 (logo = frontend static asset):** Agenic logo ships in `frontend/public/` and mails reference the deployed app URL. Closes the Phase 9 D-07a handoff (old public Supabase URL dies; new bucket fully private).
- **D-16 (synchronous send + toast):** Endpoint calls Resend in-request and returns success/failure; admin sees a toast either way. `validation_link_sent_at` / `results_link_sent_at` update **only on successful send**. No background task, no queue.

### Claude's Discretion
- Mail module layout (`app/mail/` vs `app/notifications/`), endpoint shapes/naming, and how send endpoints hang off the existing protected routers (intake-scoped for validation/results/reminder; admin-scoped for invite mail) — follow existing `app/api/` conventions, existence-hidden 404 for cross-space intakes.
- Jinja2 environment setup, template file layout, faithfulness of the port (recognizable parity, not pixel parity).
- Exact recipient-picker UI component (dialog vs popover) from existing shadcn primitives.
- How the Resend call is faked in tests (established fake-the-external-call pattern; live sends proven in UAT) and what denial tests cover (cross-space send → 404).
- Whether `admin_validated` failure is silent-logged or surfaced (it fires inside the client's validate action — the client should not see an operator-mail error).
- Audit logging of sends (event types, payload) following the Phase 5 `audit.log` conventions.
- The app route each mail's CTA points to — pick whatever the logged-in recipient can actually open given current role gating.

### Deferred Ideas (OUT OF SCOPE)
- **Scheduled auto-reminders** (Cloud Scheduler sweep) — revisit after v1.
- **Email i18n (NL/FR/EN)** — Phase 11 owns string externalization.
- **Forgot-password entry-point UI** — the D-12 handler route already supports the flow; the login-page link lands later.
- **Send-history visibility** — per-intake log beyond the two `sent_at` timestamps; audit rows may cover the data side.
- **`send-sales-mail` / `sales-friday-reminder` port** — sales track, outside Pulse re-platform requirements.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| NOTIF-01 | Transactional email is notification-only — carries no access token; links point to authenticated routes | Legacy token URLs (`/intake/{client_validation_token}`, `/results/{client_results_token}`) are removed and replaced with authenticated app routes (`/admin/pulse/intakes/{id}` for operators, `/intake/{id}` or `/intake/{id}/results` for client users). The ONLY token any mail carries is the Firebase invite action link (D-09 documented exception). See §Architecture Patterns "CTA route selection" + §Standard Stack. |
| NOTIF-02 | Email is sent for invitation, validation-ready, results-ready, and reminders | Five mail types map to endpoints: invitation (admin-scoped), validation-ready + reminder + results-ready (intake-scoped, admin CTA), plus `admin_validated` (auto, D-03). Legacy `send-pulse-mail.ts` is the parity source for subjects/HTML. See §Architecture Patterns "Endpoint surface". |
</phase_requirements>

## Summary

This phase replaces the legacy `send-pulse-mail` Deno edge function with a backend mail module on FastAPI/Cloud Run, un-stubs three already-wired frontend CTAs, adds a "send invitation mail" action, and builds a branded in-app password-set handler route. Every architectural seam this phase touches already exists and was read directly: the protected routers (`intake_router`, `admin_router`), the `Depends(get_*_repo)` data-access discipline, the `audit.log` one-tx contract, the `get_settings()` typed config, the `os.environ`-at-call-time secrets pattern (Phase 7 `app/ai/clients.py`), the `apiFetch`/`ApiResult` frontend transport, the Firebase JS SDK singleton (`frontend/src/lib/firebase.ts`), and the membership/intake ORM models that provide recipients and sent-at columns.

The four external/technical contracts are all verified: (1) Resend is a single authenticated HTTPS POST to `https://api.resend.com/emails` — and `httpx` is **already a declared backend dependency**, so no new HTTP client is needed; (2) Firebase's `generate_password_reset_link(email)` server call already exists (`app/auth/admin_users.py:86` — `generate_set_password_link`) and the client-side consume path is the modular `verifyPasswordResetCode(auth, oobCode)` → `confirmPasswordReset(auth, oobCode, newPassword)` sequence; (3) Jinja2 renders standalone strings via `Environment.get_template(...).render(...)` with **no** FastAPI response machinery — but Jinja2 is **NOT** currently a backend dependency and must be added; (4) the `validated_by_client` transition (the D-03 trigger) is the existing `POST /intakes/{id}/submit` handler's `reviewed → validated_by_client` branch (`intake_routes.py:651`).

**Primary recommendation:** Build `app/mail/` as a self-contained module (Resend transport via `httpx` reading `RESEND_API_KEY` from `os.environ` at call time; Jinja2 environment over `app/mail/templates/`), expose intake-scoped send endpoints on `intake_router` and an invite-mail endpoint on `admin_router`, resolve recipients from `organization_memberships` (active only), fire `admin_validated` inside the existing `submit_intake` handler on the `→ validated_by_client` edge (non-blocking, silent-logged on failure), and update `validation_link_sent_at`/`results_link_sent_at` on the SAME session only after a 2xx Resend response. Fake the Resend POST in tests by monkeypatching the transport function (mirror `fake_anthropic`/`fake_gcs`). Add `RESEND_API_KEY` (Secret Manager → env) and `NESTOR_ADMIN_EMAIL` + base-URL to `infra/*.tf` AND the deploy runbook.

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Recipient resolution (space active members) | API / Backend | — | `organization_memberships` is a tenant-root table; recipient list must be server-derived, never client-supplied (D-06 no free address). |
| Resend HTTPS POST | API / Backend | — | `RESEND_API_KEY` is a secret; the browser must NEVER hold it (all sends mediated server-side). |
| Jinja2 template render | API / Backend | — | Templates live beside the mail module; render is pure string production, no HTTP response. |
| Firebase action-link generation | API / Backend | — | `generate_password_reset_link` is an Admin-SDK (privileged) call — server-side only (`admin_users.py`). |
| Firebase action-code CONSUME (`confirmPasswordReset`) | Browser / Client | Frontend Server (SSR) | The oobCode is redeemed by the Firebase JS SDK in the browser; the new handler route renders the set-password form. |
| Recipient-picker UI | Browser / Client | — | Presentation of the server-provided member list; selection posted back to the send endpoint. |
| `admin_validated` auto-trigger | API / Backend | — | Fires inside the existing `submit_intake` handler; no client action beyond the validate call. |
| Sent-at timestamp update | API / Backend | — | Written on the request session after a successful send (D-16). |

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `httpx` | already declared (unpinned) in `backend/pyproject.toml:50` | The single authenticated POST to `https://api.resend.com/emails` | ALREADY a backend dependency (backs `TestClient`); reusing it means D-13's "one HTTPS POST" adds ZERO new deps. Prefer over the `resend` SDK for that reason. `[CITED: backend/pyproject.toml]` |
| `Jinja2` | `>=3.1` (verify at add time) | Render the ported Dutch HTML mail bodies from templates | The de-facto Python templating engine; FastAPI's own `Jinja2Templates` uses it. **NOT currently a backend dep — must be added to `pyproject.toml`.** `[ASSUMED]` version; `[VERIFIED: not present]` — grep of `backend/pyproject.toml`/`uv.lock` found no jinja2. |
| `firebase-admin` | `>=7.4,<8` (already declared) | `auth.generate_password_reset_link(email)` — the invite/reset action link | Already used for the invite flow (`app/auth/admin_users.py`); no change needed. `[VERIFIED: backend/pyproject.toml]` |
| `firebase/auth` (JS, modular) | already in frontend | `verifyPasswordResetCode` + `confirmPasswordReset` on the handler route | Already the frontend auth singleton (`frontend/src/lib/firebase.ts`). `[VERIFIED: frontend/src/lib/firebase.ts]` |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `resend` (Python SDK) | 2.33.0 (PyPI, released 2026-07-13; repo `github.com/resend/resend-python`) | Alternative to raw `httpx` for the Resend call (`resend.Emails.send(params)`) | ONLY if the planner prefers an SDK over a raw POST. Given D-13 ("one HTTPS POST") and that `httpx` is already present, the raw POST is the recommended path and this SDK is the documented alternative — not the default. `[CITED: pypi.org/project/resend]` |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Raw `httpx` POST | `resend` Python SDK | SDK is ~5 lines shorter per call but adds a new dependency + a new legitimacy checkpoint + a new mock seam, for a provider that is literally one POST. D-13's framing ("one HTTPS POST") points at the raw path. |
| Jinja2 file templates | Python f-strings / string builders (legacy `.ts` style) | f-strings would port the legacy builders literally but D-14 explicitly says Jinja2 templates. Jinja2 also gives autoescaping for the dynamic values (project title, client name) — an XSS-in-email guard the legacy string builders lacked. |
| `httpx` sync client | `requests` | `requests` is NOT a declared dep; `httpx` is. Use `httpx.Client` (sync — the handlers are sync `def`, pg8000-blocking-in-threadpool style). |

**Installation:**
```bash
# Only ONE new backend dependency for this phase:
#   add to backend/pyproject.toml  ->  "jinja2>=3.1,<4"
# httpx + firebase-admin already declared. No frontend package additions
# (firebase/auth already present).
```

**Version verification:** `pip`/`slopcheck` were UNAVAILABLE in the research environment (dev machine has no Python — see MEMORY). `resend` 2.33.0 confirmed via pypi.org JSON API (official repo `github.com/resend/resend-python`, MIT, established package with a multi-year changelog). `jinja2` version left `[ASSUMED]` — the planner MUST verify the exact current 3.x on PyPI at add time and gate the install behind a `checkpoint:human-verify` per the project's established legitimacy discipline (Phase 9 pattern).

## Package Legitimacy Audit

> slopcheck was UNAVAILABLE at research time (no Python on dev machine). Per protocol, packages needing a NEW install are tagged `[ASSUMED]` and the planner MUST gate each behind a `checkpoint:human-verify` task before install (mirrors the Phase 9 blocking-human legitimacy checkpoint).

| Package | Registry | Age | Downloads | Source Repo | slopcheck | Disposition |
|---------|----------|-----|-----------|-------------|-----------|-------------|
| `jinja2` | PyPI | ~14 yrs | very high (top-tier) | github.com/pallets/jinja | unavailable | **NEW install — planner adds checkpoint:human-verify.** Well-known Pallets project; low real risk, but verify version + hash at add time. |
| `httpx` | PyPI | already declared | — | github.com/encode/httpx | n/a | Already in `pyproject.toml` — no new install. |
| `firebase-admin` | PyPI | already declared | — | github.com/firebase/firebase-admin-python | n/a | Already declared. |
| `resend` (if chosen) | PyPI | multi-year | high | github.com/resend/resend-python | unavailable | Only if SDK path chosen (NOT recommended). Gate behind checkpoint. |

**Packages removed due to slopcheck [SLOP] verdict:** none
**Packages flagged as suspicious [SUS]:** none (slopcheck unavailable; `jinja2` is a canonical Pallets library, real risk minimal — checkpoint is process compliance, not a red flag).

## Architecture Patterns

### System Architecture Diagram

```
CLIENT-FACING MAIL (validation / reminder / results) — manual admin CTA
─────────────────────────────────────────────────────────────────────
[Admin @ /admin/pulse/intakes/$id]
   │  clicks NextStepBanner CTA (onSendValidationMail / …Reminder / …ResultsMail)
   ▼
[Recipient picker] ── GET active members of intake's space ──► [Backend]
   │  admin (de)selects; all preselected (D-07); disabled if 0 members
   ▼  POST /intakes/{id}/mail/{type}  { recipients: [membership_id…] }   (apiFetch)
[intake_router handler]
   │  Depends(get_tenant_repo) → intake in scope?  NO → 404 (existence-hidden, D-07)
   │  resolve recipient emails from organization_memberships (active only, D-05/06)
   │  Jinja2 render body (CTA → authenticated app route, NO token — NOTIF-01)
   ▼
[app/mail/resend.send()] ── httpx POST https://api.resend.com/emails (Bearer RESEND_API_KEY) ──►[Resend]
   │  2xx?  YES ──► update {validation|results}_link_sent_at on request session (D-16)
   │             └─► audit.log(event_type="mail.sent", metadata NO link/token)
   │  non-2xx ──► return {success:false} (no timestamp write) → toast.error
   ▼
[toast success/failure]

AUTO OPERATOR MAIL (admin_validated) — D-03, no CTA
───────────────────────────────────────────────────
[Client user] POST /intakes/{id}/submit  (reviewed → validated_by_client edge)
   ▼
[submit_intake handler]  status flip + audit (EXISTING)
   │  NEW: on the → validated_by_client edge, fire admin_validated mail
   │       to Settings.nestor_admin_email (D-08); failure = silent-logged
   │       (client must NOT see an operator-mail error — Discretion)
   ▼  returns IntakeView (client's request succeeds regardless of mail outcome)

INVITATION MAIL (D-04/D-09/D-10) — admin action, carries the ONLY token
──────────────────────────────────────────────────────────────────────
[InviteUserDialog success  OR  member-list "resend" action]
   ▼  POST /admin/users/{membership_id}/invite-mail   (or by email — planner's shape)
[admin_router handler] Depends(get_admin_session)
   │  fresh generate_set_password_link(email)  (regenerated per send, D-10)
   │  Jinja2 render invite body  →  action link → frontend handler route
   ▼  httpx POST Resend → audit.log("mail.sent", NEVER the link) → toast

PASSWORD-SET HANDLER (D-11/D-12) — the ONE genuinely new frontend route
───────────────────────────────────────────────────────────────────────
[User clicks action link]  → /auth/action?mode=resetPassword&oobCode=…   (Firebase continue URL)
   ▼
[new handler route]  read mode + oobCode from URL
   │  verifyPasswordResetCode(auth, oobCode) → email (validates + surfaces who)
   │  render "Kies je wachtwoord" form (neutral wording — invite & forgot, D-12)
   │  confirmPasswordReset(auth, oobCode, newPassword)
   ▼  → redirect to /auth/login (user signs in with the new password)
```

### Recommended Project Structure
```
backend/app/
├── mail/                          # NEW module (name at discretion: mail/ vs notifications/)
│   ├── __init__.py
│   ├── resend.py                  # send(to, subject, html) — httpx POST, key from os.environ AT CALL TIME
│   ├── render.py                  # Jinja2 Environment over templates/; render_validation()/…()
│   └── templates/
│       ├── _base.html.j2          # shared layout (styles(), logo <img> at deployed app URL, card/tag/btn)
│       ├── validation.html.j2     # buildValidationHtml port (+ isReminder branch)
│       ├── results.html.j2        # buildResultsHtml port
│       └── admin_validated.html.j2# buildAdminValidatedHtml port + invite.html.j2
├── api/
│   ├── intake_routes.py           # + POST /intakes/{id}/mail/{type}; admin_validated fires in submit_intake
│   └── admin_routes.py            # + invite-mail endpoint beside invite_user
└── core/config.py                 # + nestor_admin_email, app_base_url (non-secret Settings fields)

frontend/src/
├── routes/
│   └── auth.action.tsx            # NEW — oobCode handler (set-password / forgot, D-11/D-12)
├── components/
│   ├── intake/RecipientPicker.tsx # NEW — the one new UI element (dialog/popover, shadcn)
│   └── admin/InviteUserDialog.tsx # + "send invitation mail" button in success state (D-10)
├── lib/api/
│   ├── intake.ts (or client route module) # + sendIntakeMail(id, type, recipients)
│   └── admin.ts                   # + sendInviteMail(...), listSpaceMembers(spaceId)
└── public/
    └── agenic-logo.png            # D-15 — logo static asset; templates reference {app_base_url}/agenic-logo.png
```

### Pattern 1: Resend transport (httpx POST, secret at call time)
**What:** A single `send()` function that reads `RESEND_API_KEY` from `os.environ` inside the function body (never module-level, never Settings, never logged) — exactly the Phase 7 `app/ai/clients.py` discipline (D-07).
**When to use:** Every mail send routes through this one function (the test mock seam).
**Example:**
```python
# app/mail/resend.py — mirrors app/ai/clients.py's call-time-secret discipline (D-07/07-RESEARCH)
# Source: docs/supabase-functions/send-pulse-mail.ts:86-95 (legacy POST shape) + httpx
from __future__ import annotations
import os
import httpx

_RESEND_URL = "https://api.resend.com/emails"
FROM = "Nestor Pulse <nestor@agenic.be>"   # D-13 — unchanged sender
_TIMEOUT_S = 15.0

def send(*, to: list[str], subject: str, html: str) -> str:
    """POST one email to Resend; return the provider message id. Raises on non-2xx.

    RESEND_API_KEY is read HERE (call time, D-07): never module-level, never in
    Settings, never logged. This is the ONE function the test suite monkeypatches
    (mirror fake_anthropic / fake_gcs) so no test ever reaches Resend.
    """
    key = os.environ["RESEND_API_KEY"]          # loud KeyError beats a silent unauth call
    resp = httpx.post(
        _RESEND_URL,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json={"from": FROM, "to": to, "subject": subject, "html": html},
        timeout=_TIMEOUT_S,
    )
    resp.raise_for_status()                       # 4xx/5xx → HTTPStatusError → caller maps to failure
    return resp.json().get("id", "")
```

### Pattern 2: Jinja2 render, no web machinery (D-14)
**What:** A module-level `Environment` with a `FileSystemLoader` over `app/mail/templates/`, `autoescape=True`; each mail type gets a thin render function. NO `Jinja2Templates`/`TemplateResponse` (that couples to a `Request`/response — not what a mail body needs).
**When to use:** Producing the HTML string handed to `resend.send()`.
**Example:**
```python
# app/mail/render.py
# Source: Jinja2 official — Environment/FileSystemLoader/get_template().render()
from __future__ import annotations
from pathlib import Path
from jinja2 import Environment, FileSystemLoader, select_autoescape

_env = Environment(
    loader=FileSystemLoader(Path(__file__).parent / "templates"),
    autoescape=select_autoescape(["html", "j2"]),   # escapes project title / client name (email XSS guard)
)

def render_validation(*, first_name: str, project_title: str, cta_url: str, is_reminder: bool) -> str:
    return _env.get_template("validation.html.j2").render(
        first_name=first_name, project_title=project_title, cta_url=cta_url, is_reminder=is_reminder,
    )
```
Autoescape is a genuine improvement over the legacy `.ts` string builders, which interpolated `${clientName}` / `${projectTitle}` raw into HTML.

### Pattern 3: CTA route selection — the NOTIF-01 core (no token)
**What:** Every CTA URL is an **authenticated app route**, built from a configured base URL — never a token-bearing legacy path.
- Client-facing validation/results mail → `{app_base_url}/intake/{intake_id}` or `{app_base_url}/intake/{intake_id}/results` (the authenticated USER surfaces; `intake.$id.tsx` / `intake.$id.results.tsx` exist and gate on `validated_by_client`-or-later for results).
- `admin_validated` → `{app_base_url}/admin/pulse/intakes/{intake_id}` (operator surface).
- Invite mail → the Firebase action link (the ONLY token, D-09), whose continue URL is the new `/auth/action` handler.
**Why it matters:** The legacy function built `${BASE_URL}/intake/${intake.client_validation_token}` and `${BASE_URL}/results/${intake.client_results_token}` — those two tokens are EXACTLY what NOTIF-01 removes. Replace the token segment with `{intake_id}`; the recipient must already be logged in (they're a member, D-06).

### Pattern 4: admin_validated fires inside the existing transition (D-03)
**What:** The `submit_intake` handler (`intake_routes.py:680`) already owns the `reviewed → validated_by_client` edge (`_SUBMIT_TRANSITIONS`, line 651). Add the auto-mail there, guarded on the specific target status, AFTER the status flip + audit, wrapped so a mail failure NEVER fails the client's validate request.
**Example:**
```python
# inside submit_intake, after the existing status flip + audit.log:
if new_status == "validated_by_client":
    try:
        _send_admin_validated(intake)   # to Settings.nestor_admin_email (D-08)
    except Exception:                    # noqa: BLE001 — client must not see an operator-mail error
        log.warning("admin_validated mail failed for intake %s", intake_id)  # silent-logged (Discretion)
```
Do NOT let the mail share the request's DB transaction dependency in a way that rolls back the status change on mail failure — the validate must commit regardless (D-16 sync-send applies to the *admin-CTA* sends' timestamp writes; the client's status change is independent).

### Anti-Patterns to Avoid
- **Putting `RESEND_API_KEY` in `Settings`:** it is a SECRET (D-07). Read it from `os.environ` at call time inside `resend.send()`, exactly like `ANTHROPIC_API_KEY`. Do NOT add a `resend_api_key` field to `core/config.py`.
- **Accepting a recipient email from the request body:** D-06 forbids a free address; the picker posts membership IDs (or nothing → server derives all active). The backend resolves emails from `organization_memberships` server-side. A client-supplied `to` would reintroduce the send-to-anyone hole.
- **`space_id` from the request:** unchanged TENANT-02 rule — the send endpoints scope via the injected repo/identity, never a body/query `space_id`.
- **Logging the action link or any token in `audit.log`:** the Phase 5 contract (`audit.py` docstring) — `metadata` is structured fields only; NEVER the invite/reset link.
- **Using Firebase's hosted password page:** D-11 requires the branded in-app `/auth/action` route; set the `ActionCodeSettings` continue URL to it.
- **Blocking the client's validate on the operator mail:** `admin_validated` is fire-and-forget from the client's perspective.
- **`async def` mail handlers:** the codebase is sync-`def`/pg8000-in-threadpool (only the SSE stream is async). Use `httpx.Client` sync, not `AsyncClient`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Password-reset / set-password token lifecycle | A custom token table + email + expiry + redemption | `firebase-admin auth.generate_password_reset_link` (already wrapped) + JS `confirmPasswordReset` | Firebase owns one-time, short-lived, single-use action codes with expiry + regeneration. Rolling your own is the exact never-expiring-bearer-link mistake NOTIF-01 exists to kill. |
| Email HTML escaping | Manual `.replace('<','&lt;')` on client name / project title | Jinja2 `autoescape` | Jinja2 escapes every `{{ var }}` by default — an email-context XSS guard the legacy string builders lacked. |
| HTTP retry/timeout for the send | A hand-rolled retry loop | `httpx` timeout + `raise_for_status()`; D-16 is synchronous single-attempt | D-16 says synchronous send + toast, no queue/retry. A failed send just returns `{success:false}`; the admin re-clicks. Keep it one attempt. |
| Recipient list correctness | A denormalized "contacts" copy | Live read of `organization_memberships` (active) | The membership table is the single source; a copy drifts and can leak deactivated members. |
| Deliverability/SPF/DKIM | Anything | Resend + the already-verified `agenic.be` domain (D-13) | Domain verification is done; no infra work here beyond the API key. |

**Key insight:** This phase is mostly *wiring existing seams together*, not building new subsystems. The only genuinely new code is: one `app/mail/` module, one frontend handler route, one recipient-picker component, and endpoint handlers that compose already-present repos/config/audit.

## Runtime State Inventory

> This is a feature phase, not a rename/migration. Included for the two live-state items that DO matter.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `intakes.validation_link_sent_at` / `results_link_sent_at` columns already exist (`intake.py:78-83`). No new migration needed for send-state UNLESS the planner decides to record reminder sends (legacy did NOT set a timestamp for `validation_reminder` — matches D-01/D-02; keep parity → no new column). | None (unless a reminder-sent column is chosen — then a migration). |
| Live service config | `RESEND_API_KEY` (Secret Manager secret + Cloud Run env mapping), `NESTOR_ADMIN_EMAIL` (env), app base URL (env). These live in Cloud Run config, NOT in git today. | Add to `infra/*.tf` AND the deploy runbook (Phase 8 D-07 IaC-drift rule). The running image also needs the `jinja2` dep → rebuild (Phase 9 Pitfall 7). |
| OS-registered state | None — no scheduler/cron in v1 (D-02 defers Cloud Scheduler). | None. |
| Secrets/env vars | `RESEND_API_KEY` is a NEW Secret Manager secret (Phase 7 pattern). `NESTOR_ADMIN_EMAIL` + base URL are non-secret env → `Settings` fields. | Create the secret; grant the Cloud Run SA `secretAccessor`; map to env. Both in Terraform + runbook. |
| Build artifacts / installed packages | `jinja2` is a NEW backend dependency — the live Cloud Run image does NOT have it until a rebuild (recurring lesson: Phase 6/9 deploy-gap). | Add to `pyproject.toml`; rebuild image in the deploy runbook step. |

**Verified explicitly:** the `logo` handoff — legacy `LOGO_URL` points at the dying public Supabase bucket (`send-pulse-mail.ts:9`); D-15 replaces it with `frontend/public/` + the deployed app URL. No public bucket is created (Phase 9 D-07a: bucket fully private).

## Common Pitfalls

### Pitfall 1: Timestamp written before the send succeeds
**What goes wrong:** Updating `validation_link_sent_at` before/regardless of the Resend response marks a mail "sent" that never left.
**Why it happens:** Natural handler ordering (flip state, then call the API).
**How to avoid:** D-16 — call Resend FIRST; only on a 2xx write the timestamp on the request session, then return success. On non-2xx, return `{success:false}` with NO timestamp write.
**Warning signs:** `sent_at` set but the recipient reports no email; tests that assert the timestamp without asserting the (faked) send returned 2xx.

### Pitfall 2: The `jinja2` dependency isn't in the running image
**What goes wrong:** Endpoints 500 on first live send (`ModuleNotFoundError: jinja2`) even though the suite is green.
**Why it happens:** The recurring Nestor deploy-gap — new deps in `pyproject.toml` don't reach Cloud Run until an image rebuild (Phase 6/9 memory).
**How to avoid:** The deploy runbook step MUST rebuild the image; the plan's UAT gate must include a live send. Verify `jinja2` is in the built image before UAT.
**Warning signs:** Green CI, 500 in UAT.

### Pitfall 3: CTA still carries a token (NOTIF-01 regression)
**What goes wrong:** A template ports the legacy `${BASE_URL}/intake/${token}` verbatim, keeping a bearer link.
**Why it happens:** The legacy HTML is the parity source; copy-paste keeps the token URL.
**How to avoid:** Every CTA URL must be `{app_base_url}/intake/{intake_id}` (or the admin route) — an ID, never a token. Add a test asserting no mail body contains `client_validation_token`/`client_results_token`/a token-shaped segment, and assert the URL contains the intake id. Keep the D-09 note next to the ONE allowed exception (invite action link).
**Warning signs:** A rendered body containing a long random path segment on a non-invite mail.

### Pitfall 4: `admin_validated` failure breaks the client's validate
**What goes wrong:** The operator mail raises and the client's `POST /submit` 500s — the client can't validate.
**Why it happens:** Firing the mail inside the transition without isolating its failure.
**How to avoid:** Wrap the `admin_validated` send in try/except, silent-log on failure (Discretion), and ensure it does not share a transaction that would roll back the status change.
**Warning signs:** Validate button errors when the admin email/env is misconfigured.

### Pitfall 5: Recipient picker offers deactivated members (or an empty list silently)
**What goes wrong:** A deactivated member is emailed a "log in" link they can't use, or the send fires to zero recipients.
**Why it happens:** Reading all memberships instead of filtering `status = "active"`; not handling the empty case.
**How to avoid:** Server-side, filter active memberships (D-05). Frontend, preselect all + DISABLE the CTA with an "invite someone first" hint when the list is empty (D-07).
**Warning signs:** A "sent" toast with no recipients; a deactivated user in the picker.

### Pitfall 6: `oobCode` handler assumes only forgot-password
**What goes wrong:** The handler shows "Reset your password" copy or fails for a freshly invited user.
**Why it happens:** Treating invite and forgot as different flows.
**How to avoid:** D-12 — one route, neutral "Kies je wachtwoord" wording; `verifyPasswordResetCode` then `confirmPasswordReset` work identically for both (the invited user has a random password they never knew). Handle expired/invalid oobCode (`auth/expired-action-code`, `auth/invalid-action-code`) with a friendly "vraag een nieuwe link" message.
**Warning signs:** Invited users confused by "reset"; unhandled Firebase error codes.

## Code Examples

### Firebase action-code consume (the new /auth/action route — D-11/D-12)
```tsx
// Source: Firebase official custom-email-handler + JS SDK (verifyPasswordResetCode/confirmPasswordReset)
// frontend/src/routes/auth.action.tsx
import { verifyPasswordResetCode, confirmPasswordReset } from "firebase/auth";
import { auth } from "@/lib/firebase";

// read from URL: ?mode=resetPassword&oobCode=...&continueUrl=...
const mode = new URLSearchParams(window.location.search).get("mode");
const oobCode = new URLSearchParams(window.location.search).get("oobCode");

// resetPassword covers BOTH invite-set-password and forgot-password (D-12):
if (mode === "resetPassword" && oobCode) {
  const email = await verifyPasswordResetCode(auth, oobCode);   // validates + returns who
  // …render "Kies je wachtwoord" form, collect newPassword…
  await confirmPasswordReset(auth, oobCode, newPassword);        // applies it
  // → navigate to /auth/login
}
```
Error codes to handle: `auth/expired-action-code`, `auth/invalid-action-code`, `auth/weak-password`.

### Server-side invite action link with a continue URL (D-11)
```python
# app/auth/admin_users.py — generate_set_password_link already exists (:86).
# For D-11, pass ActionCodeSettings so the link's continue URL is the branded handler:
from firebase_admin import auth
def generate_set_password_link(email: str) -> str:
    acs = auth.ActionCodeSettings(url="https://<app-base-url>/auth/action", handle_code_in_app=True)
    return auth.generate_password_reset_link(email, action_code_settings=acs)
# NOTE: Phase 5 left ActionCodeSettings omitted deliberately (bare link). This phase
# adds it so the link lands on /auth/action. Verify the base URL comes from config/env,
# not a literal. [CITED: firebase-admin generate_password_reset_link signature]
```

### Frontend seam function (mirrors admin.ts conventions)
```ts
// Source: frontend/src/lib/api/admin.ts pattern (apiFetch + ApiResult union, never fork client.ts)
export function sendIntakeMail(
  intakeId: string,
  type: "validation" | "reminder" | "results",
  recipients: string[],   // membership ids
): Promise<ApiResult<{ sent_to: number }>> {
  return apiFetch(`/intakes/${intakeId}/mail/${type}`, {
    method: "POST",
    body: JSON.stringify({ recipients }),
  });
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Deno edge function `send-pulse-mail` w/ service-role Supabase client | FastAPI endpoint + `httpx` POST + membership read | This phase | Recipients now come from `organization_memberships`, not `clients.primary_contact_email`. |
| Token bearer links (`/intake/{token}`, `/results/{token}`) | Authenticated app routes (`/intake/{id}`) | This phase (NOTIF-01) | Recipient must be a logged-in member; no data leaks via a forwarded link. |
| `override_email` free address | Members-only picker (D-06) | This phase | Send-to-anyone hole closed. |
| Logo on public Supabase bucket | `frontend/public/` static asset (D-15) | This phase (Phase 9 D-07a handoff) | Public bucket dies; logo served from the app origin. |
| Firebase-hosted reset page | Branded `/auth/action` handler (D-11) | This phase | First-run flow stays in-app, in Dutch. |

**Deprecated/outdated:**
- `docs/supabase-functions/send-pulse-mail.ts` — the parity SOURCE, but its token URLs, `override_email`, `SUPABASE_SERVICE_ROLE_KEY`, and CORS wrapper are all discarded. Port the HTML/subjects only.
- `clients.primary_contact_email` / `primary_contact_name` — do NOT exist in the new schema (memberships replace them).

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `jinja2>=3.1,<4` is the correct current pin | Standard Stack | LOW — canonical Pallets lib; planner verifies exact version + gates behind checkpoint at add time. |
| A2 | `httpx.Client` sync usage is fine inside the sync `def` handlers (threadpool) | Pattern 1 | LOW — matches the codebase's pg8000-in-threadpool sync model; httpx sync client is standard. Verify no event-loop use. |
| A3 | The results-CTA target `/intake/{id}/results` is openable by the client member at `validated_by_client`+ | Pattern 3 | MEDIUM — route gates on `validated_by_client`-or-later (`intake.$id.results.tsx:42`); confirm role gating during planning per CONTEXT §specifics ("verify current role gating"). |
| A4 | `admin_validated` fires on the `reviewed → validated_by_client` edge in `submit_intake` (not a separate client-validate endpoint) | Pattern 4 | MEDIUM — `_SUBMIT_TRANSITIONS` (`intake_routes.py:651`) is the ONLY path to `validated_by_client` in-repo; confirm no other transition writes that status. |
| A5 | No new migration needed (reminder sends keep legacy no-timestamp parity) | Runtime State Inventory | LOW — legacy set no timestamp for `validation_reminder`; if the planner wants reminder-send tracking, add a column (migration). |
| A6 | `ActionCodeSettings(url=..., handle_code_in_app=True)` is the correct firebase-admin signature for pinning the continue URL | Code Examples | LOW-MEDIUM — standard Admin SDK shape; verify the exact kwarg name against the installed `firebase-admin>=7.4` at plan time. |

## Open Questions (RESOLVED)

1. **Endpoint shape for the send routes (`/intakes/{id}/mail/{type}` vs per-type verbs).** — RESOLVED: discrete verb endpoints (`POST /intakes/{id}/mail/validation`, `/mail/reminder`, `/mail/results`).
   - What we know: intake-scoped, on `intake_router`, existence-hidden 404 (Discretion).
   - Rationale: discrete verbs match the codebase's transition-verb convention (`/submit`, `/review`) and give per-type audit call-sites. Locked in Plan 10-03 Task 1.

2. **Does the invite-mail endpoint key on `membership_id` or `email`?** — RESOLVED: keyed on `membership_id` (`POST /admin/users/{membership_id}/invite-mail`).
   - What we know: D-10 needs it callable from both the invite-dialog success state and the member-list resend.
   - Rationale: the member list carries the membership id, and the dialog can use the returned membership after invite. One handler; a fresh link regenerated each call. Locked in Plan 10-03 Task 2.

3. **Reminder-send tracking.** — RESOLVED: reminder sends write NO timestamp (legacy parity, no new column).
   - What we know: legacy did NOT stamp a timestamp for `validation_reminder`.
   - Rationale: keep legacy parity for v1 — audit rows already record the send; a "last reminded" affordance is deferred per CONTEXT §deferred "send-history visibility". Locked in Plan 10-03 Task 1 (reminder writes NO timestamp).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `httpx` | Resend POST | ✓ (declared) | unpinned in `pyproject.toml` | — |
| `firebase-admin` | invite action link | ✓ (declared) | >=7.4,<8 | — |
| `jinja2` | template render | ✗ (NOT declared) | — | Must add to `pyproject.toml` + rebuild image; no viable fallback (D-14 requires Jinja2). |
| Resend API / `agenic.be` domain | live send | verified domain (D-13); key not yet a secret | — | Faked in tests; proven live in UAT (dev machine has no Python — MEMORY). |
| Python / Docker (local) | running the suite locally | ✗ | — | Author-by-construction; run suite in Cloud Build; UAT proves live behavior (MEMORY). |
| `gcloud` | create secret, deploy | ✓ | — | — |

**Missing dependencies with no fallback:** `jinja2` (must be added — it's the templating engine D-14 mandates).
**Missing dependencies with fallback:** live Resend send (faked in tests, UAT-proven); local Python (Cloud Build + UAT).

## Validation Architecture

> `.planning/config.json` not re-read here; nyquist_validation treated as enabled (default). The project has an established backend suite run in Cloud Build (150/150 green per MEMORY).

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (backend), with `fastapi.testclient.TestClient` (httpx-backed) |
| Config file | `backend/pyproject.toml` / existing `backend/tests/conftest.py` |
| Quick run command | `pytest backend/tests/test_mail_*.py -x` (new files) |
| Full suite command | run in Cloud Build (dev machine has no Python — MEMORY: "how to run the full suite in Cloud Build") |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| NOTIF-01 | No mail body contains a bearer token; CTA is an app route w/ intake id | unit (render) | `pytest backend/tests/test_mail_render.py -x` | ❌ Wave 0 |
| NOTIF-01 | Invite mail is the ONLY body carrying an action link | unit | `pytest backend/tests/test_mail_render.py::test_invite_carries_link -x` | ❌ Wave 0 |
| NOTIF-02 | Each send endpoint calls the (faked) Resend transport with resolved active-member emails | contract | `pytest backend/tests/test_mail_endpoints.py -x` | ❌ Wave 0 |
| NOTIF-02 | `admin_validated` fires on `reviewed → validated_by_client`; client validate succeeds even if mail fails | contract | `pytest backend/tests/test_intake_validate_mail.py -x` | ❌ Wave 0 |
| D-16 | `sent_at` updates ONLY on a 2xx send; not on failure | contract | `pytest backend/tests/test_mail_endpoints.py::test_timestamp_on_success_only -x` | ❌ Wave 0 |
| D-07/TENANT | Cross-space intake send → 404 (existence-hidden) | denial | `pytest backend/tests/test_mail_denial.py -x` (extends two-space harness) | ❌ Wave 0 |
| D-06 | Recipient emails come only from active memberships; no body-supplied address honored | contract | `pytest backend/tests/test_mail_endpoints.py::test_no_free_address -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** the new `test_mail_*.py` file(s) for the task.
- **Per wave merge:** full backend suite in Cloud Build.
- **Phase gate:** full suite green + live UAT send (invite, validation, results, reminder, admin_validated) before `/gsd:verify-work`.

### Wave 0 Gaps
- [ ] `backend/tests/test_mail_render.py` — Jinja2 render + NOTIF-01 token-absence assertions.
- [ ] `backend/tests/test_mail_endpoints.py` — send endpoints, recipient resolution, D-16 timestamp, no-free-address.
- [ ] `backend/tests/test_mail_denial.py` — cross-space 404 (extends the two-space conftest harness).
- [ ] `backend/tests/test_intake_validate_mail.py` — `admin_validated` auto-fire + client-not-blocked.
- [ ] Resend fake fixture in `conftest.py` — monkeypatch `app.mail.resend.send` (mirror `fake_anthropic`/`fake_gcs`), capture-only, returns a fake message id.
- [ ] Frontend: handler-route + recipient-picker have no backend test; prove in UAT.

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | yes | Firebase action codes (one-time, short-lived, single-use) for set/reset password — never a hand-rolled token. Invite mail's link is the only credential any mail carries (D-09). |
| V3 Session Management | no | Session unchanged; login-sync is the existing Phase 3 flow. |
| V4 Access Control | yes | Send endpoints tenant-scoped via injected repo/identity; cross-space → 404 (existence-hidden, D-07). Invite-mail admin-scoped (`get_admin_session`). Recipients server-derived from memberships, never client-supplied (D-06). |
| V5 Input Validation | yes | Pydantic bodies (recipient ids only, no `to`/`space_id`); Jinja2 `autoescape` on all interpolated strings (email-context output encoding). |
| V6 Cryptography | no | No crypto here; Resend key is a bearer secret held server-side only. |
| V7 Error Handling & Logging | yes | `audit.log("mail.sent", …)` with structured metadata ONLY — NEVER the action link/token (Phase 5 contract). `admin_validated` failure silent-logged, not surfaced to the client. |

### Known Threat Patterns for FastAPI + Resend + Firebase-Auth email

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Send-to-arbitrary-address (open relay for phishing "log in" mails) | Spoofing / Information disclosure | No body-supplied `to`; recipients resolved from active memberships only (D-06). |
| Token/link leak via logs or audit rows | Information disclosure | `audit.log` metadata excludes links/tokens (Phase 5 contract); key read at call time, never logged (D-07). |
| Cross-tenant send (mail another space's members / enumerate intakes) | Elevation / Information disclosure | Intake-scoped repo + existence-hidden 404 (D-07); denial test in the two-space harness. |
| HTML injection into email body (project title / client name) | Tampering | Jinja2 `autoescape=True` escapes every `{{ var }}`. |
| Reused/never-expiring bearer link (the RLS-class mistake) | Elevation | NOTIF-01: no data-bearer tokens in mail; only the short-lived, single-use Firebase action code (regenerated per send, D-10). |
| Resend API key exposure to the browser | Information disclosure | All sends server-mediated; key in Secret Manager → Cloud Run env, read at call time; never shipped to frontend. |

## Sources

### Primary (HIGH confidence)
- In-repo reads (authoritative for this codebase): `docs/supabase-functions/send-pulse-mail.ts` (parity source — Resend POST shape, subjects, HTML builders, sent-at behavior), `backend/app/api/intake_routes.py` (protected router, `submit_intake` transition, existence-hidden 404), `backend/app/api/admin_routes.py` + `backend/app/auth/admin_users.py:86` (invite flow, `generate_set_password_link`), `backend/app/core/config.py` (Settings), `backend/app/ai/clients.py` (call-time-secret discipline), `backend/app/db/audit.py` (audit contract), `backend/app/db/models/membership.py` + `intake.py` (recipients + sent-at columns), `backend/pyproject.toml` (httpx/firebase-admin present, jinja2 absent), `backend/tests/conftest.py` (fake_anthropic/fake_gcs/two_spaces harness), `frontend/src/lib/api/{client,admin}.ts`, `frontend/src/lib/firebase.ts`, `frontend/src/components/admin/InviteUserDialog.tsx`, `frontend/src/routes/admin.pulse.intakes.$id.tsx:569-623` (stubbed CTAs), `frontend/src/components/intake/NextStepBanner.tsx` (CTA props), `frontend/src/routes/intake.$id.results.tsx:42` (results status gate).
- Firebase official — custom email action handler (`verifyPasswordResetCode` → `confirmPasswordReset` sequence, reading `mode`/`oobCode`): firebase.google.com/docs/auth/custom-email-handler.

### Secondary (MEDIUM confidence)
- Resend Python docs / API (POST `https://api.resend.com/emails`, `from`/`to`/`subject`/`html`, `resend.Emails.send`): resend.com/docs/send-with-python, resend.com/fastapi.
- Resend Python package metadata (v2.33.0, official repo, MIT): pypi.org/project/resend.

### Tertiary (LOW confidence)
- `jinja2` version pin (`>=3.1`) — `[ASSUMED]`, verify at add time.

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — httpx/firebase-admin confirmed in `pyproject.toml`; Resend POST shape confirmed from the legacy function AND Resend docs; only the jinja2 version is assumed.
- Architecture: HIGH — every seam (routers, repos, audit, config, secrets, frontend transport, Firebase singleton, sent-at columns, the `validated_by_client` transition) was read directly in-repo.
- Pitfalls: HIGH — grounded in this project's recurring lessons (deploy-gap, timestamp-before-send, token-leak) and the legacy parity source.

**Research date:** 2026-07-13
**Valid until:** 2026-08-13 (stable — internal seams; only Resend/Firebase external contracts could drift, both are mature). Re-verify the `jinja2` pin and `firebase-admin` `ActionCodeSettings` signature at plan time.
