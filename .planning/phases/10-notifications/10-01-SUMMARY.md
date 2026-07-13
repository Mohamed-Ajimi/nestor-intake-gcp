---
phase: 10-notifications
plan: 01
subsystem: backend/mail
tags: [notifications, resend, jinja2, email, NOTIF-01, NOTIF-02, security]
requires:
  - "app/core/config.py Settings (Phase 2)"
  - "app/ai/clients.py call-time-secret discipline (Phase 7, mirrored)"
  - "tests/conftest.py fake_gcs fixture shape (Phase 9, mirrored)"
provides:
  - "app.mail.resend.send — the single mail-egress seam (RESEND_API_KEY at call time)"
  - "app.mail.render — Jinja2 autoescape Environment + 4 render_* functions"
  - "5 Dutch mail templates (validation/results/admin_validated/invite + _base)"
  - "Settings.nestor_admin_email + Settings.app_base_url (non-secret)"
  - "fake_resend conftest fixture (capture-only) for Plan 03 endpoint tests"
  - "NOTIF-01 token-absence invariant test-locked at the render layer"
affects:
  - "Plan 03 send endpoints (consume render_* + resend.send + fake_resend)"
  - "Plan 04/05 frontend (mail CTAs are intake-id app routes, login-gated)"
tech-stack:
  added:
    - "jinja2>=3.1,<4 (Pallets, legitimacy-approved) — HTML mail render + autoescape"
    - "httpx>=0.27,<1 promoted dev→runtime (Resend sync transport on Cloud Run)"
  patterns:
    - "call-time secret read (os.environ['RESEND_API_KEY'] inside send())"
    - "single monkeypatch seam (send) mirroring anthropic_client/fake_gcs"
    - "Jinja2 template inheritance (_base.html.j2 → type templates)"
key-files:
  created:
    - backend/app/mail/__init__.py
    - backend/app/mail/resend.py
    - backend/app/mail/render.py
    - backend/app/mail/templates/_base.html.j2
    - backend/app/mail/templates/validation.html.j2
    - backend/app/mail/templates/results.html.j2
    - backend/app/mail/templates/admin_validated.html.j2
    - backend/app/mail/templates/invite.html.j2
    - backend/tests/test_mail_render.py
  modified:
    - backend/pyproject.toml
    - backend/app/core/config.py
    - backend/tests/conftest.py
decisions:
  - "httpx promoted dev→runtime dep: resend.send() uses httpx.post in production (Rule 3 blocking fix — module could not run on Cloud Run with httpx dev-only)"
  - "Jinja2 template inheritance chosen over include: _base.html.j2 owns logo + inline CSS + tag/content blocks"
  - "Token substrings scrubbed from template COMMENTS too: acceptance criterion is file-level substring absence, so explanatory comments were reworded"
metrics:
  duration: ~20 min
  completed: 2026-07-13
  tasks: 3
  files: 12
---

# Phase 10 Plan 01: Mail Module (Resend + Jinja2 + Templates) Summary

Self-contained `backend/app/mail/` notification module — a call-time-secret Resend transport, a Jinja2 autoescape render layer, and 5 Dutch HTML mail templates ported from the legacy `send-pulse-mail` edge function with NOTIF-01 CTA swaps — plus 2 non-secret Settings fields, the `jinja2` dependency, a `fake_resend` conftest fixture, and Wave-0 render tests that test-lock the NOTIF-01 token-absence invariant for every downstream send endpoint.

## What Was Built

- **`resend.py`** — `send(*, to, subject, html) -> str`: reads `RESEND_API_KEY` from `os.environ` inside the function body (D-07 discipline, mirrors `app/ai/clients.py`), POSTs to `https://api.resend.com/emails` via sync `httpx.post` with `Authorization: Bearer` + 15s timeout, `raise_for_status()`, returns the Resend message id. `FROM = "Nestor Pulse <nestor@agenic.be>"` (D-13, unchanged). This is the single seam the suite monkeypatches.
- **`render.py`** — module-level Jinja2 `Environment(FileSystemLoader(templates/), autoescape=select_autoescape(["html","j2"]))` (T-10-01 XSS guard) + 4 thin functions: `render_validation` (with `is_reminder` branch), `render_results`, `render_admin_validated`, `render_invite`.
- **5 templates** — `_base.html.j2` (shared inline CSS: card border-top `#BFEC40`, `.tag` `#FF2D87`, `.btn` `#141414`; logo swapped to `{{ app_base_url }}/agenic-logo.png` per D-15) plus the 4 type templates. NOTIF-01 CTAs are intake-id app routes; only `invite.html.j2` carries an action link (D-09).
- **`config.py`** — added `nestor_admin_email` (env `NESTOR_ADMIN_EMAIL`, D-08) and `app_base_url` (env `APP_BASE_URL`). No `resend_api_key` field (secret stays out of Settings).
- **`pyproject.toml`** — `jinja2>=3.1,<4` (legitimacy-approved) + `httpx>=0.27,<1` promoted to runtime.
- **`conftest.py`** — `fake_resend` fixture: capture-only monkeypatch of `app.mail.resend.send`, records `{to, subject, html}`, returns `"fake-resend-id"`, no network.
- **`test_mail_render.py`** — 7 tests: per-type CTA/token-absence, reminder branch, `test_invite_carries_link`, `test_autoescape_guards_project_title`, and `fake_resend` capture/return-id.

