// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pixel diff, clustering, alignment, text diff and change building, driven
 * with synthetic sheets: a frame, a title block and a few walls drawn into
 * plain arrays, then edited the way a revision edits a drawing.
 */
import { describe, expect, it } from 'vitest';

import {
  CODE_ADDED,
  CODE_REMOVED,
  CODE_SAME,
  diffMasks,
  dilate,
  inkMaskFromRgba,
  overlayRgba,
  warpMask,
  type InkMask,
} from '../lib/raster';
import { classifyRegion, clusterRegions, coveredShare } from '../lib/cluster';
import { autoAlign, bestShift, inkBounds } from '../lib/align';
import { diffText, isNumericChange, normalizeText } from '../lib/textDiff';
import { buildChanges } from '../lib/buildChanges';
import { computeSheetDiff, DEFAULT_SETTINGS, pdfMatrix, pixelMatrix } from '../lib/sheetDiff';
import {
  applyAffine,
  composeAffine,
  IDENTITY,
  invertAffine,
  similarityFromTwoPoints,
  toPdfSpace,
  toPixelSpace,
} from '../lib/transform';

const W = 400;
const H = 280;

function blank(w = W, h = H): InkMask {
  return { width: w, height: h, data: new Uint8Array(w * h) };
}

function rect(m: InkMask, x: number, y: number, w: number, h: number): void {
  for (let yy = y; yy < y + h; yy++) {
    for (let xx = x; xx < x + w; xx++) {
      if (xx >= 0 && yy >= 0 && xx < m.width && yy < m.height) m.data[yy * m.width + xx] = 1;
    }
  }
}

/** Frame, title block and two walls - the parts every revision keeps. */
function sheet(dx = 0, dy = 0, s = 1, w = W, h = H): InkMask {
  const m = blank(w, h);
  const r = (x: number, y: number, ww: number, hh: number) =>
    rect(m, Math.round(dx + x * s), Math.round(dy + y * s), Math.max(1, Math.round(ww * s)), Math.max(1, Math.round(hh * s)));
  r(10, 10, 380, 2);
  r(10, 268, 380, 2);
  r(10, 10, 2, 260);
  r(388, 10, 2, 260);
  r(290, 230, 98, 2); // title block top
  r(290, 230, 2, 38); // title block side
  r(40, 40, 200, 3); // wall
  r(40, 40, 3, 150); // wall
  return m;
}

describe('ink masks', () => {
  it('reads dark pixels as ink and transparent or light ones as paper', () => {
    const rgba = new Uint8ClampedArray([
      0, 0, 0, 255, // black
      250, 250, 250, 255, // paper
      0, 0, 0, 0, // transparent
      120, 120, 120, 255, // grey line
      0, 0, 0, 40, // faint antialias
    ]);
    expect(Array.from(inkMaskFromRgba(rgba, 5, 1).data)).toEqual([1, 0, 0, 1, 0]);
  });

  it('dilates by a square neighbourhood', () => {
    const m = blank(7, 7);
    m.data[3 * 7 + 3] = 1;
    const d = dilate(m, 1);
    expect(d.reduce((a, b) => a + b, 0)).toBe(9);
    expect(d[2 * 7 + 2]).toBe(1);
    expect(d[1 * 7 + 1]).toBe(0);
    expect(dilate(m, 0)).toEqual(m.data);
  });

  it('warps through an affine with nearest-neighbour sampling', () => {
    const m = blank(20, 20);
    rect(m, 2, 2, 3, 3);
    const moved = warpMask(m, [1, 0, 0, 1, 10, 5], 20, 20);
    expect(inkBounds(moved)).toEqual({ x: 12, y: 7, w: 3, h: 3 });
    expect(warpMask(m, [0, 0, 0, 0, 0, 0], 20, 20).data.every((v) => v === 0)).toBe(true);
  });
});

