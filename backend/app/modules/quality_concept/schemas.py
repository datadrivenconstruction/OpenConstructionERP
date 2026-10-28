# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request bodies of the quality concept API.

Responses are plain dicts built in the router (``_out`` helpers), one shape per
entity, documented in the module's API contract. Points are Decimal strings;
calendar days ISO ``YYYY-MM-DD``.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.quality_concept import vocab

_CODE = r"^[a-z0-9][a-z0-9_]*$"


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


def _one_of(values: tuple[str, ...]) -> Any:
    def check(v: Any) -> Any:
        if v is not None and v not in values:
            raise ValueError(f"must be one of {', '.join(values)}")
        return v

    return check


def _points(v: Any) -> Any:
    if v is None:
        return v
    if isinstance(v, float):
        raise ValueError("send points as a decimal string")
    d = Decimal(str(v))
    if not d.is_finite() or d < 0:
        raise ValueError("points must be a finite, non-negative decimal")
    return d


# ── concept ────────────────────────────────────────────────────────────────


class PackageScopeIn(_In):
    ref: str = Field(min_length=1, max_length=64)
    code: str = Field(default="", max_length=64)
    title: str = Field(default="", max_length=255)
    no_proofs_rationale: str = Field(default="", max_length=2000)


class ConceptPatch(_In):
    packages: list[PackageScopeIn] | None = Field(default=None, max_length=500)
    holidays: list[date] | None = Field(default=None, max_length=400)
    documentation_set_code: str | None = Field(default=None, max_length=40)


class CataloguePin(_In):
    catalogue_source: Literal["shipped", "tenant", "pack"] = "shipped"
    catalogue_id: str = Field(min_length=1, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)


# ── standards and requirements ─────────────────────────────────────────────


class StandardIn(_In):
    code: str = Field(min_length=1, max_length=120)
    edition: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=500)
    family_code: str | None = Field(default=None, max_length=64)
    discipline: str = Field(default="", max_length=40)
    package_refs: list[str] = Field(default_factory=list, max_length=200)
    source_url: str | None = Field(default=None, max_length=500)
    mandate: str = "contract"
    note: str = Field(default="", max_length=5000)

    _m = field_validator("mandate")(_one_of(vocab.STANDARD_MANDATE))


class StandardPatch(_In):
    code: str | None = Field(default=None, min_length=1, max_length=120)
    edition: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=500)
    family_code: str | None = Field(default=None, max_length=64)
    discipline: str | None = Field(default=None, max_length=40)
    package_refs: list[str] | None = Field(default=None, max_length=200)
    source_url: str | None = Field(default=None, max_length=500)
    mandate: str | None = None
    note: str | None = Field(default=None, max_length=5000)

    _m = field_validator("mandate")(_one_of(vocab.STANDARD_MANDATE))


class QualityRequirementIn(_In):
    category: str = Field(pattern=r"^quality\.[a-z0-9_]+$", max_length=64)
    entity: str = Field(min_length=1, max_length=255)
    attribute: str = Field(min_length=1, max_length=255)
    constraint_value: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=50)
    source_ref: str = Field(default="", max_length=500)
    verification_method: str | None = None
    rationale: str = Field(default="", max_length=5000)

    _vm = field_validator("verification_method")(_one_of(vocab.VERIFICATION_METHODS))


# ── certification ──────────────────────────────────────────────────────────


class CertificationIn(_In):
    scheme_code: str = Field(pattern=_CODE, max_length=64)
    scheme_version: str = Field(default="", max_length=40)
    scope: str = "building"
    target_level: str = Field(pattern=_CODE, max_length=40)
    assessor_contact_id: uuid.UUID | None = None
    registration_no: str = Field(default="", max_length=120)
    points_available: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)

    _s = field_validator("scope")(_one_of(vocab.CERTIFICATION_SCOPES))


