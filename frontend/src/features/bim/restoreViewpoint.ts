// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Restore a saved BCF viewpoint back INTO the live 3D scene - the inverse of
 * the capture bridge (bcfBridge.ts / useBcfCapture.ts).
 *
 * "Navigate to issue": given a persisted {@link Viewpoint}, fly the camera to
 * exactly where the issue was raised and mark the elements it was raised
 * against, so a reviewer can jump from the issue list straight to what is
 * flagged in the model. This is the core of a coordination-review workflow.
 *
 * Two facts about our captured viewpoints shape the maths here:
 *  - the stored camera direction is a UNIT vector, so the orbit target
 *    (focal distance) is not recorded and must be reconstructed - we project
 *    the model's content-bounds centre onto the view ray. The camera
 *    orientation (position + direction + up) already fixes the rendered image
 *    exactly; only the pivot depth is inferred, which is visually harmless.
 *  - viewpoints store `element_stable_ids` (IFC GlobalId / RVT UniqueId /
 *    mesh ref), but the scene managers key on the internal element id, so the
 *    caller passes a `stableIdToElementId` resolver. Visibility restore is
 *    therefore best-effort (a mesh may not carry a stable id); the camera
 *    restore is always reliable.
 */

import * as THREE from 'three';

import type { CameraState, ElementManager, SelectionManager } from '@/shared/ui/BIMViewer';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';

import type { Viewpoint } from '@/features/bcf/api';

/** What restore needs from the viewer. All handles are read from the live
 *  `window.__oeBim` bridge by the caller; managers may be null while the scene
 *  is still mounting, in which case only the camera is restored. */
export interface ViewpointRestoreDeps {
  scene: SceneManager;
  elementManager?: ElementManager | null;
  selectionManager?: SelectionManager | null;
  /** Map a viewpoint stable id back to the internal element id the scene
   *  managers use. Returns undefined when the element is not in this model. */
  stableIdToElementId?: (stableId: string) => string | undefined;
}

const vec3 = (v: { x: number; y: number; z: number }): THREE.Vector3 =>
  new THREE.Vector3(v.x, v.y, v.z);

/**
 * Reconstruct an orbit target from a camera position + unit direction. The
 * focal distance is not stored, so project the content-bounds centre onto the
 * ray; fall back to the scene diagonal (or a fixed distance) when there are no
 * bounds. Any positive distance along the ray yields the identical view, so
 * this only affects the orbit pivot, never the rendered frame.
 */
export function reconstructTarget(
  position: THREE.Vector3,
  direction: THREE.Vector3,
  bounds: THREE.Box3 | null,
): THREE.Vector3 {
  const dir = direction.clone();
  if (dir.lengthSq() < 1e-9) dir.set(0, 0, -1);
  dir.normalize();

  let distance = 10;
  if (bounds && !bounds.isEmpty()) {
    const center = bounds.getCenter(new THREE.Vector3());
    const projected = center.clone().sub(position).dot(dir);
    const diagonal = bounds.getSize(new THREE.Vector3()).length();
    distance = Number.isFinite(projected) && projected > 0.5 ? projected : Math.max(diagonal, 1);
  }
  return position.clone().add(dir.multiplyScalar(distance));
}

/** Resolve a viewpoint's stable ids to internal element ids, de-duplicated.
 *  Falls back to the component selection when `element_stable_ids` is empty. */
function resolveElementIds(
  vp: Viewpoint,
  map?: (stableId: string) => string | undefined,
): string[] {
  const raw =
    vp.element_stable_ids && vp.element_stable_ids.length > 0
      ? vp.element_stable_ids
      : (vp.components?.selection ?? []);
  const out: string[] = [];
  const seen = new Set<string>();
  for (const stableId of raw) {
    const internal = map ? map(stableId) : stableId;
    if (internal && !seen.has(internal)) {
      seen.add(internal);
      out.push(internal);
    }
  }
  return out;
}

/**
 * Fly the camera to a saved viewpoint and select the elements it references.
 *
 * Resolves once the camera has settled. Safe to await even if a newer camera
 * move overtakes the flight (the tween rejection is swallowed). Visibility is
 * best-effort - the camera always restores; element selection only lands for
 * meshes that carry a resolvable stable id.
 */
export async function restoreBcfViewpoint(
  vp: Viewpoint,
  deps: ViewpointRestoreDeps,
  opts?: { instant?: boolean },
): Promise<void> {
  const { scene } = deps;
  const persp = vp.perspective_camera;
  const ortho = vp.orthogonal_camera;
  const cam = persp ?? ortho ?? null;
  const ids = resolveElementIds(vp, deps.stableIdToElementId);

  if (cam) {
    const position = vec3(cam.camera_view_point);
    const direction = vec3(cam.camera_direction);
    const up = vec3(cam.camera_up_vector);
    const target = reconstructTarget(position, direction, scene.getContentBounds());

    // Restore the field of view directly - flyTo/setViewpoint never touch it.
    if (persp && Number.isFinite(persp.field_of_view) && persp.field_of_view > 0) {
      scene.camera.fov = persp.field_of_view;
      scene.camera.updateProjectionMatrix();
    }

    if (opts?.instant) {
      scene.setViewpoint(
        { x: position.x, y: position.y, z: position.z },
        { x: target.x, y: target.y, z: target.z },
      );
      scene.camera.up.set(up.x, up.y, up.z);
      scene.requestRender();
    } else {
      try {
        await scene.flyTo({
          position: [position.x, position.y, position.z],
          target: [target.x, target.y, target.z],
          up: [up.x, up.y, up.z],
        } satisfies CameraState);
      } catch {
        // A newer camera move overtook this flight - leave the camera where
        // the newer move put it rather than fighting it.
      }
    }
  }

  if (ids.length > 0) {
    // Selecting (rather than isolating) marks the flagged elements without
    // hiding their context, and clears with a click on empty space.
    deps.selectionManager?.selectByIds(ids, { exclusive: true });
    // With no stored camera, frame the elements so the reviewer still lands on
    // them; with a camera the stored view already frames the issue.
    if (!cam && deps.elementManager) {
      const meshes = ids
        .map((id) => deps.elementManager?.getMesh(id))
        .filter((m): m is THREE.Mesh => Boolean(m));
      if (meshes.length > 0) scene.zoomToSelection(meshes);
    }
  }
}
