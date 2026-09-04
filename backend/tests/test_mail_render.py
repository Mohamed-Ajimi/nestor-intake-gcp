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
    """render_invite is the ONLY render that carries its action link (D-09).

    ROOT CAUSE of this test's prior failure (23.1-14): the jinja environment has
    ``autoescape`` ON by design (``app/mail/render.py:16-20``, the T-10-01 XSS
    guard), and a real Firebase action link carries a query string — so its ``&``
    renders as ``&amp;``. The old ``assert action_link in html`` compared the RAW
    url against ESCAPED output and could only ever have passed with the XSS guard
    OFF. The renderer is correct; the assertion was wrong.

    So this now asserts BOTH halves: the escaped link IS present (D-09 — the
    invite really does carry its action link, and a mail client resolves
    ``&amp;`` back to ``&``), and the raw un-escaped form is ABSENT. The second
    half is what keeps the test meaningful — it PROVES autoescape is on rather
    than accidentally proving it is off, so this test now fails if someone
    disables the guard.
    """
    action_link = "https://auth.example/action?mode=resetPassword&oobCode=XYZ123"
    escaped_link = "https://auth.example/action?mode=resetPassword&amp;oobCode=XYZ123"
    html = render.render_invite(cta_url=action_link, app_base_url=_BASE)

    # D-09: the link IS carried, in its HTML-escaped form, inside the CTA href.
    assert escaped_link in html
    assert f'href="{escaped_link}"' in html
    # T-10-01: the raw ampersand form must NOT survive — autoescape is ON.
    assert action_link not in html


def test_invite_autoescapes_hostile_cta_url():
    """A cta_url breaking out of the href attribute is escaped (T-10-01).

    This is the property ``test_invite_carries_link`` was reaching for. The
    invite is the one template that interpolates a URL into an ``href``
    (``templates/{locale}/invite.html.j2:11``), so it is the one place an
    attribute-breakout would land. A hostile url must emit no live tag and no
    closing quote.
    """
    hostile = 'https://evil.example/a"><script>alert(1)</script>'
    html = render.render_invite(cta_url=hostile, app_base_url=_BASE)

    # No live tag, and the attribute was never closed early.
    assert "<script>" not in html
    assert '"><script>' not in html
    # The escaped forms are what actually rendered.
    assert "&lt;script&gt;" in html
    assert "&#34;" in html


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


def test_research_complete_body_has_duration_cost_and_cta():
    """render_research_complete renders duration, cost, and the admin CTA (RUN-02/D-11)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_complete(
        project_title="Project Phoenix",
        duration_min=19,
        cost_usd="1.60",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "19" in html          # duration_min
    assert "1.60" in html        # cost_usd
    assert cta in html           # admin-route CTA (no token)
    assert "/admin/pulse/intakes/" in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_research_complete_autoescapes_hostile_title():
    """A <script> in project_title is HTML-escaped by autoescape (T-16-05)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_complete(
        project_title="<script>alert('x')</script>",
        duration_min=5,
        cost_usd="0.50",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_research_complete_tolerates_missing_metrics():
    """None duration/cost render without a broken 'None' body (metrics may be absent)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_complete(
        project_title="Project Phoenix",
        duration_min=None,
        cost_usd=None,
        cta_url=cta,
        app_base_url=_BASE,
    )
    # The optional metric lines are omitted rather than rendering literal "None".
    assert "None" not in html
    assert cta in html


def test_research_failed_body_has_error_and_cta():
    """render_research_failed renders the error summary + admin CTA (RUN-02)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_failed(
        project_title="Project Phoenix",
        error_summary="tribunal timed out",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "tribunal timed out" in html
    assert cta in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html


def test_research_failed_autoescapes_hostile_error():
    """A <script> in error_summary is HTML-escaped by autoescape (T-16-05)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_failed(
        project_title="Project Phoenix",
        error_summary="<script>alert('x')</script>",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ---------------------------------------------------------------------------
# F-03 / D-17 park mail (plan 15.2-19). A parked run is NOT a failed run: it is a
# pause a superadmin resumes for free. These mirror the render_research_failed
# pair above, plus a 3-locale render sweep, because the park mail is the ONLY
# notification the operator gets that a walled run stopped with its paid work
# intact.
# ---------------------------------------------------------------------------


def test_research_parked_body_has_reason_and_cta():
    """render_research_parked renders the park reason + exactly ONE admin CTA (F-03)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_parked(
        project_title="Project Phoenix",
        park_reason="Anthropic monthly cap reached",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "Anthropic monthly cap reached" in html
    assert cta in html
    # NOTIF-01: the CTA is an admin app route, never a token link.
    assert "/admin/pulse/intakes/" in html
    for token in _TOKEN_SUBSTRINGS:
        assert token not in html
    assert "token" not in html
    # EXACTLY one anchor — one decision, one button (16-D-11). _base.html.j2
    # contributes no <a>, so this counts the template's own CTA alone.
    assert html.count("<a ") == 1


def test_research_parked_autoescapes_hostile_reason():
    """A <script> in park_reason is HTML-escaped by autoescape (T-15.2-194).

    The reason arrives ALREADY error_signature()-redacted from the engine
    (15.2-16); this layer escapes it, it does not sanitise it a second time.
    """
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_parked(
        project_title="Project Phoenix",
        park_reason="<script>x</script>",
        cta_url=cta,
        app_base_url=_BASE,
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


def test_research_parked_unknown_locale_falls_back_to_nl():
    """An unknown locale resolves to the nl park variant rather than raising (RUN-02)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_parked(
        project_title="Project Phoenix",
        park_reason="geen enkele stroom leverde bruikbaar materiaal",
        cta_url=cta,
        app_base_url=_BASE,
        locale="xx",
    )
    # The nl heading proves the fallback resolved to a real template.
    assert "Het onderzoek staat op pauze" in html


@pytest.mark.parametrize("locale", ["nl", "en", "fr"])
def test_research_parked_all_three_locales_render(locale):
    """All three park templates render non-empty HTML carrying the reason."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_parked(
        project_title="Project Phoenix",
        park_reason="Anthropic monthly cap reached",
        cta_url=cta,
        app_base_url=_BASE,
        locale=locale,
    )
    assert html.strip()
    assert "Anthropic monthly cap reached" in html
    assert cta in html


def test_research_unknown_locale_falls_back_to_nl():
    """An unknown locale resolves to the nl variant (D-07 fallback chain)."""
    cta = f"{_BASE}/admin/pulse/intakes/{_INTAKE_ID}"
    html = render.render_research_complete(
        project_title="Project Phoenix",
        duration_min=10,
        cost_usd="1.00",
        cta_url=cta,
        app_base_url=_BASE,
        locale="xx",
    )
    # The nl heading proves the fallback resolved to a real template.
    assert "Het onderzoek is klaar" in html


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
