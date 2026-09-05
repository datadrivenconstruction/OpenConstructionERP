#!/usr/bin/env python3
"""Fail when a tracked Python file imports a module git does not have.

The defect this closes is invisible on the author's disk. A file that is
committed imports a module that only ever existed as an untracked file in the
working tree, so every import works locally, every test passes locally, and the
first machine to read the commit instead of the disk - a CI checkout, a fresh
clone, a wheel build, the next developer - gets ModuleNotFoundError on startup.
Nothing else in this repository looks at that seam, because every commit-scoped
gate reads the commit and every build reads the disk, and the two agree right
up until the moment one file is committed without its neighbour.

It is not hypothetical. Two live instances sat in the tree on 2026-09-05, both
uncommitted at the time of writing:

    backend/app/main.py and backend/app/modules/takeoff/router.py
        import app.core.host_disclosure, untracked
    backend/app/modules/postcalc/service.py
        imports app.modules.postcalc.norm_outturn, untracked

This runs on the same tree in two different worlds and says something useful in
both. In a working tree the missing module is usually present but untracked, so
the message is "git add it". In a checkout there are no untracked files at all
and the same import simply resolves to nothing, so the message is "the commit
does not carry it". One rule covers both: the file that defines the module has
to be in git.

What it deliberately does not fail on, because a gate that cries wolf on a tree
shared by many authors is a gate someone switches off:

  * anything that is not an intra-project module - the standard library and
    third-party packages are out of scope and are identified by their top-level
    name not being a package directly under backend/;
  * imports under `if TYPE_CHECKING:`, which never execute;
  * imports inside a `try` whose handler catches an import error and does
    something other than re-raise, i.e. optional dependencies with a real
    fallback. A handler that only re-raises is not a fallback and is still
    checked, because such an import is required, just with a nicer message;
  * a `from package import name` where `name` is a symbol rather than a
    submodule, which is the overwhelmingly common case and is told apart from a
    submodule by whether a file of that name exists at all.

The rule for what counts as an intra-project root is worth stating, because
getting it wrong is what a first attempt at this script did. A top-level name
belongs to us only when `backend/<name>/__init__.py` exists. A directory
without an `__init__.py` is a namespace portion, which loses to any regular
package found later on sys.path, so it does not shadow an installed
distribution of the same name. `backend/alembic/` is exactly that: a migrations
directory with no `__init__.py`, next to an installed `alembic` package. A
first cut of this check treated every directory under backend/ as a root and
reported 51 findings, every one of them a line importing `alembic.config` or
`alembic.operations` from the library. Three findings were real. A gate that
buries three real findings under 51 false ones has not found anything.

Exit codes:
    0  every intra-project import resolves to a file git has
    1  at least one does not, and the output names every one
    2  --self-test could not prove the check still refuses a bad tree

Usage::

    python scripts/check_untracked_imports.py                # whole tree
    python scripts/check_untracked_imports.py --paths a.py   # only these files
    python scripts/check_untracked_imports.py --self-test    # prove it refuses
"""

from __future__ import annotations

import argparse
import ast
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]

# The import root: the directory that is on sys.path when the backend runs, so
# `app.core.config` means backend/app/core/config.py. Everything this script
# resolves is relative to it.
SOURCE_PREFIX = "backend"

# Directories that never hold importable project code and cost real time to
# walk on a shared tree full of build output and scratch checkouts.
SKIP_DIRS = frozenset(
    {
        "__pycache__",
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        ".venv-run",
        "dist",
        "build",
        "node_modules",
        "site-packages",
    }
)

# Catching one of these by name says the author was thinking about an import
# that might not be there.
IMPORT_ERRORS = frozenset({"ImportError", "ModuleNotFoundError"})

# Catching one of these says nothing of the sort on its own. The backend guards
# most of its startup in `except Exception` so that a broken subsystem cannot
# stop the process, and backend/app/main.py alone carries dozens of those
# blocks with no `except ImportError` anywhere in the file. Treating them as
# optional-import guards took 111 of the 232 intra-project imports in four
# files out of the check's reach - a gate whose population excludes half the
# file it is pointed at. So a bare `except Exception` only makes an import
# optional when the `try` body is nothing but imports, which is the shape of a
# real optional dependency and not the shape of a guarded startup block.
BROAD_ERRORS = frozenset({"Exception", "BaseException"})


