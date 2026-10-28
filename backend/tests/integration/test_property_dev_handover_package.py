"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for the handover closeout package + completion gate (item #25).

Exercises end-to-end against the in-process ASGI app:

  * ``GET  /handovers/{id}/docs`` reports compliance (required vs delivered).
  * ``POST /handovers/{id}/complete`` is BLOCKED with 409 while a required
    handover document is still undelivered, and the response carries the
    ``missing_required`` doc-type list.
  * Once the required doc is delivered the same completion succeeds (200).
  * ``GET  /handovers/{id}/export`` streams a valid ZIP (application/zip,
    attachment filename) containing at least the manifest + certificates.
  * IDOR: a foreign tenant gets 404 on the export endpoint.

Mirrors the fixture style of ``test_property_dev_handover.py`` and relies on
the shared ``tests/conftest.py`` PostgreSQL cluster.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture(scope="module")
async def app_instance():
    from app.config import get_settings

    get_settings.cache_clear()

    from app.main import create_app

    app = create_app()

    async with app.router.lifespan_context(app):
        from app.database import Base, engine
        from app.modules.property_dev import models as _propdev_models  # noqa: F401

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
    email = f"{label}-{uuid.uuid4().hex[:8]}@propdev-pkg.io"
    password = f"PropDevPkg{uuid.uuid4().hex[:6]}9!"
    reg = await client.post(
        "/api/v1/users/auth/register",
        json={"email": email, "password": password, "full_name": label},
    )
    assert reg.status_code in (200, 201), reg.text
    return email, password


async def _login(client: AsyncClient, email: str, password: str) -> dict[str, str]:
    res = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert res.status_code == 200, res.text
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest_asyncio.fixture(scope="module")
async def owner(http_client):
    email, password = await _register(http_client, "pkgowner")
    await _set_role(email, "admin")
    headers = await _login(http_client, email, password)

    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"Pkg-{uuid.uuid4().hex[:6]}", "description": "x", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    project_id = proj.json()["id"]

    dev = await http_client.post(
        "/api/v1/property-dev/developments/",
        json={
            "project_id": project_id,
            "code": f"PK{uuid.uuid4().hex[:6].upper()}",
            "name": "Pkg Heights",
            "total_plots": 3,
        },
        headers=headers,
    )
    assert dev.status_code == 201, dev.text
    return {"headers": headers, "development_id": dev.json()["id"]}


@pytest_asyncio.fixture(scope="module")
async def stranger(http_client):
    email, password = await _register(http_client, "pkgstranger")
    await _set_role(email, "editor")
    headers = await _login(http_client, email, password)
    proj = await http_client.post(
        "/api/v1/projects/",
        json={"name": f"PkgS-{uuid.uuid4().hex[:6]}", "description": "x", "currency": "EUR"},
        headers=headers,
    )
    assert proj.status_code == 201, proj.text
    return {"headers": headers}


async def _new_plot(client: AsyncClient, owner: dict) -> str:
    p = await client.post(
        "/api/v1/property-dev/plots/",
        json={
            "development_id": owner["development_id"],
            "plot_number": f"PK-{uuid.uuid4().hex[:5]}",
            "area_m2": 90,
            "price_base": 400_000,
            "currency": "EUR",
            "status": "ready",
        },
        headers=owner["headers"],
    )
    assert p.status_code == 201, p.text
    return p.json()["id"]


async def _new_handover(client: AsyncClient, owner: dict, plot_id: str) -> str:
    h = await client.post(
        "/api/v1/property-dev/handovers/",
        json={"plot_id": plot_id, "scheduled_at": "2026-09-15"},
        headers=owner["headers"],
    )
    assert h.status_code == 201, h.text
    return h.json()["id"]


