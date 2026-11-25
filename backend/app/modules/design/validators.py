"""Validation rules of the Design module.

Rule set ``design``, run over one project (``GET /api/v1/design/projects/{id}/validation``):

* ``design.estimate_unpriced`` - WARNING. A position the model drives has no unit rate, so the design
  estimate total leaves it out. Nothing is guessed: the person prices it or picks a cost item.
* ``design.estimate_quantity_missing`` - WARNING. A position the rules drive got no quantity (nothing matched)
  or some selected elements lack the measured quantity, so the estimate is short. Kept overrides pass.
* ``design.revision_awaiting_decision`` - INFO. A shared revision has waited longer than
  ``REVIEW_AFTER_DAYS`` for acceptance; the estimate, schedule and procurement still follow the older one.
* ``design.brief_plausible`` - ERROR. A short brief for the quick massing contradicts itself or the country's
  minimum (storeys over the height limit, footprint over the plot, clear height under the minimum).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)
from app.core.validation.messages import translate

DESIGN_RULE_SET = "design"
REVIEW_AFTER_DAYS = 14


def _locale(context: ValidationContext) -> str:
    return str((context.metadata or {}).get("locale") or "en")


def _as_dt(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _zero(value: Any) -> bool:
    try:
        return Decimal(str(value)) == 0
    except (InvalidOperation, ValueError):
        return True


class EstimateUnpriced(ValidationRule):
    """Every model-driven estimate position carries a unit rate."""

    rule_id = "design.estimate_unpriced"
    name = "Design estimate positions are priced"
    standard = DESIGN_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A position the model drives has no unit rate, so the estimate total leaves it out."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        locale = _locale(context)
        results: list[RuleResult] = []
        for pos in data.get("positions") or []:
            missing = _zero(pos.get("unit_rate"))
            text = str(pos.get("description") or pos.get("rule") or "")
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not missing,
                    message=translate("design.estimate_unpriced.fail", locale, position=text) if missing else "OK",
                    element_ref=str(pos.get("position_id") or "") or None,
                    suggestion=translate("design.estimate_unpriced.suggestion", locale) if missing else None,
                    details={"rule": pos.get("rule"), "unit": pos.get("unit")},
                )
            )
        return results


class EstimateQuantityMissing(ValidationRule):
    """Every rule-driven estimate position has a quantity taken from all its elements."""

    rule_id = "design.estimate_quantity_missing"
    name = "Design estimate positions have quantities"
    standard = DESIGN_RULE_SET
    severity = Severity.WARNING
    category = RuleCategory.COMPLETENESS
    description = "A position matched no elements, or some of its elements carry no measured quantity."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        locale = _locale(context)
        results: list[RuleResult] = []
        for pos in data.get("positions") or []:
            flags = set(pos.get("flags") or [])
            if "override" in flags:
                missing = False
            else:
                missing = "quantity_missing" in flags or "no_match" in flags or _zero(pos.get("quantity"))
            text = str(pos.get("description") or pos.get("rule") or "")
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not missing,
                    message=translate("design.estimate_quantity_missing.fail", locale, position=text)
                    if missing
                    else "OK",
                    element_ref=str(pos.get("position_id") or "") or None,
                    suggestion=translate("design.estimate_quantity_missing.suggestion", locale) if missing else None,
                    details={"rule": pos.get("rule"), "unit": pos.get("unit"), "flags": sorted(flags)},
                )
            )
        return results


class RevisionAwaitingDecision(ValidationRule):
    """A shared revision is accepted or rejected within the review window."""

    rule_id = "design.revision_awaiting_decision"
    name = "Design revisions are decided in time"
    standard = DESIGN_RULE_SET
    severity = Severity.INFO
    category = RuleCategory.CONSISTENCY
    description = "A shared model revision has waited too long for acceptance."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        data = context.data if isinstance(context.data, dict) else {}
        now = _as_dt(data.get("as_of")) or datetime.now(UTC)
        locale = _locale(context)
        results: list[RuleResult] = []
        for rev in data.get("revisions") or []:
            if rev.get("status") != "shared":
                continue
            created = _as_dt(rev.get("created_at"))
            if created is None:
                continue
            age = (now - created).days
            late = age > REVIEW_AFTER_DAYS
            results.append(
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=not late,
                    message=translate(
                        "design.revision_awaiting_decision.fail", locale, number=rev.get("number"), days=age
                    )
                    if late
                    else "OK",
                    element_ref=str(rev.get("revision_id") or "") or None,
                    suggestion=translate("design.revision_awaiting_decision.suggestion", locale) if late else None,
                    details={"age_days": age, "review_after_days": REVIEW_AFTER_DAYS},
                )
            )
        return results


class BriefPlausible(ValidationRule):
    """A quick-massing brief is consistent: storeys, height, footprint, plot and country minimum agree."""

    rule_id = "design.brief_plausible"
    name = "Design brief is plausible"
    standard = DESIGN_RULE_SET
    severity = Severity.ERROR
    category = RuleCategory.CONSISTENCY
    description = "Storeys, floor height, GFA, plot and height limit of the brief contradict each other."

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        from .quick import check

        data = context.data if isinstance(context.data, dict) else {}
        brief = data.get("quick_brief")
        if not isinstance(brief, dict):
            return []
        locale = _locale(context)
        issues = check(brief)
        if not issues:
            return [
                RuleResult(
                    rule_id=self.rule_id,
                    rule_name=self.name,
                    severity=self.severity,
                    category=self.category,
                    passed=True,
                    message="OK",
                )
            ]
        return [
            RuleResult(
                rule_id=self.rule_id,
                rule_name=self.name,
                severity=Severity.ERROR if i["severity"] == "error" else Severity.WARNING,
                category=self.category,
                passed=False,
                message=translate(f"design.brief_plausible.{i['code']}", locale, **i["params"]),
                element_ref=i["field"],
                details={"code": i["code"], **i["params"]},
            )
            for i in issues
        ]


_RULES: list[ValidationRule] = [
    EstimateUnpriced(),
    EstimateQuantityMissing(),
    RevisionAwaitingDecision(),
    BriefPlausible(),
]


def register_design_rules() -> None:
    """Register the rule set; idempotent."""
    for rule in _RULES:
        rule_registry.register(rule, [DESIGN_RULE_SET])


async def validation_data(session: Any, project_id: uuid.UUID) -> dict[str, Any]:
    """What the rule set reads: the design estimate positions and the revisions awaiting a decision."""
    from sqlalchemy import select

    from .brief import current_brief
    from .estimate import summary
    from .models import DesignRevision
    from .quick import from_brief_doc

    est = await summary(session, project_id)
    rows = (
        await session.execute(
            select(DesignRevision).where(DesignRevision.project_id == project_id, DesignRevision.status == "shared")
        )
    ).scalars()
    return {
        "quick_brief": from_brief_doc(await current_brief(session, project_id)),
        "positions": est.get("positions", []) if est.get("estimate") else [],
        "revisions": [
            {
                "revision_id": str(r.id),
                "number": r.number,
                "status": r.status,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ],
    }


async def run(session: Any, project_id: uuid.UUID, locale: str = "en") -> tuple[dict[str, Any], Any]:
    """Run the ``design`` rule set over one project: the data it read and the engine report."""
    from app.core.validation.engine import validation_engine
    from app.core.validation.project_context import with_project_context

    data = await with_project_context(session, project_id, await validation_data(session, project_id))
    report = await validation_engine.validate(
        data=data,
        rule_sets=[DESIGN_RULE_SET],
        target_type="design_project",
        target_id=str(project_id),
        project_id=str(project_id),
        metadata={"locale": locale},
    )
    return data, report


async def record(session: Any, project_id: uuid.UUID, user_id: uuid.UUID | None, source: str) -> Any:
    """Run the rule set and store the report, so the project's validation view lists the design next to the bill."""
    from app.modules.validation.service import ValidationModuleService

    _, report = await run(session, project_id)
    return await ValidationModuleService(session).record_report(
        project_id, "design_project", str(project_id), report, [DESIGN_RULE_SET], user_id=user_id, source=source
    )


register_design_rules()
