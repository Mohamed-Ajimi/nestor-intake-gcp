"""AI-surface denial suite (SEC-01 / COST-01) — plan 23.1-11.

WHAT THIS FILE PROVES. ``23.1-CONTEXT.md`` § 1's table ends with the most expensive row in
the phase: "the whole ``ai_router`` (7 routes) — ``ai_routes.py:56`` — fire unbounded paid
Claude/OpenAI/Whisper work". Every one of those seven took ``Depends(get_current_identity)``
and NO role gate, so any logged-in role=``user`` could loop a paid model call on Agenic's
provider budget. D-23.1-02 pins the fix: ONE ``app.auth.gates.superadmin_gate`` applied at
ROUTER level (existence-hidden **404**, never 403).

THE SEVEN ROUTES (``ai_routes.py:55``, prefix ``/intakes``):

| # | Route                                          | Handler                     | Spends  |
|---|------------------------------------------------|-----------------------------|---------|
| 1 | ``POST /{id}/skills/apply``                    | ``apply_intake_skill``      | Claude  |
| 2 | ``POST /{id}/skills/context-pack``             | ``generate_context_pack``   | Claude  |
| 3 | ``POST /{id}/skills/structure-answers``        | ``structure_answers``       | Claude  |
| 4 | ``POST /{id}/skills/extract-insights``         | ``extract_insights``        | Claude  |
| 5 | ``POST /{id}/embeddings``                      | ``generate_embeddings``     | OpenAI  |
| 6 | ``POST /{id}/sources/{source_id}/transcribe``  | ``transcribe_source``       | Whisper |
| 7 | ``GET  /{id}/search``                          | ``search_intake_artifacts`` | OpenAI  |

| Test family                     | Proves                                                  |
|---------------------------------|---------------------------------------------------------|
| ``*_user_role_404``             | a role=``user`` IN THE INTAKE'S OWN SPACE gets EXACTLY   |
|                                 | 404 — not 403, not 401, not 422 — from a WELL-FORMED     |
|                                 | request, with ZERO recorded provider calls and ZERO new  |
|                                 | ``skill_runs`` rows.                                     |
| ``*_null_space_404``            | a ``user`` with ``space_id is None`` gets EXACTLY 404    |
|                                 | and **NOT** ``_dispatch_skill_run``'s 403. The ordering  |
|                                 | proof.                                                   |
| ``*_superadmin_still_works``    | a superadmin gets the route's normal success status      |
|                                 | (202 for the six dispatchers, 200 for ``GET /search``).  |
|                                 | Without this arm "404 everything" would pass the suite.  |
| ``..._exactly_one_router_...``  | the gate is ONE object on ``ai_router.dependencies``.    |
| ``..._no_ai_handler_declares``  | the RESOLVED tree of each of the seven carries the gate  |
|                                 | EXACTLY ONCE — "one dependency, not seven" as a fact.    |

WHY "ZERO NEW ``skill_runs`` ROWS" IS ASSERTED AND NOT ASSUMED. All four skill routes call
``_dispatch_skill_run`` (``ai_routes.py:58``) as their FIRST statement, and that helper
INSERTS a ``running`` ``skill_runs`` row before the background task is even scheduled. If the
gate resolved after the handler body a denied caller would still leave that row behind. Plan
23.1-12 adds a PARTIAL UNIQUE INDEX on ``(intake_id, skill) WHERE status = 'running'``, at
which point one orphan row from a denied client would 409 the real operator's next run of
that skill on that intake — permanently, since nothing ever finalizes a row whose background
task never existed. A status code alone does not catch that; a row count does.

WHY THE NULL-SPACE ARM EXISTS — it is the ORDERING proof. ``_dispatch_skill_run`` maps
``tenant_session``'s null-space ``PermissionError`` to **403** (``ai_routes.py:76``). A 403
where 404 is the convention tells an unauthorized caller the endpoint EXISTS. Router-level
dependencies are prepended to every route's own list, so the gate resolves before any handler
dependency and before the handler body — these seven arms are what pins that, on live routes,
rather than trusting the framework's documented order.

THE ASYMMETRY IN THE PROVIDER FAKES, DELIBERATE: the denial arms install ``fake_anthropic`` /
``fake_openai`` and leave the REAL background runners in place, so that if the gate ever
stopped biting the fake would record a call and the assertion would fire. The superadmin arms
stub the six background runners to no-ops instead — the happy paths of those runners are
already owned by ``test_ai_apply_skill`` / ``test_ai_context_pack`` / ``test_ai_embeddings`` /
``test_ai_structure_extract`` / ``test_ai_transcribe``, and this file's superadmin arms exist
only to prove the GATE did not brick the operator. Either way NO provider is ever reached.

THE COUNTERWEIGHT. ``tests/test_client_surface_open.py`` (plan 23.1-02) pins the TEN client
routes that must stay reachable by role=``user``. ``ai_router`` and ``intake_router`` are
separate ``APIRouter`` objects that merely share the ``/intakes`` prefix, so a router-level
dependency on one cannot reach the other — ``test_no_ai_handler_declares_its_own_superadmin_
gate`` measures that rather than assuming it, by asserting the gate is ABSENT from two
``intake_router`` client routes in the same walk.

HARNESS PROVENANCE. Drive-the-real-route + fabricated-Identity + engine-factory-patch is
``test_ai_apply_skill.py`` / ``test_intake_cross_tenant.py``; ``superadmin_engine`` and
``_patch_superadmin_engine`` are copied (never imported — no private symbol crosses a test
module) from ``test_operator_verb_gate.py`` / ``test_mail_endpoints.py``; the audio-source
seeder from ``test_ai_transcribe.py``.

The two ROUTE-WALKING helpers ARE imported from ``test_client_surface_open.py``, on
D-23.1-14's explicit instruction ("do NOT re-derive route walking"): against fastapi 0.141.1
``app.routes`` holds lazy ``_IncludedRouter`` placeholders, so the obvious
``[r for r in app.routes if r.path.startswith('/intakes')]`` returns ZERO routes and any
audit written that way is VACUOUSLY GREEN; and include-level dependencies never reach
``route.dependant``. Both structural tests carry positive self-checks so they cannot go green
on an empty tree.

Skip-clean: ``pytestmark = pytest.mark.integration`` (skips without Docker/DATABASE_URL);
``importorskip`` guards so the file COLLECTS on a box without the backend deps.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager

import pytest

pytestmark = pytest.mark.integration

# firebase-admin is pulled by app.auth.dependencies (verify_id_token). Skip (do NOT error)
# when the Admin SDK / backend deps are not installed on this box.
pytest.importorskip("firebase_admin")
pytest.importorskip("sqlalchemy")
pytest.importorskip("fastapi")

dependencies = pytest.importorskip("app.auth.dependencies")
identity_mod = pytest.importorskip("app.auth.identity")
session_mod = pytest.importorskip("app.db.session")
ai_session_mod = pytest.importorskip("app.db.ai_session")
ai_routes_mod = pytest.importorskip("app.api.ai_routes")
ai_clients_mod = pytest.importorskip("app.ai.clients")
gates = pytest.importorskip("app.auth.gates")

get_current_identity = dependencies.get_current_identity
Identity = identity_mod.Identity

SCHEMA = "nestor"
_HDR = {"Authorization": "Bearer ignored-overridden"}

#: Password granted to the app_superadmin role for the connect-as superadmin engine (test
#: only — the SAME literal test_mail_endpoints / test_operator_verb_gate use, so the role's
#: password stays stable no matter which suite touches it first.
_SUPERADMIN_TEST_PASSWORD = "gsd_test_superadmin_pw"  # noqa: S105 -- ephemeral CI/test only

#: The six background runners ``ai_routes`` imported. Stubbed to no-ops on the superadmin
#: arms only (see the module docstring's note on the deliberate fake asymmetry).
_BG_RUNNERS = (
    "run_apply_intake_skill",
    "run_context_pack",
    "run_structure_answers",
    "run_extract_insights",
    "run_embeddings",
    "run_transcribe",
)

#: The seven routes, keyed by the short name each test family uses. ``path`` is
#: ``path_format`` shaped (exactly what ``_flatten_routes`` yields); the third element is the
#: status a superadmin must receive.
_ROUTES = {
    "apply": ("POST", "/intakes/{intake_id}/skills/apply", 202),
    "context_pack": ("POST", "/intakes/{intake_id}/skills/context-pack", 202),
    "structure_answers": ("POST", "/intakes/{intake_id}/skills/structure-answers", 202),
    "extract_insights": ("POST", "/intakes/{intake_id}/skills/extract-insights", 202),
    "embeddings": ("POST", "/intakes/{intake_id}/embeddings", 202),
    "transcribe": ("POST", "/intakes/{intake_id}/sources/{source_id}/transcribe", 202),
    "search": ("GET", "/intakes/{intake_id}/search", 200),
}


# ---------------------------------------------------------------------------
# Identity fabrication (the override target — no live IdP)
# ---------------------------------------------------------------------------


def _user(space_id) -> "Identity":
    """A ``user`` Identity scoped to one space (space_id as str, as the real claim is)."""
    return Identity(uid=f"u-{space_id}", email="u@x", role="user", space_id=str(space_id))


def _null_space_user() -> "Identity":
    """A ``user`` with NO space — the D-04 default-deny ``_dispatch_skill_run`` 403s."""
    return Identity(uid="u-null", email="n@x", role="user", space_id=None)


def _superadmin() -> "Identity":
    return Identity(uid="super", email="s@x", role="superadmin", space_id=None)


def _as(identity: "Identity"):
    """Return a ``get_current_identity`` override that yields ``identity`` (closure)."""

    def _override():
        return identity

    return _override


# ---------------------------------------------------------------------------
# Engine-factory patches
# ---------------------------------------------------------------------------


def _patch_engine_factories(monkeypatch, user_engine) -> None:
    """Patch the engine factory ``app.db.ai_session`` imported.

    All seven routes reach the DB through ``ai_session`` only — ``_dispatch_skill_run`` ->
    ``create_running_skill_run`` -> ``tenant_session`` for the six dispatchers, and
    ``app.ai.search.semantic_search`` -> ``tenant_session`` for search. None of them takes
    ``get_tenant_repo`` (D-05: the long provider call must not hold the request tx), so
    ``session_mod`` is not strictly needed for these routes — it is patched anyway because
    the app builder mounts the shared ``protected_router``, whose other includes resolve
    their engines there, and an unpatched factory would reach for a real DSN.
    """
    monkeypatch.setattr(ai_session_mod, "get_engine", lambda *a, **k: user_engine)
    monkeypatch.setattr(session_mod, "get_engine", lambda *a, **k: user_engine)


def _patch_superadmin_engine(monkeypatch, sa_engine) -> None:
    """Swap ``get_superadmin_engine`` in both namespaces (the superadmin happy-path arms)."""
    monkeypatch.setattr(session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)
    monkeypatch.setattr(ai_session_mod, "get_superadmin_engine", lambda *a, **k: sa_engine)


@pytest.fixture
def superadmin_engine(engine):
    """A second engine connecting AS the ``app_superadmin`` role (connect-as, not SET ROLE).

    Faithful to production's two-engine routing (D-05): ``current_user = 'app_superadmin'``
    makes the 0003 ``*_superadmin_all`` bypass policy match, granting cross-tenant reach.
    ``app_superadmin`` is a plain non-superuser LOGIN role (conftest's
    ``_ensure_app_superadmin``), so the arm proves the bypass POLICY + GRANTs, not superuser
    ambient authority. Shape copied from ``test_operator_verb_gate.superadmin_engine``.
    """
    from sqlalchemy import create_engine, text

    with engine.begin() as conn:
        conn.execute(
            text(
                f"ALTER ROLE app_superadmin WITH LOGIN PASSWORD '{_SUPERADMIN_TEST_PASSWORD}'"
            )
        )
    sa_url = engine.url.set(username="app_superadmin", password=_SUPERADMIN_TEST_PASSWORD)
    sa_engine = create_engine(sa_url, future=True, pool_pre_ping=True)
    try:
        yield sa_engine
    finally:
        sa_engine.dispose()


# ---------------------------------------------------------------------------
# Seeding / measurement helpers
# ---------------------------------------------------------------------------


def _seed(engine, set_space, space_id, intake_id):
    """Seed org + intake + one ``audio`` intake_source; return the source id.

    The source exists so the transcribe arms send a WELL-FORMED request against real state.
    ``_dispatch_skill_run`` checks only the intake, so a fabricated source id would also be
    accepted — seeding it keeps the superadmin arm honest if that handler ever grows a check.
    """
    from sqlalchemy import text

    source_id = uuid.uuid4()
    with engine.begin() as conn:
        conn.execute(
            text(f"INSERT INTO {SCHEMA}.organizations (id, name) VALUES (:id, :name)"),
            {"id": space_id, "name": "AI router gate space"},
        )
    with engine.begin() as conn:
        set_space(conn, space_id)
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intakes (id, space_id, status) "
                "VALUES (:id, :space_id, 'submitted')"
            ),
            {"id": intake_id, "space_id": space_id},
        )
        conn.execute(
            text(
                f"INSERT INTO {SCHEMA}.intake_sources "
                "(id, space_id, intake_id, kind, file_name, language) "
                "VALUES (:id, :space_id, :intake_id, 'audio', 'gesprek.mp3', 'nl')"
            ),
            {"id": source_id, "space_id": space_id, "intake_id": intake_id},
        )
    return source_id


def _cleanup(engine, space_id) -> None:
    from sqlalchemy import text

    with engine.begin() as conn:
        conn.execute(
            text(f"DELETE FROM {SCHEMA}.organizations WHERE id = :id"),
            {"id": space_id},
        )


def _count_skill_runs(engine, set_space, space_id, intake_id) -> int:
    """Count ``skill_runs`` rows FOR ONE INTAKE (owner GUC set for the RLS read).

    Scoped to the intake id, not merely the space: each scenario seeds a fresh space, but
    filtering by intake keeps the count independent of anything a sibling test left behind.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        set_space(conn, space_id)
        return conn.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.skill_runs WHERE intake_id = :iid"),
            {"iid": intake_id},
        ).scalar_one()


