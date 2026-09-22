"""Phase 23.5 plan 04 Task 1 -- the kill switches, proven in BOTH states.

The point of this module is the one thing `test_citation_anchors.py` cannot do.
`citations/anchors.py:87` reads `NESTOR_TRIBUNAL_ANCHORS` into a module-level
constant AT IMPORT, so a test can only observe whatever the environment happened
to hold when the interpreter first imported that module -- which is why that file
carries a `skipif(not _ANCHORS_ENABLED)` instead of asserting both states. Every
accessor in `runtime_flags` reads `os.environ` at CALL time, so every test below
sets the environment AFTER import, in this same process, and still sees the
change. The flags-off golden test in `test_citation_replay.py` is worth nothing
without that property: it has to be able to turn the master off.

Pure: no DB, no network, no provider call, no `integration` marker.
"""

import pytest

from nestor_pulse_sdk import runtime_flags

#: Every citation sub-switch: (accessor name, env var name). Each defaults TRUE
#: on its own and is ANDed with the master, so all six are False until
#: `NESTOR_CITATIONS_V2` is on.
CITATION_SUB_SWITCHES = [
    ("skeptic_as_evidence", "NESTOR_CITATIONS_SKEPTIC_AS_EVIDENCE"),
    ("per_url_meta", "NESTOR_CITATIONS_PER_URL_META"),
    ("primary_anchor", "NESTOR_CITATIONS_PRIMARY_ANCHOR"),
    ("ledger_numberable_only", "NESTOR_CITATIONS_LEDGER_NUMBERABLE_ONLY"),
    ("render_resolved", "NESTOR_CITATIONS_RENDER_RESOLVED"),
]

#: Everything this module reads. Cleared before every test so a developer's own
#: shell cannot make a flag test pass or fail for reasons the test does not name.
ALL_ENV_NAMES = (
    ["NESTOR_CITATIONS_V2", "NESTOR_SYNTHESIS_CONTINUE_TRUNCATED"]
    + [env for _, env in CITATION_SUB_SWITCHES]
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """No phase-23.5 flag is set unless the test itself sets it."""
    for name in ALL_ENV_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_everything_is_off_by_default():
    """The shipped default IS today's behaviour -- D-23.5-04."""
    assert runtime_flags.citations_v2() is False
    for accessor, _env in CITATION_SUB_SWITCHES:
        assert getattr(runtime_flags, accessor)() is False, accessor
    assert runtime_flags.synthesis_continue_truncated() is False


def test_master_on_turns_every_citation_sub_switch_on(monkeypatch):
    """One lever. Flipping the master must actually change something."""
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    assert runtime_flags.citations_v2() is True
    for accessor, _env in CITATION_SUB_SWITCHES:
        assert getattr(runtime_flags, accessor)() is True, accessor


def test_a_sub_switch_can_be_turned_off_under_the_master(monkeypatch):
    """Bisecting a bad dev run without a rebuild is the sub-switches' only job."""
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    monkeypatch.setenv("NESTOR_CITATIONS_PER_URL_META", "false")
    assert runtime_flags.per_url_meta() is False
    for accessor, _env in CITATION_SUB_SWITCHES:
        if accessor == "per_url_meta":
            continue
        assert getattr(runtime_flags, accessor)() is True, accessor


@pytest.mark.parametrize("accessor,env_name", CITATION_SUB_SWITCHES)
def test_master_is_an_and_gate(monkeypatch, accessor, env_name):
    """A sub-switch set true with the master unset is still OFF.

    This is the property the operator's revert depends on: `NESTOR_CITATIONS_V2`
    off restores today's behaviour no matter what else is in the environment.
    """
    monkeypatch.setenv(env_name, "true")
    assert getattr(runtime_flags, accessor)() is False


def test_synthesis_continuation_is_a_separate_master(monkeypatch):
    """A different subsystem, a different blast radius, a different lever."""
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    assert runtime_flags.synthesis_continue_truncated() is False
    monkeypatch.setenv("NESTOR_SYNTHESIS_CONTINUE_TRUNCATED", "true")
    assert runtime_flags.synthesis_continue_truncated() is True
    monkeypatch.delenv("NESTOR_CITATIONS_V2", raising=False)
    assert runtime_flags.synthesis_continue_truncated() is True


def test_env_is_read_at_call_time_not_import_time(monkeypatch):
    """The whole reason this module exists rather than reusing the anchors idiom."""
    assert runtime_flags.citations_v2() is False
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "1")
    assert runtime_flags.citations_v2() is True
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "0")
    assert runtime_flags.citations_v2() is False


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("1", True),
        ("true", True),
        ("TRUE", True),
        ("  Yes  ", True),
        ("on", True),
        ("0", False),
        ("false", False),
        ("No", False),
        ("off", False),
    ],
)
def test_truthy_vocabulary(raw, expected):
    assert runtime_flags._truthy(raw, default=not expected) is expected


@pytest.mark.parametrize("raw", [None, "", "   ", "maybe", "2", "tru"])
def test_truthy_falls_back_to_the_documented_default(raw):
    """An unparseable value must not flip a flag by accident, in either direction."""
    assert runtime_flags._truthy(raw, default=True) is True
    assert runtime_flags._truthy(raw, default=False) is False


def test_garbage_env_value_leaves_the_documented_default_in_place(monkeypatch):
    """`NESTOR_CITATIONS_V2=maybe` is off (default false), not on."""
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "maybe")
    assert runtime_flags.citations_v2() is False
    # ... and a sub-switch with a garbage value keeps ITS default (true) under a
    # master that is genuinely on.
    monkeypatch.setenv("NESTOR_CITATIONS_V2", "true")
    monkeypatch.setenv("NESTOR_CITATIONS_PER_URL_META", "perhaps")
    assert runtime_flags.per_url_meta() is True
