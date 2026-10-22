# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Procurement concept ORM models.

Tables (all prefixed ``oe_procurement_concept_``):
    concept          -- one per project: pinned catalogue, jurisdiction, client type, lifecycle
    award_package    -- 1:1 procurement attributes of one mod3 ContractPackage
    prequal_profile  -- criteria and weights, per package or as the concept default
    candidate        -- a company considered for a package (long / short / excluded)
    candidate_score  -- one criterion score of a candidate, with evidence refs
    reference        -- a project reference of a candidate
    sounding         -- a market sounding entry with its capacity signal
    framework        -- a tenant-level framework agreement (outlives projects)

The package identity (code, title, scope, kind, who designs/builds/supplies,
execution link) lives on mod3's ``ContractPackage`` (``oe_delivery_model_package``)
and is never copied here. ``award_package.contract_package_id`` is its id and
the primary key of this row; it is a soft link without a database foreign key
because module 3 ships in its own revision (the lead may add the FK at merge).

Constraint and index names are written out (``*_oe_pcc_*``) and the migration
uses the same strings. No ``relationship()``: the repository loads explicitly.
Calendar days are ISO strings (``String(40)``) as elsewhere; money is exact.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    event,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db_types import MoneyType
from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"
_CANDIDATE_FK = "oe_procurement_concept_candidate.id"


def _money() -> MoneyType:
    return MoneyType(18, 2)


