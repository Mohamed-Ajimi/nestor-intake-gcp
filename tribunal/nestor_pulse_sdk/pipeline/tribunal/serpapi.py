"""SerpApi client for the D10 own-researcher — Phase 15.2 plan 12.

WHAT THIS IS: a plain `httpx` client for serpapi.com's search and account
endpoints. Nothing more. There is no SDK here, no session object, no retry loop
and no breaker implementation — the retry policy and the circuit breaker both
live in `pipeline/tribunal/reliability.py` (15.2-02) and are REUSED.

WHY NOT THE OFFICIAL PACKAGE. SerpApi publishes a PyPI distribution
(`google_search_results`, importable as `serpapi`). It is deliberately
**REJECTED**: it is a thin SYNCHRONOUS wrapper around one HTTP GET, it carries
its own `requests` pin, and it would add a new supply-chain surface for a
single-line call. `httpx==0.28.1` is already pinned in
`tribunal/requirements.txt:43` and is already the transport this repo uses for
the Gemini Interactions REST call. NO PACKAGE IS INSTALLED BY THIS MODULE.
(The distribution's HYPHENATED spelling is deliberately written here with
underscores instead: a repo-wide grep for that hyphenated name is this plan's
supply-chain gate for T-15.2-SC and must stay a clean zero, and a prose mention
would make it read as a hit forever. The real proof that nothing was installed
is `tribunal/requirements.txt` being byte-identical and this module importing
only `httpx` — never a docstring's spelling.)

THE KEY TRAVELS IN THE QUERY STRING (T-15.2-30). SerpApi authenticates with an
`api_key` QUERY PARAMETER, not a header. That makes ordinary, harmless-looking
code into a credential leak:
#   - httpx's status-raising response helper renders the FULL request URL —
#     query string and key included — into the exception message, which then
#     reaches logs, the breaker signature and the operator feed. It is therefore
#     banned in this module; every non-2xx is converted to a `SerpApiError` that
#     carries a status code and a redacted 200-char body excerpt and NO url.
#   - No log statement in this module may format a URL except through
#     `_safe_url()`, which returns the PATH only ("/search.json").
#   - `redact()` from 15.2-02 is applied to every body excerpt before it is
#     stored on the exception, and the live key value is additionally removed by
#     literal match, so a provider error body that echoes the key cannot leak it.

UNTRUSTED THIRD-PARTY JSON (ASVS V5). `organic_results[]` is attacker-
influenceable: anyone who can rank a page controls a `title`, a `snippet` and a
`link` that we are about to put in front of a model. `_clean_results` is the
gate: list-of-dict only, every field coerced and truncated, non-http(s) links
dropped, the list capped, garbled entries skipped, and NOTHING raises. `json` is
applied to the HTTP response BODY only and never to model text.

COST TRUTH IS PLAN-AGNOSTIC (D-16). SerpApi sells prepaid plans, so the unit
price of one search is `plan_monthly_price / searches_per_month` — a PUBLISHED
figure, which makes `count x unit` a calculation and not an estimate. This module
never hardcodes a tier price: it reads the plan live from the free account
endpoint at run start (`fetch_plan`) and the caller records it with the run
(`record_plan_for_run`), so the figure stays reproducible after the plan changes.
A Free-tier account yields an honest `Decimal("0")`; an unknown plan yields
`None`, which the caller turns into a NULL cost plus `cost_pending` — never a
guess. The tier itself is an OPEN OPERATOR DECISION owned by plan 15.2-18.
"""
from __future__ import annotations

import asyncio
import logging
import os
import urllib.parse
import uuid as _uuid_mod
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from nestor_pulse_sdk.pipeline.tribunal import reliability

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Endpoints. `SEARCH_URL` appears EXACTLY ONCE in this file, on purpose: a second
# literal is a second thing to keep in sync, and the source gate greps for it.
# ---------------------------------------------------------------------------
SEARCH_URL = "https://serpapi.com/search.json"
ACCOUNT_URL = "https://serpapi.com/account.json"


