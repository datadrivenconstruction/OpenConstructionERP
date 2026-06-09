# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub Pydantic schemas - request / response models."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Regex patterns shared across create + update + response shapes.
_SOURCE_KIND_PATTERN = r"^(bim_model|federation|development|upload|point_cloud|photogrammetry)$"
_TILESET_STATUS_PATTERN = r"^(draft|generating|ready|failed|obsolete)$"
_TILE_FORMAT_PATTERN = r"^(b3dm|i3dm|pnts|cmpt|copc)$"
_JOB_STATE_PATTERN = r"^(queued|running|completed|failed|cancelled)$"
_IMAGERY_PROVIDER_PATTERN = r"^(osm|bing|wms|wmts|custom)$"
_TERRAIN_PROVIDER_PATTERN = r"^(cesium_world|quantized_mesh|ellipsoid)$"
_OVERLAY_KIND_PATTERN = (
    r"^(boundary|survey|contour|drone_photo|site_plan|easement|"
    r"flood_zone|clash_marker|incident|field_report|risk_zone)$"
)
_RASTER_OVERLAY_KIND_PATTERN = r"^(pdf|dwg|image)$"
_REGION_CODE_PATTERN = r"^[A-Z]{2}(-[A-Z0-9]{1,3})?$"


# Common WGS84 latitude / longitude bounds.
_LAT_BOUND = (Decimal("-90"), Decimal("90"))
_LON_BOUND = (Decimal("-180"), Decimal("180"))


def _check_lat(v: Decimal) -> Decimal:
    lo, hi = _LAT_BOUND
    if not (lo <= v <= hi):
        raise ValueError(f"latitude must be in [{lo}, {hi}]")
    return v


def _check_lon(v: Decimal) -> Decimal:
    lo, hi = _LON_BOUND
    if not (lo <= v <= hi):
        raise ValueError(f"longitude must be in [{lo}, {hi}]")
    return v


# ── GeoAnchor ────────────────────────────────────────────────────────────


class GeoAnchorCreate(BaseModel):
    """Create the (unique) anchor for a project."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    lat: Decimal = Field(default=Decimal("0"))
    lon: Decimal = Field(default=Decimal("0"))
    alt: Decimal = Field(default=Decimal("0"))
    epsg_code: int = Field(default=4326, gt=0, le=999999)
    region_code: str | None = Field(default=None, pattern=_REGION_CODE_PATTERN)
    address: str | None = Field(default=None, max_length=500)
    # Horizontal accuracy in metres. Hard upper bound at 10 km - anything
    # coarser than that is "country-level" precision and should be
    # represented via the precision metadata on the GeoAnchor, not a
    # numeric uncertainty disc on the map (which Cesium would draw as
    # the size of a small country).
    accuracy_m: Decimal | None = Field(default=None, ge=0, le=10_000)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _v_lat = field_validator("lat")(lambda cls, v: _check_lat(v))  # type: ignore[arg-type, misc]
    _v_lon = field_validator("lon")(lambda cls, v: _check_lon(v))  # type: ignore[arg-type, misc]


class GeoAnchorUpdate(BaseModel):
    """Partial update of an anchor."""

    model_config = ConfigDict(str_strip_whitespace=True)

    lat: Decimal | None = None
    lon: Decimal | None = None
    alt: Decimal | None = None
    epsg_code: int | None = Field(default=None, gt=0, le=999999)
    region_code: str | None = Field(default=None, pattern=_REGION_CODE_PATTERN)
    address: str | None = Field(default=None, max_length=500)
    # Horizontal accuracy in metres. Hard upper bound at 10 km - anything
    # coarser than that is "country-level" precision and should be
    # represented via the precision metadata on the GeoAnchor, not a
    # numeric uncertainty disc on the map (which Cesium would draw as
    # the size of a small country).
    accuracy_m: Decimal | None = Field(default=None, ge=0, le=10_000)
    metadata: dict[str, Any] | None = None

    @field_validator("lat")
    @classmethod
    def _v_lat(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _check_lat(v)

    @field_validator("lon")
    @classmethod
    def _v_lon(cls, v: Decimal | None) -> Decimal | None:
        return None if v is None else _check_lon(v)


class GeoAnchorResponse(BaseModel):
    """Anchor returned from the API.

    ``id`` is ``None`` for a *transient* anchor synthesised from a
    project's address coordinates (a project that pins on the global map
    via ``address.lat``/``lng`` but has no persisted ``GeoAnchor`` row).
    The ``metadata.persisted`` flag (``False`` on transient anchors) is
    the explicit signal the frontend checks before offering "Save this
    location"; every real, DB-backed anchor carries a UUID ``id``.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID | None = None
    project_id: UUID
    lat: Decimal
    lon: Decimal
    alt: Decimal
    epsg_code: int
    region_code: str | None = None
    address: str | None = None
    accuracy_m: Decimal | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Tileset ──────────────────────────────────────────────────────────────


