# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Q15 diagnostics: current demo bills, without installing demos or starting ASGI.

Only the Project/BOQ/Position/Schedule projection is seeded, by the same helpers
as install_demo_project. Each case lives in an outer PostgreSQL transaction
which is rolled back. No existing database, assets, webhooks or live server.
No project calendar is added: this explicitly measures the regional-week
fallback, not an assertion about today's installed showcase or all 81 demos.

Run with -s to retain DIAGNOSTIC JSON lines. Characterisation tests pin proven
math; the price-derived hour provenance remains a separate unresolved issue.
"""

from __future__ import annotations

import copy
import json
import math
import uuid
from collections import Counter
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from app.core.demo_projects import (
    DEMO_TEMPLATES,
    _cost_level,
    _country_code_for,
    _demo_rate,
    _enrich_position_metadata,
    _make_position,
    _make_section,
    _resources_for_position,
)
from app.modules.boq.models import BOQ
from app.modules.projects.models import Project
from app.modules.schedule.models import Activity, Schedule
from app.modules.schedule.service import (
    ScheduleService,
    _calc_duration_from_resources,
    _resource_is_hourly,
    get_work_calendar,
)
from app.modules.users.models import User
from tests._pg import transactional_session

START = date(2026, 4, 1)
DEMOS = ("hospital-jeddah", "office-debrecen", "it-park-bangalore", "residential-athens")


async def _projected_bill(session, demo_id):
    template = DEMO_TEMPLATES[demo_id]
    user = User(email=f"schedule-diagnostic-{uuid.uuid4()}@example.com", hashed_password="x", role="editor")
    session.add(user)
    await session.flush()
    project = Project(
        name=template.project_name,
        owner_id=user.id,
        region=template.region,
        country_code=_country_code_for(template) or "DE",
        currency=template.currency,
        locale=template.locale,
        metadata_={"demo_id": demo_id, "diagnostic_fixture": True},
    )
    session.add(project)
    await session.flush()
    boq = BOQ(project_id=project.id, name=template.boq_name, metadata_=copy.deepcopy(template.boq_metadata))
    schedule = Schedule(
        project_id=project.id,
        name="Q15 source projection",
        start_date=START.isoformat(),
        end_date=(START + timedelta(days=template.total_months * 30)).isoformat(),
        metadata_={},
    )
    session.add_all([boq, schedule])
    await session.flush()
    positions = []
    order = 0
    for ordinal, title, classification, items in template.sections:
        order += 1
        section = _make_section(
            boq_id=boq.id, ordinal=ordinal, description=title, sort_order=order, classification=classification
        )
        session.add(section)
        for subordinal, description, unit, quantity, rate, codes in items:
            order += 1
            metadata = _enrich_position_metadata(
                description,
                unit,
                rate,
                codes,
                locale=template.locale,
                explicit_resources=template.position_resources.get(subordinal),
                currency=template.currency,
            )
            metadata.update(copy.deepcopy(template.position_metadata))
            position = _make_position(
                boq_id=boq.id,
                parent_id=section.id,
                ordinal=subordinal,
                description=description,
                unit=unit,
                quantity=quantity,
                unit_rate=rate,
                sort_order=order,
                classification=codes,
                metadata=metadata,
                source="cwicr",
            )
            positions.append(position)
            session.add(position)
    await session.flush()
    return template, project, boq, schedule, positions


def _resource_hours(metadata):
    # Match the duration reader's unit contract. Monetary resource allowances
    # are not physical hour norms; each accepted row is also printed below.
    return sum(
        float(resource.get("quantity") or 0)
        for resource in metadata.get("resources", [])
        if _resource_is_hourly(resource)
    )


@pytest.mark.parametrize("demo_id", DEMOS)
async def test_current_demo_projection_exposes_duration_bottlenecks(demo_id, record_property):
    async with transactional_session() as session:
        template, project, boq, schedule, positions = await _projected_bill(session, demo_id)
        service = ScheduleService(session)
        plan = await service._plan_from_boq(schedule.id, boq.id, None, START)
        calendar = get_work_calendar(await service.resolve_project_region(project.id))
        hpd, week = calendar["hours_per_day"], len(calendar["work_days"])
        by_id = {str(position.id): position for position in positions}
        tasks = [activity for activity in plan.activities if activity.activity_type == "task"]
        assert len(tasks) == len(positions) > 40
        assert (await session.execute(select(func.count()).select_from(Activity))).scalar_one() == 0
        assert project.planned_end_date is None
        assert plan.fit.compressed_pct is None  # implicit window must not shrink estimates
        total = sum(float(position.total) for position in positions)
        longest = []
        for activity in sorted(tasks, key=lambda value: value.duration_days, reverse=True)[:6]:
            position = by_id[activity.boq_position_ids[0]]
            metadata = position.metadata_
            quantity = float(position.quantity)
            per_unit = float(metadata.get("labor_hours") or 0) or _resource_hours(metadata)
            calendar_days, source = _calc_duration_from_resources(
                metadata,
                quantity,
                position.unit,
                float(position.total),
                total,
                plan.fitted_window["days"],
                hours_per_day=hpd,
                work_days_per_week=week,
                assumed_workers=plan.workers_per_position,
            )
            if source in ("labor_hours", "resource_sum"):
                assert activity.duration_days == max(1, math.ceil(calendar_days * week / 7))
            longest.append(
                {
                    "ordinal": position.ordinal,
                    "description": position.description,
                    "unit": position.unit,
                    "quantity": quantity,
                    "unit_rate": float(position.unit_rate),
                    "source": source,
                    "hours_per_unit_read": per_unit,
                    "total_hours_read": round(quantity * per_unit, 4),
                    "workers": plan.workers_per_position,
                    "hours_per_day": hpd,
                    "working_days_per_week": week,
                    "calendar_days_intermediate": calendar_days,
                    "working_days": activity.duration_days,
                    "task_start": activity.start_date,
                    "task_end": activity.end_date,
                    "explicit_build_up": position.ordinal in template.position_resources,
                    "labor_rows": [r for r in metadata.get("resources", []) if r.get("type") in ("labor", "operator")],
                    # Internal seed consistency, NOT an external labour-rate
                    # recommendation or a proposed currency conversion fix.
                    "shared_seed_labor_rates": [
                        _demo_rate(r["unit_rate"], template.currency, "labor")
                        for r in metadata.get("resources", [])
                        if r.get("type") in ("labor", "operator") and r.get("unit") == "hr"
                    ],
                }
            )
        summary = {
            "demo": demo_id,
            "currency": template.currency,
            "region": project.region,
            "positions": len(positions),
            "workers": plan.workers_per_position,
            "crews": plan.fit.crews,
            "window": plan.fitted_window,
            "seeded_end": schedule.end_date,
            "planned_end": plan.planned_end,
            "span_working_days": plan.fit.layout.span,
            "sources": dict(Counter(a.metadata_["duration_source"] for a in tasks)),
            "explicit_build_ups": len(template.position_resources),
            "longest": longest,
        }
        report = json.dumps(summary, ensure_ascii=False)
        print("DIAGNOSTIC " + report)
        record_property("diagnostic", report)


@pytest.mark.parametrize("week", [5, 6, 7])
def test_hour_duration_round_trip_does_not_apply_the_weekend_factor_twice(week):
    # 1600 hours / (20 workers * 8 h/day) = 10 working days, plus 10% = 11.
    calendar_days, source = _calc_duration_from_resources(
        {"labor_hours": 16},
        100,
        "m2",
        1,
        1,
        365,
        hours_per_day=8,
        work_days_per_week=week,
        assumed_workers=20,
    )
    planned_workdays = math.ceil(calendar_days * week / 7)
    assert source == "labor_hours"
    assert abs(planned_workdays - 11) <= 1  # only integer-rounding residue


def test_explicit_hour_norms_do_not_depend_on_money_or_target_window():
    results = {
        _calc_duration_from_resources(
            {"labor_hours": 80},
            10000,
            "m2",
            price,
            price,
            window,
            hours_per_day=8,
            work_days_per_week=5,
            assumed_workers=20,
        )
        for price in (1, 1000000)
        for window in (30, 365, 3000)
    }
    assert results == {(7700, "labor_hours")}


def test_seeded_hour_quantities_are_inferred_from_price_not_independent_productivity():
    cheap = _enrich_position_metadata("Concrete", "m3", 100, {})
    expensive = _enrich_position_metadata("Concrete", "m3", 10000, {})
    assert _resource_hours(expensive) == pytest.approx(_resource_hours(cheap) * 100, rel=0.001)
    assert expensive["resources"][1]["unit_rate"] == cheap["resources"][1]["unit_rate"] == 45


@pytest.mark.parametrize("demo_id", DEMOS)
def test_seeded_hourly_rates_are_in_the_bill_currency(demo_id):
    # A forint or rupee labour share divided by a euro hourly rate made the
    # hours 140 and 8 times too many: one Debrecen curtain wall ran 43,852
    # working days. Every hourly leaf must carry the levelled rate, and the
    # leaves must still add up to the position rate.
    template = DEMO_TEMPLATES[demo_id]
    checked = 0
    for _ordinal, _title, _classification, items in template.sections:
        for _sub, description, unit, _quantity, rate, codes in items:
            metadata = _enrich_position_metadata(description, unit, rate, codes, currency=template.currency)
            leaves = metadata.get("resources", [])
            for leaf in leaves:
                if (
                    leaf.get("unit") == "hr"
                    and leaf.get("demo_provenance", {}).get("source") == "synthetic_cost_allocation"
                ):
                    assert 20 <= leaf["unit_rate"] / _cost_level(template.currency, leaf["type"]) <= 200
                    checked += 1
            if leaves and rate:
                assert sum(leaf["total"] for leaf in leaves) == pytest.approx(rate, abs=0.01)
    assert checked > 0


def test_a_monetary_allowance_is_not_a_time_norm():
    resources = _resources_for_position("Unclassified scope", "m2", 1000, 200)
    assert next(r for r in resources if r["type"] == "labor")["unit"] == "m2"
    _, source = _calc_duration_from_resources(
        {"resources": resources},
        1000,
        "m2",
        200000,
        200000,
        365,
        hours_per_day=8,
        work_days_per_week=5,
        assumed_workers=20,
    )
    assert source != "resource_sum"


def test_ductile_concrete_is_not_a_tiling_productivity_norm():
    template = DEMO_TEMPLATES["it-park-bangalore"]
    position = next(
        item for _ordinal, _title, _classification, items in template.sections for item in items if item[0] == "3.1"
    )
    _ordinal, description, unit, _quantity, rate, classification = position
    metadata = _enrich_position_metadata(description, unit, rate, classification, locale=template.locale)
    assert "RCC M40" in description and "ductile detail" in description
    assert metadata["cwicr_ref"] != "CWICR-TIL-001"


async def test_pg_plan_excludes_monetary_allowances_without_rewriting_bill_metadata():
    async with transactional_session() as session:
        _, _, boq, schedule, positions = await _projected_bill(session, "residential-athens")
        hourly = [{"type": "labor", "unit": "hr", "quantity": 8}]
        allowance = [{"type": "labor", "unit": "m2", "quantity": 1, "estimated": True}] * 30
        resources = [hourly, hourly + allowance, allowance, []]
        before = {}
        for position, rows in zip(positions[:4], resources, strict=True):
            position.unit = "m2"
            position.quantity = "100"
            position.unit_rate = "200"
            position.total = "20000"
            position.metadata_ = {"resources": copy.deepcopy(rows)}
            before[str(position.id)] = copy.deepcopy(position.metadata_)
        await session.flush()
        plan = await ScheduleService(session)._plan_from_boq(schedule.id, boq.id, None, START, workers_per_position=1)
        tasks = {a.boq_position_ids[0]: a for a in plan.activities if a.activity_type == "task"}
        norm, mixed, money, empty = [tasks[str(p.id)] for p in positions[:4]]
        assert norm.duration_days == mixed.duration_days
        assert norm.metadata_["duration_source"] == mixed.metadata_["duration_source"] == "resource_sum"
        assert money.duration_days == empty.duration_days
        assert money.metadata_["duration_source"] == empty.metadata_["duration_source"] == "estimated_fallback"
        for position in positions[:4]:
            await session.refresh(position)
            assert position.metadata_ == before[str(position.id)]
        assert (await session.execute(select(func.count()).select_from(Activity))).scalar_one() == 0
