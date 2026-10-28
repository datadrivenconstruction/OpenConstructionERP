// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Mesh geometry extraction - pure functions plus a Three.js scene walker.
 *
 * These helpers turn raw triangle soup (from any loaded mesh format) into the
 * quantities OpenConstructionERP cares about: surface area, mesh volume,
 * bounding box, triangle/object count and the longest extent (length). They
 * are deliberately kept free of any UI or network concern so they can be unit
 * tested in isolation - see ``geometry.test.ts``.
 *
 * Units: every function works in "source units" unless a scale ``s`` (metres
 * per source unit) is supplied, in which case linear values are multiplied by
 * ``s``, areas by ``s^2`` and volumes by ``s^3``. Callers confirm the source
 * unit with the user before trusting the numbers - we never guess silently.
 *
 * Coordinate frame: the walker can apply an up-axis correction so the reported
 * bounding box is in canonical Z-up (height = Z extent), matching the rest of
 * the platform (DIN 276 / DDC canonical format) and the BIM viewer, which
 * expects Z-up geometry in the uploaded GLB.
 */

import * as THREE from 'three';
import type { CanonicalBBox } from '@/shared/ui/BIMViewer/canonicalElementDetails';

/** Axis-aligned bounding box, structurally compatible with CanonicalBBox so it
 *  can be fed straight into ``deriveGeometry`` and the upload data table. */
export type BoundingBox = CanonicalBBox;

/** A single vertex as an ``[x, y, z]`` tuple. */
export type Vertex = readonly [number, number, number];

/** A triangle as three world-space vertices. */
export type Triangle = readonly [Vertex, Vertex, Vertex];

/** Which source axis points up. glTF/GLB/OBJ/USD are conventionally Y-up;
 *  STL/PLY/3DS coming out of CAD are usually Z-up. */
export type UpAxis = 'y' | 'z';

/** Geometry metrics for a set of triangles. Linear/area/volume values already
 *  have the unit scale applied. */
export interface GeometryMetrics {
  /** Sum of triangle areas. In m^2 when ``scale`` is metres per source unit. */
  surfaceArea: number;
  /** Absolute mesh volume via the divergence theorem. Only physically
   *  meaningful when ``watertight`` is true; callers must flag it approximate
   *  otherwise. In m^3 when ``scale`` is metres per source unit. */
  volume: number;
  /** Axis-aligned bounding box, or null when there are no triangles. */
  bbox: BoundingBox | null;
  /** Number of triangles processed. */
  triangleCount: number;
  /** True when every edge is shared by exactly two triangles (closed manifold),
   *  which is the precondition for the volume to be exact. */
  watertight: boolean;
  /** Longest bounding-box extent (max of width/depth/height). Used as length. */
  longestExtent: number;
}

/** Per-object metrics with a display name and a handle back to the source mesh
 *  (needed to bake and re-export the normalized GLB). */
export interface ExtractedObject {
  /** The source mesh, so the caller can bake/rename it for GLB export. */
  mesh: THREE.Mesh;
  /** Best-effort display name from the mesh or its nearest named ancestor. */
  name: string;
  /** Surface area (m^2 at the applied scale). */
  area_m2: number;
  /** Mesh volume (m^3 at the applied scale). Exact only when ``watertight``. */
  volume_m3: number;
  /** Longest extent (m at the applied scale). */
  length_m: number;
  /** Bounding box in the (optionally up-axis-corrected) frame. */
  bbox: BoundingBox | null;
  triangleCount: number;
  watertight: boolean;
}

/** Scene-wide totals. Volume is summed over watertight objects only, so open
 *  meshes contribute area but never a bogus volume. */
export interface ExtractionTotals {
  area_m2: number;
  volume_m3: number;
  length_m: number;
  bbox: BoundingBox | null;
  triangleCount: number;
  objectCount: number;
  /** How many objects are watertight (closed). */
  watertightCount: number;
}

