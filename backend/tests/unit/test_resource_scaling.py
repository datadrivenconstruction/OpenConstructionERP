# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Proportional scaling of resource norms: the factor, rounding, locks and scope."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.modules.boq.resource_scaling import (
    RoundingRule,
    ScaleLine,
    ScaleScope,
    ScalingError,
    plan_scaling,
    resource_matches,
    scope_line_ids,
)


def _labour(qty: float, *, name: str = "Mason", rate: float = 40.0, unit: str = "h", **extra) -> dict:
    return {"name": name, "type": "labor", "unit": unit, "quantity": qty, "unit_rate": rate, **extra}


def _material(qty: float, *, name: str = "Concrete C30", code: str = "MAT-C30", rate: float = 100.0) -> dict:
    return {"name": name, "code": code, "type": "material", "unit": "m3", "quantity": qty, "unit_rate": rate}


def _line(pid: str, qty: str, resources: list[dict], **kw) -> ScaleLine:
    return ScaleLine(
        id=pid,
        ordinal=kw.pop("ordinal", pid),
        description=kw.pop("description", f"Line {pid}"),
        quantity=Decimal(qty),
        resources=resources,
        **kw,
    )


def _plan(lines, target, metric="hours", scope=None, decimals=3, mode="half_up", to_base=None):
    return plan_scaling(
        lines,
        scope=scope or ScaleScope(),
        metric=metric,
        target=None if target is None else Decimal(str(target)),
        rounding=RoundingRule(decimals=decimals, mode=mode),
        to_base=to_base,
    )


def test_hours_scale_every_labour_norm_by_one_factor() -> None:
    lines = [_line("a", "10", [_labour(2.0), _material(1.0)]), _line("b", "5", [_labour(4.0)])]
    plan = _plan(lines, 30)
    assert plan.current == Decimal(40)
    assert plan.factor == Decimal("0.75")
    assert plan.achieved == Decimal(30)
    a = next(line for line in plan.lines if line.id == "a")
    assert [(c.name, c.old_quantity, c.new_quantity) for c in a.changes] == [("Mason", Decimal(2), Decimal("1.500"))]
    # The material norm is not labour and is left as it was.
    assert a.resources[1]["quantity"] == 1.0


def test_locked_and_excluded_lines_are_fixed_and_the_rest_carries_the_difference() -> None:
    lines = [
        _line("a", "10", [_labour(2.0)], locked=True),
        _line("b", "10", [_labour(2.0)], excluded=True),
        _line("c", "10", [_labour(2.0)]),
    ]
    plan = _plan(lines, 50)
    assert plan.fixed == Decimal(40)
    assert plan.factor == Decimal("0.5")
    statuses = {line.id: line.status for line in plan.lines}
    assert statuses == {"a": "locked", "b": "excluded", "c": "scaled"}
    assert all(not line.changes for line in plan.lines if line.id != "c")


def test_a_locked_resource_row_does_not_move() -> None:
    plan = _plan([_line("a", "1", [_labour(10.0, locked=True), _labour(10.0, name="Helper")])], 15)
    assert plan.factor == Decimal("0.5")
    (line,) = plan.lines
    assert [c.name for c in line.changes] == ["Helper"]


@pytest.mark.parametrize(
    ("mode", "expected"),
    [("half_up", Decimal("0.67")), ("up", Decimal("0.67")), ("down", Decimal("0.66"))],
)
def test_rounding_rule_decides_the_written_norm_and_the_drift_is_reported(mode: str, expected: Decimal) -> None:
    plan = _plan([_line("a", "3", [_labour(1.0)])], 2, decimals=2, mode=mode)
    (line,) = plan.lines
    assert line.changes[0].new_quantity == expected
    assert plan.achieved == expected * 3
    assert plan.to_dict()["drift"] == str((expected * 3 - Decimal(2)).normalize())


def test_target_below_the_fixed_part_is_refused() -> None:
    lines = [_line("a", "10", [_labour(2.0)], locked=True), _line("b", "1", [_labour(1.0)])]
    with pytest.raises(ScalingError) as err:
        _plan(lines, 5)
    assert err.value.code == "target_below_fixed"


def test_nothing_in_scope_to_scale_is_refused() -> None:
    with pytest.raises(ScalingError) as err:
        _plan([_line("a", "10", [_material(1.0)])], 5)
    assert err.value.code == "nothing_to_scale"