@dataclass(frozen=True)
class Finding:
    """One import in one tracked file that git cannot satisfy."""

    path: str
    line: int
    module: str
    reason: str
    defining_file: str | None

    def render(self) -> str:
        where = f"  {self.path}:{self.line}"
        what = f"imports `{self.module}`"
        if self.defining_file is not None:
            return f"{where}: {what}, defined in {self.defining_file}, which git does not have ({self.reason})"
        return f"{where}: {what}, and no file defines it in this commit ({self.reason})"


@dataclass(frozen=True)
class ImportSite:
    """An import statement, with the context that decides whether it counts."""

    module: str
    names: tuple[str, ...]
    line: int
    from_form: bool
    type_checking: bool
    optional: bool


class ImportCollector(ast.NodeVisitor):
    """Collect every import in a module, remembering the guards around it.

    A regex cannot do this job here. `from x import (a, b, c)` spans lines, the
    same statement appears indented inside functions, inside `if TYPE_CHECKING`
    and inside `try`, and the difference between those cases is the whole
    question. The AST is the only reader that sees the nesting.
    """

    def __init__(self, package: str | None) -> None:
        self.package = package
        self.sites: list[ImportSite] = []
        self._type_checking = 0
        self._optional = 0

    def _visit_all(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self.visit(statement)

    def visit_If(self, node: ast.If) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        if _is_type_checking_test(node.test):
            self._type_checking += 1
            self._visit_all(node.body)
            self._type_checking -= 1
            self._visit_all(node.orelse)
        else:
            self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        if _try_makes_its_imports_optional(node):
            self._optional += 1
            self._visit_all(node.body)
            self._optional -= 1
            for handler in node.handlers:
                self._visit_all(handler.body)
            self._visit_all(node.orelse)
            self._visit_all(node.finalbody)
        else:
            self.generic_visit(node)

    def visit_Import(self, node: ast.Import) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        for alias in node.names:
            self.sites.append(self._site(alias.name, (), node.lineno, from_form=False))

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:  # noqa: N802 - ast.NodeVisitor protocol
        module = self._absolute(node)
        if module is None:
            return
        names = tuple(alias.name for alias in node.names if alias.name != "*")
        self.sites.append(self._site(module, names, node.lineno, from_form=True))

    def _site(self, module: str, names: tuple[str, ...], line: int, *, from_form: bool) -> ImportSite:
        return ImportSite(
            module=module,
            names=names,
            line=line,
            from_form=from_form,
            type_checking=self._type_checking > 0,
            optional=self._optional > 0,
        )

    def _absolute(self, node: ast.ImportFrom) -> str | None:
        """Turn `from .x import y` into the dotted name it actually reaches."""
        if not node.level:
            return node.module or None
        if self.package is None:
            return None
        parts = self.package.split(".")
        climb = node.level - 1
        if climb > len(parts):
            return None
        base = parts[: len(parts) - climb] if climb else parts
        if not base:
            return None
        return ".".join(base) + (f".{node.module}" if node.module else "")


def _is_type_checking_test(test: ast.expr) -> bool:
    """True for `if TYPE_CHECKING:` and `if typing.TYPE_CHECKING:`."""
    for node in ast.walk(test):
        if isinstance(node, ast.Name) and node.id == "TYPE_CHECKING":
            return True
        if isinstance(node, ast.Attribute) and node.attr == "TYPE_CHECKING":
            return True
    return False


def _caught_by(handler: ast.ExceptHandler) -> set[str]:
    if handler.type is None:
        return {"BaseException"}
    caught = set()
    for node in ast.walk(handler.type):
        if isinstance(node, ast.Name):
            caught.add(node.id)
        elif isinstance(node, ast.Attribute):
            caught.add(node.attr)
    return caught


def _is_import_shaped(body: list[ast.stmt]) -> bool:
    """True for a `try` body that does nothing but import.

    Nothing but import. An assignment is not allowed in here, however harmless
    it looks: `try: import x; y = x.f(); ok = True / except Exception:` is a
    guarded startup block, not an optional dependency, and letting a body with
    assignments count as import-shaped put the real defect straight back out of
    reach in backend/app/main.py, which is the file that was carrying it. See
    BROAD_ERRORS above for the count that shape is worth.
    """
    return all(
        isinstance(statement, (ast.Import, ast.ImportFrom, ast.Pass))
        or (isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant))
        for statement in body
    )


