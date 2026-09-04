"""``app/db/ai_session.py`` — THE correctness core of Phase 7 (D-05 / AI-06).

The seven AI functions (apply-intake-skill, generate-context-pack, extract-insights,
generate-embeddings, embed-artifact, transcribe-audio, semantic-search) all run a long
external LLM/embedding/transcription call between a READ and a WRITE. Two failure modes
this module exists to make impossible:

* **T-7-06 (pool starvation):** holding a pooled DB connection across the ~120s external
  call would starve the bounded pool (``pool_size=2, overflow=3``). So
  :func:`run_with_session_release` does READ (load plain DTOs, close the tx → connection
  returns to the pool) → CALL (NO connection held) → WRITE (a FRESH transaction).
* **T-7-02 (forgotten 2nd-session GUC):** the ``app.current_space_id`` GUC is
  transaction-local (``SET LOCAL``) and evaporates at COMMIT. The WRITE session is a
  brand-new transaction, so it MUST re-issue the GUC. Routing the write through
  :func:`tenant_session` — which ALWAYS calls :func:`app.db.rls.set_space_context` on the
  user path — makes forgetting it structurally impossible. ``test_ai_session_release``
  proves ``set_space_context`` is called EXACTLY twice for one user AI run.

Engine/scope routing mirrors ``app/db/session.py:58-78`` verbatim (D-05 two-engine
routing keyed on ``Identity.role``), differing ONLY in that :func:`tenant_session` is a
reusable ``@contextmanager`` usable OUTSIDE a request (the background task uses it) and
raises ``PermissionError`` (not ``HTTPException``) on the null-space default-deny case.

Driver note: pg8000 is blocking, so EVERYTHING here is sync ``def`` (Pitfall 5). A
coroutine calling the sync engine would stall the event loop, so none are used.

``get_engine`` / ``set_space_context`` are imported into THIS module's namespace so the
integration tests can ``monkeypatch.setattr(ai_session, "get_engine", ...)`` / spy on
``set_space_context`` at the call site.
"""

from __future__ import annotations

import uuid
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterator

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.identity import Identity
from app.db.base import get_engine, get_sessionmaker, get_superadmin_engine
from app.db.models.embeddings import ArtifactEmbedding
from app.db.models.research import ResearchArtifact
from app.db.models.skill_run import SkillRun
from app.db.repository import IntakeRepository, SkillRunRepository
from app.db.rls import set_space_context


class IntakeNotInScopeError(LookupError):
    """The intake id is missing or owned by another space (route → 404, D-07).

    Raised by :func:`create_running_skill_run` when the caller's scoped
    :meth:`IntakeRepository.get` returns ``None``. Mirrors the repo's existence-hiding
    contract: never leak existence, never raise the auth-layer 403 — the route maps this
    to a 404 (403 is reserved for the null-space default-deny, which surfaces as
    ``PermissionError`` from :func:`tenant_session`).
    """


#: The partial unique index migration 0014 creates:
#: ``UNIQUE (intake_id, skill) WHERE status = 'running'``. Named here so the ``except``
#: below can tell OUR violation from any other integrity problem. The literal is repeated
#: in ``app/db/models/skill_run.py``'s ``__table_args__`` and in the migration; ``alembic
#: check`` is what keeps those two in step, and ``tests/test_ai_dedup.py`` pins all three.
_ONE_RUNNING_INDEX = "uq_skill_runs_one_running_per_intake_skill"


class ActiveSkillRunExistsError(RuntimeError):
    """A run of this skill is already in flight for this intake (route → 409, D-23.1-04).

    Raised by :func:`create_running_skill_run` when the INSERT trips migration 0014's
    partial unique index. Carries the ``skill`` so ``ai_routes._dispatch_skill_run`` can
    build a readable sentence without re-deriving it — and so the DRIVER's message, which
    names the index and the SQLSTATE, never has to be shown to anyone (T-23.1-51).

    Deliberately NOT a pre-check. D-23.1-04 rejects "is one already running?" by name: two
    concurrent dispatches both read "no" and both insert, and the operator pays for two
    Claude generations. The database serializes the inserts; this exception is only the
    translation of its refusal.
    """

    def __init__(self, skill: str) -> None:
        super().__init__(f"a run of {skill!r} is already in progress for this intake")
        self.skill = skill


