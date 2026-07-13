"""Wave-0 render tests — NOTIF-01 token-absence + invite-only-link + autoescape.

These call the ``app.mail.render`` functions directly (no HTTP, no Resend) and
lock the phase invariants at the render layer, so every downstream send endpoint
(Plan 03) inherits a proven guard:

- NOTIF-01: no non-invite mail body carries a bearer token
  (``client_validation_token`` / ``client_results_token`` never appear); the CTA
  is an intake-id app route instead.
- D-09: the invite mail is the ONLY template that carries an action link.
- T-10-01: a hostile ``project_title`` containing ``<script>`` is HTML-escaped by
  Jinja2 autoescape (the email-context XSS guard).

Also covers ``fake_resend``: capture-only, returns a deterministic fake id, and
performs no network I/O (the seam Plan 03's endpoint tests reuse).

``app.mail.render`` is imported LAZILY via ``importorskip`` so this module
collects cleanly on a box without jinja2 installed (dev machine has no Python;
the suite runs in Cloud Build).
"""

from __future__ import annotations

import pytest

render = pytest.importorskip("app.mail.render")

# A realistic app origin + intake id, used to compose NOTIF-01-compliant CTAs.
_BASE = "https://app.example"
_INTAKE_ID = "3f4b1e2a-0000-4000-8000-000000000abc"

# Token substrings that must NEVER appear in a rendered non-invite body (NOTIF-01).
_TOKEN_SUBSTRINGS = ("client_validation_token", "client_results_token")


def test_validation_cta_is_intake_route_no_token():
    """render_validation carries the intake-id CTA and no bearer token (NOTIF-01)."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}"
    html = render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=cta,
        is_reminder=False,
        app_base_url=_BASE,
    )
    assert cta in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_validation_reminder_branch_renders():
    """The is_reminder branch renders the reminder greeting and keeps the CTA."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}"
    html = render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=cta,
        is_reminder=True,
        app_base_url=_BASE,
    )
    assert "herinnering" in html.lower()
    assert cta in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_results_cta_is_intake_route_no_token():
    """render_results carries the results CTA and no bearer token (NOTIF-01)."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}/results"
    html = render.render_results(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert cta in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_admin_validated_cta_is_admin_route_no_token():
    """render_admin_validated targets the admin app route, carries no token."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_admin_validated(
        client_name="Acme BV",
        project_title="Project Phoenix",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "/admin/pulse/intakes/" in html
    assert cta in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_invite_carries_link():
    """render_invite is the ONLY render that carries its action link (D-09)."""
    action_link = "https://auth.example/action?mode=resetPassword&oobCode=XYZ123"
    html = render.render_invite(cta_url=action_link, app_base_url=_BASE)
    assert action_link in html


def test_autoescape_guards_project_title():
    """A <script> in project_title is HTML-escaped by Jinja2 autoescape (T-10-01)."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}"
    html = render.render_validation(
        first_name="Sam",
        project_title="<script>alert('x')</script>",
        cta_url=cta,
        is_reminder=False,
        app_base_url=_BASE,
    )
    # The raw tag must NOT survive; the escaped form must be present instead.
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_logo_omitted_when_app_base_url_unset():
    """With app_base_url falsy the logo <img> is omitted — never `src="None/..."` (WR-01)."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}"
    html = render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=cta,
        is_reminder=False,
        app_base_url=None,
    )
    # The literal broken logo URL must NOT appear; the img is skipped entirely.
    assert "None/agenic-logo.png" not in html
    assert "agenic-logo.png" not in html


def test_logo_rendered_when_app_base_url_set():
    """With app_base_url set the logo <img> renders against the origin (WR-01 regression guard)."""
    cta = f"{_BASE}/intake/{_INTAKE_ID}"
    html = render.render_validation(
        first_name="Sam",
        project_title="Project Phoenix",
        cta_url=cta,
        is_reminder=False,
        app_base_url=_BASE,
    )
    assert f"{_BASE}/agenic-logo.png" in html


def test_fake_resend_captures_and_returns_fake_id(fake_resend):
    """fake_resend records {to, subject, html} and returns a deterministic id."""
    import app.mail.resend as resend_mod

    message_id = resend_mod.send(
        to=["client@example.com"],
        subject="Even valideren",
        html="<p>hi</p>",
    )
    assert message_id == "fake-resend-id"
    assert fake_resend["calls"] == [
        {"to": ["client@example.com"], "subject": "Even valideren", "html": "<p>hi</p>"}
    ]
