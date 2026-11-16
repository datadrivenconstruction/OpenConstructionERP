"""Plant rate catalogue: the DOMAIN worked examples, validation rules and the table importer."""

from __future__ import annotations

import asyncio
from decimal import Decimal

import pytest

from app.modules.equipment.rate_import import ColumnProfile, parse_table, rows_from_csv
from app.modules.equipment.rate_math import (
    AVERAGE_ANNUAL_INVESTMENT,
    AVERAGE_VALUE,
    RateInputError,
    RateInputs,
    compute_rate,
    monthly_charge,
)
from app.modules.equipment.rate_validators import run_rate_rules

D = Decimal


def _excavator() -> RateInputs:
    return RateInputs(D("180000"), D("18000"), D("6"), D("10"), D("0.06"), D("0.60"), D("170"))


def test_example_1_excavator_average_value() -> None:
    r = compute_rate(_excavator(), convention=AVERAGE_VALUE)
    assert r.depreciation == D("2700")
    assert r.interest == D("594")
    assert r.repair == D("1800")
    assert r.monthly == D("5094.00")
    assert r.hourly == D("29.96")
    assert r.daily is None


def test_example_2_wheel_loader_average_annual_investment() -> None:
    inputs = RateInputs(D("250000"), D("50000"), D("5"), D("12"), D("0.08"), D("0.50"), D("150"))
    r = compute_rate(inputs, convention=AVERAGE_ANNUAL_INVESTMENT)
    assert r.depreciation.quantize(D("0.01")) == D("3333.33")
    assert r.interest.quantize(D("0.01")) == D("1133.33")
    assert r.repair.quantize(D("0.01")) == D("2083.33")
    # Rounded once on the final rate: the unrounded terms sum to exactly 6550.
    assert r.monthly == D("6550.00")
    assert r.hourly == D("43.67")


def test_daily_rate_only_with_the_working_days_setting() -> None:
    r = compute_rate(_excavator(), working_days_per_month=D("20"))
    assert r.daily == D("254.70")


def test_example_3_monthly_charge() -> None:
    charge = monthly_charge(
        hourly_rate=D("29.96"),
        operational_hours=D("120"),
        standby_hours=D("30"),
        breakdown_hours=D("8"),
        standby_factor=D("0.5"),
        breakdown_factor=D("0"),
        operating_cost_per_hour=D("0"),
    )
    assert charge["operational"] == D("3595.20")
    assert charge["standby"] == D("449.40")
    assert charge["breakdown"] == D("0.00")
    assert charge["total"] == D("4044.60")


def test_standby_and_breakdown_are_off_while_their_factor_is_empty() -> None:
    charge = monthly_charge(
        hourly_rate=D("29.96"), operational_hours=D("120"), standby_hours=D("30"), breakdown_hours=D("8")
    )
    assert charge["total"] == D("3595.20")


@pytest.mark.parametrize(
    ("life", "months"),
    [(D("0"), D("10")), (D("-1"), D("10")), (D("6"), D("0")), (D("6"), D("13"))],
)
def test_formula_refuses_meaningless_inputs(life: Decimal, months: Decimal) -> None:
    bad = RateInputs(D("1000"), D("100"), life, months, D("0.05"), D("0.5"), D("100"))
    with pytest.raises(RateInputError):
        compute_rate(bad)


def test_hourly_rate_is_absent_without_hours() -> None:
    inputs = RateInputs(D("1000"), D("100"), D("5"), D("10"), D("0.05"), D("0.5"), None)
    assert compute_rate(inputs).hourly is None


def _ids(results: list[dict], *, failed_only: bool = True) -> set[str]:
    return {r["rule_id"] for r in results if (not r["passed"] if failed_only else True)}


