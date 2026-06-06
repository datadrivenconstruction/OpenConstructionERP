# DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
# Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
"""Rate-sanity benchmark bands for the multi-pass mapping pipeline.

Curated, deterministic, currency- and catalogue-agnostic data (no ML, no DB,
no price book), the same pattern as :mod:`taxonomy` and :mod:`project_types`.

The mapping pipeline's third pass (rate sanity) never invents a rate and never
silently drops a real catalogue rate. Instead it computes, per run, the *median*
per-base-unit rate across the candidates a group actually retrieved from the
cost DB, then flags any candidate that sits more than a ``band factor`` away from
that median (above or below) as a low-confidence outlier for human review. The
band is therefore self-calibrating against whatever catalogue and currency are
bound: it is a sanity flag, not a price book.

The founder-locked default (see ``docs/strategy/AI_ESTIMATOR_V3_DESIGN.md`` section
10, decision 2) is a single global band factor of ``8x``, surfaced on the module
``/meta`` endpoint so the frontend never hardcodes the magic number. A small
per-(trade, unit) override table is provided for trades whose real-world rate
spread is genuinely wider or tighter than the default; every key in it must be a
real ``(trade, unit)`` pair the curated work packages emit (asserted by a test).
"""

from __future__ import annotations

from statistics import median

# ── The global default band factor ───────────────────────────────────────────

# A candidate whose per-base-unit rate is more than this multiple away from the
# per-run median (i.e. rate > median * factor, or rate < median / factor) is an
# outlier. 8x is deliberately wide: the CWICR catalogue mixes labour-only,
# material-only and full-supply-and-fix rows for the same work, so a tight band
# would flag honest rows. The aim is to catch unit-mismatch leftovers and gross
# data errors, not to second-guess a real estimator's spread. Exposed on /meta.
DEFAULT_BAND_FACTOR: float = 8.0

# Per-(trade, unit) overrides for trades whose plausible spread differs from the
# default. Ratios are relative to the per-run catalogue median, never absolute
# money, so they stay currency- and region-agnostic. Keys must be real
# ``(trade, unit)`` pairs emitted by the curated work packages (see
# ``project_types.py``); a test enforces this so the table cannot drift.
#
# Rationale per entry:
#   - Lump-sum lines (``lsum`` / ``lump``) cover wildly different scopes (a whole
#     commissioning vs a single connection), so their honest spread is very wide:
#     a tighter band would flag legitimate rows. Widened to 12x.
#   - Demolition is cheap and fairly uniform per m2/m3, so a tighter 6x band
#     catches a stray supply-and-fix row mislabelled as demolition.
BAND_FACTOR_OVERRIDES: dict[tuple[str, str], float] = {
    ("other", "lsum"): 12.0,
    ("mep_mechanical", "lsum"): 12.0,
    ("masonry", "lsum"): 12.0,
    ("demolition", "m2"): 6.0,
    ("demolition", "m3"): 6.0,
}


def band_factor_for(trade: str, unit: str) -> float:
    """Return the rate-sanity band factor for a ``(trade, unit)`` pair.

    Looks up the per-trade override table and falls back to
    :data:`DEFAULT_BAND_FACTOR`. Pure and side-effect-free so the offline
    (no-AI-key) path computes an identical band.

    Args:
        trade: The group's trade bucket (a key from :mod:`taxonomy`).
        unit: The group's chosen measurement unit (``m2`` / ``m3`` / ``m`` /
            ``pcs`` / ``lsum`` / ``lump``).

    Returns:
        The multiplicative band factor (always ``>= 1.0``).
    """
    return BAND_FACTOR_OVERRIDES.get((trade, unit), DEFAULT_BAND_FACTOR)


def candidate_median(rates: list[float]) -> float | None:
    """Return the median per-base-unit rate across a group's candidates.

    The reference point pass 3 flags outliers against. Designed for the two
    edge cases the mapping pipeline meets in practice:

    * **Empty catalogue / no candidates** (``rates == []``): there is nothing to
      compare against, so this returns ``None`` and pass 3 flags nothing (the
      group is already an honest ``gap`` / ``needs_human`` upstream).
    * **Single candidate** (``len(rates) == 1``): the median is that one rate,
      so it can never be an outlier against itself; pass 3 keeps it as-is.

    Non-positive rates (``<= 0``) are ignored: a zero or negative rate is not a
    meaningful price and would drag the median toward zero, making every real
    rate look like a high-side outlier. If every rate is non-positive the
    function returns ``None`` (nothing usable to anchor against).

    Args:
        rates: The per-base-unit rates of the candidates retrieved for one
            group, already rescaled by the unit-reconcile pass.

    Returns:
        The median of the usable (positive) rates, or ``None`` when there is no
        usable rate to anchor against.
    """
    usable = [r for r in rates if r > 0]
    if not usable:
        return None
    return float(median(usable))


def is_outlier(rate: float, median_rate: float | None, band_factor: float) -> bool:
    """Return whether a candidate rate is a band outlier against the median.

    A rate is an outlier when it sits more than ``band_factor`` away from the
    median on either side: ``rate > median * band_factor`` (too high) or
    ``rate < median / band_factor`` (too low). This only ever *flags* a rate; it
    never replaces or drops it. The caller caps the flagged candidate's
    confidence at the LOW band and records it in the mapping trace.

    Args:
        rate: The candidate's per-base-unit rate (already unit-reconciled).
        median_rate: The per-run median from :func:`candidate_median`, or
            ``None`` when there was nothing to anchor against.
        band_factor: The band factor from :func:`band_factor_for`.

    Returns:
        ``True`` when the rate is an outlier, ``False`` otherwise. Always
        ``False`` when ``median_rate`` is ``None`` or the rate is non-positive
        (nothing to compare, so nothing is flagged).
    """
    if median_rate is None or median_rate <= 0 or rate <= 0 or band_factor <= 0:
        return False
    return rate > median_rate * band_factor or rate < median_rate / band_factor


def evaluate_band(
    trade: str,
    unit: str,
    rates: list[float],
) -> tuple[float | None, float | None, float]:
    """Return the ``(band_low, band_high, factor)`` for a group's candidates.

    A convenience wrapper that the rate-sanity pass uses to populate the
    ``benchmark`` block of the mapping trace in one call. The band bounds are the
    median divided/multiplied by the factor; they are ``None`` when there is no
    usable median (empty or all-non-positive candidate set).

    Args:
        trade: The group's trade bucket.
        unit: The group's chosen unit.
        rates: The candidates' per-base-unit rates.

    Returns:
        A ``(band_low, band_high, band_factor)`` tuple. ``band_low`` and
        ``band_high`` are ``None`` when no median could be computed.
    """
    factor = band_factor_for(trade, unit)
    med = candidate_median(rates)
    if med is None:
        return None, None, factor
    return med / factor, med * factor, factor
