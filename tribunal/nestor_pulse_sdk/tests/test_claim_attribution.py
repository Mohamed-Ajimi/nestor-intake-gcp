"""The 0017 contract, and the `as_of` grammar that fills one of its columns.

WHY THIS FILE EXISTS
--------------------
Phase 15.5 gives a claim row somewhere to record its attribution: which
sub-question it answers (`sub_question`), which corroboration group it came from
(`corroboration_key`), and its own date where the provider stated one (`as_of`).
Sections 1-3 pin the shape of tribunal alembic revision 0017 that adds those
three columns; section 4 pins the ORM against that DDL and drives
`pipeline/synthesis/claim_attribution.py::extract_as_of`.

WHAT THIS FILE CAN AND CANNOT PROVE
-----------------------------------
It can prove the revision chain is intact and single-headed, that the migration
is ADDITIVE ONLY, that the ORM matches the DDL, and that the date grammar
rejects as hard as it accepts.

IT CANNOT PROVE THE MIGRATION RAN. That proof is the literal line
`Running upgrade 0016 -> 0017` in a deploy log, and phase 15.5 deploys nothing
-- per the operator ruling of 2026-07-29 the whole engine redesign lands in git
and there is ONE deploy at the end of phase 15.8. The proof is OWED THERE,
alongside 0016s own still-unpaid `Running upgrade 0015 -> 0016`. Exit code 0 is
not a substitute: this repository has a recorded incident of a migration step
that exited 0 having printed no upgrade line at all. A chain break is precisely
how a migration silently never runs while every test here stays green, which is
why the chain is asserted rather than read off the file by a human.

THIS FILE OPENS NO DATABASE, MAKES ZERO LLM CALLS, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. It imports the ORM model (which builds table metadata in
memory), parses the migration with `ast`, and imports one stdlib-pure function.
Importing the migration executes two module-level imports and four function
definitions; `upgrade()` IS NEVER CALLED, so no DDL is emitted and no alembic
migration context is needed.

Cloud Build invocation (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import ast
import datetime
import importlib.util
import inspect
import re
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest


# --------------------------------------------------------------------------
# Locating the migration
# --------------------------------------------------------------------------
# parents[1] is `nestor_pulse_sdk/`. Resolved from THIS file rather than from a
# working directory, because the engine gate runs with /workspace mounted at the
# `tribunal/` source dir: nothing above `tribunal/` exists in that build context,
# so a path reaching outside it would pass locally and fail there.
_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_MIGRATION_PATH = _VERSIONS_DIR / "0017_claim_attribution.py"

# Order matters: it is the order `upgrade()` adds them and the exact reverse of
# the order `downgrade()` drops them.
_NEW_COLUMNS = ("sub_question", "corroboration_key", "as_of")

_REVISION_RE = re.compile(r"^revision\s*(?::\s*str\s*)?=\s*[\"']([^\"']+)[\"']", re.M)
_DOWN_REVISION_RE = re.compile(
    r"^down_revision\s*(?::[^=]*)?=\s*[\"']([^\"']+)[\"']", re.M
)


def _load_migration_at(path: Path) -> ModuleType:
    """Import an alembic version file by path.

    Version filenames start with a digit, so they are not legal module names and
    cannot be reached by `import`. Executing one defines four names and does
    nothing else -- no connection, no DDL, no side effect.
    """
    assert path.is_file(), f"missing migration: {path}"
    spec = importlib.util.spec_from_file_location(f"_alembic_{path.stem}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_migration() -> ModuleType:
    return _load_migration_at(_MIGRATION_PATH)


def _executable_source(module: ModuleType) -> str:
    """The module source with every docstring and every comment removed.

    `ast.unparse` drops comments (they never enter the tree) and this strips the
    module-, class- and function-level docstrings explicitly. String literals
    that are ARGUMENTS -- `op.add_column("claim", ...)` -- are PRESERVED, which
    is the whole point.
    """
    tree = ast.parse(inspect.getsource(module))
    holders: list[ast.AST] = [tree]
    holders += [
        node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    for holder in holders:
        body = getattr(holder, "body", None)
        if not body:
            continue
        first = body[0]
        if (
            isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str)
        ):
            holder.body = body[1:] or [ast.Pass()]  # type: ignore[attr-defined]
    ast.fix_missing_locations(tree)
    return ast.unparse(tree)


def _alembic_operations(
    source: str, *, function: str | None = None
) -> list[tuple[str, str | None]]:
    """Every `op.<name>(...)` call in `source`, as (operation, first literal arg).

    The first positional argument of every alembic table operation is the table
    name, so this yields "what was done, and to what" for a whole migration or
    for one named function of it.
    """
    tree: ast.AST = ast.parse(source)
    if function is not None:
        matches = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == function
        ]
        assert len(matches) == 1, f"expected exactly one def {function}()"
        tree = matches[0]

    found: list[tuple[str, str | None]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not isinstance(func, ast.Attribute):
            continue
        target = func.value
        if not (isinstance(target, ast.Name) and target.id == "op"):
            continue
        first: str | None = None
        if node.args and isinstance(node.args[0], ast.Constant):
            value = node.args[0].value
            if isinstance(value, str):
                first = value
        found.append((func.attr, first))
    return found


# --------------------------------------------------------------------------
# 1. The revision chain
#
# CAN prove: 0017 declares 0016 as its parent, no other file claims that parent
# or that id, and every revision id in the directory is unique.
# CANNOT prove: that `alembic upgrade head` ever ran. See the module docstring
# -- that proof is the literal `Running upgrade 0016 -> 0017` line, owed at
# phase 15.8.
# --------------------------------------------------------------------------

def test_the_revision_chain_is_0016_to_0017() -> None:
    """0017 revises 0016. A break here is how a migration silently never runs.

    `alembic upgrade head` walks down_revision pointers. A wrong id does not
    error loudly -- it just leaves this revision off the path to head, so the
    three columns never appear in production while every test in this file still
    passes.

    The spec text says "on top of 0015". That sentence predates wave 1 landing
    0016 and is stale; the verified head is 0016, and this assertion is what
    keeps the correction from drifting back.
    """
    module = _load_migration()

    assert module.revision == "0017"
    assert module.down_revision == "0016"
    # A branch label or a depends_on would take 0017 off the single linear path
    # that `alembic upgrade head` follows in this repository.
    assert module.branch_labels is None
    assert module.depends_on is None


def test_no_other_tribunal_revision_claims_0017_or_forks_off_0016() -> None:
    """One id per revision, and exactly one child of 0016.

    Two files claiming the same id, or two claiming the same parent, is a forked
    chain: alembic then refuses to resolve a head and the deploy fails -- or it
    resolves the branch that is not this file.
    """
    revisions: dict[str, str] = {}
    children_of_0016: list[str] = []

    for path in sorted(_VERSIONS_DIR.glob("[0-9]*.py")):
        text = path.read_text(encoding="utf-8")
        revs = _REVISION_RE.findall(text)
        downs = _DOWN_REVISION_RE.findall(text)
        assert len(revs) == 1, f"{path.name}: expected 1 revision id, got {revs}"
        assert len(downs) <= 1, f"{path.name}: expected <=1 down_revision, got {downs}"

        rev = revs[0]
        assert rev not in revisions, (
            f"duplicate revision id {rev}: {path.name} and {revisions[rev]}"
        )
        revisions[rev] = path.name
        if downs and downs[0] == "0016":
            children_of_0016.append(path.name)

    assert revisions.get("0017") == "0017_claim_attribution.py"
    assert children_of_0016 == ["0017_claim_attribution.py"], children_of_0016


def test_the_migration_states_its_deploy_proof_as_owed_and_never_as_done() -> None:
    """The proof obligation is written down, in the file, as an obligation.

    This is the one thing a reviewer cannot re-derive from code: whether anybody
    still owes the deploy-time assertion. `Running upgrade 0016 -> 0017` must
    appear as a LITERAL, unwrapped line -- a wrapped one cannot be grepped for in
    a deploy log, which is the only place it will ever be checked.
    """
    raw = inspect.getsource(_load_migration())
    doc = ast.get_docstring(ast.parse(raw)) or ""

    assert "Running upgrade 0016 -> 0017" in doc
    # 0016 has never touched a database either; both debts are named here so
    # neither is forgotten at 15.8.
    assert "Running upgrade 0015 -> 0016" in doc
    assert "OWED AT PHASE 15.8" in doc
    assert "WRITTEN, NOT APPLIED" in doc
    assert "PERFORMS NO DEPLOY" in doc


# --------------------------------------------------------------------------
# 2. The migration body, as an ALLOWLIST
#
# This reads the UNPARSED SOURCE, not the raw file. A grep-based check passes on
# a COMMENT that merely mentions a column name, and this migration mentions all
# three of them in prose repeatedly. `ast.unparse` keeps string literals that are
# ARGUMENTS and drops docstrings and comments, so what is scanned is exactly the
# text that can execute.
#
# Stated as an ALLOWLIST -- "these operations and nothing else" -- rather than a
# denylist. A denylist can only rule out the harm someone thought to name.
# --------------------------------------------------------------------------

def test_the_migration_only_adds_and_drops_three_columns_on_claim() -> None:
    """Three add_column up, three drop_column down, all six on `claim`.

    The invariant is ADDITIVE ONLY: no existing row is read, written, backfilled
    or deleted. Legacy rows predate all three columns and the `claim_distiller`
    fallback path carries no dispatch attribution at all by construction, so any
    backfill would be a fabrication.
    """
    code = _executable_source(_load_migration())

    assert _alembic_operations(code, function="upgrade") == [
        ("add_column", "claim"),
        ("add_column", "claim"),
        ("add_column", "claim"),
    ]
    assert _alembic_operations(code, function="downgrade") == [
        ("drop_column", "claim"),
        ("drop_column", "claim"),
        ("drop_column", "claim"),
    ]
    # And no alembic operation anywhere outside those two functions.
    assert len(_alembic_operations(code)) == 6


def test_the_migration_does_nothing_but_add_columns() -> None:
    """DENYLIST over executable code only, backing up the allowlist above.

    No index (none of the three columns is searched across tenants), no CHECK
    (a threading bug must not become a FAILED INSERT in the final persistence
    step of a paid run), no security DDL (a row-level POLICY is a TABLE-level
    object, so a new column is covered by construction), no data statement.
    """
    module = _load_migration()
    code = _executable_source(module)

    for forbidden in (
        "create_index",
        "drop_index",
        "create_table",
        "drop_table",
        "create_check_constraint",
        "drop_constraint",
        "alter_column",
        "op.execute",
        "UPDATE ",
        "DELETE ",
        "INSERT ",
        "POLICY",
        "GRANT",
        "server_default",
        "nullable=False",
    ):
        assert forbidden not in code, forbidden

    # The prose the scan strips must still STATE the invariant. Deleting the
    # docstring to satisfy the scan would be exactly the wrong way round.
    raw = inspect.getsource(module)
    assert "ADDITIVE ONLY" in raw
    assert "Why nullable" in raw


def test_the_three_columns_are_named_typed_and_nullable_in_the_ddl() -> None:
    """TEXT, TEXT, DATE -- and `nullable=True` on every one of the three.

    NULLABLE is the load-bearing word: `corroboration_key` will be NULL for
    roughly 12 of 15 winners on the next run, because only the top-3 winners get
    a dispatch key today (D-W2-2). That is correct, not a gap to be filled.
    """
    code = _executable_source(_load_migration())

    added = re.findall(r"sa\.Column\(['\"]([a-z_]+)['\"]", code)
    dropped = re.findall(r"op\.drop_column\(['\"]claim['\"],\s*['\"]([a-z_]+)", code)

    assert added == list(_NEW_COLUMNS), added
    # Exact inverse order.
    assert dropped == list(reversed(_NEW_COLUMNS)), dropped

    assert code.count("nullable=True") == 3
    assert code.count("sa.Text()") == 2
    assert code.count("sa.Date()") == 1
    # DATE and not TIMESTAMP: a claim is dated to a day at best.
    assert "sa.DateTime" not in code


# --------------------------------------------------------------------------
# 3. The negative control
#
# Section 2 could be a scan that never bites. This phase exists because a silent
# failure was reported as a success, so the scan is proved to FAIL on a
# deliberately bad migration -- through THE SAME HELPERS, not a parallel copy.
# --------------------------------------------------------------------------

def test_the_scan_bites_on_a_deliberately_bad_migration(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for section 2, through the SAME helpers.

    The bad migration adds an index and a NOT NULL column, and it also names
    both offences in a DOCSTRING and a COMMENT. So this proves two things at
    once: that the scan catches the real operations, and that the docstring
    stripping does not swallow the EXECUTABLE occurrence -- the one way the
    source-reading approach could have quietly made the scan useless.
    """
    bad_path = tmp_path / "9999_bad_migration.py"
    bad_path.write_text(
        '"""A migration that DOES create_index and DOES use nullable=False."""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "\n"
        'revision: str = "9999"\n'
        'down_revision = "0017"\n'
        "\n"
        "\n"
        "def upgrade() -> None:\n"
        '    """This docstring says create_index and nullable=False harmlessly."""\n'
        "    # ...and so does this comment: create_index, nullable=False\n"
        '    op.add_column("claim", sa.Column("sub_question", sa.Text(), nullable=False))\n'
        '    op.create_index("idx_claim_sub_question", "claim", ["sub_question"])\n',
        encoding="utf-8",
    )

    code = _executable_source(_load_migration_at(bad_path))

    # The docstring and comment mentions vanish...
    assert "harmlessly" not in code
    assert "and so does this comment" not in code
    # ...and the executable operations, string arguments included, do not.
    assert "create_index" in code
    assert "nullable=False" in code
    assert ("create_index", "idx_claim_sub_question") in _alembic_operations(code)

    # The ALLOWLIST form of section 2 catches it on shape alone.
    assert _alembic_operations(code, function="upgrade") != [
        ("add_column", "claim"),
        ("add_column", "claim"),
        ("add_column", "claim"),
    ]
    # And the DENYLIST form catches it too, so neither test is the only guard.
    for forbidden in ("create_index", "nullable=False"):
        assert forbidden in code


