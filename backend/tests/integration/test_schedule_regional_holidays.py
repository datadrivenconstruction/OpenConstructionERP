"""Country holidays survive generation and the first CPM recalculation on PostgreSQL."""

from datetime import date

import pytest

from app.modules.projects.models import Project
from app.modules.schedule.schemas import ScheduleUpdate
from tests._pg import transactional_session
from tests.integration.test_schedule_generate_from_boq_tree import _activities, _setup


@pytest.mark.asyncio
@pytest.mark.parametrize("country", ["DE", "CA"])
async def test_generated_calendar_records_year_boundary_holidays_and_cpm_keeps_dates(country):
    async with transactional_session() as session:
        service, schedule_id, bill, project_id = await _setup(session)
        project = await session.get(Project, project_id)
        project.region = country
        project.country_code = country
        for index in range(4):
            await bill.position(None, str(index), f"Work {index}", "m2", "400", "10")
        await session.flush()
        await service.generate_from_boq(schedule_id, bill.boq_id, 45, start_date=date(2026, 12, 21))
        schedule = await service.get_schedule(schedule_id)
        calendar = schedule.metadata_["calendar"]
        assert calendar["regional_holiday_country"] == country
        assert {"2026-12-25", "2027-01-01"} <= set(calendar["exceptions"])
        assert {2026, 2027} <= {entry["year"] for entry in calendar["holiday_coverage"]}
        before = {
            activity.id: (activity.start_date, activity.end_date)
            for activity in await _activities(service, schedule_id)
        }
        assert not any(day in calendar["exceptions"] for pair in before.values() for day in pair)
        await service.reschedule(schedule_id)
        after = {
            activity.id: (activity.start_date, activity.end_date)
            for activity in await _activities(service, schedule_id)
        }
        assert after == before

        # A site closure added to the generated calendar makes it explicit;
        # regeneration must preserve it rather than treating it as old data.
        site_calendar = {**calendar, "exceptions": [*calendar["exceptions"], "2027-01-06"]}
        await service.update_schedule(schedule_id, ScheduleUpdate(metadata={"calendar": site_calendar}))
        edited = await service.get_schedule(schedule_id)
        assert "regional_holiday_country" not in edited.metadata_["calendar"]
        plan_calendar, recorded = await service._generation_calendar(edited, {0, 1, 2, 3, 4}, country)
        assert "2027-01-06" in plan_calendar["exceptions"]
        assert recorded is None
