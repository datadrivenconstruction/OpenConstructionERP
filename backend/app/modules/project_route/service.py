# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Business logic for the work-type route classifier.

The heart of the module is a small, ordered **decision tree expressed as data**
(:data:`DEFAULT_ROUTE_RULES`) and one pure function, :func:`classify`, that walks
it. Keeping the tree as data - not branching code - is the whole point: a
regional pack can hand :func:`classify` a different ``rules`` tuple to map the
generic routes onto its own procedures (RU new build / reconstruction / capital
repair / re-equipment; US as-of-right zoning; UK permitted development) without
touching this engine, and the built-in tree never encodes one country's law.

Everything the service adds on top (persistence, confirm, the ``draft`` gate) is
plain CRUD around that classification.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException
from fastapi import status as http_status

from app.modules.project_route.models import RouteAssessment
from app.modules.project_route.repository import RouteAssessmentRepository
from app.modules.project_route.schemas import RouteAssessmentCreate, RouteAssessmentUpdate

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════
# Decision tree (data)
# ═══════════════════════════════════════════════════════════════════════


@dataclass(frozen=True)
class RouteRule:
    """One row of the decision tree.

    A rule fires when a candidate's ``work_type`` equals :attr:`work_type` and
    **every** key in :attr:`conditions` matches the corresponding criterion.
    Rules are evaluated in order and the first match wins, so specific rules
    (more conditions) must precede the catch-all for a work type (an empty
    ``conditions`` dict, which always matches).

    Attributes:
        work_type: The work type this rule applies to.
        conditions: Criterion key -> expected value. Booleans are matched
            leniently (``"yes"`` / ``1`` / ``True`` all read as true); strings
            are matched case-insensitively; a missing criterion never matches.
        route: The route code to return (see ``ROUTE_OPTIONS``).
        rationale: Human-readable explanation of why this route was chosen.
        confidence: The tree's self-reported certainty in ``0.0-1.0``.
    """

    work_type: str
    conditions: dict[str, Any]
    route: str
    rationale: str
    confidence: float = field(default=0.75)


# The built-in, jurisdiction-neutral tree. Ordered: specific rules first, a
# catch-all per work type last. Regional packs override by passing their own
# tuple to ``classify`` / ``RouteService(..., rules=...)``.
#
# Recognised generic criterion keys:
#   affects_structure       (bool)  - work touches load-bearing structure
#   scale                   (str)   - "minor" | "major"
#   changes_use             (bool)  - alters the use class of the asset
#   within_permitted_limits (bool)  - within the local permitted / notification
#                                      threshold (packs define the threshold)
#   heritage_protected      (bool)  - listed / protected / heritage asset
DEFAULT_ROUTE_RULES: tuple[RouteRule, ...] = (
    # ── New build ──────────────────────────────────────────────────────
    RouteRule(
        "new_build",
        {"heritage_protected": True},
        "expertise_required",
        "New build on a protected or heritage-constrained site: a full permit "
        "with independent design expertise is required.",
        0.9,
    ),
    RouteRule(
        "new_build",
        {"scale": "major"},
        "expertise_required",
        "Major new build: a full permit plus independent design and structural expertise is required.",
        0.9,
    ),
    RouteRule(
        "new_build",
        {},
        "full_permit",
        "New build: a full construction permit is required.",
        0.75,
    ),
    # ── Reconstruction ─────────────────────────────────────────────────
    RouteRule(
        "reconstruction",
        {"affects_structure": True},
        "full_permit",
        "Reconstruction affecting the load-bearing structure: a full permit is required.",
        0.9,
    ),
    RouteRule(
        "reconstruction",
        {},
        "notification",
        "Reconstruction that does not affect the structure: a prior "
        "notification to the authority is normally sufficient.",
        0.7,
    ),
    # ── Capital repair ─────────────────────────────────────────────────
    RouteRule(
        "capital_repair",
        {"affects_structure": True},
        "full_permit",
        "Capital repair that touches the structure is treated as structural work: a full permit is required.",
        0.85,
    ),
    RouteRule(
        "capital_repair",
        {},
        "notification",
        "Capital repair that does not affect the structure: notification only.",
        0.8,
    ),
    # ── Re-equipment ───────────────────────────────────────────────────
    RouteRule(
        "re_equipment",
        {"affects_structure": True},
        "notification",
        "Re-equipment that affects the structure or core building systems: notify the authority.",
        0.75,
    ),
    RouteRule(
        "re_equipment",
        {},
        "exempt",
        "Re-equipment (replacing plant or equipment) with no structural impact: exempt from permit.",
        0.8,
    ),
    # ── Maintenance ────────────────────────────────────────────────────
    RouteRule(
        "maintenance",
        {},
        "exempt",
        "Routine maintenance: exempt from permit.",
        0.85,
    ),
    # ── Demolition ─────────────────────────────────────────────────────
    RouteRule(
        "demolition",
        {"heritage_protected": True},
        "full_permit",
        "Demolition of a protected or heritage asset: a full permit / consent is required.",
        0.9,
    ),
    RouteRule(
        "demolition",
        {},
        "notification",
        "Demolition: a prior notification to the authority is required.",
        0.75,
    ),
    # ── Change of use ──────────────────────────────────────────────────
    RouteRule(
        "change_of_use",
        {"within_permitted_limits": True},
        "permitted_development",
        "Change of use within the permitted limits: proceeds as permitted development.",
        0.8,
    ),
    RouteRule(
        "change_of_use",
        {},
        "full_permit",
        "Change of use beyond the permitted limits: a full permit is required.",
        0.75,
    ),
    # ── Fallback ───────────────────────────────────────────────────────
    RouteRule(
        "other",
        {},
        "undetermined",
        "Work type not classified: a manual assessment is required.",
        0.3,
    ),
)