class CertificationPatch(_In):
    scheme_version: str | None = Field(default=None, max_length=40)
    target_level: str | None = Field(default=None, pattern=_CODE, max_length=40)
    assessor_contact_id: uuid.UUID | None = None
    registration_no: str | None = Field(default=None, max_length=120)
    points_available: Decimal | None = Field(default=None, gt=0, max_digits=12, decimal_places=4)
    certificate_cde_id: uuid.UUID | None = None


class CertificationTransition(_In):
    action: Literal["register", "assess_design", "assess_post_construction", "certify", "miss_level", "abandon"]
    achieved_level: str | None = Field(default=None, pattern=_CODE, max_length=40)
    rationale: str = Field(default="", max_length=5000)
    on: date | None = None


class CreditIn(_In):
    credit_code: str = Field(min_length=1, max_length=64)
    category: str = Field(default="", max_length=64)
    points_targeted: Decimal = Decimal("0")
    owner_user_id: uuid.UUID | None = None

    _p = field_validator("points_targeted", mode="before")(_points)


class CreditPatch(_In):
    category: str | None = Field(default=None, max_length=64)
    points_targeted: Decimal | None = None
    points_achieved: Decimal | None = None
    owner_user_id: uuid.UUID | None = None
    action: Literal["submit_evidence", "achieve", "not_achieve", "return", "drop", "reinstate"] | None = None

    _p = field_validator("points_targeted", "points_achieved", mode="before")(_points)


class CreditBulk(_In):
    items: list[CreditIn] = Field(min_length=1, max_length=200)


# ── proofs and evidence ────────────────────────────────────────────────────


class QuantityRuleIn(_In):
    per_quantity: Decimal
    unit: str = Field(max_length=20)
    min_count: int = Field(default=1, ge=1, le=10000)
    placed_quantity: Decimal | None = None

    _p = field_validator("per_quantity", "placed_quantity", mode="before")(_points)


class ProofIn(_In):
    package_ref: str | None = Field(default=None, max_length=64)
    plant_item_id: str | None = Field(default=None, max_length=36)
    cx_system_id: uuid.UUID | None = None
    evidence_type: str = Field(pattern=_CODE, max_length=64)
    title: str = Field(default="", max_length=500)
    deliverer_role: str
    deliverer_contact_id: uuid.UUID | None = None
    required_by_kind: str
    required_by_ref: str = Field(min_length=1, max_length=64)
    quantity_rule: QuantityRuleIn | None = None
    review_by_role: str = Field(default="", max_length=30)

    _d = field_validator("deliverer_role")(_one_of(vocab.DELIVERER_ROLES))
    _r = field_validator("required_by_kind")(_one_of(vocab.REQUIRED_BY_KINDS))


class ProofPatch(_In):
    title: str | None = Field(default=None, max_length=500)
    deliverer_role: str | None = None
    deliverer_contact_id: uuid.UUID | None = None
    required_by_kind: str | None = None
    required_by_ref: str | None = Field(default=None, min_length=1, max_length=64)
    quantity_rule: QuantityRuleIn | None = None
    review_by_role: str | None = Field(default=None, max_length=30)

    _d = field_validator("deliverer_role")(_one_of(vocab.DELIVERER_ROLES))
    _r = field_validator("required_by_kind")(_one_of(vocab.REQUIRED_BY_KINDS))


class ProofGenerateIn(_In):
    package_ref: str = Field(min_length=1, max_length=64)
    evidence_types: list[str] | None = Field(default=None, max_length=100)
    confirm: list[str] | None = Field(default=None, max_length=100)


class WaiverRequest(_In):
    rationale: str = Field(min_length=1, max_length=5000)


class WaiverDecision(_In):
    approve: bool


class EvidenceLinkIn(_In):
    owner_kind: Literal["proof", "credit", "stage_progress", "preservation", "expert_report"]
    owner_id: uuid.UUID
    link_kind: str
    link_id: str = Field(min_length=1, max_length=36)
    retest_of: str | None = Field(default=None, max_length=36)
    note: str = Field(default="", max_length=2000)

    _k = field_validator("link_kind")(_one_of(vocab.LINK_KINDS))


# ── stages ─────────────────────────────────────────────────────────────────


