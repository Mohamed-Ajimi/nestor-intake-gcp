"""Resolve gemini grounding redirects to their publisher URLs (D-V01-11).

WHY THIS EXISTS
---------------
Every grounded-search citation Gemini returns is an opaque
`https://vertexaisearch.cloud.google.com/grounding-api-redirect/...` URL, and
those redirects EXPIRE roughly 30 days after the run that produced them. On run
7dcf51d5 (V-01, 2026-07-28) there were 642 citation instances collapsing to 225
unique redirects, and all 225 resolved cleanly through a single plain `302`.
Without this module every report ever delivered with a gemini citation is on a
timer: the prose survives, the evidence behind it turns into a dead link.

So the publisher URL is captured AT INGEST and stored ALONGSIDE the redirect
(`source.resolved_url`, migration 0016) — never instead of it. `source.url`
remains exactly what the provider returned.

THIS IS AN ENRICHMENT. IT IS ALLOWED TO FAIL. IT MUST NEVER DELAY OR ENDANGER
PERSISTENCE.
-----------------------------------------------------------------------------
Two rules follow from that sentence, and both have been broken by well-meaning
edits elsewhere in this repository, so they are written down here rather than
left to judgement:

1. **This module is called BEFORE the persistence session is opened**, in
   `pipeline/tribunal/pipeline.py` Stage 7 — never from inside
   `persist_tribunal_claims`, whose own docstring states that the CALLER owns the
   session and the transaction. Up to `NESTOR_REDIRECT_RESOLVE_DEADLINE_S` of
   network I/O inside the final persistence transaction of a ~$50 run would hold
   a pooled connection with RLS tenant context set, and a hung socket there costs
   the run its claims. `tests/test_source_resolution.py` asserts the ORDERING —
   the last request completes before `session.begin()` is entered — precisely so
   that a future edit cannot quietly move it back inside.

2. **The bounds below stay.** They are defence in depth against stalling the run
   on its critical path, NOT the thing that made an in-transaction design safe.
   Do not remove the deadline on the grounds that the transaction is no longer
   open: this pre-pass still sits between the end of adjudication and the
   persistence of a paid run's claims, so an unbounded pre-pass is an unbounded
   stall.

NEVER DROP A CITATION
---------------------
A redirect that cannot be resolved maps to `None` here and is still upserted as a
source by the caller, marked `resolution_status='unresolved'`. "Attempted and
failed" and "never attempted" are two different facts and are never collapsed
into one — that distinction is the whole reason `source` carries two columns
rather than one.

THE `Location` HEADER IS UNTRUSTED (T-15.4-21)
---------------------------------------------
It is chosen by a remote host, and the value stored here is later rendered as a
CLICKABLE LINK in the superadmin citation panel. So it is accepted only when it
parses to an `http`/`https` scheme with a host and is at most 2048 chars — the
same control `facts.py::_parse_url_cell` applies, for the same reason. A
`javascript:` or `data:` target maps to None; it is never stored.

ENVIRONMENT KNOBS (the `grouping.py` idiom, read at CALL time so an operator can
change one without a code change, and so a test can set one):

    NESTOR_REDIRECT_RESOLVE_ENABLED      1      kill switch; 0 issues NO requests
    NESTOR_REDIRECT_RESOLVE_CONCURRENCY  8      in-flight HEAD requests
    NESTOR_REDIRECT_RESOLVE_TIMEOUT_S    5.0    per request
    NESTOR_REDIRECT_RESOLVE_DEADLINE_S   30.0   overall wall clock for the pass

This module has NO database seam of any kind — no session, no sqlalchemy import,
no sessionmaker. That absence is what makes the out-of-transaction placement
STRUCTURAL rather than a convention a later edit can break by accident, and
`test_source_resolution.py` asserts it.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from typing import Iterable, Optional
from urllib.parse import urlparse

import httpx

log = logging.getLogger(__name__)

#: The only two schemes a `Location` may carry. Mirrors `facts.py`'s http(s)-only
#: SOURCE_URL rule; anything else is a link we would render but must not.
_ALLOWED_SCHEMES = ("http", "https")

#: Same cap as `facts.py::_MAX_URL_CHARS`. A hostile Location is bounded before
#: it reaches a TEXT column and a rendered anchor.
_MAX_LOCATION_CHARS = 2048

#: Defaults for the four knobs above. Named constants so the docstring, the code
#: and the tests cannot drift.
_DEFAULT_ENABLED = True
_DEFAULT_CONCURRENCY = 8
_DEFAULT_TIMEOUT_S = 5.0
_DEFAULT_DEADLINE_S = 30.0


def _default_client_factory(timeout_s: float):
    """The real client: ONE hop, never followed automatically.

    `follow_redirects=False` is load-bearing twice over — it is what lets us read
    the first `Location` ourselves and validate it, and it is what caps a hostile
    redirect CHAIN at a single request (T-15.4-23).
    """
    return httpx.AsyncClient(follow_redirects=False, timeout=timeout_s)


#: TEST SEAM. A module-level name, so a test injects a hand-written duck-typed
#: async client (`async with` + `await .head(url)`) by monkeypatching this — no
#: network, no `respx`, no new dependency. Resolved at CALL time, deliberately.
_client_factory = _default_client_factory


def _env_flag(name: str, default: bool) -> bool:
    """A knob that is off only when it is explicitly off. Never raises."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in ("0", "false", "no", "off", "")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """A positive int knob. Garbage falls back to the default rather than raising:
    a mistyped env var must not be able to fail a paid run."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw.strip())
    except (TypeError, ValueError):
        log.warning("%s=%r is not an integer — using %d", name, raw, default)
        return default
    return max(value, minimum)


