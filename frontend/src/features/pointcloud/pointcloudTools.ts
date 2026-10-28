// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure, THREE-free helpers for the point-cloud viewer's inspection tools:
 * cross-section height slice, point-to-point measurement, and the
 * axis-aligned clip box. Kept side-effect-free and dependency-free (plain
 * numbers/objects in, plain numbers/objects out) so they are trivial to unit
 * test without booting a WebGL context; PointCloudViewer.tsx is the only
 * place that turns this data into real THREE.Plane / THREE.Vector3 objects
 * and owns their scene lifecycle.
 *
 * Frame note: PointCloudViewer rotates the loaded THREE.Points object by
 * -90 deg about X so a Z-up scan renders in three.js's Y-up world (see the
 * `points.rotation.x = -Math.PI / 2` assignment there). That rotation maps a
 * centre-relative local point (x, y, z) to the world-space point
 * (x, z, -y) - every function here that deals in "world space" (clip boxes,
 * the plan-view camera target, raycast hits) uses that mapping.
 */

/** A plain 3D point/vector - deliberately not a THREE.Vector3 so this module
 *  has zero runtime dependency on three.js. */
import { fmtFixed } from '@/shared/lib/formatters';
export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

export interface Measurement3D {
  /** Straight-line distance between the two picked points, in metres. */
  distance: number;
  /** Distance projected onto the horizontal (XZ) plane, in metres. */
  horizontal: number;
  /** Absolute vertical (Y) difference, in metres. */
  vertical: number;
}

/** Compute the straight-line / horizontal / vertical spread between two
 *  world-space points (Y is up, matching the viewer's rotated frame). */
export function computeMeasurement3D(a: Vec3, b: Vec3): Measurement3D {
  const dx = b.x - a.x;
  const dy = b.y - a.y;
  const dz = b.z - a.z;
  return {
    distance: Math.sqrt(dx * dx + dy * dy + dz * dz),
    horizontal: Math.sqrt(dx * dx + dz * dz),
    vertical: Math.abs(dy),
  };
}

/** Format a length for on-screen display at millimetre precision: whole
 *  millimetres under one metre, two-decimal metres at or above one metre. */
export function formatLengthMm(metres: number): string {
  if (!Number.isFinite(metres)) return '-';
  const abs = Math.abs(metres);
  if (abs >= 1) return `${fmtFixed(metres, 2)} m`;
  return `${Math.round(metres * 1000)} mm`;
}

/** Format a length as whole metres with two decimals - used for the
 *  elevation legend / slice sliders, where mm precision is not meaningful
 *  (heights typically span whole buildings). */
export function formatMetersLabel(metres: number): string {
  if (!Number.isFinite(metres)) return '-';
  return `${fmtFixed(metres, 2)} m`;
}

export interface CloudBoundsInput {
  bboxMin: readonly [number, number, number];
  bboxMax: readonly [number, number, number];
  center: readonly [number, number, number];
}

export interface DerivedBounds {
  /** Bounds in the centre-relative LOCAL frame the raw positions live in
   *  (pre-rotation - same frame the height-ramp colouring already uses). */
  localMin: Vec3;
  localMax: Vec3;
  /** Bounds in the rotated WORLD frame the camera / raycaster / clip boxes
   *  operate in (post `points.rotation.x = -PI/2`). */
  worldMin: Vec3;
  worldMax: Vec3;
  worldCenter: Vec3;
  /** Local-frame bounding diagonal, in metres. Never zero (floors at 1) so
   *  callers can divide by it safely. */
  diagonal: number;
  /** Local-frame Z span (= world-frame Y span): the scan's vertical extent. */
  zMin: number;
  zMax: number;
}

/** Derive every bounds/frame value the viewer's new tools need from the
 *  wire header's bbox + center. Pure number math - safe to call every
 *  render via useMemo. */
