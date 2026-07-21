"""Jinja2 mail-body render layer (autoescape ON — the XSS guard T-10-01).

Pure string production: a module-level Jinja2 ``Environment`` loading the
``templates/`` directory with ``autoescape`` enabled, plus one thin ``render_*``
function per mail type. This is NOT FastAPI ``Jinja2Templates`` /
``TemplateResponse`` — the endpoints (Plan 03) want an HTML *string* to hand to
``app.mail.resend.send``, not a Starlette response.

Autoescape (T-10-01): every ``{{ var }}`` interpolation — ``project_title``,
``client_name``, ``first_name`` — is HTML-escaped, so a hostile intake title
containing ``<script>`` cannot inject markup into a mail body. The render tests
assert this directly.

NOTIF-01 (the CTA contract): the caller passes a fully-formed ``cta_url``; the
render layer never constructs a token URL. Non-invite callers pass an intake-id
app route (``{app_base_url}/intake/{intake_id}`` etc.); only the invite mail's
``cta_url`` is an action link (D-09). ``app_base_url`` is passed through solely
for the logo ``<img>`` src (D-15).
"""

from __future__ import annotations

from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates"

#: The guaranteed-present fallback locale (D-07 chain base). Every client-facing mail
#: type ships an ``nl/`` variant, so a missing/unknown requested locale always resolves
#: to a real template rather than raising.
_FALLBACK_LOCALE = "nl"

#: Module-level Jinja2 environment. autoescape ON for html/j2 (T-10-01 / T-11-01) — every
#: ``{{ var }}`` is HTML-escaped in EVERY locale variant; no variant marks prose ``| safe``.
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def _localized_template(name: str, locale: str):
    """Return the ``{locale}/{name}.html.j2`` template, falling back to ``nl/`` (D-07).

    The Phase-11 email-i18n selector: client-facing mail types (validation/results/invite)
    live under per-locale dirs ``templates/{nl,fr,en}/``. A requested locale whose variant
    is missing (an unknown code, or a locale that never shipped a given template) resolves
    to the guaranteed ``nl/`` variant rather than raising — ``nl`` is the resolution-chain
    base (user override -> space default -> "nl"). Locale is resolved SERVER-SIDE by the
    caller (never from the sending admin's UI); this layer only maps a resolved code to a
    template path. autoescape stays ON regardless of variant (T-11-01).
    """
    try:
        return _env.get_template(f"{locale}/{name}.html.j2")
    except TemplateNotFound:
        return _env.get_template(f"{_FALLBACK_LOCALE}/{name}.html.j2")


