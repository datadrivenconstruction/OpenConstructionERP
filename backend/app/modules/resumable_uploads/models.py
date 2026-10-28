# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Resumable Uploads ORM models.

Tables:
    oe_resumable_uploads_session - one row per in-flight chunked upload.
        Tenant-scoped through ``project_id`` (the upload always targets a
        project, exactly like the single-shot document upload). The set of
        received chunk indices is stored as a JSON list of integers; the
        service treats it as a set (membership + add are idempotent) and
        reassigns the attribute on every change so SQLAlchemy flushes it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Integer,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

# Lifecycle states for an upload session. ``in_progress`` is the initial
# state; ``assembling`` is held briefly while chunks are concatenated and
# handed to the document store; ``complete`` is terminal-success;
# ``failed`` is terminal-error (assembly / integrity check failed);
# ``expired`` marks a stale session reaped by the GC sweep.
SESSION_STATUSES: tuple[str, ...] = (
    "in_progress",
    "assembling",
    "complete",
    "failed",
    "expired",
)


class ResumableUploadSession(Base):
    """One in-flight chunked upload.

    The chain of chunks is reconstructed from ``received_chunks`` (a JSON
    list of 0-based indices). A session is complete only when every index
    in ``range(total_chunks)`` is present, the assembled byte count equals
    ``total_size``, and the optional client-supplied ``sha256`` matches.
    """

    __tablename__ = "oe_resumable_uploads_session"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Sanitised display filename. The raw upload name is sanitised the same
    # way the document service does before it is stored here.
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    # Documents-module category the assembled file lands in (drawing, other...).
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="other")
    total_size: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_size: Mapped[int] = mapped_column(Integer, nullable=False)
    total_chunks: Mapped[int] = mapped_column(Integer, nullable=False)
    # Set of received 0-based chunk indices, stored as a JSON list. The
    # service reassigns this on every write so the change is flushed.
    received_chunks: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    # Optional client-provided integrity hash, lower-case hex SHA-256.
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True, default=None)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="in_progress")
    # Owner / tenant scope. ``created_by`` mirrors how other modules store
    # the uploading user id (string form of the UUID).
    created_by: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # Storage key of the assembled blob once complete (the document
    # service's final ``file_path``); null until completion.
    storage_key: Mapped[str | None] = mapped_column(String(1024), nullable=True, default=None)
    # Resulting Document row id once the assembled file is registered.
    document_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, default=None)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    def __repr__(self) -> str:
        return (
            f"<ResumableUploadSession {self.filename} "
            f"{len(self.received_chunks or [])}/{self.total_chunks} "
            f"status={self.status}>"
        )
