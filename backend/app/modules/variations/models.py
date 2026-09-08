# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Variations & Site Measurements ORM models.

Tables (all prefixed ``oe_variations_``):
    notice                  -- early-warning notice of variation
    variation_request       -- formal request for a variation (pre-issue)
    boq_trace               -- provenance of one line in a request's own bill
    variation_order         -- issued variation order (post-agreement)
    cost_impact             -- VO cost-impact line
    schedule_impact         -- VO schedule-impact line
    site_measurement        -- joint site measurement record
    daywork_sheet           -- signed time-and-material sheet
    daywork_sheet_line      -- daywork sheet line item
    disruption_claim        -- productivity-loss claim
    eot_claim               -- extension-of-time claim
    final_account           -- rolled-up settlement per project
"""

import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db_types import MoneyType
from app.database import GUID, Base


class Notice(Base):
    """Early-warning notice raised to recipient on a project."""

    __tablename__ = "oe_variations_notice"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_variations_notice_project_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raised_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raised_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    recipient_type: Mapped[str] = mapped_column(String(40), nullable=False, default="owner")
    recipient_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    target_response_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    response_received_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    response_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="issued", index=True)
    # Soft link to oe_changeorders_change_order.id (plain UUID, no DB FK)
    reference_change_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Change intelligence: who owes the next action and by when.
    ball_in_court: Mapped[str | None] = mapped_column(String(36), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Notice {self.code} ({self.status})>"


class VariationRequest(Base):
    """Formal variation request submitted for approval."""

    __tablename__ = "oe_variations_request"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_variations_request_project_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    notice_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_notice.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    requested_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    classification: Mapped[str] = mapped_column(String(40), nullable=False, default="scope_change")
    urgency: Mapped[str] = mapped_column(String(20), nullable=False, default="med")
    estimated_cost_impact: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    estimated_schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    submitted_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── The commercial approval boundary (Issue #435) ────────────────────
    # A request carries a headline estimate and may own a priced bill, and
    # the two are allowed to differ while the change is being priced. What
    # nothing recorded was the boundary between them: which pricing state
    # was put in front of the approver, and what the approver actually
    # agreed to. Without both, the agreed value is inherited implicitly
    # from whatever figure happened to be on the request, and a negotiated
    # amount is indistinguishable from a stale headline. Both are plausible
    # numbers of the right order of magnitude, so nothing downstream can
    # tell them apart either.
    #
    # ``submitted_boq_total`` is frozen at submission and never recomputed.
    # The bill goes on being revised afterwards; this column answers what
    # the approver was looking at, not what the bill says today.
    submitted_boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_boq_total: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    #: The bill as it stood at submission, kept as a snapshot in the bill's
    #: own version history (``oe_boq_snapshot``). The total above says what
    #: figure the approver was given; this says which lines, at which
    #: quantities and rates, made that figure up - and it stays readable
    #: after the bill has been revised, which is the normal way a variation
    #: gets negotiated. NULL when there was no bill to submit. No FK, like
    #: ``submitted_boq_id``: the record of what was submitted must not stop
    #: the bill it describes from being deleted.
    submitted_boq_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    #: The commercial amount actually approved. NULL until a decision is
    #: taken, and NULL on every request decided before this existed: putting
    #: a figure there for them would be putting a decision in somebody's
    #: mouth years after the fact.
    agreed_cost_impact: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    #: Why the agreed amount is what it is - ``negotiated`` when a person
    #: named it, ``priced_boq`` when it is the submitted bill's own total,
    #: ``headline_estimate`` when there was no bill to price. Empty until
    #: decided. It exists so "the agreed value equals the bill total" and
    #: "the agreed value was never really decided" cannot look the same.
    agreed_basis: Mapped[str] = mapped_column(String(30), nullable=False, default="", server_default="")
    #: Why an agreed amount departs from the pricing state it was agreed
    #: against. Required when a person names an amount that differs, because
    #: a difference nobody explained is the one this whole boundary exists
    #: to stop being invisible.
    agreed_variance_note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Contract standard + sub-clause reference (FIDIC 13.x / JCT 5.x /
    # NEC4 60-65). Free string so unsupported standards still record.
    contract_standard: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    contract_clause_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    # NEC4 Cl. 62.3 - Contractor's quotation deadline (8 weeks default).
    quotation_due_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # NEC4 Cl. 62.5 - Project Manager's assessment deadline (4 weeks
    # after quotation submitted).
    assessment_due_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Change intelligence: who owes the next action and by when.
    ball_in_court: Mapped[str | None] = mapped_column(String(36), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<VariationRequest {self.code} ({self.status})>"


class VariationBOQTrace(Base):
    """Where one line of a variation request's own bill came from.

    A variation request may own a dedicated bill of quantities holding only
    the scope that variation changes (Issue #435). The bill itself is an
    ordinary ``oe_boq_boq`` row carrying ``variation_request_id``, so it gets
    the whole BOQ module - positions, assemblies, markups, calculation,
    revisions, snapshots, exports - without any of it being reimplemented
    here. What the BOQ module has no place for is *why* a line is in that
    bill, and this table is that answer: one row per line, naming the
    contract schedule-of-values line the change affects and the estimating
    BOQ position the scope was taken from.

    Both references are optional and independent. A line that adds scope
    nobody contracted for has no SoV line; a line invented for the variation
    has no originating position; a line that re-measures a contracted item
    has both. A line that has neither is a hand-entered addition, recorded
    with ``origin='manual'`` rather than left without a row, so the trace
    covers the bill rather than only the parts of it that were derived.

    Every cross-module reference is a plain GUID, not a ForeignKey, the same
    convention ``VariationOrder.affected_contract_id`` and
    ``SiteMeasurement.contract_line_id`` already follow: the variations
    module must not put a DB-level dependency on the BOQ or contracts
    tables. Only ``variation_request_id`` is a real FK, because that row is
    in this module and deleting a request must take its trace with it.

    ``change_kind`` is the other half of provenance. The references say where
    a line came from; this says what the variation does to that source:
    ``added`` scope the contract never held, ``removed`` scope the contract
    holds and the variation omits (a negative quantity against the schedule
    of values), or ``modified`` scope where the same contract line is kept
    at a different quantity or rate. It is stated by the estimator, never
    inferred from the numbers: a negative quantity is consistent with an
    omission and also with a typing error, and only a person knows which.
    The validator reports a kind that contradicts the numbers; it does not
    correct it.
    """

    __tablename__ = "oe_variations_boq_trace"
    __table_args__ = (
        # One trace row per priced line. The line is the thing whose
        # provenance is being recorded, so two rows about it would be two
        # answers to one question.
        UniqueConstraint("position_id", name="uq_oe_variations_boq_trace_position"),
        # "Show me this request's trace" is the only read this table has.
        Index("ix_oe_variations_boq_trace_request_boq", "variation_request_id", "boq_id"),
    )

    variation_request_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_request.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: The variation bill this line lives in (``oe_boq_boq.id``).
    boq_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False, index=True)
    #: The line itself (``oe_boq_position.id``).
    position_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    #: How the line got here: ``boq_position`` (copied from the estimating
    #: bill), ``contract_line`` (taken from the contract schedule of values)
    #: or ``manual`` (entered for this variation and derived from nothing).
    origin: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    #: The estimating bill and position the scope was taken from.
    source_boq_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    source_position_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    #: The contract and schedule-of-values line the change affects.
    contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    contract_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    #: What the variation does to the source: ``added``, ``removed`` or
    #: ``modified``. ``added`` is the default because a line with no trace at
    #: all is added scope, and a row that predates the column has to read
    #: the same way as no row rather than as a claim nobody made.
    change_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="added", server_default="added")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")

    def __repr__(self) -> str:
        return f"<VariationBOQTrace {self.origin}/{self.change_kind} pos={self.position_id}>"


class VariationOrder(Base):
    """Issued variation order - the formal contract-changing document."""

    __tablename__ = "oe_variations_order"
    __table_args__ = (UniqueConstraint("project_id", "code", name="uq_oe_variations_order_project_code"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    variation_request_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_request.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    final_cost_impact: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    final_schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    agreed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    signed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="issued", index=True)
    # Soft link (plain UUID, no DB FK to oe_changeorders_*)
    reference_change_order_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Plain UUID soft link to oe_contracts.contract - set when VO bumps a
    # contract's total_value. NO DB FK across modules.
    affected_contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True, index=True)
    # Contract standard + sub-clause reference (carried through from VR
    # or set explicitly when an Engineer-issued VO has no upstream VR).
    contract_standard: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    contract_clause_ref: Mapped[str] = mapped_column(String(60), nullable=False, default="", server_default="")
    implementation_started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    implementation_completed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Change intelligence: who owes the next action and by when.
    ball_in_court: Mapped[str | None] = mapped_column(String(36), nullable=True)
    response_due_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    cost_impacts: Mapped[list["VariationCostImpact"]] = relationship(
        back_populates="variation_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    schedule_impacts: Mapped[list["VariationScheduleImpact"]] = relationship(
        back_populates="variation_order",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<VariationOrder {self.code} ({self.status})>"


class VariationCostImpact(Base):
    """Cost-impact line within a VariationOrder (labor/material/etc)."""

    __tablename__ = "oe_variations_cost_impact"

    variation_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    category: Mapped[str] = mapped_column(String(40), nullable=False, default="material")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_rate: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")

    variation_order: Mapped[VariationOrder] = relationship(back_populates="cost_impacts")

    def __repr__(self) -> str:
        return f"<VariationCostImpact {self.category} {self.total}>"


class VariationScheduleImpact(Base):
    """Schedule-impact line within a VariationOrder."""

    __tablename__ = "oe_variations_schedule_impact"

    variation_order_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_order.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Free-text reference: a Task id or activity name. No FK to oe_tasks_task.
    affected_activity_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    original_finish_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    revised_finish_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    days_added: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_critical_path: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    justification: Mapped[str] = mapped_column(Text, nullable=False, default="")

    variation_order: Mapped[VariationOrder] = relationship(back_populates="schedule_impacts")

    def __repr__(self) -> str:
        return f"<VariationScheduleImpact {self.affected_activity_ref} +{self.days_added}d>"


class SiteMeasurement(Base):
    """Joint site measurement record (owner/contractor sign-off)."""

    __tablename__ = "oe_variations_site_measurement"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    recorded_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    recorded_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    location: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    item_description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    measured_quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    agreed_with_owner_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_signature_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    photos: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Soft link to oe_contracts_line (plain UUID, no DB FK -- Module 13 optional)
    contract_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    variation_order_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_order.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<SiteMeasurement {self.location} {self.measured_quantity}{self.unit}>"


class DayworkSheet(Base):
    """Daywork sheet -- time-and-material work outside scope.

    BS 6079-1:2019 §6.4.2 - daywork accounting separates labour / plant /
    material with a markup applied for overheads + profit. The
    ``markup_percent`` column stores that markup (typically 10–25%); when
    set, ``total_amount`` includes the markup and ``subtotal_amount``
    stores the pre-markup total for audit.
    """

    __tablename__ = "oe_variations_daywork_sheet"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "sheet_number",
            name="uq_oe_variations_daywork_project_sheet",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    sheet_number: Mapped[str] = mapped_column(String(50), nullable=False)
    work_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subtotal_amount: Mapped[Decimal] = mapped_column(
        MoneyType(), nullable=False, default=Decimal("0"), server_default="0"
    )
    markup_percent: Mapped[Decimal] = mapped_column(
        MoneyType(scale=2), nullable=False, default=Decimal("0"), server_default="0"
    )
    total_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    signed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    signed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_signature_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Plain UUID link to a contract (no DB FK).
    supplied_via_contract_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    lines: Mapped[list["DayworkSheetLine"]] = relationship(
        back_populates="sheet",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<DayworkSheet {self.sheet_number} ({self.status})>"


class DayworkSheetLine(Base):
    """A single labor/material/equipment line on a DayworkSheet."""

    __tablename__ = "oe_variations_daywork_line"

    sheet_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_variations_daywork_sheet.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    line_type: Mapped[str] = mapped_column(String(20), nullable=False, default="labor")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    quantity: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    unit: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    unit_rate: Mapped[Decimal] = mapped_column(MoneyType(scale=6), nullable=False, default=Decimal("0"))
    total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    worker_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    equipment_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    sheet: Mapped[DayworkSheet] = relationship(back_populates="lines")

    def __repr__(self) -> str:
        return f"<DayworkSheetLine {self.line_type} {self.total}>"


class DisruptionClaim(Base):
    """Disruption / productivity-loss claim.

    Measured-mile method (AICPA Construction Audit Guide): compare
    baseline productivity against impacted productivity. The
    ``baseline_productivity`` and ``impacted_productivity`` columns
    capture units / hour for that comparison; ``unit_of_measure`` is
    the unit (m³ / m² / tonne / etc.).
    """

    __tablename__ = "oe_variations_disruption_claim"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raised_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raised_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    claim_period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    root_cause: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cost_amount: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    schedule_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    evidence_refs: Mapped[list] = mapped_column(  # type: ignore[assignment]
        JSON, nullable=False, default=list, server_default="[]"
    )
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    decision_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decided_amount: Mapped[Decimal | None] = mapped_column(MoneyType(), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # AICPA measured-mile fields - units per hour at baseline vs impacted.
    baseline_productivity: Mapped[Decimal | None] = mapped_column(MoneyType(scale=6), nullable=True)
    impacted_productivity: Mapped[Decimal | None] = mapped_column(MoneyType(scale=6), nullable=True)
    unit_of_measure: Mapped[str] = mapped_column(String(30), nullable=False, default="", server_default="")
    labour_hours_lost: Mapped[Decimal | None] = mapped_column(MoneyType(scale=2), nullable=True)

    def __repr__(self) -> str:
        return f"<DisruptionClaim {self.id} ({self.status})>"


class ExtensionOfTimeClaim(Base):
    """Extension of Time (EOT) claim.

    SCL Delay & Disruption Protocol-aligned. ``affected_activity_ref``
    is the schedule-activity that the delay event impacted; ``tia_delta_days``
    holds the days the project completion is forecast to slip after a
    Time-Impact-Analysis (TIA) run.
    """

    __tablename__ = "oe_variations_eot_claim"

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    raised_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    raised_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    claim_period_start: Mapped[str | None] = mapped_column(String(20), nullable=True)
    claim_period_end: Mapped[str | None] = mapped_column(String(20), nullable=True)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    root_cause_category: Mapped[str] = mapped_column(String(40), nullable=False, default="neutral")
    requested_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    granted_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    critical_path_impact: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    decision_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    decision_notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Affected schedule-activity (string ref so we don't FK across module
    # boundary). Either a UUID-string of oe_tasks_task or a free name.
    affected_activity_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    # TIA result - days the project completion is forecast to slip.
    tia_delta_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    tia_computed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Soft back-link to the forensic delay analysis (schedule_advanced T2.2)
    # this claim was raised from. Plain GUID (no FK across module boundary).
    delay_analysis_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    def __repr__(self) -> str:
        return f"<EOTClaim {self.id} req={self.requested_days}d ({self.status})>"


class FinalAccount(Base):
    """Rolled-up final account per project (single row per project)."""

    __tablename__ = "oe_variations_final_account"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            name="uq_oe_variations_final_account_project",
        ),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    original_contract_value: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    variations_total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    daywork_total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    claims_total: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    retention_held: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    retention_released: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    final_value: Mapped[Decimal] = mapped_column(MoneyType(), nullable=False, default=Decimal("0"))
    currency: Mapped[str] = mapped_column(String(10), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(40), nullable=False, default="draft", index=True)
    agreed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    closed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    def __repr__(self) -> str:
        return f"<FinalAccount project={self.project_id} ({self.status})>"