export function deriveCloudBounds(input: CloudBoundsInput): DerivedBounds {
  const localMin: Vec3 = {
    x: input.bboxMin[0] - input.center[0],
    y: input.bboxMin[1] - input.center[1],
    z: input.bboxMin[2] - input.center[2],
  };
  const localMax: Vec3 = {
    x: input.bboxMax[0] - input.center[0],
    y: input.bboxMax[1] - input.center[1],
    z: input.bboxMax[2] - input.center[2],
  };
  const dx = localMax.x - localMin.x;
  const dy = localMax.y - localMin.y;
  const dz = localMax.z - localMin.z;
  const diagonal = Math.sqrt(dx * dx + dy * dy + dz * dz) || 1;

  // local (x, y, z) -> world (x, z, -y); see the module docstring.
  // `|| 0` normalises a -0 result (e.g. when localMax.y is exactly 0) to
  // plain 0 - numerically identical, but keeps displayed/compared values
  // (legend labels, box-extent tests) from ever showing a stray sign.
  const worldMin: Vec3 = { x: localMin.x, y: localMin.z, z: -localMax.y || 0 };
  const worldMax: Vec3 = { x: localMax.x, y: localMax.z, z: -localMin.y || 0 };
  const worldCenter: Vec3 = {
    x: (worldMin.x + worldMax.x) / 2,
    y: (worldMin.y + worldMax.y) / 2,
    z: (worldMin.z + worldMax.z) / 2,
  };

  return {
    localMin,
    localMax,
    worldMin,
    worldMax,
    worldCenter,
    diagonal,
    zMin: localMin.z,
    zMax: localMax.z,
  };
}

/** A clipping-plane equation: points with `normal . p + constant >= 0` are
 *  kept, everything else is clipped away (matches THREE.Plane semantics so
 *  the viewer can build a real THREE.Plane from this with one call). */
export interface PlaneEq {
  normal: Vec3;
  constant: number;
}

export interface BoxExtent {
  min: Vec3;
  max: Vec3;
}

/** The two inward-facing planes for a world-Y height band [minY, maxY]. */
export function heightSlicePlanes(minY: number, maxY: number): [PlaneEq, PlaneEq] {
  return [
    { normal: { x: 0, y: 1, z: 0 }, constant: -minY },
    { normal: { x: 0, y: -1, z: 0 }, constant: maxY },
  ];
}

/** The six inward-facing planes of an axis-aligned world-space box. */
export function boxPlanes(box: BoxExtent): PlaneEq[] {
  return [
    { normal: { x: 1, y: 0, z: 0 }, constant: -box.min.x },
    { normal: { x: -1, y: 0, z: 0 }, constant: box.max.x },
    { normal: { x: 0, y: 1, z: 0 }, constant: -box.min.y },
    { normal: { x: 0, y: -1, z: 0 }, constant: box.max.y },
    { normal: { x: 0, y: 0, z: 1 }, constant: -box.min.z },
    { normal: { x: 0, y: 0, z: -1 }, constant: box.max.z },
  ];
}

/** Signed distance from a point to a plane equation (>= 0 means kept). */
export function planeDistance(p: Vec3, plane: PlaneEq): number {
  return p.x * plane.normal.x + p.y * plane.normal.y + p.z * plane.normal.z + plane.constant;
}

/** Whether a point survives every active clip plane - used to keep the
 *  measure tool's raycast picks consistent with what is actually visible
 *  (GPU clipping planes are invisible to THREE.Raycaster, which would
 *  otherwise happily "measure" a point hidden by an active slice/clip box). */
export function isWithinPlanes(p: Vec3, planes: readonly PlaneEq[]): boolean {
  return planes.every((plane) => planeDistance(p, plane) >= 0);
}

const AXES = ['x', 'y', 'z'] as const;

/** Scale a clip box by `factor` around its own centre (>1 grows, <1
 *  shrinks), clamped to stay within `fullBox` and never collapse below
 *  `minHalfExtent` on any axis. Pure - callers own the resulting state. */
