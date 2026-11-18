# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""China pack ORM model: a project's choices inside its provincial fee programme.

One row per project, only once somebody saves a choice. Which programme
applies is not stored by default: it follows the project's site province and
tender date (see :mod:`app.modules.china_pack.fees`). What a person states is
the rate picked inside a band, the zone, grade or class options, and whether
the labour prices already include social insurance.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class ChinaFeeProfile(Base):
    """Rates, options and the schedule override of one project's fee programme."""

    __tablename__ = "oe_china_pack_fee_profile"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    schedule_key: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rates: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    options: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    bases: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    labour_includes_social_insurance: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="0"
    )
    apply_labour_factor: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<ChinaFeeProfile {self.project_id} {self.schedule_key}>"
