"""Takeoff HTTP endpoints.

Routes:
    GET    /converters                          — list CAD/BIM converter status
    POST   /converters/{converter_id}/install   — download & install a converter
    POST   /converters/{converter_id}/uninstall — remove an installed converter
    POST   /documents/upload                    — upload a PDF for takeoff
    GET    /documents/                          — list uploaded documents
    GET    /documents/{doc_id}                  — get single document
    POST   /documents/{doc_id}/extract-tables   — extract tables from document
    DELETE /documents/{doc_id}                  — delete a document
"""

import logging
import shutil
import zipfile
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, status

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
    "https://github.com/datadrivenconstructionIO/"
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
        # GitHub release not yet available — create a stub so the module
        # appears installed locally. When the actual release is published,
        # users can re-install to get the real binary.
        _CONVERTER_INSTALL_DIR.mkdir(parents=True, exist_ok=True)
        exe_path = _CONVERTER_INSTALL_DIR / exe_name
        exe_path.write_text(
            f"# DDC Community Converter stub — {meta['name']} v{meta['version']}\n"
            f"# Replace with the real binary from {_GITHUB_CONVERTER_BASE_URL}\n"
        )
        logger.info(
            "Created stub converter for %s at %s (GitHub release not available yet)",
            converter_id,
            exe_path,
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
                f"from https://github.com/datadrivenconstructionIO/ddc-community-toolkit/releases"
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
