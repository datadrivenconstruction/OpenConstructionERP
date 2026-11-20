// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { ellipseExaggeration, ellipseRotation, fitSketch, type Ellipse } from './adjustment';

const ell = (a_m: number): Ellipse => ({ ref: 'T2', a_m, b_m: a_m / 2, azimuth_deg: 30, sd_e_m: 0, sd_n_m: 0 });

describe('traverse sketch helpers', () => {
  it('fits the riverside loop into the frame with north up', () => {
    const pts = [
      { e: 388950.0, n: 5818950.0 },
      { e: 389108.2891, n: 5818950.0079 },
      { e: 389097.4637, n: 5819101.3305 },
      { e: 388937.5471, n: 5819091.6457 },
    ];
    const { at, scale } = fitSketch(pts, 420, 300, 24);
    const [x0, y0] = at(pts[0]!.e, pts[0]!.n);
    const [, yNorth] = at(pts[2]!.e, pts[2]!.n);
    expect(yNorth).toBeLessThan(y0);
    for (const p of pts) {
      const [x, y] = at(p.e, p.n);
      expect(x).toBeGreaterThanOrEqual(24 - 1e-9);
      expect(x).toBeLessThanOrEqual(396 + 1e-9);
      expect(y).toBeGreaterThanOrEqual(24 - 1e-9);
      expect(y).toBeLessThanOrEqual(276 + 1e-9);
    }
    expect(x0).toBeGreaterThan(24);
    expect(scale).toBeCloseTo(252 / 170.742, 3);
  });

  it('turns an azimuth into an SVG rotation in [0, 180)', () => {
    expect(ellipseRotation(0)).toBe(0);
    expect(ellipseRotation(30)).toBe(30);
    expect(ellipseRotation(210)).toBe(30);
    expect(ellipseRotation(-30)).toBe(150);
  });

  it('scales the largest ellipse to a share of the drawing', () => {
    expect(ellipseExaggeration([ell(0.0112), ell(0.0123)], 252)).toBeCloseTo((252 * 0.08) / 0.0123, 6);
    expect(ellipseExaggeration([], 252)).toBe(0);
  });
});