export function scaleClipBox(
  box: BoxExtent,
  factor: number,
  fullBox: BoxExtent,
  minHalfExtent: number,
): BoxExtent {
  const min: Vec3 = { x: 0, y: 0, z: 0 };
  const max: Vec3 = { x: 0, y: 0, z: 0 };
  for (const axis of AXES) {
    const center = (box.min[axis] + box.max[axis]) / 2;
    const half = Math.max(((box.max[axis] - box.min[axis]) / 2) * factor, minHalfExtent);
    min[axis] = Math.max(fullBox.min[axis], center - half);
    max[axis] = Math.min(fullBox.max[axis], center + half);
  }
  return { min, max };
}

/** Minimal read-only view of a loaded cloud for the pure point-counting
 *  helpers below: the centre-relative XYZ triples and how many points they
 *  hold. Deliberately structural (ArrayLike) so a THREE.BufferAttribute array,
 *  a Float32Array or a plain number[] all satisfy it without a dependency. */
export interface CloudPointsView {
  positions: ArrayLike<number>;
  pointCount: number;
}

/** Count how many cloud points fall inside an axis-aligned WORLD-space box.
 *  Positions arrive in the centre-relative LOCAL frame (x, y, z); the viewer
 *  rotates them -90 deg about X, so a local point maps to world (x, z, -y) -
 *  the same mapping every other "world space" helper here uses. Degenerate
 *  input (no points, a positions buffer shorter than 3N) yields 0. */
export function countPointsInBox(cloud: CloudPointsView, box: BoxExtent): number {
  const n = cloud.pointCount;
  const pos = cloud.positions;
  if (!(n > 0) || pos.length < n * 3) return 0;
  const { min, max } = box;
  let count = 0;
  for (let i = 0; i < n; i++) {
    const lx = pos[i * 3] ?? 0;
    const ly = pos[i * 3 + 1] ?? 0;
    const lz = pos[i * 3 + 2] ?? 0;
    // local (x, y, z) -> world (x, z, -y).
    const wx = lx;
    const wy = lz;
    const wz = -ly;
    if (
      wx >= min.x &&
      wx <= max.x &&
      wy >= min.y &&
      wy <= max.y &&
      wz >= min.z &&
      wz <= max.z
    ) {
      count += 1;
    }
  }
  return count;
}

/** Linear extents + derived plan area / bounding volume of a world-space box,
 *  in metres. `width` is the world-X span, `depth` the world-Z span (the two
 *  ground axes), `height` the world-Y (vertical) span. Spans floor at 0 so an
 *  inverted or zero-extent box never yields negative quantities. Used for the
 *  Groups panel readout and its BOQ hand-off (plan area m2, volume m3). */
export interface BoxMetrics {
  width: number;
  depth: number;
  height: number;
  planArea: number;
  volume: number;
}

export function boxMetrics(box: BoxExtent): BoxMetrics {
  const width = Math.max(0, box.max.x - box.min.x);
  const depth = Math.max(0, box.max.z - box.min.z);
  const height = Math.max(0, box.max.y - box.min.y);
  return { width, depth, height, planArea: width * depth, volume: width * depth * height };
}

/** Turn a free-text scan label into a filesystem/URL-safe filename fragment
 *  for the PNG snapshot download; falls back to "scan" when nothing usable
 *  survives (e.g. a label that is entirely punctuation/CJK-only would still
 *  produce something reasonable via the fallback). */
export function slugifyForFilename(label: string): string {
  const slug = label
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'scan';
}

// ══════════════════════════════════════════════════════════════════════
// Extended inspection tools: polyline path, plan area + cut/fill volume,
// coordinate readout, preset views, on-screen decimation and CSV export.
// All still pure and THREE-free - PointCloudViewer.tsx turns the results
// into scene objects and owns their lifecycle.
// ══════════════════════════════════════════════════════════════════════

// ── Polyline / path measurement ─────────────────────────────────────────

