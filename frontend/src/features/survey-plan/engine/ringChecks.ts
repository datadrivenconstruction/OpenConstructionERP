// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Parcel and pad checks that run on every edit. They mirror the server rules
 * of the same id (land_parcels/geometry.py and validators.py, surfaces_volumes
 * pad_validators.py) so the editor flags a problem before Save; the server
 * result on save remains the record.
 */

import type { GridXY, GridXYZ, PlanFeature } from '../types';
import type { LiveCheck, LiveFinding } from './liveChecks';

const EPS = 1e-6;
/** Overlaps smaller than this are rounding, not a claim on the same ground (server MIN_OVERLAP_M2). */
export const MIN_OVERLAP_M2 = 0.01;

type Pt = [number, number];

function openRing(ring: readonly GridXYZ[]): Pt[] {
  const pts: Pt[] = ring.map((p) => [p[0], p[1]]);
  if (pts.length > 1) {
    const a = pts[0]!;
    const b = pts[pts.length - 1]!;
    if (Math.abs(a[0] - b[0]) < 1e-4 && Math.abs(a[1] - b[1]) < 1e-4) pts.pop();
  }
  return pts;
}

/** Shift to the first vertex so projected coordinates keep their precision. */
function local(ring: readonly GridXYZ[], origin: Pt): Pt[] {
  return openRing(ring).map(([x, y]) => [x - origin[0], y - origin[1]]);
}

function signed(r: readonly Pt[]): number {
  let s = 0;
  for (let i = 0; i < r.length; i++) {
    const a = r[i]!;
    const b = r[(i + 1) % r.length]!;
    s += a[0] * b[1] - b[0] * a[1];
  }
  return s / 2;
}

const cross = (o: Pt, a: Pt, b: Pt) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);

function onSegment(a: Pt, b: Pt, p: Pt): boolean {
  return (
    Math.min(a[0], b[0]) - EPS <= p[0] && p[0] <= Math.max(a[0], b[0]) + EPS &&
    Math.min(a[1], b[1]) - EPS <= p[1] && p[1] <= Math.max(a[1], b[1]) + EPS
  );
}

function segmentsTouch(p: Pt, q: Pt, r: Pt, s: Pt): boolean {
  const d1 = cross(r, s, p), d2 = cross(r, s, q), d3 = cross(p, q, r), d4 = cross(p, q, s);
  if (((d1 > EPS && d2 < -EPS) || (d1 < -EPS && d2 > EPS)) && ((d3 > EPS && d4 < -EPS) || (d3 < -EPS && d4 > EPS))) return true;
  return (
    (Math.abs(d1) <= EPS && onSegment(r, s, p)) || (Math.abs(d2) <= EPS && onSegment(r, s, q)) ||
    (Math.abs(d3) <= EPS && onSegment(p, q, r)) || (Math.abs(d4) <= EPS && onSegment(p, q, s))
  );
}

/** Index pairs of non-adjacent edges that touch or cross, plus zero-length edges (PAR-002). */
export function selfIntersections(ring: readonly GridXYZ[]): Array<[number, number]> {
  if (!ring.length) return [];
  const pts = local(ring, [ring[0]![0], ring[0]![1]]);
  const n = pts.length;
  const out: Array<[number, number]> = [];
  for (let i = 0; i < n; i++) {
    const a = pts[i]!, b = pts[(i + 1) % n]!;
    if (Math.hypot(a[0] - b[0], a[1] - b[1]) <= EPS) out.push([i, i]);
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 2; j < n; j++) {
      if (i === 0 && j === n - 1) continue;
      if (segmentsTouch(pts[i]!, pts[(i + 1) % n]!, pts[j]!, pts[(j + 1) % n]!)) out.push([i, j]);
    }
  }
  return out;
}

export function ringValid(ring: readonly GridXYZ[]): boolean {
  return openRing(ring).length >= 3 && selfIntersections(ring).length === 0;
}

