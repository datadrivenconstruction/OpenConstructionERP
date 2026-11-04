# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""measurement and price_breakdown are modules with a manifest and validation rules."""

from __future__ import annotations

import pytest

from app.core.module_loader import ModuleLoader
from app.core.validation.engine import ValidationContext, rule_registry


@pytest.fixture(scope="module")
def loader() -> ModuleLoader:
    ld = ModuleLoader()
    ld.discover()
    return ld


def test_loader_discovers_both_libraries(loader: ModuleLoader) -> None:
    names = {m for m in loader._manifests}
    assert {"oe_measurement", "oe_price_breakdown"} <= names
    for name in ("oe_measurement", "oe_price_breakdown"):
        manifest = loader._manifests[name]
        assert manifest.category == "core"
        assert manifest.auto_install is True
        assert manifest.depends == []


def test_boq_depends_on_both_and_loads_after_them(loader: ModuleLoader) -> None:
    assert {"oe_measurement", "oe_price_breakdown"} <= set(loader._manifests["oe_boq"].depends)
    order = loader.resolve_order()
    assert order.index("oe_measurement") < order.index("oe_boq")
    assert order.index("oe_price_breakdown") < order.index("oe_boq")


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data, metadata={})


async def _run(rule_id: str, data: dict) -> list:
    import app.modules.measurement.validators  # noqa: F401
    import app.modules.price_breakdown.validators  # noqa: F401

    rule = rule_registry.get_rule(rule_id)
    assert rule is not None
    return await rule.validate(_ctx(data))


@pytest.mark.asyncio
async def test_formula_parses_flags_a_broken_formula() -> None:
    sheet = {
        "item_ref": "1.1",
        "lines": [
            {"ref": "a", "formula": "2 * w", "variables": {"w": 3}},
            {"ref": "b", "formula": "2 *", "variables": {}},
            {"ref": "c", "formula": "", "nos": 2, "length": 3},
        ],
    }
    results = await _run("measurement.formula_parses", {"sheets": [sheet]})
    assert [r.passed for r in results] == [True, False]


@pytest.mark.asyncio
async def test_sheet_reconciles_with_boq_qty() -> None:
    lines = [{"ref": "a", "formula": "10"}, {"ref": "b", "formula": "5", "sign": "-"}]
    ok = await _run(
        "measurement.sheet_reconciles_with_boq_qty",
        {"sheets": [{"item_ref": "1", "lines": lines, "target_quantity": "5"}]},
    )
    bad = await _run(
        "measurement.sheet_reconciles_with_boq_qty",
        {"sheets": [{"item_ref": "1", "lines": lines, "target_quantity": "9"}]},
    )
    none = await _run("measurement.sheet_reconciles_with_boq_qty", {"sheets": [{"item_ref": "1", "lines": lines}]})
    assert [r.passed for r in ok] == [True]
    assert [r.passed for r in bad] == [False]
    assert none == []
    assert bad[0].severity.value == "warning"


@pytest.mark.asyncio
async def test_components_sum_to_rate() -> None:
    comps = [
        {"kind": "labour", "quantity": "2", "unit_cost": "30"},
        {"kind": "material", "quantity": "1", "unit_cost": "40"},
    ]
    good = {"position_ref": "p1", "unit_rate": "110.00", "components": comps, "overhead_pct": "10"}
    wrong = {"position_ref": "p2", "unit_rate": "100.00", "components": comps, "overhead_pct": "10"}
    results = await _run("price_breakdown.components_sum_to_rate", {"breakdowns": [good, wrong]})
    assert [r.passed for r in results] == [True, False]


@pytest.mark.asyncio
async def test_markup_in_range() -> None:
    rows = [
        {"position_ref": "ok", "overhead_pct": "12.5", "profit_pct": "8"},
        {"position_ref": "neg", "risk_pct": "-1"},
        {"position_ref": "huge", "profit_pct": "5000"},
    ]
    results = await _run("price_breakdown.markup_in_range", {"breakdowns": rows})
    assert [r.passed for r in results] == [True, False, False]
