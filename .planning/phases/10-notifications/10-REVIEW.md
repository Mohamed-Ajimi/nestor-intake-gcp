---
phase: 10-notifications
reviewed: 2026-07-13T00:00:00Z
depth: standard
files_reviewed: 29
files_reviewed_list:
  - backend/app/api/admin_routes.py
  - backend/app/api/intake_routes.py
  - backend/app/auth/admin_users.py
  - backend/app/core/config.py
  - backend/app/mail/__init__.py
  - backend/app/mail/render.py
  - backend/app/mail/resend.py
  - backend/app/mail/templates/_base.html.j2
  - backend/app/mail/templates/admin_validated.html.j2
  - backend/app/mail/templates/invite.html.j2
  - backend/app/mail/templates/results.html.j2
  - backend/app/mail/templates/validation.html.j2
  - backend/pyproject.toml
  - backend/tests/conftest.py
  - backend/tests/test_intake_validate_mail.py
  - backend/tests/test_mail_denial.py
  - backend/tests/test_mail_endpoints.py
  - backend/tests/test_mail_render.py
  - frontend/src/components/admin/InviteUserDialog.tsx
  - frontend/src/components/intake/RecipientPicker.tsx
  - frontend/src/lib/api/admin.ts
  - frontend/src/lib/api/intakes.ts
  - frontend/src/routes/admin.pulse.intakes.$id.tsx
  - frontend/src/routes/admin.users.tsx
  - frontend/src/routes/auth.action.tsx
  - frontend/src/routeTree.gen.ts
  - infra/DEPLOY-RUNBOOK.md
  - infra/main.tf
  - infra/variables.tf
findings:
  critical: 1
  warning: 4
  info: 5
  total: 10
status: fixed
fixed:
  critical_warning: 5
  info: 0
fixed_at: 2026-07-14T00:00:00Z
resolutions:
  CR-01: resolved   # 2b036b8 — handleSendMail reads res.data.success
  WR-01: resolved   # 1131777 — refuse send + guard logo when APP_BASE_URL unset
  WR-02: resolved   # 1131777 (backend read) + 67be932 (frontend type)
  WR-03: resolved   # 1131777 — ResearchArtifactRepository import added
  WR-04: resolved   # bbb8535 — invite-mail failure returns 200 + success:false
  IN-01: not_fixed  # out of scope (Info)
  IN-02: not_fixed  # out of scope (Info)
  IN-03: not_fixed  # out of scope (Info)
  IN-04: not_fixed  # out of scope (Info)
  IN-05: not_fixed  # out of scope (Info)
---

# Phase 10: Code Review Report

**Reviewed:** 2026-07-13
**Depth:** standard
**Files Reviewed:** 29
**Status:** issues_found

## Summary

Phase 10 (notifications) reviewed adversarially: Resend transport, Jinja2 render layer, five mail templates, the members-read + three intake send endpoints, the admin invite-mail endpoint, the `admin_validated` auto-fire, the frontend RecipientPicker / `/auth/action` route, and the Terraform/runbook additions.

**Security invariants verified as holding:**

- **NOTIF-01 (no token links in non-invite mails):** confirmed. `validation.html.j2` / `results.html.j2` / `admin_validated.html.j2` interpolate only a caller-composed `cta_url` built from `{app_base_url}/intake/{intake.id}[...]`; no bearer token is ever composed anywhere in `render.py` or `_run_intake_send`. `invite.html.j2` is the only link-carrying template and its link is the Firebase action link. Pinned by `test_mail_render.py`.
- **D-06 (server resolves recipients):** confirmed. `MailRecipients` carries `recipients: list[str]` with `model_config = {"extra": "forbid"}`, so a smuggled `to`/`email` is a 422 (`test_no_free_address`). `_resolve_active_member_emails` resolves only ACTIVE memberships of the intake's own space and 422-rejects any id that fails to resolve (no silent drop-and-send-to-fewer).
- **D-16 (timestamp on 2xx only):** confirmed in the backend. `_run_intake_send` sends first; a raised send returns `{"success": False}` with no timestamp and no `mail.sent` audit row (`test_timestamp_on_success_only`). Reminder stamps nothing. **However, the frontend consumes this contract incorrectly — see CR-01.**
- **Cross-space 404 denial:** confirmed. `repo.get(intake_id)` 404-gates both the members read and every send BEFORE recipient resolution; `test_mail_denial.py` pins exactly-404 + zero sends.
- **No plaintext secrets in Terraform:** confirmed. `resend_api_key` defaults to `""` (version resource `count = 0`), the env injection is a `secret_key_ref` reference, and the runbook seeds the value out-of-band via stdin.
- **Jinja2 autoescape:** confirmed. `select_autoescape(["html", "j2"])` matches the `*.html.j2` suffix; `test_autoescape_guards_project_title` pins the escape of a hostile `<script>` title.

