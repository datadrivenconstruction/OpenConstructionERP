# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request bodies of the design management API (Pydantic v2).

Responses are plain dicts built by ``router._out`` from the ORM rows (every
column, ``status`` mirrored as ``state``), wrapped in the list envelope
``{items, total, offset, limit}``. Inputs forbid unknown fields so a typo is a
422, not a silently ignored key.
"""

from __future__ import annotations

from datetime import date
from typing import Any, ClassVar, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

Code = Field(default=None, min_length=1, max_length=40, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
Phase = Field(default=None, min_length=1, max_length=64)
Purpose = Literal["for_approval", "for_review", "for_information", "for_construction", "for_tender", "for_record"]
Suitability = Field(default=None, pattern=r"^(S0|S1|S2|S3|S4|S6|S7|A1|A2|A3|A4|A5)$")


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    #: Keys that may be left out of a PATCH but never sent as ``null``: their column is NOT NULL.
    #: An explicit null on one is a 422 naming the field, never a database error.
    NOT_NULL: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="after")
    def _no_explicit_null(self) -> _In:
        nulls = sorted(k for k in self.model_fields_set & self.NOT_NULL if getattr(self, k) is None)
        if nulls:
            raise ValueError(f"null is not allowed for: {', '.join(nulls)}")
        return self


class SetupCreate(_In):
    scheme_source: Literal["shipped", "tenant"] = "shipped"
    scheme_id: str | None = Field(default=None, max_length=64)
    scheme_version: int | None = Field(default=None, ge=1)
    reports_source: Literal["shipped", "tenant"] = "shipped"
    reports_id: str | None = Field(default=None, max_length=64)
    reports_version: int | None = Field(default=None, ge=1)
    four_eyes_release: bool = True


class SetupPatch(_In):
    NOT_NULL = frozenset(
        {
            "four_eyes_release",
            "default_distribution_purpose",
            "hierarchical_codes",
            "wbs_separator",
            "target_suitability",
        }
    )

    four_eyes_release: bool | None = None
    default_distribution_purpose: Purpose | None = None
    hierarchical_codes: bool | None = None
    wbs_separator: str | None = Field(default=None, min_length=1, max_length=1, pattern=r"^[.\-/]$")
    target_suitability: dict[str, str] | None = None
    approval_route_id: UUID | None = None
    release_route_id: UUID | None = None
    lead_designer_role_id: UUID | None = None


class SchemeChange(_In):
    source: Literal["shipped", "tenant"] = "shipped"
    id: str = Field(min_length=1, max_length=64)
    version: int | None = Field(default=None, ge=1)
    catalogue: Literal["numbering", "reports"] = "numbering"


class WbsCreate(_In):
    code: str = Field(min_length=1, max_length=50)
    name: str = Field(default="", max_length=255)
    parent_id: UUID | None = None
    kind: Literal["location", "system", "package", "phase", "cost"] = "package"
    discipline: str | None = Field(default=None, max_length=20)
    wbs_type: str = Field(default="cost", max_length=50)
    sort_order: int = 0


class WbsPatch(_In):
    NOT_NULL = frozenset({"code", "name", "kind"})

    code: str | None = Field(default=None, min_length=1, max_length=50)
    name: str | None = Field(default=None, max_length=255)
    parent_id: UUID | None = None
    kind: Literal["location", "system", "package", "phase", "cost"] | None = None
    discipline: str | None = Field(default=None, max_length=20)


class WbsClose(_In):
    closed: bool = True


class RenumberPreview(_In):
    code: str = Field(min_length=1, max_length=50)


class RoleIn(_In):
    NOT_NULL = frozenset({"code", "title", "party_kind", "responsible_wbs_ids", "state"})

    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    party_kind: (
        Literal[
            "owner",
            "lead_designer",
            "discipline_designer",
            "specialist",
            "checker",
            "authority",
            "contractor_designer",
        ]
        | None
    ) = None
    discipline_code: str | None = Field(default=None, max_length=20)
    contact_id: UUID | None = None
    user_id: UUID | None = None
    originator_code: str | None = Field(default=None, max_length=20, pattern=r"^[A-Za-z0-9]*$")
    contract_package_id: UUID | None = None
    responsible_wbs_ids: list[UUID] | None = None
    state: Literal["planned", "appointed", "active", "released"] | None = None


class ApprovalPointIn(_In):
    NOT_NULL = frozenset({"code", "title", "kind", "note"})

    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    phase_code: str | None = Phase
    kind: Literal["owner_approval", "user_signoff", "cost_check", "authority", "internal_review"] | None = None
    governance_gate_id: UUID | None = None
    approver_role_id: UUID | None = None
    note: str | None = Field(default=None, max_length=4000)


class DeliverableIn(_In):
    NOT_NULL = frozenset(
        {
            "code",
            "title",
            "planned_count",
            "planned_count_rationale",
            "required",
            "required_for",
            "waived",
            "waived_rationale",
        }
    )

    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    phase_code: str | None = Phase
    role_id: UUID | None = None
    discipline_code: str | None = Field(default=None, max_length=20)
    form_code: str | None = Field(default=None, max_length=20)
    wbs_node_id: UUID | None = None
    planned_count: int | None = Field(default=None, ge=0, le=10000)
    planned_count_rationale: str | None = Field(default=None, max_length=4000)
    schedule_activity_id: UUID | None = None
    required: bool | None = None
    required_for: list[UUID] | None = None
    target_suitability: str | None = Suitability
    waived: bool | None = None
    waived_rationale: str | None = Field(default=None, max_length=4000)


class NumberRequest(_In):
    role_id: UUID | None = None
    phase_code: str | None = Phase
    sheet_size: str | None = Field(default=None, max_length=10)
    wbs_node_id: UUID | None = None
    fields: dict[str, str] = Field(default_factory=dict)


class NumberValidate(_In):
    number: str = Field(min_length=1, max_length=255)


class RenumberApply(_In):
    mapping: dict[UUID, str] = Field(min_length=1)


class DrawingCreate(NumberRequest):
    number: str | None = Field(default=None, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    scale: str | None = Field(default=None, max_length=40)
    deliverable_id: UUID | None = None
    planned_first_issue: date | None = None
    forecast_issue: date | None = None
    schedule_activity_id: UUID | None = None


class DrawingPatch(_In):
    NOT_NULL = frozenset({"title", "scale", "sheet_size"})

    title: str | None = Field(default=None, max_length=500)
    scale: str | None = Field(default=None, max_length=40)
    sheet_size: str | None = Field(default=None, max_length=10)
    phase_code: str | None = Phase
    deliverable_id: UUID | None = None
    wbs_node_id: UUID | None = None
    role_id: UUID | None = None
    planned_first_issue: date | None = None
    forecast_issue: date | None = None
    schedule_activity_id: UUID | None = None
    title_block_number: str | None = Field(default=None, max_length=255)


class Supersede(_In):
    by_container_id: UUID


class TitleBlock(_In):
    text: str = Field(min_length=1, max_length=20000)


class DistRuleIn(_In):
    """``purpose`` null or absent = the rule applies to releases of any purpose."""

    NOT_NULL = frozenset(
        {
            "discipline_codes",
            "form_codes",
            "phase_codes",
            "wbs_node_ids",
            "format",
            "copies_paper",
            "ack_required",
            "active",
        }
    )

    recipient_list_id: UUID | None = None
    recipient_role_id: UUID | None = None
    discipline_codes: list[str] | None = None
    form_codes: list[str] | None = None
    phase_codes: list[str] | None = None
    wbs_node_ids: list[UUID] | None = None
    min_suitability: str | None = Suitability
    purpose: Purpose | None = None
    format: Literal["pdf", "native", "both"] | None = None
    copies_paper: int | None = Field(default=None, ge=0, le=100)
    ack_required: bool | None = None
    active: bool | None = None


class ReleaseIn(_In):
    NOT_NULL = frozenset({"code", "title", "purpose", "revision_ids"})

    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    purpose: Purpose | None = None
    revision_ids: list[UUID] | None = None


class Transition(_In):
    target: str = Field(min_length=1, max_length=30)
    rationale: str = Field(default="", max_length=4000)


class IssueIn(_In):
    duplicate_reason: str = Field(default="", max_length=4000)


class ReviewIn(_In):
    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    phase_code: str | None = Phase
    deliverable_ids: list[UUID] = Field(default_factory=list)
    reviewer_role_ids: list[UUID] = Field(default_factory=list)


class Conclude(_In):
    outcome: Literal["accepted", "accepted_with_comments", "rework"]


class CommentIn(_In):
    revision_id: UUID | None = None
    text: str = Field(min_length=1, max_length=8000)
    severity: Literal["minor", "major", "critical"] = "minor"


class CommentMove(_In):
    target: Literal["answered", "closed", "open", "rejected"]
    answer: str = Field(default="", max_length=8000)
    role_id: UUID | None = None


class ReportIn(_In):
    NOT_NULL = frozenset(
        {
            "code",
            "kind_code",
            "title",
            "external_check",
            "required",
            "independent_check",
            "rationale",
            "conditions_text",
        }
    )

    code: str | None = Code
    kind_code: str | None = Field(default=None, max_length=40)
    title: str | None = Field(default=None, max_length=255)
    phase_code: str | None = Phase
    author_role_id: UUID | None = None
    checker_role_id: UUID | None = None
    container_id: UUID | None = None
    external_check: bool | None = None
    review_cycle_id: UUID | None = None
    required: bool | None = None
    independent_check: Literal["none", "optional", "required_by_rule"] | None = None
    rationale: str | None = Field(default=None, max_length=4000)
    conditions_text: str | None = Field(default=None, max_length=8000)
    from_catalogue: bool = False


class PermitIn(_In):
    NOT_NULL = frozenset({"code", "title", "profile_code"})

    code: str | None = Code
    title: str | None = Field(default=None, max_length=255)
    profile_code: str | None = Field(default=None, max_length=40)
    authority_submission_id: UUID | None = None
    review_cycle_id: UUID | None = None
    permit_application_id: UUID | None = None
    target_submission_date: date | None = None
    schedule_activity_id: UUID | None = None


class PermitItemIn(_In):
    kind: Literal["drawing", "report", "form"]
    title: str = Field(default="", max_length=255)
    container_id: UUID | None = None
    report_id: UUID | None = None
    required: bool = True


class ConditionProposal(_In):
    text: str = Field(min_length=1, max_length=4000)
    owner_user_id: UUID | None = None
    due_date: date | None = None


class ConditionsIn(_In):
    conditions: list[ConditionProposal] = Field(min_length=1)


class ConditionDecision(_In):
    confirm: bool


def dump(model: BaseModel) -> dict[str, Any]:
    """Only the fields the client sent, JSON-shaped (UUIDs and dates as strings)."""
    return model.model_dump(mode="json", exclude_unset=True)
