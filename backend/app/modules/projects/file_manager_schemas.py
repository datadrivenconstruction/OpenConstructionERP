"""‌⁠‍Pydantic schemas for the project file manager (Issue #109).

The file manager surfaces every binary that belongs to a project — drawings,
photos, BIM models, BOQ exports, takeoffs — alongside the *real* on-disk
path so users can answer "where is my project actually stored?" without
guessing. The schemas here are the wire contracts for the new endpoints
under ``/api/v1/projects/{project_id}/files/``.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# Kind of file as far as the UI is concerned. Drives the icon + which
# download endpoint to call. Stable string identifiers — never i18n.
FileKind = Literal[
    "document",
    "photo",
    "sheet",
    "bim_model",
    "dwg_drawing",
    "takeoff",
    "report",
    "markup",
]


class FileRow(BaseModel):
    """‌⁠‍Single file as shown in the file-manager grid/list."""

    id: str = Field(..., description="UUID of the underlying row (Document/Photo/...)")
    kind: FileKind = Field(..., description="Logical file type — drives UI icon and download URL")
    name: str = Field(..., description="Human-readable file name (without folder)")
    project_id: str
    size_bytes: int = Field(default=0, ge=0)
    mime_type: str | None = None
    extension: str | None = Field(
        default=None,
        description="Lower-cased file extension without leading dot, or None",
    )
    modified_at: datetime | None = None
    physical_path: str = Field(
        ...,
        description="Absolute on-disk path (or s3:// key) where this file lives",
    )
    relative_path: str = Field(
        ...,
        description="Path relative to the storage root, suitable for breadcrumbs",
    )
    storage_backend: Literal["local", "s3"] = "local"
    download_url: str | None = Field(
        default=None,
        description="Authenticated download URL (e.g. /api/v1/documents/{id}/download/)",
    )
    preview_url: str | None = Field(
        default=None,
        description="Inline preview URL when one is supported (PDF page 1 PNG, photo thumb, ...)",
    )
    thumbnail_url: str | None = None
    discipline: str | None = None
    category: str | None = None
    extra: dict = Field(
        default_factory=dict,
        description="Module-specific extras (revision, sheet_number, model_format, ...)",
    )


class FileTreeNode(BaseModel):
    """‌⁠‍Logical tree node — a category, kind, or virtual folder."""

    id: str = Field(..., description="Stable identifier — used as React key")
    label: str = Field(..., description="Localised label fallback (UI re-translates if available)")
    kind: Literal["category", "type", "folder", "trash"] = "category"
    file_count: int = 0
    total_bytes: int = 0
    physical_path: str | None = Field(
        default=None,
        description="Real on-disk parent for files inside this node (None for virtual nodes)",
    )
    storage_backend: Literal["local", "s3"] = "local"
    children: list[FileTreeNode] = Field(default_factory=list)


# Pydantic v2 forward-reference resolution — the recursive list[FileTreeNode]
# above needs an explicit rebuild call so child-node validation works.
FileTreeNode.model_rebuild()


class StorageLocations(BaseModel):
    """Real on-disk roots used by the project — surfaced in the path bar."""

    project_id: str
    project_name: str
    storage_uses_default: bool = True
    storage_path_override: str | None = None
    storage_backend: Literal["local", "s3"] = "local"
    db_path: str | None = Field(
        default=None,
        description="Absolute path to the SQLite DB or driver URL summary",
    )
    uploads_root: str | None = None
    photos_root: str | None = None
    sheets_root: str | None = None
    bim_root: str | None = None
    dwg_root: str | None = None
    extras: dict[str, str] = Field(
        default_factory=dict,
        description="Any other resolved roots (e.g. takeoff_root, reports_root)",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Operator-facing notes — typo warnings, mixed-root callouts, ...",
    )


class FileListResponse(BaseModel):
    """Paginated list response for /files/."""

    project_id: str
    items: list[FileRow]
    total: int
    limit: int
    offset: int


# ── Bundle export / import schemas ───────────────────────────────────────


BundleScope = Literal[
    "metadata_only",  # DB rows only, no attachments — small zip suitable for email
    "documents",  # DB + documents + photos + sheets
    "bim",  # BIM models + elements + their geometry files
    "dwg",  # DWG/DXF drawings + parsed entities
    "full",  # Everything — DB + every attachment kind
]


class ExportOptions(BaseModel):
    """Body for POST /export/ and /export/preview/."""

    scope: BundleScope = "metadata_only"
    include_documents: bool = False
    include_photos: bool = False
    include_sheets: bool = False
    include_bim_models: bool = False
    include_bim_elements: bool = Field(
        default=False,
        description="BIM elements can be huge (50k+ rows). Off by default; on for full bundles.",
    )
    include_bim_geometry: bool = False
    include_dwg_drawings: bool = False
    include_takeoff: bool = False
    include_reports: bool = False


class ExportPreview(BaseModel):
    """Returned by POST /export/preview/ — sizes only, no zip."""

    scope: BundleScope
    table_counts: dict[str, int]
    attachment_count: int
    estimated_size_bytes: int
    bundle_format: str = "ocep"
    bundle_format_version: str = "1.0.0"


class BundleManifest(BaseModel):
    """Embedded manifest.json contract — also returned by /import/validate/."""

    app: str = "openestimate"
    format: str = "ocep"
    format_version: str = "1.0.0"
    compat_min_app_version: str = "2.9.0"
    exported_at: datetime
    exported_by_email: str | None = None
    project_id: str
    project_name: str
    project_currency: str | None = None
    scope: BundleScope = "metadata_only"
    tables: list[str]
    record_counts: dict[str, int]
    attachment_count: int = 0
    attachment_total_bytes: int = 0
    engine_name: str = "OpenConstructionERP"
    engine_version: str = "2.9.4"
    # Origin provenance stamped on every exported .ocep bundle. Default
    # bytes XOR-decode (key 0x55) to the project authorship marker. Purely
    # informational manifest metadata: the importer reads tables/attachments
    # by name and never branches on this field, so it changes no behaviour.
    provenance: str = "OpenConstructionERP · DataDrivenConstruction · " + bytes(
        b ^ 0x55 for b in b"\x11\x11\x16\x78\x16\x02\x1c\x16\x07\x78\x1a\x10\x78\x67\x65\x67\x63"
    ).decode("ascii")


ImportMode = Literal["new_project", "merge_into_existing", "replace_existing"]


class ImportPreview(BaseModel):
    """Returned by POST /import/validate/ before the user commits."""

    manifest: BundleManifest
    bundle_size_bytes: int
    has_attachments: bool
    warnings: list[str] = Field(default_factory=list)


class ImportResult(BaseModel):
    """Returned by POST /import/ after the bundle is unpacked."""

    project_id: str
    mode: ImportMode
    imported_counts: dict[str, int]
    skipped_counts: dict[str, int]
    attachment_count: int
    warnings: list[str] = Field(default_factory=list)


class EmailLinkResponse(BaseModel):
    """Response for POST /files/{id}/email-link/."""

    url: str
    expires_at: datetime
    file_id: str
    file_name: str
    size_bytes: int
