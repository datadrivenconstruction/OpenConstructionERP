"""Budget and forecast per cost code x cost type: split, grid arithmetic and rules."""

from __future__ import annotations

import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.cost_types import split_by_cost_type
from app.core.validation.engine import ValidationContext
from app.modules.costmodel.cost_type_grid import GridLine, assemble_grid, eac_of, validation_payload
from app.modules.costmodel.cost_type_rules import PositionUnsplitRule, UnknownTypeRule
from app.modules.costmodel.service import COST_TYPE_SPLIT_KEY, _budget_lines_by_cost_type

D = Decimal


def _line(
    code: str,
    category: str,
    budget: str,
    committed: str = "0",
    actual: str = "0",
    forecast: str | None = None,
    **kw: object,
) -> GridLine:
    return GridLine(
        id=str(uuid.uuid4()),
        cost_code=code,
        cost_code_title="Mobilization" if code == "1.01" else "",
        category=category,
        description=f"{code} {category}",
        currency="EUR",
        budget=D(budget),
        committed=D(committed),
        actual=D(actual),
        forecast=D(forecast if forecast is not None else budget),
        **kw,  # type: ignore[arg-type]
    )


def _position() -> SimpleNamespace:
    return SimpleNamespace(id=uuid.uuid4(), ordinal="1.01", description="Mobilization", quantity="1", unit_rate="1000")


def test_position_becomes_one_budget_line_per_cost_type() -> None:
    resources = [
        {"type": "labor", "quantity": 10, "unit_rate": 30},
        {"type": "operator", "quantity": 2, "unit_rate": 50},
        {"type": "material", "quantity": 1, "unit_rate": 200},
        {"type": "machinery", "quantity": 2, "unit_rate": 100},
        {"type": "subcontractor", "quantity": 1, "unit_rate": 200},
    ]
    total = D("1000")
    lines = _budget_lines_by_cost_type(
        uuid.uuid4(), uuid.uuid4(), _position(), total, "EUR", split_by_cost_type(total, resources), origin=None
    )
    assert [(line.category, D(line.planned_amount)) for line in lines] == [
        ("labor", D("400")),
        ("material", D("200")),
        ("equipment", D("200")),
        ("subcontractor", D("200")),
    ]
    assert sum(D(line.planned_amount) for line in lines) == total
    labour = lines[0].metadata_[COST_TYPE_SPLIT_KEY]
    assert labour == {
        "basis": "resources",
        "weight": "400",
        "weight_total": "1000",
        "resource_count": 2,
        "position_total": "1000",
    }


def test_position_without_resources_goes_to_other_whole() -> None:
    lines = _budget_lines_by_cost_type(uuid.uuid4(), uuid.uuid4(), _position(), D("750"), "EUR", [], origin=None)
    assert [(line.category, line.planned_amount, line.forecast_amount) for line in lines] == [("other", "750", "750")]
    assert lines[0].metadata_[COST_TYPE_SPLIT_KEY]["basis"] == "no_resources"


def test_eac_is_forecast_floored_by_committed_and_actual() -> None:
    assert eac_of(D("100"), D("80"), D("50")) == (D("100"), "forecast")
    assert eac_of(D("100"), D("120"), D("50")) == (D("120"), "committed")
    assert eac_of(D("100"), D("120"), D("130")) == (D("130"), "actual")


def test_grid_subtotals_per_cost_code_and_per_type() -> None:
    lines = [
        _line("1.01", "material", "200", committed="250", forecast="240"),
        _line("1.01", "labor", "400", actual="100", forecast="380"),
        _line("1.02", "labor", "300"),
        _line("", "Earthworks", "50"),
    ]
    grid = assemble_grid(lines, project_id="p", currency="EUR")

    assert [g.cost_code for g in grid.groups] == ["1.01", "1.02", ""]
    mob = grid.groups[0]
    assert [r.cost_type for r in mob.rows] == ["labor", "material"]
    material = mob.rows[1]
    assert (material.eac, material.eac_basis, material.variance) == (D("250"), "committed", D("-50"))
    assert mob.subtotal.budget == D("600")
    assert mob.subtotal.eac == D("630")  # 380 labour + 250 material
    assert mob.subtotal.variance == D("-30")

    by_type = {t.cost_type: (t.line_count, t.totals.budget, t.totals.eac) for t in grid.by_type}
    assert by_type == {
        "labor": (2, D("700"), D("680")),
        "material": (1, D("200"), D("250")),
        "untyped": (1, D("50"), D("50")),
    }
    assert [t.cost_type for t in grid.by_type] == ["labor", "material", "untyped"]
    assert grid.total.budget == D("950")
    assert grid.total.variance == grid.total.budget - grid.total.eac
    assert grid.groups[2].rows[0].cost_type is None


def test_grid_filters_by_type_and_code_prefix() -> None:
    lines = [_line("1.01", "labor", "1"), _line("1.01", "material", "2"), _line("2.01", "labor", "4")]
    assert assemble_grid(lines, project_id="p", currency="EUR", cost_type="labor").total.budget == D("5")
    assert assemble_grid(lines, project_id="p", currency="EUR", cost_code="1.").total.budget == D("3")
    assert assemble_grid(lines, project_id="p", currency="EUR", cost_type="untyped").line_count == 0


@pytest.mark.asyncio
async def test_rules_flag_unsplit_positions_and_unknown_types() -> None:
    lines = [
        _line("1.01", "other", "750", split_basis="no_resources"),
        _line("1.02", "labor", "100", split_basis="resources"),
        _line("", "Earthworks", "50"),
    ]
    ctx = ValidationContext(data=validation_payload(lines), metadata={"locale": "en"})

    unsplit = [r for r in await PositionUnsplitRule().validate(ctx) if not r.passed]
    assert [r.element_ref for r in unsplit] == [lines[0].id]
    assert "1.01" in unsplit[0].message

    unknown = [r for r in await UnknownTypeRule().validate(ctx) if not r.passed]
    assert [r.element_ref for r in unknown] == [lines[2].id]
    assert "Earthworks" in unknown[0].message


@pytest.mark.asyncio
async def test_rules_are_silent_on_other_payloads() -> None:
    ctx = ValidationContext(data={"cost_control": {}}, metadata={})
    assert await PositionUnsplitRule().validate(ctx) == []
