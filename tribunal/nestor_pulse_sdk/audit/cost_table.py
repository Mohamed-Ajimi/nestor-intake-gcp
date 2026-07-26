"""
nestor_pulse_sdk.audit.cost_table -- hot-reloadable LLM cost computation.

Design:
  - cost_prices.json keyed by "provider/model" -> {prompt, completion, cache_read, cache_creation_5m}
  - All prices are USD per 1M tokens.
  - Hot-reloadable: file mtime is checked on each compute() call; json is re-parsed on change.
  - Unknown model: emit structured warning via logging + return None (Pitfall 5).
    Callers MUST handle None gracefully (write NULL to audit_log.cost_usd).

Cost formula (Pitfall 6 -- Anthropic prompt cache token accounting):
  total = (prompt_tokens - cached_tokens) * base_rate
        + cached_tokens * cache_read_rate       # 0.1x base for Anthropic
        + cache_creation_tokens * cache_creation_rate  # 1.25x base for Anthropic
        + completion_tokens * completion_rate
        + web_search_count * web_search_fee     # server-tool fee (Plan 15-02 C1)
        + web_fetch_count  * web_fetch_fee      # server-tool fee (Plan 15-02 C1)
        + serpapi_search_count * serpapi_unit_price  # D10 own-researcher (15.2-12, D-16)

  The SerpApi term is the one fee whose unit price is PER RUN rather than per
  table: SerpApi is sold as a prepaid plan, so the published unit price is
  plan_monthly_price / searches_per_month and it changes the moment the plan
  changes. The run reads it live from the account endpoint at start and hands it
  in here; cost_prices.json therefore carries _tool_fees.serpapi_search = null.

  In this module, `cached_tokens` = cache_read_input_tokens (already paid at 0.1x).
  As of Plan 15-02 (C1 cost-truth fix), `cache_creation_tokens` ARE charged here:
  Anthropic returns cache_creation_input_tokens on every cache-write call, and the
  audited client threads it into compute(). The full formula is now:

    prompt_cost   = (prompt_tokens - cached_tokens) * (base / 1_000_000)
    cache_cost    = cached_tokens * (cache_read / 1_000_000)
    create_cost   = cache_creation_tokens * (cache_creation_5m / 1_000_000)
    complete_cost = completion_tokens * (completion / 1_000_000)
    tool_fee      = web_search_count * web_search_fee + web_fetch_count * web_fetch_fee
    total         = prompt_cost + cache_cost + create_cost + complete_cost + tool_fee

  Server-tool fees (web_search/web_fetch) are per-call flat fees, NOT per-token, and
  are read from the "_tool_fees" object in cost_prices.json (published rates, facts
  only -- never estimated). Un-itemizable Gemini grounding fees are marked pending by
  the caller (run.cost_pending), never priced here (C1: no estimate ever).

  This matches the Pitfall 6 formula in 01-RESEARCH.md, extended for C1 cost-truth.
"""

from __future__ import annotations

import json
import logging
import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

_logger = logging.getLogger(__name__)

# Default prices file path; overridable via COST_PRICES_PATH env var.
_DEFAULT_PRICES_PATH = Path(__file__).parent / "cost_prices.json"

# Module-level cache: (path, mtime) -> prices dict
_cache: dict = {}


def _load_prices() -> dict:
    """
    Load cost_prices.json, using mtime-based hot-reload.

    Returns dict keyed by "provider/model" -> {prompt, completion, cache_read, cache_creation_5m}.
    """
    prices_path = Path(os.environ.get("COST_PRICES_PATH", str(_DEFAULT_PRICES_PATH)))

    try:
        mtime = prices_path.stat().st_mtime
    except FileNotFoundError:
        _logger.warning(
            "cost_prices.json not found at %s; all costs will be NULL",
            prices_path,
        )
        return {}

    if _cache.get("mtime") == mtime and _cache.get("path") == str(prices_path):
        return _cache["data"]

    # WR-04: the file is designed to be hot-edited in place, so a truncated
    # write mid-reload is the EXPECTED failure mode. The module contract is
    # "never fail, never guess" -- a parse error must degrade (keep serving the
    # last good table, or NULL costs), never raise out of compute() into the
    # live audit-write path.
    try:
        with prices_path.open(encoding="utf-8") as f:
            data = json.load(f)
    except json.JSONDecodeError as exc:
        _logger.warning(
            "cost_prices.json at %s is malformed (%s) -- %s",
            prices_path,
            exc,
            "serving last good table" if _cache.get("data") else "all costs will be NULL",
        )
        # Do NOT update the mtime cache: the next call re-tries the parse, so a
        # completed hot-edit is picked up as soon as the file is whole again.
        return _cache.get("data") or {}

    # Strip comment keys (keys starting with "_")
    prices = {k: v for k, v in data.items() if not k.startswith("_")}
    _cache.clear()
    _cache.update({"mtime": mtime, "path": str(prices_path), "data": prices})
    return prices


