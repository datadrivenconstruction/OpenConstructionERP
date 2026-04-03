"""Takeoff HTTP endpoints.

Routes:
    GET    /converters                          — list CAD/BIM converter status
    POST   /converters/{converter_id}/install   — download & install a converter
    POST   /converters/{converter_id}/uninstall — remove an installed converter
    POST   /documents/upload                    — upload a PDF for takeoff
    GET    /documents/                          — list uploaded documents
    GET    /documents/{doc_id}                  — get single document
    POST   /documents/{doc_id}/extract-tables   — extract tables from document
    POST   /documents/{doc_id}/analyze          — AI analysis of extracted text
    GET    /documents/{doc_id}/download          — download the stored PDF file
    DELETE /documents/{doc_id}                  — delete a document
"""

import logging
import shutil
import time as _time
import uuid as _uuid
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.takeoff.schemas import TakeoffDocumentResponse
from app.modules.takeoff.service import TakeoffService

logger = logging.getLogger(__name__)

router = APIRouter(tags=["takeoff"])


# ── Converter status ─────────────────────────────────────────────────────


_CONVERTER_META: list[dict[str, Any]] = [
    {
        "id": "dwg",
        "name": "DWG/DXF Converter",
        "description": "Import AutoCAD DWG and DXF files. Extracts geometry, layers, blocks, and properties into structured element tables for cost estimation.",
        "engine": "DDC Community",
        "extensions": [".dwg", ".dxf"],
        "exe": "DwgExporter.exe",
        "version": "1.0.0",
        "size_mb": 245.0,
    },
    {
        "id": "rvt",
        "name": "Revit (RVT) Parser",
        "description": "Native Revit file parser. No Autodesk license required. Extracts families, parameters, quantities, and spatial structure.",
        "engine": "DDC Community",
        "extensions": [".rvt", ".rfa"],
        "exe": "RvtExporter.exe",
        "version": "0.5.0",
        "size_mb": 128.0,
    },
    {
        "id": "ifc",
        "name": "IFC Import",
        "description": "Import IFC 2x3 and IFC4 files. Maps IFC entities to structured element tables with full property set extraction.",
        "engine": "DDC Community",
        "extensions": [".ifc", ".ifczip"],
        "exe": "IfcExporter.exe",
        "version": "1.0.0",
        "size_mb": 195.0,
    },
    {
        "id": "dgn",
        "name": "DGN Converter",
        "description": "Import MicroStation DGN files. Extracts elements, levels, properties, and 3D geometry into structured tables.",
        "engine": "DDC Community",
        "extensions": [".dgn"],
        "exe": "DgnExporter.exe",
        "version": "1.0.0",
        "size_mb": 180.0,
    },
]


@router.get("/converters")
async def list_converters() -> dict[str, Any]:
    """Return the status of all known CAD/BIM converters.

    Scans standard install paths and returns which converters are found.
    No authentication required — this is a public status check.
    """
    from app.modules.boq.cad_import import find_converter

    converters: list[dict[str, Any]] = []
    for meta in _CONVERTER_META:
        ext = meta["id"]
        path = find_converter(ext)
        converters.append({
            **meta,
            "installed": path is not None,
            "path": str(path) if path else None,
        })

    installed_count = sum(1 for c in converters if c["installed"])
    return {
        "converters": converters,
        "installed_count": installed_count,
        "total_count": len(converters),
    }

# ── Converter install / uninstall ────────────────────────────────────────


_GITHUB_CONVERTER_BASE_URL = (
    "https://github.com/datadrivenconstruction/"
    "ddc-community-toolkit/releases/download/v1.0.0"
)

_GITHUB_CONVERTER_FILES: dict[str, str] = {
    "dwg": "DwgExporter-v1.0.0.zip",
    "rvt": "RvtExporter-v0.5.0.zip",
    "ifc": "IfcExporter-v1.0.0.zip",
    "dgn": "DgnExporter-v1.0.0.zip",
}

_CONVERTER_CACHE_DIR = Path.home() / ".openestimator" / "cache" / "converters"
_CONVERTER_INSTALL_DIR = Path.home() / ".openestimator" / "converters"

_META_BY_ID: dict[str, dict[str, Any]] = {m["id"]: m for m in _CONVERTER_META}


