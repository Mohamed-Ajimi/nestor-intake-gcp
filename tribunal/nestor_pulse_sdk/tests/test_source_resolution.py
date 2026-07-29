"""The 0016 contract, and the resolver that fills the two columns it adds.

WHY THIS FILE EXISTS
--------------------
Gemini grounding citations arrive as `vertexaisearch.cloud.google.com` redirect
URLs that EXPIRE roughly 30 days after the run. D-V01-11 stores the publisher
URL those redirects resolve to ALONGSIDE the redirect itself, which needs two
new columns on `source` and tribunal alembic revision 0016. Sections 1-5 pin the
shape of that revision (plan 15.4-02).

Sections 6-8 are plan 15.4-09: the resolver that FILLS those columns
(`citations/redirect_resolver.py`), its wiring into the source upsert, and — the
assertion that matters most — the proof that resolution happens BEFORE the
persistence session is opened, never inside the transaction. Every one of them
is driven through hand-written duck-typed fakes: no network, no `respx`, no
mocking library, no new dependency.

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
import asyncio
import importlib.util
import inspect
import logging
import re
import textwrap
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


# ==========================================================================
# 6. PLAN 15.4-09 — the resolver
# ==========================================================================
# Everything below drives `citations/redirect_resolver.py` through a
# hand-written duck-typed async client. `_client_factory` is a module-level
# name in the resolver for exactly this reason, so nothing here patches httpx
# itself and no request ever leaves the process.

_RESOLVE_KNOBS = (
    "NESTOR_REDIRECT_RESOLVE_ENABLED",
    "NESTOR_REDIRECT_RESOLVE_CONCURRENCY",
    "NESTOR_REDIRECT_RESOLVE_TIMEOUT_S",
    "NESTOR_REDIRECT_RESOLVE_DEADLINE_S",
)


def _clear_knobs(monkeypatch) -> None:
    """Run against the DEFAULTS unless a test says otherwise.

    An operator knob left set in the build environment would otherwise silently
    change what these tests mean -- a `..._ENABLED=0` in CI would turn every
    resolution assertion below into a vacuous pass.
    """
    for name in _RESOLVE_KNOBS:
        monkeypatch.delenv(name, raising=False)


def _redirect(suffix: str) -> str:
    """A grounding redirect URL built from the ONE host constant.

    Built from `VERTEX_REDIRECT_HOST` rather than from a literal, so a change to
    that constant makes these tests describe the new host instead of quietly
    testing a host the resolver no longer recognises.
    """
    from nestor_pulse_sdk.pipeline.tribunal.facts import VERTEX_REDIRECT_HOST

    return f"https://{VERTEX_REDIRECT_HOST}/grounding-api-redirect/{suffix}"


class _FakeResponse:
    """Enough of an `httpx.Response` for `_location_of`."""

    def __init__(self, status_code: int = 302, location: str | None = None) -> None:
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        if location is not None:
            self.headers["location"] = location


class _FakeClient:
    """Duck-typed `httpx.AsyncClient`: `async with` + `await .head(url)`.

    `requests` is the assertion surface for the dedupe and kill-switch tests —
    what matters is how many requests were ISSUED, not how many keys came back.
    """

    def __init__(self, script: dict | None = None, *, default=None) -> None:
        self.script = script or {}
        self.default = default
        self.requests: list[str] = []
        self.timeouts: list[float] = []
        self.entered = 0
        self.closed = 0

    async def __aenter__(self) -> "_FakeClient":
        self.entered += 1
        return self

    async def __aexit__(self, *_exc) -> bool:
        self.closed += 1
        return False

    async def head(self, url: str):
        self.requests.append(url)
        outcome = self.script.get(url, self.default)
        if callable(outcome):
            outcome = outcome()
        if isinstance(outcome, tuple):  # (delay_seconds, response)
            delay, outcome = outcome
            await asyncio.sleep(delay)
        if isinstance(outcome, BaseException):
            raise outcome
        if outcome is None:
            return _FakeResponse(status_code=200)
        return outcome


def _install_client(monkeypatch, client: _FakeClient) -> _FakeClient:
    from nestor_pulse_sdk.citations import redirect_resolver

    def _factory(timeout_s: float) -> _FakeClient:
        client.timeouts.append(timeout_s)
        return client

    monkeypatch.setattr(redirect_resolver, "_client_factory", _factory)
    return client


# --------------------------------------------------------------------------
# 6a. The 642 -> 225 dedupe, counted in REQUESTS
# --------------------------------------------------------------------------

async def test_642_instances_of_225_unique_redirects_issue_exactly_225_requests(
    monkeypatch,
) -> None:
    """THE D-V01-11 assertion, and it counts requests, not map size.

    Run 7dcf51d5 cited 642 URL instances that collapse to 225 unique redirects.
    The per-claim dedupe already inside `persist_tribunal_claims` does NOT
    achieve this -- the same redirect is cited by many different claims, so a
    per-claim dedupe still issues one request per instance. Asserting on
    `len(result)` instead of `len(client.requests)` would pass on exactly that
    broken implementation, because the returned map is keyed by unique URL
    either way.
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    unique = [_redirect(f"u{i}") for i in range(225)]
    instances = [unique[i % 225] for i in range(642)]
    assert len(instances) == 642 and len(set(instances)) == 225

    client = _install_client(
        monkeypatch,
        _FakeClient(
            {url: _FakeResponse(302, f"https://publisher{i}.example/a")
             for i, url in enumerate(unique)}
        ),
    )

    result = await resolve_redirects(instances)

    assert len(client.requests) == 225, len(client.requests)
    assert sorted(client.requests) == sorted(unique)
    assert len(result) == 225
    assert result[unique[7]] == "https://publisher7.example/a"


