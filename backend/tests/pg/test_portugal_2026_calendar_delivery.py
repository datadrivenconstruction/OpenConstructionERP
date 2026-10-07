# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""PT national holidays for 2026, delivered without overwriting user calendars."""

from datetime import date

import pytest
from sqlalchemy import select

from app.core.data_repairs import run_data_repairs
from app.modules.i18n_foundation.models import WorkCalendar
from app.modules.i18n_foundation.seed import load_work_calendar_seed_rows, work_calendar_from_seed_row
from app.modules.i18n_foundation.service import I18nFoundationService
from tests.pg.test_work_calendar_seed_reconcile import _install, repair_factory  # noqa: F401

pytestmark = pytest.mark.asyncio

EXPECTED_DATES = {
    "2026-01-01",
    "2026-04-03",
    "2026-04-05",
    "2026-04-25",
    "2026-05-01",
    "2026-06-04",
    "2026-06-10",
    "2026-08-15",
    "2026-10-05",
    "2026-11-01",
    "2026-12-01",
    "2026-12-08",
    "2026-12-25",
}


def _portugal():
    rows = [row for row in load_work_calendar_seed_rows() if row["country_code"] == "PT"]
    assert len(rows) == 1, "PT 2026 must be shipped exactly once"
    return rows[0]


async def _old_install(factory, seeded_on="2026-10-06"):
    rows = [row for row in load_work_calendar_seed_rows() if row["country_code"] != "PT"]
    await _install(factory, rows, seeded_on)


async def _pt_rows(factory):
    async with factory() as session:
        return list((await session.scalars(select(WorkCalendar).where(WorkCalendar.country_code == "PT"))).all())


async def test_seed_contains_national_2026_dates_only():
    row = _portugal()
    assert row["year"] == "2026"
    assert row["work_days"] == [1, 2, 3, 4, 5]  # Planning default, not a statutory site week.
    dates = [item["date"] for item in row["exceptions"]]
    assert len(dates) == 13
    assert set(dates) == EXPECTED_DATES
    assert all(date.fromisoformat(day).year == 2026 for day in dates)
    assert all(item["type"] == "public_holiday" for item in row["exceptions"])
    # No Carnival, municipal holiday or invented Monday substitute.
    assert not {"2026-02-17", "2026-06-13", "2026-04-27", "2026-08-17", "2026-11-02"} & set(dates)


async def test_old_install_receives_holiday_and_delivery_is_idempotent(repair_factory):
    await _old_install(repair_factory)
    async with repair_factory() as session:
        before = await I18nFoundationService(session).get_working_days("PT", "2026-06-10", "2026-06-10")
        assert before.working_days == 1
    await run_data_repairs(repair_factory)
    [delivered] = await _pt_rows(repair_factory)
    assert {item["date"] for item in delivered.exceptions} == EXPECTED_DATES
    async with repair_factory() as session:
        service = I18nFoundationService(session)
        assert (await service.get_working_days("PT", "2026-06-10", "2026-06-10")).working_days == 0
        assert (await service.get_working_days("PT", "2026-06-11", "2026-06-11")).working_days == 1
    await run_data_repairs(repair_factory)
    [again] = await _pt_rows(repair_factory)
    assert again.id == delivered.id


async def test_existing_custom_calendar_is_preserved(repair_factory):
    await _old_install(repair_factory)
    async with repair_factory() as session:
        custom = work_calendar_from_seed_row(_portugal())
        custom.name = "Own PT site calendar"
        custom.work_days = [1, 2, 3, 4]
        custom.work_hours_per_day = "9"
        custom.exceptions = [{"date": "2026-06-11", "name": "Our closure", "type": "public_holiday"}]
        session.add(custom)
        await session.commit()
        expected = {
            column.name: getattr(custom, column.key)
            for column in WorkCalendar.__table__.columns
            if column.name != "metadata"
        }
        expected["metadata"] = custom.metadata_
    await run_data_repairs(repair_factory)
    [after] = await _pt_rows(repair_factory)
    actual = {
        column.name: getattr(after, column.key)
        for column in WorkCalendar.__table__.columns
        if column.name != "metadata"
    }
    actual["metadata"] = after.metadata_
    assert actual == expected


async def test_delivered_then_deleted_calendar_is_not_resurrected(repair_factory):
    await _old_install(repair_factory)
    await run_data_repairs(repair_factory)
    assert len(await _pt_rows(repair_factory)) == 1
    async with repair_factory() as session:
        await session.execute(WorkCalendar.__table__.delete().where(WorkCalendar.country_code == "PT"))
        await session.commit()
    await run_data_repairs(repair_factory)
    assert await _pt_rows(repair_factory) == []


async def test_post_ship_install_missing_portugal_is_left_alone(repair_factory):
    await _old_install(repair_factory, seeded_on="2026-10-08")
    await run_data_repairs(repair_factory)
    assert await _pt_rows(repair_factory) == []
