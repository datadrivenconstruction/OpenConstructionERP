# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Dashboards ORM models (T01 and later tasks).

Tables:
    oe_dashboards_snapshot        — point-in-time Parquet dumps of entity data
    oe_dashboards_source_file     — per-file manifest rows inside a snapshot (T01, T10)

The Parquet blobs themselves live under the configured StorageBackend
(see :mod:`app.modules.dashboards.snapshot_storage`). Only metadata
lives in SQL — entity rows are never persisted to the relational DB.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Snapshot(Base):
    """One named Parquet dump of a project's entity data.

    A snapshot is immutable once created — re-running cad2data produces
    a fresh snapshot with a new id. Users compare snapshots via the
    historical navigator (T11); they never edit an existing one.

    The ``parquet_dir`` column stores the *storage key prefix* (as
    composed by :func:`snapshot_storage.snapshot_prefix`), not a
    filesystem path — that way moving from local to S3 does not rewrite
    any row in the DB.
    """

    __tablename__ = "oe_dashboards_snapshot"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tenant_id: Mapped[str | None] = mapped_column(
        String(36), nullable=True, index=True,
    )
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    parquet_dir: Mapped[str] = mapped_column(String(500), nullable=False)
    total_entities: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_categories: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Shape: ``{"walls": 324, "doors": 48, ...}`` — one entry per
    # category, value is row count. Rendered directly by T07 as the
    # "category bar" chart without re-querying DuckDB.
    summary_stats: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict,
    )
    # List of source-file descriptors; populated by T10 when a snapshot
    # is built from multiple input files. Empty list = single-source.
    source_files_json: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list,
    )
    parent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), nullable=True,
    )
    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), nullable=False,
    )

    __table_args__ = (
        # A label is unique within a project — two users on the same
        # project cannot both call a snapshot "Baseline".
        UniqueConstraint(
            "project_id", "label", name="uq_oe_dashboards_snapshot_project_label",
        ),
    )

    def __repr__(self) -> str:  # pragma: no cover — debug only
        return (
            f"Snapshot(id={self.id}, project_id={self.project_id}, "
            f"label={self.label!r}, total_entities={self.total_entities})"
        )


class SnapshotSourceFile(Base):
    """Per-file descriptor inside a snapshot.

    Populated by the cad2data bridge during snapshot creation. One row
    per uploaded file. The discipline free-text is user-provided at
    upload time (``"architecture"`` / ``"structure"`` / ``"mep"`` /
    ``"civil"`` — no enum because regional naming varies).
    """

    __tablename__ = "oe_dashboards_source_file"

    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_dashboards_snapshot.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Lower-cased extension without the dot: ``"ifc"``, ``"rvt"``, ``"dwg"``, ``"dgn"``.
    format: Mapped[str] = mapped_column(String(20), nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(100), nullable=True)
    entity_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    bytes_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Free-form notes returned by the converter — parse errors, skipped
    # categories, version warnings. Stored as JSON to avoid a string
    # schema lock-in.
    converter_notes: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=dict,
    )
