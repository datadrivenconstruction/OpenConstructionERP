# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Construction-control ORM models.

Tables:
    oe_cc_acceptance_criterion - referenceable acceptance clause + tolerance +
        standard reference; every inspection result is judged against one of these.
    oe_cc_inspection           - one inspection record with a type discriminator
        (mir / wir / ir / hidden_works / acceptance) and a recorded pass/fail result.
    oe_cc_element_ref          - the Universal Element Reference (UER): a polymorphic
        link from any control record to a model element, regardless of source format
        (IFC, Revit, DWG, DGN, ...). Resolves through the normalised bim_hub identity
        ``(model_id, stable_id)`` so IFC GlobalId is optional, never required.
    oe_cc_material_record      - the digital material passport (Pillar 2): an EN 10204
        certificate (2.1 / 2.2 / 3.1 / 3.2), CE/UKCA + Declaration of Performance,
        batch/heat/lot traceability and certificate validity, tied to a procurement
        goods receipt; a rejected review raises a material NCR automatically.
    oe_cc_test_result          - a material or field test result (Pillar 2) judged
        against a criterion (sample id, method, ISO/IEC 17025 lab accreditation); a
        failed result raises an NCR, mirroring the inspection fail -> NCR bridge.
    oe_cc_asbuilt_record       - the as-built / verified-record wrapper (Pillar 3):
        ties a survey/scan/measurement to a model element with explicit metrology
        (instrument, accuracy class, coordinate system), judges it against a
        criterion, and carries a legally meaningful "valid for record" attestation
        captured with an e-signature; an out-of-tolerance survey raises an NCR.
    oe_cc_hold_gate            - the hold/witness/surveillance/review gate (Pillar 5):
        the gating engine on top of an intervention point. A blocking gate stops
        progress on the activity / package / inspection it is attached to until an
        authorised party releases it (e-signed), mirroring the QMS hold-point release.
    oe_cc_handover_package     - the handover / acceptance package (Pillar 4): the
        completion-regime wrapper that auto-assembles the acceptance evidence
        (passed inspections, recorded as-builts, accepted materials, lab tests) into
        a manifest, computes a completion gate from open NCRs and unreleased hold
        gates, and issues a regime-specific acceptance certificate behind an
        e-signature. A certificate can only be issued once the gate is clear, or a
        manager explicitly overrides it (audited, and recorded as a documentation NCR).