def _try_makes_its_imports_optional(node: ast.Try) -> bool:
    """True when this `try` really is guarding an import that may not be there.

    A handler whose body is nothing but `raise` is not a fallback. It turns a
    ModuleNotFoundError into a different exception or re-raises the same one,
    which means the module is still required and the import still has to be in
    the commit, so `except ImportError: raise RuntimeError("install extras")`
    stays inside the check rather than being waved through.
    """
    import_shaped = _is_import_shaped(node.body)
    for handler in node.handlers:
        caught = _caught_by(handler)
        if not (caught & IMPORT_ERRORS or (caught & BROAD_ERRORS and import_shaped)):
            continue
        if not all(isinstance(statement, ast.Raise) for statement in handler.body):
            return True
    return False


class ModuleIndex:
    """Where an intra-project module name resolves, and whether git has it.

    Deliberately built from two plain sets rather than from the filesystem, so
    the tests can hand it a tree that does not exist on disk.
    """

    def __init__(self, tracked: set[str], on_disk: set[str], untracked: set[str], prefix: str = SOURCE_PREFIX) -> None:
        self.prefix = prefix
        self.tracked = tracked
        self.on_disk = on_disk
        self.untracked = untracked
        # Unioned once. Doing it inside locate() instead rebuilt a thirty
        # thousand element set on every one of seventeen thousand resolutions,
        # and turned a full run into nine and a half minutes of work that is
        # really just parsing the files.
        self.known = on_disk | tracked
        self.directories = _directories_of(self.known)
        self.roots = {
            path.split("/")[1]
            for path in self.known
            if path.startswith(f"{prefix}/") and path.count("/") == 2 and path.endswith("/__init__.py")
        }

    def is_intra_project(self, module: str) -> bool:
        return module.split(".")[0] in self.roots

    def locate(self, module: str) -> tuple[str, str | None]:
        """Return (kind, defining file) for a dotted name.

        kind is one of package, module, namespace, absent. A namespace is a
        directory with no `__init__.py`: importable, but with no file to track,
        and it is how an installed distribution of the same name gets reached.
        """
        base = f"{self.prefix}/" + module.replace(".", "/")
        init, plain = f"{base}/__init__.py", f"{base}.py"
        if init in self.known:
            return "package", init
        if plain in self.known:
            return "module", plain
        if base in self.directories:
            return "namespace", None
        return "absent", None

    def state_of(self, path: str) -> str:
        if path in self.tracked:
            return "tracked"
        if path in self.untracked:
            return "untracked"
        if path in self.on_disk:
            return "ignored by .gitignore"
        return "not on disk"

    def ancestors(self, module: str) -> list[tuple[str, str]]:
        """The packages an import of this module has to load on the way in.

        Each is returned as (dotted name, defining file). A submodule can be
        tracked while the `__init__.py` above it is not, and the import fails in
        a checkout all the same.
        """
        parts = module.split(".")
        found = []
        for depth in range(1, len(parts)):
            init = f"{self.prefix}/" + "/".join(parts[:depth]) + "/__init__.py"
            if init in self.known:
                found.append((".".join(parts[:depth]), init))
        return found


def _directories_of(paths: set[str]) -> set[str]:
    directories: set[str] = set()
    for path in paths:
        parts = path.split("/")
        for depth in range(1, len(parts)):
            directories.add("/".join(parts[:depth]))
    return directories


def _package_of(path: str, prefix: str = SOURCE_PREFIX) -> str | None:
    """The dotted package a file lives in, for resolving relative imports."""
    if not path.startswith(f"{prefix}/"):
        return None
    parts = path[len(prefix) + 1 :].split("/")
    return ".".join(parts[:-1]) if len(parts) > 1 else None


