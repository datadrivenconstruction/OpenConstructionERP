# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Daily diary rule set: each rule fires, a valid record passes, a blocking rule rejects the API write."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio

from app.core.validation.engine import Severity, ValidationContext, rule_registry
from app.modules.daily_diary.permissions import register_daily_diary_permissions
from app.modules.daily_diary.router import router as diary_router
from app.modules.daily_diary.validators import (
    DAILY_DIARY_RULE_SET,
    CrewConsistentRule,
    EntryWithinDiaryDayRule,
    ObservedWeatherNotFutureRule,
    SurveyNotFutureRule,
    WeatherSunOrderRule,
    register_daily_diary_validation_rules,
)
from tests._pg import transactional_session
from tests.modules._site_api import build_app, http, make_project

pytestmark = pytest.mark.asyncio

NOW = datetime.now(UTC)
FUTURE = (NOW + timedelta(days=5)).isoformat()


async def _run(rule: object, data: dict, locale: str = "en"):
    return await rule.validate(ValidationContext(data=data, metadata={"locale": locale}))


CASES = [
    (
        WeatherSunOrderRule,
        {"weather": {"id": "w", "sunrise": "06:10", "sunset": "19:45"}},
        {"weather": {"id": "w", "sunrise": "19:45", "sunset": "06:10"}},
    ),
    (
        ObservedWeatherNotFutureRule,
        {"weather": {"id": "w", "source": "manual", "captured_at": NOW.isoformat()}},
        {"weather": {"id": "w", "source": "sensor", "captured_at": FUTURE}},
    ),
    (
        CrewConsistentRule,
        {"diary": {"id": "d", "labour_count": 8, "equipment_count": 2}},
        {"diary": {"id": "d", "labour_count": 0, "equipment_count": 2}},
    ),
    (
        EntryWithinDiaryDayRule,
        {"entry": {"id": "e", "entry_time": "2026-11-03T09:00:00+00:00", "diary_date": "2026-11-03"}},
        {"entry": {"id": "e", "entry_time": "2026-11-20T09:00:00+00:00", "diary_date": "2026-11-03"}},
    ),
    (
        SurveyNotFutureRule,
        {"survey": {"id": "s", "flown_at": NOW.isoformat()}},
        {"survey": {"id": "s", "flown_at": FUTURE}},
    ),
]


@pytest.mark.parametrize(("rule_cls", "good", "bad"), CASES, ids=lambda v: getattr(v, "__name__", ""))
async def test_rule_passes_and_fails(rule_cls: type, good: dict, bad: dict) -> None:
    rule = rule_cls()
    assert all(r.passed for r in await _run(rule, good))
    failed = [r for r in await _run(rule, bad) if not r.passed]
    assert failed
    assert "site." not in failed[0].message and "money." not in failed[0].message


async def test_partial_and_forecast_records_do_not_false_positive() -> None:
    for cls, _, _ in CASES:
        assert all(r.passed for r in await _run(cls(), {}))
    forecast = {"weather": {"id": "w", "source": "open_meteo", "captured_at": FUTURE}}
    assert all(r.passed for r in await _run(ObservedWeatherNotFutureRule(), forecast))
    only_rise = {"weather": {"id": "w", "sunrise": "06:10"}}
    assert all(r.passed for r in await _run(WeatherSunOrderRule(), only_rise))
    iso = {"weather": {"id": "w", "sunrise": "2026-11-03T06:10", "sunset": "2026-11-03T16:40"}}
    assert all(r.passed for r in await _run(WeatherSunOrderRule(), iso))
    # UTC stamps of a local day that wraps midnight, and a polar-summer sunset after midnight
    wrap = {"weather": {"id": "w", "sunrise": "2026-06-20T20:30:00Z", "sunset": "2026-06-21T07:00:00Z"}}
    assert all(r.passed for r in await _run(WeatherSunOrderRule(), wrap))
    polar = {"weather": {"id": "w", "sunrise": "03:30", "sunset": "00:20"}}
    assert all(r.passed for r in await _run(WeatherSunOrderRule(), polar))


async def test_registration_and_severities() -> None:
    assert CrewConsistentRule.severity == Severity.WARNING
    assert EntryWithinDiaryDayRule.severity == Severity.WARNING
    register_daily_diary_validation_rules()
    ids = {r.rule_id for r in rule_registry.get_rules_for_sets([DAILY_DIARY_RULE_SET])}
    assert len(ids) == 5


async def test_message_follows_locale() -> None:
    ru = await _run(SurveyNotFutureRule(), CASES[4][2], locale="ru")
    assert "будущем" in ru[0].message


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_daily_diary_permissions()
    async with transactional_session() as s:
        yield s


async def test_api_blocks_with_coded_422_and_accepts_valid(db_session) -> None:
    uid, pid = await make_project(db_session)
    base = {"project_id": str(pid), "captured_at": NOW.isoformat(), "source": "manual", "temperature_c": 7}
    async with http(build_app(db_session, uid, diary_router, "/v1/daily-diary")) as c:
        r = await c.post("/v1/daily-diary/weather-records/", json={**base, "captured_at": FUTURE})
        assert r.status_code == 422, r.text
        assert r.json()["detail"]["code"] == "daily_diary.measurement_not_future"

        r = await c.post("/v1/daily-diary/weather-records/", json={**base, "sunrise": "18:00", "sunset": "06:00"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "daily_diary.weather_sun_order"

        r = await c.post("/v1/daily-diary/weather-records/", json={**base, "sunrise": "06:30", "sunset": "16:40"})
        assert r.status_code == 201, r.text
        weather_id = r.json()["id"]

        r = await c.patch(f"/v1/daily-diary/weather-records/{weather_id}", json={"sunset": "05:00"})
        assert r.status_code == 422
        assert r.json()["detail"]["code"] == "daily_diary.weather_sun_order"

        # A warning (equipment without a crew) reports but does not block the diary.
        r = await c.post(
            "/v1/daily-diary/diaries/",
            json={
                "project_id": str(pid),
                "diary_date": NOW.date().isoformat(),
                "labour_count": 0,
                "equipment_count": 2,
            },
        )
        assert r.status_code == 201, r.text
