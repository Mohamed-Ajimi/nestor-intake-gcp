"""R3 checkpoints for the research engine — Phase 15.2 (plan 15.2-16).

WHAT THIS IS. A ~$45 Tribunal run used to be worth nothing the moment the
Anthropic account hit its monthly cap: the worker wrote `failed` and every paid
deep-research report, every gate decision and every skeptic session went in the
bin. R3 records the result of each paid stage as it completes, so a run that
PARKS (D-17, `reliability.terminal_state`) can be resumed and re-use everything
it already paid for.

NO NEW TABLE AND NO MIGRATION. Every checkpoint payload is an
`Output(format="ckpt_<key>")` row written through `pipeline._write_output`, the
primitive that has persisted the `report_spec` and `synthesis_cache` rows since
Phase 15.1. Those two are the PRE-EXISTING checkpoints owned by the resume
branch at the top of `TribunalPipeline.run()`; they have their own short-circuit
to synthesis and are deliberately ABSENT from `CHECKPOINT_KEYS` below, so this
store can never shadow, discard or double-write them.

WHY THIS MODULE HOLDS NO DATABASE CODE. `CheckpointStore` takes its `read` and
`write` as injected awaitables already bound to `(run_id, tenant_id)` by the
caller. That is what lets the whole R3 contract be proven with a plain dict in a
keyless, Docker-less, network-less test — and it is why nothing in this file
opens a connection or imports a session factory.

EVERY PARAMETER IS ENV-TUNABLE via the `NESTOR_TRIBUNAL_*` idiom copied from
`reliability.py` and `gates.py`, so August's live calibration can retune the
size bound or switch checkpointing off without a code change and a new image.

Cloud Build gate for this module's tests:
    gcloud builds submit tribunal --config=tribunal/cloudbuild.test-engine.yaml \
        --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Sequence

log = logging.getLogger(__name__)

#: Envelope version. Bump this when the SHAPE of a checkpoint payload changes.
#: `load()` DISCARDS any stored envelope written under a different version, which
#: is not a nicety: a run may park before 2026-08-01 and be resumed after a
#: redeploy, and replaying a payload the current code cannot read is worse than
#: re-running the stage (T-15.2-128).
CHECKPOINT_VERSION = 1

#: The eight resumable stages, in pipeline order. `park` is last because it is a
#: MARKER, not resumable work — see `resumed()`.
#:
#: The two pre-existing checkpoints are deliberately NOT members; see the module
#: docstring for why.
CHECKPOINT_KEYS: tuple[str, ...] = (
    "workshop",
    "angles",
    "research",
    "provider_jobs",
    "merge",
    "gates",
    "verify",
    "park",
)


def ckpt_format(key: str) -> str:
    """The `Output.format` string for a checkpoint key (`gates` -> `ckpt_gates`).

    One prefix, written once, so no call site types a format literal that can
    drift from `CHECKPOINT_KEYS`.
    """
    return f"ckpt_{key}"


#: Refusal bound on ONE encoded checkpoint payload (T-15.2-131). A refused
#: checkpoint costs a re-run of that stage on resume; an unbounded one costs a
#: failed transaction in the middle of a paid run.
CKPT_MAX_BYTES = int(os.environ.get("NESTOR_TRIBUNAL_CKPT_MAX_BYTES", "16000000"))

#: Master switch. With this false the store reads nothing and writes nothing, and
#: every run behaves exactly as it did before 15.2-16.
CKPT_ENABLED = os.environ.get("NESTOR_TRIBUNAL_CHECKPOINTS", "true").lower() == "true"


# ---------------------------------------------------------------------------
# The angle digest — the correctness guard that makes index-keyed resume safe.
# ---------------------------------------------------------------------------


def angles_digest(angles: Sequence[Any] | None) -> str:
    """A stable fingerprint of an angle list, derived from each angle's `query`.

    THIS IS A CORRECTNESS GUARD, not an optimisation. `ckpt_research` records
    results keyed by ANGLE INDEX (DEC-1), so replaying it against a DIFFERENT
    angle list would attach stream A's answer to question B — a wrong report
    that looks perfectly healthy. If the question workshop or `divide()` produced
    a different list on the resumed run, the digest differs, the payload is
    discarded and the stage runs fresh (T-15.2-123).

    Never raises: a non-dict entry contributes the empty string rather than
    blowing up a resume.
    """
    try:
        queries: list[str] = []
        for angle in angles or ():
            try:
                queries.append(str((angle or {}).get("query") or ""))
            except Exception:  # noqa: BLE001 — a non-dict entry is not an error here
                queries.append("")
        blob = json.dumps(queries, ensure_ascii=False)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
    except Exception:  # noqa: BLE001 — a digest that raises is worse than a coarse one
        return ""


# ---------------------------------------------------------------------------
# The provider job-id guard (T-15.2-125).
# ---------------------------------------------------------------------------

#: Bounded whitelist: alphanumerics plus underscore, dot, colon and hyphen.
#: NOT a deny-list — an unrecognised character is rejected, never passed through.
_JOB_ID_RE = re.compile(r"\A[A-Za-z0-9_.:-]{1,200}\Z")


def safe_job_id(value: Any) -> str | None:
    """Return `value` as a job id, or `None` if it is not one. Never raises.

    WHY THIS EXISTS. A provider-supplied job id is interpolated into a URL PATH
    — the Gemini poll is `GET .../interactions/{interaction_id}` — so an id
    containing `/` or a `..` segment is path traversal against the provider API,
    and this plan additionally PERSISTS ids and replays them from an `output`
    row on resume. So the guard is applied on the way IN (before an id is
    recorded) and on the way OUT (before a recorded id reaches a URL): a
    poisoned row cannot reach the URL builder either.

    A rejection is logged at WARNING with the offending value truncated to 80
    characters, and returns `None` so the caller degrades in words rather than
    crashing (ASVS V5 — never trust third-party text, never raise from the
    parser).
    """
    try:
        text = str(value or "").strip()
    except Exception:  # noqa: BLE001
        text = ""
    if not text:
        return None
    if not _JOB_ID_RE.match(text):
        log.warning(
            "checkpoints.safe_job_id: REFUSED a provider job id that is not a "
            "bounded alphanumeric token — it will not be persisted and will not "
            "reach a URL: %r",
            text[:80],
        )
        return None
    return text


# ---------------------------------------------------------------------------
# The store.
# ---------------------------------------------------------------------------


class CheckpointStore:
    """One run's R3 checkpoints, over injected read/write awaitables.

    ONE STORE PER RUN, NEVER A MODULE-LEVEL GLOBAL. The cache below holds one
    run's stage results; a shared instance would hand one run's research to
    another and, in a multi-tenant system, across tenants — the same rule
    `reliability.BreakerSet` states for breaker state.

    TENANT ISOLATION (T-15.2-129). This class performs no database access of its
    own. Its `write` is bound by the caller to `pipeline._write_output`, which
    runs under `set_tenant_context` and stamps `tenant_id`, so every checkpoint
    is an ordinary `output` row inheriting that table's existing FORCE-RLS
    policy. No new table, no new policy, no new grant — and therefore no new
    isolation surface to get wrong.

    Args:
        read:    awaitable taking the `Output.format` string, returning the
                 parsed payload or `None`.
        write:   awaitable taking the format string and the payload.
        enabled: master switch; defaults to `CKPT_ENABLED`.
    """

    def __init__(
        self,
        *,
        read: Callable[[str], Awaitable[Any]],
        write: Callable[[str, Any], Awaitable[None]],
        enabled: bool = CKPT_ENABLED,
    ) -> None:
        self._read = read
        self._write = write
        self.enabled = bool(enabled)
        self._cache: dict[str, dict[str, Any]] = {}
        #: Keys successfully restored by the last `load()`, in `CHECKPOINT_KEYS`
        #: order. Public so the pipeline can name them in its WARNING line.
        self.restored_keys: list[str] = []

    # -- reading -----------------------------------------------------------

    async def load(self) -> list[str]:
        """Read every checkpoint key for this run. Returns `restored_keys`.

        A payload that is not a dict, or whose `v` differs from
        `CHECKPOINT_VERSION`, is DISCARDED with a WARNING naming the key and the
        version found (T-15.2-128). Never raises — a failed checkpoint read must
        cost a re-run of a stage, never the run.
        """
        self._cache = {}
        self.restored_keys = []
        if not self.enabled:
            log.info(
                "checkpoints: disabled by NESTOR_TRIBUNAL_CHECKPOINTS — this run "
                "will not restore or record any stage result"
            )
            return self.restored_keys

        for key in CHECKPOINT_KEYS:
            try:
                payload = await self._read(ckpt_format(key))
            except Exception as exc:  # noqa: BLE001 — a read failure is not a run failure
                log.warning(
                    "checkpoints: could not read %s (%r) — that stage will run fresh",
                    ckpt_format(key), exc,
                )
                continue
            if payload is None:
                continue
            if not isinstance(payload, dict):
                log.warning(
                    "checkpoints: DISCARDED %s — the stored payload is a %s, not "
                    "an envelope; that stage will run fresh",
                    ckpt_format(key), type(payload).__name__,
                )
                continue
            found_version = payload.get("v")
            if found_version != CHECKPOINT_VERSION:
                log.warning(
                    "checkpoints: DISCARDED %s — it was written under checkpoint "
                    "version %r and this build reads version %d; that stage will "
                    "run fresh rather than replay a payload this code cannot "
                    "safely read",
                    ckpt_format(key), found_version, CHECKPOINT_VERSION,
                )
                continue
            self._cache[key] = payload
            self.restored_keys.append(key)

        if self.restored_keys:
            log.warning(
                "checkpoints: RESTORED %d checkpoint(s) for this run: %s — the "
                "stages they cover were already paid for and will not be "
                "re-dispatched",
                len(self.restored_keys), ", ".join(self.restored_keys),
            )
        return self.restored_keys

    def get(self, key: str) -> Any:
        """The restored `data` for `key`, or `None`.

        An unknown key raises `KeyError` ON PURPOSE: a typo must not read as
        "there is no checkpoint" and silently re-charge a stage.
        """
        self._require_key(key)
        envelope = self._cache.get(key)
        if not isinstance(envelope, dict):
            return None
        return envelope.get("data")

    def digest_of(self, key: str) -> str | None:
        """The digest recorded alongside `key`'s payload, or `None`."""
        self._require_key(key)
        envelope = self._cache.get(key)
        if not isinstance(envelope, dict):
            return None
        digest = envelope.get("digest")
        return digest if isinstance(digest, str) else None

    def has(self, key: str) -> bool:
        """True when `key` was restored by `load()` (or written by `put()`)."""
        self._require_key(key)
        return key in self._cache

    def resumed(self) -> bool:
        """True when this run restored resumable WORK.

        `park` alone does not count. A park marker records why a run stopped; it
        is not a stage result, and treating it as one would make a run that
        parked before its first paid stage report itself as "resumed" and skip
        the feed rows that tell the operator what was actually re-used.
        """
        return any(key != "park" for key in self.restored_keys)

    # -- writing -----------------------------------------------------------

    async def put(
        self,
        key: str,
        data: Any,
        *,
        digest: str | None = None,
        max_bytes: int | None = None,
    ) -> bool:
        """Record `data` under `key`. Returns True iff it was written.

        Wraps the payload in the version envelope, measures the encoded JSON and
        REFUSES anything over `CKPT_MAX_BYTES`, naming the byte count and the
        limit at WARNING (T-15.2-131). Never raises: the underlying
        `_write_output` is already best-effort, and a checkpoint write must never
        break the paid stage it is recording.
        """
        self._require_key(key)
        if not self.enabled:
            return False

        limit = CKPT_MAX_BYTES if max_bytes is None else int(max_bytes)
        envelope = {
            "v": CHECKPOINT_VERSION,
            "digest": digest,
            "written_at": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        try:
            encoded = json.dumps(envelope, ensure_ascii=False, default=str)
        except Exception as exc:  # noqa: BLE001 — an unserialisable payload is not a crash
            log.warning(
                "checkpoints: REFUSED %s — the payload could not be encoded (%r); "
                "that stage will re-run on a resume",
                ckpt_format(key), exc,
            )
            return False

        size = len(encoded.encode("utf-8"))
        if size > limit:
            log.warning(
                "checkpoints: REFUSED %s — the encoded payload is %d bytes and the "
                "limit is %d (NESTOR_TRIBUNAL_CKPT_MAX_BYTES); nothing was written, "
                "so that stage will re-run on a resume",
                ckpt_format(key), size, limit,
            )
            return False

        try:
            await self._write(ckpt_format(key), envelope)
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "checkpoints: could not write %s (%r) — that stage will re-run on "
                "a resume",
                ckpt_format(key), exc,
            )
            return False

        self._cache[key] = envelope
        return True

    # -- internals ---------------------------------------------------------

    @staticmethod
    def _require_key(key: str) -> None:
        if key not in CHECKPOINT_KEYS:
            raise KeyError(
                f"{key!r} is not a checkpoint key; valid keys are "
                f"{', '.join(CHECKPOINT_KEYS)}"
            )


