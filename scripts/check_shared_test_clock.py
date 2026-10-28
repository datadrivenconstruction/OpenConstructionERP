#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Fail if a shared test clock anchor appears that is not the declared one.

Ninety-nine fixed date constants live in the backend test suite, spread over
seventy-seven files, and between them they name forty distinct instants. The
same identifier means different days in different files: ``NOW`` is five
separate instants (2026-06-24, 06-25, 06-30, 07-08, 07-21), ``TODAY`` is six
(2026-06-06, 06-24, 07-10, 07-16, 07-26, 08-05), and ``AS_OF`` is 2025-01-01 in
one file and 2026-07-16 in another. Forty-three different names are in use for
the one concept.

That sounds like a defect and today it is not one, which is the whole reason
this gate exists in this shape rather than as a rewrite.

Why the ninety-nine are fine and stay untouched
-----------------------------------------------
Every one of them is file-local. No conftest defines a date, no fixture returns
one, and nothing in the suite lets two of these constants meet. Within any one
file the set is internally coherent: ``test_interface_management_register.py``
holds ``_PAST``, ``_AS_OF`` and ``_FUTURE`` as a consistent triple, and a
reader of that file is never misled. A test written against a local constant
and a helper written against a different local constant cannot disagree,
because they never appear in the same run with both constants live.

So the collision is latent, not live, and normalising ninety-nine constants
across seventy-seven files in a tree with many concurrent branches would be
certain churn today against a hypothetical benefit. The cheaper move is to make
the latent case unable to become live.

What makes it live is one thing: a *shared* anchor
--------------------------------------------------
The moment a date is defined somewhere every test can see - a conftest
constant, a fixture that returns "today" - the file-local constants stop being
independent. A test that pins 2026-07-16 locally and a helper that reads a
shared anchor pinned to 2026-06-24 will disagree about what day it is inside a
single run, and that disagreement surfaces as a logic bug in whatever the two
of them touch, a long way from either date.

This gate permits exactly one shared anchor, at one declared location under one
declared name. Anything else defined at shared scope fails. If the project ever
does want a suite-wide clock, it goes in the declared slot and the argument
about which instant it holds happens once, in one place, in the open.

What counts as shared scope
---------------------------
Two things, and only two:

* any ``conftest.py`` under the test root, because pytest hands its contents to
  every test in that directory tree without an import; and
* any test module imported by two or more other test modules, because that is a
  shared helper in practice whatever it is called. ``tests/_pg.py`` is one of
  these and is imported by more than a hundred files.

What counts as an anchor
------------------------
A module-level name bound to a value that *is* a date, or a pytest fixture that
returns or yields one. The check keys on the binding, not on the identifier, so
it needs no list of blessed names and cannot be defeated by inventing a
forty-fourth one.

Two shapes deliberately do not count, both of them present in the tree today
and both correct:

* a function parameter default, such as the ``rate_date: str = "2026-04-07"``
  on the row factory in ``tests/modules/i18n_foundation/conftest.py``. It is
  data handed to one factory, not a clock every test reads; and
* a module-level constant whose value merely *contains* a date, such as the
  ``ECB_XML`` feed sample in ``tests/modules/fx/conftest.py``. The value is a
  document, and the date inside it is part of the document.

The distinction is that the bound value has to be a date itself, not a thing
with a date in it.

