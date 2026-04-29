"""Integration tests for BIM model persistence policy (v2.6.29).

Covers the user-visible promise: "uploaded BIM models stay visible on
/bim revisit without re-conversion".  The persistence policy:

    * Conversion artifacts (GLB/DAE/parquet/thumbnails) — kept forever.
    * Raw original CAD upload — dropped after success when
      ``settings.keep_original_cad`` is False (production default), kept
      otherwise so retry works without re-upload.
    * Failed conversion — original kept regardless so the user can retry.

Tests in this module exercise the full upload → convert → list cycle
with mocked converter results so they stay deterministic and fast (no
real DDC binary required).
"""

from __future__ import annotations

import asyncio
import io
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.modules.bim_hub import file_storage as bim_file_storage


# ── Module-scoped fixtures ─────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def persist_client():
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
async def persist_auth(persist_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bimpersist-{unique}@test.io"
    password = f"BimPst{unique}9"

    reg = await persist_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM Persistence Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    token = ""
    for attempt in range(3):
        resp = await persist_client.post(
            "/api/v1/users/auth/login",
            json={"email": email, "password": password},
        )
        data = resp.json()
        token = data.get("access_token", "")
        if token:
            break
        if "Too many login attempts" in (data.get("detail") or ""):
            await asyncio.sleep(5 * (attempt + 1))
            continue
        break
    assert token, f"Login failed: {data}"
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture(scope="module")
async def persist_project(
    persist_client: AsyncClient, persist_auth: dict[str, str]
) -> str:
    resp = await persist_client.post(
        "/api/v1/projects/",
        json={
            "name": f"BIMPersist Project {uuid.uuid4().hex[:6]}",
            "description": "BIM persistence test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=persist_auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


# ── Helpers ────────────────────────────────────────────────────────────────


_MINIMAL_IFC = (
    b"ISO-10303-21;\n"
    b"HEADER;\n"
    b"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
    b"FILE_NAME('persist.ifc','2026-04-29T00:00:00',('tester'),('oe'),'test','test','');\n"
    b"FILE_SCHEMA(('IFC4'));\n"
    b"ENDSEC;\n"
    b"DATA;\n"
    b"ENDSEC;\n"
    b"END-ISO-10303-21;\n"
)


def _fake_conversion_result(_cad_path, tmp_dir, _depth) -> dict[str, Any]:
    """Drop-in stand-in for ``process_ifc_file``.

    Writes a tiny GLB to ``tmp_dir/geometry.glb`` so the upload pipeline
    has something to persist as a "conversion artifact", then returns a
    one-element result dict matching the real shape closely enough for
    the BIM model row to flip to ``status="ready"``.
    """
    geo_path = tmp_dir / "geometry.glb"
    # Minimal GLB header padded to ~2 MB so the aggregate disk-usage
    # assertion in test_list_endpoint_returns_persisted_models_with_metadata
    # has > 0 MB to round to (we round to 3 decimals; 2 MB = 2.0 MB, well
    # above the rounding floor).  Real GLBs are MB-scale so this is also
    # a more representative fixture than a 64-byte placeholder.
    geo_path.write_bytes(
        b"glTF" + b"\x02\x00\x00\x00" + b"\x40\x00\x00\x00" + (b"\x00" * (2 * 1024 * 1024))
    )

    return {
        "element_count": 1,
        "elements": [
            {
                "stable_id": "elem-001",
                "element_type": "wall",
                "name": "Test Wall",
                "storey": "L1",
                "discipline": "architectural",
                "properties": {},
                "quantities": {"area": 12.5, "volume": 3.0},
                "geometry_hash": "abc123",
                "bounding_box": None,
                "mesh_ref": "elem-001",
            }
        ],
        "storeys": ["L1"],
        "raw_elements": [
            {"stable_id": "elem-001", "element_type": "wall", "discipline": "arch"}
        ],
        "geometry_path": str(geo_path),
        "glb_path": str(geo_path),
        "geometry_type": "real",
        "geometry_quality": "real",
        "bounding_box": {"min": [0, 0, 0], "max": [10, 3, 0.2]},
    }


def _fake_zero_element_result(_cad_path, _tmp_dir, _depth) -> dict[str, Any]:
    """Conversion that produces zero elements — drives the failure path
    where the model lands in ``error`` / ``needs_converter`` and the
    original CAD blob must be preserved."""
    return {
        "element_count": 0,
        "elements": [],
        "storeys": [],
        "raw_elements": [],
        "geometry_path": None,
        "glb_path": None,
        "geometry_type": "unknown",
        "bounding_box": None,
    }


async def _wait_for_status(
    client: AsyncClient, headers: dict[str, str], model_id: str
) -> str:
    """Poll the model status until it leaves ``processing`` or 30× 0.25s."""
    for _ in range(40):
        resp = await client.get(f"/api/v1/bim_hub/{model_id}", headers=headers)
        if resp.status_code == 200:
            status = resp.json().get("status")
            if status and status != "processing":
                return status
        await asyncio.sleep(0.25)
    return "processing"


async def _upload_ifc(
    client: AsyncClient, headers: dict[str, str], project_id: str, name: str
) -> str:
    resp = await client.post(
        "/api/v1/bim_hub/upload-cad/",
        params={"project_id": project_id, "name": name, "discipline": "architecture"},
        files={"file": (f"{name}.ifc", io.BytesIO(_MINIMAL_IFC), "application/octet-stream")},
        headers=headers,
    )
    assert resp.status_code in (200, 201), f"Upload failed: {resp.text}"
    body = resp.json()
    model_id = body.get("model_id")
    assert model_id, body
    return model_id


# ── Tests ──────────────────────────────────────────────────────────────────


class TestBimPersistence:
    """Storage-policy + list-endpoint coverage for /bim revisit-without-reconvert."""

    async def test_artifacts_persist_after_successful_conversion(
        self,
        persist_client: AsyncClient,
        persist_auth: dict[str, str],
        persist_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After a successful upload → convert cycle, the GLB artifact
        must still be on storage when we re-query the project list, and
        the original CAD blob must be GONE (production policy)."""
        # Default ``keep_original_cad`` is False — assert the policy
        # without touching settings.
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_result,
        )

        model_id = await _upload_ifc(
            persist_client, persist_auth, persist_project, "persist-success"
        )
        status = await _wait_for_status(persist_client, persist_auth, model_id)
        assert status == "ready", f"Expected ready, got {status}"

        # Artifact must persist.
        size_bytes = await bim_file_storage.compute_artifact_size_bytes(
            persist_project, model_id,
        )
        assert size_bytes > 0, "GLB artifact disappeared after conversion"

        # Original must have been swept (production keep_original_cad=False).
        has_orig = await bim_file_storage.has_original_cad(
            persist_project, model_id, ext=".ifc",
        )
        assert has_orig is False, (
            "Original CAD blob still on storage despite keep_original_cad=False"
        )

    async def test_keep_original_cad_true_keeps_both(
        self,
        persist_client: AsyncClient,
        persist_auth: dict[str, str],
        persist_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """With ``keep_original_cad=True`` the original blob survives."""
        from app.config import get_settings

        # Flip the setting on the cached singleton — get_settings is
        # @lru_cache so we mutate the instance in place.  Restored on
        # teardown.
        settings = get_settings()
        original_value = settings.keep_original_cad
        settings.keep_original_cad = True
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_result,
        )

        try:
            model_id = await _upload_ifc(
                persist_client, persist_auth, persist_project, "persist-keep"
            )
            status = await _wait_for_status(
                persist_client, persist_auth, model_id
            )
            assert status == "ready"

            has_orig = await bim_file_storage.has_original_cad(
                persist_project, model_id, ext=".ifc",
            )
            assert has_orig is True, (
                "Original CAD blob removed even though keep_original_cad=True"
            )

            size_bytes = await bim_file_storage.compute_artifact_size_bytes(
                persist_project, model_id,
            )
            assert size_bytes > 0
        finally:
            settings.keep_original_cad = original_value

    async def test_failed_conversion_keeps_original(
        self,
        persist_client: AsyncClient,
        persist_auth: dict[str, str],
        persist_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Zero-element conversion → status='error' (or 'needs_converter')
        and the original blob is preserved so the user can retry without
        re-uploading."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_zero_element_result,
        )

        model_id = await _upload_ifc(
            persist_client, persist_auth, persist_project, "persist-fail"
        )
        status = await _wait_for_status(
            persist_client, persist_auth, model_id
        )
        # Both terminal failure states are acceptable — the contract is
        # only that the original blob survives.
        assert status in {"error", "needs_converter"}, status

        has_orig = await bim_file_storage.has_original_cad(
            persist_project, model_id, ext=".ifc",
        )
        assert has_orig is True, (
            "Original CAD blob deleted after a FAILED conversion — "
            "retry would now require a re-upload."
        )

    async def test_list_endpoint_returns_persisted_models_with_metadata(
        self,
        persist_client: AsyncClient,
        persist_auth: dict[str, str],
        persist_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``GET /api/v1/bim_hub/?project_id=...`` returns every persisted
        model sorted by created_at desc, each with the new
        ``conversion_artifact_size_mb`` / ``has_original`` fields and
        the response carrying aggregate ``total_artifact_size_mb``."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_result,
        )

        # Upload two models so we can verify desc ordering. SQLite's
        # CURRENT_TIMESTAMP is second-resolution, so we sleep a full
        # second between the two uploads to guarantee distinct
        # created_at values for the desc-ordering assertion.
        first = await _upload_ifc(
            persist_client, persist_auth, persist_project, "persist-list-1"
        )
        await _wait_for_status(persist_client, persist_auth, first)
        await asyncio.sleep(1.1)
        second = await _upload_ifc(
            persist_client, persist_auth, persist_project, "persist-list-2"
        )
        await _wait_for_status(persist_client, persist_auth, second)

        resp = await persist_client.get(
            f"/api/v1/bim_hub/?project_id={persist_project}",
            headers=persist_auth,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()

        items = body["items"]
        assert len(items) >= 2

        # Each item must carry the new fields (None or value, never absent).
        for item in items:
            assert "conversion_artifact_size_mb" in item
            assert "has_original" in item
            assert "error_code" in item

        # Aggregate fields must be present on the list response.
        assert "total_artifact_size_mb" in body
        assert "total_original_size_mb" in body
        assert "storage_root_label" in body
        assert body["storage_root_label"], "storage_root_label must be a non-empty label"

        # Ordering: created_at desc — the most-recent upload (`second`)
        # should come first amongst rows with the matching ids in this list.
        ids = [it["id"] for it in items]
        assert ids.index(second) < ids.index(first), (
            f"Expected newest first, got {ids}"
        )

        # At least one ready model means total_artifact_size_mb > 0.
        ready_items = [it for it in items if it["status"] == "ready"]
        if ready_items:
            assert body["total_artifact_size_mb"] > 0, (
                "Aggregate artifact size must reflect ready models"
            )