export interface ExtractionResult {
  objects: ExtractedObject[];
  totals: ExtractionTotals;
}

const EMPTY_METRICS: GeometryMetrics = {
  surfaceArea: 0,
  volume: 0,
  bbox: null,
  triangleCount: 0,
  watertight: false,
  longestExtent: 0,
};

/**
 * Watertight heuristic: a mesh is closed when every undirected edge is shared
 * by exactly two triangles. Vertices are quantized relative to the model
 * diagonal so that floating-point noise in shared vertices does not split an
 * edge into two near-identical keys.
 */
function isWatertight(triangles: readonly Triangle[], diagonal: number): boolean {
  if (triangles.length === 0) return false;
  // 1 part-per-million of the model size, with a tiny absolute floor for
  // degenerate/zero-size inputs.
  const q = diagonal > 0 ? diagonal * 1e-6 : 1e-9;
  const key = (v: Vertex): string =>
    `${Math.round(v[0] / q)},${Math.round(v[1] / q)},${Math.round(v[2] / q)}`;
  const edges = new Map<string, number>();
  const addEdge = (k1: string, k2: string): void => {
    const ek = k1 < k2 ? `${k1}|${k2}` : `${k2}|${k1}`;
    edges.set(ek, (edges.get(ek) ?? 0) + 1);
  };
  for (const [a, b, c] of triangles) {
    const ka = key(a);
    const kb = key(b);
    const kc = key(c);
    addEdge(ka, kb);
    addEdge(kb, kc);
    addEdge(kc, ka);
  }
  for (const count of edges.values()) {
    if (count !== 2) return false;
  }
  return true;
}

/**
 * Compute geometry metrics from world-space triangles.
 *
 * - surfaceArea = sum of ``0.5 * |(b - a) x (c - a)|``
 * - volume      = ``|sum of a . (b x c) / 6|`` (exact only for closed meshes)
 * - bbox        = axis-aligned min/max over every vertex
 *
 * The unit scale ``s`` scales linear values by ``s``, area by ``s^2`` and
 * volume by ``s^3``.
 */
export function computeMetricsFromTriangles(
  triangles: readonly Triangle[],
  scale = 1,
): GeometryMetrics {
  const n = triangles.length;
  if (n === 0) return { ...EMPTY_METRICS };

  let area = 0;
  let signedVolume = 0;
  let minX = Infinity;
  let minY = Infinity;
  let minZ = Infinity;
  let maxX = -Infinity;
  let maxY = -Infinity;
  let maxZ = -Infinity;

  for (let i = 0; i < n; i++) {
    const [a, b, c] = triangles[i]!;

    // Surface area from the cross product of two edge vectors.
    const abx = b[0] - a[0];
    const aby = b[1] - a[1];
    const abz = b[2] - a[2];
    const acx = c[0] - a[0];
    const acy = c[1] - a[1];
    const acz = c[2] - a[2];
    const crx = aby * acz - abz * acy;
    const cry = abz * acx - abx * acz;
    const crz = abx * acy - aby * acx;
    area += 0.5 * Math.sqrt(crx * crx + cry * cry + crz * crz);

    // Signed tetrahedron volume a . (b x c) / 6, summed over all triangles.
    const bxcx = b[1] * c[2] - b[2] * c[1];
    const bxcy = b[2] * c[0] - b[0] * c[2];
    const bxcz = b[0] * c[1] - b[1] * c[0];
    signedVolume += (a[0] * bxcx + a[1] * bxcy + a[2] * bxcz) / 6;

    // Bounding box.
    for (const v of [a, b, c]) {
      if (v[0] < minX) minX = v[0];
      if (v[1] < minY) minY = v[1];
      if (v[2] < minZ) minZ = v[2];
      if (v[0] > maxX) maxX = v[0];
      if (v[1] > maxY) maxY = v[1];
      if (v[2] > maxZ) maxZ = v[2];
    }
  }

  const dx = maxX - minX;
  const dy = maxY - minY;
  const dz = maxZ - minZ;
  const diagonal = Math.sqrt(dx * dx + dy * dy + dz * dz);
  const watertight = isWatertight(triangles, diagonal);

  const s = scale;
  const s2 = s * s;
  const s3 = s2 * s;

  return {
    surfaceArea: area * s2,
    volume: Math.abs(signedVolume) * s3,
    bbox: {
      min_x: minX * s,
      min_y: minY * s,
      min_z: minZ * s,
      max_x: maxX * s,
      max_y: maxY * s,
      max_z: maxZ * s,
    },
    triangleCount: n,
    watertight,
    longestExtent: Math.max(dx, dy, dz) * s,
  };
}

