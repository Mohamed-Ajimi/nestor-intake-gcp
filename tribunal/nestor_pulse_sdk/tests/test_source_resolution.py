"""The 0016 contract: two nullable columns on `source`, and nothing else moved.

WHY THIS FILE EXISTS
--------------------
Gemini grounding citations arrive as `vertexaisearch.cloud.google.com` redirect
URLs that EXPIRE roughly 30 days after the run. D-V01-11 stores the publisher
URL those redirects resolve to ALONGSIDE the redirect itself, which needs two
new columns on `source` and tribunal alembic revision 0016. This file pins the
shape of that revision. The resolver that FILLS the columns is plan 15.4-09 and
extends this same file; nothing here asserts anything about resolution
behaviour yet.

WHAT THIS FILE CAN AND CANNOT PROVE
-----------------------------------
It can prove the revision chain is intact, that the ORM matches the DDL, and
that the migration's EXECUTABLE code performs exactly four operations and never
names the dedupe index. It CANNOT prove the migration RAN -- that proof is the
literal `Running upgrade 0015 -> 0016` line in the deploy log, which plan
15.4-11 owns. A chain break is precisely how a migration silently never runs
while every test stays green, which is why the chain is asserted here instead
of being read off the file by a human.

THE INDEX ASSERTION IS A SOURCE ASSERTION BY NATURE, AND IT IS SCOPED
---------------------------------------------------------------------
The claim under test is about what the migration DOES NOT DO: it must not drop,
recreate or alter `idx_source_tenant_content_hash`, because that partial UNIQUE
index IS per-tenant source dedupe, and plan 15.4-09 writes these columns on the
dedupe path. There is no runtime observation of a non-event, so the assertion
reads the source.

It reads the source WITH DOCSTRINGS AND COMMENTS REMOVED, via `ast.unparse`.
That is a deliberate correction to the plan's wording, which asked for the
index name to be absent from the whole file while ALSO requiring the migration
docstring to state, in words, that the index is untouched -- two requirements
that cannot both hold, and the docstring is the one a reviewer actually reads.
Prose cannot drop an index. A real `op.drop_index("idx_source_tenant_content_hash")`
survives `ast.unparse` string-literal and all, so the scoping costs the test
nothing -- and `test_the_scan_bites_on_a_deliberately_bad_migration` proves that
by running THESE SAME HELPERS over a migration that does drop the index. Without
that negative control the two scans could pass against a check that had no
defect to catch, and this phase exists because a silent failure was reported as
a success.

The primary assertion is an ALLOWLIST, not a denylist: the only alembic
operations in the module are two `add_column` and two `drop_column`, all four on
`source`. A denylist can only catch the wrongdoing someone thought to name.

THIS FILE OPENS NO DATABASE, MAKES ZERO LLM CALLS, USES NO MOCKING LIBRARY AND
NEEDS NO API KEY. It imports the ORM model (which builds table metadata in
memory) and the citation extractor (whose module-level code is imports and
constants -- `db/base.py` reads DATABASE_URL inside `get_engine`, never at
import). Importing the migration executes two module-level imports and four
function definitions; `upgrade()` is never called, so no DDL is emitted and no
alembic migration context is needed.

Cloud Build invocation (no Postgres and no provider key needed):
  gcloud builds submit tribunal \\
    --config=tribunal/cloudbuild.test-engine.yaml \\
    --project="$GOOGLE_PROJECT"
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import re
from pathlib import Path
from types import ModuleType


# --------------------------------------------------------------------------
# Locating the migration
# --------------------------------------------------------------------------
# parents[1] is `nestor_pulse_sdk/`. Resolved from THIS file rather than from a
# working directory, because the engine gate runs with /workspace mounted at the
# `tribunal/` source dir: nothing above `tribunal/` exists in that build context,
# so a path reaching outside it would pass locally and fail there.
_VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"
_MIGRATION_PATH = _VERSIONS_DIR / "0016_source_resolved_url.py"

_NEW_COLUMNS = ("resolved_url", "resolution_status")
_DEDUPE_INDEX = "idx_source_tenant_content_hash"

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
    that are ARGUMENTS -- `op.drop_index("idx_...")` -- are preserved, which is
    the whole point: what remains is exactly the text that can execute.
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
    for one named function of it. Scoped per function rather than read off the
    module in tree order, so the assertion says WHICH DIRECTION does what.
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
# --------------------------------------------------------------------------

def test_the_revision_chain_is_0015_to_0016() -> None:
    """0016 revises 0015. A break here is how a migration silently never runs.

    `alembic upgrade head` walks down_revision pointers. A wrong id does not
    error loudly -- it just leaves this revision off the path to head, so the
    two columns never appear in production while every test in this file still
    passes.
    """
    module = _load_migration()

    assert module.revision == "0016"
    assert module.down_revision == "0015"
    # A branch label or a depends_on would take 0016 off the single linear path
    # that `alembic upgrade head` follows in this repository.
    assert module.branch_labels is None
    assert module.depends_on is None


def test_no_other_tribunal_revision_claims_0016_or_forks_off_0015() -> None:
    """One id per revision, and exactly one child of 0015.

    Two files claiming the same id, or two claiming the same parent, is a forked
    chain: alembic then refuses to resolve a head and the deploy fails -- or it
    resolves the branch that is not this file.
    """
    revisions: dict[str, str] = {}
    children_of_0015: list[str] = []

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
        if downs and downs[0] == "0015":
            children_of_0015.append(path.name)

    assert revisions.get("0016") == "0016_source_resolved_url.py"
    assert children_of_0015 == ["0016_source_resolved_url.py"], children_of_0015


# --------------------------------------------------------------------------
# 2. The migration does exactly four things
# --------------------------------------------------------------------------

def test_the_migration_only_adds_and_drops_two_columns_on_source() -> None:
    """ALLOWLIST. Two add_column up, two drop_column down, all four on `source`.

    Stated as "these and nothing else" rather than "not these": the invariant is
    ADDITIVE ONLY -- no existing row read, written, backfilled or deleted -- and
    a denylist can only rule out the harm someone thought to name.
    """
    code = _executable_source(_load_migration())

    assert _alembic_operations(code, function="upgrade") == [
        ("add_column", "source"),
        ("add_column", "source"),
    ]
    assert _alembic_operations(code, function="downgrade") == [
        ("drop_column", "source"),
        ("drop_column", "source"),
    ]
    # And no alembic operation anywhere outside those two functions.
    assert len(_alembic_operations(code)) == 4


def test_the_migration_never_names_the_dedupe_index_in_executable_code() -> None:
    """DENYLIST over code only -- see this module's docstring for the scoping.

    `idx_source_tenant_content_hash` IS per-tenant source dedupe. Plan 15.4-09
    writes these columns on the dedupe path, so an index that quietly changed
    shape underneath it would corrupt dedupe rather than fail loudly
    (threat T-15.4-05).
    """
    module = _load_migration()
    code = _executable_source(module)

    assert "drop_index" not in code
    assert "create_index" not in code
    assert _DEDUPE_INDEX not in code
    assert "idx_source_tenant_url" not in code
    for forbidden in (
        "drop_table",
        "create_table",
        "drop_constraint",
        "create_check_constraint",
        "alter_column",
        "op.execute",
        "UPDATE ",
        "DELETE ",
        "server_default",
    ):
        assert forbidden not in code, forbidden

    # The prose the scan strips must still STATE the invariant. Deleting the
    # docstring to satisfy the scan would be exactly the wrong way round.
    raw = inspect.getsource(module)
    assert _DEDUPE_INDEX in raw
    assert "ADDITIVE ONLY" in raw


def test_the_scan_bites_on_a_deliberately_bad_migration(tmp_path: Path) -> None:
    """NEGATIVE CONTROL for the two tests above, through the SAME helpers.

    The bad migration names the index in a DOCSTRING as well as in a real
    `op.drop_index` call, so this also proves the docstring stripping does not
    swallow the executable occurrence -- the one way the scoping above could
    have quietly made the scan useless.
    """
    bad_path = tmp_path / "9999_bad_migration.py"
    bad_path.write_text(
        '"""A migration that DOES touch idx_source_tenant_content_hash."""\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n"
        "\n"
        'revision: str = "9999"\n'
        'down_revision = "0016"\n'
        "\n"
        "\n"
        "def upgrade() -> None:\n"
        '    """This docstring names idx_source_tenant_content_hash harmlessly."""\n'
        "    # ...and so does this comment: idx_source_tenant_content_hash\n"
        '    op.add_column("source", sa.Column("resolved_url", sa.Text(), nullable=True))\n'
        '    op.drop_index("idx_source_tenant_content_hash", table_name="source")\n',
        encoding="utf-8",
    )

    code = _executable_source(_load_migration_at(bad_path))

    # The docstring and comment mentions vanish...
    assert "harmlessly" not in code
    assert "and so does this comment" not in code
    # ...and the executable call, string argument included, does not.
    assert "drop_index" in code
    assert _DEDUPE_INDEX in code
    assert ("drop_index", _DEDUPE_INDEX) in _alembic_operations(code)
    # The allowlist form catches it too, on shape alone.
    assert _alembic_operations(code, function="upgrade") != [
        ("add_column", "source"),
        ("add_column", "source"),
    ]


# --------------------------------------------------------------------------
# 3. The ORM is in lock-step with the DDL
# --------------------------------------------------------------------------

def test_both_new_columns_exist_and_are_nullable_on_the_orm() -> None:
    """NULLABLE is the load-bearing word.

    A NOT NULL column here would demand a backfill of every historic `source`
    row with a publisher URL nobody has: the redirects of past runs have already
    expired, so any backfilled value would be invented.
    """
    from nestor_pulse_sdk.db.models import Source

    columns = Source.__table__.c

    for name in _NEW_COLUMNS:
        assert name in columns, name
        assert columns[name].nullable is True, name
        # No default of any kind: an existing row must read back as NULL --
        # "never attempted" -- and not as a placeholder that looks like data.
        assert columns[name].server_default is None, name
        assert columns[name].default is None, name


def test_the_source_model_has_exactly_twelve_columns() -> None:
    """The whole column set, named. Ten before 0016, twelve after."""
    from nestor_pulse_sdk.db.models import Source

    assert set(Source.__table__.c.keys()) == {
        "id",
        "tenant_id",
        "url",
        "title",
        "provider",
        "fetched_at",
        "snapshot_text",
        "snapshot_gcs_uri",
        "content_hash",
        "resolved_url",
        "resolution_status",
        "created_at",
    }
    assert len(Source.__table__.c) == 12


def test_the_source_indexes_are_unchanged_and_there_is_no_third_one() -> None:
    """The same two indexes as before 0016, partial UNIQUE intact.

    `resolved_url` is read back per source row and never searched across
    tenants, so it gets no index of its own -- and an index added here would be
    a build and a per-write cost on the persistence path of a paid run.
    """
    from nestor_pulse_sdk.db.models import Source

    indexes = {index.name: index for index in Source.__table__.indexes}

    assert set(indexes) == {"idx_source_tenant_url", _DEDUPE_INDEX}
    dedupe = indexes[_DEDUPE_INDEX]
    assert dedupe.unique is True
    assert [column.name for column in dedupe.columns] == ["tenant_id", "content_hash"]
    # The PARTIAL clause is the half that makes the UNIQUE constraint usable:
    # without `WHERE content_hash IS NOT NULL`, every hash-less row would
    # collide with every other hash-less row of the same tenant.
    assert dedupe.dialect_kwargs["postgresql_where"] is not None


def test_the_ddl_column_names_match_the_orm_column_names() -> None:
    """The lock-step rule, asserted rather than trusted.

    The ORM and the migration are two independent statements of one schema, and
    the model file's own docstring makes keeping them in step a rule. A column
    added to one and misspelled in the other fails at runtime, in production, on
    the persistence step of a ~$50 run.
    """
    from nestor_pulse_sdk.db.models import Source

    code = _executable_source(_load_migration())
    added = re.findall(r"sa\.Column\(['\"]([a-z_]+)['\"]", code)
    dropped = re.findall(r"op\.drop_column\(['\"]source['\"],\s*['\"]([a-z_]+)", code)

    assert sorted(added) == sorted(_NEW_COLUMNS), added
    assert sorted(dropped) == sorted(_NEW_COLUMNS), dropped
    for name in added:
        assert name in Source.__table__.c
    # TEXT in the DDL, Text in the ORM, nullable in both.
    assert code.count("sa.Text()") == 2
    assert code.count("nullable=True") == 2


# --------------------------------------------------------------------------
# 4. Source dedupe is byte-identical after 0016
# --------------------------------------------------------------------------

def test_neither_new_column_participates_in_content_hash() -> None:
    """Neither column definition says anything about `content_hash`."""
    code = _executable_source(_load_migration())

    assert "content_hash" not in code


def test_the_upsert_hash_input_is_still_the_snapshot_alone() -> None:
    """`_upsert_source` hashes `snapshot_capped` and nothing else.

    This is what makes an additive column UNABLE to change source dedupe -- the
    same rule `title` already lives under, stated in that function's docstring.

    Deliberately scoped to the STATEMENT that computes the hash, not to the
    whole function: plan 15.4-09 WILL add both column names to this function's
    INSERT statements, and a test forbidding them anywhere in the function would
    go red on correct work. What must never change is the hash INPUT.
    """
    from nestor_pulse_sdk.citations import extractor

    source = inspect.getsource(extractor._upsert_source)
    hash_lines = [
        line.strip()
        for line in source.splitlines()
        if "_content_hash(" in line and not line.strip().startswith("#")
    ]

    assert hash_lines == [
        "chash = _content_hash(snapshot_capped) if snapshot_capped else None"
    ], hash_lines
    for name in _NEW_COLUMNS:
        assert name not in hash_lines[0]
    # And the snapshot being hashed is still built from `snapshot_text` alone.
    assert 'snapshot_capped = (snapshot_text or "")[:_SNAPSHOT_MAX_CHARS]' in source


def test_the_upsert_still_dedupes_on_the_partial_unique_index() -> None:
    """The ON CONFLICT target is untouched by this plan.

    Quotes are flattened before matching because the SQL is assembled from
    adjacent string literals, so the clause is not contiguous in the raw source.
    """
    from nestor_pulse_sdk.citations import extractor

    raw = inspect.getsource(extractor._upsert_source)
    flat = " ".join(raw.replace('"', " ").replace("'", " ").split())

    assert (
        "ON CONFLICT (tenant_id, content_hash) WHERE content_hash IS NOT NULL "
        "DO NOTHING" in flat
    )


# --------------------------------------------------------------------------
# 5. The migration is importable and declares both directions
# --------------------------------------------------------------------------

def test_the_migration_defines_both_directions_and_takes_no_arguments() -> None:
    """upgrade() and downgrade() exist, are callable, and take nothing.

    CALLING them needs a live alembic migration context, which this gate
    deliberately does not have. The behavioural proof is the deploy-time
    `Running upgrade 0015 -> 0016` line owned by plan 15.4-11; until that line
    prints, this revision is WRITTEN, not APPLIED.
    """
    module = _load_migration()

    assert callable(module.upgrade)
    assert callable(module.downgrade)
    assert len(inspect.signature(module.upgrade).parameters) == 0
    assert len(inspect.signature(module.downgrade).parameters) == 0
