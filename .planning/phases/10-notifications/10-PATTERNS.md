# Phase 10: Notifications - Pattern Map

**Mapped:** 2026-07-13
**Files analyzed:** 18 (new + modified)
**Analogs found:** 17 / 18 (1 no-analog: the frontend `/auth/action` route)

Downstream planner: each file below carries its closest existing analog + concrete excerpts to copy. The single genuinely-new pattern (Firebase `confirmPasswordReset` on a frontend route) has NO in-repo analog — use the RESEARCH.md §Code Examples for it.

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|-------------------|------|-----------|----------------|---------------|
| `backend/app/mail/resend.py` (NEW) | service (transport) | request-response (external HTTPS POST) | `backend/app/ai/clients.py` | exact (call-time-secret transport seam) |
| `backend/app/mail/render.py` (NEW) | utility (templating) | transform | `docs/supabase-functions/send-pulse-mail.ts` (HTML builders) | role-match (port target, not a live analog) |
| `backend/app/mail/templates/*.html.j2` (NEW) | config (templates) | transform | `send-pulse-mail.ts` `styles()`/`buildXHtml()` | exact (parity source) |
| `backend/app/mail/send.py` or send helpers (NEW) | service | request-response | `admin_routes.py::invite_user` composition | role-match |
| `backend/app/api/intake_routes.py` (MOD — send endpoints) | route/controller | request-response | `intake_routes.py::submit_intake` + `admin_routes.py::invite_user` | exact (same router, same audit/404 discipline) |
| `backend/app/api/intake_routes.py` (MOD — `admin_validated` in `submit_intake`) | route | event-driven (status-edge fire) | `submit_intake` (`:680`) `_SUBMIT_TRANSITIONS` | exact |
| `backend/app/api/admin_routes.py` (MOD — invite-mail endpoint) | route/controller | request-response | `admin_routes.py::invite_user` (`:110`) | exact |
| `backend/app/auth/admin_users.py` (MOD — `ActionCodeSettings`) | service (IdP wrapper) | request-response | `generate_set_password_link` (`:86`) | exact (same function) |
| `backend/app/core/config.py` (MOD — admin email, app base URL) | config | — | `Settings` non-secret fields (`storage_bucket`, model ids) | exact |
| `backend/pyproject.toml` (MOD — jinja2) | config | — | existing `httpx`/`firebase-admin` decls | exact |
| `backend/tests/test_mail_render.py` (NEW) | test | transform | (render assertions — new shape) | role-match |
| `backend/tests/test_mail_endpoints.py` (NEW) | test | request-response | `conftest.py` fake_* + two_spaces | exact (fake-seam + denial harness) |
| `backend/tests/test_mail_denial.py` (NEW) | test | request-response | cross-tenant 404 suite + `two_spaces` | exact |
| `backend/tests/test_intake_validate_mail.py` (NEW) | test | event-driven | submit-transition tests | role-match |
| `backend/tests/conftest.py` (MOD — `fake_resend`) | test fixture | request-response | `fake_gcs` / `fake_anthropic` | exact |
| `frontend/src/lib/api/admin.ts` + intake seam (MOD) | utility (transport seam) | request-response | `admin.ts::inviteUser` + `client.ts::apiFetch` | exact |
| `frontend/src/components/intake/RecipientPicker.tsx` (NEW) | component | request-response | `InviteUserDialog.tsx` (dialog + shadcn) | role-match |
| `frontend/src/routes/admin.pulse.intakes.$id.tsx` (MOD — un-stub 3 handlers) | route (handlers) | request-response | `onGenerateContextPack` (`:579`) | exact (in-file sibling) |
| `frontend/src/components/admin/InviteUserDialog.tsx` (MOD — send-mail button) | component | request-response | its own success state (`:112`) | exact |
| `frontend/src/routes/auth.action.tsx` (NEW) | route (handler) | request-response | `auth.login.tsx` (route shell only) | **no analog** for the Firebase consume; use RESEARCH §Code Examples |
| `infra/main.tf` (MOD — RESEND_API_KEY secret + env) | config (IaC) | — | `anthropic_api_key` secret block (`:157-176`) | exact |

## Pattern Assignments

### `backend/app/mail/resend.py` (service, external HTTPS POST)

**Analog:** `backend/app/ai/clients.py` — the call-time-secret transport seam AND the test monkeypatch point.

