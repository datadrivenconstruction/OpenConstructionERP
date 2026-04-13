"""Integration tests for the BIM upload converter preflight (v1.4.7).

Covers:
    * Test A — ``.rvt`` upload with no converter installed → 200 with
      ``status="converter_required"``, no file read, no model row.
    * Test B — ``.ifc`` upload must NOT be blocked by preflight even
      when ``find_converter`` returns ``None``, because IFC has a
      built-in text fallback parser.
    * Test C — ``.rvt`` upload with a (mocked) installed converter →
      preflight passes; post-processing ends up in ``needs_converter``
      or ``error`` (both acceptable — the point is preflight did not
      short-circuit).
    * Test D — success-path response shape must include the new
      ``error_message``, ``converter_id`` and ``install_endpoint``
      fields introduced in v1.4.7.

The module-scoped client + auth fixtures follow the same pattern as
``test_requirements_bim_cross.py`` — a full app lifespan (so
``module_loader.load_all`` runs) and a freshly registered admin.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Module-scoped fixtures ─────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def preflight_client():
    app = create_app()

    @asynccontextmanager
    async def lifespan_ctx():
        async with app.router.lifespan_context(app):
            yield

    async with lifespan_ctx():
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest_asyncio.fixture(scope="module")
async def preflight_auth(preflight_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bimpre-{unique}@test.io"
    password = f"BimPre{unique}9"

    reg = await preflight_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM Preflight Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    token = ""
    for attempt in range(3):
        resp = await preflight_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in data.get("detail", ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def preflight_project(
    preflight_client: AsyncClient, preflight_auth: dict[str, str]
) -> str:
    resp = await preflight_client.post(
        "/api/v1/projects/",
        json={
            "name": f"BIMPre Project {uuid.uuid4().hex[:6]}",
            "description": "BIM upload preflight test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=preflight_auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


# ── Helpers ────────────────────────────────────────────────────────────────


_MINIMAL_IFC = (
    b"ISO-10303-21;\n"
    b"HEADER;\n"
    b"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
    b"FILE_NAME('test.ifc','2026-04-11T00:00:00',('tester'),('oe'),'test','test','');\n"
    b"FILE_SCHEMA(('IFC4'));\n"
    b"ENDSEC;\n"
    b"DATA;\n"
    b"ENDSEC;\n"
    b"END-ISO-10303-21;\n"
)


async def _upload(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    filename: str,
    content: bytes,
) -> dict:
    resp = await client.post(
        "/api/v1/bim_hub/upload-cad/",
        params={"project_id": project_id, "name": filename, "discipline": "architecture"},
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers=auth,
    )
    assert resp.status_code in (200, 201), (
        f"Upload failed ({resp.status_code}): {resp.text}"
    )
    return resp.json()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestBimUploadConverterPreflight:
    """v1.4.7 preflight + response-shape coverage."""

    async def test_rvt_without_converter_is_refused_upfront(
        self,
        preflight_client: AsyncClient,
        preflight_auth: dict[str, str],
        preflight_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Force the preflight path: no converter for any extension.
        import app.modules.boq.cad_import as cad_import_mod

        monkeypatch.setattr(cad_import_mod, "find_converter", lambda _ext: None)

        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="tiny.rvt",
            content=b"\x00" * 1024,
        )

        assert body["status"] == "converter_required", body
        assert body["converter_id"] == "rvt"
        assert body["model_id"] is None
        assert body["name"] is None
        assert body["file_size"] == 0
        assert body["element_count"] == 0
        assert body["install_endpoint"] == "/api/v1/takeoff/converters/rvt/install/"
        assert "RVT" in (body.get("message") or "")

    async def test_ifc_is_never_blocked_by_preflight(
        self,
        preflight_client: AsyncClient,
        preflight_auth: dict[str, str],
        preflight_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Even with no converter available, IFC must fall through to the
        # text parser path — the preflight must not short-circuit.
        import app.modules.boq.cad_import as cad_import_mod

        monkeypatch.setattr(cad_import_mod, "find_converter", lambda _ext: None)

        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="tiny.ifc",
            content=_MINIMAL_IFC,
        )

        assert body["status"] != "converter_required", body
        # The file has no elements so we expect a non-ready terminal
        # status, but importantly a model row WAS created.
        assert body["model_id"] is not None
        assert body["format"] == "ifc"

    async def test_rvt_with_installed_converter_passes_preflight(
        self,
        preflight_client: AsyncClient,
        preflight_auth: dict[str, str],
        preflight_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Pretend the RvtExporter binary is installed. The downstream
        # subprocess call will fail (fake path) and the processor will
        # end up in ``needs_converter`` / ``error`` — either is fine;
        # we only assert that preflight did NOT short-circuit.
        import app.modules.boq.cad_import as cad_import_mod

        fake_exe = Path("/fake/RvtExporter.exe")
        monkeypatch.setattr(
            cad_import_mod, "find_converter", lambda _ext: fake_exe
        )

        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="passthrough.rvt",
            content=b"\x00" * 1024,
        )

        assert body["status"] != "converter_required", body
        assert body["model_id"] is not None
        assert body["format"] == "rvt"
        # Response shape must include the v1.4.7 keys.
        assert "error_message" in body
        assert "converter_id" in body
        assert "install_endpoint" in body

    async def test_success_path_response_shape(
        self,
        preflight_client: AsyncClient,
        preflight_auth: dict[str, str],
        preflight_project: str,
    ) -> None:
        # Upload the minimal IFC — it parses (empty data section) but
        # may extract zero elements.  Either way the response shape
        # must include the v1.4.7 additive keys.
        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="shape.ifc",
            content=_MINIMAL_IFC,
        )

        for key in (
            "model_id",
            "name",
            "format",
            "file_size",
            "status",
            "element_count",
            "error_message",
            "converter_id",
            "install_endpoint",
        ):
            assert key in body, f"Missing key in response: {key}"
