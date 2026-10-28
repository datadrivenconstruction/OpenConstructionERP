"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Reality-capture / drone auto-categorisation tests (issue #288).

Scope
-----
A reality-capture or drone-survey point cloud dropped into the generic
documents upload path must be recognised, given the dedicated
``reality_capture`` category and tagged, mirroring how a photo upload becomes a
site picture. This suite verifies:

    1. ``_reality_capture_extension`` detects every point-cloud extension and
       ignores ordinary document / drawing extensions.
    2. ``reality_capture`` is a registered document category.
    3. ``DocumentService.upload_document`` auto-assigns ``reality_capture`` when
       the caller left the category unspecified (``other``) and the file is a
       point cloud, tagging it, while an explicit category always wins.
    4. Point-cloud bytes (LAS ``LASF``, E57 ``ASTM-E57``) pass the existing
       magic-byte gate - they are unknown blobs the detector tolerates, exactly
       like the CSV/JSON/TXT uploads already accepted, so no security gate is
       weakened.

All tests are pure-Python (no DB, no filesystem). The repository and file-write
I/O are stubbed so the tests run on py3.11 in CI without PostgreSQL.
"""

from __future__ import annotations

import io
import uuid
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import UploadFile

from app.modules.documents.service import (
    REALITY_CAPTURE_EXTENSIONS,
    VALID_CATEGORIES,
    _reality_capture_extension,
)

# ── 1. Extension detector ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "filename,expected",
    [
        ("site-scan.las", ".las"),
        ("survey.LAZ", ".laz"),  # case-insensitive
        ("cloud.e57", ".e57"),
        ("optimised.copc", ".copc"),
        ("mesh.ply", ".ply"),
        ("frame.pcd", ".pcd"),
        ("leica.pts", ".pts"),
        ("raw.xyz", ".xyz"),
        ("scan.v2.las", ".las"),  # multi-dot benign
    ],
)
def test_reality_capture_extension_detects_point_clouds(filename: str, expected: str) -> None:
    assert _reality_capture_extension(filename) == expected


@pytest.mark.parametrize(
    "filename",
    [
        "plan.pdf",
        "contract.docx",
        "drawing.dwg",
        "model.ifc",
        "orthomosaic.tif",  # deliberate boundary: geotiff is NOT auto-detected
        "aerial.tiff",
        "photo.jpg",
        "notes.txt",
        "noextension",
    ],
)
def test_reality_capture_extension_ignores_non_point_clouds(filename: str) -> None:
    assert _reality_capture_extension(filename) is None


def test_every_listed_extension_is_detected() -> None:
    for ext in REALITY_CAPTURE_EXTENSIONS:
        assert _reality_capture_extension(f"file{ext}") == ext


# ── 2. Category registration ───────────────────────────────────────────────


def test_reality_capture_is_valid_category() -> None:
    assert "reality_capture" in VALID_CATEGORIES


# ── 3. Service auto-categorisation ─────────────────────────────────────────
#
# LAS files begin with the ASCII signature ``LASF``; E57 files with
# ``ASTM-E57``. Neither is a recognised magic-byte token, so ``detect`` returns
# None and the upload gate tolerates them (same as plain-text data uploads).

_LAS_HEADER = b"LASF" + b"\x00" * 20
_E57_HEADER = b"ASTM-E57" + b"\x00" * 16


def _make_upload_file(filename: str, content: bytes) -> UploadFile:
    """Build a real BytesIO-backed FastAPI ``UploadFile`` for tests.

    A real UploadFile (not a MagicMock) is used so the service's streaming read
    - ``file.read(chunk)`` in a loop until EOF - terminates. A mock whose
    ``read`` ignores the size argument and returns the whole body on every call
    would spin forever.
    """
    return UploadFile(
        filename=filename,
        file=io.BytesIO(content),
        headers={"content-type": "application/octet-stream"},
    )


async def _run_upload(filename: str, content: bytes, category: str) -> Any:
    """Drive ``upload_document`` with stubbed repo + filesystem, return the doc."""
    from app.modules.documents.service import DocumentService

    session = AsyncMock()
    svc = DocumentService(session)

    async def _echo_create(doc: Any) -> Any:
        if getattr(doc, "id", None) is None:
            doc.id = uuid.uuid4()
        return doc

    repo_mock = AsyncMock()
    repo_mock.create = AsyncMock(side_effect=_echo_create)
    svc.repo = repo_mock

    upload = _make_upload_file(filename, content)
    project_id = uuid.uuid4()

    with (
        patch("app.modules.documents.service.UPLOAD_BASE") as mock_base,
        patch("app.modules.documents.service.record_activity", new_callable=AsyncMock),
        patch("app.modules.documents.service._register_version_safely", new_callable=AsyncMock),
    ):
        mock_path = MagicMock()
        mock_path.__truediv__ = MagicMock(return_value=mock_path)
        mock_path.mkdir = MagicMock()
        mock_path.write_bytes = MagicMock()
        mock_base.__truediv__ = MagicMock(return_value=mock_path)

        return await svc.upload_document(project_id, upload, category, "user-1")


@pytest.mark.asyncio
async def test_las_upload_auto_categorised_as_reality_capture() -> None:
    doc = await _run_upload("site-scan.las", _LAS_HEADER, "other")
    assert doc.category == "reality_capture"
    assert "reality-capture" in doc.tags
    assert "las" in doc.tags


@pytest.mark.asyncio
async def test_e57_upload_auto_categorised_as_reality_capture() -> None:
    doc = await _run_upload("building.e57", _E57_HEADER, "other")
    assert doc.category == "reality_capture"


@pytest.mark.asyncio
async def test_explicit_category_wins_over_auto_detection() -> None:
    # A point cloud filed under an explicit category keeps that category.
    doc = await _run_upload("site-scan.las", _LAS_HEADER, "drawing")
    assert doc.category == "drawing"
    assert doc.tags == []


@pytest.mark.asyncio
async def test_ordinary_document_not_categorised_as_reality_capture() -> None:
    pdf_bytes = b"%PDF-1.7\n" + b"\x00" * 20
    doc = await _run_upload("report.pdf", pdf_bytes, "other")
    assert doc.category == "other"