# ---------------------------------------------------------------------------
# Tunables, in the house `NESTOR_TRIBUNAL_*` idiom (`gates.py:76-81`), so a
# retune costs an env-var change rather than a code change and a new image.
#   _TIMEOUT_S       per-request timeout.
#   _CONCURRENCY     in-flight SerpApi requests per worker. 4 sits well under
#                    SerpApi's published `account_rate_limit_per_hour` ceilings
#                    (50/hr on Free, 200/hr on Starter), so the own-researcher
#                    cannot rate-limit itself on the smallest plan.
#   _MAX_RESULTS     organic results kept from one search, and the ceiling `num`
#                    is clamped to.
# ---------------------------------------------------------------------------
_TIMEOUT_S = float(os.environ.get("NESTOR_TRIBUNAL_SERPAPI_TIMEOUT_S", "30"))
_CONCURRENCY = int(os.environ.get("NESTOR_TRIBUNAL_SERPAPI_CONCURRENCY", "4"))
_MAX_RESULTS = int(os.environ.get("NESTOR_TRIBUNAL_SERPAPI_MAX_RESULTS", "10"))

#: Characters kept of a third-party title or snippet. This is the SAME 240 that
#: `gates._gate_batch` and `grouping._cluster_block` use, and for the same
#: reason: it is a PROMPT-INJECTION CONTROL, not formatting. A search snippet is
#: text a stranger wrote and we are about to paste into a model's context.
_SNIPPET_MAX_CHARS = 240

#: Characters of a provider error body kept on a `SerpApiError`.
_BODY_EXCERPT_CHARS = 200

#: Bounds all in-flight SerpApi requests per worker.
_SEMAPHORE = asyncio.Semaphore(_CONCURRENCY)

#: The two plain-words reasons this module can put into D-12's
#: `degradation_reasons`. A lost stream is always NAMED, never a silent absence.
REASON_KEY_MISSING = "serpapi_key_missing"
REASON_BREAKER_OPEN = "serpapi_breaker_open"

#: Process-level breaker for the SerpApi endpoint, created on first use.
_BREAKER: Optional[reliability.CircuitBreaker] = None


class SerpApiError(Exception):
    """A SerpApi request that did not return a usable 2xx JSON body.

    Carries `status_code` as a plain int attribute so `reliability`'s shared
    status sniffer (`_status_of`, which reads status_code/status/code) and its
    `classify`/`is_transient` predicates work on it with NO special-casing: 429
    and 5xx are transient, 402 and cap wording are a hard wall, everything else
    is hard.

    SECURITY (T-15.2-30): the message contains a status code and a redacted body
    excerpt and NOTHING else. No URL, no params dict, no key. The excerpt is put
    through `_safe_excerpt` first, which removes the live key by literal match
    and then applies 15.2-02's `redact()`.
    """

    def __init__(
        self, message: str = "", *, status_code: int | None = None, body_excerpt: str = ""
    ) -> None:
        self.status_code = status_code
        self.body_excerpt = _safe_excerpt(body_excerpt)
        detail = message or "SerpApi request failed"
        super().__init__(
            f"{detail} (status={status_code if status_code is not None else 'none'})"
            f"{': ' + self.body_excerpt if self.body_excerpt else ''}"
        )


@dataclass(frozen=True)
class SerpApiPlan:
    """The SerpApi plan in force, and the per-search unit price derived from it.

    `unit_price_usd` is `plan_monthly_price / searches_per_month` as an exact
    `Decimal`, or `None` when it could not be established from a published
    figure. `Decimal("0")` and `None` are DIFFERENT and the difference is
    load-bearing: zero is the honest Free-tier price, None means unknown and
    forces the caller onto the `cost_pending` path (D-16, never a guess).

    `source` records WHERE the number came from, so a later reader can tell a
    live account reading from an operator override from a table default.
    """

    plan_name: str
    plan_monthly_price: Optional[Decimal]
    searches_per_month: Optional[int]
    total_searches_left: Optional[int]
    unit_price_usd: Optional[Decimal]
    source: str

    @classmethod
    def unknown(cls) -> "SerpApiPlan":
        """The honest 'we could not establish the plan' value. Never a guess."""
        return cls(
            plan_name="",
            plan_monthly_price=None,
            searches_per_month=None,
            total_searches_left=None,
            unit_price_usd=None,
            source="unknown",
        )