function params(p: Pt, q: Pt, r: Pt, s: Pt): number[] {
  const dx = q[0] - p[0], dy = q[1] - p[1], ex = s[0] - r[0], ey = s[1] - r[1];
  const den = dx * ey - dy * ex;
  const len2 = dx * dx + dy * dy;
  if (len2 <= 0) return [];
  if (Math.abs(den) <= EPS * Math.sqrt(len2 * (ex * ex + ey * ey) || 1)) {
    if (Math.abs(cross(p, q, r)) > EPS * Math.sqrt(len2)) return [];
    const out: number[] = [];
    for (const pt of [r, s]) {
      const t = ((pt[0] - p[0]) * dx + (pt[1] - p[1]) * dy) / len2;
      if (t >= -EPS && t <= 1 + EPS) out.push(Math.min(1, Math.max(0, t)));
    }
    return out;
  }
  const t = ((r[0] - p[0]) * ey - (r[1] - p[1]) * ex) / den;
  const u = ((r[0] - p[0]) * dy - (r[1] - p[1]) * dx) / den;
  return t >= -EPS && t <= 1 + EPS && u >= -EPS && u <= 1 + EPS ? [Math.min(1, Math.max(0, t))] : [];
}

function pointSegDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const len2 = dx * dx + dy * dy;
  const t = len2 === 0 ? 0 : Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / len2));
  return Math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy));
}

function inside(p: Pt, ring: readonly Pt[]): boolean {
  let hit = false;
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    if (a[1] > p[1] !== b[1] > p[1] && p[0] < a[0] + ((p[1] - a[1]) * (b[0] - a[0])) / (b[1] - a[1])) hit = !hit;
  }
  return hit;
}

function classify(p: Pt, dir: Pt, ring: readonly Pt[]): 'inside' | 'outside' | 'same' | 'opposite' {
  for (let i = 0; i < ring.length; i++) {
    const a = ring[i]!, b = ring[(i + 1) % ring.length]!;
    if (pointSegDist(p, a, b) <= EPS * 10) return dir[0] * (b[0] - a[0]) + dir[1] * (b[1] - a[1]) > 0 ? 'same' : 'opposite';
  }
  return inside(p, ring) ? 'inside' : 'outside';
}

function boundaryInside(a: readonly Pt[], b: readonly Pt[], keepSame: boolean): number {
  let total = 0;
  for (let i = 0; i < a.length; i++) {
    const p = a[i]!, q = a[(i + 1) % a.length]!;
    const ts = new Set<number>([0, 1]);
    for (let j = 0; j < b.length; j++) for (const t of params(p, q, b[j]!, b[(j + 1) % b.length]!)) ts.add(t);
    const cuts = [...ts].sort((x, y) => x - y);
    for (let k = 0; k + 1 < cuts.length; k++) {
      const t0 = cuts[k]!, t1 = cuts[k + 1]!;
      if (t1 - t0 <= 1e-12) continue;
      const s: Pt = [p[0] + (q[0] - p[0]) * t0, p[1] + (q[1] - p[1]) * t0];
      const e: Pt = [p[0] + (q[0] - p[0]) * t1, p[1] + (q[1] - p[1]) * t1];
      const where = classify([(s[0] + e[0]) / 2, (s[1] + e[1]) / 2], [q[0] - p[0], q[1] - p[1]], b);
      if (where === 'inside' || (keepSame && where === 'same')) total += (s[0] * e[1] - e[0] * s[1]) / 2;
    }
  }
  return total;
}

function bbox(r: readonly GridXYZ[]): [number, number, number, number] {
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  for (const p of r) {
    x0 = Math.min(x0, p[0]); y0 = Math.min(y0, p[1]); x1 = Math.max(x1, p[0]); y1 = Math.max(y1, p[1]);
  }
  return [x0, y0, x1, y1];
}

export function bboxesApart(a: readonly GridXYZ[], b: readonly GridXYZ[], margin = 0): boolean {
  const [ax0, ay0, ax1, ay1] = bbox(a);
  const [bx0, by0, bx1, by1] = bbox(b);
  return ax1 + margin < bx0 || bx1 + margin < ax0 || ay1 + margin < by0 || by1 + margin < ay0;
}

/** Area shared by two simple polygons; 0 for neighbours that only touch. */
export function intersectionArea(a: readonly GridXYZ[], b: readonly GridXYZ[]): number {
  if (openRing(a).length < 3 || openRing(b).length < 3 || bboxesApart(a, b)) return 0;
  const origin: Pt = [a[0]![0], a[0]![1]];
  const ccw = (r: Pt[]) => (signed(r) >= 0 ? r : [...r].reverse());
  const ra = ccw(local(a, origin)), rb = ccw(local(b, origin));
  const area = boundaryInside(ra, rb, true) + boundaryInside(rb, ra, false);
  return area > 1e-9 ? Math.max(0, area) : 0;
}

