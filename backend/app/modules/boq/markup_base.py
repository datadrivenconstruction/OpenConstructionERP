# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""What a markup line is charged on, in one place.

A bill's markup stack is walked top to bottom in more than one place: the
authoritative cascade in :mod:`app.modules.boq.service`, the list rollup in the
repository, the GAEB X84 export that prints each line's base, the X89 invoice
check, and the cost plan that shows the base beside each line. Each of them
used to spell out ``running if apply_to in ("cumulative", "subtotal") else
direct_cost`` for itself. A fourth base value added in one of them and not the
others would make the list total, the export and the editor disagree about the
same bill, so the rule lives here and every walker calls it.

The four values of ``apply_to``:

* ``direct_cost`` - the sum of the positions, no other markup.
* ``cumulative`` - the sum of the positions plus every active line above.
* ``subtotal`` - identical to ``cumulative`` (BUG-B-005). Kept because GAEB
  imports and older bills store tax lines under that name, and stored rows
  keep their meaning.
* ``same_as_previous`` - exactly the base the nearest active line above was
  charged on. This is what a German Zuschlagskalkulation needs for Wagnis and
  Gewinn, which both sit on the Selbstkosten: with ``cumulative`` alone the
  second one would compound on the first. It chains, so three lines in a row
  share one base. A line with nothing above it, or whose nearest active line
  above is a fixed amount (which has no base), falls back to the sum of the
  positions.
"""

from __future__ import annotations

from decimal import Decimal

DIRECT_COST = "direct_cost"
CUMULATIVE = "cumulative"
SUBTOTAL = "subtotal"
SAME_AS_PREVIOUS = "same_as_previous"

#: Every value the schemas accept, in the order the editor offers them.
APPLY_TO_VALUES: tuple[str, ...] = (DIRECT_COST, CUMULATIVE, SAME_AS_PREVIOUS, SUBTOTAL)

#: Bases that include the lines above. ``subtotal`` is an alias of ``cumulative``.
COMPOUNDING: frozenset[str] = frozenset({CUMULATIVE, SUBTOTAL})

#: Regex for the Pydantic ``pattern`` on ``apply_to``.
APPLY_TO_PATTERN = r"^(direct_cost|subtotal|cumulative|same_as_previous)$"


def normalise_apply_to(apply_to: object) -> str:
    """Lower-case the stored value, reading an empty one as ``direct_cost``."""
    return str(apply_to or DIRECT_COST).strip().lower()


def has_base(markup_type: object) -> bool:
    """Whether a line of this type is charged on a base at all.

    A fixed amount is not. Every other type (percentage, banded, escalation)
    multiplies or tranches a base, so a ``same_as_previous`` line below it can
    borrow that base.
    """
    return str(markup_type or "percentage").strip().lower() != "fixed"


def resolve_markup_base(
    apply_to: object,
    *,
    direct_cost: Decimal,
    running: Decimal,
    previous_base: Decimal | None,
) -> Decimal:
    """Return the amount a line is charged on.

    Args:
        apply_to: The line's stored ``apply_to``.
        direct_cost: The sum of the positions.
        running: The sum of the positions plus every active line above.
        previous_base: The base the nearest active line above was charged
            on, or None when there is no such line or it was a fixed amount.

    Returns:
        The base. Unknown values read as ``direct_cost``, as they always have.
    """
    kind = normalise_apply_to(apply_to)
    if kind == SAME_AS_PREVIOUS:
        return direct_cost if previous_base is None else previous_base
    if kind in COMPOUNDING:
        return running
    return direct_cost


def effective_apply_to(apply_to: object, previous_effective: str | None) -> str:
    """Name the kind of base a line really sits on, resolving ``same_as_previous``.

    Rules that reason about the base (a contingency must not sit on a base
    that contains profit) need to know that a ``same_as_previous`` line under a
    running-total line is itself on a running total.

    Args:
        apply_to: The line's stored ``apply_to``.
        previous_effective: What this returned for the nearest active line
            above that has a base, or None when there is none.

    Returns:
        ``direct_cost``, ``cumulative`` or ``subtotal``.
    """
    kind = normalise_apply_to(apply_to)
    if kind == SAME_AS_PREVIOUS:
        return previous_effective or DIRECT_COST
    return kind