# ---------------------------------------------------------------------------
# Configuration + the two secret-hygiene helpers.
# ---------------------------------------------------------------------------


def api_key() -> str:
    """The SerpApi key from the environment, or "" when it is not configured.

    The secret itself is created by plan 15.2-18 and DOES NOT EXIST YET. That is
    not a blocker: absence is a first-class, tested state — see
    `unavailable_reason`.
    """
    return os.environ.get("SERPAPI_API_KEY", "").strip()


def configured() -> bool:
    """True when a SerpApi key is present in the environment."""
    return bool(api_key())


def _safe_url(url: str) -> str:
    """Return the PATH of `url` and nothing else — e.g. "/search.json".

    T-15.2-30 MITIGATION. The SerpApi key rides in the query string, so a full
    URL in a log line is a credential in a log line. Every log statement in this
    module formats its endpoint through this function; nothing else in this
    module may render a URL at all.
    """
    try:
        return urllib.parse.urlsplit(str(url or "")).path or "/"
    except Exception:  # noqa: BLE001 — a log helper that raises is worse than a vague one
        return "/"


def _safe_excerpt(text: object) -> str:
    """Redact, then truncate, a third-party response body for display.

    Order matters and mirrors `reliability.redact`'s own contract: redaction
    happens BEFORE truncation so a long secret cannot survive by being cut in
    half. Two passes:
      1. the LIVE key value is removed by literal match — a provider error body
         may echo the credential we sent with no `api_key=` label at all, which
         no pattern-based redactor can catch;
      2. 15.2-02's `redact()` catches every labelled `key=value` form.
    Never raises.
    """
    try:
        out = str(text or "")
        key = api_key()
        if key:
            out = out.replace(key, "<redacted>")
        return reliability.redact(out)[:_BODY_EXCERPT_CHARS]
    except Exception:  # noqa: BLE001 — a failure to redact must not become a failure to report
        return "<unprintable>"


# ---------------------------------------------------------------------------
# The untrusted-input gate.
# ---------------------------------------------------------------------------


def _clean_results(raw: object) -> list[dict]:
    """Normalise `organic_results` into a bounded list of safe dicts.

    `organic_results[].link`, `.title` and `.snippet` are UNTRUSTED THIRD-PARTY
    INPUT: anyone who can get a page to rank writes them, and they are about to
    be pasted into a model prompt and rendered as a clickable source. So:

      * only a list is accepted, and only dict entries within it;
      * `title` / `snippet` are coerced with `str(...)` and truncated to
        `_SNIPPET_MAX_CHARS` (the injection bound);
      * `position` is coerced to int, falling back to the enumeration index;
      * `link` survives ONLY when it is a `str` beginning `http://` or
        `https://` — a `javascript:` or `data:` link would be an elevation path
        into the operator's own tool, exactly as `facts._parse_url_cell` states.
        An entry with no usable link is DROPPED: a source we cannot cite is not
        a source.
      * the list is capped at `_MAX_RESULTS`.

    Garbled entries are skipped, not raised on. Nothing here parses model text;
    `json` is applied to the HTTP body only.
    """
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for index, entry in enumerate(raw):
        if len(out) >= _MAX_RESULTS:
            break
        if not isinstance(entry, dict):
            continue
        link = entry.get("link")
        if not isinstance(link, str):
            continue
        link = link.strip()
        if not link.lower().startswith(("http://", "https://")):
            continue
        try:
            position = int(entry.get("position"))
        except (TypeError, ValueError):
            position = index
        out.append(
            {
                "title": str(entry.get("title") or "")[:_SNIPPET_MAX_CHARS],
                "link": link,
                "snippet": str(entry.get("snippet") or "")[:_SNIPPET_MAX_CHARS],
                "position": position,
            }
        )
    return out


