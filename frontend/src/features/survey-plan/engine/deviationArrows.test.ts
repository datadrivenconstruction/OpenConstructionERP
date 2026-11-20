// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { arrowLengthFor, deviationArrow, mmPerArrowMetre, stakeFeatures, verdictCounts, verdictStyle } from './deviationArrows';

describe('deviation arrows', () => {
  it('scales a 3-4-5 mm deviation x100 to a 0.5 m arrow pointing the same way', () => {
    const a = deviationArrow([100, 200], [100.003, 200.004], 100);
    expect(a.devMm).toBe(5);
    expect(a.planLength).toBeCloseTo(0.5, 9);
    expect(a.head[0]![0]).toBeCloseTo(100.3, 9);
    expect(a.head[0]![1]).toBeCloseTo(200.4, 9);
    // Shaft stops at the head base, 22 % back along the arrow.
    expect(Math.hypot(a.shaft[1][0] - 100, a.shaft[1][1] - 200)).toBeCloseTo(0.5 * 0.78, 9);
  });

  it('keeps the head short on long arrows and draws nothing for zero', () => {
    const long = deviationArrow([0, 0], [0.05, 0], 500);
    expect(long.planLength).toBeCloseTo(25, 9);
    expect(long.head[0]![0] - long.shaft[1][0]).toBeCloseTo(1.2, 9);
    expect(deviationArrow([1, 1], [1, 1], 100).head).toEqual([]);
  });

  it('states the scale in words for the legend', () => {
    expect(mmPerArrowMetre(100)).toBe(10);
    expect(mmPerArrowMetre(10)).toBe(100);
    expect(arrowLengthFor(10, 100)).toBeCloseTo(1, 9);
    expect(arrowLengthFor(10, 500)).toBeCloseTo(5, 9);
  });

  it('gives every verdict its own colour and shape', () => {
    expect(verdictStyle('pass')).toEqual({ token: 'success', shape: 'circle', semantic: 'success' });
    expect(verdictStyle('fail')).toEqual({ token: 'error', shape: 'square', semantic: 'error' });
    expect(verdictStyle('no_tolerance').shape).toBe('diamond');
    expect(verdictStyle(undefined).shape).toBe('cross');
    const shapes = new Set(['pass', 'fail', 'no_tolerance', 'open'].map((v) => verdictStyle(v).shape));
    expect(shapes.size).toBe(4);
  });

  it('builds design cross, as-staked dot, shaft and head per measured stake', () => {
    const f = stakeFeatures(
      [
        { id: 'a', pointId: 'C-03', design: [0, 0], measured: [0.004, 0], verdict: 'pass', dE: 4, dN: 0 },
        { id: 'b', pointId: 'C-04', design: [10, 0], measured: null, verdict: 'open' },
      ],
      100,
    );
    expect(f.map((x) => x.properties.role)).toEqual(['design', 'measured', 'arrow', 'head', 'design']);
    expect(f[0]!.properties.colour).toBe('success');
    expect(f[0]!.entityId).toBe('a');
    expect(verdictCounts([{ verdict: 'pass' }, { verdict: 'fail' }, { verdict: 'pass' }])).toEqual({ pass: 2, fail: 1, no_tolerance: 0, open: 0 });
  });
});
