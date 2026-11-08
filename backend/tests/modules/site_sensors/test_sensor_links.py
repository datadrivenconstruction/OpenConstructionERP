# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Site sensor events consumed by schedule, diary, inspections, safety and notifications."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.daily_diary.models import DailyDiary, DiaryEntry, WeatherRecord
from app.modules.inspections.models import QualityInspection
from app.modules.notifications.models import Notification
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem  # noqa: F401 - table for the link rule
from app.modules.safety.models import SafetyIncident, SafetyObservation
from app.modules.schedule.models import Activity, Schedule, ScheduleRelationship
from app.modules.site_sensors.models import (
    FormworkStrip,
    SensorAlert,
    SensorDevice,
    sensor_reading,
)
from app.modules.teams.models import RosterMember
from app.modules.users.models import User

NOW = datetime.now(UTC)
TODAY = NOW.date()


@pytest_asyncio.fixture(scope="module")
async def engine() -> AsyncIterator[AsyncEngine]:
    from tests._pg import isolated_engine

    async with isolated_engine() as eng:
        yield eng


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    # The code under test only flushes, so each test rolls its rows back.
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
        await s.rollback()


async def _user(s: AsyncSession, tag: str) -> User:
    u = User(email=f"{tag}-{uuid.uuid4().hex[:6]}@t.io", hashed_password="x", full_name=tag, role="editor")
    s.add(u)
    await s.flush()
    return u


async def _project(s: AsyncSession, owner: User) -> Project:
    p = Project(name="Tower", owner_id=owner.id)
    s.add(p)
    await s.flush()
    return p


async def _device(s: AsyncSession, project: Project, kind: str = "noise", unit: str = "dB(A)") -> SensorDevice:
    d = SensorDevice(project_id=project.id, code=f"{kind[:2].upper()}-{uuid.uuid4().hex[:4]}", kind=kind, unit=unit)
    s.add(d)
    await s.flush()
    return d


async def _alert(s: AsyncSession, project: Project, device: SensorDevice) -> SensorAlert:
    a = SensorAlert(
        project_id=project.id,
        device_id=device.id,
        kind="exceedance",
        raised_at=NOW,
        value=78.5,
        limit_value=70.0,
        limit_source="Day limit",
    )
    s.add(a)
    await s.flush()
    return a


def _payload(project: Project, alert: SensorAlert, device: SensorDevice) -> dict:
    return {"alert_id": str(alert.id), "project_id": str(project.id), "device_id": str(device.id), "value": 78.5}


# ── Schedule ───────────────────────────────────────────────────────────


async def _schedule(s: AsyncSession, project: Project) -> tuple[Activity, Activity]:
    sch = Schedule(project_id=project.id, name="Main", start_date="2026-11-01")
    s.add(sch)
    await s.flush()
    strike = Activity(
        schedule_id=sch.id, name="Strike slab L3", start_date="2026-12-10", end_date="2026-12-12", duration_days=2
    )
    after = Activity(
        schedule_id=sch.id, name="Fit-out L3", start_date="2026-12-13", end_date="2026-12-20", duration_days=7
    )
    s.add_all([strike, after])
    await s.flush()
    s.add(ScheduleRelationship(schedule_id=sch.id, predecessor_id=strike.id, successor_id=after.id))
    await s.flush()
    return strike, after


async def test_strength_reached_suggests_and_accept_moves_the_strike(session: AsyncSession) -> None:
    from app.modules.schedule.sensor_links import record_strike_suggestion, resolve_strike_suggestion

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    strike, _after = await _schedule(session, project)
    data = {
        "project_id": str(project.id),
        "schedule_activity_id": str(strike.id),
        "strip_id": str(uuid.uuid4()),
        "strength_mpa": 15.4,
        "target_mpa": 15.0,
    }
    act = await record_strike_suggestion(session, data)
    assert act is not None
    sug = act.metadata_["strike_suggestion"]
    assert sug["status"] == "pending"
    assert sug["proposed_start"] == TODAY.isoformat()
    assert 0 < sug["confidence"] <= 1
    # Nothing moves before a person accepts.
    assert act.start_date == "2026-12-10"

    act = await resolve_strike_suggestion(session, act, accept=True, user_id=str(owner.id))
    assert act.start_date == TODAY.isoformat()
    assert act.end_date == (TODAY + timedelta(days=2)).isoformat()
    assert act.constraint_type == "must_start_on"
    assert act.metadata_["strike_suggestion"]["status"] == "accepted"
    with pytest.raises(LookupError):
        await resolve_strike_suggestion(session, act, accept=True, user_id=None)


