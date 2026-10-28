# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Cost Explorer ORM models.

Tables:
    oe_cost_item_resource - the resource -> work reverse index. One row per
        resource line of a cost item, i.e. one ``(work item, resource)`` edge.

Why this table exists
---------------------
A cost item (``oe_costs_item``) carries its resource composition in a
``components`` JSON list, which answers "what does this work consume?" but not
the reverse, "which priced work items consume resource X?". Answering the
reverse from JSON means scanning every item, and the fan-out is real (the
busiest resource sits in tens of thousands of works). This table materialises
the edges so the reverse lookup is a plain indexed query.

It is populated from the *cleaned* ``oe_costs_item.components`` list (the CWICR
import already filters the raw price-book row types), so the quantity and money
here match exactly what the app serves. ``resource_code`` shares the
``CatalogResource.resource_code`` code space (verified 100% overlap on a full
region), so the resource catalog joins straight in with no bridge table.

Money and quantity stay ``Decimal``-as-string for the same SQLite/JSON
precision reason as the parent tables. ``region`` (``XX_CITY``) is the routing
key. Rows are managed wholesale per region by the reindex service (delete then
insert), mirroring the bare-``GUID`` cross-table convention used elsewhere in
the costs module, so ``cost_item_id`` is an indexed column without a hard FK.
"""

import uuid

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class CostItemResource(Base):
    """One ``(work item -> resource)`` edge, mirrored from ``CostItem.components``."""

    __tablename__ = "oe_cost_item_resource"
    __table_args__ = (
        # Reverse-lookup hot path: ``WHERE region = ? AND resource_code IN (...)``.
        Index("ix_oe_cir_region_resource", "region", "resource_code"),
        # Forward / rebuild-by-item path: ``WHERE region = ? AND rate_code = ?``.
        Index("ix_oe_cir_region_rate", "region", "rate_code"),
        # All-regions resource rollups (usage counts, cross-region reach).
        Index("ix_oe_cir_resource_code", "resource_code"),
    )

    # The owning cost item (``oe_costs_item.id``). Bare indexed GUID, no FK:
    # the index is rebuilt per region by the reindex service, and the parent
    # set is owned by the costs import, matching ``CostItem.catalog_id``.
    cost_item_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    # The work item's human code (``oe_costs_item.code``); unique with region.
    rate_code: Mapped[str] = mapped_column(String(100), nullable=False)
    region: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # The consumed resource (``CatalogResource.resource_code`` code space).
    resource_code: Mapped[str] = mapped_column(String(100), nullable=False)
    resource_name: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    # material | equipment | labor | operator | electricity | other
    resource_type: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")

    # Consumption norm: resource quantity per ONE work-item unit.
    quantity: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    # Resource unit price used inside this item, region-local currency.
    unit_rate: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    # Line contribution to the item's rate = quantity * unit_rate.
    cost: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<CostItemResource {self.rate_code} <- {self.resource_code} ({self.region})>"
