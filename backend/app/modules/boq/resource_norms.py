# DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Which resource buildups may price their position, and which may not.

A position's ``metadata.resources`` follows the per-unit norm convention: each
row's ``quantity`` is the amount of that resource per ONE unit of the position,
so ``sum(quantity * unit_rate)`` is the position's unit rate. The BOQ service
relies on that when an edit touches the resources and re-derives ``unit_rate``
from them; the procurement rollup and the resource split rule rely on it too.

Before 17.1.0 the AI estimator wrote rows that did not follow the convention.
Its apply path stored ``quantity = factor * position_quantity``, a
whole-position total, and its fallback path stored an allowance whose quantity
was the position quantity itself; the demo seeder's lump-sum allowance did the
same. Before the estimator started reading the catalogue norm, ``factor`` was
always 1.0, so every row's quantity was simply the position quantity and the
norm was lost. Rows of either kind price the line correctly at apply time,
because the unit rate is written separately from the chosen candidate, and
mis-price it by roughly the position quantity the first time somebody edits a
resource. Since 17.1.0 every writer in the tree stores per-unit rows, so the
shapes below describe positions booked before that release and nothing a
current apply produces.

Everything in this module is pure and database-free, so the BOQ service, the
validation rule and the review path read one definition of an untrusted
buildup instead of three:

* :func:`untrusted_buildup_reason` says why a list of rows must not re-derive
  the unit rate.
* :func:`classify_buildup` sorts a stored buildup into the review categories
  the listing reports.
* :func:`rederive_rows_from_catalogue` builds per-unit rows from a catalogue
  item's components.
* :func:`stamp_unit_rate_kept` and :func:`clear_unit_rate_kept` record on the
  position that an edit kept the stored rate, in a shape the rule reads.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

#: ``Position.source`` written by the AI estimator's apply path.
AI_ESTIMATOR_SOURCE = "ai_precise_estimate"

#: Review categories, in the order of precedence :func:`classify_buildup` uses.
CATEGORY_FALLBACK_ALLOWANCE = "fallback_allowance"
CATEGORY_ASSUMED_NORM = "assumed_norm"
CATEGORY_NORM_COLLAPSED = "norm_collapsed"
CATEGORY_WHOLE_POSITION_QUANTITIES = "whole_position_quantities"

REVIEW_CATEGORIES: tuple[str, ...] = (
    CATEGORY_FALLBACK_ALLOWANCE,
    CATEGORY_ASSUMED_NORM,
    CATEGORY_NORM_COLLAPSED,
    CATEGORY_WHOLE_POSITION_QUANTITIES,
)

#: Metadata key the BOQ service stamps when it keeps the stored unit rate
#: instead of re-deriving it from rows it cannot trust.
UNIT_RATE_KEPT_KEY = "unit_rate_rederive_skipped"

#: Metadata key the review path writes: what it did, when, and the rows before.
REVIEW_KEY = "resource_norm_review"

#: Prefix of the marker appended to ``metadata.boq_quality_warnings`` so the
#: traffic light picks the kept rate up the way it picks up a duplicate.
UNIT_RATE_KEPT_WARNING_PREFIX = "Unit rate kept: "

_REASON_TEXT: dict[str, str] = {
    CATEGORY_FALLBACK_ALLOWANCE: "are an estimated allowance split holding the position quantity, not per-unit norms",
    CATEGORY_ASSUMED_NORM: "carry assumed norms the catalogue did not state",
    CATEGORY_NORM_COLLAPSED: "lost their catalogue norm and hold the position quantity instead",
    CATEGORY_WHOLE_POSITION_QUANTITIES: "hold whole-position quantities, not per-unit norms",
}

_REL_TOL = 1e-6
_ABS_TOL = 1e-9


