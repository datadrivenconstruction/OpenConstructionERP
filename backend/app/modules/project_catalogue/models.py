# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project catalogue ORM model.

Table:
    oe_project_catalogue_item - one rate or resource that belongs to ONE project.
        It is a copy, never a reference: editing it leaves the regional cost
        database and the company library untouched. ``source_*`` records where
        the copy came from and which source price the project last took or
        acknowledged, so a moved source can be shown and decided on.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ProjectCatalogueItem(Base):
    """A project's own rate, copied from a source or typed by the estimator."""

    __tablename__ = "oe_project_catalogue_item"
    __table_args__ = (
        Index("ix_oe_project_catalogue_item_project_code", "project_id", "code"),
        # One copy per source row per project; manual rows carry NULL and never collide.
        UniqueConstraint("project_id", "source_type", "source_id", name="uq_oe_project_catalogue_item_source"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_projects_project.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    # work | labor | material | equipment | other
    item_type: Mapped[str] = mapped_column(String(20), nullable=False, default="work", server_default="work")
    rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"), server_default="0")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # manual | cost_item (oe_costs_item) | catalog_resource (oe_catalog_resource)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    source_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    source_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    # The source price the project last took or acknowledged; NULL for manual rows.
    source_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    source_currency: Mapped[str] = mapped_column(String(10), nullable=False, default="", server_default="")
    source_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:  # pragma: no cover - debug repr
        return f"<ProjectCatalogueItem {self.code} {self.rate} {self.currency} ({self.source_type})>"
