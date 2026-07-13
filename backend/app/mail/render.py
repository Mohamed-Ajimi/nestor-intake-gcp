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

from jinja2 import Environment, FileSystemLoader, select_autoescape

_TEMPLATES_DIR = Path(__file__).parent / "templates"

#: Module-level Jinja2 environment. autoescape ON for html/j2 (T-10-01).
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "j2"]),
)


def render_validation(
    *,
    first_name: str,
    project_title: str,
    cta_url: str,
    is_reminder: bool,
    app_base_url: str | None = None,
) -> str:
    """Render the validation-request / reminder mail body.

    ``cta_url`` is an intake-id app route (``{app_base_url}/intake/{intake_id}``),
    NEVER a ``client_validation_token`` (NOTIF-01). ``is_reminder`` selects the
    reminder greeting/intro branch (legacy ``buildValidationHtml`` isReminder).
    """
    return _env.get_template("validation.html.j2").render(
        first_name=first_name,
        project_title=project_title,
        cta_url=cta_url,
        is_reminder=is_reminder,
        app_base_url=app_base_url,
    )


def render_results(
    *,
    first_name: str,
    project_title: str,
    cta_url: str,
    app_base_url: str | None = None,
) -> str:
    """Render the results-ready mail body.

    ``cta_url`` is an intake-id app route
    (``{app_base_url}/intake/{intake_id}/results``), NEVER a
    ``client_results_token`` (NOTIF-01).
    """
    return _env.get_template("results.html.j2").render(
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
) -> str:
    """Render the set-password invite mail body.

    This is the ONLY mail that carries an action link (D-09): ``cta_url`` is the
    Firebase action link. Every other mail's CTA is a plain app route.
    """
    return _env.get_template("invite.html.j2").render(
        cta_url=cta_url,
        app_base_url=app_base_url,
    )