describe('pixel diff', () => {
  it('finds nothing between identical sheets', () => {
    const d = diffMasks(sheet(), sheet(), 1);
    expect(d.added).toBe(0);
    expect(d.removed).toBe(0);
    expect(d.same).toBeGreaterThan(0);
  });

  it('absorbs a one pixel misregistration within tolerance, not beyond it', () => {
    const shifted = sheet(1, 1);
    expect(diffMasks(sheet(), shifted, 1).added).toBe(0);
    expect(diffMasks(sheet(), shifted, 0).added).toBeGreaterThan(0);
  });

  it('labels new ink added, missing ink removed and kept ink unchanged', () => {
    const before = sheet();
    const after = sheet();
    rect(after, 150, 100, 60, 3); // new wall
    rect(before, 300, 60, 40, 40); // a stair that is gone
    const d = diffMasks(before, after, 1);
    expect(d.codes[101 * W + 160]).toBe(CODE_ADDED);
    expect(d.codes[70 * W + 310]).toBe(CODE_REMOVED);
    expect(d.codes[41 * W + 100]).toBe(CODE_SAME);
    expect(d.added).toBe(180);
    expect(d.removed).toBe(1600);
  });

  it('refuses masks of different frames', () => {
    expect(() => diffMasks(blank(10, 10), blank(11, 10), 1)).toThrow();
  });

  it('paints the overlay grey, red and blue', () => {
    const d = { width: 3, height: 1, codes: new Uint8Array([CODE_SAME, CODE_REMOVED, CODE_ADDED]), added: 1, removed: 1, same: 1 };
    expect(Array.from(overlayRgba(d))).toEqual([156, 163, 175, 255, 220, 38, 38, 255, 37, 99, 235, 255]);
  });
});

describe('clustering', () => {
  it('turns separate edits into separate regions with tight boxes and kinds', () => {
    const before = sheet();
    const after = sheet();
    rect(after, 150, 100, 60, 3); // added
    rect(before, 300, 60, 40, 40); // removed
    rect(before, 60, 200, 30, 3); // moved: removed here ...
    rect(after, 60, 206, 30, 3); // ... added just below
    const regions = clusterRegions(diffMasks(before, after, 1), { cell: 8, gap: 1, minPixels: 10 });
    expect(regions).toHaveLength(3);
    const byKind = Object.fromEntries(regions.map((r) => [r.kind, r]));
    expect(byKind.removed).toMatchObject({ x: 300, y: 60, w: 40, h: 40 });
    expect(byKind.added).toMatchObject({ x: 150, y: 100, w: 60, h: 3 });
    expect(byKind.modified).toMatchObject({ x: 60, y: 200, w: 30, h: 9 });
    // Largest first.
    expect(regions[0]!.kind).toBe('removed');
  });

  it('merges strokes within the gap and drops specks below the minimum', () => {
    const before = sheet();
    const after = sheet();
    rect(after, 100, 120, 10, 10);
    rect(after, 125, 120, 10, 10); // 15 px away
    rect(after, 350, 150, 1, 1); // a speck
    const diff = diffMasks(before, after, 0);
    expect(clusterRegions(diff, { cell: 8, gap: 0, minPixels: 5 })).toHaveLength(2);
    const merged = clusterRegions(diff, { cell: 8, gap: 2, minPixels: 5 });
    expect(merged).toHaveLength(1);
    expect(merged[0]).toMatchObject({ x: 100, w: 35, added: 200 });
    expect(clusterRegions(diff, { cell: 8, gap: 2, minPixels: 0 })).toHaveLength(2);
  });

  it('caps the region count', () => {
    const after = blank();
    for (let i = 0; i < 20; i++) rect(after, 20 + i * 18, 20, 4, 4);
    expect(clusterRegions(diffMasks(blank(), after, 0), { cell: 4, gap: 0, maxRegions: 5 })).toHaveLength(5);
  });

  it('classifies by the minority share', () => {
    expect(classifyRegion(100, 5)).toBe('added');
    expect(classifyRegion(5, 100)).toBe('removed');
    expect(classifyRegion(60, 40)).toBe('modified');
    expect(coveredShare({ x: 0, y: 0, w: 10, h: 10 }, { x: 5, y: 0, w: 10, h: 10 })).toBe(0.5);
  });
});