# --------------------------------------------------------------------------
# 4. ORM/DDL agreement, and the `as_of` grammar
#
# THERE IS DELIBERATELY NO RLS TEST IN THIS FILE, AND ITS ABSENCE IS NOT AN
# OVERSIGHT. Two independent reasons, both of which have bitten this repository:
#
#  (a) A PostgreSQL row-level POLICY is a TABLE-level object evaluated against
#      ROW VALUES. `claim` already carries ENABLE + FORCE ROW LEVEL SECURITY and
#      its `claim_tenant_isolation` / `claim_worker_all` policies, so a NEWLY
#      ADDED COLUMN IS COVERED BY CONSTRUCTION -- the same reasoning migrations
#      0013 and 0016 both record. There is no new isolation behaviour to test.
#
#  (b) This gate PROVISIONS NO DATABASE. A role-less DB test would connect as
#      SUPERUSER, and RLS DOES NOT APPLY TO A SUPERUSER: every isolation
#      assertion would PASS VACUOUSLY. That is strictly worse than no test,
#      because it reports as proof. The harness that can honestly run RLS
#      assertions is cloudbuild.test-rls.yaml, with its non-superuser DSN.
#
# Do not add one here later thinking it was forgotten.
# --------------------------------------------------------------------------

def test_all_three_columns_exist_and_are_nullable_on_the_orm() -> None:
    """The ORM half of the lock-step rule.

    The ORM and the migration are two independent statements of one schema. A
    column added to one and misspelled in the other fails at runtime, in
    production, on the persistence step of a roughly $50 run.
    """
    from nestor_pulse_sdk.db.models import Claim

    columns = Claim.__table__.c

    for name in _NEW_COLUMNS:
        assert name in columns, name
        assert columns[name].nullable is True, name
        # No default of any kind. An existing row must read back as NULL --
        # "nothing was recorded" -- and not as a placeholder that looks like
        # data. This is the `found_by` rule: an ABSENT value is None, never ''
        # and never [], because "no key recorded" and "recorded as the empty
        # key" are different facts.
        assert columns[name].server_default is None, name
        assert columns[name].default is None, name