def check_file(path: str, source: str, index: ModuleIndex, stats: dict[str, int] | None = None) -> list[Finding]:
    """Every import in one file that git cannot satisfy. Order is stable.

    `stats` collects the population the verdict is made over: a count of zero
    findings means nothing without the number of imports it was reached across,
    and that number has to come from the same pass that produced the verdict.
    """
    tally = stats if stats is not None else {}
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as exc:
        return [Finding(path, exc.lineno or 0, "<file>", f"cannot be parsed: {exc.msg}", None)]

    collector = ImportCollector(_package_of(path, index.prefix))
    collector.visit(tree)

    findings: list[Finding] = []
    seen: set[tuple[str, int]] = set()

    def record(module: str, line: int, kind: str, defining: str | None) -> None:
        if kind == "namespace":
            # A directory with no __init__.py. It imports at runtime and there
            # is no file to track, so there is nothing here to refuse.
            # backend/app/ has fifteen of these - fonts, licences, seed data,
            # message catalogues - and treating them as missing modules would
            # invent a finding out of a directory that is working correctly.
            return
        if kind == "absent":
            reason = "no such module"
        else:
            reason = index.state_of(defining) if defining else "no such module"
            if reason == "tracked":
                return
        if (module, line) in seen:
            return
        seen.add((module, line))
        findings.append(Finding(path, line, module, reason, defining))

    tally["statements"] = tally.get("statements", 0) + len(collector.sites)
    for site in collector.sites:
        if not index.is_intra_project(site.module):
            continue
        tally["intra_project"] = tally.get("intra_project", 0) + 1
        if site.type_checking:
            tally["skipped_type_checking"] = tally.get("skipped_type_checking", 0) + 1
            continue
        if site.optional:
            tally["skipped_optional"] = tally.get("skipped_optional", 0) + 1
            continue
        tally["resolved"] = tally.get("resolved", 0) + 1
        kind, defining = index.locate(site.module)
        record(site.module, site.line, kind, defining)
        if kind == "absent":
            continue
        for dotted, init in index.ancestors(site.module):
            record(dotted, site.line, "package", init)
        if not site.from_form or kind not in {"package", "namespace"}:
            continue
        for name in site.names:
            sub_kind, sub_defining = index.locate(f"{site.module}.{name}")
            if sub_kind == "absent":
                continue  # a class, a function or a constant, not a submodule
            record(f"{site.module}.{name}", site.line, sub_kind, sub_defining)
    return findings


def _git(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), *args],
        capture_output=True,
        text=True,
        check=True,
    )
    return [line for line in result.stdout.split("\0") if line]


def _walk_python_files(root: Path) -> set[str]:
    found: set[str] = set()
    for base, directories, files in os.walk(root):
        directories[:] = [name for name in directories if name not in SKIP_DIRS]
        for name in files:
            if name.endswith(".py"):
                found.add(Path(base).joinpath(name).relative_to(REPO_ROOT).as_posix())
    return found


def build_index() -> ModuleIndex:
    tracked = {path for path in _git("ls-files", "-z") if path.endswith(".py")}
    untracked = {path for path in _git("ls-files", "--others", "--exclude-standard", "-z") if path.endswith(".py")}
    source_root = REPO_ROOT / SOURCE_PREFIX
    on_disk = _walk_python_files(source_root) if source_root.is_dir() else set()
    return ModuleIndex(tracked=tracked, on_disk=on_disk, untracked=untracked)


