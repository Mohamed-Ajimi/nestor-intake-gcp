"""Unit tests for pipeline/gemini_config.py (quick task 261006-kzr).

The helper is the single place that decides what generation config a Gemini
call site sends:

* Gemini 3+ gets ``thinking_level`` (never ``thinking_budget`` alongside it —
  sending both is an HTTP 400), and non-lite Gemini 3 models never get
  ``minimal`` (gemini-3.8-flash rejects it).
* Gemini 3+ gets NO temperature by default (Google: values below 1.0 "may lead
  to unexpected behavior, such as looping"); ``NESTOR_GEMINI_TEMPERATURE``
  overrides.
* 1.x / 2.x models get the exact pre-261006 request (thinking_budget=0 on
  Flash, no thinking config on Pro, the site's historical temperature), so an
  env revert to 2.5 is byte-faithful.

These tests must pass under BOTH the local google-genai and the deployed pin
(google-genai==1.75.0, tribunal/requirements.txt).
"""
from __future__ import annotations

import logging

import pytest

genai_types = pytest.importorskip("google.genai.types")

from nestor_pulse_sdk.pipeline import gemini_config as gc  # noqa: E402


def _dump(obj):
    assert obj is not None
    return obj.model_dump(exclude_none=True)


def _level_value(dumped_thinking: dict) -> str:
    lvl = dumped_thinking["thinking_level"]
    return getattr(lvl, "value", lvl)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.delenv("NESTOR_GEMINI_TEMPERATURE", raising=False)
    gc._WARNED.clear()
    yield
    gc._WARNED.clear()


# ── defaults ────────────────────────────────────────────────────────────────


def test_defaults_are_operator_ruling():
    assert gc.GEMINI_FLASH_DEFAULT == "gemini-3.8-flash"
    assert gc.GEMINI_FLASH_LITE_DEFAULT == "gemini-3.5-flash-lite"


# ── build_thinking_config ───────────────────────────────────────────────────


def test_low_on_38_flash_is_level_only():
    d = _dump(gc.build_thinking_config("gemini-3.8-flash", "low"))
    assert _level_value(d) == "LOW"
    assert "thinking_budget" not in d


def test_minimal_on_38_flash_clamped_to_low_with_warning(caplog):
    with caplog.at_level(logging.WARNING, logger=gc.logger.name):
        d = _dump(gc.build_thinking_config("gemini-3.8-flash", "minimal"))
    assert _level_value(d) == "LOW"
    assert "thinking_budget" not in d
    assert any("minimal" in r.getMessage().lower() for r in caplog.records)


def test_minimal_clamp_applies_to_every_non_lite_gemini3():
    for model in ("gemini-3.7-flash", "gemini-3-pro-preview", "gemini-3.8-flash"):
        d = _dump(gc.build_thinking_config(model, "minimal"))
        assert _level_value(d) == "LOW", model


def test_clamp_warning_logged_once_per_pair(caplog):
    with caplog.at_level(logging.WARNING, logger=gc.logger.name):
        for _ in range(5):
            gc.build_thinking_config("gemini-3.8-flash", "minimal")
    assert len([r for r in caplog.records if "minimal" in r.getMessage().lower()]) == 1


def test_minimal_on_flash_lite_not_clamped():
    d = _dump(gc.build_thinking_config("gemini-3.5-flash-lite", "minimal"))
    assert _level_value(d) == "MINIMAL"
    assert "thinking_budget" not in d


def test_high_on_38_flash():
    d = _dump(gc.build_thinking_config("gemini-3.8-flash", "high"))
    assert _level_value(d) == "HIGH"


def test_medium_on_38_flash():
    d = _dump(gc.build_thinking_config("gemini-3.8-flash", "medium"))
    assert _level_value(d) == "MEDIUM"


@pytest.mark.parametrize("model", ["gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-3.7-flash"])
def test_off_on_gemini3_is_budget_zero_only(model):
    d = _dump(gc.build_thinking_config(model, "off"))
    assert d == {"thinking_budget": 0}


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "off", "banana"])
def test_legacy_flash_ignores_level_budget_zero(level):
    d = _dump(gc.build_thinking_config("gemini-2.5-flash", level))
    assert d == {"thinking_budget": 0}


@pytest.mark.parametrize("level", ["minimal", "low", "medium", "high", "off", "banana"])
def test_legacy_pro_gets_no_thinking_config(level):
    assert gc.build_thinking_config("gemini-2.5-pro", level) is None


def test_unknown_level_warns_and_is_low(caplog):
    with caplog.at_level(logging.WARNING, logger=gc.logger.name):
        d = _dump(gc.build_thinking_config("gemini-3.8-flash", "banana"))
    assert _level_value(d) == "LOW"
    assert any("banana" in r.getMessage() for r in caplog.records)


