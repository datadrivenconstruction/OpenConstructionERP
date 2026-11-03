"""Pure Monte Carlo cost sampling over register risks (no DB, no framework).

Shared by the project simulation (``RiskService.simulate``) and the BOQ risk
contingency built from the register, so both read the same distribution.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence
from dataclasses import dataclass, field


def safe_float(value: object, default: float = 0.0) -> float:
    """Coerce a stored string/Decimal/None numeric to a finite float safely."""
    if value is None or value == "":
        return default
    try:
        result = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    # A raw-written absurd value ("1e400") is inf and would poison the percentiles.
    if not math.isfinite(result):
        return default
    return result


def pert_triple_or_point(p10: object, p50: object, p90: object, *, fallback: float) -> tuple[float, float, float]:
    """Return an ordered (low, mode, high) triple; missing parts fall back to a zero-variance point."""
    lo = safe_float(p10, fallback)
    mid = safe_float(p50, fallback)
    hi = safe_float(p90, fallback)
    if hi < lo:
        lo, hi = hi, lo
    mid = min(max(mid, lo), hi)
    return lo, mid, hi


def draw(rng: random.Random | object, lo: float, mid: float, hi: float) -> float:
    """One triangular draw; ``random.triangular`` takes (low, high, mode), not (low, mode, high)."""
    return rng.triangular(lo, hi, mid) if hi > lo else mid  # type: ignore[attr-defined]


def quantile(sorted_samples: Sequence[float], p: float) -> float:
    """Inclusive-method quantile of an ascending sample, ``p`` in [0, 1]."""
    n = len(sorted_samples)
    if n == 1:
        return sorted_samples[0]
    h = p * (n - 1)
    lo = int(h)
    hi = min(lo + 1, n - 1)
    return sorted_samples[lo] + (sorted_samples[hi] - sorted_samples[lo]) * (h - lo)


@dataclass(slots=True)
class CostItem:
    """One risk's cost triple and the share of it the register still carries."""

    low: float
    mode: float
    high: float
    weight: float


@dataclass(slots=True)
class CostSimulation:
    """Per-iteration totals and per-item contribution sums of one cost run."""

    iterations: int
    totals: list[float]
    per_item_sum: list[float] = field(default_factory=list)

    def percentile(self, pct: float) -> float | None:
        """Value at ``pct`` (0-100) of the simulated total, ``None`` for an empty run."""
        return quantile(sorted(self.totals), pct / 100.0) if self.totals else None


def simulate_cost(items: Sequence[CostItem], iterations: int, seed: int | None = None) -> CostSimulation:
    """Sample the probability-weighted cost total ``iterations`` times.

    ``seed`` makes the run reproducible on a private generator; ``None`` draws from
    the module-level generator, as the project simulation always did.
    """
    iterations = max(1, min(int(iterations), 100_000))
    rng = random.Random(seed) if seed is not None else random
    totals: list[float] = []
    per_item = [0.0] * len(items)
    for _ in range(iterations):
        total = 0.0
        for idx, it in enumerate(items):
            if it.weight > 0.0:
                contrib = draw(rng, it.low, it.mode, it.high) * it.weight
                total += contrib
                per_item[idx] += contrib
        totals.append(total)
    return CostSimulation(iterations=iterations, totals=totals, per_item_sum=per_item)
