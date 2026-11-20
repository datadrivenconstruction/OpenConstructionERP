// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { hillshade, rasterise, shadedRelief, type Mesh } from './hillshade';

const plane = (dzde: number): Mesh => ({
  vertices: [[0, 0, 0], [10, 0, 10 * dzde], [10, 10, 10 * dzde], [0, 10, 0]],
  faces: [[0, 1, 2], [0, 2, 3]],
});

describe('hillshade', () => {
  it('lights a flat surface by the sine of the sun altitude', () => {
    const r = rasterise(plane(0), 100)!;
    const s = hillshade(r, 315, 45);
    expect(s[Math.floor(r.ny / 2) * r.nx + Math.floor(r.nx / 2)]).toBeCloseTo(Math.SQRT1_2, 9);
  });

  it('gives a west-facing slope under a north-west sun the exact Lambert value', () => {
    const r = rasterise(plane(0.5), 100)!;
    const s = hillshade(r, 315, 45);
    const expected = (0.5 * 0.5 + Math.SQRT1_2) / Math.hypot(0.5, 1);
    expect(s[Math.floor(r.ny / 2) * r.nx + Math.floor(r.nx / 2)]).toBeCloseTo(expected, 6);
    const away = hillshade(rasterise(plane(-0.5), 100)!, 315, 45);
    expect(away[Math.floor(r.ny / 2) * r.nx + Math.floor(r.nx / 2)]!).toBeLessThan(expected);
  });

  it('keeps cells outside the surface transparent', () => {
    const tri: Mesh = { vertices: [[0, 0, 0], [10, 0, 0], [0, 10, 0]], faces: [[0, 1, 2]] };
    const r = rasterise(tri, 100)!;
    const px = shadedRelief(r);
    expect(px[(r.nx - 1) * 4 + 3]).toBe(0);
    expect(px[(r.ny - 1) * r.nx * 4 + 3]).toBe(255);
  });
});