class PreconditionIn(_In):
    code: str
    params: dict[str, Any] = Field(default_factory=dict)

    _c = field_validator("code")(_one_of(vocab.PREDICATES))


class StageDefIn(_In):
    code: str = Field(pattern=_CODE, max_length=40)
    order: int = Field(ge=0, le=1000)
    name_override: str = Field(default="", max_length=255)
    owner_user_id: uuid.UUID | None = None
    release_party_role: str = "qa"
    preconditions: list[PreconditionIn] = Field(default_factory=list, max_length=20)
    evidence_types: list[str] = Field(default_factory=list, max_length=50)
    applies_to: dict[str, Any] = Field(default_factory=lambda: {"mode": "all"})

    _p = field_validator("release_party_role")(_one_of(vocab.PARTY_ROLES))


class StageDefPatch(_In):
    order: int | None = Field(default=None, ge=0, le=1000)
    name_override: str | None = Field(default=None, max_length=255)
    owner_user_id: uuid.UUID | None = None
    release_party_role: str | None = None
    release_user_ids: list[uuid.UUID] | None = Field(default=None, max_length=50)
    preconditions: list[PreconditionIn] | None = Field(default=None, max_length=20)
    evidence_types: list[str] | None = Field(default=None, max_length=50)
    applies_to: dict[str, Any] | None = None

    _p = field_validator("release_party_role")(_one_of(vocab.PARTY_ROLES))


class StageResultIn(_In):
    result: Literal["pass", "fail"]
    note: str = Field(default="", max_length=5000)
    severity: Literal["low", "medium", "high", "critical"] = "high"


class RationaleIn(_In):
    rationale: str = Field(min_length=1, max_length=5000)


class DependsOnIn(_In):
    system_ids: list[uuid.UUID] = Field(default_factory=list, max_length=200)


# ── acceptance ─────────────────────────────────────────────────────────────


class AcceptancePreconditionsIn(_In):
    stages: list[str] = Field(default_factory=list, max_length=20)
    evidence_types: list[str] = Field(default_factory=list, max_length=50)
    slot_keys: list[str] = Field(default_factory=list, max_length=50)
    include_units: list[uuid.UUID] = Field(default_factory=list, max_length=200)


class AcceptanceUnitIn(_In):
    code: str = Field(default="", max_length=40)
    title: str = Field(default="", max_length=500)
    kind: str
    package_refs: list[str] = Field(default_factory=list, max_length=200)
    section_ref: str = Field(default="", max_length=255)
    regime_code: str | None = Field(default=None, pattern=_CODE, max_length=40)
    planned_date: date | None = None
    schedule_activity_id: str | None = Field(default=None, max_length=36)
    preconditions: AcceptancePreconditionsIn = Field(default_factory=AcceptancePreconditionsIn)

    _k = field_validator("kind")(_one_of(vocab.ACCEPTANCE_KINDS))


class AcceptanceUnitPatch(_In):
    code: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=500)
    package_refs: list[str] | None = Field(default=None, max_length=200)
    section_ref: str | None = Field(default=None, max_length=255)
    regime_code: str | None = Field(default=None, pattern=_CODE, max_length=40)
    planned_date: date | None = None
    schedule_activity_id: str | None = Field(default=None, max_length=36)
    preconditions: AcceptancePreconditionsIn | None = None
    handover_package_id: uuid.UUID | None = None


class AcceptanceRequestIn(_In):
    with_reservations: bool = False
    notes: dict[str, str] = Field(default_factory=dict)


class AcceptanceRecordIn(_In):
    completion_notice_at: date | None = None
    use_started_at: date | None = None
    deadline_at: date | None = None


class AcceptanceRefuseIn(_In):
    rationale: str = Field(min_length=1, max_length=5000)
    defects: list[str] = Field(default_factory=list, max_length=500)


class EffectConfirmIn(_In):
    effect: str
    effective_date: date | None = None
    warranty_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)

    _e = field_validator("effect")(_one_of(vocab.LEGAL_EFFECTS))


