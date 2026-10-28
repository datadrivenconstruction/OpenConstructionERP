# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠Small descriptive statistics shared by every module that ranks a population.

Three places in the tree were each carrying their own linear-interpolation
percentile, and a fourth (the cross-project performance benchmark) needed one
too. They agree on the formula, which is the one a spreadsheet's
``PERCENTILE.INC`` uses, so it lives here once.

Everything works on ``float`` or on ``Decimal`` without mixing the two: a list
of ``Decimal`` comes back as a ``Decimal`` computed in ``Decimal``, so money and
productivity figures never pick up binary noise on the way through, and a list
of ``float`` comes back exactly as the old per-module helpers returned it.

No dependency on numpy or statistics' float-only paths, on purpose: this is a
dozen lines and the core has to start on a 3 GB box.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal


def percentile[Number: (float, Decimal)](sorted_values: Sequence[Number], pct: float | Decimal) -> Number | None:
    """Linear-interpolation percentile of an ascending-sorted sequence.

    Args:
        sorted_values: The population, already sorted ascending. All ``float``
            or all ``Decimal``.
        pct: The percentile, 0..100.

    Returns:
        The interpolated value, of the same type as the inputs, or ``None``
        for an empty population. An empty population has no percentile, and
        answering ``0`` would read as a measurement.
    """
    n = len(sorted_values)
    if n == 0:
        return None
    if n == 1:
        return sorted_values[0]
    if isinstance(sorted_values[0], Decimal):
        idx_d = Decimal(str(pct)) / Decimal(100) * (n - 1)
        lower = int(idx_d)
        upper = min(lower + 1, n - 1)
        frac_d = idx_d - lower
        return sorted_values[lower] + frac_d * (sorted_values[upper] - sorted_values[lower])
    # Same expression order as the helpers this replaced, so a seeded Monte
    # Carlo run reproduces its previous percentiles bit for bit.
    idx = float(pct) / 100.0 * (n - 1)
    lower = int(idx)
    upper = min(lower + 1, n - 1)
    frac = idx - lower
    return sorted_values[lower] + frac * (sorted_values[upper] - sorted_values[lower])


def median[Number: (float, Decimal)](values: Sequence[Number]) -> Number | None:
    """The 50th percentile of an unsorted sequence, ``None`` when empty."""
    return percentile(sorted(values), 50)


def quartiles[Number: (float, Decimal)](values: Sequence[Number]) -> tuple[Number | None, Number | None, Number | None]:
    """``(P25, median, P75)`` of an unsorted sequence, all ``None`` when empty."""
    ordered = sorted(values)
    return percentile(ordered, 25), percentile(ordered, 50), percentile(ordered, 75)


def weighted_mean[Number: (float, Decimal)](values: Sequence[Number], weights: Sequence[Number]) -> Number | None:
    """``sum(value * weight) / sum(weight)``.

    Returns ``None`` when the weights sum to zero or there is nothing to
    weigh. A zero total weight means no evidence, not a mean of zero.

    Raises:
        ValueError: ``values`` and ``weights`` differ in length.
    """
    if len(values) != len(weights):
        raise ValueError("values and weights must have the same length")
    if not values:
        return None
    total_weight = sum(weights[1:], weights[0])
    if total_weight == 0:
        return None
    weighted = sum((v * w for v, w in zip(values[1:], weights[1:], strict=True)), values[0] * weights[0])
    return weighted / total_weight


__all__ = ["median", "percentile", "quartiles", "weighted_mean"]
