"""Permanent delete of an archived project (POST /projects/{id}/purge/).

Archive stays the first step; the purge refuses an active project, a wrong typed
name and a non-owner, and removes the rows and uploaded files of an archived one.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

from app.config import Settings
from app.dependencies import get_current_user_payload, get_session
from app.modules.documents import service as docs_service
from app.modules.documents.models import Document
from app.modules.projects import router as projects_router
from app.modules.projects.models import Project
from app.modules.projects.schemas import ProjectCreate
from app.modules.projects.service import ProjectService
from app.modules.users.models import User
from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session() as s:
        yield s


async def _user(session, role="editor") -> User:
    user = User(email=f"p-{uuid.uuid4().hex}@test.local", hashed_password="x", full_name="U", role=role)
    session.add(user)
    await session.flush()
    return user


def _client(session, user_id, role="editor") -> AsyncClient:
    app = FastAPI()
    app.include_router(projects_router.router, prefix="/projects")

    async def current_session():
        yield session

    app.dependency_overrides[get_session] = current_session
    app.dependency_overrides[get_current_user_payload] = lambda: {
        "sub": str(user_id),
        "role": role,
        "permissions": ["*"],
    }
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _archived_project(session, owner: User, tmp_path, monkeypatch):
    monkeypatch.setattr(docs_service, "UPLOAD_BASE", tmp_path / "uploads")
    service = ProjectService(session, Settings(_env_file=None))
    project = await service.create_project(ProjectCreate(name="Tower A"), owner.id)
    stored = docs_service.UPLOAD_BASE / str(project.id) / "abc_plan.pdf"
    stored.parent.mkdir(parents=True)
    stored.write_bytes(b"%PDF-1.4")
    session.add(Document(project_id=project.id, name="plan.pdf", file_path=str(stored)))
    await session.flush()
    await service.delete_project(project.id, changed_by=str(owner.id))
    return project.id, stored


@pytest.mark.asyncio
async def test_archive_then_purge_removes_rows_and_files(session, tmp_path, monkeypatch):
    owner = await _user(session)
    pid, stored = await _archived_project(session, owner, tmp_path, monkeypatch)
    async with _client(session, owner.id) as client:
        resp = await client.post(f"/projects/{pid}/purge/", json={"confirm_name": "Tower A"})
    assert resp.status_code == 200, resp.text
    assert resp.json()["removed_files"] >= 1
    assert (await session.execute(select(func.count()).select_from(Project).where(Project.id == pid))).scalar() == 0
    docs = await session.execute(select(func.count()).select_from(Document).where(Document.project_id == pid))
    assert docs.scalar() == 0
    assert not stored.exists()


@pytest.mark.asyncio
async def test_non_owner_cannot_purge(session, tmp_path, monkeypatch):
    owner = await _user(session)
    other = await _user(session)
    pid, _ = await _archived_project(session, owner, tmp_path, monkeypatch)
    async with _client(session, other.id) as client:
        resp = await client.post(f"/projects/{pid}/purge/", json={"confirm_name": "Tower A"})
    assert resp.status_code == 403
    assert (await session.execute(select(func.count()).select_from(Project).where(Project.id == pid))).scalar() == 1


@pytest.mark.asyncio
async def test_admin_can_purge_and_active_project_is_refused(session, tmp_path, monkeypatch):
    owner = await _user(session)
    admin = await _user(session, role="admin")
    service = ProjectService(session, Settings(_env_file=None))
    active = await service.create_project(ProjectCreate(name="Live"), owner.id)
    async with _client(session, owner.id) as client:
        resp = await client.post(f"/projects/{active.id}/purge/", json={"confirm_name": "Live"})
    assert resp.status_code == 409
    pid, _ = await _archived_project(session, owner, tmp_path, monkeypatch)
    async with _client(session, admin.id, role="admin") as client:
        resp = await client.post(f"/projects/{pid}/purge/", json={"confirm_name": "Tower A"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_wrong_typed_name_is_refused(session, tmp_path, monkeypatch):
    owner = await _user(session)
    pid, _ = await _archived_project(session, owner, tmp_path, monkeypatch)
    async with _client(session, owner.id) as client:
        resp = await client.post(f"/projects/{pid}/purge/", json={"confirm_name": "tower"})
    assert resp.status_code == 400