def _is_one_running_violation(exc: IntegrityError) -> bool:
    """True only for a 0014 unique violation — never for any OTHER integrity error.

    Scoped on purpose: a genuine FK violation (an intake deleted between the scope check
    and the insert, say) or a NOT NULL violation must surface as itself, not be reported
    to the operator as "already running" (T-23.1-53). The discriminator is the CONSTRAINT
    NAME, which is exact.

    pg8000 — the driver in both the test container and Cloud Run — hands the server's
    error fields back as a dict in ``exc.orig.args[0]``, where ``"n"`` is the constraint
    name and ``"C"`` the SQLSTATE. A driver that reports no structured fields falls
    through to a substring check on the rendered message, which is weaker but never
    broader: it still requires the index name to appear.
    """
    orig = getattr(exc, "orig", None)
    for arg in getattr(orig, "args", ()) or ():
        if isinstance(arg, dict):
            if arg.get("n") == _ONE_RUNNING_INDEX:
                return True
            if arg.get("C") == "23505" and _ONE_RUNNING_INDEX in str(arg.get("M", "")):
                return True
    return _ONE_RUNNING_INDEX in str(orig)


def _engine_and_space(identity: Identity) -> tuple[Any, Any]:
    """Reproduce ``app/db/session.py:58-78`` engine-by-role routing (D-05 / D-04).

    * ``superadmin`` → the ``app_superadmin`` engine + ``space_id=None`` (the 0003 bypass
      is current_user-based, so NO GUC is set — Pitfall 2).
    * ``user`` with a null/empty ``space_id`` → ``PermissionError`` (default-deny, D-04):
      an unset GUC must never reach a query. This is the request-time 403 expressed as an
      exception usable outside a request (the bg task).
    * ``user`` → the app-role engine + ``identity.space_id`` (RLS-scoped via the GUC).
    """
    if identity.role == "superadmin":
        return get_superadmin_engine(), None
    if not identity.space_id:
        raise PermissionError("No space — not authorized")
    return get_engine(), identity.space_id


@contextmanager
def tenant_session(identity: Identity) -> Iterator[Session]:
    """Open ONE tenant-scoped transaction and re-issue the GUC on EVERY entry.

    A reusable ``@contextmanager`` (the bg task opens it twice per AI run — read + write).
    Picks the engine/space via :func:`_engine_and_space`, opens ``maker.begin()`` (ONE tx;
    commit/rollback + connection return guaranteed on exit), and — for the user path
    (``space_id is not None``) — calls :func:`set_space_context` so the transaction-local
    ``app.current_space_id`` is set BEFORE any tenant query. The superadmin path sets NO
    GUC. The connection returns to the pool the instant this block exits.
    """
    engine, space_id = _engine_and_space(identity)
    maker = get_sessionmaker(engine)
    with maker.begin() as session:  # ONE tx; commit + conn return on exit
        if space_id is not None:
            # SET LOCAL (tx-local, reverts at COMMIT) — re-issued on every entry.
            set_space_context(session, space_id)
        yield session


