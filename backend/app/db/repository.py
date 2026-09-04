"""Generic always-filter ``TenantRepository`` — the single tenant data-access seam.

This is the un-omittable repository layer (API-02): every read/write over a
tenant-owned table goes through a :class:`TenantRepository` subclass, which composes
an EXPLICIT ``WHERE space_id = <identity.space_id>`` for ``user`` requests. The
``space_id`` is taken ONLY from the verified :class:`app.auth.identity.Identity`,
NEVER from a method/handler argument — a repo method that accepted ``space_id`` would
reopen the exact "trust the client's tenant" hole this phase exists to kill
(TENANT-02 / D-01). There is no ``space_id`` parameter anywhere in this module.

Locked decisions realized here (04-CONTEXT.md / 04-RESEARCH.md):

* D-01 — belt-and-suspenders with RLS: the explicit ``WHERE`` excludes a foreign row
  INDEPENDENTLY of RLS. Even if the GUC were somehow wrong, the repo ``WHERE`` still
  filters; even if the ``WHERE`` were dropped, 0002's policy still denies. The
  ``where_filter`` test proves the repo wall on its own (RESEARCH Q3).
* D-05 — superadmin: ``identity.role == "superadmin"`` ⇒ ``_scope`` returns the
  statement UNCHANGED. Cross-tenant reach is the ``app_superadmin`` DB role + the 0003
  bypass policy (selected via the second engine in ``app/db/session.py``), NOT an
  app-layer filter and NOT a GUC (Pitfall 2).
* D-07 — existence hiding: ``get()`` returns ``None`` and ``patch()`` returns
  ``rowcount == 0`` for a cross-tenant id. The repo NEVER raises and NEVER leaks
  existence; the HTTP handler maps None/0 to a 404 (403 is reserved for the
  auth-layer / null-space denial — D-04).
* Pitfall 6 — ``Identity.space_id`` is a ``str`` but ``Intake.space_id`` is
  ``UUID(as_uuid=True)``; coerce to ``uuid.UUID(identity.space_id)`` so the pg8000
  bind/compare is unambiguous (a silently-broken coercion is caught by ``where_filter``).

The space_id-comes-only-from-Identity invariant (no method arg) is asserted by the
plan's AST/grep acceptance check and the threat register (T-04-05).
"""

from __future__ import annotations

import uuid
from typing import Generic, TypeVar

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.db.rls import set_space_context

from app.auth.identity import Identity
from app.db.base import Base
from app.db.models.intake import Intake, IntakeAnswer, IntakeTemplate
from app.db.models.research import ResearchArtifact
from app.db.models.research_runs import ResearchRun
from app.db.models.skill_run import SkillRun
from app.db.models.sources import IntakeSource
from app.db.models.transcripts import Transcript
from app.db.models.insights import ExtractedInsight
from app.db.models.embeddings import ArtifactEmbedding

M = TypeVar("M", bound=Base)


