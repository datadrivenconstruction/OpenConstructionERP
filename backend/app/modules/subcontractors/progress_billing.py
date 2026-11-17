# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Progress billing against a subcontract's schedule of values.

Pure arithmetic over plain dicts (standard library and Decimal only), so the
statement a pay application prints and the rules that judge it read the same
numbers. Each work package of the agreement is one line of the schedule of
values. For one pay application the statement shows, per line, the scheduled
value, what earlier applications already billed, this period, the total
completed to date, the percent complete, the retention on it and the balance to
finish. Everything "previous" is derived from the earlier applications of the
same agreement that were approved for payment; a draft, a submitted or a
rejected application never counts, so nothing is billed twice and a rejected
claim does not eat into the line.

"Earlier" is the order of the list the caller passes (oldest first): an
application sees only the approved ones before it, so re-reading an old
statement after later months were approved gives the same figures.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

#: Application statuses whose amounts are certain enough to count as billed.
COUNTED_STATUSES: frozenset[str] = frozenset({"finance_approved", "paid"})

_CENT = Decimal("0.01")
_PCT = Decimal("0.01")
_ZERO = Decimal("0")


def _d(raw: Any) -> Decimal:
    if raw is None or raw == "":
        return _ZERO
    return Decimal(str(raw))


def _q(value: Decimal) -> Decimal:
    return value.quantize(_CENT, rounding=ROUND_HALF_UP)


def percent_of(part: Decimal, whole: Decimal) -> Decimal | None:
    """``part`` as a percentage of ``whole``, or ``None`` when there is no whole to measure against."""
    if whole == 0:
        return None
    return (part * Decimal("100") / whole).quantize(_PCT, rounding=ROUND_HALF_UP)


def amount_from_percent(scheduled_value: Decimal, percent: Decimal) -> Decimal:
    """The amount a period percentage of a scheduled value comes to."""
    return _q(scheduled_value * percent / Decimal("100"))


def _line_amount(application: dict[str, Any], line: dict[str, Any]) -> Decimal:
    """What a line contributes: the approved amount once approved, the claim before."""
    if application.get("status") in COUNTED_STATUSES:
        return _d(line.get("approved_amount"))
    return _d(line.get("claimed_amount"))


def _gross(application: dict[str, Any]) -> Decimal:
    approved = application.get("approved_gross_amount")
    return _d(approved if approved is not None else application.get("gross_amount"))


def _net(application: dict[str, Any]) -> Decimal:
    approved = application.get("approved_net_amount")
    return _d(approved if approved is not None else application.get("net_amount"))


def build_statement(
    *,
    contract_sum_to_date: Any,
    change_orders_total: Any,
    retention_percent: Any,
    work_packages: list[dict[str, Any]],
    applications: list[dict[str, Any]],
    current_id: str | None = None,
    current_lines: list[dict[str, Any]] | None = None,
    current_status: str = "submitted",
) -> dict[str, Any]:
    """The progress statement of one pay application.

    Args:
        contract_sum_to_date: The agreement value including approved changes
            (the agreement's ``total_value``, which approval of a change raises).
        change_orders_total: What approved changes added to the value.
        retention_percent: The agreement's retention rate.
        work_packages: ``{"id", "name", "planned_value"}`` per line of the
            schedule of values, in display order.
        applications: Every application of the agreement, oldest first, each
            ``{"id", "number", "status", "gross_amount", "net_amount",
            "approved_gross_amount", "approved_net_amount", "lines": [{
            "work_package_id", "claimed_amount", "approved_amount"}]}``.
        current_id: The application the statement is for. ``None`` prepares the
            statement of one not yet saved: every counted application is
            earlier, and ``current_lines`` carries its lines.
        current_lines: Lines of the unsaved application (used when ``current_id``
            is ``None`` or not in ``applications``).
        current_status: Status of the unsaved application.

    Returns:
        ``{"lines": [...], "summary": {...}}``; money as Decimal.
    """
    rate = _d(retention_percent)
    previous_by_wp: dict[str, Decimal] = {}
    previous_gross = _ZERO
    previous_net = _ZERO
    current: dict[str, Any] | None = None

    for application in applications:
        if current_id is not None and str(application.get("id")) == str(current_id):
            current = application
            break
        if application.get("status") not in COUNTED_STATUSES:
            continue
        previous_gross += _gross(application)
        previous_net += _net(application)
        for line in application.get("lines") or []:
            key = str(line["work_package_id"])
            previous_by_wp[key] = previous_by_wp.get(key, _ZERO) + _line_amount(application, line)

    this_by_wp: dict[str, Decimal] = {}
    if current is not None:
        this_lines = [(line, _line_amount(current, line)) for line in current.get("lines") or []]
        this_gross = _gross(current)
    else:
        probe = {"status": current_status}
        this_lines = [(line, _line_amount(probe, line)) for line in current_lines or []]
        this_gross = sum((amount for _line, amount in this_lines), _ZERO)
    for line, amount in this_lines:
        key = str(line["work_package_id"])
        this_by_wp[key] = this_by_wp.get(key, _ZERO) + amount

    rows: list[dict[str, Any]] = []
    total_scheduled = _ZERO
    total_previous = _ZERO
    total_this = _ZERO
    total_completed = _ZERO
    total_retention = _ZERO
    for package in work_packages:
        key = str(package["id"])
        scheduled = _d(package.get("planned_value"))
        previous = previous_by_wp.get(key, _ZERO)
        this_period = this_by_wp.get(key, _ZERO)
        completed = previous + this_period
        retention = _q(completed * rate / Decimal("100"))
        rows.append(
            {
                "work_package_id": key,
                "name": package.get("name") or "",
                "scheduled_value": scheduled,
                "previous": previous,
                "this_period": this_period,
                "this_period_percent": percent_of(this_period, scheduled),
                "total_completed": completed,
                "percent_complete": percent_of(completed, scheduled),
                "retention": retention,
                "balance_to_finish": scheduled - completed,
            }
        )
        total_scheduled += scheduled
        total_previous += previous
        total_this += this_period
        total_completed += completed
        total_retention += retention

    contract_sum = _d(contract_sum_to_date)
    changes = _d(change_orders_total)
    summary = {
        "original_contract_sum": contract_sum - changes,
        "change_orders": changes,
        "contract_sum_to_date": contract_sum,
        "scheduled_total": total_scheduled,
        "previous_completed": total_previous,
        "this_period": total_this,
        "completed_to_date": total_completed,
        "percent_complete": percent_of(total_completed, contract_sum),
        "retention_percent": rate,
        "retention_held": total_retention,
        "previous_certified": previous_net,
        "current_due": total_completed - total_retention - previous_net,
        "balance_to_finish": contract_sum - total_completed,
        "previous_gross_billed": previous_gross,
        "this_gross": this_gross,
    }
    return {"lines": rows, "summary": summary}
