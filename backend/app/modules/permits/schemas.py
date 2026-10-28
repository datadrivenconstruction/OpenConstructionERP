# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request bodies of the permits API. Responses are plain dicts built by the service (``*_out``)."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Code = Field(pattern=r"^[a-z0-9][a-z0-9_]*$", max_length=64)
ApplicantRole = Literal["owner", "designer", "contractor", "operator"]
ConditionKind = Literal[
    "suspensive", "obligation", "time_limit", "revocation_reserve", "reserved_obligation", "information"
]
Trigger = Literal[
    "before_application_x",
    "before_start",
    "before_stage",
    "before_occupation",
    "ongoing",
    "by_date",
    "on_event",
    "after_completion",
]
Topic = Literal[
    "hse",
    "environment",
    "noise",
    "traffic",
    "heritage",
    "structural",
    "fire",
    "drainage",
    "ecology",
    "design",
    "admin",
    "other",
]


# The constraint kinds ``requirements.RequirementCreate`` accepts (rule 23); kept in step by a test.
ConstraintType = Literal[
    "equals", "not_equals", "min", "max", "range", "contains", "not_contains", "regex", "exists", "not_exists"
]


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class _Patch(_In):
    """A partial update. A field left out is untouched; ``null`` clears it, where the column can be empty.

    ``NOT_NULL`` names the fields whose column cannot: an explicit ``null`` there is refused
    as invalid input (422) instead of reaching the database.
    """

    NOT_NULL: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_null_on_required(self) -> Self:
        nulled = sorted(n for n in self.model_fields_set & self.NOT_NULL if getattr(self, n) is None)
        if nulled:
            raise ValueError(f"field_not_nullable: {', '.join(nulled)}")
        return self


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class RoadmapSet(_In):
    catalogue_source: Literal["shipped", "tenant"] | None = None
    catalogue_id: str | None = Field(default=None, max_length=64)
    catalogue_version: int | None = Field(default=None, ge=1)
    jurisdiction: str | None = Field(default=None, pattern=r"^[A-Za-z]{2}(-[A-Za-z0-9]{1,3})?$")
    route_assessment_id: uuid.UUID | None = None
    delivery_model_id: uuid.UUID | None = None
    approval_route_id: uuid.UUID | None = None
    internal_review: bool | None = None
    escalation_days: int | None = Field(default=None, ge=0, le=365)
    buffer_days: int | None = Field(default=None, ge=0, le=365)
    roadmap_area_code: str | None = Field(default=None, max_length=64)
    conditions_area_code: str | None = Field(default=None, max_length=64)


class ProposeIn(_In):
    route_assessment_id: uuid.UUID | None = None


class AcceptIn(_In):
    permit_type_codes: list[str] = Field(min_length=1)
    route_assessment_id: uuid.UUID | None = None
    change_request_id: uuid.UUID | None = None


class DependencyIn(_In):
    depends_on_id: uuid.UUID
    on: Literal["granted", "submitted"] = "granted"


class RequirementCreate(_In):
    permit_type_code: str = Code
    title: str = Field(default="", max_length=255)
    applicable: bool = True
    applicability_rationale: str = ""
    applicant_role: ApplicantRole | None = None
    applicant_rationale: str = ""
    applicant_party: str = Field(default="", max_length=255)
    applicant_contact_id: uuid.UUID | None = None
    responsible_user_id: uuid.UUID | None = None
    planned_submit_date: date | None = None
    needed_by_activity_id: uuid.UUID | None = None
    needed_by_date: date | None = None
    clock_variant: str = Field(default="", max_length=40)
    expected_decision_date: date | None = None
    schedule_activity_id: uuid.UUID | None = None
    governance_area_code: str | None = Field(default=None, max_length=64)
    # Edges the new requirement waits on: one structural change together with the requirement.
    dependencies: list[DependencyIn] = Field(default_factory=list)
    change_request_id: uuid.UUID | None = None


