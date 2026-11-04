"""Plant cost board: owning vs operating cost, idle share and the rent-or-return call."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import date
from decimal import Decimal

from app.modules.equipment.cost_board import (
    MachineFacts,
    build_row,
    depreciation_days,
    owning_cost,
)
from app.modules.equipment.validators import run_rules

D = Decimal
START, END = date(2026, 10, 1), date(2026, 10, 31)  # 31 days

OWNED = MachineFacts(
    equipment_id="e1",
    code="EX-01",
    name="Excavator",
    ownership="owned",
    currency="EUR",
    purchase_date=date(2024, 1, 1),
    purchase_value=D("365250"),
    residual_value=D("0"),
    useful_life_years=10,
    holding_cost_per_month=None,
    market_hire_rate_per_day=D("400"),
    telemetry_days=31,
    worked_hours=D("200"),
    idle_hours=D("40"),
    billed_days=20,
    hire_cost=D("12000"),
    fuel_cost=D("3000"),
    maintenance_cost=D("500"),
)


def test_straight_line_owning_cost_prorated_to_window():
    # 365250 over 10 * 365.25 days = 100 per day, 31 days.
    assert owning_cost(OWNED, START, END) == D("3100")


def test_rows_split_owning_and_operating_cost():
    row = build_row(OWNED, START, END)
    assert row["owning_cost"] == "3100.00"
    assert row["operating_cost"] == "3500.00"
    assert row["total_cost"] == "6600.00"
    assert row["used_hours"] == "200"
    assert row["billed_hours"] == "160"
    assert row["cost_per_used_hour"] == "33.00"
    assert row["idle_pct"] == "16.7"
    assert row["utilisation_pct"] == "80.6"  # 200 of 31 * 8 hours
    assert row["recovery_pct"] == "181.8"


def test_depreciation_stops_at_end_of_useful_life():
    # Life ended on 2026-10-10 for a machine bought 2016-10-10 with a 10 year life.
    days = depreciation_days(START, END, date(2016, 10, 10), 10)
    assert days == D("9")


def test_machine_bought_after_window_has_no_owning_cost():
    f = replace(OWNED, purchase_date=date(2026, 12, 1), holding_cost_per_month=D("100"))
    assert owning_cost(f, START, END) == D("0")


def test_rented_unit_costs_its_rent_without_depreciation():
    f = replace(OWNED, ownership="rented", holding_cost_per_month=D("3652.5"))
    # 3652.5 * 12 / 365.25 = 120 per day.
    assert owning_cost(f, START, END) == D("3720")


def test_idle_rented_unit_is_returned():
    f = replace(OWNED, ownership="rented", holding_cost_per_month=D("3000"), worked_hours=D("20"))
    row = build_row(f, START, END)
    assert (row["suggestion"], row["reason"]) == ("return", "underused_rented")


def test_busy_rented_unit_is_kept():
    f = replace(OWNED, ownership="leased", holding_cost_per_month=D("3000"))
    assert build_row(f, START, END)["suggestion"] == "keep"


def test_owned_unit_costlier_than_market_is_rented_instead():
    f = replace(OWNED, worked_hours=D("30"), market_hire_rate_per_day=D("200"))
    row = build_row(f, START, END)
    assert (row["suggestion"], row["reason"]) == ("rent", "cost_above_market")


def test_owned_unit_with_zero_worked_hours_does_not_divide_by_zero():
    f = replace(OWNED, worked_hours=D("0"), idle_hours=D("0"))
    row = build_row(f, START, END)
    assert row["cost_per_used_hour"] is None
    assert row["idle_pct"] is None
    assert row["suggestion"] == "rent"


def test_owned_underused_without_market_rate_asks_for_review():
    f = replace(OWNED, market_hire_rate_per_day=None, worked_hours=D("20"))
    assert build_row(f, START, END)["reason"] == "underused_no_rate"


def test_machine_without_telemetry_gets_no_call():
    f = replace(OWNED, telemetry_days=0, worked_hours=D("0"), idle_hours=D("0"))
    assert build_row(f, START, END)["suggestion"] == "no_data"


def test_unknown_ownership_cost_is_flagged_not_called_free():
    f = replace(OWNED, purchase_value=None)
    row = build_row(f, START, END)
    assert row["ownership_cost_known"] is False
    assert (row["suggestion"], row["reason"]) == ("review", "ownership_cost_unknown")


def test_currency_mismatch_withholds_the_suggestion():
    row = build_row(replace(OWNED, currency_mismatch=True), START, END)
    assert (row["suggestion"], row["reason"]) == ("review", "currency_mismatch")


def test_rules_flag_cost_above_market_and_unknown_basis():
    costly = build_row(replace(OWNED, worked_hours=D("30"), market_hire_rate_per_day=D("200")), START, END)
    blind = build_row(replace(OWNED, equipment_id="e2", code="EX-02", purchase_value=None), START, END)
    results = asyncio.run(run_rules({"machines": [costly, blind]}))
    failed = {(r["rule_id"], r["element_ref"]) for r in results if not r["passed"]}
    assert ("equipment_telematics.cost_within_market", "e1") in failed
    assert ("equipment_telematics.owning_cost_known", "e2") in failed


def test_board_rules_stay_silent_on_the_telematics_payload():
    payload = {"today": "2026-10-31", "idle_threshold": "0.35", "machines": [{"equipment_id": "e1", "code": "X"}]}
    ids = {r["rule_id"] for r in asyncio.run(run_rules(payload))}
    assert not ids & {"equipment_telematics.owning_cost_known", "equipment_telematics.cost_within_market"}
