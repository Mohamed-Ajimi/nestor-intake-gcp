---
phase: 10
slug: notifications
status: verified
threats_open: 0
asvs_level: 1
created: 2026-07-14
---

# Phase 10 — Security

> Per-phase security contract: threat register, accepted risks, and audit trail.

---

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| dynamic value → email HTML | project title / client name interpolated into mail bodies | tenant-supplied strings (HTML-injection surface) |
| process env → Resend | RESEND_API_KEY held server-side, read at call time | API secret |
| Secret Manager → Cloud Run | RESEND_API_KEY injected via secret_key_ref | API secret (never in IaC state) |
| client → members read / send endpoint | admin-supplied intake id + membership ids cross into the tenant-scoped API | tenant identifiers |
| intake space → membership read | recipient emails resolved from a root table, pinned to the intake's own space | member PII (emails) |
| picker → send endpoint | browser supplies membership ids only, never raw addresses (D-06) | membership ids |
| mailed action link → browser | Firebase single-use oobCode redeemed client-side | short-lived action code |

---

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-10-01 | Tampering | render.py template interpolation | mitigate | `select_autoescape(["html","j2"])` on module env (render.py:30-33); `<script>` escape pinned by test_mail_render.py:103-115 | closed |
| T-10-02 | Info disclosure | resend.py RESEND_API_KEY | mitigate | Key read from os.environ inside send() (resend.py:58); no Settings field; name appears on no other executable line | closed |
| T-10-03 | Elevation/Info | non-invite templates carrying bearer token (NOTIF-01) | mitigate | Zero `client_*_token` refs in templates; invite is only link-carrier (D-09); token-absence locked by render tests | closed |
| T-10-SC | Tampering | jinja2 install (new dependency) | mitigate | Human legitimacy checkpoint approved pre-install; pinned `jinja2>=3.1,<4` (pyproject.toml:46, Pallets project) | closed |
| T-10-04 | Info disclosure | RESEND_API_KEY value in committed IaC/state | mitigate | Sensitive var default "" with count-0 version (main.tf:226); real value seeded out-of-band per runbook; no `re_*` key material in infra/ | closed |
| T-10-05 | Elevation | over-broad secretAccessor grant | accept | Grant resource-scoped to the single resend secret for the runtime SA only (main.tf:231-233) | closed |
| T-10-06 | Elevation/Info | cross-space intake send / members read / enumeration | mitigate | get_tenant_repo 404 existence-hiding before any resolution (intake_routes.py:655-657, 749-751); test_mail_denial asserts 404 + zero sends | closed |
| T-10-07 | Spoofing/Info | send-to-arbitrary-address (open relay) | mitigate | MailRecipients `extra="forbid"`, ids only (intake_routes.py:244-246); server-side resolution from ACTIVE own-space memberships (591-632); test_no_free_address | closed |
| T-10-08 | Info disclosure | action link / token in audit rows or logs | mitigate | Structured audit fields only ({type, recipient_count}); invite audit excludes link (admin_routes.py:334); WR-04 try/except preserves audit-on-success-only | closed |
| T-10-09 | Tampering | sent-at stamped before mail left | mitigate | D-16 send-then-stamp (intake_routes.py:798-806); WR-01 app_base_url-unset refusal (761-765); test_timestamp_on_success_only | closed |
| T-10-10 | DoS | admin_validated failure crashes client validate | mitigate | try/except after status flip, no shared rollback tx (intake_routes.py:1014-1021); test_validate_not_blocked_by_mail_failure | closed |
| T-10-13a | Info disclosure | members read leaks another space's member emails | mitigate | Query pinned to `organization_id == intake.space_id`, active-only, email NOT NULL (intake_routes.py:585-588, 662); scope tests | closed |
| T-10-11 | Spoofing | free-text recipient in the picker | mitigate | RecipientPicker offers only server-provided membership rows, no free-text input; backend re-validates ids | closed |
| T-10-12 | Info disclosure | action link surfaced in frontend dialog | accept | Copy-link fallback retained per D-04 (InviteUserDialog.tsx:151-190); link is a short-lived single-use Firebase code, not a data-bearer token | closed |
| T-10-13b | Elevation | reused / never-expiring bearer link (RLS-class mistake) | mitigate | Firebase single-use short-lived action code, fresh per send (admin_routes.py:320); verifyPasswordResetCode rejects expired/invalid (auth.action.tsx:85) with friendly re-request message; continue URL pinned via ActionCodeSettings (admin_users.py:108-112) | closed |
| T-10-14 | Authentication | weak password set via handler | mitigate | auth/weak-password caught → inline field error (auth.action.tsx:126-128); client-side min-length pre-check | closed |

*Status: open · closed*
*Disposition: mitigate (implementation required) · accept (documented risk) · transfer (third-party)*

*Note: plans 10-03 and 10-05 both used the ID T-10-13 for different threats; disambiguated here as T-10-13a (members-read scoping) and T-10-13b (bearer-link reuse).*

---

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-10-01 | T-10-05 | secretAccessor grant is resource-scoped to the single resend secret for the runtime SA (mirrors the anthropic_api_key pattern); no project-level secret access | plan 10-02 threat model (user-approved plans) | 2026-07-14 |
| AR-10-02 | T-10-12 | Invite action link shown in dialog for the copy-link fallback (existing Phase-5 behavior, D-04); it is a short-lived single-use Firebase code, not a data-bearer token (D-09) | plan 10-04 threat model (user-approved plans) | 2026-07-14 |

*Accepted risks do not resurface in future audit runs.*

---

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-07-14 | 16 | 16 | 0 | gsd-security-auditor (opus) — verify-mitigations mode, register authored at plan time; tests verified by reading (no local Python; Cloud Build is execution gate of record) |

---

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-07-14