def render_validation(
    *,
    first_name: str,
    project_title: str,
    cta_url: str,
    is_reminder: bool,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the validation-request / reminder mail body in ``locale`` (nl fallback).

    ``cta_url`` is an intake-id app route (``{app_base_url}/intake/{intake_id}``),
    NEVER a ``client_validation_token`` (NOTIF-01). ``is_reminder`` selects the
    reminder greeting/intro branch (legacy ``buildValidationHtml`` isReminder).
    ``locale`` (D-07, resolved server-side by the caller) selects the per-locale variant
    ``templates/{locale}/validation.html.j2`` — an unknown locale falls back to ``nl``.
    """
    return _localized_template("validation", locale).render(
        first_name=first_name,
        project_title=project_title,
        cta_url=cta_url,
        is_reminder=is_reminder,
        app_base_url=app_base_url,
    )


def render_intake(
    *,
    first_name: str,
    project_title: str,
    cta_url: str,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the intake-invite mail body in ``locale`` (nl fallback).

    ``cta_url`` is the token-free intake-id app route
    (``{app_base_url}/intake/{intake_id}``), NEVER a ``client_intake_token``
    (NOTIF-01). ``locale`` (D-07, resolved server-side by the caller) selects
    ``templates/{locale}/intake.html.j2`` — an unknown locale falls back to ``nl``.
    """
    return _localized_template("intake", locale).render(
        first_name=first_name,
        project_title=project_title,
        cta_url=cta_url,
        app_base_url=app_base_url,
    )


def render_results(
    *,
    first_name: str,
    project_title: str,
    cta_url: str,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the results-ready mail body in ``locale`` (nl fallback).

    ``cta_url`` is an intake-id app route
    (``{app_base_url}/intake/{intake_id}/results``), NEVER a
    ``client_results_token`` (NOTIF-01). ``locale`` (D-07, resolved server-side by the
    caller) selects ``templates/{locale}/results.html.j2`` — unknown locale falls back to
    ``nl``.
    """
    return _localized_template("results", locale).render(
        first_name=first_name,
        project_title=project_title,
        cta_url=cta_url,
        app_base_url=app_base_url,
    )


def render_admin_validated(
    *,
    client_name: str,
    project_title: str,
    cta_url: str,
    app_base_url: str | None = None,
) -> str:
    """Render the admin "klant heeft gevalideerd" notification body.

    ``cta_url`` is an admin app route
    (``{app_base_url}/admin/pulse/intakes/{intake_id}``) — no token (NOTIF-01).
    """
    return _env.get_template("admin_validated.html.j2").render(
        client_name=client_name,
        project_title=project_title,
        cta_url=cta_url,
        app_base_url=app_base_url,
    )


def render_invite(
    *,
    cta_url: str,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the set-password invite mail body in ``locale`` (nl fallback).

    This is the ONLY mail that carries an action link (D-09): ``cta_url`` is the
    Firebase action link. Every other mail's CTA is a plain app route. ``locale`` (D-07;
    at invite time the invitee has no membership locale yet, so the caller resolves it to
    the target space's ``default_locale`` -> "nl") selects
    ``templates/{locale}/invite.html.j2`` — unknown locale falls back to ``nl``.
    """
    return _localized_template("invite", locale).render(
        cta_url=cta_url,
        app_base_url=app_base_url,
    )


def render_research_complete(
    *,
    project_title: str,
    duration_min: int | None,
    cost_usd: object = None,
    cta_url: str,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the "research complete" notification body in ``locale`` (nl fallback, RUN-02).

    Short body per D-11: "research for {project_title} is done" + duration + cost +
    ONE CTA button to the admin intake route. ``cta_url`` is
    ``{app_base_url}/admin/pulse/intakes/{intake_id}`` — an admin app route, NEVER a
    token (NOTIF-01). Sent to the triggering superadmin (D-10). ``locale`` selects
    ``templates/{locale}/research_complete.html.j2`` — an unknown locale falls back to
    ``nl``. autoescape stays ON, so a hostile ``project_title`` cannot inject markup
    (T-16-05).
    """
    return _localized_template("research_complete", locale).render(
        project_title=project_title,
        duration_min=duration_min,
        cost_usd=cost_usd,
        cta_url=cta_url,
        app_base_url=app_base_url,
    )


def render_research_failed(
    *,
    project_title: str,
    error_summary: str,
    cta_url: str,
    app_base_url: str | None = None,
    locale: str = "nl",
) -> str:
    """Render the "research failed" notification body in ``locale`` (nl fallback, RUN-02).

    Short body per D-11: what failed (``error_summary``) + ONE CTA button to the admin
    intake route. ``cta_url`` is ``{app_base_url}/admin/pulse/intakes/{intake_id}`` — an
    admin app route, NEVER a token (NOTIF-01). Sent to the triggering superadmin (D-10).
    ``locale`` selects ``templates/{locale}/research_failed.html.j2`` — an unknown locale
    falls back to ``nl``. autoescape stays ON, so a hostile ``project_title`` /
    ``error_summary`` cannot inject markup (T-16-05).
    """
    return _localized_template("research_failed", locale).render(
        project_title=project_title,
        error_summary=error_summary,
        cta_url=cta_url,
        app_base_url=app_base_url,
    )