def _num(value: Any) -> float | None:
    """A finite float out of whatever the JSON column holds, or None."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(value)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


def _rows(resources: Any) -> list[dict[str, Any]]:
    return [r for r in resources if isinstance(r, dict)] if isinstance(resources, list) else []


def _close(a: float, b: float) -> bool:
    return math.isclose(a, b, rel_tol=_REL_TOL, abs_tol=_ABS_TOL)


def is_estimator_position(source: Any, metadata: Any) -> bool:
    """True when the position was booked by the AI estimator.

    The source column is the primary signal; the run id in the metadata is the
    second, for rows whose source was later overwritten by an edit.
    """
    if str(source or "") == AI_ESTIMATOR_SOURCE:
        return True
    return isinstance(metadata, dict) and bool(metadata.get("ai_estimator_run_id"))


def _row_is_whole_position_total(row: dict[str, Any], position_quantity: float) -> bool:
    """A row whose quantity is exactly ``factor * position_quantity``.

    That product was the estimator's output shape before 17.1.0. A
    hand-entered per-unit row carries no ``factor`` and is never matched here,
    whatever its quantity.
    """
    if "factor" not in row:
        return False
    factor = _num(row.get("factor"))
    quantity = _num(row.get("quantity"))
    if factor is None or quantity is None or quantity == 0:
        return False
    return _close(quantity, factor * position_quantity)


def _row_is_whole_position_allowance(row: dict[str, Any], position_quantity: float) -> bool:
    """An ``estimated`` allowance row whose quantity is the position quantity.

    Three writers flag allowance rows ``estimated``: the estimator's fallback
    and the demo seeder store the position quantity on each leaf, so the leaf
    rates sum to the position TOTAL, while the flagship seeder stores a
    quantity of one, so they sum to the unit rate. The flag alone therefore
    says nothing about size; the shape does, and only the first two shapes
    mis-price the line on an edit.
    """
    if not row.get("estimated"):
        return False
    quantity = _num(row.get("quantity"))
    return quantity is not None and quantity != 0 and _close(quantity, position_quantity)


def untrusted_buildup_reason(
    *,
    source: Any,
    metadata: Any,
    quantity: Any,
    resources: Any,
) -> str | None:
    """Why these rows must not re-derive the position's unit rate, or None.

    The BOQ service calls this before it replaces ``unit_rate`` with
    ``sum(quantity * unit_rate)`` over the rows. A reason means the sum would
    not be a per-unit figure, or would rest on a norm nobody stated, and the
    stored rate has to stand.

    Returns one of the review categories:

    * ``assumed_norm`` - a row flagged ``factor_estimated``: the catalogue
      component declared no norm and 1.0 was substituted. Blocked whatever
      the shape, because the figure a re-derivation would rest on is a guess.
    * ``fallback_allowance`` - an ``estimated`` allowance row holding the
      position quantity, the shape the estimator's fallback and the demo
      seeder write. A per-unit allowance (quantity one) is trusted.
    * ``whole_position_quantities`` - an estimator-booked position whose rows
      hold ``factor * position_quantity``. Pre-fix rows (``factor`` 1.0) and
      post-fix rows alike.

    The two shape checks are skipped when the position quantity is one,
    because then the total and the norm coincide and the sum is right either
    way. Any other buildup, including every hand-entered one, returns None.
    """
    rows = _rows(resources)
    if not rows:
        return None
    if any(row.get("factor_estimated") for row in rows):
        return CATEGORY_ASSUMED_NORM
    position_quantity = _num(quantity)
    if position_quantity is None or position_quantity <= 0 or _close(position_quantity, 1.0):
        return None
    if any(row.get("estimated") for row in rows):
        if any(_row_is_whole_position_allowance(row, position_quantity) for row in rows):
            return CATEGORY_FALLBACK_ALLOWANCE
        return None
    if not is_estimator_position(source, metadata):
        return None
    if any(_row_is_whole_position_total(row, position_quantity) for row in rows):
        return CATEGORY_WHOLE_POSITION_QUANTITIES
    return None


@dataclass(frozen=True)
class BuildupVerdict:
    """What the review sees in one position's stored rows."""

    category: str
    #: True when the position links a catalogue item the rows can be
    #: re-derived from. False means the position can only be marked.
    recoverable: bool
    row_count: int
    #: Rows that carry the signal (flag or shape) the category rests on.
    flagged_rows: int


def classify_buildup(
    *,
    source: Any,
    metadata: Any,
    quantity: Any,
    resources: Any,
) -> BuildupVerdict | None:
    """Sort a stored buildup into a review category, or None when it is clean.

    Differs from :func:`untrusted_buildup_reason` in one place: it separates
    the oldest shape, every contributing row holding the position quantity
    (``norm_collapsed``), from the shape where the norm survived but was
    multiplied by the position quantity (``whole_position_quantities``). Both
    describe positions booked before 17.1.0 and nothing a current apply
    produces: since that release the estimator stores the norm itself. The
    first can be re-derived from the catalogue to recover a lost norm; the
    second can be re-derived to restore the per-unit convention. Both are
    recoverable only through a ``cost_item_id`` link.

    A buildup with a position quantity of one and every row at 1.0 is listed
    under ``norm_collapsed`` too. Shape cannot tell a lost norm from a norm
    that genuinely is one, and the listing is a request for a human to look,
    not a repair. An allowance split at quantity one is not listed: there is
    no norm behind it to recover and nothing about it mis-prices the line.
    """
    rows = _rows(resources)
    if not rows:
        return None
    meta = metadata if isinstance(metadata, dict) else {}
    linked = bool(meta.get("cost_item_id"))

    flagged = sum(1 for row in rows if row.get("factor_estimated"))
    if flagged:
        return BuildupVerdict(CATEGORY_ASSUMED_NORM, recoverable=False, row_count=len(rows), flagged_rows=flagged)

    position_quantity = _num(quantity)
    if position_quantity is None or position_quantity <= 0:
        return None

    if any(row.get("estimated") for row in rows):
        if _close(position_quantity, 1.0):
            return None
        flagged = sum(1 for row in rows if _row_is_whole_position_allowance(row, position_quantity))
        if flagged:
            return BuildupVerdict(
                CATEGORY_FALLBACK_ALLOWANCE, recoverable=False, row_count=len(rows), flagged_rows=flagged
            )
        return None

    if not is_estimator_position(source, meta):
        return None

    contributing = [row for row in rows if (_num(row.get("quantity")) or 0.0) != 0]
    if not contributing:
        return None
    if all(_close(_num(row.get("quantity")) or 0.0, position_quantity) for row in contributing):
        return BuildupVerdict(
            CATEGORY_NORM_COLLAPSED,
            recoverable=linked,
            row_count=len(rows),
            flagged_rows=len(contributing),
        )
    if _close(position_quantity, 1.0):
        return None
    totals = sum(1 for row in contributing if _row_is_whole_position_total(row, position_quantity))
    if totals:
        return BuildupVerdict(
            CATEGORY_WHOLE_POSITION_QUANTITIES,
            recoverable=linked,
            row_count=len(rows),
            flagged_rows=totals,
        )
    return None