Findings below are the defects that survive that verification. The single Critical is a frontend/backend contract mismatch that makes every failed client-facing send report success to the operator.

## Critical Issues

### CR-01: Frontend reports "E-mail verstuurd" for a FAILED send — body-level `success: false` is never read

**Status:** RESOLVED (commit 2b036b8) — `handleSendMail` now checks `res.data.success` and, on false, toasts a Dutch failure and keeps the picker open for retry.

**File:** `frontend/src/routes/admin.pulse.intakes.$id.tsx:553-571` (with `frontend/src/lib/api/intakes.ts:121-130`)
**Issue:** The backend deliberately returns **HTTP 200 with `{"success": false}`** when the Resend transport fails (`_run_intake_send`, `intake_routes.py:775-779`; pinned by `test_timestamp_on_success_only`: "a failed send returns a 200 JSON body (success=False)"). But `apiFetch` maps any 2xx to `{ success: true, data }` (transport-level success), and `handleSendMail` checks only that transport flag:

```ts
const res = await sendIntakeMail(intake.id, type, recipients);
if (!res.success) {            // transport-level only — true on HTTP 200
  toast.error(`Versturen mislukt: ${res.error}`);
  return;
}
toast.success("E-mail verstuurd.");   // fires even when data.success === false
setMailPickerType(null);
```

`res.data.success` (the `MailResult` the file itself imports the type for) is never inspected. When Resend is down, the API key is missing/misconfigured, or the send otherwise fails, the operator sees a success toast, the picker closes, and — because the backend correctly did NOT stamp `validation_link_sent_at` / `results_link_sent_at` — the phase banner silently stays in the "send" state. The client never receives the validation mail and nobody is told. This defeats the phase's core purpose for exactly the failure case D-16 was designed around.
**Fix:**
```ts
const res = await sendIntakeMail(intake.id, type, recipients);
if (!res.success) {
  toast.error(`Versturen mislukt: ${res.error}`);
  return;
}
if (!res.data.success) {
  toast.error("Versturen mislukt — de mail is niet verstuurd. Probeer opnieuw.");
  return; // keep the picker open so the operator can retry
}
toast.success("E-mail verstuurd.");
setMailPickerType(null);
void load();
```
(Alternative: change the backend to return a non-2xx, e.g. 502, on a failed send — but that requires updating `test_timestamp_on_success_only` and keeps the two send surfaces consistent, since the admin invite-mail already surfaces failure as non-2xx.)

## Warnings

### WR-01: Unset `APP_BASE_URL` produces dead relative CTAs and a literal `None` logo URL — and the send still proceeds and stamps the timestamp

**Status:** RESOLVED (commit 1131777) — `_run_intake_send` refuses (returns `{success: false}`, no stamp, no audit) when `app_base_url` is unset; `_base.html.j2` guards the logo `<img>` with `{% if app_base_url %}`. Tests added: refusal test + logo omit/render render-tests.

**File:** `backend/app/api/intake_routes.py:742-758, 1025-1030`; `backend/app/mail/templates/_base.html.j2:25`
**Issue:** `base = (settings.app_base_url or "").rstrip("/")` means that with `APP_BASE_URL` unset the CTA becomes a *relative* `href="/intake/{id}"` — a dead link in every mail client — while the mail is still sent, `validation_link_sent_at`/`results_link_sent_at` is still stamped, and the audit row is still written. Separately, `_base.html.j2` renders `src="{{ app_base_url }}/agenic-logo.png"`, which with `app_base_url=None` (the value `_run_intake_send` and `_send_admin_validated` pass straight through) renders the literal `src="None/agenic-logo.png"`. This is not hypothetical: per the runbook's own IaC-DRIFT notes, `APP_BASE_URL` is **not set on the live service** until the manual Step 10.2 runs — so the first live send after the image rebuild but before Step 10.2 emits broken mails with a stamped sent-at (which then hides the "send validation" CTA from the operator). Contrast `_send_admin_validated`, which correctly skips when `nestor_admin_email` is unset.
**Fix:** Guard the client-facing sends the same way the admin mail guards its recipient — refuse (or fail loudly) when `app_base_url` is unset:
```python
settings = get_settings()
if not settings.app_base_url:
    _log.warning("APP_BASE_URL unset — refusing mail send for intake %s", intake.id)
    return {"success": False}
```
And in the template, guard the logo: `{% if app_base_url %}<img src="{{ app_base_url }}/agenic-logo.png" ... />{% endif %}`.

