# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Plant rate catalogue tables: versioned catalogues, their machines and saved import layouts.

A catalogue is never edited in place by an import: a new version (same ``family_id``, later
``valid_from``) is created and the older one reads as superseded from that date. Interest and
repair are stored as fractions (0.06 = 6%). No national list content is shipped; the demo
catalogue is flagged ``is_synthetic``.
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class EquipmentRateCatalogue(Base):
    """One version of an internal plant rate table."""

    __tablename__ = "oe_equipment_rate_catalogue"
    __table_args__ = (Index("ix_oe_equipment_rate_catalogue_family", "family_id"),)

    family_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_label: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    licence_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    valid_from: Mapped[str] = mapped_column(String(10), nullable=False)
    interest_convention: Mapped[str] = mapped_column(
        String(40), nullable=False, default="average_value", server_default="average_value"
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Catalogue-level settings, all empty until the pack or the user sets them.
    working_days_per_month: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    standby_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    breakdown_factor: Mapped[Decimal | None] = mapped_column(Numeric(8, 4), nullable=True)
    tolerance_pct: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)

    def __repr__(self) -> str:
        return f"<EquipmentRateCatalogue {self.name} from {self.valid_from}>"


class EquipmentRateItem(Base):
    """One machine of a catalogue with the inputs of the rate formula."""

    __tablename__ = "oe_equipment_rate_item"
    __table_args__ = (
        UniqueConstraint("catalogue_id", "code", name="uq_oe_equipment_rate_item_code"),
        Index("ix_oe_equipment_rate_item_catalogue", "catalogue_id"),
    )

    catalogue_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_equipment_rate_catalogue.id", ondelete="CASCADE"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    size_key: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    residual: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False)
    life_years: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    months_per_year: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False)
    interest: Mapped[Decimal] = mapped_column(Numeric(8, 6), nullable=False)
    repair: Mapped[Decimal] = mapped_column(Numeric(8, 4), nullable=False)
    hours_per_month: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    override_monthly_rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    operating_cost_per_hour: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)

    def __repr__(self) -> str:
        return f"<EquipmentRateItem {self.code} ({self.name})>"


class EquipmentRateProfile(Base):
    """A saved column mapping for a customer's table layout (column names only, no rates)."""

    __tablename__ = "oe_equipment_rate_profile"
    __table_args__ = (UniqueConstraint("name", name="uq_oe_equipment_rate_profile_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    layout_key: Mapped[str] = mapped_column(String(50), nullable=False, default="own", server_default="own")
    mapping: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    decimal_comma: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    percent_fields: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
