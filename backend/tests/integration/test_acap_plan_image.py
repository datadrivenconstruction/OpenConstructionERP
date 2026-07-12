# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""HTTP-layer verification of the ACAP plan-image upload endpoint.

Mirrors test_layout_edit.py's in-process app pattern: acap router mounted with
DB/auth dependencies overridden by a transaction-isolated session, so the
upload is exercised exactly as the real app serves it — without booting the
full module loader.

Covers:
  (a) happy PNG upload → 200 with {image_id, filename, content_type, size_bytes}
      and the storage backend's put() called once with a server-generated key
      starting "acap/plan-images/{project_id}/" (client filename NEVER used).
  (b) wrong content-type (text/plain) → 400.
  (c) non-owner JWT → 403 (write guard: project exists, user is not owner).
"""

from __future__ import annotations

import re
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


class _FakeStorage:
    """Records put() calls so the test can assert the key + content."""

    def __init__(self) -> None:
        self.puts: list[tuple[str, bytes]] = []

    async def put(self, key: str, content: bytes) -> None:
        self.puts.append((key, content))


def _png_bytes() -> bytes:
    # Minimal PNG magic + enough body to exceed the 16-byte floor.
    return b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


@pytest.mark.asyncio
async def test_upload_plan_image_happy(session, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    pid = await _make_project(session, _TEST_OWNER)
    app = _build_app(session, user_id=_TEST_OWNER)

    png = _png_bytes()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images",
                files={"file": ("rumah.png", png, "image/png")},
            )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["filename"] == "rumah.png"
    assert body["content_type"] == "image/png"
    assert body["size_bytes"] == len(png)
    assert body["image_id"]
    # uuid-parseable image_id
    uuid.UUID(body["image_id"])

    assert len(fake.puts) == 1
    key, content = fake.puts[0]
    # Server-generated key: uuid4 hex stem + ext from content_type map — the
    # client filename ("rumah.png") must NOT leak into the key path.
    assert "rumah" not in key
    assert re.fullmatch(rf"acap/plan-images/{pid}/[0-9a-f]{{32}}\.png", key), key
    assert content == png


@pytest.mark.asyncio
async def test_upload_plan_image_ext_from_content_type_not_filename(session, monkeypatch):
    """A .txt filename with an image/png content-type still keys as .png."""
    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    pid = await _make_project(session, _TEST_OWNER)
    app = _build_app(session, user_id=_TEST_OWNER)

    png = _png_bytes()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images",
                files={"file": ("evil.txt", png, "image/png")},
            )

    assert resp.status_code == 200, resp.text
    key, _ = fake.puts[0]
    assert "evil" not in key
    assert key.endswith(".png")


@pytest.mark.asyncio
async def test_upload_plan_image_size_cap(session, monkeypatch):
    """A body over 15 MiB → 413, nothing persisted."""
    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    pid = await _make_project(session, _TEST_OWNER)
    app = _build_app(session, user_id=_TEST_OWNER)

    oversized = b"\x89PNG\r\n\x1a\n" + b"\x00" * (15 * 1024 * 1024 + 1)
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images",
                files={"file": ("huge.png", oversized, "image/png")},
            )

    assert resp.status_code == 413, resp.text
    assert fake.puts == []


@pytest.mark.asyncio
async def test_upload_plan_image_rejects_wrong_content_type(session, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    pid = await _make_project(session, _TEST_OWNER)
    app = _build_app(session, user_id=_TEST_OWNER)

    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images",
                files={"file": ("notes.txt", b"hello world", "text/plain")},
            )

    assert resp.status_code == 400, resp.text
    assert fake.puts == []  # nothing persisted on a rejected upload


@pytest.mark.asyncio
async def test_upload_plan_image_non_owner_forbidden(session, monkeypatch):
    fake = _FakeStorage()
    monkeypatch.setattr("app.core.storage.get_storage_backend", lambda: fake)

    # Project owned by _TEST_OWNER, but the caller is _TEST_OTHER.
    pid = await _make_project(session, _TEST_OWNER)
    app = _build_app(session, user_id=_TEST_OTHER)

    png = _png_bytes()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.post(
                f"/api/v1/acap/projects/{pid}/plan-images",
                files={"file": ("rumah.png", png, "image/png")},
            )

    assert resp.status_code == 403, resp.text
    assert fake.puts == []