# ---------------------------------------------------------------------------
# DEC-5 — the park-sequence primitives.
# ---------------------------------------------------------------------------


def park_signature(stage: Any, reason: Any) -> str:
    """A short fingerprint of a park event: `(stage, redacted reason)`.

    Two parks with the SAME signature are the same event observed twice (a
    resume that hit the identical wall again, or two drivers scheduled for one
    park); a DIFFERENT signature is a new event that deserves its own
    notification. Never raises.
    """
    try:
        blob = f"{str(stage or '')}|{str(reason or '')}"
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()[:12]
    except Exception:  # noqa: BLE001
        return "0" * 12


def next_park_seq(prior: Any, signature: str) -> int:
    """The monotonic park sequence number for `signature`, given the prior park.

    `1` when there is no usable prior; the SAME `seq` when the prior park
    carries this signature; `prior["seq"] + 1` otherwise. Never raises.

    THE CONSUMER IS PLAN 15.2-19, not this plan: `finalize_parked` stamps
    `error_message` as `"[park#<seq>] <reason>"` and the intake poll driver skips
    the park mail when the mirror row already carries that exact marker prefix,
    so two drivers scheduled for one park event send one mail. This plan owns
    only the numbers and the `ckpt_park` row that carries them.
    """
    try:
        if not isinstance(prior, dict):
            return 1
        seq = prior.get("seq")
        if not isinstance(seq, int) or isinstance(seq, bool) or seq < 1:
            return 1
        if prior.get("signature") == signature:
            return seq
        return seq + 1
    except Exception:  # noqa: BLE001
        return 1
