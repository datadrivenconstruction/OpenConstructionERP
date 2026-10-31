# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Bar bending schedule arithmetic and its rule set, without a database."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.modules.rebar_schedule.bbs import (
    BbsError,
    compute_row,
    cut_length,
    render_csv,
    shape_codes,
    totals_by_diameter,
    unit_weight,
)
from app.modules.rebar_schedule.bbs_validators import LapLengthMinRule, TotalVsBoqRule, UnitWeightRule

D = Decimal


def test_unit_weight_is_d_squared_over_162() -> None:
    assert unit_weight(D("12")) == D("0.8889")
    assert unit_weight(D("16")) == D("1.5802")


def test_every_shape_code_evaluates() -> None:
    codes = shape_codes()
    assert {c["standard"] for c in codes} == {"BS8666", "IS2502"}
    for c in codes:
        dims = dict.fromkeys(c["dimensions"], D("600"))
        assert cut_length(c["standard"], c["code"], D("12"), dims) > 0, c


def test_bs8666_shape_21_deducts_radius_and_two_diameters() -> None:
    # 16 mm bar: r = 2d = 32; 300 + 1000 + 300 - 32 - 32 = 1536, quoted to the nearest 5 mm
    assert cut_length("BS8666", "21", D("16"), {"A": D("300"), "B": D("1000"), "C": D("300")}) == D("1535")


def test_is2502_stirrup_adds_hooks() -> None:
    # 8 mm link 200 x 400: 2 x 600 + 20d - 6d - 6d = 1264, quoted as 1265
    assert cut_length("IS2502", "F", D("8"), {"A": D("200"), "B": D("400")}) == D("1265")


def test_missing_dimension_is_refused() -> None:
    with pytest.raises(BbsError, match="B"):
        cut_length("BS8666", "11", D("12"), {"A": D("500")})


def test_row_totals_and_diameter_summary() -> None:
    row = compute_row(
        standard="BS8666",
        code="00",
        diameter_mm=D("12"),
        dims={"A": D("6000")},
        members_count=4,
        bars_per_member=10,
    )
    assert row["total_length_m"] == D("240.000")
    assert row["weight_kg"] == D("213.336")
    rows = [
        SimpleNamespace(diameter_mm=D("12"), members_count=4, bars_per_member=10, **row),
        SimpleNamespace(diameter_mm=D("12.00"), members_count=1, bars_per_member=5, **row),
    ]
    totals = totals_by_diameter(rows)
    assert len(totals) == 1
    assert totals[0]["bar_count"] == 45


def test_csv_has_header_rows_and_totals() -> None:
    row = SimpleNamespace(
        member="B1",
        bar_mark="01",
        shape_standard="BS8666",
        shape_code="00",
        diameter_mm=D("12"),
        dim_a=D("6000"),
        dim_b=None,
        dim_c=None,
        dim_d=None,
        dim_e=None,
        members_count=1,
        bars_per_member=2,
        cut_length_mm=D("6000"),
        total_length_m=D("12.000"),
        unit_weight_kg_m=D("0.8889"),
        weight_kg=D("10.667"),
        steel_grade=None,
        lap_length_mm=None,
        notes=None,
    )
    text = render_csv([row])
    assert text.splitlines()[0].startswith("member,bar_mark")
    assert "B1,01,BS8666,00,12" in text
    assert "12,2,12.000,10.667" in text


def _ctx(data: dict) -> ValidationContext:
    return ValidationContext(data=data)


@pytest.mark.asyncio
async def test_lap_length_rule_uses_configured_multiple() -> None:
    rows = [{"member": "C1", "bar_mark": "1", "diameter_mm": D("16"), "lap_length_mm": D("640")}]
    short = await LapLengthMinRule().validate(_ctx({"rows": rows, "lap_multiple": D("50")}))
    ok = await LapLengthMinRule().validate(_ctx({"rows": rows, "lap_multiple": D("40")}))
    assert not short[0].passed
    assert ok[0].passed


@pytest.mark.asyncio
async def test_unit_weight_rule_flags_a_wrong_figure() -> None:
    rows = [{"member": "C1", "bar_mark": "1", "diameter_mm": D("16"), "unit_weight_kg_m": D("1.21")}]
    res = await UnitWeightRule().validate(_ctx({"rows": rows}))
    assert not res[0].passed


@pytest.mark.asyncio
async def test_total_vs_boq_in_tonnes_with_tolerance() -> None:
    rows = [{"weight_kg": D("1030"), "boq_position_id": "p1"}]
    positions = {"p1": {"ordinal": "05.010", "unit": "t", "quantity": "1"}}
    within = await TotalVsBoqRule().validate(_ctx({"rows": rows, "positions": positions, "tolerance_pct": D("5")}))
    beyond = await TotalVsBoqRule().validate(_ctx({"rows": rows, "positions": positions, "tolerance_pct": D("2")}))
    assert within[0].passed
    assert not beyond[0].passed
