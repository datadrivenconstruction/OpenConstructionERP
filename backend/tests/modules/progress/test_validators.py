# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress rule set on real PostgreSQL through the API."""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio

from app.modules.progress.permissions import register_progress_permissions
from app.modules.progress.router import router as progress_router
from app.modules.progress.validators import register_progress_validation_rules
from tests._pg import transactional_session
from tests.modules._control_pg import build_app, http, make_project, rule_ids

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    register_progress_permissions()
    register_progress_validation_rules()
    async with transactional_session() as s:
        yield s


async def _entry(c, project_id, pct, **kw):
    return await c.post(
        "/v1/progress/entries/",
        json={
            "project_id": str(project_id),
            "period_label": kw.pop("period_label", "2026-W10"),
            "percent_complete": pct,
            **kw,
        },
    )


async def _plan(c, project_id, period, pct):
    return await c.post(
        "/v1/progress/plan/", json={"project_id": str(project_id), "period_label": period, "planned_pct": pct}
    )


async def test_a_first_reading_passes_without_findings(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        r = await _entry(c, pid, 35, geo_lat=48.1, geo_lon=11.5)
    assert r.status_code == 201, r.text
    assert r.json()["validation_warnings"] == []


async def test_half_a_position_fix_is_refused_with_its_code(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        r = await _entry(c, pid, 35, geo_lat=48.1)
    assert r.status_code == 422, r.text
    assert r.json()["detail"]["code"] == "progress.geo_pair_complete"


async def test_a_reading_below_the_previous_one_warns_and_is_saved(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        await _entry(c, pid, 60)
        r = await _entry(c, pid, 45, period_label="2026-W11")
    assert r.status_code == 201, r.text
    assert rule_ids(r.json()["validation_warnings"]) == {"progress.reading_not_backwards"}


async def test_completion_needs_a_photo_or_a_note(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        bare = await _entry(c, pid, 100)
        noted = await _entry(c, pid, 100, period_label="2026-W11", notes="Signed off with the clerk of works")
    assert rule_ids(bare.json()["validation_warnings"]) == {"progress.completion_evidenced"}
    assert noted.json()["validation_warnings"] == []


async def test_a_plan_point_below_an_earlier_period_warns(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        first = await _plan(c, pid, "2026-01", 20)
        second = await _plan(c, pid, "2026-02", 40)
        low = await _plan(c, pid, "2026-03", 30)
        middle = await _plan(c, pid, "2026-02", 25)
    assert first.json()["validation_warnings"] == [] and second.json()["validation_warnings"] == []
    assert rule_ids(low.json()["validation_warnings"]) == {"progress.plan_cumulative"}
    assert middle.json()["validation_warnings"] == []


async def test_plan_periods_compare_in_natural_order(db_session) -> None:
    uid, pid = await make_project(db_session)
    async with http(build_app(progress_router, "/v1/progress", db_session, uid)) as c:
        await _plan(c, pid, "W2", 10)
        await _plan(c, pid, "W10", 50)
        r = await _plan(c, pid, "W9", 30)
    assert r.json()["validation_warnings"] == []
