# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""File References ORM models.

Tables:
    oe_file_naming_violation — one row per (project_id, file_kind,
                               file_id) where the filename fails the
                               active naming convention. The detected
                               violation codes are stored as a JSON
                               list so a single sweep doesn't need
                               multiple rows per file.
    oe_file_reference        — generic file → entity link. A file may
                               be referenced from any kind of target
                               (RFI, issue, task, submittal, punchlist,
                               ...) — ``target_type`` is a free-form
                               string validated by the Pydantic schema.

Polymorphism rationale
----------------------
Both file_id and target_id are string columns instead of true FKs
because the 8 file kinds + N target kinds live in many tables and a
polymorphic FK requires either inheritance or a join-table per kind.
Cleanup is the responsibility of the file-manager dispatcher: when a
file is hard-deleted, ``service.purge_references_for_file`` removes
related rows.
"""

import uuid

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# ── Naming violations ─────────────────────────────────────────────────


class FileNamingViolation(Base):
    """Per-file violation row written by a project-wide naming scan."""

    __tablename__ = "oe_file_naming_violation"
    __table_args__ = (
        # One violation row per file. A re-scan upserts the row in
        # place rather than appending; ``violation_codes`` keeps the
        # multi-issue payload in a JSON list.
        UniqueConstraint(
            "project_id",
            "file_kind",
            "file_id",
            name="uq_oe_file_naming_violation_project_kind_file",
        ),
        Index(
            "ix_oe_file_naming_violation_project_ack",
            "project_id",
            "acknowledged_at",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rule_set: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="iso19650",
        server_default="iso19650",
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # JSON list of violation codes (e.g. ``["missing-volume", "bad-role-code"]``).
    violation_codes: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list, server_default="[]")
    # Optional human-readable note for the worst single issue — surfaced
    # in the banner so the user sees the punch-line without expanding.
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    acknowledged_at: Mapped[object | None] = mapped_column(DateTime(timezone=True), nullable=True)
    acknowledged_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return f"<FileNamingViolation {self.file_kind}/{self.filename} codes={self.violation_codes}>"


# ── Cross-entity references ──────────────────────────────────────────


class FileReference(Base):
    """A directional ``file → target`` link.

    Examples:
        * RFI #142 references drawing ``A-203 Floor Plan.pdf``.
        * Task ``Install windows`` references photo ``IMG-3344.jpg``.
        * Submittal ``SUB-007`` references spec ``Section 09 22.pdf``.

    ``relation`` is intentionally an open string so consumer modules
    can describe context-specific link semantics ("evidence",
    "supersedes", "spawned-from") without a migration. The default is
    ``"references"`` — read it as "is mentioned in".
    """

    __tablename__ = "oe_file_reference"
    __table_args__ = (
        # A given (file, target, relation) link is at most once. Re-
        # linking the same triple is idempotent.
        UniqueConstraint(
            "file_kind",
            "file_id",
            "target_type",
            "target_id",
            "relation",
            name="uq_oe_file_reference_file_target_relation",
        ),
        Index(
            "ix_oe_file_reference_file",
            "file_kind",
            "file_id",
        ),
        Index(
            "ix_oe_file_reference_target",
            "target_type",
            "target_id",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    file_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    file_id: Mapped[str] = mapped_column(String(255), nullable=False)
    target_type: Mapped[str] = mapped_column(String(64), nullable=False)
    target_id: Mapped[str] = mapped_column(String(255), nullable=False)
    relation: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="references",
        server_default="references",
    )
    # Human-readable label for the chip in the preview pane. Fallback
    # to ``f"{target_type} {target_id[:8]}"`` if NULL.
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_users_user.id", ondelete="SET NULL"),
        nullable=True,
    )

    def __repr__(self) -> str:  # pragma: no cover — debug helper
        return (
            f"<FileReference {self.file_kind}/{self.file_id} -> {self.target_type}/{self.target_id} ({self.relation})>"
        )