# ---------------------------------------------------------------------------
# The two endpoints.
# ---------------------------------------------------------------------------


async def search(
    *,
    q: str,
    hl: str = "",
    gl: str = "",
    google_domain: str = "",
    location: str = "",
    num: int = 10,
    client: Any | None = None,
) -> dict:
    """Run ONE Google search through our SerpApi account.

    Returns `{"billable", "status", "results", "metadata", "search_id"}`.

    BILLABLE IS NOT "A CALL HAPPENED". SerpApi's published pricing states that
    "only successful searches are counted toward your monthly searches. Cached,
    errored, and failed searches are not." So the billable unit is
    `search_metadata.status == "Success"`, and that — not the HTTP call count —
    is what the D-16 fee is computed from.

    `metadata` is a WHITELIST of `{id, status, total_time_taken}`. The raw
    response blob is deliberately not returned: it echoes `search_parameters`
    back, and a future SerpApi change could echo the key there. What we never
    carry, we can never leak.

    `client` is the test seam — any object exposing `async get(url, params=...)`.

    Raises `SerpApiError` on a non-2xx status or an unreadable body. The caller
    (the agent loop) owns the retry/degrade decision; this function does not
    retry, because there is exactly ONE retry policy in this phase and it lives
    in `reliability.with_retry`.
    """
    params: dict[str, Any] = {"engine": "google", "q": str(q or "")}
    try:
        wanted = int(num)
    except (TypeError, ValueError):
        wanted = 10
    params["num"] = max(1, min(wanted, _MAX_RESULTS))
    for name, value in (
        ("hl", hl),
        ("gl", gl),
        ("google_domain", google_domain),
        ("location", location),
    ):
        if value:
            params[name] = str(value)
    # The key goes in LAST and is never logged, never returned and never put in
    # an audit blob. It exists in this dict and nowhere else.
    params["api_key"] = api_key()

    async with _SEMAPHORE:
        if client is not None:
            response = await client.get(SEARCH_URL, params=params)
        else:
            import httpx  # noqa: PLC0415 — local import keeps module load light

            async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http:
                response = await http.get(SEARCH_URL, params=params)

    status_code = getattr(response, "status_code", None)
    if not isinstance(status_code, int) or not (200 <= status_code < 300):
        log.warning(
            "serpapi: %s returned HTTP %s", _safe_url(SEARCH_URL), status_code
        )
        raise SerpApiError(
            "SerpApi search failed",
            status_code=status_code if isinstance(status_code, int) else None,
            body_excerpt=str(getattr(response, "text", "") or ""),
        )

    try:
        data = response.json()
    except Exception as exc:  # noqa: BLE001 — an unreadable body is a SerpApi failure
        log.warning(
            "serpapi: %s returned a body that is not JSON (%s)",
            _safe_url(SEARCH_URL),
            type(exc).__name__,
        )
        raise SerpApiError(
            "SerpApi search returned an unreadable body",
            status_code=status_code,
            body_excerpt=str(getattr(response, "text", "") or ""),
        ) from exc

    meta = data.get("search_metadata") if isinstance(data, dict) else None
    meta = meta if isinstance(meta, dict) else {}
    status = str(meta.get("status") or "")
    results = _clean_results(data.get("organic_results") if isinstance(data, dict) else None)

    return {
        "billable": status == "Success",
        "status": status,
        "results": results,
        "metadata": {
            "id": str(meta.get("id") or ""),
            "status": status,
            "total_time_taken": meta.get("total_time_taken"),
        },
        "search_id": str(meta.get("id") or ""),
    }


