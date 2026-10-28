// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Measurement utilities for DWG takeoff annotations.
 */

import { isMetricUnit, toDisplayQuantity } from '@/shared/lib/unitConversion';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { fmtFixed, fmtPrecision } from '@/shared/lib/formatters';
import { formatFeetInches } from '@/modules/pdf-takeoff/data/scale-helpers';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/** Euclidean distance between two points. */
export function calculateDistance(
  p1: { x: number; y: number },
  p2: { x: number; y: number },
): number {
  const dx = p2.x - p1.x;
  const dy = p2.y - p1.y;
  return Math.sqrt(dx * dx + dy * dy);
}

/** Convert a DXF $INSUNITS label to a "native unit → metres" factor.
 *
 *  Most architectural DWGs are authored in millimetres even though the
 *  page is read at 1:100/1:50. Without this factor a 12 000-mm wall on
 *  an unscaled drawing reads as "12 000 m" - which is what the user
 *  was seeing. Falls back to 1.0 for "unitless" / missing, which keeps
 *  the historical "DXF units are metres" assumption intact for files
 *  that genuinely have no header. */
export function unitFactorToMetres(units?: string | null): number {
  switch ((units ?? '').toLowerCase()) {
    case 'mm':
      return 0.001;
    case 'cm':
      return 0.01;
    case 'm':
      return 1;
    case 'km':
      return 1000;
    case 'inches':
    case 'in':
      return 0.0254;
    case 'feet':
    case 'ft':
      return 0.3048;
    case 'miles':
      return 1609.344;
    default:
      return 1;
  }
}

/** Area of a polygon defined by ordered vertices (Shoelace formula).
 *
 *  Returns the absolute shoelace magnitude. NOTE: for a *non-simple*
 *  (self-intersecting) polygon the shoelace sum cancels - a perfect
 *  "bowtie" returns 0 even though it covers real area. Callers that
 *  feed a quantity to the user / BOQ should use {@link calculateAreaSafe}
 *  so the degeneracy is surfaced instead of silently understated
 *  (D-TKC-015). This raw form is kept for label-placement / sorting /
 *  hit-test callers that only need a fast number. */
export function calculateArea(points: { x: number; y: number }[]): number {
  if (points.length < 3) return 0;
  let area = 0;
  const n = points.length;
  for (let i = 0; i < n; i++) {
    const j = (i + 1) % n;
    const pi = points[i]!;
    const pj = points[j]!;
    area += pi.x * pj.y;
    area -= pj.x * pi.y;
  }
  return Math.abs(area) / 2;
}

type Pt2 = { x: number; y: number };
type Seg = [Pt2, Pt2];

/** Orientation sign of the ordered triplet (p, q, r). */
function orient(p: Pt2, q: Pt2, r: Pt2): number {
  const v = (q.y - p.y) * (r.x - q.x) - (q.x - p.x) * (r.y - q.y);
  if (v > 1e-12) return 1;
  if (v < -1e-12) return -1;
  return 0;
}

function onSeg(p: Pt2, q: Pt2, r: Pt2): boolean {
  return (
    Math.min(p.x, r.x) - 1e-9 <= q.x &&
    q.x <= Math.max(p.x, r.x) + 1e-9 &&
    Math.min(p.y, r.y) - 1e-9 <= q.y &&
    q.y <= Math.max(p.y, r.y) + 1e-9
  );
}

/** Proper segment-segment intersection test (shared endpoints excluded
 *  - adjacent polygon edges legitimately touch at a vertex). */
function segmentsIntersect(a: Seg, b: Seg): boolean {
  const [p1, p2] = a;
  const [p3, p4] = b;
  const o1 = orient(p1, p2, p3);
  const o2 = orient(p1, p2, p4);
  const o3 = orient(p3, p4, p1);
  const o4 = orient(p3, p4, p2);
  if (o1 !== o2 && o3 !== o4) return true;
  if (o1 === 0 && onSeg(p1, p3, p2)) return true;
  if (o2 === 0 && onSeg(p1, p4, p2)) return true;
  if (o3 === 0 && onSeg(p3, p1, p4)) return true;
  if (o4 === 0 && onSeg(p3, p2, p4)) return true;
  return false;
}

/** `true` when the closed polygon described by `points` has at least
 *  one pair of non-adjacent edges that cross (a non-simple polygon). */
