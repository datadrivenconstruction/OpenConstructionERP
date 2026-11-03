"""Legacy progress-update endpoints validate input and gate approval.

Routes run for real over a small in-memory session double.
"""

from __future__ import annotations

import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.sql.dml import Update

from app.dependencies import get_current_user_payload, get_session
from app.modules.schedule import router as schedule_router
from app.modules.schedule.permissions import register_schedule_permissions

PROJECT = uuid.uuid4()


class _Session:
    def __init__(self) -> None:
        self.rows: dict[uuid.UUID, Any] = {}

    def add(self, obj: Any) -> None:
        obj.id = obj.id or uuid.uuid4()
        obj.metadata_ = obj.metadata_ or {}
        obj.created_at = obj.updated_at = datetime.now(UTC)
        self.rows[obj.id] = obj

    async def flush(self) -> None:
        return None

    async def get(self, _model: Any, key: uuid.UUID) -> Any:
        return self.rows.get(key)

    async def scalar(self, *_args: Any, **_kwargs: Any) -> None:
        return None

    async def execute(self, stmt: Any) -> None:
        assert isinstance(stmt, Update)
        params = dict(stmt.compile().params)
        target = self.rows[params.pop("id_1")]
        for key, value in params.items():
            if key != "updated_at":  # the double has no onupdate hook
                setattr(target, key, value)

    def expire_all(self) -> None:
        return None


@pytest.fixture(autouse=True)
def _perms(monkeypatch):
    register_schedule_permissions()

    async def _allow(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr(schedule_router, "verify_project_access", _allow)


@asynccontextmanager
async def _api(role: str):
    session = _Session()
    user_id = str(uuid.uuid4())
    app = FastAPI()
    app.include_router(schedule_router.router, prefix="/schedule")

    async def _get_session():
        yield session

    app.dependency_overrides[get_session] = _get_session
    app.dependency_overrides[get_current_user_payload] = lambda: {"sub": user_id, "role": role, "permissions": []}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client, session, user_id


def _body(**over: Any) -> dict[str, Any]:
    body = {"project_id": str(PROJECT), "update_date": "2026-05-01", "progress_pct": "40"}
    body.update(over)
    return body


URL = "/schedule/progress-updates/"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "over",
    [
        {"progress_pct": "150"},
        {"progress_pct": "-1"},
        {"progress_pct": "abc"},
        {"remaining_duration": "-3"},
        {"remaining_duration": "soon"},
        {"update_date": "yesterday"},
        {"actual_start": "2026-13-40"},
        {"actual_start": "2026-05-10", "actual_finish": "2026-05-01"},
        {"update_date": (datetime.now(UTC) + timedelta(days=5)).date().isoformat()},
    ],
)
async def test_invalid_input_is_rejected(over):
    async with _api("editor") as (client, session, _uid):
        assert (await client.post(URL, json=_body(**over))).status_code == 422
        assert session.rows == {}


@pytest.mark.asyncio
async def test_valid_input_is_stored_and_caller_is_the_submitter():
    async with _api("editor") as (client, _session, uid):
        forged = str(uuid.uuid4())
        resp = await client.post(
            URL,
            json=_body(
                progress_pct="42.50",
                remaining_duration=4,
                actual_start="2026-05-01",
                actual_finish="2026-05-09",
                status="submitted",
                submitted_by=forged,
                approved_by=forged,
            ),
        )
        assert resp.status_code == 201, resp.text
        data = resp.json()
        assert data["progress_pct"] == "42.5"
        assert data["remaining_duration"] == "4"
        assert data["submitted_by"] == uid
        assert data["approved_by"] is None


@pytest.mark.asyncio
async def test_editor_cannot_approve_but_manager_can_and_is_recorded():
    async with _api("editor") as (client, session, _uid):
        assert (await client.post(URL, json=_body(status="approved"))).status_code == 403
        assert session.rows == {}
        created = (await client.post(URL, json=_body(status="submitted"))).json()
        patch = await client.patch(f"{URL}{created['id']}", json={"status": "approved"})
        assert patch.status_code == 403
    async with _api("manager") as (client, _session, uid):
        resp = await client.post(URL, json=_body(status="approved", approved_by=str(uuid.uuid4())))
        assert resp.status_code == 201, resp.text
        assert resp.json()["approved_by"] == uid


@pytest.mark.asyncio
async def test_approved_record_is_read_only_except_notes_and_activity_cannot_move():
    async with _api("manager") as (client, _session, _uid):
        created = (await client.post(URL, json=_body(status="approved"))).json()
        rid = created["id"]
        assert (await client.patch(f"{URL}{rid}", json={"progress_pct": "10"})).status_code == 409
        assert (await client.patch(f"{URL}{rid}", json={"status": "draft"})).status_code == 409
        noted = await client.patch(f"{URL}{rid}", json={"notes": "checked on site"})
        assert noted.status_code == 200, noted.text
        assert noted.json()["notes"] == "checked on site"
        assert noted.json()["progress_pct"] == "40"
        assert (await client.patch(f"{URL}{rid}", json={"activity_id": str(uuid.uuid4())})).status_code == 422


@pytest.mark.asyncio
async def test_patch_validates_and_checks_dates_against_the_stored_record():
    async with _api("editor") as (client, _session, _uid):
        created = (await client.post(URL, json=_body(actual_start="2026-05-10"))).json()
        rid = created["id"]
        assert (await client.patch(f"{URL}{rid}", json={"progress_pct": "150"})).status_code == 422
        assert (await client.patch(f"{URL}{rid}", json={"actual_finish": "2026-05-01"})).status_code == 422
        ok = await client.patch(f"{URL}{rid}", json={"actual_finish": "2026-05-12", "progress_pct": "75"})
        assert ok.status_code == 200, ok.text
        assert ok.json()["progress_pct"] == "75"