def test_level_is_case_insensitive():
    assert _level_value(_dump(gc.build_thinking_config("gemini-3.8-flash", "HIGH"))) == "HIGH"
    assert _level_value(_dump(gc.build_thinking_config("gemini-3.8-flash", " Low "))) == "LOW"
    assert _dump(gc.build_thinking_config("gemini-3.8-flash", "OFF")) == {"thinking_budget": 0}


_MODELS = [
    "gemini-3.8-flash",
    "gemini-3.5-flash-lite",
    "gemini-3.7-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
]
_LEVELS = ["minimal", "low", "medium", "high", "off", "garbage"]


@pytest.mark.parametrize("model", _MODELS)
@pytest.mark.parametrize("level", _LEVELS)
def test_property_never_both_thinking_fields(model, level):
    tc = gc.build_thinking_config(model, level)
    if tc is not None:
        d = tc.model_dump(exclude_none=True)
        assert not ("thinking_budget" in d and "thinking_level" in d), (model, level, d)
        assert len(d) == 1, (model, level, d)
    cfg = gc.build_generate_config(model, level=level, max_output_tokens=100, legacy_temperature=0.0)
    d = cfg.model_dump(exclude_none=True)
    th = d.get("thinking_config", {})
    assert not ("thinking_budget" in th and "thinking_level" in th), (model, level, d)
    # A non-lite Gemini 3 model is never sent "minimal".
    if not gc._is_legacy(model) and "flash-lite" not in model and "thinking_level" in th:
        assert _level_value(th) != "MINIMAL"


# ── resolve_temperature ─────────────────────────────────────────────────────


def test_temperature_omitted_for_gemini3_by_default():
    assert gc.resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) is None


def test_temperature_empty_env_is_omitted(monkeypatch):
    monkeypatch.setenv("NESTOR_GEMINI_TEMPERATURE", "")
    assert gc.resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) is None


def test_temperature_env_override(monkeypatch):
    monkeypatch.setenv("NESTOR_GEMINI_TEMPERATURE", "0.3")
    assert gc.resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) == 0.3


def test_temperature_env_read_at_call_time(monkeypatch):
    assert gc.resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) is None
    monkeypatch.setenv("NESTOR_GEMINI_TEMPERATURE", "0")
    assert gc.resolve_temperature("gemini-3.8-flash", legacy_temperature=0.0) == 0.0


def test_temperature_legacy_flash_keeps_historical():
    assert gc.resolve_temperature("gemini-2.5-flash", legacy_temperature=0.0) == 0.0


def test_temperature_legacy_pro_none_when_site_sent_none():
    assert gc.resolve_temperature("gemini-2.5-pro", legacy_temperature=None) is None


# ── build_generate_config ───────────────────────────────────────────────────


def test_generate_config_38_flash_low():
    d = _dump(
        gc.build_generate_config(
            "gemini-3.8-flash", level="low", max_output_tokens=4096, legacy_temperature=0.0
        )
    )
    assert d["max_output_tokens"] == 4096
    assert _level_value(d["thinking_config"]) == "LOW"
    assert "thinking_budget" not in d["thinking_config"]
    assert "temperature" not in d


def test_generate_config_no_max_tokens_key_when_none():
    d = _dump(gc.build_generate_config("gemini-3.8-flash", level="high", max_output_tokens=None))
    assert "max_output_tokens" not in d
    assert _level_value(d["thinking_config"]) == "HIGH"


def test_generate_config_legacy_flash_is_byte_faithful():
    d = _dump(
        gc.build_generate_config(
            "gemini-2.5-flash", level="minimal", max_output_tokens=65535, legacy_temperature=0.0
        )
    )
    assert d == {
        "max_output_tokens": 65535,
        "temperature": 0.0,
        "thinking_config": {"thinking_budget": 0},
    }


def test_generate_config_legacy_pro_scrub_shape():
    d = _dump(
        gc.build_generate_config(
            "gemini-2.5-pro", level="high", max_output_tokens=8192, legacy_temperature=0.0
        )
    )
    assert d == {"max_output_tokens": 8192, "temperature": 0.0}


def test_generate_config_degrades_without_thinking_when_thinking_raises(monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("ThinkingConfig unavailable")

    monkeypatch.setattr(gc, "build_thinking_config", _boom)
    d = _dump(
        gc.build_generate_config(
            "gemini-3.8-flash", level="low", max_output_tokens=4096, legacy_temperature=0.0
        )
    )
    assert "thinking_config" not in d
    assert d["max_output_tokens"] == 4096


def test_generate_config_returns_none_when_genai_unimportable(monkeypatch):
    def _raise():
        raise ImportError("no google.genai")

    monkeypatch.setattr(gc, "_genai_types", _raise)
    assert gc.build_generate_config("gemini-3.8-flash", level="low", max_output_tokens=10) is None
