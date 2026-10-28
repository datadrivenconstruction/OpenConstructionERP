# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Quality concept ORM models.

Tables (all prefixed ``oe_qconcept_``):
    concept         -- one per project: pinned catalogue, state, package scope
    revision        -- frozen snapshot of the concept at approval / revision
    standard        -- the standards basis (open codes, never an enum on evidence)
    cert_target     -- a certification target (scheme, level, assessor, state)
    credit          -- an optional credit target with points (Decimal)
    proof           -- one required proof: package, evidence type, deliverer, due
    evidence_link   -- typed pointer from a proof / credit / stage / survey to an
                       existing evidence row in another module; never a copy
    stage_def       -- project copy of the commissioning levels (copy on write)
    stage_progress  -- commissioning unit (CxSystem) x stage; released only by a
                       construction_control hold gate
    acceptance_unit -- the acceptance plan (partial, total, handover, authority);
                       the ACT stays a construction_control handover package
    effect          -- a confirmed legal effect of an acceptance (unique per unit
                       and effect, which makes confirmation idempotent)
    preservation    -- evidence-preservation survey (neighbours, own structure)
    expert_report   -- owner-commissioned expert reports during construction

Quality requirements are ``requirements.Requirement`` rows, documentation slots
are ``closeout`` slots and FM data are ``requirements.RequirementDeliverable``
rows: no table here holds them. Soft references into other modules (contract
packages, plant items, CX systems, hold gates, handover packages, contacts,
CDE documents, schedule activities) carry no foreign key: the other module owns
those rows and each write checks the referenced row belongs to the project.

There are no ``relationship()`` declarations; the repository loads by id.
Calendar days are ISO strings in ``String(40)`` as elsewhere on the platform;
instants are timezone-aware ``DateTime``. Points are Decimal.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base

_PROJECT_FK = "oe_projects_project.id"


def _project_fk() -> Any:
    return mapped_column(GUID(), ForeignKey(_PROJECT_FK, ondelete="CASCADE"), nullable=False)


