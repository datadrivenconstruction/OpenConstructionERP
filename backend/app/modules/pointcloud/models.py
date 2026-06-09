# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture ORM models.

Tables (all prefixed ``oe_pointcloud_``):

    scan_dataset         - one registered reality-capture scan (laser scan,
                           photogrammetry, drone LiDAR, handheld LiDAR)
    scan_registration    - alignment / deviation result tying a scan to a
                           design target or a prior scan

Design constraints (see ``docs/strategy/POINTCLOUD_AND_SPATIAL_PLAN.md``)
------------------------------------------------------------------------

* NO PostGIS. The embedded pixeltable-pgserver is vanilla PostgreSQL, so
  geometry / geography columns or indexes would break ``create_all`` and
  alembic. We follow ``geo_hub/models.py``: store the spatial extent as a
  JSON ``bbox_json`` blob plus plain ``Numeric(10,7)`` min/max lat/lon for
  cheap B-tree range filters. ``Numeric(10,7)`` holds ~1.1 cm precision at
  the equator, which is finer than any accuracy tier we support.
* Thin core. The point bytes never live in PostgreSQL. The raw upload, the
  COPC archive, the 3D Tiles ``pnts`` and the DTM/DSM raster all live in
  MinIO under tenant-namespaced keys; this row only carries the keys / URIs
  and the metadata needed to drive validation, billing and the viewer.
* Multi-tenant. ``tenant_id`` is carried on every scan and the upload key is
  tenant-namespaced so two tenants that happen to upload the same vendor key
  can never collide.

Money / quantities
------------------

