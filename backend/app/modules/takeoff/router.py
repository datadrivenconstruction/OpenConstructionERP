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

    POST   /measurements                       — create measurement
    GET    /measurements                        — list measurements (filtered)
    GET    /measurements/summary                — stats by group/type
    GET    /measurements/export                 — export measurements as CSV/JSON
    POST   /measurements/bulk                   — bulk create measurements
    GET    /measurements/{id}                   — get single measurement
    PATCH  /measurements/{id}                   — update measurement
    DELETE /measurements/{id}                   — delete measurement
    POST   /measurements/{id}/link-to-boq       — link measurement to BOQ position

    POST   /cad-group/create-boq               — create BOQ from grouped CAD QTO
    GET    /cad-group/export                    — export grouped QTO as Excel

    POST   /cad-data/describe                   — DataFrame-like describe of CAD session
    POST   /cad-data/value-counts               — value counts for a single column
    GET    /cad-data/elements                    — paginated element table with sort/filter
    POST   /cad-data/aggregate                   — group-by aggregation on CAD elements
"""

import logging
import shutil
import time as _time
import uuid as _uuid
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from statistics import mean as _mean
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.takeoff.models import CadExtractionSession
from app.modules.takeoff.schemas import (
    LinkToBoqRequest,
    TakeoffDocumentResponse,
    TakeoffMeasurementBulkCreate,
    TakeoffMeasurementCreate,
    TakeoffMeasurementResponse,
    TakeoffMeasurementSummary,
    TakeoffMeasurementUpdate,
)
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

# In-memory cache kept as fast fallback; primary storage is the database.
_cad_sessions: dict[str, dict] = {}
_CAD_SESSION_TTL = 86400  # 24 hours (was 5 minutes)


def _cleanup_memory_sessions() -> None:
    """Remove expired CAD extraction sessions from the in-memory cache."""
    now = _time.time()
    expired = [k for k, v in _cad_sessions.items() if now - v["created"] > _CAD_SESSION_TTL]
    for k in expired:
        del _cad_sessions[k]


async def _cleanup_db_sessions(session: Any) -> None:
    """Remove expired CAD extraction sessions from the database (skip permanent)."""
    now = datetime.now(timezone.utc)
    await session.execute(
        delete(CadExtractionSession).where(
            CadExtractionSession.expires_at < now,
            CadExtractionSession.is_permanent == False,  # noqa: E712
        )
    )


async def _save_session_to_db(
    session: Any,
    session_id: str,
    elements: list[dict],
    filename: str,
    file_format: str,
    columns_metadata: dict | None = None,
    user_id: str = "",
    extraction_time: float = 0,
) -> None:
    """Persist a CAD extraction session to the database."""
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=_CAD_SESSION_TTL)
    db_session = CadExtractionSession(
        session_id=session_id,
        user_id=user_id,
        filename=filename,
        file_format=file_format,
        element_count=len(elements),
        extraction_time=extraction_time,
        elements_data=elements,
        columns_metadata=columns_metadata or {},
        expires_at=expires_at,
        created_by=user_id,
    )
    session.add(db_session)
    await session.flush()


async def _get_session_from_db(session: Any, session_id: str) -> dict | None:
    """Retrieve a CAD extraction session from the database.

    Returns a dict matching the old in-memory format, or None if not found / expired.
    """
    now = datetime.now(timezone.utc)
    result = await session.execute(
        select(CadExtractionSession).where(
            CadExtractionSession.session_id == session_id,
            CadExtractionSession.expires_at > now,
        )
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    return {
        "elements": row.elements_data or [],
        "filename": row.filename,
        "format": row.file_format,
        "created": row.created_at.timestamp() if row.created_at else _time.time(),
        "columns_metadata": row.columns_metadata or {},
    }


async def _get_cad_session(session: Any, session_id: str) -> dict | None:
    """Look up a CAD session from memory first, then fall back to database."""
    # Fast path: in-memory
    mem = _cad_sessions.get(session_id)
    if mem is not None:
        return mem
    # Slow path: database
    return await _get_session_from_db(session, session_id)


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
    session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
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
    _cleanup_memory_sessions()
    session_id = str(_uuid.uuid4())
    _cad_sessions[session_id] = {
        "elements": real_elements,
        "filename": filename,
        "format": ext,
        "created": _time.time(),
        "columns_metadata": columns,
    }

    # Persist to database for durability
    if session is not None:
        await _cleanup_db_sessions(session)
        await _save_session_to_db(
            session=session,
            session_id=session_id,
            elements=real_elements,
            filename=filename,
            file_format=ext,
            columns_metadata=columns,
            user_id=user_id or "",
            extraction_time=duration_ms / 1000.0,
        )

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
        "confidence": columns.get("confidence", {}),
        "preview": preview_candidates,
    }


@router.post(
    "/cad-group",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_group(
    body: CadGroupRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Group previously uploaded CAD elements by user-selected columns.

    Step 2 of the two-step interactive QTO flow. Requires a valid
    ``session_id`` from a prior ``POST /cad-columns`` call.

    Sessions are stored in the database and expire after 24 hours.
    If expired, the user must re-upload the file.
    """
    from app.modules.boq.cad_import import group_cad_elements_dynamic

    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = cad_session["elements"]

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
        "filename": cad_session["filename"],
        "format": cad_session["format"],
        **grouped,
    }


