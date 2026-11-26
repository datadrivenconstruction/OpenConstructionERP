# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Pure checks behind the commercial control rules (rule set ``commercial_control``).

Commercial control is where four modules meet: the bill (budget at target
cost), procurement and subcontracts (commitments), the approval engine (who
signs which amount) and the valuation workflows (submitted, assessed,
certified). Each check below reads plain dicts, returns :class:`Finding` rows
and does no I/O, so the same function serves the API response, the validation
engine wrapper in :mod:`app.core.validation.rules.commercial_control` and the
unit tests.

Payload blocks, one per check:

``budget_positions``
    ``[{id, ordinal, basis}]`` for every priced position (``basis`` is
    ``target`` or ``unit_rate``, see :mod:`app.modules.boq.budget_basis`).
``unmapped_sources``
    ``[{kind, ref, committed, actual}]``: cost records with no WBS or cost code.
``grid_rows``
    ``[{id, ordinal, budget_qty, committed_qty, budget_value, committed_value}]``.
``route_steps``
    ``[{ordinal, amount_min, amount_max}]``: the steps of one approval route.
``valuation_lines``
    ``[{id, label, submitted, assessed, certified, prior_cumulative,
    cumulative, note}]``: quantities of one progress claim or subcontractor
    payment application; the cumulative pair is the line's running total
    before and after this document, the note the document's explanation.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from typing import Any

ZERO = Decimal("0")


@dataclass(frozen=True)
class Finding:
    """One failed check on one element; ``severity`` overrides the rule's own when set."""

    element_ref: str
    params: dict[str, str] = field(default_factory=dict)
    details: dict[str, Any] = field(default_factory=dict)
    severity: str | None = None


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError, TypeError):
        return None
    return value if value.is_finite() else None


def _num(raw: Any) -> Decimal:
    return _dec(raw) or ZERO


