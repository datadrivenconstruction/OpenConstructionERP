// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SnapDetector — screen-space snap refinement for the BIM ruler (W6.6).
 *
 * Raycaster.intersectObjects() returns an arbitrary point on the picked
 * triangle. That is the wrong granularity for engineering measurements: the
 * user wants to snap to a vertex, an edge midpoint, or the foot of the
 * perpendicular onto an edge. This module takes the raw hit and refines it
 * to the closest such feature within a 12 px screen-space radius so the
 * recorded measurement endpoint matches what the user visually pinned.
 */

import * as THREE from 'three';

export type SnapKind = 'vertex' | 'edge_midpoint' | 'edge_perp' | 'none';

export interface SnapResult {
  point: THREE.Vector3;
  kind: SnapKind;
  distancePx: number;
}

/** Triangle face descriptor — matches THREE.Intersection.face shape. */
export interface SnapFace {
  a: number;
  b: number;
  c: number;
}

interface CachedTriangle {
  v0: THREE.Vector3;
  v1: THREE.Vector3;
  v2: THREE.Vector3;
  m0: THREE.Vector3;
  m1: THREE.Vector3;
  m2: THREE.Vector3;
  /** Cached matrix-world snapshot — used to invalidate when a mesh moves. */
  matrixWorldEpoch: number;
}

/** Default screen-space radius in CSS pixels. */
const DEFAULT_SNAP_PX = 12;

/**
 * Project a world-space point to canvas pixel coordinates. Returns `null` if
 * the point is behind the near or beyond the far plane (the projected z is
 * outside the [-1, 1] NDC band).
 */
function projectToCanvasPx(
  world: THREE.Vector3,
  camera: THREE.Camera,
  canvasWidth: number,
  canvasHeight: number,
): { x: number; y: number } | null {
  const ndc = world.clone().project(camera);
  if (ndc.z < -1 || ndc.z > 1) return null;
  return {
    x: (ndc.x * 0.5 + 0.5) * canvasWidth,
    y: (1 - (ndc.y * 0.5 + 0.5)) * canvasHeight,
  };
}

/**
 * Compute the foot of the perpendicular from `p` onto the infinite line
 * through `a` and `b`, then clamp the result back inside the segment so we
 * never return a snap point that sits beyond an endpoint (in which case the
 * nearer vertex would have been picked instead).
 */
function footOnSegment(
  p: THREE.Vector3,
  a: THREE.Vector3,
  b: THREE.Vector3,
): THREE.Vector3 {
  const ab = b.clone().sub(a);
  const lenSq = ab.lengthSq();
  if (lenSq < 1e-12) return a.clone();
  const t = p.clone().sub(a).dot(ab) / lenSq;
  const tClamped = t < 0 ? 0 : t > 1 ? 1 : t;
  return a.clone().add(ab.multiplyScalar(tClamped));
}

export class SnapDetector {
  /** Per-mesh per-face triangle cache. WeakMap so unloading a Mesh releases
   *  the entry automatically. */
  private cache = new WeakMap<THREE.Mesh, Map<number, CachedTriangle>>();

  /** Configurable radius in screen pixels — tests can override. */
  private snapPx: number;

  constructor(snapPx: number = DEFAULT_SNAP_PX) {
    this.snapPx = snapPx;
  }

  /** Allow callers (UI, tests) to override the snap radius. */
  setSnapPx(px: number): void {
    if (Number.isFinite(px) && px > 0) this.snapPx = px;
  }

  /** Drop every cached triangle. Call when geometry is reloaded or after a
   *  bulk transform that invalidates world matrices. */
  clearCache(): void {
    this.cache = new WeakMap();
  }

