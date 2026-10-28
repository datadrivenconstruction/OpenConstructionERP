#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every `from app... import name` in the commit must resolve inside the commit.

On 2026-08-17 `app/modules/rfi/router.py` was committed, clean, importing
`count_activity_for_entity` from `app.core.audit_log` twice. The function
itself never left the working tree. Every local run passed, because every
local run reads the working tree, where the function was present. A fresh
clone could not import the RFI router at all, so the application did not
start, and the first thing to notice was a test failing on collection in CI.

Two neighbouring guards do not cover this. A check for untracked FILES that
the tree references cannot see it, because `audit_log.py` was tracked and only
the symbol inside it was absent. `check_migration_heads.py` answers the same
shape of question for the alembic graph, which is where this class was first
found (a revision naming a parent the repository did not carry), and this is
the import-graph half of it.

So: read blobs out of a git ref rather than off disk, parse them, and ask of
every intra-app `from a.b.c import name` whether this ref's own `a/b/c.py`
binds `name` at module level. Text only, no runtime import, so it needs no
database, no dependencies installed, and it cannot hang on an environment
problem the way importing the real package can.

A symbol is not always imported under its own name. `import app.core.events as
ev` and `from app.core import events` both bind a MODULE, and the symbol is
then reached as an attribute, `ev.publish`. Reading import statements alone
saw the binding and never the use, so a commit could alias a module, call
something that module does not carry, and still be told its imports were fine.
That is the same failure one indirection later: it does not stop the boot, it
stops the first request that reaches the line. So every local name that holds
an app module is followed, and every attribute loaded through one of those
names is asked of that module's own text. An `import app.x` is also asked
whether the ref carries `app/x.py` at all, which the from-import half asked
from the start and this half, reading no `import` statements, could not.

Deliberately quiet about three shapes that cannot break a boot:

  * an import inside `try:` that is caught, which is how this tree probes for
    optional modules,
  * an import inside `if TYPE_CHECKING:`, which never executes,
  * a name reached through a star import, where the namespace is not knowable
    from the module's own text.

Three more keep the attribute half quiet where it cannot know the answer.
Dunder attributes (`modules_pkg.__path__`) are put there by the interpreter and
are in no module's text. A name bound to two different modules in one file is
dropped rather than guessed at, because the tree really does that. A name that
anything else in the file also binds, a parameter or a local, is dropped for
the same reason: from here there is no telling which one a use meant.

Relative imports are skipped; they resolve by position and a missing one is a
syntax-level error the interpreter reports on its own. Modules that do not
parse are counted and named rather than being reported as missing, because
calling an unreadable file an absent one produced 120 false findings on the
first run of this script and a checker that cries wolf stops being read.

Needs a 3.12 interpreter, the same floor the backend itself declares, because
it parses the backend's own syntax. Anything older reads healthy files as
unparsable and the check refuses rather than blaming them.

Usage: .venv-run/Scripts/python.exe scripts/check_head_imports.py [ref]
       (default ref HEAD)
       .venv-run/Scripts/python.exe scripts/check_head_imports.py --selftest
