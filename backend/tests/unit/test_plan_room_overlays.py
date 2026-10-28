"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Baseline unit tests for the Plan Room overlays endpoint.

Scope (tight, DB-backed):
    1. The overlays composite groups a document page's defect pins, markups and
       plan pins by page: a source on another page - and a punch pin with no
       drawing coordinate - is excluded from the page's overlay. Document-level
       photos surface for every page.
    2. A positioned plan pin created via the router round-trips into the overlay
       and can be deleted again.

Uses a PostgreSQL session wrapped in an outer transaction rolled back on
teardown (``tests._pg.transactional_session``) and the FastAPI app via
``httpx.ASGITransport``. Auth + session dependencies are overridden so the test
isolates the aggregation and the project-access gate; the caller owns the
project, so the real ``verify_project_access`` (called directly by the router)
passes.
"""

from __future__ import annotations

import uuid
from typing import AsyncIterator

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI

from app.dependencies import (
    get_current_user_id,
    get_current_user_payload,
    get_session,
)
from app.modules.documents.models import Document, ProjectPhoto
from app.modules.markups.models import Markup
from app.modules.plan_room.models import PlanPin
from app.modules.plan_room.router import router as plan_room_router
from app.modules.projects.models import Project
from app.modules.punchlist.models import PunchItem
from app.modules.users.models import User
from tests._pg import transactional_session

# -- Fixtures ---------------------------------------------------------------


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator:
    """PostgreSQL session isolated by an outer transaction, rolled back on exit."""
    async with transactional_session() as s:
        yield s


async def _make_user(session) -> uuid.UUID:
    user = User(email=f"u{uuid.uuid4().hex[:8]}@example.com", hashed_password="x")
    session.add(user)
    await session.flush()
    await session.refresh(user)
    return user.id


async def _make_project(session, owner_id: uuid.UUID) -> uuid.UUID:
    project = Project(name="Plan Room Test", owner_id=owner_id)
    session.add(project)
    await session.flush()
    await session.refresh(project)
    return project.id


async def _make_document(session, project_id: uuid.UUID) -> Document:
    doc = Document(
        project_id=project_id,
        name="A-101 Floor Plan.pdf",
        revision_code="C.01",
        is_current_revision=True,
    )
    session.add(doc)
    await session.flush()
    await session.refresh(doc)
    return doc


def _build_app(db_session, *, caller_id: str) -> FastAPI:
    """Mount the plan-room router with auth + session overrides.

    The payload override hands ``RequirePermission`` an admin role so the RBAC
    gate short-circuits; ``verify_project_access`` is the real function (the
    router calls it directly) and passes because the caller owns the project.
    """
    app = FastAPI()
    app.include_router(plan_room_router, prefix="/v1/plan-room")

    async def _session_override():
        yield db_session

    async def _user_override() -> str:
        return caller_id

    async def _payload_override() -> dict:
        return {"sub": caller_id, "role": "admin", "permissions": []}

    app.dependency_overrides[get_session] = _session_override
    app.dependency_overrides[get_current_user_id] = _user_override
    app.dependency_overrides[get_current_user_payload] = _payload_override
    return app


# -- 1. Overlay grouping + off-page exclusion -------------------------------


class TestOverlaysGrouping:
    @pytest.mark.asyncio
    async def test_overlays_group_by_page_and_exclude_off_page(self, db_session):
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        document = await _make_document(db_session, project_id)
        doc_id = str(document.id)

        # Punch pin ON page 2 with a drawing coordinate -> included.
        db_session.add(
            PunchItem(
                project_id=project_id,
                document_id=doc_id,
                page=2,
                location_x=0.25,
                location_y=0.75,
                title="Cracked tile",
                status="open",
                priority="high",
            )
        )
        # Punch pin on page 2 but WITHOUT a coordinate -> excluded from pins.
        db_session.add(
            PunchItem(
                project_id=project_id,
                document_id=doc_id,
                page=2,
                title="Unplaced defect",
                status="open",
            )
        )
        # Punch pin on page 3 -> excluded from the page-2 overlay.
        db_session.add(
            PunchItem(
                project_id=project_id,
                document_id=doc_id,
                page=3,
                location_x=0.1,
                location_y=0.1,
                title="Other page defect",
                status="open",
            )
        )
        # Markups: one on page 2 (included), one on page 3 (excluded).
        db_session.add(
            Markup(
                project_id=project_id,
                document_id=doc_id,
                page=2,
                type="rectangle",
                author_id="tester",
                label="Zone A",
            )
        )
        db_session.add(
            Markup(
                project_id=project_id,
                document_id=doc_id,
                page=3,
                type="cloud",
                author_id="tester",
            )
        )
        # Plan pins: one on page 2 (included), one on page 3 (excluded).
        db_session.add(PlanPin(project_id=project_id, document_id=doc_id, page=2, x=0.5, y=0.5, note="Check outlet"))
        db_session.add(PlanPin(project_id=project_id, document_id=doc_id, page=3, x=0.2, y=0.2, note="Off page"))
        # Photo attached to the document (document-level, no page).
        db_session.add(
            ProjectPhoto(
                project_id=project_id,
                document_id=doc_id,
                filename="site1.jpg",
                file_path="/uploads/site1.jpg",
                caption="North elevation",
            )
        )
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/v1/plan-room/{doc_id}/pages/2/overlays")

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["document_id"] == doc_id
        assert body["page"] == 2
        assert body["version"]["revision_code"] == "C.01"
        assert body["version"]["is_current_revision"] is True

        # Pins: exactly the page-2 punch (with coord) + the page-2 plan pin.
        assert sorted(p["kind"] for p in body["pins"]) == ["plan", "punch"]
        punch = next(p for p in body["pins"] if p["kind"] == "punch")
        assert punch["title"] == "Cracked tile"
        assert punch["x"] == 0.25
        assert punch["y"] == 0.75
        assert punch["priority"] == "high"
        plan = next(p for p in body["pins"] if p["kind"] == "plan")
        assert plan["note"] == "Check outlet"

        # Markups: only the page-2 one.
        assert len(body["markups"]) == 1
        assert body["markups"][0]["label"] == "Zone A"

        # Photos: the document-level photo shows regardless of page.
        assert len(body["photos"]) == 1
        assert body["photos"][0]["filename"] == "site1.jpg"


# -- 2. Pin create -> overlay -> delete round-trip --------------------------


class TestPinRoundTrip:
    @pytest.mark.asyncio
    async def test_create_pin_appears_in_overlay_then_delete(self, db_session):
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        document = await _make_document(db_session, project_id)
        doc_id = str(document.id)
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            create = await client.post(
                f"/v1/plan-room/{doc_id}/pages/1/pins",
                json={"page": 1, "x": 0.4, "y": 0.6, "note": "Verify riser"},
            )
            assert create.status_code == 201, create.text
            pin_id = create.json()["id"]

            overlays = await client.get(f"/v1/plan-room/{doc_id}/pages/1/overlays")
            assert overlays.status_code == 200, overlays.text
            plan_pins = [p for p in overlays.json()["pins"] if p["kind"] == "plan"]
            assert len(plan_pins) == 1
            assert plan_pins[0]["id"] == pin_id
            assert plan_pins[0]["note"] == "Verify riser"

            deleted = await client.delete(f"/v1/plan-room/pins/{pin_id}")
            assert deleted.status_code == 204, deleted.text

            after = await client.get(f"/v1/plan-room/{doc_id}/pages/1/overlays")
            assert [p for p in after.json()["pins"] if p["kind"] == "plan"] == []

    @pytest.mark.asyncio
    async def test_body_page_must_match_url_page(self, db_session):
        owner_id = await _make_user(db_session)
        owner = str(owner_id)
        project_id = await _make_project(db_session, owner_id)
        document = await _make_document(db_session, project_id)
        doc_id = str(document.id)
        await db_session.commit()

        app = _build_app(db_session, caller_id=owner)
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/v1/plan-room/{doc_id}/pages/1/pins",
                json={"page": 2, "x": 0.4, "y": 0.6},
            )
        assert resp.status_code == 400, resp.text