def _tool_fee(fee_name: str) -> Decimal:
    """Return the per-call USD fee for a server-tool (web_search/web_fetch).

    Reads the "_tool_fees" object from cost_prices.json. Missing entry -> 0
    (no estimate, no crash). Fees are published flat rates (facts only).
    """
    prices = _load_prices()
    # _tool_fees is stripped by _load_prices (leading-underscore keys removed),
    # so re-read the raw file for the fee table.
    prices_path = Path(os.environ.get("COST_PRICES_PATH", str(_DEFAULT_PRICES_PATH)))
    try:
        with prices_path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return Decimal("0")
    fees = raw.get("_tool_fees", {})
    val = fees.get(fee_name)
    if val is None:
        return Decimal("0")
    return Decimal(str(val))


def tool_fee_or_none(fee_name: str) -> Optional[Decimal]:
    """Return the per-call USD fee for a server tool, or None when UNKNOWN.

    The sibling of `_tool_fee`, and deliberately NOT a change to it:
    `test_cost_cache_write.py` depends on `_tool_fee`'s missing-entry-returns-zero
    behaviour, and web_fetch's genuine 0.0 relies on it too.

    THE None/ZERO DISTINCTION IS LOAD-BEARING (D-16, plan 15.2-12). For a fee
    that may legitimately be zero, "missing" and "free" must not collapse into
    the same number:
      * Decimal("0")  -- a KNOWN price of zero. SerpApi's Free tier really does
                        cost $0.00 per search, and that is an exact fact that
                        belongs in the run total as a zero.
      * None          -- UNKNOWN. The caller must write NULL cost_usd and set
                        cost_pending rather than present an incomplete cost as
                        settled (C1: never fail, never guess).

    Returns None when the key is absent OR its value is JSON null.
    """
    prices_path = Path(os.environ.get("COST_PRICES_PATH", str(_DEFAULT_PRICES_PATH)))
    try:
        with prices_path.open(encoding="utf-8") as f:
            raw = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    fees = raw.get("_tool_fees", {})
    if not isinstance(fees, dict):
        return None
    val = fees.get(fee_name)
    if val is None:
        return None
    try:
        return Decimal(str(val))
    except Exception:  # noqa: BLE001 -- a malformed hot-edit is unknown, not a crash
        _logger.warning(
            "cost_prices.json _tool_fees.%s is not a number -- treating as unknown",
            fee_name,
        )
        return None


