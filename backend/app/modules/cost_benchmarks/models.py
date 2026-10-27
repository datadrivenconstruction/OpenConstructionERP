# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks ORM models.

Tables:
    oe_cost_benchmarks_record  - one completed project (``kind='completed'``) or one
                                 estimate to compare (``kind='estimate'``): final cost,
                                 cost date, GFA, functional units, location, currency.
    oe_cost_benchmarks_element - the cost of one element group of a record.

Every record carries ``tenant_id``; reads filter on it, so one company never sees
another's history. ``project_id`` is a soft link with no foreign key: a record keeps
its numbers when the source project is archived.
"""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import SafeDate
from app.database import GUID, Base


class BenchmarkRecord(Base):
    """A completed project's final cost (or an estimate) on its own basis."""

    __tablename__ = "oe_cost_benchmarks_record"
    __table_args__ = (
        Index("ix_cost_benchmarks_record_tenant_kind", "tenant_id", "kind"),
        Index("ix_cost_benchmarks_record_type_country", "project_type", "country"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="", index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, default="completed", server_default="completed")
    project_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    project_type: Mapped[str] = mapped_column(String(50), nullable=False, default="", server_default="")
    country: Mapped[str] = mapped_column(String(2), nullable=False, default="", server_default="")
    region: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="", server_default="")
    cost_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    standard: Mapped[str] = mapped_column(String(20), nullable=False, default="din276", server_default="din276")
    gfa_m2: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    functional_unit: Mapped[str] = mapped_column(String(30), nullable=False, default="", server_default="")
    functional_units: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_cost: Mapped[Decimal] = mapped_column(
        Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual", server_default="manual")
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata", JSON, nullable=False, default=dict, server_default="{}"
    )

    elements: Mapped[list["BenchmarkElement"]] = relationship(
        back_populates="record", cascade="all, delete-orphan", lazy="selectin", order_by="BenchmarkElement.code"
    )


class BenchmarkElement(Base):
    """The cost of one element group (DIN 276 ``330``, NRM 1 ``2.5``, ...) of a record."""

    __tablename__ = "oe_cost_benchmarks_element"

    record_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_cost_benchmarks_record.id", ondelete="CASCADE"), nullable=False, index=True
    )
    code: Mapped[str] = mapped_column(String(30), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"), server_default="0")

    record: Mapped[BenchmarkRecord] = relationship(back_populates="elements")
