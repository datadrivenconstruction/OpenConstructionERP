"""‌⁠‍Subcontractor ORM models.

Tables:
    oe_subcontractors_subcontractor              — legal entity
    oe_subcontractors_subcontractor_contact      — point of contact (FK subcontractor)
    oe_subcontractors_prequalification           — onboarding application
    oe_subcontractors_certificate                — insurance / license / iso / etc.
    oe_subcontractors_agreement                  — master contract per project
    oe_subcontractors_work_package               — scope of work under an agreement
    oe_subcontractors_payment_application        — periodic payment claim
    oe_subcontractors_payment_application_line   — line under a payment application
    oe_subcontractors_retention_ledger           — retention accrual / release entries
    oe_subcontractors_rating                     — monthly rating rollup
    oe_subcontractors_lien_waiver                — uploaded lien waiver / W-9 form
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class Subcontractor(Base):
    """‌⁠‍Legal subcontractor entity (may be linked to a Contact row)."""

    __tablename__ = "oe_subcontractors_subcontractor"

    # FK declared in alembic migration only; ORM-level FK omitted to avoid
    # metadata-level cross-module coupling in test fixtures.
    contact_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
        index=True,
    )
    legal_name: Mapped[str] = mapped_column(String(255), nullable=False)
    trade_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    tax_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    trade_categories: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    prequalification_status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
    )
    rating_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    country: Mapped[str | None] = mapped_column(String(2), nullable=True)
    address: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # type: ignore[assignment]
    website: Mapped[str | None] = mapped_column(String(500), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # ── Wave 4 / T12: BuildingConnected-style prequal + insurance tracking ──
    # All nullable so legacy rows (created before v3093) still load.
    prequal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    insurance_expiry_date: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
        index=True,
    )
    insurance_doc_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        nullable=True,
    )
    prequal_questionnaire: Mapped[dict | None] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=True,
    )
    prequal_completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    blocked_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_blocked: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default="0",
    )
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Subcontractor {self.legal_name} ({self.prequalification_status})>"


class SubcontractorContact(Base):
    """‌⁠‍Point of contact for a subcontractor."""

    __tablename__ = "oe_subcontractors_subcontractor_contact"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<SubcontractorContact {self.name} ({self.role or '-'})>"


class PrequalificationApplication(Base):
    """Subcontractor prequalification application."""

    __tablename__ = "oe_subcontractors_prequalification"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    answers: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    reviewer_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    def __repr__(self) -> str:
        return f"<PrequalificationApplication sub={self.subcontractor_id} ({self.status})>"


class Certificate(Base):
    """A certificate held by a subcontractor (insurance / license / iso / safety / bond)."""

    __tablename__ = "oe_subcontractors_certificate"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    cert_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    issued_by: Mapped[str | None] = mapped_column(String(255), nullable=True)
    issue_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True, index=True)
    document_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="valid",
        index=True,
    )
    revoked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Certificate {self.cert_type} valid_until={self.valid_until} ({self.status})>"


class SubcontractAgreement(Base):
    """Master contract between GC and subcontractor on a project."""

    __tablename__ = "oe_subcontractors_agreement"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    total_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    retention_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("5.0"),
        server_default="5.0",
    )
    retention_release_event: Mapped[str | None] = mapped_column(String(120), nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SubcontractAgreement {self.title!r} ({self.status})>"


class WorkPackage(Base):
    """Scope of work under a subcontract agreement."""

    __tablename__ = "oe_subcontractors_work_package"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_agreement.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    scope: Mapped[str | None] = mapped_column(Text, nullable=True)
    planned_value: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    completion_percent: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="planned",
        index=True,
    )

    def __repr__(self) -> str:
        return f"<WorkPackage {self.name!r} ({self.status})>"


class PaymentApplication(Base):
    """Periodic payment application against an agreement."""

    __tablename__ = "oe_subcontractors_payment_application"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_agreement.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    application_number: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    period_end: Mapped[date | None] = mapped_column(Date, nullable=True)
    gross_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    retention_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    net_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="submitted",
        index=True,
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    foreman_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    foreman_approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    finance_approved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    finance_approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<PaymentApplication {self.application_number} ({self.status})>"


class PaymentApplicationLine(Base):
    """Line item under a payment application, mapped to a work package."""

    __tablename__ = "oe_subcontractors_payment_application_line"

    payment_application_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_payment_application.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    work_package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_work_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claimed_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    certified_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    approved_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )

    def __repr__(self) -> str:
        return f"<PaymentApplicationLine wp={self.work_package_id} approved={self.approved_amount}>"


class RetentionLedger(Base):
    """Retention accrual / release ledger entry."""

    __tablename__ = "oe_subcontractors_retention_ledger"

    agreement_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_agreement.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_payment_application.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    accrued_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    released_amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    release_reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return (
            f"<RetentionLedger agreement={self.agreement_id} "
            f"accrued={self.accrued_amount} released={self.released_amount}>"
        )


class SubcontractorRating(Base):
    """Monthly rating rollup for a subcontractor."""

    __tablename__ = "oe_subcontractors_rating"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    period: Mapped[str] = mapped_column(String(7), nullable=False)  # "YYYY-MM"
    quality_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    hse_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    schedule_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    cost_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    overall_score: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    basis: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<SubcontractorRating sub={self.subcontractor_id} period={self.period} overall={self.overall_score}>"


class LienWaiver(Base):
    """A lien-waiver / W-9 / W-8 form filed against a payment application.

    Per US lien-law practice, every payment to a subcontractor must be
    accompanied by a signed lien waiver (conditional / unconditional,
    partial / final). We persist the uploaded PDF/PNG/JPEG/TIFF with a
    magic-byte gate at upload time and link it back to both the
    subcontractor and the specific payment application it covers.

    ``payment_application_id`` is nullable so a stand-alone W-9 / W-8
    upload (no payment-app linkage) can be filed against the
    subcontractor as a whole, with ``waiver_type='w9'`` or ``'w8'``.
    """

    __tablename__ = "oe_subcontractors_lien_waiver"

    subcontractor_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_subcontractors_subcontractor.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    payment_application_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey(
            "oe_subcontractors_payment_application.id",
            ondelete="SET NULL",
        ),
        nullable=True,
        index=True,
    )
    # Conditional / unconditional, partial / final, w9 (US), w8 (intl).
    waiver_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # Document path under uploads/ — populated by the magic-byte-gated
    # upload endpoint, NEVER by the create-from-URL path (which would
    # let a caller smuggle a remote URL into the storage column).
    document_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    # IANA mime-type derived from the detected signature, not the
    # attacker-controlled Content-Type header.
    mime_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    file_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signed_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Amount the waiver covers — informational; the actual money flows
    # through the payment_application row. Stored as Numeric(18,2)
    # like every other money column in the module.
    amount: Mapped[Decimal] = mapped_column(
        Numeric(18, 2),
        nullable=False,
        default=Decimal("0"),
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, server_default="")
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    uploaded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<LienWaiver sub={self.subcontractor_id} type={self.waiver_type} amount={self.amount}>"


# OCR auto-extraction hook stub: deferred per Module 4 backend scope.
# When implemented, parse certificate PDFs and populate Certificate fields.
async def ocr_extract_certificate_hook(  # pragma: no cover - stub
    document_url: str,
    cert_type: str,
) -> dict:
    """Stub for OCR-based certificate field auto-extraction.

    Args:
        document_url: URL or path to the uploaded certificate.
        cert_type: Type of certificate (insurance/license/iso/safety/bond).

    Returns:
        Empty dict — real implementation populates issuer / dates / numbers.
    """
    return {}
