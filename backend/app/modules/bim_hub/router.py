"""BIM Hub API routes.

Endpoints:
    Models:
        GET    /                                — List models for a project
        POST   /                                — Create model
        POST   /upload                          — Upload BIM data (DataFrame + optional DAE)
        GET    /{model_id}                      — Get single model
        PATCH  /{model_id}                      — Update model
        DELETE /{model_id}                      — Delete model
        GET    /models/{model_id}/geometry       — Serve DAE geometry file

    Elements:
        GET    /models/{model_id}/elements      — List elements (paginated, filterable)
        POST   /models/{model_id}/elements      — Bulk import elements
        GET    /elements/{element_id}            — Get single element

    BOQ Links:
        GET    /links                            — List links for a BOQ position
        POST   /links                            — Create link
        DELETE /links/{link_id}                  — Delete link

    Quantity Maps:
        GET    /quantity-maps                    — List quantity map rules
        POST   /quantity-maps                    — Create quantity map rule
        PATCH  /quantity-maps/{map_id}           — Update quantity map rule
        POST   /quantity-maps/apply              — Apply rules on model

    Diffs:
        POST   /models/{model_id}/diff/{old_id}  — Compute diff
        GET    /diffs/{diff_id}                   — Get diff
"""

import csv
import io
import json
import logging
import pathlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse

from app.dependencies import CurrentUserId, SessionDep
from app.modules.bim_hub.schemas import (
    BIMElementBulkImport,
    BIMElementListResponse,
    BIMElementResponse,
    BIMModelCreate,
    BIMModelDiffResponse,
    BIMModelListResponse,
    BIMModelResponse,
    BIMModelUpdate,
    BIMQuantityMapCreate,
    BIMQuantityMapListResponse,
    BIMQuantityMapResponse,
    BIMQuantityMapUpdate,
    BOQElementLinkCreate,
    BOQElementLinkListResponse,
    BOQElementLinkResponse,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.bim_hub.service import BIMHubService

logger = logging.getLogger(__name__)

router = APIRouter()

# Base directory for storing BIM geometry files
_BIM_DATA_DIR = pathlib.Path(__file__).resolve().parents[4] / "data" / "bim"


def _get_service(session: SessionDep) -> BIMHubService:
    return BIMHubService(session)


# ═══════════════════════════════════════════════════════════════════════════════
# DataFrame column alias detection (flexible header matching)
# ═══════════════════════════════════════════════════════════════════════════════

_BIM_COLUMN_ALIASES: dict[str, list[str]] = {
    "element_id": [
        "element_id",
        "elementid",
        "id",
        "guid",
        "ifc_guid",
        "ifcguid",
        "global_id",
        "globalid",
        "stable_id",
        "stableid",
        "unique_id",
        "uniqueid",
        "revit_id",
        "elem_id",
    ],
    "element_type": [
        "element_type",
        "elementtype",
        "type",
        "category",
        "ifc_type",
        "ifctype",
        "object_type",
        "objecttype",
        "family",
        "class",
    ],
    "name": [
        "name",
        "element_name",
        "elementname",
        "description",
        "bezeichnung",
        "label",
        "title",
        "family_name",
        "familyname",
    ],
    "storey": [
        "storey",
        "story",
        "level",
        "floor",
        "etage",
        "geschoss",
        "building_storey",
        "buildingstorey",
        "ifc_storey",
    ],
    "discipline": [
        "discipline",
        "disziplin",
        "trade",
        "gewerk",
        "domain",
        "system",
    ],
    "area_m2": [
        "area_m2",
        "area",
        "flaeche",
        "fläche",
        "surface_area",
        "surfacearea",
        "gross_area",
        "grossarea",
        "net_area",
        "netarea",
    ],
    "volume_m3": [
        "volume_m3",
        "volume",
        "volumen",
        "gross_volume",
        "grossvolume",
        "net_volume",
        "netvolume",
    ],
    "length_m": [
        "length_m",
        "length",
        "laenge",
        "länge",
        "span",
    ],
    "weight_kg": [
        "weight_kg",
        "weight",
        "gewicht",
        "mass",
        "masse",
    ],
    "properties": [
        "properties",
        "props",
        "attributes",
        "parameters",
        "pset",
    ],
}


def _match_bim_column(header: str) -> str | None:
    """Match a header string to a canonical BIM column name."""
    normalised = header.strip().lower().replace(" ", "_").replace("-", "_")
    for canonical, aliases in _BIM_COLUMN_ALIASES.items():
        if normalised in aliases:
            return canonical
    return normalised if normalised else None


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Parse a value to float, returning *default* on failure."""
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    if "," in text and "." in text:
        last_comma = text.rfind(",")
        last_dot = text.rfind(".")
        if last_comma > last_dot:
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif "," in text:
        text = text.replace(",", ".")
    try:
        return float(text)
    except (ValueError, TypeError):
        return default


def _parse_bim_rows_from_csv(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from a CSV file for BIM element import."""
    for encoding in ("utf-8-sig", "utf-8", "latin-1"):
        try:
            text = content_bytes.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Unable to decode CSV file — unsupported encoding")

    sniffer = csv.Sniffer()
    try:
        dialect = sniffer.sniff(text[:4096], delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel  # type: ignore[assignment]

    reader = csv.reader(io.StringIO(text), dialect)
    raw_headers = next(reader, None)
    if not raw_headers:
        raise ValueError("CSV file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        canonical = _match_bim_column(hdr)
        if canonical:
            column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in reader:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical:
                row[canonical] = val.strip() if isinstance(val, str) else val
        if row:
            rows.append(row)

    return rows


def _parse_bim_rows_from_excel(content_bytes: bytes) -> list[dict[str, Any]]:
    """Parse rows from an Excel (.xlsx) file for BIM element import."""
    from openpyxl import load_workbook

    wb = load_workbook(io.BytesIO(content_bytes), read_only=True, data_only=True)
    ws = wb.active
    if ws is None:
        raise ValueError("Excel file has no worksheets")

    rows_iter = ws.iter_rows(values_only=True)
    raw_headers = next(rows_iter, None)
    if not raw_headers:
        raise ValueError("Excel file is empty or has no header row")

    column_map: dict[int, str] = {}
    for idx, hdr in enumerate(raw_headers):
        if hdr is not None:
            canonical = _match_bim_column(str(hdr))
            if canonical:
                column_map[idx] = canonical

    rows: list[dict[str, Any]] = []
    for raw_row in rows_iter:
        row: dict[str, Any] = {}
        for idx, val in enumerate(raw_row):
            canonical = column_map.get(idx)
            if canonical and val is not None:
                row[canonical] = val
        if row:
            rows.append(row)

    wb.close()
    return rows


def _rows_to_elements(
    rows: list[dict[str, Any]],
    has_geometry: bool,
) -> list[dict[str, Any]]:
    """Convert parsed rows into BIMElement-compatible dicts.

    Builds quantities JSON from area_m2, volume_m3, length_m, weight_kg columns.
    Parses properties column as JSON if present.
    """
    elements: list[dict[str, Any]] = []
    quantity_keys = {"area_m2", "volume_m3", "length_m", "weight_kg"}

    for row in rows:
        eid = str(row.get("element_id", "")).strip()
        if not eid:
            continue

        # Parse quantities
        quantities: dict[str, float] = {}
        for qk in quantity_keys:
            val = row.get(qk)
            if val is not None:
                fval = _safe_float(val)
                if fval != 0.0:
                    quantities[qk] = fval

        # Parse properties (could be JSON string)
        raw_props = row.get("properties")
        props: dict[str, Any] = {}
        if isinstance(raw_props, str) and raw_props.strip():
            try:
                props = json.loads(raw_props)
            except (json.JSONDecodeError, ValueError):
                props = {"raw": raw_props}
        elif isinstance(raw_props, dict):
            props = raw_props

        # Collect any extra columns not in known canonical keys as properties
        known_keys = {
            "element_id", "element_type", "name", "storey",
            "discipline", "properties",
        } | quantity_keys
        for k, v in row.items():
            if k not in known_keys and v is not None and str(v).strip():
                props[k] = v

        element: dict[str, Any] = {
            "stable_id": eid,
            "element_type": str(row.get("element_type", "")).strip() or None,
            "name": str(row.get("name", "")).strip() or None,
            "storey": str(row.get("storey", "")).strip() or None,
            "discipline": str(row.get("discipline", "")).strip() or None,
            "quantities": quantities,
            "properties": props,
            "mesh_ref": eid if has_geometry else None,
        }
        elements.append(element)

    return elements


# ═══════════════════════════════════════════════════════════════════════════════
# Upload (DataFrame + optional DAE geometry)
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/upload/", status_code=201)
async def upload_bim_data(
    project_id: str = Query(..., description="Project UUID"),
    name: str = Query(default="Imported Model", max_length=255),
    discipline: str = Query(default="architecture", max_length=50),
    data_file: UploadFile = File(..., description="CSV or Excel file with element data"),
    geometry_file: UploadFile | None = File(
        default=None, description="DAE/COLLADA geometry file"
    ),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> dict[str, Any]:
    """Upload BIM data from Cad2Data converter output.

    Accepts a DataFrame file (CSV/Excel) with one row per building element
    and an optional COLLADA (.dae) geometry file where each mesh node has
    an ID matching ``element_id`` from the DataFrame.

    Expected DataFrame columns (flexible auto-detection via aliases):
    - **element_id / id / guid** -- unique element identifier (required)
    - **element_type / type / category** -- element classification
    - **name / description** -- human-readable name
    - **storey / level / floor** -- building storey assignment
    - **discipline / trade** -- discipline (architecture, structural, ...)
    - **area_m2 / area** -- area in m2
    - **volume_m3 / volume** -- volume in m3
    - **length_m / length** -- length in m
    - **weight_kg / weight** -- weight in kg
    - **properties** -- JSON string of additional properties

    Returns:
        Summary with model_id, element_count, storeys, and disciplines.
    """
    # --- Validate data file ---
    data_filename = (data_file.filename or "").lower()
    if not data_filename.endswith((".csv", ".xlsx", ".xls")):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Unsupported data file type. Please upload CSV (.csv) or Excel (.xlsx) file.",
        )

    data_content = await data_file.read()
    if not data_content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded data file is empty.",
        )

    # 50 MB limit for data files
    if len(data_content) > 50 * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Data file too large. Maximum size is 50 MB.",
        )

    # --- Validate geometry file (if provided) ---
    has_geometry = False
    geometry_content: bytes | None = None
    if geometry_file is not None:
        geo_filename = (geometry_file.filename or "").lower()
        if not geo_filename.endswith((".dae", ".glb", ".gltf")):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported geometry file type. Please upload DAE (.dae), GLB (.glb), or glTF (.gltf) file.",
            )
        geometry_content = await geometry_file.read()
        if geometry_content:
            # 200 MB limit for geometry files
            if len(geometry_content) > 200 * 1024 * 1024:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Geometry file too large. Maximum size is 200 MB.",
                )
            has_geometry = True

    # --- Parse data file ---
    try:
        if data_filename.endswith((".xlsx", ".xls")):
            rows = _parse_bim_rows_from_excel(data_content)
        else:
            rows = _parse_bim_rows_from_csv(data_content)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse data file: {exc}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error parsing BIM data file")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to parse data file: {exc}",
        ) from exc

    if not rows:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No data rows found in the uploaded file.",
        )

    # --- Convert rows to element dicts ---
    element_dicts = _rows_to_elements(rows, has_geometry=has_geometry)
    if not element_dicts:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No valid elements found. Ensure the file has an 'element_id' column.",
        )

    # --- Determine format from geometry file extension ---
    geo_ext = ""
    if geometry_file and geometry_file.filename:
        geo_ext = pathlib.Path(geometry_file.filename).suffix.lstrip(".").lower()

    model_format = geo_ext if geo_ext else "csv"

    # --- Create BIM model ---
    from app.modules.bim_hub.schemas import BIMModelCreate

    model_data = BIMModelCreate(
        project_id=uuid.UUID(project_id),
        name=name,
        discipline=discipline,
        model_format=model_format,
        status="processing",
    )
    model = await service.create_model(model_data, user_id=user_id)
    model_id = model.id

    # --- Save geometry file to disk ---
    if has_geometry and geometry_content:
        geo_dir = _BIM_DATA_DIR / str(project_id) / str(model_id)
        geo_dir.mkdir(parents=True, exist_ok=True)
        ext = pathlib.Path(geometry_file.filename or "geometry.dae").suffix or ".dae"  # type: ignore[union-attr]
        geo_path = geo_dir / f"geometry{ext}"
        geo_path.write_bytes(geometry_content)
        logger.info("Saved BIM geometry: %s (%d bytes)", geo_path, len(geometry_content))

    # --- Import elements ---
    from app.modules.bim_hub.schemas import BIMElementCreate

    elements_create = [
        BIMElementCreate(
            stable_id=ed["stable_id"],
            element_type=ed.get("element_type"),
            name=ed.get("name"),
            storey=ed.get("storey"),
            discipline=ed.get("discipline") or discipline,
            quantities=ed.get("quantities", {}),
            properties=ed.get("properties", {}),
            mesh_ref=ed.get("mesh_ref"),
        )
        for ed in element_dicts
    ]
    created_elements = await service.bulk_import_elements(model_id, elements_create)

    # Compute summary
    storeys = sorted({e.storey for e in created_elements if e.storey})
    disciplines_found = sorted({e.discipline for e in created_elements if e.discipline})

    logger.info(
        "BIM upload complete: model=%s, elements=%d, storeys=%d, disciplines=%s",
        name,
        len(created_elements),
        len(storeys),
        disciplines_found,
    )

    return {
        "model_id": str(model_id),
        "element_count": len(created_elements),
        "storeys": storeys,
        "disciplines": disciplines_found,
        "has_geometry": has_geometry,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Direct CAD file upload (RVT, IFC, DWG, DGN, FBX, OBJ, 3DS)
# ═══════════════════════════════════════════════════════════════════════════════

_ALLOWED_CAD_EXTENSIONS = {".rvt", ".ifc", ".dwg", ".dgn", ".fbx", ".obj", ".3ds"}
_CAD_MAX_SIZE = 500 * 1024 * 1024  # 500 MB


@router.post("/upload-cad/", status_code=201)
async def upload_cad_file(
    project_id: str = Query(..., description="Project UUID"),
    name: str = Query(default="", max_length=255),
    discipline: str = Query(default="architecture", max_length=50),
    file: UploadFile = File(..., description="CAD file (RVT, IFC, DWG, DGN, FBX, OBJ, 3DS)"),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> dict:
    """Upload a raw CAD file for background processing.

    The file is stored on disk at ``data/bim/{project_id}/{model_id}/original.{ext}``
    and a BIMModel record is created with status="processing". A real CAD converter
    service would pick it up asynchronously; for now the model stays in processing state.

    Accepted extensions: .rvt, .ifc, .dwg, .dgn, .fbx, .obj, .3ds
    Max size: 500 MB
    """
    filename = (file.filename or "").strip()
    if not filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No filename provided.",
        )

    ext = pathlib.Path(filename).suffix.lower()
    if ext not in _ALLOWED_CAD_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                f"Unsupported file type '{ext}'. "
                f"Accepted: {', '.join(sorted(_ALLOWED_CAD_EXTENSIONS))}"
            ),
        )

    content = await file.read()
    if not content:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Uploaded file is empty.",
        )
    if len(content) > _CAD_MAX_SIZE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"File too large. Maximum size is {_CAD_MAX_SIZE // (1024 * 1024)} MB.",
        )

    # Auto-fill model name from filename
    model_name = name or pathlib.Path(filename).stem

    # Determine model format from extension (strip the dot)
    model_format = ext.lstrip(".")

    # Create BIM model record with processing status
    from app.modules.bim_hub.schemas import BIMModelCreate

    model_data = BIMModelCreate(
        project_id=uuid.UUID(project_id),
        name=model_name,
        discipline=discipline,
        model_format=model_format,
        status="processing",
    )
    model = await service.create_model(model_data, user_id=user_id)
    model_id = model.id

    # Save CAD file to disk
    cad_dir = _BIM_DATA_DIR / str(project_id) / str(model_id)
    cad_dir.mkdir(parents=True, exist_ok=True)
    cad_path = cad_dir / f"original{ext}"
    cad_path.write_bytes(content)

    logger.info(
        "CAD file uploaded: %s (%s, %d bytes) -> model %s",
        filename,
        ext,
        len(content),
        model_id,
    )

    # Cross-link: create Document record so BIM files appear in Documents hub
    try:
        import json as _json
        from datetime import datetime as _dt
        from sqlalchemy import text as _text

        doc_id = str(uuid.uuid4())
        now = _dt.utcnow().isoformat()
        tags_json = _json.dumps(["bim", model_format, discipline])
        await service.session.execute(
            _text(
                "INSERT INTO oe_documents_document "
                "(id, project_id, name, description, category, file_size, mime_type, "
                "file_path, version, uploaded_by, tags, metadata, created_at, updated_at) "
                "VALUES (:id, :pid, :name, :desc, :cat, :fsize, :mime, :fpath, 1, :by, :tags, '{}', :now, :now)"
            ),
            {
                "id": doc_id, "pid": project_id, "name": filename,
                "desc": f"BIM model: {model_name}", "cat": "drawing",
                "fsize": len(content), "mime": f"application/{model_format}",
                "fpath": str(cad_path), "by": user_id or "",
                "tags": tags_json, "now": now,
            },
        )
        logger.info("Cross-linked BIM model %s → document %s", model_id, doc_id)
    except Exception as exc:
        logger.warning("Failed to cross-link BIM to documents hub: %s", exc)

    # Process the CAD file — extract elements + generate COLLADA geometry
    # IFC: text-based parser (instant). RVT: requires DDC cad2data binary.
    final_status = "processing"
    element_count = 0

    processable = ext in (".ifc", ".rvt")
    if processable:
        try:
            import asyncio
            from app.modules.bim_hub.ifc_processor import process_ifc_file

            # Run sync processor in thread to avoid blocking the event loop
            result = await asyncio.to_thread(process_ifc_file, cad_path, cad_dir)
            element_count = result["element_count"]

            if element_count > 0:
                # Insert elements into DB
                from app.modules.bim_hub.models import BIMElement

                for elem_data in result["elements"]:
                    el = BIMElement(
                        model_id=model_id,
                        stable_id=elem_data["stable_id"],
                        element_type=elem_data.get("element_type"),
                        name=elem_data.get("name"),
                        storey=elem_data.get("storey"),
                        discipline=elem_data.get("discipline"),
                        properties=elem_data.get("properties", {}),
                        quantities=elem_data.get("quantities", {}),
                        geometry_hash=elem_data.get("geometry_hash"),
                        bounding_box=elem_data.get("bounding_box"),
                    )
                    service.session.add(el)

                # Update model record
                model.status = "ready"
                model.element_count = element_count
                model.storey_count = len(result["storeys"])
                model.bounding_box = result.get("bounding_box")
                if result.get("geometry_path"):
                    model.canonical_file_path = result["geometry_path"]
                await service.session.flush()
                final_status = "ready"

                logger.info(
                    "CAD processed: %d elements, %d storeys → model %s is ready",
                    element_count, len(result["storeys"]), model_id,
                )
            else:
                # No elements extracted — set informative status
                if ext == ".rvt":
                    model.status = "needs_converter"
                    model.error_message = (
                        "RVT files require the DDC cad2data converter. "
                        "Install cad2data or convert to IFC first, then re-upload."
                    )
                else:
                    model.status = "error"
                    model.error_message = "No elements could be extracted from this IFC file."
                await service.session.flush()
                final_status = model.status
                logger.warning("CAD processed but no elements found: %s", filename)
        except Exception as exc:
            logger.warning("CAD processing failed for %s: %s", filename, exc)
            model.status = "error"
            model.error_message = f"Processing failed: {exc}"
            try:
                await service.session.flush()
            except Exception:
                pass
            final_status = "error"
    else:
        # Non-processable format (DWG, DGN, FBX, etc.) — needs converter
        model.status = "needs_converter"
        model.error_message = (
            f"{ext.upper().lstrip('.')} files require an external converter. "
            "Convert to IFC first, then re-upload."
        )
        await service.session.flush()
        final_status = "needs_converter"

    return {
        "model_id": str(model_id),
        "name": model_name,
        "format": model_format,
        "file_size": len(content),
        "status": final_status,
        "element_count": element_count,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# Geometry file serving
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/models/{model_id}/geometry/")
async def get_model_geometry(
    model_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> FileResponse:
    """Serve the COLLADA/DAE geometry file for the 3D viewer.

    Looks for geometry files (DAE, GLB, glTF) saved during upload
    at ``data/bim/{project_id}/{model_id}/geometry.*``.
    """
    model = await service.get_model(model_id)
    project_id = str(model.project_id)
    geo_dir = _BIM_DATA_DIR / project_id / str(model_id)

    # Try known extensions
    for ext in (".dae", ".glb", ".gltf"):
        geo_path = geo_dir / f"geometry{ext}"
        if geo_path.is_file():
            media_types = {
                ".dae": "model/vnd.collada+xml",
                ".glb": "model/gltf-binary",
                ".gltf": "model/gltf+json",
            }
            return FileResponse(
                path=str(geo_path),
                media_type=media_types.get(ext, "application/octet-stream"),
                filename=f"{model.name}{ext}",
            )

    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="No geometry file found for this model.",
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Models
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/", response_model=BIMModelListResponse)
async def list_models(
    project_id: uuid.UUID = Query(...),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=50, ge=1, le=200),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelListResponse:
    """List BIM models for a project."""
    items, total = await service.list_models(project_id, offset=offset, limit=limit)
    return BIMModelListResponse(
        items=[BIMModelResponse.model_validate(m) for m in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/", response_model=BIMModelResponse, status_code=201)
async def create_model(
    data: BIMModelCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Create a new BIM model record."""
    model = await service.create_model(data, user_id=user_id)
    return BIMModelResponse.model_validate(model)


@router.get("/{model_id}", response_model=BIMModelResponse)
async def get_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Get a single BIM model by ID."""
    model = await service.get_model(model_id)
    return BIMModelResponse.model_validate(model)


@router.patch("/{model_id}", response_model=BIMModelResponse)
async def update_model(
    model_id: uuid.UUID,
    data: BIMModelUpdate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Update a BIM model."""
    model = await service.update_model(model_id, data)
    return BIMModelResponse.model_validate(model)


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BIM model and all its elements."""
    await service.delete_model(model_id)


@router.post("/cleanup-stale")
async def cleanup_stale_processing(
    project_id: uuid.UUID = Query(...),
    max_age_hours: int = Query(default=1, ge=0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> dict[str, int]:
    """Remove models stuck in 'processing' with 0 elements older than max_age_hours."""
    count = await service.cleanup_stale_processing(project_id, max_age_hours=max_age_hours)
    return {"deleted": count}


# ═══════════════════════════════════════════════════════════════════════════════
# Elements
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/models/{model_id}/elements/", response_model=BIMElementListResponse)
async def list_elements(
    model_id: uuid.UUID,
    element_type: str | None = Query(default=None),
    storey: str | None = Query(default=None),
    discipline: str | None = Query(default=None),
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=200, ge=1, le=5000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """List elements for a BIM model (paginated, filterable)."""
    items, total = await service.list_elements(
        model_id,
        element_type=element_type,
        storey=storey,
        discipline=discipline,
        offset=offset,
        limit=limit,
    )
    return BIMElementListResponse(
        items=[BIMElementResponse.model_validate(e) for e in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post(
    "/models/{model_id}/elements/",
    response_model=BIMElementListResponse,
    status_code=201,
)
async def bulk_import_elements(
    model_id: uuid.UUID,
    data: BIMElementBulkImport,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """Bulk import elements for a model (replaces existing)."""
    elements = await service.bulk_import_elements(model_id, data.elements)
    return BIMElementListResponse(
        items=[BIMElementResponse.model_validate(e) for e in elements],
        total=len(elements),
        offset=0,
        limit=len(elements),
    )


@router.get("/elements/{element_id}", response_model=BIMElementResponse)
async def get_element(
    element_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMElementResponse:
    """Get a single BIM element by ID."""
    element = await service.get_element(element_id)
    return BIMElementResponse.model_validate(element)


# ═══════════════════════════════════════════════════════════════════════════════
# BOQ Links
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/links/", response_model=BOQElementLinkListResponse)
async def list_links(
    boq_position_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkListResponse:
    """List BIM element links for a BOQ position."""
    items = await service.list_links_for_position(boq_position_id)
    return BOQElementLinkListResponse(
        items=[BOQElementLinkResponse.model_validate(lnk) for lnk in items],
        total=len(items),
    )


@router.post("/links/", response_model=BOQElementLinkResponse, status_code=201)
async def create_link(
    data: BOQElementLinkCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkResponse:
    """Create a link between a BOQ position and a BIM element."""
    link = await service.create_link(data, user_id=user_id)
    return BOQElementLinkResponse.model_validate(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(
    link_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BOQ-BIM link."""
    await service.delete_link(link_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Quantity Maps
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/quantity-maps/", response_model=BIMQuantityMapListResponse)
async def list_quantity_maps(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapListResponse:
    """List quantity mapping rules."""
    items, total = await service.list_quantity_maps(offset=offset, limit=limit)
    return BIMQuantityMapListResponse(
        items=[BIMQuantityMapResponse.model_validate(m) for m in items],
        total=total,
    )


@router.post("/quantity-maps/", response_model=BIMQuantityMapResponse, status_code=201)
async def create_quantity_map(
    data: BIMQuantityMapCreate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Create a new quantity mapping rule."""
    qmap = await service.create_quantity_map(data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.patch("/quantity-maps/{map_id}", response_model=BIMQuantityMapResponse)
async def update_quantity_map(
    map_id: uuid.UUID,
    data: BIMQuantityMapUpdate,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Update a quantity mapping rule."""
    qmap = await service.update_quantity_map(map_id, data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.post("/quantity-maps/apply/", response_model=QuantityMapApplyResult)
async def apply_quantity_maps(
    data: QuantityMapApplyRequest,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> QuantityMapApplyResult:
    """Apply quantity mapping rules to all elements in a model."""
    return await service.apply_quantity_maps(data)


# ═══════════════════════════════════════════════════════════════════════════════
# Diffs
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/models/{model_id}/diff/{old_id}", response_model=BIMModelDiffResponse, status_code=201)
async def compute_diff(
    model_id: uuid.UUID,
    old_id: uuid.UUID,
    user_id: CurrentUserId,
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Compute diff between two model versions."""
    diff = await service.compute_diff(new_model_id=model_id, old_model_id=old_id)
    return BIMModelDiffResponse.model_validate(diff)


@router.get("/diffs/{diff_id}", response_model=BIMModelDiffResponse)
async def get_diff(
    diff_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Get a model diff by ID."""
    diff = await service.get_diff(diff_id)
    return BIMModelDiffResponse.model_validate(diff)