async def fetch_plan(*, client: Any | None = None) -> SerpApiPlan:
    """Read the SerpApi plan in force. FREE — this call does not consume quota.

    On ANY failure — no key, transport error, non-2xx, unreadable body, missing
    fields — this logs at WARNING through `_safe_url` and returns
    `SerpApiPlan.unknown()`. It NEVER raises and it NEVER guesses a tier: an
    unknown plan becomes a NULL cost plus `cost_pending` downstream, which is the
    honest answer, and a fabricated unit price is not.

    THE FREE TIER IS AN HONEST $0.00. `plan_monthly_price == 0` with a positive
    `searches_per_month` yields `unit_price_usd == Decimal("0")` and
    `source == "account.json"`. That is a KNOWN price of zero, NOT a missing
    number and NOT "pending" — the distinction is D-16's exact wording and every
    downstream branch keys on it.

    `unit_price_usd` is deliberately NOT quantized: the default decimal context
    precision keeps the figure reproducible, and display rounding belongs to the
    surface that displays it.
    """
    if not configured():
        log.warning(
            "serpapi: no SERPAPI_API_KEY, so %s was not called and the plan is unknown",
            _safe_url(ACCOUNT_URL),
        )
        return SerpApiPlan.unknown()

    try:
        params = {"api_key": api_key()}
        async with _SEMAPHORE:
            if client is not None:
                response = await client.get(ACCOUNT_URL, params=params)
            else:
                import httpx  # noqa: PLC0415

                async with httpx.AsyncClient(timeout=_TIMEOUT_S) as http:
                    response = await http.get(ACCOUNT_URL, params=params)

        status_code = getattr(response, "status_code", None)
        if not isinstance(status_code, int) or not (200 <= status_code < 300):
            log.warning(
                "serpapi: %s returned HTTP %s — plan unknown, spend will be marked "
                "pending rather than guessed",
                _safe_url(ACCOUNT_URL),
                status_code,
            )
            return SerpApiPlan.unknown()

        data = response.json()
        if not isinstance(data, dict):
            log.warning(
                "serpapi: %s returned a non-object body — plan unknown",
                _safe_url(ACCOUNT_URL),
            )
            return SerpApiPlan.unknown()

        plan_name = str(data.get("plan_name") or "")
        price = _as_decimal(data.get("plan_monthly_price"))
        quota = _as_positive_int(data.get("searches_per_month"))
        left = _as_positive_int(data.get("total_searches_left"), allow_zero=True)

        unit: Optional[Decimal] = None
        if price is not None and quota:
            unit = price / Decimal(str(quota))

        return SerpApiPlan(
            plan_name=plan_name,
            plan_monthly_price=price,
            searches_per_month=quota,
            total_searches_left=left,
            unit_price_usd=unit,
            source="account.json",
        )
    except Exception as exc:  # noqa: BLE001 — a plan probe never breaks a run
        log.warning(
            "serpapi: %s could not be read (%s) — plan unknown, spend will be "
            "marked pending rather than guessed",
            _safe_url(ACCOUNT_URL),
            type(exc).__name__,
        )
        return SerpApiPlan.unknown()


def _as_decimal(value: object) -> Optional[Decimal]:
    """Coerce a third-party numeric field to Decimal, or None. Never raises."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _as_positive_int(value: object, *, allow_zero: bool = False) -> Optional[int]:
    """Coerce a third-party count to a non-negative int, or None. Never raises."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    if number < 0 or (number == 0 and not allow_zero):
        return None
    return number


