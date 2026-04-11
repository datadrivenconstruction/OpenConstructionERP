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

    Element Groups (saved selections):
        GET    /element-groups/                   — List groups for a project
        POST   /element-groups/                   — Create a group
        PATCH  /element-groups/{group_id}         — Update a group
        DELETE /element-groups/{group_id}         — Delete a group
"""

import csv
import io
import json
import logging
import pathlib
import uuid
from typing import Any

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, UploadFile, status
from fastapi.responses import RedirectResponse, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import CurrentUserId, RequirePermission, SessionDep
from app.modules.bim_hub import file_storage as bim_file_storage
from app.modules.bim_hub.schemas import (
    BIMElementBulkImport,
    BIMElementGroupCreate,
    BIMElementGroupResponse,
    BIMElementGroupUpdate,
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
    BOQElementLinkBrief,
    BOQElementLinkCreate,
    BOQElementLinkListResponse,
    BOQElementLinkResponse,
    QuantityMapApplyRequest,
    QuantityMapApplyResult,
)
from app.modules.bim_hub.service import BIMHubService

logger = logging.getLogger(__name__)

router = APIRouter()

# Legacy on-disk path kept only for backward compatibility with any
# external code that may still import ``_BIM_DATA_DIR``.  New code MUST
# go through :mod:`app.modules.bim_hub.file_storage` which wraps the
# pluggable :class:`~app.core.storage.StorageBackend`.
_BIM_DATA_DIR = pathlib.Path(__file__).resolve().parents[4] / "data" / "bim"


def _get_service(session: SessionDep) -> BIMHubService:
    return BIMHubService(session)


# ═══════════════════════════════════════════════════════════════════════════════
# Project-ownership authorization helper
#
# Every BIM endpoint that touches a project (directly via ?project_id= or
# indirectly via a model/element/diff that belongs to a project) MUST call
# ``_verify_project_access`` before returning data or mutating state.
#
# This closes the IDOR from the v1.3.13 audit: previously any authenticated
# user could read/modify/delete models belonging to projects they do not own
# simply by guessing UUIDs. We now resolve the underlying project, verify
# ownership (or admin bypass) and return a 404 — not a 403 — so we also don't
# leak the existence of UUIDs the caller is not allowed to see.
# ═══════════════════════════════════════════════════════════════════════════════


async def _verify_project_access(
    session: AsyncSession,
    project_id: uuid.UUID,
    user_id: str,
) -> None:
    """Raise 404 if the user is not the owner or an admin of the project.

    Mirrors the central helper in ``erp_chat.tools._require_project_access``
    but returns an HTTPException suitable for router use. Emits 404 (not 403)
    on both "project missing" and "access denied" to avoid UUID enumeration.
    """
    from app.modules.projects.repository import ProjectRepository
    from app.modules.users.repository import UserRepository

    proj_repo = ProjectRepository(session)
    project = await proj_repo.get_by_id(project_id)
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )

    # Admin bypass — admins can touch any project regardless of ownership.
    try:
        user_repo = UserRepository(session)
        user = await user_repo.get_by_id(uuid.UUID(str(user_id)))
        if user is not None and getattr(user, "role", "") == "admin":
            return
    except Exception:
        # If the role lookup explodes, fall through to the ownership check —
        # never silently bypass authorization.
        logger.exception("Admin-role lookup failed during BIM access check")

    if str(project.owner_id) != str(user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Project not found",
        )


async def _verify_model_access(
    service: "BIMHubService",
    model_id: uuid.UUID,
    user_id: str,
) -> Any:
    """Load a BIM model and verify the caller owns its project.

    Returns the model object so callers can reuse it without a second query.
    Raises 404 if the model is missing or the user has no access.
    """
    model = await service.get_model(model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )
    await _verify_project_access(service.session, model.project_id, user_id)
    return model


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
        "level_name",
        "levelname",
        "host_level_name",
        "hostlevelname",
        "floor",
        "floor_name",
        "etage",
        "geschoss",
        "building_storey",
        "buildingstorey",
        "ifc_storey",
        "ifcstorey",
        "base_constraint",
        "baseconstraint",
        "base_level",
        "baselevel",
        "reference_level",
        "referencelevel",
        "associated_level",
        "associatedlevel",
        "schedule_level",
        "schedulelevel",
    ],
    "mesh_ref": [
        "mesh_ref",
        "meshref",
        "mesh_id",
        "meshid",
        "node_id",
        "nodeid",
        "dae_node",
        "daenode",
        "collada_node",
        "colladanode",
        "geometry_ref",
        "geometryref",
    ],
    "bbox_min_x": [
        "bbox_min_x", "bboxminx", "min_x", "minx",
        "bounding_box_min_x", "boundingboxminx",
        "bb_min_x", "bbminx", "xmin",
    ],
    "bbox_min_y": [
        "bbox_min_y", "bboxminy", "min_y", "miny",
        "bounding_box_min_y", "boundingboxminy",
        "bb_min_y", "bbminy", "ymin",
    ],
    "bbox_min_z": [
        "bbox_min_z", "bboxminz", "min_z", "minz",
        "bounding_box_min_z", "boundingboxminz",
        "bb_min_z", "bbminz", "zmin",
    ],
    "bbox_max_x": [
        "bbox_max_x", "bboxmaxx", "max_x", "maxx",
        "bounding_box_max_x", "boundingboxmaxx",
        "bb_max_x", "bbmaxx", "xmax",
    ],
    "bbox_max_y": [
        "bbox_max_y", "bboxmaxy", "max_y", "maxy",
        "bounding_box_max_y", "boundingboxmaxy",
        "bb_max_y", "bbmaxy", "ymax",
    ],
    "bbox_max_z": [
        "bbox_max_z", "bboxmaxz", "max_z", "maxz",
        "bounding_box_max_z", "boundingboxmaxz",
        "bb_max_z", "bbmaxz", "zmax",
    ],
    "bounding_box": [
        "bounding_box",
        "boundingbox",
        "bbox",
        "aabb",
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

        # Explicit mesh_ref column wins, otherwise fall back to element_id
        # (which matches DDC RvtExporter's DAE ``<node id="...">`` pattern).
        raw_mesh_ref = row.get("mesh_ref")
        if raw_mesh_ref is not None and str(raw_mesh_ref).strip():
            mesh_ref: str | None = str(raw_mesh_ref).strip()
        elif has_geometry:
            mesh_ref = eid
        else:
            mesh_ref = None

        # Explicit bbox — either a pre-built JSON blob in ``bounding_box`` or
        # six individual min/max columns.
        bbox: dict[str, float] | None = None
        raw_bbox = row.get("bounding_box")
        if isinstance(raw_bbox, dict):
            bbox = {k: float(v) for k, v in raw_bbox.items() if v is not None}
        elif isinstance(raw_bbox, str) and raw_bbox.strip():
            try:
                parsed = json.loads(raw_bbox)
                if isinstance(parsed, dict):
                    bbox = {k: float(v) for k, v in parsed.items() if v is not None}
            except (json.JSONDecodeError, ValueError, TypeError):
                pass
        if bbox is None:
            bbox_keys = ("bbox_min_x", "bbox_min_y", "bbox_min_z",
                         "bbox_max_x", "bbox_max_y", "bbox_max_z")
            if any(row.get(k) is not None for k in bbox_keys):
                bbox = {
                    "min_x": _safe_float(row.get("bbox_min_x")),
                    "min_y": _safe_float(row.get("bbox_min_y")),
                    "min_z": _safe_float(row.get("bbox_min_z")),
                    "max_x": _safe_float(row.get("bbox_max_x")),
                    "max_y": _safe_float(row.get("bbox_max_y")),
                    "max_z": _safe_float(row.get("bbox_max_z")),
                }
                # Heuristic: if the numbers look like millimetres (range >10000
                # in any axis) convert to metres.
                ranges = [
                    abs(bbox["max_x"] - bbox["min_x"]),
                    abs(bbox["max_y"] - bbox["min_y"]),
                    abs(bbox["max_z"] - bbox["min_z"]),
                ]
                if any(r > 10_000 for r in ranges):
                    bbox = {k: v / 1000.0 for k, v in bbox.items()}

        # Collect any extra columns not in known canonical keys as properties
        bbox_col_keys = {
            "bounding_box", "bbox_min_x", "bbox_min_y", "bbox_min_z",
            "bbox_max_x", "bbox_max_y", "bbox_max_z",
        }
        known_keys = {
            "element_id", "element_type", "name", "storey",
            "discipline", "properties", "mesh_ref",
        } | quantity_keys | bbox_col_keys
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
            "mesh_ref": mesh_ref,
            "bounding_box": bbox,
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
    _perm: None = Depends(RequirePermission("bim.create")),
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
    # --- Verify project access (IDOR guard) ---
    try:
        project_uuid = uuid.UUID(project_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project_id: {exc}",
        ) from exc
    await _verify_project_access(service.session, project_uuid, user_id or "")

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

    # --- Save geometry file to configured storage backend ---
    if has_geometry and geometry_content:
        ext = pathlib.Path(geometry_file.filename or "geometry.dae").suffix or ".dae"  # type: ignore[union-attr]
        await bim_file_storage.save_geometry(
            project_id=project_id,
            model_id=str(model_id),
            ext=ext,
            content=geometry_content,
        )

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
            bounding_box=ed.get("bounding_box"),
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
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> dict:
    """Upload a raw CAD file for background processing.

    The file is stored on disk at ``data/bim/{project_id}/{model_id}/original.{ext}``
    and a BIMModel record is created with status="processing". A real CAD converter
    service would pick it up asynchronously; for now the model stays in processing state.

    Accepted extensions: .rvt, .ifc, .dwg, .dgn, .fbx, .obj, .3ds
    Max size: 500 MB
    """
    # --- Verify project access (IDOR guard) ---
    try:
        project_uuid = uuid.UUID(project_id)
    except (ValueError, TypeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid project_id: {exc}",
        ) from exc
    await _verify_project_access(service.session, project_uuid, user_id or "")

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

    # Save CAD file via the configured storage backend
    await bim_file_storage.save_original_cad(
        project_id=project_id,
        model_id=str(model_id),
        ext=ext,
        content=content,
    )

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
                        mesh_ref=elem_data.get("mesh_ref"),
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


@router.get("/models/{model_id}/geometry/", response_model=None)
async def get_model_geometry(
    model_id: uuid.UUID,
    token: str | None = Query(
        default=None,
        description="JWT access token (alternative to Authorization header for static loaders)",
    ),
    authorization: str | None = Header(default=None),
    service: BIMHubService = Depends(_get_service),
) -> StreamingResponse | RedirectResponse:
    """Serve the COLLADA/DAE geometry file for the 3D viewer.

    Auth: accepts either an Authorization header OR a ``?token=...`` query
    parameter. The query param exists because Three.js ColladaLoader cannot
    set custom headers — without this fallback the viewer would 401.

    The geometry blob is resolved through :mod:`app.modules.bim_hub.file_storage`
    so both the local filesystem and S3 backends work transparently.  For S3
    we redirect to a short-lived presigned URL; for the local backend we
    stream the bytes directly through the route.
    """
    # Validate the token (header or query). ColladaLoader can't set headers,
    # so we accept ?token=<jwt> as an alternative auth mechanism.
    from app.config import get_settings
    from app.dependencies import decode_access_token

    auth_token: str | None = token
    if not auth_token and authorization and authorization.lower().startswith("bearer "):
        auth_token = authorization[7:]

    if not auth_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing token (use ?token=<jwt> or Authorization header)",
        )

    try:
        payload = decode_access_token(auth_token, get_settings())
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token",
        )

    # Check the token-bearer actually has bim.read before we load data.
    token_role = payload.get("role", "")
    token_perms: list[str] = payload.get("permissions", [])
    if token_role != "admin" and "bim.read" not in token_perms:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Missing permission: bim.read",
        )

    model = await service.get_model(model_id)
    if model is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Model not found",
        )

    # IDOR guard: verify the caller owns the project this model belongs to.
    token_user_id = str(payload.get("sub") or "")
    await _verify_project_access(service.session, model.project_id, token_user_id)

    project_id = str(model.project_id)

    # Resolve the geometry blob through the storage backend.
    found = await bim_file_storage.find_geometry_key(project_id, model_id)
    if found is not None:
        key, ext = found
        media_type = bim_file_storage.GEOMETRY_MEDIA_TYPES.get(
            ext, "application/octet-stream"
        )
        cache_headers = {
            # Allow long browser caching since DAE content is content-addressed
            "Cache-Control": "private, max-age=3600",
        }

        # Prefer a presigned URL so the browser fetches directly from the
        # bucket (S3).  Local backend returns None → fall back to streaming.
        presigned = bim_file_storage.presigned_geometry_url(key)
        if presigned:
            return RedirectResponse(url=presigned, status_code=307)

        stream = bim_file_storage.open_geometry_stream(key)
        return StreamingResponse(
            stream,
            media_type=media_type,
            headers={
                **cache_headers,
                "Content-Disposition": (
                    f'inline; filename="{model.name}{ext}"'
                ),
            },
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
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelListResponse:
    """List BIM models for a project."""
    await _verify_project_access(service.session, project_id, user_id or "")
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
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Create a new BIM model record."""
    await _verify_project_access(service.session, data.project_id, user_id)
    model = await service.create_model(data, user_id=user_id)
    return BIMModelResponse.model_validate(model)


