// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { clipPolygon, clipSegment, fitScale, overlaps, pageLayout, placeLabels, scaleBar, toPaper, type LabelCandidate } from './pdfPlan';

describe('page and scale', () => {
  it('leaves a 320 x 257 mm drawing frame on A3 landscape and fits 150 x 100 m at 1:500', () => {
    const { frame, title } = pageLayout('A3');
    expect(frame).toEqual({ x: 20, y: 20, w: 320, h: 257 });
    expect(title.x).toBe(340);
    expect(fitScale([150, 100], frame)).toBe(500);
    expect(fitScale([170, 100], frame)).toBe(1000);
  });

  it('puts 10 m on the ground at 20 mm on paper at 1:500, north up', () => {
    const v = { centre: [1000, 2000] as [number, number], scale: 500, frame: { x: 0, y: 0, w: 200, h: 100 } };
    expect(toPaper([1010, 2000], v)).toEqual([120, 50]);
    expect(toPaper([1000, 2010], v)).toEqual([100, 30]);
  });

  it('draws a 4 x 5 m bar 40 mm long at 1:500 within 50 mm, exact to 0.1 mm', () => {
    const bar = scaleBar(500, 50, { linearUnit: 'm' });
    expect(bar.step).toBe(5);
    expect(bar.unit).toBe('m');
    expect(Math.abs(bar.lengthMm - 40)).toBeLessThan(0.1);
  });

  it('steps the bar in the project unit when the project works in feet', () => {
    const bar = scaleBar(500, 50, { linearUnit: 'ft' });
    expect(bar.step).toBe(20);
    expect(bar.segmentMm).toBeCloseTo(12.192, 6);
  });
});

describe('clipping', () => {
  const r = { x: 0, y: 0, w: 10, h: 10 };
  it('cuts a segment at the frame edge and drops one outside', () => {
    expect(clipSegment([-5, 5], [5, 5], r)).toEqual([[0, 5], [5, 5]]);
    expect(clipSegment([-5, -5], [-1, -1], r)).toBeNull();
  });

  it('cuts a polygon to the frame', () => {
    const out = clipPolygon([[5, 5], [15, 5], [15, 15], [5, 15]], r);
    const xs = out.map((p) => p[0]), ys = out.map((p) => p[1]);
    expect(Math.min(...xs)).toBe(5);
    expect(Math.max(...xs)).toBe(10);
    expect(Math.max(...ys)).toBe(10);
  });
});

describe('placeLabels', () => {
  it('never prints two labels over each other and keeps them in the frame', () => {
    const frame = { x: 0, y: 0, w: 60, h: 40 };
    const cands: LabelCandidate[] = [];
    for (let i = 0; i < 40; i++) cands.push({ text: `P${i} 12.34 m`, x: 5 + (i % 8) * 6, y: 5 + Math.floor(i / 8) * 6, sizePt: 7, priority: i % 3 });
    const placed = placeLabels(cands, frame);
    expect(placed.length).toBeGreaterThan(0);
    expect(placed.length).toBeLessThan(cands.length);
    for (let i = 0; i < placed.length; i++) {
      const b = placed[i]!.box;
      expect(b.x >= 0 && b.y >= 0 && b.x + b.w <= 60 && b.y + b.h <= 40).toBe(true);
      for (let j = i + 1; j < placed.length; j++) expect(overlaps(b, placed[j]!.box)).toBe(false);
    }
  });

  it('keeps clear of an obstacle such as the scale bar', () => {
    const placed = placeLabels([{ text: 'A', x: 10, y: 10, sizePt: 8, priority: 1 }], { x: 0, y: 0, w: 40, h: 40 }, [{ x: 0, y: 0, w: 40, h: 9.9 }]);
    expect(placed).toHaveLength(1);
    expect(placed[0]!.box.y).toBeGreaterThanOrEqual(9.9);
  });
});
