// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { recommendationOf, weightedScore, weightsTotal, type Scores, type Weights } from './logic';

const W: Weights = { client: 20, capacity: 20, risk: 20, margin: 25, competition: 15 };
const all = (n: number): Scores => ({ client: n, capacity: n, risk: n, margin: n, competition: n });

describe('bid / no-bid scoring', () => {
  it('weights the ratings into a 0-100 score', () => {
    expect(weightedScore(W, all(5))).toBe(100);
    expect(weightedScore(W, all(3))).toBe(60);
    expect(weightedScore(W, { ...all(3), margin: 5, competition: 1 })).toBe(64);
  });

  it('waits until every criterion is rated', () => {
    expect(weightedScore(W, { ...all(3), risk: null })).toBeNull();
    expect(weightedScore({ client: 0, capacity: 0, risk: 0, margin: 0, competition: 0 }, all(3))).toBeNull();
  });

  it('recommends at or above the threshold', () => {
    expect(recommendationOf(60, 60)).toBe('bid');
    expect(recommendationOf(59.9, 60)).toBe('no_bid');
    expect(recommendationOf(null, 60)).toBe('');
  });

  it('sums the weights', () => {
    expect(weightsTotal(W)).toBe(100);
  });
});
