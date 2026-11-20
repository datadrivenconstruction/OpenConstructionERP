// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Long and cross sections from the surface `sample` route (surfaces_volumes):
 * `{polyline, interval, offsets}` to rows `{ch, offset, e, n, z | null}`, with
 * `ch` measured from the first polyline vertex and offsets right of travel.
 * Nothing here samples a surface; it only shapes the rows for drawing.
 */

export interface SampleRow {
  ch: number;
  offset: number;
  e: number;
  n: number;
  z: number | null;
}

export interface SectionPoint {
  /** Chainage on the alignment (start chainage added). */
  ch: number;
  offset: number;
  z: number | null;
}

export interface CrossSection {
  ch: number;
  points: SectionPoint[];
}

/** Offsets for cross sections: symmetric, `step` apart, out to `half` each side, 0 included. */
export function crossOffsets(half: number, step: number): number[] {
  if (!(half > 0) || !(step > 0)) return [0];
  const n = Math.floor(half / step + 1e-9);
  const out: number[] = [];
  for (let k = -n; k <= n; k++) out.push(Number((k * step).toFixed(6)));
  if (Math.abs(out[out.length - 1]! - half) > 1e-9) {
    out.unshift(-half);
    out.push(half);
  }
  return out;
}

/** The long section: the centreline rows in chainage order. */
export function longSection(rows: readonly SampleRow[], startCh = 0): SectionPoint[] {
  return rows
    .filter((r) => Math.abs(r.offset) < 1e-9)
    .map((r) => ({ ch: r.ch + startCh, offset: 0, z: r.z }))
    .sort((a, b) => a.ch - b.ch);
}

/**
 * Cross sections at the stations that are multiples of `every` (the sample also
 * returns every polyline vertex, which a curve has many of), left to right.
 */
export function crossSections(rows: readonly SampleRow[], startCh = 0, every = 0): CrossSection[] {
  const by = new Map<number, SectionPoint[]>();
  for (const r of rows) {
    const ch = Number((r.ch + startCh).toFixed(6));
    if (every > 0) {
      const q = ch / every;
      if (Math.abs(q - Math.round(q)) > 1e-6) continue;
    }
    const list = by.get(ch) ?? [];
    list.push({ ch, offset: r.offset, z: r.z });
    by.set(ch, list);
  }
  return [...by.entries()]
    .sort((a, b) => a[0] - b[0])
    .map(([ch, points]) => ({ ch, points: points.sort((a, b) => a.offset - b.offset) }));
}

/** Runs of known heights: a gap (z null, off the surface) breaks the line. */
export function runs<T extends { z: number | null }>(pts: readonly T[]): (T & { z: number })[][] {
  const out: (T & { z: number })[][] = [];
  let cur: (T & { z: number })[] = [];
  for (const p of pts) {
    if (p.z == null) {
      if (cur.length) out.push(cur);
      cur = [];
    } else cur.push(p as T & { z: number });
  }
  if (cur.length) out.push(cur);
  return out;
}

export interface SectionFrame {
  x0: number;
  x1: number;
  z0: number;
  z1: number;
  /** Vertical exaggeration actually used. */
  vx: number;
  sx: (x: number) => number;
  sz: (z: number) => number;
}

/**
 * Pixel mapping of a section: x across the full width, heights exaggerated
 * `vx` times relative to x, centred and padded so the profile never touches
 * the frame. Without heights the frame spans 0..1 m.
 */
export function sectionFrame(xs: readonly number[], zs: readonly (number | null)[], width: number, height: number, vx = 10, pad = 24): SectionFrame {
  const known = zs.filter((z): z is number => z != null);
  const x0 = xs.length ? Math.min(...xs) : 0;
  const x1 = xs.length ? Math.max(...xs) : 1;
  const span = Math.max(x1 - x0, 1e-6);
  const pxPerM = (width - 2 * pad) / span;
  const zlo = known.length ? Math.min(...known) : 0;
  const zhi = known.length ? Math.max(...known) : 1;
  const room = (height - 2 * pad) / (pxPerM * vx);
  const mid = (zlo + zhi) / 2;
  const half = Math.max(room, zhi - zlo) / 2;
  const z0 = mid - half;
  const z1 = mid + half;
  const used = (height - 2 * pad) / ((z1 - z0) * pxPerM);
  return {
    x0,
    x1,
    z0,
    z1,
    vx: used,
    sx: (x) => pad + (x - x0) * pxPerM,
    sz: (z) => height - pad - ((z - z0) / (z1 - z0)) * (height - 2 * pad),
  };
}

/** Round height steps for the grid lines of a section (1, 2, 5 x 10^k), about `target` lines. */
export function niceStep(range: number, target = 5): number {
  if (!(range > 0)) return 1;
  const raw = range / target;
  const p = 10 ** Math.floor(Math.log10(raw));
  const m = raw / p;
  return (m < 1.5 ? 1 : m < 3.5 ? 2 : m < 7.5 ? 5 : 10) * p;
}