  /**
   * Refine a raw raycaster hit to the nearest vertex / edge midpoint / edge
   * perpendicular foot, ranked in that priority order, within the configured
   * screen-space radius. Returns `kind: 'none'` when no feature is close
   * enough — callers should fall back to the raw hit in that case.
   */
  refine(
    rawHit: THREE.Vector3,
    face: SnapFace,
    mesh: THREE.Mesh,
    camera: THREE.Camera,
    canvas: HTMLCanvasElement,
    faceIndex?: number,
  ): SnapResult {
    const rect = canvas.getBoundingClientRect();
    const width = rect.width || canvas.width || 1;
    const height = rect.height || canvas.height || 1;

    const cursorPx = projectToCanvasPx(rawHit, camera, width, height);
    if (!cursorPx) {
      return { point: rawHit.clone(), kind: 'none', distancePx: Infinity };
    }

    const triangle = this.getTriangle(mesh, face, faceIndex);
    if (!triangle) {
      return { point: rawHit.clone(), kind: 'none', distancePx: Infinity };
    }

    const radiusSq = this.snapPx * this.snapPx;

    // ── 1. Closest vertex (highest priority). ─────────────────────────
    let bestVertex: THREE.Vector3 | null = null;
    let bestVertexDsq = radiusSq;
    for (const v of [triangle.v0, triangle.v1, triangle.v2]) {
      const px = projectToCanvasPx(v, camera, width, height);
      if (!px) continue;
      const dsq = (px.x - cursorPx.x) ** 2 + (px.y - cursorPx.y) ** 2;
      if (dsq < bestVertexDsq) {
        bestVertexDsq = dsq;
        bestVertex = v;
      }
    }
    if (bestVertex) {
      return {
        point: bestVertex.clone(),
        kind: 'vertex',
        distancePx: Math.sqrt(bestVertexDsq),
      };
    }

    // ── 2. Closest edge midpoint. ─────────────────────────────────────
    let bestMid: THREE.Vector3 | null = null;
    let bestMidDsq = radiusSq;
    for (const m of [triangle.m0, triangle.m1, triangle.m2]) {
      const px = projectToCanvasPx(m, camera, width, height);
      if (!px) continue;
      const dsq = (px.x - cursorPx.x) ** 2 + (px.y - cursorPx.y) ** 2;
      if (dsq < bestMidDsq) {
        bestMidDsq = dsq;
        bestMid = m;
      }
    }
    if (bestMid) {
      return {
        point: bestMid.clone(),
        kind: 'edge_midpoint',
        distancePx: Math.sqrt(bestMidDsq),
      };
    }

    // ── 3. Foot-of-perpendicular onto each edge. ──────────────────────
    const edges: [THREE.Vector3, THREE.Vector3][] = [
      [triangle.v0, triangle.v1],
      [triangle.v1, triangle.v2],
      [triangle.v2, triangle.v0],
    ];
    let bestPerp: THREE.Vector3 | null = null;
    let bestPerpDsq = radiusSq;
    for (const [a, b] of edges) {
      const foot = footOnSegment(rawHit, a, b);
      const px = projectToCanvasPx(foot, camera, width, height);
      if (!px) continue;
      const dsq = (px.x - cursorPx.x) ** 2 + (px.y - cursorPx.y) ** 2;
      if (dsq < bestPerpDsq) {
        bestPerpDsq = dsq;
        bestPerp = foot;
      }
    }
    if (bestPerp) {
      return {
        point: bestPerp.clone(),
        kind: 'edge_perp',
        distancePx: Math.sqrt(bestPerpDsq),
      };
    }

    return { point: rawHit.clone(), kind: 'none', distancePx: Infinity };
  }

  /**
   * Look up — or build — the cached world-space vertex/midpoint set for the
   * given face. We key on (mesh, faceIndex) so adjacent triangles reuse the
   * mesh's outer entry. If `faceIndex` is undefined we synthesize a stable
   * key from the (a, b, c) tuple.
   */
  private getTriangle(
    mesh: THREE.Mesh,
    face: SnapFace,
    faceIndex?: number,
  ): CachedTriangle | null {
    const geometry = mesh.geometry;
    if (!geometry) return null;
    const positionAttr = geometry.getAttribute('position') as
      | THREE.BufferAttribute
      | undefined;
    if (!positionAttr) return null;

    let perMesh = this.cache.get(mesh);
    if (!perMesh) {
      perMesh = new Map();
      this.cache.set(mesh, perMesh);
    }

    // Synthesize a key when faceIndex is not provided. Bitwise mix keeps it
    // collision-free for typical IFC vertex counts (< 2^20 per attribute).
    const key =
      typeof faceIndex === 'number'
        ? faceIndex
        : (face.a * 73856093) ^ (face.b * 19349663) ^ (face.c * 83492791);

    // Cheap epoch comparison: any change to the mesh's local matrix bumps
    // matrixWorldNeedsUpdate. We treat each call's identity-checked matrix
    // as the epoch. If the mesh hasn't moved the cached world points stay
    // valid.
    const epochSource = mesh.matrixWorld.elements;
    const epoch =
      epochSource[0]! +
      epochSource[5]! * 31 +
      epochSource[10]! * 131 +
      epochSource[12]! * 911 +
      epochSource[13]! * 9923 +
      epochSource[14]! * 97939;

    const existing = perMesh.get(key);
    if (existing && existing.matrixWorldEpoch === epoch) {
      return existing;
    }

    const v0 = new THREE.Vector3()
      .fromBufferAttribute(positionAttr, face.a)
      .applyMatrix4(mesh.matrixWorld);
    const v1 = new THREE.Vector3()
      .fromBufferAttribute(positionAttr, face.b)
      .applyMatrix4(mesh.matrixWorld);
    const v2 = new THREE.Vector3()
      .fromBufferAttribute(positionAttr, face.c)
      .applyMatrix4(mesh.matrixWorld);

    const m0 = v0.clone().add(v1).multiplyScalar(0.5);
    const m1 = v1.clone().add(v2).multiplyScalar(0.5);
    const m2 = v2.clone().add(v0).multiplyScalar(0.5);

    const next: CachedTriangle = {
      v0,
      v1,
      v2,
      m0,
      m1,
      m2,
      matrixWorldEpoch: epoch,
    };
    perMesh.set(key, next);
    return next;
  }
}