# ── preservation and expert reports ────────────────────────────────────────


class PreservationIn(_In):
    subject_kind: str
    subject_ref: str = Field(min_length=1, max_length=64)
    address: str = Field(default="", max_length=500)
    parcel: str = Field(default="", max_length=120)
    owner_contact_id: uuid.UUID | None = None
    influence_triggers: list[str] = Field(default_factory=list, max_length=10)
    trigger_activities: dict[str, Any] = Field(default_factory=dict)
    phase: str = "before"
    methods: list[str] = Field(default_factory=list, max_length=10)
    surveyor_contact_id: uuid.UUID | None = None
    planned_date: date | None = None
    paired_with_id: uuid.UUID | None = None
    lat: Decimal | None = Field(default=None, ge=-90, le=90)
    lng: Decimal | None = Field(default=None, ge=-180, le=180)

    _s = field_validator("subject_kind")(_one_of(vocab.PRESERVATION_SUBJECTS))
    _p = field_validator("phase")(_one_of(vocab.SURVEY_PHASES))

    @field_validator("influence_triggers")
    @classmethod
    def _triggers(cls, v: list[str]) -> list[str]:
        bad = [t for t in v if t not in vocab.INFLUENCE_TRIGGERS]
        if bad:
            raise ValueError(f"unknown triggers: {bad}")
        return v

    @field_validator("methods")
    @classmethod
    def _methods(cls, v: list[str]) -> list[str]:
        bad = [m for m in v if m not in vocab.SURVEY_METHODS]
        if bad:
            raise ValueError(f"unknown survey methods: {bad}")
        return v


class PreservationPatch(_In):
    address: str | None = Field(default=None, max_length=500)
    parcel: str | None = Field(default=None, max_length=120)
    owner_contact_id: uuid.UUID | None = None
    influence_triggers: list[str] | None = Field(default=None, max_length=10)
    trigger_activities: dict[str, Any] | None = None
    methods: list[str] | None = Field(default=None, max_length=10)
    surveyor_contact_id: uuid.UUID | None = None
    planned_date: date | None = None
    lat: Decimal | None = Field(default=None, ge=-90, le=90)
    lng: Decimal | None = Field(default=None, ge=-180, le=180)


class PreservationAction(_In):
    action: Literal["invite", "record_survey", "issue_report", "close", "refuse_access"]
    on: date | None = None
    owner_acknowledged: bool | None = None
    acknowledgment_cde_id: uuid.UUID | None = None
    note: str = Field(default="", max_length=5000)


class PairIn(_In):
    before_id: uuid.UUID


class ExpertReportIn(_In):
    subject: str = Field(min_length=1, max_length=500)
    expert_contact_id: uuid.UUID | None = None
    trigger: str = Field(default="", max_length=40)
    frequency: str = Field(default="", max_length=40)
    due_dates: list[date] = Field(default_factory=list, max_length=200)

    _t = field_validator("trigger")(_one_of(("", *vocab.EXPERT_REPORT_TRIGGERS)))
    _f = field_validator("frequency")(_one_of(("", *vocab.EXPERT_REPORT_FREQUENCIES)))
    commitment_ref: str | None = Field(default=None, max_length=64)
    state: Literal["planned", "commissioned", "reporting", "completed", "cancelled"] = "planned"


class ExpertReportPatch(_In):
    subject: str | None = Field(default=None, min_length=1, max_length=500)
    expert_contact_id: uuid.UUID | None = None
    trigger: str | None = Field(default=None, max_length=40)
    frequency: str | None = Field(default=None, max_length=40)
    due_dates: list[date] | None = Field(default=None, max_length=200)

    _t = field_validator("trigger")(_one_of(("", *vocab.EXPERT_REPORT_TRIGGERS)))
    _f = field_validator("frequency")(_one_of(("", *vocab.EXPERT_REPORT_FREQUENCIES)))
    commitment_ref: str | None = Field(default=None, max_length=64)
    state: Literal["planned", "commissioned", "reporting", "completed", "cancelled"] | None = None
