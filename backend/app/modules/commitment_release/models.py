# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Commitment and release matrix ORM models.

Tables (all prefixed ``oe_commitment_``):
    matrix       -- one per project: pinned authority schedule, enforcement, FX policy, tier routes
    assignment   -- who fills a ``project_role`` tier on this project, and when
    item         -- one planned or existing commitment and its release state
    link         -- a document (contract, PO, change, ...) counted in exactly one item
    precondition -- what must hold before a release; linked kinds are computed on read
    release      -- a release request and, once decided, its immutable decision
    abort_terms  -- how stopping the item (or one of its links) would be settled
    scenario     -- a saved snapshot of a computed abort exposure, for reporting

The module stores no amount of a contract, PO, change or budget: those are read
from their own modules through ``costmodel`` and the documents. The only stored
estimate is ``planned_manual_amount`` on an item whose planned source is
``manual`` (used before any budget exists, flagged as such).

Constraint and index names are written out and short (``*_oe_cmt_*``), and the
migration uses the same strings. There are no ``relationship()`` declarations:
rows reference each other by id and the repository loads what a request needs,
so no lazy load can fire from async code. Soft references into other modules
carry no foreign key.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"
_ITEM_FK = "oe_commitment_item.id"


def _money() -> MoneyType:
    return MoneyType(18, 4)


