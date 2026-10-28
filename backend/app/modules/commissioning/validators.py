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
