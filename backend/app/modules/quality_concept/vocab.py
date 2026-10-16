# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Closed vocabularies of the quality concept.

Everything a catalogue may name lives here once, so the catalogue validator,
the schemas and the evaluator agree. Words that belong to another module are
re-exported from there, never copied: the hold gate party roles from
construction_control and the verification methods from requirements.
"""

from __future__ import annotations

from app.modules.requirements.lifecycle import VERIFICATION_METHODS

# construction_control ``HoldGate.required_party_role`` vocabulary (models.py, gating_service._PARTY_ROLE_RANK).
PARTY_ROLES: tuple[str, ...] = ("qc", "qa", "tpi", "ahj")

# Existing evidence tables a proof, credit, stage or survey may point at (INTEGRATION 1.9).
LINK_KINDS: tuple[str, ...] = (
    "cc_test_result",
    "cc_material_record",
    "cc_inspection",
    "cc_asbuilt",
    "cc_handover_package",
    "qms_itp_plan",
    "qms_calibration",
    "cx_checklist",
    "cx_system",
    "closeout_slot",
    "submittal",
    "inspection",
    "cde_document",
    "diary_photo",
    "diary_reality_capture",
    "requirement_deliverable",
    # A delivery of material (procurement goods receipt): the proof that what
    # was built in arrived, with its certificates.
    "goods_receipt",
)

EVIDENCE_KINDS: tuple[str, ...] = ("test", "protocol", "record", "certificate", "report", "document", "dataset")
DELIVERER_ROLES: tuple[str, ...] = (
    "designer",
    "contractor",
    "supplier",
    "independent_expert",
    "owner",
    "authority",
)
CERTIFICATION_SCOPES: tuple[str, ...] = ("building", "plant", "operation")
CERTIFICATION_PHASES: tuple[str, ...] = (
    "pre_assessment",
    "registration",
    "design_stage",
    "post_construction",
    "certified",
)
SCORE_UNITS: tuple[str, ...] = ("percent", "points")
MATERIAL_FAMILIES: tuple[str, ...] = (
    "raw_material",
    "concrete",
    "suspension",
    "reinforcing_steel",
    "structural_steel",
    "soil",
    "asphalt",
)

# Section 4 rule 9: precondition predicates are codes the evaluator knows, never free code.
PREDICATES: tuple[str, ...] = (
    "previous_stage_released",
    "proofs_delivered",
    "no_open_cx_issues",
    "hold_gates_released",
    "plant_item_delivered",
    "delivery_limit_agreed",
    "authority_acceptance_present",
    "systems_released",
    "documentation_slots_delivered",
)

ACCEPTANCE_KINDS: tuple[str, ...] = (
    "partial_package",
    "partial_section",
    "total",
    "handover_to_operation",
    "authority",
)
CONTRACT_BASES: tuple[str, ...] = ("statute", "standard_form")
DEEMED_TRIGGERS: tuple[str, ...] = ("completion_notice", "use_start", "deadline_set")
LEGAL_EFFECTS: tuple[str, ...] = (
    "risk_transfer",
    "limitation_starts",
    "payment_due",
    "retention_release_part",
    "liquidated_damages_end",
    "burden_of_proof_shifts",
    "defects_period_starts",
    "occupation_permitted",
    "insurance_responsibility_shifts",
)
# Effects that write somewhere when confirmed (rule 15); the rest are recorded and notified only.
WARRANTY_EFFECTS: tuple[str, ...] = ("limitation_starts", "defects_period_starts")

PRESERVATION_SUBJECTS: tuple[str, ...] = (
    "neighbour_building",
    "own_existing_structure",
    "public_road",
    "utility",
    "heritage",
    "trees",
    "watercourse",
)
INFLUENCE_TRIGGERS: tuple[str, ...] = (
    "excavation",
    "piling",
    "dewatering",
    "vibration",
    "crane_oversail",
    "demolition",
)
SURVEY_METHODS: tuple[str, ...] = ("photo", "crack_mapping", "level_survey", "vibration_monitoring", "reality_capture")
SURVEY_PHASES: tuple[str, ...] = ("before", "during", "after", "on_complaint")
# A subset of what a requirement deliverable accepts; the catalogue is validated against that schema.
FM_DELIVERABLE_TYPES: tuple[str, ...] = ("cobie", "pset", "other")

# What makes an expert report due, and how often it recurs. An empty value means not stated.
EXPERT_REPORT_TRIGGERS: tuple[str, ...] = (
    "before_start",
    "before_concreting",
    "before_concealment",
    "after_installation",
    "before_commissioning",
    "before_acceptance",
    "on_defect",
    "on_change",
    "periodic",
)
EXPERT_REPORT_FREQUENCIES: tuple[str, ...] = (
    "once",
    "per_floor",
    "per_section",
    "per_package",
    "weekly",
    "monthly",
    "quarterly",
    "on_event",
)

STANDARD_MANDATE: tuple[str, ...] = ("statute", "contract", "voluntary")
PROOF_SOURCES: tuple[str, ...] = ("catalogue_default", "edited")
REQUIRED_BY_KINDS: tuple[str, ...] = ("stage", "acceptance_unit", "activity", "date")

__all__ = [
    "ACCEPTANCE_KINDS",
    "CERTIFICATION_PHASES",
    "CERTIFICATION_SCOPES",
    "CONTRACT_BASES",
    "DEEMED_TRIGGERS",
    "DELIVERER_ROLES",
    "EVIDENCE_KINDS",
    "EXPERT_REPORT_FREQUENCIES",
    "EXPERT_REPORT_TRIGGERS",
    "FM_DELIVERABLE_TYPES",
    "INFLUENCE_TRIGGERS",
    "LEGAL_EFFECTS",
    "LINK_KINDS",
    "MATERIAL_FAMILIES",
    "PARTY_ROLES",
    "PREDICATES",
    "PRESERVATION_SUBJECTS",
    "PROOF_SOURCES",
    "REQUIRED_BY_KINDS",
    "SCORE_UNITS",
    "STANDARD_MANDATE",
    "SURVEY_METHODS",
    "SURVEY_PHASES",
    "VERIFICATION_METHODS",
    "WARRANTY_EFFECTS",
]