async def test_strike_suggestion_refuses_an_activity_of_another_project(session: AsyncSession) -> None:
    from app.modules.schedule.sensor_links import record_strike_suggestion

    owner = await _user(session, "owner")
    project, other = await _project(session, owner), await _project(session, owner)
    strike, _ = await _schedule(session, other)
    data = {"project_id": str(project.id), "schedule_activity_id": str(strike.id), "strip_id": "s1"}
    assert await record_strike_suggestion(session, data) is None


# ── Daily diary ────────────────────────────────────────────────────────


async def test_exceedance_drafts_a_diary_entry_links_it_and_takes_sensor_weather(session: AsyncSession) -> None:
    from app.modules.daily_diary.sensor_links import record_exceedance

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    noise = await _device(session, project)
    wind = await _device(session, project, "weather", "m/s")
    day_start = datetime.combine(NOW.date(), datetime.min.time(), tzinfo=UTC)
    await session.execute(
        insert(sensor_reading),
        [
            {"device_id": wind.id, "recorded_at": day_start + timedelta(hours=h), "value": v}
            for h, v in ((6, 2.0), (12, 9.5), (18, 4.0))
        ],
    )
    alert = await _alert(session, project, noise)

    entry = await record_exceedance(session, _payload(project, alert, noise))
    assert entry is not None
    assert entry.entry_type == "event"
    assert entry.metadata_["draft"] is True
    assert entry.source_ref == alert.id
    assert alert.diary_id == entry.diary_id
    again = await record_exceedance(session, _payload(project, alert, noise))
    assert again.id == entry.id

    diary = await session.get(DailyDiary, entry.diary_id)
    assert diary.weather_summary["sensor"]["min"] == 2.0
    assert diary.weather_summary["sensor"]["max"] == 9.5
    assert diary.weather_summary["sensor"]["source"] == "sensor"
    rec = (await session.execute(select(WeatherRecord).where(WeatherRecord.source == "sensor"))).scalars().one()
    assert float(rec.wind_speed_kmh) == pytest.approx(34.2)


async def test_closed_diary_is_left_alone(session: AsyncSession) -> None:
    from app.modules.daily_diary.sensor_links import record_exceedance

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    noise = await _device(session, project)
    session.add(DailyDiary(project_id=project.id, diary_date=NOW.date().isoformat(), status="closed"))
    alert = await _alert(session, project, noise)
    assert await record_exceedance(session, _payload(project, alert, noise)) is None
    assert alert.diary_id is None


# ── Strike: diary + inspection ─────────────────────────────────────────


async def _struck_strip(s: AsyncSession, project: Project) -> tuple[FormworkStrip, SensorDevice]:
    cm = await _device(s, project, "concrete_maturity", "degC")
    pour = NOW - timedelta(hours=72)
    await s.execute(
        insert(sensor_reading),
        [
            {"device_id": cm.id, "recorded_at": pour + timedelta(hours=h), "value": 8.0 + h / 10}
            for h in range(0, 72, 6)
        ],
    )
    strip = FormworkStrip(
        project_id=project.id,
        device_id=cm.id,
        element="Slab L3",
        target_strength_mpa=Decimal("15.00"),
        struck_at=NOW,
        strength_at_strike_mpa=Decimal("15.40"),
        status="struck",
    )
    s.add(strip)
    s.add(
        SensorAlert(
            project_id=project.id, device_id=cm.id, kind="strength_reached", raised_at=NOW, value=15.4, limit_value=15
        )
    )
    await s.flush()
    return strip, cm


async def test_strike_opens_a_release_inspection_and_a_diary_entry(session: AsyncSession) -> None:
    from app.modules.daily_diary.sensor_links import record_strike
    from app.modules.inspections.sensor_links import create_strike_inspection

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    strip, cm = await _struck_strip(session, project)
    data = {"strip_id": str(strip.id), "project_id": str(project.id), "strength_mpa": 15.4}

    insp = await create_strike_inspection(session, data)
    assert insp is not None
    assert insp.inspection_type == "formwork_strike_release"
    assert insp.inspection_number == "INS-001"
    checks = {c["id"]: c for c in insp.checklist_data}
    assert set(checks) == {"strength", "age", "temperature"}
    assert checks["strength"]["notes"] == "15.4 MPa / 15 MPa"
    assert checks["age"]["notes"] == "72 h"
    assert checks["temperature"]["notes"] == "min 8 degC"
    assert all(c["response"] is None for c in checks.values())
    alert = (await session.execute(select(SensorAlert).where(SensorAlert.kind == "strength_reached"))).scalars().one()
    assert alert.inspection_id == insp.id
    assert (await create_strike_inspection(session, data)).id == insp.id
    assert len((await session.execute(select(QualityInspection))).scalars().all()) == 1

    entry = await record_strike(session, data)
    assert entry is not None and entry.entry_type == "completion"
    assert entry.metadata_["params"]["strength"] == "15.4"
    assert (await record_strike(session, data)).id == entry.id
    assert len((await session.execute(select(DiaryEntry))).scalars().all()) == 1


