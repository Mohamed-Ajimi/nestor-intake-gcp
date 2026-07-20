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

  In this module, `cached_tokens` = cache_read_input_tokens (already paid at 0.1x).
  cache_creation_tokens are NOT tracked separately here (they arrive via a different
  AuditedLLMClient field). The formula simplifies to:

    prompt_cost   = (prompt_tokens - cached_tokens) * (base / 1_000_000)
    cache_cost    = cached_tokens * (cache_read / 1_000_000)
    complete_cost = completion_tokens * (completion / 1_000_000)
    total         = prompt_cost + cache_cost + complete_cost

  This matches the Pitfall 6 formula in 01-RESEARCH.md.
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

    with prices_path.open(encoding="utf-8") as f:
        data = json.load(f)

    # Strip comment keys (keys starting with "_")
    prices = {k: v for k, v in data.items() if not k.startswith("_")}
    _cache.clear()
    _cache.update({"mtime": mtime, "path": str(prices_path), "data": prices})
    return prices


def compute(
    provider: str,
    model: str,
    prompt_tokens: int,
    completion_tokens: int,
    cached_tokens: int,
) -> Optional[Decimal]:
    """
    Compute cost in USD for one LLM call.

    Arguments:
      provider:          "anthropic", "google", or "openai"
      model:             model identifier (e.g. "claude-sonnet-4-6")
      prompt_tokens:     total input tokens (includes cached_tokens; from provider usage)
      completion_tokens: output tokens
      cached_tokens:     cache_read_input_tokens (Pitfall 6 -- Anthropic prompt cache hits)

    Returns:
      Decimal cost in USD, or None if the model is not in cost_prices.json.

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
    base_per_token = Decimal(str(entry["prompt"])) / Decimal("1000000")
    cache_read_per_token = Decimal(str(entry["cache_read"])) / Decimal("1000000")
    completion_per_token = Decimal(str(entry["completion"])) / Decimal("1000000")

    # Prompt cost: non-cached tokens at full rate
    non_cached = max(0, prompt_tokens - cached_tokens)
    prompt_cost = Decimal(str(non_cached)) * base_per_token

    # Cache-read tokens at reduced rate (0.1x base for Anthropic; per cost_prices.json for others)
    cache_cost = Decimal(str(cached_tokens)) * cache_read_per_token

    # Completion cost
    completion_cost = Decimal(str(completion_tokens)) * completion_per_token

    return prompt_cost + cache_cost + completion_cost
