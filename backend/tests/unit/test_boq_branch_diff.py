# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure rules of estimate branches: identity, compare, three-way plan, drift.

Everything here runs on plain rows, no database: what a cherry-pick or a merge
writes is decided by :mod:`app.modules.boq.branch_diff` alone.
"""

from __future__ import annotations

from decimal import Decimal

from app.modules.boq.branch_diff import (
    LINEAGE_KEY,
    changed_fields,
    compare_lines,
    cost_group_of,
    divergence,
    lineage_of,
    lines_from_snapshot,
    plan_apply,
)


def _row(pid: str, ordinal: str, desc: str, qty: str, rate: str, *, lineage: str | None = None, **extra):
    meta = {LINEAGE_KEY: lineage} if lineage else {}
    total = str(Decimal(qty) * Decimal(rate))
    row = {
        "id": pid,
        "ordinal": ordinal,
        "description": desc,
        "unit": extra.pop("unit", "m3"),
        "quantity": qty,
        "unit_rate": rate,
        "total": total,
        "metadata": meta,
    }
    row.update(extra)
    return row


def _section(pid: str, ordinal: str, desc: str, *, lineage: str | None = None):
    return {
        "id": pid,
        "ordinal": ordinal,
        "description": desc,
        "unit": "",
        "quantity": "0",
        "unit_rate": "0",
        "total": "0",
        "metadata": {LINEAGE_KEY: lineage} if lineage else {},
    }


def _lines(*rows):
    return lines_from_snapshot({"positions": list(rows)})


# ── Identity ────────────────────────────────────────────────────────────────


def test_lineage_prefers_the_stored_key_and_falls_back_to_the_id() -> None:
    assert lineage_of({LINEAGE_KEY: "L1"}, "id-9") == "L1"
    assert lineage_of({}, "id-9") == "id-9"
    assert lineage_of({LINEAGE_KEY: "  "}, "id-9") == "id-9"
    assert lineage_of(None, None) == ""


def test_copies_in_another_bill_pair_with_their_origin_by_lineage() -> None:
    main = _lines(_row("m1", "1.1", "Excavation", "100", "10"))
    branch = _lines(_row("b1", "1.1", "Excavation", "120", "10", lineage="m1"))
    assert set(main) == set(branch) == {"m1"}
    assert changed_fields(main["m1"], branch["m1"]) == ["quantity"]


def test_a_duplicated_key_inside_one_bill_does_not_merge_two_lines() -> None:
    lines = _lines(
        _row("a", "1.1", "Wall", "1", "1", lineage="L"),
        _row("b", "1.2", "Wall copy", "1", "1", lineage="L"),
    )
    assert set(lines) == {"L", "id:b"}


def test_parent_links_are_expressed_as_keys() -> None:
    lines = _lines(
        _section("s", "1", "Earthworks", lineage="S"),
        _row("p", "1.1", "Dig", "1", "1", lineage="P", parent_id="s"),
    )
    assert lines["P"].parent_key == "S"
    assert lines["S"].is_section


# ── Compare ─────────────────────────────────────────────────────────────────


def test_compare_classifies_added_removed_changed_and_text() -> None:
    a = _lines(
        _section("s", "1", "Concrete", lineage="S"),
        _row("p1", "1.1", "Slab C30/37", "50", "120", lineage="P1", parent_id="s", classification={"din276": "330"}),
        _row("p2", "1.2", "Walls", "20", "200", lineage="P2", parent_id="s"),
        _row("p3", "1.3", "Columns", "5", "300", lineage="P3", parent_id="s"),
    )
    b = _lines(
        _section("s", "1", "Concrete", lineage="S"),
        _row("q1", "1.1", "Slab precast", "50", "110", lineage="P1", parent_id="s", classification={"din276": "330"}),
        _row("q2", "1.2", "Walls", "20", "200", lineage="P2", parent_id="s"),
        _row("q4", "1.4", "Precast beams", "10", "90", lineage="N", parent_id="s"),
    )
    result = compare_lines(a, b, standard="din276")
    by_key = {r["key"]: r for r in result["rows"]}
    assert "S" not in by_key, "section headers carry no money and are not rows"
    assert by_key["P1"]["change_type"] == "changed"
    assert by_key["P1"]["changed_fields"] == ["description", "unit_rate"]
    assert by_key["P1"]["a_description"] == "Slab C30/37"
    assert by_key["P2"]["change_type"] == "unchanged"
    assert by_key["P3"]["change_type"] == "removed"
    assert by_key["N"]["change_type"] == "added"
    summary = result["summary"]
    assert (summary["added"], summary["removed"], summary["changed"], summary["unchanged"]) == (1, 1, 1, 1)
    assert Decimal(summary["total_a"]) == Decimal("6000") + Decimal("4000") + Decimal("1500")
    assert Decimal(summary["total_b"]) == Decimal("5500") + Decimal("4000") + Decimal("900")
    assert Decimal(summary["delta"]) == Decimal(summary["total_b"]) - Decimal(summary["total_a"])
    sections = {g["key"]: g for g in result["by_section"]}
    assert Decimal(sections["S"]["delta"]) == Decimal(summary["delta"])
    assert sections["S"]["label"] == "1 Concrete"
    groups = {g["key"]: g for g in result["by_cost_group"]}
    assert Decimal(groups["din276:330"]["delta"]) == Decimal("-500")


def test_cost_group_uses_the_project_standard_first() -> None:
    line = _lines(_row("p", "1", "x", "1", "1", classification={"nrm": "2.6.1", "din276": "330"}))["p"]
    assert cost_group_of(line, "din276") == "din276:330"
    assert cost_group_of(line, None) == "din276:330"
    assert cost_group_of(line, "masterformat") == "din276:330"
    bare = _lines(_row("q", "1", "x", "1", "1"))["q"]
    assert cost_group_of(bare, "din276") == ""


# ── Three-way plan ─────────────────────────────────────────────────────────


def _base():
    return _lines(
        _row("m1", "1.1", "Excavation", "100", "10", lineage="m1"),
        _row("m2", "1.2", "Backfill", "40", "8", lineage="m2"),
        _row("m3", "1.3", "Disposal", "60", "12", lineage="m3"),
    )


def test_plan_carries_only_what_the_source_changed() -> None:
    base = _base()
    source = _lines(
        _row("b1", "1.1", "Excavation", "120", "10", lineage="m1"),
        _row("b2", "1.2", "Backfill", "40", "8", lineage="m2"),
        _row("b4", "1.4", "Shoring", "10", "50", lineage="new"),
    )
    target = _base()
    plan = {i["key"]: i for i in plan_apply(base, source, target)}
    assert set(plan) == {"m1", "m3", "new"}
    assert plan["m1"]["action"] == "update"
    assert plan["m3"]["action"] == "remove"
    assert plan["new"]["action"] == "add"
    assert not any(i["conflict"] for i in plan.values())
    assert plan["m1"]["fields"]["quantity"] == {"base": "100", "source": "120", "target": "100"}


def test_plan_flags_a_line_both_sides_changed_differently() -> None:
    base = _base()
    source = _lines(_row("b1", "1.1", "Excavation", "120", "10", lineage="m1"), *_base_rows_except("m1"))
    target = _lines(_row("t1", "1.1", "Excavation", "100", "11", lineage="m1"), *_base_rows_except("m1"))
    plan = plan_apply(base, source, target)
    assert len(plan) == 1
    assert plan[0]["conflict"] is True
    assert plan[0]["fields"]["unit_rate"] == {"base": "10", "source": "10", "target": "11"}


def test_plan_skips_a_line_the_target_already_holds() -> None:
    base = _base()
    changed = _row("x", "1.1", "Excavation", "120", "10", lineage="m1")
    source = _lines(changed, *_base_rows_except("m1"))
    target = _lines({**changed, "id": "y"}, *_base_rows_except("m1"))
    assert plan_apply(base, source, target) == []


def test_plan_restricted_to_chosen_keys_is_a_cherry_pick() -> None:
    base = _base()
    source = _lines(
        _row("b1", "1.1", "Excavation", "120", "10", lineage="m1"),
        _row("b2", "1.2", "Backfill", "45", "8", lineage="m2"),
        _row("b3", "1.3", "Disposal", "60", "12", lineage="m3"),
    )
    plan = plan_apply(base, source, _base(), keys=["m2"])
    assert [i["key"] for i in plan] == ["m2"]


def test_without_a_common_ancestor_nothing_is_a_conflict() -> None:
    source = _lines(_row("b1", "1.1", "Excavation", "120", "10", lineage="m1"))
    target = _lines(_row("t1", "1.1", "Excavation", "100", "11", lineage="m1"))
    plan = plan_apply(None, source, target)
    assert len(plan) == 1 and plan[0]["conflict"] is False


def test_children_come_after_their_parents_by_depth() -> None:
    base = _lines()
    source = _lines(
        _section("s", "2", "New section", lineage="S"),
        _row("c", "2.1", "Child", "1", "1", lineage="C", parent_id="s"),
    )
    plan = {i["key"]: i for i in plan_apply(base, source, _lines())}
    assert plan["S"]["depth"] == 0 and plan["C"]["depth"] == 1


def _base_rows_except(key: str):
    rows = {
        "m1": _row("m1", "1.1", "Excavation", "100", "10", lineage="m1"),
        "m2": _row("m2", "1.2", "Backfill", "40", "8", lineage="m2"),
        "m3": _row("m3", "1.3", "Disposal", "60", "12", lineage="m3"),
    }
    return [r for k, r in rows.items() if k != key]


# ── Drift ───────────────────────────────────────────────────────────────────


def test_divergence_counts_main_changes_and_conflicts() -> None:
    base = _base()
    branch = _lines(_row("b1", "1.1", "Excavation", "120", "10", lineage="m1"), *_base_rows_except("m1"))
    main = _lines(
        _row("m1", "1.1", "Excavation", "100", "11", lineage="m1"),
        _row("m2", "1.2", "Backfill", "50", "8", lineage="m2"),
        _row("m3", "1.3", "Disposal", "60", "12", lineage="m3"),
    )
    drift = divergence(base, branch, main)
    assert drift["base_known"] is True
    assert drift["main_changes"] == 2
    assert [c["key"] for c in drift["conflicts"]] == ["m1"]


def test_divergence_after_carrying_main_over_is_zero() -> None:
    base = _base()
    main = _lines(_row("m1", "1.1", "Excavation", "100", "11", lineage="m1"), *_base_rows_except("m1"))
    branch = _lines(_row("b1", "1.1", "Excavation", "100", "11", lineage="m1"), *_base_rows_except("m1"))
    assert divergence(base, branch, main)["main_changes"] == 0


def test_divergence_without_ancestor_claims_nothing() -> None:
    assert divergence(None, _base(), _base()) == {"base_known": False, "main_changes": 0, "conflicts": []}