@router.get("/{model_id}", response_model=BIMModelResponse)
async def get_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Get a single BIM model by ID."""
    model = await _verify_model_access(service, model_id, user_id or "")
    return BIMModelResponse.model_validate(model)


@router.patch("/{model_id}", response_model=BIMModelResponse)
async def update_model(
    model_id: uuid.UUID,
    data: BIMModelUpdate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.update")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelResponse:
    """Update a BIM model."""
    await _verify_model_access(service, model_id, user_id)
    model = await service.update_model(model_id, data)
    return BIMModelResponse.model_validate(model)


@router.delete("/{model_id}", status_code=204)
async def delete_model(
    model_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.delete")),
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BIM model and all its elements."""
    await _verify_model_access(service, model_id, user_id)
    await service.delete_model(model_id)


@router.post("/cleanup-stale")
async def cleanup_stale_processing(
    project_id: uuid.UUID = Query(...),
    max_age_hours: int = Query(default=1, ge=0),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.update")),
    service: BIMHubService = Depends(_get_service),
) -> dict[str, int]:
    """Remove models stuck in 'processing' with 0 elements older than max_age_hours."""
    await _verify_project_access(service.session, project_id, user_id or "")
    count = await service.cleanup_stale_processing(project_id, max_age_hours=max_age_hours)
    return {"deleted": count}