**Imports + module-doc discipline** (copy the docstring intent from `clients.py:1-21`): state that the key is read at call time, never in Settings, never logged; name this the ONE function the suite monkeypatches (mirror `fake_anthropic`/`fake_gcs`).

**Core pattern — secret read at call time** (`clients.py:38-49`):
```python
import os
def anthropic_client() -> anthropic.Anthropic:
    return anthropic.Anthropic(
        api_key=os.environ["ANTHROPIC_API_KEY"],   # read HERE (call time, D-07); missing → loud KeyError
        timeout=_ANTHROPIC_TIMEOUT_S,
    )
```
Apply identically: `send()` reads `os.environ["RESEND_API_KEY"]` inside the body. RESEARCH.md §Pattern 1 gives the exact `httpx.post(...)` body (URL `https://api.resend.com/emails`, `Bearer` header, `{"from","to","subject","html"}`, `raise_for_status()`, `FROM = "Nestor Pulse <nestor@agenic.be>"`). `httpx` is already declared; do NOT add the `resend` SDK.

**Legacy POST shape to port** (`send-pulse-mail.ts:86-90`):
```ts
await fetch('https://api.resend.com/emails', {
  method: 'POST',
  headers: { 'Authorization': `Bearer ${resendKey}`, 'Content-Type': 'application/json' },
  body: JSON.stringify({ from: FROM, to: [to], subject, html }),
});
```

---

### `backend/app/mail/render.py` + `templates/*.html.j2` (utility, transform)

**Analog:** `docs/supabase-functions/send-pulse-mail.ts` — the parity source (Dutch subjects, inline-CSS `styles()`, `buildValidationHtml`/`buildResultsHtml`/`buildAdminValidatedHtml`).

**Port verbatim** the `styles()` block (`send-pulse-mail.ts:118-130`) into a shared `_base.html.j2` (card border `#BFEC40`, tag `#FF2D87`, btn `#141414`). Port each `buildXHtml` body (`:132-183`) into per-type templates. The validation template needs the `isReminder` branch (`:133-136` greeting/intro switch).

**CRITICAL swaps during the port (NOTIF-01 — RESEARCH §Pattern 3 / Pitfall 3):**
- `LOGO_URL` (`send-pulse-mail.ts:9`, dying Supabase bucket) → `{app_base_url}/agenic-logo.png` (D-15, `frontend/public/`).
- `${BASE_URL}/intake/${intake.client_validation_token}` (`:59`) → `{app_base_url}/intake/{intake_id}` (NO token).
- `${BASE_URL}/results/${intake.client_results_token}` (`:69`) → `{app_base_url}/intake/{intake_id}/results` (NO token).
- `admin_validated` URL (`:75`) → `{app_base_url}/admin/pulse/intakes/{intake_id}`.

**Render env** (RESEARCH §Pattern 2): module-level `Environment(FileSystemLoader(...templates), autoescape=select_autoescape(["html","j2"]))`; thin `render_validation(...)` etc. NO `Jinja2Templates`/`TemplateResponse`.

---

### `backend/app/api/intake_routes.py` — send endpoints + `admin_validated` (route, request-response / event-driven)

**Analog:** `submit_intake` (`intake_routes.py:680`) for the router/scope/audit shape; `admin_routes.py::invite_user` for the compose-external-call-then-audit shape.

**Router mounting + scope invariants** (module docstring `intake_routes.py:11-35`): router carries NO auth dep of its own (mounted under `protected_router`); handlers get data via `Depends(get_tenant_repo)`; `space_id` NEVER from the request; cross-tenant `repo.get → None` → **404** (existence-hidden, D-07); sync `def` (pg8000 threadpool). Send endpoints follow ALL of these.

**404 + audit-in-same-tx core** (`submit_intake:695-710`):
```python
intake = repo.get(intake_id)
if intake is None:
    raise HTTPException(status.HTTP_404_NOT_FOUND, "Intake not found")
# ... do work ...
audit.log(repo.session, actor_uid=identity.uid,
          event_type="intake.status_changed", target=str(intake_id),
          space_id=intake.space_id, metadata={"from": old, "to": new})
```
For send endpoints: resolve active-member emails server-side (see membership pattern below), call `resend.send` FIRST, and only on 2xx write `validation_link_sent_at`/`results_link_sent_at` via `repo.patch` + `audit.log(event_type="mail.sent", metadata=<no link/token>)` on `repo.session` (D-16 / Pitfall 1).