def _build_app():
    """Build a FastAPI app carrying the REAL protected_router + ai_router.

    Mirrors ``app/main.py``'s wiring (``ai_router`` mounted UNDER the default-deny
    ``protected_router``) without the health probes / lifespan / CORS. Same shape as
    ``test_ai_apply_skill._build_app``.
    """
    from fastapi import FastAPI

    from app.api.auth_routes import protected_router

    protected_router.include_router(ai_routes_mod.ai_router)
    app = FastAPI()
    app.include_router(protected_router)
    return app


class _Scenario:
    """The seeded state + the provider fakes one arm drives (attribute bag, no behaviour)."""

    def __init__(self, engine, set_space, space_id, intake_id, source_id, app, anth, oai):
        self.engine = engine
        self.set_space = set_space
        self.space_id = space_id
        self.intake_id = intake_id
        self.source_id = source_id
        self.app = app
        self.anthropic = anth
        self.openai = oai

    def client(self):
        from fastapi.testclient import TestClient

        return TestClient(self.app)

    def request(self, key: str):
        """Issue a WELL-FORMED request for one of the seven routes.

        Every required parameter is supplied — ``source_id`` for transcribe, ``q`` for
        search. A request missing one returns 422, and a 422 is NOT a denial: that is
        precisely how this suite would go vacuously green.
        """
        method, path, _ok = _ROUTES[key]
        url = path.format(intake_id=self.intake_id, source_id=self.source_id)
        client = self.client()
        if method == "GET":
            return client.get(url, params={"q": "wat is de doelgroep"}, headers=_HDR)
        return client.post(url, headers=_HDR)

    def provider_calls(self) -> list:
        """Every provider call the fakes recorded, across all three seams."""
        return (
            list(self.anthropic.calls)
            + list(self.openai.embedding_calls)
            + list(self.openai.transcription_calls)
        )

    def skill_runs(self) -> int:
        return _count_skill_runs(self.engine, self.set_space, self.space_id, self.intake_id)