class RequirementPatch(_Patch):
    NOT_NULL: ClassVar[frozenset[str]] = frozenset(
        {
            "title",
            "applicable",
            "applicability_rationale",
            "applicant_role",
            "applicant_rationale",
            "applicant_party",
            "clock_variant",
            "governance_area_code",
            "conflict_accepted",
        }
    )

    title: str | None = Field(default=None, max_length=255)
    applicable: bool | None = None
    applicability_rationale: str | None = None
    applicant_role: ApplicantRole | None = None
    applicant_rationale: str | None = None
    applicant_party: str | None = Field(default=None, max_length=255)
    applicant_contact_id: uuid.UUID | None = None
    responsible_user_id: uuid.UUID | None = None
    planned_submit_date: date | None = None
    needed_by_activity_id: uuid.UUID | None = None
    needed_by_date: date | None = None
    clock_variant: str | None = Field(default=None, max_length=40)
    expected_decision_date: date | None = None
    schedule_activity_id: uuid.UUID | None = None
    governance_area_code: str | None = Field(default=None, max_length=64)
    conflict_accepted: bool | None = None
    change_request_id: uuid.UUID | None = None


class DependenciesPut(_In):
    dependencies: list[DependencyIn]
    change_request_id: uuid.UUID | None = None


class ApplicationCreate(_In):
    requirement_id: uuid.UUID
    kind: Literal[
        "new", "variation", "amendment_non_material", "extension_of_validity", "discharge_of_conditions", "early_start"
    ] = "new"
    parent_permit_id: uuid.UUID | None = None
    discharges_condition_ids: list[uuid.UUID] = Field(default_factory=list)
    authority_name: str = Field(default="", max_length=255)
    authority_reference: str = Field(default="", max_length=120)
    review_cycle_ids: list[uuid.UUID] = Field(default_factory=list)
    submission_id: uuid.UUID | None = None
    cde_container_id: uuid.UUID | None = None


class ApplicationPatch(_Patch):
    NOT_NULL: ClassVar[frozenset[str]] = frozenset(
        {"authority_name", "authority_reference", "review_cycle_ids", "appeal_note"}
    )

    authority_name: str | None = Field(default=None, max_length=255)
    authority_reference: str | None = Field(default=None, max_length=120)
    submitted_at: date | None = None
    received_at: date | None = None
    validated_at: date | None = None
    review_cycle_ids: list[uuid.UUID] | None = None
    submission_id: uuid.UUID | None = None
    cde_container_id: uuid.UUID | None = None
    appeal_note: str | None = None


class TransitionIn(_In):
    target: Literal[
        "preparing", "internal_review", "submitted", "validated", "under_review", "info_requested", "withdrawn"
    ]
    on_date: date | None = None
    reason: str = ""


class ClockEventIn(_In):
    kind: Literal["stop", "resume", "extension_agreed", "extension_by_authority"]
    at: date
    period: int | None = Field(default=None, ge=1, le=3650)
    unit: Literal["calendar_days", "working_days", "weeks", "months", "years"] | None = None
    reason: str = ""


class ConditionIn(_In):
    number: str = Field(min_length=1, max_length=40)
    text: str = Field(min_length=1)
    kind: ConditionKind
    national_kind: str = Field(default="", max_length=64)
    trigger: Trigger | Literal[""] = ""
    stage_ref: str = Field(default="", max_length=120)
    event_text: str = ""
    due_date: date | None = None
    topic: Topic = "other"
    purpose: Literal["", "restoration", "security"] = ""
    owner_user_id: uuid.UUID | None = None
    responsible_party: str = Field(default="", max_length=255)
    requires_authority_approval: bool = False
    evidence_required: str = ""
    hse_relevant: bool | None = None
    gate_condition_id: uuid.UUID | None = None


class ConditionProposal(ConditionIn):
    confidence: str = Field(pattern=r"^(0(\.\d{1,4})?|1(\.0{1,4})?)$")
    text_span: str = Field(default="", max_length=40)
    # The sentence of the notice the condition is taken from; ``text_span`` is only its locator.
    passage: str = Field(default="", max_length=2000)


class ProposalsIn(_In):
    proposals: list[ConditionProposal] = Field(min_length=1)