def run_with_session_release(
    identity: Identity,
    read_fn: Callable[[Session], Any],
    call_fn: Callable[[Any], Any],
    write_fn: Callable[[Session, Any, Any], Any],
    *,
    on_error: Callable[[Session, Any, Exception], Any] | None = None,
) -> Any:
    """READ → release → CALL → reopen-WRITE — the AI-06 connection-release contract.

    Phase 1 (READ): open :func:`tenant_session`, ``dto = read_fn(session)``. ``read_fn``
    MUST return PLAIN data (dict/dataclass), NEVER live ORM rows — a row from session #1 is
    detached in session #2 (``DetachedInstanceError``). The tx commits/closes on block exit,
    returning the connection to the pool.

    Phase 2 (CALL): ``result = call_fn(dto)`` runs with NO DB connection held — the
    bounded pool is free across the long external call (T-7-06). ``engine.pool.checkedout()``
    is 0 here.

    Phase 3 (WRITE): a FRESH :func:`tenant_session` re-issues the GUC structurally (the
    marquee 2nd-session ``set_space_context`` — T-7-02) and returns ``write_fn(session,
    dto, result)``.

    ``on_error`` (D-09 terminal-status guard): FastAPI ``BackgroundTasks`` swallows an
    exception that escapes the task, which would leave the ``skill_runs`` row stuck at
    ``running`` until the next startup sweep. When ``on_error`` is provided, ANY exception
    raised by read/call/write is routed to ``on_error(session, dto, exc)`` inside a fresh
    :func:`tenant_session` so the caller can finalize the run row to EXACTLY ``failed``
    (with ``error_message``) — the contract the frontend polls. ``dto`` is ``None`` when
    the READ phase itself raised. Without ``on_error`` the exception re-raises unchanged.
    """
    dto: Any = None
    try:
        # Phase 1 — READ: load plain DTOs, then release the connection on block exit.
        with tenant_session(identity) as session:
            dto = read_fn(session)

        # Phase 2 — CALL: no DB connection held across the external call (AI-06 / T-7-06).
        result = call_fn(dto)

        # Phase 3 — WRITE: a fresh tx; tenant_session re-issues the GUC (T-7-02).
        with tenant_session(identity) as session:
            return write_fn(session, dto, result)
    except Exception as exc:  # noqa: BLE001 — finalize the run as failed (D-09)
        if on_error is None:
            raise
        # A fresh tx (the failed write tx rolled back on block exit); tenant_session
        # re-issues the GUC so the failed-finalize patch is space-scoped like any write.
        with tenant_session(identity) as session:
            return on_error(session, dto, exc)


def create_running_skill_run(
    identity: Identity,
    intake_id: Any,
    skill: str,
    llm_model: str | None,
    prompt_system: str | None = None,
    prompt_user: str | None = None,
) -> Any:
    """Insert ONE ``skill_runs`` row (status=running) in a short tx; return its id.

    The synchronous step the AI endpoint performs BEFORE scheduling the background task:
    it verifies the intake is in the caller's scope (a scoped :meth:`IntakeRepository.get`
    returning ``None`` → :class:`IntakeNotInScopeError`, so the route returns 404 for a
    cross-tenant/missing id — D-07), inserts the ``running`` row (D-09 status literal), and
    returns the id BEFORE the route responds 202. The connection is released the moment this
    block exits — nothing is held while the bg task runs.

    ``space_id`` is identity-derived via the repo (TENANT-02): the user path uses
    :meth:`TenantRepository.create` (space from the verified Identity); the superadmin path
    (no own space) uses :meth:`create_in_space` against the intake's OWN space.

    THIRD outcome (COST-01 / D-23.1-04): if a run of this skill is ALREADY ``running`` for
    this intake, migration 0014's partial unique index refuses the insert and this raises
    :class:`ActiveSkillRunExistsError` -> the route returns ``409``. The check is the
    DATABASE's, never this function's: an app-level "is one already running?" query races,
    and the two racing inserts are two paid Claude generations. The refused transaction
    rolls back on the ``with`` block's exit, so no half-written row and no poisoned session
    survive (the session is never reused after the failed flush).
    """
    with tenant_session(identity) as session:
        intake = IntakeRepository(session, identity).get(intake_id)
        if intake is None:
            raise IntakeNotInScopeError(str(intake_id))

        run_repo = SkillRunRepository(session, identity)
        values = dict(
            intake_id=intake_id,
            skill=skill,
            status="running",  # D-09 lifecycle literal
            llm_model=llm_model,
            prompt_system=prompt_system,
            prompt_user=prompt_user,
        )
        # create()/create_in_space() FLUSH to populate the server-side id — which is
        # exactly where migration 0014's partial unique index fires. The try wraps ONLY
        # the insert+flush: everything above it (the scope check) has its own error, and
        # nothing below it can raise an IntegrityError.
        try:
            if identity.role == "superadmin":
                # No own space — write into the intake's space (audited superadmin path).
                run = run_repo.create_in_space(intake.space_id, **values)
            else:
                run = run_repo.create(**values)  # space_id injected from Identity
        except IntegrityError as exc:
            if not _is_one_running_violation(exc):
                # Some OTHER integrity problem (FK, NOT NULL, ...). Do NOT dress it up as
                # "already running" — that would hide a real defect behind a 409.
                raise
            raise ActiveSkillRunExistsError(skill) from exc
        return run.id