@contextmanager
def _scenario(
    engine,
    set_space,
    monkeypatch,
    fake_anthropic,
    fake_openai,
    identity,
    *,
    sa_engine=None,
    stub_background=False,
):
    """Seed space + intake + audio source, install the provider fakes, yield a ``_Scenario``.

    ``identity`` may be ``None`` when the caller needs the seeded ``space_id`` to build it —
    the caller then sets ``app.dependency_overrides[get_current_identity]`` itself.
    """
    space_id = uuid.uuid4()
    intake_id = uuid.uuid4()
    app = _build_app()
    try:
        source_id = _seed(engine, set_space, space_id, intake_id)
        _patch_engine_factories(monkeypatch, engine)
        if sa_engine is not None:
            _patch_superadmin_engine(monkeypatch, sa_engine)

        anth = fake_anthropic("{}")
        oai = fake_openai()
        monkeypatch.setattr(ai_clients_mod, "anthropic_client", lambda *a, **k: anth)
        monkeypatch.setattr(ai_clients_mod, "openai_client", lambda *a, **k: oai)
        if stub_background:
            for name in _BG_RUNNERS:
                monkeypatch.setattr(ai_routes_mod, name, lambda *a, **k: None)

        if identity is not None:
            app.dependency_overrides[get_current_identity] = _as(identity)
        yield _Scenario(engine, set_space, space_id, intake_id, source_id, app, anth, oai)
    finally:
        app.dependency_overrides.clear()
        _cleanup(engine, space_id)