class CommitmentMatrix(Base):
    """The project's matrix settings. ``base_currency`` is read from the project, never stored."""

    __tablename__ = "oe_commitment_matrix"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_cmt_matrix_project"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_matrix_project"), nullable=False
    )
    # shipped | tenant
    schedule_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    schedule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # off | warn | block
    enforcement: Mapped[str] = mapped_column(String(10), nullable=False, default="warn")
    # Under block: refuse documents that are in no item at all.
    require_link: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # fx_service_rate_set | project_rates
    fx_policy: Mapped[str] = mapped_column(String(30), nullable=False, default="fx_service_rate_set")
    # {tier_code: route_id}; soft links to approval_routes.Route.
    tier_routes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # {tier_code: {"route_id", "fingerprint"}} of routes this module generated,
    # so a regeneration can tell a route a manager edited since.
    generated_routes: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class AuthorityAssignment(Base):
    """Who fills a ``project_role`` tier on this project. Absence is a Delegation, not a row here."""

    __tablename__ = "oe_commitment_assignment"
    __table_args__ = (
        UniqueConstraint("project_id", "project_role", "user_id", name="uq_oe_cmt_assignment"),
        Index("ix_oe_cmt_assignment_role", "project_id", "project_role"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_assignment_project"), nullable=False
    )
    project_role: Mapped[str] = mapped_column(String(64), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    deputy_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_to: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CommitmentItem(Base):
    """One commitment of the matrix: what, how much is planned, who decides by when."""

    __tablename__ = "oe_commitment_item"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_cmt_item_code"),
        Index("ix_oe_cmt_item_status", "project_id", "status"),
        Index("ix_oe_cmt_item_gate", "project_id", "gate_code"),
        Index("ix_oe_cmt_item_group", "project_id", "split_group"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_item_project"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    commitment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    # The state a request or a hold returns to.
    status_before: Mapped[str | None] = mapped_column(String(30), nullable=True)
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # Novelty flags set on the item (e.g. novel_contentious, multi_year_commitment).
    flags: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    cost_line_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    control_account_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    cost_bearer_legal_entity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    funding_application_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    risk_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    governance_area_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gate_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    deferred: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    deferred_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    split_group: Mapped[str | None] = mapped_column(String(64), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # budget_line | cost_line | boq_position | manual
    planned_source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    planned_source_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    planned_manual_amount: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    need_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    requisition_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Soft link to an item of the plant register (an optional module, so no foreign key). When
    # set, the lead time and the latest order date are the register's, not this row's.
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    decision_buffer_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latest_decision_date_fixed: Mapped[str | None] = mapped_column(String(40), nullable=True)
    transferred_to_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class CommitmentLink(Base):
    """A document counted in one item. Unique per project: a document counts once. No amount stored."""

    __tablename__ = "oe_commitment_link"
    __table_args__ = (
        UniqueConstraint("project_id", "kind", "target_id", name="uq_oe_cmt_link_document"),
        Index("ix_oe_cmt_link_item", "item_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_link_project"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_ITEM_FK, ondelete="CASCADE", name="fk_oe_cmt_link_item"), nullable=False
    )
    # contract | contract_line | purchase_order | change_order | variation_order | tender_package | bid_package | rfq
    # | contingency_drawdown
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    # The id of the contract, PO, change, award ... that ``kind`` names; never a CDE
    # document (so not one of the document references the delete prompt asks about).
    target_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)

    @property
    def document_id(self) -> uuid.UUID:
        """The API's name for :attr:`target_id`."""
        return self.target_id


class CommitmentPrecondition(Base):
    """A precondition of an item. Only ``manual`` and evidence kinds store a tick; linked kinds compute."""

    __tablename__ = "oe_commitment_precondition"
    __table_args__ = (Index("ix_oe_cmt_precondition_item", "item_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_precondition_project"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_ITEM_FK, ondelete="CASCADE", name="fk_oe_cmt_precondition_item"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    ref_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # open | met (stored for manual kinds only)
    state: Mapped[str] = mapped_column(String(10), nullable=False, default="open")
    evidence_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ReleaseDecision(Base):
    """A release request and its decision.

    Written once on request with ``outcome = pending`` and once more when the
    route decides or the requester withdraws; after that the row is frozen
    (the service refuses every further write, see ``_freeze``). Amounts, the
    FX rate and its date, the required tier and the schedule version are
    captured at request time and never recomputed.
    """

    __tablename__ = "oe_commitment_release"
    __table_args__ = (
        UniqueConstraint("item_id", "attempt", name="uq_oe_cmt_release_attempt"),
        Index("ix_oe_cmt_release_item", "item_id"),
        Index("ix_oe_cmt_release_instance", "approval_instance_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_release_project"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_ITEM_FK, ondelete="CASCADE", name="fk_oe_cmt_release_item"), nullable=False
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    requested_amount: Mapped[Decimal] = mapped_column(_money(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    schedule_currency: Mapped[str] = mapped_column(String(3), nullable=False)
    amount_in_schedule_currency: Mapped[Decimal] = mapped_column(_money(), nullable=False)
    fx_rate_used: Mapped[str] = mapped_column(String(40), nullable=False, default="1")
    fx_rate_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    fx_source: Mapped[str] = mapped_column(String(30), nullable=False, default="same_currency")
    evaluated_amount: Mapped[Decimal] = mapped_column(_money(), nullable=False)
    cumulative_after: Mapped[Decimal] = mapped_column(_money(), nullable=False)
    required_tier: Mapped[str | None] = mapped_column(String(40), nullable=True)
    escalate_outside: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    external_approval_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    schedule_source: Mapped[str] = mapped_column(String(20), nullable=False)
    schedule_id: Mapped[str] = mapped_column(String(64), nullable=False)
    schedule_version: Mapped[int] = mapped_column(Integer, nullable=False)
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # release = money may be bound; abort = the item may be stopped (SPEC rule 15). An abort is decided
    # on the same routes and never counts as released money.
    purpose: Mapped[str] = mapped_column(String(12), nullable=False, default="release")
    # pending | released | aborted | rejected | withdrawn
    outcome: Mapped[str] = mapped_column(String(12), nullable=False, default="pending")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    on_behalf_of: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Linked document ids and amounts, precondition states, tier evaluation.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    tranche_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conditions: Mapped[str] = mapped_column(Text, nullable=False, default="")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    valid_until: Mapped[str | None] = mapped_column(String(40), nullable=True)


class AbortTerms(Base):
    """How stopping an item, or one of its links, would be settled. ``scope`` = ``item`` or a link id."""

    __tablename__ = "oe_commitment_abort_terms"
    __table_args__ = (UniqueConstraint("item_id", "scope", name="uq_oe_cmt_abort_scope"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_abort_project"), nullable=False
    )
    item_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_ITEM_FK, ondelete="CASCADE", name="fk_oe_cmt_abort_item"), nullable=False
    )
    scope: Mapped[str] = mapped_column(String(40), nullable=False, default="item")
    basis_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    basis_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    basis_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # [{milestone, from_date?, progress_pct?, charge_amount?, charge_pct?}]
    cancellation_schedule: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Overrides of basis parameters taken from the contract (e.g. fee_pct).
    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # no | to_project | resale
    transferable: Mapped[str] = mapped_column(String(20), nullable=False, default="no")
    transfer_value_estimate: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    salvage_value_estimate: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    saved_cost_estimate: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    other_charge_estimate: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    progress_pct: Mapped[Decimal | None] = mapped_column(MoneyType(9, 6), nullable=True)
    notice_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    entered_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    entered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AbortScenario(Base):
    """A saved snapshot of the computed abort exposure on one date (the live figure is always computed)."""

    __tablename__ = "oe_commitment_scenario"
    __table_args__ = (Index("ix_oe_cmt_scenario_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name="fk_oe_cmt_scenario_project"), nullable=False
    )
    as_of: Mapped[str] = mapped_column(String(40), nullable=False)
    label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


ALL_MODELS = (
    CommitmentMatrix,
    AuthorityAssignment,
    CommitmentItem,
    CommitmentLink,
    CommitmentPrecondition,
    ReleaseDecision,
    AbortTerms,
    AbortScenario,
)
