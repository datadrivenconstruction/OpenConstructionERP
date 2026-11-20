// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { centreline, chainageTicks, designAlignment, ipsFromStored, pointAt, stationOffset, tickSegment } from './alignmentGeom';

// IP1 (100, 0), 90 deg left, R 50: T = 50, L = 25 pi = 78.5398, E = 50 (sqrt2 - 1).
const L_TURN = [
  { e: 0, n: 0, radius: 0 },
  { e: 100, n: 0, radius: 50 },
  { e: 100, n: 100, radius: 0 },
];

describe('alignment by IP', () => {
  it('matches the hand calc of a 90 degree left turn', () => {
    const d = designAlignment(L_TURN);
    const [c] = d.curves;
    expect(c!.left).toBe(true);
    expect(c!.tangent).toBeCloseTo(50, 9);
    expect(c!.tc[0]).toBeCloseTo(50, 9);
    expect(c!.tc[1]).toBeCloseTo(0, 9);
    expect(c!.ct[0]).toBeCloseTo(100, 9);
    expect(c!.ct[1]).toBeCloseTo(50, 9);
    expect(c!.centre[0]).toBeCloseTo(50, 9);
    expect(c!.centre[1]).toBeCloseTo(50, 9);
    expect(c!.arcLength).toBeCloseTo(78.5398, 4);
    expect(c!.external).toBeCloseTo(50 * (Math.SQRT2 - 1), 9);
    expect(c!.tcCh).toBeCloseTo(50, 9);
    expect(c!.ctCh).toBeCloseTo(128.5398, 4);
    expect(d.length).toBeCloseTo(178.5398, 4);
    expect(d.fits).toBe(true);
  });

  it('stations an arc: mid-arc lies on the bisector, offsets right of travel', () => {
    const d = designAlignment(L_TURN, 1000);
    const mid = pointAt(d, 1000 + 50 + 78.5398 / 2)!;
    expect(mid.p[0]).toBeCloseTo(50 + 50 / Math.SQRT2, 3);
    expect(mid.p[1]).toBeCloseTo(50 - 50 / Math.SQRT2, 3);
    expect(mid.az).toBeCloseTo(45, 3);
    // Turning left, right of travel points away from the centre.
    const right = pointAt(d, 1000 + 50 + 78.5398 / 2, 5)!;
    expect(Math.hypot(right.p[0] - 50, right.p[1] - 50)).toBeCloseTo(55, 6);
    expect(pointAt(d, 999)).toBeNull();
    const back = stationOffset(d, right.p)!;
    expect(back.ch).toBeCloseTo(1000 + 50 + 78.5398 / 2, 3);
    expect(back.offset).toBeCloseTo(5, 6);
  });

  it('puts chainage ticks every 20 m and labels every 100 m', () => {
    const d = designAlignment(L_TURN);
    const ticks = chainageTicks(d, 20, 100);
    expect(ticks.map((t) => t.ch)).toEqual([0, 20, 40, 60, 80, 100, 120, 140, 160]);
    expect(ticks.filter((t) => t.labelled).map((t) => t.ch)).toEqual([0, 100]);
    expect(ticks[1]!.p).toEqual([20, 0]);
    const [a, b] = tickSegment(ticks[1]!, 2);
    expect(a[1]).toBeCloseTo(2, 9);
    expect(b[1]).toBeCloseTo(-2, 9);
  });

  it('starts ticks at the next round chainage after a non-round start', () => {
    const d = designAlignment(L_TURN, 1013.2);
    expect(chainageTicks(d, 20, 100)[0]!.ch).toBe(1020);
  });

  it('flags curves that overlap on one tangent and still draws them', () => {
    const d = designAlignment([
      { e: 0, n: 0, radius: 0 },
      { e: 100, n: 0, radius: 60 },
      { e: 100, n: 100, radius: 60 },
      { e: 200, n: 100, radius: 0 },
    ]);
    expect(d.fits).toBe(false);
    expect(d.overlaps).toHaveLength(1);
    expect(d.overlaps[0]).toMatchObject({ a: 'IP1', b: 'IP2' });
    expect(d.overlaps[0]!.need).toBeCloseTo(120, 9);
    expect(d.overlaps[0]!.have).toBeCloseTo(100, 9);
    expect(d.curves.map((c) => c.fits)).toEqual([false, false]);
    expect(centreline(d).length).toBeGreaterThan(10);
  });

  it('keeps an angle point without a radius as a vertex', () => {
    const d = designAlignment([
      { e: 0, n: 0, radius: 0 },
      { e: 100, n: 0, radius: 0 },
      { e: 100, n: 100, radius: 0 },
    ]);
    expect(d.curves).toEqual([]);
    expect(d.length).toBeCloseTo(200, 9);
    expect(centreline(d)).toEqual([[0, 0], [100, 0], [100, 100]]);
  });

  it('reads the IPs back from the stored alignment', () => {
    const back = ipsFromStored({ name: 'A', start_chainage: 5, design_speed_kmh: 50, ips: L_TURN, elements: [] });
    expect(back).toEqual({ ips: L_TURN.map((p) => ({ ...p, name: '' })), startCh: 5, speed: 50, name: 'A' });
    expect(ipsFromStored({ elements: [{ type: 'line' }] })).toBeNull();
  });
});
