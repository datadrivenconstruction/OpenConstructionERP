#!/usr/bin/env python3
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Every migration that rewrites rows must say whether that rewrite reaches a real install.

Why this exists
---------------
This product does not run ``alembic upgrade``. The schema moves at boot through
``postgres_auto_migrate`` (ADD COLUMN / CREATE INDEX / ADD CONSTRAINT, plus one
DROP NOT NULL) and ``Base.metadata.create_all`` (whole missing tables). Neither
executes a revision's ``upgrade()`` body, and ``stamp_head_if_unstamped`` then
records the database at head. So a revision that backfills, renames or
de-duplicates rows never runs on an ordinary install, while every signal the
product has reports that it did.

``v3271_formwork_debrand`` is the case that made this concrete: it renames
trademarked catalogue rows, it had never executed on any install brought up the
normal way, and eleven months passed before anyone noticed - because there was
nothing to notice. The version table said head.

Sister script, different question
---------------------------------
``check_migration_data_rewrites.py`` asks how BIG a data rewrite is (issue #126,
a backfill that doubled peak disk on a 1724 MB table) and requires a
``# data-rewrite-ack:`` comment per table. This script reuses that script's scan
verbatim - same enumeration, same AST classifier, imported rather than
re-implemented, so the two cannot disagree about which revisions are flagged -
and asks the other question about the same set: does the rewrite REACH anybody.

The declaration
---------------
A flagged revision must carry at least one ``# boot-repair:`` comment. Four
forms, and the third and fourth are answers rather than escape hatches::

    # boot-repair: registry=<repair_id>
    # boot-repair: boot-path=<path>::<symbol>
    # boot-repair: none - <why no boot-path half is needed>
    # boot-repair: gap - <what does not reach an ordinary install>

``registry`` names an id passed to ``register_data_repair()`` in an
app/**/repairs.py, whose core lives in
``backend/app/core/data_repairs.py``, which the boot path runs on every start.
The id is checked against that file.

``boot-path`` names a module-level function that already does this repair
somewhere on the boot sequence - two of them predate the registry and are
ordered against the schema heal, so they stay where they are. The file and the
symbol are both checked.

``none`` says no boot-path half is needed, and the reason has to say why: the
rewrite only touches rows the same revision created, the statement is dead, the
heal's own ``server_default`` already produces the same result, or the revision
itself records that leaving the rows alone is correct.

``gap`` says the rewrite does NOT reach an ordinary install and that this is
known. It is accepted, and every one is printed on every run with a count in the
summary. That list is the point: the failure this whole script exists for is a
gap nobody knew about, and a gap that is written down in the file and counted in
CI is a different thing from one that is not.

What it does not cover
----------------------
Statements the sister script cannot resolve to a table at all. Those are its
business, they have their own baseline there, and a second opinion from here
would only be a second way to be wrong about the same nine statements.

Exit codes: 0 clean, 1 a flagged revision has no valid declaration (or the scan
itself looks too small to trust).
"""

from __future__ import annotations

import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))

from check_migration_data_rewrites import (  # noqa: E402 - path set above
    _MIN_EXPECTED_REVISIONS,
    VERSIONS_DIR,
    scan_file,
)

REGISTRY_CORE_FILE = REPO_ROOT / "backend" / "app" / "core" / "data_repairs.py"
REGISTRY_FUNC = "register_data_repair"

# Where registrations live: one ``repairs.py`` per owning module. Scanned as
# source text, so a module that fails to import at runtime still shows up here.
APP_DIR = REPO_ROOT / "backend" / "app"

# A registry that comes back empty makes every ``registry=`` declaration below
# look unresolvable, which would fail the gate for the wrong reason and send
# the reader hunting through revisions. Refuse outright instead, naming the
# real cause.
_MIN_EXPECTED_REGISTRATIONS = 1

# A scan that comes back with almost nothing flagged reports "clean" for the
# same reason a passing suite with zero tests does. The floor is set well under
# whatever the tree currently flags, so ordinary churn does not trip it, and
# well above zero, so a broken scan cannot pass. Deliberately no count of
# today's tree here: that number moved twice while this file was being written
# and a stale one reads as authoritative later. Run the gate for the live count.
_MIN_EXPECTED_FLAGGED = 10

# Long enough that "n/a" cannot satisfy it, short enough that a real one-line
# reason fits. Measured against the reasons written for the tree today: the
# shortest is 74 characters.
_MIN_REASON_CHARS = 30

_PLACEHOLDER_RE = re.compile(r"^(todo|tbd|n/?a|none|unknown|see above|fixme)\b", re.IGNORECASE)

_DECL_RE = re.compile(r"#\s*boot-repair:\s*(.+?)\s*$")
_REF_RE = re.compile(r"^(registry|boot-path)=(\S+)$")
_REASON_RE = re.compile(r"^(none|gap)\s+-\s+(.+)$")


@dataclass(frozen=True)
class Declaration:
    """One parsed ``# boot-repair:`` comment."""

    lineno: int
    kind: str  # registry | boot-path | none | gap
    value: str  # the repair id, the path::symbol, or the reason text


