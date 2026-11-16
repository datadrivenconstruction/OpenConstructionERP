# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Tables of the payroll hours export: saved profiles and immutable runs.

A run never changes after it is created. Its rows (``PayrollExportRunLine``) are the signed
hours it handed over; the sum of all run lines per key is what has been exported so far, and
a later change to an approved line shows up as a correction row in the next run.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import SafeDate
from app.database import GUID, Base


class PayrollExportProfile(Base):
    """A saved layout: columns, separators, pay codes per hour type, grouping."""

    __tablename__ = "oe_field_time_payroll_profile"
    __table_args__ = (UniqueConstraint("name", name="uq_oe_field_time_payroll_profile_name"),)

    name: Mapped[str] = mapped_column(String(200), nullable=False)
    # Optional legal entity (soft link: the entity register belongs to another module).
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    is_sample: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    config: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]


class PayrollExportRun(Base):
    """One export, immutable once written."""

    __tablename__ = "oe_field_time_payroll_run"
    __table_args__ = (
        UniqueConstraint("number", name="uq_oe_field_time_payroll_run_number"),
        Index("ix_oe_field_time_payroll_run_period", "period_from", "period_to"),
    )

    number: Mapped[int] = mapped_column(Integer, nullable=False)
    profile_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    profile_name: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    profile_snapshot: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)  # type: ignore[assignment]
    period_from: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    period_to: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    project_ids: Mapped[list] = mapped_column(JSON, nullable=False, default=list)  # type: ignore[assignment]
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    correction_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    worker_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    total_hours: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False, default=Decimal("0"))
    filename: Mapped[str] = mapped_column(String(200), nullable=False, default="", server_default="")
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")
    content: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PayrollExportRunLine(Base):
    """One signed row of a run, stamped with the run id."""

    __tablename__ = "oe_field_time_payroll_run_line"
    __table_args__ = (
        Index("ix_oe_field_time_payroll_run_line_run", "run_id"),
        Index("ix_oe_field_time_payroll_run_line_key", "resource_id", "work_date"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_field_time_payroll_run.id", ondelete="CASCADE"), nullable=False
    )
    resource_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    work_date: Mapped[date] = mapped_column(SafeDate(), nullable=False)
    project_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="", server_default="")
    hour_type: Mapped[str] = mapped_column(String(20), nullable=False, default="regular", server_default="regular")
    hours: Mapped[Decimal] = mapped_column(Numeric(18, 2), nullable=False)
    is_correction: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