export interface PolylineMetrics {
  /** Sum of every segment length walked along the path, in metres. */
  totalLength: number;
  /** Number of segments (vertices - 1); 0 for an empty or single-point path. */
  segmentCount: number;
  /** Straight-line / horizontal / vertical spread of the final segment, or
   *  null when the path has fewer than two vertices. */
  lastSegment: Measurement3D | null;
  /** Straight-line distance from the first vertex to the last, in metres. */
  straightLine: number;
}

/** Running metrics for a multi-segment measurement path - the polyline
 *  generalisation of `computeMeasurement3D`: total walked length, the final
 *  segment's spread and the first-to-last straight line. An empty or
 *  single-point path yields all zeros with a null last segment. */
export function computePolylineMetrics(points: readonly Vec3[]): PolylineMetrics {
  if (points.length < 2) {
    return { totalLength: 0, segmentCount: 0, lastSegment: null, straightLine: 0 };
  }
  let totalLength = 0;
  for (let i = 1; i < points.length; i++) {
    totalLength += computeMeasurement3D(points[i - 1] as Vec3, points[i] as Vec3).distance;
  }
  const lastSegment = computeMeasurement3D(
    points[points.length - 2] as Vec3,
    points[points.length - 1] as Vec3,
  );
  const straightLine = computeMeasurement3D(
    points[0] as Vec3,
    points[points.length - 1] as Vec3,
  ).distance;
  return { totalLength, segmentCount: points.length - 1, lastSegment, straightLine };
}

// ── Plan area + cut/fill volume on the ground plane ──────────────────────

/** Plan (horizontal) area of a polygon in square metres, via the shoelace
 *  formula on the world X/Z axes. Y is up in the viewer frame, so X/Z is the
 *  ground plane. Fewer than three vertices encloses no area, returning 0. */
export function polygonAreaXZ(points: readonly Vec3[]): number {
  if (points.length < 3) return 0;
  let twiceArea = 0;
  for (let i = 0; i < points.length; i++) {
    const a = points[i] as Vec3;
    const b = points[(i + 1) % points.length] as Vec3;
    twiceArea += a.x * b.z - b.x * a.z;
  }
  return Math.abs(twiceArea) / 2;
}

/** Even-odd ray-cast test: is the horizontal point (x, z) inside the polygon
 *  on the world X/Z ground plane? A polygon of fewer than three vertices
 *  contains nothing. Edge-exact hits are not guaranteed either way (standard
 *  for the even-odd rule) - unproblematic for cloud sampling where a point
 *  landing exactly on a boundary is vanishingly rare. */
export function pointInPolygonXZ(
  p: { x: number; z: number },
  polygon: readonly Vec3[],
): boolean {
  if (polygon.length < 3) return false;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const vi = polygon[i] as Vec3;
    const vj = polygon[j] as Vec3;
    const straddles = vi.z > p.z !== vj.z > p.z;
    if (straddles && p.x < ((vj.x - vi.x) * (p.z - vi.z)) / (vj.z - vi.z) + vi.x) {
      inside = !inside;
    }
  }
  return inside;
}

export interface VolumeEstimate {
  /** Net volume = fill - cut, in cubic metres (positive = mostly above the
   *  reference plane). */
  net: number;
  /** Volume above the reference plane, in cubic metres (>= 0). */
  fill: number;
  /** Volume below the reference plane, in cubic metres (>= 0). */
  cut: number;
  /** Plan area actually covered by sampled grid cells, in square metres. */
  area: number;
  /** Number of grid cells that received at least one sample point. */
  cellCount: number;
  /** The grid cell size used, echoed back for the readout. */
  cellSize: number;
}

/** Estimate cut / fill volume of a sampled surface against a flat reference
 *  elevation by the grid (DEM) method: bucket every in-polygon sample into a
 *  square cell, take each cell's mean height, then sum cell_area x (mean - ref)
 *  as fill (above) or cut (below). This is the standard stockpile / earthwork
 *  estimate from a raw cloud; accuracy scales with sample density and a
 *  sensible cell size. Degenerate input (empty samples, < 3 polygon vertices,
 *  non-positive cell size, non-finite reference) yields an all-zero estimate. */