class TilesetCreate(BaseModel):
    """Create a Tileset record (usually populated by the job, not the
    user - but exposing it is handy for tests and re-registrations)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    source_kind: str = Field(default="bim_model", pattern=_SOURCE_KIND_PATTERN)
    source_id: UUID
    name: str = Field(default="", max_length=255)
    bucket: str = Field(default="", max_length=100)
    prefix: str = Field(default="", max_length=500)
    tileset_json_uri: str | None = Field(default=None, max_length=2000)
    bounding_volume: dict[str, Any] | None = None
    geometric_error: Decimal = Field(default=Decimal("0"), ge=0)
    tile_format: str = Field(default="b3dm", pattern=_TILE_FORMAT_PATTERN)
    tile_count: int = Field(default=0, ge=0)
    total_bytes: int = Field(default=0, ge=0)
    status: str = Field(default="draft", pattern=_TILESET_STATUS_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TilesetUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    tileset_json_uri: str | None = Field(default=None, max_length=2000)
    bounding_volume: dict[str, Any] | None = None
    geometric_error: Decimal | None = Field(default=None, ge=0)
    status: str | None = Field(default=None, pattern=_TILESET_STATUS_PATTERN)
    metadata: dict[str, Any] | None = None


class TilesetResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    source_kind: str
    source_id: UUID
    name: str = ""
    bucket: str = ""
    prefix: str = ""
    tileset_json_uri: str | None = None
    bounding_volume: dict[str, Any] | None = None
    geometric_error: Decimal = Decimal("0")
    tile_format: str = "b3dm"
    tile_count: int = 0
    total_bytes: int = 0
    status: str = "draft"
    generated_at: datetime | None = None
    generation_job_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class TileGenerateRequest(BaseModel):
    """Enqueue a tile-generation job."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    source_kind: str = Field(default="bim_model", pattern=_SOURCE_KIND_PATTERN)
    source_id: UUID
    # When True we re-tile even if a ``ready`` Tileset already exists
    # for the same (source_kind, source_id) pair.
    force: bool = False


class CanonicalToTilesetRequest(BaseModel):
    """Optional body for the canonical -> tileset packaging endpoint."""

    model_config = ConfigDict(str_strip_whitespace=True)

    heading_deg: Decimal = Field(default=Decimal("0"), ge=-360, le=720)
    name: str | None = Field(default=None, max_length=255)
    tags: list[str] = Field(default_factory=list)


# ── ImageryLayer ─────────────────────────────────────────────────────────


class ImageryLayerCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=120)
    provider: str = Field(default="osm", pattern=_IMAGERY_PROVIDER_PATTERN)
    url_template: str = Field(default="", max_length=2000)
    attribution: str = Field(default="", max_length=500)
    requires_api_key: bool = False
    default_for_project: bool = False
    is_visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ImageryLayerUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=120)
    provider: str | None = Field(default=None, pattern=_IMAGERY_PROVIDER_PATTERN)
    url_template: str | None = Field(default=None, max_length=2000)
    attribution: str | None = Field(default=None, max_length=500)
    requires_api_key: bool | None = None
    default_for_project: bool | None = None
    is_visible: bool | None = None
    metadata: dict[str, Any] | None = None


class ImageryLayerResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str = ""
    provider: str = "osm"
    url_template: str = ""
    attribution: str = ""
    requires_api_key: bool = False
    default_for_project: bool = False
    is_visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── TerrainSource ────────────────────────────────────────────────────────


class TerrainSourceCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(..., min_length=1, max_length=120)
    provider: str = Field(default="ellipsoid", pattern=_TERRAIN_PROVIDER_PATTERN)
    endpoint: str | None = Field(default=None, max_length=2000)
    ion_token: str | None = Field(default=None, max_length=500)
    is_default: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TerrainSourceUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    provider: str | None = Field(default=None, pattern=_TERRAIN_PROVIDER_PATTERN)
    endpoint: str | None = Field(default=None, max_length=2000)
    ion_token: str | None = Field(default=None, max_length=500)
    is_default: bool | None = None
    metadata: dict[str, Any] | None = None


class TerrainSourceResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    name: str
    provider: str = "ellipsoid"
    endpoint: str | None = None
    is_default: bool = False
    # ``ion_token`` is intentionally NEVER returned. The frontend uses
    # a separate short-lived token endpoint when ion is enabled.
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── Viewpoint ────────────────────────────────────────────────────────────


class ViewpointCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(..., min_length=1, max_length=120)
    description: str | None = None
    camera_lat: Decimal = Field(default=Decimal("0"))
    camera_lon: Decimal = Field(default=Decimal("0"))
    camera_alt: Decimal = Field(default=Decimal("0"))
    heading: Decimal = Field(default=Decimal("0"), ge=-360, le=720)
    pitch: Decimal = Field(default=Decimal("0"), ge=-180, le=180)
    roll: Decimal = Field(default=Decimal("0"), ge=-180, le=180)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _v_lat = field_validator("camera_lat")(lambda cls, v: _check_lat(v))  # type: ignore[arg-type, misc]
    _v_lon = field_validator("camera_lon")(lambda cls, v: _check_lon(v))  # type: ignore[arg-type, misc]


class ViewpointUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None
    camera_lat: Decimal | None = None
    camera_lon: Decimal | None = None
    camera_alt: Decimal | None = None
    heading: Decimal | None = Field(default=None, ge=-360, le=720)
    pitch: Decimal | None = Field(default=None, ge=-180, le=180)
    roll: Decimal | None = Field(default=None, ge=-180, le=180)
    metadata: dict[str, Any] | None = None


class ViewpointResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str
    description: str | None = None
    camera_lat: Decimal
    camera_lon: Decimal
    camera_alt: Decimal
    heading: Decimal
    pitch: Decimal
    roll: Decimal
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── GeoOverlay ───────────────────────────────────────────────────────────


