"""Suite hygiene: the tests that test the tests (Phase 15.8, plan 15.8-11).

WHY THIS FILE EXISTS
--------------------
In this repo a test-file defect is not cosmetic. A green gate is the only evidence
the engine is correct before a $45 unrepeatable run, so a defective test crosses
that boundary as FALSE ASSURANCE and every downstream number is then unearned.
Four precedents, all real, all from the last two phases:

  * THREE TEST HELPERS DEFINED TWICE in `test_workshop_critique.py`. Python keeps
    the last binding; the shadowed versions had been silently degrading fixtures
    on tests that still PASSED. Nothing went red. (Fixed in 15.7.)
  * A TEST PINNING AN EXACT ALLOWLIST over a file a sibling plan also edited
    (15.5-01's stdlib allowlist vs 15.5-02's imports). Three green verifications,
    a passed plan-check and three executors reporting success; only executing the
    MERGED tree found it. Parallel executors in isolated worktrees cannot see each
    other's assertions.
  * A TEST ASSERTING A DEAD CONSTANT. `DROP_CLUSTERED_ONTO_LIVE`'s only writer was
    `test_workshop_critique.py`, which is how a production branch stayed dead while
    looking covered.
  * THE `ast`-LIFT HARNESS, which SUPPLIES MODULE GLOBALS and therefore
    MANUFACTURES any name a module forgot to import. It hid a missing
    `DISCOVERY_PARENT` -- used at four call sites -- through nine plans,
    through `py_compile`, and through "38 lifted tests green".

COVERAGE
--------
  1. the scan walked the whole suite (the NON-VACUITY control, first on purpose)
  2. no test module binds the same name twice in one namespace
  3. no test module injects module globals into a parsed namespace (the lift ban)

All pure: no Postgres, no LLM, no network, and NO import of any
`nestor_pulse_sdk` production module. This file reads source TEXT; it never
executes the code it reads.

Cloud Build gate:
  gcloud builds submit tribunal \
    --config=tribunal/cloudbuild.test-engine.yaml \
    --project="$GOOGLE_PROJECT"
"""

from __future__ import annotations

import ast
import collections
import pathlib

# The suite's own directory. Resolved from THIS file so the scan cannot be
# pointed at an empty tree by a change of working directory -- a scan that
# reports zero findings having walked zero files is the failure mode this
# file exists to prevent.
_TESTS_DIR = pathlib.Path(__file__).resolve().parent

# Measured floor, not a guess: 91 `test_*.py` modules on disk at 15.8 wave 3.
# Set below the live count on purpose so that adding files never trips it while
# a broken glob (0, or a handful) still goes RED.
_MIN_TEST_MODULES = 80


def _test_modules() -> list[pathlib.Path]:
    return sorted(_TESTS_DIR.glob("test_*.py"))


# ---------------------------------------------------------------------------
# 1. NON-VACUITY CONTROL -- this one comes first on purpose
# ---------------------------------------------------------------------------


def test_the_scan_walked_the_whole_suite():
    """Prove the glob found the suite BEFORE any finding count is believed.

    Every other function in this file reports "no findings" by asserting an empty
    list. An empty list is also what a scan over ZERO files produces. This repo
    has been burned by a guard that read green having checked nothing, so the
    module-count floor is asserted here, separately, and a bad glob goes red HERE
    rather than passing silently one function down.
    """
    mods = _test_modules()

    assert len(mods) >= _MIN_TEST_MODULES, (
        f"only {len(mods)} test modules found under {_TESTS_DIR} -- "
        f"expected at least {_MIN_TEST_MODULES}. The glob is broken, or the "
        f"suite shrank; either way every other check in this file is now vacuous."
    )

    unparsable: list[str] = []
    for mod in mods:
        try:
            ast.parse(mod.read_text(encoding="utf-8"))
        except SyntaxError as exc:  # pragma: no cover -- a red here is a real break
            unparsable.append(f"{mod.name}:{exc.lineno}: {exc.msg}")

    assert unparsable == [], (
        "test modules that do not parse (the scans below skip what they cannot "
        f"read, so this must be empty): {unparsable}"
    )


# ---------------------------------------------------------------------------
# 2. DUPLICATE DEFINITIONS
# ---------------------------------------------------------------------------


def _decorator_names(node: ast.AST) -> set[str]:
    out: set[str] = set()
    for dec in getattr(node, "decorator_list", []) or []:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if isinstance(target, ast.Name):
            out.add(target.id)
        elif isinstance(target, ast.Attribute):
            out.add(target.attr)
    return out