export function estimateVolumeVsPlane(
  samples: readonly Vec3[],
  polygon: readonly Vec3[],
  referenceY: number,
  cellSize: number,
): VolumeEstimate {
  const empty: VolumeEstimate = { net: 0, fill: 0, cut: 0, area: 0, cellCount: 0, cellSize };
  if (
    polygon.length < 3 ||
    samples.length === 0 ||
    !(cellSize > 0) ||
    !Number.isFinite(referenceY)
  ) {
    return empty;
  }

  // Index cells from the polygon's ground-plane bounding-box origin so the
  // grid is stable regardless of where the polygon sits in world space.
  let minX = Infinity;
  let minZ = Infinity;
  for (const v of polygon) {
    if (v.x < minX) minX = v.x;
    if (v.z < minZ) minZ = v.z;
  }
  if (!Number.isFinite(minX) || !Number.isFinite(minZ)) return empty;

  // Per-cell running mean of the vertical (Y) coordinate.
  const cells = new Map<string, { sum: number; count: number }>();
  for (const s of samples) {
    if (!Number.isFinite(s.x) || !Number.isFinite(s.y) || !Number.isFinite(s.z)) continue;
    if (!pointInPolygonXZ(s, polygon)) continue;
    const ix = Math.floor((s.x - minX) / cellSize);
    const iz = Math.floor((s.z - minZ) / cellSize);
    const key = `${ix}:${iz}`;
    const cell = cells.get(key);
    if (cell) {
      cell.sum += s.y;
      cell.count += 1;
    } else {
      cells.set(key, { sum: s.y, count: 1 });
    }
  }

  const cellArea = cellSize * cellSize;
  let fill = 0;
  let cut = 0;
  for (const cell of cells.values()) {
    const dh = cell.sum / cell.count - referenceY;
    if (dh >= 0) fill += dh * cellArea;
    else cut += -dh * cellArea;
  }

  return {
    net: fill - cut,
    fill,
    cut,
    area: cells.size * cellArea,
    cellCount: cells.size,
    cellSize,
  };
}

// ── Point inspector: recover absolute scan coordinates ───────────────────

/** Map a world-space point (the rotated, centre-relative frame the viewer's
 *  camera and raycaster use) back to the scan's own coordinate system: undo
 *  the viewer's -90 deg X rotation, then add the wire `center` origin that was
 *  subtracted for float32 safety. The result is the point's real coordinate in
 *  the file's CRS, or its local frame when the scan carried no georeference. */
export function worldToScanCoords(
  world: Vec3,
  center: readonly [number, number, number],
): Vec3 {
  // Inverse of local (x, y, z) -> world (x, z, -y): local = (wx, -wz, wy).
  return {
    x: world.x + center[0],
    y: -world.z + center[1],
    z: world.y + center[2],
  };
}

// ── Preset camera views ──────────────────────────────────────────────────

export type PresetView = 'top' | 'front' | 'side' | 'iso';

/** Camera offset from the look-at target for a named preset view, scaled so
 *  the whole cloud fits at `distance`. World frame is Y-up (see the module
 *  docstring). The top view carries a tiny lateral tilt so OrbitControls'
 *  spherical coordinates stay well-defined and orbiting away from straight
 *  down does not snap. */
export function presetViewOffset(view: PresetView, distance: number): Vec3 {
  const d = Number.isFinite(distance) && distance > 0 ? distance : 1;
  switch (view) {
    case 'top':
      return { x: d * 0.02, y: d, z: 0 };
    case 'front':
      return { x: 0, y: 0, z: d };
    case 'side':
      return { x: d, y: 0, z: 0 };
    case 'iso':
    default:
      return { x: d * 0.7, y: d * 0.55, z: d * 0.7 };
  }
}

// ── On-screen (client-side) decimation ───────────────────────────────────