def test_the_orm_column_types_are_text_text_and_date() -> None:
    """DATE for `as_of`, and TEXT for the two attribution strings.

    `as_of` is a DATE and not a DATETIME on purpose: a claim is dated to a day at
    best, and a spurious time component would invite false ordering between two
    claims from the same day.
    """
    from sqlalchemy import Date, Text

    from nestor_pulse_sdk.db.models import Claim

    columns = Claim.__table__.c

    assert isinstance(columns["sub_question"].type, Text)
    assert isinstance(columns["corroboration_key"].type, Text)
    assert isinstance(columns["as_of"].type, Date)


def test_the_ddl_column_names_match_the_orm_column_names() -> None:
    """The lock-step rule, asserted rather than trusted."""
    from nestor_pulse_sdk.db.models import Claim

    code = _executable_source(_load_migration())
    added = re.findall(r"sa\.Column\(['\"]([a-z_]+)['\"]", code)

    assert sorted(added) == sorted(_NEW_COLUMNS), added
    for name in added:
        assert name in Claim.__table__.c


def test_the_claim_model_carries_exactly_the_columns_it_should() -> None:
    """The whole column set, named. Nine before 0017, twelve after."""
    from nestor_pulse_sdk.db.models import Claim

    assert set(Claim.__table__.c.keys()) == {
        "id",
        "tenant_id",
        "run_id",
        "text",
        "facet",
        "position",
        "certainty",
        "found_by",
        "sub_question",
        "corroboration_key",
        "as_of",
        "created_at",
    }
    assert len(Claim.__table__.c) == 12


