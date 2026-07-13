"""Self-contained transactional-mail module (Phase 10, NOTIF-01/02).

Three pieces, no side effects at import:

- ``resend``  — the Resend HTTPS transport. ``send()`` reads ``RESEND_API_KEY``
  from ``os.environ`` at CALL TIME (D-07 discipline, mirroring ``app/ai/clients``)
  and is the single seam the test suite monkeypatches (see ``fake_resend``).
- ``render``  — a Jinja2 ``Environment`` (autoescape ON, the XSS guard T-10-01)
  plus thin per-type ``render_*`` functions producing HTML strings.
- ``templates/*.html.j2`` — the Dutch mail bodies ported from the legacy
  ``send-pulse-mail`` edge function, with NOTIF-01 CTA swaps applied (every
  non-invite CTA is an intake-id app route, NEVER a bearer token; only the invite
  mail carries an action link — D-09).

Intentionally kept import-light so ``fake_resend`` in conftest can
``importorskip("app.mail.resend")`` on a box without jinja2/httpx installed.
"""
