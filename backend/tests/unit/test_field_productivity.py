# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Foreman productivity compute and its two validation rules, no database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules.field_productivity import (
    ProductivityFactorImplausible,
    ProductivityHoursWithoutProgress,
)
from app.modules.field_time.productivity import (
    Booking,
    PositionInput,
    QuantityInput,
    compute_productivity,
    quantity_from_measurements,
    quantity_from_progress,
    traffic_light,
)

D_FROM = date(2026, 10, 5)  # Monday
D_TO = date(2026, 10, 18)  # Sunday, two ISO weeks


def _pos(pid: str, norm: str | None = "0.5", planned: str = "100") -> PositionInput:
    return PositionInput(
        position_id=pid,
        ref=f"REF-{pid}",
        description="Brick wall",
        unit="m2",
        planned_quantity=Decimal(planned),
        norm_labour_per_unit=Decimal(norm) if norm else None,
        norm_plant_per_unit=None,
    )


def _book(pid: str | None, day: date, hours: str, *, crew: str | None = "c1", worker: str = "w1") -> Booking:
    return Booking(
        day=day,
        hours=Decimal(hours),
        kind="labour",
        position_id=pid,
        cost_code="X" if pid is None else "",
        worker_id=worker,
        crew_id=crew,
        crew_name="Crew A" if crew else "",
    )


def test_factor_earned_rates_and_forecast() -> None:
    # 20 m2 installed at a 0.5 h/m2 norm earns 10 h; 12 h spent -> factor 1.2.
    qty = QuantityInput(source="measurement", weekly={date(2026, 10, 5): Decimal("20")}, to_date=Decimal("40"))
    report = compute_productivity(
        [_pos("p1")],
        [_book("p1", date(2026, 10, 6), "8"), _book("p1", date(2026, 10, 7), "4", worker="w2")],
        {"p1": qty},
        date_from=D_FROM,
        date_to=D_TO,
        hours_to_date={"p1": Decimal("24")},
    )
    row = report["rows"][0]
    assert row["earned_hours"] == "10.00"
    assert row["labour_hours"] == "12.00"
    assert row["productivity_factor"] == "1.200"
    assert row["status"] == "under_productive"
    assert row["light"] == "red"
    assert row["actual_hours_per_unit"] == "0.6000"
    assert row["units_per_man_hour"] == "1.6667"
    # Remaining 60 m2 at the to-date rate 24 h / 40 m2 = 0.6 h/m2.
    assert row["forecast_hours_to_complete"] == "36.00"
    assert row["forecast_basis"] == "to_date_rate"
    assert row["budget_hours_to_complete"] == "30.00"
    assert [w["labour_hours"] for w in row["weeks"]] == ["12.00", "0.00"]
    assert row["crews"][0]["workers"] == 2
    assert report["totals"]["productivity_factor"] == "1.200"


def test_hours_without_quantity_is_no_progress_and_red() -> None:
    report = compute_productivity(
        [_pos("p1")], [_book("p1", date(2026, 10, 6), "8")], {}, date_from=D_FROM, date_to=D_TO
    )
    row = report["rows"][0]
    assert row["status"] == "no_progress"
    assert row["light"] == "red"
    assert row["productivity_factor"] is None


def test_no_norm_is_grey_and_unresolved_code_gets_its_own_row() -> None:
    qty = QuantityInput(source="progress", weekly={date(2026, 10, 5): Decimal("5")}, to_date=Decimal("5"))
    report = compute_productivity(
        [_pos("p1", norm=None)],
        [_book("p1", date(2026, 10, 6), "3"), _book(None, date(2026, 10, 6), "2", crew=None)],
        {"p1": qty},
        date_from=D_FROM,
        date_to=D_TO,
    )
    lights = {r["ref"]: r["light"] for r in report["rows"]}
    assert lights == {"REF-p1": "grey", "X": "grey"}
    assert report["totals"]["labour_hours"] == "5.00"


def test_traffic_light_bands() -> None:
    assert traffic_light("over_productive", Decimal("0.8")) == "green"
    assert traffic_light("on_plan", Decimal("1.04")) == "green"
    assert traffic_light("under_productive", Decimal("1.10")) == "amber"
    assert traffic_light("under_productive", Decimal("1.30")) == "red"
    assert traffic_light("no_baseline", None) == "grey"


def test_quantity_from_progress_uses_latest_seq_per_cutoff() -> None:
    readings = [
        (1, date(2026, 10, 1), Decimal("10")),
        (2, date(2026, 10, 8), Decimal("30")),
        (3, date(2026, 10, 8), Decimal("25")),  # same-day correction wins by seq
        (4, date(2026, 10, 15), Decimal("40")),
    ]
    q = quantity_from_progress(readings, Decimal("200"), D_FROM, D_TO)
    assert q.weekly[date(2026, 10, 5)] == Decimal("30")  # 10% -> 25% of 200
    assert q.weekly[date(2026, 10, 12)] == Decimal("30")  # 25% -> 40%
    assert q.to_date == Decimal("80")


def test_quantity_from_measurements_splits_period_and_to_date() -> None:
    q = quantity_from_measurements(
        [(date(2026, 9, 30), Decimal("7")), (date(2026, 10, 13), Decimal("3")), (date(2026, 10, 20), Decimal("9"))],
        D_FROM,
        D_TO,
    )
    assert q.to_date == Decimal("10")
    assert q.weekly == {date(2026, 10, 12): Decimal("3")}


@pytest.mark.asyncio
async def test_rules_flag_hours_without_progress_and_implausible_factor() -> None:
    rows = [
        {"position_id": "a", "ref": "A", "labour_hours": "8", "installed_quantity": "0", "productivity_factor": None},
        {"position_id": "b", "ref": "B", "labour_hours": "8", "installed_quantity": "5", "productivity_factor": "2.6"},
        {"position_id": "c", "ref": "C", "labour_hours": "8", "installed_quantity": "5", "productivity_factor": "1.1"},
    ]
    data = {"productivity_rows": rows, "date_from": "2026-10-05", "date_to": "2026-10-18"}
    ctx = ValidationContext(data=data, metadata={"locale": "de"})
    missing = await ProductivityHoursWithoutProgress().validate(ctx)
    odd = await ProductivityFactorImplausible().validate(ctx)
    assert [r.element_ref for r in missing] == ["a"]
    assert [r.element_ref for r in odd] == ["b"]
    assert "Position A" in missing[0].message and "Fortschritt" in missing[0].message


@pytest.mark.asyncio
async def test_rules_are_silent_on_a_timesheet_payload() -> None:
    ctx = ValidationContext(data={"lines": []}, metadata={})
    assert await ProductivityHoursWithoutProgress().validate(ctx) == []
    assert await ProductivityFactorImplausible().validate(ctx) == []
