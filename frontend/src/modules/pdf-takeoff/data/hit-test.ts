/**
 * In-canvas measurement editing geometry (issue #194 Feature 1).
 *
 * Pure, dependency-free hit-testing + live-recompute helpers for the PDF
 * takeoff viewer. Everything here operates in PDF user units (the same
 * space stored measurement points live in): the viewer inverts a pointer
 * to PDF units with `(clientX - rect.left) / zoom` and never divides by
 * `dpr`, so a screen-constant grab radius is just `GRAB_PX / zoom`.
 *
 * Geometry is shared with the rest of the takeoff stack rather than
 * re-derived: the segment / polygon / self-intersection primitives come
 * from `features/dwg-takeoff/lib/measurement.ts`, and the scale-aware
 * real-world conversions from `data/scale-helpers.ts`. That keeps
 * create-time math (in `TakeoffViewerModule`) and reshape-time math
 * (here) from drifting, which matters because the label strings this
 * module emits are read back by the ledger / CSV / Excel export.
 */

import {
  pointInPolygon,
  pointToSegmentDistance,
  isSelfIntersecting,
} from '@/features/dwg-takeoff/lib/measurement';
import {
  pixelDistance,
  toRealDistance,
  toRealArea,
  polygonAreaPixels,
  polygonPerimeterPixels,
  formatMeasurement,
  type ScaleConfig,
} from './scale-helpers';

export interface Point {
  x: number;
  y: number;
}

/** Measurement types the editor understands. Mirrors the viewer's union
 *  without importing the (heavy) module so this stays pure + testable. */
export type EditableMeasurementType =
  | 'distance'
  | 'polyline'
  | 'area'
  | 'volume'
  | 'count'
  | 'cloud'
  | 'arrow'
  | 'text'
  | 'rectangle'
  | 'highlight';

/** Minimal measurement shape the geometry helpers need. The viewer's
 *  full `Measurement` is structurally assignable to this. */
export interface EditableMeasurement {
  type: EditableMeasurementType;
  points: Point[];
  depth?: number;
  unit?: string;
}

/* ── Tolerances (screen pixels; divide by zoom for PDF-unit space) ───── */

/** Grab radius for an edge / midpoint / interior body, in screen pixels. */
export const GRAB_PX = 8;
/** Grab radius for a vertex handle, in screen pixels (slightly larger so a
 *  vertex always wins over the edge it sits on). */
export const VERTEX_GRAB_PX = 10;

/* ── Per-type capability matrix ──────────────────────────────────────── */

/** Closed polygon types (the wrap edge participates in hit-testing). */
const CLOSED_TYPES: ReadonlySet<EditableMeasurementType> = new Set([
  'area',
  'volume',
  'cloud',
]);

/** Open multi-segment types. */
const OPEN_LINE_TYPES: ReadonlySet<EditableMeasurementType> = new Set([
  'distance',
  'polyline',
  'arrow',
]);

/** Whether a measurement type supports adding / removing vertices. */
export function supportsVariableVertices(type: EditableMeasurementType): boolean {
  return type === 'polyline' || type === 'area' || type === 'volume' || type === 'cloud';
}

/** Minimum vertex count a type must keep to stay valid. Dropping below
 *  this should delete the whole measurement instead. */
export function minVertices(type: EditableMeasurementType): number {
  if (CLOSED_TYPES.has(type)) return 3;
  if (type === 'polyline') return 2;
  if (type === 'count') return 1;
  return 2;
}

/* ── Hit-testing ─────────────────────────────────────────────────────── */

export type HitKind = 'vertex' | 'edge' | 'body';

export interface HitResult {
  kind: HitKind;
  /** For `vertex`: the vertex index. For `edge`: the index of the edge's
   *  first vertex (insert the new vertex at `index + 1`). For `body`: the
   *  nearest edge / dot index (informational). */
  index: number;
}

/** Number of edges to test for a measurement (closes the wrap edge for
 *  polygon types). */
function edgeCount(type: EditableMeasurementType, n: number): number {
  if (n < 2) return 0;
  return CLOSED_TYPES.has(type) ? n : n - 1;
}

