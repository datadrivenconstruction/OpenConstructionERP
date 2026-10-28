// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Accelerated picking for the BIM viewer.
 *
 * A click or hover in the viewer raycasts the whole scene. Without an
 * acceleration structure every ray tests every triangle of every mesh, which
 * on a real model (hundreds of meshes, each thousands of triangles) is the
 * dominant cost of selecting or hovering an element. three-mesh-bvh builds a
 * bounding-volume hierarchy per geometry so a ray descends a handful of nodes
 * instead of scanning all triangles.
 *
 * The patch is behaviour-preserving. `acceleratedRaycast` consults the BVH
 * only when the geometry actually has a `boundsTree`; otherwise it delegates
 * to the stock `Mesh.raycast` it captured at import time. Meshes with no
 * bounds tree (placeholder boxes, helpers, highlight outlines) raycast exactly
 * as before. We patch only `Mesh.prototype.raycast`, never
 * `BatchedMesh.prototype.raycast`, so the big-model BatchedMesh path and its
 * `batchHandle` -> elementId resolution are untouched.
 *
 * Element identity is untouched: the BVH changes only WHICH triangles a ray
 * tests, never the object it belongs to, so SelectionManager's
 * node-name -> element-id match keeps resolving the same id.
 */

import * as THREE from 'three';
import {
  acceleratedRaycast,
  computeBoundsTree,
  disposeBoundsTree,
} from 'three-mesh-bvh';

let installed = false;

/**
 * Patch three's prototypes so a geometry can carry a BVH and Mesh raycasts use
 * it. Idempotent - safe to call on every viewer mount.
 */
export function installBVH(): void {
  if (installed) return;
  THREE.BufferGeometry.prototype.computeBoundsTree = computeBoundsTree;
  THREE.BufferGeometry.prototype.disposeBoundsTree = disposeBoundsTree;
  THREE.Mesh.prototype.raycast = acceleratedRaycast;
  installed = true;
}

/** True once {@link installBVH} has patched the prototypes. Test seam. */
export function isBVHInstalled(): boolean {
  return installed;
}

/**
 * Build a bounds tree for one geometry if it is pickable and has none yet.
 * Returns true when the geometry ends up with a bounds tree. Never throws - a
 * geometry that can't be indexed (no position attribute, degenerate, or a
 * builder error) simply keeps the stock raycast path.
 */
export function ensureBoundsTree(geometry: THREE.BufferGeometry | null | undefined): boolean {
  if (!geometry || !geometry.attributes?.position) return false;
  if (geometry.boundsTree) return true;
  installBVH();
  try {
    geometry.computeBoundsTree();
  } catch {
    return false;
  }
  return !!geometry.boundsTree;
}

/** Release a geometry's bounds tree if it has one. Never throws. */
export function disposeBounds(geometry: THREE.BufferGeometry | null | undefined): void {
  if (!geometry || !geometry.boundsTree) return;
  try {
    geometry.disposeBoundsTree();
  } catch {
    /* geometry already partially torn down - nothing to free */
  }
}
