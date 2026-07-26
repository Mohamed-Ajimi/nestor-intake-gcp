"""
StageFeed -- the single in-process OWNER of one stage's live feed rows (D15).

WHY THIS EXISTS (F9 / Pitfall 4). `set_stage` merges with `||`
(`stages.py:117-124`: `stage_detail = COALESCE(stage_detail,'{}') || :entry`), and
`||` REPLACES the whole top-level key. So every caller must hand `set_stage` the
COMPLETE `{"items":[...]}` list for its stage, built from its own snapshot. Today
that is safe only because the one writer is single-owner (`pipeline.py:453-465`,
`_angle_status`). The 15.2 engine fans out N concurrent agents inside a single
stage -- the question workshop, the own-researcher, the cross-provider merge -- and
with the current pattern each agent's write replaces the others' rows: last writer
wins, and rows the operator watched appear then vanish.

The fix is ownership, not a new writer. ONE StageFeed instance per stage key holds
the item list, mutations go through an `asyncio.Lock`, and the debounced writer
delegates the actual write to `runs.stages.set_stage`. This module opens NO database
session and issues NO SQL: `tenant_id` is bound at construction and is handed to
`set_stage`, which is the single place that binds the tenant GUC and runs the write
under FORCE RLS. Tenant scoping therefore stays in exactly one place -- a second
writer would be a second chance to get it wrong, which is the defect class this
project's security constraint names by name.

THE ROW SCHEMA IS NOT DEFINED HERE. It is `runs/schemas.py::StageDetailItem` /
`StageRetry` / `StageSummary` / `StageDetail`, which already declare
`task_prompt` / `cost_usd` / `facts` / `retry` / `audit_id` and already accept
`"retry"` as a status literal -- and the frontend's `toStageRows`
(`ResearchRunProgress.tsx:69-107`) already renders them. This module POPULATES that
contract; it does not restate it. Emitted key names must match those field names
exactly.

Every write is BEST-EFFORT and never raises, inheriting `set_stage`'s contract
(`stages.py:125-126`): a progress write must never break the pipeline that is
reporting it. But it is never silently green either -- every dropped row, clamped
value, out-of-range handle and swallowed writer exception is logged at WARNING with
run / stage / row identity, and feed OVERFLOW is rendered as a visible row in the
feed itself rather than truncated away.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from typing import Any, Optional, Sequence

from nestor_pulse_sdk.runs.stages import set_stage

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tunables. Same NESTOR_TRIBUNAL_* + os.environ.get(..., default) idiom as
# gates.py:76-81 / grouping.py:87-100, so the August retune needs no code change.
#   _FEED_DEBOUNCE_S  seconds of quiet before a dirty snapshot is written.
#   _FEED_PROMPT_MAX  characters of task_prompt kept per row (Pitfall 12: the
#                     angle queries are ~2.6 KB each and stage_detail is re-read
#                     on EVERY SSE poll).
#   _FEED_MAX_ITEMS   rows per stage before overflow is collapsed into one
#                     stated-in-words row.
# ---------------------------------------------------------------------------
_FEED_DEBOUNCE_S = float(os.environ.get("NESTOR_TRIBUNAL_FEED_DEBOUNCE_S", "0.75"))
_FEED_PROMPT_MAX = int(os.environ.get("NESTOR_TRIBUNAL_FEED_PROMPT_MAX", "400"))
_FEED_MAX_ITEMS = int(os.environ.get("NESTOR_TRIBUNAL_FEED_MAX_ITEMS", "200"))

#: Characters of `name` kept per row. Names are short display labels, not prose.
_FEED_NAME_MAX = 120

#: The five literals `StageDetailItem.status` accepts (`schemas.py:162`). Anything
#: else is CLAMPED rather than raising or passed through: caller-supplied strings
#: reach this class from code paths that derive them from model-influenced state,
#: and an out-of-vocabulary value would fail response validation at the API edge
#: far away from here (ASVS V5 enum clamping, same spirit as
#: group_skeptic._normalise_verdict).
_STATUS_VOCAB = ("running", "done", "retry", "failed", "pending")

_DEFAULT_STATUS = "pending"

#: Field names a caller may set on a row. Anything else is dropped with a WARNING
#: -- `StageDetailItem` allows extras, so an unfiltered kwargs splat would quietly
#: grow the JSONB column with typo'd keys the UI never reads.
_ROW_FIELDS = ("name", "status", "task_prompt", "cost_usd", "facts", "audit_id", "retry")

#: Sub-keys of `StageRetry` (`schemas.py:141-149`).
_RETRY_FIELDS = ("attempt", "max", "wait_s")


def truncate_task_prompt(text: object, limit: Optional[int] = None) -> Optional[str]:
    """Bound a feed row's `task_prompt` (Pitfall 12).

    The full prompt is never lost -- it is reachable through the tenant-scoped
    `GET /{run_id}/audit/{audit_id}` drill-down that the row's `audit_id` points at.
    What is bounded here is the copy that lives in `run.stage_detail`, a JSONB
    column read in full on every SSE poll of a running brief.

    Returns None for None/blank so the key is omitted from the emitted row rather
    than written as a JSON null. Coerces non-str defensively (never raises). When
    the text is longer than `limit`, returns the first `limit` characters plus a
    single U+2026 ellipsis, so the result is `limit + 1` characters and is visibly
    marked as cut rather than silently shortened.

    Shared deliberately: plans 15.2-10/11/12/13 reuse this rather than each
    re-implementing a truncation with a slightly different width.
    """
    if text is None:
        return None
    if not isinstance(text, str):
        try:
            text = str(text)
        except Exception:  # noqa: BLE001 -- a feed helper never raises
            return None
    text = text.strip()
    if not text:
        return None
    cap = _FEED_PROMPT_MAX if limit is None else int(limit)
    if cap <= 0:
        return None
    if len(text) <= cap:
        return text
    return text[:cap] + "…"


class StageFeed:
    """One stage key's feed rows, owned by one instance, written debounced.

    Usage (the contract plans 15.2-10/11/12/13/15/16 code against)::

        async with StageFeed(run_id=rid, tenant_id=tid, stage_key="workshop") as feed:
            handles = await feed.declare([a.name for a in agents])
            ...
            await feed.update(handles[i], status="running", task_prompt=q)
            await feed.mark_retry(handles[i], attempt=2, max=3, wait_s=1.5)
            await feed.update(handles[i], status="done", facts=7,
                              audit_id=audit_out["audit_id"],
                              cost_usd=audit_out["cost_usd"])
            await feed.set_summary(duration_s=12.4, actions=len(agents))

    `declare()` is the preferred entry point for a fan-out stage: it fixes row
    ORDER up front, so what the operator sees does not depend on which agent's task
    happened to be scheduled first.

    Row handles are opaque ints issued only by this instance. There is no
    addressing API by name and no cross-feed API: an agent cannot write into
    another stage's feed or overwrite another agent's row by guessing a label.
    """

    def __init__(
        self,
        *,
        run_id: uuid.UUID,
        tenant_id: uuid.UUID,
        stage_key: str,
        writer=None,
        debounce_s: Optional[float] = None,
    ) -> None:
        """
        Args:
            stage_key:  the ENGINE_STAGES key this feed owns. Bound here and never
                        taken from a row payload, so a row can never redirect a
                        write to another stage.
            writer:     defaults to `runs.stages.set_stage`. Exists ONLY so tests
                        can inject a recorder -- it is NOT a production seam, and
                        no production caller should pass it.
            debounce_s: seconds of quiet before a dirty snapshot is written.
        """
        self._run_id = run_id
        self._tenant_id = tenant_id
        self._stage_key = stage_key
        self._writer = writer if writer is not None else set_stage
        self._debounce_s = _FEED_DEBOUNCE_S if debounce_s is None else float(debounce_s)

        self._items: list[dict[str, Any]] = []
        self._summary: Optional[dict[str, Any]] = None
        self._lock = asyncio.Lock()
        self._dirty = False
        self._closed = False
        self._writer_task: Optional[asyncio.Task] = None
        #: Rows refused because the feed hit _FEED_MAX_ITEMS. Counted, not ignored.
        self._overflow = 0
        self._overflow_logged_at = 0

    # -- public mutations ---------------------------------------------------

    async def declare(
        self,
        names: Sequence[str],
        *,
        status: str = _DEFAULT_STATUS,
        task_prompts: Optional[Sequence[str]] = None,
    ) -> list[int]:
        """Append every row in ONE locked mutation; return handles in input order.

        This is the deterministic path (it mirrors `pipeline.py:445-452`, which
        declares every angle as `pending` up front). A fan-out stage should declare
        its whole roster before starting any agent, so row order is the roster's
        order rather than the event loop's scheduling order.
        """
        if not self._live("declare"):
            return []
        handles: list[int] = []
        async with self._lock:
            for i, name in enumerate(names):
                prompt = None
                if task_prompts is not None and i < len(task_prompts):
                    prompt = task_prompts[i]
                handle = self._append_locked(
                    {"name": name, "status": status, "task_prompt": prompt}
                )
                handles.append(handle)
            self._mark_dirty_locked()
        self._ensure_writer()
        return handles

    async def add(
        self,
        name: str,
        *,
        status: str = _DEFAULT_STATUS,
        task_prompt: Optional[str] = None,
        **fields: Any,
    ) -> int:
        """Append one row; return its handle (-1 if the feed is closed or full)."""
        if not self._live("add"):
            return -1
        async with self._lock:
            row = {"name": name, "status": status, "task_prompt": task_prompt}
            row.update(fields)
            handle = self._append_locked(row)
            self._mark_dirty_locked()
        self._ensure_writer()
        return handle

    async def update(self, handle: int, **fields: Any) -> None:
        """Merge `fields` into the row at `handle`.

        An out-of-range handle is logged at WARNING naming run / stage / handle and
        returns: it never raises, and it never appends a phantom row (which would
        put a nameless entry in the operator's view and hide the real bug).

        A field passed as None means "leave it alone", NOT "clear it": these calls
        are made from inside per-agent code that often passes an optional it does
        not have yet, and letting that null through would silently downgrade an
        already-`done` row back to `pending`.
        """
        if not self._live("update"):
            return
        fields = {k: v for k, v in fields.items() if v is not None}
        async with self._lock:
            if not isinstance(handle, int) or not (0 <= handle < len(self._items)):
                log.warning(
                    "StageFeed.update: handle %r out of range (run=%s stage=%s rows=%d) "
                    "-- row dropped, nothing written",
                    handle, self._run_id, self._stage_key, len(self._items),
                )
                return
            self._items[handle] = self._normalise_row(
                {**self._items[handle], **fields}, handle=handle
            )
            self._mark_dirty_locked()
        self._ensure_writer()

    async def mark_retry(
        self, handle: int, *, attempt: int, max: int, wait_s: float  # noqa: A002
    ) -> None:
        """Flag the row as retrying, with attempt / max / wait_s (R5).

        A retried call otherwise looks STALLED in the live feed -- the operator sees
        a row sitting at `running` with no explanation while a backoff sleeps.
        `"retry"` is already a legal `StageDetailItem.status` literal
        (`schemas.py:162`) and the frontend already renders the sub-state, so this
        needs zero schema and zero frontend work.

        This is the callback surface plan 15.2-02's `with_retry(on_retry=...)` binds
        to.
        """
        await self.update(
            handle,
            status="retry",
            retry={"attempt": attempt, "max": max, "wait_s": wait_s},
        )

    async def set_summary(
        self,
        *,
        duration_s: Optional[float] = None,
        actions: Optional[int] = None,
        items_read: Optional[int] = None,
        cost_usd: Any = None,
    ) -> None:
        """Set the stage's `StageSummary` rollup. None fields are omitted."""
        if not self._live("set_summary"):
            return
        summary: dict[str, Any] = {}
        if duration_s is not None:
            summary["duration_s"] = _coerce_float(duration_s)
        if actions is not None:
            summary["actions"] = _coerce_int(actions)
        if items_read is not None:
            summary["items_read"] = _coerce_int(items_read)
        if cost_usd is not None:
            # Decimal -> str, never float: StageSummary.cost_usd is `str | None`
            # and float() would lose the exact cent text.
            summary["cost_usd"] = str(cost_usd)
        summary = {k: v for k, v in summary.items() if v is not None}
        async with self._lock:
            self._summary = summary or None
            self._mark_dirty_locked()
        self._ensure_writer()

    # -- lifecycle ----------------------------------------------------------

    async def flush(self) -> None:
        """Cancel any pending debounce and write the current snapshot immediately."""
        await self._cancel_writer()
        async with self._lock:
            await self._write_locked()

    async def close(self) -> None:
        """Flush once, then make the feed INERT.

        Why inert and not merely idle: `set_stage` sets `run.current_stage` on
        EVERY write (`stages.py:119`). A late row arriving after the pipeline has
        moved on would drag the operator's view backwards onto a finished stage.
        After close, every mutation is a no-op logged at WARNING.
        """
        if self._closed:
            return
        try:
            await self.flush()
        finally:
            self._closed = True

    async def __aenter__(self) -> "StageFeed":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        # Close on the exception path too: a stage that failed mid-way should still
        # leave its partial feed persisted, not lose the rows explaining the failure.
        await self.close()

    # -- internals ----------------------------------------------------------

    def _live(self, op: str) -> bool:
        if self._closed:
            log.warning(
                "StageFeed.%s after close() ignored (run=%s stage=%s) -- a late write "
                "would re-pin run.current_stage onto a finished stage",
                op, self._run_id, self._stage_key,
            )
            return False
        return True

    def _append_locked(self, row: dict[str, Any]) -> int:
        """Append a normalised row under the caller-held lock; return its handle."""
        if len(self._items) >= _FEED_MAX_ITEMS:
            self._overflow += 1
            if self._overflow - self._overflow_logged_at >= 50 or self._overflow == 1:
                self._overflow_logged_at = self._overflow
                log.warning(
                    "StageFeed row cap %d reached (run=%s stage=%s): %d row(s) not "
                    "shown individually -- reported in the feed as a summary row",
                    _FEED_MAX_ITEMS, self._run_id, self._stage_key, self._overflow,
                )
            return -1
        self._items.append(self._normalise_row(row, handle=len(self._items)))
        return len(self._items) - 1

    def _normalise_row(self, row: dict[str, Any], *, handle: int) -> dict[str, Any]:
        """Coerce, clamp and prune one row. Never raises."""
        out: dict[str, Any] = {}

        for key, value in row.items():
            if key not in _ROW_FIELDS:
                log.warning(
                    "StageFeed: unknown row field %r dropped (run=%s stage=%s row=%d)",
                    key, self._run_id, self._stage_key, handle,
                )
                continue
            if value is None:
                # Omitted, not written as null: keeps the JSONB small and keeps a
                # legacy {name,status} row byte-identical to what ships today.
                continue

            if key == "name":
                text = _coerce_str(value)
                if text is not None:
                    out["name"] = text.strip()[:_FEED_NAME_MAX]
            elif key == "status":
                out["status"] = self._clamp_status(value, handle=handle)
            elif key == "task_prompt":
                prompt = truncate_task_prompt(value)
                if prompt is not None:
                    out["task_prompt"] = prompt
            elif key == "cost_usd":
                # str(), never float(): StageDetailItem.cost_usd is `str | None`
                # and a Decimal must reach JSONB with its exact text intact.
                out["cost_usd"] = str(value)
            elif key == "facts":
                facts = _coerce_int(value)
                if facts is not None:
                    out["facts"] = facts
            elif key == "audit_id":
                audit_id = _coerce_str(value)
                if audit_id is not None:
                    out["audit_id"] = audit_id
            elif key == "retry":
                retry = self._normalise_retry(value, handle=handle)
                if retry:
                    out["retry"] = retry

        # `name` is the only REQUIRED StageDetailItem field; a nameless row would
        # fail validation at the API edge, so it is named here instead.
        if "name" not in out:
            out["name"] = f"row {handle}"
        out.setdefault("status", _DEFAULT_STATUS)
        return out

    def _clamp_status(self, value: Any, *, handle: int) -> str:
        text = _coerce_str(value)
        if text in _STATUS_VOCAB:
            return text  # type: ignore[return-value]
        log.warning(
            "StageFeed: status %r is not one of %s -- clamped to %r "
            "(run=%s stage=%s row=%d)",
            value, _STATUS_VOCAB, _DEFAULT_STATUS,
            self._run_id, self._stage_key, handle,
        )
        return _DEFAULT_STATUS

    def _normalise_retry(self, value: Any, *, handle: int) -> dict[str, Any]:
        if not isinstance(value, dict):
            log.warning(
                "StageFeed: retry payload %r is not a dict -- dropped "
                "(run=%s stage=%s row=%d)",
                value, self._run_id, self._stage_key, handle,
            )
            return {}
        out: dict[str, Any] = {}
        for key in _RETRY_FIELDS:
            raw = value.get(key)
            if raw is None:
                continue
            coerced = _coerce_float(raw) if key == "wait_s" else _coerce_int(raw)
            if coerced is not None:
                out[key] = coerced
        return out

    def _mark_dirty_locked(self) -> None:
        self._dirty = True

    def _snapshot_locked(self) -> dict[str, Any]:
        """Build the `StageDetail` dict handed to `set_stage(detail=...)`."""
        items = list(self._items)
        if self._overflow:
            # Fail LOUD, in the operator's own view: the dropped rows are stated
            # as a row rather than silently absent (cross-cutting rule 6).
            items.append({
                "name": (
                    f"+{self._overflow} more agent(s) not shown "
                    f"(feed row cap {_FEED_MAX_ITEMS})"
                ),
                "status": "done",
            })
        snapshot: dict[str, Any] = {"items": items}
        if self._summary:
            snapshot["summary"] = dict(self._summary)
        return snapshot

    async def _write_locked(self) -> None:
        """Write the snapshot if dirty. Caller MUST hold the lock. Never raises."""
        if not self._dirty:
            return
        snapshot = self._snapshot_locked()
        self._dirty = False
        try:
            await self._writer(
                self._run_id, self._tenant_id, self._stage_key, detail=snapshot
            )
        except asyncio.CancelledError:
            # A cancelled write leaves the snapshot unwritten -- re-arm so a later
            # flush() still persists it rather than losing the rows.
            self._dirty = True
            raise
        except Exception as exc:  # noqa: BLE001 -- progress writes are best-effort
            log.warning(
                "StageFeed write failed (run=%s stage=%s rows=%d): %r",
                self._run_id, self._stage_key, len(snapshot.get("items", [])), exc,
            )

    def _ensure_writer(self) -> None:
        task = self._writer_task
        if task is None or task.done():
            try:
                self._writer_task = asyncio.create_task(self._writer_loop())
            except RuntimeError as exc:
                # No running loop (a sync caller). Not fatal: flush() will write.
                log.warning(
                    "StageFeed could not schedule its writer (run=%s stage=%s): %r",
                    self._run_id, self._stage_key, exc,
                )

    async def _writer_loop(self) -> None:
        """Wait out the debounce, then write one full snapshot under the lock.

        The write happens INSIDE the lock deliberately. Holding it across the await
        serialises the full-snapshot writes, so a slow write cannot be overtaken by
        a newer one -- which is the exact last-writer-wins defect (F9) this class
        exists to prevent. Debouncing keeps the write frequency low enough that the
        serialisation stall is not material.
        """
        try:
            await asyncio.sleep(self._debounce_s)
            async with self._lock:
                await self._write_locked()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "StageFeed writer loop failed (run=%s stage=%s): %r",
                self._run_id, self._stage_key, exc,
            )

    async def _cancel_writer(self) -> None:
        task, self._writer_task = self._writer_task, None
        if task is None or task.done():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "StageFeed writer task ended badly (run=%s stage=%s): %r",
                self._run_id, self._stage_key, exc,
            )


# ---------------------------------------------------------------------------
# Defensive coercions. Every one returns None rather than raising: a feed row is
# telemetry, and telemetry must not be able to abort the work it describes.
# ---------------------------------------------------------------------------
def _coerce_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return str(value)
    except Exception:  # noqa: BLE001
        return None


def _coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value)
    except Exception:  # noqa: BLE001
        return None


def _coerce_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except Exception:  # noqa: BLE001
        return None
