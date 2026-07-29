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
import uuid
from pathlib import Path
from types import ModuleType, SimpleNamespace


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
