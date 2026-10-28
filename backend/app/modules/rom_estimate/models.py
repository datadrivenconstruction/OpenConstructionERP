# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Conceptual (ROM) estimate ORM models.

Tables:
    oe_rom_estimate_estimate - a saved order-of-magnitude estimate for a project

Monetary and ratio columns are stored as strings (the platform Decimal-as-string
convention) so precision is never lost through a binary float. The elemental
breakdown is stored as JSON so a saved estimate keeps a faithful snapshot even
after the reference cost rates are updated.
"""

import uuid

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class RomEstimate(Base):
    """A rough order-of-magnitude estimate saved against a project.

    Captures the inputs (building type, quality, region, gross floor area), the
    computed headline figures (cost per m2, total, accuracy band) and the full
    six-element breakdown snapshot.
    """

    __tablename__ = "oe_rom_estimate_estimate"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    building_type: Mapped[str] = mapped_column(String(60), nullable=False)
    quality: Mapped[str] = mapped_column(String(40), nullable=False, default="standard")
    region: Mapped[str] = mapped_column(String(60), nullable=False, default="global")
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    gross_floor_area: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    gfa_unit: Mapped[str] = mapped_column(String(20), nullable=False, default="m2")
    cost_per_m2: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    total_cost: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    estimate_class: Mapped[str] = mapped_column(String(40), nullable=False, default="order_of_magnitude")
    accuracy_low_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="0")
    accuracy_high_pct: Mapped[str] = mapped_column(String(20), nullable=False, default="0")
    accuracy_low_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    accuracy_high_amount: Mapped[str] = mapped_column(String(50), nullable=False, default="0")
    breakdown: Mapped[list] = mapped_column(  # type: ignore[type-arg]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<RomEstimate project={self.project_id} type={self.building_type} total={self.total_cost}>"
