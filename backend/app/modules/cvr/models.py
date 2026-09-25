# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""CVR (Cost-Value Reconciliation) & Cashflow ORM models.

Tables:
    oe_cvr_report               - a monthly CVR report for a project
    oe_cvr_line                 - one reconciled cost head within a CVR report
    oe_cvr_cashflow_point       - a monthly cash-in / cash-out point for a project
    oe_cvr_payment_application  - an interim payment application (IPA) for a project

Every monetary column is ``NUMERIC(18, 4)`` so the Python layer always sees a
``decimal.Decimal`` (matching the costs module's rate columns). Money is never a
float: values are quantized to 2dp in the service and schemas emit them as
Decimal-as-string on the wire.
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class CvrReport(Base):
    """A monthly Cost-Value Reconciliation report for a project.

    One report per project per period (``YYYY-MM``). All of its lines share the
    report's ``currency`` - the single-currency guard in the service enforces
    that so totals are never summed across currencies.
    """

    __tablename__ = "oe_cvr_report"
    __table_args__ = (
        # One CVR per project per month. A re-issue is an update, not a second
        # row, so the service returns a clean 409 on a duplicate period.
        UniqueConstraint("project_id", "period", name="uq_cvr_report_project_period"),
        Index("ix_cvr_report_project_status", "project_id", "status"),
    )

    # Scoped to a project; the row cascades away with the project it belongs to.
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Reporting period as ``YYYY-MM`` (a commercial CVR is struck monthly).
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Lifecycle: draft | final.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    # ISO 4217 code shared by every line of the report. Empty string until set
    # (mirrors the finance "no silent EUR default" rule - the UI renders amounts
    # without a symbol rather than mislabelling them).
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    lines: Mapped[list["CvrLine"]] = relationship(
        back_populates="report",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<CvrReport {self.period} ({self.status})>"


class CvrLine(Base):
    """A single cost head reconciled within a CVR report.

    ``cost_to_date`` / ``value_to_date`` are the position to date; ``accruals``
    are cost incurred but not yet invoiced; ``forecast_cost`` / ``forecast_value``
    are the anticipated final figures. Margin is derived, never stored.
    """

    __tablename__ = "oe_cvr_line"
    __table_args__ = (Index("ix_cvr_line_report_sort", "report_id", "sort_order"),)

    report_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_cvr_report.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cost_code: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    wbs_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    description: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    cost_to_date: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    value_to_date: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    accruals: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    forecast_cost: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    forecast_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    report: Mapped["CvrReport"] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return f"<CvrLine {self.cost_code} cost={self.cost_to_date} value={self.value_to_date}>"


class CashflowPoint(Base):
    """A monthly cash-in / cash-out point on a project's cashflow curve.

    One point per project per period. The cumulative S-curve is derived by
    running-summing these in period order (see ``compute.cumulative_series``).
    """

    __tablename__ = "oe_cvr_cashflow_point"
    __table_args__ = (UniqueConstraint("project_id", "period", name="uq_cvr_cashflow_project_period"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    cash_in: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    cash_out: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    label: Mapped[str | None] = mapped_column(String(255), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<CashflowPoint {self.period} in={self.cash_in} out={self.cash_out}>"


class PaymentApplication(Base):
    """An interim payment application (IPA) raised for a project period.

    ``net_value`` is always ``gross_value - retention`` (clamped at zero); the
    service recomputes it on every write so the three figures can never drift
    apart.
    """

    __tablename__ = "oe_cvr_payment_application"
    __table_args__ = (Index("ix_cvr_payapp_project_status", "project_id", "status"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    application_number: Mapped[str | None] = mapped_column(String(50), nullable=True)
    gross_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    retention: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    net_value: Mapped[Decimal] = mapped_column(Numeric(18, 4), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    # Lifecycle: draft | submitted | certified | paid.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The contract progress claim this application was raised from, if any.
    # Plain GUID with no foreign key, like every cross-module link: the claims
    # table belongs to the contracts module. The service checks that the claim
    # exists and sits under a contract of the same project.
    progress_claim_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<PaymentApplication {self.application_number or self.period} ({self.status})>"