# ── Element detail view for a specific group ──────────────────────────────


class CadGroupElementsRequest(BaseModel):
    """Request body for the ``POST /cad-group/elements`` endpoint."""

    session_id: str = Field(..., description="Session ID returned by /cad-columns")
    group_key: dict[str, str] = Field(
        ...,
        description='Key-value pairs identifying the group (e.g. {"category": "Walls", "type name": "Exterior Wall"})',
    )


@router.post(
    "/cad-group/elements",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def get_group_elements(
    body: CadGroupElementsRequest,
) -> dict[str, Any]:
    """Get individual elements for a specific group.

    Returns all raw elements matching the provided ``group_key`` filter,
    allowing users to inspect what makes up each grouped row.
    """
    _cleanup_memory_sessions()

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

    # Filter elements matching all key-value pairs in group_key
    matching: list[dict] = []
    for el in elements:
        match = True
        for col, expected in body.group_key.items():
            raw = el.get(col)
            val = str(raw).strip() if raw is not None else ""
            normalized = val if val and val != "None" else "(empty)"
            if normalized != expected:
                match = False
                break
        if match:
            matching.append(el)

    # Discover all column names across matching elements
    all_cols: list[str] = []
    seen: set[str] = set()
    for el in matching:
        for k in el:
            if k not in seen:
                seen.add(k)
                all_cols.append(k)

    # Compute totals for numeric columns
    totals: dict[str, float] = {}
    for col in all_cols:
        numeric_sum = 0.0
        is_numeric = False
        for el in matching:
            val = el.get(col)
            if val is not None:
                try:
                    numeric_sum += float(val)
                    is_numeric = True
                except (ValueError, TypeError):
                    pass
        if is_numeric:
            totals[col] = round(numeric_sum, 4)

    return {
        "group_key": body.group_key,
        "total_elements": len(matching),
        "columns": all_cols,
        "elements": matching[:500],  # Limit to 500 elements for performance
        "totals": totals,
        "truncated": len(matching) > 500,
    }


# ── Create BOQ from CAD QTO ───────────────────────────────────────────────


class CreateBOQFromCadRequest(BaseModel):
    """Request body for creating a BOQ from grouped CAD QTO data."""

    session_id: str = Field(..., description="Session ID from /cad-columns")
    project_id: str = Field(..., description="Project UUID to create BOQ in")
    boq_name: str = Field(default="CAD Import", description="Name for the new BOQ")
    group_by: list[str] = Field(default_factory=list, description="Columns used for grouping")
    sum_columns: list[str] = Field(default_factory=list, description="Columns used for summing")


@router.post(
    "/cad-group/create-boq",
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def create_boq_from_cad_qto(
    body: CreateBOQFromCadRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
    user_id: CurrentUserId = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Create a BOQ directly from grouped CAD QTO data.

    Retrieves the cached CAD session, runs grouping using the provided
    (or stored) column selections, creates a new BOQ in the specified
    project, and adds positions for each group.
    """
    import uuid

    from app.modules.boq.cad_import import group_cad_elements_dynamic
    from app.modules.boq.models import BOQ, Position

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "CAD session not found or expired. "
                "Please re-upload the CAD file."
            ),
        )

    elements: list[dict] = cad_session["elements"]

    # Use provided grouping or fall back to stored metadata
    group_by = body.group_by
    sum_columns = body.sum_columns
    if not group_by:
        stored = cad_session.get("columns_metadata", {})
        group_by = stored.get("suggested_grouping", [])
    if not sum_columns:
        stored = cad_session.get("columns_metadata", {})
        sum_columns = stored.get("suggested_quantities", [])

    if not group_by:
        raise HTTPException(
            status_code=400,
            detail="No grouping columns specified and no defaults available.",
        )

    grouped = group_cad_elements_dynamic(elements, group_by, sum_columns)
    groups = grouped.get("groups", [])

    # Determine unit labels from stored metadata
    stored_meta = cad_session.get("columns_metadata", {})
    unit_labels: dict[str, str] = stored_meta.get("unit_labels", {})

    # Create BOQ
    project_uuid = uuid.UUID(body.project_id)
    boq = BOQ(
        project_id=project_uuid,
        name=body.boq_name,
        description=f"Auto-generated from CAD file: {cad_session['filename']}",
        status="draft",
        metadata_={"source": "cad_qto", "cad_filename": cad_session["filename"]},
    )
    db_session.add(boq)
    await db_session.flush()

    # Create positions from groups
    position_count = 0
    for idx, group in enumerate(groups):
        # Skip empty groups
        sums = group.get("sums", {})
        count = group.get("count", 0)
        if count == 0 and all(v == 0 for v in sums.values()):
            continue

        # Build description from group key parts
        key_parts = group.get("key_parts", {})
        parts = []
        for col, val in key_parts.items():
            cleaned = str(val or "").strip()
            if col == "category":
                cleaned = cleaned.replace("OST_", "")
            if cleaned:
                parts.append(cleaned)
        description = " — ".join(parts) if parts else group.get("key", f"Group {idx + 1}")

        # Determine best unit and quantity (volume > area > length > count)
        unit = "pcs"
        quantity = float(count)
        for col_name in ["volume", "area", "length"]:
            if col_name in sums and sums[col_name] > 0:
                unit = unit_labels.get(col_name, col_name)
                quantity = round(sums[col_name], 4)
                break

        ordinal = f"{idx + 1:03d}"

        position = Position(
            boq_id=boq.id,
            ordinal=ordinal,
            description=description,
            unit=unit,
            quantity=str(quantity),
            unit_rate="0",
            total="0",
            source="cad_import",
            sort_order=idx,
            metadata_={
                "cad_source": "cad_qto",
                "cad_count": count,
                "cad_sums": sums,
            },
        )
        db_session.add(position)
        position_count += 1

    await db_session.flush()

    logger.info(
        "Created BOQ '%s' with %d positions from CAD QTO session %s",
        body.boq_name,
        position_count,
        body.session_id,
    )

    return {
        "boq_id": str(boq.id),
        "project_id": body.project_id,
        "position_count": position_count,
        "boq_name": body.boq_name,
    }


# ── Export grouped CAD QTO as Excel ───────────────────────────────────────


@router.get(
    "/cad-group/export",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def export_cad_group(
    session_id: str = Query(..., description="Session ID from /cad-columns"),
    group_by: str = Query(default="", description="Comma-separated grouping columns"),
    sum_columns: str = Query(default="", description="Comma-separated sum columns"),
    format: str = Query(default="xlsx", pattern="^(xlsx)$"),
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> StreamingResponse:
    """Export grouped QTO results as an Excel spreadsheet.

    Retrieves the CAD session, runs grouping, and returns an xlsx file
    with headers, data rows, and a bold grand-total row.
    """
    import io

    from app.modules.boq.cad_import import group_cad_elements_dynamic

    cad_session = await _get_cad_session(db_session, session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "CAD session not found or expired. "
                "Please re-upload the CAD file."
            ),
        )

    elements: list[dict] = cad_session["elements"]

    # Parse column lists
    group_by_list = [c.strip() for c in group_by.split(",") if c.strip()] if group_by else []
    sum_columns_list = [c.strip() for c in sum_columns.split(",") if c.strip()] if sum_columns else []

    # Fall back to stored metadata
    if not group_by_list:
        stored = cad_session.get("columns_metadata", {})
        group_by_list = stored.get("suggested_grouping", [])
    if not sum_columns_list:
        stored = cad_session.get("columns_metadata", {})
        sum_columns_list = stored.get("suggested_quantities", [])

    if not group_by_list:
        raise HTTPException(
            status_code=400,
            detail="No grouping columns specified.",
        )

    grouped = group_cad_elements_dynamic(elements, group_by_list, sum_columns_list)
    groups = grouped.get("groups", [])
    grand_totals = grouped.get("grand_totals", {})

    # Build Excel workbook
    try:
        import openpyxl
        from openpyxl.styles import Alignment, Font
    except ImportError:
        raise HTTPException(
            status_code=500,
            detail="openpyxl is not installed. Cannot generate Excel export.",
        )

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QTO Export"

    # Determine column order
    all_sum_cols = [c for c in sum_columns_list if c != "count"]
    header = list(group_by_list) + all_sum_cols + ["Count"]

    # Write header
    bold_font = Font(bold=True)
    for col_idx, col_name in enumerate(header, 1):
        cell = ws.cell(row=1, column=col_idx, value=col_name.replace("_", " ").title())
        cell.font = bold_font

    # Write data rows
    for row_idx, group in enumerate(groups, 2):
        key_parts = group.get("key_parts", {})
        sums = group.get("sums", {})
        count = group.get("count", 0)

        col_idx = 1
        for gc in group_by_list:
            val = str(key_parts.get(gc, "")).replace("OST_", "")
            ws.cell(row=row_idx, column=col_idx, value=val)
            col_idx += 1
        for sc in all_sum_cols:
            ws.cell(row=row_idx, column=col_idx, value=round(sums.get(sc, 0), 4))
            col_idx += 1
        ws.cell(row=row_idx, column=col_idx, value=count)

    # Grand total row
    total_row = len(groups) + 2
    col_idx = 1
    total_cell = ws.cell(row=total_row, column=col_idx, value="TOTAL")
    total_cell.font = bold_font
    col_idx = len(group_by_list) + 1
    for sc in all_sum_cols:
        cell = ws.cell(row=total_row, column=col_idx, value=round(grand_totals.get(sc, 0), 4))
        cell.font = bold_font
        col_idx += 1
    total_count = grand_totals.get("count", sum(g.get("count", 0) for g in groups))
    cell = ws.cell(row=total_row, column=col_idx, value=total_count)
    cell.font = bold_font

    # Auto-fit column widths
    for col_cells in ws.columns:
        max_len = 0
        col_letter = col_cells[0].column_letter  # type: ignore[union-attr]
        for cell in col_cells:
            try:
                cell_len = len(str(cell.value or ""))
                if cell_len > max_len:
                    max_len = cell_len
            except Exception:
                pass
        ws.column_dimensions[col_letter].width = min(max_len + 4, 50)

    # Write to buffer
    output = io.BytesIO()
    wb.save(output)
    output.seek(0)

    filename_base = cad_session.get("filename", "export").rsplit(".", 1)[0]
    download_name = f"{filename_base}_qto.xlsx"

    return StreamingResponse(
        output,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{download_name}"'},
    )


# ── CAD Data Explorer ────────────────────────────────────────────────────


class CadDataDescribeRequest(BaseModel):
    """Request body for the ``POST /cad-data/describe`` endpoint."""

    session_id: str = Field(..., description="Session ID returned by /cad-columns")


class CadDataValueCountsRequest(BaseModel):
    """Request body for the ``POST /cad-data/value-counts`` endpoint."""

    session_id: str = Field(..., description="Session ID returned by /cad-columns")
    column: str = Field(..., description="Column name to count values for")
    limit: int = Field(default=50, ge=1, le=500, description="Max number of distinct values")


class CadDataAggregateRequest(BaseModel):
    """Request body for the ``POST /cad-data/aggregate`` endpoint."""

    session_id: str = Field(..., description="Session ID returned by /cad-columns")
    group_by: list[str] = Field(..., min_length=1, description="Columns to group by")
    aggregations: dict[str, str] = Field(
        ...,
        description=(
            "Mapping of column -> aggregation function. "
            "Supported: sum, avg, mean, min, max, count."
        ),
    )


def _is_numeric(value: Any) -> bool:
    """Return True if *value* can be converted to a float."""
    if value is None:
        return False
    try:
        float(value)
        return True
    except (ValueError, TypeError):
        return False


def _to_float(value: Any) -> float:
    """Convert *value* to float, raising on failure."""
    return float(value)


def _collect_column_names(elements: list[dict]) -> list[str]:
    """Return a stable list of all column names across *elements*."""
    seen: set[str] = set()
    columns: list[str] = []
    for el in elements:
        for k in el:
            if k not in seen:
                seen.add(k)
                columns.append(k)
    return columns


@router.post(
    "/cad-data/describe",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_data_describe(
    body: CadDataDescribeRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return a DataFrame-like describe of the CAD session data.

    For each column, reports dtype, non-null count, unique count, and
    summary statistics (min/max/mean/sum for numbers, top/top_freq for strings).
    """
    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = cad_session["elements"]
    all_columns = _collect_column_names(elements)

    columns_info: list[dict[str, Any]] = []
    for col in all_columns:
        values = [el.get(col) for el in elements]
        non_null = [v for v in values if v is not None]
        non_null_count = len(non_null)

        # Determine if column is numeric
        numeric_vals: list[float] = []
        for v in non_null:
            if _is_numeric(v):
                numeric_vals.append(_to_float(v))

        is_numeric_col = len(numeric_vals) > len(non_null) * 0.5 and numeric_vals

        unique_vals = set(str(v) for v in non_null)
        unique_count = len(unique_vals)

        col_info: dict[str, Any] = {
            "name": col,
            "dtype": "number" if is_numeric_col else "string",
            "non_null": non_null_count,
            "unique": unique_count,
        }

        if is_numeric_col:
            col_info["min"] = round(min(numeric_vals), 4)
            col_info["max"] = round(max(numeric_vals), 4)
            col_info["mean"] = round(_mean(numeric_vals), 4)
            col_info["sum"] = round(sum(numeric_vals), 4)
        else:
            # Find the most common value
            freq: dict[str, int] = {}
            for v in non_null:
                key = str(v)
                freq[key] = freq.get(key, 0) + 1
            if freq:
                top_value = max(freq, key=freq.get)  # type: ignore[arg-type]
                col_info["top"] = top_value
                col_info["top_freq"] = freq[top_value]

        columns_info.append(col_info)

    return {
        "filename": cad_session.get("filename", ""),
        "format": cad_session.get("format", ""),
        "total_elements": len(elements),
        "total_columns": len(all_columns),
        "columns": columns_info,
    }


@router.post(
    "/cad-data/value-counts",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_data_value_counts(
    body: CadDataValueCountsRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return value counts for a single column, sorted by frequency descending."""
    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = cad_session["elements"]

    # Validate column exists
    all_columns = _collect_column_names(elements)
    if body.column not in all_columns:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown column: '{body.column}'. Available: {sorted(all_columns)}",
        )

    # Count values
    freq: dict[str, int] = {}
    for el in elements:
        raw = el.get(body.column)
        key = str(raw) if raw is not None else "(null)"
        freq[key] = freq.get(key, 0) + 1

    total = len(elements)
    sorted_values = sorted(freq.items(), key=lambda kv: kv[1], reverse=True)

    values = [
        {
            "value": val,
            "count": cnt,
            "percentage": round(cnt / total * 100, 1) if total else 0,
        }
        for val, cnt in sorted_values[: body.limit]
    ]

    return {
        "column": body.column,
        "total": total,
        "values": values,
    }


@router.get(
    "/cad-data/elements",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_data_elements(
    session_id: str = Query(..., description="Session ID from /cad-columns"),
    offset: int = Query(default=0, ge=0, description="Number of rows to skip"),
    limit: int = Query(default=100, ge=1, le=1000, description="Max rows to return"),
    sort_by: str | None = Query(default=None, description="Column to sort by"),
    sort_order: str = Query(default="asc", pattern="^(asc|desc)$", description="Sort direction"),
    filter_column: str | None = Query(default=None, description="Column to filter on"),
    filter_value: str | None = Query(default=None, description="Value to match (equality)"),
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Return a paginated, sortable, filterable table of CAD elements."""
    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = cad_session["elements"]
    all_columns = _collect_column_names(elements)

    # --- Filter ---
    if filter_column and filter_value is not None:
        if filter_column not in all_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown filter column: '{filter_column}'. Available: {sorted(all_columns)}",
            )
        elements = [
            el for el in elements
            if str(el.get(filter_column, "")) == filter_value
        ]

    # --- Sort ---
    if sort_by is not None:
        if sort_by not in all_columns:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown sort column: '{sort_by}'. Available: {sorted(all_columns)}",
            )
        reverse = sort_order == "desc"

        def _sort_key(el: dict) -> tuple:
            v = el.get(sort_by)
            if v is None:
                # None sorts last regardless of direction
                return (1, "")
            if _is_numeric(v):
                return (0, _to_float(v))
            return (0, str(v).lower())

        elements = sorted(elements, key=_sort_key, reverse=reverse)

    total = len(elements)
    page = elements[offset : offset + limit]

    return {
        "total": total,
        "offset": offset,
        "limit": limit,
        "columns": all_columns,
        "rows": page,
    }


_SUPPORTED_AGG_FUNCS = {"sum", "avg", "mean", "min", "max", "count"}


@router.post(
    "/cad-data/aggregate",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_data_aggregate(
    body: CadDataAggregateRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Aggregate CAD element data by grouping columns.

    Supported aggregation functions: sum, avg (alias: mean), min, max, count.
    ``count`` ignores the column values and counts elements in each group.
    """
    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(
            status_code=404,
            detail=(
                "Session not found or expired. "
                "Please re-upload the CAD file via POST /cad-columns."
            ),
        )

    elements: list[dict] = cad_session["elements"]
    all_columns_set: set[str] = set()
    for el in elements:
        all_columns_set.update(el.keys())

    # Validate group_by columns
    missing_group = [c for c in body.group_by if c not in all_columns_set]
    if missing_group:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown grouping column(s): {missing_group}. Available: {sorted(all_columns_set)}",
        )

    # Validate aggregation specs
    for col, func in body.aggregations.items():
        func_lower = func.lower()
        if func_lower not in _SUPPORTED_AGG_FUNCS:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Unsupported aggregation function '{func}' for column '{col}'. "
                    f"Supported: {sorted(_SUPPORTED_AGG_FUNCS)}"
                ),
            )
        if func_lower != "count" and col not in all_columns_set:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown aggregation column: '{col}'. Available: {sorted(all_columns_set)}",
            )

    # --- Build groups ---
    groups_map: dict[tuple, list[dict]] = {}
    for el in elements:
        key = tuple(str(el.get(c, "")) for c in body.group_by)
        groups_map.setdefault(key, []).append(el)

    def _aggregate(vals: list[dict], col: str, func: str) -> float:
        func = func.lower()
        if func == "count":
            return len(vals)
        numeric = []
        for el in vals:
            v = el.get(col)
            if _is_numeric(v):
                numeric.append(_to_float(v))
        if not numeric:
            return 0.0
        if func == "sum":
            return round(sum(numeric), 4)
        if func in ("avg", "mean"):
            return round(_mean(numeric), 4)
        if func == "min":
            return round(min(numeric), 4)
        if func == "max":
            return round(max(numeric), 4)
        return 0.0

    result_groups: list[dict[str, Any]] = []
    for key_tuple, group_elements in groups_map.items():
        key_dict = {c: v for c, v in zip(body.group_by, key_tuple)}
        results: dict[str, float] = {}
        for col, func in body.aggregations.items():
            results[col] = _aggregate(group_elements, col, func)
        result_groups.append({"key": key_dict, "results": results, "count": len(group_elements)})

    # Sort groups by first group_by column for stable output
    result_groups.sort(key=lambda g: tuple(g["key"].get(c, "") for c in body.group_by))

    # --- Compute totals across all elements ---
    totals: dict[str, float] = {}
    for col, func in body.aggregations.items():
        totals[col] = _aggregate(elements, col, func)

    return {
        "groups": result_groups,
        "totals": totals,
        "total_count": len(elements),
    }


# ── CAD Data Explorer: Session Management (save, list, delete) ─────────────


class CadDataSaveRequest(BaseModel):
    """Save a CAD session permanently to a project."""
    session_id: str
    project_id: str
    display_name: str


@router.post(
    "/cad-data/save",
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def cad_data_save(
    body: CadDataSaveRequest,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    """Mark a CAD session as permanent and link it to a project."""
    _cleanup_memory_sessions()

    cad_session = await _get_cad_session(db_session, body.session_id)
    if not cad_session:
        raise HTTPException(status_code=404, detail="Session not found or expired.")

    # Update the database record
    from sqlalchemy import update as sa_update
    stmt = (
        sa_update(CadExtractionSession)
        .where(CadExtractionSession.session_id == body.session_id)
        .values(
            project_id=body.project_id,
            display_name=body.display_name,
            is_permanent=True,
            expires_at=datetime.now(timezone.utc) + timedelta(days=365 * 10),
        )
    )
    await db_session.execute(stmt)
    await db_session.commit()

    return {
        "status": "saved",
        "session_id": body.session_id,
        "project_id": body.project_id,
        "display_name": body.display_name,
    }


@router.get(
    "/cad-data/sessions",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def cad_data_list_sessions(
    project_id: str | None = Query(default=None),
    saved_only: bool = Query(default=False),
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> list[dict[str, Any]]:
    """List CAD sessions. By default shows all non-expired. Use saved_only=true for permanent only."""
    from sqlalchemy import select

    now = datetime.now(timezone.utc)
    stmt = select(CadExtractionSession)
    if saved_only:
        stmt = stmt.where(CadExtractionSession.is_permanent == True)  # noqa: E712
    else:
        # Show permanent + non-expired temporary
        stmt = stmt.where(
            (CadExtractionSession.is_permanent == True) |  # noqa: E712
            (CadExtractionSession.expires_at > now)
        )
    if project_id:
        stmt = stmt.where(CadExtractionSession.project_id == project_id)
    stmt = stmt.order_by(CadExtractionSession.created_at.desc())

    result = await db_session.execute(stmt)
    rows = result.scalars().all()

    return [
        {
            "session_id": row.session_id,
            "display_name": row.display_name or row.filename,
            "filename": row.filename,
            "file_format": row.file_format,
            "element_count": row.element_count,
            "extraction_time": row.extraction_time,
            "project_id": row.project_id,
            "is_permanent": bool(row.is_permanent),
            "created_at": row.created_at.isoformat() if row.created_at else None,
        }
        for row in rows
    ]


@router.delete(
    "/cad-data/sessions/{session_id}",
    dependencies=[Depends(RequirePermission("takeoff.delete"))],
    status_code=204,
)
async def cad_data_delete_session(
    session_id: str,
    db_session: SessionDep = None,  # type: ignore[assignment]
) -> None:
    """Delete a saved CAD session."""
    from sqlalchemy import delete as sa_delete

    stmt = sa_delete(CadExtractionSession).where(
        CadExtractionSession.session_id == session_id
    )
    result = await db_session.execute(stmt)
    await db_session.commit()

    if result.rowcount == 0:  # type: ignore[union-attr]
        raise HTTPException(status_code=404, detail="Session not found.")

    # Also remove from memory cache
    _cad_sessions.pop(session_id, None)


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

    file_path = Path(doc.file_path).resolve()

    # Security: ensure resolved path is within the takeoff upload directory
    allowed_base = (Path.home() / ".openestimator").resolve()
    if not str(file_path).startswith(str(allowed_base)):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists() or file_path.is_symlink():
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


# ═══════════════════════════════════════════════════════════════════════════
# Measurement endpoints
# ═══════════════════════════════════════════════════════════════════════════


def _measurement_to_response(item: object) -> TakeoffMeasurementResponse:
    """Build a TakeoffMeasurementResponse from an ORM object."""
    return TakeoffMeasurementResponse(
        id=item.id,  # type: ignore[attr-defined]
        project_id=item.project_id,  # type: ignore[attr-defined]
        document_id=item.document_id,  # type: ignore[attr-defined]
        page=item.page,  # type: ignore[attr-defined]
        type=item.type,  # type: ignore[attr-defined]
        group_name=item.group_name,  # type: ignore[attr-defined]
        group_color=item.group_color,  # type: ignore[attr-defined]
        annotation=item.annotation,  # type: ignore[attr-defined]
        points=item.points or [],  # type: ignore[attr-defined]
        measurement_value=item.measurement_value,  # type: ignore[attr-defined]
        measurement_unit=item.measurement_unit,  # type: ignore[attr-defined]
        depth=item.depth,  # type: ignore[attr-defined]
        volume=item.volume,  # type: ignore[attr-defined]
        perimeter=item.perimeter,  # type: ignore[attr-defined]
        count_value=item.count_value,  # type: ignore[attr-defined]
        scale_pixels_per_unit=item.scale_pixels_per_unit,  # type: ignore[attr-defined]
        linked_boq_position_id=item.linked_boq_position_id,  # type: ignore[attr-defined]
        metadata=getattr(item, "metadata_", {}),  # type: ignore[attr-defined]
        created_by=item.created_by,  # type: ignore[attr-defined]
        created_at=item.created_at,  # type: ignore[attr-defined]
        updated_at=item.updated_at,  # type: ignore[attr-defined]
    )


# ── Summary (must be before /{measurement_id} to avoid route collision) ──


@router.get(
    "/measurements/summary",
    response_model=TakeoffMeasurementSummary,
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def measurement_summary(
    project_id: _uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> TakeoffMeasurementSummary:
    """Aggregated measurement stats for a project."""
    data = await service.get_measurement_summary(project_id)
    return TakeoffMeasurementSummary(**data)


# ── Export ───────────────────────────────────────────────────────────────


@router.get(
    "/measurements/export",
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def export_measurements(
    project_id: _uuid.UUID = Query(...),
    format: str = Query(default="csv", pattern="^(csv|json)$"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> Any:
    """Export measurements for a project.

    Supported formats: csv, json.
    CSV returns a downloadable text response; JSON returns a list of dicts.
    """
    rows = await service.export_measurements(project_id, fmt=format)

    if format == "csv":
        import csv
        import io

        if not rows:
            return {"csv": "", "count": 0}

        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
        csv_text = output.getvalue()
        return {"csv": csv_text, "count": len(rows)}

    return {"measurements": rows, "count": len(rows)}


# ── Bulk create ──────────────────────────────────────────────────────────


@router.post(
    "/measurements/bulk",
    response_model=list[TakeoffMeasurementResponse],
    status_code=201,
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def bulk_create_measurements(
    data: TakeoffMeasurementBulkCreate,
    user_id: CurrentUserId,
    service: TakeoffService = Depends(_get_service),
) -> list[TakeoffMeasurementResponse]:
    """Bulk create measurements (e.g. importing from localStorage)."""
    try:
        items = await service.bulk_create_measurements(
            data.measurements, created_by=user_id
        )
        return [_measurement_to_response(i) for i in items]
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to bulk create measurements")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to bulk create measurements",
        )


# ── Create ───────────────────────────────────────────────────────────────


@router.post(
    "/measurements",
    response_model=TakeoffMeasurementResponse,
    status_code=201,
    dependencies=[Depends(RequirePermission("takeoff.create"))],
)
async def create_measurement(
    data: TakeoffMeasurementCreate,
    user_id: CurrentUserId,
    service: TakeoffService = Depends(_get_service),
) -> TakeoffMeasurementResponse:
    """Create a new takeoff measurement."""
    try:
        item = await service.create_measurement(data, created_by=user_id)
        return _measurement_to_response(item)
    except HTTPException:
        raise
    except Exception:
        logger.exception("Failed to create measurement")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create measurement",
        )


# ── List ─────────────────────────────────────────────────────────────────


@router.get(
    "/measurements",
    response_model=list[TakeoffMeasurementResponse],
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def list_measurements(
    project_id: _uuid.UUID = Query(...),
    document_id: str | None = Query(default=None),
    page: int | None = Query(default=None, ge=1),
    group: str | None = Query(default=None),
    type: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> list[TakeoffMeasurementResponse]:
    """List measurements for a project with optional filters."""
    items = await service.list_measurements(
        project_id,
        document_id=document_id,
        page=page,
        group_name=group,
        measurement_type=type,
        offset=offset,
        limit=limit,
    )
    return [_measurement_to_response(i) for i in items]


# ── Get single ───────────────────────────────────────────────────────────


@router.get(
    "/measurements/{measurement_id}",
    response_model=TakeoffMeasurementResponse,
    dependencies=[Depends(RequirePermission("takeoff.read"))],
)
async def get_measurement(
    measurement_id: _uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> TakeoffMeasurementResponse:
    """Get a single measurement by ID."""
    item = await service.get_measurement(measurement_id)
    return _measurement_to_response(item)


# ── Update ───────────────────────────────────────────────────────────────


@router.patch(
    "/measurements/{measurement_id}",
    response_model=TakeoffMeasurementResponse,
    dependencies=[Depends(RequirePermission("takeoff.update"))],
)
async def update_measurement(
    measurement_id: _uuid.UUID,
    data: TakeoffMeasurementUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> TakeoffMeasurementResponse:
    """Update a measurement."""
    item = await service.update_measurement(measurement_id, data)
    return _measurement_to_response(item)


# ── Delete ───────────────────────────────────────────────────────────────


@router.delete(
    "/measurements/{measurement_id}",
    status_code=204,
    dependencies=[Depends(RequirePermission("takeoff.delete"))],
)
async def delete_measurement(
    measurement_id: _uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> None:
    """Delete a measurement."""
    await service.delete_measurement(measurement_id)


# ── Link to BOQ ──────────────────────────────────────────────────────────


@router.post(
    "/measurements/{measurement_id}/link-to-boq",
    response_model=TakeoffMeasurementResponse,
    dependencies=[Depends(RequirePermission("takeoff.update"))],
)
async def link_measurement_to_boq(
    measurement_id: _uuid.UUID,
    data: LinkToBoqRequest,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: TakeoffService = Depends(_get_service),
) -> TakeoffMeasurementResponse:
    """Link a measurement to a BOQ position."""
    item = await service.link_measurement_to_boq(
        measurement_id, data.boq_position_id
    )
    return _measurement_to_response(item)
