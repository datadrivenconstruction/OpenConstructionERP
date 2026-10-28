# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Waste-factor ORM model.

Table:
    oe_waste_factors_factor - one waste / lap / coverage multiplier keyed by
    material or work category.

The ``factor`` column is ``Numeric(8, 4)`` (a multiplier, not money) and carries
an explicit ``server_default='1'`` so a fresh ``create_all`` gives every row a
safe pass-through factor even before the central migration adds the column - a
factor of 1 leaves the quantity unchanged. It serialises as a string via
Pydantic (the project's Decimal-as-string contract), never a float.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class WasteFactor(Base):
    """A single net-to-gross multiplier for a material or work category.

    ``gross_quantity = net_quantity * factor``. The factor is ``>= 1`` in normal
    use: ``1.10`` means order 10 percent more than the drawn quantity to cover
    offcuts, laps and breakage. Rows form a shared library (optionally
    tenant-scoped) that the ``/apply`` endpoint resolves by category.
    """

    __tablename__ = "oe_waste_factors_factor"

    category: Mapped[str] = mapped_column(String(120), nullable=False, default="", index=True)
    label: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    factor: Mapped[Decimal] = mapped_column(
        Numeric(8, 4),
        nullable=False,
        default=Decimal("1"),
        server_default="1",
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)

    def __repr__(self) -> str:
        return f"<WasteFactor {self.category} x{self.factor}>"
