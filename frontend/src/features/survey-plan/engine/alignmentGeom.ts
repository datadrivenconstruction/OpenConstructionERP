// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Horizontal alignment by intersection points, live in the browser. Mirrors
 * `setting_out/alignment_design.py` (the saved alignment is the server's):
 *
 *   deflection D (left positive), T = R tan(|D|/2), L = R |D|,
 *   TC = IP - u_in T, CT = IP + u_out T, centre = TC + R n (towards the turn).
 *
 * Curves whose tangents need more of a leg than the leg has are kept and
 * flagged (`fits: false`), so the editor can draw them red while you type.
 */

import type { GridXY } from '../types';
import { azimuthOf } from '../units/angles';

export interface IpInput {
  e: number;
  n: number;
  /** 0 is an angle point without a curve. */
  radius: number;
  name?: string;
}

export interface CurveGeom {
  ref: string;
  ipIndex: number;
  radius: number;
  deflectionDeg: number;
  left: boolean;
  tangent: number;
  arcLength: number;
  external: number;
  tc: GridXY;
  ct: GridXY;
  centre: GridXY;
  tcCh: number;
  ctCh: number;
  /** False when this curve overlaps a neighbour or overruns its tangent. */
  fits: boolean;
}

export type AlignElement =
  | { kind: 'line'; start: GridXY; end: GridXY; ch0: number; length: number }
  | { kind: 'arc'; start: GridXY; end: GridXY; centre: GridXY; radius: number; left: boolean; ch0: number; length: number };

export interface Overlap {
  a: string;
  b: string;
  need: number;
  have: number;
}

export interface AlignmentDesign {
  startCh: number;
  length: number;
  curves: CurveGeom[];
  elements: AlignElement[];
  overlaps: Overlap[];
  fits: boolean;
}

const EPS = 1e-9;

export const ipRef = (ips: readonly IpInput[], i: number) => ips[i]?.name || `IP${i}`;

function unit(a: GridXY, b: GridXY): { u: GridXY; len: number } {
  const dx = b[0] - a[0];
  const dy = b[1] - a[1];
  const len = Math.hypot(dx, dy);
  return { u: len < EPS ? [0, 0] : [dx / len, dy / len], len };
}

/** Tangent points, arcs, elements and overlaps of an IP polyline. */
export function designAlignment(ips: readonly IpInput[], startCh = 0): AlignmentDesign {
  const pts = ips.map((p) => [p.e, p.n] as GridXY);
  const empty: AlignmentDesign = { startCh, length: 0, curves: [], elements: [], overlaps: [], fits: true };
  if (pts.length < 2) return empty;
  const legs = pts.slice(0, -1).map((p, i) => unit(p, pts[i + 1]!));
  const tangents = pts.map(() => 0);
  const raw: { i: number; defl: number; r: number }[] = [];
  for (let i = 1; i < pts.length - 1; i++) {
    const u1 = legs[i - 1]!.u;
    const u2 = legs[i]!.u;
    const cross = u1[0] * u2[1] - u1[1] * u2[0];
    const dot = Math.max(-1, Math.min(1, u1[0] * u2[0] + u1[1] * u2[1]));
    const defl = Math.atan2(cross, dot);
    const r = ips[i]!.radius;
    if (!(r > 0) || Math.abs(defl) < EPS || Math.abs(Math.abs(defl) - Math.PI) < 1e-6) {
      if (Math.abs(defl) >= EPS) raw.push({ i, defl, r: 0 });
      continue;
    }
    tangents[i] = r * Math.tan(Math.abs(defl) / 2);
    raw.push({ i, defl, r });
  }
  const bad = new Set<number>();
  const overlaps: Overlap[] = [];
  legs.forEach((leg, k) => {
    const need = tangents[k]! + tangents[k + 1]!;
    if (need > leg.len + 1e-6) {
      const a = tangents[k] ? ipRef(ips, k) : ipRef(ips, k + 1);
      const b = tangents[k] ? ipRef(ips, k + 1) : a;
      overlaps.push({ a, b, need, have: leg.len });
      if (tangents[k]) bad.add(k);
      if (tangents[k + 1]) bad.add(k + 1);
    }
  });

  const elements: AlignElement[] = [];
  const curves: CurveGeom[] = [];
  let cursor = pts[0]!;
  let ch = startCh;
  const line = (to: GridXY) => {
    const len = Math.hypot(to[0] - cursor[0], to[1] - cursor[1]);
    if (len > EPS) elements.push({ kind: 'line', start: cursor, end: to, ch0: ch, length: len });
    ch += len;
    cursor = to;
  };
  for (const { i, defl, r } of raw) {
    const ip = pts[i]!;
    if (r === 0) {
      line(ip);
      continue;
    }
    const u1 = legs[i - 1]!.u;
    const u2 = legs[i]!.u;
    const t = tangents[i]!;
    const left = defl > 0;
    const tc: GridXY = [ip[0] - u1[0] * t, ip[1] - u1[1] * t];
    const ct: GridXY = [ip[0] + u2[0] * t, ip[1] + u2[1] * t];
    const nrm: GridXY = left ? [-u1[1], u1[0]] : [u1[1], -u1[0]];
    const centre: GridXY = [tc[0] + nrm[0] * r, tc[1] + nrm[1] * r];
    line(tc);
    const arc = r * Math.abs(defl);
    curves.push({
      ref: ipRef(ips, i),
      ipIndex: i,
      radius: r,
      deflectionDeg: (Math.abs(defl) * 180) / Math.PI,
      left,
      tangent: t,
      arcLength: arc,
      external: r * (1 / Math.cos(Math.abs(defl) / 2) - 1),
      tc,
      ct,
      centre,
      tcCh: ch,
      ctCh: ch + arc,
      fits: !bad.has(i),
    });
    elements.push({ kind: 'arc', start: tc, end: ct, centre, radius: r, left, ch0: ch, length: arc });
    ch += arc;
    cursor = ct;
  }
  line(pts[pts.length - 1]!);
  return { startCh, length: ch - startCh, curves, elements, overlaps, fits: overlaps.length === 0 };
}

function onElement(el: AlignElement, s: number, offset: number): { p: GridXY; az: number } {
  if (el.kind === 'line') {
    const { u } = unit(el.start, el.end);
    // Right of travel (ux, uy) is (uy, -ux).
    return {
      p: [el.start[0] + u[0] * s + u[1] * offset, el.start[1] + u[1] * s - u[0] * offset],
      az: azimuthOf(el.start, el.end),
    };
  }
  const a0 = Math.atan2(el.start[1] - el.centre[1], el.start[0] - el.centre[0]);
  const a = a0 + (el.left ? s / el.radius : -s / el.radius);
  const rr = el.left ? el.radius + offset : el.radius - offset;
  const p: GridXY = [el.centre[0] + rr * Math.cos(a), el.centre[1] + rr * Math.sin(a)];
  // Tangent of travel: radius direction turned 90 deg towards the travel sense.
  const tx = el.left ? -Math.sin(a) : Math.sin(a);
  const ty = el.left ? Math.cos(a) : -Math.cos(a);
  return { p, az: azimuthOf([0, 0], [tx, ty]) };
}

/** Grid point and travel azimuth at chainage `ch`, `offset` right positive; null off the alignment. */
export function pointAt(design: AlignmentDesign, ch: number, offset = 0): { p: GridXY; az: number } | null {
  const s = ch - design.startCh;
  if (!design.elements.length || s < -1e-6 || s > design.length + 1e-6) return null;
  for (let i = 0; i < design.elements.length; i++) {
    const el = design.elements[i]!;
    const last = i === design.elements.length - 1;
    const local = ch - el.ch0;
    if (local <= el.length + 1e-6 || last) return onElement(el, Math.min(Math.max(local, 0), el.length), offset);
  }
  return null;
}

/** Densified centreline for drawing; arcs get a vertex every `step` metres (at least 8 per arc). */
export function centreline(design: AlignmentDesign, step = 2): GridXY[] {
  const out: GridXY[] = [];
  for (const el of design.elements) {
    if (!out.length) out.push(el.start);
    if (el.kind === 'line') {
      out.push(el.end);
      continue;
    }
    const n = Math.max(8, Math.ceil(el.length / step));
    for (let k = 1; k <= n; k++) out.push(onElement(el, (el.length * k) / n, 0).p);
  }
  return out;
}

export interface Tick {
  ch: number;
  p: GridXY;
  az: number;
  labelled: boolean;
}

/** Ticks on round multiples of `interval`; labelled where a multiple of `labelEvery` falls. */
export function chainageTicks(design: AlignmentDesign, interval = 20, labelEvery = 100): Tick[] {
  if (!(interval > 0) || !(labelEvery > 0) || !design.elements.length) return [];
  const end = design.startCh + design.length;
  const out: Tick[] = [];
  for (let k = Math.ceil(design.startCh / interval - 1e-9); k * interval <= end + 1e-9; k++) {
    const ch = Number((k * interval).toFixed(6));
    const at = pointAt(design, Math.min(ch, end));
    if (!at) continue;
    const q = ch / labelEvery;
    out.push({ ch, p: at.p, az: at.az, labelled: Math.abs(q - Math.round(q)) < 1e-9 });
  }
  return out;
}

/** A short tick across the line at `p`, `half` metres each side. */
export function tickSegment(t: Tick, half: number): [GridXY, GridXY] {
  const r = (t.az * Math.PI) / 180;
  const rx = Math.cos(r);
  const ry = -Math.sin(r);
  return [
    [t.p[0] - rx * half, t.p[1] - ry * half],
    [t.p[0] + rx * half, t.p[1] + ry * half],
  ];
}

/** Chainage and right-positive offset of a point: the element with the smallest |offset| wins. */
export function stationOffset(design: AlignmentDesign, p: GridXY): { ch: number; offset: number } | null {
  let best: { ch: number; offset: number } | null = null;
  for (const el of design.elements) {
    let hit: { s: number; off: number } | null = null;
    if (el.kind === 'line') {
      const { u, len } = unit(el.start, el.end);
      const px = p[0] - el.start[0];
      const py = p[1] - el.start[1];
      const s = px * u[0] + py * u[1];
      if (s >= -1e-6 && s <= len + 1e-6) hit = { s, off: px * u[1] - py * u[0] };
    } else {
      const a0 = Math.atan2(el.start[1] - el.centre[1], el.start[0] - el.centre[0]);
      const a = Math.atan2(p[1] - el.centre[1], p[0] - el.centre[0]);
      const tau = 2 * Math.PI;
      const swept = ((((el.left ? a - a0 : a0 - a) % tau) + tau) % tau);
      const s = swept * el.radius;
      const d = Math.hypot(p[0] - el.centre[0], p[1] - el.centre[1]);
      if (s <= el.length + 1e-6) hit = { s, off: el.left ? d - el.radius : el.radius - d };
    }
    if (hit && (!best || Math.abs(hit.off) < Math.abs(best.offset))) best = { ch: el.ch0 + hit.s, offset: hit.off };
  }
  return best;
}

/** The stored alignment JSON (setting_out) back to IPs; null when it was not drawn by IP. */
export function ipsFromStored(data: unknown): { ips: IpInput[]; startCh: number; speed: number | null; name: string } | null {
  if (!data || typeof data !== 'object') return null;
  const d = data as { ips?: unknown; start_chainage?: unknown; design_speed_kmh?: unknown; name?: unknown };
  if (!Array.isArray(d.ips) || d.ips.length < 2) return null;
  const ips = d.ips
    .map((p) => p as { e?: unknown; n?: unknown; radius?: unknown; name?: unknown })
    .filter((p) => typeof p.e === 'number' && typeof p.n === 'number')
    .map((p) => ({ e: p.e as number, n: p.n as number, radius: typeof p.radius === 'number' ? p.radius : 0, name: typeof p.name === 'string' ? p.name : '' }));
  return {
    ips,
    startCh: typeof d.start_chainage === 'number' ? d.start_chainage : 0,
    speed: typeof d.design_speed_kmh === 'number' ? d.design_speed_kmh : null,
    name: typeof d.name === 'string' ? d.name : '',
  };
}