Design note: the UER is a shared table rather than columns inlined on each record,
so one resolver and one schema serve inspections today and NCR / test results /
material records / as-built records / handover packages as later pillars land.
"""

import uuid

from sqlalchemy import JSON, Boolean, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import GUID, Base


class AcceptanceCriterion(Base):
    """A referenceable acceptance clause: what is measured, against which standard,
    and the tolerance that decides pass or fail."""

    __tablename__ = "oe_cc_acceptance_criterion"
    __table_args__ = (
        UniqueConstraint("project_id", "code", name="uq_oe_cc_criterion_project_code"),
        Index("ix_oe_cc_criterion_project", "project_id"),
        Index("ix_oe_cc_criterion_project_category", "project_id", "category"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Open-standard anchor, e.g. "ISO 9001:2015 8.6", "EN 1992-1-1", "ACI 318",
    # "AS 3600", "BS 8500", "GOST/SP 70.13330". Free text - never an enum.
    standard_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    category: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # What is measured, e.g. "cube compressive strength", "weld throat thickness".
    characteristic: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # How to verify - test/inspection method reference.
    method: Mapped[str | None] = mapped_column(Text, nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # How a measured value is judged against this criterion:
    # range | min | max | boolean | text. Drives the pass/fail decision.
    acceptance_rule: Mapped[str] = mapped_column(String(20), nullable=False, default="text", server_default="text")
    # Numeric bounds kept as strings (consistent with the platform's money/quantity
    # convention) so arbitrary precision survives the JSON/SQL round trip.
    nominal_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tolerance_lower: Mapped[str | None] = mapped_column(String(80), nullable=True)
    tolerance_upper: Mapped[str | None] = mapped_column(String(80), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True, server_default="1", nullable=False)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<AcceptanceCriterion {self.code} - {self.title[:40]}>"


class Inspection(Base):
    """A single inspection / acceptance act on a work location or model element.

    One entity serves every phase-specific document through the ``inspection_type``
    discriminator (material / witness / final / hidden-works / acceptance), and every
    legal regime through ``party_role`` (contractor QC, client/engineer QA, third-party
    inspection, authority having jurisdiction).
    """

    __tablename__ = "oe_cc_inspection"
    __table_args__ = (
        UniqueConstraint("project_id", "inspection_number", name="uq_oe_cc_inspection_project_number"),
        Index("ix_oe_cc_inspection_project", "project_id"),
        Index("ix_oe_cc_inspection_project_status", "project_id", "status"),
        Index("ix_oe_cc_inspection_project_type", "project_id", "inspection_type"),
        Index("ix_oe_cc_inspection_criterion", "criterion_id"),
        Index("ix_oe_cc_inspection_raised_ncr", "raised_ncr_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    inspection_number: Mapped[str] = mapped_column(String(20), nullable=False)
    # mir | wir | ir | hidden_works | acceptance
    inspection_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # Viewpoint that produced the record: qc | qa | tpi | ahj.
    party_role: Mapped[str] = mapped_column(String(10), nullable=False, default="qc", server_default="qc")
    # Intervention-point class (Pillar 5 gating hook): hold | witness | surveillance | review.
    intervention_point: Mapped[str | None] = mapped_column(String(20), nullable=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    location_description: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # Cross-module soft links (plain ids, no FK): schedule activity, acceptance criterion.
    activity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # draft | scheduled | in_progress | passed | failed | closed | void
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", server_default="draft")
    # pass | fail | conditional (set when a result is recorded)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    measured_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    result_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NCR auto-raised when the inspection fails; links back via NCR.linked_inspection_id.
    raised_ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    scheduled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    performed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<Inspection {self.inspection_number} {self.inspection_type} ({self.status})>"


class ElementRef(Base):
    """Universal Element Reference (UER).

    A polymorphic link attaching any control record to a model element regardless of
    the source format. The strong link is ``bim_element_id``; failing that the element
    resolves from the normalised ``(model_id, stable_id)`` identity, then from
    ``(model_id, native_id)``. Display fields are denormalised so a record renders even
    when the model is offline or not yet ingested. ``ifc_global_id`` is an optional
    open-standard crosswalk that gates BCF round-trip; it is never required.
    """

    __tablename__ = "oe_cc_element_ref"
    __table_args__ = (
        Index("ix_oe_cc_element_ref_owner", "owner_type", "owner_id"),
        Index("ix_oe_cc_element_ref_model_stable", "model_id", "stable_id"),
        Index("ix_oe_cc_element_ref_project", "project_id"),
        Index("ix_oe_cc_element_ref_element", "bim_element_id"),
    )

    # Polymorphic owner: inspection | ncr | criterion | test_result | material_record |
    # asbuilt | handover_package.
    owner_type: Mapped[str] = mapped_column(String(40), nullable=False)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False)
    # Denormalised so every UER is tenant-scoped on its own (IDOR defence + fast filter).
    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Strong link; SET NULL on element delete keeps the row resolvable via stable_id.
    bim_element_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_element.id", ondelete="SET NULL"),
        nullable=True,
    )
    model_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(),
        ForeignKey("oe_bim_model.id", ondelete="SET NULL"),
        nullable=True,
    )
    # Normalised per-format id (IFC GlobalId / Revit UniqueId / DWG handle / DGN id).
    stable_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # ifc / revit / dwg / dxf / dgn / nwd / pointcloud / other.
    source_format: Mapped[str | None] = mapped_column(String(20), nullable=True)
    # Optional open-standard crosswalk (BCF). 22-char IFC GlobalId.
    ifc_global_id: Mapped[str | None] = mapped_column(String(22), nullable=True)
    # Raw source id when it differs from stable_id (Revit ElementId vs UniqueId).
    native_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Audit-critical: the model revision the record was made against ("accepted vs rev C").
    model_version: Mapped[str | None] = mapped_column(String(20), nullable=True)
    element_name: Mapped[str | None] = mapped_column(String(500), nullable=True)
    element_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    bbox: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    viewpoint: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<ElementRef {self.owner_type}:{self.owner_id} -> {self.source_format}:{self.stable_id}>"


class MaterialRecord(Base):
    """Digital material passport (Pillar 2).

    A material/product submitted for use on the project, carrying its conformity
    evidence: the EN 10204 certificate grade, CE/UKCA marking and Declaration of
    Performance (EU CPR), batch/heat/lot traceability and the certificate validity
    window, optionally tied to the procurement goods receipt that brought it on site.

    A review records an accept / reject / conditional decision (the same grammar the
    inspection uses): a rejection raises a material NCR and a conditional acceptance
    raises an observation NCR, so non-conforming materials never pass silently.
    """

    __tablename__ = "oe_cc_material_record"
    __table_args__ = (
        UniqueConstraint("project_id", "record_number", name="uq_oe_cc_material_project_number"),
        Index("ix_oe_cc_material_project", "project_id"),
        Index("ix_oe_cc_material_project_status", "project_id", "status"),
        Index("ix_oe_cc_material_project_type", "project_id", "material_type"),
        Index("ix_oe_cc_material_gr", "gr_id"),
        Index("ix_oe_cc_material_criterion", "criterion_id"),
        Index("ix_oe_cc_material_raised_ncr", "raised_ncr_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project human number "MAT-NNN", allocated collision-safe in the repository.
    record_number: Mapped[str] = mapped_column(String(20), nullable=False)
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    # Free-text family, e.g. "concrete", "reinforcing steel", "structural steel",
    # "timber", "membrane". Never an enum - every market names materials differently.
    material_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # Grade/designation, e.g. "C30/37", "S355JR", "B500B", "EN 10025-2".
    spec_grade: Mapped[str | None] = mapped_column(String(255), nullable=True)
    manufacturer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    supplier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft link to a supplier contact id (no FK - keeps the module decoupled).
    supplier_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    product_code: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Conformity certificate (EN 10204 grammar + EU CPR / UKCA) ──────────────
    # EN 10204 inspection-document type: 2.1 | 2.2 | 3.1 | 3.2, plus the CPR/UKCA
    # markings (dop | ce | ukca) and a generic certificate of conformity (coc).
    cert_type: Mapped[str | None] = mapped_column(String(20), nullable=True)
    cert_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Who issued it: the mill, the manufacturer, an independent inspector or lab,
    # or a notified body for a CE Declaration of Performance.
    cert_issuer: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft link to the stored certificate document / transmittal (no FK).
    cert_document_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Declaration of Performance number (EU Construction Products Regulation).
    dop_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    ce_marking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    ukca_marking: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    # Dates kept as strings (platform convention - arbitrary precision survives the
    # JSON/SQL round trip and no timezone ambiguity creeps in for plain calendar dates).
    issued_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    valid_from: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Certificate / shelf-life expiry; an expired certificate at review time is a
    # rejection reason and is surfaced as ``is_expired`` on the response.
    valid_until: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Traceability (batch / heat / lot) ──────────────────────────────────────
    batch_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Heat / cast number - the steel mill's melt identifier.
    heat_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    lot_number: Mapped[str | None] = mapped_column(String(120), nullable=True)
    quantity: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # ── Cross-module soft links (plain ids, no FK) ─────────────────────────────
    # Acceptance criterion the material is judged against.
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Procurement goods receipt (and line) that brought the material on site.
    po_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gr_item_id: Mapped[str | None] = mapped_column(String(36), nullable=True)

    # ── Lifecycle ───────────────────────────────────────────────────────────--
    # draft | submitted | under_review | accepted | rejected | expired | superseded
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", server_default="draft")
    review_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NCR auto-raised on a rejected / conditional review.
    raised_ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    received_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    received_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    reviewed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<MaterialRecord {self.record_number} {self.name[:40]} ({self.status})>"


class TestResult(Base):
    """A material or field test result (Pillar 2).

    Records the outcome of a sample test against an acceptance criterion - the sample
    id, the test method (e.g. "EN 12390-3", "ISO 6892-1", "ASTM C39") and, where the
    test was run by a laboratory, the ISO/IEC 17025 accreditation that makes the result
    legally defensible. A ``fail`` (or ``conditional``) raises an NCR, mirroring the
    inspection fail -> NCR bridge.
    """

    __tablename__ = "oe_cc_test_result"
    __table_args__ = (
        UniqueConstraint("project_id", "result_number", name="uq_oe_cc_test_project_number"),
        Index("ix_oe_cc_test_project", "project_id"),
        Index("ix_oe_cc_test_project_status", "project_id", "status"),
        Index("ix_oe_cc_test_material", "material_record_id"),
        Index("ix_oe_cc_test_criterion", "criterion_id"),
        Index("ix_oe_cc_test_raised_ncr", "raised_ncr_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project human number "TST-NNN", allocated collision-safe in the repository.
    result_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Cross-module soft links (plain ids, no FK): the tested material lot, the parent
    # inspection (a test performed as part of one), and the criterion it is judged on.
    material_record_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sample_id: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Standard test method reference (free text - one per market/standard family).
    test_method: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Laboratory (ISO/IEC 17025) ─────────────────────────────────────────────
    lab_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Accreditation body + number, e.g. "UKAS 0001", "A2LA 1234.01", "DAkkS D-PL-1".
    lab_accreditation: Mapped[str | None] = mapped_column(String(120), nullable=True)
    is_accredited: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")

    measured_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Specimen age at test, e.g. concrete cube tested at 7 / 28 days.
    specimen_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # draft | recorded | void
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", server_default="draft")
    # pass | fail | conditional (set when the result is recorded)
    result: Mapped[str | None] = mapped_column(String(20), nullable=True)
    result_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # NCR auto-raised on a failed / conditional result.
    raised_ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The instrument's calibration certificate (soft id of ``oe_qms_calibration``). A
    # result whose instrument was out of calibration on ``tested_at`` does not count
    # as evidence in a quality concept.
    calibration_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sampled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    tested_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    performed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<TestResult {self.result_number} {self.result or self.status}>"


class AsBuiltRecord(Base):
    """As-built / verified record (Pillar 3).

    A legal-record wrapper tying a survey, scan or measurement to a model element with
    explicit metrology (the instrument and its calibration, an accuracy class and value,
    the coordinate system), judging the captured value against an acceptance criterion,
    and carrying a deliberately separate ``valid_for_legal_record`` attestation that is
    never set automatically: it is reached only through an e-signature once the record is
    verified. An out-of-tolerance survey raises a workmanship NCR, mirroring the
    inspection fail -> NCR bridge. The captured element is linked through the shared
    Universal Element Reference (``owner_type="asbuilt"``).
    """

    __tablename__ = "oe_cc_asbuilt_record"
    __table_args__ = (
        UniqueConstraint("project_id", "record_number", name="uq_oe_cc_asbuilt_project_number"),
        Index("ix_oe_cc_asbuilt_project", "project_id"),
        Index("ix_oe_cc_asbuilt_project_status", "project_id", "status"),
        Index("ix_oe_cc_asbuilt_criterion", "criterion_id"),
        Index("ix_oe_cc_asbuilt_source", "source_kind", "source_ref"),
        Index("ix_oe_cc_asbuilt_raised_ncr", "raised_ncr_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project human number "ASB-NNN", allocated collision-safe in the repository.
    record_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    discipline: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location_description: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # ── Metrology ───────────────────────────────────────────────────────────--
    # How the as-built was captured: laser_scan | photogrammetry | total_station |
    # gnss | tape | drone_lidar | model_extract | manual.
    capture_method: Mapped[str] = mapped_column(String(20), nullable=False, default="manual", server_default="manual")
    instrument: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Soft link to a calibration certificate (e.g. oe_qms_calibration); no FK.
    instrument_calibration_ref: Mapped[str | None] = mapped_column(String(120), nullable=True)
    # Accuracy class of the capture: survey | standard | coarse.
    accuracy_class: Mapped[str] = mapped_column(
        String(20), nullable=False, default="standard", server_default="standard"
    )
    # Stated accuracy magnitude kept as a string (platform money/quantity convention).
    accuracy_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    accuracy_unit: Mapped[str | None] = mapped_column(String(40), nullable=True)
    coordinate_system: Mapped[str | None] = mapped_column(String(120), nullable=True)
    survey_date: Mapped[str | None] = mapped_column(String(40), nullable=True)
    surveyed_by: Mapped[str | None] = mapped_column(String(255), nullable=True)

    # ── Conformity (judged against an acceptance criterion) ─────────────────---
    # Acceptance criterion the as-built value is judged against (soft id).
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    measured_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    deviation_value: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # within | out_of_tolerance | not_assessed (set when the survey is recorded).
    tolerance_result: Mapped[str | None] = mapped_column(String(20), nullable=True)

    # ── Legal record attestation (never auto-true) ──────────────────────────---
    valid_for_legal_record: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="0")
    validity_signed_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    validity_signed_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    validity_signature_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    validity_signature_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Provenance ──────────────────────────────────────────────────────────--
    # Where the record came from: pointcloud_scan | pointcloud_registration |
    # takeoff_measurement | cde_document | manual.
    source_kind: Mapped[str] = mapped_column(String(30), nullable=False, default="manual", server_default="manual")
    # Soft id of the source row in its own module (no FK).
    source_ref: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # MinIO / CDE URI of the deviation colour map, when one exists.
    deviation_map_uri: Mapped[str | None] = mapped_column(String(2000), nullable=True)

    # draft | surveyed | verified | recorded | superseded | void
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft", server_default="draft")
    # NCR auto-raised when the as-built is verified out of tolerance.
    raised_ncr_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<AsBuiltRecord {self.record_number} {self.title[:40]} ({self.status})>"


class HoldGate(Base):
    """Hold / witness / surveillance / review gate (Pillar 5).

    The gating engine built on top of the inspection ``intervention_point`` seed. A gate
    is attached to an activity, a handover package or an inspection; a hold gate is a hard
    block on progress, a witness gate is a configurable soft block (notify + attendance),
    and surveillance / review gates are advisory and never block. ``blocks_progress`` is
    the single source of truth for whether a gate stops work.

    A gate is released by an authorised party whose role must satisfy the gate's
    ``required_party_role`` (defence in depth alongside RBAC), captured with an
    e-signature over a canonical snapshot. A witness / surveillance / review gate may be
    waived; a hold gate may never be waived.
    """

    __tablename__ = "oe_cc_hold_gate"
    __table_args__ = (
        UniqueConstraint("project_id", "gate_number", name="uq_oe_cc_gate_project_number"),
        Index("ix_oe_cc_gate_project", "project_id"),
        Index("ix_oe_cc_gate_project_status", "project_id", "status"),
        Index("ix_oe_cc_gate_attached", "attached_kind", "attached_id"),
        Index("ix_oe_cc_gate_inspection", "inspection_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project human number "GATE-NNN", allocated collision-safe in the repository.
    gate_number: Mapped[str] = mapped_column(String(20), nullable=False)
    # hold | witness | surveillance | review.
    point_type: Mapped[str] = mapped_column(String(20), nullable=False, default="hold", server_default="hold")
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The party whose presence/sign-off the gate requires: qc | qa | tpi | ahj.
    required_party_role: Mapped[str] = mapped_column(String(10), nullable=False, default="qa", server_default="qa")
    # Inspection that satisfies the point (soft id), and the criterion it checks.
    inspection_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    criterion_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # What the gate is attached to: activity | handover_package | inspection | cx_stage
    # (a commissioning stage of one system in a quality concept, released only here).
    attached_kind: Mapped[str | None] = mapped_column(String(20), nullable=True)
    attached_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # Contract package the gate belongs to (soft ref); a partial handover counts only
    # the gates of its own packages.
    package_ref: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # The single source of truth for whether the gate stops progress. A hold gate
    # blocks by default; witness/surveillance/review default to soft but are overridable.
    blocks_progress: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="1")

    # pending | released | waived | void
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending", server_default="pending")

    # ── Release (authorised, e-signed) ──────────────────────────────────────--
    released_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # The party role asserted at release time; must satisfy required_party_role.
    released_party_role: Mapped[str | None] = mapped_column(String(10), nullable=True)
    released_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    release_justification: Mapped[str | None] = mapped_column(Text, nullable=True)
    release_signature_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_signature_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Waiver (witness / surveillance / review only) ───────────────────────--
    waived_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    waived_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Optional routed approval (approval_routes) when a gate is released via a route.
    approval_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<HoldGate {self.gate_number} {self.point_type} ({self.status})>"


class HandoverPackage(Base):
    """Handover / acceptance package (Pillar 4).

    The completion-regime wrapper that turns the project's accumulated control evidence
    into an acceptance dossier. It auto-assembles a manifest of the acceptance evidence
    (passed / closed inspections, recorded and legally-attested as-builts, accepted
    materials, recorded passing lab tests), computes a completion gate from the open
    non-conformances and the unreleased hold gates on the project, and issues a
    regime-specific acceptance certificate.

    The acceptance regime spans the major legal traditions through ``completion_regime``
    (taking-over under FIDIC, substantial completion under US practice, practical
    completion under UK practice) and ``completion_type`` (whole / sectional / partial),
    so one table serves every market the platform reaches.

    The completion gate is the heart of the pillar: a certificate can only be issued once
    ``gating_state`` is ``clear`` (no open NCRs and no unreleased blocking gates), or once
    a manager explicitly overrides the gate. Issue is captured with an e-signature - a
    SHA-256 over a canonical snapshot, the signer and their IP - exactly as the as-built
    legal attestation and the gate release are. Linked model elements (a sectional area,
    a system) attach through the shared Universal Element Reference
    (``owner_type="handover_package"``).
    """

    __tablename__ = "oe_cc_handover_package"
    __table_args__ = (
        UniqueConstraint("project_id", "package_number", name="uq_oe_cc_handover_project_number"),
        Index("ix_oe_cc_handover_project", "project_id"),
        Index("ix_oe_cc_handover_project_status", "project_id", "status"),
        Index("ix_oe_cc_handover_closeout", "closeout_package_id"),
    )

    project_id: Mapped[uuid.UUID] = mapped_column(
        GUID(),
        ForeignKey("oe_projects_project.id", ondelete="CASCADE"),
        nullable=False,
    )
    # Per-project human number "HOP-NNN", allocated collision-safe in the repository.
    # Multiple packages per project are allowed (sectional / partial handover).
    package_number: Mapped[str] = mapped_column(String(20), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)

    # ── Completion regime ─────────────────────────────────────────────────────
    # The legal completion regime this package is issued under:
    # taking_over (FIDIC) | substantial (US) | practical (UK).
    completion_regime: Mapped[str] = mapped_column(
        String(20), nullable=False, default="taking_over", server_default="taking_over"
    )
    # Whole / sectional / partial handover.
    completion_type: Mapped[str] = mapped_column(String(20), nullable=False, default="whole", server_default="whole")
    # Free-text section / area reference for a sectional or partial handover.
    section_ref: Mapped[str | None] = mapped_column(String(255), nullable=True)
    # Acceptance regime code from the project's quality concept catalogue (de_vob_b,
    # uk_jct_practical, ...). When set it names the act; ``completion_regime`` stays the
    # coarse legal tradition.
    regime_code: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # Contract packages this handover covers (soft refs). When set, the completion gate
    # counts only NCRs and hold gates of these packages.
    package_refs: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # ── Lifecycle ───────────────────────────────────────────────────────────--
    # draft | assembling | ready | issued | revoked
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", server_default="draft")

    # ── Completion gate (the heart of the pillar) ──────────────────────────────
    # blocked | clear | overridden. The single source of truth for whether the
    # acceptance certificate may be issued.
    gating_state: Mapped[str] = mapped_column(String(20), nullable=False, default="blocked", server_default="blocked")
    # Denormalised gate inputs, recomputed by validate_gates (counts kept as Int,
    # not money/quantity, so a real integer column is correct here).
    open_ncr_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    unreleased_hold_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    completeness_pct: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    # Manager override of a blocked gate (a legitimate snag-list handover under FIDIC).
    gating_override_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    gating_override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # ── Acceptance certificate (e-signed at issue, never auto-issued) ──────────-
    certificate_no: Mapped[str | None] = mapped_column(String(120), nullable=True)
    issued_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    issued_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    issue_signature_ip: Mapped[str | None] = mapped_column(String(64), nullable=True)
    issue_signature_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # ── Assembled dossier ──────────────────────────────────────────────────────
    # Soft link to a generic closeout package (lazy-created) that owns the heavy ZIP
    # build; no FK, so the construction-control module stays decoupled from closeout.
    closeout_package_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    # MinIO / CDE key of the built dossier ZIP, when one exists.
    dossier_key: Mapped[str | None] = mapped_column(String(2000), nullable=True)
    dossier_built_at: Mapped[str | None] = mapped_column(String(40), nullable=True)
    # When the evidence manifest was last (re)assembled.
    assembled_at: Mapped[str | None] = mapped_column(String(40), nullable=True)

    # Optional routed approval (approval_routes) when issue is routed for sign-off.
    approval_instance_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    metadata_: Mapped[dict] = mapped_column(  # type: ignore[assignment]
        "metadata",
        JSON,
        nullable=False,
        default=dict,
        server_default="{}",
    )

    def __repr__(self) -> str:
        return f"<HandoverPackage {self.package_number} {self.completion_regime} ({self.status})>"