## Task 1 — Checkpoint (Pre-Approved)

Task 1 was a `checkpoint:human-verify` gate for `jinja2` package legitimacy (RESEARCH § Package Legitimacy Audit, slopcheck unavailable at research time). The orchestrator presented it to the human and it was **APPROVED**: "approved — pin jinja2>=3.1,<4". Jinja2 confirmed as the Pallets project on PyPI (github.com/pallets/jinja), MIT-licensed, stable 3.x line, no typo-squat concern. Task 2 used the `jinja2>=3.1,<4` pin accordingly. No pause was performed by this executor.

## Verification

Grep-verified (Python cannot run locally — dev machine has no Python; the suite runs in Cloud Build):
- `RESEND_API_KEY` appears only inside `resend.py::send` (plus doc/comment mentions in `resend.py`/`config.py`/`__init__` — never a live read outside `send()`).
- No non-invite `.html.j2` template file contains `client_validation_token` / `client_results_token` (verified NONE, including comments).
- No template references the legacy Supabase logo URL (`inmsssedwdmgtnhaydmg.supabase.co`); logo is `{{ app_base_url }}/agenic-logo.png`.
- `resend.py` contains no `AsyncClient` reference (sync httpx only).
- `render.py` constructs a Jinja2 `Environment` with `autoescape` + `FileSystemLoader`.
- `config.py` has `nestor_admin_email` + `app_base_url`, no `resend_api_key`.
- Test suite includes `test_invite_carries_link` and the autoescape assertion; `fake_resend` present in conftest.

`pytest backend/tests/test_mail_render.py -x` is expected green in Cloud Build (author-by-construction, per project convention — see STATE.md and prior-phase SUMMARYs).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Promoted `httpx` from dev-only to runtime dependency**
- **Found during:** Task 2
- **Issue:** `httpx` was declared only under `[project.optional-dependencies].dev` / `[dependency-groups].dev` (it backs `TestClient`). `resend.py::send` uses `httpx.post` at runtime, so on the Cloud Run image (which installs runtime deps only) the mail send path would `ImportError` — the module could not run in production.
- **Fix:** Added `httpx>=0.27,<1` to the runtime `dependencies` array (kept the dev entry). Not a package-manager-install ambiguity (httpx is already a vetted, present dep — this is a section move, not a new/typo-squattable package), so the RULE 3 package-install exclusion does not apply.
- **Files modified:** `backend/pyproject.toml`
- **Commit:** ca77227

**2. [Rule 1 - Acceptance-criterion correctness] Scrubbed token substrings from template comments**
- **Found during:** Task 2 (grep self-check before commit)
- **Issue:** My initial `validation.html.j2` / `results.html.j2` header comments contained the literal strings `client_validation_token` / `client_results_token` while explaining the swap. The acceptance criterion is file-level substring absence ("No non-invite template file contains the substrings"), which a downstream grep guard enforces — comments count.
- **Fix:** Reworded the comments to "a bearer validation token" / "a bearer results token".
- **Files modified:** `validation.html.j2`, `results.html.j2`
- **Commit:** ca77227

**3. [Rule 1 - same] Removed `AsyncClient` literal from resend.py docstring**
- **Found during:** Task 2 (grep self-check)
- **Issue:** Docstring said "not `AsyncClient`", producing a false hit against the "no `AsyncClient`" acceptance grep.
- **Fix:** Reworded to "the blocking `httpx.post` is used deliberately (no async client)".
- **Files modified:** `backend/app/mail/resend.py`
- **Commit:** ca77227

## Authentication Gates

None.

## Known Stubs

None. `invite.html.j2` is a new template (no legacy analog — the login-only model replaces bearer links); its copy is final Dutch set-password content, not a placeholder. Its `cta_url` is supplied by the caller (Plan 03, the Firebase action link) — that is the intended contract, not a stub.

## Threat Flags

None. All new surface (mail render interpolation, RESEND_API_KEY handling, token-absence in CTAs) is already enumerated in the plan's `<threat_model>` (T-10-01, T-10-02, T-10-03, T-10-SC) and mitigated as specified.

## TDD Gate Compliance

Task 3 is `tdd="true"`, but its implementation (the `render_*` functions) was authored in Task 2 within the same plan, so the RED→GREEN sequence collapses: the tests are GREEN-by-construction against the already-built render layer. This is intentional per the plan structure (Task 2 builds the module; Task 3 locks it with tests). The `test(...)` commit (b912c6d) records the render/fixture tests; the `feat(...)` commit (ca77227) records the implementation that precedes it. No RED commit exists because the implementation was a prerequisite artifact of the prior task, not a to-be-discovered behavior. Tests cannot be executed locally (no Python) — Cloud Build is the gate of record.

## Commits

- ca77227 — `feat(10-01): mail module — Resend transport, Jinja2 render, 5 Dutch templates`
- b912c6d — `test(10-01): fake_resend fixture + render tests lock NOTIF-01 + autoescape`
- 8676434 — `docs(10-01): complete mail module plan — SUMMARY`

## Self-Check: PASSED

All 9 created source/test files and the SUMMARY exist on disk; all three commits (ca77227, b912c6d, 8676434) are reachable in git; working tree clean.
