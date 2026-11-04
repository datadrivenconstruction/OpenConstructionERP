# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Pure, database-free commissioning validation and readiness math.

This module is deliberately side-effect free so it can be unit tested without a
database and reused from the service, a report generator or a test. It answers
two questions about a commissionable system:

1. **How ready is it?** ``compute_readiness`` turns the status of a system's
   *functional* checklist items (plus its open critical issue count) into an
   explainable readiness figure - the percent of applicable functional items
   that have passed - with every component it was derived from exposed so a
   reader can reproduce the number by hand.
2. **May it be commissioned?** The same call decides ``can_commission`` and
   lists the human-readable ``blocking_reasons`` when it may not. The gate is:
   no open functional checklist item (every functional item is ``pass`` or
   ``na``) and no open ``critical`` issue, with at least one applicable
   functional item to pass.

Items marked ``na`` (not applicable) are excluded from the denominator, matching
standard commissioning practice: readiness is measured over the tests that
actually apply to the system.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from app.core.validation.engine import RuleResult, Severity, ValidationContext, rule_registry
from app.core.validation.money_rules import MoneyRule, blank, section

# ── Vocabulary ─────────────────────────────────────────────────────────────

ITEM_PENDING = "pending"
ITEM_PASS = "pass"
ITEM_FAIL = "fail"
ITEM_NA = "na"

#: Canonical set of checklist-item result statuses.
ITEM_STATUSES: tuple[str, ...] = (ITEM_PENDING, ITEM_PASS, ITEM_FAIL, ITEM_NA)

#: Canonical set of checklist kinds; only ``functional`` items gate readiness.
CHECKLIST_KINDS: tuple[str, ...] = ("prefunctional", "functional")

#: Canonical CxSystem lifecycle statuses, in order.
SYSTEM_STATUSES: tuple[str, ...] = (
    "not_started",
    "in_progress",
    "tests_complete",
    "commissioned",
)

#: Canonical issue severities, low to high.
ISSUE_SEVERITIES: tuple[str, ...] = ("low", "medium", "high", "critical")


def compute_readiness(
    functional_item_statuses: Iterable[str],
    open_critical_issues: int = 0,
) -> dict[str, Any]:
    """Return an explainable commissioning-readiness breakdown.

    Args:
        functional_item_statuses: The ``status`` of every *functional*
            checklist item on the system (any casing). Unrecognised values are
            treated conservatively as ``pending`` so a malformed status never
            counts as passed.
        open_critical_issues: Count of ``critical`` issues on the system that
            are still ``open``. Negative or non-integer input is coerced to 0.

    Returns:
        A dictionary exposing the derived figure and every component it was
        built from::

            {
                "functional_total": int,
                "functional_passed": int,
                "functional_failed": int,
                "functional_pending": int,
                "functional_na": int,
                "applicable": int,            # total - na
                "open_functional_items": int, # failed + pending
                "open_critical_issues": int,
                "readiness_pct": float,       # 0.0-100.0
                "defined": bool,              # False when applicable == 0
                "can_commission": bool,
                "readiness_level": str,       # "green" | "amber" | "red"
                "blocking_reasons": list[str],
                "formula": str,
            }

        The result never contains ``NaN`` or infinity: with no applicable items
        the percent is a well-defined ``0.0`` flagged ``defined=False`` so a
        caller can render "no data" rather than a misleading zero.
    """
    passed = failed = na = pending = 0
    for raw in functional_item_statuses:
        status = (raw or "").strip().lower() if isinstance(raw, str) else ""
        if status == ITEM_PASS:
            passed += 1
        elif status == ITEM_FAIL:
            failed += 1
        elif status == ITEM_NA:
            na += 1
        else:
            # ``pending`` and any unknown value are conservatively "not done".
            pending += 1

    total = passed + failed + na + pending
    applicable = total - na
    open_functional = failed + pending

    try:
        crit = int(open_critical_issues)
    except (TypeError, ValueError):
        crit = 0
    crit = max(0, crit)

    if applicable > 0:
        readiness_pct = round(passed / applicable * 100.0, 2)
        defined = True
    else:
        readiness_pct = 0.0
        defined = False

    # The commission gate: at least one applicable item, all applicable items
    # passed (no open functional item), and no open critical issue.
    can_commission = defined and open_functional == 0 and crit == 0

    blocking_reasons: list[str] = []
    if total == 0:
        blocking_reasons.append("This system has no functional checklist items to test.")
    elif applicable == 0:
        blocking_reasons.append("Every functional checklist item is marked not applicable; at least one must pass.")
    elif open_functional > 0:
        blocking_reasons.append(f"{open_functional} functional checklist item(s) are not passed yet.")
    if crit > 0:
        blocking_reasons.append(f"{crit} critical issue(s) are still open.")

    if crit > 0 or failed > 0 or not defined:
        readiness_level = "red"
    elif can_commission:
        readiness_level = "green"
    else:
        readiness_level = "amber"

    return {
        "functional_total": total,
        "functional_passed": passed,
        "functional_failed": failed,
        "functional_pending": pending,
        "functional_na": na,
        "applicable": applicable,
        "open_functional_items": open_functional,
        "open_critical_issues": crit,
        "readiness_pct": readiness_pct,
        "defined": defined,
        "can_commission": can_commission,
        "readiness_level": readiness_level,
        "blocking_reasons": blocking_reasons,
        "formula": "functional_passed / (functional_total - functional_na) * 100",
    }


