// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Changed pixels into changed regions.
 *
 * The diff is binned into square cells; cells with changed pixels that lie
 * within `gap` cells of each other form one region, so a moved door reads as
 * one change and not as forty separate strokes. Each region keeps the tight
 * pixel box of its changed pixels and how many were added or removed, which
 * decides whether it reads as added, removed or modified.
 */

import { CODE_ADDED, CODE_REMOVED, type PixelDiff } from './raster';

export type RegionKind = 'added' | 'removed' | 'modified';

export interface DiffRegion {
  x: number;
  y: number;
  w: number;
  h: number;
  added: number;
  removed: number;
  kind: RegionKind;
}

export interface ClusterOptions {
  /** Cell size in pixels. */
  cell?: number;
  /** Cells closer than this (in cells, square distance) join one region. */
  gap?: number;
  /** Regions with fewer changed pixels are noise. */
  minPixels?: number;
  /** Keep at most this many regions, the largest first. */
  maxRegions?: number;
  /** Share of the minority colour below which a region reads one-sided. */
  oneSidedShare?: number;
}

export function classifyRegion(added: number, removed: number, oneSidedShare = 0.1): RegionKind {
  const total = added + removed;
  if (total === 0 || removed <= total * oneSidedShare) return 'added';
  if (added <= total * oneSidedShare) return 'removed';
  return 'modified';
}

export function clusterRegions(diff: PixelDiff, options: ClusterOptions = {}): DiffRegion[] {
  const cell = Math.max(1, Math.round(options.cell ?? 8));
  const gap = Math.max(0, Math.round(options.gap ?? 2));
  const minPixels = options.minPixels ?? 12;
  const maxRegions = options.maxRegions ?? 500;
  const share = options.oneSidedShare ?? 0.1;
  const { width, height, codes } = diff;
  const gw = Math.ceil(width / cell);
  const gh = Math.ceil(height / cell);
  const n = gw * gh;
  const cellAdded = new Uint32Array(n);
  const cellRemoved = new Uint32Array(n);
  const minX = new Int32Array(n).fill(2 ** 30);
  const minY = new Int32Array(n).fill(2 ** 30);
  const maxX = new Int32Array(n).fill(-1);
  const maxY = new Int32Array(n).fill(-1);

  for (let y = 0; y < height; y++) {
    const cy = Math.floor(y / cell) * gw;
    for (let x = 0; x < width; x++) {
      const code = codes[y * width + x];
      if (code !== CODE_ADDED && code !== CODE_REMOVED) continue;
      const c = cy + Math.floor(x / cell);
      if (code === CODE_ADDED) cellAdded[c]!++;
      else cellRemoved[c]!++;
      if (x < minX[c]!) minX[c] = x;
      if (y < minY[c]!) minY[c] = y;
      if (x > maxX[c]!) maxX[c] = x;
      if (y > maxY[c]!) maxY[c] = y;
    }
  }

  const label = new Int32Array(n).fill(-1);
  const regions: DiffRegion[] = [];
  const stack: number[] = [];
  for (let start = 0; start < n; start++) {
    if (label[start] !== -1 || cellAdded[start]! + cellRemoved[start]! === 0) continue;
    const id = regions.length;
    const r = { x0: 2 ** 30, y0: 2 ** 30, x1: -1, y1: -1, added: 0, removed: 0 };
    label[start] = id;
    stack.push(start);
    while (stack.length) {
      const c = stack.pop()!;
      r.added += cellAdded[c]!;
      r.removed += cellRemoved[c]!;
      r.x0 = Math.min(r.x0, minX[c]!);
      r.y0 = Math.min(r.y0, minY[c]!);
      r.x1 = Math.max(r.x1, maxX[c]!);
      r.y1 = Math.max(r.y1, maxY[c]!);
      const cx = c % gw;
      const cy = (c - cx) / gw;
      for (let dy = -gap - 1; dy <= gap + 1; dy++) {
        const ny = cy + dy;
        if (ny < 0 || ny >= gh) continue;
        for (let dx = -gap - 1; dx <= gap + 1; dx++) {
          const nx = cx + dx;
          if (nx < 0 || nx >= gw) continue;
          const nc = ny * gw + nx;
          if (label[nc] !== -1 || cellAdded[nc]! + cellRemoved[nc]! === 0) continue;
          label[nc] = id;
          stack.push(nc);
        }
      }
    }
    regions.push({
      x: r.x0,
      y: r.y0,
      w: r.x1 - r.x0 + 1,
      h: r.y1 - r.y0 + 1,
      added: r.added,
      removed: r.removed,
      kind: classifyRegion(r.added, r.removed, share),
    });
  }
  return regions
    .filter((r) => r.added + r.removed >= minPixels)
    .sort((a, b) => b.added + b.removed - (a.added + a.removed) || a.y - b.y || a.x - b.x)
    .slice(0, maxRegions);
}

/** Share of `region` covered by `cover` (both in the same units). */
export function coveredShare(
  region: { x: number; y: number; w: number; h: number },
  cover: { x: number; y: number; w: number; h: number },
): number {
  const ix = Math.max(0, Math.min(region.x + region.w, cover.x + cover.w) - Math.max(region.x, cover.x));
  const iy = Math.max(0, Math.min(region.y + region.h, cover.y + cover.h) - Math.max(region.y, cover.y));
  const area = region.w * region.h;
  return area > 0 ? (ix * iy) / area : 0;
}