export function isSelfIntersecting(points: Pt2[]): boolean {
  const n = points.length;
  if (n < 4) return false; // a triangle cannot self-intersect
  const edges: Seg[] = [];
  for (let i = 0; i < n; i++) {
    edges.push([points[i]!, points[(i + 1) % n]!]);
  }
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      // Skip adjacent edges (share a vertex) and the wrap-around pair.
      if (j === i || j === i + 1 || (i === 0 && j === n - 1)) continue;
      if (segmentsIntersect(edges[i]!, edges[j]!)) return true;
    }
  }
  return false;
}

/** Reason a polygon area could not be trusted, or `null` when fine. */
export type AreaDegeneracy = 'too_few_points' | 'self_intersecting' | 'zero' | null;

/**
 * Area of a polygon plus a degeneracy verdict.
 *
 * Use this anywhere the area becomes a number the estimator reads or a
 * BOQ quantity. A self-intersecting "bowtie" trace, fewer than 3
 * vertices, or a collapsed (zero) polygon are reported instead of being
 * silently rounded to a wrong/zero figure (D-TKC-015). The UI shows a
 * warning and lets the user fix the trace rather than booking a wrong
 * quantity.
 */
export function calculateAreaSafe(points: Pt2[]): {
  area: number;
  degenerate: AreaDegeneracy;
} {
  if (points.length < 3) return { area: 0, degenerate: 'too_few_points' };
  if (isSelfIntersecting(points)) {
    return { area: calculateArea(points), degenerate: 'self_intersecting' };
  }
  const area = calculateArea(points);
  if (area <= 1e-9) return { area, degenerate: 'zero' };
  return { area, degenerate: null };
}

/** A unit is "composite" (area / volume) when it carries a superscript
 *  exponent (m², m³). A linear k/m SI prefix is invalid on these:
 *  1 km² = 1e6 m², not 1e3 - so `1500 m²` must NOT render `1.50 km²`
 *  (off by 1e6). Detect and never prefix-scale them (D-TKC-006). */
function isCompositeUnit(unit: string): boolean {
  return unit.includes('²') || unit.includes('³'); // ² or ³
}

/** Format a measurement value with a unit label.
 *
 *  Linear (length) units get the usual k/m SI prefixes for readability.
 *  Area/volume units are *never* prefix-scaled - the prefix maths is
 *  non-linear for them and produced physically wrong labels
 *  (`1500 m²` → `1.50 km²`). Composite units are shown with adaptive
 *  fixed precision instead so a large slab area or a tiny patch both
 *  stay correct and legible.
 *
 *  Measurement-system aware: the incoming ``value``/``unit`` are always the
 *  metric-canonical pair the DWG layer stores (m / m² / m³). When the user's
 *  preference is "imperial" they are converted at this DISPLAY boundary
 *  (m -> ft, m² -> ft², m³ -> ft³) before the precision/prefix rules run, and a
 *  LINEAR length is then written in the architectural feet-and-inches notation
 *  (12'-6 3/4") that an American estimator reads off a drawing rather than as
 *  decimal feet;
 *  for "metric" the pair passes through unchanged so output is byte-identical
 *  to before. Storage / on-canvas geometry are never touched - only the
 *  formatted string. Reads the preference via ``getState()`` (not a param)
 *  because most callers are deep inside the canvas render loop where a React
 *  hook cannot run, and threading a flag through every renderer would be
 *  invasive; the canvas re-renders with the new label on the next frame. */
