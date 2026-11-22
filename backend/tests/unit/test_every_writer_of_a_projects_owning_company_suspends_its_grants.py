# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Every writer of a project's owning company has to suspend the grants on it.

ADR 006, owner decision 4: when a project changes hands its grants are suspended
pending review. The decision is easy to state and easy to lose, because today
nothing in the product moves a project between companies - so there is no route
to hang the behaviour on, no test that would exercise it through an endpoint, and
nothing that would fail when somebody adds the transfer feature and forgets.

This file is the thing that fails. It reads the source rather than the runtime,
which is the only way to guard a code path that does not exist yet:

* every place in ``app/`` that assigns ``organization_id`` on an existing object,
  and every ``UPDATE`` that sets that column on the project table, has to be in a
  file that also calls ``suspend_grants_on_ownership_change`` - or be named in
  :data:`_EXEMPT` with the reason it is exempt;
* the one exempt file today is ``app.modules.users.repairs``, whose update is
  guarded on ``organization_id IS NULL``. That guard is what makes it a backfill
  rather than a transfer, so it is asserted too: a repair that started replacing
  one company with another would stop being exempt, and this test would say so
  before the grants it should have suspended were forgotten.

Constructing a ``Project`` with an ``organization_id`` is not in scope and that is
deliberate: a project being created has no grants to suspend, and counting
constructor keyword arguments as ownership changes would put every creation path
in the census and bury the one case that matters.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
APP = BACKEND / "app"
PROJECT_TABLE = "oe_projects_project"
SUSPEND_CALL = "suspend_grants_on_ownership_change"

#: Files that write a project's owning company and do not have to suspend grants,
#: each with the reason it is exempt. An entry here is a claim about the file, and
#: the test below checks the claim rather than trusting it.
_EXEMPT = {
    "app/modules/users/repairs.py": (
        "The boot backfill fills an owning company where there is none: its UPDATE is guarded on "
        "`organization_id IS NULL`, so it can never move a project from one company to another, and a "
        "project with no owning company has no grants (creating one needs an owner to create it). "
        "Asserted below by _REPAIR_ONLY_FILLS_A_GAP."
    ),
}

#: The guard that makes the repair a backfill rather than a transfer.
_REPAIR_ONLY_FILLS_A_GAP = re.compile(r"organization_id\s+IS\s+NULL", re.IGNORECASE)

#: ``UPDATE ... SET ... organization_id``, allowing the SET list to span lines. Raw
#: SQL is in scope because that is how the one writer that exists today writes,
#: and a transfer implemented the same way would be invisible to an AST scan.
#:
#: The pattern matches any table and is then filtered on the text of the statement
#: it matched, because the table name in the source is not the table name in the
#: database: the repair writes ``UPDATE {_PROJECT_TABLE}`` inside an f-string, so
#: a pattern looking for ``oe_projects_project`` finds nothing and passes for the
#: wrong reason. Accepting a placeholder whose name mentions the table, alongside
#: the literal name, covers both spellings without sweeping in every other table
#: that happens to have an ``organization_id`` column.
_SQL_UPDATE = re.compile(
    r"UPDATE\s+\S+?(?P<body>.{0,400}?)\bSET\b(?P<setlist>.{0,400}?)\borganization_id\s*=",
    re.IGNORECASE | re.DOTALL,
)
#: A matched statement counts when it names the project table, literally or as an
#: f-string placeholder.
_NAMES_THE_PROJECT_TABLE = re.compile(rf"{re.escape(PROJECT_TABLE)}|\{{\w*PROJECT_TABLE\w*\}}", re.IGNORECASE)


def _python_files() -> list[Path]:
    return sorted(path for path in APP.rglob("*.py") if path.is_file())


