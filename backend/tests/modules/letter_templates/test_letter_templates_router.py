# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Letter templates API: precedence project > company > default, rules on save, permissions."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.dependencies import get_current_user_id, get_current_user_payload, get_session
from app.modules.letter_templates.models import LetterTemplateOverride  # noqa: F401 - registers ORM
from app.modules.letter_templates.permissions import register_letter_templates_permissions
from app.modules.letter_templates.router import router as lt_router
from app.modules.projects.models import Project
from app.modules.users.models import User
from tests._pg import transactional_session

KEY = "tendering.award_letter"
BODY = "Dear {bidder}, we award {package} for {amount}."


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    async with transactional_session() as s:
        yield s


async def _user(session) -> uuid.UUID:
    u = User(email=f"lt-{uuid.uuid4().hex[:8]}@example.com", hashed_password="x", role="admin")
    session.add(u)
    await session.flush()
    return u.id


async def _project(session, owner_id: uuid.UUID, locale: str = "de") -> uuid.UUID:
    p = Project(name="Letters", owner_id=owner_id, locale=locale)
    session.add(p)
    await session.flush()
    return p.id


def _app(db_session, caller_id: str, role: str = "admin", permissions: list[str] | None = None) -> FastAPI:
    register_letter_templates_permissions()
    app = FastAPI()
    app.include_router(lt_router, prefix="/lt")

    async def _session():
        yield db_session

    async def _uid() -> str:
        return caller_id

    async def _payload() -> dict:
        return {"sub": caller_id, "role": role, "permissions": permissions or []}

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_current_user_id] = _uid
    app.dependency_overrides[get_current_user_payload] = _payload
    return app


@asynccontextmanager
async def _http(app: FastAPI) -> AsyncIterator[AsyncClient]:
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        yield client


@pytest.mark.asyncio
async def test_project_beats_company_beats_default(db_session) -> None:
    uid = await _user(db_session)
    pid = await _project(db_session, uid, locale="de")
    await db_session.commit()
    async with _http(_app(db_session, str(uid))) as c:
        r = await c.get(f"/lt/{KEY}", params={"project_id": str(pid)})
        assert r.status_code == 200, r.text
        assert r.json()["source"] == "default"
        assert r.json()["language"] == "de", "the letter reads the project's language"
        assert "Sehr geehrte" in r.json()["text"]["body"]

        r = await c.put(f"/lt/{KEY}", json={"language": "de", "body": "Firma " + BODY})
        assert r.status_code == 200, r.text
        r = await c.get(f"/lt/{KEY}", params={"project_id": str(pid)})
        assert r.json()["source"] == "company"

        r = await c.put(f"/lt/{KEY}", json={"language": "de", "project_id": str(pid), "body": "Projekt " + BODY})
        assert r.status_code == 200, r.text
        r = await c.get(f"/lt/{KEY}", params={"project_id": str(pid)})
        assert (r.json()["source"], r.json()["text"]["body"][:7]) == ("project", "Projekt")

        r = await c.delete(f"/lt/{KEY}", params={"language": "de", "project_id": str(pid)})
        assert r.status_code == 204
        r = await c.get(f"/lt/{KEY}", params={"project_id": str(pid)})
        assert r.json()["source"] == "company"

        listing = (await c.get("/lt/")).json()
        award = next(t for t in listing["items"] if t["key"] == KEY)
        assert award["customised_languages"] == ["de"]


@pytest.mark.asyncio
async def test_save_refuses_errors_and_keeps_warnings(db_session) -> None:
    uid = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(uid))) as c:
        r = await c.put(f"/lt/{KEY}", json={"language": "en", "body": "{package} {bonus} {amount}"})
        assert r.status_code == 422
        r = await c.put(f"/lt/{KEY}", json={"language": "en", "body": ""})
        assert r.status_code == 422
        r = await c.put(f"/lt/{KEY}", json={"language": "en", "body": "We award {package}."})
        assert r.status_code == 200
        assert [i["placeholder"] for i in r.json()["issues"]] == ["amount"]
        r = await c.post(f"/lt/{KEY}/validate", json={"body": "{nope}"})
        assert {i["code"] for i in r.json()} >= {"unknown_placeholder"}


@pytest.mark.asyncio
async def test_editor_reads_but_cannot_change_a_template(db_session) -> None:
    uid = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(uid), role="editor")) as c:
        assert (await c.get(f"/lt/{KEY}")).status_code == 200
        r = await c.put(f"/lt/{KEY}", json={"language": "en", "body": BODY})
        assert r.status_code == 403
        assert (await c.delete(f"/lt/{KEY}", params={"language": "en"})).status_code == 403
    async with _http(_app(db_session, str(uid), role="manager")) as c:
        assert (await c.put(f"/lt/{KEY}", json={"language": "en", "body": BODY})).status_code == 200
    async with _http(_app(db_session, str(uid), role="viewer")) as c:
        assert (await c.get(f"/lt/{KEY}")).status_code == 403


@pytest.mark.asyncio
async def test_preview_renders_a_pdf_from_unsaved_text(db_session) -> None:
    uid = await _user(db_session)
    await db_session.commit()
    async with _http(_app(db_session, str(uid))) as c:
        r = await c.post(f"/lt/{KEY}/preview", json={"language": "de", "body": BODY})
        assert r.status_code == 200
        assert r.content.startswith(b"%PDF")
        assert (await c.get("/lt/nope.nothing")).status_code == 404