describe('alignment', () => {
  it('recovers an offset re-plot from the frame and title block', () => {
    const before = sheet();
    const after = sheet(7, -4);
    const { matrix, confidence } = autoAlign(before, after);
    expect(matrix[4]).toBe(7);
    expect(matrix[5]).toBe(-4);
    expect(confidence).toBeGreaterThan(0.95);
    const aligned = warpMask(before, matrix, W, H);
    expect(diffMasks(aligned, after, 1).added).toBe(0);
  });

  it('recovers a scale change (sheet plotted smaller)', () => {
    const before = sheet();
    const after = sheet(20, 14, 0.9);
    const { matrix, confidence } = autoAlign(before, after);
    expect(matrix[0]).toBeCloseTo(0.9, 1);
    expect(confidence).toBeGreaterThan(0.8);
  });

  it('keeps identity with zero confidence when a sheet is blank', () => {
    expect(autoAlign(blank(), sheet())).toEqual({ matrix: IDENTITY, confidence: 0 });
  });

  it('prefers the smaller shift on a flat profile', () => {
    const flat = new Float64Array([1, 1, 1, 1, 1]);
    expect(bestShift(flat, flat, 2).shift).toBe(0);
  });
});

describe('transforms', () => {
  it('builds a two-point similarity and inverts it', () => {
    const m = similarityFromTwoPoints([[0, 0], [100, 0]], [[10, 20], [10, 70]])!;
    expect(applyAffine(m, 100, 0)[0]).toBeCloseTo(10);
    expect(applyAffine(m, 100, 0)[1]).toBeCloseTo(70);
    const inv = invertAffine(m)!;
    const [x, y] = applyAffine(inv, ...applyAffine(m, 33, 44));
    expect(x).toBeCloseTo(33);
    expect(y).toBeCloseTo(44);
    expect(similarityFromTwoPoints([[1, 1], [1, 1]], [[0, 0], [1, 1]])).toBeNull();
    expect(invertAffine([1, 2, 2, 4, 0, 0])).toBeNull();
  });

  it('moves between pixel and PDF space and composes in order', () => {
    const pdf: [number, number, number, number, number, number] = [1, 0, 0, 1, 10, 5];
    expect(toPixelSpace(pdf, 2)).toEqual([1, 0, 0, 1, 20, 10]);
    expect(toPdfSpace(toPixelSpace(pdf, 2), 2)).toEqual(pdf);
    const shiftThenScale = composeAffine([2, 0, 0, 2, 0, 0], [1, 0, 0, 1, 3, 0]);
    expect(applyAffine(shiftThenScale, 1, 1)).toEqual([8, 2]);
  });
});

describe('text diff', () => {
  const item = (str: string, x: number, y: number, w = 30, h = 8) => ({ str, x, y, w, h });

  it('pairs a revised dimension, a revision label and added or removed notes', () => {
    const before = [item('3200', 100, 100), item('REV B', 500, 700), item('EXISTING DOOR', 300, 300, 80), item('A-101', 520, 720)];
    const after = [item('3400', 101, 100), item('REV C', 500, 700), item('A-101', 520, 720), item('NEW STAIR', 50, 50, 60)];
    const changes = diffText(before, after, IDENTITY);
    const changed = changes.filter((c) => c.change === 'changed');
    expect(changed.map((c) => [c.old_text, c.new_text, c.numeric])).toEqual([
      ['REV B', 'REV C', false],
      ['3200', '3400', true],
    ]);
    expect(changes.find((c) => c.change === 'added')?.new_text).toBe('NEW STAIR');
    expect(changes.find((c) => c.change === 'removed')?.old_text).toBe('EXISTING DOOR');
  });

  it('compares old text through the alignment', () => {
    const before = [item('NOTE 4', 90, 95)];
    const after = [item('NOTE 4', 100, 100)];
    expect(diffText(before, after, IDENTITY, { sameRadius: 3, changedRadius: 3 })).toHaveLength(2);
    expect(diffText(before, after, [1, 0, 0, 1, 10, 5])).toEqual([]);
  });

  it('normalises whitespace and width forms, and spots number-only edits', () => {
    expect(normalizeText('  A  101 ')).toBe('A 101');
    expect(normalizeText('Ａ')).toBe('A');
    expect(isNumericChange('2 x 3200 mm', '2 x 3400 mm')).toBe(true);
    expect(isNumericChange('3200', '3200')).toBe(false);
    expect(isNumericChange('WALL', 'DOOR')).toBe(false);
  });
});

