# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
"""Point Cloud / Reality Capture Pydantic schemas - request / response models.

Decimal quantities (RMS, coverage, confidence, hole area, lat/lon) are stored
as ``Decimal`` and emitted as plain decimal *strings* in JSON, mirroring the v3
money-serialisation rule used across the codebase (``boq.schemas`` /
``bim_hub.schemas``). A float would force every consumer to parse a
locale-coloured number and would silently drop precision; a string round-trips
exactly. There is no money in this module, but the same rule keeps survey-grade
figures (a 3 mm RMS) honest.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_serializer

from app.modules.pointcloud.models import ACCEPTED_SCAN_FORMATS


# ── Decimal-as-string helper ─────────────────────────────────────────────
def _serialise_decimal(v: Decimal | None) -> str | None:
    """Emit a finite ``Decimal`` as a plain non-scientific string, else ``None``.

    Non-finite values (``NaN`` / ``Infinity``) collapse to ``None`` rather than
    poison the JSON payload - a non-finite RMS or coverage is meaningless and
    should read as "not measured".
    """
    if v is None:
        return None
    if not isinstance(v, Decimal):
        try:
            v = Decimal(str(v))
        except (InvalidOperation, ValueError):
            return None
    if not v.is_finite():
        return None
    return format(v, "f")


# ── Accuracy tier (USIBD Level of Accuracy) ──────────────────────────────


class AccuracyTier(StrEnum):
    """USIBD Level of Accuracy (LOA) tier for a reality-capture scan.

    The mapping is the industry-standard USIBD LOA specification (plan
    decision #2). Each tier bounds the representation accuracy the scan can be
    trusted at, which in turn gates what the scan is allowed to drive:

    * ``survey``   - LOA30-40, ±3-6 mm. Terrestrial laser scanning (TLS).
                     Trusted for dimensional QA and for cut/fill feeding BOQ
                     price.
    * ``standard`` - LOA20, ±15 mm. Mobile / SLAM / drone capture. Trusted for
                     earthwork volumes and coarse QA.
    * ``coarse``   - LOA10, ±50 mm. iPhone / iPad LiDAR, handheld. Forbidden
                     from dimensional QA and from feeding cut/fill into BOQ
                     price without an explicit human override.

    The string values are the canonical column values stored on
    ``ScanDataset.accuracy_tier``.
    """

    survey = "survey"
    standard = "standard"
    coarse = "coarse"


class SourceType(StrEnum):
    """How a cloud was captured."""

    laser_scan = "laser_scan"
    photogrammetry = "photogrammetry"
    lidar = "lidar"
    other = "other"


class RetentionPolicy(StrEnum):
    """Raw-blob retention policy (plan decision #6).

    * ``keep_raw`` - keep the raw container indefinitely (default, data safety).
    * ``delete_raw_after_copc`` - delete the raw container after the COPC is
      verified, within a grace window. The COPC / tiles are never auto-deleted.
    """

    keep_raw = "keep_raw"
    delete_raw_after_copc = "delete_raw_after_copc"


# Accepted upload formats, derived from the model allow-list so the schema and
# the ORM can never drift. Proprietary ReCap ``rcp`` / ``rcs`` are not present.
ScanFormat = StrEnum(  # type: ignore[misc]
    "ScanFormat",
    {fmt: fmt for fmt in sorted(ACCEPTED_SCAN_FORMATS)},
)


# ── ScanDataset schemas ──────────────────────────────────────────────────


class ScanDatasetCreate(BaseModel):
    """Register a new reality-capture scan.

    This mints a ``ScanDataset`` row in ``status='uploading'`` with a
    tenant-namespaced upload key. The bytes are uploaded presigned-direct-to-
    MinIO afterwards; the backend never proxies the cloud. ``original_format``
    is validated against the accepted allow-list (E57/LAS/LAZ/COPC/PLY/PCD/
    PTS/XYZ); proprietary ReCap ``rcp`` / ``rcs`` are rejected with an
    explanatory error.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable scan name shown in the scan list.",
    )
    source_type: SourceType = Field(
        default=SourceType.laser_scan,
        description="How the cloud was captured (laser scan, photogrammetry, LiDAR).",
    )
    original_format: ScanFormat = Field(  # type: ignore[valid-type]
        ...,
        description=(
            "Uploaded container format. One of E57/LAS/LAZ/COPC/PLY/PCD/PTS/XYZ. "
            "Autodesk ReCap RCP/RCS is proprietary and not accepted - export E57 "
            "or LAS instead."
        ),
    )
    accuracy_tier: AccuracyTier = Field(
        default=AccuracyTier.standard,
        description=(
            "USIBD Level of Accuracy tier: survey (LOA30-40, plus/minus 3-6 mm), "
            "standard (LOA20, plus/minus 15 mm), coarse (LOA10, plus/minus 50 mm)."
        ),
    )
    retention_policy: RetentionPolicy = Field(
        default=RetentionPolicy.keep_raw,
        description=(
            "Whether to keep the raw upload (keep_raw, default) or delete it after "
            "the COPC archive is verified (delete_raw_after_copc)."
        ),
    )
    # Optional client-known hints; the converter corrects them authoritatively.
    crs_epsg: int | None = Field(
        default=None,
        ge=1024,
        le=999999,
        description="EPSG code of the cloud's coordinate reference system, if known.",
    )
    point_count: int = Field(
        default=0,
        ge=0,
        description="Approximate point count from a client-side header sniff, if known.",
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class ScanDatasetRead(BaseModel):
    """A reality-capture scan returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    tenant_id: UUID
    source_type: str
    original_format: str
    accuracy_tier: str
    registration_status: str
    crs_epsg: int | None = None
    crs_confidence: Decimal | None = None
    point_count: int = 0
    bbox_json: dict[str, Any] = Field(default_factory=dict)
    bbox_min_lat: Decimal | None = None
    bbox_min_lon: Decimal | None = None
    bbox_max_lat: Decimal | None = None
    bbox_max_lon: Decimal | None = None
    upload_key: str = ""
    copc_uri: str | None = None
    tileset_uri: str | None = None
    dtm_uri: str | None = None
    classification_stats: dict[str, Any] = Field(default_factory=dict)
    status: str
    generation_job_id: UUID | None = None
    retention_policy: str
    created_by: UUID | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "crs_confidence",
        "bbox_min_lat",
        "bbox_min_lon",
        "bbox_max_lat",
        "bbox_max_lon",
        when_used="json",
    )
    def _ser_decimal(self, v: Decimal | None) -> str | None:
        return _serialise_decimal(v)


class ScanDatasetList(BaseModel):
    """Paginated list of reality-capture scans."""

    items: list[ScanDatasetRead] = Field(default_factory=list)
    total: int = 0
    offset: int = 0
    limit: int = 50


# ── Presigned-direct-to-MinIO multipart ingest ───────────────────────────
#
# Reality-capture scans are 5-200 GB. The browser / CLI uploads them
# presigned-direct-to-MinIO so the FastAPI core never proxies the bytes:
#   1. POST /scans/ingest/init    -> creates the scan, opens a multipart
#      upload, returns one presigned PUT URL per part.
#   2. The client PUTs each part straight to object storage, collecting the
#      ETag each part returns.
#   3. POST /scans/ingest/complete -> finalises the multipart upload and flips
#      the scan to status=uploaded.


class ScanIngestInit(BaseModel):
    """Open a presigned-direct multipart upload for a new scan.

    Registers a ``ScanDataset`` in ``status='uploading'`` with a
    tenant-namespaced MinIO key, opens a multipart upload and returns one
    presigned ``PUT`` URL per part. ``total_size_bytes`` is the client's known
    file size; the server uses it only to compute how many part URLs to mint -
    the bytes themselves go direct to object storage and are never proxied.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    name: str = Field(
        ...,
        min_length=1,
        max_length=255,
        description="Human-readable scan name shown in the scan list.",
    )
    source_type: SourceType = Field(
        default=SourceType.laser_scan,
        description="How the cloud was captured (laser scan, photogrammetry, LiDAR).",
    )
    original_format: ScanFormat = Field(  # type: ignore[valid-type]
        ...,
        description=(
            "Uploaded container format. One of E57/LAS/LAZ/COPC/PLY/PCD/PTS/XYZ. "
            "Autodesk ReCap RCP/RCS is proprietary and not accepted - export E57 "
            "or LAS instead."
        ),
    )
    accuracy_tier: AccuracyTier = Field(
        default=AccuracyTier.standard,
        description=(
            "USIBD Level of Accuracy tier: survey (LOA30-40, plus/minus 3-6 mm), "
            "standard (LOA20, plus/minus 15 mm), coarse (LOA10, plus/minus 50 mm)."
        ),
    )
    retention_policy: RetentionPolicy = Field(
        default=RetentionPolicy.keep_raw,
        description=(
            "Whether to keep the raw upload (keep_raw, default) or delete it after "
            "the COPC archive is verified (delete_raw_after_copc)."
        ),
    )
    crs_epsg: int | None = Field(
        default=None,
        ge=1024,
        le=999999,
        description="EPSG code of the cloud's coordinate reference system, if known.",
    )
    point_count: int = Field(
        default=0,
        ge=0,
        description="Approximate point count from a client-side header sniff, if known.",
    )
    total_size_bytes: int = Field(
        ...,
        gt=0,
        description=(
            "Total size of the file the client is about to upload, in bytes. Used "
            "only to size the multipart upload (how many presigned part URLs to "
            "mint). The bytes go direct to object storage and are never proxied."
        ),
    )


class PresignedPart(BaseModel):
    """One presigned multipart part the client uploads directly to storage."""

    part_number: int = Field(
        ...,
        ge=1,
        description="1-based part index, matching the S3 multipart API.",
    )
    url: str = Field(
        ...,
        description="Short-lived presigned PUT URL the client uploads this part to.",
    )


class ScanIngestInitResponse(BaseModel):
    """Everything the client needs to upload a scan presigned-direct.

    The client PUTs each ``parts[i].url`` with the matching byte range, records
    the ETag each PUT returns, then calls ``/scans/ingest/complete`` with the
    ``(part_number, etag, size_bytes)`` list.
    """

    scan_id: UUID
    upload_id: str = Field(
        ...,
        description="Multipart upload id - echo it back on complete.",
    )
    upload_key: str = Field(
        ...,
        description="Tenant-namespaced object-storage key the parts assemble into.",
    )
    part_size_bytes: int = Field(
        ...,
        description="Size each part should be, except the last which may be shorter.",
    )
    parts: list[PresignedPart] = Field(
        default_factory=list,
        description="One presigned PUT URL per part, in ascending part order.",
    )
    expires_at: datetime = Field(
        ...,
        description="When the presigned URLs expire and the upload must be finished by.",
    )


class CompletedPart(BaseModel):
    """One finished part the client reports back on complete.

    ``etag`` is whatever the storage PUT returned for the part (the S3 ETag, or
    the local backend's chunk SHA-256); the server passes it straight through to
    ``CompleteMultipartUpload``.
    """

    part_number: int = Field(..., ge=1)
    etag: str = Field(..., min_length=1)
    size_bytes: int = Field(default=0, ge=0)


class ScanIngestComplete(BaseModel):
    """Finalise a presigned-direct multipart upload.

    Calls ``CompleteMultipartUpload`` with the reported parts, then flips the
    scan to ``status='uploaded'`` so a later phase can submit the out-of-core
    ingest job. The part list must be contiguous starting at 1.
    """

    upload_id: str = Field(..., min_length=1)
    parts: list[CompletedPart] = Field(
        ...,
        min_length=1,
        description="Every uploaded part, contiguous from part 1.",
    )


class ScanIngestCompleteResponse(BaseModel):
    """Result of finalising the multipart upload."""

    scan_id: UUID
    upload_key: str
    status: str
    size_bytes: int = 0


# ── ScanRegistration schemas ─────────────────────────────────────────────


class ScanRegistrationRead(BaseModel):
    """An alignment / deviation result returned from the API.

    The accuracy companions (``rms_error``, ``coverage_pct``, ``hole_area``,
    ``out_of_tolerance_count``, ``confidence``) are surfaced together so the UI
    never shows a deviation or volume figure without the context that tells the
    estimator whether to trust it.
    """

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    scan_id: UUID
    target_ref: str
    transform_matrix: list[Any] = Field(default_factory=list)
    rms_error: Decimal | None = None
    deviation_map_uri: str | None = None
    out_of_tolerance_count: int = 0
    coverage_pct: Decimal | None = None
    hole_area: Decimal | None = None
    confidence: Decimal | None = None
    created_at: datetime
    updated_at: datetime

    @field_serializer(
        "rms_error",
        "coverage_pct",
        "hole_area",
        "confidence",
        when_used="json",
    )
    def _ser_decimal(self, v: Decimal | None) -> str | None:
        return _serialise_decimal(v)


__all__ = [
    "AccuracyTier",
    "CompletedPart",
    "PresignedPart",
    "RetentionPolicy",
    "ScanDatasetCreate",
    "ScanDatasetList",
    "ScanDatasetRead",
    "ScanFormat",
    "ScanIngestComplete",
    "ScanIngestCompleteResponse",
    "ScanIngestInit",
    "ScanIngestInitResponse",
    "ScanRegistrationRead",
    "SourceType",
]
