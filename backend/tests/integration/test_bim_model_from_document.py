"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Integration tests for "create a BIM model from a Project Document" (issue #273).

A file uploaded through the Documents hub is stored but never converted, so
opening it in the BIM viewer used to find no model and ask the user to upload
the same file a second time. ``POST /bim_hub/models/from-document/`` turns an
existing document into a BIM model on demand, reusing the direct-upload
conversion pipeline.

Covers:
    * Test A - an IFC document becomes a processable BIM model (status is
      handed to the same background worker as a direct CAD upload).
    * Test B - the endpoint is idempotent: a document already linked to a
      model returns that model with ``already_existed=True`` instead of
      converting the file twice.
    * Test C - a DWG document (no built-in parser) is accepted but flagged
      ``needs_converter`` rather than scheduled for inline processing.
    * Test D - a non-CAD document (e.g. a .txt) is rejected with 400.
    * Test E - an unknown document id returns 404.

The module-scoped client + auth fixtures mirror
``test_bim_upload_converter_preflight.py``.
"""

from __future__ import annotations

import asyncio
import io
import uuid
from contextlib import asynccontextmanager

import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# --- Module-scoped fixtures -------------------------------------------------


@pytest_asyncio.fixture(scope="module")
async def fromdoc_client():
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
async def fromdoc_auth(fromdoc_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bimfromdoc-{unique}@test.io"
    password = f"BimDoc{unique}9"

    reg = await fromdoc_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM From-Document Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)

    token = ""
    data: dict = {}
    for attempt in range(3):
        resp = await fromdoc_client.post(
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
async def fromdoc_project(fromdoc_client: AsyncClient, fromdoc_auth: dict[str, str]) -> str:
    resp = await fromdoc_client.post(
        "/api/v1/projects/",
        json={
            "name": f"FromDoc Project {uuid.uuid4().hex[:6]}",
            "description": "BIM from-document test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=fromdoc_auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


# --- Helpers ----------------------------------------------------------------


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

# A real DWG magic header ("AC" + 4-digit version) so the Documents
# magic-byte gate accepts it; the bytes after are irrelevant here because
# the from-document endpoint only inspects the file extension.
_DWG_HEADER = b"AC1027" + b"\x00" * 1018


async def _upload_document(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    filename: str,
    content: bytes,
) -> str:
    resp = await client.post(
        "/api/v1/documents/upload/",
        params={"project_id": project_id, "category": "other"},
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers=auth,
    )
    assert resp.status_code == 201, f"Document upload failed ({resp.status_code}): {resp.text}"
    return resp.json()["id"]


async def _from_document(
    client: AsyncClient,
    auth: dict[str, str],
    document_id: str,
    **extra: object,
):
    return await client.post(
        "/api/v1/bim_hub/models/from-document/",
        json={"document_id": document_id, **extra},
        headers=auth,
    )


# --- Tests ------------------------------------------------------------------


class TestBimModelFromDocument:
    """issue #273 - convert an existing Project Document into a BIM model."""

    async def test_ifc_document_becomes_model(
        self,
        fromdoc_client: AsyncClient,
        fromdoc_auth: dict[str, str],
        fromdoc_project: str,
    ) -> None:
        doc_id = await _upload_document(
            fromdoc_client,
            fromdoc_auth,
            fromdoc_project,
            filename="tower.ifc",
            content=_MINIMAL_IFC,
        )

        resp = await _from_document(fromdoc_client, fromdoc_auth, doc_id)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["model_id"], body
        assert body["format"] == "ifc"
        assert body["already_existed"] is False
        # IFC is processed inline by the same worker as a direct upload, so
        # it must NOT be flagged for an external converter.
        assert body["status"] != "needs_converter"

    async def test_idempotent_returns_existing_model(
        self,
        fromdoc_client: AsyncClient,
        fromdoc_auth: dict[str, str],
        fromdoc_project: str,
    ) -> None:
        doc_id = await _upload_document(
            fromdoc_client,
            fromdoc_auth,
            fromdoc_project,
            filename="reused.ifc",
            content=_MINIMAL_IFC,
        )

        first = await _from_document(fromdoc_client, fromdoc_auth, doc_id)
        assert first.status_code == 201, first.text
        first_model_id = first.json()["model_id"]
        assert first.json()["already_existed"] is False

        # Second call for the SAME document must not convert again.
        second = await _from_document(fromdoc_client, fromdoc_auth, doc_id)
        assert second.status_code == 201, second.text
        second_body = second.json()
        assert second_body["already_existed"] is True
        assert second_body["model_id"] == first_model_id

    async def test_dwg_document_flagged_needs_converter(
        self,
        fromdoc_client: AsyncClient,
        fromdoc_auth: dict[str, str],
        fromdoc_project: str,
    ) -> None:
        doc_id = await _upload_document(
            fromdoc_client,
            fromdoc_auth,
            fromdoc_project,
            filename="floorplan.dwg",
            content=_DWG_HEADER,
        )

        resp = await _from_document(fromdoc_client, fromdoc_auth, doc_id)
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["model_id"], body
        assert body["format"] == "dwg"
        assert body["status"] == "needs_converter"
        assert body["error_message"], "needs_converter must explain why"

    async def test_non_cad_document_rejected(
        self,
        fromdoc_client: AsyncClient,
        fromdoc_auth: dict[str, str],
        fromdoc_project: str,
    ) -> None:
        doc_id = await _upload_document(
            fromdoc_client,
            fromdoc_auth,
            fromdoc_project,
            filename="notes.txt",
            content=b"just some project notes, not a model\n",
        )

        resp = await _from_document(fromdoc_client, fromdoc_auth, doc_id)
        assert resp.status_code == 400, resp.text
        assert "convertible" in (resp.json().get("detail") or "").lower()

    async def test_missing_document_returns_404(
        self,
        fromdoc_client: AsyncClient,
        fromdoc_auth: dict[str, str],
    ) -> None:
        resp = await _from_document(
            fromdoc_client,
            fromdoc_auth,
            str(uuid.uuid4()),
        )
        assert resp.status_code == 404, resp.text
