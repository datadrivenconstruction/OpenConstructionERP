# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Unit tests for the pure resource-index computation.

The resource-index method prices each resource group of a norm at base prices
and multiplies it by that group's own regional quarterly index, then charges
overheads (NR) and estimated profit (SP) on the wage fund (FOT = workers' wages
plus machine operators' wages), then totals and VAT.

Every figure below was worked out by hand before the code existed; the comment
next to each assertion shows the multiplication. The example deliberately
contains the two shapes a wrong implementation gets wrong:

* operator wages are counted once in direct cost (inside machine operation)
  and also in FOT, so both "added twice" and "left out of FOT" change a total;
* two material lines whose current amounts each round up by half a kopeck, so
  rounding each line and rounding the sum differ by one kopeck.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.modules.price_index import resource_index_math as rim

D = Decimal

REGION = "RU-MOW"
QUARTER = "2026-Q1"

INDICES = {
    rim.GROUP_LABOR: D("1.25"),
    rim.GROUP_MACHINE: D("1.10"),
    rim.GROUP_OPERATOR_WAGES: D("1.30"),
    rim.GROUP_MATERIAL: D("1.05"),
}

NORMS = {
    "concrete": rim.OverheadProfitNorm(work_type="concrete", nr_pct=D("103"), sp_pct=D("65")),
    "earthworks": rim.OverheadProfitNorm(work_type="earthworks", nr_pct=D("89"), sp_pct=D("50")),
}


def _line(kind: str, quantity: str, price: str, code: str = "") -> rim.ResourceLineInput:
    return rim.ResourceLineInput(
        code=code or kind,
        name=kind,
        unit="",
        kind=kind,
        quantity=D(quantity),
        base_unit_price=D(price),
    )


def _position_1() -> rim.PositionInput:
    # Q = 2, work type "concrete" (NR 103 %, SP 65 %).
    return rim.PositionInput(
        ref="p1",
        ordinal="1",
        description="Concrete blinding",
        unit="100 m3",
        quantity=D("2"),
        work_type="concrete",
        resources=(
            _line("labor", "12.5", "400.00", "L1"),
            _line("machine", "3", "1000.00", "M1"),
            _line("operator", "3", "500.00", "O1"),
            _line("material", "10", "250.00", "MAT1"),
        ),
    )


def _position_2() -> rim.PositionInput:
    # Q = 1.5, work type "earthworks" (NR 89 %, SP 50 %).
    return rim.PositionInput(
        ref="p2",
        ordinal="2",
        description="Rounding case",
        unit="m3",
        quantity=D("1.5"),
        work_type="earthworks",
        resources=(
            _line("labor", "2.4", "280.75", "L2"),
            _line("material", "0.5", "13.47", "MAT2A"),
            _line("material", "0.5", "13.47", "MAT2B"),
        ),
    )


def _compute(vat: str = "22", positions: tuple[rim.PositionInput, ...] | None = None) -> rim.EstimateResult:
    return rim.compute_resource_index_estimate(
        rim.EstimateInput(
            region=REGION,
            quarter=QUARTER,
            indices=INDICES,
            norms=NORMS,
            positions=positions if positions is not None else (_position_1(), _position_2()),
            vat_rate_pct=D(vat),
        )
    )


# ── Lines ─────────────────────────────────────────────────────────────────────


def test_every_line_multiplication_is_reported() -> None:
    p1 = _compute().positions[0]
    labor, machine, operator, material = p1.lines

    # 2 x 12.5 x 400.00 = 10 000.00 ; 10 000.00 x 1.25 = 12 500.00
    assert labor.base_amount == D("10000.00")
    assert labor.index == D("1.25")
    assert labor.index_group == rim.GROUP_LABOR
    assert labor.current_amount == D("12500.00")

    # 2 x 3 x 1 000.00 = 6 000.00 ; 6 000.00 x 1.10 = 6 600.00
    assert machine.base_amount == D("6000.00")
    assert machine.index == D("1.10")
    assert machine.current_amount == D("6600.00")

    # 2 x 3 x 500.00 = 3 000.00 ; in machine operation 3 000.00 x 1.10 = 3 300.00,
    # as operators' wages for FOT 3 000.00 x 1.30 = 3 900.00
    assert operator.base_amount == D("3000.00")
    assert operator.index == D("1.10")
    assert operator.index_group == rim.GROUP_MACHINE
    assert operator.current_amount == D("3300.00")
    assert operator.operator_wage_index == D("1.30")
    assert operator.operator_wage_current == D("3900.00")

    # 2 x 10 x 250.00 = 5 000.00 ; 5 000.00 x 1.05 = 5 250.00
    assert material.base_amount == D("5000.00")
    assert material.current_amount == D("5250.00")


def test_position_one_totals_count_operator_wages_once_and_in_fot() -> None:
    p1 = _compute().positions[0]
    assert p1.ot == D("12500.00")
    assert p1.em == D("9900.00")  # 6 600.00 + 3 300.00
    assert p1.otm == D("3900.00")
    assert p1.m == D("5250.00")
    # 12 500.00 + 9 900.00 + 5 250.00. Adding the operators a second time
    # would give 31 550.00.
    assert p1.direct == D("27650.00")
    # 12 500.00 + 3 900.00. Leaving the operators out would give 12 500.00.
    assert p1.fot == D("16400.00")
    assert p1.nr_pct == D("103")
    assert p1.nr == D("16892.00")  # 16 400.00 x 103 %
    assert p1.sp_pct == D("65")
    assert p1.sp == D("10660.00")  # 16 400.00 x 65 %
    assert p1.total == D("55202.00")  # 27 650.00 + 16 892.00 + 10 660.00


def test_position_one_base_figures() -> None:
    p1 = _compute().positions[0]
    assert p1.base_ot == D("10000.00")
    assert p1.base_em == D("9000.00")  # 6 000.00 + 3 000.00
    assert p1.base_otm == D("3000.00")
    assert p1.base_m == D("5000.00")
    assert p1.base_direct == D("24000.00")


def test_rounding_is_per_line_half_up_to_kopecks() -> None:
    p2 = _compute().positions[1]
    labor, mat_a, mat_b = p2.lines
    # 1.5 x 2.4 x 280.75 = 1 010.70 ; x 1.25 = 1 263.375 -> 1 263.38
    assert labor.base_amount == D("1010.70")
    assert labor.current_amount == D("1263.38")
    # 1.5 x 0.5 x 13.47 = 10.1025 -> 10.10 ; x 1.05 = 10.605 -> 10.61
    assert mat_a.base_amount == D("10.10")
    assert mat_a.current_amount == D("10.61")
    assert mat_b.current_amount == D("10.61")
    # Per-line rounding: 10.61 + 10.61 = 21.22. Rounding the sum instead
    # (20.20 x 1.05 = 21.21) would be one kopeck lower.
    assert p2.m == D("21.22")
    assert p2.direct == D("1284.60")  # 1 263.38 + 21.22
    assert p2.fot == D("1263.38")
    assert p2.nr == D("1124.41")  # 1 263.38 x 89 % = 1 124.4082
    assert p2.sp == D("631.69")  # 1 263.38 x 50 % = 631.69
    assert p2.total == D("3040.70")


def test_estimate_totals_and_vat() -> None:
    result = _compute()
    t = result.totals
    assert t.ot == D("13763.38")  # 12 500.00 + 1 263.38
    assert t.em == D("9900.00")
    assert t.otm == D("3900.00")
    assert t.m == D("5271.22")  # 5 250.00 + 21.22
    assert t.direct == D("28934.60")
    assert t.fot == D("17663.38")
    assert t.nr == D("18016.41")  # 16 892.00 + 1 124.41
    assert t.sp == D("11291.69")  # 10 660.00 + 631.69
    assert t.total == D("58242.70")
    assert t.vat_rate_pct == D("22")
    assert t.vat == D("12813.39")  # 58 242.70 x 22 % = 12 813.394
    assert t.total_with_vat == D("71056.09")
    assert t.base_direct == D("25030.90")  # 24 000.00 + 1 010.70 + 10.10 + 10.10
    # The totals are the sum of the positions, nothing added on the side.
    assert t.total == sum((p.total for p in result.positions), D("0"))


def test_vat_rate_is_an_input_not_a_constant() -> None:
    t = _compute(vat="20").totals
    assert t.total == D("58242.70")
    assert t.vat == D("11648.54")  # 58 242.70 x 20 %
    assert t.total_with_vat == D("69891.24")


def test_nr_sp_summary_by_work_type() -> None:
    result = _compute()
    by_type = {row.work_type: row for row in result.by_work_type}
    assert set(by_type) == {"concrete", "earthworks"}
    assert by_type["concrete"].fot == D("16400.00")
    assert by_type["concrete"].nr == D("16892.00")
    assert by_type["concrete"].sp == D("10660.00")
    assert by_type["earthworks"].fot == D("1263.38")
    assert by_type["earthworks"].nr == D("1124.41")
    assert by_type["earthworks"].sp == D("631.69")


def test_indices_used_are_echoed_back() -> None:
    result = _compute()
    assert result.region == REGION
    assert result.quarter == QUARTER
    assert result.indices_used == {
        rim.GROUP_LABOR: D("1.25"),
        rim.GROUP_MACHINE: D("1.10"),
        rim.GROUP_OPERATOR_WAGES: D("1.30"),
        rim.GROUP_MATERIAL: D("1.05"),
    }


# ── Explicit errors ───────────────────────────────────────────────────────────


def test_missing_index_for_a_used_group_is_an_error_not_one() -> None:
    indices = {k: v for k, v in INDICES.items() if k != rim.GROUP_MATERIAL}
    with pytest.raises(rim.MissingIndexError) as excinfo:
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter=QUARTER,
                indices=indices,
                norms=NORMS,
                positions=(_position_1(),),
                vat_rate_pct=D("22"),
            )
        )
    assert excinfo.value.groups == (rim.GROUP_MATERIAL,)
    assert excinfo.value.region == REGION
    assert excinfo.value.quarter == QUARTER