def run(selected: list[str] | None) -> tuple[list[Finding], dict[str, int]]:
    index = build_index()
    counts: dict[str, int] = {"files": 0, "unreadable": 0, "not_checked": 0}
    if selected is None:
        targets = sorted(path for path in index.tracked if path.startswith(f"{SOURCE_PREFIX}/"))
    else:
        # A path this cannot check is said out loud rather than dropped. A hook
        # handed five files and quietly reading four still prints a verdict,
        # and the verdict looks exactly like the one it would print having read
        # all five.
        given = sorted({Path(path).as_posix().removeprefix("./") for path in selected})
        targets = [path for path in given if path in index.tracked and path.startswith(f"{SOURCE_PREFIX}/")]
        counts["not_checked"] = len(given) - len(targets)

    findings: list[Finding] = []
    for path in targets:
        try:
            source = (REPO_ROOT / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            counts["unreadable"] += 1
            continue
        counts["files"] += 1
        findings.extend(check_file(path, source, index, counts))
    counts["roots"] = len(index.roots)
    return findings, counts


# A tree small enough to read in one sitting and shaped like the real defect.
# Its point is the second half: every entry below the untracked import is a
# shape the check has to let through, and each one of them is a shape that
# exists in backend/ today.
SELF_TEST_TRACKED = {
    "backend/app/__init__.py",
    "backend/app/core/__init__.py",
    "backend/app/core/config.py",
    "backend/app/main.py",
}
SELF_TEST_UNTRACKED = {"backend/app/core/secrets_probe.py"}
SELF_TEST_SOURCE = """\
from __future__ import annotations

import json
from typing import TYPE_CHECKING

import alembic.config

from app.core import config
from app.core.config import Settings
from app.core.secrets_probe import probe

if TYPE_CHECKING:
    from app.core.only_for_types import Shape

try:
    from app.core.optional_extra import extra
except ImportError:
    extra = None
"""


def self_test() -> int:
    """Prove the check still refuses, on a tree built for the purpose.

    A gate is only worth its silence if its noise has been seen. This runs the
    real checker over a synthetic tree that carries one genuine defect and five
    lookalikes, and fails when either half stops holding.
    """
    index = ModuleIndex(
        tracked=set(SELF_TEST_TRACKED),
        on_disk=set(SELF_TEST_TRACKED) | set(SELF_TEST_UNTRACKED),
        untracked=set(SELF_TEST_UNTRACKED),
    )
    findings = check_file("backend/app/main.py", SELF_TEST_SOURCE, index)
    modules = sorted(finding.module for finding in findings)

    problems = []
    if modules != ["app.core.secrets_probe"]:
        problems.append(f"expected exactly the untracked import to be caught, got {modules}")
    if index.roots != {"app"}:
        problems.append(f"expected `app` to be the only intra-project root, got {sorted(index.roots)}")

    clean = ModuleIndex(
        tracked=set(SELF_TEST_TRACKED) | set(SELF_TEST_UNTRACKED),
        on_disk=set(SELF_TEST_TRACKED) | set(SELF_TEST_UNTRACKED),
        untracked=set(),
    )
    if check_file("backend/app/main.py", SELF_TEST_SOURCE, clean):
        problems.append("the same file passed nothing once its import was tracked, so the check never clears")

    if problems:
        print("FAIL: the untracked-import check cannot prove it still works.")
        for problem in problems:
            print(f"  {problem}")
        return 2
    print("[OK] self-test: one untracked import caught, five lookalikes let through, tracked tree clean")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fail when a tracked Python file imports a module git does not have.",
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        help="check only these files instead of every tracked file under backend/",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the check still refuses a tree with an untracked import",
    )
    args = parser.parse_args()

    if args.self_test:
        return self_test()

    findings, counts = run(args.paths)
    where = "the tracked tree" if args.paths is None else "the selected files"
    population = (
        f"{counts['files']} tracked Python files under {SOURCE_PREFIX}/, "
        f"{counts.get('statements', 0)} import statements, "
        f"{counts.get('intra_project', 0)} of them intra-project over "
        f"{counts['roots']} roots, {counts.get('resolved', 0)} resolved "
        f"({counts.get('skipped_type_checking', 0)} skipped as TYPE_CHECKING, "
        f"{counts.get('skipped_optional', 0)} as optional)"
    )
    if counts["not_checked"]:
        population += f"; not read: {counts['not_checked']} of the given paths, untracked or outside {SOURCE_PREFIX}/"
    if counts["unreadable"]:
        population += f"; {counts['unreadable']} could not be decoded as UTF-8"

    if findings:
        print(f"ERROR: {len(findings)} import(s) in {where} name a module git does not have:", file=sys.stderr)
        for finding in sorted(findings, key=lambda item: (item.path, item.line, item.module)):
            print(finding.render(), file=sys.stderr)
        print(
            "\nThe file that defines each module has to be in the same commit as "
            "the file importing it. `git add` it, or, if it is ignored, stop "
            "ignoring it. Until then this import works on the disk it was "
            "written on and nowhere else: a checkout has no untracked files, so "
            "the backend fails to start on the first machine that reads the "
            f"commit rather than the working tree. Checked {population}.",
            file=sys.stderr,
        )
        return 1

    print(f"untracked imports OK: {population}, every intra-project import resolves to a tracked file")
    return 0


if __name__ == "__main__":
    sys.exit(main())