def _registrations() -> dict[str, str | None]:
    """Map every literal ``repair_id`` to the revision its registration names.

    Scans every ``app/**/repairs.py`` rather than one central list, because
    there is no central list any more: modules register their own repairs so
    that two authors working at once cannot overwrite each other in a shared
    file. The gate follows the code.

    Parsed with ``ast`` rather than imported: importing a repairs module pulls
    in SQLAlchemy and ``app.database``, which builds an engine from the
    environment, so this gate would then need a configured database to answer a
    question about source text. ``tests/unit/test_data_repair_registry.py``
    asserts this reading and the live registry agree after discovery, so the
    shortcut cannot drift away from the thing it is reading.

    Only literal ids count. An id built at runtime would be invisible here and
    the gate would report a revision as undeclared, which is the safe direction
    to be wrong in: it fails loudly rather than passing blindly.

    The mapped value distinguishes three cases the caller has to treat
    differently. A non-empty string is a revision the registration claims, and
    it is checkable. An empty string is a repair with no revision behind it,
    which :class:`app.core.data_repairs.DataRepair` documents as a legal value,
    so it is not a defect. ``None`` means the revision was not a literal and
    this reading cannot see it, which is not a defect either: an unreadable
    declaration must not be reported as a broken one.
    """
    found: dict[str, str | None] = {}
    for path in sorted(APP_DIR.rglob("repairs.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except SyntaxError:
            # A repairs.py that does not parse registers nothing at runtime
            # either. Left to the syntax gate rather than swallowed here.
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != REGISTRY_FUNC:
                continue
            for inner in ast.walk(node):
                if not isinstance(inner, ast.Call):
                    continue
                kwargs = {kw.arg: kw.value for kw in inner.keywords}
                rid = kwargs.get("repair_id")
                if not (isinstance(rid, ast.Constant) and isinstance(rid.value, str)):
                    continue
                rev = kwargs.get("revision")
                found[rid.value] = rev.value if isinstance(rev, ast.Constant) and isinstance(rev.value, str) else None
    return found


def registry_ids() -> set[str]:
    """The registered repair ids alone, for resolving ``registry=`` declarations."""
    return set(_registrations())


def _module_level_symbols(path: Path) -> set[str]:
    """Top-level function, class and assignment names defined in ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
        elif isinstance(node, ast.Assign):
            names.update(t.id for t in node.targets if isinstance(t, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def parse_declarations(source: str) -> list[Declaration]:
    """Every ``# boot-repair:`` comment in one revision file, parsed loosely.

    Anything that matches the comment prefix is returned, well-formed or not, so
    :func:`validate` can complain about a typo instead of the file reading as
    though it carried no declaration at all - which would produce the same
    message as forgetting one, and send the author looking in the wrong place.
    """
    found: list[Declaration] = []
    for lineno, line in enumerate(source.splitlines(), start=1):
        m = _DECL_RE.search(line)
        if not m:
            continue
        body = m.group(1)
        ref = _REF_RE.match(body)
        if ref:
            found.append(Declaration(lineno, ref.group(1), ref.group(2)))
            continue
        reason = _REASON_RE.match(body)
        if reason:
            found.append(Declaration(lineno, reason.group(1), reason.group(2)))
            continue
        found.append(Declaration(lineno, "malformed", body))
    return found


def validate(decl: Declaration, known_ids: set[str]) -> str | None:
    """Return a problem with one declaration, or None when it is sound."""
    if decl.kind == "malformed":
        return (
            f"line {decl.lineno}: not one of the four forms - "
            f"registry=<id> | boot-path=<path>::<symbol> | none - <reason> | gap - <reason>"
        )

    if decl.kind == "registry":
        if decl.value not in known_ids:
            return (
                f"line {decl.lineno}: repair id {decl.value!r} is registered by no "
                f"{REGISTRY_FUNC}() call in any app/**/repairs.py"
            )
        return None

    if decl.kind == "boot-path":
        if "::" not in decl.value:
            return f"line {decl.lineno}: expected <path>::<symbol>, got {decl.value!r}"
        rel, symbol = decl.value.split("::", 1)
        target = REPO_ROOT / rel
        if not target.is_file():
            return f"line {decl.lineno}: {rel} does not exist"
        try:
            symbols = _module_level_symbols(target)
        except SyntaxError as exc:
            return f"line {decl.lineno}: {rel} does not parse ({exc})"
        if symbol not in symbols:
            return f"line {decl.lineno}: {rel} defines no top-level {symbol!r}"
        return None

    # none / gap - the value is prose, and the only thing that can be checked
    # about prose is that somebody wrote some.
    reason = decl.value.strip()
    if _PLACEHOLDER_RE.match(reason):
        return f"line {decl.lineno}: {decl.kind!r} needs a reason, not a placeholder ({reason!r})"
    if len(reason) < _MIN_REASON_CHARS:
        return f"line {decl.lineno}: {decl.kind!r} reason is {len(reason)} chars, needs {_MIN_REASON_CHARS}"
    return None


def main(argv: list[str]) -> int:  # noqa: ARG001 - argv taken for symmetry with the sister script
    if not VERSIONS_DIR.is_dir():
        print(f"[FAIL] versions directory not found: {VERSIONS_DIR}")
        return 1

    paths = sorted(VERSIONS_DIR.glob("*.py"))
    if len(paths) < _MIN_EXPECTED_REVISIONS:
        print(
            f"[FAIL] only {len(paths)} revision(s) under {VERSIONS_DIR}, expected at least "
            f"{_MIN_EXPECTED_REVISIONS}. A clean summary over this few files would be a false "
            "clean, so this fails instead of reporting one."
        )
        return 1

    registrations = _registrations()
    known_ids = set(registrations)
    if len(known_ids) < _MIN_EXPECTED_REGISTRATIONS:
        print(
            f"[FAIL] found {len(known_ids)} {REGISTRY_FUNC}() call(s) with a literal repair_id "
            f"across {APP_DIR.relative_to(REPO_ROOT).as_posix()}/**/repairs.py. Either nothing "
            "registers a repair any more, or this script is no longer reading the registrations - "
            "and a registry that cannot be read would silently reject every registry= declaration "
            f"below. {REGISTRY_CORE_FILE.relative_to(REPO_ROOT).as_posix()} defines the function."
        )
        return 1

    # The direction this gate was blind in. Everything below resolves a
    # revision's ``registry=`` declaration against the registrations. Nothing
    # asked the reverse: does the revision a registration NAMES exist. That
    # blindness is not hypothetical - a registration naming a revision that was
    # not on the tree sat on main and no gate said a word, because every check
    # ran the other way, and the runner never looks at the migration tree at
    # all. Nothing downstream would ever have noticed.
    #
    # An empty revision is not a defect and is not failed here. DataRepair
    # documents the field as the revision "or '' when the repair has no
    # revision behind it", so failing it would be this gate contradicting the
    # contract it exists to guard. Same for a revision this reading cannot see:
    # unreadable is not broken.
    #
    # No floor of its own. _MIN_EXPECTED_REGISTRATIONS above already refuses an
    # unreadable registry, so by the time this runs the registrations are known
    # to have been read, and that is what stops a clean here meaning nothing.
    stems = {path.stem for path in paths}
    dangling: list[tuple[str, str]] = []
    no_revision = 0
    unreadable = 0
    for repair_id, revision in sorted(registrations.items()):
        if revision is None:
            unreadable += 1
        elif not revision:
            no_revision += 1
        elif revision not in stems:
            dangling.append((repair_id, revision))

    flagged = 0
    missing: list[tuple[str, str]] = []
    problems: list[tuple[str, list[str]]] = []
    by_kind: dict[str, int] = {"registry": 0, "boot-path": 0, "none": 0, "gap": 0}
    gaps: list[tuple[str, str]] = []

    for path in paths:
        try:
            findings, _unresolved, source = scan_file(path)
        except SyntaxError:
            # The sister script owns parse errors and fails on them; reporting
            # the same file twice from two gates only doubles the noise.
            continue
        if not findings:
            continue
        flagged += 1

        decls = parse_declarations(source)
        if not decls:
            tables = ", ".join(sorted({f.table for f in findings}))
            missing.append((path.name, tables))
            continue

        bad = [problem for d in decls if (problem := validate(d, known_ids))]
        if bad:
            problems.append((path.name, bad))
            continue

        for d in decls:
            by_kind[d.kind] += 1
            if d.kind == "gap":
                gaps.append((path.name, d.value))

    if flagged < _MIN_EXPECTED_FLAGGED:
        print(
            f"[FAIL] only {flagged} revision(s) came back flagged, expected at least "
            f"{_MIN_EXPECTED_FLAGGED}. The scan this gate reads from is not seeing what it used "
            "to, and a clean result over an empty scan means nothing."
        )
        return 1

    if gaps:
        print(f"Data rewrites that do NOT reach an ordinary install ({len(gaps)} declared):")
        for name, reason in gaps:
            print(f"  {name}")
            print(f"      {reason}")
        print()

    print(
        f"SUMMARY: {len(paths)} revisions scanned, {flagged} rewrite pre-existing rows; "
        f"declarations: {by_kind['registry']} registry, {by_kind['boot-path']} boot-path, "
        f"{by_kind['none']} not needed, {by_kind['gap']} gap"
    )

    resolved = len(registrations) - no_revision - unreadable - len(dangling)
    print(
        f"REGISTRATIONS: {len(registrations)} registered; {resolved} name a revision that "
        f"exists, {no_revision} name none, {unreadable} not statically readable, "
        f"{len(dangling)} name a revision that is absent"
    )

    if dangling:
        print()
        print("Registrations naming a revision that is not in backend/alembic/versions:")
        for repair_id, revision in dangling:
            print(f"  {repair_id}  names {revision!r}")
        print()
        print(
            "The registration is the only place that revision is written down, and "
            "nothing reads it back: the runner does not consult the migration tree, "
            "by design. So an absent revision is caught by nothing downstream. It "
            "sits there claiming a schema half that never arrived, on a tree where "
            "everything else still passes. Either the revision file did not make it "
            "into the commit, or the registration names the wrong one."
        )

    if missing or problems:
        print()
        if missing:
            print("Revisions that rewrite pre-existing rows and do not say whether it reaches an install:")
            for name, tables in missing:
                print(f"  {name}  (rewrites {tables})")
        for name, bad in problems:
            print(f"  {name}")
            for problem in bad:
                print(f"      {problem}")
        print()
        print(
            "Add one line to the revision, next to its data-rewrite-ack:\n"
            "  # boot-repair: registry=<repair_id>            # runs from app/core/data_repairs.py\n"
            "  # boot-repair: boot-path=<path>::<symbol>      # runs from existing boot-path code\n"
            "  # boot-repair: none - <why none is needed>     # the rewrite has nothing to reach\n"
            "  # boot-repair: gap - <what does not land>      # it does not reach ordinary installs\n"
            "\n"
            "The product never runs `alembic upgrade`, so a revision body executes only where an\n"
            "operator runs it by hand. This is where that gets said out loud instead of being\n"
            "rediscovered from a customer's data."
        )

    # One exit for both directions. A tree with a dangling registration and a
    # missing declaration has two separate things wrong with it and the reader
    # needs both printed, so neither branch returns on its own.
    if missing or problems or dangling:
        return 1

    print(
        "Blocking: every revision that rewrites pre-existing rows declares where that "
        "lands, and every registration names a revision that exists."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