"""

from __future__ import annotations

import ast
import os
import subprocess
import sys
from typing import NamedTuple

PKG = "app"
BACKEND = "backend"


class Findings(NamedTuple):
    """What one scan concluded, and how much of it there was to conclude it from."""

    broken: list[str]
    names: int  # `from app... import x` names asked of the module that should bind them
    modules: int  # `import app.x` modules asked of the ref that should carry them
    attributes: int  # attributes asked of a module reached through a local name
    skipped: set[str]
    unparsable: list[str]


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=os.getcwd(),
    ).stdout


def module_path(mod: str) -> list[str]:
    """Candidate blob paths for a dotted module name, package before module."""
    rel = mod.replace(".", "/")
    return [f"{BACKEND}/{rel}/__init__.py", f"{BACKEND}/{rel}.py"]


def bound_by(target: ast.expr, names: set[str]) -> None:
    """Names bound by one assignment target, including unpacking.

    `ai_limiter, api_limiter, login_limiter = _create_limiters()` binds three
    module-level names through a Tuple target. Reading only ast.Name targets
    missed all three and called four live imports unresolved.
    """
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, (ast.Tuple, ast.List)):
        for el in target.elts:
            bound_by(el, names)
    elif isinstance(target, ast.Starred):
        bound_by(target.value, names)


def bind_block(stmts: list[ast.stmt], names: set[str]) -> None:
    """Names one nested block binds, when the block itself sits at module level.

    A TYPE_CHECKING guard, a version guard and an optional import all bind for
    real, and the module that imports from here cannot tell the difference.
    """
    for sub in stmts:
        if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(sub.name)
        elif isinstance(sub, ast.Import):
            for a in sub.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(sub, ast.ImportFrom):
            for a in sub.names:
                if a.name != "*":
                    names.add(a.asname or a.name)
        elif isinstance(sub, ast.Assign):
            for t in sub.targets:
                bound_by(t, names)
        elif isinstance(sub, ast.AnnAssign) and isinstance(sub.target, ast.Name):
            names.add(sub.target.id)


def optional_line_ranges(tree: ast.Module) -> list[tuple[int, int]]:
    """Line spans where an import may fail or never runs at all."""
    spans: list[tuple[int, int]] = []
    for node in ast.walk(tree):
        guarded = isinstance(node, ast.Try)
        if isinstance(node, ast.If):
            test = node.test
            guarded = (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
                isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
            )
        lineno = getattr(node, "lineno", None)
        end = getattr(node, "end_lineno", None)
        if guarded and lineno and end:
            spans.append((lineno, end))
    return spans


def toplevel_names(tree: ast.Module) -> tuple[set[str], bool]:
    """Every name bound at module level, and whether the module star-imports."""
    names: set[str] = set()
    star = False
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                bound_by(t, names)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.Import):
            for a in node.names:
                names.add(a.asname or a.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == "*":
                    star = True
                else:
                    names.add(a.asname or a.name)
        elif isinstance(node, ast.If):
            # A TYPE_CHECKING block or a version guard still binds names.
            bind_block(list(node.body) + list(node.orelse), names)
        elif isinstance(node, ast.Try):
            # `try: from shapely import Polygon / except ImportError: Polygon = None`
            # binds the name whichever branch runs, and ten modules here bind 40
            # names that way, `collect_rule_issues` and `ClashGeometryProvider`
            # among them. Reading only the unguarded body would call an import of
            # any of those unresolved, which is a false red on a healthy commit.
            for block in (
                node.body,
                node.orelse,
                node.finalbody,
                *(h.body for h in node.handlers),
            ):
                bind_block(block, names)
    return names, star


def rebound_names(tree: ast.Module, ours: set[ast.stmt]) -> set[str]:
    """Names this file binds to something that is not one of those module imports.

    `from app.modules.boq import service` binds a module, and a function further
    down the same file taking a `service` parameter binds something else
    entirely under the same name. Nothing in the text says which of the two a
    given `service.x` meant, so such a name is dropped rather than checked.
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and not isinstance(node.ctx, ast.Load):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) or (
            isinstance(node, ast.ExceptHandler) and node.name
        ):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)) and node not in ours:
            for a in node.names:
                if a.name != "*":
                    names.add(a.asname or a.name.split(".")[0])
    return names


def module_bindings(
    tree: ast.Module,
    defined: dict[str, tuple[set[str], bool]],
    optional: list[tuple[int, int]],
) -> dict[str, str]:
    """Local names in this file that hold an app module, and the module each holds.

    Two shapes bind a module rather than a name: `import app.core.events as ev`,
    and `from app.core import events` where the package does not itself bind
    `events`, which is the far commoner of the two. Imports inside an optional
    span are left out, the same way the name half leaves them out.
    """
    holds: dict[str, set[str]] = {}
    ours: set[ast.stmt] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        if any(lo <= node.lineno <= hi for lo, hi in optional):
            continue
        if isinstance(node, ast.Import):
            for a in node.names:
                if a.asname and (a.name == PKG or a.name.startswith(PKG + ".")):
                    holds.setdefault(a.asname, set()).add(a.name)
                    ours.add(node)
            continue
        mod = node.module or ""
        if node.level or not (mod == PKG or mod.startswith(PKG + ".")):
            continue
        target = next((c for c in module_path(mod) if c in defined), None)
        bound = defined[target][0] if target else set()
        for a in node.names:
            if a.name == "*" or a.name in bound:
                continue
            if any(c in defined for c in module_path(f"{mod}.{a.name}")):
                holds.setdefault(a.asname or a.name, set()).add(f"{mod}.{a.name}")
                ours.add(node)

    if not holds:
        return {}
    shadowed = rebound_names(tree, ours)
    return {name: next(iter(mods)) for name, mods in holds.items() if len(mods) == 1 and name not in shadowed}


