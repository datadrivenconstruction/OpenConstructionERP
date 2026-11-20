// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import type { ViewTransformDTO } from '../types';
import { LOCAL_K, fromDTO, localTransform, metresPerPixel, niceBar, scaleDenominator } from './viewTransform';

describe('local grid mapping', () => {
  it('round-trips to well under a millimetre across 10 km', () => {
    const t = localTransform(1000, 5000);
    for (const p of [[1000, 5000], [6000, 10000], [-4000, 0], [1234.5678, 5432.1012]] as [number, number][]) {
      const back = t.toGrid(t.toView(p));
      expect(Math.abs(back[0] - p[0])).toBeLessThan(1e-6);
      expect(Math.abs(back[1] - p[1])).toBeLessThan(1e-6);
    }
    expect(t.toView([1000 + LOCAL_K, 5000])).toEqual([1, 0]);
    expect(t.residualMm).toBe(0);
  });

  it('distorts distances by less than 2e-6 on a 10 km site', () => {
    // Web Mercator stretches north-south by 1/cos(lat); at the 5 km edge lat is 0.045 deg.
    const lat = 5000 / LOCAL_K;
    expect(1 / Math.cos((lat * Math.PI) / 180) - 1).toBeLessThan(2e-6);
  });
});

describe('polynomial transform', () => {
  it('evaluates both directions and refines the inverse', () => {
    // A pure affine "polynomial": lon = 13 + u * 0.01, lat = 52 + v * 0.009.
    const dto: ViewTransformDTO = {
      kind: 'polynomial',
      epsg: 25833,
      crs_name: 'ETRS89 / UTM zone 33N',
      e0: 400000,
      n0: 5800000,
      s: 1000,
      lon: [13, 0.01, 0, 0, 0, 0],
      lat: [52, 0, 0.009, 0, 0, 0],
      lon0: 13,
      lat0: 52,
      q: 0.01,
      e: [400000, 1000, 0, 0, 0, 0],
      n: [5800000, 0, 1000 / 0.9, 0, 0, 0],
      residual_mm: 0.2,
      grid_north_bearing: -0.8,
      extent: null,
    };
    const t = fromDTO(dto);
    const v = t.toView([401000, 5801000]);
    expect(v[0]).toBeCloseTo(13.01, 12);
    expect(v[1]).toBeCloseTo(52.009, 12);
    const g = t.toGrid(v);
    expect(g[0]).toBeCloseTo(401000, 6);
    expect(g[1]).toBeCloseTo(5801000, 6);
    expect(t.gridNorthBearing).toBe(-0.8);
  });
});

describe('scale', () => {
  it('reads 1:N at 96 dpi and picks a round bar', () => {
    const mpp = metresPerPixel(20, 0, 'local');
    expect(scaleDenominator(mpp)).toBeGreaterThan(280);
    expect(scaleDenominator(mpp)).toBeLessThan(290);
    const bar = niceBar(0.1, 120);
    expect(bar.metres).toBe(10);
    expect(bar.px).toBeCloseTo(100, 9);
  });
});
