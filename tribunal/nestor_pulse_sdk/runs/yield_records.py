"""
Yield records -- the durable, per-assignment and per-round measurement (D-R8).

THIS MODULE NEVER RAISES INTO A CALLER. Not from `record_assignment`, not from
`complete_assignment`, not from `record_round`, and not from any of the three
`_safe` wrappers. A run that loses a yield row is DEGRADED; a run that dies
because of a telemetry write is a REGRESSION, and this one costs roughly $45.
Every entry point below swallows its own failures and logs them at WARNING --
and it is never SILENTLY green either: every clamped value, every failed write
and every unexpected affected-row count is logged with run / provider identity.

AND NO FIELD VALUE CAN CAUSE A ROW TO BE DISCARDED. That is a separate and
stronger promise than "never raises", and it is the one D-W5-10 was ruled on.

WHY THIS IS A TABLE AND NOT A `run_events` FEED (D-W5-1)
--------------------------------------------------------
`run_events._normalise_meta` passes `meta` through the `_META_FIELDS` ALLOWLIST
and drops every unknown key WITH A WARNING BUT OUT OF THE ROW. Not one of the
yield keys is in that tuple, so every one of them would vanish -- the
inert-instrumentation class this project has been burned by three times (V-01's
stage logging, D-W4-11's workshop notes, the out-of-vocabulary `kind` trap).
`run_event.text` is also scrubbed AND CLAMPED TO 400 CHARS, and that feed is
PER-RUN, while CROSS-RUN IS THE ENTIRE POINT OF D-R8: "does round 7+ ever produce
a new entrant across several runs" cannot be asked of a per-run feed at all.

WHY THIS MODULE CLAMPS WHERE `run_events.emit` DROPS (D-W5-10)
---------------------------------------------------------------
`emit`'s step (2) drops an out-of-vocabulary `kind`, and its stated reason is:
"An out-of-vocabulary kind renders as a BLANK LINE IN THE FEED, which is worse
than an absent one -- so drop the row." THAT RATIONALE IS DISPLAY-SPECIFIC AND
DOES NOT TRANSFER HERE. Two consequences follow from dropping a row in a
TELEMETRY table, and the second is the decisive one:

  1. A LOST MEASUREMENT. `cost_usd`, `claims_kept`, `resolvable_sources` and
     `duration_s` all discarded because one discriminator column was wrong. And
     `parent_kind` is ENGINE-AUTHORED, not model-authored, so an
     out-of-vocabulary value means an ENGINE BUG -- precisely the run whose
     telemetry is most worth keeping. Dropping it makes the one condition that
     most needs measuring the one condition that erases itself.

  2. A SILENT UNDERSTATEMENT OF SPEND. `SUM(cost_usd)` SKIPS NULL ROWS, and
     `runs/worker.py` totals spend across four `COALESCE(...)` sites, so MISSING
     COST DATA DOES NOT ANNOUNCE ITSELF -- the total simply LOOKS complete. A row
     carrying `provider = 'unknown'` still carries its dollars.

A `log.warning` IS NOT PERSISTENCE. That is the V-01 lesson stated exactly.

So a bad discriminator is CLAMPED to `PARENT_KIND_UNKNOWN` / `PROVIDER_UNKNOWN`,
THE ROW IS STILL WRITTEN with every other column intact, and the refused value is
logged loudly. There is deliberately no CHECK constraint in migration 0018
either: a CHECK would turn the same event into a FAILED TRANSACTION in a paid
run, which is worse still. Neither sentinel is a member of any vocabulary tuple,
so `parent_kind IN PARENT_KINDS` still returns exactly the three ruled shapes
while `= 'unknown'` is the engine-bug query.

THE INSERT-THEN-UPDATE CONTRACT, AND WHY THE KEY IS NATURAL
------------------------------------------------------------
The research half (cost, duration, claims kept, sources, the parse/retry flags)
is DURABLE and paid for the moment research resolves.
`claims_surviving_verification` only exists after verification, so it is written
by a SEPARATE UPDATE. Writing one row late would lose the paid half on a run
parked between the two stages.

That UPDATE is keyed on the NATURAL KEY
`(run_id, provider, group_id, client_question)` and NOT on a row id returned by
the INSERT, because A PARKED RUN RESUMES IN A DIFFERENT PROCESS where an
in-memory row id is gone. Nullable members are compared with
`IS NOT DISTINCT FROM`, so a NULL `group_id` or `client_question` matches its own
row instead of matching nothing.

⚠ THE KEY-SYMMETRY RULE -- THE ONE DEFECT IN THIS MODULE THAT FAILS SILENTLY
-----------------------------------------------------------------------------
THREE of the four key members are NORMALISED: `provider` is clamped to a
sentinel, `group_id` has `''` turned into NULL and is length-clamped, and
`client_question` is SCRUBBED AND THEN CLAMPED. If the completer built its key
from RAW values while the INSERT stored normalised ones, THE UPDATE WOULD MATCH
NOTHING -- and this module's own warning reads an affected-row count of 0 as "the
INSERT half never landed". A bad value would therefore produce a SPECIFIC,
CONFIDENT AND COMPLETELY WRONG DIAGNOSIS OF A DIFFERENT FAILURE, in the one run
there is.

None of the three is exotic: `scrub_pii` rewrites any question containing an
email or a phone number, and the clamp rewrites any question over
`MAX_QUESTION_CHARS`.

THE RULE: ONE NORMALISER, CALLED ON BOTH PATHS, APPLIED BEFORE THE KEY IS
ASSEMBLED. Not "the emitter normalises and the completer trusts". `_natural_key`
returns the four bound values, and BOTH `record_assignment` and
`complete_assignment` call it. CALLERS PASS RAW VALUES ON BOTH PATHS; this module
owns the symmetry, because a caller cannot.

WHY THERE IS NO QUEUE AND NO DRAIN TASK HERE
---------------------------------------------
`run_events` buffers because a run emits THOUSANDS of feed lines from inside
per-poll provider code. This module writes AT MOST ~45 assignment rows and ~10
round rows per run, each once, at a stage boundary, after a paid call has already
resolved. A queue here would need a drain task and a `close_run` hook -- and a
row lost at close is precisely the inert-instrumentation failure the whole schema
decision was made to avoid. DURABILITY OF THESE ROWS MATTERS MORE THAN THE
MICROSECONDS. What IS copied from `run_events` is the discipline: own session,
`session.begin()`, `set_tenant_context` FIRST, swallow-and-warn, never retry.

WHY EVERY DB IMPORT IS FUNCTION-LOCAL. Module scope imports only stdlib plus
`pii.scrub_pii` (itself a stdlib-only module). This is not tidiness: it is what
lets `tests/test_yield_records.py` import THE REAL MODULE on a machine with no
sqlalchemy, which is the only way to defeat the `ast`-lift trap -- that harness
SUPPLIES MODULE GLOBALS and therefore MANUFACTURES any name a module forgot to
import, so a green lifted test proves nothing about name resolution.

TEST SEAMS, NAMED AS SUCH. `_assignment_writer`, `_assignment_completer` and
`_round_writer` are module-level names so `tests/test_yield_records.py` can
replace the three operations that touch Postgres and drive everything else --
clamping, scrubbing, key assembly, coercion -- as real production code. They are
TEST SEAMS, not production seams: no pipeline caller passes or replaces any of
them.

WHAT A PIPELINE MODULE MAY CALL. `record_assignment_safe`,
`complete_assignment_safe` and `record_round_safe`, AND NOTHING ELSE. See
`record_assignment_safe`'s docstring for the control-flow reason.

Cloud Build invocation for this module's suite (no Postgres, no provider key):
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Callable, Optional

from nestor_pulse_sdk.pipeline.tribunal.pii import scrub_pii

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# THE VOCABULARY (D-W5-2). The three shapes an assignment row can have, and ONLY
# those three. A cross-cutting `d1` group has no single parent and records
# `client_question = NULL`; a discovery rider parented to a client-question label
# records ITS OWN question; an ordinary mandate assignment records
# `client_question`. `parent_kind` is a REAL column and is NEVER inferred from
# `client_question IS NULL` -- the two encode different things.
# ---------------------------------------------------------------------------
PARENT_KINDS: tuple[str, ...] = (
    "client_question",
    "discovery_rider",
    "cross_cutting",
)

#: The recorded sentinel for an out-of-vocabulary `parent_kind` (D-W5-10).
#: DELIBERATELY NOT A MEMBER OF `PARENT_KINDS`: a reader querying
#: `parent_kind IN PARENT_KINDS` gets exactly the three ruled shapes, while
#: `parent_kind = 'unknown'` finds the engine bugs.
PARENT_KIND_UNKNOWN: str = "unknown"

#: The same sentinel for column 4. DO NOT ADD IT TO ANY PROVIDER VOCABULARY
#: TUPLE (`research_division._D6_STREAMS`), for the same reason.
PROVIDER_UNKNOWN: str = "unknown"

# ---------------------------------------------------------------------------
# Tunables. Same `os.environ.get(name, default)` idiom as `run_events._FLUSH_S`,
# so a retune needs no code change.
# ---------------------------------------------------------------------------
#: Characters of `client_question` persisted. Read at import time.
MAX_QUESTION_CHARS = int(os.environ.get("NESTOR_YIELD_QUESTION_MAX", "600"))

#: Bound for the short label columns: `provider`, `group_id`, `stakes`. Every
#: real value is far under this; the clamp only stops a mistyped caller putting
#: an unbounded string in a column that later queries GROUP BY.
MAX_LABEL_CHARS = 64


# ===========================================================================
# Coercion helpers. None of them may raise, and none may turn garbage into a
# number: `None` means "not recorded" and `0` means "measured zero", and the
# whole point of this table is that those stay distinguishable.
# ===========================================================================


def _coerce_str(value: Any) -> Optional[str]:
    """Defensive stringify. Returns None rather than raising."""
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001 -- a hostile __str__ costs a label, not the run
        return None


def _clamp(text: str, cap: int) -> str:
    """Bound `text` to `cap`, marking a cut with a single ellipsis.

    The result is `cap + 1` characters when it was cut, so a truncated value is
    VISIBLY cut rather than silently shortened -- the convention
    `run_events._clamp` and `stage_feed.truncate_task_prompt` both use.
    DETERMINISTIC, which is what lets a clamped value serve as a key member.
    """
    cap = int(cap)
    if cap <= 0 or len(text) <= cap:
        return text
    return text[:cap] + "…"


def _coerce_int(value: Any) -> Optional[int]:
    """To `int`, or **None on anything ungainly -- NEVER 0**.

    This is the ONE place where copying `workshop_loop._count_of`, which returns
    0, would be WRONG. A 0 written here is a MEASUREMENT ("this provider kept no
    claims"); a None is an ABSENCE ("nothing was recorded"). Collapsing the
    second into the first fabricates data in the only measuring run.
    """
    if value is None or isinstance(value, bool):
        # `bool` is an `int` subclass; True would silently become 1.
        return None
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _coerce_bool(value: Any) -> Optional[bool]:
    """To `bool`, or None when the caller passed None. Never raises."""
    if value is None:
        return None
    try:
        return bool(value)
    except Exception:  # noqa: BLE001 -- a hostile __bool__ costs the flag, not the run
        return None


def _coerce_decimal(value: Any) -> Optional[Any]:
    """To `Decimal` via `str(value)`; None on failure.

    Via `str` and not via `float`: `Decimal(0.1)` carries the binary rounding
    error into a NUMERIC column that a human will later read as money.
    """
    from decimal import Decimal, InvalidOperation

    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    text = _coerce_str(value)
    if text is None:
        return None
    try:
        return Decimal(text.strip())
    except (InvalidOperation, ValueError, ArithmeticError):
        return None


def _normalise_label(value: Any) -> Optional[str]:
    """Coerce, strip, clamp to `MAX_LABEL_CHARS`; empty becomes None."""
    text = _coerce_str(value)
    if text is None:
        return None
    text = text.strip()
    if not text:
        return None
    return _clamp(text, MAX_LABEL_CHARS)


def _normalise_provider(value: Any, *, run_id: Any) -> str:
    """CLAMP to `PROVIDER_UNKNOWN` when unusable. NEVER returns a "skip" value.

    The return type is `str`, always. There is no value of `provider` that can
    make a row unwritable -- see the module docstring on D-W5-10, and note in
    particular that a dropped row would SILENTLY UNDERSTATE SPEND.

    THIS IS A NATURAL-KEY MEMBER, so it is reached ONLY through `_natural_key`
    and is therefore applied identically on the INSERT and the UPDATE path.
    """
    label = _normalise_label(value)
    if label is None:
        log.warning(
            "yield_records: provider %r is unusable (run=%s) -- clamped to %r "
            "and THE ROW IS STILL WRITTEN, because a dropped row loses its "
            "cost_usd and SUM() skips NULLs silently",
            value, run_id, PROVIDER_UNKNOWN,
        )
        return PROVIDER_UNKNOWN
    return label


def _normalise_parent_kind(value: Any, *, run_id: Any, provider: Any) -> str:
    """CLAMP to `PARENT_KIND_UNKNOWN` when out of vocabulary. Never drops.

    The return type is `str`, always. `parent_kind` is ENGINE-AUTHORED, so an
    out-of-vocabulary value means an ENGINE BUG -- precisely the run whose
    telemetry is most worth keeping (D-W5-10).

    NOT a natural-key member, so this is applied on the INSERT path only.
    """
    label = _normalise_label(value)
    if label not in PARENT_KINDS:
        log.warning(
            "yield_records: parent_kind %r is not one of %s (run=%s provider=%r) "
            "-- clamped to %r and THE ROW IS STILL WRITTEN. An out-of-vocabulary "
            "parent_kind is engine-authored, so this is an ENGINE BUG and its "
            "measurement is the one most worth keeping.",
            value, PARENT_KINDS, run_id, provider, PARENT_KIND_UNKNOWN,
        )
        return PARENT_KIND_UNKNOWN
    return label


def _normalise_group_id(value: Any) -> Optional[str]:
    """The `group_id` rule, with EXACTLY ONE CALL SITE (inside `_natural_key`).

    An ABSENT key is bound as NULL and NEVER as `''` -- migration 0017's own
    rule, because "no key recorded" and "recorded as the empty key" are
    different facts and the corroboration queries must tell them apart.

    A separate name from `_normalise_label` on purpose: `stakes` uses the label
    rule too, and a reviewer counting the call sites of the KEY MEMBER's rule
    must see exactly one. Two normalisation paths for one key member IS the
    defect this module is built to prevent.
    """
    return _normalise_label(value)


def _normalise_question(value: Any) -> Optional[str]:
    """SCRUB FIRST, CLAMP SECOND. THE ORDER IS LOAD-BEARING (D-07).

    Clamping first can cut an email in half and leave a fragment the scrubber no
    longer matches -- `someone@example.com` truncated to `someone@ex` has no TLD,
    so `pii._EMAIL_RE` misses it and a recognisable identifier is PERSISTED. And
    these rows are long-lived cross-run analysis data, so an unscrubbed
    identifier here outlives the run by a great deal. DO NOT REORDER.

    `scrub_pii` is DETERMINISTIC -- the same input always yields the same output
    -- which is exactly what makes the scrubbed value safe as a key member.

    EXACTLY ONE CALL SITE, inside `_natural_key`.
    """
    text = _coerce_str(value)
    if text is None:
        return None
    try:
        scrubbed, _removed = scrub_pii(text)
    except Exception as exc:  # noqa: BLE001 -- a scrub failure costs the label
        log.warning("yield_records: scrub_pii failed: %r -- question dropped", exc)
        return None
    scrubbed = _clamp(scrubbed, MAX_QUESTION_CHARS).strip()
    return scrubbed or None


def _natural_key(
    run_id: Any, provider: Any, group_id: Any, client_question: Any
) -> dict[str, Any]:
    """THE SHARED NORMALISER. Both halves build their key through THIS.

    Returns the four bound values `run_id`, `provider`, `group_id` and
    `client_question`, with `_normalise_provider`, `_normalise_group_id` and
    `_normalise_question` ALL applied. `record_assignment` builds its INSERT
    parameters from this; `complete_assignment` builds its WHERE from it. THERE
    IS NO SECOND PLACE WHERE ANY OF THOSE THREE VALUES IS NORMALISED.

    THE FAILURE THIS PREVENTS, stated so it is not re-discovered the expensive
    way: a key assembled from RAW values on one path and NORMALISED values on the
    other MATCHES NOTHING. `complete_assignment` then sees 0 affected rows, and
    its warning reads 0 as "the INSERT half never landed" -- a specific,
    confident and completely WRONG diagnosis of an entirely different failure, in
    the one measuring run this project gets.

    ⚠ A FUTURE REFACTOR THAT INLINES ONE CALL AND NOT THE OTHER REINTRODUCES THAT
    DEFECT WHILE LOOKING TIDIER. If you are here to "simplify", you are about to
    do exactly that.
    """
    return {
        "run_id": str(run_id),
        "provider": _normalise_provider(provider, run_id=run_id),
        "group_id": _normalise_group_id(group_id),
        "client_question": _normalise_question(client_question),
    }


# ===========================================================================
# The three operations that touch Postgres. All are TEST SEAMS (see the module
# docstring): they are looked up as module globals at call time so the suite can
# replace them, and no production caller passes or replaces any of them.
#
# Every statement is a `sqlalchemy.text` with BOUND PARAMETERS ONLY. No f-string,
# no `%`, no `.format()` anywhere near SQL -- `client_question` and `group_id`
# originate in model output built from client-authored text (T-15.8-05-01).
# ===========================================================================


async def _insert_assignment(tenant_id: Any, params: dict[str, Any]) -> None:
    """One row into `assignment_yield`, under the tenant GUC.

    Own session + `session.begin()` + `set_tenant_context` FIRST, the same
    pattern `run_events._insert_events` and `set_stage` use, so tenant binding
    lives in exactly one place per writer. `set_config(..., true)` is
    transaction-local (RLS Pitfall 1); a `false` third argument would leak across
    a pooled connection.
    """
    from sqlalchemy import text as sql_text

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context

    stmt = sql_text(
        "INSERT INTO assignment_yield "
        "(id, tenant_id, run_id, provider, group_id, client_question, "
        "parent_kind, stakes, fact_list_parsed, retry_used, claims_kept, "
        "resolvable_sources, cost_usd, duration_s) VALUES "
        "(:id, :tenant_id, :run_id, :provider, :group_id, :client_question, "
        ":parent_kind, :stakes, :fact_list_parsed, :retry_used, :claims_kept, "
        ":resolvable_sources, :cost_usd, :duration_s)"
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            await session.execute(stmt, params)


async def _update_assignment(tenant_id: Any, params: dict[str, Any]) -> int:
    """Fill `claims_surviving_verification` + `verified_at`. Returns rowcount.

    The WHERE is the NATURAL KEY. Nullable members use `IS NOT DISTINCT FROM` so
    a NULL `group_id` or `client_question` matches ITS OWN ROW rather than
    matching nothing -- `= NULL` is never true in SQL.
    """
    from sqlalchemy import text as sql_text

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context

    stmt = sql_text(
        "UPDATE assignment_yield SET "
        "claims_surviving_verification = :claims_surviving_verification, "
        "verified_at = now() "
        "WHERE run_id = :run_id "
        "AND provider = :provider "
        "AND group_id IS NOT DISTINCT FROM :group_id "
        "AND client_question IS NOT DISTINCT FROM :client_question"
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            result = await session.execute(stmt, params)
    return int(getattr(result, "rowcount", -1))


async def _insert_round(tenant_id: Any, params: dict[str, Any]) -> None:
    """One row into `workshop_round_yield`, under the tenant GUC."""
    from sqlalchemy import text as sql_text

    from nestor_pulse_sdk.db.base import get_sessionmaker
    from nestor_pulse_sdk.db.rls import set_tenant_context

    stmt = sql_text(
        "INSERT INTO workshop_round_yield "
        "(id, tenant_id, run_id, round_no, candidates_in, new_candidates, "
        "keep_count, weak_count, kill_count, new_entrants_top_n, barred_drops, "
        "round_cost_usd) VALUES "
        "(:id, :tenant_id, :run_id, :round_no, :candidates_in, :new_candidates, "
        ":keep_count, :weak_count, :kill_count, :new_entrants_top_n, "
        ":barred_drops, :round_cost_usd)"
    )

    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        async with session.begin():
            await set_tenant_context(session, tenant_id)
            await session.execute(stmt, params)


#: TEST SEAMS. Rebound by tests/test_yield_records.py to recorders. Never rebound
#: in production. Resolved as module globals at CALL time, which is what makes
#: `monkeypatch.setattr` work without threading a parameter through every caller.
_assignment_writer: Callable[..., Any] = _insert_assignment
_assignment_completer: Callable[..., Any] = _update_assignment
_round_writer: Callable[..., Any] = _insert_round


# ===========================================================================
# Public surface. 15.8-09 and 15.8-10 call the `_safe` trio and NOTHING else,
# and they pass RAW VALUES ON BOTH PATHS -- this module owns normalisation and
# therefore owns key symmetry, because a caller cannot.
# ===========================================================================


async def record_assignment(
    run_id: Any,
    tenant_id: Any,
    *,
    provider: Any,
    group_id: Any,
    client_question: Any,
    parent_kind: Any,
    stakes: Any,
    fact_list_parsed: Any,
    retry_used: Any,
    claims_kept: Any,
    resolvable_sources: Any,
    cost_usd: Any,
    duration_s: Any,
) -> None:
    """INSERT one `assignment_yield` row. Never raises, never discards a row.

    `claims_surviving_verification` is DELIBERATELY NOT A PARAMETER: it is not
    known at this point in the run. `complete_assignment` fills it later, keyed
    on the natural key this function's `_natural_key` call establishes.
    """
    try:
        key = _natural_key(run_id, provider, group_id, client_question)
        params = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            **key,
            # Clamped, never dropped (D-W5-10). Not a key member, so it is
            # normalised here on the INSERT path only.
            "parent_kind": _normalise_parent_kind(
                parent_kind, run_id=run_id, provider=key["provider"]
            ),
            "stakes": _normalise_label(stakes),
            "fact_list_parsed": _coerce_bool(fact_list_parsed),
            "retry_used": _coerce_bool(retry_used),
            "claims_kept": _coerce_int(claims_kept),
            "resolvable_sources": _coerce_int(resolvable_sources),
            "cost_usd": _coerce_decimal(cost_usd),
            "duration_s": _coerce_decimal(duration_s),
        }
        await _assignment_writer(tenant_id, params)
    except Exception as exc:  # noqa: BLE001 -- a yield write may never fail a run
        log.warning(
            "yield_records.record_assignment failed (run=%s provider=%r): %r -- "
            "row lost, NOT retried; the run is unaffected",
            run_id, provider, exc,
        )
    return None


async def complete_assignment(
    run_id: Any,
    tenant_id: Any,
    *,
    provider: Any,
    group_id: Any,
    client_question: Any,
    claims_surviving_verification: Any,
) -> None:
    """UPDATE the verification half of an `assignment_yield` row. Never raises.

    TAKES THE SAME RAW VALUES `record_assignment` TOOK and normalises them
    ITSELF, through the SAME `_natural_key`. A caller that "helpfully" cleaned a
    value first would reintroduce the mismatch this function exists to avoid.
    """
    try:
        params = {
            **_natural_key(run_id, provider, group_id, client_question),
            "claims_surviving_verification": _coerce_int(
                claims_surviving_verification
            ),
        }
        affected = await _assignment_completer(tenant_id, params)
        rows = _coerce_int(affected)
        if rows != 1:
            # ⚠ THE `0` READING BELOW IS ONLY TRUSTWORTHY BECAUSE `_natural_key`
            # IS SHARED BY BOTH HALVES. If a later refactor lets this function
            # build its key from RAW values while the INSERT stored normalised
            # ones, the UPDATE matches nothing, `rows` is 0, and THIS WARNING
            # THEN LIES -- it would blame a missing INSERT for what is really an
            # asymmetric key. Do not remove the shared helper and leave this
            # sentence standing.
            log.warning(
                "yield_records.complete_assignment: affected %r rows, expected "
                "exactly 1 (run=%s provider=%r). 0 means the INSERT half never "
                "landed -- a reading that holds ONLY because both halves build "
                "the key through _natural_key. >1 means divide()'s doubled "
                "high-stakes fallback row, where a SUM over "
                "claims_surviving_verification would DOUBLE-COUNT.",
                affected, run_id, provider,
            )
    except Exception as exc:  # noqa: BLE001 -- a yield write may never fail a run
        log.warning(
            "yield_records.complete_assignment failed (run=%s provider=%r): %r "
            "-- verification count lost, NOT retried; the run is unaffected",
            run_id, provider, exc,
        )
    return None


async def record_round(
    run_id: Any,
    tenant_id: Any,
    *,
    round_no: Any,
    candidates_in: Any,
    new_candidates: Any,
    keep_count: Any,
    weak_count: Any,
    kill_count: Any,
    new_entrants_top_n: Any,
    barred_drops: Any,
    round_cost_usd: Any,
) -> None:
    """INSERT one `workshop_round_yield` row. Never raises, never discards.

    `keep_count` is the KEEP CRITIQUE-VERDICT count and NOT the winner-set size
    (`len(entries)`); `barred_drops` is the BARRED CAUSE ONLY (D-W5-6). This
    module binds what it is given -- getting either one right is the CALLER's
    obligation, and both are stated here because a plausible wrong binding is
    unrecoverable in the one measuring run.
    """
    try:
        params = {
            "id": str(uuid.uuid4()),
            "tenant_id": str(tenant_id),
            "run_id": str(run_id),
            "round_no": _coerce_int(round_no),
            "candidates_in": _coerce_int(candidates_in),
            "new_candidates": _coerce_int(new_candidates),
            "keep_count": _coerce_int(keep_count),
            "weak_count": _coerce_int(weak_count),
            "kill_count": _coerce_int(kill_count),
            "new_entrants_top_n": _coerce_int(new_entrants_top_n),
            "barred_drops": _coerce_int(barred_drops),
            "round_cost_usd": _coerce_decimal(round_cost_usd),
        }
        await _round_writer(tenant_id, params)
    except Exception as exc:  # noqa: BLE001 -- a yield write may never fail a run
        log.warning(
            "yield_records.record_round failed (run=%s round=%r): %r -- row "
            "lost, NOT retried; the run is unaffected",
            run_id, round_no, exc,
        )
    return None


# ---------------------------------------------------------------------------
# The `_safe` trio. A PIPELINE MODULE MAY CALL NOTHING ELSE.
# ---------------------------------------------------------------------------


async def record_assignment_safe(
    run_id: Any, tenant_id: Any, *, build: "Callable[[], dict]"
) -> None:
    """INSERT one row whose FIELDS ARE BUILT INSIDE THIS FUNCTION'S TRY.

    THE REASON THIS EXISTS is a control-flow fact that is easy to talk past:

        A CALLER'S ARGUMENTS ARE EVALUATED BEFORE THE CALLEE IS ENTERED.

    So wrapping `record_assignment`'s BODY in try/except protects nothing against
    the expression that produced its arguments. Written the obvious way,

        await record_assignment(rid, tid, claims_kept=result["facts"], ...)

    a degrading provider that returns a short dict raises `KeyError` AT THE CALL
    SITE, inside the paid angle loop, and no defensive code inside this module
    can catch it. The yield fields are built from exactly the provider-shaped
    dicts most likely to arrive malformed, so this is not hypothetical.

    Passing a ZERO-ARGUMENT CALLABLE moves that construction inside the try
    below::

        await yield_records.record_assignment_safe(
            run_id, tenant_id,
            build=lambda: {"provider": stream, "group_id": angle.corroboration_key,
                           "client_question": angle.facet, "parent_kind": kind,
                           "stakes": angle.stakes, "claims_kept": result["facts"],
                           ...},
        )

    ONE `try/except` WRAPS BOTH THE `build()` CALL AND THE AWAITED CALL THAT
    FOLLOWS IT. DO NOT "tidy" this by assigning `build()` to a local above the
    try -- that hoists the evaluation back out of the protected region and
    reintroduces the entire defect while looking correct.

    A `build()` returning a non-dict is THE ONE AND ONLY CASE where nothing is
    written: there are no field values to salvage. It is logged, never
    `**`-unpacked blindly.
    """
    try:
        built = build()
        if not isinstance(built, dict):
            log.warning(
                "yield_records.record_assignment_safe: build() returned %s, not "
                "a dict -- nothing written (run=%s). There are no field values "
                "to salvage; this is the only unwritten-row case in this module.",
                type(built).__name__, run_id,
            )
            return None
        await record_assignment(run_id, tenant_id, **built)
    except Exception as exc:  # noqa: BLE001 -- D-06 at the CALL SITE
        log.warning(
            "yield_records.record_assignment_safe: building or writing a yield "
            "row raised %s (run=%s) -- row lost, run unaffected",
            type(exc).__name__, run_id,
        )
    return None


async def complete_assignment_safe(
    run_id: Any, tenant_id: Any, *, build: "Callable[[], dict]"
) -> None:
    """UPDATE the verification half, with the fields built inside the try.

    Same control-flow reasoning as `record_assignment_safe`. ONE `try` wraps BOTH
    `build()` and the awaited call; do not hoist `build()` above it.
    """
    try:
        built = build()
        if not isinstance(built, dict):
            log.warning(
                "yield_records.complete_assignment_safe: build() returned %s, "
                "not a dict -- nothing written (run=%s)",
                type(built).__name__, run_id,
            )
            return None
        await complete_assignment(run_id, tenant_id, **built)
    except Exception as exc:  # noqa: BLE001 -- D-06 at the CALL SITE
        log.warning(
            "yield_records.complete_assignment_safe: building or writing raised "
            "%s (run=%s) -- verification count lost, run unaffected",
            type(exc).__name__, run_id,
        )
    return None


async def record_round_safe(
    run_id: Any, tenant_id: Any, *, build: "Callable[[], dict]"
) -> None:
    """INSERT one round row, with the fields built inside the try.

    Same control-flow reasoning as `record_assignment_safe`. ONE `try` wraps BOTH
    `build()` and the awaited call; do not hoist `build()` above it.
    """
    try:
        built = build()
        if not isinstance(built, dict):
            log.warning(
                "yield_records.record_round_safe: build() returned %s, not a "
                "dict -- nothing written (run=%s)",
                type(built).__name__, run_id,
            )
            return None
        await record_round(run_id, tenant_id, **built)
    except Exception as exc:  # noqa: BLE001 -- D-06 at the CALL SITE
        log.warning(
            "yield_records.record_round_safe: building or writing a round row "
            "raised %s (run=%s) -- row lost, run unaffected",
            type(exc).__name__, run_id,
        )
    return None