def scan(blobs: dict[str, str]) -> Findings:
    """Resolve every intra-app import and module attribute in one set of file texts.

    Takes texts rather than a ref, so the self-test can hand it fixtures and
    nothing in here knows or cares whether they came out of git.
    """
    defined: dict[str, tuple[set[str], bool]] = {}
    unparsable: list[str] = []
    for path, text in blobs.items():
        try:
            defined[path] = toplevel_names(ast.parse(text))
        except SyntaxError as exc:
            unparsable.append(f"{path}: {exc}")

    broken: list[str] = []
    checked = 0
    modules = 0
    attributes = 0
    skipped: set[str] = set()

    for path, text in blobs.items():
        try:
            tree = ast.parse(text)
        except SyntaxError:
            continue
        optional = optional_line_ranges(tree)
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom) or node.level:
                continue
            if any(lo <= node.lineno <= hi for lo, hi in optional):
                continue
            mod = node.module or ""
            if not (mod == PKG or mod.startswith(PKG + ".")):
                continue
            target = next((c for c in module_path(mod) if c in defined), None)
            if target is None:
                present = next((c for c in module_path(mod) if c in blobs), None)
                if present is not None:
                    skipped.add(present)
                    continue
                for a in node.names:
                    if a.name != "*":
                        broken.append(f"MISSING MODULE {mod} (wanted {a.name}), imported by {path}")
                continue
            names, star = defined[target]
            for a in node.names:
                if a.name == "*":
                    continue
                checked += 1
                if a.name in names or star:
                    continue
                if any(c in defined for c in module_path(f"{mod}.{a.name}")):
                    continue  # importing a submodule, not a name
                broken.append(f"UNRESOLVED {mod}.{a.name}, imported by {path}, not defined in {target}")

        # `import app.core.events` names a module rather than a name in it, so the
        # walk above never asks whether the ref carries the module at all. That is
        # the headline failure of this whole check, a clean clone that cannot
        # import the file, and it was reported for one import shape and not the
        # other until this was added.
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import):
                continue
            if any(lo <= node.lineno <= hi for lo, hi in optional):
                continue
            for a in node.names:
                mod = a.name
                if not (mod == PKG or mod.startswith(PKG + ".")):
                    continue
                modules += 1
                if any(c in defined for c in module_path(mod)):
                    continue
                present = next((c for c in module_path(mod) if c in blobs), None)
                if present is not None:
                    skipped.add(present)
                    continue
                broken.append(f"MISSING MODULE {mod}, imported by {path}")

        bindings = module_bindings(tree, defined, optional)
        for node in ast.walk(tree):
            if not isinstance(node, ast.Attribute) or not isinstance(node.ctx, ast.Load):
                continue
            if not isinstance(node.value, ast.Name):
                continue
            mod = bindings.get(node.value.id, "")
            if not mod:
                continue
            if node.attr.startswith("__") and node.attr.endswith("__"):
                continue  # __path__ and __file__ are the interpreter's, not the module's text
            if any(lo <= node.lineno <= hi for lo, hi in optional):
                continue
            target = next((c for c in module_path(mod) if c in defined), None)
            if target is None:
                continue
            names, star = defined[target]
            attributes += 1
            if node.attr in names or star:
                continue
            if any(c in defined for c in module_path(f"{mod}.{node.attr}")):
                continue  # a submodule reached through its package
            broken.append(
                f"UNRESOLVED {mod}.{node.attr}, reached through `{node.value.id}` in {path}, not defined in {target}"
            )

    return Findings(broken, checked, modules, attributes, skipped, unparsable)