# Returned when no rule matches at all (e.g. an unknown work type from a pack).
_UNDETERMINED = (
    "undetermined",
    "No rule matched this work type: a manual assessment is required.",
    0.2,
)

_TRUE_TOKENS: frozenset[str] = frozenset({"true", "yes", "y", "1", "on"})


def _as_bool(value: Any) -> bool:
    """Lenient truth test for a criterion value.

    ``True`` / ``"yes"`` / ``"true"`` / ``1`` all read as true; everything else
    (including ``None`` and unknown strings) reads as false.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.strip().lower() in _TRUE_TOKENS
    return False


def _matches(expected: Any, actual: Any) -> bool:
    """Does a single criterion ``actual`` satisfy a rule's ``expected`` value?"""
    if isinstance(expected, bool):
        return _as_bool(actual) == expected
    if isinstance(expected, str):
        return isinstance(actual, str) and actual.strip().lower() == expected.strip().lower()
    return actual == expected


def classify(
    work_type: str,
    criteria: dict[str, Any] | None = None,
    *,
    rules: tuple[RouteRule, ...] = DEFAULT_ROUTE_RULES,
) -> tuple[str, str, float]:
    """Resolve a ``work_type`` + ``criteria`` to ``(route, rationale, confidence)``.

    Pure function: no session, no clock, no side effects, so the whole decision
    tree is unit-testable in isolation. Walks ``rules`` in order and returns the
    first rule whose work type and conditions all match; falls back to
    ``undetermined`` when nothing matches.

    Args:
        work_type: The project's work type (see ``WORK_TYPES``).
        criteria: The classifier answers. ``None`` is treated as empty.
        rules: The decision tree to walk. Defaults to the built-in,
            jurisdiction-neutral :data:`DEFAULT_ROUTE_RULES`; a regional pack
            passes its own tuple here.

    Returns:
        A ``(determined_route, rationale, confidence)`` triple.
    """
    answers = criteria or {}
    for rule in rules:
        if rule.work_type != work_type:
            continue
        if all(_matches(expected, answers.get(key)) for key, expected in rule.conditions.items()):
            return rule.route, rule.rationale, rule.confidence
    return _UNDETERMINED