def test_operator_lines_need_their_own_wage_index() -> None:
    # The machine index is present; the operators' wage index is not. No
    # fallback to the labour or machine index.
    indices = {k: v for k, v in INDICES.items() if k != rim.GROUP_OPERATOR_WAGES}
    with pytest.raises(rim.MissingIndexError) as excinfo:
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter=QUARTER,
                indices=indices,
                norms=NORMS,
                positions=(_position_1(),),
                vat_rate_pct=D("22"),
            )
        )
    assert excinfo.value.groups == (rim.GROUP_OPERATOR_WAGES,)


def test_missing_index_for_an_unused_group_is_fine() -> None:
    # Position 2 has no machines and no operators.
    indices = {rim.GROUP_LABOR: D("1.25"), rim.GROUP_MATERIAL: D("1.05")}
    result = rim.compute_resource_index_estimate(
        rim.EstimateInput(
            region=REGION,
            quarter=QUARTER,
            indices=indices,
            norms=NORMS,
            positions=(_position_2(),),
            vat_rate_pct=D("22"),
        )
    )
    assert result.totals.total == D("3040.70")


def test_all_missing_groups_are_named_at_once() -> None:
    with pytest.raises(rim.MissingIndexError) as excinfo:
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter=QUARTER,
                indices={},
                norms=NORMS,
                positions=(_position_1(),),
                vat_rate_pct=D("22"),
            )
        )
    assert excinfo.value.groups == (
        rim.GROUP_LABOR,
        rim.GROUP_MACHINE,
        rim.GROUP_MATERIAL,
        rim.GROUP_OPERATOR_WAGES,
    )


