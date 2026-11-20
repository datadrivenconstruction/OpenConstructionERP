# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The forecast to every level and the link between a point and its risk, on the course numbers.

Lesson 1: -15 mm at -1.29 mm/day is Alert; the trend line (-1.07 mm/day over three epochs, fitted
-14.5 mm) reaches Action in 5.1 days and Alarm in 14.5 days. Lesson 3: -23 mm is Action and opens a
risk; the trend reaches Alarm in 6.6 days.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.modules.monitoring import monitoring_math as mm

BASE = "/api/v1/monitoring"
DEMO = Path(__file__).resolve().parents[3] / "app" / "modules" / "monitoring" / "demo" / "riverside"
EXPECTED = json.loads((DEMO / "expected.json").read_text(encoding="utf-8"))["monitoring"]
DEMO_T = mm.Thresholds(alert_mm=Decimal(10), action_mm=Decimal(20), alarm_mm=Decimal(30), rate_alert=Decimal(1))
T0 = datetime(2026, 10, 9, tzinfo=UTC)


def _weekly(values: list[str]) -> list[mm.Evaluation]:
    return [mm.Evaluation(T0 + timedelta(days=7 * i), Decimal(v), None, "ok", False) for i, v in enumerate(values)]


def _levels(fc: mm.Forecast) -> dict[str, object]:
    return {lf.level: "reached" if lf.reached else lf.days for lf in fc.levels}


@pytest.mark.parametrize(
    ("lesson", "values"), [("lesson_1", ["0", "-6", "-15"]), ("lesson_3", ["0", "-6", "-15", "-23"])]
)
def test_course_forecast_to_every_level(lesson: str, values: list[str]) -> None:
    want = EXPECTED[lesson]["forecast"]
    fc = mm.forecast(_weekly(values), DEMO_T)
    assert fc is not None
    assert fc.epochs == want["epochs"]
    assert fc.slope_mm_day == pytest.approx(want["rate_used_mm_day"])
    assert fc.fitted_mm == pytest.approx(want["fitted_mm"])
    assert fc.approaching is want["approaching"]
    assert _levels(fc) == want["levels"]


def test_next_level_fields_still_name_the_first_unreached_level() -> None:
    fc = mm.forecast(_weekly(["0", "-6", "-15"]), DEMO_T)
    assert fc is not None and (fc.level, fc.limit_mm, fc.days) == ("action", 20.0, 5.1)


@pytest.mark.parametrize("values", [["-8", "-8", "-8"], ["-8", "-6", "-4"]])
def test_flat_or_receding_trend_is_not_approaching(values: list[str]) -> None:
    fc = mm.forecast(_weekly(values), DEMO_T)
    assert fc is not None and fc.approaching is False and fc.level is None
    assert [(lf.level, lf.reached, lf.days) for lf in fc.levels] == [
        ("alert", False, None),
        ("action", False, None),
        ("alarm", False, None),
    ]


def test_heave_is_approaching_too() -> None:
    fc = mm.forecast(_weekly(["0", "6", "15"]), DEMO_T)
    assert fc is not None and fc.approaching and _levels(fc) == {"alert": "reached", "action": 5.1, "alarm": 14.5}


async def _points(client: AsyncClient, header: dict, project_id: str) -> dict[str, dict]:
    response = await client.get(f"{BASE}/projects/{project_id}/points", headers=header)
    assert response.status_code == 200, response.text
    return {p["code"]: p for p in response.json()["items"]}


async def test_points_carry_every_level_and_the_rate_used(client: AsyncClient, header: dict, project_id: str) -> None:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside?epochs=3", headers=header)
    assert response.status_code == 200, response.text
    mp1 = (await _points(client, header, project_id))["MP-01"]
    want = EXPECTED["lesson_1"]
    assert (mp1["displacement_mm"], mp1["rate_mm_day"], mp1["level"]) == (
        want["displacement_mm"],
        want["rate_mm_day"],
        want["level"],
    )
    assert mp1["forecast_rate_mm_day"] == pytest.approx(want["forecast"]["rate_used_mm_day"])
    assert mp1["forecast_approaching"] is True and mp1["forecast_epochs"] == 3
    got = {f["level"]: "reached" if f["reached"] else f["days"] for f in mp1["forecast_levels"]}
    assert got == want["forecast"]["levels"]


async def test_reading_and_risk_link_both_ways(client: AsyncClient, header: dict, project_id: str) -> None:
    response = await client.post(f"{BASE}/projects/{project_id}/demo/riverside?epochs=4", headers=header)
    assert response.status_code == 200, response.text
    mp1 = (await _points(client, header, project_id))["MP-01"]
    detail = (await client.get(f"{BASE}/points/{mp1['id']}", headers=header)).json()
    link = EXPECTED["lesson_3"]["risk_link"]
    action = next(a for a in detail["alerts"] if a["level"] == "action")
    linked = [s for s in detail["series"] if s["risk_id"]]
    assert [s["at"][:10] for s in linked] == [link["reading_date"]]
    assert linked[0]["risk_id"] == action["risk_id"]

    risks = (await client.get(f"/api/v1/risk/?project_id={project_id}", headers=header)).json()["items"]
    risk = next(r for r in risks if r["id"] == action["risk_id"])
    assert {k: risk["metadata"][k] for k in link["risk_metadata"]} == link["risk_metadata"]
    assert risk["metadata"]["point_id"] == mp1["id"]
    assert risk["metadata"]["reading_id"] == action["reading_id"]
