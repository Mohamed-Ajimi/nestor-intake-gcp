"""`assignment_identity` — the D-W5-2 discriminator for one `assignment_yield` row.

WHAT BREAKS IN PRODUCTION IF THIS FILE FIRES. `parent_kind`, `client_question`
and `group_id` are three columns of the `assignment_yield` table, which exists to
answer ONE question ONCE — *which provider actually yields surviving claims per
dollar* — over a single ~$45 run that cannot be repeated to check the numbers. A
wrong discriminator here does not fail loudly: it produces a row that LOOKS
right, attributes a cross-cutting group's spend to client question 1, and is
believed.

THE CENTRAL RULE THESE TESTS PIN. `parent_kind` is a REAL column and must NEVER
be inferred from `client_question IS NULL` (D-W5-2). The two encode different
things, and this engine really produces both of the rows that prove it: a MANDATE
group whose label resolves empty (NULL question, `client_question` kind) and a
CROSS-CUTTING group with a perfectly good label (NULL question, `cross_cutting`
kind). Collapsing them reports a naming failure as a cross-cutting group.

No LLM calls, no database, no I/O — `assignment_identity` is a pure function.
"""
from __future__ import annotations

import pytest

from nestor_pulse_sdk.pipeline.tribunal import question_grouping
from nestor_pulse_sdk.pipeline.tribunal import research_division as rd
from nestor_pulse_sdk.runs import yield_records


# ---------------------------------------------------------------------------
# Angle fixtures. Shapes copied from what `_group_angle` and `divide()` really
# build, not invented: a group angle carries `bracket`, `corroboration_key`,
# `focus_area` and `sub_questions`, and `discovery_riders` ONLY when the group
# holds at least one discovered question; a focus-area-path angle carries none of
# the first, second or fourth.
# ---------------------------------------------------------------------------

def _group_angle(**over) -> dict:
    angle = {
        "bracket": question_grouping.GROUP_BRACKET_MANDATE,
        "corroboration_key": "g1",
        "focus_area": "How do competitors price?",
        "sub_questions": ["a", "b"],
        "provider": "gemini",
        "stakes": "high",
    }
    angle.update(over)
    return angle


def _cross_cutting(**over) -> dict:
    # `d1` is the LITERAL group id `question_grouping.build_groups` mints for the
    # discovery bracket — there is never a `d2`, which is exactly why the group
    # has no single parent.
    return _group_angle(
        bracket=question_grouping.GROUP_BRACKET_DISCOVERY,
        corroboration_key="d1",
        **over,
    )


def _focus_area_angle(**over) -> dict:
    """`divide()`'s focus-area path: NO bracket, NO key, NO sub_questions."""
    angle = {"focus_area": "How do competitors price?", "provider": "gemini",
             "stakes": "high", "query": "..."}
    angle.update(over)
    return angle


# ---------------------------------------------------------------------------
# THE THREE D-W5-2 SHAPES, PROVED DISTINCTLY
# ---------------------------------------------------------------------------

def test_cross_cutting_group_discards_the_orphan_resolved_label():
    """If this fires, the `d1` group's whole spend is attributed to Q1.

    `_group_angle`'s ORPHAN RULE puts `labels[0]` in `focus_area` for a group
    whose parent is unknown, so a cross-cutting angle arrives here LOOKING like a
    Q1 assignment. Recording that label would fabricate provenance in a row whose
    entire purpose is to be trusted after the run.
    """
    identity = rd.assignment_identity(_cross_cutting(focus_area="Q1 label"))

    assert identity["parent_kind"] == "cross_cutting"
    assert identity["client_question"] is None


def test_cross_cutting_row_still_records_which_group_it_measured():
    """If this fires, cross-cutting rows cannot be joined back to their group."""
    assert rd.assignment_identity(_cross_cutting())["group_id"] == "d1"


def test_all_rider_group_is_discovery_rider_and_keeps_its_own_question():
    """If this fires, discovered questions cannot be told from client questions.

    An ALL-RIDER mandate group has no client mandate of its own, but it DOES
    carry a parent label (D-W3-5.2 parents a discovery question to a
    client-question label), so it records that label and NOT NULL.
    """
    identity = rd.assignment_identity(
        _group_angle(sub_questions=["r1", "r2"], discovery_riders=2,
                     focus_area="Q2 label")
    )

    assert identity["parent_kind"] == "discovery_rider"
    assert identity["client_question"] == "Q2 label"


