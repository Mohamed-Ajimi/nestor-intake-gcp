---
phase: 11-internationalization-nl-fr-en
plan: 08
subsystem: backend-mail
tags: [i18n, mail, jinja2, locale, D-02, D-07, D-12, D-16]
requires:
  - "11-02: membership.locale + organization.default_locale columns (0010) + D-07 resolution semantics"
provides:
  - "Per-locale mail variants nl/fr/en for validation/results/invite"
  - "render_validation/render_results/render_invite locale param with nl fallback"
  - "_resolve_recipient_locales: server-side per-recipient locale (membership.locale -> org.default_locale -> nl)"
  - "Per-locale grouped render+send in _run_intake_send (D-16 preserved)"
  - "Invite-mail rendered in the target space default_locale"
affects:
  - "backend/app/mail (render + templates)"
  - "backend/app/api intake + admin mail send paths"
tech-stack:
  added: []
  patterns:
    - "Jinja2 per-locale template dirs templates/{nl,fr,en}/ + nl fallback selector"
    - "Per-distinct-locale render+send loop with once-only stamp/audit on 2xx"
key-files:
  created:
    - backend/app/mail/templates/nl/validation.html.j2
    - backend/app/mail/templates/nl/results.html.j2
    - backend/app/mail/templates/nl/invite.html.j2
    - backend/app/mail/templates/fr/validation.html.j2
    - backend/app/mail/templates/fr/results.html.j2
    - backend/app/mail/templates/fr/invite.html.j2
    - backend/app/mail/templates/en/validation.html.j2
    - backend/app/mail/templates/en/results.html.j2
    - backend/app/mail/templates/en/invite.html.j2
    - backend/tests/test_mail_locale.py
  modified:
    - backend/app/mail/render.py
    - backend/app/api/intake_routes.py
    - backend/app/api/admin_routes.py
decisions:
  - "Per-locale subject lines added (D-12) so the subject matches the recipient's body variant, not only the body"
  - "The old top-level validation/results/invite templates were MOVED into nl/ (git renames) — nl is the canonical variant with verbatim prose (D-02)"
  - "_resolve_active_member_emails retained as a documented sibling; the send path now uses _resolve_recipient_locales"
metrics:
  duration_min: 12
  completed: 2026-07-14
  tasks: 2
  files: 13
---

# Phase 11 Plan 08: Email i18n (NL/FR/EN mail variants + per-recipient locale) Summary

Closes the Phase 10 email-i18n deferral (D-02): validation/results/invite mails now render in
each recipient's server-side-resolved locale (membership override → space default → nl), with a
mixed-locale recipient list sending the right variant to each recipient, while `admin_validated`
stays Dutch and the D-16 send-first/stamp-on-2xx discipline is preserved exactly.

## What was built

**Task 1 — Per-locale template variants + render.py locale param (commit a4f09a0)**
- Adopted the per-locale template-dir shape: `templates/{nl,fr,en}/{validation,results,invite}.html.j2`.
  The three original top-level Dutch templates were moved into `nl/` **verbatim** (git recorded them
  as renames), and `fr/`/`en/` variants were authored (D-12) preserving the recognizable layout
  (headings, CTA button, reminder branch, bullet list, footer) of the Dutch originals.
- `_base.html.j2` stays where it is and remains **structural-only** (layout, colours, logo `<img>`);
  `admin_validated.html.j2` stays at the top level and stays **Dutch** (D-02).
- Added `_localized_template(name, locale)` selecting `{locale}/{name}.html.j2` with an `nl/` fallback
  on `TemplateNotFound`. `render_validation` / `render_results` / `render_invite` now take
  `locale: str = "nl"`; `render_admin_validated` deliberately has **no** locale param. autoescape
  (T-11-01) stays ON in every variant — no prose is marked `| safe`.
- Authored `test_mail_locale.py` render-level cases: fr/en variant selection, unknown-locale nl
  fallback, default-is-nl, autoescape-on across nl/fr/en/de (parametrized), and
  `render_admin_validated`-has-no-locale-param + stays Dutch.

