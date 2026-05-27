"""Integration tests for Parquet sidecar write observability (Task #155).

Covers the silent-failure path in
``_process_cad_in_background`` (``backend/app/modules/bim_hub/router.py``)
where a Parquet write exception used to be swallowed with only a WARN
log. The fix surfaces the failure in three places:

    1. structured logger.error with ``event="bim_parquet_write_failed"``
    2. metadata.parquet_status / parquet_error / parquet_attempted_at
       stamped onto the model row
    3. dedicated ``/parquet-status/`` and ``/parquet/retry/`` endpoints

Tests:
    * test_parquet_success_updates_metadata
    * test_parquet_failure_surfaces_in_metadata_and_log
    * test_parquet_failure_does_not_fail_overall_ingest
    * test_parquet_retry_endpoint_recovers
    * test_parquet_status_endpoint_returns_current_state
"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from contextlib import asynccontextmanager
from typing import Any

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.main import create_app

# ── Module-scoped fixtures ─────────────────────────────────────────────────


@pytest_asyncio.fixture(scope="module")
async def pq_client():
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
async def pq_auth(pq_client: AsyncClient) -> dict[str, str]:
    unique = uuid.uuid4().hex[:8]
    email = f"bimpq-{unique}@test.io"
    password = f"BimPq{unique}9"

    reg = await pq_client.post(
        "/api/v1/users/auth/register",
        json={
            "email": email,
            "password": password,
            "full_name": "BIM Parquet Tester",
            "role": "admin",
        },
    )
    assert reg.status_code == 201, f"Registration failed: {reg.text}"

    token = ""
    data: dict[str, Any] = {}
    for attempt in range(3):
        resp = await pq_client.post(
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
async def pq_project(pq_client: AsyncClient, pq_auth: dict[str, str]) -> str:
    resp = await pq_client.post(
        "/api/v1/projects/",
        json={
            "name": f"BIMPq Project {uuid.uuid4().hex[:6]}",
            "description": "BIM parquet observability test project",
            "region": "DACH",
            "classification_standard": "din276",
            "currency": "EUR",
        },
        headers=pq_auth,
    )
    assert resp.status_code == 201, f"Project create failed: {resp.text}"
    return resp.json()["id"]


# ── Helpers ────────────────────────────────────────────────────────────────


_MINIMAL_IFC = (
    b"ISO-10303-21;\n"
    b"HEADER;\n"
    b"FILE_DESCRIPTION(('ViewDefinition [CoordinationView]'),'2;1');\n"
    b"FILE_NAME('pq.ifc','2026-05-25T00:00:00',('tester'),('oe'),'test','test','');\n"
    b"FILE_SCHEMA(('IFC4'));\n"
    b"ENDSEC;\n"
    b"DATA;\n"
    b"ENDSEC;\n"
    b"END-ISO-10303-21;\n"
)


def _fake_conversion_with_raw_elements(_cad_path, tmp_dir, _depth) -> dict[str, Any]:
    """Deterministic stand-in for ``process_ifc_file`` that always returns
    ``raw_elements`` so the Parquet code path is exercised."""
    geo_path = tmp_dir / "geometry.glb"
    geo_path.write_bytes(b"glTF" + b"\x02\x00\x00\x00" + b"\x40\x00\x00\x00" + (b"\x00" * 1024))
    return {
        "element_count": 2,
        "elements": [
            {
                "stable_id": "el-001",
                "element_type": "wall",
                "name": "Test Wall A",
                "storey": "L1",
                "discipline": "arch",
                "properties": {"material": "concrete"},
                "quantities": {"area": 12.5, "volume": 3.0},
                "geometry_hash": "h001",
                "bounding_box": None,
                "mesh_ref": "el-001",
            },
            {
                "stable_id": "el-002",
                "element_type": "slab",
                "name": "Test Slab B",
                "storey": "L1",
                "discipline": "arch",
                "properties": {"material": "concrete"},
                "quantities": {"area": 50.0, "volume": 12.5},
                "geometry_hash": "h002",
                "bounding_box": None,
                "mesh_ref": "el-002",
            },
        ],
        "storeys": ["L1"],
        "raw_elements": [
            {"stable_id": "el-001", "element_type": "wall", "area": 12.5},
            {"stable_id": "el-002", "element_type": "slab", "area": 50.0},
        ],
        "geometry_path": str(geo_path),
        "glb_path": str(geo_path),
        "geometry_type": "real",
        "geometry_quality": "real",
        "bounding_box": {"min": [0, 0, 0], "max": [10, 3, 0.2]},
    }


async def _wait_for_status(client: AsyncClient, headers: dict[str, str], model_id: str) -> dict[str, Any]:
    """Poll until status leaves 'processing' (max 40 × 0.25s = 10s)."""
    for _ in range(40):
        resp = await client.get(f"/api/v1/bim_hub/{model_id}", headers=headers)
        if resp.status_code == 200:
            body = resp.json()
            if body.get("status") and body["status"] != "processing":
                return body
        await asyncio.sleep(0.25)
    pytest.fail(f"Model {model_id} stuck in processing")


async def _upload_ifc(client: AsyncClient, headers: dict[str, str], project_id: str, name: str) -> str:
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


class TestBimParquetObservability:
    """Task #155 — surface silent Parquet-write failures."""

    async def test_parquet_success_updates_metadata(
        self,
        pq_client: AsyncClient,
        pq_auth: dict[str, str],
        pq_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Successful ingest must stamp parquet_status='ok' on metadata."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_with_raw_elements,
        )

        model_id = await _upload_ifc(pq_client, pq_auth, pq_project, "pq-success")
        body = await _wait_for_status(pq_client, pq_auth, model_id)

        # Model itself flipped to ready.
        assert body["status"] in ("ready", "degraded"), body["status"]

        meta = body.get("metadata") or {}
        assert meta.get("parquet_status") == "ok", f"Expected parquet_status=ok, got meta={meta}"
        assert meta.get("parquet_error") in (None, ""), meta
        assert meta.get("parquet_attempted_at"), "parquet_attempted_at must be set after a Parquet attempt"

    async def test_parquet_failure_surfaces_in_metadata_and_log(
        self,
        pq_client: AsyncClient,
        pq_auth: dict[str, str],
        pq_project: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """A raised Parquet write must land in metadata + structured log."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_with_raw_elements,
        )

        def _boom(**_kwargs: Any) -> None:
            raise OSError("simulated disk full")

        # Patch in the router's import namespace too — write_dataframe is
        # imported inside the try block at call time, so monkeypatching
        # the source module is the right spot.
        monkeypatch.setattr(
            "app.modules.bim_hub.dataframe_store.write_dataframe",
            _boom,
        )

        caplog.set_level(logging.ERROR, logger="app.modules.bim_hub.router")

        model_id = await _upload_ifc(pq_client, pq_auth, pq_project, "pq-fail")
        body = await _wait_for_status(pq_client, pq_auth, model_id)

        meta = body.get("metadata") or {}
        assert meta.get("parquet_status") == "failed", f"Expected parquet_status=failed, got meta={meta}"
        assert "simulated disk full" in (meta.get("parquet_error") or ""), (
            f"Error string must mention the original message, got {meta.get('parquet_error')!r}"
        )

        # Structured log event must have fired with the right event tag.
        matched = [
            r
            for r in caplog.records
            if getattr(r, "event", None) == "bim_parquet_write_failed" and getattr(r, "model_id", None) == model_id
        ]
        assert matched, (
            "Expected structured log event 'bim_parquet_write_failed' "
            f"for model_id={model_id} — none found in caplog "
            f"(records: {[r.message for r in caplog.records]!r})"
        )
        # And the structured payload carries the labels the future
        # metrics surface (or log-based counter) needs.
        first = matched[0]
        assert first.levelno == logging.ERROR
        assert getattr(first, "metric", None) == "bim_parquet_write_failed_total"
        assert getattr(first, "exception_type", None) == "OSError"
        assert getattr(first, "row_count", 0) >= 1

    async def test_parquet_failure_does_not_fail_overall_ingest(
        self,
        pq_client: AsyncClient,
        pq_auth: dict[str, str],
        pq_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A Parquet write failure must NOT mark the model as error."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_with_raw_elements,
        )

        def _boom(**_kwargs: Any) -> None:
            raise RuntimeError("nope")

        monkeypatch.setattr(
            "app.modules.bim_hub.dataframe_store.write_dataframe",
            _boom,
        )

        model_id = await _upload_ifc(pq_client, pq_auth, pq_project, "pq-nonfatal")
        body = await _wait_for_status(pq_client, pq_auth, model_id)

        # Parquet failure is non-fatal — model itself must still be usable.
        assert body["status"] in ("ready", "degraded"), f"Parquet failure leaked into model.status: {body['status']}"
        # Element rows must have landed too.
        assert body["element_count"] >= 1, body

    async def test_parquet_retry_endpoint_recovers(
        self,
        pq_client: AsyncClient,
        pq_auth: dict[str, str],
        pq_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """After a failed write, the retry endpoint can recover from DB rows."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_with_raw_elements,
        )

        # First upload — patched to fail Parquet write.
        call_count = {"n": 0}

        def _boom_once(**_kwargs: Any) -> None:
            call_count["n"] += 1
            raise OSError("first attempt fails")

        monkeypatch.setattr(
            "app.modules.bim_hub.dataframe_store.write_dataframe",
            _boom_once,
        )

        model_id = await _upload_ifc(pq_client, pq_auth, pq_project, "pq-retry")
        body = await _wait_for_status(pq_client, pq_auth, model_id)
        meta = body.get("metadata") or {}
        assert meta.get("parquet_status") == "failed", meta

        # Swap in a no-op writer so the retry succeeds. The patch path is
        # the source module so both call sites pick it up.
        def _ok(**_kwargs: Any) -> None:
            return None

        monkeypatch.setattr(
            "app.modules.bim_hub.dataframe_store.write_dataframe",
            _ok,
        )

        retry_resp = await pq_client.post(
            f"/api/v1/bim_hub/models/{model_id}/parquet/retry/",
            headers=pq_auth,
        )
        assert retry_resp.status_code == 202, retry_resp.text
        retry_body = retry_resp.json()
        assert retry_body["status"] == "ok", retry_body
        assert retry_body["rows_attempted"] >= 1

        # The model row's metadata is now updated.
        post = await pq_client.get(
            f"/api/v1/bim_hub/{model_id}",
            headers=pq_auth,
        )
        post_meta = (post.json() or {}).get("metadata") or {}
        assert post_meta.get("parquet_status") == "ok", post_meta
        assert post_meta.get("parquet_error") in (None, "")

    async def test_parquet_status_endpoint_returns_current_state(
        self,
        pq_client: AsyncClient,
        pq_auth: dict[str, str],
        pq_project: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """The dedicated status endpoint mirrors the metadata fields."""
        monkeypatch.setattr(
            "app.modules.bim_hub.ifc_processor.process_ifc_file",
            _fake_conversion_with_raw_elements,
        )
        monkeypatch.setattr(
            "app.modules.bim_hub.dataframe_store.write_dataframe",
            lambda **_k: None,
        )

        model_id = await _upload_ifc(pq_client, pq_auth, pq_project, "pq-status")
        await _wait_for_status(pq_client, pq_auth, model_id)

        resp = await pq_client.get(
            f"/api/v1/bim_hub/models/{model_id}/parquet-status/",
            headers=pq_auth,
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["model_id"] == model_id
        assert body["status"] == "ok"
        assert body["error"] in (None, "")
        assert body["attempted_at"], body
        assert body["retry_endpoint"].endswith(f"/models/{model_id}/parquet/retry/")