@pytest.mark.parametrize("bad", ["0", "-1.2"])
def test_non_positive_index_is_an_error(bad: str) -> None:
    indices = {**INDICES, rim.GROUP_LABOR: D(bad)}
    with pytest.raises(rim.InvalidIndexError):
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter=QUARTER,
                indices=indices,
                norms=NORMS,
                positions=(_position_1(),),
                vat_rate_pct=D("22"),
            )
        )


def test_missing_overhead_norm_for_a_used_work_type_is_an_error() -> None:
    with pytest.raises(rim.MissingOverheadNormError) as excinfo:
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter=QUARTER,
                indices=INDICES,
                norms={"concrete": NORMS["concrete"]},
                positions=(_position_1(), _position_2()),
                vat_rate_pct=D("22"),
            )
        )
    assert excinfo.value.work_types == ("earthworks",)


def test_position_without_work_type_is_an_error() -> None:
    p = _position_2()
    blank = rim.PositionInput(
        ref=p.ref,
        ordinal=p.ordinal,
        description=p.description,
        unit=p.unit,
        quantity=p.quantity,
        work_type="  ",
        resources=p.resources,
    )
    with pytest.raises(rim.ResourceIndexInputError):
        _compute(positions=(blank,))


def test_unknown_resource_kind_is_an_error_not_material() -> None:
    p = _position_2()
    odd = rim.PositionInput(
        ref=p.ref,
        ordinal=p.ordinal,
        description=p.description,
        unit=p.unit,
        quantity=p.quantity,
        work_type=p.work_type,
        resources=(*p.resources, _line("subcontractor", "1", "100")),
    )
    with pytest.raises(rim.ResourceIndexInputError):
        _compute(positions=(odd,))


def test_negative_vat_rate_is_an_error() -> None:
    with pytest.raises(rim.ResourceIndexInputError):
        _compute(vat="-1")


def test_empty_estimate_is_all_zero() -> None:
    result = _compute(positions=())
    assert result.totals.total == D("0.00")
    assert result.totals.vat == D("0.00")
    assert result.positions == ()


def test_quarter_format_is_checked() -> None:
    with pytest.raises(rim.ResourceIndexInputError):
        rim.compute_resource_index_estimate(
            rim.EstimateInput(
                region=REGION,
                quarter="2026-01",
                indices=INDICES,
                norms=NORMS,
                positions=(),
                vat_rate_pct=D("22"),
            )
        )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("2026-Q1", "2026-Q1"), (" 2025-q4 ", "2025-Q4")],
)
def test_normalise_quarter(raw: str, expected: str) -> None:
    assert rim.normalise_quarter(raw) == expected


@pytest.mark.parametrize("raw", ["2026-Q5", "2026-Q0", "26-Q1", "2026Q1", ""])
def test_normalise_quarter_rejects(raw: str) -> None:
    with pytest.raises(rim.ResourceIndexInputError):
        rim.normalise_quarter(raw)


def test_input_is_not_mutated_and_result_is_deterministic() -> None:
    positions = (_position_1(), _position_2())
    first = _compute(positions=positions)
    second = _compute(positions=positions)
    assert first == second
