"""Per-site guards for the 261006-kzr Gemini model switch (2026-10-06).

Operator ruling (DEV first; Google retires gemini-2.5-* on 2026-10-20):

| site                                   | default               | thinking |
|----------------------------------------|-----------------------|----------|
| claim gates                            | gemini-3.8-flash      | low      |
| grouping                               | gemini-3.8-flash      | low      |
| report planner                         | gemini-3.8-flash      | low      |
| workshop rank (critique + judge)       | gemini-3.8-flash      | low      |
| evolve meta-review (inherits rank)     | gemini-3.8-flash      | rank's   |
| admission classifier (fallback)        | GEMINI_FLASH_DEFAULT  | rank's   |
| conflict detector                      | gemini-3.8-flash      | high     |
| scrub                                  | gemini-3.8-flash      | high     |
| claim distiller                        | gemini-3.5-flash-lite | minimal  |

Each test pins one property: the default model, the env override (in a FRESH
interpreter — reloading steps.py has module-level side effects), the dumped
config shape, the revert-to-2.5 byte-faithfulness, and the G-7 price row.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

pytest.importorskip("google.genai.types")

from nestor_pulse_sdk.pipeline import gemini_config as gc  # noqa: E402
from nestor_pulse_sdk.pipeline.synthesis import steps  # noqa: E402
from nestor_pulse_sdk.pipeline.tribunal import (  # noqa: E402
    gates,
    grouping,
    report_planner,
)

workshop_rank = pytest.importorskip("nestor_pulse_sdk.pipeline.tribunal.workshop_rank")
workshop_evolve = pytest.importorskip("nestor_pulse_sdk.pipeline.tribunal.workshop_evolve")
workshop_admission = pytest.importorskip(
    "nestor_pulse_sdk.pipeline.tribunal.workshop_admission"
)

_TRIBUNAL_ROOT = Path(__file__).resolve().parents[2]

# Every env var that can move a site's model or thinking level. Cleared for the
# subprocess tests so the developer's shell cannot leak into an assertion.
_SITE_ENV = (
    "NESTOR_TRIBUNAL_GATE_MODEL",
    "NESTOR_TRIBUNAL_GATE_THINKING",
    "NESTOR_TRIBUNAL_GROUP_MODEL",
    "NESTOR_TRIBUNAL_GROUP_THINKING",
    "NESTOR_TRIBUNAL_PLANNER_MODEL",
    "NESTOR_TRIBUNAL_PLANNER_THINKING",
    "NESTOR_TRIBUNAL_WORKSHOP_RANK_MODEL",
    "NESTOR_TRIBUNAL_WORKSHOP_RANK_THINKING",
    "NESTOR_TRIBUNAL_WORKSHOP_META_MODEL",
    "NESTOR_CONFLICT_MODEL",
    "NESTOR_CONFLICT_THINKING",
    "NESTOR_SCRUB_MODEL",
    "NESTOR_SCRUB_THINKING",
    "NESTOR_SCRUB_MAX_TOKENS",
    "NESTOR_DISTILLER_MODEL",
    "NESTOR_DISTILLER_THINKING",
    "NESTOR_GEMINI_TEMPERATURE",
)

# The module-level defaults are read at import; a developer shell with any of
# these set would make the default assertions meaningless rather than wrong.
_ENV_LEAK = [k for k in _SITE_ENV if os.environ.get(k)]
needs_clean_env = pytest.mark.skipif(
    bool(_ENV_LEAK), reason=f"site env vars set in this shell: {_ENV_LEAK}"
)


def _lvl(dumped: dict) -> str:
    v = dumped["thinking_config"]["thinking_level"]
    return getattr(v, "value", v)


def _dump(cfg) -> dict:
    assert cfg is not None
    return cfg.model_dump(exclude_none=True)


@pytest.fixture(autouse=True)
def _no_temperature_env(monkeypatch):
    monkeypatch.delenv("NESTOR_GEMINI_TEMPERATURE", raising=False)


# ── default model per site ──────────────────────────────────────────────────


@needs_clean_env
@pytest.mark.parametrize(
    "value, expected",
    [
        (lambda: gates._GATE_MODEL, "gemini-3.8-flash"),
        (lambda: grouping._GROUPER_MODEL, "gemini-3.8-flash"),
        (lambda: report_planner._PLANNER_MODEL, "gemini-3.8-flash"),
        (lambda: workshop_rank._RANK_MODEL, "gemini-3.8-flash"),
        (lambda: workshop_evolve._META_MODEL, "gemini-3.8-flash"),
        (lambda: steps._CONFLICT_MODEL, "gemini-3.8-flash"),
        (lambda: steps._SCRUB_MODEL, "gemini-3.8-flash"),
        (lambda: steps._DISTILLER_MODEL, "gemini-3.5-flash-lite"),
    ],
    ids=["gates", "grouping", "planner", "rank", "meta", "conflict", "scrub", "distiller"],
)
def test_site_default_model(value, expected):
    assert value() == expected


@needs_clean_env
def test_default_thinking_levels():
    assert gates._GATE_THINKING == "low"
    assert grouping._GROUPER_THINKING == "low"
    assert report_planner._PLANNER_THINKING == "low"
    assert workshop_rank._RANK_THINKING == "low"
    assert steps._CONFLICT_THINKING == "high"
    assert steps._SCRUB_THINKING == "high"
    assert steps._DISTILLER_THINKING == "minimal"


def test_admission_fallback_derives_from_helper(monkeypatch):
    """When `_RANK_MODEL` cannot be imported, the classifier falls back to
    GEMINI_FLASH_DEFAULT (derived, not a copied literal), and still sends a
    config built for that model."""
    monkeypatch.delattr(workshop_rank, "_RANK_MODEL")

    seen: dict = {}

    class _Resp:
        text = "0 | 0"

    class _Audited:
        async def gemini_generate(self, **kw):
            seen.update(kw)
            return _Resp()

    asyncio.run(
        workshop_admission.classify_parent(
            questions=["an angle about coffee unit economics"],
            client_questions=[{"label": "Q1 coffee"}],
            audited=_Audited(),
            run_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
        )
    )
    assert seen["model"] == gc.GEMINI_FLASH_DEFAULT
    d = _dump(seen["config"])
    assert "thinking_budget" not in d["thinking_config"]
    assert "temperature" not in d


# ── config shape per site ───────────────────────────────────────────────────


@needs_clean_env
@pytest.mark.parametrize(
    "build, level, max_tokens",
    [
        (lambda: gates._make_config(), "LOW", 4096),
        (lambda: grouping._make_config(), "LOW", 4096),
        (lambda: report_planner._make_config(), "LOW", 4096),
        (
            lambda: gates._make_config(
                model=workshop_rank._RANK_MODEL, level=workshop_rank._RANK_THINKING
            ),
            "LOW",
            4096,
        ),
        (lambda: steps._make_conflict_config(), "HIGH", None),
        (lambda: steps._make_scrub_config(), "HIGH", 32768),
        (lambda: steps._make_distiller_config(), "MINIMAL", 65535),
    ],
    ids=["gates", "grouping", "planner", "rank", "conflict", "scrub", "distiller"],
)
def test_site_config_shape(build, level, max_tokens):
    d = _dump(build())
    assert _lvl(d) == level
    assert "thinking_budget" not in d["thinking_config"]
    assert "temperature" not in d
    if max_tokens is None:
        assert "max_output_tokens" not in d
    else:
        assert d["max_output_tokens"] == max_tokens


def test_temperature_env_reaches_every_site(monkeypatch):
    monkeypatch.setenv("NESTOR_GEMINI_TEMPERATURE", "0")
    for cfg in (
        gates._make_config(),
        grouping._make_config(),
        report_planner._make_config(),
        steps._make_conflict_config(),
        steps._make_scrub_config(),
        steps._make_distiller_config(),
    ):
        assert _dump(cfg)["temperature"] == 0.0


def test_workshop_path_builds_for_its_own_model(monkeypatch):
    """Rank / meta / admission get a config built for THEIR model, not the gate's.
    A 2.x-pro meta model must therefore get no thinking config at all."""
    cfg = gates._make_config(model="gemini-2.5-pro", level=workshop_rank._RANK_THINKING)
    d = _dump(cfg)
    assert "thinking_config" not in d
    assert d["temperature"] == 0.0


def test_workshop_call_sites_pass_model_and_level():
    """Source guard: every gates._make_config() in the workshop modules passes
    the workshop model + level (before 261006-kzr they got the GATE config)."""
    import inspect
    import re

    def code(mod) -> str:
        # Comments are prose ABOUT the call, not the call.
        return "\n".join(
            ln for ln in inspect.getsource(mod).splitlines()
            if not ln.lstrip().startswith("#")
        )

    for mod in (workshop_rank, workshop_evolve, workshop_admission):
        bare = re.findall(r"gates\._make_config\(\s*\)", code(mod))
        assert bare == [], f"{mod.__name__} still calls gates._make_config() bare"
    assert len(re.findall(r"gates\._make_config\(model=_RANK_MODEL, level=_RANK_THINKING\)",
                          code(workshop_rank))) == 2
    assert "gates._make_config(model=_META_MODEL" in code(workshop_evolve)
    assert "gates._make_config(model=model, level=_level)" in code(workshop_admission)


# ── env override (fresh interpreter) ────────────────────────────────────────


def _run_fresh(code: str, env_over: dict[str, str]) -> str:
    env = {k: v for k, v in os.environ.items() if k not in _SITE_ENV}
    env.update(env_over)
    env["PYTHONPATH"] = str(_TRIBUNAL_ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    out = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        cwd=str(_TRIBUNAL_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert out.returncode == 0, out.stderr[-2000:]
    return out.stdout.strip().splitlines()[-1]


def test_env_overrides_every_site_model():
    code = (
        "import json\n"
        "from nestor_pulse_sdk.pipeline.synthesis import steps\n"
        "from nestor_pulse_sdk.pipeline.tribunal import gates, grouping, report_planner,"
        " workshop_rank, workshop_evolve\n"
        "print(json.dumps({'gate': gates._GATE_MODEL, 'group': grouping._GROUPER_MODEL,"
        " 'planner': report_planner._PLANNER_MODEL, 'rank': workshop_rank._RANK_MODEL,"
        " 'meta': workshop_evolve._META_MODEL, 'conflict': steps._CONFLICT_MODEL,"
        " 'scrub': steps._SCRUB_MODEL, 'distiller': steps._DISTILLER_MODEL,"
        " 'gate_t': gates._GATE_THINKING, 'distiller_t': steps._DISTILLER_THINKING,"
        " 'scrub_max': steps._SCRUB_MAX_TOKENS}))\n"
    )
    got = json.loads(
        _run_fresh(
            code,
            {
                "NESTOR_TRIBUNAL_GATE_MODEL": "gemini-2.5-flash",
                "NESTOR_TRIBUNAL_GROUP_MODEL": "m-group",
                "NESTOR_TRIBUNAL_PLANNER_MODEL": "m-planner",
                "NESTOR_TRIBUNAL_WORKSHOP_RANK_MODEL": "m-rank",
                "NESTOR_CONFLICT_MODEL": "gemini-2.5-pro",
                "NESTOR_SCRUB_MODEL": "m-scrub",
                "NESTOR_DISTILLER_MODEL": "m-distiller",
                "NESTOR_TRIBUNAL_GATE_THINKING": "off",
                "NESTOR_DISTILLER_THINKING": "low",
                "NESTOR_SCRUB_MAX_TOKENS": "9000",
            },
        )
    )
    assert got == {
        "gate": "gemini-2.5-flash",
        "group": "m-group",
        "planner": "m-planner",
        "rank": "m-rank",
        "meta": "m-rank",  # inherits rank when its own env is unset
        "conflict": "gemini-2.5-pro",
        "scrub": "m-scrub",
        "distiller": "m-distiller",
        "gate_t": "off",
        "distiller_t": "low",
        "scrub_max": 9000,
    }


def test_revert_distiller_to_25_flash_is_byte_faithful():
    code = (
        "import json\n"
        "from nestor_pulse_sdk.pipeline.synthesis import steps\n"
        "print(json.dumps(steps._make_distiller_config().model_dump(mode='json',"
        " exclude_none=True)))\n"
    )
    got = json.loads(_run_fresh(code, {"NESTOR_DISTILLER_MODEL": "gemini-2.5-flash"}))
    assert got == {
        "max_output_tokens": 65535,
        "temperature": 0.0,
        "thinking_config": {"thinking_budget": 0},
    }


def test_revert_scrub_and_conflict_to_25_pro_is_byte_faithful():
    code = (
        "import json\n"
        "from nestor_pulse_sdk.pipeline.synthesis import steps\n"
        "print(json.dumps([steps._make_scrub_config().model_dump(mode='json', exclude_none=True),"
        " steps._make_conflict_config().model_dump(mode='json', exclude_none=True)]))\n"
    )
    got = json.loads(
        _run_fresh(
            code,
            {
                "NESTOR_SCRUB_MODEL": "gemini-2.5-pro",
                "NESTOR_SCRUB_MAX_TOKENS": "8192",
                "NESTOR_CONFLICT_MODEL": "gemini-2.5-pro",
            },
        )
    )
    # scrub: today's inline config; conflict: today sent NO config -> empty.
    assert got == [{"max_output_tokens": 8192, "temperature": 0.0}, {}]


def test_revert_gate_to_37_era_request():
    code = (
        "import json\n"
        "from nestor_pulse_sdk.pipeline.tribunal import gates\n"
        "print(json.dumps(gates._make_config().model_dump(mode='json', exclude_none=True)))\n"
    )
    got = json.loads(
        _run_fresh(
            code,
            {
                "NESTOR_TRIBUNAL_GATE_MODEL": "gemini-3.7-flash",
                "NESTOR_TRIBUNAL_GATE_THINKING": "off",
                "NESTOR_GEMINI_TEMPERATURE": "0",
            },
        )
    )
    assert got == {
        "max_output_tokens": 4096,
        "temperature": 0.0,
        "thinking_config": {"thinking_budget": 0},
    }


# ── G-7: every default has a price row ──────────────────────────────────────


@pytest.mark.parametrize(
    "model",
    sorted(
        {
            gc.GEMINI_FLASH_DEFAULT,
            gc.GEMINI_FLASH_LITE_DEFAULT,
            gates._GATE_MODEL,
            grouping._GROUPER_MODEL,
            report_planner._PLANNER_MODEL,
            steps._CONFLICT_MODEL,
            steps._SCRUB_MODEL,
            steps._DISTILLER_MODEL,
        }
    ),
)
def test_site_default_has_price_row(model):
    """compute() returns None for an unknown model -> NULL cost_usd -> SUM skips
    it (the booked G-7 defect)."""
    from nestor_pulse_sdk.audit import cost_table as ct

    cost = ct.compute("google", model, 1_000_000, 1_000_000, 0, 0)
    assert cost is not None, (
        f"google/{model} has NO row in audit/cost_prices.json — every call would "
        f"write NULL cost_usd (G-7). Add the price row."
    )


def test_price_rows_match_published_rates():
    from decimal import Decimal

    from nestor_pulse_sdk.audit import cost_table as ct

    assert ct.compute("google", "gemini-3.8-flash", 1_000_000, 1_000_000, 0, 0) == Decimal(
        "4.50"
    )
    assert ct.compute(
        "google", "gemini-3.5-flash-lite", 1_000_000, 1_000_000, 0, 0
    ) == Decimal("2.80")