def _fail(message: str) -> None:
    print(f"SELF-TEST FAILED: {message}", file=sys.stderr)
    raise SystemExit(2)


def _module(mod: str, text: str, *, package: bool = False) -> tuple[str, str]:
    """One fixture blob, keyed by the path git would key it by."""
    return module_path(mod)[0 if package else 1], text


def self_test() -> None:
    """Prove both halves of the check on fixtures before either is trusted on a ref.

    Runs on every invocation, for the reason its sibling check gives: the tree
    this is pointed at is clean nearly always, so the branch that matters would
    otherwise never be seen to run at all. Fixtures are built in memory and
    nothing is written anywhere, which matters in a working tree that several
    sessions share.
    """
    events = '"""fixture module."""\n\n\ndef publish(topic: str) -> None:\n    return None\n'
    core = dict(
        [
            _module("app", '"""fixture package."""\n', package=True),
            _module("app.core", "", package=True),
        ]
    )
    base = dict(core, **dict([_module("app.core.events", events)]))
    router = "app.modules.rfi.router"

    # The incident this check was written for: a name imported under its own
    # name that the module it names does not bind.
    incident = dict(base, **dict([_module(router, "from app.core.events import record_activity\n")]))
    found = scan(incident)
    if len(found.broken) != 1 or "record_activity" not in found.broken[0]:
        _fail(f"a from-import of a name the module does not carry read as {found.broken}")
    if found.names != 1:
        _fail(f"one imported name was examined, the count says {found.names}")
    if scan(dict(base, **dict([_module(router, "from app.core.events import publish\n")]))).broken:
        _fail("a from-import that does resolve was reported as broken")

    # The hole. Both shapes bind a module and reach the symbol as an attribute,
    # so the import statement alone says nothing about whether it is there.
    use = "\n\n\ndef handle() -> None:\n    {expr}\n"
    aliased = "import app.core.events as ev" + use.format(expr="ev.record_activity('rfi')")
    for source in (
        aliased,
        "from app.core import events" + use.format(expr="events.record_activity('rfi')"),
    ):
        found = scan(dict(base, **dict([_module(router, source)])))
        if len(found.broken) != 1 or "record_activity" not in found.broken[0]:
            _fail(f"an attribute reached through a bound module read as {found.broken}, from:\n{source}")
    # The name half never saw the aliased form at all, which is the whole reason
    # it could pass a commit that calls a function nothing defines.
    if scan(dict(base, **dict([_module(router, aliased)]))).names:
        _fail("an aliased module import was counted as an imported name")
    resolving = "import app.core.events as ev" + use.format(expr="ev.publish('rfi')")
    found = scan(dict(base, **dict([_module(router, resolving)])))
    if found.broken or found.attributes != 1 or found.modules != 1:
        _fail(f"an attribute that does resolve read as {found.broken}, {found.attributes} attribute(s) examined")

    # A module the ref does not carry at all. The from-import shape said so from
    # the start; the two `import` shapes said nothing, which is the same clean
    # clone that cannot start, reported for one spelling and not the others.
    for source in ("import app.core.evnets\n", "import app.core.evnets as ev\n"):
        found = scan(dict(base, **dict([_module(router, source)])))
        if len(found.broken) != 1 or "MISSING MODULE app.core.evnets" not in found.broken[0]:
            _fail(f"an import of a module the ref does not carry read as {found.broken}, from: {source!r}")
    guarded = "try:\n    import app.core.evnets\nexcept ImportError:\n    pass\n"
    if scan(dict(base, **dict([_module(router, guarded)]))).broken:
        _fail("an import of an absent module inside a try was reported")

    # Everything below must stay quiet, because from the text alone the answer
    # is not knowable. A gate that rejects these rejects the tree it guards.
    quiet = {
        "a dunder the interpreter provides": "import app.core as pkg" + use.format(expr="print(pkg.__path__)"),
        "a submodule reached through its package": (
            "import app.core as pkg" + use.format(expr="pkg.events.publish('x')")
        ),
        "a name bound to two different modules": (
            "from app.core import events\nfrom app.other import events" + use.format(expr="events.record_activity('x')")
        ),
        "a name a parameter also binds": (
            "import app.core.events as ev\n\n\ndef handle(ev: object) -> None:\n    ev.record_activity('rfi')\n"
        ),
        "an import that is allowed to fail": (
            "try:\n    import app.core.events as ev\nexcept ImportError:\n    pass\n"
            + use.format(expr="ev.record_activity('rfi')")
        ),
    }
    other = dict([_module("app.other", "", package=True), _module("app.other.events", events)])
    for description, source in quiet.items():
        found = scan(dict(base, **other, **dict([_module(router, source)])))
        if found.broken:
            _fail(f"{description} was reported: {found.broken}")

    # The module answering for its own names has to read its guarded blocks too.
    # Ten modules here bind names nowhere but a module-level try, so a reader of
    # the unguarded body alone reds a healthy import of any of the 40.
    guard = "try:\n    from elsewhere import publish\nexcept ImportError:\n    publish = None\n"
    fallback = dict(base, **dict([_module("app.core.events", guard)]))
    if scan(dict(fallback, **dict([_module(router, "from app.core.events import publish\n")]))).broken:
        _fail("a name bound only inside a module-level try was reported as missing")

    # A star import puts names in the namespace that the module's own text does
    # not carry, so the module stops being able to answer for its attributes.
    star = dict(base, **dict([_module("app.core.events", "from something import *\n")]))
    reaching = "import app.core.events as ev" + use.format(expr="ev.anything()")
    if scan(dict(star, **dict([_module(router, reaching)]))).broken:
        _fail("an attribute of a star-importing module was reported")