/**
 * Rotation that brings the given source up-axis to canonical Z-up.
 *
 * A Y-up source is rotated +90 degrees about X so its up axis becomes Z. A
 * Z-up source needs no change. Applying this before measuring keeps the
 * bounding box in Z-up (height = Z), and baking the same rotation into the
 * exported GLB means the viewer's fixed Z-up->Y-up display rotation shows the
 * model upright.
 */
export function upAxisMatrix(up: UpAxis): THREE.Matrix4 {
  const m = new THREE.Matrix4();
  if (up === 'y') m.makeRotationX(Math.PI / 2);
  return m;
}

/** Extract world-space triangles from a single mesh, applying ``matrix`` to
 *  every vertex. Handles both indexed and non-indexed geometry. */
function meshTriangles(mesh: THREE.Mesh, matrix: THREE.Matrix4): Triangle[] {
  const geom = mesh.geometry as THREE.BufferGeometry | undefined;
  const pos = geom?.getAttribute('position') as
    | THREE.BufferAttribute
    | THREE.InterleavedBufferAttribute
    | undefined;
  if (!geom || !pos || pos.count === 0) return [];

  const index = geom.getIndex();
  const tris: Triangle[] = [];
  const vA = new THREE.Vector3();
  const vB = new THREE.Vector3();
  const vC = new THREE.Vector3();

  const read = (i: number, target: THREE.Vector3): void => {
    target.fromBufferAttribute(pos, i).applyMatrix4(matrix);
  };

  if (index) {
    for (let i = 0; i + 2 < index.count; i += 3) {
      read(index.getX(i), vA);
      read(index.getX(i + 1), vB);
      read(index.getX(i + 2), vC);
      tris.push([
        [vA.x, vA.y, vA.z],
        [vB.x, vB.y, vB.z],
        [vC.x, vC.y, vC.z],
      ]);
    }
  } else {
    for (let i = 0; i + 2 < pos.count; i += 3) {
      read(i, vA);
      read(i + 1, vB);
      read(i + 2, vC);
      tris.push([
        [vA.x, vA.y, vA.z],
        [vB.x, vB.y, vB.z],
        [vC.x, vC.y, vC.z],
      ]);
    }
  }
  return tris;
}

/** Best-effort display name for a mesh: its own name, else the nearest named
 *  ancestor below the root, else an empty string (the caller assigns a
 *  fallback and guarantees uniqueness). */
function deriveObjectName(mesh: THREE.Mesh, root: THREE.Object3D): string {
  if (mesh.name && mesh.name.trim()) return mesh.name.trim();
  let cursor: THREE.Object3D | null = mesh.parent;
  while (cursor && cursor !== root.parent) {
    if (cursor.name && cursor.name.trim()) return cursor.name.trim();
    if (cursor === root) break;
    cursor = cursor.parent;
  }
  return '';
}

function unionBBox(a: BoundingBox | null, b: BoundingBox | null): BoundingBox | null {
  if (!a) return b;
  if (!b) return a;
  return {
    min_x: Math.min(a.min_x, b.min_x),
    min_y: Math.min(a.min_y, b.min_y),
    min_z: Math.min(a.min_z, b.min_z),
    max_x: Math.max(a.max_x, b.max_x),
    max_y: Math.max(a.max_y, b.max_y),
    max_z: Math.max(a.max_z, b.max_z),
  };
}

