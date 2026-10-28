# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Connectors ORM models.

Tables:
    oe_connectors_source - a registered inbound document source for a project.
    Today the only kind is ``watched_folder``: an operator points the source at
    a server-local directory and a sync scans it, creating a referencing
    :class:`~app.modules.documents.models.Document` for each new file so the
    scattered records land as first-class, searchable project documents. The
    last sync outcome is kept on the row so the UI can show what happened.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String, true
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ConnectorSource(Base):
    """A registered inbound document source bound to a project."""

    __tablename__ = "oe_connectors_source"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # The connector implementation. Only "watched_folder" exists today; the
    # column leaves room for cloud-storage adapters without a migration.
    kind: Mapped[str] = mapped_column(
        String(40), nullable=False, default="watched_folder", server_default="watched_folder", index=True
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    # Server-local directory a watched-folder source scans. Confined to itself
    # at sync time (a discovered file that resolves outside the root is skipped).
    root_path: Mapped[str] = mapped_column(String(1000), nullable=False, default="", server_default="")
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    # ISO-8601 string of the last sync, and the last sync's summary counts.
    last_synced_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    last_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ConnectorSource {self.id} ({self.kind}) project={self.project_id}>"
