"""Tests for ACAP interior render — prompts, model, endpoints."""

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


async def _insert_floor_plan(session, project_id):
    """Insert a minimal FloorPlanRecord with a valid plan_json."""
    from app.modules.acap.models.floor_plan import FloorPlanRecord, next_version

    version = await next_version(session, project_id)
    record = FloorPlanRecord(
        project_id=project_id,
        version=version,
        requirement_text="Test rumah",
        jumlah_lantai=1,
        model="test",
        status="generated",
        plan_json={
            "kavling": {"width_m": 10.0, "length_m": 12.0},
            "levels": [
                {
                    "level": 1,
                    "rooms": [
                        {
                            "name": "Ruang Tamu",
                            "type": "ruang_tamu",
                            "polygon": [
                                {"x": 0.0, "y": 0.0},
                                {"x": 5.0, "y": 0.0},
                                {"x": 5.0, "y": 4.0},
                                {"x": 0.0, "y": 4.0},
                            ],
                            "area_m2": 20.0,
                        }
                    ],
                    "walls": [],
                    "openings": [],
                }
            ],
            "requirement_text": "",
            "jumlah_lantai": 1,
            "generated_by": "test",
            "notes": "",
        },
    )
    session.add(record)
    await session.flush()
    return record


# ── Pure function tests (no DB, no HTTP) ──────────────────────────────────────


class TestBuildInteriorPrompt:
    @pytest.mark.asyncio
    async def test_known_style_returns_string_with_room_name(self):
        from app.modules.acap.interior.prompts import build_interior_prompt

        prompt = build_interior_prompt(
            room_name="Kamar Tidur Utama",
            room_type="kamar_tidur_utama",
            area_m2=17.6,
            style="japandi",
        )
        assert "Kamar Tidur Utama" in prompt
        assert "17.6" in prompt
        assert "Japandi" in prompt or "japandi" in prompt
        assert isinstance(prompt, str)
        # Distinctive japandi style fragment (STYLES['japandi']) — proves the
        # style copy is actually spliced in, not just the bare style word.
        assert "wabi-sabi" in prompt
        # ROOM_HINTS['kamar_tidur_utama'] master-bedroom hint is spliced in too.
        assert "master bedroom with queen bed" in prompt

    @pytest.mark.asyncio
    async def test_unknown_style_raises_value_error(self):
        from app.modules.acap.interior.prompts import build_interior_prompt

        with pytest.raises(ValueError, match="Unknown interior style"):
            build_interior_prompt(
                room_name="X",
                room_type="ruang_tamu",
                area_m2=10.0,
                style="nonexistent_style",
            )


# ── HTTP endpoint tests ──────────────────────────────────────────────────────