**Endpoint verb style (RESEARCH Open Q1):** prefer discrete verbs (`/mail/validation`, `/mail/reminder`, `/mail/results`) to mirror the existing `/submit`/`/review` transition-verb convention (`:680`, `:713`).

**`admin_validated` auto-fire (D-03 / RESEARCH §Pattern 4)** — inside `submit_intake`, after the existing flip+audit, guarded on the target:
```python
if new_status == "validated_by_client":
    try:
        _send_admin_validated(intake)          # to Settings.nestor_admin_email (D-08)
    except Exception:                          # noqa: BLE001 — client must not see an operator-mail error
        log.warning("admin_validated mail failed for intake %s", intake_id)
```
The `reviewed → validated_by_client` edge is `_SUBMIT_TRANSITIONS` (`:649-652`) — the ONLY in-repo path to that status. Do NOT let the mail share a tx that rolls back the client's status change (Pitfall 4).

---

### `backend/app/api/admin_routes.py` — invite-mail endpoint (route, request-response)

**Analog:** `admin_routes.py::invite_user` (`:110-178`) — the exact sibling; the invite-mail endpoint sits beside it.

**Admin-scope + audit** (`:110-113`, `:163-176`):
```python
@admin_router.post("/users")
def invite_user(body, repo: AdminRepo = Depends(get_admin_session),
                identity: Identity = Depends(get_current_identity)) -> InviteResult:
    ...
    action_link = admin_users.generate_set_password_link(body.email)   # fresh link
    audit.log(repo.session, actor_uid=identity.uid, event_type="user.invited",
              target=uid, space_id=space.id,
              metadata={"email": body.email, ...})   # NEVER the link/token
    return InviteResult(uid=uid, space_id=body.space_id, action_link=action_link)
```
Invite-mail endpoint (RESEARCH Open Q2: key on `membership_id`, `POST /admin/users/{membership_id}/invite-mail`): look up membership → `generate_set_password_link(email)` fresh per send (D-10) → `resend.send` → `audit.log(event_type="mail.sent", metadata NEVER the link)`. Reuse `Depends(get_admin_session)`.

---

### `backend/app/auth/admin_users.py` — `ActionCodeSettings` (service, IdP wrapper)

**Analog / same function:** `generate_set_password_link` (`admin_users.py:86-94`). Phase 5 deliberately omitted `ActionCodeSettings` (bare link). D-11 adds it so the link's continue URL is `/auth/action`:
```python
def generate_set_password_link(email: str) -> str:
    acs = auth.ActionCodeSettings(url=f"{app_base_url}/auth/action", handle_code_in_app=True)
    return auth.generate_password_reset_link(email, action_code_settings=acs)
```
Keep the mockable-seam discipline (module-level `from firebase_admin import auth`; tests patch `app.auth.admin_users.auth.<call>` — `:39-43`). Base URL from config, not a literal (verify `ActionCodeSettings` kwarg against `firebase-admin>=7.4` — RESEARCH A6).

---

### `backend/app/core/config.py` — admin email + app base URL (config)

**Analog:** the non-secret `Settings` fields (`config.py:69-95`, e.g. `storage_bucket`, model ids).

**Copy the field-with-env-name + docstring pattern** (`config.py:69-74`):
```python
storage_bucket: str | None = None   # env STORAGE_BUCKET; non-secret; read at call time
```
Add `nestor_admin_email: str | None = None` (env `NESTOR_ADMIN_EMAIL`, D-08) and an app-base-URL field (env, the legacy `NESTOR_BASE_URL` analog). **Anti-pattern (RESEARCH):** do NOT add `resend_api_key` here — it is a secret, read from `os.environ` in `resend.send()`.

---

### `backend/tests/conftest.py` — `fake_resend` fixture (test fixture)

**Analog:** `fake_gcs` (`conftest.py:676-755`) — the closest (capture-only, monkeypatch-the-seam) fixture; `fake_anthropic` (`:446-472`) for the `.calls`-recording style.

**Copy the `fake_gcs` monkeypatch shape** (`:743-753`): monkeypatch `app.mail.resend.send` with a capture-only fake that appends `{to, subject, html}` to a `calls` list and returns a fake message id. Import `app.mail.resend` lazily via `pytest.importorskip` so conftest stays importable before the module lands (`:700`). The two-space denial harness reuses `two_spaces` (`:352-359`) + `set_space` (`:324-345`).