# --- the as_of grammar ----------------------------------------------------
# `extract_as_of` is the ONLY place in phase 15.5 where a persisted value is
# derived from model output, so its REJECTIONS are asserted as hard as its
# acceptances. A wrong date is worse than no date: it turns a real contradiction
# into a fake time series, which is the failure that made this column necessary.

_ACCEPTED: list[tuple[str, datetime.date]] = [
    # ISO 8601 -- the only accepted all-numeric form.
    ("2021-03-04", datetime.date(2021, 3, 4)),
    ("gepubliceerd 2021-03-04", datetime.date(2021, 3, 4)),
    # Textual month WITH an explicit day, both orders, EN and NL, any case.
    ("4 maart 2021", datetime.date(2021, 3, 4)),
    ("4 March 2021", datetime.date(2021, 3, 4)),
    ("March 4, 2021", datetime.date(2021, 3, 4)),
    ("4 mrt 2021", datetime.date(2021, 3, 4)),
    ("4 Mar 2021", datetime.date(2021, 3, 4)),
    ("4 MAART 2021", datetime.date(2021, 3, 4)),
    ("op 4 december 2019 stond er", datetime.date(2019, 12, 4)),
    # A bare year -> JANUARY 1, the year-precision CONVENTION (not a stated day).
    ("2021", datetime.date(2021, 1, 1)),
    ("bron uit 2021", datetime.date(2021, 1, 1)),
    # D-W2-4: MONTH PRECISION keeps the month and encodes it as the 1st of that
    # month -- the same "first of the stated period" convention as the bare year
    # one level up. This REPLACED an earlier reading that let `maart 2021` fall
    # through to the bare-year rule and return 2021-01-01, silently overwriting
    # March with January.
    #
    # The overturned behaviour was not merely lossy, it was the exact failure
    # this column exists to prevent: De Haan reported 7 sites in one article and
    # ~90 in a later one, and `maart 2021` / `december 2021` both collapsing onto
    # 2021-01-01 records a nine-month rollout as one instant -- a contradiction
    # rather than a time series (V-01 finding D-V01-4).
    ("maart 2021", datetime.date(2021, 3, 1)),
    ("March 2021", datetime.date(2021, 3, 1)),
    ("Mar 2021", datetime.date(2021, 3, 1)),
    ("in december 2021 waren het er 90", datetime.date(2021, 12, 1)),
    # Numeric month precision, both orders, same convention.
    ("2021-03", datetime.date(2021, 3, 1)),
    ("03-2021", datetime.date(2021, 3, 1)),
    ("2021/03", datetime.date(2021, 3, 1)),
    # One explicit full date beats a trailing archive year: extra bare years are
    # ignored because the full date is the more precise statement.
    ("2021-03-04, gearchiveerd 2023", datetime.date(2021, 3, 4)),
    # The same date stated twice is ONE distinct candidate, not two.
    ("2021-03-04 en nogmaals 4 maart 2021", datetime.date(2021, 3, 4)),
]

