# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Delivery model ORM models.

Tables (all prefixed ``oe_delivery_model_``):
    model       -- one per project: pinned delivery forms catalogue, chosen form, status
    option      -- a candidate form in the comparison
    criterion   -- a decision criterion with its weight (weights sum to 100)
    score       -- (option, criterion) score 1..5 with rationale; totals are computed on read
    decision    -- a proposed decision and its frozen snapshot; approved only through governance
    allocation  -- who carries one risk category, on what basis, and why
    package     -- the package plan: the one place that says who designs, builds, supplies
    ofi         -- an owner-furnished item, its procurement route and installing package
    contract_item -- a contract-side item of the project: contract form, land tenure, utility contract,
                     user agreement or partner structure

Constraint and index names are written out (``*_oe_dm_*``) and the migration
uses the same strings. No ``relationship()``: rows reference each other by id
and the repository loads explicitly, so no lazy load fires from async code.
Soft references into other modules (governance documents, risk register rows,
contracts, procurement rows, schedule activities) carry no foreign key.

Calendar days are ISO strings in ``String(40)`` as elsewhere on the platform;
instants are timezone-aware ``DateTime``. Weights and shares are exact decimals.
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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project_fk(name: str) -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE", name=name), nullable=False)


class DeliveryModel(Base):
    """The project's delivery model: pinned catalogue, chosen form, lifecycle status."""

    __tablename__ = "oe_delivery_model_model"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_dm_model_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_model_project")
    catalogue_source: Mapped[str] = mapped_column(
        String(20), nullable=False, default="shipped", server_default="shipped"
    )
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False)
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False)
    selected_form_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    # FIDIC Emerald style ground risk sharing on a geotechnical baseline (lead decision 6).
    underground_risk_sharing: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    # {owner_has_design_team, owner_has_cm_capacity, public_client, funding_source}
    owner_capability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # The governance change request that licensed the current reopening (rule 9); cleared when it is settled.
    # The frame document that carries the decision is resolved from the governance catalogue at read time.
    change_request_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    current_decision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1, server_default="1")

    __mapper_args__ = {"version_id_col": version}


class DeliveryOption(Base):
    """A candidate delivery form in the comparison, with attribute overrides."""

    __tablename__ = "oe_delivery_model_option"
    __table_args__ = (
        UniqueConstraint("project_id", "form_code", name="uq_oe_dm_option_form"),
        Index("ix_oe_dm_option_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_option_project")
    form_code: Mapped[str] = mapped_column(String(64), nullable=False)
    overrides: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class DecisionCriterion(Base):
    """A decision criterion of the project, weight copied from the catalogue and editable."""

    __tablename__ = "oe_delivery_model_criterion"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dm_criterion_code"),
        Index("ix_oe_dm_criterion_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_criterion_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    weight: Mapped[Decimal] = mapped_column(Numeric(9, 4), nullable=False, default=Decimal("0"), server_default="0")
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class OptionScore(Base):
    """One score of one option on one criterion."""

    __tablename__ = "oe_delivery_model_score"
    __table_args__ = (
        UniqueConstraint("option_id", "criterion_id", name="uq_oe_dm_score_pair"),
        Index("ix_oe_dm_score_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_score_project")
    option_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_delivery_model_option.id", ondelete="CASCADE", name="fk_oe_dm_score_option"),
        nullable=False,
    )
    criterion_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_delivery_model_criterion.id", ondelete="CASCADE", name="fk_oe_dm_score_criterion"),
        nullable=False,
    )
    score: Mapped[int] = mapped_column(Integer, nullable=False)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


class DeliveryDecision(Base):
    """A decision: proposed here, approved only by the governance gate; the snapshot never changes."""

    __tablename__ = "oe_delivery_model_decision"
    __table_args__ = (Index("ix_oe_dm_decision_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_decision_project")
    form_code: Mapped[str] = mapped_column(String(64), nullable=False)
    option_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # proposed | approved | superseded | withdrawn | rejected
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="proposed", server_default="proposed")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # Options, criteria, scores, totals, allocations, packages and catalogue pin at proposal.
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    owner_capability: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # {package_id: keep | re_scope | cancel} for packages already in procurement or awarded (rule 9).
    dispositions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    proposed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    proposed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approved_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # gate | change_request: which governance act approved it.
    approval_source: Mapped[str] = mapped_column(String(20), nullable=False, default="", server_default="")
    governance_document_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_governance_document.id", ondelete="SET NULL", name="fk_oe_dm_decision_gov_document"),
        nullable=True,
    )
    governance_ref_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bound_revision_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    bound_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    supersedes_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # SHA-256 of the canonical snapshot, fixed when the snapshot is frozen at approval.
    snapshot_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The project's four-eyes setting as it stood when the decision was approved; a later toggle changes nothing.
    four_eyes: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    # Why the governance act that bound the frame document did not approve this decision (a reason code).
    approval_blocked_reason: Mapped[str] = mapped_column(String(64), nullable=False, default="", server_default="")