class TenantRepository(Generic[M]):
    """Base repository bound to a per-request ``Session`` + the request ``Identity``.

    Subclasses set ``model`` (e.g. :class:`IntakeRepository`). Every query is routed
    through :meth:`_scope`, which applies the explicit space filter for ``user`` and
    omits it for ``superadmin``. The ``space_id`` is derived ONLY from the injected
    ``Identity`` — there is deliberately no ``space_id`` method parameter (TENANT-02).
    """

    model: type[M]  # set by subclass (e.g. Intake)

    def __init__(self, session: Session, identity: Identity) -> None:
        self._s = session
        self._identity = identity
        self._is_super = identity.role == "superadmin"
        # space_id is ALWAYS from the verified Identity, NEVER a method arg (TENANT-02).
        # Coerce str -> uuid.UUID for the explicit WHERE (pg8000, Pitfall 6). For a
        # superadmin (space_id is None) there is no filter, so the coercion is skipped.
        self._space_id: uuid.UUID | None = (
            None if identity.space_id is None else uuid.UUID(identity.space_id)
        )

    def _scope(self, stmt):
        """Apply the tenant filter unless the identity is a superadmin.

        superadmin: return ``stmt`` unchanged — the 0003 bypass policy (matched by the
        ``app_superadmin`` connection) handles cross-tenant reach (D-05 / Pitfall 2).
        user: ``stmt.where(model.space_id == self._space_id)`` — the un-omittable wall
        (D-01). Callers never reach the raw statement, only these methods.
        """
        if self._is_super:
            return stmt
        return stmt.where(self.model.space_id == self._space_id)

    def list(self):
        """Return all rows visible to this identity (own space only for a user)."""
        return self._s.execute(self._scope(select(self.model))).scalars().all()

    def get(self, row_id):
        """Return the row by id within scope, or ``None`` (handler → 404, D-07)."""
        stmt = self._scope(select(self.model).where(self.model.id == row_id))
        return self._s.execute(stmt).scalar_one_or_none()

    def patch(self, row_id, **values):
        """Update the in-scope row by id; return rowcount (0 → handler 404, D-07).

        Never raises and never leaks existence: a cross-tenant ``row_id`` matches the
        scoped ``WHERE`` against nothing, so ``rowcount == 0`` and the foreign row is
        left untouched.
        """
        stmt = self._scope(update(self.model).where(self.model.id == row_id)).values(
            **values
        )
        # synchronize_session="fetch": the default "evaluate" strategy compares the
        # str path-param row_id against the UUID attribute in Python (always False),
        # so an already-loaded instance is NOT synced and a follow-up get() returns
        # stale attributes (e.g. /submit responding with the pre-transition status).
        result = self._s.execute(
            stmt, execution_options={"synchronize_session": "fetch"}
        )
        return result.rowcount

    def patch_if(self, row_id, expected: dict, **values):
        """Conditional twin of :meth:`patch` — update by id ONLY IF the row still
        matches ``expected``; return rowcount (D-23.1-05 compare-and-swap).

        The whole point is that the DATABASE does the comparison: the precondition
        rides in the same ``UPDATE`` statement's ``WHERE``, so there is no window
        between a read and a write for a concurrent transaction to slip through.
        A ``get()`` followed by a ``patch()`` — even inside one transaction — is
        still read-then-write under READ COMMITTED and does NOT give this guarantee.

        ``expected`` is an explicit dict, NOT keyword arguments, precisely because the
        predicate dict and the value dict are the same shape: taking both as ``**kwargs``
        would let a caller send a column into the SET clause that they meant as a
        precondition, silently and unrecoverably.

        Three notes for callers:

        * ``rowcount == 0`` means "the precondition did not hold" — which is
          INDISTINGUISHABLE here from "the row does not exist" and from "the row belongs
          to another space". All three are 0 by design (existence hiding, D-07). A caller
          that must tell them apart has to re-read; no caller in phase 23.1 does, and the
          re-read must never become the precondition.
        * The tenant scope is applied FIRST (``_scope``) and the ``expected`` predicates
          are ANDed onto it. Adding predicates can only narrow the match, never widen it,
          so the TENANT-02 wall is not weakened (T-23.1-15 — asserted by the cross-tenant
          rowcount-0 case in ``test_ai_context_pack_cas.py``).
        * ``synchronize_session="fetch"`` is copied from :meth:`patch` for the same
          reason: the default "evaluate" strategy compares a str ``row_id`` against the
          UUID attribute in Python, never matches, and leaves an already-loaded instance
          unsynced so a follow-up ``get()`` returns stale attributes.
        """
        stmt = self._scope(update(self.model).where(self.model.id == row_id))
        for column, value in expected.items():
            stmt = stmt.where(getattr(self.model, column) == value)
        stmt = stmt.values(**values)
        result = self._s.execute(
            stmt, execution_options={"synchronize_session": "fetch"}
        )
        return result.rowcount

    @property
    def session(self) -> Session:
        """The request's bound ``Session`` — the user-path audit-write target (Pitfall 2).

        Mirrors :attr:`app.db.admin_repo.AdminRepo.session` verbatim. Exposed so a
        user-path status-transition handler can pass the SAME session to
        :func:`app.db.audit.log`, keeping the ``audit_log`` row inside the action's ONE
        transaction (D-02). The base — not only ``AdminRepo`` — must own this so the
        tenant (user) path can audit too. This is the request session, NOT a new
        engine/session, so the no-raw-DB grep-guard stays green.
        """
        return self._s

    def create(self, **values):
        """Insert one row in this identity's space and return it (user-path create).

        ``space_id`` is injected from the verified ``Identity`` (``self._space_id``) ONLY
        — it is NEVER accepted as a method kwarg (TENANT-02 / D-03 / T-06-01). For a
        ``user`` (``self._space_id is not None``) the tenant key is forced onto the row;
        a superadmin create (``self._space_id is None``) is out of scope for the tenant
        seam and goes through :meth:`create_in_space` against a chosen target space (or
        :class:`app.db.admin_repo.AdminRepo` — Pitfall 3). A superadmin reaching this
        method would emit a row with NO ``space_id`` (a ``NOT NULL`` violation), so it
        fails fast and loud instead (WR-01 — the mirror of ``create_in_space``'s guard).
        The row is flushed so its server-side defaults / id are populated before return.
        """
        if self._space_id is None:
            raise RuntimeError(
                "create() requires a user-scoped identity (space_id); a superadmin "
                "must use create_in_space() against an explicit target space"
            )
        values["space_id"] = self._space_id  # identity-derived; never a kwarg
        row = self.model(**values)
        self._s.add(row)
        self._s.flush()
        return row

    def create_in_space(self, space_id, **values):
        """Superadmin-only create into an EXPLICIT target space (D-05 / Pitfall 3).

        The tenant :meth:`create` deliberately refuses a ``space_id`` kwarg (TENANT-02): a
        user may never target a foreign space. A SUPERADMIN, however, has no own space and
        acts cross-tenant against a CHOSEN space (the active-client switcher). This is the
        audited superadmin write path: valid ONLY on a superadmin-scoped repo
        (``self._space_id is None``, bound to the ``app_superadmin`` engine whose 0003 bypass
        policy permits the cross-space insert), it sets the target ``space_id`` explicitly.
        """
        if self._space_id is not None:
            raise RuntimeError(
                "create_in_space is superadmin-only — the user path must use create()"
            )
        # The BEFORE-INSERT prefill trigger (SECURITY DEFINER) writes a client_name row into
        # intake_answers, whose RLS WITH CHECK is ``space_id = app.current_space_id``. The
        # superadmin path sets NO GUC, and the ``app_superadmin`` bypass policy does NOT apply
        # inside the definer trigger (current_user becomes the function owner there), so that
        # child insert would fail with 42501. Set the GUC to the TARGET space (tx-local) first
        # so the trigger's write passes its space-isolation check; it reverts at COMMIT.
        set_space_context(self._s, space_id)
        values["space_id"] = space_id
        row = self.model(**values)
        self._s.add(row)
        self._s.flush()
        return row