No money in this module. All quantities (point counts, lat/lon degrees, RMS
millimetres, coverage percent, hole area, deviation counts) use ``Decimal``
via ``Numeric`` for stable serialisation; the schema layer emits them as
plain strings so no consumer parses a locale-coloured float.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import (
    JSON,
    ForeignKey,
    Index,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base

# Accepted source formats. Proprietary Autodesk ReCap containers (``rcp`` /
# ``rcs``) are deliberately excluded - they carry a licensing trap and are
# never accepted as input (plan section 9). The schema layer enforces this
# allow-list at the API boundary; the column stays an open string so a future
# open format does not require a migration.
ACCEPTED_SCAN_FORMATS: frozenset[str] = frozenset(
    {"e57", "las", "laz", "copc", "ply", "pcd", "pts", "xyz"},
)

# Formats that are rejected on sight. Listed so the validator and the API can
# give an explanatory error ("ReCap RCP/RCS is proprietary; export E57 or LAS
# instead") instead of a silent drop.
REJECTED_SCAN_FORMATS: frozenset[str] = frozenset({"rcp", "rcs"})


# ── ScanDataset ──────────────────────────────────────────────────────────


class ScanDataset(Base):
    """One registered reality-capture scan.

    A scan starts life in ``status='uploading'`` the moment the upload key is
    minted, advances to ``status='uploaded'`` when the bytes land in MinIO,
    and to ``status='ready'`` once the out-of-core converter has produced a
    COPC archive (and optionally a DTM and 3D-Tiles ``pnts`` tileset). The
    heavy work is never done in this process; this row only records where the
    artifacts live and the metadata the viewer / validation / billing need.
    """

    __tablename__ = "oe_pointcloud_scan_dataset"
    __table_args__ = (
        # The list view is always "scans for this project", tenant-scoped; this
        # composite index serves that hot path directly.
        Index("ix_oe_pointcloud_scan_dataset_project_tenant", "project_id", "tenant_id"),
        # Geo discovery uses the min/max lat/lon B-tree columns; index the SW
        # corner so a bbox-overlap pre-filter can range-scan without PostGIS.
        Index("ix_oe_pointcloud_scan_dataset_bbox_sw", "bbox_min_lat", "bbox_min_lon"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Tenant boundary. Resolved from the project owner at register time and
    # woven into the MinIO upload key so blobs are tenant-namespaced. Indexed
    # for the tenant-scoped list query.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        nullable=False,
        index=True,
    )
    # How the cloud was captured: ``laser_scan`` (TLS), ``photogrammetry``
    # (SfM / drone), ``lidar`` (MLS / SLAM / handheld), ``other``. Free-form
    # string; the schema layer documents the canonical set.
    source_type: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="laser_scan",
        server_default="laser_scan",
    )
    # The uploaded container format - one of ``ACCEPTED_SCAN_FORMATS``. Never
    # ``rcp`` / ``rcs`` (rejected at the API boundary).
    original_format: Mapped[str] = mapped_column(
        String(8),
        nullable=False,
        default="las",
        server_default="las",
    )
    # USIBD Level of Accuracy tier (plan decision #2):
    #   survey   = LOA30-40  (±3-6 mm, TLS)
    #   standard = LOA20     (±15 mm, MLS / SLAM / drone)
    #   coarse   = LOA10     (±50 mm, iPhone / iPad LiDAR)
    # ``coarse`` is forbidden from dimensional QA and from feeding cut/fill into
    # BOQ price without an explicit override (enforced in a later phase).
    accuracy_tier: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="standard",
        server_default="standard",
    )
    # Registration state of a multi-scan set: ``unregistered`` (single raw
    # scan), ``registered`` (aligned, RMS within tier), ``failed`` (RMS over
    # tolerance). A scan must be registered before it can feed deviation QA.
    registration_status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="unregistered",
        server_default="unregistered",
    )
    # EPSG code of the cloud's coordinate reference system, when known.
    # ``None`` means "not yet detected / local coordinates"; validation blocks
    # geo-referenced cut/fill until a CRS is present.
    crs_epsg: Mapped[int | None] = mapped_column(
        nullable=True,
    )
    # Confidence (0..1) of the auto-detected CRS, as a decimal string. ``None``
    # when the CRS was set explicitly by a human (no guessing involved).
    crs_confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )
    # Total point count. Populated from the laspy header sniff at upload, then
    # corrected by the converter after reprojection / classification. ``0``
    # until the header has been read.
    point_count: Mapped[int] = mapped_column(
        Numeric(18, 0),
        nullable=False,
        default=0,
        server_default="0",
    )
    # Full axis-aligned bounding box in the cloud's own units, as a JSON blob:
    #   {"min": [x, y, z], "max": [x, y, z], "units": "m", "crs_epsg": 25832}
    # The Numeric min/max lat/lon columns below mirror the WGS84-projected
    # corners for cheap B-tree range filters (no PostGIS).
    bbox_json: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # WGS84-projected bounding-box corners for range filtering. ``Numeric(10,7)``
    # = ~1.1 cm at the equator. ``None`` until the cloud is geo-referenced.
    bbox_min_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    bbox_min_lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    bbox_max_lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    bbox_max_lon: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    # Tenant-namespaced MinIO key of the raw uploaded container. The bytes are
    # uploaded presigned-direct-to-MinIO; this column only records the key.
    upload_key: Mapped[str] = mapped_column(
        String(500),
        nullable=False,
        default="",
        server_default="",
    )
    # MinIO URI of the range-readable COPC archive (``.copc.laz``) produced by
    # the converter. ``None`` until conversion completes.
    copc_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # MinIO URI of the 3D-Tiles ``pnts`` tileset, generated on demand the first
    # time a Cesium geo-view is opened, then cached. ``None`` until then.
    tileset_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # MinIO URI of the DTM/DSM GeoTIFF used for cut/fill. ``None`` until the
    # ground-classify + raster step runs.
    dtm_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Per-class aggregate counts produced by the converter's ground/class
    # segmentation, e.g. {"ground": 1200000, "building": 540000, ...}. The full
    # per-point class lives inside the COPC; this is the cheap summary.
    classification_stats: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    # Lifecycle: ``uploading`` -> ``uploaded`` -> ``converting`` -> ``ready``,
    # with ``failed`` as a side-exit. Indexed for the "what is still
    # processing" filter.
    status: Mapped[str] = mapped_column(
        String(16),
        nullable=False,
        default="uploading",
        server_default="uploading",
        index=True,
    )
    # JobRun id of the in-flight / completed ``pointcloud_ingest`` job. ``None``
    # before a conversion job is submitted (pre-tiled vendor COPC needs none).
    generation_job_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    # Raw-blob retention policy (plan decision #6). ``keep_raw`` (default, data
    # safety) or ``delete_raw_after_copc`` (delete the raw container after the
    # COPC is verified, with a grace window). The COPC / tiles are never
    # auto-deleted under either policy.
    retention_policy: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="keep_raw",
        server_default="keep_raw",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )

    # Relationships - registrations cascade on scan delete so we never strand
    # orphaned alignment rows.
    registrations: Mapped[list[ScanRegistration]] = relationship(
        back_populates="scan",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"<ScanDataset {self.id} ({self.original_format} / {self.status})>"


# ── ScanRegistration ─────────────────────────────────────────────────────


class ScanRegistration(Base):
    """Alignment / deviation result tying a scan to a target.

    A registration records how a scan was aligned to a design model or a prior
    scan, the residual error of that alignment, and the resulting deviation
    map. The accuracy companions (``rms_error``, ``coverage_pct``,
    ``hole_area``, ``out_of_tolerance_count``, ``confidence``) are mandatory
    inputs to the validation gate so a silently mis-registered scan can never
    invent phantom volume or phantom deviation.
    """

    __tablename__ = "oe_pointcloud_scan_registration"
    __table_args__ = (Index("ix_oe_pointcloud_scan_registration_scan", "scan_id"),)

    scan_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_pointcloud_scan_dataset.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # What the scan was aligned to. Free-form polymorphic reference resolved by
    # the service: a BIM model id, a prior scan id, or a named datum. Kept as a
    # string (not an FK) so a deviation can target a design that lives in
    # another module's table without cross-module schema coupling.
    target_ref: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
        default="",
        server_default="",
    )
    # 4x4 rigid-body transform that maps the scan into the target frame, stored
    # row-major as a JSON list of 16 numbers. Empty list = identity / not yet
    # computed.
    transform_matrix: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    # Registration RMS error in millimetres. Must be below the scan's accuracy
    # tier tolerance or validation blocks downstream QA. ``None`` until an
    # alignment has run.
    rms_error: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 4),
        nullable=True,
    )
    # MinIO URI of the point-to-mesh deviation colour map. ``None`` until a
    # deviation pass runs.
    deviation_map_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    # Number of points beyond the deviation tolerance band. Drives the QA
    # "clash with reality" queue. ``0`` until a deviation pass runs.
    out_of_tolerance_count: Mapped[int] = mapped_column(
        Numeric(18, 0),
        nullable=False,
        default=0,
        server_default="0",
    )
    # Percentage of the target surface actually covered by points (0..100).
    # Low coverage means the rest was filled by interpolation and the figure is
    # not trustworthy - mandatory companion to every cut/fill and deviation.
    coverage_pct: Mapped[Decimal | None] = mapped_column(
        Numeric(6, 3),
        nullable=True,
    )
    # Total occlusion / hole area in square metres - surface the scan never
    # saw. Silent DTM interpolation across holes is a classic accuracy trap, so
    # this is recorded and surfaced alongside the volume.
    hole_area: Mapped[Decimal | None] = mapped_column(
        Numeric(18, 6),
        nullable=True,
    )
    # Confidence (0..1) of the alignment, as a decimal string. ``None`` for a
    # human-confirmed datum where no estimate applies.
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3),
        nullable=True,
    )

    # Relationships
    scan: Mapped[ScanDataset] = relationship(back_populates="registrations")

    def __repr__(self) -> str:  # pragma: no cover - display only
        return f"<ScanRegistration {self.id} scan={self.scan_id} target={self.target_ref!r}>"


__all__ = [
    "ACCEPTED_SCAN_FORMATS",
    "REJECTED_SCAN_FORMATS",
    "ScanDataset",
    "ScanRegistration",
]