def _collect_rebindings(
    body: list[ast.stmt],
    scope: str,
    module_level: bool,
    found: list[tuple[str, str, list[int]]],
) -> None:
    """Record every name bound more than once within ONE namespace.

    Namespace rules, and they are the load-bearing detail:

      * `Try` / `With` / `For` / `While` bodies (and their `else` / `finally` /
        `except` bodies) are descended as the SAME namespace, because Python
        binds names defined there into the enclosing scope. A scan that stopped
        at those statements would miss a helper defined inside a `try:` -- which
        is precisely where import-guarded helpers live.

      * Each branch of an `If` is a SIBLING namespace and is NOT compared against
        the other. Without this exemption every legitimate `if TYPE_CHECKING: /
        else:` or version-guarded definition pair false-positives, and a scan
        that cries wolf gets deleted.

      * A `FunctionDef` carrying a `typing.overload` / `overload` decorator is
        SKIPPED. Overloads are *meant* to repeat the name; that is the whole
        construct.

    Both exemptions are stated here deliberately. An unstated exemption is how a
    scan quietly stops biting.
    """
    names: dict[str, list[int]] = collections.defaultdict(list)

    def sweep(stmts: list[ast.stmt]) -> None:
        for node in stmts:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if "overload" in _decorator_names(node):
                    continue
                names[node.name].append(node.lineno)
                _collect_rebindings(node.body, f"{scope}.{node.name}", False, found)
            elif isinstance(node, ast.ClassDef):
                names[node.name].append(node.lineno)
                _collect_rebindings(node.body, f"{scope}.{node.name}", False, found)
            elif module_level and isinstance(node, ast.Assign):
                # Module-level constants only. A rebinding inside a function is
                # ordinary local reassignment and is not the defect class.
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        names[target.id].append(node.lineno)
            elif isinstance(
                node,
                (ast.Try, ast.With, ast.AsyncWith, ast.For, ast.AsyncFor, ast.While),
            ):
                sweep(node.body)
                sweep(getattr(node, "orelse", []) or [])
                sweep(getattr(node, "finalbody", []) or [])
                for handler in getattr(node, "handlers", []) or []:
                    sweep(handler.body)
            elif isinstance(node, ast.If):
                _collect_rebindings(node.body, f"{scope}<if>", module_level, found)
                _collect_rebindings(node.orelse, f"{scope}<else>", module_level, found)

    sweep(body)

    for name, lines in names.items():
        if len(lines) > 1:
            found.append((scope, name, lines))


def test_no_test_module_defines_the_same_name_twice_in_one_namespace():
    """A shadowed helper degrades a fixture while every test still PASSES.

    `test_workshop_critique.py` carried three of these into 15.7. Python keeps the
    LAST binding, so the earlier definition -- often the one a reader is looking at
    -- is dead, and the tests that relied on it went on reporting green against a
    helper they were not using. Nothing in pytest reports this. Nothing in
    `py_compile` reports this. It has to be scanned for.
    """
    duplicates: list[str] = []

    for mod in _test_modules():
        found: list[tuple[str, str, list[int]]] = []
        _collect_rebindings(
            ast.parse(mod.read_text(encoding="utf-8")).body, "<module>", True, found
        )
        for scope, name, lines in found:
            duplicates.append(
                f"{mod.name}: `{name}` bound {len(lines)}x in {scope} "
                f"at lines {lines}"
            )

    assert duplicates == [], (
        "names bound more than once in a single namespace -- Python keeps the "
        "LAST, so every earlier definition is dead code that a reader will "
        f"believe is live:\n  " + "\n  ".join(duplicates)
    )


# ---------------------------------------------------------------------------
# 3. THE `ast`-LIFT BAN
# ---------------------------------------------------------------------------

# EVERY CHECK BELOW IS AST-BASED, NOT TEXT-BASED, AND THAT IS DELIBERATE.
#
# A source-text denylist for `types.ModuleType(` / `exec(compile(` would flag
# THIS FILE, because a file that names the banned patterns necessarily contains
# them as string literals. That is the "RED ON CORRECT SOURCE" class, and its
# obvious remedy -- exempting this file by name -- would leave the one module
# that could most easily hide a lift as the only module nobody scans.
#
# The AST does not have that problem. `types.ModuleType(...)` is a `Call`;
# `"types.ModuleType("` is a `Constant`. Annotations are the same story: twelve
# sites across `test_claim_attribution.py`, `test_source_resolution.py` and
# `test_yield_schema.py` write `-> ModuleType:` as a RETURN TYPE while loading
# their migration through a real `spec.loader.exec_module`. Those are correct and
# a text scan would have to special-case every one of them.