def _fmt(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text if text != "-0" else "0"


def _rows(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    rows = payload.get(key)
    return [r for r in rows if isinstance(r, dict)] if isinstance(rows, list) else []


# ── cvr.target_rate_basis ──────────────────────────────────────────────────


def check_target_rate_basis(payload: dict[str, Any]) -> list[Finding]:
    """Warn once when some priced positions are budgeted at the sale rate.

    One finding for the whole bill rather than one per line: a bill imported
    without target costs would otherwise drown every other result. The count and
    the first few ordinals tell the reader where to start.
    """
    rows = _rows(payload, "budget_positions")
    missing = [r for r in rows if r.get("basis") != "target"]
    if not rows or not missing:
        return []
    sample = ", ".join(str(r.get("ordinal") or r.get("id") or "") for r in missing[:5])
    return [
        Finding(
            element_ref="budget",
            params={"missing": str(len(missing)), "total": str(len(rows)), "sample": sample},
            details={"position_ids": [str(r.get("id")) for r in missing]},
        )
    ]


# ── cvr.unmapped_cost ──────────────────────────────────────────────────────


def check_unmapped_cost(payload: dict[str, Any]) -> list[Finding]:
    """Flag each commitment or actual cost that has no WBS or cost code to land on."""
    out: list[Finding] = []
    for row in _rows(payload, "unmapped_sources"):
        committed = _num(row.get("committed"))
        actual = _num(row.get("actual"))
        if committed == 0 and actual == 0:
            continue
        out.append(
            Finding(
                element_ref=f"{row.get('kind')}:{row.get('ref')}",
                params={
                    "kind": str(row.get("kind") or ""),
                    "label": str(row.get("label") or row.get("ref") or ""),
                    "committed": _fmt(committed),
                    "actual": _fmt(actual),
                },
                details={"kind": row.get("kind"), "ref": str(row.get("ref"))},
            )
        )
    return out


# ── procurement.line_over_committed ────────────────────────────────────────


def check_line_over_committed(payload: dict[str, Any]) -> list[Finding]:
    """Flag a bill line whose commitments exceed its budget, in quantity or in value."""
    out: list[Finding] = []
    for row in _rows(payload, "grid_rows"):
        budget_qty = _num(row.get("budget_qty"))
        committed_qty = _num(row.get("committed_qty"))
        budget_value = _num(row.get("budget_value"))
        committed_value = _num(row.get("committed_value"))
        over_qty = budget_qty > 0 and committed_qty > budget_qty
        over_value = committed_value > budget_value
        if not (over_qty or over_value):
            continue
        out.append(
            Finding(
                element_ref=str(row.get("id") or ""),
                params={
                    "ordinal": str(row.get("ordinal") or ""),
                    "committed_qty": _fmt(committed_qty),
                    "budget_qty": _fmt(budget_qty),
                    "committed_value": _fmt(committed_value),
                    "budget_value": _fmt(budget_value),
                },
                details={"over_qty": over_qty, "over_value": over_value},
            )
        )
    return out


# ── approval_routes.bands_contiguous ───────────────────────────────────────


@dataclass(frozen=True)
class Band:
    """The amount range one route step applies to: ``[low, high)``, ``high`` None = no ceiling."""

    ordinal: int
    low: Decimal
    high: Decimal | None


def step_bands(steps: list[dict[str, Any]]) -> tuple[list[Band], bool]:
    """The banded steps, and whether the route also has a step with no band."""
    bands: list[Band] = []
    unbanded = False
    for step in steps:
        low = _dec(step.get("amount_min"))
        high = _dec(step.get("amount_max"))
        if low is None and high is None:
            unbanded = True
            continue
        bands.append(Band(ordinal=int(step.get("ordinal") or 0), low=low if low is not None else ZERO, high=high))
    return bands, unbanded


def step_applies(amount: Decimal | None, amount_min: Any, amount_max: Any) -> bool:
    """Whether a step with this band takes part in routing an amount.

    The band is ``amount_min <= amount < amount_max``. A step with no band, or
    a workflow with no amount, always applies: missing information routes to
    more approvers, never fewer.
    """
    low = _dec(amount_min)
    high = _dec(amount_max)
    if amount is None or (low is None and high is None):
        return True
    if low is not None and amount < low:
        return False
    return not (high is not None and amount >= high)


def check_bands_contiguous(payload: dict[str, Any]) -> list[Finding]:
    """Approval bands must not leave an amount without an approver, and should not overlap.

    * ``empty`` (error): a band whose minimum is not below its maximum.
    * ``gap`` (error): amounts between two bands, or below the first band when
      no step is unbanded, would reach no banded approver.
    * ``overlap`` (warning): two bounded bands both claim the same amounts.
      Open-ended thresholds (``amount_max`` empty) are the escalation pattern,
      "the director also signs above 50 000", and are not an overlap.
    """
    bands, unbanded = step_bands(_rows(payload, "route_steps"))
    out: list[Finding] = []
    valid: list[Band] = []
    for band in bands:
        if band.high is not None and band.high <= band.low:
            out.append(
                Finding(
                    element_ref=f"step:{band.ordinal}",
                    params={"kind": "empty", "step": str(band.ordinal), "low": _fmt(band.low), "high": _fmt(band.high)},
                    details={"kind": "empty"},
                    severity="error",
                )
            )
        else:
            valid.append(band)
    if not valid:
        return out

    valid.sort(key=lambda b: (b.low, b.ordinal))
    if not unbanded and valid[0].low > 0:
        out.append(
            Finding(
                element_ref=f"step:{valid[0].ordinal}",
                params={"kind": "gap", "step": str(valid[0].ordinal), "low": "0", "high": _fmt(valid[0].low)},
                details={"kind": "gap"},
                severity="error",
            )
        )

    covered: Decimal | None = valid[0].high
    for prev, band in zip(valid, valid[1:], strict=False):
        if covered is not None and band.low > covered:
            out.append(
                Finding(
                    element_ref=f"step:{band.ordinal}",
                    params={"kind": "gap", "step": str(band.ordinal), "low": _fmt(covered), "high": _fmt(band.low)},
                    details={"kind": "gap"},
                    severity="error",
                )
            )
        if prev.high is not None and band.low < prev.high:
            top = prev.high if band.high is None else min(prev.high, band.high)
            out.append(
                Finding(
                    element_ref=f"step:{band.ordinal}",
                    params={"kind": "overlap", "step": str(band.ordinal), "low": _fmt(band.low), "high": _fmt(top)},
                    details={"kind": "overlap", "with_step": prev.ordinal},
                    severity="warning",
                )
            )
        if covered is not None:
            covered = None if band.high is None else max(covered, band.high)
    return out


# ── valuation.assessed_within_submitted / valuation.certified_within_assessed ──


def _stage_check(payload: dict[str, Any], upper: str, lower: str) -> list[Finding]:
    out: list[Finding] = []
    for row in _rows(payload, "valuation_lines"):
        top = _num(row.get(upper))
        below = _num(row.get(lower))
        if below <= top:
            continue
        out.append(
            Finding(
                element_ref=str(row.get("id") or ""),
                params={"line": str(row.get("label") or row.get("id") or ""), upper: _fmt(top), lower: _fmt(below)},
                details={upper: _fmt(top), lower: _fmt(below)},
            )
        )
    return out


def check_assessed_within_submitted(payload: dict[str, Any]) -> list[Finding]:
    """The assessed quantity of a valuation line should not exceed what was submitted."""
    return _stage_check(payload, "submitted", "assessed")


def check_certified_within_assessed(payload: dict[str, Any]) -> list[Finding]:
    """The certified quantity of a valuation line should not exceed what was assessed."""
    return _stage_check(payload, "assessed", "certified")


# ── valuation.cumulative_not_decreasing ────────────────────────────────────


def check_cumulative_not_decreasing(payload: dict[str, Any]) -> list[Finding]:
    """A line's running total should not fall below the previous document's without a note.

    A first document has no prior total and is never flagged. A drop is a
    legitimate remeasure or correction only when someone wrote down why.
    """
    out: list[Finding] = []
    for row in _rows(payload, "valuation_lines"):
        prior = _dec(row.get("prior_cumulative"))
        current = _dec(row.get("cumulative"))
        if prior is None or current is None or current >= prior:
            continue
        if str(row.get("note") or "").strip():
            continue
        out.append(
            Finding(
                element_ref=str(row.get("id") or ""),
                params={
                    "line": str(row.get("label") or row.get("id") or ""),
                    "prior": _fmt(prior),
                    "cumulative": _fmt(current),
                },
                details={"prior": _fmt(prior), "cumulative": _fmt(current)},
            )
        )
    return out


# ── cvr.wbs_rollup_reconciles ──────────────────────────────────────────────


def check_wbs_rollup_reconciles(payload: dict[str, Any]) -> list[Finding]:
    """A WBS parent must equal its own lines plus its children, the report its roots plus unallocated.

    Each part is rounded to the cent before it reaches the payload, so half a
    cent per part is rounding, not a gap.
    """
    out: list[Finding] = []
    for row in _rows(payload, "wbs_rollup_nodes"):
        total = row.get("total") if isinstance(row.get("total"), dict) else {}
        parts = [p for p in (row.get("parts") or []) if isinstance(p, dict)]
        tolerance = Decimal("0.005") * max(len(parts), 1)
        for name in sorted(total):
            expected = _num(total.get(name))
            summed = sum((_num(p.get(name)) for p in parts), ZERO)
            if abs(expected - summed) <= tolerance:
                continue
            out.append(
                Finding(
                    element_ref=f"{row.get('id')}:{name}",
                    params={
                        "label": str(row.get("label") or row.get("id") or ""),
                        "field": name,
                        "total": _fmt(expected),
                        "parts": _fmt(summed),
                    },
                    details={"id": str(row.get("id") or ""), "field": name},
                    severity="error",
                )
            )
    return out


CHECKS: dict[str, Any] = {
    "cvr.target_rate_basis": check_target_rate_basis,
    "cvr.unmapped_cost": check_unmapped_cost,
    "procurement.line_over_committed": check_line_over_committed,
    "approval_routes.bands_contiguous": check_bands_contiguous,
    "valuation.assessed_within_submitted": check_assessed_within_submitted,
    "valuation.certified_within_assessed": check_certified_within_assessed,
    "valuation.cumulative_not_decreasing": check_cumulative_not_decreasing,
    "cvr.wbs_rollup_reconciles": check_wbs_rollup_reconciles,
}