/**
 * Hit-test a pointer (in PDF units) against one measurement.
 *
 * Priority high to low: vertex, then (only when `selected`) an edge
 * midpoint for add-vertex, then the edge / line body, then the interior.
 * Returns `null` when nothing is within grab tolerance.
 *
 * `zoom` is the current canvas zoom so the grab radius stays constant in
 * screen pixels at any zoom level (no `dpr` ever enters this space).
 */
export function hitTest(
  pt: Point,
  m: EditableMeasurement,
  zoom: number,
  selected: boolean,
): HitResult | null {
  const z = zoom > 0 ? zoom : 1;
  const pts = m.points;
  const n = pts.length;
  if (n === 0) return null;

  const vertexTol = VERTEX_GRAB_PX / z;
  const edgeTol = GRAB_PX / z;

  // 1) Vertex - nearest within the vertex grab radius.
  let bestVertex = -1;
  let bestVertexDist = Infinity;
  for (let i = 0; i < n; i++) {
    const p = pts[i]!;
    const d = pixelDistance(pt.x, pt.y, p.x, p.y);
    if (d < vertexTol && d < bestVertexDist) {
      bestVertexDist = d;
      bestVertex = i;
    }
  }
  if (bestVertex >= 0) return { kind: 'vertex', index: bestVertex };

  // Count markers have no edges / interior - a dot miss is a full miss.
  if (m.type === 'count') return null;

  // Text pins only have the single anchor vertex tested above.
  if (m.type === 'text') return null;

  // Rectangle / highlight: two-corner bbox. The corners were already
  // tested as vertices; the body is the filled bbox.
  if ((m.type === 'rectangle' || m.type === 'highlight') && n === 2) {
    const a = pts[0]!;
    const b = pts[1]!;
    const minX = Math.min(a.x, b.x) - edgeTol;
    const maxX = Math.max(a.x, b.x) + edgeTol;
    const minY = Math.min(a.y, b.y) - edgeTol;
    const maxY = Math.max(a.y, b.y) + edgeTol;
    if (pt.x >= minX && pt.x <= maxX && pt.y >= minY && pt.y <= maxY) {
      return { kind: 'body', index: 0 };
    }
    return null;
  }

  const edges = edgeCount(m.type, n);

  // 2) Edge midpoint (add-vertex) - only on an already-selected,
  //    variable-vertex measurement.
  if (selected && supportsVariableVertices(m.type)) {
    for (let i = 0; i < edges; i++) {
      const a = pts[i]!;
      const b = pts[(i + 1) % n]!;
      const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
      if (pixelDistance(pt.x, pt.y, mid.x, mid.y) < edgeTol) {
        return { kind: 'edge', index: i };
      }
    }
  }

  // 3) Edge / line body.
  if (OPEN_LINE_TYPES.has(m.type) || CLOSED_TYPES.has(m.type)) {
    let bestEdge = -1;
    let bestEdgeDist = Infinity;
    for (let i = 0; i < edges; i++) {
      const a = pts[i]!;
      const b = pts[(i + 1) % n]!;
      const d = pointToSegmentDistance(pt, a, b);
      if (d < edgeTol && d < bestEdgeDist) {
        bestEdgeDist = d;
        bestEdge = i;
      }
    }
    if (bestEdge >= 0) return { kind: 'body', index: bestEdge };
  }

  // 4) Interior - closed polygon fill.
  if (CLOSED_TYPES.has(m.type) && n >= 3 && pointInPolygon(pt, pts)) {
    return { kind: 'body', index: 0 };
  }

  return null;
}

/* ── Vertex add / delete ─────────────────────────────────────────────── */

/** Insert a vertex at `index + 1` on the segment from `index` to its
 *  successor, positioned at the segment midpoint. Returns a NEW array. */
export function insertVertexAt(points: Point[], edgeIndex: number): Point[] {
  const n = points.length;
  if (n < 2) return points;
  const a = points[edgeIndex]!;
  const b = points[(edgeIndex + 1) % n]!;
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 };
  const next = points.slice();
  next.splice(edgeIndex + 1, 0, mid);
  return next;
}

/** Remove the vertex at `vertexIndex`. Returns a NEW array; callers must
 *  guard `points.length > minVertices(type)` before calling so the
 *  measurement never drops below a valid shape. */