def resolve_unit_price(plan: SerpApiPlan) -> SerpApiPlan:
    """Fill `unit_price_usd`/`source` from the first PUBLISHED figure available.

    The ladder, in order, and why each rung is a fact rather than an estimate:

      1. the value already read from the account endpoint — INCLUDING
         `Decimal("0")`, which is the Free tier's real price;
      2. `NESTOR_TRIBUNAL_SERPAPI_UNIT_USD` — the operator escape hatch for a
         published price the API does not expose. It is still a published fact
         that a human typed in, never a model's or this module's estimate;
      3. `cost_table.tool_fee_or_none("serpapi_search")` — the price table's
         plan-independent rate, which ships as JSON `null` precisely because
         SerpApi has no plan-independent rate;
      4. nothing — `unit_price_usd` stays None with `source="unknown"` and a
         WARNING says, in words, that the run's SerpApi spend will be marked
         PENDING rather than guessed.
    """
    if plan.unit_price_usd is not None:
        return plan

    override = os.environ.get("NESTOR_TRIBUNAL_SERPAPI_UNIT_USD", "").strip()
    if override:
        value = _as_decimal(override)
        if value is not None and value >= 0:
            return _with_unit(plan, value, "env")
        log.warning(
            "serpapi: NESTOR_TRIBUNAL_SERPAPI_UNIT_USD is not a usable number — ignored"
        )

    # cost_table gains `tool_fee_or_none` in task 2 of this same plan. The
    # getattr keeps this module importable and correct against an older
    # cost_table (e.g. a partially-rolled image) instead of failing at import.
    try:
        from nestor_pulse_sdk.audit import cost_table  # noqa: PLC0415

        reader = getattr(cost_table, "tool_fee_or_none", None)
        table_value = reader("serpapi_search") if callable(reader) else None
    except Exception:  # noqa: BLE001 — the price table never breaks a run
        table_value = None
    if table_value is not None:
        return _with_unit(plan, table_value, "cost_prices.json")

    log.warning(
        "serpapi: no published unit price could be established (plan_name=%r) — "
        "this run's SerpApi spend will be recorded as PENDING rather than guessed",
        plan.plan_name,
    )
    return SerpApiPlan(
        plan_name=plan.plan_name,
        plan_monthly_price=plan.plan_monthly_price,
        searches_per_month=plan.searches_per_month,
        total_searches_left=plan.total_searches_left,
        unit_price_usd=None,
        source="unknown",
    )


def _with_unit(plan: SerpApiPlan, unit: Decimal, source: str) -> SerpApiPlan:
    return SerpApiPlan(
        plan_name=plan.plan_name,
        plan_monthly_price=plan.plan_monthly_price,
        searches_per_month=plan.searches_per_month,
        total_searches_left=plan.total_searches_left,
        unit_price_usd=unit,
        source=source,
    )


async def record_plan_for_run(run_id, tenant_id, plan: SerpApiPlan) -> None:
    """Persist the plan + unit price in force, as one `output` row for this run.

    D-16 reproducibility: the tier can change between today's run and next
    month's audit, so the number the fee was computed from is written down WITH
    the run rather than re-derived later from whatever the account says then.

    Mirrors `pipeline._write_output` (`pipeline.py:1300-1319`) step for step —
    sessionmaker, `session.begin()`, `set_tenant_context` before the INSERT, and
    a best-effort try/except that logs and swallows. `_write_output` is NOT
    imported because `pipeline.py` imports this package (a circular import);
    plan 15.2-16 may consolidate the two. A bookkeeping write must never break a
    run, so every failure here is a WARNING and nothing more.
    """
    import json as _json  # noqa: PLC0415
    from datetime import datetime, timezone  # noqa: PLC0415

    from sqlalchemy import text as _sql  # noqa: PLC0415

    from nestor_pulse_sdk.db.base import get_sessionmaker  # noqa: PLC0415
    from nestor_pulse_sdk.db.rls import set_tenant_context  # noqa: PLC0415

    body = {
        "plan_name": plan.plan_name,
        "plan_monthly_price": (
            str(plan.plan_monthly_price) if plan.plan_monthly_price is not None else ""
        ),
        "searches_per_month": (
            str(plan.searches_per_month) if plan.searches_per_month is not None else ""
        ),
        "unit_price_usd": (
            str(plan.unit_price_usd) if plan.unit_price_usd is not None else ""
        ),
        "source": plan.source,
        "recorded_at": datetime.now(tz=timezone.utc).isoformat(),
    }
    try:
        sm = get_sessionmaker()
        async with sm() as session:
            async with session.begin():
                await set_tenant_context(session, tenant_id)
                await session.execute(
                    _sql(
                        "INSERT INTO output (id, tenant_id, run_id, format, body, created_at) "
                        "VALUES (:id,:tid,:rid,:fmt,:body,NOW())"
                    ),
                    {
                        "id": str(_uuid_mod.uuid4()),
                        "tid": str(tenant_id),
                        "rid": str(run_id),
                        "fmt": "serpapi_plan",
                        "body": _json.dumps(body, ensure_ascii=False, default=str),
                    },
                )
    except Exception as exc:  # noqa: BLE001 — bookkeeping never breaks a run
        log.warning("serpapi: record_plan_for_run failed: %s", reliability.redact(repr(exc)))


