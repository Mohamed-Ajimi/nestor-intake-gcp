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
from pathlib import Path
from types import ModuleType

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
    # A textual month with NO day falls to the bare-year rule; the month is lost
    # and that is year precision doing its job.
    ("maart 2021", datetime.date(2021, 1, 1)),
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
    # Numeric month precision, both orders: it would have to fabricate a day.
    "2021-03",
    "03-2021",
    "2021/03",
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
