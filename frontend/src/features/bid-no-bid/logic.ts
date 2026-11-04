// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Client copy of the server's scoring, used only to show the new score the
 * moment a rating is clicked. The server's answer replaces it.
 */
export const CRITERIA = ['client', 'capacity', 'risk', 'margin', 'competition'] as const;
export type Criterion = (typeof CRITERIA)[number];
export type Weights = Record<Criterion, number>;
export type Scores = Record<Criterion, number | null>;

/** 0-100 with one decimal, or null until every criterion is rated. */
export function weightedScore(weights: Weights, scores: Scores): number | null {
  if (CRITERIA.some((k) => scores[k] == null)) return null;
  const total = CRITERIA.reduce((s, k) => s + Math.max(weights[k], 0), 0);
  if (total <= 0) return null;
  const got = CRITERIA.reduce((s, k) => s + Math.max(weights[k], 0) * (scores[k] as number), 0);
  return Math.round((got * 1000) / (total * 5)) / 10;
}

export function recommendationOf(score: number | null, threshold: number): '' | 'bid' | 'no_bid' {
  if (score == null) return '';
  return score >= threshold ? 'bid' : 'no_bid';
}

export function weightsTotal(weights: Weights): number {
  return CRITERIA.reduce((s, k) => s + weights[k], 0);
}