/** Shortest distance between two boundaries; 0 when they touch or cross. */
export function boundaryGap(a: readonly GridXYZ[], b: readonly GridXYZ[]): number {
  const origin: Pt = [a[0]![0], a[0]![1]];
  const ra = local(a, origin), rb = local(b, origin);
  let best = Infinity;
  for (let i = 0; i < ra.length; i++) {
    const p = ra[i]!, q = ra[(i + 1) % ra.length]!;
    for (let j = 0; j < rb.length; j++) {
      const r = rb[j]!, s = rb[(j + 1) % rb.length]!;
      if (segmentsTouch(p, q, r, s)) return 0;
      best = Math.min(best, pointSegDist(p, r, s), pointSegDist(q, r, s), pointSegDist(r, p, q), pointSegDist(s, p, q));
    }
  }
  return best <= EPS ? 0 : best;
}

export function ringAreaM2(ring: readonly GridXYZ[]): number {
  if (!ring.length) return 0;
  return Math.abs(signed(local(ring, [ring[0]![0], ring[0]![1]])));
}

// ── Parcel checks ─────────────────────────────────────────────────────────

/** What the parcel checks read from the project and its country profile. */
export interface ParcelCheckSettings {
  /** PAR-005: boundaries closer than this without touching are a sliver gap; 0 switches it off. */
  gapToleranceM: number;
  /** PAR-001: allowed |computed - legal| in m² for a parcel, or null when nothing is set. */
  areaTolerance: (legalM2: number) => number | null;
  /** PAR-006: the pack's parcel id pattern; '' means no format (neutral). */
  idPattern: string;
}

const outerRing = (f: PlanFeature): GridXYZ[] => (f.geometry.type === 'Polygon' ? f.geometry.coordinates[0] ?? [] : []);
const centre = (ring: readonly GridXYZ[]): GridXY => {
  const [x0, y0, x1, y1] = bbox(ring);
  return [(x0 + x1) / 2, (y0 + y1) / 2];
};
const refOf = (f: PlanFeature) => String(f.properties.ref ?? f.properties.label ?? f.id);
const fmt2 = (v: number) => v.toFixed(2);

/** PAR-001, 002, 004, 005, 006 over the features of the `parcels` layer. */
export function parcelFindings(features: readonly PlanFeature[], s: ParcelCheckSettings): LiveFinding[] {
  const parcels = features.filter((f) => f.layer === 'parcels' && f.geometry.type === 'Polygon');
  const out: LiveFinding[] = [];
  const valid: PlanFeature[] = [];
  let idRe: RegExp | null = null;
  try {
    idRe = s.idPattern ? new RegExp(`^(?:${s.idPattern})$`) : null;
  } catch {
    idRe = null;
  }
  for (const f of parcels) {
    const ring = outerRing(f);
    const crossings = selfIntersections(ring);
    if (openRing(ring).length < 3 || crossings.length) {
      out.push({ ruleId: 'PAR-002', severity: 'error', featureId: f.id, at: ring.length ? centre(ring) : undefined,
        messageKey: 'plan.parcel.check.ring_invalid', defaultMessage: 'Parcel {{id}}: the boundary is not one closed ring that does not cross itself', params: { id: refOf(f) } });
      continue;
    }
    valid.push(f);
    const legal = Number(f.properties.legal_area);
    if (f.properties.legal_area != null && f.properties.legal_area !== '' && Number.isFinite(legal)) {
      const tol = s.areaTolerance(legal);
      const area = ringAreaM2(ring);
      if (tol != null && Math.abs(area - legal) > tol) {
        out.push({ ruleId: 'PAR-001', severity: 'warning', featureId: f.id, at: centre(ring),
          messageKey: 'plan.parcel.check.area_mismatch', defaultMessage: 'Parcel {{id}}: {{a}} m² from coordinates against {{l}} m² registered (tolerance {{t}} m²)',
          params: { id: refOf(f), a: fmt2(area), l: fmt2(legal), t: fmt2(tol) } });
      }
    }
    if (idRe && !idRe.test(refOf(f))) {
      out.push({ ruleId: 'PAR-006', severity: 'warning', featureId: f.id, at: centre(ring),
        messageKey: 'plan.parcel.check.id_format', defaultMessage: 'Parcel {{id}}: the id does not follow the register format', params: { id: refOf(f) } });
    }
  }
  for (let i = 0; i < valid.length; i++) {
    for (let j = i + 1; j < valid.length; j++) {
      const a = valid[i]!, b = valid[j]!;
      const ra = outerRing(a), rb = outerRing(b);
      if (bboxesApart(ra, rb, Math.max(s.gapToleranceM, 0))) continue;
      const shared = intersectionArea(ra, rb);
      if (shared >= MIN_OVERLAP_M2) {
        out.push({ ruleId: 'PAR-004', severity: 'error', featureId: a.id, at: centre(ra),
          messageKey: 'plan.parcel.check.overlap', defaultMessage: 'Parcels {{a}} and {{b}} overlap by {{area}} m²',
          params: { a: refOf(a), b: refOf(b), area: fmt2(shared) } });
        continue;
      }
      if (s.gapToleranceM > 0) {
        const gap = boundaryGap(ra, rb);
        if (gap > 0 && gap <= s.gapToleranceM) {
          out.push({ ruleId: 'PAR-005', severity: 'warning', featureId: a.id, at: centre(ra),
            messageKey: 'plan.parcel.check.gap', defaultMessage: 'Parcels {{a}} and {{b}} leave a {{gap}} m gap',
            params: { a: refOf(a), b: refOf(b), gap: gap.toFixed(3) } });
        }
      }
    }
  }
  return out;
}

