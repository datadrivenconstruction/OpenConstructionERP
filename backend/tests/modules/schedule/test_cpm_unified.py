"""One CPM entry point: permissions, calendar parity, summary rows and read-only risk analysis.

Routes run for real over in-memory repository stubs, so no database is needed.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.core.cpm import calculate_cpm
from app.dependencies import get_current_user_payload, get_session
from app.modules.schedule import router as schedule_router
from app.modules.schedule.permissions import register_schedule_permissions
from app.modules.schedule.schemas import ActivityCreate
from tests.unit.test_schedule_dependency_unification import _create_schedule, _make_service

SIX_DAY = {"work_days": [0, 1, 2, 3, 4, 5], "exceptions": ["2026-05-05"]}


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    register_schedule_permissions()

    async def _allow(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(schedule_router, "verify_project_access", _allow)


async def _act(svc, schedule_id, name, duration, *, after=None, kind="task", parent=None):
    deps = [{"activity_id": str(after), "type": "FS", "lag_days": 0}] if after else []
    return await svc.create_activity(
        ActivityCreate(
            schedule_id=schedule_id,
            name=name,
            start_date="2026-05-01",
            end_date="2026-06-01",
            duration_days=duration,
            activity_type=kind,
            parent_id=parent,
            dependencies=deps,
        )
    )


@asynccontextmanager
async def _api(role: str, *, calendar: dict | None = None):
    svc = _make_service()
    sched = await _create_schedule(svc)
    if calendar is not None:
        svc.schedule_repo.rows[sched.id].metadata_ = {"calendar": calendar}
    app = FastAPI()
    app.include_router(schedule_router.router, prefix="/schedule")
    payload = {"sub": str(uuid.uuid4()), "role": role, "permissions": []}

    async def _session():
        yield None

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_payload] = lambda: payload
    app.dependency_overrides[schedule_router._get_service] = lambda: svc
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, svc, sched


def _count_writes(svc) -> list[int]:
    calls: list[int] = []
    original = svc.activity_repo.bulk_update_fields

    async def spy(updates):
        calls.append(len(updates))
        await original(updates)

    svc.activity_repo.bulk_update_fields = spy
    return calls


@pytest.mark.asyncio
async def test_viewer_cannot_run_cpm_but_can_read_risk_and_editor_can_run():
    async with _api("viewer") as (client, svc, sched):
        a = await _act(svc, sched.id, "A", 3)
        await _act(svc, sched.id, "B", 2, after=a.id)
        writes = _count_writes(svc)
        assert (await client.post(f"/schedule/schedules/{sched.id}/calculate-cpm/")).status_code == 403
        assert (await client.post(f"/schedule/schedule/cpm/calculate/?schedule_id={sched.id}")).status_code == 403
        assert (await client.get(f"/schedule/schedules/{sched.id}/risk-analysis/")).status_code == 200
        assert writes == []
    async with _api("editor") as (client, svc, sched):
        a = await _act(svc, sched.id, "A", 3)
        await _act(svc, sched.id, "B", 2, after=a.id)
        assert (await client.post(f"/schedule/schedules/{sched.id}/calculate-cpm/")).status_code == 200
        assert (await client.post(f"/schedule/schedule/cpm/calculate/?schedule_id={sched.id}")).status_code == 200


@pytest.mark.asyncio
async def test_both_routes_share_the_calendar_aware_engine():
    async with _api("editor", calendar=SIX_DAY) as (client, svc, sched):
        a = await _act(svc, sched.id, "A", 6)
        b = await _act(svc, sched.id, "B", 4, after=a.id)
        await _act(svc, sched.id, "Side", 2, after=a.id)

        first = (await client.post(f"/schedule/schedules/{sched.id}/calculate-cpm/")).json()
        colours_one = {r.id: r.color for r in svc.activity_repo.rows.values()}
        second = (await client.post(f"/schedule/schedule/cpm/calculate/?schedule_id={sched.id}")).json()
        colours_two = {r.id: r.color for r in svc.activity_repo.rows.values()}

        def shape(body):
            return sorted(
                (r["name"], r["early_start"], r["early_finish"], r["total_float"]) for r in body["all_activities"]
            )

        assert shape(first) == shape(second)
        assert colours_one == colours_two
        expected = {
            r["name"]: r
            for r in await calculate_cpm(
                [
                    {"id": "A", "name": "A", "duration": 6},
                    {"id": "B", "name": "B", "duration": 4},
                    {"id": "Side", "name": "Side", "duration": 2},
                ],
                [
                    {"predecessor_id": "A", "successor_id": "B", "type": "FS", "lag": 0},
                    {"predecessor_id": "A", "successor_id": "Side", "type": "FS", "lag": 0},
                ],
                calendar=SIX_DAY,
                project_start_date=sched.start_date,
            )
        }
        got = {r["name"]: r for r in first["all_activities"]}
        assert got["B"]["early_start"] == expected["B"]["early_start"] > 6  # the holiday pushes it past day 6
        assert got["Side"]["total_float"] == expected["Side"]["total_float"] > 0
        assert svc.activity_repo.rows[b.id].is_critical is True
        assert svc.activity_repo.rows[b.id].color == "#ef4444"


@pytest.mark.asyncio
async def test_risk_get_leaves_activities_untouched():
    async with _api("viewer") as (client, svc, sched):
        a = await _act(svc, sched.id, "A", 3)
        await _act(svc, sched.id, "B", 2, after=a.id)
        before = {r.id: (r.color, r.updated_at, r.is_critical, r.total_float) for r in svc.activity_repo.rows.values()}
        writes = _count_writes(svc)
        assert (await client.get(f"/schedule/schedules/{sched.id}/risk-analysis/")).status_code == 200
        after = {r.id: (r.color, r.updated_at, r.is_critical, r.total_float) for r in svc.activity_repo.rows.values()}
        assert after == before
        assert writes == []


@pytest.mark.asyncio
async def test_summary_rows_stay_out_of_the_network_and_the_risk_figures():
    async with _api("editor") as (client, svc, sched):
        sec1 = await _act(svc, sched.id, "Section 1", 10, kind="summary")
        sec2 = await _act(svc, sched.id, "Section 2", 10, kind="summary")
        a = await _act(svc, sched.id, "A", 5, parent=sec1.id)
        b = await _act(svc, sched.id, "B", 5, after=a.id, parent=sec1.id)
        c = await _act(svc, sched.id, "C", 4, parent=sec2.id)
        summary_ids = {str(sec1.id), str(sec2.id)}

        before = (await client.get(f"/schedule/schedules/{sched.id}/risk-analysis/")).json()
        body = (await client.post(f"/schedule/schedules/{sched.id}/calculate-cpm/")).json()

        assert not summary_ids & {r["activity_id"] for r in body["critical_path"]}
        assert not summary_ids & {r["activity_id"] for r in body["all_activities"]}
        assert not summary_ids & {r["activity_id"] for r in before["activity_risks"]}
        rows = svc.activity_repo.rows
        for sid in (sec1.id, sec2.id):
            assert rows[sid].is_critical is False
            assert rows[sid].total_float is None
        assert rows[sec1.id].early_start == str(rows[a.id].early_start)
        assert rows[sec1.id].early_finish == str(rows[b.id].early_finish)
        assert rows[sec2.id].early_finish == str(rows[c.id].early_finish)

        # a plan without the summary rows gives the same P80
        async with _api("editor") as (client2, svc2, sched2):
            a2 = await _act(svc2, sched2.id, "A", 5)
            await _act(svc2, sched2.id, "B", 5, after=a2.id)
            await _act(svc2, sched2.id, "C", 4)
            plain = (await client2.get(f"/schedule/schedules/{sched2.id}/risk-analysis/")).json()
        assert plain["p80_days"] == before["p80_days"]
        assert plain["deterministic_days"] == before["deterministic_days"]
