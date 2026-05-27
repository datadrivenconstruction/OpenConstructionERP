"""‌⁠‍Bid Management ORM models.

Tables:
    oe_bid_management_package           — bid packages (formal RFx)
    oe_bid_management_line_item         — scope line items inside a package
    oe_bid_management_invitation        — invitation to a bidder
    oe_bid_management_bidder            — denormalised bidder snapshot
    oe_bid_management_submission        — submitted envelope from a bidder
    oe_bid_management_submission_line   — priced line in a submission
    oe_bid_management_qa                — Q&A thread on a package
    oe_bid_management_comparison        — leveling header (one per package)
    oe_bid_management_leveling          — per-bidder leveling row
    oe_bid_management_award             — award decision (one per package)
    oe_bid_management_rejection         — formal rejection record

All cross-module references (tender_id, contact_id, subcontractor_id,
contract_template_ref) are plain UUID / string columns — no SQLAlchemy
ForeignKey crossing module boundaries.
"""

from __future__ import annotations

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import GUID, Base


class BidPackage(Base):
    """‌⁠‍A formal bid package (RFx) belonging to a project."""

    __tablename__ = "oe_bid_management_package"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain UUID — references oe_tendering_tender.id but no FK so the
    # tendering module can be reorganised/swapped without breaking us.
    tender_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    scope_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instructions_to_bidders: Mapped[str] = mapped_column(Text, nullable=False, default="")
    submission_deadline: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_due_by: Mapped[str | None] = mapped_column(String(40), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    total_budget_estimate: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="draft",
        index=True,
        server_default="draft",
    )
    confidentiality_level: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="limited",
        server_default="limited",
    )
    published_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    awarded_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    line_items: Mapped[list[BidPackageLineItem]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    invitations: Mapped[list[BidInvitation]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="raise",
    )
    bidders: Mapped[list[Bidder]] = relationship(
        back_populates="package",
        cascade="all, delete-orphan",
        lazy="raise",
    )

    def __repr__(self) -> str:
        return f"<BidPackage {self.code} ({self.status})>"


class BidPackageLineItem(Base):
    """‌⁠‍A single line of scope inside a bid package."""

    __tablename__ = "oe_bid_management_line_item"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    quantity: Mapped[str] = mapped_column(
        Numeric(18, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    alternative_allowed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    order_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    parent_line_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_line_item.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    spec_attachment_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    is_mandatory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    package: Mapped[BidPackage] = relationship(back_populates="line_items")

    def __repr__(self) -> str:
        return f"<BidPackageLineItem {self.code} qty={self.quantity}>"


class BidInvitation(Base):
    """Invitation extended to a single bidder for a package."""

    __tablename__ = "oe_bid_management_invitation"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Plain UUID — references oe_subcontractors_subcontractor.id OR
    # oe_contacts_contact.id, no FK.
    bidder_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    invitee_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    invitee_company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    sent_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    opened_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    submission_received_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    declined_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decline_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="pending",
        index=True,
        server_default="pending",
    )
    token_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)

    package: Mapped[BidPackage] = relationship(back_populates="invitations")

    def __repr__(self) -> str:
        return f"<BidInvitation {self.invitee_email} ({self.status})>"


class Bidder(Base):
    """Denormalised snapshot of a bidder participating in a package."""

    __tablename__ = "oe_bid_management_bidder"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    company_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    contact_phone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    country: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    status: Mapped[str] = mapped_column(
        String(32),
        nullable=False,
        default="active",
        index=True,
        server_default="active",
    )
    disqualification_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")

    package: Mapped[BidPackage] = relationship(back_populates="bidders")

    def __repr__(self) -> str:
        return f"<Bidder {self.company_name} ({self.status})>"


class BidSubmission(Base):
    """A submitted envelope from a bidder."""

    __tablename__ = "oe_bid_management_submission"

    invitation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_invitation.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    total_amount: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    completeness_score: Mapped[str] = mapped_column(
        Numeric(5, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    notes_to_owner: Mapped[str] = mapped_column(Text, nullable=False, default="")
    exclusions: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    qualifications: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )
    is_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    open_after_deadline: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    envelope_payload: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<BidSubmission inv={self.invitation_id} total={self.total_amount}>"


class BidSubmissionLine(Base):
    """A priced line within a bid submission."""

    __tablename__ = "oe_bid_management_submission_line"

    submission_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_submission.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_line_item.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    unit_price: Mapped[str] = mapped_column(
        Numeric(18, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    quantity_priced: Mapped[str] = mapped_column(
        Numeric(18, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    total_price: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    alternative_offered: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    alternative_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Bid-leveling inclusion taxonomy ("included", "excluded",
    # "clarification_needed", "alternative", "noted"). Drives the
    # leveling matrix flag column the PM uses to normalize bids.
    inclusion_status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="included", server_default="included"
    )
    # US public works flag — Davis-Bacon Act 40 USC 3142 / state
    # prevailing wage laws. Auditable per submission line.
    prevailing_wage_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    def __repr__(self) -> str:
        return f"<BidSubmissionLine sub={self.submission_id} total={self.total_price}>"


class BidQA(Base):
    """A Q&A thread entry on a package."""

    __tablename__ = "oe_bid_management_qa"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bidder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    asked_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    asked_by_email: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answered_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # No FK to users — keeps the module decoupled.
    answered_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_public: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    visible_to_bidder_ids: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=list,
        server_default="[]",
    )

    def __repr__(self) -> str:
        return f"<BidQA package={self.package_id} public={self.is_public}>"


class BidComparison(Base):
    """Leveling header — one per package, holds scoring rule + recommendation."""

    __tablename__ = "oe_bid_management_comparison"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    computed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    normalized_low: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    normalized_high: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    technical_scoring_rule: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )
    commercial_weight_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=100, server_default="100")
    technical_weight_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    recommended_bidder_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="SET NULL"),
        nullable=True,
    )
    recommended_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<BidComparison package={self.package_id}>"


class BidLeveling(Base):
    """Per-bidder leveling row within a comparison."""

    __tablename__ = "oe_bid_management_leveling"

    comparison_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_comparison.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raw_total: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    normalized_total: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    commercial_score: Mapped[str] = mapped_column(
        Numeric(8, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    technical_score: Mapped[str] = mapped_column(
        Numeric(8, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    total_score: Mapped[str] = mapped_column(
        Numeric(8, 4),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    manual_adjustment: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    manual_adjustment_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")

    def __repr__(self) -> str:
        return f"<BidLeveling bidder={self.bidder_id} rank={self.rank}>"


class BidAward(Base):
    """Award decision — one per package."""

    __tablename__ = "oe_bid_management_award"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    awarded_bidder_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    awarded_amount: Mapped[str] = mapped_column(
        Numeric(18, 2),  # type: ignore[arg-type]
        nullable=False,
        default=0,
        server_default="0",
    )
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    decision_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # No FK to users — plain UUID/string.
    decision_signed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    decision_signed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Plain string — references a template id from documents/contracts module.
    contract_template_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    notified_others_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:
        return f"<BidAward package={self.package_id} amount={self.awarded_amount}>"


class BidRejection(Base):
    """A formal rejection record for non-awarded bidders."""

    __tablename__ = "oe_bid_management_rejection"

    package_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_package.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    bidder_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_bid_management_bidder.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    rejection_code: Mapped[str] = mapped_column(String(32), nullable=False, default="other")
    rejection_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    notified_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:
        return f"<BidRejection package={self.package_id} bidder={self.bidder_id}>"
