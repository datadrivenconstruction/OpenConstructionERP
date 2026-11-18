# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Project tax profile ORM model.

One row per project, and only once somebody states it. A project without a row
is not "general method, newest edition": the service answers with a derived
profile marked ``stored=False`` so the screen can say the values are proposals,
and the bill rules treat an unstated edition as unstated.
"""

from __future__ import annotations

import uuid
from datetime import date

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ProjectTaxProfile(Base):
    """How one project accounts for output tax, and which bill edition it uses.

    ``method_history`` is the list of methods the project left, each
    ``{"method", "election_date", "changed_on"}``; the lock check reads the
    current election, the history is the evidence behind it.
    """

    __tablename__ = "oe_project_tax_profile"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    tax_method: Mapped[str] = mapped_column(String(20), nullable=False, default="general", server_default="general")
    election_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    lock_months: Mapped[int | None] = mapped_column(Integer, nullable=True)
    grandfathered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    simplified_basis: Mapped[str | None] = mapped_column(String(40), nullable=True)
    employer_supplied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    taxpayer_size: Mapped[str] = mapped_column(String(20), nullable=False, default="general", server_default="general")
    permit_start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    contract_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    tender_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    standard_edition: Mapped[str | None] = mapped_column(String(40), nullable=True)
    site_subdivision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    site_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    home_subdivision: Mapped[str | None] = mapped_column(String(10), nullable=True)
    home_city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    method_history: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ProjectTaxProfile {self.project_id} {self.tax_method} {self.standard_edition}>"
