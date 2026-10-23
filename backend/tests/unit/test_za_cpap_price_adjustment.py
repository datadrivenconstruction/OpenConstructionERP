# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""South Africa's Haylett formula, the P0151.1 Table 1 parser and the formula rule.

All index values below are SAMPLE numbers chosen for easy arithmetic; they are
not Stats SA figures.
"""

from __future__ import annotations

import io
from decimal import Decimal
from typing import Any

import pytest
from openpyxl import Workbook

from app.core.validation.engine import ValidationContext
from app.modules.contracts.price_adjustment import (
    PriceAdjustmentError,
    coefficient_problems,
    compute_adjustment,
    regime_for,
)
from app.modules.contracts.validators import ContractPriceAdjustmentFormulaRule
from app.modules.price_index.statssa_p0151 import (
    ACKNOWLEDGEMENT,
    P0151ImportError,
    parse_p0151_table1,
    parse_period,
)

_WEIGHTS = [("L", "0.4"), ("P", "0.1"), ("M", "0.4"), ("F", "0.1")]
_BASE = {"L": "100", "P": "100", "M": "100", "F": "100"}
_CURRENT = {"L": "110", "P": "100", "M": "105", "F": "120"}


def test_haylett_scales_by_one_minus_x() -> None:
    # sum(c * I/Io) - 1 = 0.04 + 0 + 0.02 + 0.02 = 0.08; (1 - 0.15) x 1 000 000 x 0.08 = 68 000
    result = compute_adjustment("za_cpap_haylett", "1000000", _WEIGHTS, _BASE, _CURRENT)
    assert result.total == Decimal("68000.00")
    assert result.fixed_portion == Decimal("0.15")


def test_contract_x_overrides_the_default() -> None:
    result = compute_adjustment("za_cpap_haylett", "1000000", _WEIGHTS, _BASE, _CURRENT, "0.10")
    assert result.total == Decimal("72000.00")


def test_weights_must_add_up_to_one() -> None:
    regime = regime_for("za_cpap_haylett")
    assert regime is not None
    problems = coefficient_problems(regime, [("L", "0.4"), ("M", "0.4")])
    assert [p["problem"] for p in problems] == ["coefficient_sum_not_one"]
    with pytest.raises(PriceAdjustmentError) as exc:
        compute_adjustment("za_cpap_haylett", "1", _WEIGHTS, _BASE, _CURRENT, "1")
    assert exc.value.problem == "non_adjustable_portion_out_of_range"


def test_other_regimes_unchanged() -> None:
    result = compute_adjustment("eg_law182_art97", "1000000", [("M", "0.4")], {"M": "100"}, {"M": "110"})
    assert result.total == Decimal("40000.00")
    assert result.fixed_portion == Decimal("0.6")


# ── P0151.1 parser ──────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("cell", "period"),
    [("Jan 2026", "2026-01"), ("Sept-25", "2025-09"), ("2026-03", "2026-03"), ("2026 Feb", "2026-02"), ("x", None)],
)
def test_parse_period(cell: str, period: str | None) -> None:
    assert parse_period(cell) == period


def _xlsx(rows: list[list[Any]]) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Table 1"
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_parse_xlsx_table1() -> None:
    from datetime import datetime

    content = _xlsx(
        [
            ["Table 1 - Sample layout"],
            ["Work group", "Description", datetime(2026, 1, 1), datetime(2026, 2, 1)],
            [110, "Sample group A", 100.0, 101.5],
            [120, "Sample group B", "..", 99.2],
            ["Notes: sample"],
        ]
    )
    table = parse_p0151_table1(content, "p0151.xlsx")
    by_code = {g.code: g for g in table.work_groups}
    assert by_code["110"].points == {"2026-01": Decimal("100.0"), "2026-02": Decimal("101.5")}
    assert by_code["120"].points == {"2026-02": Decimal("99.2")}
    assert by_code["110"].series_name == "ZA P0151.1 WG110 Sample group A"
    assert table.skipped == ["WG120 2026-01: '..'"]


def test_parse_csv_code_and_description_in_one_cell() -> None:
    content = b"Work group;Jan 2026;Feb 2026\n210 Sample group C;100,0;102,0\n"
    table = parse_p0151_table1(content, "p0151.csv")
    assert table.work_groups[0].code == "210"
    assert table.work_groups[0].description == "Sample group C"
    assert table.work_groups[0].points["2026-02"] == Decimal("102.0")


@pytest.mark.parametrize(
    ("content", "name", "problem"),
    [
        (b"a,b\n1,2\n", "x.csv", "no_month_header"),
        (b"Group,Jan 2026\nTotal,100\n", "x.csv", "no_work_groups"),
        (b"", "x.pdf", "unsupported_format"),
    ],
)
def test_parse_refuses(content: bytes, name: str, problem: str) -> None:
    with pytest.raises(P0151ImportError) as exc:
        parse_p0151_table1(content, name)
    assert exc.value.problem == problem


def test_acknowledgement_names_stats_sa() -> None:
    assert "Statistics South Africa" in ACKNOWLEDGEMENT and "P0151.1" in ACKNOWLEDGEMENT


# ── contracts.price_adjustment_formula ───────────────────────────────────────


def _ctx(block: dict[str, Any]) -> ValidationContext:
    return ValidationContext(
        data={
            "project": {"country_code": "ZA", "works": "private"},
            "contract": {"id": "c1", "counterparty_type": "client", "terms": {"price_adjustment": block}},
        },
        metadata={"locale": "en"},
    )


async def _fails(block: dict[str, Any]) -> list[Any]:
    return [r for r in await ContractPriceAdjustmentFormulaRule().validate(_ctx(block)) if not r.passed]


@pytest.mark.asyncio
async def test_rule_passes_valid_haylett_and_is_silent_without_regime() -> None:
    rows = [{"item": i, "coefficient": c} for i, c in _WEIGHTS]
    assert await _fails({"regime": "za_cpap_haylett", "coefficients": rows}) == []
    assert await ContractPriceAdjustmentFormulaRule().validate(_ctx({})) == []


@pytest.mark.asyncio
async def test_rule_flags_bad_sum_x_and_unknown_regime() -> None:
    rows = [{"item": "L", "coefficient": "0.5"}]
    fails = await _fails({"regime": "za_cpap_haylett", "coefficients": rows, "non_adjustable_portion": "1.2"})
    assert [f.details["item"] for f in fails] == ["0.5", "1.2"]
    assert "exactly one" in fails[0].message
    unknown = await _fails({"regime": "nope", "coefficients": rows})
    assert "nope" in unknown[0].message
