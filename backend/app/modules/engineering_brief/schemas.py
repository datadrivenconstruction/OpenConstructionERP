# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Request schemas of the engineering brief API.

Quantities travel as strings, never floats. Platform vocabularies are closed literals; catalogue codes
(requirement categories, concept topics, programme and milestone kinds) are open strings checked against
the pinned catalogue by the service, because a tenant catalogue may add codes. Inputs forbid unknown
fields. An explicit null on a field the row cannot leave empty is a validation error, not a database
error.

The requirement schemas mirror the vocabularies of the requirements module and import them, so the two
cannot drift.
"""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.modules.requirements.lifecycle import ORIGINATOR_ROLES, PHASE_SPINE, VERIFICATION_METHODS

CatalogueSource = Literal["shipped", "tenant"]
ConstraintType = Literal[
    "equals", "not_equals", "min", "max", "range", "contains", "not_contains", "regex", "exists", "not_exists"
]
Priority = Literal["must", "should", "could", "wont"]
ConceptStatus = Literal["open", "agreed"]
MAX_LEAD_DAYS = 3650


def _no_float(value: Any) -> Any:
    if isinstance(value, float):
        raise ValueError("send decimals as strings")
    return value


class _In(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")


class Page[T](BaseModel):
    items: list[T]
    total: int
    offset: int = 0
    limit: int = 0


class FindingOut(BaseModel):
    rule_id: str
    passed: bool
    severity: str
    message: str
    element_ref: str | None = None
    suggestion: str | None = None


class BriefSet(_In):
    catalogue_source: CatalogueSource = "shipped"
    catalogue_id: str | None = Field(default=None, max_length=64)
    catalogue_version: int | None = None
    title: str = Field(default="", max_length=255)
    summary: str = Field(default="", max_length=20000)
    operation_proof_date: date | None = None


class BriefPatch(_In):
    title: str | None = Field(default=None, max_length=255)
    summary: str | None = Field(default=None, max_length=20000)
    operation_proof_date: date | None = None


# ── requirements ───────────────────────────────────────────────────────────


class RequirementIn(_In):
    entity: str = Field(min_length=1, max_length=255)
    attribute: str = Field(min_length=1, max_length=255)
    constraint_type: ConstraintType = "equals"
    constraint_value: str = Field(default="", max_length=500)
    unit: str = Field(default="", max_length=50)
    category: str = Field(min_length=1, max_length=100)
    priority: Priority = "must"
    verification_method: Literal[*VERIFICATION_METHODS, ""] = ""  # type: ignore[valid-type]
    originator: str = Field(default="", max_length=255)
    originator_role: Literal[*ORIGINATOR_ROLES, ""] = ""  # type: ignore[valid-type]
    source_ref: str = Field(default="", max_length=500)
    rationale: str = Field(default="", max_length=20000)
    phase: Literal[*PHASE_SPINE, ""] = ""  # type: ignore[valid-type]


class RequirementPatch(_In):
    entity: str | None = Field(default=None, min_length=1, max_length=255)
    attribute: str | None = Field(default=None, min_length=1, max_length=255)
    constraint_type: ConstraintType | None = None
    constraint_value: str | None = Field(default=None, max_length=500)
    unit: str | None = Field(default=None, max_length=50)
    category: str | None = Field(default=None, min_length=1, max_length=100)
    priority: Priority | None = None
    verification_method: Literal[*VERIFICATION_METHODS, ""] | None = None  # type: ignore[valid-type]
    originator: str | None = Field(default=None, max_length=255)
    originator_role: Literal[*ORIGINATOR_ROLES, ""] | None = None  # type: ignore[valid-type]
    source_ref: str | None = Field(default=None, max_length=500)
    rationale: str | None = Field(default=None, max_length=20000)
    phase: Literal[*PHASE_SPINE, ""] | None = None  # type: ignore[valid-type]


# ── technical concept ──────────────────────────────────────────────────────


class ConceptIn(_In):
    topic_code: str = Field(min_length=1, max_length=64)
    title: str = Field(min_length=1, max_length=255)
    description: str = Field(default="", max_length=20000)
    decision: str = Field(default="", max_length=20000)
    requirement_ids: list[uuid.UUID] = Field(default_factory=list, max_length=500)


class ConceptPatch(_In):
    topic_code: str | None = Field(default=None, min_length=1, max_length=64)
    title: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=20000)
    decision: str | None = Field(default=None, max_length=20000)
    requirement_ids: list[uuid.UUID] | None = Field(default=None, max_length=500)


class ConceptStatusIn(_In):
    status: ConceptStatus


# ── programme ──────────────────────────────────────────────────────────────


class ProgrammeIn(_In):
    kind_code: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=255)
    unit: str = Field(min_length=1, max_length=20)
    quantity: str = Field(max_length=32)
    basis: str = Field(default="", max_length=5000)

    @field_validator("quantity", mode="before")
    @classmethod
    def _decimal_string(cls, v: Any) -> Any:
        return _no_float(v)


class ProgrammePatch(_In):
    kind_code: str | None = Field(default=None, min_length=1, max_length=64)
    label: str | None = Field(default=None, min_length=1, max_length=255)
    unit: str | None = Field(default=None, min_length=1, max_length=20)
    quantity: str | None = Field(default=None, max_length=32)
    basis: str | None = Field(default=None, max_length=5000)

    @field_validator("quantity", mode="before")
    @classmethod
    def _decimal_string(cls, v: Any) -> Any:
        return _no_float(v)


# ── framework schedule ─────────────────────────────────────────────────────


class MilestoneIn(_In):
    kind_code: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=255)
    planned_date: date | None = None
    lead_days: int = Field(default=0, ge=0, le=MAX_LEAD_DAYS)
    successor_id: uuid.UUID | None = None
    gate_code: str | None = Field(default=None, max_length=64)
    permit_requirement_id: uuid.UUID | None = None
    notes: str = Field(default="", max_length=5000)


class MilestonePatch(_In):
    kind_code: str | None = Field(default=None, min_length=1, max_length=64)
    name: str | None = Field(default=None, min_length=1, max_length=255)
    planned_date: date | None = None
    lead_days: int | None = Field(default=None, ge=0, le=MAX_LEAD_DAYS)
    successor_id: uuid.UUID | None = None
    gate_code: str | None = Field(default=None, max_length=64)
    permit_requirement_id: uuid.UUID | None = None
    notes: str | None = Field(default=None, max_length=5000)


class BackplanIn(_In):
    # False: only report the dates a backward plan would give. True: write them (a human confirms).
    apply: bool = False


class MilestonesFromCatalogue(_In):
    codes: list[str] | None = Field(default=None, max_length=100)


# ── studies and the specification issue ────────────────────────────────────

STUDY_KIND = Literal["site_analysis", "suitability"]
STUDY_CONCLUSION = Literal["open", "suitable", "conditional", "unsuitable"]


class StudyIn(_In):
    kind: STUDY_KIND
    title: str = Field(min_length=1, max_length=255)
    scope: str = Field(default="", max_length=20000)
    author: str = Field(default="", max_length=255)
    study_date: date | None = None
    result: str = Field(default="", max_length=20000)
    conclusion: STUDY_CONCLUSION = "open"
    document_id: uuid.UUID | None = None


class StudyPatch(_In):
    kind: STUDY_KIND | None = None
    title: str | None = Field(default=None, min_length=1, max_length=255)
    scope: str | None = Field(default=None, max_length=20000)
    author: str | None = Field(default=None, max_length=255)
    study_date: date | None = None
    result: str | None = Field(default=None, max_length=20000)
    conclusion: STUDY_CONCLUSION | None = None
    document_id: uuid.UUID | None = None


class IssueIn(_In):
    note: str = Field(default="", max_length=5000)
