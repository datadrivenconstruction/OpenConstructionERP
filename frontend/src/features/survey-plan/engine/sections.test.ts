// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { crossOffsets, crossSections, longSection, niceStep, runs, sectionFrame, type SampleRow } from './sections';

// The sample contract of surfaces_volumes on a plane z = 10 + 0.01 ch: stations 0, 20, 30 (vertex), 40.
const ROWS: SampleRow[] = [0, 20, 30, 40].flatMap((ch) =>
  [-5, 0, 5].map((offset) => ({ ch, offset, e: ch, n: -offset, z: ch === 30 && offset === 5 ? null : 10 + 0.01 * ch })),
);

describe('section sampling', () => {
  it('builds symmetric offsets that always reach the edge', () => {
    expect(crossOffsets(10, 5)).toEqual([-10, -5, 0, 5, 10]);
    expect(crossOffsets(12, 5)).toEqual([-12, -10, -5, 0, 5, 10, 12]);
    expect(crossOffsets(0, 5)).toEqual([0]);
  });

  it('takes the centreline rows for the long section, shifted to the start chainage', () => {
    const ls = longSection(ROWS, 1000);
    expect(ls.map((p) => p.ch)).toEqual([1000, 1020, 1030, 1040]);
    expect(ls[3]!.z).toBeCloseTo(10.4, 9);
  });

  it('groups cross sections by station and keeps only round ones when asked', () => {
    const all = crossSections(ROWS);
    expect(all.map((s) => s.ch)).toEqual([0, 20, 30, 40]);
    expect(all[0]!.points.map((p) => p.offset)).toEqual([-5, 0, 5]);
    expect(crossSections(ROWS, 0, 20).map((s) => s.ch)).toEqual([0, 20, 40]);
  });

  it('breaks the line where the surface ends', () => {
    const cs = crossSections(ROWS).find((s) => s.ch === 30)!;
    expect(runs(cs.points).map((r) => r.length)).toEqual([2]);
    expect(runs([{ z: 1 }, { z: null }, { z: 2 }, { z: 3 }]).map((r) => r.length)).toEqual([1, 2]);
  });

  it('frames a section with the requested exaggeration and padding', () => {
    const f = sectionFrame([0, 100], [10, 11], 548, 248, 10, 24);
    expect(f.sx(0)).toBe(24);
    expect(f.sx(100)).toBe(524);
    // 5 px per metre across, x10 up: 50 px per metre of height, 200 px of room = 4 m.
    expect(f.z1 - f.z0).toBeCloseTo(4, 9);
    expect(f.vx).toBeCloseTo(10, 9);
    expect(f.sz(10.5)).toBeCloseTo(124, 9);
  });

  it('shrinks the exaggeration when the relief would not fit', () => {
    const f = sectionFrame([0, 100], [0, 20], 548, 248, 10, 24);
    expect(f.vx).toBeCloseTo(2, 9);
  });

  it('picks round grid steps', () => {
    expect(niceStep(4)).toBe(1);
    expect(niceStep(12)).toBe(2);
    expect(niceStep(0.3)).toBeCloseTo(0.05, 12);
  });
});