class ConditionPatch(_Patch):
    NOT_NULL: ClassVar[frozenset[str]] = frozenset(
        {
            "text",
            "kind",
            "trigger",
            "stage_ref",
            "event_text",
            "topic",
            "purpose",
            "responsible_party",
            "requires_authority_approval",
            "evidence_required",
        }
    )

    text: str | None = None
    kind: ConditionKind | None = None
    trigger: Trigger | Literal[""] | None = None
    stage_ref: str | None = Field(default=None, max_length=120)
    event_text: str | None = None
    due_date: date | None = None
    topic: Topic | None = None
    purpose: Literal["", "restoration", "security"] | None = None
    owner_user_id: uuid.UUID | None = None
    responsible_party: str | None = Field(default=None, max_length=255)
    requires_authority_approval: bool | None = None
    evidence_required: str | None = None
    hse_relevant: bool | None = None
    gate_condition_id: uuid.UUID | None = None


class DecisionIn(_In):
    outcome: Literal[
        "granted", "granted_with_conditions", "partially_granted", "refused", "deemed_granted", "withdrawn"
    ]
    decision_date: date
    served_date: date | None = None
    reference: str = Field(default="", max_length=120)
    scope_note: str = ""
    scope_activity_ids: list[uuid.UUID] = Field(default_factory=list)
    conditions: list[ConditionIn] = Field(default_factory=list)
    conditions_pending: bool = False
    appeal_deadline: date | None = None
    document_revision_id: uuid.UUID | None = None
    security_amount: str | None = Field(default=None, pattern=r"^\d{1,14}(\.\d{1,4})?$")
    security_currency: str = Field(default="", pattern=r"^([A-Za-z]{3})?$")
    discharged_condition_ids: list[uuid.UUID] | None = None
    removed_condition_numbers: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _money_has_currency(self) -> Self:
        if (self.security_amount is not None) != bool(self.security_currency):
            raise ValueError("security_needs_amount_and_currency")
        return self


class DecisionCorrection(_Patch):
    """A correction of how a decision was recorded; the outcome and the conditions are not correctable."""

    NOT_NULL: ClassVar[frozenset[str]] = frozenset({"decision_date", "reference", "scope_note"})

    reason: str = Field(min_length=1)
    decision_date: date | None = None
    served_date: date | None = None
    reference: str | None = Field(default=None, max_length=120)
    scope_note: str | None = None
    appeal_deadline: date | None = None
    document_revision_id: uuid.UUID | None = None


class StartNoticeIn(_In):
    on_date: date


class InterruptionIn(_In):
    on_date: date | None = None


class PermitTransitionIn(_In):
    target: Literal["suspended", "in_force", "revoked", "expired", "lapsed"]
    reason: str = ""


class EvidenceIn(_In):
    kind: Literal[
        "cde_revision", "inspection", "commissioning_item", "report", "photo", "external_url", "discharge_decision"
    ]
    ref_id: str = Field(default="", max_length=500)
    note: str = ""


class DischargeIn(_In):
    mode: Literal["self_certified", "not_triggered", "waived_by_authority", "authority_discharged", "deemed_discharged"]
    on_date: date | None = None
    document_revision_id: uuid.UUID | None = None
    note: str = ""


class BreachIn(_In):
    ref_kind: Literal["safety_observation", "inspection", "manual"] = "manual"
    ref_id: uuid.UUID | None = None
    note: str = ""


class NoteIn(_In):
    note: str = ""


class AssignIn(_In):
    condition_ids: list[uuid.UUID] = Field(min_length=1)
    owner_user_id: uuid.UUID


class ConfirmIn(_In):
    accept: bool


class RequirementFromConditionIn(_In):
    entity: str = Field(min_length=1, max_length=255)
    attribute: str = Field(min_length=1, max_length=255)
    constraint_type: ConstraintType = "equals"
    constraint_value: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=50)


class CatalogueCreate(_In):
    code: str = Code
    name: str = Field(min_length=1, max_length=255)
    based_on_source: Literal["shipped", "tenant"] | None = None
    based_on_id: str | None = None
    based_on_version: int | None = None


class CatalogueUpdate(_In):
    name: str | None = Field(default=None, max_length=255)
    body: dict[str, Any] | None = None
