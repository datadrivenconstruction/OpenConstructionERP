// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { ellipseFeatures, ellipseRing, ellipseScale } from './errorEllipses';

describe('ellipseScale', () => {
  it('picks a round factor that draws the largest ellipse near the share of the span', () => {
    // 4 mm on a 400 m network at 6 %: raw 6000, rounded down to 5000.
    expect(ellipseScale([{ ref: 'A', a_m: 0.004, b_m: 0.002, azimuth_deg: 0 }], 400)).toBe(5000);
    expect(ellipseScale([{ ref: 'A', a_m: 0.01, b_m: 0.002, azimuth_deg: 0 }], 400)).toBe(2000);
    expect(ellipseScale([], 400)).toBe(1);
    expect(ellipseScale([{ ref: 'A', a_m: 50, b_m: 1, azimuth_deg: 0 }], 400)).toBe(1);
  });
});

describe('ellipseRing', () => {
  it('lays the major axis on the azimuth from grid north', () => {
    const north = ellipseRing([100, 200], { ref: 'A', a_m: 0.002, b_m: 0.001, azimuth_deg: 0 }, 1000, 4);
    expect(north[0]![0]).toBeCloseTo(100, 9);
    expect(north[0]![1]).toBeCloseTo(202, 9);
    expect(north[1]![0]).toBeCloseTo(101, 9);
    const east = ellipseRing([0, 0], { ref: 'A', a_m: 0.002, b_m: 0.001, azimuth_deg: 90 }, 1000, 4);
    expect(east[0]![0]).toBeCloseTo(2, 9);
    expect(east[0]![1]).toBeCloseTo(0, 9);
  });
});

describe('ellipseFeatures', () => {
  it('draws a ring and an axis for every station with a position and skips the rest', () => {
    const at = new Map([['T2', [10, 20] as [number, number]]]);
    const f = ellipseFeatures(
      [
        { ref: 'T2', a_m: 0.003, b_m: 0.001, azimuth_deg: 45 },
        { ref: 'T9', a_m: 0.003, b_m: 0.001, azimuth_deg: 45 },
      ],
      at,
      1000,
    );
    expect(f.map((x) => x.id)).toEqual(['ellipse:T2', 'ellipse-axis:T2']);
    expect(f[0]!.layer).toBe('ellipses');
  });
});