/** Stride for thinning a cloud on screen to roughly `keepFraction` of its
 *  points (draw every stride-th point). Always >= 1. A fraction >= 1 keeps
 *  everything (stride 1); a fraction <= 0 collapses to a single point (stride
 *  = point count). Lets the viewer keep navigation smooth on very large clouds
 *  without re-downloading a coarser decimation from the server. */
export function decimationStride(pointCount: number, keepFraction: number): number {
  if (!Number.isFinite(pointCount) || pointCount <= 1) return 1;
  if (!Number.isFinite(keepFraction) || keepFraction >= 1) return 1;
  if (keepFraction <= 0) return pointCount;
  return Math.min(pointCount, Math.max(1, Math.round(1 / keepFraction)));
}

// ── Display formatters (area / volume) ───────────────────────────────────

/** Format a plan area for display, in square metres (ASCII "m2"). */
export function formatAreaM2(m2: number): string {
  if (!Number.isFinite(m2)) return '-';
  return `${fmtFixed(m2, 2)} m2`;
}

/** Format a volume for display, in cubic metres (ASCII "m3"). */
export function formatVolumeM3(m3: number): string {
  if (!Number.isFinite(m3)) return '-';
  return `${fmtFixed(m3, 2)} m3`;
}

// ── CSV export ────────────────────────────────────────────────────────────

/** Escape one CSV field per RFC 4180: wrap in double quotes and double any
 *  embedded quote when the value contains a comma, quote or line break. */