def test_item_rules_fire_on_bad_inputs() -> None:
    item = {
        "code": "X",
        "value": "100",
        "residual": "100",
        "life_years": "0",
        "months_per_year": "13",
        "interest": "0.5",
        "repair": "3.5",
        "hours_per_month": "0",
    }
    out = asyncio.run(run_rate_rules({"items": [item]}))
    assert _ids(out) == {
        "equip_rate.life_not_positive",
        "equip_rate.months_out_of_range",
        "equip_rate.residual_exceeds_value",
        "equip_rate.hours_not_positive",
        "equip_rate.interest_unusual",
        "equip_rate.repair_unusual",
    }


def test_item_rules_pass_on_the_worked_example() -> None:
    item = {
        "code": "E-20",
        "value": "180000",
        "residual": "18000",
        "life_years": "6",
        "months_per_year": "10",
        "interest": "0.06",
        "repair": "0.60",
        "hours_per_month": "170",
    }
    assert _ids(asyncio.run(run_rate_rules({"items": [item]}))) == set()


def test_rental_rules() -> None:
    rentals = [
        {"code": "EX-03", "rate": "40", "catalogue_rate": "29.96", "tolerance_pct": "10", "synthetic": True},
        {"code": "EX-04", "rate": "30", "catalogue_rate": "29.96", "tolerance_pct": "10", "synthetic": False},
        {"code": "EX-05", "rate": "40", "catalogue_rate": "29.96", "synthetic": True, "project_is_demo": True},
    ]
    failed = [r for r in asyncio.run(run_rate_rules({"rentals": rentals})) if not r["passed"]]
    assert {(r["rule_id"], r["details"]["code"]) for r in failed} == {
        ("equip_rate.rental_deviates", "EX-03"),
        ("equip_rate.synthetic_in_use", "EX-03"),
    }


def test_deviation_rule_stays_silent_without_a_tolerance() -> None:
    rental = {"code": "EX-03", "rate": "99", "catalogue_rate": "29.96"}
    out = asyncio.run(run_rate_rules({"rentals": [rental]}))
    assert "equip_rate.rental_deviates" not in _ids(out, failed_only=False)


PROFILE = ColumnProfile(
    mapping={
        "code": "Code",
        "name": "Machine",
        "value": "Value",
        "residual": "Residual",
        "life_years": "Life",
        "months_per_year": "Months",
        "interest": "Interest",
        "repair": "Repair",
        "hours_per_month": "Hours",
    },
    decimal_comma=False,
    percent_fields=("interest", "repair"),
)

CSV = (
    "Code,Machine,Value,Residual,Life,Months,Interest,Repair,Hours\n"
    "E-20,Demo excavator 20 t,180000,18000,6,10,6,60,170\n"
    "E-21,Broken row,abc,18000,6,10,6,60,170\n"
)


def test_import_dry_run_reports_row_errors_and_converts_percent() -> None:
    result = parse_table(rows_from_csv(CSV.encode("utf-8")), PROFILE)
    assert result.ready == 1
    assert result.error_rows == 1
    item = result.items[0]
    assert item["interest"] == D("0.06")
    assert item["repair"] == D("0.60")
    issue = result.issues[0]
    assert (issue["rule_id"], issue["row"], issue["field"]) == ("equip_rate.import_row_invalid", 3, "value")


def test_import_reads_decimal_comma_and_semicolon() -> None:
    text = (
        "Code;Machine;Value;Residual;Life;Months;Interest;Repair;Hours\nE-1;Bagger;180.000,50;18.000;6;10;6,5;60;170\n"
    )
    profile = ColumnProfile(mapping=PROFILE.mapping, decimal_comma=True, percent_fields=("interest", "repair"))
    result = parse_table(rows_from_csv(text.encode("utf-8")), profile)
    assert result.ready == 1
    assert result.items[0]["value"] == D("180000.50")
    assert result.items[0]["interest"] == D("0.065")


def test_import_flags_a_missing_column_once_per_row() -> None:
    text = "Code,Machine,Value\nE-1,Bagger,100\n"
    result = parse_table(rows_from_csv(text.encode("utf-8")), PROFILE)
    assert result.ready == 0
    assert {i["field"] for i in result.issues} >= {"residual", "life_years"}