def main() -> int:
    args = list(sys.argv[1:])

    # The backend needs 3.12 (PEP 695 `type` aliases, PEP 701 f-strings), so an
    # older interpreter cannot parse it and the files that use either read as
    # unparsable. The check then names those files and returns 2, which is
    # indistinguishable from "this commit is broken". On 2026-08-18 that cost a
    # real investigation before a release: a 3.11 on PATH accused four healthy
    # files, one of them on the single line `type JobHandler = ...`. "I cannot
    # read this" is not "this is wrong", so refuse rather than accuse. This has
    # to stay ahead of the self-test, whose fixtures are read by the same parser.
    # Not a compatibility branch ruff can fold away: this check parses 3.12 syntax
    # and has to refuse rather than report a false clean when run on an older one.
    if sys.version_info < (3, 12):  # noqa: UP036
        running = ".".join(str(p) for p in sys.version_info[:3])
        print(f"ERROR: this check parses 3.12 syntax and is running on {running}, so it proved nothing")
        print("Re-run with the project interpreter, e.g. .venv-run/Scripts/python.exe scripts/check_head_imports.py")
        return 2

    self_test()
    if "--selftest" in args:
        print("self-test OK: both the imported-name half and the module-attribute half hold on fixtures.")
        return 0

    ref = next((a for a in args if not a.startswith("-")), "HEAD")

    files = [p for p in git("ls-tree", "--name-only", "-r", ref, f"{BACKEND}/{PKG}").splitlines() if p.endswith(".py")]
    if not files:
        # "found nothing" and "did not look" must not print the same thing.
        print(f"ERROR: {ref} carries no {BACKEND}/{PKG} python files, this check proved nothing")
        return 2

    found = scan({path: git("show", f"{ref}:{path}") for path in files})

    if found.unparsable:
        print(f"ERROR: {len(found.unparsable)} file(s) under {BACKEND}/{PKG} do not parse in {ref}:")
        for u in found.unparsable:
            print(f"    {u}")
        return 2

    if found.broken:
        print(f"ERROR: {len(found.broken)} import(s) in {ref} name something {ref} does not carry.")
        print("A clean clone of this commit cannot import these modules, so the application does not start.")
        print("The fix is almost always that the definition is still sitting in a working tree uncommitted.\n")
        for b in found.broken:
            print(f"    {b}")
        return 1

    note = f", {len(found.skipped)} unparsable module(s) skipped" if found.skipped else ""
    print(
        f"head imports OK: {found.names} imported name(s), {found.modules} imported module(s) and "
        f"{found.attributes} attribute(s) reached through a bound module in {ref} all resolve within {ref}{note}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