def test_rider_riding_along_with_real_members_is_a_client_question():
    """If this fires, every ride-along group is misfiled as a discovery rider.

    Under D-W3-5.2 a group holding one client question PLUS a rider is the
    INTENDED shape: the assignment's mandate IS the client question and the rider
    rides along. Only an all-rider group lacks a mandate of its own.
    """
    identity = rd.assignment_identity(
        _group_angle(sub_questions=["real", "rider"], discovery_riders=1)
    )

    assert identity["parent_kind"] == "client_question"
    assert identity["client_question"] == "How do competitors price?"


def test_ordinary_mandate_group_has_no_discovery_riders_key_at_all():
    """If this fires, the ordinary case — most rows in the table — is wrong.

    `_group_angle` OMITS `discovery_riders` entirely when a group carries no
    discovered question. Absent must read the same as zero.
    """
    identity = rd.assignment_identity(_group_angle())

    assert "discovery_riders" not in _group_angle()
    assert identity["parent_kind"] == "client_question"
    assert identity["client_question"] == "How do competitors price?"
    assert identity["group_id"] == "g1"


def test_focus_area_path_angle_has_no_group_id():
    """If this fires, the focus-area fallback path writes a bogus group id.

    That path produces angles with no `bracket`, no `corroboration_key` and no
    `sub_questions`; its rows are keyed on `client_question` alone.
    """
    identity = rd.assignment_identity(_focus_area_angle())

    assert identity["parent_kind"] == "client_question"
    assert identity["group_id"] is None
    assert identity["client_question"] == "How do competitors price?"


# ---------------------------------------------------------------------------
# THE DISCRIMINATOR IS NOT DERIVED FROM `client_question` (D-W5-2)
# ---------------------------------------------------------------------------

def test_mandate_angle_with_an_empty_label_is_still_a_client_question():
    """THE MUTANT ROW. If this fires, `parent_kind` has been made derivable.

    A mandate group whose label resolves empty writes `client_question = NULL`
    with `parent_kind = 'client_question'` — the assignment's mandate IS a client
    question; we merely failed to name it. An implementation that reads
    "question is NULL" as "cross-cutting" reports that naming failure as a
    cross-cutting group, and there is no second run to catch it.
    """
    identity = rd.assignment_identity(_group_angle(focus_area=""))

    assert identity["parent_kind"] == "client_question"
    assert identity["client_question"] is None


def test_cross_cutting_angle_with_a_good_label_is_still_cross_cutting():
    """The other half of the same pair: a real label, and still no parent."""
    identity = rd.assignment_identity(_cross_cutting(focus_area="A real question"))

    assert identity["parent_kind"] == "cross_cutting"
    assert identity["client_question"] is None


def test_cross_cutting_is_decided_on_the_bracket_constant():
    """If this fires, the classifier is matching a literal that has drifted.

    The bracket is compared against `question_grouping.GROUP_BRACKET_DISCOVERY`,
    never the string `"discovery"`. This test would break if the constant's value
    changed while the classifier kept the old literal — which is the point.
    """
    angle = _group_angle(bracket=question_grouping.GROUP_BRACKET_DISCOVERY)

    assert rd.assignment_identity(angle)["parent_kind"] == "cross_cutting"
    assert (
        rd.assignment_identity(
            _group_angle(bracket=question_grouping.GROUP_BRACKET_MANDATE)
        )["parent_kind"]
        == "client_question"
    )


# ---------------------------------------------------------------------------
# `group_id`: ABSENT IS NULL, NEVER `''` (migration 0017)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("raw", ["", "   ", None])
def test_absent_corroboration_key_is_none_and_never_empty_string(raw):
    """If this fires, "no key recorded" and "the empty key" become one fact.

    Migration 0017's own rule. The corroboration queries must tell them apart.
    """
    assert rd.assignment_identity(_group_angle(corroboration_key=raw))["group_id"] is None


@pytest.mark.parametrize(
    "angle",
    [
        _group_angle(),
        _group_angle(corroboration_key=""),
        _cross_cutting(),
        _focus_area_angle(),
        _group_angle(focus_area=""),
    ],
)
def test_group_id_can_never_disagree_with_the_existing_corroboration_stamp(angle):
    """If this fires, the yield row and the claim row name different groups.

    `_one_angle` already stamps `_corroboration_key` as
    `angle.get("corroboration_key") or None`. The identity must agree with it
    exactly, or a join between `assignment_yield` and `claim` silently loses rows.
    """
    assert rd.assignment_identity(angle)["group_id"] == (
        angle.get("corroboration_key") or None
    )