---

### Frontend — API seam functions (`admin.ts` / intake seam) (utility, request-response)

**Analog:** `admin.ts::inviteUser` (`admin.ts:52-57`) + `client.ts::apiFetch` (never fork it — `client.ts:43`).

**Copy the thin-function-over-apiFetch shape** (`admin.ts:52-57`):
```ts
export function inviteUser(input: { email: string; spaceId: string }): Promise<ApiResult<InviteResult>> {
  return apiFetch<InviteResult>("/admin/users", {
    method: "POST",
    body: JSON.stringify({ email: input.email, space_id: input.spaceId }),
  });
}
```
Add `sendIntakeMail(intakeId, type, recipients)` (RESEARCH §Code Examples has the exact body: `POST /intakes/${id}/mail/${type}`, body `{ recipients }`), `sendInviteMail(membershipId)`, and `listSpaceMembers(spaceId)` (mirror `listUsers`/`listInvitations` `:59-61`,`:158-160`). All return the `ApiResult<T>` union; never throw (`client.ts:8`).

---

### `frontend/src/components/intake/RecipientPicker.tsx` (component, NEW)

**Analog:** `InviteUserDialog.tsx` — shadcn `Dialog` + `useState` + `apiFetch`-backed submit + `sonner` toasts.

**Copy the dialog scaffold + state-reset-on-open** (`InviteUserDialog.tsx:34-62`, `:109-211`): controlled `open`/`onOpenChange`, `useEffect(() => { if (open) { reset } }, [open])`, shadcn `Dialog`/`DialogContent`/`DialogHeader`/`DialogFooter`. For the member list use shadcn checkboxes; **preselect all active members** and **disable the confirm CTA when the list is empty** with an "invite someone first" hint (D-07). Recipient source is server-provided membership rows (D-05/06 — never a free-text address). Dutch copy + `font-mono uppercase` label style (`:157`, `:189`).

---

### `frontend/src/routes/admin.pulse.intakes.$id.tsx` — un-stub 3 handlers (route)

**Analog (in-file sibling):** `onGenerateContextPack` (`:579-597`) — the real busy-key + seam-call + toast handler right next to the stubs.

**Replace the stubs** (`:571-577`, `:621-623` — `toast.message("... komt in Phase 10.")`) with the working pattern from `onGenerateContextPack`:
```ts
const onGenerateContextPack = async () => {
  if (!intake) return;
  setBusyKey("generateContextPack", true);
  try {
    const res = await skills.generateContextPack(intake.id);
    if (!res.success) { toast.error(`… mislukt: ${res.error}`); return; }
    toast.success("…");
  } finally { setBusyKey("generateContextPack", false); }
};
```
For validation/reminder/results: open the RecipientPicker, then call `sendIntakeMail`, gate the busy key (`sendValidation`/`sendReminder`/`sendResults` — the exact keys NextStepBanner already reads, `NextStepBanner.tsx:183`,`:202`,`:270`), and toast success/failure. CTA props are already wired (`NextStepBanner.tsx:18-26`).

---

### `frontend/src/components/admin/InviteUserDialog.tsx` — send-mail button (component)

**Analog:** its own success state (`:112-144`) — the copyable-action-link block. Add a "Verstuur uitnodigingsmail" `Button` next to `Kopieer link` (`:134`) that calls `sendInviteMail(...)` and toasts (D-10). The copy-link fallback stays (D-04).

---

### `frontend/src/routes/auth.action.tsx` (route, NEW) — NO in-repo analog

**Route shell analog:** `auth.login.tsx` (file-route `createFileRoute` convention only). The Firebase action-code CONSUME has **no existing pattern in the repo** — use RESEARCH.md §Code Examples verbatim: read `mode`/`oobCode` from the URL, `verifyPasswordResetCode(auth, oobCode)` then `confirmPasswordReset(auth, oobCode, newPassword)`, import `auth` from `@/lib/firebase` (`firebase.ts:18`). One route serves invite-set-password AND forgot-password (D-12); neutral "Kies je wachtwoord" wording. Handle `auth/expired-action-code` / `auth/invalid-action-code` / `auth/weak-password` (Pitfall 6). `→ navigate("/auth/login")` on success.

---

### `infra/main.tf` — RESEND_API_KEY secret + env (config, IaC)

