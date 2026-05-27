"""Shared fixtures for the Geo Hub raster-overlay test suite.

Per-module SQLite isolation must run BEFORE any ``from app...`` import.
A fresh temp DB per test module keeps cross-test bleed at zero.
"""

from __future__ import annotations

import io
import os
import tempfile
import uuid
from pathlib import Path

# Allocate the temp DB path at import time but defer setting the env var
# to the fixture so individual test modules can opt out via their own
# fixture.
_TMP_DIR = Path(tempfile.mkdtemp(prefix="oe-geo-overlay-"))
_TMP_DB = _TMP_DIR / "geo_overlay.db"
os.environ.setdefault("DATABASE_URL", f"sqlite+aiosqlite:///{_TMP_DB.as_posix()}")
os.environ.setdefault("DATABASE_SYNC_URL", f"sqlite:///{_TMP_DB.as_posix()}")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402


def make_tiny_pdf_bytes(text: str = "Site plan") -> bytes:
    """Return a single-page PDF with a rectangle + caption via PyMuPDF."""
    import fitz

    doc = fitz.open()
    page = doc.new_page(width=595, height=842)  # A4 portrait
    page.draw_rect(fitz.Rect(120, 200, 475, 500), color=(0.2, 0.4, 0.9), width=2)
    page.insert_text((140, 230), text, fontsize=14, color=(0.1, 0.1, 0.1))
    buf = io.BytesIO()
    doc.save(buf)
    doc.close()
    return buf.getvalue()


def make_tiny_png_bytes(size: int = 64) -> bytes:
    from PIL import Image

    img = Image.new("RGB", (size, size), "#22c55e")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()
    from app.main import create_app

    app = create_app()
    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.bim_hub import models as _bim  # noqa: F401
        from app.modules.geo_hub import models as _geo  # noqa: F401
        from app.modules.property_dev import models as _prop  # noqa: F401

        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        yield app


@pytest_asyncio.fixture(scope="module")
async def http_client(app_instance):
    transport = ASGITransport(app=app_instance)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _set_role(email: str, role: str) -> None:
    from sqlalchemy import update

    from app.database import async_session_factory
    from app.modules.users.models import User

    async with async_session_factory() as s:
        await s.execute(update(User).where(User.email == email.lower()).values(role=role, is_active=True))
        await s.commit()


async def _register(client: AsyncClient, label: str) -> tuple[str, str]:
    email = f"{label}-{uuid.uuid4().hex[:8]}@geo-overlay.io"
    password = f"GeoOv{uuid.uuid4().hex[:6]}9!"
    res = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert res.status_code in (200, 201), res.text
    return email, password


async def _login(
    client: AsyncClient,
    email: str,
    password: str,
) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def tenant_a(http_client):
    email, password = await _register(http_client, "tenant-a")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"GeoOverlay-A {uuid.uuid4().hex[:6]}",
            "description": "tenant A",
            "currency": "EUR",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]
    # Anchor the project so default corners aren't placeholder.
    anchor = await http_client.post(
        "/api/v1/geo-hub/anchors/",
        json={
            "project_id": project_id,
            "lat": "52.5200",
            "lon": "13.4050",
            "alt": "34",
            "epsg_code": 4326,
        },
        headers=headers,
    )
    assert anchor.status_code in (200, 201), anchor.text
    return {"email": email, "headers": headers, "project_id": project_id}


@pytest_asyncio.fixture(scope="module")
async def tenant_b(http_client):
    email, password = await _register(http_client, "tenant-b")
    # editor — NOT admin so IDOR tests can't bypass via role
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)
    proj = await http_client.post(
        "/api/v1/projects/",
        json={
            "name": f"GeoOverlay-B {uuid.uuid4().hex[:6]}",
            "description": "tenant B",
            "currency": "USD",
        },
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {
        "email": email,
        "headers": headers,
        "project_id": proj.json()["id"],
    }


@pytest.fixture(scope="module")
def tiny_pdf() -> bytes:
    return make_tiny_pdf_bytes()


@pytest.fixture(scope="module")
def tiny_png() -> bytes:
    return make_tiny_png_bytes()