def sweep_orphaned_skill_runs(max_age_minutes: int = 30) -> int:
    """Startup self-heal: mark stale ``running`` rows ``failed`` (D-01a backstop).

    A Cloud Run instance can die mid-run (restart/scale-in/crash), leaving a
    ``skill_runs`` row stuck at ``running`` forever — the accepted limitation D-01a. On
    startup this runs ONE cheap UPDATE on the superadmin engine (cross-space reach, no
    GUC) flipping every ``running`` row older than ``max_age_minutes`` to ``failed`` with
    an explanatory ``error_message``. Returns the number of rows swept.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
    engine = get_superadmin_engine()
    maker = get_sessionmaker(engine)
    with maker.begin() as session:
        result = session.execute(
            update(SkillRun)
            .where(SkillRun.status == "running")
            .where(SkillRun.created_at < cutoff)
            .values(status="failed", error_message="orphaned by restart")
        )
        return result.rowcount


def search_artifacts(
    session: Session,
    query_vec: Any,
    *,
    intake_id: Any | None = None,
    limit: int = 25,
    max_distance: float | None = None,
):
    """Space-confined EXACT cosine (``<=>``) scan over ``artifact_embeddings`` (AI-04 / D-03).

    Takes a READY ``query_vec`` (the query-text embedding lives in ``app/ai/search.py``,
    07-06) and the caller's tenant-scoped ``session`` (opened via :func:`tenant_session`).
    Builds ``ORDER BY embedding <=> :query_vec LIMIT :limit`` over the pgvector cosine
    operator (:meth:`ArtifactEmbedding.embedding.cosine_distance`).

    ``intake_id`` (optional) narrows the scan to ONE intake's artifacts — legacy
    ``match_intake_content`` parity. ``artifact_embeddings`` carries no ``intake_id``
    column, so the predicate goes through the owning ``research_artifacts`` row
    (``artifact_id IN (SELECT id FROM research_artifacts WHERE intake_id = ...)``),
    itself RLS/space-confined on the same session. This is an INTAKE filter within the
    caller's space — tenant confinement stays with RLS + the GUC (below), unchanged.

    Tenant confinement is NOT a manual ``WHERE space_id`` here: on the user engine the 0002
    RLS policy + the GUC set by :func:`tenant_session` prefilter the scan to the caller's
    space (the predicate ``test_ai_search_explain`` looks for, and the zero-foreign-rows
    guarantee ``test_ai_search_cross_tenant`` proves). The space-leading btree index
    (``ix_artifact_embeddings_space_id``) supplies the prefilter — there is deliberately NO
    approximate-nearest-neighbour vector index this phase (D-03): exact ``<=>`` over the
    small per-tenant set is correct and cheap on an empty/near-empty table.

    ``max_distance`` (default ``None``) optionally drops rows past a distance threshold —
    the legacy 0.7-cosine-similarity cutoff maps to distance ``0.3`` (``distance = 1 −
    similarity``); param/config-driven so the default keeps every nearest row. Returns plain
    SQLAlchemy ``Row`` tuples (``id, artifact_id, chunk_text, distance``) — no live ORM rows
    to detach across sessions.
    """
    distance = ArtifactEmbedding.embedding.cosine_distance(query_vec)
    stmt = (
        select(
            ArtifactEmbedding.id,
            ArtifactEmbedding.artifact_id,
            ArtifactEmbedding.chunk_text,
            distance.label("distance"),
        )
        .order_by(distance)
        .limit(limit)
    )
    if intake_id is not None:
        # Per-intake narrowing (legacy match_intake_content parity, WR-02): the
        # embeddings row links to its intake via the owning research_artifacts row.
        stmt = stmt.where(
            ArtifactEmbedding.artifact_id.in_(
                select(ResearchArtifact.id).where(
                    ResearchArtifact.intake_id == uuid.UUID(str(intake_id))
                )
            )
        )
    if max_distance is not None:
        stmt = stmt.where(distance <= max_distance)
    return session.execute(stmt).all()