class GeoOverlayCreate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    kind: str = Field(default="boundary", pattern=_OVERLAY_KIND_PATTERN)
    geojson: dict[str, Any] = Field(default_factory=dict)
    source_file: str | None = Field(default=None, max_length=500)
    style: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class GeoOverlayUpdate(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    kind: str | None = Field(default=None, pattern=_OVERLAY_KIND_PATTERN)
    geojson: dict[str, Any] | None = None
    style: dict[str, Any] | None = None
    is_visible: bool | None = None
    metadata: dict[str, Any] | None = None


class GeoOverlayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str = ""
    kind: str = "boundary"
    geojson: dict[str, Any] = Field(default_factory=dict)
    source_file: str | None = None
    style: dict[str, Any] = Field(default_factory=dict)
    is_visible: bool = True
    source_event_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class GeoJSONImportRequest(BaseModel):
    """Import a GeoJSON FeatureCollection as a new GeoOverlay."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    kind: str = Field(default="boundary", pattern=_OVERLAY_KIND_PATTERN)
    geojson: dict[str, Any]
    style: dict[str, Any] = Field(default_factory=dict)


class KMLImportRequest(BaseModel):
    """Import KML as a new GeoOverlay (we parse to GeoJSON on the way in)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    kind: str = Field(default="boundary", pattern=_OVERLAY_KIND_PATTERN)
    kml: str = Field(..., min_length=10, max_length=10_000_000)
    style: dict[str, Any] = Field(default_factory=dict)


# ── GeoRasterOverlay (PDF / DWG / image pinned to globe surface) ────────


def _check_corners(v: list[Any]) -> list[Any]:
    """Validate a 4-point corners array of ``[lon, lat]`` pairs.

    The frontend always sends ``[NW, NE, SE, SW]``. We tolerate an empty
    list on create (the service falls back to the project anchor bbox)
    but reject any partially-formed shape.
    """
    if not v:
        return v
    if len(v) != 4:
        raise ValueError("corners_geojson must contain exactly 4 points")
    for point in v:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("each corner must be a 2-element [lon, lat] array")
        lon, lat = point
        try:
            lon_d = Decimal(str(lon))
            lat_d = Decimal(str(lat))
        except Exception as exc:  # noqa: BLE001
            raise ValueError("corner coords must be numeric") from exc
        if not (Decimal("-180") <= lon_d <= Decimal("180")):
            raise ValueError("corner longitude out of range")
        if not (Decimal("-90") <= lat_d <= Decimal("90")):
            raise ValueError("corner latitude out of range")
    return v


def _check_crop_polygon(v: dict[str, Any] | None) -> dict[str, Any] | None:
    """Light GeoJSON Polygon shape check - defers full validation to client."""
    if v is None:
        return None
    if not isinstance(v, dict):
        raise ValueError("crop_polygon_geojson must be a GeoJSON object")
    if v.get("type") != "Polygon":
        raise ValueError("crop_polygon_geojson must be type Polygon")
    coords = v.get("coordinates")
    if not isinstance(coords, list) or not coords:
        raise ValueError("crop_polygon_geojson.coordinates must be non-empty")
    ring = coords[0]
    if not isinstance(ring, list) or len(ring) < 3:
        raise ValueError("crop_polygon_geojson outer ring needs >= 3 points")
    for point in ring:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ValueError("crop polygon points must be [lon, lat] pairs")
    return v


class GeoRasterOverlayCreate(BaseModel):
    """Create a raster overlay record (usually via upload endpoint)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(default="", max_length=255)
    source_kind: str = Field(
        default="image",
        pattern=_RASTER_OVERLAY_KIND_PATTERN,
    )
    source_blob_url: str | None = Field(default=None, max_length=500)
    source_page: int = Field(default=1, ge=1, le=10_000)
    raster_blob_url: str | None = Field(default=None, max_length=500)
    raster_width_px: int = Field(default=0, ge=0, le=200_000)
    raster_height_px: int = Field(default=0, ge=0, le=200_000)
    corners_geojson: list[Any] = Field(default_factory=list)
    rotation_deg: Decimal = Field(default=Decimal("0"), ge=-720, le=720)
    opacity: Decimal = Field(default=Decimal("0.7"), ge=0, le=1)
    crop_polygon_geojson: dict[str, Any] | None = None
    z_order: int = Field(default=0, ge=-1000, le=1000)
    visible: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)

    _v_corners = field_validator("corners_geojson")(  # type: ignore[arg-type, misc]
        lambda cls, v: _check_corners(v)
    )
    _v_crop = field_validator("crop_polygon_geojson")(  # type: ignore[arg-type, misc]
        lambda cls, v: _check_crop_polygon(v)
    )


class GeoRasterOverlayUpdate(BaseModel):
    """Partial update - corners, opacity, crop polygon, visibility."""

    model_config = ConfigDict(str_strip_whitespace=True)

    name: str | None = Field(default=None, max_length=255)
    corners_geojson: list[Any] | None = None
    rotation_deg: Decimal | None = Field(default=None, ge=-720, le=720)
    opacity: Decimal | None = Field(default=None, ge=0, le=1)
    crop_polygon_geojson: dict[str, Any] | None = None
    z_order: int | None = Field(default=None, ge=-1000, le=1000)
    visible: bool | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("corners_geojson")
    @classmethod
    def _v_corners(cls, v: list[Any] | None) -> list[Any] | None:
        return None if v is None else _check_corners(v)

    @field_validator("crop_polygon_geojson")
    @classmethod
    def _v_crop(
        cls,
        v: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        return _check_crop_polygon(v)


class GeoRasterOverlayResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    name: str = ""
    source_kind: str = "image"
    source_blob_url: str | None = None
    source_page: int = 1
    raster_blob_url: str | None = None
    raster_width_px: int = 0
    raster_height_px: int = 0
    corners_geojson: list[Any] = Field(default_factory=list)
    rotation_deg: Decimal = Decimal("0")
    opacity: Decimal = Decimal("0.7")
    crop_polygon_geojson: dict[str, Any] | None = None
    z_order: int = 0
    visible: bool = True
    created_by: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


class RasterOverlayUploadResponse(BaseModel):
    """Lightweight response for the PDF / image upload endpoints."""

    model_config = ConfigDict()

    overlay: GeoRasterOverlayResponse
    page_count: int = 1


# ── TileGenerationJob ────────────────────────────────────────────────────


class TileJobResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    tileset_id: UUID | None = None
    source_kind: str
    source_id: UUID
    requested_by: UUID | None = None
    state: str = "queued"
    progress_pct: int = 0
    started_at: datetime | None = None
    completed_at: datetime | None = None
    error_message: str | None = None
    output_uri: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict, alias="metadata_")
    created_at: datetime
    updated_at: datetime


# ── MapConfig one-shot bundle ────────────────────────────────────────────


class MapConfigResponse(BaseModel):
    """Single round-trip bundle for the Cesium viewer boot path."""

    model_config = ConfigDict(populate_by_name=True)

    project_id: UUID
    anchor: GeoAnchorResponse | None = None
    imagery_layers: list[ImageryLayerResponse] = Field(default_factory=list)
    terrain_source: TerrainSourceResponse | None = None
    tilesets: list[TilesetResponse] = Field(default_factory=list)
    overlays: list[GeoOverlayResponse] = Field(default_factory=list)
    viewpoints: list[ViewpointResponse] = Field(default_factory=list)
    active_jobs: list[TileJobResponse] = Field(default_factory=list)


# ── Cross-module geo pins (HSE / Punchlist / Daily Diary) ───────────────


class HSEPinResponse(BaseModel):
    """A single HSE incident pinned on the project map."""

    model_config = ConfigDict(from_attributes=True)

    incident_id: UUID
    incident_number: str
    title: str | None = None
    incident_type: str
    severity: str
    status: str
    lat: float
    lon: float


class PunchlistPinResponse(BaseModel):
    """A single punch list item pinned on the project map."""

    model_config = ConfigDict(from_attributes=True)

    item_id: UUID
    title: str
    priority: str
    status: str
    category: str | None = None
    lat: float
    lon: float


class AnchoredProjectResponse(BaseModel):
    """A single locatable project for the Global map's project-pin layer.

    Returned by ``GET /api/v1/geo-hub/projects`` - projects the caller can
    access that have a location, either a registered ``GeoAnchor`` OR
    ``lat``/``lng`` coordinates on their address. Used by the global Geo
    Hub to drop a pin per project on the earth-scale view (no tilesets at
    this LOD).

    ``anchor_id`` is ``None`` for projects pinned purely from their address
    coordinates (no GeoAnchor row yet).

    ``project_type`` and ``status`` let the viewer pick the right pin
    icon (residential / commercial / civil) and tint by lifecycle
    (active / planning / completed).
    """

    model_config = ConfigDict(from_attributes=True)

    project_id: UUID
    project_name: str
    anchor_id: UUID | None = None
    lat: Decimal
    lon: Decimal
    alt: Decimal
    region_code: str | None = None
    address: str | None = None
    project_type: str | None = None
    status: str | None = None
    # Free-text project address as captured on the project (NOT the
    # geocoded display name on the anchor) - the frontend compares this
    # against ``address`` to surface a drift indicator when the user
    # edited the address after the first geocode.
    project_address_text: str | None = None


# ── Auto-anchor (from project address) ──────────────────────────────────


class AnchorFromAddressRequest(BaseModel):
    """Body for ``POST /api/v1/geo-hub/anchors/from-address/``."""

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID


class AnchorFromAddressResponse(BaseModel):
    """Return shape for the auto-anchor endpoint.

    Carries the persisted ``GeoAnchor`` plus the resolved precision +
    source so the UI can render a confidence chip without an extra GET.
    """

    model_config = ConfigDict()

    anchor: GeoAnchorResponse
    precision: str = Field(default="address")
    source: str = Field(default="nominatim")
    display_name: str | None = None


class BulkAnchorOutcome(BaseModel):
    """Per-project status row inside ``BulkAnchorFromAddressResponse``."""

    model_config = ConfigDict()

    project_id: UUID
    project_name: str | None = None
    status: str  # "ok" | "skipped" | "failed"
    reason: str | None = None
    anchor_id: UUID | None = None
    precision: str | None = None


class BulkAnchorFromAddressResponse(BaseModel):
    """Summary of the bulk auto-anchor sweep."""

    model_config = ConfigDict()

    succeeded: int = 0
    skipped: int = 0
    failed: int = 0
    results: list[BulkAnchorOutcome] = Field(default_factory=list)


class GeocodeSuggestionResponse(BaseModel):
    """A single Nominatim search hit for the autocomplete dropdown.

    Returned by ``GET /api/v1/geo-hub/geocode/suggest`` - projected from
    the upstream Nominatim payload so the frontend can render a country
    flag + display name + lat/lon preview without parsing the raw OSM
    response.
    """

    model_config = ConfigDict()

    display_name: str
    lat: Decimal
    lon: Decimal
    country_code: str | None = None
    addresstype: str | None = None
    osm_type: str | None = None
    bbox: list[Decimal] | None = None  # [min_lat, min_lon, max_lat, max_lon]
    # Structured address parts (street / city / country / postcode etc.)
    # so the project form can autofill its dedicated inputs without
    # re-parsing ``display_name``.
    address_parts: dict[str, str] | None = None


class GeocodeSuggestResponse(BaseModel):
    """Response wrapper for the autocomplete suggest endpoint."""

    model_config = ConfigDict()

    query: str
    suggestions: list[GeocodeSuggestionResponse] = Field(default_factory=list)
    # ``true`` when the geocoder is disabled via env (operator opt-out
    # or sanctioned region) - the frontend uses this to switch from
    # "no matches" to "service disabled" copy.
    geocoder_disabled: bool = False


class GeocodeCacheStatsResponse(BaseModel):
    """Aggregate counters for the Geo Hub admin cache panel."""

    model_config = ConfigDict()

    total: int = 0
    fresh: int = 0
    stale: int = 0
    hit_sum: int = 0
    ttl_days: int = 30
    oldest_cached_at: datetime | None = None
    newest_cached_at: datetime | None = None


class GeocodeCachePurgeResponse(BaseModel):
    """Result of a manual cache invalidation sweep."""

    model_config = ConfigDict()

    deleted: int = 0
    older_than_days: int | None = None


class DiaryPhotoPinResponse(BaseModel):
    """A single geo-tagged Daily Diary photo on the project map."""

    model_config = ConfigDict(from_attributes=True)

    photo_id: UUID
    diary_id: UUID | None = None
    taken_at: datetime
    thumbnail_url: str | None = None
    file_url: str
    is_360: bool = False
    is_drone: bool = False
    lat: float
    lon: float


# ── Map layer summary (project-scoped legend) ───────────────────────────


class MapLayerSummary(BaseModel):
    """Counts + breakdown for one toggleable map layer.

    Powers the project-map layer legend: how many features the layer
    carries and, where it helps the user triage, a small breakdown
    keyed by a domain dimension (HSE severity, punch priority, tileset
    status). ``total`` of 0 lets the frontend render a muted "nothing
    pinned yet" row with a deep-link to the source module instead of an
    invisible empty layer.
    """

    model_config = ConfigDict()

    total: int = 0
    # Open-ended bucket map (e.g. ``{"high": 3, "low": 1}``). Empty when a
    # breakdown does not apply to the layer (diary photos, viewpoints).
    breakdown: dict[str, int] = Field(default_factory=dict)


class MapSummaryResponse(BaseModel):
    """Aggregate of everything visible on a project's map.

    One round-trip the frontend uses to render the layer legend (counts
    per layer + status breakdowns) and to decide which layers are worth
    showing a toggle for. Computed server-side so the legend stays
    correct even when individual pin layers are lazily fetched, and so a
    user with hundreds of pins isn't forced to download every row just to
    learn the count.
    """

    model_config = ConfigDict()

    project_id: UUID
    has_anchor: bool = False
    # ``True`` when the anchor is synthesised from address coords (not a
    # persisted GeoAnchor) so the legend can nudge the user to confirm it.
    anchor_is_derived: bool = False
    tilesets: MapLayerSummary = Field(default_factory=MapLayerSummary)
    overlays: MapLayerSummary = Field(default_factory=MapLayerSummary)
    raster_overlays: MapLayerSummary = Field(default_factory=MapLayerSummary)
    viewpoints: MapLayerSummary = Field(default_factory=MapLayerSummary)
    hse_pins: MapLayerSummary = Field(default_factory=MapLayerSummary)
    punchlist_pins: MapLayerSummary = Field(default_factory=MapLayerSummary)
    diary_pins: MapLayerSummary = Field(default_factory=MapLayerSummary)
    active_jobs: int = 0
    # Total feature count across every layer - the legend's headline number.
    total_features: int = 0


__all__ = [
    "AnchorFromAddressRequest",
    "AnchorFromAddressResponse",
    "AnchoredProjectResponse",
    "BulkAnchorFromAddressResponse",
    "BulkAnchorOutcome",
    "CanonicalToTilesetRequest",
    "DiaryPhotoPinResponse",
    "GeoAnchorCreate",
    "GeoAnchorResponse",
    "GeoAnchorUpdate",
    "GeoJSONImportRequest",
    "GeoOverlayCreate",
    "GeoOverlayResponse",
    "GeoOverlayUpdate",
    "GeoRasterOverlayCreate",
    "GeoRasterOverlayResponse",
    "GeoRasterOverlayUpdate",
    "GeocodeCachePurgeResponse",
    "GeocodeCacheStatsResponse",
    "GeocodeSuggestResponse",
    "GeocodeSuggestionResponse",
    "RasterOverlayUploadResponse",
    "HSEPinResponse",
    "ImageryLayerCreate",
    "ImageryLayerResponse",
    "ImageryLayerUpdate",
    "KMLImportRequest",
    "MapConfigResponse",
    "MapLayerSummary",
    "MapSummaryResponse",
    "PunchlistPinResponse",
    "TerrainSourceCreate",
    "TerrainSourceResponse",
    "TerrainSourceUpdate",
    "TileGenerateRequest",
    "TileJobResponse",
    "TilesetCreate",
    "TilesetResponse",
    "TilesetUpdate",
    "ViewpointCreate",
    "ViewpointResponse",
    "ViewpointUpdate",
]