**Task 2 — Recipient-locale resolution in the send path + invite send + tests (commit 22a5969)**
- Added `_resolve_recipient_locales(session, space_id, recipient_ids)`, a sibling of
  `_resolve_active_member_emails`, returning `(email, locale)` per active recipient via the D-07 chain
  (`membership.locale` → `organization.default_locale` → `"nl"`). It reuses the exact same
  active-member + 422-rejection validation (foreign/deactivated/email-less ids reject the whole batch;
  empty set raises), reading membership and org strictly within the intake's own `space_id` (T-11-11 —
  no cross-space inference).
- Reworked `_run_intake_send` to group resolved recipients by locale and render+send **once per
  distinct locale group** (deterministic `sorted()` order). D-16 preserved exactly: SEND FIRST; a
  non-2xx on any group returns `{"success": False}` with NO stamp / NO audit; on success the
  `*_sent_at` column is stamped **once** (not per group) and one `mail.sent` audit row is written with
  `recipient_count` = total across groups. The APP_BASE_URL refusal guard (WR-01) is unchanged.
- Added per-locale subject maps (`_SUBJECTS` + `_subject_for`, D-12) so the subject line matches the
  recipient's body variant; the NL rows are the verbatim parity source.
- `admin_routes.send_invite_mail` now resolves the invitee's locale to the target space's
  `default_locale` → `"nl"` (the invitee has no membership locale at invite time) via
  `repo.get_space(...)` and passes `locale=` into `render_invite`.
- Extended `test_mail_locale.py` with send-path cases (a)-(g): membership.locale=fr → fr; no override
  + space default en → en; neither → nl; mixed-locale list → correct variant per recipient (one send
  per distinct locale, single stamp/audit); admin UI language (Accept-Language) does NOT affect the
  variant; D-16 failure path (no stamp/audit); invite uses the space default_locale.

## Deviations from Plan

### Auto-added (Rule 2 — completeness / parity)

**1. [Rule 2] Per-locale subject lines (D-12)**
- **Found during:** Task 2
- **Issue:** The plan's Task-2 action wires `locale=` into the render calls but leaves the module-level
  `_SUBJECT_*` constants Dutch. The phase environment brief explicitly says to author FR/EN subjects
  (D-12); a Dutch subject on an FR/EN body would desync the mail.
- **Fix:** Added `_SUBJECTS` (nl/fr/en × validation/reminder/results) + `_subject_for(locale, type, client)`
  with nl fallback, selected per locale group in `_run_intake_send`. NL rows are the verbatim parity source.
- **Files modified:** backend/app/api/intake_routes.py
- **Commit:** 22a5969

### Test-harness robustness (not a behavior change)

**2. Soft-guarded send-path imports in test_mail_locale.py**
- The send-path test section imports fastapi/firebase/sqlalchemy. To keep the **render-level** cases
  collectable on a box that only has jinja2 (per the plan's Task-1 collect-clean requirement), the
  send-path deps are imported in a `try/except` that marks the send-path cases skipped individually
  (`pytestmark_integration`) rather than a module-level `importorskip` that would skip the render cases
  too. Cloud Build has every dep and runs the full set.

## Threat surface

No new security-relevant surface beyond the plan's `<threat_model>`. Mitigations honored:
- **T-11-01 (XSS):** autoescape ON in every locale variant; no `| safe` on prose (asserted across
  nl/fr/en/de).
- **T-11-11 (Info disclosure):** locale resolved from the recipient's OWN membership/space within the
  intake's `space_id`; the existing active-member 422 rejection blocks foreign/deactivated ids — no
  cross-space recipient inference. The admin's UI language never selects a variant (asserted).
- **T-11-12 (D-16):** per-locale grouping does not regress the send-first/stamp-on-2xx discipline —
  failure returns `{"success": False}` with no stamp/audit (asserted).

## Verification

Backend tests are authored by construction and run in Cloud Build (dev box has no Python). The
render-level cases collect with only jinja2; the send-path cases are `integration`-marked (live PG via
Docker) and skip cleanly otherwise.

- 9 locale variants exist under `templates/{nl,fr,en}/`; each `{% extends %}` `_base`; `admin_validated`
  + `_base` unchanged/Dutch.
- `render_*` select the variant with nl fallback; autoescape ON.
- Send path resolves per-recipient locale server-side; mixed-locale sends per group; D-16 intact.

## Self-Check: PASSED

All 13 key files present on disk; old top-level validation/results/invite templates removed (moved to
`nl/`); `admin_validated.html.j2` + `_base.html.j2` retained. Both task commits (a4f09a0, 22a5969)
present in git log.