def _catalogue_norm(component: dict[str, Any]) -> tuple[float, bool]:
    """The per-unit norm a catalogue component states, and whether it did.

    ``CostItem.components`` writes the norm as ``quantity``: the costs module
    prices an item as ``sum(quantity * unit_price)`` and stores the sum as the
    item's UNIT rate, so ``quantity`` is per one unit of the item. ``factor``
    is the spelling of a few hand-written seed rows. A component that states
    neither yields ``(1.0, False)`` and the caller flags the row, because a
    plausible default that changes no visible number is exactly how the lost
    norm went unnoticed.
    """
    for key in ("quantity", "factor"):
        if key not in component:
            continue
        value = _num(component.get(key))
        if value is not None and value > 0:
            return value, True
    return 1.0, False


def _money_str(value: Any) -> str:
    try:
        dec = Decimal(str(value if value not in (None, "") else "0"))
    except (InvalidOperation, ValueError):
        return "0"
    return format(dec, "f") if dec.is_finite() else "0"


def rederive_rows_from_catalogue(components: Any) -> list[dict[str, Any]]:
    """Per-unit resource rows for a position, from a catalogue item's components.

    The output follows the platform convention (``quantity`` per one unit of
    the position) and keeps the estimator's field names so every reader of an
    estimator-booked row keeps working. ``factor`` equals ``quantity`` here
    and is kept for those readers; it no longer multiplies anything.
    """
    out: list[dict[str, Any]] = []
    if not isinstance(components, list):
        return out
    for comp in components:
        if not isinstance(comp, dict):
            continue
        norm, grounded = _catalogue_norm(comp)
        row: dict[str, Any] = {
            "name": str(comp.get("description") or comp.get("name") or comp.get("code") or ""),
            "code": str(comp.get("code") or ""),
            "unit": str(comp.get("unit") or ""),
            "type": str(comp.get("type") or "other"),
            "factor": norm,
            "quantity": norm,
            "unit_rate": _money_str(comp.get("unit_rate") or comp.get("rate")),
        }
        if not grounded:
            row["factor_estimated"] = True
        out.append(row)
    return out


def resource_subtotal(resources: Any) -> Decimal:
    """``sum(quantity * unit_rate)`` over the rows, the figure an edit would store."""
    total = Decimal("0")
    for row in _rows(resources):
        try:
            total += Decimal(str(row.get("quantity") or 0)) * Decimal(str(row.get("unit_rate") or 0))
        except (InvalidOperation, ValueError):
            continue
    return total


def stamp_unit_rate_kept(metadata: dict[str, Any], *, reason: str, unit_rate: Any) -> None:
    """Record on the position that an edit kept the stored rate.

    Writes a structured stamp the validation rule and the review listing read,
    and a ``boq_quality_warnings`` marker in the shape the duplicate-content
    check uses, so the traffic light shows the row without a new reader.
    Idempotent: a second blocked edit replaces the marker rather than stacking.
    """
    metadata[UNIT_RATE_KEPT_KEY] = {
        "reason": reason,
        "kept_unit_rate": str(unit_rate),
        "at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    existing = metadata.get("boq_quality_warnings")
    warnings = [w for w in (existing if isinstance(existing, list) else []) if not _is_kept_marker(w)]
    text = _REASON_TEXT.get(reason, reason)
    warnings.append(
        f"{UNIT_RATE_KEPT_WARNING_PREFIX}the resource rows {text}, so the unit rate was not "
        "re-derived from them. Review the buildup before trusting the split."
    )
    metadata["boq_quality_warnings"] = warnings


def clear_unit_rate_kept(metadata: dict[str, Any]) -> bool:
    """Drop the stamp and its marker once the rows can price the line again."""
    changed = metadata.pop(UNIT_RATE_KEPT_KEY, None) is not None
    existing = metadata.get("boq_quality_warnings")
    if isinstance(existing, list):
        remaining = [w for w in existing if not _is_kept_marker(w)]
        if len(remaining) != len(existing):
            changed = True
            if remaining:
                metadata["boq_quality_warnings"] = remaining
            else:
                metadata.pop("boq_quality_warnings", None)
    return changed


def _is_kept_marker(warning: Any) -> bool:
    return isinstance(warning, str) and warning.startswith(UNIT_RATE_KEPT_WARNING_PREFIX)