class RiskAllocation(Base):
    """Who carries one risk category. Only party, basis and rationale live here; the risk lives in the register."""

    __tablename__ = "oe_delivery_model_allocation"
    __table_args__ = (
        UniqueConstraint("project_id", "category_code", name="uq_oe_dm_allocation_category"),
        Index("ix_oe_dm_allocation_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_allocation_project")
    category_code: Mapped[str] = mapped_column(String(64), nullable=False)
    party: Mapped[str | None] = mapped_column(String(40), nullable=True)
    basis: Mapped[str] = mapped_column(String(30), nullable=False, default="contract", server_default="contract")
    # {party: percent string} for party == "shared"
    shares: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    not_applicable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    # catalogue_default | edited
    source: Mapped[str] = mapped_column(
        String(30), nullable=False, default="catalogue_default", server_default="catalogue_default"
    )
    # unconfirmed | confirmed | link_missing
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="unconfirmed", server_default="unconfirmed")
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Soft links to oe_risk_register rows.
    risk_item_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)


class ContractPackage(Base):
    """One package of the plan. Modules 4, 7 and 8 read responsibility from here and nowhere else."""

    __tablename__ = "oe_delivery_model_package"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dm_package_code"),
        Index("ix_oe_dm_package_project", "project_id"),
        Index("ix_oe_dm_package_link", "link_kind", "link_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_package_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    designs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    builds: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    supplies: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    manages: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=text("false"))
    party: Mapped[str] = mapped_column(String(40), nullable=False, default="contractor", server_default="contractor")
    # owner | manager: who holds the contract for this package.
    contracting_party: Mapped[str] = mapped_column(String(20), nullable=False, default="owner", server_default="owner")
    price_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    standard_form: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    scope: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    wbs_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    boq_ref: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    need_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # planned | closed | cancelled; in_procurement / awarded are read from the linked row.
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="planned", server_default="planned")
    # bid_package | tender_package | rfq | subcontract_agreement | contract
    link_kind: Mapped[str | None] = mapped_column(String(30), nullable=True)
    link_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")


class OwnerFurnishedItem(Base):
    """Equipment, material, design or service the owner provides to a package."""

    __tablename__ = "oe_delivery_model_ofi"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dm_ofi_code"),
        Index("ix_oe_dm_ofi_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_ofi_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")
    # equipment | material | design | service | utility
    item_kind: Mapped[str] = mapped_column(String(20), nullable=False, default="equipment", server_default="equipment")
    # owner | package
    install_by: Mapped[str] = mapped_column(String(20), nullable=False, default="package", server_default="package")
    package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # rfq | purchase_order | requisition | framework | existing_stock | none_yet
    procurement_route: Mapped[str] = mapped_column(
        String(20), nullable=False, default="none_yet", server_default="none_yet"
    )
    link_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    link_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    schedule_activity_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    need_by_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    expected_delivery_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Own figures: in force only while no plant item is linked (see ``plant.py``).
    enquiry_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # The plant item this is, when the plant register holds it too. Soft id, checked through the register's port.
    plant_item_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="identified", server_default="identified")


class ContractItem(Base):
    """One contract-side agreement of the project, outside the package plan.

    ``group_code`` says what it is (contract form, land tenure, utility contract, user agreement,
    partner structure); ``kind_code`` is the catalogue kind within the group. A contract form may name
    the package it governs and its price basis; a partner structure carries the partner's share.
    """

    __tablename__ = "oe_delivery_model_contract_item"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_dm_contract_item_code"),
        Index("ix_oe_dm_contract_item_project", "project_id", "group_code"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk("fk_oe_dm_contract_item_project")
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    # contract_form | land_tenure | utility_contract | user_agreement | partner_structure
    group_code: Mapped[str] = mapped_column(String(30), nullable=False)
    kind_code: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="", server_default="")
    counterparty: Mapped[str] = mapped_column(String(255), nullable=False, default="", server_default="")
    package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # draft | negotiating | agreed | signed | terminated
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")
    reference: Mapped[str] = mapped_column(String(120), nullable=False, default="", server_default="")
    start_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    end_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # A contract form's price basis (one of the delivery model price bases).
    price_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # A partner structure's share of the project, a decimal string in percent.
    share_percent: Mapped[str | None] = mapped_column(String(10), nullable=True)
    notes: Mapped[str] = mapped_column(Text, nullable=False, default="", server_default="")


ALL_MODELS = (
    DeliveryModel,
    DeliveryOption,
    DecisionCriterion,
    OptionScore,
    DeliveryDecision,
    RiskAllocation,
    ContractPackage,
    OwnerFurnishedItem,
    ContractItem,
)