class IntakeRepository(TenantRepository[Intake]):
    """Sample/concrete repository over ``nestor.intakes`` (the Phase 4 seam driver).

    Thin subclass — all behaviour lives in :class:`TenantRepository`; Phase 6 adds one
    subclass per tenant entity the same way.
    """

    model = Intake


class IntakeAnswerRepository(TenantRepository[IntakeAnswer]):
    """Tenant-scoped repository over ``nestor.intake_answers``.

    Thin subclass — list/get/patch/create come from :class:`TenantRepository` and are
    space-walled by ``_scope`` for free. Adds a per-intake read and the section-batch
    upsert the save-as-you-go flow needs.
    """

    model = IntakeAnswer

    def list_for_intake(self, intake_id):
        """Return this intake's answers within scope (own space only for a user)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model).where(self.model.intake_id == intake_id)
                )
            )
            .scalars()
            .all()
        )

    def upsert_batch(self, intake_id, items):
        """Upsert a section's answers on the EXISTING ``(intake_id, field_key)`` unique
        constraint (``uq_intake_answers_intake_field``) — INSERT ... ON CONFLICT DO UPDATE.

        ``space_id`` is injected from ``self._space_id`` (the verified Identity) and
        ``intake_id`` from the path arg — NEVER from the item dict (D-03 / T-06-03). Each
        item carries only ``field_key`` / ``value`` / ``value_json``; any ``space_id`` /
        ``intake_id`` it happened to carry is ignored. This is the user-path section save, so
        it relies on the tenant key being present (a superadmin batch goes via the admin seam).

        D-01 repo wall (independent of RLS): the ``ON CONFLICT DO UPDATE`` carries an
        explicit ``WHERE space_id = self._space_id`` so a conflicting row owned by a
        FOREIGN space is NEVER overwritten — even if RLS were dropped. The conflict TARGET
        stays the ``(intake_id, field_key)`` constraint (no migration); ``space_id`` comes
        ONLY from ``self._space_id`` (no method parameter — module invariant). A superadmin
        repo (``self._space_id is None``) must NOT reach this method — a NULL ``space_id``
        row would violate the ``NOT NULL`` constraint — so it fails fast and loud instead.
        """
        if self._space_id is None:
            raise RuntimeError(
                "upsert_batch requires a user-scoped identity (space_id); a superadmin "
                "write must target an explicit space"
            )
        rows = [
            {
                "space_id": self._space_id,
                "intake_id": intake_id,
                "field_key": item["field_key"],
                "value": item.get("value"),
                "value_json": item.get("value_json"),
            }
            for item in items
        ]
        if not rows:
            return
        stmt = pg_insert(self.model).values(rows)
        # Same conflict target the legacy prefill/save-as-you-go RPC used.
        set_ = {
            "value": stmt.excluded.value,
            "value_json": stmt.excluded.value_json,
        }
        # D-01: overwrite only a conflicting row owned by THIS space (independent wall).
        stmt = stmt.on_conflict_do_update(
            constraint="uq_intake_answers_intake_field",
            set_=set_,
            where=(self.model.space_id == self._space_id),
        )
        self._s.execute(stmt)

    def upsert_batch_in_space(self, space_id, intake_id, items):
        """Superadmin-only section upsert into an EXPLICIT target space.

        Mirrors :meth:`upsert_extracted_in_space` for the plain (human/AI-review) answer
        columns: the tenant :meth:`upsert_batch` derives its space ONLY from the verified
        Identity, so a SUPERADMIN (no own space) needs this audited cross-tenant path
        against the intake's OWN space (resolved from the fetched intake row by the route,
        never from the request). Valid ONLY on a superadmin-scoped repo
        (``self._space_id is None``). Sets the tx-local GUC to the TARGET space and stamps
        ``space_id`` on every row; the ``ON CONFLICT DO UPDATE`` carries an explicit
        ``WHERE space_id = <target>`` so only rows in the chosen space are ever
        overwritten (D-01 wall, unchanged). Live-UAT regression 2026-07-13: the admin
        AI-review apply path (PATCH /answers as superadmin) 500'd here.
        """
        if self._space_id is not None:
            raise RuntimeError(
                "upsert_batch_in_space is superadmin-only — the user path must use "
                "upsert_batch()"
            )
        rows = [
            {
                "space_id": space_id,
                "intake_id": intake_id,
                "field_key": item["field_key"],
                "value": item.get("value"),
                "value_json": item.get("value_json"),
            }
            for item in items
        ]
        if not rows:
            return
        # Mirror create_in_space: set the tx-local GUC to the TARGET space so any
        # definer-trigger write passes its space-isolation check (reverts at COMMIT).
        set_space_context(self._s, space_id)
        stmt = pg_insert(self.model).values(rows)
        set_ = {
            "value": stmt.excluded.value,
            "value_json": stmt.excluded.value_json,
        }
        # D-01: overwrite only a conflicting row owned by the TARGET space.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_intake_answers_intake_field",
            set_=set_,
            where=(self.model.space_id == space_id),
        )
        self._s.execute(stmt)

    def upsert_extracted(self, intake_id, items):
        """LLM-extracted answer upsert — the structure-answers handler's write path (A6).

        Per 07-RESEARCH A6 (D-05 LLM-answer collision): machine-extracted answers
        land in the SAME ``intake_answers`` rows as human input and MUST respect the
        existing ``uq_intake_answers_intake_field`` unique constraint — we do NOT relax
        or re-target it. This mirrors :meth:`upsert_batch` but stamps
        ``extracted_by='llm'`` and carries the extraction provenance
        (``confidence`` / ``source_chunk_id``) so 07-07's structure-answers handler
        reuses this verbatim instead of re-opening the constraint.

        ``space_id`` is injected from ``self._space_id`` (the verified Identity) and
        ``intake_id`` from the path arg — NEVER from the item dict (D-03). Each item
        carries only ``field_key`` / ``value`` / ``value_json`` / ``confidence`` /
        ``source_chunk_id``; any tenant key it happened to carry is ignored.

        D-01 repo wall (independent of RLS): the ``ON CONFLICT DO UPDATE`` carries an
        explicit ``WHERE space_id = self._space_id`` so a conflicting row owned by a
        FOREIGN space is NEVER overwritten — even if RLS were dropped. The conflict
        TARGET stays the ``(intake_id, field_key)`` constraint (no migration). space_id
        is NEVER a method parameter. A superadmin repo (``self._space_id is None``)
        must use :meth:`upsert_extracted_in_space` against the intake's OWN space —
        reaching this method with no space would emit a NULL ``space_id`` row (a
        ``NOT NULL`` violation), so it fails fast and loud instead.
        """
        if self._space_id is None:
            raise RuntimeError(
                "upsert_extracted requires a user-scoped identity (space_id); a "
                "superadmin write must use upsert_extracted_in_space()"
            )
        rows = [
            {
                "space_id": self._space_id,
                "intake_id": intake_id,
                "field_key": item["field_key"],
                "value": item.get("value"),
                "value_json": item.get("value_json"),
                "confidence": item.get("confidence"),
                "source_chunk_id": item.get("source_chunk_id"),
                "extracted_by": "llm",
            }
            for item in items
        ]
        if not rows:
            return
        stmt = pg_insert(self.model).values(rows)
        set_ = {
            "value": stmt.excluded.value,
            "value_json": stmt.excluded.value_json,
            "confidence": stmt.excluded.confidence,
            "source_chunk_id": stmt.excluded.source_chunk_id,
            "extracted_by": stmt.excluded.extracted_by,
        }
        # D-01: overwrite only a conflicting row owned by THIS space (independent wall).
        stmt = stmt.on_conflict_do_update(
            constraint="uq_intake_answers_intake_field",
            set_=set_,
            where=(self.model.space_id == self._space_id),
        )
        self._s.execute(stmt)

    def upsert_extracted_in_space(self, space_id, intake_id, items):
        """Superadmin-only LLM-extracted upsert into an EXPLICIT target space (D-05).

        Mirrors :meth:`create_in_space`: the tenant :meth:`upsert_extracted` derives its
        space ONLY from the verified Identity, so a SUPERADMIN (no own space) needs this
        audited cross-tenant path against the intake's OWN space. Valid ONLY on a
        superadmin-scoped repo (``self._space_id is None``, bound to the
        ``app_superadmin`` engine whose 0003 bypass policy permits the cross-space
        write). Sets the tx-local GUC to the TARGET space (as :meth:`create_in_space`
        does for the SECURITY DEFINER trigger path) and stamps ``space_id`` on every
        row. The conflict TARGET stays the ``(intake_id, field_key)`` constraint and the
        ``ON CONFLICT DO UPDATE`` carries an explicit ``WHERE space_id = <target>`` so
        only rows in the chosen space are ever overwritten (D-01 wall, unchanged).
        """
        if self._space_id is not None:
            raise RuntimeError(
                "upsert_extracted_in_space is superadmin-only — the user path must "
                "use upsert_extracted()"
            )
        rows = [
            {
                "space_id": space_id,
                "intake_id": intake_id,
                "field_key": item["field_key"],
                "value": item.get("value"),
                "value_json": item.get("value_json"),
                "confidence": item.get("confidence"),
                "source_chunk_id": item.get("source_chunk_id"),
                "extracted_by": "llm",
            }
            for item in items
        ]
        if not rows:
            return
        # Mirror create_in_space: set the tx-local GUC to the TARGET space so any
        # definer-trigger write passes its space-isolation check (reverts at COMMIT).
        set_space_context(self._s, space_id)
        stmt = pg_insert(self.model).values(rows)
        set_ = {
            "value": stmt.excluded.value,
            "value_json": stmt.excluded.value_json,
            "confidence": stmt.excluded.confidence,
            "source_chunk_id": stmt.excluded.source_chunk_id,
            "extracted_by": stmt.excluded.extracted_by,
        }
        # D-01: overwrite only a conflicting row owned by the TARGET space.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_intake_answers_intake_field",
            set_=set_,
            where=(self.model.space_id == space_id),
        )
        self._s.execute(stmt)


class SkillRunRepository(TenantRepository[SkillRun]):
    """Tenant-scoped repository over ``nestor.skill_runs``.

    Thin subclass — list/get/patch/create come from :class:`TenantRepository`. Adds the
    per-intake list and the "latest run" read the phase machine / progress poll need.
    """

    model = SkillRun

    def list_for_intake(self, intake_id):
        """Return this intake's skill runs within scope (newest first)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model)
                    .where(self.model.intake_id == intake_id)
                    .order_by(self.model.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    def latest_for_intake(self, intake_id):
        """Return the most recent skill run for this intake within scope, or ``None``."""
        return self._s.execute(
            self._scope(
                select(self.model)
                .where(self.model.intake_id == intake_id)
                .order_by(self.model.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


class ResearchRunRepository(TenantRepository[ResearchRun]):
    """Tenant-scoped repository over ``nestor.research_runs`` (Phase 16 trigger/poll seam).

    Thin subclass — list/get/patch/create/create_in_space come from
    :class:`TenantRepository`, all space-walled by ``_scope`` for free (D-01). The
    ``space_id`` is derived ONLY from the verified Identity (user path via
    :meth:`create`) or set explicitly against the intake's OWN space by the superadmin
    path (via :meth:`create_in_space`) — it is NEVER a method parameter (TENANT-02).
    Because the research trigger is a superadmin action against a chosen client's
    intake, the trigger endpoint (Plan 02) uses ``create_in_space`` against the
    intake's resolved space; the poll driver PATCHes the mirrored status/stage fields
    on the in-scope row. Adds the per-intake "latest run" read the trigger (dedup /
    stale-window check) and the SSE stream endpoint (Plan 04) consume.

    Status literals are carried VERBATIM here too — this repo NEVER remaps
    ``completed`` to ``succeeded`` (D-05 boundary; the model owns that contract).
    """

    model = ResearchRun

    def list_for_intake(self, intake_id):
        """Return this intake's research runs within scope (newest first)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model)
                    .where(self.model.intake_id == intake_id)
                    .order_by(self.model.created_at.desc())
                )
            )
            .scalars()
            .all()
        )

    def latest_for_intake(self, intake_id):
        """Return the most recent research run for this intake within scope, or ``None``.

        A cross-tenant / missing intake matches the scoped ``WHERE`` against nothing →
        ``None`` (the handler renders that as an existence-hidden empty read, D-07).
        """
        return self._s.execute(
            self._scope(
                select(self.model)
                .where(self.model.intake_id == intake_id)
                .order_by(self.model.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()


class ResearchArtifactRepository(TenantRepository[ResearchArtifact]):
    """Tenant-scoped repository over ``nestor.research_artifacts`` (07-09 context-pack read).

    Thin subclass — list/get/patch/create come from :class:`TenantRepository` and are
    space-walled by ``_scope`` for free (D-01). Adds the two READ helpers the context-pack
    display endpoint needs: the latest pack + the full pack history for an intake. Both
    filter on ``source == "context-pack-generator"`` — the EXACT literal the write path
    (``app.ai.skills.context_pack``) stamps — so ONLY context-pack artifacts surface, not
    future post-``decomposed`` research-evidence rows (T-7-09-05). ``space_id`` is derived
    ONLY from the verified Identity via ``_scope`` — never a method arg (TENANT-02).
    """

    model = ResearchArtifact

    #: The exact ``source`` literal the generate-context-pack write path stamps.
    _CONTEXT_PACK_SOURCE = "context-pack-generator"

    def latest_context_pack_for_intake(self, intake_id):
        """Return this intake's most recent context-pack artifact within scope, or ``None``.

        A cross-tenant/missing intake matches the scoped ``WHERE`` against nothing → ``None``
        (the handler renders that as an existence-hidden empty read, D-07).
        """
        return self._s.execute(
            self._scope(
                select(self.model)
                .where(
                    self.model.intake_id == intake_id,
                    self.model.source == self._CONTEXT_PACK_SOURCE,
                )
                .order_by(self.model.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    def list_context_packs_for_intake(self, intake_id):
        """Return this intake's context-pack artifacts within scope (newest first)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model)
                    .where(
                        self.model.intake_id == intake_id,
                        self.model.source == self._CONTEXT_PACK_SOURCE,
                    )
                    .order_by(self.model.created_at.desc())
                )
            )
            .scalars()
            .all()
        )


class IntakeTemplateRepository(TenantRepository[IntakeTemplate]):
    """Tenant-scoped repository over ``nestor.intake_templates``.

    Thin subclass — all behaviour lives in :class:`TenantRepository`. The user path reads
    only templates in its own space; superadmin cross-space template ops go via
    :class:`app.db.admin_repo.AdminRepo` (Pitfall 3).
    """

    model = IntakeTemplate


class IntakeSourceRepository(TenantRepository[IntakeSource]):
    """Tenant-scoped repository over ``nestor.intake_sources`` (Phase 7 AI ports).

    Thin subclass — list/get/patch/create come from :class:`TenantRepository` and are
    space-walled by ``_scope`` for free. ``space_id`` is injected from the verified
    Identity on ``create``; it is NEVER a method parameter (TENANT-02). Adds a per-intake
    read the transcribe/extract handlers use to enumerate an intake's uploads.
    """

    model = IntakeSource

    def list_for_intake(self, intake_id):
        """Return this intake's source uploads within scope (own space only for a user)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model).where(self.model.intake_id == intake_id)
                )
            )
            .scalars()
            .all()
        )

    def delete_by_storage_path(self, intake_id, storage_path):
        """Delete this intake's source row(s) pointing at ``storage_path``; return rowcount.

        The storage-delete handler (09-02) calls this to clean the ``intake_sources``
        ref matching a just-deleted GCS object in the SAME tx as the object delete
        (D-09 / T-09-09 — no dangling ref). The delete is routed through :meth:`_scope`,
        so a ``user`` can only ever remove a row in THEIR own space (the explicit
        ``WHERE space_id = self._space_id`` wall, D-01) — a cross-tenant / forged
        ``storage_path`` matches nothing and ``rowcount == 0``. ``space_id`` is derived
        ONLY from the verified Identity via ``_scope`` — never a method arg (TENANT-02).
        The handler additionally asserts the key prefix before ever calling this, so a
        forged key never reaches the DB (D-08).
        """
        stmt = self._scope(
            delete(self.model).where(
                self.model.intake_id == intake_id,
                self.model.storage_path == storage_path,
            )
        )
        result = self._s.execute(
            stmt, execution_options={"synchronize_session": False}
        )
        return result.rowcount


class TranscriptRepository(TenantRepository[Transcript]):
    """Tenant-scoped repository over ``nestor.transcripts`` (Phase 7 AI ports).

    Thin subclass — the inherited ``_scope`` wall applies the explicit space filter for a
    user and is omitted for a superadmin (0003 bypass). ``space_id`` is identity-derived
    only. Adds per-intake / per-source reads the insight-extraction handler consumes.
    """

    model = Transcript

    def list_for_intake(self, intake_id):
        """Return this intake's transcript chunks within scope (own space only for a user)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model)
                    .where(self.model.intake_id == intake_id)
                    .order_by(self.model.chunk_index)
                )
            )
            .scalars()
            .all()
        )

    def list_for_source(self, source_id):
        """Return one source's transcript chunks within scope (ordered by chunk_index)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model)
                    .where(self.model.source_id == source_id)
                    .order_by(self.model.chunk_index)
                )
            )
            .scalars()
            .all()
        )


class ExtractedInsightRepository(TenantRepository[ExtractedInsight]):
    """Tenant-scoped repository over ``nestor.extracted_insights`` (Phase 7 AI ports).

    Thin subclass — list/get/patch/create come from :class:`TenantRepository`, all
    space-walled by ``_scope``. ``space_id`` is taken only from the verified Identity.
    Adds the per-intake read the context-pack / review surfaces consume.
    """

    model = ExtractedInsight

    def list_for_intake(self, intake_id):
        """Return this intake's extracted insights within scope (own space only for a user)."""
        return (
            self._s.execute(
                self._scope(
                    select(self.model).where(self.model.intake_id == intake_id)
                )
            )
            .scalars()
            .all()
        )


class ArtifactEmbeddingRepository(TenantRepository[ArtifactEmbedding]):
    """Tenant-scoped repository over ``nestor.artifact_embeddings`` (Phase 7 search seam).

    Thin subclass — the inherited ``_scope`` wall pre-filters every read/write by the
    identity's space, so the vector store never has a cross-tenant leak path (threat
    T-01-06). ``space_id`` is identity-derived only — never a method parameter (TENANT-02).
    The embed/search handlers add vector ops on top of this scoped base in later plans.
    """

    model = ArtifactEmbedding