class QualityConcept(Base):
    """The quality concept of one project. ``version`` is the optimistic lock column."""

    __tablename__ = "oe_qconcept_concept"
    __table_args__ = (UniqueConstraint("project_id", name="uq_oe_qconcept_concept_project"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    catalogue_source: Mapped[str] = mapped_column(String(20), nullable=False, default="shipped")
    catalogue_id: Mapped[str] = mapped_column(String(64), nullable=False, default="neutral")
    catalogue_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    # draft | in_review | approved | binding | revising (approved / binding mirrored from governance).
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="draft")
    governance_doc_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    requirement_set_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    documentation_set_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Declared package scope: [{ref, code, title, no_proofs_rationale}] (soft refs to ContractPackage).
    packages: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    # Public holidays (ISO dates) the deemed-acceptance clock skips; data, never a country rule.
    holidays: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    submitted_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class QualityConceptRevision(Base):
    """A frozen snapshot of proofs, stages and acceptance units (rule 22)."""

    __tablename__ = "oe_qconcept_revision"
    __table_args__ = (
        UniqueConstraint("concept_id", "revision_no", name="uq_oe_qconcept_revision_no"),
        Index("ix_oe_qconcept_revision_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    concept_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_qconcept_concept.id", ondelete="CASCADE"), nullable=False
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(String(40), nullable=False, default="submitted")
    snapshot: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class AppliedStandard(Base):
    __tablename__ = "oe_qconcept_standard"
    __table_args__ = (Index("ix_oe_qconcept_standard_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(120), nullable=False)
    edition: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    family_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    discipline: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    package_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # statute | contract | voluntary
    mandate: Mapped[str] = mapped_column(String(20), nullable=False, default="contract")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")


class CertificationTarget(Base):
    __tablename__ = "oe_qconcept_cert_target"
    __table_args__ = (Index("ix_oe_qconcept_cert_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    scheme_code: Mapped[str] = mapped_column(String(64), nullable=False)
    scheme_version: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    scope: Mapped[str] = mapped_column(String(20), nullable=False, default="building")
    target_level: Mapped[str] = mapped_column(String(40), nullable=False)
    achieved_level: Mapped[str | None] = mapped_column(String(40), nullable=True)
    assessor_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    registration_no: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # Points the project can score in this scheme; a percent floor is read against it (rule 18).
    points_available: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    certificate_cde_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # planned | registered | design_assessed | post_construction_assessed | certified | level_missed | abandoned
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    registered_on: Mapped[str | None] = mapped_column(String(40), nullable=True)
    certified_on: Mapped[str | None] = mapped_column(String(40), nullable=True)


class CreditTarget(Base):
    __tablename__ = "oe_qconcept_credit"
    __table_args__ = (
        UniqueConstraint("target_id", "credit_code", name="uq_oe_qconcept_credit_code"),
        Index("ix_oe_qconcept_credit_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    target_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_qconcept_cert_target.id", ondelete="CASCADE"), nullable=False
    )
    credit_code: Mapped[str] = mapped_column(String(64), nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    points_targeted: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False, default=Decimal("0"))
    points_achieved: Mapped[Decimal | None] = mapped_column(Numeric(12, 4), nullable=True)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # targeted | evidence_submitted | achieved | not_achieved | dropped
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="targeted")


class ProofRequirement(Base):
    __tablename__ = "oe_qconcept_proof"
    __table_args__ = (
        Index("ix_oe_qconcept_proof_project", "project_id"),
        Index("ix_oe_qconcept_proof_package", "project_id", "package_ref"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    # Soft link to a contract package (module 3); null only for project-wide proofs.
    package_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    plant_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    cx_system_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    evidence_type: Mapped[str] = mapped_column(String(64), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    deliverer_role: Mapped[str] = mapped_column(String(30), nullable=False)
    deliverer_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # stage | acceptance_unit | activity | date, and its reference (stage code, unit id, activity id, ISO date).
    required_by_kind: Mapped[str] = mapped_column(String(20), nullable=False)
    required_by_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    # {"per_quantity": "150", "unit": "m3", "min_count": 1, "placed_quantity": "400"}; empty = one proof.
    quantity_rule: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    review_by_role: Mapped[str] = mapped_column(String(30), nullable=False, default="")
    # catalogue_default | edited
    source: Mapped[str] = mapped_column(String(30), nullable=False, default="edited")
    # none | accepted | waived; open / partly_delivered / delivered are derived on read.
    decision: Mapped[str] = mapped_column(String(20), nullable=False, default="none")
    decision_rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    requested_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    approval_instance_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class EvidenceLink(Base):
    __tablename__ = "oe_qconcept_evidence_link"
    __table_args__ = (
        UniqueConstraint("owner_kind", "owner_id", "link_kind", "link_id", name="uq_oe_qconcept_link"),
        Index("ix_oe_qconcept_link_owner", "owner_kind", "owner_id"),
        Index("ix_oe_qconcept_link_target", "link_kind", "link_id"),
        Index("ix_oe_qconcept_link_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    # proof | credit | stage_progress | preservation | expert_report
    owner_kind: Mapped[str] = mapped_column(String(30), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    link_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    link_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Re-test of a failed linked result (rule 6): the failed link id.
    retest_of: Mapped[str | None] = mapped_column(String(36), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)


class CommissioningStageDef(Base):
    __tablename__ = "oe_qconcept_stage_def"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_qconcept_stage_code"),
        Index("ix_oe_qconcept_stage_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    order: Mapped[int] = mapped_column("sort_order", Integer, nullable=False)
    name_override: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    release_party_role: Mapped[str] = mapped_column(String(10), nullable=False, default="qa")
    release_user_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    preconditions: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    evidence_types: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # {"mode": "all"} | {"mode": "system_types", "values": [...]} | {"mode": "systems", "values": [...]}
    applies_to: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    # catalogue code this row was copied from ("" for a stage the project added).
    catalogue_code: Mapped[str] = mapped_column(String(40), nullable=False, default="")


class StageProgress(Base):
    """One commissioning unit at one stage. ``version`` is the optimistic lock column."""

    __tablename__ = "oe_qconcept_stage_progress"
    __table_args__ = (
        UniqueConstraint("system_id", "stage_code", name="uq_oe_qconcept_progress_unit_stage"),
        Index("ix_oe_qconcept_progress_project", "project_id"),
        Index("ix_oe_qconcept_progress_gate", "hold_gate_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    # commissioning.CxSystem (soft id, checked against the project on write).
    system_id: Mapped[uuid.UUID] = mapped_column(GUID(), nullable=False)
    stage_code: Mapped[str] = mapped_column(String(40), nullable=False)
    # blocked | ready | in_test | passed | failed | released | stale | not_applicable
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="blocked")
    rationale: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Systems this unit's stage depends on (an IST names the systems it integrates).
    depends_on_system_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hold_gate_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    released_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    last_issue_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class AcceptanceUnit(Base):
    __tablename__ = "oe_qconcept_acceptance_unit"
    __table_args__ = (Index("ix_oe_qconcept_unit_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    code: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    title: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    # partial_package | partial_section | total | handover_to_operation | authority
    kind: Mapped[str] = mapped_column(String(30), nullable=False)
    package_refs: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    section_ref: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    regime_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    planned_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    schedule_activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # {"stages": [codes], "evidence_types": [...], "slot_keys": [...], "include_units": [ids]}
    preconditions: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    handover_package_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # planned | requested | inspection_scheduled | accepted | accepted_with_reservations | refused | deemed_accepted
    state: Mapped[str] = mapped_column(String(30), nullable=False, default="planned")
    completion_notice_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    use_started_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    deadline_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    accepted_on: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # [{kind, ref, note}] listed on an accept-with-reservations request (rule 13).
    reservations: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False, default=list)
    refusal_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    refusal_defects: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __mapper_args__ = {"version_id_col": version}


class AcceptanceEffect(Base):
    """A confirmed legal effect; unique per (unit, effect) so confirming twice is a no-op."""

    __tablename__ = "oe_qconcept_effect"
    __table_args__ = (
        UniqueConstraint("unit_id", "effect", name="uq_oe_qconcept_effect_unit"),
        Index("ix_oe_qconcept_effect_project", "project_id"),
    )

    project_id: Mapped[uuid.UUID] = _project_fk()
    unit_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("oe_qconcept_acceptance_unit.id", ondelete="CASCADE"), nullable=False
    )
    effect: Mapped[str] = mapped_column(String(40), nullable=False)
    effective_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    review_status: Mapped[str] = mapped_column(String(20), nullable=False, default="unconfirmed")
    # What the confirmation wrote or linked: {"warranty_ids": [...]} or {"commitment_ref": "..."}.
    outcome: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    confirmed_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PreservationSurvey(Base):
    __tablename__ = "oe_qconcept_preservation"
    __table_args__ = (Index("ix_oe_qconcept_preservation_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    subject_kind: Mapped[str] = mapped_column(String(40), nullable=False)
    # Groups the before / during / after surveys of one subject (a building, a road section).
    subject_ref: Mapped[str] = mapped_column(String(64), nullable=False)
    address: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    parcel: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    owner_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    influence_triggers: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # Soft links to schedule activities that start the triggers: {trigger: {"activity_id", "start"}}.
    trigger_activities: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    phase: Mapped[str] = mapped_column(String(20), nullable=False, default="before")
    methods: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    surveyor_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    planned_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    survey_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    invitation_sent_on: Mapped[str | None] = mapped_column(String(40), nullable=True)
    owner_acknowledged: Mapped[bool | None] = mapped_column(nullable=True)
    acknowledgment_cde_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    # A refusal is recorded once and never edited (rule 20).
    access_refused_on: Mapped[str | None] = mapped_column(String(40), nullable=True)
    access_refusal_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # planned | invited | surveyed | report_issued | closed | access_refused
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
    paired_with_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    lat: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(10, 7), nullable=True)


class ExpertReportPlan(Base):
    __tablename__ = "oe_qconcept_expert_report"
    __table_args__ = (Index("ix_oe_qconcept_expert_project", "project_id"),)

    project_id: Mapped[uuid.UUID] = _project_fk()
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    expert_contact_id: Mapped[uuid.UUID | None] = mapped_column(GUID(), nullable=True)
    trigger: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    frequency: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    due_dates: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    commitment_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # planned | commissioned | reporting | completed | cancelled
    state: Mapped[str] = mapped_column(String(20), nullable=False, default="planned")
