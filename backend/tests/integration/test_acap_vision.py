# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""HTTP-layer + unit verification of the ACAP Gemini-vision extract path.

Three deterministic cases (NO live API calls):

  (a) ``vision_service_configured()`` reflects ``GOOGLE_API_KEY`` env var.
  (b) ``build_draft_plan(extract)`` produces a correct FloorPlan-shaped dict
      with CCW polygon, computed area_m2, and valid/invalid from the layout
      validator.
  (c) The extract endpoint returns 400 with ``reason == "GOOGLE_API_KEY not set"``
      when the env var is absent (but authz passes).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from tests._pg import transactional_session


@pytest_asyncio.fixture
async def session():
    async with transactional_session(disable_fks=True) as s:
        yield s


_TEST_OWNER = uuid.UUID("00000000-0000-0000-0000-0000000000aa")
_TEST_OTHER = uuid.UUID("00000000-0000-0000-0000-0000000000bb")


def _build_app(session, *, user_id=_TEST_OWNER) -> FastAPI:
    from app.dependencies import get_current_user_payload
    from app.modules.acap.router import get_session as acap_get_session
    from app.modules.acap.router import router as acap_router

    app = FastAPI()
    app.include_router(acap_router, prefix="/api/v1/acap")

    async def _override_session():
        yield session

    def _override_payload() -> dict:
        return {"sub": str(user_id)}

    app.dependency_overrides[acap_get_session] = _override_session
    app.dependency_overrides[get_current_user_payload] = _override_payload
    return app


async def _make_project(session, owner_id=_TEST_OWNER) -> uuid.UUID:
    from app.modules.projects.models import Project

    project = Project(name=f"ACAP {uuid.uuid4().hex[:6]}", currency="IDR", owner_id=owner_id)
    session.add(project)
    await session.flush()
    return project.id


# ── Test (a) vision_service_configured ─────────────────────────────────────