/** PAR-003: a work zone over land the project does not hold yet. */
export function zoneFindings(features: readonly PlanFeature[]): LiveFinding[] {
  const zones = features.filter((f) => f.layer === 'zones' && openRing(outerRing(f)).length >= 3);
  const out: LiveFinding[] = [];
  for (const p of features) {
    if (p.layer !== 'parcels' || p.properties.status === 'acquired') continue;
    const ring = outerRing(p);
    if (!ringValid(ring)) continue;
    const overlap = zones.reduce((sum, z) => sum + intersectionArea(outerRing(z), ring), 0);
    if (overlap >= MIN_OVERLAP_M2) {
      out.push({ ruleId: 'PAR-003', severity: 'warning', featureId: p.id, at: centre(ring),
        messageKey: 'plan.parcel.check.zone_not_acquired', defaultMessage: 'The work zone takes {{area}} m² of parcel {{id}}, which is not acquired',
        params: { id: refOf(p), area: fmt2(overlap) } });
    }
  }
  return out;
}

/** SRV-083: a pad outline is closed, simple and has a design level. */
export function padFindings(features: readonly PlanFeature[]): LiveFinding[] {
  const out: LiveFinding[] = [];
  for (const f of features) {
    if (f.layer !== 'pads' || f.geometry.type !== 'Polygon') continue;
    const ring = outerRing(f);
    const name = String(f.properties.name ?? f.properties.label ?? '');
    if (openRing(ring).length < 3) {
      out.push({ ruleId: 'SRV-083', severity: 'error', featureId: f.id, messageKey: 'plan.tin.check.pad_ring_open', defaultMessage: 'Pad {{name}}: the outline needs at least three points', params: { name } });
      continue;
    }
    const crossings = selfIntersections(ring).filter(([i, j]) => i !== j).length;
    if (crossings) {
      out.push({ ruleId: 'SRV-083', severity: 'error', featureId: f.id, at: centre(ring), messageKey: 'plan.tin.check.pad_self_intersects', defaultMessage: 'Pad {{name}}: the outline crosses itself {{n}} times', params: { name, n: crossings } });
    }
    const level = f.properties.level;
    if (level == null || level === '' || !Number.isFinite(Number(level))) {
      out.push({ ruleId: 'SRV-083', severity: 'error', featureId: f.id, at: centre(ring), messageKey: 'plan.tin.check.pad_no_level', defaultMessage: 'Pad {{name}}: set the design level', params: { name } });
    }
  }
  return out;
}

/** Live check factories; the parcel screen registers them with its settings. */
export function parcelLiveCheck(settings: () => ParcelCheckSettings): LiveCheck {
  return ({ features }) => [...parcelFindings(features, settings()), ...zoneFindings(features)];
}
export const padLiveCheck: LiveCheck = ({ features }) => padFindings(features);
