// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Automatic sheet alignment.
 *
 * Revisions of one sheet share their frame and title block, which carry most
 * of the ink at the edges of the sheet. So the ink extent of each revision is
 * the registration: matching the two extents gives scale and offset (a sheet
 * re-plotted with a wider margin, or at another paper size). A search on the
 * row and column ink profiles then refines the offset to the pixel, and the
 * share of ink that lands on ink afterwards is the confidence the reviewer
 * sees. Rotation is left to the manual two-point alignment.
 */

import { dilate, inkCount, warpMask, type InkMask } from './raster';
import { composeAffine, IDENTITY, type Affine } from './transform';

export interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface AlignResult {
  /** Old raster pixel -> new raster pixel. */
  matrix: Affine;
  /** 0..1: share of ink that meets ink once aligned. */
  confidence: number;
}

export function inkBounds(mask: InkMask): Box | null {
  const { width, height, data } = mask;
  let x0 = width;
  let y0 = height;
  let x1 = -1;
  let y1 = -1;
  for (let y = 0; y < height; y++) {
    const row = y * width;
    for (let x = 0; x < width; x++) {
      if (!data[row + x]) continue;
      if (x < x0) x0 = x;
      if (x > x1) x1 = x;
      if (y < y0) y0 = y;
      y1 = y;
    }
  }
  return x1 < 0 ? null : { x: x0, y: y0, w: x1 - x0 + 1, h: y1 - y0 + 1 };
}

/** Ink per column (`axis` 'x') or per row ('y'). */
export function inkProfile(mask: InkMask, axis: 'x' | 'y'): Float64Array {
  const { width, height, data } = mask;
  const out = new Float64Array(axis === 'x' ? width : height);
  for (let y = 0; y < height; y++) {
    for (let x = 0; x < width; x++) {
      if (data[y * width + x]) out[axis === 'x' ? x : y]! += 1;
    }
  }
  return out;
}

/** Shift of `moving` (within ±maxShift) that best matches `fixed`, by correlation. */
export function bestShift(fixed: Float64Array, moving: Float64Array, maxShift: number): { shift: number; score: number } {
  let best = { shift: 0, score: -Infinity };
  const n = Math.min(fixed.length, moving.length);
  for (let s = -maxShift; s <= maxShift; s++) {
    let dot = 0;
    for (let i = 0; i < n; i++) {
      const j = i - s;
      if (j < 0 || j >= n) continue;
      dot += fixed[i]! * moving[j]!;
    }
    // Ties prefer the smaller shift, so a featureless profile stays put.
    if (dot > best.score || (dot === best.score && Math.abs(s) < Math.abs(best.shift))) best = { shift: s, score: dot };
  }
  return best;
}

/** Share of ink of both masks that meets ink of the other within one pixel. */
export function overlapScore(a: InkMask, b: InkMask): number {
  const na = inkCount(a);
  const nb = inkCount(b);
  if (na === 0 || nb === 0) return 0;
  const bNear = dilate(b, 1);
  const aNear = dilate(a, 1);
  let hitA = 0;
  let hitB = 0;
  for (let i = 0; i < a.data.length; i++) {
    if (a.data[i] && bNear[i]) hitA++;
    if (b.data[i] && aNear[i]) hitB++;
  }
  return (hitA + hitB) / (na + nb);
}

export interface AutoAlignOptions {
  /** Largest offset refinement, as a share of the larger side. */
  searchShare?: number;
  /** Scale ratios of width and height must agree this closely to be trusted. */
  scaleAgreement?: number;
}

export function autoAlign(oldMask: InkMask, newMask: InkMask, options: AutoAlignOptions = {}): AlignResult {
  const searchShare = options.searchShare ?? 0.02;
  const agreement = options.scaleAgreement ?? 0.03;
  const ob = inkBounds(oldMask);
  const nb = inkBounds(newMask);
  if (!ob || !nb) return { matrix: IDENTITY, confidence: 0 };

  const sx = nb.w / ob.w;
  const sy = nb.h / ob.h;
  let scale = 1;
  if (Math.abs(sx - sy) <= agreement * Math.max(sx, sy) && sx >= 0.5 && sx <= 2) scale = (sx + sy) / 2;
  if (Math.abs(scale - 1) < 0.002) scale = 1;
  const coarse: Affine = [scale, 0, 0, scale, nb.x - scale * ob.x, nb.y - scale * ob.y];

  const warped = warpMask(oldMask, coarse, newMask.width, newMask.height);
  const maxShift = Math.max(2, Math.round(Math.max(newMask.width, newMask.height) * searchShare));
  const dx = bestShift(inkProfile(newMask, 'x'), inkProfile(warped, 'x'), maxShift).shift;
  const dy = bestShift(inkProfile(newMask, 'y'), inkProfile(warped, 'y'), maxShift).shift;
  const matrix = composeAffine([1, 0, 0, 1, dx, dy], coarse);

  const candidates: Affine[] = [matrix, coarse, IDENTITY];
  let best: AlignResult = { matrix: IDENTITY, confidence: -1 };
  for (const m of candidates) {
    const score = overlapScore(warpMask(oldMask, m, newMask.width, newMask.height), newMask);
    if (score > best.confidence + 1e-9) best = { matrix: m, confidence: score };
  }
  return best;
}