def _project_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class ProcurementConcept(Base):
    """The project's award concept. ``binding`` is read from governance, never written here."""

    __tablename__ = "oe_procurement_concept_concept"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_pcc_concept_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_concept_project")
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    client_type: Mapped[str] = mapped_column(String(20), nullable=False, default="private")
    public_client: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    vat_rate_pct: Mapped[Decimal] = mapped_column(Numeric(5, 2), nullable=False, default=Decimal("0"))
    # draft | in_review | approved (binding and reopened are derived from governance)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    # The frame document that hosts procurement (project_governance is a declared dependency).
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_pcc_concept_gov_document"),
        nullable=True,
    )
    # Gate whose decision releases procurement (rule 11). Empty = the gate into the phase the governance
    # catalogue tags as releasing procurement, resolved on every read.
    release_gate_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    default_profile_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class AwardPackage(Base):
    """Procurement attributes of one ContractPackage; ``id`` IS the ContractPackage id."""

    __tablename__ = "oe_procurement_concept_award_package"
    __table_args__ = (
        Index("ix_oe_pcc_award_project", "project_id"),
        Index("ix_oe_pcc_award_framework", "framework_agreement_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_award_project")
    # trade | section | system | whole
    split_basis: Mapped[str] = mapped_column(String(20), nullable=False, default="whole")
    is_advance: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    advance_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # gate_decision | condition: the governance act that releases an advance package (rule 12)
    advance_release_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    advance_release_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    estimated_value: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    # Soft link to the cost basis: cost_line | boq_section | budget_line
    cost_ref_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cost_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    lot_group: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    small_lot_exemption: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    procedure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # detailed | functional | mixed
    tender_basis: Mapped[str | None] = mapped_column(String(20), nullable=True)
    framework_agreement_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # lowest_price | best_value
    evaluation_method: Mapped[str] = mapped_column(String(20), nullable=False, default="lowest_price")
    # {"price": "60", "quality": "40"} for best_value
    evaluation_weights: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    need_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    need_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    procedure_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    planned_start: Mapped[str | None] = mapped_column(String(40), nullable=True)
    prequal_profile_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Schedule activities a human confirmed from the backward pass (rule 11, Decision 7).
    start_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    award_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    state_before: Mapped[str | None] = mapped_column(String(20), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class PrequalProfile(Base):
    """Criteria picked from the catalogue with weights; ``package_id`` null = the concept default."""

    __tablename__ = "oe_procurement_concept_prequal_profile"
    __table_args__ = (Index("ix_oe_pcc_profile_project", "project_id", "package_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_profile_project")
    package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # [{"code", "kind": pass_fail|scored, "weight": "25"}]
    criteria: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    pass_mark: Mapped[Decimal] = mapped_column(Numeric(6, 2), nullable=False, default=Decimal("0"))
    validity_months: Mapped[int] = mapped_column(Integer, nullable=False, default=12)


class BidderCandidate(Base):
    """A company considered for one award package."""

    __tablename__ = "oe_procurement_concept_candidate"
    __table_args__ = (
        Index("ix_oe_pcc_candidate_package", "project_id", "package_id"),
        UniqueConstraint("package_id", "subcontractor_id", name="uq_oe_pcc_candidate_sub"),
        UniqueConstraint("package_id", "vendor_id", name="uq_oe_pcc_candidate_vendor"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_candidate_project")
    package_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # Only while neither company record exists yet; must be registered before shortlisting.
    free_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # market_sounding | own_list | framework | public_notice
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="own_list")
    # long | short | excluded
    list_kind: Mapped[str] = mapped_column(String(10), nullable=False, default="long")
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    conflict_of_interest_declared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    conflict_note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CandidateScore(Base):
    """One criterion of one candidate: a pass/fail verdict or a 0..100 score, with evidence refs."""

    __tablename__ = "oe_procurement_concept_candidate_score"
    __table_args__ = (UniqueConstraint("candidate_id", "criterion_code", name="uq_oe_pcc_score"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_CANDIDATE_FK, ondelete="CASCADE", name="fk_oe_pcc_score_candidate"), nullable=False
    )
    criterion_code: Mapped[str] = mapped_column(String(64), nullable=False)
    passed: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    # [{"kind": certificate|prequal_application|rating|reference|document, "id": "..."}]
    evidence: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    scored_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class ProjectReference(Base):
    """A reference project a candidate names."""

    __tablename__ = "oe_procurement_concept_reference"
    __table_args__ = (Index("ix_oe_pcc_reference_candidate", "candidate_id"),)

    candidate_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey(_CANDIDATE_FK, ondelete="CASCADE", name="fk_oe_pcc_reference_candidate"), nullable=False
    )
    project_name: Mapped[str] = mapped_column(String(255), nullable=False)
    client: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    value: Mapped[Decimal | None] = mapped_column(_money(), nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    year: Mapped[int | None] = mapped_column(Integer, nullable=True)
    role: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    contact: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    verified_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MarketSounding(Base):
    """A light log entry of one market sounding (Decision 8), for one package or a group."""

    __tablename__ = "oe_procurement_concept_sounding"
    __table_args__ = (Index("ix_oe_pcc_sounding_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_sounding_project")
    # Award package ids this sounding covers (one package or a trade group).
    package_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    trade: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    held_on: Mapped[str] = mapped_column(String(40), nullable=False)
    # survey | meeting | rfi | notice
    method: Mapped[str] = mapped_column(String(10), nullable=False, default="meeting")
    participant_candidate_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    findings: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ample | adequate | tight | insufficient
    capacity_signal: Mapped[str] = mapped_column(String(20), nullable=False, default="adequate")
    # below_estimate | in_line | above_estimate | unknown
    price_signal: Mapped[str] = mapped_column(String(20), nullable=False, default="unknown")
    lead_time_signal_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mitigation: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resplit: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class FrameworkAgreement(Base):
    """A framework agreement of a company (tenant), called off by packages of any of its projects."""

    __tablename__ = "oe_procurement_concept_framework"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_oe_pcc_framework_code"),
        Index("ix_oe_pcc_framework_tenant", "tenant_id", "state"),
    )

    tenant_id: Mapped[str] = mapped_column(String(64), nullable=False)
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    subcontractor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    vendor_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    supplier_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Package kinds the scope covers (design | works | supply | supply_and_install | services).
    package_kinds: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    lots: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    max_value: Mapped[Decimal] = mapped_column(_money(), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    start_date: Mapped[str] = mapped_column(String(40), nullable=False)
    end_date: Mapped[str] = mapped_column(String(40), nullable=False)
    # direct | mini_competition
    call_off_mode: Mapped[str] = mapped_column(String(20), nullable=False, default="direct")
    source_procedure_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class RuleSnapshot(Base):
    """Frozen record of the rules evaluated when a package's procedure was set (never updated)."""

    __tablename__ = "oe_procurement_concept_rule_snapshot"
    __table_args__ = (Index("ix_oe_pcc_snapshot_package", "project_id", "package_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_snapshot_project")
    package_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    procedure_code: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False)
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # The day the thresholds were tested on (the planned procedure start), ISO.
    checked_on: Mapped[str] = mapped_column(String(40), nullable=False)
    # Value, currency, contract kind, client, jurisdiction, procedure: what the rules were given.
    inputs: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # Every rule applied: id, source, review status, effective dates, figure.
    rules: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Status, allowed procedures, findings and one outcome per rule.
    result: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # sha256 of the canonical content: a changed row is detectable.
    digest: Mapped[str] = mapped_column(String(64), nullable=False)
    taken_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class RuleOverride(Base):
    """A person's override of one rule outcome of a snapshot; the reason is mandatory."""

    __tablename__ = "oe_procurement_concept_rule_override"
    __table_args__ = (Index("ix_oe_pcc_override_snapshot", "snapshot_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_pcc_override_project")
    snapshot_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_procurement_concept_rule_snapshot.id", ondelete="CASCADE", name="fk_oe_pcc_override_snapshot"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(64), nullable=False)
    original_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    override_outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    overridden_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    overridden_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


@event.listens_for(RuleSnapshot, "before_update")
def _snapshot_is_frozen(*_: Any) -> None:
    raise ValueError("a rule snapshot is frozen")


# Not in ALL_MODELS: that tuple is what revision v72 builds.
SNAPSHOT_MODELS: tuple[type[Base], ...] = (RuleSnapshot, RuleOverride)


ALL_MODELS: tuple[type[Base], ...] = (
    ProcurementConcept,
    AwardPackage,
    PrequalProfile,
    BidderCandidate,
    CandidateScore,
    ProjectReference,
    MarketSounding,
    FrameworkAgreement,
)