def _env_float(name: str, default: float, *, minimum: float = 0.1) -> float:
    """A positive float knob. Same never-raises rule as `_env_int`."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = float(raw.strip())
    except (TypeError, ValueError):
        log.warning("%s=%r is not a number — using %.1f", name, raw, default)
        return default
    return max(value, minimum)


def is_redirect_url(url: object) -> bool:
    """True when `url` is a gemini grounding redirect and nothing else.

    THE ONE definition of "would we ever request this", used by the resolver to
    decide what to fetch and by `citations/extractor.py` to decide whether a
    `None` in the resolved map means 'unresolved' (attempted, failed) or NULL
    (never attempted). Two copies of this predicate would let those two meanings
    drift apart, which is the one thing the two-column design exists to prevent.

    `VERTEX_REDIRECT_HOST` is imported function-locally from
    `pipeline/tribunal/facts.py` — the ONE definition of the host — so this
    module keeps no fork of it and no import-time dependency on the pipeline.
    """
    from nestor_pulse_sdk.pipeline.tribunal.facts import VERTEX_REDIRECT_HOST

    if not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:  # pragma: no cover — urlparse is total on str in practice
        return False
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False
    return (parsed.hostname or "").lower() == VERTEX_REDIRECT_HOST.lower()


def _validated_target(location: object) -> Optional[str]:
    """The `Location` header, or None. T-15.4-21 — this value becomes a link.

    A RELATIVE Location maps to None rather than being resolved against the
    request URL. That is a deliberate choice, not an omission: a relative target
    on the redirect host would resolve back to `vertexaisearch.cloud.google.com`,
    which is the very URL we are trying to escape, so storing it would be worse
    than storing nothing. All 225 observed Locations on run 7dcf51d5 were
    absolute.
    """
    if not isinstance(location, str):
        return None
    candidate = location.strip()
    if not candidate or len(candidate) > _MAX_LOCATION_CHARS:
        return None
    try:
        parsed = urlparse(candidate)
    except Exception:  # pragma: no cover — as above
        return None
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return None
    if not parsed.netloc:
        return None
    return candidate


def _location_of(response: object) -> Optional[str]:
    """The first `Location` header of a redirect response, defensively.

    Reads the status when the response carries one: a non-3xx response has no
    business supplying a redirect target. A duck-typed response without a
    `status_code` skips that check rather than failing it.
    """
    status = getattr(response, "status_code", None)
    if isinstance(status, int) and not (300 <= status < 400):
        return None
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    try:
        # httpx headers are case-insensitive; a plain dict fake may not be.
        value = headers.get("location")
        if value is None:
            value = headers.get("Location")
    except Exception:
        return None
    return value if isinstance(value, str) else None


def _unique_urls(urls: Iterable[str]) -> list[str]:
    """The deduped input, order preserved. THE 642 -> 225 step.

    Deduping here rather than per claim is the whole point of D-V01-11: the
    per-claim dedupe already in `persist_tribunal_claims` collapsed 642 instances
    to 642 requests, because the same redirect is cited by many claims.
    """
    seen: set[str] = set()
    ordered: list[str] = []
    for raw in urls or ():
        if not isinstance(raw, str):
            continue
        url = raw.strip()
        if not url or url in seen:
            continue
        seen.add(url)
        ordered.append(url)
    return ordered


async def resolve_redirects(urls: Iterable[str]) -> dict[str, Optional[str]]:
    """Map every URL in `urls` to its publisher URL, or to None.

    Returns a key for EVERY unique input URL. A `None` value means one of two
    things and the caller distinguishes them with `is_redirect_url`:
      * not a redirect host at all  -> never requested, stored as NULL;
      * a redirect that did not resolve -> stored as `'unresolved'`.

    NEVER RAISES, for any input — a hostile mapping, a malformed URL, a dead
    network, a missing `httpx`, or a blown deadline all degrade to None values.
    The one exception is `asyncio.CancelledError`, which is a BaseException and
    is deliberately allowed to propagate: a cancelled run must stay cancelled.
    """
    started = time.monotonic()
    resolved: dict[str, Optional[str]] = {}

    try:
        unique = _unique_urls(urls)
    except Exception as exc:
        log.warning("redirect resolution: could not read the URL set (%s) — skipping", exc)
        return {}

    for url in unique:
        resolved[url] = None
    if not unique:
        return resolved

    if not _env_flag("NESTOR_REDIRECT_RESOLVE_ENABLED", _DEFAULT_ENABLED):
        log.info(
            "redirect resolution DISABLED by NESTOR_REDIRECT_RESOLVE_ENABLED — "
            "%d unique url(s) stored unresolved, 0 requests issued",
            len(unique),
        )
        return resolved

    targets = [url for url in unique if is_redirect_url(url)]
    if not targets:
        log.info(
            "redirect resolution: %d unique url(s), none on the redirect host — "
            "0 requests issued",
            len(unique),
        )
        return resolved

    concurrency = _env_int("NESTOR_REDIRECT_RESOLVE_CONCURRENCY", _DEFAULT_CONCURRENCY)
    timeout_s = _env_float("NESTOR_REDIRECT_RESOLVE_TIMEOUT_S", _DEFAULT_TIMEOUT_S)
    deadline_s = _env_float("NESTOR_REDIRECT_RESOLVE_DEADLINE_S", _DEFAULT_DEADLINE_S)

    semaphore = asyncio.Semaphore(concurrency)
    deadline_hit = False

    async def _resolve_one(client: object, url: str) -> None:
        async with semaphore:
            try:
                response = await client.head(url)  # type: ignore[attr-defined]
            except Exception as exc:
                # A timeout, a connection error, a DNS failure. One dead citation
                # is not worth a line each at WARNING; the aggregate below is.
                log.debug("redirect resolution: %s failed (%s)", url[:120], exc)
                return
            target = _validated_target(_location_of(response))
            if target is not None:
                resolved[url] = target

    try:
        async with _client_factory(timeout_s) as client:
            await asyncio.wait_for(
                asyncio.gather(
                    *(_resolve_one(client, url) for url in targets),
                    return_exceptions=True,
                ),
                timeout=deadline_s,
            )
    except TimeoutError:
        # asyncio.TimeoutError IS the builtin from 3.11. Caught BEFORE the
        # generic Exception below so the deadline is reported as a deadline.
        deadline_hit = True
    except Exception as exc:
        log.warning("redirect resolution: the pass failed wholesale (%s)", exc)

    hits = sum(1 for url in targets if resolved.get(url))
    misses = len(targets) - hits
    log.info(
        "redirect resolution: %d unique url(s), %d on the redirect host, "
        "%d resolved, %d unresolved in %.1fs",
        len(unique), len(targets), hits, misses, time.monotonic() - started,
    )
    if deadline_hit:
        log.warning(
            "redirect resolution: hit the %.1fs deadline — %d of %d redirect(s) "
            "were left unresolved and are stored as the redirect alone",
            deadline_s, misses, len(targets),
        )
    if misses:
        # A citation that did not resolve is a NAMED loss, never a silent one:
        # its publisher URL will be gone once the redirect expires.
        log.warning(
            "redirect resolution: %d of %d redirect(s) did not resolve — those "
            "citations keep only the redirect, which expires ~30 days after the run",
            misses, len(targets),
        )
    return resolved