_REJECTED: list[str] = [
    # Ambiguous all-numeric orders. `03/04/2021` is not decidable between DD/MM
    # and MM/DD, and guessing is how a contradiction becomes a time series.
    "03/04/2021",
    "3-4-2021",
    "04.03.2021",
    "04-03-2021",
    # A two-digit year.
    "04-03-21",
    # D-W2-4 moved numeric month precision (`2021-03`, `03-2021`, `2021/03`) OUT
    # of this list and into _ACCEPTED. It is deliberately NOT re-listed here.
    # Two month-precision statements in one cell are still two candidates, and
    # the single-candidate rule still refuses to pick between them.
    "maart 2021 en december 2021",
    "2021-03 en 2021-07",
    # Impossible calendar dates -- and the year inside one must NOT leak out as
    # a bare year, which is why these are None and not 2021-01-01.
    "2021-02-30",
    "2021-13-01",
    # Out of the 1900..2100 range, rejected rather than clamped.
    "1899",
    "2101",
    "1899-05-06",
    # Four digits inside a longer DIGIT run -- an id, not a year. Digit
    # boundaries, not word boundaries.
    "20211",
    "v20214",
    "https://example.test/a/20214/b",
    # More than one candidate: refuse rather than pick.
    "2020-2021",
    "tussen 2019 en 2023",
    "2021-03-04 en 2019-01-02",
    # Nothing at all.
    "geen datum hier",
    "",
]


@pytest.mark.parametrize("evidence,expected", _ACCEPTED)
def test_extract_as_of_accepts(evidence: str, expected: datetime.date) -> None:
    from nestor_pulse_sdk.pipeline.synthesis.claim_attribution import extract_as_of

    assert extract_as_of(evidence) == expected


@pytest.mark.parametrize("evidence", _REJECTED)
def test_extract_as_of_rejects(evidence: str) -> None:
    from nestor_pulse_sdk.pipeline.synthesis.claim_attribution import extract_as_of

    assert extract_as_of(evidence) is None


@pytest.mark.parametrize("evidence", [None, 12345, 3.5, [], {}, b"2021-03-04", object()])
def test_extract_as_of_returns_none_on_non_string_input(evidence: object) -> None:
    """NEVER RAISES is a hard guarantee, not a best effort.

    This runs on the persistence path of a paid run. An exception here would
    trade a missing date for lost claims (threat T-15.5-01).
    """
    from nestor_pulse_sdk.pipeline.synthesis.claim_attribution import extract_as_of

    assert extract_as_of(evidence) is None  # type: ignore[arg-type]


def test_extract_as_of_survives_a_hostile_hundred_kilobyte_input() -> None:
    """Untrusted model output is BOUNDED before it is scanned (T-15.5-02).

    Only the first 2000 characters are read, and the patterns are flat
    alternations with no nested quantifiers, so there is no catastrophic
    backtracking to trigger.
    """
    from nestor_pulse_sdk.pipeline.synthesis.claim_attribution import extract_as_of

    for hostile in (
        "x" * 100_000,
        "1" * 100_000,
        "-" * 50_000 + "2021",
        "2021-03-04" * 20_000,
        "maart " * 30_000,
        ("2019 " * 25_000) + "2021-03-04",
    ):
        assert len(hostile) >= 100_000 or hostile.endswith("2021")
        extract_as_of(hostile)  # must not raise and must not hang

    # The bound is REAL, not decorative: a date past character 2000 is unseen.
    assert extract_as_of(" " * 2500 + "2021-03-04") is None
    assert extract_as_of(" " * 1980 + "2021-03-04") == datetime.date(2021, 3, 4)