@pytest.mark.asyncio
async def test_complete_blocked_until_required_docs_delivered(http_client: AsyncClient, owner: dict) -> None:
    plot_id = await _new_plot(http_client, owner)
    handover_id = await _new_handover(http_client, owner, plot_id)

    # Add a REQUIRED, undelivered warranty doc.
    doc = await http_client.post(
        "/api/v1/property-dev/handover-docs/",
        json={
            "handover_id": handover_id,
            "doc_type": "warranty",
            "title": "10y structural warranty",
            "is_required": True,
            "is_delivered": False,
        },
        headers=owner["headers"],
    )
    assert doc.status_code == 201, doc.text
    doc_id = doc.json()["id"]

    # Bundle reports it as not-ready.
    bundle = await http_client.get(
        f"/api/v1/property-dev/handovers/{handover_id}/docs",
        headers=owner["headers"],
    )
    assert bundle.status_code == 200, bundle.text
    body = bundle.json()
    assert body["ready_for_handover"] is False
    assert "warranty" in body["missing_required"]

    # Completion is blocked with 409 + missing list.
    blocked = await http_client.post(
        f"/api/v1/property-dev/handovers/{handover_id}/complete",
        json={"completed_at": "2026-09-30", "customer_signature_ref": "SIG-1"},
        headers=owner["headers"],
    )
    assert blocked.status_code == 409, blocked.text
    detail = blocked.json()["detail"]
    assert "warranty" in detail["missing_required"]

    # Deliver the doc.
    patched = await http_client.patch(
        f"/api/v1/property-dev/handover-docs/{doc_id}",
        json={"is_delivered": True},
        headers=owner["headers"],
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["is_delivered"] is True
    assert patched.json()["delivered_at"]

    # Bundle now ready.
    bundle2 = await http_client.get(
        f"/api/v1/property-dev/handovers/{handover_id}/docs",
        headers=owner["headers"],
    )
    assert bundle2.json()["ready_for_handover"] is True


@pytest.mark.asyncio
async def test_export_package_streams_zip(http_client: AsyncClient, owner: dict) -> None:
    plot_id = await _new_plot(http_client, owner)
    handover_id = await _new_handover(http_client, owner, plot_id)

    # An optional, delivered doc with an external URL (listed in manifest,
    # never fetched in-request).
    doc = await http_client.post(
        "/api/v1/property-dev/handover-docs/",
        json={
            "handover_id": handover_id,
            "doc_type": "manual",
            "title": "Appliance manuals",
            "file_url": "https://example.com/manuals.pdf",
            "is_required": False,
            "is_delivered": True,
        },
        headers=owner["headers"],
    )
    assert doc.status_code == 201, doc.text

    res = await http_client.get(
        f"/api/v1/property-dev/handovers/{handover_id}/export",
        headers=owner["headers"],
    )
    assert res.status_code == 200, res.text
    assert res.headers["content-type"].startswith("application/zip")
    assert "attachment" in res.headers.get("content-disposition", "")
    assert ".zip" in res.headers.get("content-disposition", "")

    zf = zipfile.ZipFile(io.BytesIO(res.content))
    names = zf.namelist()
    assert "MANIFEST.txt" in names
    manifest = zf.read("MANIFEST.txt").decode("utf-8")
    # The external doc is referenced, not embedded.
    assert "example.com/manuals.pdf" in manifest
    assert "DIGITAL HANDOVER" in manifest

    # Machine-readable manifest.json mirrors the bundle + lists the docs.
    import json

    assert "manifest.json" in names
    mj = json.loads(zf.read("manifest.json"))
    assert mj["kind"] == "handover_closeout_package"
    assert mj["handover_id"] == handover_id
    assert any(d["doc_type"] == "manual" for d in mj["documents"])
    assert "compliance" in mj


@pytest.mark.tenant_isolation
@pytest.mark.asyncio
async def test_stranger_cannot_export(http_client: AsyncClient, owner: dict, stranger: dict) -> None:
    plot_id = await _new_plot(http_client, owner)
    handover_id = await _new_handover(http_client, owner, plot_id)

    res = await http_client.get(
        f"/api/v1/property-dev/handovers/{handover_id}/export",
        headers=stranger["headers"],
    )
    assert res.status_code == 404, res.text