# ---------------------------------------------------------------------------
# PURE AND NEVER RAISES
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "hostile",
    [
        None,
        17,
        "x",
        {},
        {"sub_questions": 5, "discovery_riders": "many", "bracket": object()},
        {"corroboration_key": object(), "focus_area": object()},
    ],
)
def test_hostile_input_returns_the_conservative_shape_rather_than_raising(hostile):
    """If this fires, a data-shape defect kills a run whose money is spent.

    Asserting the RETURNED VALUE and not merely "did not raise": a classifier
    that returned `None` would not raise either, and would then take the whole
    aggregator down one frame later.
    """
    identity = rd.assignment_identity(hostile)

    assert sorted(identity) == ["client_question", "group_id", "parent_kind"]
    assert identity["parent_kind"] == "client_question"
    assert identity["group_id"] is None


def test_a_hostile_bracket_does_not_become_cross_cutting():
    """An unreadable bracket must fall through to the mandate case, not to `d1`."""
    identity = rd.assignment_identity(_group_angle(bracket=object()))

    assert identity["parent_kind"] == "client_question"


# ---------------------------------------------------------------------------
# THE VOCABULARY, PINNED BY A TEST RATHER THAN BY AN IMPORT
# ---------------------------------------------------------------------------

def test_every_emitted_parent_kind_is_in_the_emitter_vocabulary():
    """If this fires, rows land on the D-W5-10 `unknown` sentinel.

    `research_division` deliberately does NOT import `runs.yield_records`: the
    angle builder has no business depending on a database module for a naming
    convenience. The vocabulary is pinned HERE instead.

    A SUBSET assertion and NOT an exact set. An exact-set allowlist over a file a
    sibling plan owns breaks the moment that plan adds a fourth kind — the trap
    that cost phase 15.5 a cross-plan regression.
    """
    emitted = {
        rd.assignment_identity(angle)["parent_kind"]
        for angle in [
            _group_angle(),
            _cross_cutting(),
            _group_angle(sub_questions=["r"], discovery_riders=1),
            _focus_area_angle(),
            _group_angle(focus_area=""),
            None,
            17,
        ]
    }

    assert emitted, "the fixtures must exercise the classifier at all"
    assert emitted <= set(yield_records.PARENT_KINDS)
    # And the three ruled shapes really are all reachable.
    assert emitted >= {"client_question", "cross_cutting", "discovery_rider"}


def test_the_classifier_never_emits_the_unknown_sentinel():
    """`PARENT_KIND_UNKNOWN` means ENGINE BUG. This function must not mint one."""
    assert yield_records.PARENT_KIND_UNKNOWN not in {
        rd.assignment_identity(a)["parent_kind"]
        for a in [_group_angle(), _cross_cutting(), None, {}, "x"]
    }


# ---------------------------------------------------------------------------
# THE DISPATCH MODULE GAINS NO DATABASE DEPENDENCY, AND THE CLOCK IS MONOTONIC
#
# Both are SOURCE-TEXT / CODE-REVIEW guards, and are labelled as such rather than
# dressed up as behavioural proofs. No runtime assertion can distinguish
# `time.monotonic()` from `time.time()` on a machine whose clock does not step
# mid-test, so claiming a behavioural proof here would be a false one.
# ---------------------------------------------------------------------------

def _executable_source(module) -> str:
    """Module source with comments and docstrings removed.

    Comments AND docstrings, because prose explaining WHY a form is banned would
    otherwise satisfy a grep for that very form and turn the guard vacuous on
    correct source — the self-invalidating-acceptance-criterion trap.
    """
    import ast
    import io
    import tokenize

    src = open(module.__file__, encoding="utf-8").read()
    out = []
    for tok in tokenize.generate_tokens(io.StringIO(src).readline):
        if tok.type == tokenize.COMMENT:
            continue
        out.append(tok)
    stripped = tokenize.untokenize(out)
    tree = ast.parse(stripped)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                             ast.ClassDef)):
            body = node.body
            if (body and isinstance(body[0], ast.Expr)
                    and isinstance(body[0].value, ast.Constant)
                    and isinstance(body[0].value.value, str)):
                body.pop(0)
    return ast.unparse(tree)


def test_research_division_imports_no_database_module():
    """If this fires, the angle builder has acquired a Cloud SQL dependency."""
    assert "yield_records" not in _executable_source(rd)


def test_angle_duration_uses_a_monotonic_clock():
    """CODE-REVIEW GUARD, not a runtime one — stated plainly.

    A wall-clock step (NTP correction, DST, an operator setting the clock) during
    a forty-minute deep-research call produces a negative or absurd elapsed value
    in a `NUMERIC(10, 3)` column. `time.monotonic` cannot go backwards by
    construction. Nothing observable at test time distinguishes the two calls, so
    this is asserted over the source.
    """
    source = _executable_source(rd)

    assert "time.monotonic()" in source
    assert "time.time()" not in source