class TestInteriorEndpoints:
    @pytest.mark.asyncio
    async def test_generate_no_layout_returns_404(self, session, monkeypatch):
        monkeypatch.setenv("GEMINIGEN_API_KEY", "fake-key")
        pid = await _make_project(session)
        app = _build_app(session)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "Ruang Tamu", "style": "japandi"},
                )

        assert resp.status_code == 404, resp.text

    @pytest.mark.asyncio
    async def test_generate_missing_key_returns_400(self, session, monkeypatch):
        monkeypatch.delenv("GEMINIGEN_API_KEY", raising=False)

        pid = await _make_project(session)
        await _insert_floor_plan(session, pid)
        app = _build_app(session)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "Ruang Tamu", "style": "japandi"},
                )

        assert resp.status_code == 400, resp.text
        body = resp.json()
        assert body["detail"]["reason"] == "GEMINIGEN_API_KEY not set"

    @pytest.mark.asyncio
    async def test_generate_room_not_in_layout_returns_422(self, session, monkeypatch):
        monkeypatch.setenv("GEMINIGEN_API_KEY", "fake-key")

        pid = await _make_project(session)
        await _insert_floor_plan(session, pid)
        app = _build_app(session)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "NonExistentRoom", "style": "japandi"},
                )

        assert resp.status_code == 422, resp.text
        body = resp.json()
        assert "not found" in body.get("detail", "").lower()

    @pytest.mark.asyncio
    async def test_interior_non_owner_forbidden(self, session, monkeypatch):
        """A non-owner is rejected on BOTH generate and list endpoints."""
        monkeypatch.setenv("GEMINIGEN_API_KEY", "fake-key")

        pid = await _make_project(session, _TEST_OWNER)
        await _insert_floor_plan(session, pid)
        app = _build_app(session, user_id=_TEST_OTHER)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                gen = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "Ruang Tamu", "style": "japandi"},
                )
                lst = await ac.get(f"/api/v1/acap/projects/{pid}/interiors")

        assert gen.status_code in (403, 404), gen.text
        assert lst.status_code in (403, 404), lst.text

    @pytest.mark.asyncio
    async def test_interior_generate_happy(self, session, monkeypatch):
        """Full happy path → completed InteriorRenderRecord persisted + image stored."""
        monkeypatch.setenv("GEMINIGEN_API_KEY", "fake-key")

        pid = await _make_project(session, _TEST_OWNER)
        await _insert_floor_plan(session, pid)

        async def _fake_generate(prompt, **kwargs):
            return {"uuid": "prov-123", "media_url": "http://cdn/x.png"}

        monkeypatch.setattr(
            "app.modules.acap.render.client.generate_render_image", _fake_generate
        )

        image_bytes = b"\x89PNG\r\n\x1a\n" + b"0" * 4000  # >1024 so the size guard passes

        class _DLResp:
            status_code = 200
            content = image_bytes

        class _DLClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return False

            async def get(self, url):
                return _DLResp()

        # The endpoint downloads via `import httpx; httpx.AsyncClient(...)` at call
        # time → patched here. The test's own AsyncClient name (bound at import)
        # is unaffected, so the ASGI client keeps working.
        monkeypatch.setattr("httpx.AsyncClient", _DLClient)

        class _FakeStorage:
            def __init__(self):
                self.puts: dict[str, bytes] = {}

            async def put(self, key, content):
                self.puts[key] = content

        storage = _FakeStorage()
        monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: storage)

        app = _build_app(session, user_id=_TEST_OWNER)
        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "Ruang Tamu", "style": "japandi"},
                )

        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["status"] == "completed"
        assert body["room_name"] == "Ruang Tamu"
        assert body["style"] == "japandi"
        assert storage.puts  # image persisted to object storage

        from sqlalchemy import select

        from app.modules.acap.models.interior_render import InteriorRenderRecord

        rec = (
            await session.execute(
                select(InteriorRenderRecord).where(
                    InteriorRenderRecord.project_id == pid
                )
            )
        ).scalars().one()
        assert rec.status == "completed"
        assert rec.room_name == "Ruang Tamu"
        assert rec.style == "japandi"
        assert rec.storage_key in storage.puts

    @pytest.mark.asyncio
    async def test_interior_bogus_style_422(self, session, monkeypatch):
        """A valid room but an unknown style → 422 (build_interior_prompt rejects)."""
        monkeypatch.setenv("GEMINIGEN_API_KEY", "fake-key")

        pid = await _make_project(session, _TEST_OWNER)
        await _insert_floor_plan(session, pid)
        app = _build_app(session, user_id=_TEST_OWNER)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.post(
                    f"/api/v1/acap/projects/{pid}/interior:generate",
                    json={"room_name": "Ruang Tamu", "style": "bogus"},
                )

        assert resp.status_code == 422, resp.text

    @pytest.mark.asyncio
    async def test_list_interiors_returns_empty(self, session):
        pid = await _make_project(session)
        app = _build_app(session)

        async with app.router.lifespan_context(app):
            transport = ASGITransport(app=app)
            async with AsyncClient(transport=transport, base_url="http://test") as ac:
                resp = await ac.get(
                    f"/api/v1/acap/projects/{pid}/interiors"
                )

        assert resp.status_code == 200, resp.text
        assert resp.json() == []
