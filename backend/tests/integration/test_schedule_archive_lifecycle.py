"""Q05: reversible schedule archives, real PostgreSQL/FKs and HTTP RBAC.

Only authentication is supplied by the fixture. Route dependencies, project
ownership checks, schemas, repositories and SQL all run normally. Each test
uses a rollback-isolated test database, never an installation's database.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.exc import InvalidRequestError

from app.dependencies import get_current_user_payload, get_session
from app.modules.contracts.models import Contract, ContractMilestone
from app.modules.projects.models import Project
from app.modules.schedule import router as schedule_router
from app.modules.schedule import service as schedule_service
from app.modules.schedule.models import Activity, Schedule, ScheduleBaseline, ScheduleRelationship
from app.modules.schedule.permissions import register_schedule_permissions
from app.modules.schedule.schemas import ScheduleCreate
from app.modules.schedule.service import ScheduleService
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest.fixture(autouse=True)
def published(monkeypatch):
    register_schedule_permissions()
    events = []
    monkeypatch.setattr(schedule_service, "_safe_publish", AsyncMock())
    monkeypatch.setattr(
        schedule_service,
        "publish_after_commit",
        lambda _session, name, data=None, **_kwargs: events.append((name, data)),
    )
    return events


@asynccontextmanager
async def api(role="editor", permissions=()):
    async with transactional_session() as session:
        user = User(
            email=f"archive-{uuid.uuid4()}@example.test",
            full_name="Archive owner",
            hashed_password="x",
            role=role,
            is_active=True,
        )
        session.add(user)
        await session.flush()
        project = Project(name="Archive project", owner_id=user.id)
        session.add(project)
        await session.flush()
        service = ScheduleService(session)
        schedule = await service.create_schedule(
            ScheduleCreate(
                project_id=project.id,
                name="Contract programme",
                start_date="2026-10-01",
                metadata={"calendar": "kept"},
            )
        )
        payload = {"sub": str(user.id), "role": role, "permissions": list(permissions)}
        app = FastAPI()
        app.include_router(schedule_router.router, prefix="/schedule")

        async def current_session():
            yield session

        app.dependency_overrides[get_session] = current_session
        app.dependency_overrides[get_current_user_payload] = lambda: payload
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            yield client, session, service, schedule, project, payload


def url(schedule, suffix=""):
    return f"/schedule/schedules/{schedule.id}{suffix}"


@pytest.mark.asyncio
async def test_lifecycle_lock_does_not_present_unloaded_activities_as_empty():
    async with api() as (_client, session, service, schedule, _project, _payload):
        activity = Activity(
            schedule_id=schedule.id, name="Retained work", start_date="2026-10-01", end_date="2026-10-01"
        )
        session.add(activity)
        await session.flush()
        await session.refresh(schedule, ["activities"])
        assert len(schedule.activities) == 1

        locked = await service.schedule_repo.get_for_update(schedule.id)
        # A lifecycle read must not replace real work with a fabricated empty
        # collection in the session's identity map. Readers explicitly load it.
        with pytest.raises(InvalidRequestError):
            _ = locked.activities
        await session.refresh(locked, ["activities"])
        assert [item.id for item in locked.activities] == [activity.id]


@pytest.mark.asyncio
@pytest.mark.parametrize("previous", ["draft", "active", "completed", "frozen"])
async def test_archive_and_restore_are_idempotent_and_return_recorded_status(previous, published):
    async with api() as (client, session, service, schedule, _project, _payload):
        schedule.status = previous
        await session.flush()
        for _ in range(2):
            response = await client.delete(url(schedule))
            assert response.status_code == 204, response.text
            assert (await service.get_schedule(schedule.id)).status == "archived"
            history = dict(schedule.metadata_["_schedule_archive"])
            assert history["previous_status"] == previous
            if _ == 0:
                original_history = history
            else:
                assert history == original_history
        assert schedule.metadata_["calendar"] == "kept"
        restored = await client.post(url(schedule, "/restore/"))
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == previous
        assert restored.json()["metadata_"]["_schedule_archive"]["restore_used_fallback"] is False
        # Repeated restore does not rewind a later ordinary status update.
        changed = "active" if previous != "active" else "completed"
        assert (await client.patch(url(schedule), json={"status": changed})).status_code == 200
        assert (await client.post(url(schedule, "/restore/"))).json()["status"] == changed
        assert {name for name, _ in published} == {"schedule.schedule.updated"}


@pytest.mark.asyncio
async def test_archive_keeps_baseline_activity_dependency_boq_bim_and_payment_links(published):
    async with api() as (client, session, _service, schedule, project, _payload):
        first = Activity(
            schedule_id=schedule.id,
            name="Milestone",
            activity_type="milestone",
            start_date="2026-10-01",
            end_date="2026-10-01",
            duration_days=0,
            boq_position_ids=[str(uuid.uuid4())],
            bim_element_ids=["bim-global-id"],
        )
        second = Activity(
            schedule_id=schedule.id, name="Following", start_date="2026-10-02", end_date="2026-10-02", duration_days=1
        )
        session.add_all([first, second])
        await session.flush()
        edge = ScheduleRelationship(
            schedule_id=schedule.id, predecessor_id=first.id, successor_id=second.id, relationship_type="FS", lag_days=0
        )
        baseline = ScheduleBaseline(
            schedule_id=schedule.id,
            project_id=project.id,
            name="Signed baseline",
            baseline_date="2026-10-01",
            snapshot_data={"activity": str(first.id), "cost": "123.45"},
        )
        contract = Contract(project_id=project.id, code=f"Q05-{uuid.uuid4()}", title="Contract")
        session.add_all([edge, baseline, contract])
        await session.flush()
        payment = ContractMilestone(
            contract_id=contract.id,
            name="Milestone payment",
            schedule_id=schedule.id,
            activity_id=first.id,
            forecast_reached_date="2026-10-01",
        )
        session.add(payment)
        await session.flush()
        snapshot = dict(baseline.snapshot_data)
        positions = list(first.boq_position_ids)
        for method, suffix in (("delete", ""), ("post", "/restore/")):
            response = await client.request(method, url(schedule, suffix))
            assert response.status_code in (200, 204), response.text
            await session.refresh(baseline)
            await session.refresh(first)
            await session.refresh(edge)
            await session.refresh(payment)
            assert baseline.snapshot_data == snapshot
            assert first.boq_position_ids == positions
            assert first.bim_element_ids == ["bim-global-id"]
            assert (edge.predecessor_id, edge.successor_id) == (first.id, second.id)
            assert (payment.schedule_id, payment.activity_id, payment.forecast_reached_date) == (
                schedule.id,
                first.id,
                "2026-10-01",
            )
        assert all(name not in {"schedule.activities.cleared", "schedule.schedule.deleted"} for name, _ in published)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("delete", "", None),
        ("post", "/restore/", None),
        ("patch", "", {"status": "archived"}),
        ("delete", "/permanent/", None),
    ],
)
async def test_viewer_cannot_mutate_lifecycle(method, suffix, body):
    async with api("viewer") as (client, _session, _service, schedule, _project, _payload):
        response = await client.request(method, url(schedule, suffix), json=body)
        assert response.status_code == 403, response.text
        assert schedule.status == "draft"


@pytest.mark.asyncio
async def test_update_permission_does_not_bypass_archive_or_restore_guard():
    async with api("viewer", ["schedule.update"]) as (client, session, _service, schedule, _project, _payload):
        assert (await client.patch(url(schedule), json={"name": "Allowed edit"})).status_code == 200
        assert (await client.patch(url(schedule), json={"status": "archived"})).status_code == 403
        schedule.status = "archived"
        schedule.metadata_ = {"_schedule_archive": {"previous_status": "active"}}
        await session.flush()
        assert (await client.patch(url(schedule), json={"status": "active"})).status_code == 403
        assert (await client.post(url(schedule, "/restore/"))).status_code == 403
        assert schedule.status == "archived"


@pytest.mark.asyncio
async def test_patch_lifecycle_uses_server_history_and_cannot_replace_it():
    async with api() as (client, _session, _service, schedule, project, _payload):
        assert (await client.patch(url(schedule), json={"status": "frozen"})).status_code == 200
        archived = await client.patch(url(schedule), json={"status": "archived"})
        assert archived.status_code == 200
        assert archived.json()["metadata_"]["_schedule_archive"]["previous_status"] == "frozen"
        assert (await client.patch(url(schedule), json={"status": "active"})).status_code == 409
        assert (await client.patch(url(schedule), json={"status": None})).status_code == 422
        for metadata in ({"_schedule_archive": None}, {"_schedule_archive": {"previous_status": "active"}}):
            assert (await client.patch(url(schedule), json={"metadata": metadata})).status_code == 422
            assert (
                await client.post(
                    "/schedule/schedules/",
                    json={
                        "project_id": str(project.id),
                        "name": "Forged history",
                        "metadata": metadata,
                    },
                )
            ).status_code == 422
        for metadata in ({"custom": "new"}, None, {}):
            updated = await client.patch(url(schedule), json={"metadata": metadata})
            assert updated.status_code == 200, updated.text
            assert updated.json()["metadata_"]["_schedule_archive"]["previous_status"] == "frozen"
        restored = await client.patch(url(schedule), json={"status": "frozen"})
        assert restored.status_code == 200
        assert restored.json()["metadata_"]["custom"] == "new"


@pytest.mark.asyncio
@pytest.mark.parametrize("history", [None, "invalid", {}, {"previous_status": "archived"}, {"previous_status": []}])
async def test_legacy_archive_restores_draft_with_explicit_fallback_marker(history):
    async with api() as (client, session, _service, schedule, _project, _payload):
        schedule.status = "archived"
        schedule.metadata_ = {} if history is None else {"_schedule_archive": history}
        await session.flush()
        restored = await client.post(url(schedule, "/restore/"))
        assert restored.status_code == 200, restored.text
        assert restored.json()["status"] == "draft"
        assert restored.json()["metadata_"]["_schedule_archive"]["restore_used_fallback"] is True


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["editor", "viewer"])
async def test_explicit_purge_permission_does_not_override_admin_role_guard(role):
    async with api(role, ["schedule.purge"]) as (client, session, _service, schedule, _project, _payload):
        schedule.status = "archived"
        await session.flush()
        assert (await client.delete(url(schedule, "/permanent/"))).status_code == 403
        assert (await client.get(url(schedule, "/delete-impact/"))).json()["can_delete"] is False
        assert await session.get(Schedule, schedule.id) is not None


@pytest.mark.asyncio
async def test_admin_must_archive_before_purge_and_baselines_do_not_survive_purge(published):
    async with api("admin") as (client, session, _service, schedule, project, _payload):
        schedule_id = schedule.id
        baseline = ScheduleBaseline(
            schedule_id=schedule_id,
            project_id=project.id,
            name="Original",
            baseline_date="2026-10-01",
            snapshot_data={"kept_until_purge": True},
        )
        session.add(baseline)
        await session.flush()
        impact = (await client.get(url(schedule, "/delete-impact/"))).json()
        assert (impact["can_delete"], impact["blocked_reason"]) == (False, "schedule_not_archived")
        assert (await client.delete(url(schedule, "/permanent/"))).status_code == 409
        assert (await client.delete(url(schedule))).status_code == 204
        assert (await client.get(url(schedule, "/delete-impact/"))).json()["can_delete"] is True
        assert (await client.delete(url(schedule, "/permanent/"))).status_code == 204
        assert (await client.get(url(schedule))).status_code == 404
        assert (
            await session.execute(
                select(func.count()).select_from(ScheduleBaseline).where(ScheduleBaseline.schedule_id == schedule_id)
            )
        ).scalar_one() == 0
        assert [name for name, _ in published][-2:] == ["schedule.activities.cleared", "schedule.schedule.deleted"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "method,suffix,body",
    [
        ("delete", "", None),
        ("post", "/restore/", None),
        ("patch", "", {"status": "archived"}),
        ("get", "/delete-impact/", None),
    ],
)
async def test_other_project_is_indistinguishable_from_missing(method, suffix, body):
    async with api() as (client, session, service, _schedule, _project, _payload):
        foreign_user = User(
            email=f"other-{uuid.uuid4()}@example.test", full_name="Other", hashed_password="x", role="editor"
        )
        session.add(foreign_user)
        await session.flush()
        foreign_project = Project(name="Other project", owner_id=foreign_user.id)
        session.add(foreign_project)
        await session.flush()
        foreign = await service.create_schedule(ScheduleCreate(project_id=foreign_project.id, name="Other plan"))
        response = await client.request(method, url(foreign, suffix), json=body)
        assert response.status_code == 404, response.text
        assert foreign.status == "draft"
        response = await client.get(
            "/schedule/schedules/", params={"project_id": str(foreign_project.id), "archive_state": "all"}
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_archive_filters_count_before_pagination_and_preserve_internal_all_default():
    async with api() as (client, session, service, schedule, project, _payload):
        for state in ("active", "completed", "frozen", "archived", "archived"):
            other = await service.create_schedule(ScheduleCreate(project_id=project.id, name=f"Plan {state}"))
            other.status = state
        await session.flush()
        for archive_state, expected in ((None, 4), ("current", 4), ("archived", 2), ("all", 6)):
            params = {"project_id": str(project.id), "limit": 1, "offset": 1}
            if archive_state:
                params["archive_state"] = archive_state
            result = await client.get("/schedule/schedules/", params=params)
            assert result.status_code == 200, result.text
            assert result.json()["total"] == expected
            assert len(result.json()["items"]) == 1
            if archive_state == "archived":
                assert result.json()["items"][0]["status"] == "archived"
            elif archive_state != "all":
                assert result.json()["items"][0]["status"] != "archived"
        assert (await service.schedule_repo.list_for_project(project.id))[1] == 6
        assert (await service.list_schedules_for_project(project.id))[1] == 4
        assert (
            await client.get("/schedule/schedules/", params={"project_id": str(project.id), "archive_state": "bogus"})
        ).status_code == 422
