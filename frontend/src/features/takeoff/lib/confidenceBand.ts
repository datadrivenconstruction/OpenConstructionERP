// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/** Turn a detector's confidence into the band a reviewer can act on.
 *
 *  The takeoff viewer used to print the raw number ("62%") next to every AI
 *  suggestion. A percentage is not a decision: an estimator has no way to know
 *  whether 62 is good, and the number reads as precision the detector does not
 *  have. The server already publishes the two cut points it uses itself
 *  (``/plan-read/meta``), so the same suggestion is described the same way on
 *  both sides.
 *
 *  The thresholds are always passed in. Hardcoding them here is what this
 *  module exists to prevent: they are configurable per deployment
 *  (``MATCH_CONFIDENCE_HIGH`` / ``MATCH_CONFIDENCE_MEDIUM``), and a UI that
 *  disagrees with the server about where "high" starts is worse than one that
 *  shows no band at all.
 */

export type ConfidenceBand = 'high' | 'medium' | 'low' | 'unknown';

export interface ConfidenceThresholds {
  /** Lowest confidence still called "high". Inclusive. */
  high: number;
  /** Lowest confidence still called "medium". Inclusive. */
  medium: number;
}

/** Used only while ``/plan-read/meta`` is in flight or unreachable.
 *
 *  Mirrors the backend defaults (``CONFIDENCE_HIGH_THRESHOLD`` /
 *  ``CONFIDENCE_MEDIUM_THRESHOLD``). A deployment that moved its cut points
 *  gets the real ones a moment later; showing nothing until then would make
 *  the badge flicker on every document open.
 */
export const FALLBACK_CONFIDENCE_THRESHOLDS: ConfidenceThresholds = {
  high: 0.78,
  medium: 0.62,
};

/** A threshold pair we can actually band with, or the fallback.
 *
 *  A pair that is non-finite, outside [0, 1], or inverted (medium above high)
 *  cannot produce an honest answer: with high=0.5 and medium=0.8 a score of
 *  0.6 would be labelled "high" while sitting below the medium cut. That is a
 *  confidently wrong badge, which is the one outcome worth avoiding here, so
 *  a malformed pair falls back rather than being repaired into a guess.
 */
function resolveThresholds(thresholds: ConfidenceThresholds | null | undefined): ConfidenceThresholds {
  if (!thresholds) return FALLBACK_CONFIDENCE_THRESHOLDS;
  const { high, medium } = thresholds;
  if (typeof high !== 'number' || typeof medium !== 'number') return FALLBACK_CONFIDENCE_THRESHOLDS;
  if (!Number.isFinite(high) || !Number.isFinite(medium)) return FALLBACK_CONFIDENCE_THRESHOLDS;
  if (high < 0 || high > 1 || medium < 0 || medium > 1) return FALLBACK_CONFIDENCE_THRESHOLDS;
  if (medium > high) return FALLBACK_CONFIDENCE_THRESHOLDS;
  return { high, medium };
}

/** Band a confidence score.
 *
 *  Comparison is inclusive on the lower edge, matching ``confidence_band`` in
 *  ``ai_estimator/intl.py`` so a score sitting exactly on a cut point is
 *  called the same thing by both sides.
 *
 *  Anything that is not a real score in [0, 1] returns ``unknown`` rather than
 *  throwing. The backend raises on a malformed score because it is validating;
 *  here the value is already stored and the only question is what to paint,
 *  and no badge is ever worth taking the viewer down for. ``unknown`` is also
 *  the honest answer for the offline Recognize path, which proposes geometry
 *  without scoring it.
 */
export function confidenceBand(
  value: number | null | undefined,
  thresholds?: ConfidenceThresholds | null,
): ConfidenceBand {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'unknown';
  if (value < 0 || value > 1) return 'unknown';
  const { high, medium } = resolveThresholds(thresholds);
  if (value >= high) return 'high';
  if (value >= medium) return 'medium';
  return 'low';
}

/** How many suggestions sit in each band.
 *
 *  Feeds the review bar: "Accept all" over a pile of low-confidence proposals
 *  is a different act from accepting a pile of high-confidence ones, and the
 *  bar could not say so while the counts lived only inside each row's badge.
 */
export function countConfidenceBands(
  values: readonly (number | null | undefined)[],
  thresholds?: ConfidenceThresholds | null,
): Record<ConfidenceBand, number> {
  const counts: Record<ConfidenceBand, number> = { high: 0, medium: 0, low: 0, unknown: 0 };
  for (const value of values) counts[confidenceBand(value, thresholds)] += 1;
  return counts;
}
