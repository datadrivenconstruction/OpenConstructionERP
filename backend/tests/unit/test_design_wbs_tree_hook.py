# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠WBS rules on writes made outside the design module: the pure tree check and the core hook.

The copy, restore and projects-router paths against a database are in
``tests/pg/test_design_wbs_paths_on_pg.py``.
"""

from __future__ import annotations

import ast
import asyncio
import uuid
from pathlib import Path

import pytest
from fastapi import HTTPException

from app.core import wbs_rules
from app.modules.design_management import wbs as wr

_PROJECTS = Path(__file__).resolve().parents[2] / "app" / "modules" / "projects"


def _n(code: str, parent: wr.Node | None = None, closed: bool = False) -> wr.Node:
    return wr.Node(uuid.uuid4(), parent.id if parent else None, code, closed)


def test_a_clean_tree_has_no_errors() -> None:
    root = _n("1")
    assert wr.tree_errors([root, _n("1.1", root), _n("1.2", root)]) == []


def test_duplicate_codes_are_found_case_insensitively_one_entry_per_node() -> None:
    a, b = _n("A1"), _n("a1")
    errors = wr.tree_errors([a, b], hierarchical=False)
    assert [e["code"] for e in errors] == ["wbs_code_duplicate", "wbs_code_duplicate"]
    assert {e["node_id"] for e in errors} == {str(a.id), str(b.id)}


def test_only_violations_a_write_adds_are_new() -> None:
    """Decision 2: legacy duplicates are listed, never used to refuse an unrelated write."""
    a, b = _n("1"), _n("1")
    before = wr.tree_errors([a, b], hierarchical=False)
    unrelated = _n("2")
    assert wr.new_errors(before, wr.tree_errors([a, b, unrelated], hierarchical=False)) == []
    third = _n("1")
    added = wr.new_errors(before, wr.tree_errors([a, b, third], hierarchical=False))
    assert [(e["code"], e["node_id"]) for e in added] == [("wbs_code_duplicate", str(third.id))]


def test_moving_a_broken_node_onto_another_broken_value_is_new() -> None:
    a, b, c, d = _n("1"), _n("1"), _n("2"), _n("2")
    before = wr.tree_errors([a, b, c, d], hierarchical=False)
    moved = wr.Node(a.id, None, "2")
    added = wr.new_errors(before, wr.tree_errors([moved, b, c, d], hierarchical=False))
    assert [(e["node_id"], e["value"]) for e in added] == [(str(a.id), "2")]


def test_renaming_a_parent_away_from_its_children_is_a_new_violation_on_the_children() -> None:
    root = _n("1")
    child = _n("1.1", root)
    before = wr.tree_errors([root, child])
    renamed = wr.Node(root.id, None, "3")
    added = wr.new_errors(before, wr.tree_errors([renamed, child]))
    assert [(e["code"], e["node_id"]) for e in added] == [("wbs_code_not_under_parent", str(child.id))]


def test_a_child_outside_its_parent_prefix_fails_only_when_hierarchical() -> None:
    root = _n("1")
    nodes = [root, _n("2.1", root)]
    assert [e["code"] for e in wr.tree_errors(nodes, hierarchical=True)] == ["wbs_code_not_under_parent"]
    assert wr.tree_errors(nodes, hierarchical=False) == []
    assert wr.tree_errors([root, _n("1/1", root)], hierarchical=True, separator="/") == []


def test_an_open_child_under_a_closed_node_fails_and_a_closed_subtree_passes() -> None:
    root = _n("1", closed=True)
    assert [e["code"] for e in wr.tree_errors([root, _n("1.1", root)])] == ["wbs_node_closed"]
    assert wr.tree_errors([root, _n("1.1", root, closed=True)]) == []


def test_an_empty_code_fails() -> None:
    assert [e["code"] for e in wr.tree_errors([_n(" ")])] == ["wbs_code_required"]


def _with_checker(found: list[list[dict]]):
    """A checker that returns the next list on every call; restores the registry afterwards."""
    calls = iter(found)

    async def checker(session, project_id):
        return next(calls)

    return checker


def _run_hook(before: list[dict], after: list[dict]) -> HTTPException | None:
    saved = dict(wbs_rules._CHECKERS)
    wbs_rules._CHECKERS.clear()
    wbs_rules.register_wbs_checker("t", _with_checker([before, after]))
    try:
        pid = uuid.uuid4()
        taken = asyncio.run(wbs_rules.wbs_violations(None, pid))
        try:
            asyncio.run(wbs_rules.check_wbs_tree(None, pid, before=taken))
        except HTTPException as exc:
            return exc
        return None
    finally:
        wbs_rules._CHECKERS.clear()
        wbs_rules._CHECKERS.update(saved)


def test_the_hook_passes_when_the_write_added_nothing_even_on_a_broken_tree() -> None:
    legacy = [{"code": "wbs_code_duplicate", "node_id": "a", "value": "1"}]
    assert _run_hook(legacy, list(legacy)) is None


def test_the_hook_refuses_only_what_the_write_added() -> None:
    legacy = {"code": "wbs_code_duplicate", "node_id": "a", "value": "1"}
    added = {"code": "wbs_node_closed", "node_id": "b", "value": "2"}
    exc = _run_hook([legacy], [legacy, added])
    assert exc is not None and exc.status_code == 422
    assert exc.detail["code"] == "wbs_invalid"
    assert exc.detail["violations"] == [added]


def test_the_hook_is_a_no_op_without_checkers() -> None:
    saved = dict(wbs_rules._CHECKERS)
    wbs_rules._CHECKERS.clear()
    try:
        asyncio.run(wbs_rules.check_wbs_tree(None, uuid.uuid4(), before=[]))
    finally:
        wbs_rules._CHECKERS.update(saved)


def test_design_startup_registers_the_wbs_checker() -> None:
    from app.modules.design_management import on_startup

    asyncio.run(on_startup())
    assert "design_management.wbs" in wbs_rules._CHECKERS


def _awaited(file: str, function: str) -> list[str]:
    tree = ast.parse((_PROJECTS / file).read_text(encoding="utf-8"))
    fn = next(n for n in ast.walk(tree) if isinstance(n, ast.AsyncFunctionDef) and n.name == function)
    return [
        n.value.func.id
        for n in sorted((x for x in ast.walk(fn) if isinstance(x, ast.Await)), key=lambda x: (x.lineno, x.col_offset))
        if isinstance(n.value, ast.Call) and isinstance(n.value.func, ast.Name)
    ]


@pytest.mark.parametrize("function", ["create_wbs_node", "update_wbs_node"])
def test_the_projects_router_takes_the_snapshot_before_it_checks(function: str) -> None:
    called = _awaited("router.py", function)
    assert "wbs_violations" in called and "check_wbs_tree" in called, function
    assert called.index("wbs_violations") < called.index("check_wbs_tree"), function


@pytest.mark.parametrize("function", ["duplicate_project", "restore_project_from_backup"])
def test_copy_and_restore_reproduce_a_tree_and_are_not_checked(function: str) -> None:
    assert "check_wbs_tree" not in _awaited("service.py", function)