@pytest.mark.asyncio
async def test_vision_service_configured(monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    from app.modules.acap.vision.client import vision_service_configured

    assert vision_service_configured() is False

    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")
    assert vision_service_configured() is True


_EXTRACT_FIXTURE = {
    "kavling_width_m": 12.32,
    "kavling_length_m": 12.47,
    "levels": [
        {
            "level": 1,
            "rooms": [
                {
                    "name": "Ruang Tamu",
                    "type": "ruang_tamu",
                    "x_m": 0.0,
                    "y_m": 0.0,
                    "width_m": 5.92,
                    "length_m": 4.2,
                }
            ],
        }
    ],
}


# ── Test (b) build_draft_plan ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_build_draft_plan():
    from app.modules.acap.vision.extractor import build_draft_plan

    draft, valid, reasons = build_draft_plan(_EXTRACT_FIXTURE)

    room = draft["levels"][0]["rooms"][0]
    assert room["polygon"] == [
        {"x": 0.0, "y": 0.0},
        {"x": 5.92, "y": 0.0},
        {"x": 5.92, "y": 4.2},
        {"x": 0.0, "y": 4.2},
    ]
    assert room["area_m2"] == 24.864

    assert valid is True
    assert reasons == []


# ── Test (c) extract endpoint returns 400 when key absent ──────────────────


class _FakeStorage:
    def __init__(self, content: bytes = b"fake-image-data"):
        self.content = content

    async def get(self, key: str) -> bytes:
        return self.content

    async def put(self, key: str, content: bytes) -> None:
        pass


# ── build_draft_plan: invalid + unknown-type paths (pure, offline) ──────────


_EXTRACT_OVERLAP_FIXTURE = {
    "kavling_width_m": 10.0,
    "kavling_length_m": 10.0,
    "levels": [
        {
            "level": 1,
            "rooms": [
                {"name": "A", "type": "ruang_tamu", "x_m": 0.0, "y_m": 0.0, "width_m": 4.0, "length_m": 4.0},
                {"name": "B", "type": "ruang_tamu", "x_m": 0.0, "y_m": 0.0, "width_m": 4.0, "length_m": 4.0},
            ],
        }
    ],
}

_EXTRACT_UNKNOWN_TYPE_FIXTURE = {
    "kavling_width_m": 10.0,
    "kavling_length_m": 10.0,
    "levels": [
        {
            "level": 1,
            "rooms": [
                {"name": "Ruang Rahasia", "type": "gudang_rahasia", "x_m": 0.0, "y_m": 0.0, "width_m": 4.0, "length_m": 4.0},
            ],
        }
    ],
}


@pytest.mark.asyncio
async def test_build_draft_plan_invalid():
    """Two overlapping rooms → validator rejects; still returns a draft dict."""
    from app.modules.acap.vision.extractor import build_draft_plan

    draft, valid, reasons = build_draft_plan(_EXTRACT_OVERLAP_FIXTURE)

    assert valid is False
    assert reasons  # non-empty — at minimum the overlap is flagged
    # A draft dict is still returned (never a 500) even on the invalid path.
    assert draft["levels"][0]["rooms"]


@pytest.mark.asyncio
async def test_build_draft_plan_unknown_type_maps_to_other():
    """An unrecognized room type degrades to 'other' rather than crashing."""
    from app.modules.acap.vision.extractor import build_draft_plan

    draft, _valid, _reasons = build_draft_plan(_EXTRACT_UNKNOWN_TYPE_FIXTURE)

    assert draft["levels"][0]["rooms"][0]["type"] == "other"


# ── extract endpoint: never-persists invariant + authz ──────────────────────


@pytest.mark.asyncio
async def test_extract_never_persists(session, monkeypatch):
    """A successful extract returns a draft but writes ZERO FloorPlanRecords.

    Proves the invariant "extract NEVER writes oe_acap_floor_plan" — the draft
    is handed back for manual confirmation; only saveLayout persists.
    """
    monkeypatch.setenv("GOOGLE_API_KEY", "test-key")

    async def _fake_extract(image_bytes, mime_type, *, client=None):
        return _EXTRACT_FIXTURE

    monkeypatch.setattr(
        "app.modules.acap.vision.client.extract_floor_plan", _fake_extract
    )

    from sqlalchemy import func, select

    from app.modules.acap.models.floor_plan import FloorPlanRecord
    from app.modules.acap.models.plan_image import PlanImageRecord

    pid = await _make_project(session, _TEST_OWNER)
    image = PlanImageRecord(
        project_id=pid,
        filename="test.png",
        content_type="image/png",
        size_bytes=16,
        storage_key=f"acap/plan-images/{pid}/test.png",
        status="uploaded",
    )
    session.add(image)
    await session.flush()

    fake = _FakeStorage(b"\x89PNG\r\n\x1a\n" + b"0" * 100)
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    app = _build_app(session, user_id=_TEST_OWNER)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images/{image.id}/extract",
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "draft_plan" in body
    assert body["draft_plan"]["levels"][0]["rooms"][0]["area_m2"] == 24.864

    count = (
        await session.execute(
            select(func.count())
            .select_from(FloorPlanRecord)
            .where(FloorPlanRecord.project_id == pid)
        )
    ).scalar_one()
    assert count == 0  # extract NEVER writes oe_acap_floor_plan


@pytest.mark.asyncio
async def test_extract_non_owner_forbidden(session, monkeypatch):
    """A non-owner cannot extract another project's plan image."""
    from app.modules.acap.models.plan_image import PlanImageRecord

    pid = await _make_project(session, _TEST_OWNER)
    image = PlanImageRecord(
        project_id=pid,
        filename="test.png",
        content_type="image/png",
        size_bytes=16,
        storage_key=f"acap/plan-images/{pid}/test.png",
        status="uploaded",
    )
    session.add(image)
    await session.flush()

    app = _build_app(session, user_id=_TEST_OTHER)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images/{image.id}/extract",
            )

    assert resp.status_code in (403, 404), resp.text


@pytest.mark.asyncio
async def test_extract_endpoint_returns_400_when_key_absent(session, monkeypatch):
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    from app.modules.acap.models.plan_image import PlanImageRecord

    pid = await _make_project(session, _TEST_OWNER)

    image = PlanImageRecord(
        project_id=pid,
        filename="test.png",
        content_type="image/png",
        size_bytes=16,
        storage_key=f"acap/plan-images/{pid}/test.png",
        status="uploaded",
    )
    session.add(image)
    await session.flush()

    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    app = _build_app(session, user_id=_TEST_OWNER)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images/{image.id}/extract",
            )

    assert resp.status_code == 400, resp.text
    body = resp.json()
    assert body["detail"]["reason"] == "GOOGLE_API_KEY not set"