def test_extract_as_of_returns_a_date_and_never_a_datetime() -> None:
    """`claim.as_of` is a DATE column; a datetime would carry a fake midnight."""
    from nestor_pulse_sdk.pipeline.synthesis.claim_attribution import extract_as_of

    for evidence in ("2021-03-04", "2021", "4 maart 2021"):
        value = extract_as_of(evidence)
        assert type(value) is datetime.date
        assert not isinstance(value, datetime.datetime)


def test_the_extractor_module_stays_stdlib_pure() -> None:
    """Stdlib-only is what makes this function provable without pytest.

    The dev box has no pytest, no sqlalchemy and no Docker, but does ship a
    stdlib-only Python. A stdlib-pure module can be lifted out of the COMMITTED
    source and DRIVEN there, which is how the grammar above was proved before it
    ever reached this gate. An import from elsewhere in the SDK would take that
    away, so it is asserted rather than hoped for.
    """
    from nestor_pulse_sdk.pipeline.synthesis import claim_attribution

    tree = ast.parse(inspect.getsource(claim_attribution))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert imported <= {"re", "datetime", "logging", "__future__"}, imported


# --------------------------------------------------------------------------
# 5. THE WRITE PATH -- does anything actually PUT the three values in the row?
#
# Sections 1-4 prove the columns EXIST. That is not the same as proving they
# are ever written, and this repository has the scar: before plan 15.1-14
# NOTHING in production wrote a `verification_verdict` row, the table was
# schema-perfect, and every report published four empty verdict lists. A column
# with no writer is exactly as useless as a column that does not exist, and it
# is harder to notice.
#
# WHAT THIS SECTION CAN PROVE
#   That `persist_tribunal_claims` names all three columns in its claim INSERT,
#   binds the claim dict values through unchanged, coerces ABSENT and EMPTY to
#   NULL, truncates an over-long value, refuses a non-date `as_of`, and runs the
#   whole thing INSIDE the tenant context.
#
# WHAT IT CANNOT PROVE, AND WHY NO ATTEMPT IS MADE
#   It cannot prove that RLS actually DENIES a cross-tenant write. That needs a
#   real Postgres AND a non-superuser role, and this gate provisions neither: a
#   DB-bound test here would connect as SUPERUSER, RLS does not apply to a
#   superuser, and every isolation assertion would PASS VACUOUSLY -- reporting
#   as proof while proving nothing, which is strictly worse than no test.
#
#   The enforcement is covered BY CONSTRUCTION instead. A PostgreSQL row-level
#   POLICY is a TABLE-level object evaluated against row values, so the three
#   columns added by 0017 are governed by `claim`s existing
#   `claim_tenant_isolation` / `claim_worker_all` policies (migrations 0003 and
#   0008) with no new DDL -- the same reasoning migrations 0013 and 0016 record.
#   What is left to check is that the INSERT runs where the policy can see it,
#   and that is an ORDERING fact about the recorded calls, which a fake session
#   proves honestly. Hence `test_the_tenant_context_is_set_before_the_first_
#   claim_insert` below and no `test_cross_tenant_read_is_denied` anywhere.
#
# THE HARNESS IS COPIED, NOT IMPORTED, from test_verdict_write_path.py -- the
# same choice test_source_resolution.py made, and for the same reason: those
# two files are collected by DIFFERENT Cloud Build configs, and a fixture shared
# across a gate boundary is a coupling neither config expresses. A file that
# imports its harness from a file the other gate owns can be broken by an edit
# nobody ran against it.
#
# PURE: no Postgres, no network, no provider key, no mocking library.
# `asyncio_mode = "auto"` is set in pyproject.toml, so the async tests need no
# decorator.
# --------------------------------------------------------------------------

_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_RUN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

# SQL needles. The trailing paren in "INSERT INTO claim (" is load-bearing: it
# keeps claim rows distinct from the "INSERT INTO claim_source (" join rows,
# which would otherwise match the same prefix.
_CLAIM_INSERT = "INSERT INTO claim ("
_TENANT_CONTEXT = "set_config"


class _FakeResult:
    """Enough of a Result for the RETURNING path in `_upsert_source`."""

    def __init__(self) -> None:
        self._row = SimpleNamespace(id=uuid.uuid4())

    def first(self):
        return self._row


