# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""HTTP-layer verification of the ACAP layout-edit endpoints.

In-process FastAPI app mounting ONLY the acap router (mirrors
test_ai_agents_feedback.py's pattern: in-process app + httpx AsyncClient,
DB/auth dependencies overridden with a transaction-isolated PostgreSQL
session), so GET/PUT /projects/{project_id}/layout are exercised exactly as
the real app serves them - without booting the full module loader.

Covers:
  (a) PUT a valid plan -> 200, a new version is created (never overwrites).
  (b) PUT a plan with two overlapping rooms -> 422 with non-empty reasons.
  (c) GET after a PUT returns the saved plan + version.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    # FK triggers off: we seed a project without a real user row.
    async with transactional_session(disable_fks=True) as s:
        yield s


# The app authenticates as this owner; _make_project makes it the project owner
# so the Phase-8 per-project authz guards (require_project_owner/access) pass.
_TEST_OWNER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")


def _build_app(session) -> FastAPI:
    """A minimal app exposing the acap router with session/auth overridden."""
    from app.dependencies import get_current_user_payload
    from app.modules.acap.router import get_session as acap_get_session
    from app.modules.acap.router import router as acap_router

    app = FastAPI()
    app.include_router(acap_router, prefix="/api/v1/acap")

    async def _override_session():
        # Hand the app the SAME transactional session the test set up.
        yield session

    def _override_payload() -> dict:
        return {"sub": str(_TEST_OWNER)}

    app.dependency_overrides[acap_get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload
    return app


async def _make_project(session) -> uuid.UUID:
    """Create a bare Project owned by _TEST_OWNER and return its id."""
    from app.modules.projects.models import Project

    project = Project(name=f"ACAP {uuid.uuid4().hex[:6]}", currency="IDR", owner_id=_TEST_OWNER)
    session.add(project)
    await session.flush()
    return project.id


# --- Fixtures: plan payloads ------------------------------------------------


def _valid_plan() -> dict[str, Any]:
    """Kavling 8x15 m, one kamar_tidur + one sirkulasi - no overlap, within KDB."""
    return {
        "kavling": {"width_m": 8.0, "length_m": 15.0},
        "levels": [
            {
                "level": 1,
                "rooms": [
                    {
                        "name": "K. Tidur",
                        "type": "kamar_tidur",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 3.0, "y": 0.0},
                            {"x": 3.0, "y": 3.0},
                            {"x": 0.0, "y": 3.0},
                        ],
                        "area_m2": 9.0,
                    },
                    {
                        "name": "Sirkulasi",
                        "type": "sirkulasi",
                        "polygon": [
                            {"x": 3.0, "y": 0.0},
                            {"x": 5.0, "y": 0.0},
                            {"x": 5.0, "y": 2.0},
                            {"x": 3.0, "y": 2.0},
                        ],
                        "area_m2": 4.0,
                    },
                ],
            }
        ],
        "jumlah_lantai": 1,
    }


def _overlapping_plan() -> dict[str, Any]:
    """Kavling 10x10 m, two rooms that overlap -> geometrically invalid."""
    return {
        "kavling": {"width_m": 10.0, "length_m": 10.0},
        "levels": [
            {
                "level": 1,
                "rooms": [
                    {
                        "name": "A",
                        "type": "ruang_tamu",
                        "polygon": [
                            {"x": 0.0, "y": 0.0},
                            {"x": 4.0, "y": 0.0},
                            {"x": 4.0, "y": 4.0},
                            {"x": 0.0, "y": 4.0},
                        ],
                        "area_m2": 16.0,
                    },
                    {
                        "name": "B",
                        "type": "kamar_tidur",
                        "polygon": [
                            {"x": 2.0, "y": 2.0},
                            {"x": 6.0, "y": 2.0},
                            {"x": 6.0, "y": 6.0},
                            {"x": 2.0, "y": 6.0},
                        ],
                        "area_m2": 16.0,
                    },
                ],
            }
        ],
        "jumlah_lantai": 1,
    }


# --- (a) PUT a valid plan creates a new version -----------------------------


@pytest.mark.asyncio
async def test_put_valid_plan_creates_version(session):
    project_id = await _make_project(session)
    app = _build_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.put(f"/api/v1/acap/projects/{project_id}/layout", json=_valid_plan())
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["version"] == 1
    assert body["plan"]["kavling"]["width_m"] == 8.0
    assert len(body["plan"]["levels"][0]["rooms"]) == 2

    # A second PUT creates version 2 - never overwrites version 1.
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res2 = await ac.put(f"/api/v1/acap/projects/{project_id}/layout", json=_valid_plan())
    assert res2.status_code == 200, res2.text
    assert res2.json()["version"] == 2


# --- (b) PUT an invalid (overlapping) plan is rejected ----------------------


@pytest.mark.asyncio
async def test_put_overlapping_plan_rejected(session):
    project_id = await _make_project(session)
    app = _build_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.put(f"/api/v1/acap/projects/{project_id}/layout", json=_overlapping_plan())
    assert res.status_code == 422, res.text
    detail = res.json()["detail"]
    assert detail["detail"] == "Layout invalid"
    assert len(detail["reasons"]) > 0


# --- (c) GET after PUT returns the saved plan + version ---------------------


@pytest.mark.asyncio
async def test_get_returns_latest_saved_layout(session):
    project_id = await _make_project(session)
    app = _build_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        put_res = await ac.put(f"/api/v1/acap/projects/{project_id}/layout", json=_valid_plan())
        assert put_res.status_code == 200, put_res.text

        get_res = await ac.get(f"/api/v1/acap/projects/{project_id}/layout")
    assert get_res.status_code == 200, get_res.text
    body = get_res.json()
    assert body["version"] == 1
    assert body["status"] == "edited"
    assert body["plan"]["kavling"]["length_m"] == 15.0


@pytest.mark.asyncio
async def test_get_no_layout_returns_404(session):
    project_id = await _make_project(session)
    app = _build_app(session)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        res = await ac.get(f"/api/v1/acap/projects/{project_id}/layout")
    assert res.status_code == 404, res.text
    assert res.json()["detail"] == "No layout for this project"
