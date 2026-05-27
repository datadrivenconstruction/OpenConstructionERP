# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Geo Hub ORM models.

Tables (all prefixed ``oe_geo_hub_``):

    anchor               — WGS84 anchor (lat / lon / alt / EPSG) for a project
    tileset              — 3D Tiles 1.1 tileset metadata + storage uri
    imagery_layer        — base / overlay imagery provider per project
    terrain_source       — global terrain catalogue (ellipsoid / CWT / quantized mesh)
    viewpoint            — saved camera pose per project
    overlay              — GeoJSON / KML feature collections (boundaries, drone scans, ...)
    tile_job             — async tile-generation job with FSM state

External references kept as plain UUID columns (no FK):
    source_id            — points at bim_hub.BIMModel.id, federations,
                           property_dev.Development.id, an upload key, etc.
                           polymorphic on ``source_kind``
    created_by           — oe_users_user.id

Multi-tenant model
------------------

property_dev / bim_hub do single-tenant per project. We follow that
convention: ``project_id`` is the IDOR boundary and the service layer
resolves project -> owner_id and 404s on cross-tenant access.

Money / quantities
------------------

No money in this module. All quantities (lat / lon / metres / degrees)
use ``Decimal`` for stable serialisation across SQLite + Postgres.
"""

from __future__ import annotations

import uuid
from datetime import datetime  # noqa: F401 — used in Mapped[datetime] annotations
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# ── GeoAnchor ────────────────────────────────────────────────────────────


class GeoAnchor(Base):
    """WGS84 anchor for a project — exactly one per project."""

    __tablename__ = "oe_geo_hub_anchor"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_geo_hub_anchor_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # WGS84 latitude / longitude in decimal degrees. ``Decimal(10, 7)``
    # holds 1.1 cm precision at the equator — more than enough for
    # construction-scale anchoring without burning storage on float64
    # rounding bugs.
    lat: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
    )
    lon: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
    )
    # Ellipsoidal height in metres. Negative values allowed (Dead Sea
    # construction is a real customer scenario).
    alt: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
        default=Decimal("0"),
    )
    # EPSG code of the *source* coordinate reference system. 4326 =
    # WGS84 geographic. 3857 = Web Mercator. 25832 = ETRS89 / UTM 32N
    # (DACH default). 32633 = WGS84 / UTM 33N. Anything else is fine
    # too — we only validate the integer-positive range; the actual
    # transform is done at view time via pyproj if installed.
    epsg_code: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=4326,
    )
    # ISO 3166-2 region code, e.g. ``DE-BE`` (Berlin), ``GB-LND``
    # (London), ``US-CA``. Optional — drives imagery defaults.
    region_code: Mapped[str | None] = mapped_column(String(8), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Horizontal accuracy in metres, when surveyed. ``None`` for "this
    # anchor was geocoded from a street address". The frontend may
    # display a small uncertainty disc on the map for non-null values.
    accuracy_m: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 2),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover — display only
        return f"<GeoAnchor project={self.project_id} ({self.lat},{self.lon})>"


# ── Tileset ──────────────────────────────────────────────────────────────


class Tileset(Base):
    """3D Tiles 1.1 tileset produced from a polymorphic source.

    ``source_kind`` selects which row ``source_id`` references:

    ====================  ====================================================
    source_kind           ``source_id`` references
    ====================  ====================================================
    ``bim_model``         oe_bim_model.id
    ``federation``        oe_bim_federation.id
    ``development``       oe_property_dev_development.id
    ``upload``            opaque upload key — caller-side ownership
    ``point_cloud``       opaque upload key
    ``photogrammetry``    opaque upload key
    ====================  ====================================================

    We deliberately do NOT add foreign keys here: that would force the
    geo_hub schema to know every other module's table name (poor
    layering) and prevent decoupled tile generation from offline files
    that haven't yet been registered in any module. Cross-row integrity
    is enforced at the service layer.
    """

    __tablename__ = "oe_geo_hub_tileset"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="bim_model",
        index=True,
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    bucket: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
        default="",
    )
    prefix: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    tileset_json_uri: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    # Cesium-native bounding-volume shape. One of:
    #     {"box":   [cx, cy, cz, dx, 0, 0, 0, dy, 0, 0, 0, dz]}
    #     {"region": [west, south, east, north, min_h, max_h]}
    #     {"sphere": [cx, cy, cz, r]}
    bounding_volume: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    geometric_error: Mapped[Decimal] = mapped_column(
        Numeric(10, 2),
        nullable=False,
        default=Decimal("0"),
    )
    tile_format: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="b3dm",
    )
    tile_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    total_bytes: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="draft",
        index=True,
    )
    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<Tileset {self.id} ({self.source_kind} / {self.status})>"


# ── ImageryLayer ─────────────────────────────────────────────────────────


class ImageryLayer(Base):
    """Per-project base / overlay imagery (OSM, Bing, WMS, ...)."""

    __tablename__ = "oe_geo_hub_imagery_layer"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    provider: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="osm",
    )
    url_template: Mapped[str] = mapped_column(
        String(2000),
        nullable=False,
        default="",
    )
    attribution: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
    )
    requires_api_key: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
    )
    default_for_project: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── TerrainSource ────────────────────────────────────────────────────────


class TerrainSource(Base):
    """System-wide terrain catalogue (no per-project rows).

    The default terrain is the WGS84 ellipsoid — free, no third-party
    keys, ships out of the box. Cesium World Terrain (CWT) is offered
    as an opt-in source: the admin sets the ion access token here and
    the frontend stops sending it back to the server (browser talks
    directly to Cesium ion). Quantized mesh terrain hosted on a custom
    endpoint is the third option.
    """

    __tablename__ = "oe_geo_hub_terrain_source"
    __table_args__ = (UniqueConstraint("name", name="uq_oe_geo_hub_terrain_source_name"),)

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="ellipsoid",
    )
    endpoint: Mapped[str | None] = mapped_column(
        String(2000),
        nullable=True,
    )
    # ion access token, when ``provider == "cesium_world"``. Stored
    # encrypted-at-rest by the storage backend, never returned in API
    # responses — the frontend constructs the Cesium ion URL itself
    # using a short-lived token endpoint (out of scope of v1).
    ion_token: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    is_default: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── Viewpoint ────────────────────────────────────────────────────────────


class GeoViewpoint(Base):
    """Saved camera pose per project.

    Named ``GeoViewpoint`` (not ``Viewpoint``) to avoid the registry
    clash with :class:`app.modules.collaboration.models.Viewpoint` —
    SQLAlchemy unifies all DeclarativeBase descendants into one
    registry so unqualified class names must be unique across modules.
    """

    __tablename__ = "oe_geo_hub_viewpoint"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    camera_lat: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
    )
    camera_lon: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
    )
    camera_alt: Mapped[Decimal] = mapped_column(
        Numeric(8, 2),
        nullable=False,
        default=Decimal("0"),
    )
    heading: Mapped[Decimal] = mapped_column(
        Numeric(7, 3),
        nullable=False,
        default=Decimal("0"),
    )
    pitch: Mapped[Decimal] = mapped_column(
        Numeric(7, 3),
        nullable=False,
        default=Decimal("0"),
    )
    roll: Mapped[Decimal] = mapped_column(
        Numeric(7, 3),
        nullable=False,
        default=Decimal("0"),
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── GeoOverlay ───────────────────────────────────────────────────────────


class GeoOverlay(Base):
    """GeoJSON / KML feature collection for boundaries, scans, risks, ..."""

    __tablename__ = "oe_geo_hub_overlay"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="boundary",
        index=True,
    )
    geojson: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    source_file: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # Cesium PolygonGraphics-compatible style hints, e.g.::
    #   {"fillColor": "#3399FF", "outlineColor": "#1166AA",
    #    "extrudedHeight": 6, "fillOpacity": 0.35}
    style: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    is_visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
    )
    # Cross-module dedup: when a subscriber creates an overlay from
    # an event (clash detected, risk zone flagged, ...), the originating
    # event id is stamped here so a replay does not duplicate the row.
    source_event_id: Mapped[str | None] = mapped_column(
        String(64),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── TileGenerationJob ────────────────────────────────────────────────────


class TileGenerationJob(Base):
    """Async job that runs the canonical -> glTF -> 3D Tiles pipeline."""

    __tablename__ = "oe_geo_hub_tile_job"

    tileset_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_geo_hub_tileset.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_kind: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="bim_model",
    )
    source_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    requested_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    state: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="queued",
        index=True,
    )
    progress_pct: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    output_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )


# ── GeoRasterOverlay ─────────────────────────────────────────────────────


class GeoRasterOverlay(Base):
    """Raster overlay pinned to the globe surface.

    Backs the "PDF/DWG/image on the globe" feature: a user uploads a
    PDF page, picks a rasterised DWG top-view, or drops an image; the
    backend rasterises it to PNG; the frontend places it as a Cesium
    ``SingleTileImageryProvider`` whose rectangle / corner cartographic
    coordinates are stored here so the placement survives reloads.

    ``source_kind`` selects which optional source-blob references apply:

    ====================  ====================================================
    source_kind           ``source_blob_url``
    ====================  ====================================================
    ``pdf``               key to the uploaded PDF
    ``dwg``               key to the canonical-JSON projection of a converted
                          DWG (we store the raster in ``raster_blob_url``)
    ``image``             same as ``raster_blob_url`` (no separate source)
    ====================  ====================================================

    ``corners_geojson`` is a 4-element GeoJSON-style coords array (no
    Feature wrapper) holding ``[NW, NE, SE, SW]`` as ``[lon, lat]`` pairs.
    ``crop_polygon_geojson``, when present, is a full GeoJSON Polygon
    that the frontend applies as a ``ClippingPolygonCollection`` on the
    imagery layer so users can crop irrelevant edges away. We deliberately
    do not enforce GeoJSON schema at the column level — Pydantic
    validates on the way in; the JSON column is the storage primitive.
    """

    __tablename__ = "oe_geo_hub_raster_overlay"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # One of ``pdf``, ``dwg``, ``image`` — Pydantic enforces the enum.
    source_kind: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="image",
        index=True,
    )
    source_blob_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    # 1-based PDF page index. Always 1 for non-PDF kinds.
    source_page: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=1,
        server_default="1",
    )
    raster_blob_url: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )
    raster_width_px: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    raster_height_px: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    # GeoJSON-style coord array: [[nw_lon, nw_lat], [ne_lon, ne_lat],
    # [se_lon, se_lat], [sw_lon, sw_lat]]. Defaults to an empty list so
    # the create-from-upload path can stamp the project anchor's bbox.
    corners_geojson: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    rotation_deg: Mapped[Decimal] = mapped_column(
        Numeric(7, 3),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    opacity: Mapped[Decimal] = mapped_column(
        Numeric(4, 3),
        nullable=False,
        default=Decimal("0.7"),
        server_default="0.7",
    )
    # GeoJSON Polygon (with type/coordinates) or NULL when no crop set.
    crop_polygon_geojson: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    z_order: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )
    visible: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="1",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    # Soft-delete sentinel. Endpoints filter out non-null rows; a
    # purge sweep can later hard-delete after a grace period.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        index=True,
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:  # pragma: no cover
        return f"<GeoRasterOverlay {self.id} ({self.source_kind} / {self.name})>"


# ── GeocodeCache ─────────────────────────────────────────────────────────


class GeocodeCache(Base):
    """30-day cache of Nominatim address-to-coords lookups.

    Keyed by ``query_hash`` (SHA-256 of the normalised query string) so
    we can serve a repeat lookup without re-hitting Nominatim and without
    burning rate-limit budget. ``cached_at`` drives the 30-day TTL: a row
    older than 30 days is treated as a miss and re-fetched on next
    request. ``hit_count`` is incremented every time the row is reused
    so we have visibility into which addresses are hot (handy for
    moving them to a seed file later).

    Every NOT NULL column ships a ``server_default`` so the ``create_all``
    fresh-DB path can't trip ``IntegrityError`` (see v4.4.1 memory note).
    """

    __tablename__ = "oe_geo_hub_geocode_cache"
    __table_args__ = (
        UniqueConstraint(
            "query_hash",
            name="uq_oe_geo_hub_geocode_cache_query_hash",
        ),
    )

    query_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
        default="",
        server_default="",
        index=True,
    )
    query_text: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    lat: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    lon: Mapped[Decimal] = mapped_column(
        Numeric(10, 7),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    precision: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="address",
        server_default="address",
    )
    display_name: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    bbox_min_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )
    bbox_min_lon: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )
    bbox_max_lat: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )
    bbox_max_lon: Mapped[Decimal | None] = mapped_column(
        Numeric(10, 7),
        nullable=True,
    )
    source: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
        default="nominatim",
        server_default="nominatim",
    )
    cached_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        index=True,
    )
    hit_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default="0",
    )

    def __repr__(self) -> str:  # pragma: no cover — display only
        return f"<GeocodeCache {self.query_hash[:8]}… ({self.lat},{self.lon}) {self.precision}>"


__all__ = [
    "GeoAnchor",
    "GeoOverlay",
    "GeoRasterOverlay",
    "GeocodeCache",
    "ImageryLayer",
    "TerrainSource",
    "TileGenerationJob",
    "Tileset",
    "GeoViewpoint",
]