def _download_converter_from_github(converter_id: str) -> Path | None:
    """Download a converter zip from GitHub releases.

    Downloads to ``~/.openestimator/cache/converters/{filename}``.
    Returns the local path on success, ``None`` on failure.
    """
    import urllib.request

    zip_name = _GITHUB_CONVERTER_FILES.get(converter_id)
    if not zip_name:
        return None

    url = f"{_GITHUB_CONVERTER_BASE_URL}/{zip_name}"
    _CONVERTER_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    local_path = _CONVERTER_CACHE_DIR / zip_name

    # Return cached zip if it exists and is non-trivial
    if local_path.exists() and local_path.stat().st_size > 1000:
        logger.info("Using cached converter zip: %s", local_path)
        return local_path

    logger.info("Downloading converter %s from GitHub: %s", converter_id, url)
    try:
        urllib.request.urlretrieve(url, str(local_path))
        if local_path.exists() and local_path.stat().st_size > 1000:
            logger.info(
                "Downloaded converter %s: %d bytes",
                converter_id,
                local_path.stat().st_size,
            )
            return local_path
        else:
            logger.warning("Downloaded file too small or missing: %s", local_path)
            local_path.unlink(missing_ok=True)
            return None
    except Exception as exc:
        logger.warning("Failed to download converter %s: %s", converter_id, exc)
        local_path.unlink(missing_ok=True)
        return None


def _install_converter_from_zip(zip_path: Path, converter_id: str) -> Path:
    """Extract a converter zip into the install directory.

    Returns the path to the installed executable.
    Raises ``ValueError`` if the expected exe is not found after extraction.
    """
    meta = _META_BY_ID.get(converter_id)
    if not meta:
        raise ValueError(f"Unknown converter: {converter_id}")

    exe_name: str = meta["exe"]
    _CONVERTER_INSTALL_DIR.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(_CONVERTER_INSTALL_DIR)

    # The exe may be at root or nested one level deep
    exe_path = _CONVERTER_INSTALL_DIR / exe_name
    if exe_path.exists():
        return exe_path

    # Check one level deep
    for child in _CONVERTER_INSTALL_DIR.iterdir():
        if child.is_dir():
            nested = child / exe_name
            if nested.exists():
                return nested

    raise ValueError(
        f"Converter executable '{exe_name}' not found after extraction "
        f"in {_CONVERTER_INSTALL_DIR}"
    )


@router.post(
    "/converters/{converter_id}/install",
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def install_converter(
    converter_id: str,
    _user_id: CurrentUserId,
) -> dict[str, Any]:
    """Download and install a DDC CAD/BIM converter from GitHub.

    Downloads the converter zip from the DDC Community Toolkit releases,
    extracts it to ``~/.openestimator/converters/``, and verifies the
    executable is present.
    """
    from app.modules.boq.cad_import import find_converter

    meta = _META_BY_ID.get(converter_id)
    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown converter: '{converter_id}'. "
            f"Available: {list(_META_BY_ID.keys())}",
        )

    # Already installed?
    existing = find_converter(converter_id)
    if existing:
        return {
            "converter_id": converter_id,
            "installed": True,
            "path": str(existing),
            "already_installed": True,
            "message": f"{meta['name']} is already installed at {existing}",
        }

    # Download from GitHub
    zip_path = _download_converter_from_github(converter_id)

    exe_name: str = meta["exe"]
    exe_path: Path | None = None

    if zip_path:
        # Extract from downloaded zip
        try:
            exe_path = _install_converter_from_zip(zip_path, converter_id)
        except (zipfile.BadZipFile, ValueError) as exc:
            logger.warning("Failed to extract converter %s: %s", converter_id, exc)

    if exe_path is None:
        raise HTTPException(
            status_code=502,
            detail=(
                f"Failed to download {meta['name']}. "
                f"The DDC Community Toolkit release is not yet available at "
                f"{_GITHUB_CONVERTER_BASE_URL}. "
                f"CAD/BIM converters are planned for a future release."
            ),
        )

    size_bytes = exe_path.stat().st_size if exe_path.exists() else 0

    return {
        "converter_id": converter_id,
        "installed": True,
        "path": str(exe_path),
        "already_installed": False,
        "size_bytes": size_bytes,
        "message": f"{meta['name']} installed successfully at {exe_path}",
    }