export function deleteVertexAt(points: Point[], vertexIndex: number): Point[] {
  if (vertexIndex < 0 || vertexIndex >= points.length) return points;
  const next = points.slice();
  next.splice(vertexIndex, 1);
  return next;
}

/* ── Shape translation ───────────────────────────────────────────────── */

/** Translate every point of a shape by `(dx, dy)`. Returns a NEW array. */
export function translatePoints(points: Point[], dx: number, dy: number): Point[] {
  return points.map((p) => ({ x: p.x + dx, y: p.y + dy }));
}

/* ── Live recompute (the money path, mirrors create-time math) ──────── */

const SUP2 = '²';
const SUP3 = '³';
const TIMES = '×';

export interface RecomputePatch {
  value: number;
  label: string;
  unit?: string;
  area?: number;
  depth?: number;
  width?: number;
  height?: number;
  /** True when an area / volume polygon currently self-intersects (bowtie).
   *  The caller surfaces a non-blocking amber readout; the trace is still
   *  editable so the user can fix it (D-TKC-015). */
  selfIntersecting?: boolean;
}

/**
 * Recompute a measurement's value + label from a candidate set of points.
 *
 * This is the single source of truth for reshape-time numbers and is the
 * exact mirror of the create-time handlers in `TakeoffViewerModule`
 * (`handleCanvasDblClick`, `handleVolumeDepthConfirm`, distance / rectarea
 * paths). The label strings (`"(P: ...)"`, `"V = ..."`) are pinned because
 * the ledger and exports parse them.
 */
export function recomputeMeasurement(
  m: EditableMeasurement,
  points: Point[],
  scale: ScaleConfig,
): RecomputePatch {
  const unitLabel = scale.unitLabel;

  switch (m.type) {
    case 'distance': {
      const a = points[0];
      const b = points[1];
      if (!a || !b) return { value: 0, label: '' };
      const value = toRealDistance(pixelDistance(a.x, a.y, b.x, b.y), scale);
      return { value, label: formatMeasurement(value, unitLabel), unit: unitLabel };
    }

    case 'polyline': {
      let totalPx = 0;
      for (let i = 0; i < points.length - 1; i++) {
        const pa = points[i]!;
        const pb = points[i + 1]!;
        totalPx += pixelDistance(pa.x, pa.y, pb.x, pb.y);
      }
      const value = toRealDistance(totalPx, scale);
      return { value, label: formatMeasurement(value, unitLabel), unit: unitLabel };
    }

    case 'area': {
      const value = toRealArea(polygonAreaPixels(points), scale);
      const perim = toRealDistance(polygonPerimeterPixels(points), scale);
      const label = `${formatMeasurement(value, unitLabel + SUP2)} (P: ${formatMeasurement(perim, unitLabel)})`;
      return {
        value,
        label,
        unit: `${unitLabel}${SUP2}`,
        selfIntersecting: isSelfIntersecting(points),
      };
    }

    case 'volume': {
      const area = toRealArea(polygonAreaPixels(points), scale);
      const depth = m.depth ?? 0;
      const value = area * depth;
      const label =
        `V = ${formatMeasurement(value, unitLabel + SUP3)} ` +
        `(A: ${formatMeasurement(area, unitLabel + SUP2)} ${TIMES} D: ${formatMeasurement(depth, unitLabel)})`;
      return {
        value,
        label,
        unit: `${unitLabel}${SUP3}`,
        area,
        depth,
        selfIntersecting: isSelfIntersecting(points),
      };
    }

    case 'count': {
      // Vertex drag repositions a dot; the count equals the dot count.
      return { value: points.length, label: String(points.length), unit: 'pcs' };
    }

    case 'rectangle':
    case 'highlight': {
      const a = points[0];
      const b = points[1];
      const width = a && b ? Math.abs(b.x - a.x) : 0;
      const height = a && b ? Math.abs(b.y - a.y) : 0;
      return { value: 0, label: '', width, height };
    }

    case 'cloud':
    case 'arrow':
    case 'text':
    default:
      return { value: 0, label: '' };
  }
}
