---
phase: 10
slug: notifications
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-07-13
---

# Phase 10 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (backend/tests, established Phases 1–9; testcontainers pgvector:pg16 — runs in Cloud Build, not locally). Frontend: `npx tsc --noEmit` (no component test runner in-repo). |
| **Config file** | backend/pyproject.toml |
| **Quick run command** | authored-by-construction (no local Python/Docker); suite runs via Cloud Build |
| **Full suite command** | Cloud Build test job (see deploy runbook — Phase 7 pattern) |
| **Estimated runtime** | ~10 minutes (Cloud Build) |

---

## Sampling Rate

- **After every task commit:** Author-by-construction review (no local runtime)
- **After every plan wave:** Static checks (grep-guards, `alembic check` authored invariants)
- **Before `/gsd:verify-work`:** Full suite green in Cloud Build + live UAT
- **Max feedback latency:** one Cloud Build run (~10 min, user-triggered)

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 10-01 Task 1 | 10-01 | 1 | (gate) | T-10-SC | jinja2 legitimacy verified on PyPI (Pallets) before install | checkpoint | `<human-check>` (blocking-human) | n/a | ⬜ pending |
| 10-01 Task 2 | 10-01 | 1 | NOTIF-01 | T-10-01/02/03 | Mail module + 5 templates; token-free CTAs; call-time secret; autoescape | build | proven by 10-01 Task 3 `pytest backend/tests/test_mail_render.py -x` | ❌ W0 → created Task 3 | ⬜ pending |
| 10-01 Task 3 | 10-01 | 1 | NOTIF-01 | T-10-01/03 | No access token in any non-invite mail body; invite is the only link-carrier (D-09); autoescape guard | unit (render) | `pytest backend/tests/test_mail_render.py -x` | ❌ W0 → this task | ⬜ pending |
| 10-02 Task 1 | 10-02 | 1 | NOTIF-02 | T-10-04/05 | RESEND_API_KEY secret + resource-scoped grant + env; no plaintext key committed | infra grep | `grep` for resend secret/iam/env in infra/main.tf + variables.tf; no plaintext key (see plan) | ✅ (grep) | ⬜ pending |
| 10-02 Task 2 | 10-02 | 1 | NOTIF-02 | — | Runbook records secret-version, env-var, jinja2 image-rebuild, UAT triggers | doc grep | `grep` for RESEND_API_KEY/NESTOR_ADMIN_EMAIL/APP_BASE_URL/jinja2 in DEPLOY-RUNBOOK.md | ✅ (grep) | ⬜ pending |
| 10-03 Task 1 | 10-03 | 2 | NOTIF-02, D-16 | T-10-06/09/10/13 | Members read (active-only, cross-space 404) + send endpoints resolve active-member recipients; sent-at on 2xx only; admin_validated non-blocking | integration | `pytest backend/tests/test_mail_endpoints.py backend/tests/test_intake_validate_mail.py -x` | ❌ W0 → 10-03 Task 3 | ⬜ pending |
| 10-03 Task 2 | 10-03 | 2 | NOTIF-02 | T-10-08 | invite-mail fresh-link send; ActionCodeSettings continue URL /auth/action; no link in audit | contract | `pytest backend/tests/test_mail_endpoints.py -x -k "invite or action_code"` | ❌ W0 → 10-03 Task 3 | ⬜ pending |
| 10-03 Task 3 | 10-03 | 2 | NOTIF-02, D-16, D-07, D-06 | T-10-06/07/09/13 | Members-read scope + cross-space 404 + no-free-address + timestamp-on-success-only + deactivated-excluded + admin_validated non-blocking | denial + contract | `pytest backend/tests/test_mail_denial.py backend/tests/test_mail_endpoints.py backend/tests/test_intake_validate_mail.py -x` | ❌ W0 → this task | ⬜ pending |
| 10-04 Task 1 | 10-04 | 3 | NOTIF-01, NOTIF-02 | T-10-11 | Seam fns (listSpaceMembers/sendIntakeMail/sendInviteMail) + RecipientPicker (members-only, no free-text) + logo asset | typecheck | `cd frontend && npx tsc --noEmit` | ✅ (tsc) | ⬜ pending |
| 10-04 Task 2 | 10-04 | 3 | NOTIF-02 | T-10-11 | 3 CTAs un-stubbed → RecipientPicker → sendIntakeMail; no "komt in Phase 10" | typecheck | `cd frontend && npx tsc --noEmit` | ✅ (tsc) | ⬜ pending |
| 10-04 Task 3 | 10-04 | 3 | NOTIF-02 | — | Invite-mail action in dialog + member list via sendInviteMail; copy-link fallback kept | typecheck | `cd frontend && npx tsc --noEmit` | ✅ (tsc) | ⬜ pending |
| 10-04 Task 4 | 10-04 | 3 | NOTIF-02 | — | Visual/functional confirm of picker preselect + empty-guard + toast + invite-mail surfaces | checkpoint | `<human-check>` (blocking) | n/a | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/test_mail_render.py` — NOTIF-01 token-absence + invite-only-link + autoescape (10-01 Task 3).
- [x] `backend/tests/test_mail_endpoints.py` — members read (active-only), send endpoints, recipient resolution, D-16 timestamp, no-free-address, invite/action_code (10-03 Task 3).
- [x] `backend/tests/test_mail_denial.py` — cross-space 404 for members read + send endpoints; zero cross-space sends (10-03 Task 3, extends the two-space conftest harness).
- [x] `backend/tests/test_intake_validate_mail.py` — `admin_validated` auto-fire + client-not-blocked (10-03 Task 3).
- [x] `fake_resend` fixture in `conftest.py` — monkeypatch `app.mail.resend.send`, capture-only, returns a fake message id (10-01 Task 3).

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Real Resend delivery + rendering in mail clients | NOTIF-02 | External service; no local runtime | Live UAT: trigger each mail type (invite, validation, results, reminder, admin_validated) against deployed rev, inspect inbox |
| Firebase action-link click-through → custom handler → password set → login | NOTIF-02 | Requires live Identity Platform + browser | Live UAT: invite a test user, click mailed link, set password, log in |
| RecipientPicker preselect + empty-space guard + send toast; both invite-mail surfaces | NOTIF-02 | Visual/functional; no frontend test runner in-repo | 10-04 Task 4 checkpoint: run frontend locally against deployed backend, exercise the picker + invite surfaces |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies (10-01 Task 1 + 10-04 Task 4 are `<human-check>` checkpoints)
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references (render/endpoints/denial/validate-mail test files + fake_resend all authored in the plans)
- [x] No watch-mode flags
- [x] Feedback latency < one Cloud Build run
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** ready
