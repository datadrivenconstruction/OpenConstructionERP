# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""Trade demand vs availability grid and the trade-missing rule, no database."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.validation.engine import ValidationContext
from app.core.validation.rules.field_productivity import ActivityLabourWithoutTrade
from app.modules.resources.workforce_demand import (
    SupplyItem,
    TradeCatalog,
    activity_demand,
    build_weeks,
    cell_status,
    compute_workforce,
    working_days,
)

CATALOG_SKILLS = [("trade.carpentry", "Carpentry"), ("trade.masonry", "Masonry")]


def _activity(resources: list[dict], **kw: object) -> SimpleNamespace:
    base = {
        "id": "a1",
        "name": "Formwork L2",
        "start_date": "2026-11-02",  # Monday
        "end_date": "2026-11-13",  # Friday of the next week: 10 working days
        "status": "in_progress",
        "progress_pct": "0",
        "resources": resources,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def test_working_days() -> None:
    assert working_days(date(2026, 11, 2), date(2026, 11, 8)) == 5
    assert working_days(date(2026, 11, 7), date(2026, 11, 8)) == 0
    assert working_days(date(2026, 11, 2), date(2026, 11, 13)) == 10


def test_trade_catalog_matches_name_code_and_short_code() -> None:
    cat = TradeCatalog(CATALOG_SKILLS)
    assert cat.key("Carpentry") == "trade.carpentry"
    assert cat.key("carpentry") == "trade.carpentry"
    assert cat.key("TRADE.MASONRY") == "trade.masonry"
    assert cat.key("Scaffolder") == "scaffolder"
    assert cat.labels["scaffolder"] == "Scaffolder"
    assert cat.key("  ") == ""


def test_man_hours_spread_over_working_days_and_scaled_by_progress() -> None:
    cat = TradeCatalog(CATALOG_SKILLS)
    act = _activity([{"type": "labor", "trade": "Carpentry", "units": 800}], progress_pct="50")
    items, checks = activity_demand(act, "p1", "Tower", cat)
    weeks = build_weeks(date(2026, 11, 2), 3)
    grid = compute_workforce(items, [], weeks, cat.labels)
    row = grid["trades"][0]
    # 400 remaining man-hours over 10 days = 200 h per week = 5 FTE at 40 h.
    assert [c["demand_fte"] for c in row["cells"]] == ["5.00", "5.00", "0.00"]
    assert row["cells"][0]["contributors"][0]["name"] == "Formwork L2"
    assert row["label"] == "Carpentry"
    assert checks[0]["trade"] == "trade.carpentry"


def test_supply_minus_leave_gives_gap_and_status() -> None:
    cat = TradeCatalog(CATALOG_SKILLS)
    items, _ = activity_demand(_activity([{"type": "labour", "trade": "carpentry", "headcount": 3}]), "p1", "T", cat)
    people = [
        SupplyItem("r1", "person", ["trade.carpentry"], Decimal("1")),
        SupplyItem(
            "r2", "person", ["trade.carpentry"], Decimal("1"), unavailable=[(date(2026, 11, 2), date(2026, 11, 8))]
        ),
    ]
    grid = compute_workforce(items, people, build_weeks(date(2026, 11, 2), 2), cat.labels)
    cells = grid["trades"][0]["cells"]
    assert cells[0]["available_fte"] == "1.00" and cells[0]["gap_fte"] == "-2.00"
    assert cells[1]["available_fte"] == "2.00" and cells[1]["status"] == "short"
    assert grid["short_trades"] == 1


def test_completed_or_non_labour_entries_add_no_demand() -> None:
    cat = TradeCatalog(CATALOG_SKILLS)
    assert activity_demand(_activity([{"type": "labor", "units": 10}], status="completed"), None, "", cat) == ([], [])
    items, _ = activity_demand(_activity([{"type": "equipment", "units": 10}]), None, "", cat)
    assert items == []


def test_cell_status() -> None:
    assert cell_status(Decimal("0"), Decimal("0")) == "idle"
    assert cell_status(Decimal("3"), Decimal("2")) == "short"
    assert cell_status(Decimal("1.9"), Decimal("2")) == "tight"
    assert cell_status(Decimal("1"), Decimal("4")) == "surplus"


@pytest.mark.asyncio
async def test_rule_flags_labour_without_trade() -> None:
    cat = TradeCatalog(CATALOG_SKILLS)
    _, checks = activity_demand(
        _activity([{"type": "labor", "units": 40}, {"type": "labor", "trade": "Masonry", "units": 40}]),
        "p1",
        "Tower",
        cat,
    )
    results = await ActivityLabourWithoutTrade().validate(
        ValidationContext(data={"workforce_activities": checks}, metadata={"locale": "ru"})
    )
    assert len(results) == 1
    assert results[0].element_ref == "a1"
    assert "Formwork L2" in results[0].message