class _FakeSession:
    """Records `(sql_text, params)` per execute. Opens no connection.

    No begin/commit on purpose: `persist_tribunal_claims` is documented as
    running inside a transaction the CALLER opens.
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _FakeResult()


def _sql(calls: list[tuple[str, dict]], needle: str) -> list[tuple[str, dict]]:
    """The recorded calls whose SQL text contains `needle`, in call order."""
    return [(s, p) for s, p in calls if needle in s]


def _params(calls: list[tuple[str, dict]], needle: str) -> list[dict]:
    return [p for _, p in _sql(calls, needle)]


async def _persist(claims: list[dict]) -> _FakeSession:
    """Drive the real `persist_tribunal_claims` over a fake session."""
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    session = _FakeSession()
    await persist_tribunal_claims(
        claims=claims,
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )
    return session


async def _one_claim_row(claim: dict) -> dict:
    """The single bound parameter dict for a one-claim run."""
    session = await _persist([claim])
    rows = _params(session.calls, _CLAIM_INSERT)
    assert len(rows) == 1, f"expected exactly one claim row, got {len(rows)}"
    return rows[0]


async def test_the_claim_insert_names_all_three_new_columns() -> None:
    """The statement text, not the model -- a column the INSERT never names is
    a column that is NULL on every row forever, whatever the ORM says.

    The COLUMN LIST and the VALUES list are checked SEPARATELY, and that split
    is not fussiness. A plain `"as_of" in sql_text` is satisfied by the `:as_of`
    PLACEHOLDER in the VALUES clause, so a statement that had lost `as_of` from
    its column list -- the exact shape that writes nothing while looking
    correct -- passed a substring check during this test's own mutation run. The
    two halves are split here so that mutation turns it red.
    """
    session = await _persist([{"text": "Rate X stood at 21 percent.", "facet": "market"}])
    statements = _sql(session.calls, _CLAIM_INSERT)

    assert statements, "no claim INSERT was recorded at all"
    sql_text = statements[0][0]

    head, _, tail = sql_text.partition("VALUES")
    assert tail, f"no VALUES clause in the claim INSERT: {sql_text}"

    for column in _NEW_COLUMNS:
        assert column in head, f"{column} missing from the INSERT COLUMN LIST"
        assert f":{column}" in tail, f":{column} missing from the VALUES list"

    # The column list and the VALUES list must also be the same LENGTH -- a
    # mismatch is a runtime error in the final persistence transaction of a
    # roughly $50 run, and nowhere earlier.
    columns = [c.strip() for c in head[head.index("(") + 1:head.rindex(")")].split(",")]
    values = [v.strip().lstrip(":") for v in tail[tail.index("(") + 1:tail.rindex(")")].split(",")]
    assert len(columns) == len(values), f"{len(columns)} columns vs {len(values)} values"

    # The three new columns must sit at the SAME INDEX in both lists, or each
    # value lands in the wrong column. (The first three pre-existing binds are
    # deliberately named `tid` / `rid` rather than after their columns, so the
    # two lists are compared positionally for the D-R3 columns, not by name.)
    for column in _NEW_COLUMNS:
        assert columns.index(column) == values.index(column), column

    # And the values actually reach the driver, keyed by those names.
    assert set(_NEW_COLUMNS) <= set(statements[0][1]), statements[0][1].keys()


async def test_the_three_values_are_bound_through_unchanged() -> None:
    """The happy path. Nothing between the claim dict and the row rewrites a
    value that is already valid."""
    row = await _one_claim_row(
        {
            "text": "De Haan operated 7 sites.",
            "facet": "market",
            "sub_question": "How many sites did De Haan operate?",
            "corroboration_key": "w01",
            "as_of": datetime.date(2021, 3, 4),
        }
    )

    assert row["sub_question"] == "How many sites did De Haan operate?"
    assert row["corroboration_key"] == "w01"
    assert row["as_of"] == datetime.date(2021, 3, 4)


async def test_a_pre_15_5_claim_dict_binds_three_nulls_and_does_not_raise() -> None:
    """D-R3 invariant 1. A claim dict built before phase 15.5 -- and every dict
    the `claim_distiller` fallback path produces, which carries NO dispatch
    attribution by construction -- has none of the three keys. It must keep
    working and write NULLs, not raise a KeyError inside the final persistence
    transaction of a roughly $50 run.
    """
    row = await _one_claim_row({"text": "A fact with no attribution.", "facet": "market"})

    assert row["sub_question"] is None
    assert row["corroboration_key"] is None
    assert row["as_of"] is None


async def test_an_empty_corroboration_key_binds_as_null_not_as_the_empty_string() -> None:
    """D-W2-2, and the single most load-bearing assertion in this section.

    `research_division.py` deals the top-3 winners a real key and deals the
    REMAINDER round-robin with the EMPTY STRING, so roughly 12 of 15 winners
    arrive here with `""`. `is None` rather than `not value` is deliberate: the
    empty string is falsy too, and a falsiness check would pass on exactly the
    bug this asserts against. "No key recorded" and "recorded as the empty key"
    are DIFFERENT FACTS -- the first is the honest state of a claim outside the
    top 3, the second is a claim that belongs to a corroboration group whose key
    is the empty string, and a corroboration query joining on the column must be
    able to tell them apart.
    """
    row = await _one_claim_row(
        {"text": "A remainder-stream fact.", "facet": "market", "corroboration_key": ""}
    )

    assert row["corroboration_key"] is None
    # Whitespace-only is the same fact wearing a hat.
    row = await _one_claim_row(
        {"text": "Another one.", "facet": "market", "corroboration_key": "   "}
    )
    assert row["corroboration_key"] is None

    # Same rule for the sibling column.
    row = await _one_claim_row(
        {"text": "And a third.", "facet": "market", "sub_question": ""}
    )
    assert row["sub_question"] is None


async def test_an_over_long_sub_question_is_truncated_to_the_cap() -> None:
    """A bug bound, not an injection control -- these values are caller-supplied
    -- but the column must not be a place a bug can write unbounded data. The
    cap is read from the module rather than hardcoded here, so raising it stays
    a one-line change instead of a two-file one."""
    from nestor_pulse_sdk.citations.extractor import (
        _CORROBORATION_KEY_MAX_CHARS,
        _SUB_QUESTION_MAX_CHARS,
    )

    row = await _one_claim_row(
        {
            "text": "A fact.",
            "facet": "market",
            "sub_question": "q" * (_SUB_QUESTION_MAX_CHARS + 250),
            "corroboration_key": "k" * (_CORROBORATION_KEY_MAX_CHARS + 10),
        }
    )

    assert len(row["sub_question"]) == _SUB_QUESTION_MAX_CHARS
    assert len(row["corroboration_key"]) == _CORROBORATION_KEY_MAX_CHARS

    # A value AT the cap is untouched -- the bound must not be off by one.
    exact = "e" * _SUB_QUESTION_MAX_CHARS
    row = await _one_claim_row(
        {"text": "A fact.", "facet": "market", "sub_question": exact}
    )
    assert row["sub_question"] == exact


async def test_an_as_of_string_binds_as_null_rather_than_reaching_the_column() -> None:
    """A date-shaped STRING that slipped past `extract_as_of` is refused here.

    The parsing already happened upstream, where every ambiguous form is
    rejected rather than guessed; this boundary only refuses what it cannot
    vouch for. A wrong date is worse than no date -- it turns a real
    contradiction into a fake time series, which is the failure that made this
    column necessary in the first place.
    """
    for bad in ("2021-03-04", "maart 2021", "", 20210304, ["2021-03-04"]):
        row = await _one_claim_row(
            {"text": "A fact.", "facet": "market", "as_of": bad}
        )
        assert row["as_of"] is None, bad


async def test_a_datetime_as_of_binds_as_a_date_so_no_time_can_reach_the_column() -> None:
    """`datetime` is a SUBCLASS of `date`, so an `isinstance(value, date)` test
    alone would let a timestamp through into a DATE column. It is narrowed with
    `.date()`, so two claims from the same day can never acquire a false
    ordering from a time nobody stated."""
    row = await _one_claim_row(
        {
            "text": "A fact.",
            "facet": "market",
            "as_of": datetime.datetime(2021, 3, 4, 13, 46, 7),
        }
    )

    assert row["as_of"] == datetime.date(2021, 3, 4)
    assert type(row["as_of"]) is datetime.date
    assert not isinstance(row["as_of"], datetime.datetime)


async def test_the_tenant_context_is_set_before_the_first_claim_insert() -> None:
    """RUNTIME ordering proof -- source line order cannot establish this.

    `_insert_claim` is DEFINED far above `persist_tribunal_claims`, so comparing
    source positions would invert and prove nothing. What matters is that every
    claim INSERT EXECUTES after `set_tenant_context`, in the same transaction,
    binding the same tenant_id: that is what puts the write -- and therefore the
    three new columns on it -- under `claim`s row-level policies rather than
    around them. This is the honest half of the RLS question; see the section
    heading for why the other half is deliberately not attempted here.
    """
    session = await _persist(
        [
            {"text": "First fact.", "facet": "market", "corroboration_key": "w01"},
            {"text": "Second fact.", "facet": "policy", "corroboration_key": "w02"},
        ]
    )

    context_idx = min(
        i for i, (s, _) in enumerate(session.calls) if _TENANT_CONTEXT in s
    )
    claim_idx = [i for i, (s, _) in enumerate(session.calls) if _CLAIM_INSERT in s]

    assert len(claim_idx) == 2, "expected one claim INSERT per survivor"
    assert all(i > context_idx for i in claim_idx)

    bound_tenant = session.calls[context_idx][1]["tid"]
    assert bound_tenant == str(_TENANT_ID)
    assert {p["tid"] for p in _params(session.calls, _CLAIM_INSERT)} == {bound_tenant}


async def test_the_pre_existing_columns_are_untouched_by_the_three_new_ones() -> None:
    """D-R3 invariant 3: NO BEHAVIOUR CHANGE BEYOND RECORDING.

    The 15.8 measuring run has to hold one variable still -- which claims reach
    paid verification -- so the D-13 columns beside the new ones are asserted to
    bind exactly as they did before, on the same call that now carries three
    more values.
    """
    row = await _one_claim_row(
        {
            "text": "A corroborated fact.",
            "facet": "market",
            "certainty": "certain",
            "found_by": ["gemini", "claude"],
            "corroboration_key": "w01",
        }
    )

    assert row["text"] == "A corroborated fact."
    assert row["facet"] == "market"
    assert row["position"] == 0
    assert row["certainty"] == "certain"
    assert row["found_by"] == ["gemini", "claude"]
