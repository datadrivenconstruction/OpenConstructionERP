# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Profile photo​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ endpoints: POST/GET/DELETE /api/v1/users/me/avatar/.

Covers upload, replace (old file removed), serve, delete, validation
rejections, per-user isolation, and ``avatar_url`` on ``GET /me``.
"""

from __future__ import annotations

import io
import uuid

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from PIL import Image


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        yield app


@pytest_asyncio.fixture(scope="module")
async def client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _register_and_login(client: AsyncClient) -> dict[str, str]:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    email = f"avatar-{uuid.uuid4().hex[:8]}@prefs.io"
    password = "AvatarTest1234"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": "Avatar Tester"},
    )
    assert reg.status_code in (200, 201), reg.text
    async with async_session_factory() as session:
        await session.execute(update(User).where(User.email == email.lower()).values(role="admin", is_active=True))
        await session.commit()
    resp = await client.post("/api/v1/users/auth/login", json={"email": email, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _png(size: tuple[int, int] = (500, 300)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


def _files(data: bytes, mime: str = "image/png", name: str = "me.png") -> dict:
    return {"file": (name, data, mime)}


URL = "/api/v1/users/me/avatar/"


async def _stored_key(client: AsyncClient, headers: dict[str, str]) -> str:
    from sqlalchemy import select

    from app.database import async_session_factory
    from app.modules.users.models import User

    me = (await client.get("/api/v1/users/me/", headers=headers)).json()
    async with async_session_factory() as session:
        row = (await session.execute(select(User).where(User.id == uuid.UUID(me["id"])))).scalar_one()
        return row.avatar_key


@pytest.mark.asyncio
async def test_no_photo_means_404_and_no_avatar_url(client):
    headers = await _register_and_login(client)
    assert (await client.get(URL, headers=headers)).status_code == 404
    me = (await client.get("/api/v1/users/me/", headers=headers)).json()
    assert me["avatar_url"] is None


@pytest.mark.asyncio
async def test_upload_serve_replace_delete(client):
    headers = await _register_and_login(client)

    up = await client.post(URL, headers=headers, files=_files(_png()))
    assert up.status_code == 200, up.text
    first_url = up.json()["avatar_url"]
    assert first_url
    assert first_url.startswith("/api/v1/users/me/avatar/")

    served = await client.get(URL, headers=headers)
    assert served.status_code == 200
    assert served.headers["content-type"] == "image/png"
    with Image.open(io.BytesIO(served.content)) as img:
        assert img.size == (256, 256)

    again = await client.post(URL, headers=headers, files=_files(_png((300, 300))))
    assert again.status_code == 200
    assert again.json()["avatar_url"] != first_url

    me = (await client.get("/api/v1/users/me/", headers=headers)).json()
    assert me["avatar_url"] == again.json()["avatar_url"]

    gone = await client.delete(URL, headers=headers)
    assert gone.status_code == 200
    assert gone.json()["avatar_url"] is None
    assert (await client.get(URL, headers=headers)).status_code == 404


@pytest.mark.asyncio
async def test_replace_and_delete_remove_the_old_stored_file(client):
    from app.core.storage import get_storage_backend

    headers = await _register_and_login(client)
    await client.post(URL, headers=headers, files=_files(_png()))
    first = await _stored_key(client, headers)
    assert await get_storage_backend().exists(first)

    await client.post(URL, headers=headers, files=_files(_png()))
    second = await _stored_key(client, headers)
    assert second != first
    assert not await get_storage_backend().exists(first)
    assert await get_storage_backend().exists(second)

    await client.delete(URL, headers=headers)
    assert not await get_storage_backend().exists(second)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("data", "mime", "rule"),
    [
        (b"GIF89a" + b"\0" * 40, "image/gif", "users.avatar.type"),
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "image/svg+xml", "users.avatar.type"),
        (b"\x89PNG\r\n\x1a\n" + b"junk" * 20, "image/png", "users.avatar.content"),
        (b"", "image/png", "users.avatar.empty"),
    ],
)
async def test_invalid_uploads_are_422_with_a_rule_id(client, data, mime, rule):
    headers = await _register_and_login(client)
    resp = await client.post(URL, headers=headers, files=_files(data, mime))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["rule"] == rule


@pytest.mark.asyncio
async def test_oversize_upload_is_422(client):
    headers = await _register_and_login(client)
    resp = await client.post(URL, headers=headers, files=_files(_png() + b"\0" * (2 * 1024 * 1024 + 1)))
    assert resp.status_code == 422, resp.text
    assert resp.json()["detail"]["rule"] == "users.avatar.size"


@pytest.mark.asyncio
async def test_photos_are_per_user(client):
    a = await _register_and_login(client)
    b = await _register_and_login(client)
    await client.post(URL, headers=a, files=_files(_png()))
    assert (await client.get(URL, headers=b)).status_code == 404


@pytest.mark.asyncio
async def test_requires_authentication(client):
    assert (await client.post(URL, files=_files(_png()))).status_code in (401, 403)
    assert (await client.get(URL)).status_code in (401, 403)
    assert (await client.delete(URL)).status_code in (401, 403)