describe('change list', () => {
  it('lets a changed value stand for its pixel smudge and folds loose text into regions', () => {
    const regions = [
      { x: 200, y: 200, w: 60, h: 16, added: 40, removed: 40, kind: 'modified' as const }, // under "3200 -> 3400"
      { x: 600, y: 600, w: 200, h: 100, added: 900, removed: 0, kind: 'added' as const },
    ];
    const texts = [
      { change: 'changed' as const, x: 100, y: 100, w: 30, h: 8, old_text: '3200', new_text: '3400', numeric: true },
      { change: 'added' as const, x: 320, y: 320, w: 40, h: 8, old_text: null, new_text: 'NEW STAIR', numeric: false },
    ];
    const out = buildChanges(regions, texts, 2);
    expect(out.map((c) => c.kind)).toEqual(['text', 'added']);
    expect(out[0]).toMatchObject({ old_text: '3200', new_text: '3400', details: { numeric: true } });
    expect(out[1]).toMatchObject({ x: 300, y: 300, w: 100, h: 50, new_text: 'NEW STAIR', score: 900 });
    expect(buildChanges(regions, texts, 2, 1)).toHaveLength(1);
  });
});

describe('sheet compare pipeline', () => {
  const toRgba = (m: InkMask): Uint8ClampedArray => {
    const out = new Uint8ClampedArray(m.data.length * 4).fill(255);
    m.data.forEach((v, i) => {
      if (v) out.set([0, 0, 0, 255], i * 4);
    });
    return out;
  };
  const raster = (m: InkMask, scale: number, text: { str: string; x: number; y: number; w: number; h: number }[] = []) => ({
    width: m.width,
    height: m.height,
    rgba: toRgba(m),
    scale,
    widthPt: m.width / scale,
    heightPt: m.height / scale,
    text,
  });

  it('aligns a shifted re-plot, finds the new wall and reports regions in PDF units', () => {
    const before = sheet();
    const after = sheet(6, 3);
    rect(after, 156, 103, 60, 4);
    const result = computeSheetDiff(raster(before, 2), raster(after, 2), { ...DEFAULT_SETTINGS, compareText: false });
    expect(result.matrix[4]).toBeCloseTo(3); // 6 px at 2 px per unit
    expect(result.matrix[5]).toBeCloseTo(1.5);
    expect(result.confidence).toBeGreaterThan(0.9);
    expect(result.changes).toHaveLength(1);
    expect(result.changes[0]).toMatchObject({ kind: 'added', x: 78, y: 51.5, w: 30, h: 2 });
  });

  it('compares sheets rendered at different resolutions and reads changed text', () => {
    const before = sheet();
    const big = sheet(0, 0, 2, W * 2, H * 2);
    const result = computeSheetDiff(
      raster(before, 1, [{ str: '3200', x: 100, y: 150, w: 20, h: 6 }]),
      raster(big, 2, [{ str: '3400', x: 100, y: 150, w: 20, h: 6 }]),
      { ...DEFAULT_SETTINGS, alignment: 'none' },
    );
    expect(result.regions).toHaveLength(0);
    expect(result.changes).toEqual([
      expect.objectContaining({ kind: 'text', old_text: '3200', new_text: '3400', details: { numeric: true } }),
    ]);
  });

  it('uses two manual points and converts between pixel and PDF space consistently', () => {
    const m: [number, number, number, number, number, number] = [1, 0, 0, 1, 5, 7];
    expect(pdfMatrix(pixelMatrix(m, 1.5, 3), 1.5, 3).map((v) => Math.round(v * 1e9) / 1e9)).toEqual(m);
    const before = sheet();
    const after = sheet(10, 0);
    const result = computeSheetDiff(raster(before, 1), raster(after, 1), {
      ...DEFAULT_SETTINGS,
      alignment: 'manual',
      manualPoints: { old: [[10, 10], [390, 10]], new: [[20, 10], [400, 10]] },
    });
    expect(result.matrix[4]).toBeCloseTo(10);
    expect(result.confidence).toBeNull();
    expect(result.changes).toHaveLength(0);
  });
});
