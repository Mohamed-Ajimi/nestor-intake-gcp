"""``research_runs`` — the intake-side MIRROR of a Tribunal deep-research run.

Phase 16 foundation (ENGINE-03). Tenant-OWNED (TENANT-01): every row carries
``space_id NOT NULL`` -> ``organizations(id)`` and is FORCE-RLS space-isolated
from day one (Pitfall 5 — a fresh tenant surface is a fresh chance to reintroduce
the broken-RLS bug class). This table is the seam of record between the intake
backend and the internal Tribunal engine:

  * the run-trigger endpoint (Plan 02) INSERTs a ``queued`` row and stamps the
    ``tribunal_run_id`` returned by ``tribunal_client.create_run``;
  * the poll driver (Plan 03) mirrors the Tribunal ``get_metrics`` status /
    ``current_stage`` / ``stage_detail`` / ``cost_usd_total`` into this row and,
    on the terminal ``completed`` status, persists the raw ``output_markdown``
    (via ``get_report``) so Phase 17's raw-output surface is a pure UI add (A4);
  * the SSE stream endpoint (Plan 04) READs this row (never Tribunal directly).

STATUS LITERALS ARE CARRIED VERBATIM (D-05 boundary): the ``status`` column holds
the Tribunal engine's own values ``{queued, running, completed, failed,
cancelled}`` — it is NEVER remapped to the skill-run vocabulary ``{succeeded,
failed}``. A run that finishes successfully is ``completed`` here (NOT
``succeeded``); mixing the two vocabularies is the exact class of contract drift
the SSE terminal-set pitfall warns about (16-RESEARCH Pitfall). ``server_default``
is ``queued`` to mirror the run's birth state.

Index shape mirrors ``SkillRun`` (space-LEADING composite indexes) so the
space_id predicate is index-served for the per-intake poll/read paths. The three
index names MUST match migration 0011 1:1 (``alembic check`` gate).

Phase 17 (RUN-03) adds three NULLABLE chain-guard / bundle columns via migration
0012 — ``chain_status`` / ``chain_broken_at`` / ``bundle_key`` — written by the
completion path (Plan 02) and read by the SSE dict + download/re-verify routes
(Plan 03). They inherit ``research_runs``' existing FORCE-RLS row policy; 0012
adds NO new policy, grant, or index.

Phase 15.3 (plan 15.3-06) adds ONE more NULLABLE column via migration 0013 —
``event_seq``, the run-event feed CURSOR — on the same additive terms: written
by the poll driver's mirror, read by the SSE dict, no policy/grant/index change.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class ResearchRun(Base):
    __tablename__ = "research_runs"

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    space_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    intake_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("nestor.intakes.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Tribunal literals carried VERBATIM — {queued, running, completed, failed,
    # cancelled}. NEVER remapped to skill-run {succeeded, failed} (D-05 boundary).
    status: Mapped[str] = mapped_column(
        String, nullable=False, server_default="queued"
    )
    # ---- Tribunal mirror columns (poll driver / trigger stamp these). All
    #      NULLABLE except ``attempt`` — a freshly-inserted ``queued`` row carries
    #      none of the progress fields until the first poll.
    #: The Tribunal-side run id returned by create_run — the poll key (nullable
    #: until the trigger stamps the create_run response).
    tribunal_run_id: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The currently-executing stage key (dynamic; NEVER a hardcoded 9-stage
    #: assumption — the progress UI renders the stage list dynamically).
    current_stage: Mapped[str | None] = mapped_column(String, nullable=True)
    #: Per-stage progress detail, shape ``{stage_key: {items:[{name,status}]}}``.
    stage_detail: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    #: Running cost total in USD (mirrored from the Tribunal budget governor).
    cost_usd_total: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    #: Attempt counter (D-04 attempt tracking) — NOT NULL, starts at 1. A retrigger
    #: after a failed/stale run bumps this so the audit trail keeps every attempt.
    attempt: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="1"
    )
    #: Terminal error message on the ``failed`` path (nullable otherwise).
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    #: The raw research output markdown, persisted on ``completed`` (A4) so the
    #: Phase 17 raw-output surface is a pure UI add — no re-fetch from Tribunal.
    output_markdown: Mapped[str | None] = mapped_column(Text, nullable=True)
    # ---- Phase 17 chain-guard / bundle columns (RUN-03). All NULLABLE, NO
    #      server_default — pre-existing live rows (smoke intake e08620c5 has 3)
    #      carry NULL until the completion path (Plan 02) writes the verdict + key.
    #: The audit-chain verdict at completion: ``"verified"`` | ``"broken"``.
    #: NULL until the completion path runs verify_chain (D-06). A ``"broken"``
    #: value locks the raw-output download until a re-verify lifts it (D-08).
    chain_status: Mapped[str | None] = mapped_column(String, nullable=True)
    #: The broken row index ``verify_chain`` returns on a broken chain; NULL when
    #: verified or unrun (the audit chain's first divergent hash position).
    chain_broken_at: Mapped[int | None] = mapped_column(Integer, nullable=True)
    #: The GCS object key of the materialized raw-output zip (D-04/D-05); NULL
    #: until the completion path builds and uploads the bundle.
    bundle_key: Mapped[str | None] = mapped_column(String, nullable=True)
    # ---- Phase 15.3 run-event FEED CURSOR (plan 15.3-06, migration 0013).
    #: The run's feed POSITION: the highest ``run_event.seq`` the engine has
    #: written for this run. Source of truth is ``RunMetrics.event_seq`` (plan
    #: 15.3-02, ``MAX(run_event.seq)``); the poll driver mirrors it here and
    #: ``read_latest_research_run_dict`` re-emits it on the existing SSE frame,
    #: so the page can fetch ONLY the delta past its own cursor (D-05).
    #:
    #: A POSITION, never a payload — the frame never carries events themselves,
    #: and this is NOT a completion signal: ``completed_at`` says whether the run
    #: ended, this says how far its feed got. A ``parked`` run keeps advancing it
    #: (``run_task.finalize_parked``). NULL means "no events yet" — never 0,
    #: which would claim a stream positioned at its start.
    event_seq: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    # ---- Phase 23.3 RECONCILER columns (plan 23.3-04, migration 0017,
    #      COST-01 / DEF-23.2-03). All NULLABLE, NO server_default — the app is
    #      the sole writer, and this table holds paid, IN-FLIGHT rows, so four
    #      nullable undefaulted columns are a metadata-only ADD COLUMN with no
    #      table rewrite. NULL means "this run predates the reconciler", which is
    #      a state the sweep must be able to observe and SKIP.
    #:
    #: WHO. ``Identity.uid`` of the human who triggered or resumed this run.
    #: Exists because the Tribunal seam REQUIRES a non-empty ``X-Acting-User-Id``
    #: and answers 400 without one (``auth/internal_caller.py``) — the D-05
    #: acting-user attribution is a hard legal constraint on a FROZEN audit
    #: chain. Today the actor is derived in-process from the live request
    #: ``Identity`` (``run_task.load_trigger_context``), which a stateless sweep
    #: does not have; so the row must carry the ORIGINAL human's and the sweep
    #: must REPLAY it. Inventing a system actor would corrupt exactly the
    #: attribution the chain exists to carry.
    acting_user_id: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment=(
            "Identity.uid of the human who triggered or resumed this run. Persisted so "
            "a stateless reconciler can REPLAY the original actor's D-05 attribution "
            "across the Tribunal seam (which requires a non-empty X-Acting-User-Id and "
            "answers 400 without one) rather than inventing a system actor on a frozen "
            "audit chain. NULL = the run predates 0017."
        ),
    )
    #: The same human's address. TWO consumers: the seam's required
    #: ``X-Acting-User-Email`` header, and the D-10 completion / park mail, which
    #: otherwise has nobody to write to when a run is finished by a sweep instead
    #: of by its own driver. ``Identity.email`` is ``str | None``, so a superadmin
    #: token without one stores NULL here DELIBERATELY — never ``""``, never a
    #: placeholder address. Plan 05's reconciler skips such a row rather than
    #: calling a seam that will answer 400: a fabricated actor on a legally
    #: load-bearing chain is worse than a skipped sweep.
    acting_email: Mapped[str | None] = mapped_column(
        String,
        nullable=True,
        comment=(
            "The same human's address. Two consumers: the seam's required "
            "X-Acting-User-Email header, and the D-10 completion / park mail, which "
            "otherwise has nobody to write to when a run is finished by a sweep "
            "instead of by its own driver. NULL is DELIBERATE when Identity.email is "
            "None — never '' and never a placeholder address; a fabricated actor on a "
            "legally load-bearing chain is worse than a skipped sweep."
        ),
    )
    #: LIVENESS. Bumped by ``run_task.mirror_tick`` on EVERY tick (~3 s,
    #: ``POLL_SECONDS``), UNCONDITIONALLY — it is the driver's assertion about
    #: ITSELF, never a value mirrored from the seam.
    #:
    #: MUST NOT be confused with ``created_at`` or ``started_at``. Those are
    #: stamped ONCE and never move, which is exactly why the D-E defect happened:
    #: a live 35-minute provider long-poll was indistinguishable from a process
    #: that died 35 minutes ago, and the designed response to a dead process is to
    #: re-run at FULL COST. A liveness signal is the one that MOVES. There is no
    #: ``updated_at`` on this table, which is why this column has to exist at all.
    driver_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "LIVENESS. Bumped by run_task.mirror_tick on EVERY tick (~3s), "
            "unconditionally — the driver's assertion about ITSELF, never a value "
            "mirrored from the seam. MUST NOT be confused with created_at or "
            "started_at: those are stamped ONCE and never move, which is exactly why "
            "the D-E defect happened — a live 35-minute provider long-poll was "
            "indistinguishable from a process that died 35 minutes ago, and the "
            "designed response to a dead process is to re-run at full cost. A liveness "
            "signal is the one that MOVES."
        ),
    )
    #: THE LEASE. Set by a sweep when it CLAIMS this row, so a second nestor-api
    #: instance (``maxScale=4``) skips it. A LEASE, not a lock: it EXPIRES, so a
    #: sweep that dies mid-flight cannot strand the row — which is the very
    #: failure mode the reconciler exists to end, and reintroducing it one layer
    #: up would be absurd.
    reconcile_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        comment=(
            "Set by a sweep when it CLAIMS this row, so a second nestor-api instance "
            "(maxScale=4) skips it. A LEASE, not a lock: it EXPIRES, so a sweep that "
            "dies mid-flight cannot strand the row — which is the very failure mode "
            "the reconciler exists to end."
        ),
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (
        Index("ix_research_runs_space_id", "space_id"),
        Index("idx_research_runs_space_intake", "space_id", "intake_id"),
        Index("idx_research_runs_space_status", "space_id", "status"),
        # COST-01 / D-23.2-12 (F-05) — at most ONE IN-FLIGHT research run per intake.
        # The arbiter is the DATABASE, not an app-level "is one already running?"
        # check, which races: two concurrent triggers both read "nothing is running"
        # and both insert, and the operator pays ~$45 twice on a path that runs with
        # NESTOR_TRIBUNAL_UNCAPPED=1.
        #
        # THREE literals, not two. mirror_tick writes the engine's status VERBATIM and
        # there is no CHECK constraint, so the predicate is the COMPLEMENT of
        # _RETRYABLE_RUN_STATUSES (research_routes.py) union RESEARCH_TERMINAL
        # (research/run_status.py) over the nine measured statuses.
        # ``needs_report_spec`` is NOT retryable — a run sitting there is alive and
        # awaiting an operator's report spec — so it holds the in-flight slot too. It
        # is documented as UNREACHABLE on the seam path today (research/brief.py never
        # opts into the interactive-report gate); it is here as defence-in-depth
        # against a design change, not as a fix for a live hole.
        #
        # POSITIVE IN (...), never NOT IN (terminal): an unknown FUTURE engine status
        # must fail OPEN rather than block that intake's triggers permanently.
        #
        # PARTIAL, so terminal rows stay unconstrained and the retry path and the
        # Resume verb keep working. The name is byte-identical to migration 0016's —
        # a mismatch is invisible until a downgrade or a later autogenerate, and
        # ``alembic check`` does NOT catch a drifted predicate (its postgresql
        # compare_indexes looks at the unique flag and the expressions only), so
        # tests/test_research_dispatch_dedup.py pins name AND predicate against the
        # deployed pg_indexes.indexdef.
        Index(
            "uq_research_runs_one_inflight_per_intake",
            "intake_id",
            unique=True,
            postgresql_where=text("status IN ('queued', 'running', 'needs_report_spec')"),
        ),
        # Phase 23.3 / DEF-23.2-03 (migration 0017) — the ORPHAN-CANDIDATE scan.
        # A PARTIAL btree on the liveness column so the reconciler's "which
        # non-terminal runs have a stale (or absent) driver heartbeat?" query never
        # seq-scans a table of terminal, paid runs.
        #
        # The predicate is the SAME three literals as
        # uq_research_runs_one_inflight_per_intake above, sourced from 0017's own
        # _INFLIGHT tuple, so the two indexes cannot disagree about what "in flight"
        # means. ``needs_report_spec`` is the easy one to drop and the one that matters
        # most: a run sitting there is ALIVE, awaiting an operator's report spec.
        #
        # POSITIVE IN (...), never NOT IN (terminal) — and here the direction matters
        # MORE than it does for the sibling index. mirror_tick writes the engine's
        # status VERBATIM into a plain String with no CHECK constraint, so the engine
        # can emit a status this repository has never heard of. Under a negated
        # predicate that unknown status would count as a candidate and the sweep would
        # treat a perfectly healthy run as an ORPHAN — and the response to an orphan is
        # to TAKE IT OVER. Failing open costs a missed sweep; failing closed would cost
        # a live run being seized.
        #
        # The name is byte-identical to migration 0017's. ⚠ ``alembic check`` will NOT
        # protect this: its postgresql compare_indexes inspects the unique flag and the
        # expressions only and never looks at postgresql_where, so a drifted predicate
        # passes it SILENTLY (DEF-23.2-15). tests/test_research_run_reconciler_columns.py
        # pins the name AND the three literals against the deployed pg_indexes.indexdef.
        Index(
            "ix_research_runs_orphan_candidates",
            "driver_heartbeat_at",
            postgresql_where=text("status IN ('queued', 'running', 'needs_report_spec')"),
        ),
    )
