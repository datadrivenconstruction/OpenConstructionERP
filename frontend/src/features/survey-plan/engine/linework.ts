// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Linework from feature codes. A point coded `EP1` belongs to string 1 of the
 * kerb code `EP`; points of one string are joined in field order
 * (`source_line`). Control suffixes: `ST` starts a new string, `CL` closes it,
 * `END` ends it. The code library (pack default, project override) says which
 * codes draw lines, whether they close and whether they are smoothed.
 */

import type { GridXY, PlanFeature } from '../types';

export interface CodeEntry {
  code: string;
  label: string;
  /** Symbol name in cartography (`tree`, `post`, `manhole`, `kerb`, `spot`, `control`). */
  symbol: string;
  line: 'none' | 'open' | 'closed';
  smooth: boolean;
  layer: string;
  /** A `--oe-map-*` token name (without the prefix), never a hex value. */
  colour: string;
}

export interface CodedPoint {
  id: string;
  e: number;
  n: number;
  z?: number | null;
  code: string;
  sourceLine?: number | null;
}

export interface ParsedCode {
  entry: CodeEntry | null;
  base: string;
  string: string;
  control: 'ST' | 'CL' | 'END' | null;
}

const CONTROL = /(?:^|[\s_./-]?)(ST|CL|END)$/i;

/** Split `EP1 ST` / `EP1CL` / `TR` into its library entry, string number and control suffix. */
export function parseCode(raw: string, library: readonly CodeEntry[]): ParsedCode {
  let text = raw.trim().toUpperCase();
  let control: ParsedCode['control'] = null;
  const m = CONTROL.exec(text);
  if (m && text.length > m[1]!.length) {
    const rest = text.slice(0, text.length - m[0].length).trim();
    // Only a suffix when what is left is still a known code: "CL" alone may be a code.
    if (rest && library.some((c) => rest.startsWith(c.code.toUpperCase()))) {
      control = m[1]!.toUpperCase() as ParsedCode['control'];
      text = rest;
    }
  }
  text = text.split(/\s+/)[0] ?? '';
  // Longest library code that prefixes the token, the remainder being digits.
  let entry: CodeEntry | null = null;
  for (const c of library) {
    const k = c.code.toUpperCase();
    if (text.startsWith(k) && /^\d*$/.test(text.slice(k.length)) && (!entry || k.length > entry.code.length)) entry = c;
  }
  const base = entry ? entry.code.toUpperCase() : text.replace(/\d+$/, '');
  const string = entry ? text.slice(base.length) || '1' : text.slice(base.length) || '1';
  return { entry, base, string, control };
}

function catmullRom(pts: GridXY[], closed: boolean, steps = 4): GridXY[] {
  if (pts.length < 3) return pts;
  const n = pts.length;
  const at = (i: number): GridXY => (closed ? pts[(i + n) % n]! : pts[Math.max(0, Math.min(n - 1, i))]!);
  const out: GridXY[] = [];
  const segs = closed ? n : n - 1;
  for (let i = 0; i < segs; i++) {
    const [p0, p1, p2, p3] = [at(i - 1), at(i), at(i + 1), at(i + 2)];
    for (let s = 0; s < steps; s++) {
      const t = s / steps;
      const t2 = t * t;
      const t3 = t2 * t;
      const c = (a: number, b: number, cc: number, d: number) =>
        0.5 * (2 * b + (-a + cc) * t + (2 * a - 5 * b + 4 * cc - d) * t2 + (-a + 3 * b - 3 * cc + d) * t3);
      out.push([c(p0[0], p1[0], p2[0], p3[0]), c(p0[1], p1[1], p2[1], p3[1])]);
    }
  }
  if (!closed) out.push(pts[n - 1]!);
  return out;
}

/** Linework features from coded points. Each feature lists the point ids it joins. */
export function buildLinework(points: readonly CodedPoint[], library: readonly CodeEntry[]): PlanFeature[] {
  const ordered = [...points].sort((a, b) => (a.sourceLine ?? Number.MAX_SAFE_INTEGER) - (b.sourceLine ?? Number.MAX_SAFE_INTEGER));
  const open = new Map<string, { entry: CodeEntry; pts: CodedPoint[]; closed: boolean; part: number }>();
  const parts = new Map<string, number>();
  const out: PlanFeature[] = [];

  const flush = (key: string) => {
    const s = open.get(key);
    open.delete(key);
    if (!s || s.pts.length < 2) return;
    const closed = s.closed || s.entry.line === 'closed';
    let xy: GridXY[] = s.pts.map((p) => [p.e, p.n]);
    if (s.entry.smooth) xy = catmullRom(xy, closed);
    const id = `linework:${key}:${s.part}`;
    out.push({
      id,
      layer: 'linework',
      geometry: closed && xy.length >= 3 ? { type: 'Polygon', coordinates: [xy] } : { type: 'LineString', coordinates: xy },
      properties: {
        code: s.entry.code,
        string: key,
        label: s.entry.label,
        colour: s.entry.colour,
        closed,
        points: s.pts.map((p) => p.id),
      },
    });
  };

  for (const p of ordered) {
    if (!p.code) continue;
    const parsed = parseCode(p.code, library);
    if (!parsed.entry || parsed.entry.line === 'none') continue;
    const key = `${parsed.base}${parsed.string}`;
    if (parsed.control === 'ST') flush(key);
    let s = open.get(key);
    if (!s) {
      const part = (parts.get(key) ?? 0) + 1;
      parts.set(key, part);
      s = { entry: parsed.entry, pts: [], closed: false, part };
      open.set(key, s);
    }
    s.pts.push(p);
    if (parsed.control === 'CL') {
      s.closed = true;
      flush(key);
    } else if (parsed.control === 'END') flush(key);
  }
  for (const key of [...open.keys()]) flush(key);
  return out;
}

/** Strings that cannot draw: one point, or a closed string under three points (SRV-141/142 mirror). */
export function lineworkProblems(points: readonly CodedPoint[], library: readonly CodeEntry[]): { key: string; code: string; count: number; closed: boolean }[] {
  const counts = new Map<string, { code: string; count: number; closed: boolean }>();
  for (const p of points) {
    const parsed = parseCode(p.code, library);
    if (!parsed.entry || parsed.entry.line === 'none') continue;
    const key = `${parsed.base}${parsed.string}`;
    const cur = counts.get(key) ?? { code: parsed.entry.code, count: 0, closed: parsed.entry.line === 'closed' };
    cur.count += 1;
    if (parsed.control === 'CL') cur.closed = true;
    counts.set(key, cur);
  }
  return [...counts.entries()]
    .filter(([, v]) => v.count < 2 || (v.closed && v.count < 3))
    .map(([key, v]) => ({ key, ...v }));
}
