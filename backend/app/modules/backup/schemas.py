"""‌⁠‍Pydantic schemas for the Backup & Restore module.

Schemas are kept here so they appear explicitly in the OpenAPI spec.
Bug-018: ``POST /backup/export/`` had no documented request body, which
made the OpenAPI surface empty for that endpoint — clients then guessed
field names that the server silently ignored.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class ExportRequest(BaseModel):
    """‌⁠‍Request body for ``POST /api/v1/backup/export/``.

    All fields are optional; an empty body (``{}``) produces a full
    backup of every table the requesting user owns.
    """

    include_modules: list[str] | None = Field(
        default=None,
        description=(
            "Subset of backup keys (table aliases) to include — for example "
            "``['projects', 'boqs', 'positions']``. ``None`` (the default) "
            "exports every known table. Unknown keys are silently dropped "
            "and surfaced as a warning entry in ``manifest.json``."
        ),
        examples=[["projects", "boqs"]],
    )
    include_files: bool = Field(
        default=False,
        description=(
            "When ``true``, embed binary files referenced by ``file_path`` "
            "columns (documents, photos, markup overlays) into the archive "
            "under ``files/<storage-key>``. Files that fail to read are "
            "skipped and listed in ``manifest.json`` warnings."
        ),
    )
    compression_level: int = Field(
        default=6,
        ge=0,
        le=9,
        description=(
            "DEFLATE compression level (0 = store, 9 = best). Default 6 matches Python's ``zipfile`` default."
        ),
    )


class RestoreResponse(BaseModel):
    """‌⁠‍Result of a restore operation."""

    status: str
    mode: str
    imported: dict[str, int]
    skipped: dict[str, int]
    warnings: list[str]


class ValidateResponse(BaseModel):
    """Result of a backup validation check."""

    valid: bool
    format_version: str
    created_at: str
    record_counts: dict[str, int]
    warnings: list[str]
    checksum: str
