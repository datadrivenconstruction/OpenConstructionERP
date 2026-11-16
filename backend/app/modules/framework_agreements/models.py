# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Framework agreement ORM models.

The agreement itself is a ``contracts.Contract`` with ``contract_type="framework"`` and every
call-off order is a ``Contract`` with ``contract_type="call_off"`` whose ``parent_contract_id``
is the agreement. These tables hold only what a contract has no place for:

Tables:
    oe_framework_rate_item   - the agreement's price list, one row per item code
    oe_framework_rate_period - rate versions: validity window, escalation method, overrides
    oe_framework_adjustment  - condition surcharges (out of hours, weekend, zone) and coefficients

``agreement_id`` points at ``oe_contracts_contract`` and cascades: an agreement deleted while
still a draft takes its price list with it.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class FrameworkRateItem(Base):
    """One priced item of an agreement's price list."""

    __tablename__ = "oe_framework_rate_item"
    __table_args__ = (Index("ix_framework_rate_item_agreement_code", "agreement_id", "code"),)

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    base_rate: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    classification: Mapped[str | None] = mapped_column(String(80), nullable=True)
    max_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    estimated_qty: Mapped[Decimal | None] = mapped_column(Numeric(18, 4), nullable=True)
    surcharge_flags: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    escalation_group: Mapped[str | None] = mapped_column(String(40), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    sort_order: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0")

    def __repr__(self) -> str:
        return f"<FrameworkRateItem {self.code} {self.base_rate}>"


class FrameworkRatePeriod(Base):
    """A rate version: from when to when, and how base rates escalate inside it.

    ``series_refs`` is ``[{"series": name}]`` for ``index_ratio`` and
    ``[{"series": name, "weight": "0.35"}]`` for ``formula`` (weights plus ``fixed_part`` sum
    to 1). ``rate_overrides`` maps an item code to the base rate that applies in this period,
    which is how a rate cited by an issued order changes without being edited in place.
    """

    __tablename__ = "oe_framework_rate_period"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    effective_from: Mapped[date] = mapped_column(Date, nullable=False)
    effective_to: Mapped[date | None] = mapped_column(Date, nullable=True)
    method: Mapped[str] = mapped_column(String(20), nullable=False, default="none", server_default="none")
    template_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    base_period: Mapped[str | None] = mapped_column(String(7), nullable=True)
    fixed_price_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    fixed_part: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    fixed_factor: Mapped[Decimal | None] = mapped_column(Numeric(12, 6), nullable=True)
    series_refs: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    rate_overrides: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict, server_default="{}")  # type: ignore[assignment]
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active", server_default="active")

    def __repr__(self) -> str:
        return f"<FrameworkRatePeriod {self.label} {self.effective_from}>"


class FrameworkAdjustment(Base):
    """A condition adjustment: a multiplier or an addition that a condition tag switches on."""

    __tablename__ = "oe_framework_adjustment"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_contracts_contract.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="multiplier")
    value: Mapped[Decimal] = mapped_column(Numeric(12, 6), nullable=False, default=Decimal("1"))
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="all", server_default="all")
    scope_items: Mapped[list] = mapped_column(JSON, nullable=False, default=list, server_default="[]")  # type: ignore[assignment]
    scope_group: Mapped[str | None] = mapped_column(String(40), nullable=True)
    condition: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<FrameworkAdjustment {self.code} {self.kind} {self.value}>"
