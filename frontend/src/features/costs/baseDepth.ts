// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// How thoroughly a cost base is worked out, as a band from 1 to 5, so the
// picker can say more than "here are nine countries, good luck".
//
// It is derived from the catalogue's work-item count and from nothing else, and
// that is a decision worth writing down. The registry carries four other things
// that sound like they measure depth - bundled, coefficient, repriceable_markets
// and market_count - and three of them are constant across the bases that have
// them: every national base ships bundled, every one of them declares 49
// repriceable markets, and all but Vietnam can be repriced by resource code. A
// criterion that scores the same for eight of nine families moves every bar by
// the same amount and separates nothing, so folding it into a score would only
// dress the number up. The one attribute that does discriminate, `coefficient`
// (Vietnam and Indonesia are codeless and need a resource price sheet), is shown
// beside the meter as its own mark rather than deducted from it: it is a
// different fact about the base, not less of the same fact.
//
// Bands are absolute rather than relative to the largest base. A ratio would
// re-scale every base the day a bigger one is added, and a base does not become
// shallower because a neighbour grew.

/** Number of segments in the meter. Level 5 is the top band. */
export const DEPTH_BANDS = 5;

/**
 * Lower bound of each band above the first, highest first. A base with at least
 * 40,000 work items reads 5 of 5; below 4,000 it reads 1 of 5.
 */
export const DEPTH_THRESHOLDS = [40000, 15000, 8000, 4000] as const;

/**
 * The depth band of a base with `positions` work items, 1..DEPTH_BANDS.
 *
 * Anything at or below zero reads as the lowest band rather than as an error:
 * the catalogue is what it is, and a picker should still draw a row for it.
 */
export function baseDepthLevel(positions: number): number {
  const index = DEPTH_THRESHOLDS.findIndex((threshold) => positions >= threshold);
  return index === -1 ? 1 : DEPTH_BANDS - index;
}