function longestExtentOf(bbox: BoundingBox | null): number {
  if (!bbox) return 0;
  return Math.max(bbox.max_x - bbox.min_x, bbox.max_y - bbox.min_y, bbox.max_z - bbox.min_z);
}

/**
 * Walk a Three.js object tree and measure every mesh in WORLD space.
 *
 * Each mesh becomes one extracted object (and later one BIM element / one GLB
 * node). The mesh world matrix is always applied so scale and rotation are
 * respected; an optional up-axis correction is applied on top so the bounding
 * box comes out in Z-up. Non-mesh nodes (points, lines, lights) are ignored -
 * they carry no surface area or volume.
 */
export function extractSceneMetrics(
  root: THREE.Object3D,
  opts: { upAxis?: UpAxis; scale?: number } = {},
): ExtractionResult {
  const upAxis = opts.upAxis ?? 'y';
  const scale = opts.scale ?? 1;
  root.updateMatrixWorld(true);

  const correction = upAxisMatrix(upAxis);
  const effective = new THREE.Matrix4();
  const objects: ExtractedObject[] = [];

  root.traverse((obj) => {
    if (!(obj instanceof THREE.Mesh)) return;
    effective.multiplyMatrices(correction, obj.matrixWorld);
    const tris = meshTriangles(obj, effective);
    if (tris.length === 0) return;
    const m = computeMetricsFromTriangles(tris, scale);
    objects.push({
      mesh: obj,
      name: deriveObjectName(obj, root),
      area_m2: m.surfaceArea,
      volume_m3: m.volume,
      length_m: m.longestExtent,
      bbox: m.bbox,
      triangleCount: m.triangleCount,
      watertight: m.watertight,
    });
  });

  let area = 0;
  let volume = 0;
  let triangleCount = 0;
  let watertightCount = 0;
  let bbox: BoundingBox | null = null;
  for (const o of objects) {
    area += o.area_m2;
    triangleCount += o.triangleCount;
    bbox = unionBBox(bbox, o.bbox);
    if (o.watertight) {
      watertightCount += 1;
      volume += o.volume_m3;
    }
  }

  return {
    objects,
    totals: {
      area_m2: area,
      volume_m3: volume,
      length_m: longestExtentOf(bbox),
      bbox,
      triangleCount,
      objectCount: objects.length,
      watertightCount,
    },
  };
}

function scaleBBox(bbox: BoundingBox | null, s: number): BoundingBox | null {
  if (!bbox) return null;
  return {
    min_x: bbox.min_x * s,
    min_y: bbox.min_y * s,
    min_z: bbox.min_z * s,
    max_x: bbox.max_x * s,
    max_y: bbox.max_y * s,
    max_z: bbox.max_z * s,
  };
}

/**
 * Re-scale a raw (scale = 1) extraction result to a new unit scale without
 * re-walking the scene. Area scales by ``s^2``, volume by ``s^3`` and linear
 * values by ``s``; counts and watertightness are unchanged. This makes the
 * live unit selector cheap even for large meshes.
 */
export function scaleExtraction(result: ExtractionResult, s: number): ExtractionResult {
  const s2 = s * s;
  const s3 = s2 * s;
  const objects = result.objects.map((o) => ({
    ...o,
    area_m2: o.area_m2 * s2,
    volume_m3: o.volume_m3 * s3,
    length_m: o.length_m * s,
    bbox: scaleBBox(o.bbox, s),
  }));
  const t = result.totals;
  return {
    objects,
    totals: {
      ...t,
      area_m2: t.area_m2 * s2,
      volume_m3: t.volume_m3 * s3,
      length_m: t.length_m * s,
      bbox: scaleBBox(t.bbox, s),
    },
  };
}
