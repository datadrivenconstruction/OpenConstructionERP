"""Integration tests for the BIM upload converter preflight.

Covers:
    * Test A — ``.rvt`` upload with no converter installed → 202 with
      ``status="converter_required"``, the upload **persisted** and a
      placeholder model row created.
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

Two contract changes have landed since this file was written for v1.4.7
and Test A / Test C now assert the current behaviour instead:

    * ``f58d36fab`` (v2.6.28, "BUG-RVT03/04 — converter_required upload
      now persists file + 202 Accepted") turned the missing-converter
      response from "refuse and keep nothing" into "save the upload,
      create a ``needs_converter`` model row, answer 202 Accepted". Test
      A used to assert ``model_id is None`` / ``name is None`` /
      ``file_size == 0``; that "nothing was persisted" contract is gone
      deliberately, because re-uploading a 500 MB model after running
      the converter install is worse than re-processing a saved one.
    * ``f6d8e50f1`` (v1.9.6/v1.9.7) added ``app/core/file_signature.py``
      and wired ``ALLOWED_CAD_TYPES`` into this upload route, so the
      payload now has to look like the format it claims to be. Test C's
      old fixture (1 KB of zero bytes) is not an RVT and is rejected
      with 400 before the mocked converter is ever consulted, so it now
      uses ``_MINIMAL_RVT`` instead.

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

    from tests.integration._auth_helpers import promote_to_admin

    await promote_to_admin(email)

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
async def preflight_project(preflight_client: AsyncClient, preflight_auth: dict[str, str]) -> str:
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

# An RVT is an OLE compound document, and ``ALLOWED_CAD_TYPES`` accepts the
# ``ole`` token, so the magic-byte guard the upload route gained in
# ``f6d8e50f1`` is happy with the real 8-byte header and nothing else. Same
# header the RVT fixtures in ``tests/unit/test_cad_diagnostics.py`` use; no
# binary blob needed in the repo.
_MINIMAL_RVT = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 1016


async def _upload(
    client: AsyncClient,
    auth: dict[str, str],
    project_id: str,
    *,
    filename: str,
    content: bytes,
    expect_status: tuple[int, ...] = (200, 201),
) -> dict:
    resp = await client.post(
        "/api/v1/bim_hub/upload-cad/",
        params={"project_id": project_id, "name": filename, "discipline": "architecture"},
        files={"file": (filename, io.BytesIO(content), "application/octet-stream")},
        headers=auth,
    )
    assert resp.status_code in expect_status, f"Upload failed ({resp.status_code}): {resp.text}"
    return resp.json()


# ── Tests ──────────────────────────────────────────────────────────────────


class TestBimUploadConverterPreflight:
    """Converter preflight + response-shape coverage."""

    # Name kept for continuity: what is refused upfront is the *conversion*,
    # decided before the file is handed to any converter. The upload itself
    # is accepted (202) and kept, see the contract note in the module
    # docstring.
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
        monkeypatch.setattr(cad_import_mod, "converter_supported_here", lambda: True)

        # Deliberately NOT a valid RVT: the preflight short-circuits above
        # the magic-byte guard, so these bytes are never sniffed on this
        # path. If the guard is ever reordered ahead of the preflight this
        # upload starts failing with 400, which is the signal we want.
        content = _MINIMAL_RVT
        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="tiny.rvt",
            content=content,
            expect_status=(202,),
        )

        assert body["status"] == "converter_required", body
        assert body["converter_id"] == "rvt"
        assert body["install_endpoint"] == "/api/v1/takeoff/converters/rvt/install/"
        assert "RVT" in (body.get("message") or "")
        # Since f58d36fab the upload is kept rather than discarded, so the
        # response carries the saved file's identity instead of the empty
        # placeholders v1.4.7 returned.
        assert body["model_id"] is not None, body
        uuid.UUID(str(body["model_id"]))
        assert body["name"] == "tiny.rvt"
        assert body["file_size"] == len(content)
        # Nothing was converted, the converter is what is missing, so the
        # element count is 0 even though the bytes were persisted.
        assert body["element_count"] == 0

        # The persistence half of the contract: a placeholder row exists and
        # is waiting for the converter.
        listing = await preflight_client.get(
            "/api/v1/bim_hub/",
            params={"project_id": preflight_project},
            headers=preflight_auth,
        )
        assert listing.status_code == 200, listing.text
        pending = [m for m in listing.json()["items"] if m["name"] == "tiny.rvt"]
        assert len(pending) == 1, listing.json()["items"]
        assert pending[0]["status"] == "needs_converter"
        assert pending[0]["model_format"] == "rvt"

        # The returned id has to be the row's id. It was not: the route minted
        # a UUID to key the saved blob with, before any row existed, and
        # returned that instead of the primary key the database handed back, so
        # this GET answered 404 and the reprocess link in the ``Link`` header
        # addressed nothing. The message the same response carries tells people
        # to click Re-process, which is the thing that id is for. Asserted
        # against the listing's own id so the two cannot drift apart again.
        assert body["model_id"] == pending[0]["id"], (body["model_id"], pending[0]["id"])
        detail = await preflight_client.get(
            f"/api/v1/bim_hub/{body['model_id']}",
            headers=preflight_auth,
        )
        assert detail.status_code == 200, f"returned model_id does not resolve: {detail.text}"
        assert detail.json()["status"] == "needs_converter"

    async def test_reprocess_link_addresses_the_row_that_was_created(
        self,
        preflight_client: AsyncClient,
        preflight_auth: dict[str, str],
        preflight_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The ``Link`` header's reprocess URL must name the row, not the blob key.

        Asserted separately from the body because the two were built from the
        same wrong variable and a reader checking only the body would call the
        pair fixed. A client that follows the header rather than reading the
        JSON is the one this route was given a ``Link`` header for.
        """
        import app.modules.boq.cad_import as cad_import_mod

        monkeypatch.setattr(cad_import_mod, "find_converter", lambda _ext: None)
        monkeypatch.setattr(cad_import_mod, "converter_supported_here", lambda: True)

        resp = await preflight_client.post(
            "/api/v1/bim_hub/upload-cad/",
            params={
                "project_id": preflight_project,
                "name": "linkcheck.rvt",
                "discipline": "architecture",
            },
            files={"file": ("linkcheck.rvt", io.BytesIO(_MINIMAL_RVT), "application/octet-stream")},
            headers=preflight_auth,
        )
        assert resp.status_code == 202, resp.text
        model_id = resp.json()["model_id"]

        link = resp.headers.get("Link") or ""
        assert 'rel="reprocess-model"' in link, link
        assert f"/api/v1/bim_hub/{model_id}/retry/" in link, link

        # And the URL that header advertises has to be a real endpoint on a
        # real row. A retry answers 202 when it has something to retry.
        retry = await preflight_client.post(
            f"/api/v1/bim_hub/{model_id}/retry/",
            headers=preflight_auth,
        )
        assert retry.status_code != 404, f"reprocess link points at no row: {retry.text}"

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
        monkeypatch.setattr(cad_import_mod, "converter_supported_here", lambda: True)

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
        monkeypatch.setattr(cad_import_mod, "find_converter", lambda _ext: fake_exe)

        # Past the preflight the magic-byte guard runs, so the payload has to
        # carry the OLE header a real RVT has: zero bytes are refused with
        # 400 before the mocked converter is reached.
        body = await _upload(
            preflight_client,
            preflight_auth,
            preflight_project,
            filename="passthrough.rvt",
            content=_MINIMAL_RVT,
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