# --------------------------------------------------------------------------
# 6b. Only the redirect host is ever requested
# --------------------------------------------------------------------------

async def test_a_non_redirect_host_url_is_never_requested_and_maps_to_none(
    monkeypatch,
) -> None:
    """An ordinary publisher URL is already the publisher URL.

    Requesting it would be a needless HEAD against a third party for every
    citation of every run, and its `None` here is what the extractor reads as
    "never attempted" (NULL), not as "attempted and failed".
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    plain = "https://publisher.example/article"
    redirect = _redirect("a")
    client = _install_client(
        monkeypatch,
        _FakeClient({redirect: _FakeResponse(302, "https://publisher.example/real")}),
    )

    result = await resolve_redirects([plain, redirect])

    assert client.requests == [redirect]
    assert result[plain] is None
    assert result[redirect] == "https://publisher.example/real"


async def test_a_lookalike_host_is_not_the_redirect_host(monkeypatch) -> None:
    """`vertexaisearch.cloud.google.com.evil.example` is not our host.

    Substring matching on the host is the obvious wrong implementation, and it
    would hand an attacker-controlled domain the right to set `resolved_url`.
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import (
        is_redirect_url,
        resolve_redirects,
    )
    from nestor_pulse_sdk.pipeline.tribunal.facts import VERTEX_REDIRECT_HOST

    lookalike = f"https://{VERTEX_REDIRECT_HOST}.evil.example/grounding-api-redirect/a"
    prefixed = f"https://not{VERTEX_REDIRECT_HOST}/grounding-api-redirect/a"

    assert is_redirect_url(lookalike) is False
    assert is_redirect_url(prefixed) is False
    assert is_redirect_url(_redirect("a")) is True

    client = _install_client(monkeypatch, _FakeClient())
    result = await resolve_redirects([lookalike, prefixed])

    assert client.requests == []
    assert result == {lookalike: None, prefixed: None}


# --------------------------------------------------------------------------
# 6c. The `Location` header is untrusted (T-15.4-21)
# --------------------------------------------------------------------------

async def test_a_javascript_location_maps_to_none_and_never_reaches_the_map(
    monkeypatch,
) -> None:
    """T-15.4-21. `resolved_url` is rendered as a CLICKABLE LINK for a superadmin.

    The remote host chooses this header. A `javascript:` target stored here is a
    stored-XSS / elevation-of-privilege path into the operator's own tool, so it
    maps to None -- and the second assertion is the one that would catch an
    implementation that stored it under a different key or a mangled form.
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    hostile = _redirect("js")
    _install_client(
        monkeypatch,
        _FakeClient({hostile: _FakeResponse(302, "javascript:alert(1)")}),
    )

    result = await resolve_redirects([hostile])

    assert result[hostile] is None
    assert all("javascript:" not in (value or "") for value in result.values())


async def test_a_data_uri_location_maps_to_none(monkeypatch) -> None:
    """Same control, second scheme. `data:` renders too."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    hostile = _redirect("data")
    _install_client(
        monkeypatch,
        _FakeClient(
            {hostile: _FakeResponse(302, "data:text/html,<script>alert(1)</script>")}
        ),
    )

    result = await resolve_redirects([hostile])

    assert result[hostile] is None
    assert all("data:" not in (value or "") for value in result.values())


async def test_a_relative_location_maps_to_none(monkeypatch) -> None:
    """The documented choice of the two the plan allows.

    A relative Location resolves against the REDIRECT host, so joining it would
    store another `vertexaisearch...` URL -- the very thing that expires and the
    very thing this feature exists to escape. Storing nothing is more honest
    than storing a second copy of the problem.
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("rel")
    _install_client(
        monkeypatch, _FakeClient({url: _FakeResponse(302, "/some/relative/path")})
    )

    result = await resolve_redirects([url])

    assert result[url] is None


async def test_a_protocol_relative_location_maps_to_none(monkeypatch) -> None:
    """`//evil.example/x` has a host but NO scheme -- rejected on the scheme rule."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("protorel")
    _install_client(
        monkeypatch, _FakeClient({url: _FakeResponse(302, "//evil.example/x")})
    )

    assert (await resolve_redirects([url]))[url] is None


async def test_an_over_long_location_maps_to_none(monkeypatch) -> None:
    """2048 chars, the same cap `facts.py` applies to a SOURCE_URL cell."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    long_url = "https://publisher.example/" + ("a" * 2100)
    at_cap = "https://publisher.example/" + ("a" * (2048 - len("https://publisher.example/")))
    too_long, ok = _redirect("long"), _redirect("cap")
    _install_client(
        monkeypatch,
        _FakeClient({
            too_long: _FakeResponse(302, long_url),
            ok: _FakeResponse(302, at_cap),
        }),
    )

    result = await resolve_redirects([too_long, ok])

    assert result[too_long] is None
    assert result[ok] == at_cap and len(at_cap) == 2048


# --------------------------------------------------------------------------
# 6d. Every degradation maps to None, and nothing raises
# --------------------------------------------------------------------------

async def test_a_timeout_maps_to_none_without_raising(monkeypatch) -> None:
    _clear_knobs(monkeypatch)
    import httpx

    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("timeout")
    _install_client(
        monkeypatch, _FakeClient({url: httpx.ReadTimeout("simulated read timeout")})
    )

    assert (await resolve_redirects([url]))[url] is None


async def test_a_connection_error_maps_to_none_without_raising(monkeypatch) -> None:
    _clear_knobs(monkeypatch)
    import httpx

    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("connerr")
    _install_client(
        monkeypatch, _FakeClient({url: httpx.ConnectError("simulated connect error")})
    )

    assert (await resolve_redirects([url]))[url] is None


async def test_a_200_without_a_location_maps_to_none(monkeypatch) -> None:
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("ok200")
    _install_client(monkeypatch, _FakeClient({url: _FakeResponse(200, None)}))

    assert (await resolve_redirects([url]))[url] is None


async def test_a_500_maps_to_none(monkeypatch) -> None:
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("err500")
    _install_client(monkeypatch, _FakeClient({url: _FakeResponse(500, None)}))

    assert (await resolve_redirects([url]))[url] is None


async def test_a_200_that_carries_a_location_is_still_not_a_redirect(
    monkeypatch,
) -> None:
    """Status is read, not just the header. A 200 has no business redirecting."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    url = _redirect("odd200")
    _install_client(
        monkeypatch,
        _FakeClient({url: _FakeResponse(200, "https://publisher.example/sneaky")}),
    )

    assert (await resolve_redirects([url]))[url] is None