@router.post(
    "/converters/{converter_id}/uninstall",
    dependencies=[Depends(RequirePermission("takeoff.delete"))],
)
async def uninstall_converter(
    converter_id: str,
    _user_id: CurrentUserId,
) -> dict[str, Any]:
    """Remove an installed DDC CAD/BIM converter."""
    meta = _META_BY_ID.get(converter_id)
    if not meta:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown converter: '{converter_id}'",
        )

    exe_name: str = meta["exe"]
    removed = False

    # Build list of candidate paths to check
    candidates = [_CONVERTER_INSTALL_DIR / exe_name]
    if _CONVERTER_INSTALL_DIR.exists():
        for child in _CONVERTER_INSTALL_DIR.iterdir():
            if child.is_dir():
                candidates.append(child / exe_name)

    # Remove from install dir
    for candidate in candidates:
        if candidate.exists():
            candidate.unlink()
            removed = True
            logger.info("Removed converter executable: %s", candidate)

    # Also clear cached zip
    zip_name = _GITHUB_CONVERTER_FILES.get(converter_id, "")
    cached_zip = _CONVERTER_CACHE_DIR / zip_name
    if cached_zip.exists():
        cached_zip.unlink()
        logger.info("Removed cached zip: %s", cached_zip)

    return {
        "converter_id": converter_id,
        "removed": removed,
        "message": f"{meta['name']} uninstalled" if removed else f"{meta['name']} was not installed",
    }


# ── CAD quantity extraction (no AI) ──────────────────────────────────────

MAX_CAD_SIZE = 100 * 1024 * 1024  # 100 MB

_SUPPORTED_CAD_EXTS = {"rvt", "ifc", "dwg", "dgn", "rfa", "dxf"}


@router.post(
    "/cad-extract",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_extract(
    file: UploadFile = File(..., description="CAD/BIM file (.rvt, .ifc, .dwg, .dgn)"),
) -> dict[str, Any]:
    """Extract grouped quantity tables from a CAD/BIM file.

    Converts the file using a DDC Community converter, parses the resulting
    Excel output, and groups elements deterministically by category and type.
    **No AI key required** — this is pure file conversion + grouping.

    Returns quantity tables with per-category and grand totals for:
    count, volume (m3), area (m2), and length (m).
    """
    import tempfile
    import time

    from app.modules.boq.cad_import import (
        convert_cad_to_excel,
        find_converter,
        group_cad_elements,
        parse_cad_excel,
    )

    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in _SUPPORTED_CAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: .{ext}. "
                f"Accepted: {', '.join(f'.{e}' for e in sorted(_SUPPORTED_CAD_EXTS))}"
            ),
        )

    converter = find_converter(ext)
    if not converter:
        raise HTTPException(
            status_code=400,
            detail=(
                f"DDC converter for .{ext} files is not installed. "
                f"Install it from the Quantities page (/quantities) or download "
                f"from https://github.com/datadrivenconstruction/ddc-community-toolkit/releases"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_CAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Max: {MAX_CAD_SIZE // 1024 // 1024} MB.",
        )

    start_time = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / filename
        input_path.write_bytes(content)

        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        excel_path = await convert_cad_to_excel(input_path, output_dir, ext)
        if not excel_path:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"CAD conversion failed for .{ext} file. "
                    "Ensure the converter is properly installed and the file is valid."
                ),
            )

        elements = parse_cad_excel(excel_path)

    if not elements:
        raise HTTPException(
            status_code=422,
            detail="Converter produced no elements. The file may be empty or unsupported.",
        )

    grouped = group_cad_elements(elements)
    duration_ms = int((time.monotonic() - start_time) * 1000)

    return {
        "filename": filename,
        "format": ext,
        "total_elements": grouped["total_elements"],
        "duration_ms": duration_ms,
        "groups": grouped["groups"],
        "grand_totals": grouped["grand_totals"],
    }


# ── CAD interactive grouping (two-step flow) ──────────────────────────────

# In-memory cache for CAD extraction sessions (5 min TTL)
_cad_sessions: dict[str, dict] = {}
_CAD_SESSION_TTL = 300  # 5 minutes


def _cleanup_sessions() -> None:
    """Remove expired CAD extraction sessions from the in-memory cache."""
    now = _time.time()
    expired = [k for k, v in _cad_sessions.items() if now - v["created"] > _CAD_SESSION_TTL]
    for k in expired:
        del _cad_sessions[k]


class CadGroupRequest(BaseModel):
    """Request body for the ``POST /cad-group`` endpoint."""

    session_id: str = Field(..., description="Session ID returned by /cad-columns")
    group_by: list[str] = Field(..., min_length=1, description="Columns to group by")
    sum_columns: list[str] = Field(default_factory=list, description="Numeric columns to sum")