# ── Safety ─────────────────────────────────────────────────────────────


async def test_exceedance_becomes_an_observation_by_default_once_per_episode(session: AsyncSession) -> None:
    from app.modules.safety.sensor_links import record_exceedance

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    noise = await _device(session, project)
    alert = await _alert(session, project, noise)
    obs = await record_exceedance(session, _payload(project, alert, noise))
    assert isinstance(obs, SafetyObservation)
    assert obs.observation_type == "unsafe_condition"
    assert obs.observation_number == "OBS-001"
    assert (await record_exceedance(session, _payload(project, alert, noise))).id == obs.id


async def test_incident_and_off_modes(session: AsyncSession) -> None:
    from app.modules.safety.sensor_links import get_mode, record_exceedance, set_mode

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    noise = await _device(session, project)
    assert await get_mode(session, project.id) == "observation"
    await set_mode(session, project.id, "incident")
    inc = await record_exceedance(session, _payload(project, await _alert(session, project, noise), noise))
    assert isinstance(inc, SafetyIncident)
    assert inc.incident_type == "environmental"
    await set_mode(session, project.id, "off")
    assert await record_exceedance(session, _payload(project, await _alert(session, project, noise), noise)) is None
    with pytest.raises(ValueError, match="invalid_mode"):
        await set_mode(session, project.id, "email")


# ── Notifications ──────────────────────────────────────────────────────


async def test_alerts_go_to_site_managers_and_foremen(session: AsyncSession) -> None:
    from app.modules.notifications._site_sensors_subscribers import route_alert

    owner = await _user(session, "owner")
    project = await _project(session, owner)
    manager, foreman, surveyor = [await _user(session, t) for t in ("sm", "fm", "sv")]
    for u, role, active in ((manager, "site_manager", True), (foreman, "foreman", True), (surveyor, "surveyor", True)):
        session.add(
            RosterMember(
                project_id=project.id, user_id=u.id, display_name=u.full_name, site_role=role, is_active=active
            )
        )
    session.add(RosterMember(project_id=project.id, user_id=owner.id, display_name="o", site_role="site_manager"))
    await session.flush()
    noise = await _device(session, project)
    alert = await _alert(session, project, noise)

    sent = await route_alert(session, "site_sensors.limit.exceeded", _payload(project, alert, noise))
    assert sent == 2
    rows = (await session.execute(select(Notification))).scalars().all()
    assert {r.user_id for r in rows} == {manager.id, foreman.id}
    assert rows[0].title_key == "notifications.site_sensors_exceedance_title"
    assert await route_alert(session, "site_sensors.alert.acknowledged", _payload(project, alert, noise)) == 0


# ── Link rule ──────────────────────────────────────────────────────────


async def test_link_rule_flags_missing_and_cross_project_targets(session: AsyncSession) -> None:
    from app.core.validation.engine import ValidationContext
    from app.modules.integrations.validators import SensorLinkInProject, build_sensor_link_payload

    owner = await _user(session, "owner")
    project, other = await _project(session, owner), await _project(session, owner)
    noise = await _device(session, project)
    own_diary = DailyDiary(project_id=project.id, diary_date=date(2026, 11, 2).isoformat())
    foreign_diary = DailyDiary(project_id=other.id, diary_date=date(2026, 11, 2).isoformat())
    session.add_all([own_diary, foreign_diary])
    await session.flush()
    good, foreign, missing = [await _alert(session, project, noise) for _ in range(3)]
    good.diary_id, foreign.diary_id, missing.inspection_id = own_diary.id, foreign_diary.id, uuid.uuid4()
    await session.flush()

    payload = await build_sensor_link_payload(session, project.id)
    results = await SensorLinkInProject().validate(ValidationContext(data=payload, metadata={}))
    by_ref = {r.element_ref: r for r in results}
    assert by_ref[str(good.id)].passed
    assert by_ref[str(foreign.id)].details["message_key"] == "siteSensors.rules.link_other_project"
    assert by_ref[str(missing.id)].details["message_key"] == "siteSensors.rules.link_missing"