async def test_only_the_first_hop_is_read(monkeypatch) -> None:
    """T-15.4-23. ONE request per URL, whatever the Location points at.

    The client is built with `follow_redirects=False` and the target of the
    first hop is never itself requested, so a redirect LOOP costs exactly one
    request rather than a chain the remote host controls the length of.
    """
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    first, second = _redirect("hop1"), _redirect("hop2")
    client = _install_client(
        monkeypatch,
        _FakeClient({
            first: _FakeResponse(302, second),
            second: _FakeResponse(302, "https://publisher.example/final"),
        }),
    )

    result = await resolve_redirects([first])

    assert client.requests == [first]
    assert result[first] == second
    assert second not in result


async def test_garbage_input_never_raises(monkeypatch) -> None:
    """Any input at all. A malformed claim dict must not fail a paid run."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    client = _install_client(monkeypatch, _FakeClient())

    result = await resolve_redirects(
        [None, 123, "", "   ", "not a url at all", {"a": 1}, ["x"], "ftp://x.example/f"]
    )

    assert isinstance(result, dict)
    assert client.requests == []
    assert all(value is None for value in result.values())
    assert await resolve_redirects([]) == {}
    assert await resolve_redirects(None) == {}


async def test_a_client_that_cannot_even_be_constructed_degrades_to_all_none(
    monkeypatch,
) -> None:
    """The wholesale-failure arm: no httpx, no sockets, no DNS -- still no raise."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations import redirect_resolver

    def _explode(_timeout):
        raise RuntimeError("simulated: the http client could not be created")

    monkeypatch.setattr(redirect_resolver, "_client_factory", _explode)

    url = _redirect("noclient")
    result = await redirect_resolver.resolve_redirects([url])

    assert result == {url: None}


# --------------------------------------------------------------------------
# 6e. The bounds
# --------------------------------------------------------------------------

async def test_the_kill_switch_issues_zero_requests(monkeypatch) -> None:
    """`NESTOR_REDIRECT_RESOLVE_ENABLED=0` turns the whole pass off.

    ZERO requests -- not "requests that are ignored". This is the knob an
    operator reaches for when the redirect host is misbehaving mid-incident, and
    it must cost nothing. Every URL still comes back as a key, so the caller
    still upserts every citation.
    """
    _clear_knobs(monkeypatch)
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_ENABLED", "0")
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    urls = [_redirect("a"), _redirect("b")]
    client = _install_client(
        monkeypatch,
        _FakeClient(default=_FakeResponse(302, "https://publisher.example/x")),
    )

    result = await resolve_redirects(urls)

    assert client.requests == []
    assert client.entered == 0
    assert result == {urls[0]: None, urls[1]: None}


async def test_the_deadline_leaves_the_rest_none_and_warns_once(
    monkeypatch, caplog
) -> None:
    """An unbounded pre-pass is an unbounded stall on a ~$50 run.

    The fast URL resolves, the slow one is abandoned when the overall deadline
    fires -- and the loss is announced at WARNING, which is the lowest level
    production actually serves (D-V01-6). A silent partial resolution would look
    exactly like a run where those redirects simply did not resolve.
    """
    _clear_knobs(monkeypatch)
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_DEADLINE_S", "0.1")
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    fast, slow = _redirect("fast"), _redirect("slow")
    _install_client(
        monkeypatch,
        _FakeClient({
            fast: _FakeResponse(302, "https://publisher.example/fast"),
            slow: (30.0, _FakeResponse(302, "https://publisher.example/slow")),
        }),
    )

    with caplog.at_level(
        logging.WARNING, logger="nestor_pulse_sdk.citations.redirect_resolver"
    ):
        result = await resolve_redirects([fast, slow])

    assert result[fast] == "https://publisher.example/fast"
    assert result[slow] is None
    deadline_warnings = [
        record for record in caplog.records if "deadline" in record.getMessage()
    ]
    assert len(deadline_warnings) == 1, [r.getMessage() for r in caplog.records]