**Analog:** the `anthropic_api_key` secret block (`main.tf:157-176`) — secret resource + optional version seed + resource-scoped `secretAccessor` grant to the runtime SA.

**Copy that block** for `resend_api_key`: `google_secret_manager_secret` + `..._version` (count-guarded default-0 seed, value out-of-band per runbook) + `google_secret_manager_secret_iam_member` `roles/secretmanager.secretAccessor`, then map into the Cloud Run env via `value_source.secret_key_ref` (as `RESEND_API_KEY`). Add `NESTOR_ADMIN_EMAIL` + app-base-URL as plain (non-secret) Cloud Run env vars. Mirror the changes in `infra/DEPLOY-RUNBOOK.md` (Phase 8 D-07 IaC-drift rule) AND rebuild the image so `jinja2` reaches Cloud Run (Pitfall 2).

## Shared Patterns

### Call-time secret discipline (D-07)
**Source:** `backend/app/ai/clients.py:38-49`
**Apply to:** `app/mail/resend.py`
The API key is read from `os.environ` INSIDE the function, never at module import, never in `Settings`, never logged. Missing key → loud `KeyError`. This function is also the single test monkeypatch seam.

### Audit-in-same-tx, never log links/tokens
**Source:** `backend/app/db/audit.py:41-71` + `admin_routes.py:163-176`
**Apply to:** every send endpoint (`mail.sent` event) + `admin_validated`
```python
audit.log(repo.session, actor_uid=identity.uid, event_type="mail.sent",
          target=..., space_id=..., metadata={<structured only, NEVER the link/token>})
```
`metadata` is structured fields only; the invite/reset action link and any token are NEVER written (Phase 5 contract, `audit.py:25-29`).

### Existence-hidden 404 + tenant-from-identity
**Source:** `intake_routes.py:11-35` (docstring) + `submit_intake:695-697`
**Apply to:** all intake-scoped send endpoints
`space_id` never from the request; `repo.get → None` → 404 (never 403, never leak). Cross-space send denial test extends the `two_spaces` harness.

### Recipient resolution from active memberships (D-05/06)
**Source:** `backend/app/db/models/membership.py:39-47`
**Apply to:** validation/reminder/results send endpoints + `listSpaceMembers`
`OrganizationMembership.email` is the recipient source; filter `status == "active"` (`:45-47`, app-level set `{"active","deactivated"}`). NEVER accept a `to`/email from the request body (RESEARCH anti-pattern). `organization_id` is the space link.

### Sent-at write only on 2xx (D-16)
**Source:** legacy `send-pulse-mail.ts:100-106` (timestamp AFTER a successful send) — but the legacy order is the Pitfall-1 trap; invert it: send FIRST, timestamp only on 2xx.
**Apply to:** validation/results endpoints. Columns already exist: `intake.py:78-83` (`validation_link_sent_at`/`results_link_sent_at`) — no migration needed.

### Frontend transport (never fork)
**Source:** `frontend/src/lib/api/client.ts:43` (`apiFetch`) + `admin.ts` thin functions
**Apply to:** all new seam functions — one thin function per backend route, returns `ApiResult<T>`, never throws.

## No Analog Found

| File | Role | Data Flow | Reason |
|------|------|-----------|--------|
| `frontend/src/routes/auth.action.tsx` (the Firebase `verifyPasswordResetCode`/`confirmPasswordReset` consume) | route/handler | request-response | No existing route consumes a Firebase action code in-repo. The route *shell* copies `auth.login.tsx`'s `createFileRoute` convention and imports `auth` from `firebase.ts`, but the consume logic must come from RESEARCH.md §Code Examples. |
| `backend/app/mail/render.py` + templates | utility | transform | No Jinja2 anywhere in the backend yet (new dependency). The *content* is a direct port of `send-pulse-mail.ts` HTML builders; the *mechanism* (Environment/FileSystemLoader/autoescape) comes from RESEARCH §Pattern 2. |

## Metadata

**Analog search scope:** `backend/app/{ai,auth,api,core,db}`, `backend/tests/conftest.py`, `frontend/src/{lib/api,components/{admin,intake},routes}`, `infra/main.tf`, `docs/supabase-functions/send-pulse-mail.ts`
**Files scanned:** 13 read in full/part + 3 grep sweeps
**Pattern extraction date:** 2026-07-13