What this gate does not do
--------------------------
It runs as a pre-commit hook and in the Repo hygiene lane, so it fires when
somebody commits or when CI runs. It is not a tripwire and nothing here watches
the tree: a shared anchor written this morning is caught when it is committed,
not when it is written. It also cannot see an anchor introduced by a route it
does not scan - a plugin, an installed package, an environment variable read at
collection time. It closes the path that is actually open, which is a constant
or a fixture in a file, and a reader should not assume more of it than that.
"""

from __future__ import annotations

import ast
import os
import re
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEST_ROOT = os.path.join(REPO_ROOT, "backend", "tests")

# The single permitted shared anchor. Nothing occupies this slot today; the
# suite has no shared clock at all, and the count below says so on every run.
# If a suite-wide clock is ever wanted, it goes here and only here.
DECLARED_ANCHOR_FILE = os.path.join("backend", "tests", "conftest.py")
DECLARED_ANCHOR_NAME = "SUITE_CLOCK"

# A scan that walks nothing reports a clean tree, for the same reason a suite
# with no tests reports success. These floors are the measured shape of the
# tree when this gate was written (1753 test modules, 14 conftests, and shared
# helpers led by tests/_pg.py); anything far below them means the scan did not
# see the test tree and must say so rather than pass.
MIN_TEST_FILES = 500
MIN_CONFTESTS = 5
MIN_SHARED_HELPERS = 1

# A whole string that is a date, and nothing else. Anchored at both ends on
# purpose: a document that merely contains a date is not an anchor.
WHOLE_ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?(?:Z|[+-]\d{2}:?\d{2})?$")

DATE_CTORS = {"date", "datetime"}

# ``from tests.x.y import z`` / ``import tests.x.y``, at the start of a line.
TESTS_IMPORT = re.compile(r"^\s*(?:from|import)\s+(tests\.[A-Za-z0-9_.]+)", re.M)


def _is_date_value(node: ast.AST) -> str | None:
    """Return a readable form of the date this expression IS, or None.

    ``date(2026, 6, 1)`` and ``"2026-06-01"`` are dates. ``"<xml ... 2026-03-02
    ... />"`` is a document and returns None. An anchor written with an offset,
    ``date(2026, 6, 1) + timedelta(days=7)``, is still an anchor, so the left
    side of an addition is inspected too.
    """
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub)):
        return _is_date_value(node.left)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value if WHOLE_ISO_DATE.match(node.value) else None
    if isinstance(node, ast.Call):
        fn = node.func
        name = fn.attr if isinstance(fn, ast.Attribute) else (fn.id if isinstance(fn, ast.Name) else None)
        if name in DATE_CTORS:
            args = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, int)]
            if len(args) >= 3:
                return f"{name}({', '.join(str(a) for a in args[:3])})"
    return None


def _is_fixture(node: ast.AST) -> bool:
    """Whether a function carries a pytest fixture decorator."""
    for dec in getattr(node, "decorator_list", []):
        target = dec.func if isinstance(dec, ast.Call) else dec
        name = target.attr if isinstance(target, ast.Attribute) else (target.id if isinstance(target, ast.Name) else "")
        if name == "fixture":
            return True
    return False


def collect_python_files(root: str) -> list[str]:
    out: list[str] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            if name.endswith(".py"):
                out.append(os.path.join(dirpath, name))
    return sorted(out)


def shared_helper_modules(files: list[str]) -> dict[str, int]:
    """Test modules imported by two or more other test modules.

    A helper does not have to be called a helper. What makes a module shared is
    that other test modules import it, so that is what gets counted.
    """
    # Read imports with a regex rather than an AST. Parsing all 1753 test
    # modules to answer a line-oriented question took seventeen seconds, which
    # is too slow for a hook that runs on every commit touching a test, and a
    # slow hook is a hook people disable. The precision loss is one-sided and
    # safe: a commented-out or quoted import adds a module to the set of files
    # whose bindings get inspected properly by AST below, and inspecting one
    # extra file cannot produce a false failure.
    importers: dict[str, set[str]] = {}
    for path in files:
        try:
            with open(path, encoding="utf-8") as handle:
                text = handle.read()
        except (OSError, UnicodeDecodeError):
            continue
        for match in TESTS_IMPORT.finditer(text):
            importers.setdefault(match.group(1), set()).add(path)
    return {mod: len(who) for mod, who in importers.items() if len(who) >= 2}


def module_to_path(dotted: str) -> str:
    rel = dotted[len("tests.") :].replace(".", os.sep)
    for candidate in (
        os.path.join(TEST_ROOT, rel + ".py"),
        os.path.join(TEST_ROOT, rel, "__init__.py"),
    ):
        if os.path.isfile(candidate):
            return candidate
    return ""


def anchors_in(path: str) -> list[tuple[int, str, str, str]]:
    """Module-level date constants and fixtures returning a date."""
    try:
        with open(path, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
    except (OSError, SyntaxError, UnicodeDecodeError):
        return []
    found: list[tuple[int, str, str, str]] = []

    for node in tree.body:
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            value = node.value
            if value is None:
                continue
            shown = _is_date_value(value)
            if shown is None:
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    found.append((node.lineno, target.id, shown, "module-level constant"))
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and _is_fixture(node):
            for sub in ast.walk(node):
                if isinstance(sub, (ast.Return, ast.Yield)) and sub.value is not None:
                    shown = _is_date_value(sub.value)
                    if shown is not None:
                        found.append((sub.lineno, node.name, shown, "fixture return"))
    return found


def main() -> int:
    if not os.path.isdir(TEST_ROOT):
        print(f"ERROR: test root not found: {TEST_ROOT}")
        print("The scan walked nothing, so its answer about shared clocks means nothing.")
        return 1

    files = collect_python_files(TEST_ROOT)
    conftests = [f for f in files if os.path.basename(f) == "conftest.py"]
    helpers = shared_helper_modules(files)

    failed = False
    if len(files) < MIN_TEST_FILES:
        print(f"ERROR: found {len(files)} test modules, expected at least {MIN_TEST_FILES}.")
        print("The scan did not see the test tree, so a clean result would be meaningless.")
        failed = True
    if len(conftests) < MIN_CONFTESTS:
        print(f"ERROR: found {len(conftests)} conftest.py files, expected at least {MIN_CONFTESTS}.")
        failed = True
    if len(helpers) < MIN_SHARED_HELPERS:
        print(f"ERROR: found {len(helpers)} shared test helper modules, expected at least {MIN_SHARED_HELPERS}.")
        print("Shared helpers are one of the two places an anchor can hide; finding none means the scan missed them.")
        failed = True
    if failed:
        return 1

    scanned: list[tuple[str, str]] = [(p, "conftest") for p in conftests]
    for dotted in sorted(helpers):
        path = module_to_path(dotted)
        if path and (path, "conftest") not in scanned:
            scanned.append((path, f"shared helper, imported by {helpers[dotted]} modules"))

    violations: list[tuple[str, int, str, str, str]] = []
    for path, why in scanned:
        rel = os.path.relpath(path, REPO_ROOT).replace(os.sep, "/")
        for lineno, name, shown, kind in anchors_in(path):
            declared = rel == DECLARED_ANCHOR_FILE.replace(os.sep, "/") and name == DECLARED_ANCHOR_NAME
            if not declared:
                violations.append((rel, lineno, name, shown, f"{kind}, {why}"))

    if violations:
        print(f"ERROR: {len(violations)} shared test clock anchor(s) that are not the declared one:\n")
        for rel, lineno, name, shown, kind in violations:
            print(f"  {rel}:{lineno}")
            print(f"      {name} = {shown}   ({kind})")
        print(
            "\nA date defined at shared scope is visible to every test that can reach it, and\n"
            "that is what makes the suite's file-local date constants able to disagree with\n"
            "each other. There are 99 of them across 77 files naming 40 distinct instants;\n"
            "they are safe today only because nothing lets two of them meet in one run.\n"
            "\n"
            "What to do instead, in order of preference:\n"
            "\n"
            "  1. Keep it file-local. If only one test file needs the date, define it in that\n"
            "     file. This is what the other 99 do and it needs no coordination with anyone.\n"
            "\n"
            "  2. Pass it in explicitly. Most of this suite's date-sensitive code already takes\n"
            "     an as-of parameter - as_of, today, data_date, reference_date, as_at - and the\n"
            "     tests that use it are the ones that never rot. Prefer this to any anchor.\n"
            "\n"
            "  3. If the suite genuinely needs one shared clock, put it at\n"
            f"     {DECLARED_ANCHOR_FILE} as {DECLARED_ANCHOR_NAME} and change this gate in the\n"
            "     same commit. That is a deliberate, reviewable decision about which instant\n"
            "     the whole suite believes in, which is exactly the conversation worth having\n"
            "     once rather than forty times.\n"
            "\n"
            "A parameter default and a document that happens to contain a date are not\n"
            "anchors and this gate does not flag them; if you are seeing this for one of\n"
            "those, the check is wrong and should be fixed rather than worked around."
        )
        return 1

    print(
        f"no shared test clock: {len(conftests)} conftest(s) and "
        f"{len(helpers)} shared helper module(s) scanned across {len(files)} test modules, "
        f"0 shared date anchors."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