def _module_type_construction(tree: ast.AST) -> list[tuple[int, str]]:
    """`types.ModuleType(...)` / `ModuleType(...)` CALLED -- a synthetic module.

    Only a Call counts. A bare `ModuleType` in an annotation or an import is not
    a lift; it is how the safe real-import helpers in this suite type their
    return values.
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", None)
        if name == "ModuleType":
            out.append((node.lineno, "ModuleType(...) constructed"))
    return out


def _compile_calls(tree: ast.AST) -> list[tuple[int, str]]:
    """A call to the builtin `compile` -- the other half of `exec(compile(...))`."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "compile"
        ):
            out.append((node.lineno, "compile(...) called"))
    return out


def _dict_update_injections(tree: ast.AST) -> list[tuple[int, str]]:
    """`<x>.__dict__.update(...)` where `<x>` is NOT `self` or `cls`.

    EXEMPTION, STATED: `self.__dict__.update(kw)` inside an `__init__` is ordinary
    instance-attribute assignment and is the standard way this suite builds
    duck-typed stand-ins for provider SDK objects (`test_discovery_bracket.py`'s
    `Blk`, `test_web_fetch_replay.py`'s `_SDKish`). Two such uses exist today and
    BOTH ARE CORRECT. A bare `.__dict__.update(` denylist is RED ON CORRECT
    SOURCE, and the tempting remedy for that -- deleting the check -- would retire
    the guard entirely. So the receiver is discriminated instead of the method.
    """
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        fn = node.func
        if not (isinstance(fn, ast.Attribute) and fn.attr == "update"):
            continue
        owner = fn.value
        if not (isinstance(owner, ast.Attribute) and owner.attr == "__dict__"):
            continue
        receiver = owner.value
        if isinstance(receiver, ast.Name) and receiver.id in {"self", "cls"}:
            continue
        out.append((node.lineno, ast.unparse(fn)))
    return out


def _exec_with_namespace(tree: ast.AST) -> list[tuple[int, str]]:
    """`exec(source, some_namespace)` -- exec with an explicit globals mapping."""
    out: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "exec"
            and len(node.args) >= 2
        ):
            out.append((node.lineno, "exec(<source>, <namespace>)"))
    return out


def test_no_test_module_injects_module_globals_into_a_parsed_namespace():
    """Ban the `ast`-LIFT. Static `ast` WALKING is a different thing and is fine.

    THE DISTINCTION, PLAINLY:

      * STATIC AST WALKING -- parse a module and inspect its tree WITHOUT
        executing it. Safe. Used by this very file, three functions up. It reads
        what the source says and can prove nothing about runtime, which is
        exactly what it claims.

      * THE `ast`-LIFT -- build a namespace, POPULATE it with module globals, and
        execute a parsed body inside it. BANNED. Because the harness SUPPLIES the
        globals, it manufactures any name the module forgot to import, so it can
        never distinguish a name a module IMPORTS from a name it FORGOT to
        import. It only ever proves behaviour, never name resolution -- and it
        will report green either way.

      * A REAL IMPORT -- `importlib.util.spec_from_file_location` +
        `spec.loader.exec_module(module)`. Safe, and the correct tool when name
        resolution is the question, because the module's own imports have to
        succeed. `test_workshop_critique.py::
        test_the_module_loads_standalone_from_its_file_with_no_package_import`
        does this and is NOT a violation. Do not "harden" this guard to ban it.

    THE PRECEDENT: a missing `DISCOVERY_PARENT`, used at four call sites, survived
    nine plans, a clean `py_compile`, and "38 lifted tests green" -- because the
    lift handed the module the name it had failed to import. The first real
    import found it instantly.
    """
    hits: list[str] = []

    for mod in _test_modules():
        tree = ast.parse(mod.read_text(encoding="utf-8"))

        for probe in (
            _module_type_construction,
            _compile_calls,
            _exec_with_namespace,
        ):
            for lineno, what in probe(tree):
                hits.append(f"{mod.name}:{lineno}: {what}")

        for lineno, what in _dict_update_injections(tree):
            hits.append(f"{mod.name}:{lineno}: namespace injection via {what}")

    assert hits == [], (
        "module-global injection found in test modules. The lift SUPPLIES the "
        "globals, so it cannot tell an imported name from a forgotten one and "
        "will report green on a module that does not import. Use a real import "
        f"(`spec.loader.exec_module`) when name resolution is the question:\n  "
        + "\n  ".join(hits)
    )