def test_a_negative_target_is_refused() -> None:
    with pytest.raises(ScalingError) as err:
        _plan([_line("a", "1", [_labour(1.0)])], -1)
    assert err.value.code == "target_negative"


def test_cost_counts_lines_without_resources_and_unmatched_rows_as_fixed() -> None:
    lines = [
        _line("a", "10", [_labour(1.0, rate=50.0), _material(1.0, rate=100.0)]),
        _line("b", "1", [], total=Decimal("500")),
    ]
    scope = ScaleScope(resource_type="labor")
    plan = _plan(lines, 2000, metric="cost", scope=scope)
    # 10 x 50 labour moves; 10 x 100 material and the 500 lump are fixed.
    assert plan.current == Decimal(2000)
    assert plan.fixed == Decimal(1500)
    plan = _plan(lines, 2500, metric="cost", scope=scope)
    assert plan.factor == Decimal(2)
    (scaled,) = plan.changed_lines
    assert scaled.changes[0].new_quantity == Decimal("2.000")


def test_cost_in_a_currency_without_a_rate_is_left_out_and_reported() -> None:
    def to_base(amount: Decimal, code: str) -> Decimal | None:
        return None if code == "XYZ" else amount

    lines = [_line("a", "1", [_labour(1.0, rate=10.0), _labour(1.0, name="Foreign", rate=10.0, currency="XYZ")])]
    plan = _plan(lines, 20, metric="cost", to_base=to_base)
    assert plan.current == Decimal(10)
    assert {"code": "unconverted_currency", "count": 1} in plan.warnings


def test_resource_key_narrows_to_one_resource_by_code_or_name() -> None:
    lines = [_line("a", "2", [_material(3.0), _material(5.0, name="Rebar", code="MAT-R")])]
    plan = _plan(lines, 3, metric="quantity", scope=ScaleScope(resource_key="mat-c30"))
    assert plan.factor == Decimal("0.5")
    (line,) = plan.lines
    assert [c.name for c in line.changes] == ["Concrete C30"]
    assert resource_matches({"name": "Rebar"}, ScaleScope(resource_key="REBAR"), "quantity")


def test_labour_spellings_match_each_other_but_not_the_operator() -> None:
    assert resource_matches({"type": "labour"}, ScaleScope(resource_type="labor"), "hours")
    assert not resource_matches({"type": "operator"}, ScaleScope(resource_type="labor"), "hours")
    assert resource_matches({"type": "operator"}, ScaleScope(), "hours")
    assert not resource_matches({"type": "equipment"}, ScaleScope(), "hours")


def test_mixed_units_and_norms_rounded_to_zero_are_warned() -> None:
    lines = [_line("a", "1", [_labour(1.0), _labour(0.001, name="Helper", unit="d")])]
    plan = _plan(lines, 0.1, decimals=2)
    codes = {w["code"] for w in plan.warnings}
    assert codes == {"mixed_units", "rounded_to_zero"}


def test_measuring_without_a_target_changes_nothing() -> None:
    plan = _plan([_line("a", "10", [_labour(2.12345)])], None)
    assert plan.factor == Decimal(1)
    assert plan.target == plan.current
    assert plan.changed_lines == []


def test_resource_total_is_recomputed_when_the_row_carries_one() -> None:
    plan = _plan([_line("a", "1", [_labour(2.0, rate=40.0, total=80.0)])], 1)
    assert plan.changed_lines[0].resources[0]["total"] == "40.00"


def test_scope_walks_every_level_under_a_section_and_skips_section_rows() -> None:
    rows = [
        SimpleNamespace(id="s1", parent_id=None, kind="section"),
        SimpleNamespace(id="s2", parent_id="s1", kind="section"),
        SimpleNamespace(id="p1", parent_id="s2", kind="line"),
        SimpleNamespace(id="p2", parent_id="p1", kind="line"),
        SimpleNamespace(id="p3", parent_id=None, kind="line"),
    ]

    def is_section(row) -> bool:
        return row.kind == "section"

    assert scope_line_ids(rows, "s1", is_section) == {"p1", "p2"}
    assert scope_line_ids(rows, None, is_section) == {"p1", "p2", "p3"}
