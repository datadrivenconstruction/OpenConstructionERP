# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Validation rule set ``schedule_delay`` for forensic delay analyses.

Rules read a plain payload so they stay pure:

    {"analysis": {"id", "name", "has_baseline"},
     "events": [{"id", "code", "outside_project_dates", "fragnet_cycle"}]}

An analysis without a baseline cannot say what the plan was, an event dated
outside the project cannot have delayed it, and a fragnet that closes a logic
loop makes the schedule impossible to calculate.
"""

from __future__ import annotations

from typing import Any

from app.core.validation.engine import (
    RuleCategory,
    RuleResult,
    Severity,
    ValidationContext,
    ValidationRule,
    rule_registry,
)

DELAY_RULE_SET = "schedule_delay"


def fragnet_makes_cycle(activities: list[Any], spec: dict[str, Any]) -> bool:
    """Whether splicing an event's fragnets into ``activities`` closes a logic loop."""
    from app.modules.schedule_advanced.cpm import CycleError, critical_path
    from app.modules.schedule_advanced.delay_engine import apply_fragnets
    from app.modules.schedule_advanced.delay_report import build_engine_event

    try:
        net = apply_fragnets(list(activities), build_engine_event(spec).fragnets)
        critical_path(net)
    except CycleError:
        return True
    return False


def _data(context: ValidationContext) -> dict[str, Any]:
    return context.data if isinstance(context.data, dict) else {}


class _DelayRule(ValidationRule):
    standard = "schedule_delay"
    category = RuleCategory.CONSISTENCY
    severity = Severity.WARNING
    key = ""
    text = ""

    def _result(self, ref: str, passed: bool, **params: Any) -> RuleResult:
        return RuleResult(
            rule_id=self.rule_id,
            rule_name=self.name,
            severity=self.severity,
            category=self.category,
            passed=passed,
            message="OK" if passed else self.text.format(**params),
            element_ref=ref,
            details={"message_key": f"schedule.delay.rules.{self.key}", **{k: str(v) for k, v in params.items()}},
        )


class AnalysisHasBaseline(_DelayRule):
    """The analysis names the as-planned baseline it measures against."""

    key = "no_baseline"
    rule_id = "delay_analysis.no_baseline"
    name = "Delay Analysis Has A Baseline"
    description = "A delay analysis is tied to a stored as-planned baseline."
    text = "{analysis} has no as-planned baseline, so the slip has nothing to be measured against"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        a = _data(context).get("analysis")
        if not isinstance(a, dict):
            return []
        return [self._result(str(a.get("id") or ""), bool(a.get("has_baseline")), analysis=a.get("name") or "")]


class EventInsideProjectDates(_DelayRule):
    """A delay event lies within the project's start and finish."""

    key = "event_outside_project_dates"
    rule_id = "delay_analysis.event_outside_project_dates"
    name = "Event Inside Project Dates"
    description = "Every delay event starts and ends between the project start and its current finish."
    text = "Event {event} is dated outside the project, so it cannot be a cause of delay"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for ev in _data(context).get("events") or []:
            if isinstance(ev, dict) and ev.get("outside_project_dates") is not None:
                out.append(
                    self._result(str(ev.get("id") or ""), not ev["outside_project_dates"], event=ev.get("code") or "")
                )
        return out


class FragnetHasNoCycle(_DelayRule):
    """A fragnet does not close a logic loop in the schedule."""

    key = "fragnet_cycle"
    rule_id = "delay_analysis.fragnet_cycle"
    name = "Fragnet Has No Logic Cycle"
    description = "Inserting the event's fragnet leaves the network acyclic."
    severity = Severity.ERROR
    text = "The fragnet of event {event} creates a logic loop, so the schedule cannot be calculated"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        out = []
        for ev in _data(context).get("events") or []:
            if isinstance(ev, dict) and ev.get("fragnet_cycle") is not None:
                out.append(self._result(str(ev.get("id") or ""), not ev["fragnet_cycle"], event=ev.get("code") or ""))
        return out


DELAY_RULES: tuple[type[_DelayRule], ...] = (AnalysisHasBaseline, EventInsideProjectDates, FragnetHasNoCycle)


def register_delay_rules() -> None:
    """Idempotently register the delay-analysis rules."""
    for rule in DELAY_RULES:
        rule_registry.register(rule(), rule_sets=[DELAY_RULE_SET])


async def run_delay_rules(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Every delay-analysis rule against one payload, as plain dicts."""
    context = ValidationContext(data=payload, metadata={})
    out: list[dict[str, Any]] = []
    for rule_cls in DELAY_RULES:
        for r in await rule_cls().validate(context):
            out.append(
                {
                    "rule_id": r.rule_id,
                    "passed": r.passed,
                    "severity": str(getattr(r.severity, "value", r.severity)),
                    "message": r.message,
                    "element_ref": r.element_ref,
                    "details": r.details,
                }
            )
    return out


register_delay_rules()