async def test_an_unresolved_redirect_is_a_named_loss_at_warning(
    monkeypatch, caplog
) -> None:
    """A citation that did not resolve is announced, never silently dropped."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    good, bad = _redirect("good"), _redirect("bad")
    _install_client(
        monkeypatch,
        _FakeClient({
            good: _FakeResponse(302, "https://publisher.example/good"),
            bad: _FakeResponse(404, None),
        }),
    )

    with caplog.at_level(
        logging.WARNING, logger="nestor_pulse_sdk.citations.redirect_resolver"
    ):
        result = await resolve_redirects([good, bad])

    assert result[bad] is None
    assert any("did not resolve" in record.getMessage() for record in caplog.records)


async def test_a_clean_pass_logs_no_warning_at_all(monkeypatch, caplog) -> None:
    """The control for the two tests above -- 225/225 resolved cries no wolf."""
    _clear_knobs(monkeypatch)
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    urls = [_redirect(f"c{i}") for i in range(5)]
    _install_client(
        monkeypatch,
        _FakeClient({
            url: _FakeResponse(302, f"https://publisher.example/{i}")
            for i, url in enumerate(urls)
        }),
    )

    with caplog.at_level(
        logging.WARNING, logger="nestor_pulse_sdk.citations.redirect_resolver"
    ):
        result = await resolve_redirects(urls)

    assert all(value is not None for value in result.values())
    assert [r for r in caplog.records if r.levelno >= logging.WARNING] == []


async def test_the_per_request_timeout_reaches_the_client(monkeypatch) -> None:
    """The knob is not decoration: the value is what the client is built with."""
    _clear_knobs(monkeypatch)
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_TIMEOUT_S", "1.5")
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    client = _install_client(
        monkeypatch,
        _FakeClient(default=_FakeResponse(302, "https://publisher.example/x")),
    )

    await resolve_redirects([_redirect("t")])

    assert client.timeouts == [1.5]


async def test_the_concurrency_cap_is_never_exceeded(monkeypatch) -> None:
    """A cap that is read but not applied is the easiest bound to get wrong."""
    _clear_knobs(monkeypatch)
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_CONCURRENCY", "3")
    from nestor_pulse_sdk.citations.redirect_resolver import resolve_redirects

    state = {"now": 0, "peak": 0}

    class _CountingClient(_FakeClient):
        async def head(self, url: str):
            self.requests.append(url)
            state["now"] += 1
            state["peak"] = max(state["peak"], state["now"])
            await asyncio.sleep(0)
            state["now"] -= 1
            return _FakeResponse(302, "https://publisher.example/x")

    client = _install_client(monkeypatch, _CountingClient())

    await resolve_redirects([_redirect(f"n{i}") for i in range(20)])

    assert len(client.requests) == 20
    assert state["peak"] <= 3, state["peak"]


async def test_a_garbled_knob_falls_back_to_the_default_instead_of_raising(
    monkeypatch,
) -> None:
    """A mistyped env var must not be able to fail a run."""
    _clear_knobs(monkeypatch)
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_CONCURRENCY", "eight")
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_TIMEOUT_S", "soon")
    monkeypatch.setenv("NESTOR_REDIRECT_RESOLVE_DEADLINE_S", "")
    from nestor_pulse_sdk.citations import redirect_resolver

    client = _install_client(
        monkeypatch,
        _FakeClient(default=_FakeResponse(302, "https://publisher.example/x")),
    )

    url = _redirect("garbled")
    result = await redirect_resolver.resolve_redirects([url])

    assert result[url] == "https://publisher.example/x"
    assert client.timeouts == [redirect_resolver._DEFAULT_TIMEOUT_S]


# --------------------------------------------------------------------------
# 6f. The module has NO database seam -- the structural half of the placement
# --------------------------------------------------------------------------

def test_the_resolver_module_has_no_database_seam_of_any_kind() -> None:
    """This is what makes the out-of-transaction placement STRUCTURAL.

    The ordering test in section 8 proves resolution happens before
    `session.begin()` TODAY. This proves it cannot quietly stop being true: a
    module that cannot name a session, a sqlalchemy symbol or a sessionmaker
    cannot be moved inside a transaction without that move being visible in the
    diff of a file whose whole purpose is to have no database in it.
    """
    from nestor_pulse_sdk.citations import redirect_resolver

    source = Path(redirect_resolver.__file__).read_text(encoding="utf-8")
    code = _executable_source(redirect_resolver)

    for forbidden in ("AsyncSession", "sqlalchemy", "get_sessionmaker", "session"):
        assert forbidden not in code, forbidden
    # `import httpx` is present and no other network client is. Matched as an
    # IMPORT, not as a bare word: "0 requests issued" is a log string in this
    # module, and a bare-word scan would go red on a summary line.
    assert "import httpx" in source
    assert "import requests" not in code
    assert "aiohttp" not in code


def test_the_resolver_builds_its_client_with_follow_redirects_disabled() -> None:
    """ONE hop, asserted on the code as well as on the behaviour (T-15.4-23).

    The behavioural test above proves the SECOND hop is not requested. This
    proves the client could not follow one even if the loop changed, which is
    the difference between a bound and a habit.
    """
    from nestor_pulse_sdk.citations import redirect_resolver

    code = _executable_source(redirect_resolver)

    assert "follow_redirects=False" in code
    assert "follow_redirects=True" not in code
    # And the request verb is HEAD -- never a GET that would pull the body of a
    # page we have no intention of reading.
    assert "client.head(" in code
    assert "client.get(" not in code


# ==========================================================================
# 7. PLAN 15.4-09 — the map reaches the source upsert
# ==========================================================================
# `persist_tribunal_claims` is driven through a hand-written session that
# records every `(sql, params)` pair -- the same shape test_verdict_write_path.py
# uses, and for the same reason: this function SWALLOWS nothing but its caller
# does, so "it did not raise" proves nothing. The recorded parameters are the
# only honest evidence that a row was written and what was in it.

_TENANT_ID = uuid.UUID("11111111-1111-1111-1111-111111111111")
_RUN_ID = uuid.UUID("22222222-2222-2222-2222-222222222222")

_SOURCE_INSERT = "INSERT INTO source"


class _FakeResult:
    """Enough of a Result for `_upsert_source`'s RETURNING path."""

    def __init__(self) -> None:
        self._row = SimpleNamespace(id=uuid.uuid4())

    def first(self):
        return self._row