def compute(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
    cache_creation_tokens: int = 0,
    web_search_count: int = 0,
    web_fetch_count: int = 0,
    serpapi_search_count: int = 0,
    serpapi_unit_price_usd: Optional[Decimal] = None,
) -> Optional[Decimal]:
    """
    Compute cost in USD for one LLM call.

    Arguments:
      provider:              "anthropic", "google", or "openai"
      model:                 model identifier (e.g. "claude-sonnet-4-6")
      prompt_tokens:         total input tokens (includes cached_tokens; from provider usage)
      completion_tokens:     output tokens
      cached_tokens:         cache_read_input_tokens (Pitfall 6 -- Anthropic prompt cache hits)
      cache_creation_tokens: cache_creation_input_tokens (Plan 15-02 C1 -- charged at the
                             cache_creation_5m rate; 0 for providers without cache-write).
                             Defaults to 0 so pre-15-02 callers keep identical results.
      web_search_count:      number of server-side web_search invocations on this call
                             (Plan 15-02 C1 -- priced at the published _tool_fees.web_search
                             flat fee; 0 by default).
      web_fetch_count:       number of server-side web_fetch invocations on this call
                             (priced at _tool_fees.web_fetch; 0 by default).
      serpapi_search_count:  number of BILLABLE SerpApi searches on this call (plan
                             15.2-12, D-16). Billable means search_metadata.status ==
                             "Success"; SerpApi does not charge for cached, errored or
                             failed searches, so this is NOT the HTTP-call count.
                             0 by default, so every pre-15.2-12 caller is unaffected.
      serpapi_unit_price_usd: the PUBLISHED per-search price in force for THIS run,
                             i.e. plan_monthly_price / searches_per_month read live
                             from the SerpApi account endpoint. None means unknown ->
                             the whole call returns None (never a guessed unit).

    Returns:
      Decimal cost in USD, or None if the model is not in cost_prices.json, or None
      if a non-zero serpapi_search_count has no published unit price.

    On unknown model: logs a structured WARNING with (provider, model) tuple + returns None.
    Callers write NULL to audit_log.cost_usd (Pitfall 5 -- never fail, never guess).
    """
    prices = _load_prices()
    key = f"{provider}/{model}"

    if key not in prices:
        _logger.warning(
            "Unknown LLM model cost: provider=%r model=%r -- writing NULL cost_usd (Pitfall 5)",
            provider,
            model,
        )
        return None

    entry = prices[key]

    # WR-04: a hot-added entry may omit a rate field -- degrade that component to
    # 0 with a warning instead of raising KeyError out of the live audit write.
    def _rate(field: str) -> Decimal:
        val = entry.get(field)
        if val is None:
            _logger.warning(
                "cost_prices.json entry %r missing rate %r -- treating as 0 "
                "(fix the price file)",
                key,
                field,
            )
            return Decimal("0")
        return Decimal(str(val))

    base_per_token = _rate("prompt") / Decimal("1000000")
    cache_read_per_token = _rate("cache_read") / Decimal("1000000")
    completion_per_token = _rate("completion") / Decimal("1000000")
    # cache_creation_5m: 1.25x base for Anthropic; 0.0 for providers without cache-write.
    cache_create_per_token = _rate("cache_creation_5m") / Decimal("1000000")

    # Prompt cost: non-cached tokens at full rate
    non_cached = max(0, prompt_tokens - cached_tokens)
    prompt_cost = Decimal(str(non_cached)) * base_per_token

    # Cache-read tokens at reduced rate (0.1x base for Anthropic; per cost_prices.json for others)
    cache_cost = Decimal(str(cached_tokens)) * cache_read_per_token

    # Cache-CREATE tokens at the 5m rate (Plan 15-02 C1). 0 for non-cache-write calls.
    cache_create_cost = Decimal(str(cache_creation_tokens)) * cache_create_per_token

    # Completion cost
    completion_cost = Decimal(str(completion_tokens)) * completion_per_token

    # Server-tool flat fees (Plan 15-02 C1 -- published rate, facts only, never estimated).
    tool_fee_cost = Decimal("0")
    if web_search_count:
        tool_fee_cost += Decimal(str(web_search_count)) * _tool_fee("web_search")
    if web_fetch_count:
        tool_fee_cost += Decimal(str(web_fetch_count)) * _tool_fee("web_fetch")

    # D10 own-researcher SerpApi fee (plan 15.2-12, D-16). Exact Decimal, never
    # a float, and never a guessed tier.
    #
    # INVARIANT: `serpapi_search_count` is only ever passed by
    # AuditedLLMClient.serpapi_search, together with provider="serpapi". NEVER
    # attach it to an LLM call -- an unknown SerpApi unit price returns None for
    # the WHOLE call, so doing so would null out that LLM call's own cost too.
    if serpapi_search_count:
        unit = (
            serpapi_unit_price_usd
            if serpapi_unit_price_usd is not None
            else tool_fee_or_none("serpapi_search")
        )
        if unit is None:
            _logger.warning(
                "SerpApi unit price unknown for %d billable search(es) -- writing "
                "NULL cost_usd and cost_pending rather than guessing a plan tier "
                "(D-16; the tier is plan 15.2-18's operator decision)",
                serpapi_search_count,
            )
            return None
        tool_fee_cost += Decimal(str(serpapi_search_count)) * Decimal(str(unit))

    return prompt_cost + cache_cost + cache_create_cost + completion_cost + tool_fee_cost
