"""
Pytest fixtures for the Nestor Intake (GCP re-platform) backend test suite.

This is the **Wave 0** harness: the schema (plan 01-02) and RLS policies
(plan 01-03) do NOT exist yet, so the schema-shape and RLS-isolation suites
that consume these fixtures are RED by design until those plans land. The
harness itself must collect cleanly and skip — never hard-error — when no
Postgres is reachable.

Authoritative references (this repo):
- .planning/phases/01-schema-migrations/01-RESEARCH.md
    § Environment Availability  -- pgvector/pgvector:pg16 image requirement;
                                   app_superadmin out-of-band role (fixture fallback)
    § Common Pitfalls / Pitfall 1 -- set_config(..., true) transaction-local GUC
    § Open Questions / Q1 RESOLVED -- sync pg8000 driver (NOT the sibling's async asyncpg)
- .planning/phases/01-schema-migrations/01-PATTERNS.md
    § tests/conftest.py assignment -- fixture list (pgvector container, async/sync
      engine, set_space helper, two_spaces, app_superadmin role creation)

Ported from the sibling repo
``C:/Users/ajimimo/Desktop/MOELD/Nestor/nestor_pulse_sdk/tests/conftest.py``
with the global rename applied:
    tenant_id          -> space_id
    app.tenant_id (GUC)-> app.current_space_id
    worker_user (role) -> app_superadmin
    two_tenants        -> two_spaces
    set_tenant         -> set_space
and the engine switched from async asyncpg to **sync pg8000** per Q1.

Design notes:
- The Postgres container is session-scoped and SKIPPED cleanly when Docker is
  not reachable (Docker availability is a known gap on the dev box per
  01-RESEARCH.md § Environment Availability). The suite must still exit 0 in
  that case (`pytest --collect-only` must succeed with no Docker).
- The engine fixture exposes a single ``alembic upgrade head`` call site
  (``_run_migrations``). It may fail RED until plan 01-02 lands the migrations;
  that is the intended Wave 0 state.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import pytest

# The literal Postgres image that ships the `vector` extension. Plain
# `postgres:16` would NOT have pgvector, so the schema's `vector(1536)` column
# and `CREATE EXTENSION vector` would fail. This MUST be pgvector/pgvector:pg16.
PGVECTOR_IMAGE = "pgvector/pgvector:pg16"

# The transaction-local GUC key. MUST match the policy expression authored in
# plan 01-03's 0002 migration: NULLIF(current_setting('app.current_space_id', true), '')::uuid
SPACE_GUC_KEY = "app.current_space_id"

# The NON-superuser role that owns the schema in tests. The container's
# POSTGRES_USER is a Postgres SUPERUSER, and superusers bypass RLS
# unconditionally (FORCE ROW LEVEL SECURITY binds table OWNERS, not
# superusers) — so every RLS-observing suite would silently test nothing if it
# ran on the superuser DSN. Cloud SQL's migration/app roles are NOT superusers,
# so a non-superuser owner is also the higher-fidelity shape. The superuser DSN
# is used only for one-time bootstrap (extensions, roles, database ownership).
OWNER_ROLE = "nestor_owner"
OWNER_PASSWORD = "nestor-owner-test-pw"


# ---------------------------------------------------------------------------
# Skip-clean guard: no Docker AND no DATABASE_URL -> skip, never error
# ---------------------------------------------------------------------------

def _database_url_from_env() -> str | None:
    """Return an explicit DATABASE_URL if one is set, else None.

    Mirrors the sibling `_require_database_url` pattern, but as a soft probe:
    when DATABASE_URL is provided (e.g. a Cloud SQL Auth Proxy DSN in CI) we
    use it directly and skip the container spin-up entirely.
    """
    return os.environ.get("DATABASE_URL") or None


# ---------------------------------------------------------------------------
# Session-scoped Postgres (pgvector) container fixture (testcontainers)
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session")
def pg_container():
    """Spin up an ephemeral `pgvector/pgvector:pg16` container.

    Skipped (NOT errored) when:
      - testcontainers is not installed yet (Wave 0 deps pending), OR
      - Docker is not reachable on this box.
    so the suite exits 0 on a dev machine with no live DB.

    When DATABASE_URL is set the container is bypassed (yields None) and the
    engine fixture binds to that DSN instead.
    """
    if _database_url_from_env():
        # An explicit DSN was provided; no container needed.
        yield None
        return

    try:
        from testcontainers.postgres import PostgresContainer  # type: ignore
    except ImportError:
        pytest.skip("testcontainers not installed yet (Wave 0 dev deps pending)")
        return  # unreachable; pytest.skip raises

    try:
        container = PostgresContainer(PGVECTOR_IMAGE)
        container.start()
    except Exception as exc:  # noqa: BLE001 -- DockerException family + connection errors
        pytest.skip(f"Docker not available for testcontainers: {exc}")
        return  # unreachable; pytest.skip raises

    try:
        yield container
    finally:
        try:
            container.stop()
        except Exception:  # noqa: BLE001
            pass


# ---------------------------------------------------------------------------
# Connection-URL resolution (sync pg8000 driver — Q1 RESOLVED)
# ---------------------------------------------------------------------------

def _sync_pg8000_url(pg_container: Any) -> str:
    """Resolve a `postgresql+pg8000://` DSN from the container or env.

    Q1 RESOLVED: Phase 1 standardizes on the sync **pg8000** driver (matching
    the Cloud SQL connector's documented sync driver), so the test engine and
    Alembic env.py agree on one driver.
    """
    explicit = _database_url_from_env()
    if explicit:
        # Normalize any driver the env DSN happens to carry to pg8000.
        for prefix in (
            "postgresql+psycopg2://",
            "postgresql+psycopg://",
            "postgresql+asyncpg://",
            "postgresql://",
        ):
            if explicit.startswith(prefix):
                return "postgresql+pg8000://" + explicit[len(prefix):]
        return explicit

    if pg_container is None:  # pragma: no cover - guarded by pg_container skip
        pytest.skip("No Postgres container and no DATABASE_URL available")

    # testcontainers hands back a psycopg2 URL by default; swap the driver.
    url = pg_container.get_connection_url()
    return url.replace("postgresql+psycopg2://", "postgresql+pg8000://")


def _run_migrations(engine: Any) -> None:
    """Single call site for building the schema into the container.

    Runs ``alembic upgrade head`` against the test engine's URL. This is the
    ONE place the suite materializes the schema; the schema-shape and RLS
    suites depend on it. It WILL fail RED until plan 01-02 lands the Alembic
    migrations — that is the intended Wave 0 state, so failures here are
    surfaced as skips so the harness itself stays collectable.
    """
    try:
        from alembic import command  # type: ignore
        from alembic.config import Config  # type: ignore
    except ImportError:
        pytest.skip("alembic not installed yet (Wave 0 dev deps pending)")
        return

    backend_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    alembic_ini = os.path.join(backend_root, "alembic.ini")
    if not os.path.exists(alembic_ini):
        # Plans 01-02/01-03 land alembic.ini + versions/. Until then there is
        # no schema to build; the consuming suites are RED-by-design.
        pytest.skip("alembic.ini not present yet (schema lands in plan 01-02)")
        return

    cfg = Config(alembic_ini)
    # render_as_string(hide_password=False): str(engine.url) masks the password
    # as literal "***", which Alembic would then use as the real password.
    cfg.set_main_option(
        "sqlalchemy.url", engine.url.render_as_string(hide_password=False)
    )
    command.upgrade(cfg, "head")


# ---------------------------------------------------------------------------
# app_superadmin role fixture (Cloud SQL has no BYPASSRLS — bypass via role)
# ---------------------------------------------------------------------------

def _ensure_app_superadmin(engine: Any) -> None:
    """Create the `app_superadmin` LOGIN role if it does not already exist.

    On real Cloud SQL this role is created out-of-band (`gcloud sql users
    create app_superadmin ...`); in the local/test container we create it in
    this fixture. Idempotent: guards against the duplicate-role error so a
    re-run of the session-scoped fixture (or a reused DSN) does not blow up.
    """
    from sqlalchemy import text

    with engine.begin() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_roles WHERE rolname = 'app_superadmin'")
        ).first()
        if exists is None:
            # DO block so concurrent CI sessions racing the CREATE both succeed.
            conn.execute(
                text(
                    "DO $$ BEGIN "
                    "  CREATE ROLE app_superadmin LOGIN; "
                    "EXCEPTION WHEN duplicate_object THEN NULL; "
                    "END $$;"
                )
            )


# ---------------------------------------------------------------------------
# Session-scoped engine fixture (sync pg8000) — builds schema via Alembic
# ---------------------------------------------------------------------------

def _owner_url(pg_container) -> str:
    """The engine DSN with the NON-superuser ``nestor_owner`` credentials.

    Derives host/port/db from the same source as `_sync_pg8000_url` and swaps in
    the bootstrap-created owner role. Exposed for suites that build their own
    engines (e.g. the pooled-connection Pitfall-1 regression test) — they MUST
    NOT use the superuser DSN or RLS is silently bypassed.
    """
    from sqlalchemy.engine import make_url

    url = make_url(_sync_pg8000_url(pg_container))
    return url.set(
        username=OWNER_ROLE, password=OWNER_PASSWORD
    ).render_as_string(hide_password=False)


def _bootstrap_non_superuser_owner(admin_engine: Any) -> None:
    """One-time superuser bootstrap: extensions + the non-superuser owner role.

    - Pre-creates pgcrypto/vector so 0001's ``CREATE EXTENSION IF NOT EXISTS``
      no-ops regardless of who runs the migrations.
    - Creates ``nestor_owner`` (LOGIN, CREATEDB, CREATEROLE, NOSUPERUSER) and
      makes it the database owner so it can create the ``nestor`` schema and
      the ``alembic_version`` table in ``public``.
    - ``createrole_self_grant = 'set, inherit'`` so roles the owner creates in
      tests (e.g. the WR-02 app role) can be assumed via ``SET ROLE``.
    Idempotent — safe on a reused DSN.
    """
    from sqlalchemy import text

    with admin_engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.execute(
            text(
                "DO $$ BEGIN "
                f"  CREATE ROLE {OWNER_ROLE} LOGIN PASSWORD '{OWNER_PASSWORD}' "
                "   CREATEDB CREATEROLE NOSUPERUSER; "
                "EXCEPTION WHEN duplicate_object THEN NULL; "
                "END $$;"
            )
        )
        conn.execute(
            text(
                f"ALTER ROLE {OWNER_ROLE} SET createrole_self_grant = 'set, inherit'"
            )
        )
        dbname = conn.execute(text("SELECT current_database()")).scalar_one()
        conn.execute(text(f'ALTER DATABASE "{dbname}" OWNER TO {OWNER_ROLE}'))


@pytest.fixture(scope="session")
def engine(pg_container):
    """Yield a sync SQLAlchemy engine bound to the pgvector container / DSN.

    The yielded engine authenticates as the NON-superuser ``nestor_owner`` (see
    OWNER_ROLE above) — the superuser DSN would bypass RLS and void every
    isolation assertion in the suite.

    Side effects (session-scoped, run once, as the container superuser):
      1. bootstrap extensions + the ``nestor_owner`` role (database owner),
      2. create the `app_superadmin` bypass role and grant it to the owner
         (so tests can ``SET LOCAL ROLE app_superadmin``),
      3. run `alembic upgrade head` AS THE OWNER to build the schema — the
         owner then owns every table, and FORCE RLS binds it (T-01-02).
    """
    sa = pytest.importorskip("sqlalchemy")
    from sqlalchemy import text

    admin_eng = sa.create_engine(
        _sync_pg8000_url(pg_container), echo=False, future=True, pool_pre_ping=True
    )
    try:
        _bootstrap_non_superuser_owner(admin_eng)
        _ensure_app_superadmin(admin_eng)
        with admin_eng.begin() as conn:
            # Membership (PG16 default WITH SET) lets the owner assume the role;
            # ADMIN OPTION lets the CREATEROLE owner ALTER it (e.g. the
            # superadmin_engine fixture sets a LOGIN password on it — PG16
            # requires CREATEROLE + ADMIN OPTION on the target role for that).
            conn.execute(
                text(f"GRANT app_superadmin TO {OWNER_ROLE} WITH ADMIN OPTION")
            )
    finally:
        admin_eng.dispose()

    eng = sa.create_engine(
        _owner_url(pg_container), echo=False, future=True, pool_pre_ping=True
    )
    try:
        _run_migrations(eng)
        yield eng
    finally:
        eng.dispose()


# ---------------------------------------------------------------------------
# Transaction-local GUC helper (canonical SET LOCAL pattern — Pitfall 1)
# ---------------------------------------------------------------------------

@pytest.fixture
def set_space():
    """Return a helper that sets `app.current_space_id` for the current tx.

    Mirrors `backend/app/db/rls.py::set_space_context` (plan 01-02):

        SELECT set_config('app.current_space_id', :sid, true)

    The third argument `true` makes the setting **transaction-local**
    (equivalent to `SET LOCAL`), NOT session-local. NEVER pass `false` — a
    session-scoped GUC leaks across pooled connections and is a catastrophic
    cross-tenant data leak (01-RESEARCH.md Pitfall 1).
    """
    from sqlalchemy import text

    def _set_space(conn_or_session: Any, space_id: Any) -> None:
        conn_or_session.execute(
            text("SELECT set_config('app.current_space_id', :sid, true)"),
            {"sid": str(space_id)},
        )

    return _set_space


# ---------------------------------------------------------------------------
# Two-space UUID pair for cross-tenant RLS tests
# ---------------------------------------------------------------------------

@pytest.fixture
def two_spaces():
    """Return a deterministic-per-call `(space_a, space_b)` UUID tuple.

    Distinct UUIDs so the cross-tenant denial test can prove space_b's rows
    are invisible to a session scoped to space_a.
    """
    return uuid.uuid4(), uuid.uuid4()


# ===========================================================================
# Phase 7 — AI external-call fakes (fake_anthropic / fake_openai)
# ===========================================================================
#
# These fixtures hand back STUB SDK clients so the AI contract suites can fake
# every Anthropic / OpenAI / Whisper call (no network, no keys, deterministic).
# Tests monkeypatch the client factory in ``app.ai.clients`` (e.g.
# ``app.ai.clients.anthropic_client`` / ``openai_client``) to return one of
# these stubs, then assert (1) the REQUEST shape recorded on ``.calls`` (model
# id, max_tokens, dimensions, response_format, language) and (2) the DB writes
# the handler made from the canned response.
#
# Design discipline (07-01 PLAN must_have): these fixtures import NOTHING from
# the not-yet-existing ``app.ai`` / ``app.db.ai_session`` modules, so conftest
# stays importable while the implementation (07-04..07-07) is still pending —
# only the test MODULES hard-import the impl (and stay RED until it lands).
# The stub classes use stdlib only and are defined at module scope so the
# fixtures can be parametrised per test.


class _FakeUsage:
    """Mirrors ``anthropic`` ``message.usage`` (typed token counts)."""

    def __init__(self, input_tokens: int, output_tokens: int) -> None:
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens


class _FakeContentBlock:
    """Mirrors one ``message.content[i]`` text block (``.text`` / ``.type``)."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.type = "text"


class _FakeMessage:
    """Mirrors the object ``Anthropic().messages.create(...)`` returns.

    Exposes ``.content[0].text`` (the raw model output the port parses) and
    ``.usage.input_tokens`` / ``.usage.output_tokens`` (cost/observability).
    """

    def __init__(self, text: str, input_tokens: int, output_tokens: int) -> None:
        self.content = [_FakeContentBlock(text)]
        self.usage = _FakeUsage(input_tokens, output_tokens)
        self.stop_reason = "end_turn"
        self.model = None  # set by _FakeMessages.create from the request kwargs


class _FakeMessages:
    """``client.messages`` namespace — records each ``create`` call's kwargs."""

    def __init__(self, parent: "_FakeAnthropicClient") -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeMessage:
        # Record the REQUEST shape for assertions (model, max_tokens, system, messages).
        self._parent.calls.append(kwargs)
        msg = _FakeMessage(
            self._parent.response_text,
            self._parent.input_tokens,
            self._parent.output_tokens,
        )
        msg.model = kwargs.get("model")
        return msg


class _FakeAnthropicClient:
    """A stand-in for ``anthropic.Anthropic`` with a controllable response.

    ``.calls`` is the list of kwargs each ``messages.create`` was called with —
    the contract suites assert ``calls[0]["model"] == "claude-sonnet-4-5"`` and
    ``calls[0]["max_tokens"] == 8192`` etc.
    """

    def __init__(self, response_text: str, input_tokens: int, output_tokens: int) -> None:
        self.response_text = response_text
        self.input_tokens = input_tokens
        self.output_tokens = output_tokens
        self.calls: list[dict[str, Any]] = []
        self.messages = _FakeMessages(self)


@pytest.fixture
def fake_anthropic():
    """Factory -> a stub ``anthropic.Anthropic`` client (no network).

    Usage::

        client = fake_anthropic('{"x": 1}', output_tokens=42)
        monkeypatch.setattr("app.ai.clients.anthropic_client", lambda: client)
        ...
        assert client.calls[0]["model"] == "claude-sonnet-4-5"
        assert client.calls[0]["max_tokens"] == 8192

    ``response_text`` is whatever the model "returns" — pass valid JSON to drive
    the success (``succeeded``) path, or a non-JSON string to drive the parse
    failure (``failed`` + ``error_message``) path. The returned object exposes
    ``.content[0].text`` and ``.usage.input_tokens`` / ``.usage.output_tokens``.
    """

    def _make(
        response_text: str = "{}",
        *,
        input_tokens: int = 120,
        output_tokens: int = 340,
    ) -> _FakeAnthropicClient:
        return _FakeAnthropicClient(response_text, input_tokens, output_tokens)

    return _make


class _FakeEmbeddingItem:
    """One ``response.data[i]`` row — exposes ``.embedding`` (list[float])."""

    def __init__(self, embedding: list[float]) -> None:
        self.embedding = embedding


class _FakeEmbeddingResponse:
    """Mirrors ``client.embeddings.create(...)`` -> ``.data[0].embedding``."""

    def __init__(self, embedding: list[float]) -> None:
        self.data = [_FakeEmbeddingItem(list(embedding))]


class _FakeEmbeddings:
    """``client.embeddings`` namespace — records each ``create`` call's kwargs."""

    def __init__(self, parent: "_FakeOpenAIClient") -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeEmbeddingResponse:
        # Record model + dimensions for the AI-04 request-shape assertion.
        self._parent.embedding_calls.append(kwargs)
        return _FakeEmbeddingResponse(self._parent.embedding)


class _FakeSegment:
    """One Whisper ``verbose_json`` segment (``.start`` / ``.end`` / ``.text``)."""

    def __init__(self, start: float, end: float, text: str) -> None:
        self.start = start
        self.end = end
        self.text = text


class _FakeTranscription:
    """Mirrors ``audio.transcriptions.create(...)`` (verbose_json) result.

    Exposes ``.text`` (full transcript), ``.language`` and ``.segments`` (the
    chunk boundaries the port maps into ``transcripts`` rows).
    """

    def __init__(self, text: str, language: str, segments: list) -> None:
        self.text = text
        self.language = language
        self.segments = [_FakeSegment(s, e, t) for (s, e, t) in segments]


class _FakeTranscriptions:
    """``client.audio.transcriptions`` namespace — records ``create`` kwargs."""

    def __init__(self, parent: "_FakeOpenAIClient") -> None:
        self._parent = parent

    def create(self, **kwargs: Any) -> _FakeTranscription:
        # Record model / response_format / language for AI-05 request-shape asserts.
        self._parent.transcription_calls.append(kwargs)
        return _FakeTranscription(
            self._parent.transcript_text,
            self._parent.transcript_language,
            self._parent.transcript_segments,
        )


class _FakeAudio:
    """``client.audio`` namespace -> ``.transcriptions.create``."""

    def __init__(self, parent: "_FakeOpenAIClient") -> None:
        self.transcriptions = _FakeTranscriptions(parent)


class _FakeOpenAIClient:
    """A stand-in for ``openai.OpenAI`` covering embeddings + Whisper.

    ``.embedding_calls`` / ``.transcription_calls`` capture request kwargs for
    the contract assertions (``dimensions == 1536``, ``model``,
    ``response_format == "verbose_json"``, ``language``).
    """

    def __init__(
        self,
        embedding: list[float],
        transcript_text: str,
        transcript_language: str,
        transcript_segments: list,
    ) -> None:
        self.embedding = list(embedding)
        self.transcript_text = transcript_text
        self.transcript_language = transcript_language
        self.transcript_segments = transcript_segments
        self.embedding_calls: list[dict[str, Any]] = []
        self.transcription_calls: list[dict[str, Any]] = []
        self.embeddings = _FakeEmbeddings(self)
        self.audio = _FakeAudio(self)


@pytest.fixture
def fake_openai():
    """Factory -> a stub ``openai.OpenAI`` client (embeddings + Whisper, no network).

    Usage::

        client = fake_openai()                         # default 1536-float vector
        monkeypatch.setattr("app.ai.clients.openai_client", lambda: client)
        ...
        assert client.embedding_calls[0]["dimensions"] == 1536
        assert client.transcription_calls[0]["response_format"] == "verbose_json"

    Defaults give a deterministic 1536-float embedding (matching
    ``text-embedding-3-small`` at ``dimensions=1536``) and a one-segment Dutch
    transcript so the chunking + space-scoped ``transcripts`` writes are testable
    without any real audio (AI-05; audio download is Phase 9 / D-08).
    """

    def _make(
        *,
        embedding: list[float] | None = None,
        transcript_text: str = "Dit is een test transcript.",
        transcript_language: str = "nl",
        transcript_segments: list | None = None,
    ) -> _FakeOpenAIClient:
        if embedding is None:
            # Deterministic, non-zero, length-1536 vector (text-embedding-3-small dims).
            embedding = [round(0.001 * ((i % 97) + 1), 6) for i in range(1536)]
        if transcript_segments is None:
            transcript_segments = [(0.0, 2.5, transcript_text)]
        return _FakeOpenAIClient(
            embedding, transcript_text, transcript_language, transcript_segments
        )

    return _make


# ===========================================================================
# Phase 7 — seed_artifact_embeddings: two-space vector seeding for AI-04 search
# ===========================================================================


@pytest.fixture
def seed_artifact_embeddings():
    """Return a helper that inserts ``artifact_embeddings`` rows for one space.

    Signature: ``_seed(conn_or_session, space_id, vectors)`` where ``vectors`` is
    a list of either ``embedding`` lists or ``(chunk_text, embedding)`` tuples.
    Each row carries ``space_id`` so the cross-tenant search suite can seed
    space-A and space-B and prove a space-A search returns ZERO space-B rows
    (AI-04 / T-7-01). Returns the inserted row ids.

    The caller MUST have set ``app.current_space_id`` (via the ``set_space``
    fixture) to ``space_id`` inside the SAME transaction first, so the 0002 RLS
    ``WITH CHECK`` on ``artifact_embeddings`` admits the INSERT — mirrors the
    GUC-then-INSERT shape of ``test_intake_cross_tenant._insert_intake``.

    The embedding is bound as a pgvector text literal (``[f1,f2,...]``) cast to
    ``vector`` — pg8000 has no native vector type, so the cast is explicit. Uses
    raw SQL (no ORM model import) to keep conftest free of app-model imports.
    """
    from sqlalchemy import text

    def _seed(conn_or_session: Any, space_id: Any, vectors: Any) -> list[str]:
        ids: list[str] = []
        for index, item in enumerate(vectors):
            if isinstance(item, tuple):
                chunk_text, vec = item
            else:
                chunk_text, vec = f"chunk-{index}", item
            vec_literal = "[" + ",".join(str(float(x)) for x in vec) + "]"
            row = conn_or_session.execute(
                text(
                    "INSERT INTO nestor.artifact_embeddings "
                    "(id, space_id, chunk_text, embedding) "
                    "VALUES (gen_random_uuid(), :space_id, :chunk_text, "
                    "CAST(:embedding AS vector)) RETURNING id"
                ),
                {
                    "space_id": str(space_id),
                    "chunk_text": chunk_text,
                    "embedding": vec_literal,
                },
            ).first()
            if row is not None:
                ids.append(str(row[0]))
        return ids

    return _seed


# ===========================================================================
# Phase 9 — fake_gcs: the app.storage.gcs seam faked (no bucket, no network)
# ===========================================================================
#
# Clones the fake_openai / fake_anthropic discipline for the GCS seam: the
# storage suites monkeypatch ALL FOUR seam functions —
# ``app.storage.gcs.upload_object`` / ``app.storage.gcs.signed_download_url`` /
# ``app.storage.gcs.delete_object`` / ``app.storage.gcs.download_bytes`` —
# with capture-only fakes, so no storage test ever reaches a real bucket or
# constructs SDK credentials. The fixture imports ``app.storage.gcs`` LAZILY
# (importorskip inside the fixture body), so conftest itself stays importable
# on a box without google-cloud-storage installed.


@pytest.fixture
def fake_gcs(monkeypatch):
    """Monkeypatch the four ``app.storage.gcs`` seam functions; return the capture dict.

    Usage::

        def test_x(fake_gcs, ...):
            ...  # drive an endpoint that uploads
            assert fake_gcs["uploads"][0]["key"].startswith(f"{space}/{intake}/")

    Captures (one list per seam function, append-per-call):

    - ``uploads``:      {key, data, content_type}
    - ``signed_urls``:  {key, ttl_seconds, filename, content_type, disposition}
    - ``deletes``:      {key}
    - ``downloads``:    {key}

    The signed-url fake returns a deterministic ``https://signed.example/{key}``
    and records the ``ttl_seconds`` + ``filename`` it was called with;
    ``disposition`` records the attachment header the real seam would emit.
    Both the ``app.storage.gcs`` module attributes AND the ``app.storage``
    package-level re-exports are patched, so a consumer that bound either name
    is intercepted.
    """
    gcs_mod = pytest.importorskip("app.storage.gcs")
    storage_pkg = pytest.importorskip("app.storage")

    calls: dict[str, list[dict[str, Any]]] = {
        "uploads": [],
        "signed_urls": [],
        "deletes": [],
        "downloads": [],
    }

    def _fake_upload(key: str, data: bytes, content_type: str | None = None) -> None:
        calls["uploads"].append(
            {"key": key, "data": data, "content_type": content_type}
        )

    def _fake_signed_url(
        key: str,
        *,
        ttl_seconds: int,
        filename: str,
        content_type: str | None = None,
    ) -> str:
        calls["signed_urls"].append(
            {
                "key": key,
                "ttl_seconds": ttl_seconds,
                "filename": filename,
                "content_type": content_type,
                # WR-07: the fake does NOT fabricate a `disposition` — the forced-download
                # (attachment) invariant is emitted INSIDE the real seam and is pinned by a
                # dedicated unit test (test_storage_signed_url.py::test_seam_forces_
                # attachment_disposition), not by anything this fake makes up.
            }
        )
        return f"https://signed.example/{key}"

    def _fake_delete(key: str) -> None:
        calls["deletes"].append({"key": key})

    def _fake_download(key: str) -> bytes:
        calls["downloads"].append({"key": key})
        return b"\x00\x01fake-gcs-bytes"

    for name, fake in (
        ("upload_object", _fake_upload),
        ("signed_download_url", _fake_signed_url),
        ("delete_object", _fake_delete),
        ("download_bytes", _fake_download),
    ):
        monkeypatch.setattr(gcs_mod, name, fake)
        # Package-level re-exports bind the ORIGINAL function objects — patch
        # them too so `from app.storage import download_bytes` consumers are
        # intercepted as well (raising=False: tolerate a slimmed __init__).
        monkeypatch.setattr(storage_pkg, name, fake, raising=False)

    return calls


# ===========================================================================
# Phase 10 — fake_resend: the app.mail.resend.send seam faked (no network)
# ===========================================================================
#
# Clones the fake_gcs / fake_anthropic discipline for the mail-egress seam: the
# notification suites monkeypatch ``app.mail.resend.send`` with a capture-only
# fake, so no test ever reaches the real Resend API or reads RESEND_API_KEY. The
# fixture imports ``app.mail.resend`` LAZILY (importorskip inside the fixture
# body), so conftest itself stays importable on a box without jinja2/httpx
# installed. Plan 03's send-endpoint tests reuse this fixture.


@pytest.fixture
def fake_resend(monkeypatch):
    """Monkeypatch ``app.mail.resend.send``; return the capture dict.

    Usage::

        def test_x(fake_resend, ...):
            ...  # drive an endpoint that sends a mail
            assert fake_resend["calls"][0]["subject"].startswith("Even valideren")

    Captures (append-per-call to ``calls``): ``{to, subject, html}``. The fake
    returns a deterministic ``"fake-resend-id"`` and performs NO network I/O.
    Both the ``app.mail.resend`` module attribute AND any ``app.mail``
    package-level re-export are patched (raising=False), so a consumer that bound
    either name is intercepted.
    """
    resend_mod = pytest.importorskip("app.mail.resend")
    mail_pkg = pytest.importorskip("app.mail")

    calls: dict[str, list[dict[str, Any]]] = {"calls": []}

    def _fake_send(*, to: list[str], subject: str, html: str) -> str:
        calls["calls"].append({"to": to, "subject": subject, "html": html})
        return "fake-resend-id"

    monkeypatch.setattr(resend_mod, "send", _fake_send)
    # Package-level re-export (if app.mail ever re-exports send) binds the
    # ORIGINAL function object — patch it too (raising=False: tolerate a slim
    # __init__ that does not re-export send).
    monkeypatch.setattr(mail_pkg, "send", _fake_send, raising=False)

    return calls


# ===========================================================================
# Phase 16 — fake_tribunal_client: the internal Tribunal seam faked (no network)
# ===========================================================================
#
# Clones the fake_resend discipline for the Tribunal integration seam: the
# Phase-16 trigger/poll/stream suites monkeypatch the ``app.research.tribunal_client``
# call surface with capture-only fakes, so NO test ever reaches the real internal
# Tribunal API (no OIDC mint, no httpx.post). The fixture imports the seam module
# LAZILY (``importorskip`` inside the body), so conftest itself stays importable on
# a box without httpx/google-auth installed.
#
# Seam surface faked:
#   - create_run / get_metrics / get_report — the Phase-16 run lifecycle methods.
#     These DO NOT EXIST on the module yet (Plan 02 adds them); the fixture patches
#     them by NAME against the agreed signatures with ``raising=False`` so it is
#     written now and simply attaches the fakes when the real methods land.
#   - ensure_org / ensure_project — the Phase-14 provisioning methods that DO exist.
#
# Metrics scripting: ``get_metrics`` walks a status sequence ending in a terminal
# state. The DEFAULT script ends in ``completed``; a failure-path test overrides
# ``capture["metrics_script"]`` (e.g. to end in ``failed``) BEFORE driving the poll
# so the same fixture drives both the happy and the failure terminal (D-05 verbatim
# literals — ``completed`` / ``failed``, never the skill-run ``succeeded``).


@pytest.fixture
def fake_tribunal_client(monkeypatch):
    """Monkeypatch ``app.research.tribunal_client``'s seam surface; return the capture dict.

    Usage::

        def test_trigger(fake_tribunal_client, ...):
            ...  # drive the run-trigger endpoint
            assert fake_tribunal_client["create_run"][0]["brief"]

        def test_failure(fake_tribunal_client, ...):
            fake_tribunal_client["metrics_script"] = [
                {"status": "running"}, {"status": "failed"},
            ]
            ...  # drive the poll -> asserts the failed terminal is mirrored

    Captures:
      - ``create_run``: list of ``{brief, idempotency_key, project_id}`` per call.
      - ``get_metrics_calls``: int count of poll calls served.
      - ``metrics_script``: the OVERRIDABLE status sequence get_metrics walks; the
        LAST entry is returned once the script is exhausted (so a terminal state
        sticks). Defaults to ``running`` -> ``completed``.

    The fakes perform NO network I/O and mint NO token. ``create_run`` returns the
    Tribunal-verbatim ``{"id": "fake-run-id", "status": "queued"}``; ``get_report``
    returns ``{"markdown": "fake report", "sources": []}``; ``ensure_org`` returns
    None; ``ensure_project`` returns ``"fake-project-id"``.
    """
    tc = pytest.importorskip("app.research.tribunal_client")

    capture: dict[str, Any] = {
        "create_run": [],
        "get_metrics_calls": 0,
        # Default happy path: one running poll then the completed terminal. A
        # failure-path test reassigns this list BEFORE driving the poll.
        "metrics_script": [
            {"status": "running", "current_stage": "delegation"},
            {"status": "completed", "current_stage": "report"},
        ],
    }

    def _fake_create_run(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Accept the agreed keyword surface without pinning to a not-yet-final
        # signature — record the load-bearing fields the trigger passes.
        capture["create_run"].append(
            {
                "brief": kwargs.get("brief"),
                "idempotency_key": kwargs.get("idempotency_key"),
                "project_id": kwargs.get("project_id"),
            }
        )
        return {"id": "fake-run-id", "status": "queued"}

    def _fake_get_metrics(*args: Any, **kwargs: Any) -> dict[str, Any]:
        # Walk the script; once exhausted, keep returning the terminal entry so a
        # completed/failed state sticks across further polls.
        script = capture["metrics_script"]
        idx = min(capture["get_metrics_calls"], len(script) - 1)
        capture["get_metrics_calls"] += 1
        return dict(script[idx])

    def _fake_get_report(*args: Any, **kwargs: Any) -> dict[str, Any]:
        return {"markdown": "fake report", "sources": []}

    def _fake_ensure_org(*args: Any, **kwargs: Any) -> None:
        return None

    def _fake_ensure_project(*args: Any, **kwargs: Any) -> str:
        return "fake-project-id"

    # create_run / get_metrics / get_report do NOT exist on the module until Plan
    # 02 — patch with raising=False so this fixture is written now and binds the
    # fakes once the real methods land. ensure_org / ensure_project already exist.
    for name, fake in (
        ("create_run", _fake_create_run),
        ("get_metrics", _fake_get_metrics),
        ("get_report", _fake_get_report),
        ("ensure_org", _fake_ensure_org),
        ("ensure_project", _fake_ensure_project),
    ):
        monkeypatch.setattr(tc, name, fake, raising=False)

    return capture
