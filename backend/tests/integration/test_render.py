# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""ACAP visual-render tests.

PURE (no DB/network): prompt builder, key-gate, media-url extraction, and the
GeminiGen client driven by an httpx.MockTransport (no real API call).
INTEGRATION (PostgreSQL): generate_render persists a RenderRecord and stores
the image via an injected fake storage backend.

The render path is decorative (never feeds the RAB) and must NEVER leak the
API key — asserted below.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import pytest_asyncio

from app.modules.acap.layout.schema import FloorPlan, Kavling, Level, Point, Room
from app.modules.acap.models.render import RenderRecord
from app.modules.acap.render.client import (
    RenderNotConfiguredError,
    RenderServiceError,
    extract_media_url,
    generate_render_image,
    render_service_configured,
)
from app.modules.acap.render.generator import generate_render
from app.modules.acap.render.prompt import build_render_prompt
from tests._pg import transactional_session

_PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 4000  # >1024 bytes so the size guard passes


def _plan() -> FloorPlan:
    room = Room(
        name="Kamar Utama",
        type="kamar_tidur",
        polygon=[Point(x=0, y=0), Point(x=3, y=0), Point(x=3, y=4), Point(x=0, y=4)],
        area_m2=12.0,
    )
    return FloorPlan(kavling=Kavling(width_m=8.0, length_m=10.0), levels=[Level(level=1, rooms=[room])])


# ═══════════════════════════════════════════════════════════════════════════
# PURE
# ═══════════════════════════════════════════════════════════════════════════


def test_build_render_prompt_is_factual():
    out = build_render_prompt(_plan())
    assert "kamar tidur" in out
    assert "12 m2" in out
    assert "1-storey" in out and "8x10 m lot" in out


def test_render_service_configured_reflects_env(monkeypatch):
    monkeypatch.delenv("GEMINIGEN_API_KEY", raising=False)
    assert render_service_configured() is False
    monkeypatch.setenv("GEMINIGEN_API_KEY", "secret-xyz")
    assert render_service_configured() is True


def test_extract_media_url_both_shapes():
    assert extract_media_url({"generate_result": "http://x/a.png"}) == "http://x/a.png"
    assert extract_media_url({"data": [{"image_url": "http://x/b.png"}]}) == "http://x/b.png"
    assert extract_media_url({"data": [{"file_download_url": "http://x/c.png"}]}) == "http://x/c.png"
    assert extract_media_url({"status": 1}) is None


@pytest.mark.asyncio
async def test_generate_render_image_not_configured(monkeypatch):
    monkeypatch.delenv("GEMINIGEN_API_KEY", raising=False)
    with pytest.raises(RenderNotConfiguredError):
        await generate_render_image("a house")


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


@pytest.mark.asyncio
async def test_generate_render_image_submit_poll_success(monkeypatch):
    monkeypatch.setenv("GEMINIGEN_API_KEY", "secret-xyz")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/generate_image"):
            return httpx.Response(200, json={"uuid": "job1", "status": 1})
        if "history" in request.url.path:
            return httpx.Response(200, json={"status": 2, "generate_result": "http://cdn/x.png"})
        return httpx.Response(404)

    async with _mock_client(handler) as client:
        result = await generate_render_image("a house", poll_interval=0, client=client)
    assert result["uuid"] == "job1"
    assert result["media_url"] == "http://cdn/x.png"


@pytest.mark.asyncio
async def test_generate_render_image_failed_job_no_key_leak(monkeypatch):
    monkeypatch.setenv("GEMINIGEN_API_KEY", "secret-xyz")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/generate_image"):
            return httpx.Response(200, json={"uuid": "job2", "status": 1})
        return httpx.Response(200, json={"status": 3, "error_message": "content policy"})

    async with _mock_client(handler) as client:
        with pytest.raises(RenderServiceError) as exc:
            await generate_render_image("a house", poll_interval=0, client=client)
    assert "content policy" in str(exc.value)
    assert "secret-xyz" not in str(exc.value)  # key never surfaced in errors


# ═══════════════════════════════════════════════════════════════════════════
# INTEGRATION
# ═══════════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture
async def session():
    async with transactional_session(disable_fks=True) as s:
        yield s


class _FakeStorage:
    def __init__(self):
        self.puts: dict[str, bytes] = {}

    async def put(self, key: str, content: bytes) -> None:
        self.puts[key] = content


@pytest.mark.asyncio
async def test_generate_render_persists_completed_record(session, monkeypatch):
    monkeypatch.setenv("GEMINIGEN_API_KEY", "secret-xyz")
    project_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/generate_image"):
            return httpx.Response(200, json={"uuid": "job3", "status": 1})
        if "history" in request.url.path:
            return httpx.Response(200, json={"status": 2, "generate_result": "http://cdn/r.png"})
        return httpx.Response(200, content=_PNG)  # image download

    storage = _FakeStorage()
    async with _mock_client(handler) as client:
        record = await generate_render(session, project_id, _plan(), 1, client=client, storage=storage)

    assert record.status == "completed"
    assert record.storage_key and record.storage_key in storage.puts
    assert storage.puts[record.storage_key] == _PNG
    assert record.source_url == "http://cdn/r.png"
    assert record.provider_uuid == "job3"

    # Round-trips out of the DB.
    from sqlalchemy import select

    fetched = (await session.execute(select(RenderRecord).where(RenderRecord.id == record.id))).scalars().one()
    assert fetched.status == "completed"


@pytest.mark.asyncio
async def test_generate_render_provider_failure_persists_failed_record(session, monkeypatch):
    monkeypatch.setenv("GEMINIGEN_API_KEY", "secret-xyz")
    project_id = uuid.uuid4()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/generate_image"):
            return httpx.Response(200, json={"uuid": "job4", "status": 1})
        return httpx.Response(200, json={"status": 3, "error_message": "nsfw"})

    storage = _FakeStorage()
    async with _mock_client(handler) as client:
        record = await generate_render(session, project_id, _plan(), 1, client=client, storage=storage)

    assert record.status == "failed"
    assert "nsfw" in (record.error_message or "")
    assert "secret-xyz" not in (record.error_message or "")  # no key leak into the DB
    assert record.storage_key is None
    assert not storage.puts