# ---------------------------------------------------------------------------
# The three shared arm bodies (each named test below delegates to one)
# ---------------------------------------------------------------------------


def _assert_user_role_404(key, engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    """role=``user`` in the intake's OWN space -> EXACTLY 404, no spend, no row."""
    method, path, _ok = _ROUTES[key]
    with _scenario(engine, set_space, monkeypatch, fake_anthropic, fake_openai, None) as s:
        s.app.dependency_overrides[get_current_identity] = _as(_user(s.space_id))
        before = s.skill_runs()
        resp = s.request(key)

        assert resp.status_code == 404, (
            f"SEC-01 / COST-01: {method} {path} must answer a role=user caller with EXACTLY "
            f"404 (the existence-hidden gate denial), got {resp.status_code} "
            f"(body={resp.text!r}). A 403 is an existence oracle; a 422 means the request "
            f"was malformed and this arm proved nothing; a 2xx means the gate is absent."
        )
        assert s.provider_calls() == [], (
            f"COST-01 VIOLATION: {method} {path} reached a paid provider despite denying "
            f"the caller — recorded calls: {s.provider_calls()!r}"
        )
        after = s.skill_runs()
        assert after == before, (
            f"T-23.1-45: {method} {path} left {after - before} new skill_runs row(s) behind "
            f"for a DENIED caller. _dispatch_skill_run inserted a 'running' row before the "
            f"gate could refuse, and plan 23.1-12's partial unique index on "
            f"(intake_id, skill) WHERE status='running' will turn that orphan into a "
            f"permanent 409 on the real operator's next run."
        )


def _assert_null_space_404(key, engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    """A ``user`` with ``space_id is None`` -> EXACTLY 404, never the dispatcher's 403."""
    method, path, _ok = _ROUTES[key]
    with _scenario(
        engine, set_space, monkeypatch, fake_anthropic, fake_openai, _null_space_user()
    ) as s:
        before = s.skill_runs()
        resp = s.request(key)

        assert resp.status_code == 404, (
            f"ORDERING PROOF FAILED for {method} {path}: a null-space user got "
            f"{resp.status_code} (body={resp.text!r}), not 404. 403 means "
            f"_dispatch_skill_run's PermissionError arm (ai_routes.py:76) ran BEFORE the "
            f"gate — which tells an unauthorized caller the endpoint exists. The gate must "
            f"resolve first; router-level dependencies are prepended for exactly this reason."
        )
        assert s.provider_calls() == [], (
            f"COST-01 VIOLATION: {method} {path} reached a paid provider for a null-space "
            f"caller — recorded calls: {s.provider_calls()!r}"
        )
        assert s.skill_runs() == before, (
            f"T-23.1-45: {method} {path} wrote a skill_runs row for a null-space caller."
        )


def _assert_superadmin_still_works(
    key, engine, set_space, monkeypatch, fake_anthropic, fake_openai, sa_engine
):
    """A superadmin gets the route's normal success status against seeded state."""
    method, path, ok = _ROUTES[key]
    with _scenario(
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        _superadmin(),
        sa_engine=sa_engine,
        stub_background=True,
    ) as s:
        resp = s.request(key)
        assert resp.status_code == ok, (
            f"THE GATE BRICKED THE OPERATOR: {method} {path} must still answer a superadmin "
            f"{ok}, got {resp.status_code} (body={resp.text!r}). Without this arm, gating "
            f"everything to 404 would pass the whole denial suite."
        )


# ===========================================================================
# 1. POST /intakes/{intake_id}/skills/apply — Claude
# ===========================================================================


def test_apply_user_role_404(engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    _assert_user_role_404(
        "apply", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_apply_null_space_404(engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    _assert_null_space_404(
        "apply", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_apply_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "apply",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 2. POST /intakes/{intake_id}/skills/context-pack — Claude
# ===========================================================================


def test_context_pack_user_role_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_user_role_404(
        "context_pack", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_context_pack_null_space_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_null_space_404(
        "context_pack", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_context_pack_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "context_pack",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 3. POST /intakes/{intake_id}/skills/structure-answers — Claude
# ===========================================================================


def test_structure_answers_user_role_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_user_role_404(
        "structure_answers", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_structure_answers_null_space_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_null_space_404(
        "structure_answers", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_structure_answers_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "structure_answers",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 4. POST /intakes/{intake_id}/skills/extract-insights — Claude
# ===========================================================================


def test_extract_insights_user_role_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_user_role_404(
        "extract_insights", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_extract_insights_null_space_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_null_space_404(
        "extract_insights", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_extract_insights_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "extract_insights",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 5. POST /intakes/{intake_id}/embeddings — OpenAI
# ===========================================================================


def test_embeddings_user_role_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_user_role_404(
        "embeddings", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_embeddings_null_space_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_null_space_404(
        "embeddings", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_embeddings_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "embeddings",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 6. POST /intakes/{intake_id}/sources/{source_id}/transcribe — Whisper
# ===========================================================================


def test_transcribe_user_role_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_user_role_404(
        "transcribe", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_transcribe_null_space_404(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai
):
    _assert_null_space_404(
        "transcribe", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_transcribe_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "transcribe",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# 7. GET /intakes/{intake_id}/search — OpenAI (query embed)
# ===========================================================================


def test_search_user_role_404(engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    _assert_user_role_404(
        "search", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_search_null_space_404(engine, set_space, monkeypatch, fake_anthropic, fake_openai):
    _assert_null_space_404(
        "search", engine, set_space, monkeypatch, fake_anthropic, fake_openai
    )


def test_search_superadmin_still_works(
    engine, set_space, monkeypatch, fake_anthropic, fake_openai, superadmin_engine
):
    _assert_superadmin_still_works(
        "search",
        engine,
        set_space,
        monkeypatch,
        fake_anthropic,
        fake_openai,
        superadmin_engine,
    )


# ===========================================================================
# The structural audit — ONE dependency, at router level, not seven copies
# ===========================================================================


def test_ai_router_carries_exactly_one_router_level_gate():
    """``ai_router.dependencies`` holds ``gates.superadmin_gate`` EXACTLY once.

    Read off the ROUTER OBJECT rather than a route, because "at router level" is the claim
    D-23.1-02 actually makes: it is what makes route number EIGHT gated by construction. The
    seven-per-route alternative would satisfy every denial arm above and still leave the next
    route added to this file wide open — which is exactly how the six extra ungated intake
    verbs in 23.1-CONTEXT.md § 1 came to exist.

    Identity is compared with ``is`` on the resolved ``Depends(...).dependency`` target: a
    name-string check passes on any lookalike local named ``superadmin_gate`` and fails on a
    legitimate re-export (``research_routes`` imports this very object as
    ``_superadmin_gate``).

    Not a marker test: it is FALSE if someone moves the gate onto the seven handlers, and
    FALSE if someone adds a second copy at router level.
    """
    superadmin_gate = gates.superadmin_gate
    resolved = [
        getattr(dep, "dependency", None)
        for dep in (ai_routes_mod.ai_router.dependencies or [])
    ]
    hits = [call for call in resolved if call is superadmin_gate]
    assert len(hits) == 1, (
        "D-23.1-02: ai_router must carry EXACTLY ONE router-level Depends(superadmin_gate), "
        f"found {len(hits)}. Resolved router-level dependencies: "
        f"{[getattr(c, '__name__', repr(c)) for c in resolved]}"
    )


def test_no_ai_handler_declares_its_own_superadmin_gate():
    """Each of the seven routes resolves ``superadmin_gate`` EXACTLY ONCE — and no more.

    "One dependency, not seven" (D-23.1-02) as a machine-checked fact rather than a comment.
    A count of exactly one is strictly stronger than "at least one": it fails if anyone adds
    a per-route ``Depends(superadmin_gate)`` alongside the router-level one, which is the
    silent drift D-23.1-01 forbids.

    THE WALKERS ARE IMPORTED, NOT RE-DERIVED (D-23.1-14, measured on this tree against
    fastapi 0.141.1): ``app.routes`` holds lazy ``_IncludedRouter`` placeholders, so the
    obvious ``[r for r in app.routes if r.path.startswith('/intakes')]`` returns ZERO routes
    and an audit written that way is VACUOUSLY GREEN; and include-level dependencies never
    reach ``route.dependant`` at all. ``_resolved_dependency_calls`` walks BOTH the recursive
    dependant tree and the include context, so it sees a gate attached either way.

    THE POSITIVE SELF-CHECKS, so this cannot go green on an empty tree:
      1. the flattened ``/intakes`` inventory is non-empty and covers all seven targets;
      2. the gate is OBSERVED PRESENT on ``GET /intakes/research/runs/{run_id}/locate``, a
         route already known to carry it (plan 23.1-01) — if the walker could not see a gate
         that IS there, the seven assertions below would be meaningless.

    THE NON-LEAK CHECK. ``ai_router`` and ``intake_router`` are separate ``APIRouter``
    objects that merely share the ``/intakes`` prefix, so a router-level dependency on one
    cannot reach the other. That is asserted, not assumed: ``GET /intakes`` and
    ``GET /intakes/{intake_id}/answers`` (rows 1 and 4 of the stay-open list) must resolve
    ZERO gates in the same walk. ``test_client_surface_open.py`` owns the reachability half.
    """
    main = pytest.importorskip("app.main")
    from tests.test_client_surface_open import (  # noqa: E402 -- D-23.1-14: reuse, don't re-derive
        _flatten_routes,
        _resolved_dependency_calls,
    )

    superadmin_gate = gates.superadmin_gate
    flat = _flatten_routes(main.app.routes)

    intake_paths = {p for p, _r, _i in flat if p.startswith("/intakes")}
    assert len(intake_paths) > 0, (
        "the route walker found ZERO /intakes routes — FastAPI does not flatten "
        "include_router (D-23.1-14) and this audit would be vacuously green. Re-verify "
        "_flatten_routes before trusting anything below."
    )

    # SELF-CHECK 2 — the walker CAN see a gate that is genuinely present.
    known_gated = [
        (r, i)
        for p, r, i in flat
        if p == "/intakes/research/runs/{run_id}/locate"
        and "GET" in (getattr(r, "methods", None) or set())
    ]
    assert len(known_gated) >= 1, (
        "the known-gated control route GET /intakes/research/runs/{run_id}/locate is not "
        "mounted at all; the self-check cannot run."
    )
    control_calls = _resolved_dependency_calls(*known_gated[0])
    assert any(call is superadmin_gate for call in control_calls), (
        "SELF-CHECK FAILED: superadmin_gate is NOT visible on a route that carries it "
        "(GET /intakes/research/runs/{run_id}/locate, gated by plan 23.1-01). The walker is "
        "blind, so the seven assertions below would pass by finding nothing. Resolved tree: "
        f"{[getattr(c, '__name__', repr(c)) for c in control_calls]}"
    )

    # The audit proper. EVERY mount is checked, not just the first: ``app.main.app`` includes
    # the module-global ``protected_router`` LAZILY (D-23.1-14), so every other suite's
    # ``_build_app()`` doing ``protected_router.include_router(ai_router)`` adds another mount
    # that shows up here under a full-suite run. Requiring exactly one gate on ALL mounts is
    # strictly stronger than requiring it on one.
    wrong = []
    checked = 0
    for _key, (method, path, _ok) in _ROUTES.items():
        targets = [
            (r, i)
            for p, r, i in flat
            if p == path and method in (getattr(r, "methods", None) or set())
        ]
        assert len(targets) >= 1, (
            f"{method} {path} is NOT mounted on the app — 23.1-CONTEXT.md § 1 names it as "
            f"one of the seven ai_router routes, so it cannot simply have vanished."
        )
        checked += 1
        for route, inherited in targets:
            calls = _resolved_dependency_calls(route, inherited)
            hits = sum(1 for call in calls if call is superadmin_gate)
            if hits != 1:
                wrong.append(
                    f"{method} {path} -> {hits} gate(s): "
                    f"{[getattr(c, '__name__', repr(c)) for c in calls]}"
                )
                break

    assert checked == 7, f"expected to audit exactly 7 AI routes, audited {checked}"
    assert not wrong, (
        "SEC-01 / D-23.1-02 VIOLATION: these ai_router routes do not resolve "
        "superadmin_gate EXACTLY ONCE. Zero means a role=user caller can still spend "
        "Agenic's provider budget; two or more means someone added a per-route copy "
        "alongside the router-level dependency (the drift D-23.1-01 forbids):\n  "
        + "\n  ".join(wrong)
    )

    # NON-LEAK: the gate must NOT have reached intake_router's client routes.
    leaked = []
    for method, path in (("GET", "/intakes"), ("GET", "/intakes/{intake_id}/answers")):
        targets = [
            (r, i)
            for p, r, i in flat
            if p == path and method in (getattr(r, "methods", None) or set())
        ]
        assert len(targets) >= 1, f"{method} {path} is not mounted — it is a CLIENT route."
        for route, inherited in targets:
            calls = _resolved_dependency_calls(route, inherited)
            if any(call is superadmin_gate for call in calls):
                leaked.append(
                    f"{method} {path} -> {[getattr(c, '__name__', repr(c)) for c in calls]}"
                )
                break
    assert not leaked, (
        "the ai_router gate LEAKED onto intake_router. The two routers share the /intakes "
        "prefix but are separate APIRouter objects, so this can only mean the dependency "
        "was attached to the wrong object or to the shared include:\n  " + "\n  ".join(leaked)
    )