class RouteService:
    """Business logic for the work-type route classifier."""

    def __init__(
        self,
        session: object,
        *,
        rules: tuple[RouteRule, ...] = DEFAULT_ROUTE_RULES,
    ) -> None:
        self.session = session
        self.rules = rules
        self.repo = RouteAssessmentRepository(session)  # type: ignore[arg-type]

    @staticmethod
    def _now() -> datetime:
        return datetime.now(UTC)

    def classify(self, work_type: str, criteria: dict[str, Any] | None) -> tuple[str, str, float]:
        """Run the decision tree (stateless) using this service's rule set."""
        return classify(work_type, criteria, rules=self.rules)

    # ── CRUD ────────────────────────────────────────────────────────────

    async def create_assessment(
        self,
        data: RouteAssessmentCreate,
        *,
        user_id: str | None = None,
    ) -> RouteAssessment:
        if data.determined_route is not None:
            # Human override: honour the explicit route, low confidence because
            # it was set by hand rather than derived.
            route = data.determined_route
            rationale = "Route set manually."
            confidence = 0.5
        else:
            route, rationale, confidence = self.classify(data.work_type, data.criteria)

        assessment = RouteAssessment(
            project_id=data.project_id,
            work_type=data.work_type,
            criteria=data.criteria,
            determined_route=route,
            rationale=rationale,
            confidence=confidence,
            status="draft",
            classified_at=self._now(),
            classified_by=user_id,
            metadata_=data.metadata,
        )
        assessment = await self.repo.create(assessment)
        logger.info(
            "Route assessment created: %s (%s -> %s) for project %s",
            assessment.id,
            assessment.work_type,
            assessment.determined_route,
            assessment.project_id,
        )
        return assessment

    async def get_assessment(self, assessment_id: uuid.UUID) -> RouteAssessment:
        row = await self.repo.get_by_id(assessment_id)
        if row is None:
            raise HTTPException(
                status_code=http_status.HTTP_404_NOT_FOUND,
                detail="Route assessment not found.",
            )
        return row

    async def list_assessments(
        self,
        project_id: uuid.UUID,
        *,
        status: str | None = None,
        work_type: str | None = None,
    ) -> list[RouteAssessment]:
        return await self.repo.list_for_project(
            project_id,
            status=status,
            work_type=work_type,
        )

    async def update_assessment(
        self,
        assessment_id: uuid.UUID,
        data: RouteAssessmentUpdate,
        *,
        user_id: str | None = None,
    ) -> RouteAssessment:
        assessment = await self.get_assessment(assessment_id)
        fields: dict[str, Any] = data.model_dump(exclude_unset=True)

        new_work_type = fields.get("work_type", assessment.work_type)
        new_criteria = fields.get("criteria", assessment.criteria)

        # Re-classification: any change to the inputs (or the presence of an
        # explicit override) re-derives the route and returns the row to draft.
        reclassify = "work_type" in fields or "criteria" in fields or "determined_route" in fields
        if reclassify:
            if fields.get("determined_route") is not None:
                fields["determined_route"] = fields["determined_route"]
                fields["rationale"] = "Route set manually."
                fields["confidence"] = 0.5
            else:
                route, rationale, confidence = self.classify(new_work_type, new_criteria)
                fields["determined_route"] = route
                fields["rationale"] = rationale
                fields["confidence"] = confidence
            fields["status"] = "draft"
            fields["classified_at"] = self._now()
            if user_id is not None:
                fields["classified_by"] = user_id

        if "metadata" in fields:
            incoming = fields.pop("metadata")
            merged = dict(assessment.metadata_ or {})
            if isinstance(incoming, dict):
                merged.update(incoming)
            fields["metadata_"] = merged

        for key, value in fields.items():
            setattr(assessment, key, value)
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(assessment)  # type: ignore[attr-defined]
        return assessment

    async def confirm_assessment(
        self,
        assessment_id: uuid.UUID,
        *,
        user_id: str | None = None,
    ) -> RouteAssessment:
        """Confirm an assessment's route - the gate the project proceeds under.

        An ``undetermined`` route cannot be confirmed: it is not a decision.
        """
        assessment = await self.get_assessment(assessment_id)
        if assessment.determined_route == "undetermined":
            raise HTTPException(
                status_code=http_status.HTTP_400_BAD_REQUEST,
                detail="Cannot confirm an undetermined route - classify it first.",
            )
        assessment.status = "confirmed"
        assessment.classified_at = self._now()
        if user_id is not None:
            assessment.classified_by = user_id
        await self.session.flush()  # type: ignore[attr-defined]
        await self.session.refresh(assessment)  # type: ignore[attr-defined]
        logger.info("Route assessment confirmed: %s (%s)", assessment.id, assessment.determined_route)
        return assessment

    async def delete_assessment(self, assessment_id: uuid.UUID) -> None:
        await self.get_assessment(assessment_id)
        await self.repo.delete(assessment_id)