@router.post("/cleanup-orphans/")
async def cleanup_orphan_bim_files(
    _user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.delete")),
    service: BIMHubService = Depends(_get_service),
) -> dict[str, Any]:
    """Scan ``data/bim/`` and remove directories with no matching DB row.

    Admin-grade disk hygiene. Protects against orphaned RVT/IFC/COLLADA/Excel
    artefacts left behind by failed uploads, crashed conversions, or manual
    DB deletes that bypassed the service layer.
    """
    return await service.cleanup_orphan_bim_files()


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
    # Cap raised to 50000 because the BIM viewer needs all elements at once to
    # match COLLADA mesh nodes by stable_id. Real Revit models routinely have
    # 10–30k elements; pagination on the viewer side would mean missing
    # geometry references.
    limit: int = Query(default=50000, ge=1, le=50000),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """List elements for a BIM model (paginated, filterable).

    Each element in the response includes a ``boq_links`` array of
    ``BOQElementLinkBrief`` entries, a ``linked_documents`` array of
    ``DocumentLinkBrief`` entries, a ``linked_tasks`` array of ``TaskBrief``
    entries, and a ``linked_activities`` array of ``ActivityBrief`` entries
    so the viewer can render link badges without a second round trip.
    """
    from app.modules.bim_hub.schemas import (
        ActivityBrief,
        DocumentLinkBrief,
        ElementValidationSummary,
        TaskBrief,
    )

    await _verify_model_access(service, model_id, user_id or "")
    (
        items,
        total,
        boq_links_by_id,
        doc_links_by_id,
        task_links_by_id,
        activity_briefs_by_id,
        validation_summaries_by_id,
    ) = await service.list_elements_with_links(
        model_id,
        element_type=element_type,
        storey=storey,
        discipline=discipline,
        offset=offset,
        limit=limit,
    )

    # The service stashes a sentinel entry under ``_VALIDATION_REPORT_SENTINEL``
    # (UUID(int=0)) when a ``target_type='bim_model'`` report exists. We pop
    # it so it never reaches the per-element loop.
    from app.modules.bim_hub.service import _VALIDATION_REPORT_SENTINEL

    report_exists = _VALIDATION_REPORT_SENTINEL in validation_summaries_by_id
    validation_summaries_by_id.pop(_VALIDATION_REPORT_SENTINEL, None)

    responses: list[BIMElementResponse] = []
    for elem in items:
        boq_briefs = [
            BOQElementLinkBrief.model_validate(b)
            for b in boq_links_by_id.get(elem.id, [])
        ]
        doc_briefs = [
            DocumentLinkBrief.model_validate(b)
            for b in doc_links_by_id.get(elem.id, [])
        ]
        task_briefs = [
            TaskBrief.model_validate(b)
            for b in task_links_by_id.get(elem.id, [])
        ]
        activity_briefs = [
            ActivityBrief.model_validate(b)
            for b in activity_briefs_by_id.get(elem.id, [])
        ]
        raw_val = validation_summaries_by_id.get(elem.id, [])
        validation_summaries = [
            ElementValidationSummary.model_validate(v) for v in raw_val
        ]
        # Derive worst-severity status; 'unchecked' iff no report exists
        # at all (any element had at least one entry → report_exists).
        if not report_exists:
            val_status: str = "unchecked"
        elif any(v.severity == "error" for v in validation_summaries):
            val_status = "error"
        elif any(v.severity == "warning" for v in validation_summaries):
            val_status = "warning"
        else:
            val_status = "pass"
        resp = BIMElementResponse.model_validate(elem)
        resp.boq_links = boq_briefs
        resp.linked_documents = doc_briefs
        resp.linked_tasks = task_briefs
        resp.linked_activities = activity_briefs
        resp.validation_results = validation_summaries
        resp.validation_status = val_status  # type: ignore[assignment]
        responses.append(resp)

    return BIMElementListResponse(
        items=responses,
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
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BIMElementListResponse:
    """Bulk import elements for a model (replaces existing)."""
    await _verify_model_access(service, model_id, user_id)
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
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMElementResponse:
    """Get a single BIM element by ID."""
    element = await service.get_element(element_id)
    if element is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Element not found",
        )
    # Verify caller owns the project this element's model belongs to.
    await _verify_model_access(service, element.model_id, user_id or "")
    return BIMElementResponse.model_validate(element)


