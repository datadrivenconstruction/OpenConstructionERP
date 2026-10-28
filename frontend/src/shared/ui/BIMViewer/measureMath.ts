// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * measureMath — pure 3D measurement math used by MeasureManager.
 *
 * Kept dependency-free of Three.js scene state (takes plain {x,y,z} tuples)
 * so it is trivially unit-testable and reusable. Three.Vector3 satisfies the
 * `Vec3` shape structurally, so the MeasureManager can pass its vectors
 * straight through.
 */

export interface Vec3 {
  x: number;
  y: number;
  z: number;
}

/** Euclidean distance between two points. */
export function distance3(a: Vec3, b: Vec3): number {
  const dx = a.x - b.x;
  const dy = a.y - b.y;
  const dz = a.z - b.z;
  return Math.sqrt(dx * dx + dy * dy + dz * dz);
}

/**
 * Area of a (possibly non-planar) polygon in 3D via Newell's method.
 *
 * Newell's method returns the magnitude of the polygon's vector area, which
 * equals the true area for any planar polygon regardless of its orientation
 * in space (the common case for a face traced on a wall / slab / roof) and
 * degrades gracefully — never NaN — for slightly non-planar point sets.
 *
 * Requires ≥ 3 points; fewer returns 0.
 */
export function polygonArea3(points: readonly Vec3[]): number {
  if (points.length < 3) return 0;
  let nx = 0;
  let ny = 0;
  let nz = 0;
  for (let i = 0; i < points.length; i++) {
    const cur = points[i]!;
    const next = points[(i + 1) % points.length]!;
    nx += (cur.y - next.y) * (cur.z + next.z);
    ny += (cur.z - next.z) * (cur.x + next.x);
    nz += (cur.x - next.x) * (cur.y + next.y);
  }
  return Math.sqrt(nx * nx + ny * ny + nz * nz) / 2;
}

/** Total perimeter (closed loop) of a polygon. ≥ 2 points required. */
export function polygonPerimeter3(points: readonly Vec3[]): number {
  if (points.length < 2) return 0;
  let p = 0;
  for (let i = 0; i < points.length; i++) {
    p += distance3(points[i]!, points[(i + 1) % points.length]!);
  }
  return p;
}

/**
 * Interior angle at vertex `b` formed by the rays b→a and b→c, in degrees.
 *
 * Returns 0 when either ray is degenerate (a/c coincides with b). The result
 * is always in [0, 180].
 */
export function angleBetween3(a: Vec3, b: Vec3, c: Vec3): number {
  const v1x = a.x - b.x;
  const v1y = a.y - b.y;
  const v1z = a.z - b.z;
  const v2x = c.x - b.x;
  const v2y = c.y - b.y;
  const v2z = c.z - b.z;
  const l1 = Math.sqrt(v1x * v1x + v1y * v1y + v1z * v1z);
  const l2 = Math.sqrt(v2x * v2x + v2y * v2y + v2z * v2z);
  if (l1 === 0 || l2 === 0) return 0;
  let cos = (v1x * v2x + v1y * v2y + v1z * v2z) / (l1 * l2);
  // Floating-point can push the dot ratio just outside [-1, 1].
  if (cos > 1) cos = 1;
  if (cos < -1) cos = -1;
  return (Math.acos(cos) * 180) / Math.PI;
}

/** Centroid of a point set (used to anchor the on-screen area label). */
export function centroid3(points: readonly Vec3[]): Vec3 {
  if (points.length === 0) return { x: 0, y: 0, z: 0 };
  let x = 0;
  let y = 0;
  let z = 0;
  for (const p of points) {
    x += p.x;
    y += p.y;
    z += p.z;
  }
  const n = points.length;
  return { x: x / n, y: y / n, z: z / n };
}