def _attribute_writes(tree: ast.AST) -> list[int]:
    """Line numbers of ``something.organization_id = ...`` assignments."""
    lines: list[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        for target in targets:
            if isinstance(target, ast.Attribute) and target.attr == "organization_id":
                lines.append(node.lineno)
    return lines


def _sql_writes(source: str) -> list[int]:
    """Line numbers of raw SQL that sets the project table's ``organization_id``."""
    lines: list[int] = []
    for match in _SQL_UPDATE.finditer(source):
        if not _NAMES_THE_PROJECT_TABLE.search(match.group(0)):
            continue
        lines.append(source.count("\n", 0, match.start()) + 1)
    return lines


def _calls_suspension(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func
            if isinstance(name, ast.Attribute) and name.attr == SUSPEND_CALL:
                return True
            if isinstance(name, ast.Name) and name.id == SUSPEND_CALL:
                return True
    return False


def _writers() -> dict[str, list[int]]:
    """Every file under ``app/`` that changes a project's owning company, with line numbers."""
    found: dict[str, list[int]] = {}
    for path in _python_files():
        source = path.read_text(encoding="utf-8")
        try:
            tree = ast.parse(source)
        except SyntaxError:  # pragma: no cover - a file that does not parse is another test's problem
            continue
        lines = _attribute_writes(tree) + _sql_writes(source)
        if lines:
            found[str(path.relative_to(BACKEND)).replace("\\", "/")] = sorted(lines)
    return found


def test_the_census_found_the_writers_it_was_written_for():
    """The scan is not vacuous.

    A guard that finds nothing passes for the wrong reason, and this one would
    keep passing after a refactor renamed the column it looks for. The repair is
    the writer that is known to exist, so it is asserted to be in the census -
    which also means the census has found at least one real site.
    """
    writers = _writers()
    assert "app/modules/users/repairs.py" in writers, writers


def test_every_writer_of_a_projects_owning_company_suspends_its_grants():
    writers = _writers()
    unguarded: list[str] = []
    for relative, lines in sorted(writers.items()):
        if relative in _EXEMPT:
            continue
        tree = ast.parse((BACKEND / relative).read_text(encoding="utf-8"))
        if not _calls_suspension(tree):
            unguarded.append(f"{relative}:{lines}")
    assert not unguarded, (
        "These files change a project's owning company without suspending its participant grants "
        f"(ADR 006 owner decision 4): {unguarded}. Call "
        f"`app.modules.projects.grants.{SUSPEND_CALL}` from the path that makes the change, or add the file to "
        "_EXEMPT in this test with the reason it does not have to."
    )


def test_the_exempt_writers_are_named_and_their_exemption_is_still_true():
    """An exemption is a claim, and the claim is checked.

    The repair is exempt because it fills a gap rather than moving a project
    between companies. If that stopped being true - the ``IS NULL`` guard removed,
    or the update rewritten to replace one company with another - the exemption
    would be hiding exactly the case this file exists to catch.
    """
    repair = (BACKEND / "app/modules/users/repairs.py").read_text(encoding="utf-8")
    assert _REPAIR_ONLY_FILLS_A_GAP.search(repair), (
        "app/modules/users/repairs.py no longer guards its organization_id UPDATE with `IS NULL`, so it can move a "
        "project from one company to another and is no longer exempt. Remove it from _EXEMPT here and call "
        f"`{SUSPEND_CALL}` from it."
    )
    # Every exempt file still has to be a writer, or the exemption is dead weight
    # that silently stops covering anything.
    writers = _writers()
    stale = sorted(set(_EXEMPT) - set(writers))
    assert not stale, f"_EXEMPT names files that no longer write a project's owning company: {stale}"


def test_the_exemptions_carry_a_reason():
    assert all(reason.strip() for reason in _EXEMPT.values())


def test_the_suspension_function_is_where_the_writers_are_told_to_find_it():
    """The import path the guard names has to exist and keep that name.

    Renaming the function would leave every future writer with a message pointing
    at nothing, which is the same as having no guard.
    """
    from app.modules.projects import grants

    assert callable(getattr(grants, SUSPEND_CALL))
    assert SUSPEND_CALL in grants.__all__