export function formatMeasurement(value: number, unit: string): string {
  if (!Number.isFinite(value)) return `0 ${unit}`;
  // Convert the metric-canonical input to the display system. Metric is a
  // pass-through (value unchanged, label normalised); imperial scales + relabels.
  const system = usePreferencesStore.getState().measurementSystem;
  // Hold on to the metres before the line below reassigns `value` to decimal
  // feet. formatFeetInches converts in integer sixteenths, and handing it an
  // already-converted value would convert twice and reintroduce exactly the
  // float rounding the integer path exists to avoid. Only a genuinely
  // metric-canonical input qualifies: the docstring promises metres, but
  // AnnotationOverlay calls this with `ann.measurement_unit ?? fallbackUnit`,
  // which is whatever the wire sent, and a value already in feet must never be
  // read as metres.
  const metres = unit === 'm' ? value : null;
  ({ value, unit } = toDisplayQuantity(value, unit, system));
  if (metres !== null && unit === 'ft') {
    // A linear dimension in imperial is written the way it is written on a
    // drawing: 12'-6 3/4", not 41.01 ft. Area and volume are not, so they fall
    // through - nobody dimensions a slab as four hundred square feet and three
    // quarters. An empty string means degenerate or below 1/16", where this
    // notation has nothing to say; falling through then keeps the historic
    // "0.00 ft" rather than leaving the annotation with no dimension text.
    const feetInches = formatFeetInches(metres);
    if (feetInches) return feetInches;
  }
  if (isCompositeUnit(unit)) {
    const abs = Math.abs(value);
    if (abs !== 0 && abs < 0.01) return `${fmtPrecision(value, 2)} ${unit}`;
    if (abs < 1) return `${fmtFixed(value, 4)} ${unit}`;
    if (abs < 1000) return `${fmtFixed(value, 2)} ${unit}`;
    // Group thousands instead of a bogus k-prefix.
    return `${value.toLocaleString(getNumberLocale(), { maximumFractionDigits: 1 })} ${unit}`;
  }
  // SI prefixes belong to SI units. Gluing k/m onto a converted imperial label
  // coins units that do not exist: an imperial reader was getting "0.00 mft"
  // (millifeet) for a sub-centimetre length and "1.23 kft" for a long one.
  // `isMetricUnit` answers false only for a known imperial unit, so unknown
  // pass-through units (pcs, hr, %) keep the prefixing they have always had in
  // both systems and the metric path stays byte-identical.
  const siPrefixable = isMetricUnit(unit) !== false;
  if (siPrefixable && value >= 1000) {
    return `${fmtFixed(value / 1000, 2)} k${unit}`;
  }
  if (siPrefixable && value !== 0 && Math.abs(value) < 0.01) {
    return `${fmtFixed(value * 1000, 2)} m${unit}`;
  }
  return `${fmtFixed(value, 2)} ${unit}`;
}

/* ── Polyline-specific measurements ──────────────────────────────── */

type Pt = { x: number; y: number };

/** Lengths of each segment in a polyline. */
export function getSegmentLengths(vertices: Pt[], closed = false): number[] {
  const lengths: number[] = [];
  for (let i = 0; i < vertices.length - 1; i++) {
    lengths.push(calculateDistance(vertices[i]!, vertices[i + 1]!));
  }
  if (closed && vertices.length >= 3) {
    lengths.push(calculateDistance(vertices[vertices.length - 1]!, vertices[0]!));
  }
  return lengths;
}

/** Total perimeter (sum of segment lengths). */
export function calculatePerimeter(vertices: Pt[], closed = false): number {
  return getSegmentLengths(vertices, closed).reduce((a, b) => a + b, 0);
}

/** Midpoint of a segment (for label placement). */
export function segmentMidpoint(a: Pt, b: Pt): Pt {
  return { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
}

/** Minimum distance from a point to a line segment AB. */
export function pointToSegmentDistance(p: Pt, a: Pt, b: Pt): number {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const lenSq = dx * dx + dy * dy;
  if (lenSq === 0) return calculateDistance(p, a); // degenerate segment
  let t = ((p.x - a.x) * dx + (p.y - a.y) * dy) / lenSq;
  t = Math.max(0, Math.min(1, t));
  const proj = { x: a.x + t * dx, y: a.y + t * dy };
  return calculateDistance(p, proj);
}

/** Centroid of a polygon (for area label placement). */
export function polygonCentroid(vertices: Pt[]): Pt {
  let cx = 0, cy = 0;
  for (const v of vertices) { cx += v.x; cy += v.y; }
  return { x: cx / vertices.length, y: cy / vertices.length };
}

/** Ray-casting point-in-polygon test for closed polylines. */
export function pointInPolygon(p: Pt, vertices: Pt[]): boolean {
  let inside = false;
  const n = vertices.length;
  for (let i = 0, j = n - 1; i < n; j = i++) {
    const vi = vertices[i]!;
    const vj = vertices[j]!;
    if (
      (vi.y > p.y) !== (vj.y > p.y) &&
      p.x < ((vj.x - vi.x) * (p.y - vi.y)) / (vj.y - vi.y) + vi.x
    ) {
      inside = !inside;
    }
  }
  return inside;
}