### WR-02: Members read includes NULL-email active members that the send resolver then rejects — the picker's preselect-all makes the default send 422

**Status:** RESOLVED (commits 1131777 backend, 67be932 frontend) — `list_members` now filters `email IS NOT NULL`; `SpaceMember.email` aligned to `string | null`; picker label hardened to `name ?? email ?? "(geen naam)"`. Null-email exclusion test added.

**File:** `backend/app/api/intake_routes.py:652-657` vs `620-631`; `frontend/src/components/intake/RecipientPicker.tsx:71,127`; `frontend/src/lib/api/intakes.ts:95-99`
**Issue:** `list_members` returns every ACTIVE membership row with no `email IS NOT NULL` filter (`MemberView.email: str | None` — the backend explicitly models the null). But `_resolve_active_member_emails` builds `resolved` only from rows `if row.email`, so a NULL-email active member always lands in `missing` → the WHOLE send is 422-rejected. The RecipientPicker preselects **all** returned members (`setSelected(new Set(res.data.map((m) => m.id)))`), and a NULL-email member renders as `m.name ?? m.email` → `null` — an **invisible blank checkbox row**. Net effect: one email-less active membership in a space makes the one-click legacy flow fail with an opaque 422 until the operator finds and unticks a row with no label. Additionally, the frontend type `SpaceMember.email: string` contradicts the backend's `str | None`, hiding the case from TypeScript.
**Fix:** Filter the members read to usable recipients (add `OrganizationMembership.email.is_not(None)` to the read — the resolver's stricter rule then matches what the picker showed), OR keep the read as-is but label and disable email-less rows in the picker and exclude them from preselection. Align `SpaceMember.email` to `string | null` either way.

### WR-03: `ResearchArtifactRepository` used in an annotation but never imported in `intake_routes.py`

**Status:** RESOLVED (commit 1131777) — added `ResearchArtifactRepository` to the `app.db.repository` import block.

**File:** `backend/app/api/intake_routes.py:530` (import block at 63-67)
**Issue:** `get_context_pack`'s parameter is annotated `repo: ResearchArtifactRepository`, but the name is absent from the module's imports (`from app.db.repository import IntakeAnswerRepository, IntakeRepository, SkillRunRepository`). It currently survives only because `from __future__ import annotations` stringifies the annotation and the installed FastAPI version tolerates the unresolvable forward reference at dependency construction (empirically: the route is deployed and the suite is green). This is a latent `NameError` under any stricter annotation evaluation (`typing.get_type_hints`, a FastAPI upgrade that resolves signatures eagerly, runtime type checkers), and it fails static analysis (F821). Pre-existing from 07-09, but this file is in the phase diff and the fix is one line.
**Fix:**
```python
from app.db.repository import (
    IntakeAnswerRepository,
    IntakeRepository,
    ResearchArtifactRepository,
    SkillRunRepository,
)
```

### WR-04: Admin invite-mail send has no failure handling — transport errors surface as raw 500s, inconsistent with the intake send contract

**Status:** RESOLVED (commit bbb8535) — `send_invite_mail` wraps link-gen + render + send in try/except and returns `MailResult(success=False)` on failure (audit-on-success-only). Frontend consumers (InviteUserDialog, admin.users resend) now check `res.data.success`. Failure test added.

**File:** `backend/app/api/admin_routes.py:310-312`
**Issue:** `send_invite_mail` calls `mail_resend.send(...)` bare. Any transport failure — Resend non-2xx (`raise_for_status`), a network error, or a missing `RESEND_API_KEY` (`KeyError` from `os.environ[...]`) — propagates as an unhandled exception → HTTP 500 with a generic body. The safety property holds (no audit row is written on failure), but the operator gets `"HTTP 500"` in the toast instead of an actionable message, and the two send surfaces built in the same phase now have divergent failure contracts (intake sends: 200 + `success:false`; invite mail: 500). A missing-key 500 also risks logging a `KeyError: 'RESEND_API_KEY'` traceback in Cloud Run logs on every attempt during the pre-Step-10.3 drift window.
**Fix:** Mirror `_run_intake_send`'s shape:
```python
try:
    mail_resend.send(to=[membership.email], subject=_INVITE_SUBJECT, html=html)
except Exception:  # noqa: BLE001
    _log.warning("invite mail send failed for membership %s", membership_id)
    return MailResult(success=False)
```
(and have the frontend `handleSendMail`/`handleResendInvite` check `res.data.success` — same consumption fix as CR-01).

## Info

### IN-01: Dead call — `resolve_existing_uid` result discarded in the invite reconcile path

**File:** `backend/app/api/admin_routes.py:150-154`
**Issue:** On `EmailAlreadyExistsError` the handler calls `admin_users.resolve_existing_uid(body.email)` and throws away the returned uid, then raises 409 regardless. The docstring claims "we reconcile to the existing uid" but nothing is reconciled — the call is a pure no-op network round-trip to the IdP.
**Fix:** Drop the call, or actually use the uid (e.g., include it in the 409 detail/audit metadata) if reconciliation is intended.

### IN-02: `admin.users.tsx` duplicates the `load()` body inside its mount effect

**File:** `frontend/src/routes/admin.users.tsx:50-83`
**Issue:** The `useEffect` re-implements `load()` line-for-line (with a `cancelled` flag) instead of calling it. Two copies of the same fetch logic will drift.
**Fix:** Extract the cancellable core once, or call `load()` from the effect and accept the unmount race (the pattern used elsewhere in this codebase).

### IN-03: Test apps mutate the module-global `protected_router` per test

**File:** `backend/tests/test_mail_denial.py:131-141`, `backend/tests/test_mail_endpoints.py:158-178`, `backend/tests/test_intake_validate_mail.py:81-90`
**Issue:** `_build_app()` calls `protected_router.include_router(intake_router)` on the shared module-level router object every invocation, so routes accumulate duplicates across tests in one pytest session (first match wins, so assertions still pass). Inherited from `test_intake_cross_tenant.py`, but each new suite compounds it.
**Fix:** Build a fresh `APIRouter` per test app (copy `protected_router`'s dependencies onto a new router) or include once at module scope.

### IN-04: Client-controlled `client_name` flows into mail subject lines

**File:** `backend/app/api/intake_routes.py:748,759-762,1035`
**Issue:** `intake.client_name` (settable by any space user via `PATCH /intakes/{id}` / create) is interpolated into subjects via `str.format`. Header injection is effectively mitigated because Resend takes the subject as a JSON field (no raw MIME splicing), but a hostile name still controls operator/inbox-visible subject text (phishing-ish surface).
**Fix:** Strip control characters (`\r`, `\n`) and cap length when composing the subject.

### IN-05: `resend.send` assumes a JSON 2xx response body

**File:** `backend/app/mail/resend.py:69`
**Issue:** `resp.json().get("id", "")` raises if a 2xx response is not JSON. In `_run_intake_send` that raise is caught by the blanket except and reported as a FAILED send even though the mail already left — a false-negative against D-16 (mail sent, timestamp not stamped). Unlikely with Resend's API, but the seam should not couple "was sent" to "body parsed".
**Fix:** `try: return resp.json().get("id", "") except ValueError: return ""` after `raise_for_status()`.

---

**Notes on scope:** `frontend/src/routeTree.gen.ts` was verified for consistency only — `/auth/action`, `/intake/$id`, and `/intake/$id/results` (all mail CTA targets) are present and consistent with the route files; no style findings raised on generated code. `infra/main.tf` / `variables.tf` were checked for secret hygiene: no plaintext secret literals; the `random_password` for `app_superadmin` living in Terraform state is the documented, pre-existing Path-B exception, not a Phase-10 regression. Pytest was not executed (no local Python — per environment constraint); test files were reviewed by construction.

---

_Reviewed: 2026-07-13_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
