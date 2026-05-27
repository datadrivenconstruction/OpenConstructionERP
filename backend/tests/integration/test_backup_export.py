"""Regression tests for BUG-018: ``POST /backup/export/`` returns empty zip.

Originally, ``POST /api/v1/backup/export/`` with a JSON body — even
``{}`` — returned ``HTTP 200`` with ``Content-Length: 0``. The combo of
``StreamingResponse`` and ``_RejectNonFiniteJSONMiddleware`` (which
emits an ``http.disconnect`` after replaying the body) caused Starlette
to cancel the streaming iterator before any chunk was sent. Fix:
``service.build_backup`` writes into a ``SpooledTemporaryFile`` and the
handler returns the archive via ``FileResponse``, which is unaffected.
"""

from __future__ import annotations

import io
import json
import uuid
import zipfile

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app


@pytest_asyncio.fixture(scope="module")
async def client():
    """Module-scoped client + lifespan to avoid login rate-limit churn."""
    app = create_app()
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test", timeout=30.0) as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    """Register a fresh admin user and return Authorization headers."""
    unique = uuid.uuid4().hex[:8]
    email = f"backup-{unique}@test.io"
    password = f"BackupTest{unique}9"

    reg = await client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "Backup Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, reg.text

    from ._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    login = await client.post(
        "/api/v1/users/auth/login",
        json={"email": email, "password": password},
    )
    assert login.status_code == 200, login.text
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_export_with_empty_body_returns_valid_zip(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """BUG-018: ``POST /backup/export/`` with ``json={}`` must NOT be empty."""
    resp = await client.post("/api/v1/backup/export/", headers=admin_headers, json={})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "application/zip"
    body = resp.content
    assert len(body) > 0, "BUG-018 regression: empty zip"
    assert body[:4] == b"PK\x03\x04", "not a ZIP archive"

    zf = zipfile.ZipFile(io.BytesIO(body))
    names = zf.namelist()
    assert "manifest.json" in names, "manifest.json missing from archive"

    manifest = json.loads(zf.read("manifest.json"))
    assert manifest["app"] == "openestimate"
    assert manifest["format_version"]
    assert manifest["app_version"]
    assert manifest["created_at"]
    assert "modules" in manifest
    assert "file_count" in manifest
    assert "checksum" in manifest

    # At least one per-module dump must be present.
    module_dumps = [n for n in names if n.endswith(".json") and n != "manifest.json"]
    assert module_dumps, "no per-module JSON dump in archive"


@pytest.mark.asyncio
async def test_export_with_include_modules_filters_archive(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """When ``include_modules`` is specified, only those JSON dumps appear."""
    resp = await client.post(
        "/api/v1/backup/export/",
        headers=admin_headers,
        json={"include_modules": ["projects", "boqs"], "include_files": True},
    )

    assert resp.status_code == 200
    body = resp.content
    assert len(body) > 0
    assert body[:4] == b"PK\x03\x04"

    zf = zipfile.ZipFile(io.BytesIO(body))
    names = set(zf.namelist())
    assert "manifest.json" in names

    manifest = json.loads(zf.read("manifest.json"))
    assert sorted(manifest["modules"]) == ["boqs", "projects"]
    assert manifest["include_files"] is True

    # No JSON dumps for tables we did not request.
    assert "users.json" not in names
    assert "risks.json" not in names


@pytest.mark.asyncio
async def test_export_unknown_module_surfaces_warning(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """Unknown ``include_modules`` entries must emit a manifest warning."""
    resp = await client.post(
        "/api/v1/backup/export/",
        headers=admin_headers,
        json={"include_modules": ["projects", "this_module_does_not_exist"]},
    )

    assert resp.status_code == 200
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    manifest = json.loads(zf.read("manifest.json"))
    assert any("this_module_does_not_exist" in w for w in manifest.get("warnings", [])), manifest


@pytest.mark.asyncio
async def test_export_no_body_still_works(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """Sanity: ``POST`` without a body still returns a full backup."""
    resp = await client.post("/api/v1/backup/export/", headers=admin_headers)
    assert resp.status_code == 200
    assert len(resp.content) > 0
    assert resp.content[:4] == b"PK\x03\x04"


@pytest.mark.asyncio
async def test_export_openapi_documents_request_body(client: AsyncClient, admin_headers: dict[str, str]) -> None:
    """OpenAPI must document ``include_modules`` / ``include_files``."""
    resp = await client.get("/api/openapi.json")
    assert resp.status_code == 200, resp.text
    spec = resp.json()
    op = spec["paths"]["/api/v1/backup/export/"]["post"]
    request_body = op.get("requestBody")
    assert request_body, "BUG-018: /backup/export/ has no documented request body"

    schema_ref = request_body["content"]["application/json"]["schema"]
    # Resolve $ref if necessary.
    if "$ref" in schema_ref:
        ref = schema_ref["$ref"].split("/")[-1]
        schema = spec["components"]["schemas"][ref]
    else:
        schema = schema_ref
    assert "include_modules" in schema["properties"]
    assert "include_files" in schema["properties"]
