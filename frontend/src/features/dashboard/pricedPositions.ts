// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The "Priced positions" KPI tile used to read a synthesized proxy: the
// dashboard collapsed every project's positions into a one-element array
// carrying a 0/1 flag, and the tile then counted that array as if it were
// the positions themselves. With one project holding 1 priced and 99
// unpriced positions the tile computed 1/1 and rendered 100 percent, in
// green - the opposite of the user's state, with a colour confirming it.
//
// The rollup already carries the real numbers (``position_count`` and
// ``positions_zero_price`` on ``boq_summary``), which is what the
// BOQSummaryWidget in components/NewWidgets.tsx has always used for its
// "Zero priced" figure. This is that arithmetic, lifted out so the tile
// and the widget cannot drift and so it can be tested without mounting a
// 2700-line page.

/** The two counts the tile needs, as the ``boq_summary`` rollup reports them. */
export interface PositionCounts {
  /** Every BOQ position across the caller's projects. */
  position_count: number;
  /** Of those, how many carry no price. */
  positions_zero_price: number;
}

/**
 * Below this many positions the tile shows the counts and no percentage.
 *
 * A percentage over a handful of positions is arithmetically true and
 * useless: one priced line out of two is "50 percent" and reads like a
 * project half-costed. The counts say the same thing without the false
 * precision, and they say it at every size, which is why they are always
 * shown and the percentage is not.
 */
export const MIN_POSITIONS_FOR_PCT = 10;

/**
 * A priced-positions reading.
 *
 * ``pct`` is 0-100 rounded, or ``null`` when ``total`` is below
 * {@link MIN_POSITIONS_FOR_PCT} - including a total of 0, which is not a
 * special case here. "0 of 0 priced" is the truth and needs no branch.
 */
export interface PricedPositions {
  priced: number;
  total: number;
  pct: number | null;
}

/**
 * Priced-position counts, and a percentage only when one is meaningful.
 *
 * Returns ``null`` only when the rollup has not loaded - "we do not know
 * yet", which the caller renders as a loading tile. That is distinct from
 * knowing the counts are zero, which returns ``{priced: 0, total: 0, pct:
 * null}`` and renders as "0 of 0 priced".
 *
 * Counts are clamped rather than trusted: a backend that reported more
 * unpriced positions than positions would otherwise produce a negative
 * numerator and a negative percentage on screen.
 */
export function pricedPositions(counts: PositionCounts | null | undefined): PricedPositions | null {
  if (!counts) return null;

  const total = Math.max(0, Math.trunc(counts.position_count) || 0);
  const unpriced = Math.min(total, Math.max(0, Math.trunc(counts.positions_zero_price) || 0));
  const priced = total - unpriced;

  return {
    priced,
    total,
    pct: total >= MIN_POSITIONS_FOR_PCT ? Math.round((priced / total) * 100) : null,
  };
}
