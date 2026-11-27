"""Read-only check that a position's resource composition adds up to its unit rate.

The estimator opens one line and asks: do the resource rows price this rate?
The answer re-derives the rate exactly as the editor does
(``service._derived_unit_rate_str``: per-unit norms or whole-position rows,
foreign currencies converted with the project table) and lists what is wrong
per row. It writes nothing. The same arithmetic across a whole bill is the
validation rule ``boq_quality.resource_split_mismatch``.

Issue codes are stable identifiers, the UI maps them to words.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from app.modules.boq.service import _derived_unit_rate_str, _detect_resource_fx_warnings
from app.modules.costs.resource_pricing import _to_decimal

COHERENCE_TOLERANCE = Decimal("0.01")

ISSUE_MISSING_NAME = "missing_name"
ISSUE_MISSING_UNIT = "missing_unit"
ISSUE_NON_POSITIVE_QUANTITY = "non_positive_quantity"
ISSUE_UNPRICED = "unpriced"
ISSUE_NEGATIVE_RATE = "negative_rate"
ISSUE_TOTAL_MISMATCH = "total_mismatch"


def _row_issues(row: dict[str, Any]) -> list[str]:
    issues: list[str] = []
    qty = _to_decimal(row.get("quantity"))
    rate = _to_decimal(row.get("unit_rate"))
    if not str(row.get("name") or "").strip():
        issues.append(ISSUE_MISSING_NAME)
    if not str(row.get("unit") or "").strip():
        issues.append(ISSUE_MISSING_UNIT)
    if qty <= 0:
        issues.append(ISSUE_NON_POSITIVE_QUANTITY)
    if rate < 0:
        issues.append(ISSUE_NEGATIVE_RATE)
    elif rate == 0:
        issues.append(ISSUE_UNPRICED)
    if row.get("total") not in (None, "") and abs(_to_decimal(row.get("total")) - qty * rate) > COHERENCE_TOLERANCE:
        issues.append(ISSUE_TOTAL_MISMATCH)
    return issues


def inspect_composition(
    *,
    unit_rate: Any,
    quantity: Any,
    metadata: dict[str, Any] | None,
    fx_rates_map: dict[str, str] | None = None,
    base_currency: str = "",
) -> dict[str, Any]:
    """Compare the stored unit rate with the one the resource rows derive.

    Returns ``stored_unit_rate``, ``derived_unit_rate``, ``delta`` (stored minus
    derived), ``coherent``, ``fx_missing`` (currencies the rows use that the
    project cannot convert) and ``components`` with one ``issues`` list per row.
    A position without rows is coherent by definition: nothing to compare.
    """
    meta = metadata or {}
    rows = [r for r in (meta.get("resources") or []) if isinstance(r, dict)]
    stored = _to_decimal(unit_rate)
    derived = _to_decimal(_derived_unit_rate_str(rows, meta, quantity, fx_rates_map, base_currency)) if rows else stored
    delta = stored - derived
    return {
        "stored_unit_rate": str(stored),
        "derived_unit_rate": str(derived),
        "delta": str(delta),
        "coherent": abs(delta) <= COHERENCE_TOLERANCE,
        "fx_missing": _detect_resource_fx_warnings(rows, fx_rates_map, base_currency),
        "components": [
            {
                "index": i,
                "name": str(r.get("name") or ""),
                "unit": str(r.get("unit") or ""),
                "quantity": str(_to_decimal(r.get("quantity"))),
                "unit_rate": str(_to_decimal(r.get("unit_rate"))),
                "issues": _row_issues(r),
            }
            for i, r in enumerate(rows)
        ],
    }