@router.post(
    "/cad-columns",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_columns(
    file: UploadFile = File(..., description="CAD/BIM file (.rvt, .ifc, .dwg, .dgn)"),
) -> dict[str, Any]:
    """Upload a CAD file and analyze its columns for interactive grouping.

    Step 1 of the two-step interactive QTO flow:
    1. Upload file -> get available columns + session_id
    2. POST /cad-group with session_id + chosen columns -> get grouped results

    Returns column classification (grouping / quantity / text), suggested
    defaults, a preview of the first 10 elements, and a ``session_id`` for
    the follow-up grouping request.
    """
    import tempfile
    import time

    from app.modules.boq.cad_import import (
        convert_cad_to_excel,
        find_converter,
        get_available_columns,
        parse_cad_excel,
    )

    filename = file.filename or "file"
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

    if ext not in _SUPPORTED_CAD_EXTS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported file type: .{ext}. "
                f"Accepted: {', '.join(f'.{e}' for e in sorted(_SUPPORTED_CAD_EXTS))}"
            ),
        )

    converter = find_converter(ext)
    if not converter:
        raise HTTPException(
            status_code=400,
            detail=(
                f"DDC converter for .{ext} files is not installed. "
                f"Install it from the Quantities page (/quantities) or download "
                f"from https://github.com/datadrivenconstruction/ddc-community-toolkit/releases"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")
    if len(content) > MAX_CAD_SIZE:
        raise HTTPException(
            status_code=400,
            detail=(
                f"File too large ({len(content) / 1024 / 1024:.1f} MB). "
                f"Max: {MAX_CAD_SIZE // 1024 // 1024} MB."
            ),
        )

    start_time = time.monotonic()

    with tempfile.TemporaryDirectory() as tmpdir:
        input_path = Path(tmpdir) / filename
        input_path.write_bytes(content)

        output_dir = Path(tmpdir) / "output"
        output_dir.mkdir()

        excel_path = await convert_cad_to_excel(input_path, output_dir, ext)
        if not excel_path:
            raise HTTPException(
                status_code=502,
                detail=(
                    f"CAD conversion failed for .{ext} file. "
                    "Ensure the converter is properly installed and the file is valid."
                ),
            )

        elements = parse_cad_excel(excel_path)

    if not elements:
        raise HTTPException(
            status_code=422,
            detail="Converter produced no elements. The file may be empty or unsupported.",
        )

    # Filter out empty/system elements (Phases, Patterns, Views, etc.)
    _SKIP_CATEGORIES = {
        "none", "", "ost_phases", "ost_materials", "ost_viewports",
        "ost_colorfilllegends", "ost_views", "ost_grids", "ost_levels",
        "ost_sheets", "ost_titleblocks",
    }
    real_elements = [
        el for el in elements
        if str(el.get("category", "")).strip().lower() not in _SKIP_CATEGORIES
    ]
    # If filtering removed everything, keep originals
    if not real_elements:
        real_elements = elements

    columns = get_available_columns(real_elements, file_format=ext)
    duration_ms = int((time.monotonic() - start_time) * 1000)

    # Cleanup expired sessions, then store new one
    _cleanup_sessions()
    session_id = str(_uuid.uuid4())
    _cad_sessions[session_id] = {
        "elements": real_elements,
        "filename": filename,
        "format": ext,
        "created": _time.time(),
    }

    # Preview: pick elements that have actual quantity data (volume > 0 or area > 0)
    def _has_quantity(el: dict) -> bool:
        for key in ("volume", "area", "length", "gross volume", "gross area"):
            val = el.get(key)
            if val is not None:
                try:
                    if float(val) > 0:
                        return True
                except (ValueError, TypeError):
                    pass
        return False

    preview_candidates = [el for el in real_elements if _has_quantity(el)][:10]
    if not preview_candidates:
        # Fallback: elements with type name
        preview_candidates = [
            el for el in real_elements if el.get("type name")
        ][:10]
    if not preview_candidates:
        preview_candidates = real_elements[:10]

    return {
        "session_id": session_id,
        "filename": filename,
        "format": ext,
        "total_elements": len(real_elements),
        "duration_ms": duration_ms,
        "columns": {
            "grouping": columns.get("grouping", []),
            "quantity": columns.get("quantity", []),
            "text": columns.get("text", []),
        },
        "suggested_grouping": columns.get("suggested_grouping", []),
        "suggested_quantities": columns.get("suggested_quantities", []),
        "presets": columns.get("presets", {}),
        "unit_labels": columns.get("unit_labels", {}),
        "preview": preview_candidates,
    }


@router.post(
    "/cad-group",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_group(
    body: CadGroupRequest,
) -> dict[str, Any]:
    """Group previously uploaded CAD elements by user-selected columns.

    Step 2 of the two-step interactive QTO flow. Requires a valid
    ``session_id`` from a prior ``POST /cad-columns`` call.

    The session is kept alive in memory for 5 minutes. If it expires,
    the user must re-upload the file.
    """
    from app.modules.boq.cad_import import group_cad_elements_dynamic

    _cleanup_sessions()

    session = _cad_sessions.get(body.session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = session["elements"]

    # Validate that requested columns actually exist in the data
    all_columns: set[str] = set()
    for el in elements:
        all_columns.update(el.keys())

    missing_group = [c for c in body.group_by if c not in all_columns]
    if missing_group:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown grouping column(s): {missing_group}. Available: {sorted(all_columns)}",
        )

    # "count" is a virtual column (computed as number of elements per group)
    missing_sum = [c for c in body.sum_columns if c not in all_columns and c != "count"]
    if missing_sum:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown sum column(s): {missing_sum}. Available: {sorted(all_columns)}",
        )

    grouped = group_cad_elements_dynamic(elements, body.group_by, body.sum_columns)

    return {
        "filename": session["filename"],
        "format": session["format"],
        **grouped,
    }


MAX_PDF_SIZE = 50 * 1024 * 1024  # 50 MB


def _get_service(session: SessionDep) -> TakeoffService:
    return TakeoffService(session)


# ── Upload ────────────────────────────────────────────────────────────────


@router.post(
    "/documents/upload",
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def upload_document(
    user_id: CurrentUserId,
    file: UploadFile = File(..., description="PDF file (.pdf)"),
    project_id: str | None = Query(default=None),
    service: TakeoffService = Depends(_get_service),
) -> dict[str, Any]:
    """Upload a PDF document for quantity takeoff."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext != "pdf":
        raise HTTPException(
            status_code=400,
            detail=f"Only PDF files are supported, got .{ext}",
        )

    content = await file.read()

    if len(content) > MAX_PDF_SIZE:
        raise HTTPException(
            status_code=400,
            detail=f"File too large ({len(content) / 1024 / 1024:.1f} MB). Maximum is {MAX_PDF_SIZE / 1024 / 1024:.0f} MB.",
        )

    doc = await service.upload_document(
        filename=file.filename,
        content=content,
        size_bytes=len(content),
        owner_id=user_id,
        project_id=project_id,
    )

    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "pages": doc.pages,
        "size_bytes": doc.size_bytes,
    }


# ── List documents ────────────────────────────────────────────────────────


@router.get(
    "/documents/",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def list_documents(
    user_id: CurrentUserId,
    project_id: str | None = Query(default=None),
    service: TakeoffService = Depends(_get_service),
) -> list[dict[str, Any]]:
    """List uploaded takeoff documents."""
    docs = await service.list_documents(user_id, project_id=project_id)
    return [
        {
            "id": str(d.id),
            "filename": d.filename,
            "pages": d.pages,
            "size_bytes": d.size_bytes,
            "status": d.status,
            "uploaded_at": d.created_at.isoformat() if d.created_at else None,
        }
        for d in docs
    ]


# ── Get single document ──────────────────────────────────────────────────


@router.get(
    "/documents/{doc_id}",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def get_document(
    doc_id: str,
    service: TakeoffService = Depends(_get_service),
) -> dict[str, Any]:
    """Get a single takeoff document with its data."""
    doc = await service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return {
        "id": str(doc.id),
        "filename": doc.filename,
        "pages": doc.pages,
        "size_bytes": doc.size_bytes,
        "status": doc.status,
        "extracted_text": doc.extracted_text[:2000] if doc.extracted_text else "",
        "page_data": doc.page_data,
        "analysis": doc.analysis,
        "uploaded_at": doc.created_at.isoformat() if doc.created_at else None,
    }


# ── Extract tables ────────────────────────────────────────────────────────


@router.post(
    "/documents/{doc_id}/extract-tables",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def extract_tables(
    doc_id: str,
    service: TakeoffService = Depends(_get_service),
) -> dict[str, Any]:
    """Extract tabular data from an uploaded document."""
    doc = await service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return await service.extract_tables(doc_id)


# ── Download stored PDF ─────────────────────────────────────────────────


@router.get(
    "/documents/{doc_id}/download",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def download_document(
    doc_id: str,
    service: TakeoffService = Depends(_get_service),
) -> FileResponse:
    """Download the stored PDF file for a takeoff document."""
    doc = await service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    if not doc.file_path:
        raise HTTPException(status_code=404, detail="PDF file not available for this document")

    file_path = Path(doc.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="PDF file not found on disk")

    return FileResponse(
        path=str(file_path),
        media_type="application/pdf",
        filename=doc.filename,
    )


# ── AI Analysis ──────────────────────────────────────────────────────────


@router.post(
    "/documents/{doc_id}/analyze",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def analyze_document(
    doc_id: str,
    user_id: CurrentUserId,
    session: SessionDep,
    service: TakeoffService = Depends(_get_service),
) -> dict[str, Any]:
    """Analyze a takeoff document's extracted text using AI.

    Sends the document's previously extracted text to the configured AI provider
    and returns structured BOQ items parsed from the AI response.
    """
    import time
    import uuid as _uuid

    from app.modules.ai.ai_client import call_ai, extract_json, resolve_provider_and_key
    from app.modules.ai.prompts import SMART_IMPORT_PROMPT, SYSTEM_PROMPT
    from app.modules.ai.repository import AISettingsRepository

    # 1. Get the document
    doc = await service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    # 2. Check extracted text
    extracted_text = doc.extracted_text or ""
    if not extracted_text.strip():
        raise HTTPException(
            status_code=400,
            detail="Document has no extracted text. Please re-upload the PDF.",
        )

    # 3. Get user AI settings and resolve provider
    settings_repo = AISettingsRepository(session)
    settings = await settings_repo.get_by_user_id(_uuid.UUID(user_id))

    try:
        provider, api_key = resolve_provider_and_key(settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # 4. Build prompt
    filename = doc.filename or "document.pdf"
    # Limit text to prevent overly large prompts
    text_for_prompt = extracted_text[:15000]
    prompt = SMART_IMPORT_PROMPT.format(filename=filename, text=text_for_prompt)

    # 5. Call AI
    start_time = time.monotonic()
    try:
        raw_response, tokens = await call_ai(
            provider=provider,
            api_key=api_key,
            system=SYSTEM_PROMPT,
            prompt=prompt,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("AI analysis failed for document %s: %s", doc_id, exc)
        raise HTTPException(
            status_code=502,
            detail=f"AI analysis failed: {exc}",
        ) from exc

    duration_ms = int((time.monotonic() - start_time) * 1000)

    # 6. Parse AI response
    parsed = extract_json(raw_response)
    if not isinstance(parsed, list):
        parsed = []

    # 7. Convert to the AnalysisResult format expected by frontend
    elements: list[dict[str, Any]] = []
    categories: dict[str, dict[str, Any]] = {}

    for idx, item in enumerate(parsed):
        if not isinstance(item, dict):
            continue

        description = str(item.get("description", "")).strip()
        if len(description) < 3:
            continue

        try:
            quantity = float(item.get("quantity", 0))
        except (ValueError, TypeError):
            quantity = 0.0

        unit = str(item.get("unit", "pcs")).strip() or "pcs"
        category = str(item.get("category", "General")).strip() or "General"

        try:
            unit_rate = float(item.get("unit_rate", 0))
        except (ValueError, TypeError):
            unit_rate = 0.0

        element = {
            "id": f"ai_{idx + 1}",
            "category": category,
            "description": description,
            "quantity": round(quantity, 2),
            "unit": unit,
            "confidence": 0.8,
        }
        elements.append(element)

        # Build category summary
        if category not in categories:
            categories[category] = {"count": 0, "total_quantity": 0, "unit": unit}
        categories[category]["count"] += 1
        categories[category]["total_quantity"] += quantity

    logger.info(
        "AI analysis completed: doc=%s, items=%d, tokens=%d, duration=%dms",
        doc_id,
        len(elements),
        tokens,
        duration_ms,
    )

    return {
        "elements": elements,
        "summary": {
            "total_elements": len(elements),
            "categories": categories,
        },
    }


# ── Delete ────────────────────────────────────────────────────────────────


@router.delete(
    "/documents/{doc_id}",
    dependencies=[Depends(RequirePermission("takeoff.delete"))],
    status_code=status.HTTP_204_NO_CONTENT,
)
async def delete_document(
    doc_id: str,
    service: TakeoffService = Depends(_get_service),
) -> None:
    """Delete an uploaded takeoff document."""
    doc = await service.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    await service.delete_document(doc_id)