class _FakeSession:
    """Records `(sql, params)` per execute. No begin/commit: the CALLER owns
    the transaction, which is the whole subject of section 8."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _FakeResult()


def _source_params(session: _FakeSession) -> list[dict]:
    """The bound parameters of every `INSERT INTO source` in call order."""
    return [p for sql, p in session.calls if _SOURCE_INSERT in sql]


async def test_a_resolved_redirect_is_stored_beside_the_redirect_not_instead_of_it(
    monkeypatch,
) -> None:
    """Both columns written, and `url` still holds the REDIRECT.

    Overwriting `url` with the publisher URL would be the obvious "tidier"
    implementation and it would destroy the citation as the provider stated it,
    which is the thing the audit trail is.
    """
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    redirect = _redirect("stored")
    claim = {"text": "A fact worth a citation.", "facet": "market",
             "source_urls": [redirect]}
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
        resolved_urls={redirect: "https://publisher.example/article"},
    )

    rows = _source_params(session)
    assert len(rows) == 1
    assert rows[0]["url"] == redirect
    assert rows[0]["resolved_url"] == "https://publisher.example/article"
    assert rows[0]["resolution_status"] == "resolved"


async def test_a_redirect_that_failed_to_resolve_is_still_written_as_unresolved(
    monkeypatch,
) -> None:
    """D-V01-11 verbatim: keep the redirect and mark it unresolved, NEVER drop it.

    The row exists, `resolved_url` is NULL and the status is `'unresolved'` --
    which is a DIFFERENT fact from NULL. NULL would say nobody ever looked;
    `'unresolved'` says we looked and this citation's publisher URL will be gone
    when the redirect expires. Collapsing the two makes that loss unfindable.
    """
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    redirect = _redirect("failed")
    claim = {"text": "A fact whose redirect would not resolve.", "facet": "market",
             "source_urls": [redirect]}
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
        resolved_urls={redirect: None},
    )

    rows = _source_params(session)
    assert len(rows) == 1, "the citation was DROPPED — this is the one thing forbidden"
    assert rows[0]["url"] == redirect
    assert rows[0]["resolved_url"] is None
    assert rows[0]["resolution_status"] == "unresolved"


async def test_an_ordinary_publisher_url_gets_null_not_unresolved() -> None:
    """Never attempted is not the same fact as attempted and failed.

    An ordinary publisher URL is already the publisher URL. Marking it
    `'unresolved'` would fill the column with hundreds of fake losses and drown
    the real ones.
    """
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    plain = "https://publisher.example/article"
    claim = {"text": "A fact with a direct citation.", "facet": "market",
             "source_urls": [plain]}
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
        resolved_urls={plain: None},
    )

    rows = _source_params(session)
    assert len(rows) == 1
    assert rows[0]["resolved_url"] is None
    assert rows[0]["resolution_status"] is None


async def test_calling_with_no_resolved_urls_argument_writes_both_columns_null() -> None:
    """BACK COMPAT. The five existing call sites pass no such argument.

    The parameter defaults to None and None means "never attempted", so every
    row those callers write is byte-identical to what they wrote before this
    plan -- both new columns NULL.
    """
    from nestor_pulse_sdk.citations.extractor import persist_tribunal_claims

    claim = {
        "text": "A fact from a caller that predates redirect resolution.",
        "facet": "market",
        "source_urls": [_redirect("legacy"), "https://publisher.example/x"],
    }
    session = _FakeSession()

    await persist_tribunal_claims(
        claims=[claim],
        verdicts_by_claim={},
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
        session=session,
    )

    rows = _source_params(session)
    assert len(rows) == 2
    for row in rows:
        assert row["resolved_url"] is None
        assert row["resolution_status"] is None


async def test_an_existing_unmodified_call_site_still_writes_both_columns_null() -> None:
    """The same proof, through a call site this plan did not touch.

    `test_verdict_write_path.py::_run` is a pre-existing fixture that calls
    `persist_tribunal_claims` in its original shape. Driving IT is a stronger
    back-compat statement than writing a fresh call that merely omits the new
    argument, because that file was written before the argument existed and
    would be red here if the default had been got wrong.
    """
    from nestor_pulse_sdk.tests import test_verdict_write_path

    session, _result = await test_verdict_write_path._run()

    rows = [p for sql, p in session.calls if _SOURCE_INSERT in sql]
    assert rows, "the pre-existing fixture wrote no source row at all"
    for row in rows:
        assert row["resolved_url"] is None
        assert row["resolution_status"] is None


async def test_a_garbled_status_is_clamped_to_null_rather_than_written() -> None:
    """The `claim.certainty` idiom. A bug must not write a fourth vocabulary word.

    `resolution_status` is deliberately not a CHECK constraint or an enum in the
    DDL -- a resolver bug must not be able to fail an INSERT inside a paid run --
    so the clamp is here, in Python, and it stores NULL plus a log line.
    """
    from nestor_pulse_sdk.citations import extractor

    session = _FakeSession()
    await extractor._upsert_source(
        session,
        tenant_id=_TENANT_ID,
        url="https://publisher.example/x",
        provider="tribunal_skeptic",
        snapshot_text="https://publisher.example/x",
        resolved_url="https://publisher.example/x",
        resolution_status="MAYBE",
    )

    rows = _source_params(session)
    assert rows[0]["resolution_status"] is None
    # 'resolved' and 'unresolved' survive the clamp, case-insensitively.
    for word in ("resolved", "UNRESOLVED"):
        session = _FakeSession()
        await extractor._upsert_source(
            session,
            tenant_id=_TENANT_ID,
            url="https://publisher.example/x",
            provider="tribunal_skeptic",
            snapshot_text="https://publisher.example/x",
            resolution_status=word,
        )
        assert _source_params(session)[0]["resolution_status"] == word.lower()


async def test_an_over_long_resolved_url_is_truncated_at_the_writer() -> None:
    """The bound is applied AGAIN here, on the D-13 rule.

    The resolver already rejects a Location over 2048 chars. A bound that exists
    only in the parser is one refactor away from being gone, and this function is
    the last thing between a remote host's header and a persisted column.
    """
    from nestor_pulse_sdk.citations import extractor

    session = _FakeSession()
    await extractor._upsert_source(
        session,
        tenant_id=_TENANT_ID,
        url="https://publisher.example/x",
        provider="tribunal_skeptic",
        snapshot_text="https://publisher.example/x",
        resolved_url="https://publisher.example/" + ("a" * 4000),
        resolution_status="resolved",
    )

    assert len(_source_params(session)[0]["resolved_url"]) == 2048


def test_neither_new_column_reaches_the_content_hash_computation() -> None:
    """T-15.4-24, restated after the columns were actually threaded through.

    Section 4 asserted this before `_upsert_source` named the columns at all.
    Now that it does, the statement worth making is that the hash INPUT is still
    the snapshot alone -- so `ON CONFLICT` still fires on exactly the same rows
    and an existing row keeps whatever it had.
    """
    from nestor_pulse_sdk.citations import extractor

    source = inspect.getsource(extractor._upsert_source)
    hash_line = [
        line.strip()
        for line in source.splitlines()
        if "_content_hash(" in line and not line.strip().startswith("#")
    ]

    assert hash_line == [
        "chash = _content_hash(snapshot_capped) if snapshot_capped else None"
    ]
    assert "resolved_url" in source  # the columns ARE written...
    for name in _NEW_COLUMNS:  # ...and neither is part of the hash INPUT
        assert name not in hash_line[0]


# --------------------------------------------------------------------------
# 7b. ONE extraction, two callers
# --------------------------------------------------------------------------

def test_the_pre_pass_and_the_loop_see_exactly_the_same_url_set() -> None:
    """`_gather_source_urls` called over the run == the union of the per-claim calls.

    If the two views could drift, the pre-pass would resolve a set of URLs that
    is not the set the loop upserts, and the difference would surface as
    citations silently missing a publisher URL for no stated reason. Calling ONE
    function from both places makes drift impossible; this asserts it.
    """
    from nestor_pulse_sdk.citations.extractor import _gather_source_urls

    shared = _redirect("shared")
    claim_a = {"text": "A", "source_urls": [shared, "https://a.example/1"]}
    claim_b = {"text": "B", "evidence_refs": [shared], "source_urls": ["https://b.example/2"]}
    verdict_a = {"verdict": "support", "evidence_refs": ["https://skeptic.example/3"],
                 "citations": [{"url": "https://skeptic.example/4"}]}
    verdict_b = {"verdict": "support", "citations": ["https://skeptic.example/5"]}
    verdicts = {id(claim_a): [verdict_a], id(claim_b): verdict_b}

    claims = [claim_a, claim_b]
    pre_pass = _gather_source_urls(claims, verdicts)

    from_the_loop: list[str] = []
    for claim in claims:
        for url in _gather_source_urls([claim], verdicts):
            if url not in from_the_loop:
                from_the_loop.append(url)

    assert pre_pass == from_the_loop
    assert set(pre_pass) == {
        shared, "https://a.example/1", "https://b.example/2",
        "https://skeptic.example/3", "https://skeptic.example/4",
        "https://skeptic.example/5",
    }
    # THE 642 -> 225 shape in miniature: two claims cite one redirect, and the
    # run-wide set names it ONCE.
    assert pre_pass.count(shared) == 1


def test_gather_source_urls_never_raises_on_a_malformed_claim() -> None:
    """Model-authored shapes reach this function on the path of a paid run."""
    from nestor_pulse_sdk.citations.extractor import _gather_source_urls

    claim = {
        "text": "A claim with a hostile citation list.",
        "source_urls": ["https://ok.example/1", None, 42, ""],
        "evidence_refs": "not-a-list",
        }
    verdict = {"verdict": "support", "evidence_refs": [None, 7],
               "citations": [{"url": 99}, {"source_url": "https://ok.example/2"}, 5, None]}

    result = _gather_source_urls(
        [claim, "not-a-dict", None], {id(claim): [verdict, "not-a-dict"]}
    )

    assert result == ["https://ok.example/1", "https://ok.example/2"]
    assert _gather_source_urls([], {}) == []
    assert _gather_source_urls(None, None) == []


# ==========================================================================
# 8. PLAN 15.4-09 — THE PLACEMENT. Resolution finishes before the transaction.
# ==========================================================================
# This is the section that stops the change being silently undone. A test that
# only checked "the map arrived" would still pass if a future edit moved
# resolution back inside `async with session.begin()`, which is the edit the
# operator decision of 2026-07-29 exists to prevent.


class _OrderingSession(_FakeSession):
    """A session that RECORDS when it is opened and when `begin()` is entered."""

    def __init__(self, events: list[str]) -> None:
        super().__init__()
        self.events = events

    async def __aenter__(self) -> "_OrderingSession":
        self.events.append("session-open")
        return self

    async def __aexit__(self, *_exc) -> bool:
        self.events.append("session-close")
        return False

    def begin(self):
        events = self.events

        class _Begin:
            async def __aenter__(self_inner):
                events.append("begin")
                return None

            async def __aexit__(self_inner, *_exc):
                events.append("commit")
                return False

        return _Begin()


def _install_ordering_sessionmaker(monkeypatch, session: _OrderingSession):
    """Replace `get_sessionmaker` on the pipeline module with a fake factory.

    `pipeline.py` does `_sm = get_sessionmaker()` and then `async with _sm()`,
    so the fake returns a callable that returns the session itself.
    """
    from nestor_pulse_sdk.pipeline.tribunal import pipeline as pipeline_mod

    monkeypatch.setattr(pipeline_mod, "get_sessionmaker", lambda: (lambda: session))
    return pipeline_mod


async def test_the_last_resolver_request_completes_before_session_begin(
    monkeypatch,
) -> None:
    """THE PLACEMENT ASSERTION, stated as an ORDERING and not as an inspection.

    Up to 30 s of third-party network I/O inside the final persistence
    transaction of a ~$50 run would hold a pooled connection with RLS tenant
    context set. A pool stall or a hung socket there costs the run its claims --
    for an enrichment that is by design allowed to fail. So every request must
    be DONE before the transaction opens, and this fails the moment that stops
    being true.
    """
    _clear_knobs(monkeypatch)
    events: list[str] = []
    session = _OrderingSession(events)
    pipeline_mod = _install_ordering_sessionmaker(monkeypatch, session)

    urls = [_redirect("p1"), _redirect("p2"), _redirect("p3")]

    class _OrderingClient(_FakeClient):
        async def head(self, url: str):
            self.requests.append(url)
            # Yield, so a resolution that had been moved inside the transaction
            # would interleave with it rather than completing by luck.
            await asyncio.sleep(0)
            events.append(f"request-done:{url}")
            return _FakeResponse(302, f"https://publisher.example/{len(self.requests)}")

    client = _install_client(monkeypatch, _OrderingClient())

    survivors = [{"text": f"Claim {i}", "facet": "market", "source_urls": [url]}
                 for i, url in enumerate(urls)]

    await pipeline_mod._resolve_then_persist_claims(
        survivors=survivors,
        dropped=[],
        verdicts_by_claim={},
        research_gaps=None,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
    )

    assert len(client.requests) == 3, client.requests
    assert "begin" in events, f"the transaction was never opened: {events}"
    request_indexes = [
        i for i, event in enumerate(events) if event.startswith("request-done:")
    ]
    assert len(request_indexes) == 3, events
    assert max(request_indexes) < events.index("session-open"), events
    assert max(request_indexes) < events.index("begin"), events


async def test_resolution_failure_does_not_stop_the_claims_being_persisted(
    monkeypatch,
) -> None:
    """The enrichment is allowed to fail. The claims are not.

    A resolver that blew up entirely must degrade to an empty map and leave
    persistence untouched -- a citation without its publisher URL is still a
    citation, and a ~$50 run must not lose its claims to a redirect service.
    """
    _clear_knobs(monkeypatch)
    session = _OrderingSession([])
    pipeline_mod = _install_ordering_sessionmaker(monkeypatch, session)

    async def _boom(_urls):
        raise RuntimeError("simulated: the resolver itself failed")

    monkeypatch.setattr(
        "nestor_pulse_sdk.citations.redirect_resolver.resolve_redirects", _boom
    )

    redirect = _redirect("boom")
    await pipeline_mod._resolve_then_persist_claims(
        survivors=[{"text": "A claim that must survive.", "facet": "market",
                    "source_urls": [redirect]}],
        dropped=[],
        verdicts_by_claim={},
        research_gaps=None,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
    )

    rows = _source_params(session)
    assert len(rows) == 1
    assert rows[0]["url"] == redirect
    assert rows[0]["resolved_url"] is None
    assert rows[0]["resolution_status"] is None  # never attempted, honestly stated
    assert [p for sql, p in session.calls if "INSERT INTO claim (" in sql]


async def test_turning_resolution_off_changes_zero_citations(monkeypatch) -> None:
    """THE NO-CITATION-LOST PROOF: an EQUAL upsert count in both modes.

    Enabling or disabling resolution must change what is KNOWN about a citation
    and nothing else. If the two counts ever differ, some code path is skipping
    the upsert when resolution fails -- the one thing D-V01-11 forbids.
    """
    from nestor_pulse_sdk.pipeline.tribunal import pipeline as pipeline_mod

    urls = [_redirect("e1"), _redirect("e2"), "https://publisher.example/plain"]

    async def _run(enabled: bool) -> list[dict]:
        with pytest.MonkeyPatch.context() as patch:
            for name in _RESOLVE_KNOBS:
                patch.delenv(name, raising=False)
            if not enabled:
                patch.setenv("NESTOR_REDIRECT_RESOLVE_ENABLED", "0")

            from nestor_pulse_sdk.citations import redirect_resolver

            client = _FakeClient(default=_FakeResponse(302, "https://publisher.example/r"))
            patch.setattr(redirect_resolver, "_client_factory", lambda _t: client)

            session = _OrderingSession([])
            patch.setattr(
                pipeline_mod, "get_sessionmaker", lambda: (lambda: session)
            )
            await pipeline_mod._resolve_then_persist_claims(
                survivors=[{"text": f"Claim {i}", "facet": "market", "source_urls": [url]}
                           for i, url in enumerate(urls)],
                dropped=[],
                verdicts_by_claim={},
                research_gaps=None,
                run_id=_RUN_ID,
                tenant_id=_TENANT_ID,
            )
            return _source_params(session)

    on = await _run(enabled=True)
    off = await _run(enabled=False)

    assert len(on) == len(off) == 3
    assert [row["url"] for row in on] == [row["url"] for row in off] == urls
    # What DOES differ is only what is known about them.
    assert [row["resolution_status"] for row in on] == ["resolved", "resolved", None]
    assert [row["resolution_status"] for row in off] == [None, None, None]


async def test_two_claims_citing_one_redirect_cost_exactly_one_request(
    monkeypatch,
) -> None:
    """The run-wide dedupe, proven end to end through Stage 7.

    The per-claim dedupe that has always been in the persistence loop does NOT
    achieve this: the same redirect cited by two claims would be two requests.
    Both claims still get their own `claim_source` link, and both source upserts
    name the same URL -- so Postgres` ON CONFLICT dedupes them to ONE row (that
    last step needs a real database and is proven in test_citation_roundtrip.py).
    """
    _clear_knobs(monkeypatch)
    session = _OrderingSession([])
    pipeline_mod = _install_ordering_sessionmaker(monkeypatch, session)

    shared = _redirect("shared-by-two")
    client = _install_client(
        monkeypatch,
        _FakeClient({shared: _FakeResponse(302, "https://publisher.example/one")}),
    )

    await pipeline_mod._resolve_then_persist_claims(
        survivors=[
            {"text": "First claim.", "facet": "market", "source_urls": [shared]},
            {"text": "Second claim.", "facet": "policy", "evidence_refs": [shared]},
        ],
        dropped=[],
        verdicts_by_claim={},
        research_gaps=None,
        run_id=_RUN_ID,
        tenant_id=_TENANT_ID,
    )

    assert client.requests == [shared]
    rows = _source_params(session)
    assert len(rows) == 2
    assert {row["url"] for row in rows} == {shared}
    for row in rows:
        assert row["resolved_url"] == "https://publisher.example/one"
        assert row["resolution_status"] == "resolved"
    assert len([p for sql, p in session.calls if "INSERT INTO claim_source" in sql]) == 2


# --------------------------------------------------------------------------
# 8b. The structural half of the placement
# --------------------------------------------------------------------------

def test_the_persistence_function_cannot_reach_the_resolver_at_all() -> None:
    """`resolve_redirects` appears NOWHERE in `citations/extractor.py`.

    The ordering test above proves the placement holds today. This proves the
    persistence function has no way to resolve anything itself: the only thing
    it takes from the resolver package is `is_redirect_url`, a pure predicate
    over a string with no client and no I/O.
    """
    from nestor_pulse_sdk.citations import extractor

    source = Path(extractor.__file__).read_text(encoding="utf-8")

    assert "resolve_redirects" not in source
    assert "is_redirect_url" in source
    # And no http client is imported here either -- the resolver package's only
    # export this module takes is a pure string predicate.
    assert "import httpx" not in source


def test_no_resolver_call_sits_inside_an_async_with_block_in_the_pipeline() -> None:
    """AST proof: every `resolve_redirects` call in `pipeline.py` is OUTSIDE
    every `async with`.

    `async with _sm() as session` and `async with session.begin()` are the two
    blocks that must never contain network I/O. Rather than naming them, this
    walks EVERY `AsyncWith` in the module and asserts no resolver call is a
    descendant of any of them -- so a resolver call placed inside some future
    third `async with` is caught too.
    """
    from nestor_pulse_sdk.pipeline.tribunal import pipeline as pipeline_mod

    tree = ast.parse(Path(pipeline_mod.__file__).read_text(encoding="utf-8"))

    def _resolver_calls(node: ast.AST) -> list[ast.Call]:
        return [
            child
            for child in ast.walk(node)
            if isinstance(child, ast.Call)
            and (
                (isinstance(child.func, ast.Name) and child.func.id == "resolve_redirects")
                or (
                    isinstance(child.func, ast.Attribute)
                    and child.func.attr == "resolve_redirects"
                )
            )
        ]

    all_calls = _resolver_calls(tree)
    assert len(all_calls) == 1, f"expected exactly one resolver call, got {len(all_calls)}"

    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncWith):
            assert not _resolver_calls(node), (
                "a resolve_redirects() call sits inside an `async with` block in "
                "pipeline.py — that is network I/O inside the persistence "
                "transaction of a paid run (D-V01-11, T-15.4-22)"
            )


def test_stage_7_resolves_before_it_asks_for_a_sessionmaker() -> None:
    """Lexical order inside `_resolve_then_persist_claims`, asserted.

    Belt and braces beside the ordering test: the resolver await comes before
    the first mention of `get_sessionmaker` in the function body, so the
    placement is visible in the diff as well as in the run.
    """
    from nestor_pulse_sdk.pipeline.tribunal import pipeline as pipeline_mod

    tree = ast.parse(
        textwrap.dedent(inspect.getsource(pipeline_mod._resolve_then_persist_claims))
    )
    function = tree.body[0]
    assert isinstance(function, ast.AsyncFunctionDef)
    # Strip the docstring: it DISCUSSES `get_sessionmaker()` before the code
    # calls anything, so a raw-text scan would compare prose to code and pass or
    # fail for the wrong reason. `ast.unparse` drops comments on its own.
    if isinstance(function.body[0], ast.Expr) and isinstance(
        function.body[0].value, ast.Constant
    ):
        function.body = function.body[1:]
    code = ast.unparse(function)

    assert code.index("resolve_redirects(") < code.index("get_sessionmaker()")
    assert code.index("resolve_redirects(") < code.index("session.begin()")
