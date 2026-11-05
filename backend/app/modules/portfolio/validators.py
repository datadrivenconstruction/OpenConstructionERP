# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Portfolio validation rules (rule set ``portfolio``).

Rules run over a plain dict context built by the caller. A tree write supplies::

    {"node": {"id", "node_type", "code", "parent_type", "child_types", "sibling_codes"}}

and a cross-schedule link write supplies::

    {"cross_link": {"id", "predecessor_schedule_id", "predecessor_activity_id",
                    "successor_schedule_id", "successor_activity_id", "lag_days",
                    "duplicate", "reverse_exists"}}

A rule whose section is absent passes, so one rule set serves both write kinds.
"""

from __future__ import annotations

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import blank, section
from app.core.validation.quality_rules import QualityRule

PORTFOLIO_RULE_SET = "portfolio"

#: Outermost first: a portfolio holds programmes, a programme holds subprogrammes.
NODE_LEVELS = {"portfolio": 0, "programme": 1, "subprogramme": 2}

#: A lag between two projects beyond a year is almost always days typed as something else.
MAX_SANE_LAG_DAYS = 365


class _PortfolioRule(QualityRule):
    standard = PORTFOLIO_RULE_SET
    message_section = "portfolio"


class NodeCodeUniqueRule(_PortfolioRule):
    """Two nodes under the same parent do not share a code."""

    rule_id = "portfolio.node_code_unique"
    name = "Node code is unique among its siblings"
    description = "a non-blank code must not repeat under the same parent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        node = section(context, "node")
        ref = str(node.get("id", ""))
        code = str(node.get("code") or "").strip().casefold()
        taken = {str(c).strip().casefold() for c in node.get("sibling_codes") or []}
        if code and code in taken:
            return [self.fail(context, "code_duplicate", ref=ref, code=str(node.get("code")).strip())]
        return [self.ok(ref)]


class NodeLevelOrderRule(_PortfolioRule):
    """A node never outranks the node it sits under, nor one of its own children."""

    rule_id = "portfolio.node_level_order"
    name = "Node type fits its place in the tree"
    description = "portfolio > programme > subprogramme; a node may not outrank its parent"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        node = section(context, "node")
        ref = str(node.get("id", ""))
        level = NODE_LEVELS.get(str(node.get("node_type")))
        if level is None:
            return [self.ok(ref)]
        parent = NODE_LEVELS.get(str(node.get("parent_type")))
        if parent is not None and level < parent:
            return [
                self.fail(context, "level_order", ref=ref, child=node.get("node_type"), parent=node.get("parent_type"))
            ]
        for child_type in node.get("child_types") or []:
            child = NODE_LEVELS.get(str(child_type))
            if child is not None and child < level:
                return [self.fail(context, "level_order", ref=ref, child=child_type, parent=node.get("node_type"))]
        return [self.ok(ref)]


class CrossLinkEndpointsRule(_PortfolioRule):
    """A cross-schedule link joins two different activities, and normally two different schedules."""

    rule_id = "portfolio.link_endpoints_distinct"
    name = "Cross-schedule link joins two different schedules"
    description = (
        "an activity cannot be linked to itself (error); a link inside one schedule is an ordinary dependency (warning)"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "cross_link")
        ref = str(link.get("id", ""))
        if blank(link.get("predecessor_activity_id")):
            return [self.ok(ref)]
        if str(link.get("predecessor_activity_id")) == str(link.get("successor_activity_id")):
            return [self.fail(context, "link_endpoints", ref=ref)]
        if str(link.get("predecessor_schedule_id")) == str(link.get("successor_schedule_id")):
            return [self.fail(context, "link_endpoints", ref=ref, severity=Severity.WARNING)]
        return [self.ok(ref)]


class CrossLinkNoLoopRule(_PortfolioRule):
    """A link is not entered twice, nor against an existing link in the opposite direction."""

    rule_id = "portfolio.link_no_duplicate_or_loop"
    name = "Cross-schedule link is new and does not close a loop"
    description = "the same pair cannot be linked twice, and A->B with B->A makes the critical path undefined"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "cross_link")
        ref = str(link.get("id", ""))
        if link.get("duplicate"):
            return [self.fail(context, "link_repeats", ref=ref)]
        if link.get("reverse_exists"):
            return [self.fail(context, "link_repeats", ref=ref)]
        return [self.ok(ref)]


class CrossLinkLagRule(_PortfolioRule):
    """The lag between two projects is within a year."""

    rule_id = "portfolio.link_lag_sane"
    name = "Cross-schedule lag is plausible"
    severity = Severity.WARNING
    description = "a lag beyond 365 days either way is probably a unit slip"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        link = section(context, "cross_link")
        ref = str(link.get("id", ""))
        try:
            lag = int(link.get("lag_days") or 0)
        except (TypeError, ValueError):
            return [self.ok(ref)]
        if abs(lag) > MAX_SANE_LAG_DAYS:
            return [self.fail(context, "lag_extreme", ref=ref, days=lag)]
        return [self.ok(ref)]


PORTFOLIO_RULES = (
    NodeCodeUniqueRule,
    NodeLevelOrderRule,
    CrossLinkEndpointsRule,
    CrossLinkNoLoopRule,
    CrossLinkLagRule,
)


def register_portfolio_validation_rules() -> None:
    """Register the portfolio rules with the platform rule registry."""
    for rule_class in PORTFOLIO_RULES:
        rule_registry.register(rule_class(), [PORTFOLIO_RULE_SET])


__all__ = ["PORTFOLIO_RULES", "PORTFOLIO_RULE_SET", "register_portfolio_validation_rules"]
