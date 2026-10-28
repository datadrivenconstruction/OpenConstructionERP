# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Front-door OOM guards on the BIM Hub upload endpoint.

``upload_bim_data`` used to ``await file.read()`` both the element table and
the geometry blob with no size cap, and handed the xlsx straight to openpyxl
with no decompression-bomb guard - a single large drop could push the 3 GB
box into swap and OOM-kill the worker for everyone.

These tests call the router handler directly (no ASGI / DB): the project
access check and the service are stubbed, so they prove the guard behaviour
and the normal-upload happy path in isolation. They assert that:

    1. an oversized element table is rejected with 413 (streamed cap),
    2. an xlsx decompression bomb is rejected with 413 before openpyxl,
    3. an oversized geometry blob is rejected with 413 and no model is
       created (the guard fires before persistence),
    4. a normal CSV upload still converts to elements,
    5. geometry is persisted from the on-disk temp path (never a RAM blob),
    6. every extension the refusal message advertises can really be accepted.

Mirrors the direct-handler patch style of
``test_documents_revision_folder_write_gate.py``.
"""

from __future__ import annotations

import io
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import BackgroundTasks, HTTPException, UploadFile

import app.core.upload_guards as upload_guards
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub import router as bim_router
from app.modules.bim_hub.mesh_formats import is_mesh_geometry_ext


def _upload(data: bytes, filename: str) -> UploadFile:
    """A minimal UploadFile backed by an in-memory buffer."""
    return UploadFile(filename=filename, file=io.BytesIO(data))


def _make_service() -> AsyncMock:
    """Stub BIMHubService: no DB, mirrors imported elements back."""
    service = AsyncMock()
    service.create_model = AsyncMock(return_value=SimpleNamespace(id=uuid.uuid4()))
    service.bulk_import_elements = AsyncMock(
        side_effect=lambda model_id, elements: [  # noqa: ARG005 - model_id unused by stub
            SimpleNamespace(storey=e.storey, discipline=e.discipline) for e in elements
        ],
    )
    return service


async def _call(
    service: AsyncMock,
    data_file: UploadFile,
    geometry_file: UploadFile | None = None,
) -> dict:
    """Invoke the handler with the project-access + rate-limiter gates neutralised."""
    with (
        patch.object(bim_router, "_verify_project_access", new=AsyncMock(return_value=None)),
        patch.object(bim_router.upload_limiter, "is_allowed", new=lambda _key: (True, 0)),
    ):
        return await bim_router.upload_bim_data(
            background_tasks=BackgroundTasks(),
            project_id=str(uuid.uuid4()),
            name="Imported Model",
            discipline="architecture",
            data_file=data_file,
            geometry_file=geometry_file,
            user_id="user-1",
            _perm=None,
            service=service,
        )


@pytest.mark.asyncio
async def test_oversized_data_file_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """An element table past the cap is streamed, aborted, and returned as 413."""
    monkeypatch.setattr(bim_router, "MAX_BIM_DATA_BYTES", 16)
    oversized = _upload(b"element_id\n" + b"x" * 128, "elements.csv")

    with pytest.raises(HTTPException) as exc:
        await _call(_make_service(), oversized)

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_xlsx_decompression_bomb_rejected_413(monkeypatch: pytest.MonkeyPatch) -> None:
    """A zip whose uncompressed payload exceeds the cap is 413'd before openpyxl."""
    monkeypatch.setattr(
        bim_router,
        "reject_if_xlsx_bomb",
        lambda content: upload_guards.reject_if_xlsx_bomb(content, max_uncompressed=1024),
    )
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        # ~4 KB uncompressed but a few bytes on the wire - the classic bomb shape.
        zf.writestr("xl/worksheets/sheet1.xml", b"<v>0</v>" * 512)

    with pytest.raises(HTTPException) as exc:
        await _call(_make_service(), _upload(buf.getvalue(), "elements.xlsx"))

    assert exc.value.status_code == 413


@pytest.mark.asyncio
async def test_oversized_geometry_rejected_before_model_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized geometry blob is 413'd and never reaches model creation."""
    monkeypatch.setattr(bim_router, "MAX_BIM_GEOMETRY_BYTES", 16)
    service = _make_service()
    geometry = _upload(b"y" * 128, "model.glb")

    with pytest.raises(HTTPException) as exc:
        await _call(service, _upload(b"element_id\nE1\n", "elements.csv"), geometry_file=geometry)

    assert exc.value.status_code == 413
    service.create_model.assert_not_called()


@pytest.mark.asyncio
async def test_normal_csv_upload_converts() -> None:
    """A normal CSV drop still parses and imports every element."""
    service = _make_service()
    csv_bytes = b"element_id,element_type,storey\nE1,wall,L1\nE2,slab,L2\n"

    result = await _call(service, _upload(csv_bytes, "elements.csv"))

    assert result["element_count"] == 2
    assert result["has_geometry"] is False
    assert result["model_id"] == str(service.create_model.return_value.id)
    service.bulk_import_elements.assert_awaited_once()


@pytest.mark.asyncio
async def test_geometry_persisted_from_temp_path() -> None:
    """Geometry is handed to storage by on-disk path, present at save time."""
    captured: dict[str, object] = {}

    async def _fake_save(
        *,
        project_id: str,
        model_id: str,
        ext: str,
        src_path: Path,
        size: int,
    ) -> str:
        captured.update(exists=src_path.exists(), ext=ext, size=size)
        return f"bim/{project_id}/{model_id}/geometry{ext}"

    service = _make_service()
    geometry_bytes = b"glTF-binary-placeholder"

    with patch.object(bim_file_storage, "save_geometry_from_path", new=_fake_save):
        result = await _call(
            service,
            _upload(b"element_id\nE1\n", "elements.csv"),
            geometry_file=_upload(geometry_bytes, "model.glb"),
        )

    assert result["has_geometry"] is True
    assert captured["exists"] is True  # temp file still on disk when storage is called
    assert captured["ext"] == ".glb"
    assert captured["size"] == len(geometry_bytes)


def test_advertised_cad_extensions_are_all_reachable() -> None:
    """No extension is named as accepted that the mesh guard refuses first.

    Both upload paths run ``is_mesh_geometry_ext`` before consulting
    ``_ALLOWED_CAD_EXTENSIONS``, and the refusal message is built by joining
    that same set. An extension sitting in both is therefore unreachable: it
    can never be accepted, yet it is still advertised as accepted to whoever
    uploaded something else. FBX, OBJ and 3DS were in both for exactly that
    reason, which sent people to the endpoint that cannot take them instead of
    the in-browser importer that can.
    """
    assert bim_router._ALLOWED_CAD_EXTENSIONS, "the accepted list must not be empty"
    for ext in bim_router._ALLOWED_CAD_EXTENSIONS:
        assert not is_mesh_geometry_ext(ext), (
            f"{ext} is advertised as convertible CAD, but the geometry-only mesh "
            f"guard rejects it first, so no upload of it can ever be accepted"
        )