# ── Engine rules (rule set ``commissioning``) ─────────────────────────────
#
# Rules run over a plain dict built by the service:
#   {"issue": {"id", "severity", "status", "resolution"}}
#   {"system": {"id", "status", "can_commission", "blocking_reasons"}}
#   {"result": {"id", "kind", "status", "result_note"},
#    "prefunctional": {"failed", "pending"}}
# Each rule reads only the section for the write it guards.

COMMISSIONING_RULE_SET = "commissioning"
_HARD_SEVERITIES = frozenset({"high", "critical"})


class _CommissioningRule(MoneyRule):
    standard = COMMISSIONING_RULE_SET
    message_section = "commissioning"
    suggestion_key = "commissioning.suggestion"


class IssueClosedHasResolutionRule(_CommissioningRule):
    """A closed issue says how it was resolved; high and critical ones must."""

    rule_id = "commissioning.issue_closed_has_resolution"
    name = "Closed issue records its resolution"
    description = "A high or critical issue cannot be closed without a resolution; lower severities are warned"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        issue = section(context, "issue")
        ref = str(issue.get("id", ""))
        if issue.get("status") != "closed" or not blank(issue.get("resolution")):
            return [self.ok(ref)]
        severity = Severity.ERROR if issue.get("severity") in _HARD_SEVERITIES else Severity.WARNING
        return [
            self.fail(context, "issue_closed_has_resolution", ref=ref, severity=severity, level=issue.get("severity"))
        ]


class SystemTestsCompleteRule(_CommissioningRule):
    """A system is labelled tests complete only when its functional tests are all passed."""

    rule_id = "commissioning.tests_complete_requires_passed_tests"
    name = "Tests complete means functional tests passed"
    description = (
        "Setting a system to tests_complete needs every applicable functional item passed and no critical issue open"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        system = section(context, "system")
        ref = str(system.get("id", ""))
        if system.get("status") != "tests_complete" or system.get("can_commission"):
            return [self.ok(ref)]
        return [self.fail(context, "tests_complete_requires_passed_tests", ref=ref)]


class FunctionalAfterPrefunctionalRule(_CommissioningRule):
    """A functional test is signed off only on equipment whose pre-functional checks are done."""

    rule_id = "commissioning.functional_after_prefunctional"
    name = "Functional pass follows pre-functional checks"
    description = (
        "Passing a functional item with a failed pre-functional item is blocked; with an open one it is warned"
    )

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        result = section(context, "result")
        ref = str(result.get("id", ""))
        if result.get("kind") != "functional" or result.get("status") != "pass":
            return [self.ok(ref)]
        pre = section(context, "prefunctional")
        failed, pending = int(pre.get("failed") or 0), int(pre.get("pending") or 0)
        out: list[RuleResult] = []
        if failed:
            out.append(self.fail(context, "prefunctional_failed", ref=ref, count=failed))
        if pending:
            out.append(self.fail(context, "prefunctional_open", ref=ref, severity=Severity.WARNING, count=pending))
        return out or [self.ok(ref)]


class FailedTestNeedsNoteRule(_CommissioningRule):
    """A failed test records what was observed, so the retest has something to prove."""

    rule_id = "commissioning.failed_test_needs_note"
    name = "Failed test has a result note"
    severity = Severity.WARNING
    description = "A fail result without a note leaves the deficiency untraceable"

    async def validate(self, context: ValidationContext) -> list[RuleResult]:
        result = section(context, "result")
        ref = str(result.get("id", ""))
        if result.get("status") == "fail" and blank(result.get("result_note")):
            return [self.fail(context, "failed_test_needs_note", ref=ref)]
        return [self.ok(ref)]


COMMISSIONING_RULES = (
    IssueClosedHasResolutionRule,
    SystemTestsCompleteRule,
    FunctionalAfterPrefunctionalRule,
    FailedTestNeedsNoteRule,
)


def register_commissioning_validation_rules() -> None:
    """Register the commissioning rules with the platform rule registry."""
    for rule_class in COMMISSIONING_RULES:
        rule_registry.register(rule_class(), [COMMISSIONING_RULE_SET])
