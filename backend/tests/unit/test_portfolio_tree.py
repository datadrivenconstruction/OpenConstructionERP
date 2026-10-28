# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Unit tests for the pure portfolio-tree pruning (T3.3, acceptance #1).

Pure (stdlib only) so they run on the local 3.11 runner without a DB.
"""

from __future__ import annotations

from app.modules.portfolio.tree_logic import build_visible_tree

# A small fixed tree:
#   root (portfolio)
#     ├─ progA (programme)   -> project P1
#     └─ progB (programme)   -> project P2
NODES = [
    {"id": "root", "parent_id": None, "node_type": "portfolio", "name": "Enterprise", "sort_order": 0},
    {"id": "progA", "parent_id": "root", "node_type": "programme", "name": "Alpha", "sort_order": 0},
    {"id": "progB", "parent_id": "root", "node_type": "programme", "name": "Bravo", "sort_order": 1},
]
MEMBERSHIPS = [
    {"node_id": "progA", "project_id": "P1"},
    {"node_id": "progB", "project_id": "P2"},
]


def _flatten(tree: list[dict]) -> set[str]:
    out: set[str] = set()
    for node in tree:
        out.add(node["id"])
        out |= _flatten(node["children"])
    return out


def test_admin_sees_every_node() -> None:
    tree = build_visible_tree(NODES, MEMBERSHIPS, None)
    assert _flatten(tree) == {"root", "progA", "progB"}
    # Nesting is preserved.
    assert tree[0]["id"] == "root"
    child_ids = {c["id"] for c in tree[0]["children"]}
    assert child_ids == {"progA", "progB"}


def test_non_admin_sees_only_nodes_with_accessible_projects() -> None:
    # Caller can reach only P1 -> Bravo (P2-only) must be absent, Alpha + root kept.
    tree = build_visible_tree(NODES, MEMBERSHIPS, {"P1"})
    assert _flatten(tree) == {"root", "progA"}
    root = tree[0]
    assert [c["id"] for c in root["children"]] == ["progA"]
    assert root["children"][0]["project_ids"] == ["P1"]


def test_node_with_only_inaccessible_projects_is_omitted_entirely() -> None:
    # No accessible projects at all -> the whole tree collapses to nothing,
    # so a user never even sees a node label for projects they cannot reach.
    tree = build_visible_tree(NODES, MEMBERSHIPS, set())
    assert tree == []


def test_project_ids_lists_only_accessible_memberships() -> None:
    # progA holds P1 and P3; caller can reach only P1.
    nodes = [{"id": "progA", "parent_id": None, "node_type": "programme", "name": "Alpha", "sort_order": 0}]
    memberships = [
        {"node_id": "progA", "project_id": "P1"},
        {"node_id": "progA", "project_id": "P3"},
    ]
    tree = build_visible_tree(nodes, memberships, {"P1"})
    assert tree[0]["project_ids"] == ["P1"]


def test_ancestor_of_accessible_leaf_is_kept() -> None:
    # Deep chain root>mid>leaf, only leaf holds an accessible project.
    nodes = [
        {"id": "root", "parent_id": None, "node_type": "portfolio", "name": "R", "sort_order": 0},
        {"id": "mid", "parent_id": "root", "node_type": "programme", "name": "M", "sort_order": 0},
        {"id": "leaf", "parent_id": "mid", "node_type": "subprogramme", "name": "L", "sort_order": 0},
    ]
    memberships = [{"node_id": "leaf", "project_id": "P9"}]
    tree = build_visible_tree(nodes, memberships, {"P9"})
    assert _flatten(tree) == {"root", "mid", "leaf"}


def test_orphan_node_with_dangling_parent_is_treated_as_root() -> None:
    # parent_id points at a node that no longer exists (SET NULL race / stale).
    nodes = [{"id": "x", "parent_id": "ghost", "node_type": "programme", "name": "X", "sort_order": 0}]
    memberships = [{"node_id": "x", "project_id": "P1"}]
    tree = build_visible_tree(nodes, memberships, {"P1"})
    assert [n["id"] for n in tree] == ["x"]
    assert tree[0]["parent_id"] is None


def test_children_sorted_by_sort_order_then_name() -> None:
    nodes = [
        {"id": "root", "parent_id": None, "node_type": "portfolio", "name": "R", "sort_order": 0},
        {"id": "b", "parent_id": "root", "node_type": "programme", "name": "Bbb", "sort_order": 0},
        {"id": "a", "parent_id": "root", "node_type": "programme", "name": "Aaa", "sort_order": 0},
        {"id": "c", "parent_id": "root", "node_type": "programme", "name": "Ccc", "sort_order": -1},
    ]
    tree = build_visible_tree(nodes, [], None)
    assert [c["id"] for c in tree[0]["children"]] == ["c", "a", "b"]
