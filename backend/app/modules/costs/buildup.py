# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""The unit rate a bill line receives when a cost item is added to it.

A catalogue item with a component breakdown is not added at its catalogue
``rate``. The add flow turns every component into a resource row and the
line's unit rate becomes the sum of those rows, which is the platform rule for
any resource-priced line. The catalogue rate and that sum are separate figures
in the source data and often differ, so a picker that shows only the catalogue
rate promises one price and delivers another.

:func:`buildup_rate` states the figure the line will receive, so the picker can
show it. It mirrors the frontend add flow (``BOQModals.tsx``): a component
contributes its ``cost`` when it carries one, otherwise ``quantity x
unit_rate`` with a missing quantity read as 1. An item with a variant slot has
no single build-up rate, since the rate depends on the variant the estimator
picks, and one without components is added at its catalogue rate, so both
return ``None``.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


def _dec(value: Any) -> Decimal:
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0")
    return d if d.is_finite() else Decimal("0")


def _is_variant_catalogue(variants: Any, stats: Any) -> bool:
    return isinstance(variants, list) and len(variants) >= 2 and bool(stats)


def has_variant_slot(components: list[Any] | None, metadata: dict[str, Any] | None) -> bool:
    """True when adding the item asks the estimator to choose a variant."""
    md = metadata if isinstance(metadata, dict) else {}
    if _is_variant_catalogue(md.get("variants"), md.get("variant_stats")):
        return True
    for comp in components or []:
        if isinstance(comp, dict) and _is_variant_catalogue(
            comp.get("available_variants"), comp.get("available_variant_stats")
        ):
            return True
    return False


def buildup_rate(components: list[Any] | None, metadata: dict[str, Any] | None) -> Decimal | None:
    """The unit rate the add flow writes for this item, to the cent, or ``None``.

    Args:
        components: The item's component rows as stored.
        metadata: The item's metadata (variant catalogues live here).

    Returns:
        The sum of the component contributions, rounded half up to 2 dp, or
        ``None`` when the item has no components or has a variant slot.
    """
    rows = [c for c in components or [] if isinstance(c, dict)]
    if not rows or has_variant_slot(rows, metadata):
        return None
    total = Decimal("0")
    for comp in rows:
        cost = _dec(comp.get("cost"))
        if cost != 0:
            total += cost
            continue
        qty_raw = comp.get("quantity")
        qty = Decimal("1") if qty_raw is None else _dec(qty_raw)
        total += qty * _dec(comp.get("unit_rate"))
    return total.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
