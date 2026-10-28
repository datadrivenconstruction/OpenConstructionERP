# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Site-inventory ORM models (on-site material metering and stock).

Tables:
    oe_site_inventory_location  - a geo-tagged storage location on a project
    oe_site_inventory_item      - a stock item / material record
    oe_site_inventory_movement  - a stock movement (inbound / consumption /
                                  waste / transfer)

Stock on hand is never stored: it is derived as the signed sum of movements by
:mod:`app.modules.site_inventory.ledger`. Cross-module links (BoQ position,
procurement goods receipt, procurement requisition line) are foreign keys by id
only - this module references those tables, it never alters them, and the
``ondelete`` rules keep a stock record readable if the thing it pointed at is
removed.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    JSON,
    Boolean,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import AwareDateTime, MoneyType
from app.database import GUID, Base

# -- Storage location --------------------------------------------------------


class StockLocation(Base):
    """A geo-tagged storage location on a project (yard, container, floor bay).

    Movements happen at a location, and a ``TRANSFER`` moves stock from one
    location to another. Latitude / longitude are stored as ``Decimal`` (never a
    float) so a location can be pinned on a site map without precision loss.
    """

    __tablename__ = "oe_site_inventory_location"
    __table_args__ = (Index("ix_site_inv_location_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<StockLocation {self.name} project={self.project_id}>"


# -- Stock item / material record --------------------------------------------


class StockItem(Base):
    """A stock item / material record tracked on a project.

    Optionally linked to the BoQ position it is installed against and to the
    procurement requisition line it was ordered on. Both links are nullable and
    ``SET NULL`` on delete, so a material record survives the removal of the
    estimate line or requisition it referenced.
    """

    __tablename__ = "oe_site_inventory_item"
    __table_args__ = (
        Index("ix_site_inv_item_project", "project_id"),
        Index("ix_site_inv_item_boq_position", "boq_position_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(64), nullable=True)
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")

    # Optional link to the BoQ position this material is installed against.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optional link to the procurement requisition line this material came from.
    procurement_req_item_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_req_item.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Optional default storage location for this item.
    default_location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_inventory_location.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Optional standard unit cost (Decimal money). Used as a fallback valuation
    # when a movement carries no explicit unit cost of its own.
    standard_unit_cost: Mapped[Decimal | None] = mapped_column(MoneyType(18, 4), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    # Optional reorder trigger (min stock) - a quantity, not money.
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    movements: Mapped[list["StockMovement"]] = relationship(
        "app.modules.site_inventory.models.StockMovement",
        back_populates="item",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<StockItem {self.name} ({self.unit}) project={self.project_id}>"


# -- Stock movement (the ledger entry) ---------------------------------------


class StockMovement(Base):
    """One stock movement: the signed unit of the on-site material ledger.

    ``quantity`` and ``unit_cost`` are non-negative magnitudes stored as
    ``Decimal``; the direction (add or remove) is derived from ``movement_type``
    by the pure ledger, never from a negative quantity. ``INBOUND`` may reference
    the procurement goods receipt it arrived on; ``CONSUMPTION`` may reference the
    BoQ position it was installed against; ``TRANSFER`` carries both a source
    ``location_id`` and a destination ``to_location_id``.
    """

    __tablename__ = "oe_site_inventory_movement"
    __table_args__ = (
        Index("ix_site_inv_move_project_item", "project_id", "item_id"),
        Index("ix_site_inv_move_project_type", "project_id", "movement_type"),
        Index("ix_site_inv_move_project_occurred", "project_id", "occurred_at"),
        Index("ix_site_inv_move_boq_position", "boq_position_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_site_inventory_item.id", ondelete="CASCADE"),
        nullable=False,
    )
    # One of INBOUND, CONSUMPTION, WASTE, TRANSFER (see ledger.MovementType).
    movement_type: Mapped[str] = mapped_column(String(20), nullable=False)

    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    unit_cost: Mapped[Decimal] = mapped_column(MoneyType(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")

    # Source location (and destination, for a TRANSFER).
    location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_inventory_location.id", ondelete="SET NULL"),
        nullable=True,
    )
    to_location_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_site_inventory_location.id", ondelete="SET NULL"),
        nullable=True,
    )

    # CONSUMPTION links to the BoQ position it was installed against.
    boq_position_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_boq_position.id", ondelete="SET NULL"),
        nullable=True,
    )
    # INBOUND links to the procurement goods receipt it arrived on.
    goods_receipt_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_goods_receipt.id", ondelete="SET NULL"),
        nullable=True,
    )

    # When the movement physically happened (may differ from the record's
    # created_at). Timezone-aware.
    occurred_at: Mapped[datetime] = mapped_column(AwareDateTime(), nullable=False)
    # Who recorded it (the acting user id).
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    item: Mapped[StockItem] = relationship(
        "app.modules.site_inventory.models.StockItem",
        back_populates="movements",
    )

    def __repr__(self) -> str:
        return f"<StockMovement {self.movement_type} {self.quantity} item={self.item_id}>"
