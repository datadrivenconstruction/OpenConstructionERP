/**
 * Traffic-light thresholds for the budget-variance KPI (RFC 25).
 *
 * Levels:
 *   green  — |variance%| <= 3.0
 *   amber  — 3.0 < |variance%| <= 5.0
 *   red    — |variance%| > 5.0
 */

export type VarianceLevel = 'green' | 'amber' | 'red';

export const VARIANCE_GREEN_THRESHOLD = 3.0;
export const VARIANCE_AMBER_THRESHOLD = 5.0;

export function classifyVariance(variancePct: number): VarianceLevel {
  const magnitude = Math.abs(variancePct);
  if (magnitude <= VARIANCE_GREEN_THRESHOLD) return 'green';
  if (magnitude <= VARIANCE_AMBER_THRESHOLD) return 'amber';
  return 'red';
}
