# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""A submitted field report reaches the daily diary (link) and safety (observation)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from app.modules.daily_diary.field_report_links import link_field_report
from app.modules.daily_diary.models import DailyDiary, DiaryEntry
from app.modules.fieldreports.models import FieldReport
from app.modules.projects.models import Project
from app.modules.safety.field_report_links import record_field_report_safety
from app.modules.safety.models import SafetyObservation
from app.modules.users.models import User

DAY = date(2026, 11, 20)


@pytest_asyncio.fixture(scope="module")
async def engine() -> AsyncIterator[AsyncEngine]:
    from tests._pg import isolated_engine

    async with isolated_engine() as eng:
        yield eng


@pytest_asyncio.fixture
async def session(engine: AsyncEngine) -> AsyncIterator[AsyncSession]:
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
        await s.rollback()


async def _project(s: AsyncSession) -> Project:
    u = User(email=f"fr-{uuid.uuid4().hex[:6]}@t.io", hashed_password="x", full_name="fr", role="editor")
    s.add(u)
    await s.flush()
    p = Project(name="Depot", owner_id=u.id)
    s.add(p)
    await s.flush()
    return p


async def _report(s: AsyncSession, p: Project, **kw: object) -> FieldReport:
    r = FieldReport(project_id=p.id, report_date=DAY, status="submitted", **kw)
    s.add(r)
    await s.flush()
    return r


async def _diary(s: AsyncSession, p: Project, status: str = "open") -> DailyDiary:
    d = DailyDiary(project_id=p.id, diary_date=DAY.isoformat(), status=status)
    s.add(d)
    await s.flush()
    return d


@pytest.mark.asyncio
async def test_weather_delay_links_into_open_diary_once(session: AsyncSession) -> None:
    p = await _project(session)
    d = await _diary(session, p)
    r = await _report(session, p, weather_condition="rain", delay_hours=3.5, delays="Heavy rain, pour stopped")
    first = await link_field_report(session, {"report_id": str(r.id)})
    again = await link_field_report(session, {"report_id": str(r.id)})
    assert first is not None
    assert again is not None
    assert again.id == first.id
    assert first.diary_id == d.id
    assert first.source_module == "fieldreports"
    assert first.source_ref == r.id
    assert first.metadata_["title_key"] == "daily_diary.field_report.delay"
    assert first.metadata_["params"]["delay_hours"] == 3.5
    assert first.description == "Heavy rain, pour stopped"
    rows = (await session.execute(select(DiaryEntry).where(DiaryEntry.diary_id == d.id))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_no_open_diary_means_no_entry(session: AsyncSession) -> None:
    p = await _project(session)
    await _diary(session, p, status="closed")
    r = await _report(session, p)
    assert await link_field_report(session, {"report_id": str(r.id)}) is None


@pytest.mark.asyncio
async def test_report_without_delay_is_linked_not_copied(session: AsyncSession) -> None:
    p = await _project(session)
    d = await _diary(session, p)
    r = await _report(session, p, delay_hours=0)
    e = await link_field_report(session, {"report_id": str(r.id)})
    assert e is not None
    assert e.metadata_["title_key"] == "daily_diary.field_report.linked"
    await session.refresh(d)
    assert d.labour_count == 0


@pytest.mark.asyncio
async def test_safety_text_becomes_one_open_observation(session: AsyncSession) -> None:
    p = await _project(session)
    r = await _report(session, p, safety_incidents="Worker slipped on scaffold deck, no injury")
    obs = await record_field_report_safety(session, {"report_id": str(r.id)})
    again = await record_field_report_safety(session, {"report_id": str(r.id)})
    assert obs is not None
    assert again is not None
    assert again.id == obs.id
    assert obs.status == "open"
    assert obs.observation_type == "unsafe_condition"
    assert obs.metadata_["field_report_id"] == str(r.id)
    assert obs.observation_number
    count = (
        (await session.execute(select(SafetyObservation).where(SafetyObservation.project_id == p.id))).scalars().all()
    )
    assert len(count) == 1


@pytest.mark.asyncio
async def test_blank_safety_text_creates_nothing(session: AsyncSession) -> None:
    p = await _project(session)
    r = await _report(session, p, safety_incidents="   ")
    assert await record_field_report_safety(session, {"report_id": str(r.id)}) is None
    assert await record_field_report_safety(session, {"report_id": "not-a-uuid"}) is None
