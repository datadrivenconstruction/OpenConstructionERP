import { describe, it, expect } from 'vitest';
import { buildPareto } from '../components/ParetoHelper';

describe('buildPareto — top N by share', () => {
  it('returns empty array when input is empty', () => {
    expect(buildPareto([], 5)).toEqual([]);
  });

  it('orders by descending share and fills cumulative totals', () => {
    const input = [
      { position_id: 'a', description: 'A', total_cost: 100 },
      { position_id: 'b', description: 'B', total_cost: 400 },
      { position_id: 'c', description: 'C', total_cost: 200 },
      { position_id: 'd', description: 'D', total_cost: 300 },
    ];
    const pareto = buildPareto(input, 5);
    expect(pareto.map((p) => p.key)).toEqual(['b', 'd', 'c', 'a']);
    expect(pareto[0]!.share).toBeCloseTo(0.4, 5);
    expect(pareto[pareto.length - 1]!.cumulative).toBeCloseTo(1.0, 5);
  });

  it('collapses the tail into an "other" bucket when more than topN items exist', () => {
    const input = Array.from({ length: 10 }, (_, i) => ({
      position_id: `p${i}`,
      description: `Item ${i}`,
      total_cost: (i + 1) * 10,
    }));
    const pareto = buildPareto(input, 3);
    expect(pareto).toHaveLength(4);
    expect(pareto[pareto.length - 1]!.is_other).toBe(true);
    expect(pareto[pareto.length - 1]!.key).toBe('__other__');
    const totalShare = pareto.reduce((acc, p) => acc + p.share, 0);
    expect(totalShare).toBeCloseTo(1.0, 5);
  });

  it('breaks ties deterministically by position_id', () => {
    const input = [
      { position_id: 'bravo', description: 'B', total_cost: 100 },
      { position_id: 'alpha', description: 'A', total_cost: 100 },
      { position_id: 'delta', description: 'D', total_cost: 100 },
      { position_id: 'charlie', description: 'C', total_cost: 100 },
    ];
    const pareto = buildPareto(input, 4);
    // Equal shares -> sorted ascending by key for stable ordering
    expect(pareto.map((p) => p.key)).toEqual([
      'alpha',
      'bravo',
      'charlie',
      'delta',
    ]);
  });

  it('computes shares from total_cost when share_of_total is missing', () => {
    const input = [
      { position_id: 'x', total_cost: 80 },
      { position_id: 'y', total_cost: 20 },
    ];
    const pareto = buildPareto(input, 5);
    expect(pareto[0]!.share).toBeCloseTo(0.8, 5);
    expect(pareto[1]!.share).toBeCloseTo(0.2, 5);
  });
});