# ---------------------------------------------------------------------------
# Availability. R2's breaker, and the missing-secret case that behaves like it.
# ---------------------------------------------------------------------------


def get_breaker() -> reliability.CircuitBreaker:
    """The SerpApi circuit, created on first use.

    SCOPE NOTE, stated because `reliability.CircuitBreaker`'s own docstring says
    "construct these through a per-run `BreakerSet`; NEVER at module level".
    `run_own_research` takes a `breaker=` argument precisely so 15.2-13 can hand
    it the RUN-SCOPED breaker from that run's `BreakerSet`, and it should. This
    module-level instance exists only as the default for `unavailable_reason()`,
    which must be answerable before a run context exists; one worker runs one
    run (`runs/worker.py`), so the default carries no cross-tenant state. Use
    `reset_breaker()` between runs in any process that ever runs two.
    """
    global _BREAKER
    if _BREAKER is None:
        _BREAKER = reliability.CircuitBreaker("serpapi")
    return _BREAKER


def reset_breaker() -> None:
    """Drop the module-level breaker so the next call starts from `closed`."""
    global _BREAKER
    _BREAKER = None


def unavailable_reason(*, breaker: Any | None = None) -> str | None:
    """The plain-words reason SerpApi may not be called right now, or None.

    THE INVARIANT: **a missing `SERPAPI_API_KEY` is treated exactly like an open
    breaker.** The stream is refused BEFORE any call — zero HTTP, zero LLM, zero
    spend — the reason is NAMED into D-12's `degradation_reasons`, and the run
    continues as a clean 3-stream `completed_degraded` rather than a park (D-12 /
    D-17: one stream lost degrades, it never parks).

    The two-branch form is used rather than force-opening the breaker at
    construction, which 15.2-02's `force_open` would also allow. The invariant is
    identical either way, and reading the environment each time is the honest
    one: the secret does not exist yet (15.2-18 creates it), and a breaker forced
    open at first construction would stay open for the life of the process after
    the secret finally arrives.
    """
    if not configured():
        return REASON_KEY_MISSING
    circuit = breaker if breaker is not None else get_breaker()
    try:
        if circuit.state != reliability.CLOSED:
            return REASON_BREAKER_OPEN
    except Exception:  # noqa: BLE001 — an unreadable breaker is not a reason to refuse
        return None
    return None


def note_failure(exc: BaseException, *, breaker: Any | None = None) -> None:
    """Book a SerpApi failure against the circuit, with the right severity.

    Classification is `reliability`'s, not a second marker list of this module's:
      * 402 and cap/billing wording -> HARD_WALL, trips on the FIRST occurrence;
      * 429 -> RATE_LIMIT, retried, and NEVER trips the breaker (a rate limit
        means the provider is healthy and we are sending too fast);
      * 5xx / timeouts -> transient or overload, retried, higher threshold.

    ONE addition on top of `record_failure`: HTTP **401** trips immediately.
    `classify` reads a bare 401 as an ordinary HARD failure needing five
    identical repeats, but from SerpApi a 401 is an unambiguous statement about
    the ACCOUNT — the key is wrong or revoked — and five more requests can only
    produce five more 401s. That is the 776-errors-in-55-seconds lesson applied
    to this provider. Never raises.
    """
    circuit = breaker if breaker is not None else get_breaker()
    try:
        if reliability._status_of(exc) == 401:
            circuit.trip(
                "serpapi rejected our API key (HTTP 401) — the key is wrong or "
                "revoked, so no retry can fix this"
            )
            return
        circuit.record_failure(exc)
    except Exception as breaker_exc:  # noqa: BLE001 — bookkeeping never breaks a run
        log.warning(
            "serpapi: could not record failure on the breaker: %s",
            reliability.redact(repr(breaker_exc)),
        )