function escapeCsvField(value: string | number): string {
  const s = typeof value === 'number' ? String(value) : value;
  return /[",\r\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
}

/** Build a CSV document from a header row and body rows. Fields are escaped
 *  per RFC 4180; rows are newline-separated. Empty `rows` yields just the
 *  header line. */
export function buildCsv(
  headers: readonly string[],
  rows: readonly (readonly (string | number)[])[],
): string {
  const lines = [headers.map(escapeCsvField).join(',')];
  for (const row of rows) lines.push(row.map(escapeCsvField).join(','));
  return lines.join('\n');
}

/** Round to at most three decimals as a plain string (no trailing-zero
 *  padding) for compact CSV coordinate columns. Non-finite -> empty string. */
function csvNumber(v: number): string {
  if (!Number.isFinite(v)) return '';
  return String(Math.round(v * 1000) / 1000);
}

export interface AnnotationExportRow {
  index: number;
  note: string;
  /** Absolute scan/CRS coordinate of the pin. */
  scan: Vec3;
  /** Viewer-frame (rotated, centre-relative) coordinate of the pin. */
  world: Vec3;
}

/** Serialise dropped annotations to CSV: index, note, absolute scan XYZ and
 *  viewer-frame XYZ. */
export function annotationsToCsv(rows: readonly AnnotationExportRow[]): string {
  return buildCsv(
    ['index', 'note', 'scan_x', 'scan_y', 'scan_z', 'view_x', 'view_y', 'view_z'],
    rows.map((r) => [
      r.index,
      r.note,
      csvNumber(r.scan.x),
      csvNumber(r.scan.y),
      csvNumber(r.scan.z),
      csvNumber(r.world.x),
      csvNumber(r.world.y),
      csvNumber(r.world.z),
    ]),
  );
}

/** Serialise a measurement path to CSV: per vertex the absolute scan XYZ, the
 *  segment length from the previous vertex and the cumulative walked length. */
export function polylineToCsv(
  points: readonly Vec3[],
  center: readonly [number, number, number],
): string {
  let cumulative = 0;
  const rows = points.map((p, i) => {
    const scan = worldToScanCoords(p, center);
    const segment = i === 0 ? 0 : computeMeasurement3D(points[i - 1] as Vec3, p).distance;
    cumulative += segment;
    return [
      i + 1,
      csvNumber(scan.x),
      csvNumber(scan.y),
      csvNumber(scan.z),
      csvNumber(segment),
      csvNumber(cumulative),
    ];
  });
  return buildCsv(['vertex', 'scan_x', 'scan_y', 'scan_z', 'segment_m', 'cumulative_m'], rows);
}

// ══════════════════════════════════════════════════════════════════════
// Angle measurement + dynamic scale bar. Still pure and THREE-free -
// PointCloudViewer.tsx renders the markers/lines and the on-screen bar.
// ══════════════════════════════════════════════════════════════════════

// ── Angle measurement (three-point) ──────────────────────────────────────

/** Interior angle in degrees at vertex `b`, formed by the rays b->a and b->c
 *  in 3D. Always in [0, 180]. Degenerate input (a or c coincident with b) has
 *  no defined angle and yields NaN, so callers can show a placeholder rather
 *  than a misleading 0. Handy for reading a roof pitch, a wall corner or the
 *  splay of two site features straight off the cloud. */
export function angleAtVertex(a: Vec3, b: Vec3, c: Vec3): number {
  const ux = a.x - b.x;
  const uy = a.y - b.y;
  const uz = a.z - b.z;
  const vx = c.x - b.x;
  const vy = c.y - b.y;
  const vz = c.z - b.z;
  const lu = Math.sqrt(ux * ux + uy * uy + uz * uz);
  const lv = Math.sqrt(vx * vx + vy * vy + vz * vz);
  if (lu === 0 || lv === 0) return NaN;
  let cos = (ux * vx + uy * vy + uz * vz) / (lu * lv);
  // Clamp against floating-point drift so acos never sees |x| > 1.
  if (cos > 1) cos = 1;
  else if (cos < -1) cos = -1;
  return (Math.acos(cos) * 180) / Math.PI;
}

/** Format an angle in degrees for display (one decimal + degree glyph).
 *  Non-finite -> "-". */
export function formatAngle(deg: number): string {
  if (!Number.isFinite(deg)) return '-';
  return `${fmtFixed(deg, 1)}°`;
}

// ── Dynamic scale bar ─────────────────────────────────────────────────────

export interface ScaleBar {
  /** The "nice" round length the bar represents, in metres. */
  meters: number;
  /** How wide to draw the bar on screen, in pixels. */
  pixels: number;
  /** Human label for the bar, e.g. "5 m", "50 cm", "2 km". */
  label: string;
}

/** Format a scale-bar length: km at/above 1000 m, cm below 1 m, plain metres
 *  in between. Inputs are the 1/2/5 x 10^n "nice" numbers `chooseScaleBar`
 *  produces, so these stay whole (5 m, 50 cm, 2 km) rather than showing
 *  spurious decimals. */
function formatScaleBarLabel(meters: number): string {
  if (meters >= 1000) return `${meters / 1000} km`;
  if (meters >= 1) return `${meters} m`;
  return `${Math.round(meters * 100)} cm`;
}

/** Pick a "nice" 1/2/5 x 10^n scale-bar length that fits within `maxPixels` at
 *  the given world-metres-per-pixel, and report its on-screen width. This is
 *  the familiar map/CAD scale bar: the largest round distance no wider than
 *  the allotted space, so the viewer always shows a clean "5 m" / "20 m" ruler
 *  that grows and shrinks as you zoom. Invalid input (non-positive or
 *  non-finite scale) yields a zero-width bar with a "-" label. */
export function chooseScaleBar(worldPerPixel: number, maxPixels: number): ScaleBar {
  const raw = worldPerPixel * maxPixels;
  if (!(worldPerPixel > 0) || !(maxPixels > 0) || !Number.isFinite(raw)) {
    return { meters: 0, pixels: 0, label: '-' };
  }
  const pow = Math.pow(10, Math.floor(Math.log10(raw)));
  let meters = pow;
  for (const mult of [5, 2, 1]) {
    if (mult * pow <= raw) {
      meters = mult * pow;
      break;
    }
  }
  return { meters, pixels: meters / worldPerPixel, label: formatScaleBarLabel(meters) };
}