# ═══════════════════════════════════════════════════════════════════════════════
# BOQ Links
# ═══════════════════════════════════════════════════════════════════════════════


async def _verify_boq_position_access(
    service: "BIMHubService",
    position_id: uuid.UUID,
    user_id: str,
) -> None:
    """Resolve a BOQ position → its BOQ → project and verify the caller owns it.

    `Position` has no direct `project_id` column — the project lives on the
    parent `BOQ` row reached via `position.boq_id`.  We do a single-row
    SELECT joining position → boq so this stays one round-trip.
    """
    from app.modules.boq.models import BOQ as BOQModel, Position

    stmt = (
        select(BOQModel.project_id)
        .join(Position, Position.boq_id == BOQModel.id)
        .where(Position.id == position_id)
    )
    result = await service.session.execute(stmt)
    project_id = result.scalar_one_or_none()
    if project_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BOQ position not found",
        )
    await _verify_project_access(service.session, project_id, user_id)


@router.get("/links/", response_model=BOQElementLinkListResponse)
async def list_links(
    boq_position_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkListResponse:
    """List BIM element links for a BOQ position."""
    await _verify_boq_position_access(service, boq_position_id, user_id or "")
    items = await service.list_links_for_position(boq_position_id)
    return BOQElementLinkListResponse(
        items=[BOQElementLinkResponse.model_validate(lnk) for lnk in items],
        total=len(items),
    )


@router.post("/links/", response_model=BOQElementLinkResponse, status_code=201)
async def create_link(
    data: BOQElementLinkCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BOQElementLinkResponse:
    """Create a link between a BOQ position and a BIM element."""
    # Verify both sides: the BOQ position's project AND the BIM element's
    # model/project. Prevents cross-project link forgery.
    await _verify_boq_position_access(service, data.boq_position_id, user_id)
    element = await service.get_element(data.bim_element_id)
    if element is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BIM element not found",
        )
    await _verify_model_access(service, element.model_id, user_id)
    link = await service.create_link(data, user_id=user_id)
    return BOQElementLinkResponse.model_validate(link)


@router.delete("/links/{link_id}", status_code=204)
async def delete_link(
    link_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.delete")),
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BOQ-BIM link."""
    # Resolve the link → element → model → project and verify access.
    from app.modules.bim_hub.models import BOQElementLink

    link = await service.session.get(BOQElementLink, link_id)
    if link is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found",
        )
    element = await service.get_element(link.bim_element_id)
    if element is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Link not found",
        )
    await _verify_model_access(service, element.model_id, user_id)
    await service.delete_link(link_id)


# ═══════════════════════════════════════════════════════════════════════════════
# Quantity Maps
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/quantity-maps/", response_model=BIMQuantityMapListResponse)
async def list_quantity_maps(
    offset: int = Query(default=0, ge=0),
    limit: int = Query(default=100, ge=1, le=500),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapListResponse:
    """List quantity mapping rules (global + templates)."""
    items, total = await service.list_quantity_maps(offset=offset, limit=limit)
    return BIMQuantityMapListResponse(
        items=[BIMQuantityMapResponse.model_validate(m) for m in items],
        total=total,
    )


@router.post("/quantity-maps/", response_model=BIMQuantityMapResponse, status_code=201)
async def create_quantity_map(
    data: BIMQuantityMapCreate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Create a new quantity mapping rule."""
    # If the rule is scoped to a specific project, enforce ownership.
    if data.project_id is not None:
        await _verify_project_access(service.session, data.project_id, user_id)
    qmap = await service.create_quantity_map(data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.patch("/quantity-maps/{map_id}", response_model=BIMQuantityMapResponse)
async def update_quantity_map(
    map_id: uuid.UUID,
    data: BIMQuantityMapUpdate,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.update")),
    service: BIMHubService = Depends(_get_service),
) -> BIMQuantityMapResponse:
    """Update a quantity mapping rule."""
    # If the existing rule is project-scoped, verify access to that project.
    from app.modules.bim_hub.models import BIMQuantityMap

    existing = await service.session.get(BIMQuantityMap, map_id)
    if existing is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Quantity map not found",
        )
    if existing.project_id is not None:
        await _verify_project_access(service.session, existing.project_id, user_id)
    qmap = await service.update_quantity_map(map_id, data)
    return BIMQuantityMapResponse.model_validate(qmap)


@router.post("/quantity-maps/apply/", response_model=QuantityMapApplyResult)
async def apply_quantity_maps(
    data: QuantityMapApplyRequest,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> QuantityMapApplyResult:
    """Apply quantity mapping rules to all elements in a model."""
    await _verify_model_access(service, data.model_id, user_id)
    return await service.apply_quantity_maps(data)


# ═══════════════════════════════════════════════════════════════════════════════
# Diffs
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/models/{model_id}/diff/{old_id}", response_model=BIMModelDiffResponse, status_code=201)
async def compute_diff(
    model_id: uuid.UUID,
    old_id: uuid.UUID,
    user_id: CurrentUserId,
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Compute diff between two model versions."""
    # Both models must be readable by the caller.
    await _verify_model_access(service, model_id, user_id)
    await _verify_model_access(service, old_id, user_id)
    diff = await service.compute_diff(new_model_id=model_id, old_model_id=old_id)
    return BIMModelDiffResponse.model_validate(diff)


@router.get("/diffs/{diff_id}", response_model=BIMModelDiffResponse)
async def get_diff(
    diff_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> BIMModelDiffResponse:
    """Get a model diff by ID."""
    diff = await service.get_diff(diff_id)
    if diff is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Diff not found",
        )
    # Verify access via the new (or old) model's project.
    await _verify_model_access(service, diff.new_model_id, user_id or "")
    return BIMModelDiffResponse.model_validate(diff)


# ═══════════════════════════════════════════════════════════════════════════════
# Element Groups (saved selections)
# ═══════════════════════════════════════════════════════════════════════════════


async def _verify_group_access(
    service: "BIMHubService",
    group_id: uuid.UUID,
    user_id: str,
) -> Any:
    """Load a BIM element group and verify the caller owns its project.

    Returns the loaded group so the caller can reuse it. Raises 404 on both
    "not found" and "no access" to avoid UUID enumeration.
    """
    from app.modules.bim_hub.models import BIMElementGroup

    group = await service.session.get(BIMElementGroup, group_id)
    if group is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="BIM element group not found",
        )
    await _verify_project_access(service.session, group.project_id, user_id)
    return group


@router.get("/element-groups/", response_model=list[BIMElementGroupResponse])
async def list_element_groups(
    project_id: uuid.UUID = Query(...),
    model_id: uuid.UUID | None = Query(default=None),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.read")),
    service: BIMHubService = Depends(_get_service),
) -> list[BIMElementGroupResponse]:
    """List BIM element groups for a project, optionally scoped to one model."""
    await _verify_project_access(service.session, project_id, user_id or "")
    return await service.list_element_groups(project_id, model_id=model_id)


@router.post(
    "/element-groups/",
    response_model=BIMElementGroupResponse,
    status_code=201,
)
async def create_element_group(
    data: BIMElementGroupCreate,
    project_id: uuid.UUID = Query(...),
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.create")),
    service: BIMHubService = Depends(_get_service),
) -> BIMElementGroupResponse:
    """Create a new BIM element group (saved selection) in a project."""
    await _verify_project_access(service.session, project_id, user_id or "")
    # If the group is scoped to a specific model, verify the model belongs
    # to the same project the caller is creating the group in.
    if data.model_id is not None:
        model = await _verify_model_access(service, data.model_id, user_id or "")
        if model.project_id != project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model_id does not belong to the supplied project_id",
            )
    user_uuid: uuid.UUID | None = None
    if user_id:
        try:
            user_uuid = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            user_uuid = None
    return await service.create_element_group(project_id, data, user_uuid)


@router.patch(
    "/element-groups/{group_id}",
    response_model=BIMElementGroupResponse,
)
async def update_element_group(
    group_id: uuid.UUID,
    data: BIMElementGroupUpdate,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.update")),
    service: BIMHubService = Depends(_get_service),
) -> BIMElementGroupResponse:
    """Partially update a BIM element group."""
    group = await _verify_group_access(service, group_id, user_id or "")
    # If the caller is moving the group to a different model, validate that
    # model belongs to the same project.
    if data.model_id is not None:
        model = await _verify_model_access(service, data.model_id, user_id or "")
        if model.project_id != group.project_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="model_id does not belong to the group's project",
            )
    return await service.update_element_group(group_id, data)


@router.delete("/element-groups/{group_id}", status_code=204)
async def delete_element_group(
    group_id: uuid.UUID,
    user_id: CurrentUserId = None,  # type: ignore[assignment]
    _perm: None = Depends(RequirePermission("bim.delete")),
    service: BIMHubService = Depends(_get_service),
) -> None:
    """Delete a BIM element group."""
    await _verify_group_access(service, group_id, user_id or "")
    await service.delete_element_group(group_id)
