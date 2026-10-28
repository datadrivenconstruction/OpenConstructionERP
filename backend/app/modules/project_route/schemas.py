# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pydantic schemas for the work-type route classifier."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

# ── Canonical vocabularies (open-ended; packs may extend via the DB) ───
#
# These are the built-in, jurisdiction-neutral code sets. The DB columns are
# plain String so a regional pack can persist a value outside these lists
# without a migration; the API validates against the union so the built-in UI
# pickers stay honest.

WORK_TYPES: tuple[str, ...] = (
    "new_build",  # a wholly new structure
    "reconstruction",  # rebuilding / substantial alteration of an existing one
    "capital_repair",  # major repair restoring an asset (may touch structure)
    "re_equipment",  # replacing plant / equipment / building systems
    "maintenance",  # routine upkeep
    "demolition",  # taking a structure down
    "change_of_use",  # a use-class change without major works
    "other",
)

ROUTE_OPTIONS: tuple[str, ...] = (
    "full_permit",  # a full construction / building permit is required
    "notification",  # a prior notification to the authority suffices
    "permitted_development",  # proceeds under a permitted-development regime
    "exempt",  # no permit or notification required
    "expertise_required",  # needs independent design / structural expertise (+ permit)
    "undetermined",  # the tree could not settle a route - manual assessment
)

STATUSES: tuple[str, ...] = ("draft", "confirmed")

_WORK_TYPE_PATTERN = "^(" + "|".join(WORK_TYPES) + ")$"
_ROUTE_PATTERN = "^(" + "|".join(ROUTE_OPTIONS) + ")$"


# ── Classify (stateless) ───────────────────────────────────────────────


class ClassifyRequest(BaseModel):
    """Body for ``POST /v1/project-route/classify`` - does not persist."""

    model_config = ConfigDict(str_strip_whitespace=True)

    work_type: str = Field(..., pattern=_WORK_TYPE_PATTERN)
    criteria: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Classifier answers. Recognised generic keys: affects_structure "
            "(bool), scale ('minor'|'major'), changes_use (bool), "
            "within_permitted_limits (bool), heritage_protected (bool)."
        ),
    )


class ClassifyResult(BaseModel):
    """The route the decision tree resolved for a work type + criteria."""

    model_config = ConfigDict(str_strip_whitespace=True)

    work_type: str
    determined_route: str
    rationale: str
    confidence: float = Field(..., ge=0.0, le=1.0)


# ── Create ─────────────────────────────────────────────────────────────


class RouteAssessmentCreate(BaseModel):
    """Body for ``POST /v1/project-route/assessments``.

    The route, rationale and confidence are derived from ``work_type`` +
    ``criteria`` by the classifier on create; supplying ``determined_route``
    overrides the tree (an explicit human decision), which drops confidence to
    reflect that it was set by hand rather than derived.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    project_id: UUID
    work_type: str = Field(..., pattern=_WORK_TYPE_PATTERN)
    criteria: dict[str, Any] = Field(default_factory=dict)
    determined_route: str | None = Field(default=None, pattern=_ROUTE_PATTERN)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Update ─────────────────────────────────────────────────────────────


class RouteAssessmentUpdate(BaseModel):
    """Body for ``PATCH /v1/project-route/assessments/{id}``.

    Changing ``work_type`` or ``criteria`` re-runs the classifier (unless an
    explicit ``determined_route`` is supplied) and returns the row to ``draft``.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    work_type: str | None = Field(default=None, pattern=_WORK_TYPE_PATTERN)
    criteria: dict[str, Any] | None = None
    determined_route: str | None = Field(default=None, pattern=_ROUTE_PATTERN)
    metadata: dict[str, Any] | None = None


# ── Response ───────────────────────────────────────────────────────────


class RouteAssessmentResponse(BaseModel):
    """A route assessment returned from the API."""

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)

    id: UUID
    project_id: UUID
    work_type: str
    criteria: dict[str, Any] = Field(default_factory=dict)
    determined_route: str = "undetermined"
    rationale: str = ""
    confidence: float = 0.0
    status: str = "draft"
    classified_at: datetime | None = None
    classified_by: str | None = None
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        validation_alias="metadata_",
    )
    created_at: datetime
    updated_at: datetime


__all__ = [
    "ROUTE_OPTIONS",
    "STATUSES",
    "WORK_TYPES",
    "ClassifyRequest",
    "ClassifyResult",
    "RouteAssessmentCreate",
    "RouteAssessmentResponse",
    "RouteAssessmentUpdate",
]
