"""Shared Gemini generation-config helper (quick task 261006-kzr, 2026-10-06).

Every tribunal Gemini call site (claim gates, grouping, report planner,
workshop rank / evolve meta-review / admission classifier, conflict resolver,
scrub, claim distiller) builds its ``GenerateContentConfig`` through
:func:`build_generate_config`, so the model-family rules live in ONE place:

* **Gemini 3+** gets ``thinking_level`` ("minimal" | "low" | "medium" | "high")
  and NEVER ``thinking_budget`` alongside it — ``thinking_budget`` is deprecated
  on Gemini 3 and sending both fields is an HTTP 400. A non-lite Gemini 3 model
  is never sent "minimal" (gemini-3.8-flash rejects it); it is clamped to "low".
  The level "off" maps to ``thinking_budget=0`` alone — the 3.7-era request.
* **Gemini 3+** gets NO temperature by default. Google: keep temperature at its
  default 1.0 for Gemini 3, because values below 1.0 "may lead to unexpected
  behavior, such as looping or degraded performance". Set
  ``NESTOR_GEMINI_TEMPERATURE`` to send a value to every site (read at CALL
  time, so one env flip moves every site with no rebuild).
* **Gemini 1.x / 2.x** (legacy family) ignore the level and get exactly the
  pre-261006 request: ``thinking_budget=0`` on Flash, no thinking config on Pro
  (2.x Pro rejects budget 0), and the site's historical temperature.

Revert recipe (env only, no rebuild — each site has a MODEL and a THINKING env):

* back to 3.7-era behaviour: ``<SITE>_MODEL=gemini-3.7-flash``,
  ``<SITE>_THINKING=off`` and ``NESTOR_GEMINI_TEMPERATURE=0``;
* back to 2.5-era behaviour: ``<SITE>_MODEL=gemini-2.5-flash`` (or
  ``gemini-2.5-pro`` for conflict / scrub) — the legacy branch reproduces the
  old thinking + temperature automatically.

Light module: imports only ``os``, ``logging`` and, lazily, ``google.genai.types``.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ── Operator ruling 261006-kzr (2026-10-06) ────────────────────────────────
# Google retires gemini-2.5-flash / gemini-2.5-pro on 2026-10-20, so every
# tribunal Gemini site moves off 2.5 / 3.7-flash, DEV first:
#   * gemini-3.8-flash for gates, grouping, planner, workshop rank (and through
#     it evolve meta-review + the admission classifier), conflict and scrub.
#     Introductory price $0.75 input / $3.75 output per 1M tokens through
#     2026-12-31 — the same as gemini-3.7-flash.
#   * gemini-3.5-flash-lite for the claim distiller.
# No production run has executed on either model yet.
GEMINI_FLASH_DEFAULT = "gemini-3.8-flash"
GEMINI_FLASH_LITE_DEFAULT = "gemini-3.5-flash-lite"

_LEVELS = ("minimal", "low", "medium", "high")
_OFF = "off"

# (model, level) pairs already warned about — warn once, not per call.
_WARNED: set[tuple[str, str]] = set()


def _warn_once(model: str, level: str, msg: str, *args: Any) -> None:
    key = (model, level)
    if key in _WARNED:
        return
    _WARNED.add(key)
    logger.warning(msg, *args)


def _genai_types():
    from google.genai import types  # lazy: keep this module cheap to import

    return types


def _is_legacy(model: str) -> bool:
    """1.x / 2.x model ids are the legacy family; everything else is Gemini 3+."""
    m = (model or "").strip().lower()
    return m.startswith("gemini-1.") or m.startswith("gemini-2.")


def _normalise_level(model: str, level: Optional[str]) -> str:
    raw = (level or "").strip().lower()
    if raw == _OFF or raw in _LEVELS:
        return raw
    _warn_once(
        model,
        raw,
        "gemini_config: unknown thinking level %r for %s — using 'low'",
        level,
        model,
    )
    return "low"


def build_thinking_config(model: str, level: Optional[str], genai_types: Any = None):
    """Return a ``ThinkingConfig`` built with EXACTLY ONE field, or ``None``.

    * legacy Flash (1.x/2.x, not ``-pro``) → ``thinking_budget=0`` (level ignored)
    * legacy Pro → ``None`` (2.x Pro rejects budget 0)
    * Gemini 3+ with level "off" → ``thinking_budget=0``
    * Gemini 3+ otherwise → ``thinking_level=<LEVEL>``; "minimal" is clamped to
      "low" unless the model id contains "flash-lite"
    """
    t = genai_types if genai_types is not None else _genai_types()
    m = (model or "").strip().lower()

    if _is_legacy(m):
        if "-pro" in m:
            return None
        return t.ThinkingConfig(thinking_budget=0)

    lvl = _normalise_level(model, level)
    if lvl == _OFF:
        return t.ThinkingConfig(thinking_budget=0)

    if lvl == "minimal" and "flash-lite" not in m:
        _warn_once(
            model,
            "minimal",
            "gemini_config: %s does not accept thinking level 'minimal' — clamped to 'low'",
            model,
        )
        lvl = "low"

    enum = getattr(t, "ThinkingLevel", None)
    value: Any = enum[lvl.upper()] if enum is not None else lvl.upper()
    return t.ThinkingConfig(thinking_level=value)


def resolve_temperature(model: str, legacy_temperature: Optional[float]) -> Optional[float]:
    """Temperature to send, or ``None`` to omit it.

    ``NESTOR_GEMINI_TEMPERATURE`` (non-empty) wins for every model. Otherwise
    the legacy family keeps the site's historical value and Gemini 3+ omits it.
    Read at call time.
    """
    env = os.environ.get("NESTOR_GEMINI_TEMPERATURE", "").strip()
    if env:
        return float(env)
    if _is_legacy(model):
        return legacy_temperature
    return None


def build_generate_config(
    model: str,
    *,
    level: Optional[str],
    max_output_tokens: Optional[int] = None,
    legacy_temperature: Optional[float] = None,
):
    """Build a ``GenerateContentConfig`` from only the non-None fields.

    Returns ``None`` if google.genai is unimportable. If building the
    ThinkingConfig raises, the config is built WITHOUT thinking_config — it
    never falls back to resending ``thinking_budget``.
    """
    try:
        t = _genai_types()
    except Exception:  # noqa: BLE001 - SDK missing → caller sends no config
        return None

    kwargs: dict[str, Any] = {}
    if max_output_tokens is not None:
        kwargs["max_output_tokens"] = max_output_tokens
    temperature = resolve_temperature(model, legacy_temperature)
    if temperature is not None:
        kwargs["temperature"] = temperature
    try:
        thinking = build_thinking_config(model, level, genai_types=t)
    except Exception as exc:  # noqa: BLE001 - degrade to no thinking config
        logger.debug("gemini_config: ThinkingConfig unavailable for %s (%s)", model, exc)
        thinking = None
    if thinking is not None:
        kwargs["thinking_config"] = thinking
    try:
        return t.GenerateContentConfig(**kwargs)
    except Exception as exc:  # noqa: BLE001
        logger.debug("gemini_config: GenerateContentConfig failed for %s (%s)", model, exc)
        return None
