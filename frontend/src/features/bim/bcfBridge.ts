// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Concrete BcfViewerBridge backed by the shared BIM viewer's SceneManager.
 *
 * useBcfCapture (features/bcf) is deliberately viewer-agnostic: it takes a
 * BcfViewerBridge that yields the camera, the selected element ids and a PNG
 * snapshot. This factory builds that bridge from a live SceneManager plus a
 * getter for the current selection's stable ids, so "raise issue here" records
 * a real viewpoint (camera + selection + snapshot) from whatever model is on
 * screen.
 *
 * The snapshot goes through SceneManager.getScreenshot(), which forces a
 * synchronous render before reading the pixels - the renderer is created
 * without preserveDrawingBuffer, so a plain canvas.toDataURL() would read a
 * cleared buffer and capture a blank frame. Every getter reads its source
 * lazily and tolerates a null scene, so the bridge identity can stay stable
 * while the viewer mounts.
 */

import type { BcfViewerBridge, ViewerCameraSnapshot } from '@/features/bcf';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';

/**
 * Build a BcfViewerBridge from lazy accessors.
 *
 * @param getScene returns the live SceneManager, or null before it mounts.
 * @param getGuids returns the currently selected elements' stable ids (the BCF
 *   GUIDs). Pass the ids the parent already tracks via onSelectionChange so the
 *   viewpoint's component selection matches what the user sees on screen.
 */
export function makeBcfBridge(
  getScene: () => SceneManager | null,
  getGuids: () => string[],
): BcfViewerBridge {
  return {
    getCamera(): ViewerCameraSnapshot | null {
      const scene = getScene();
      if (!scene) return null;
      const cam = scene.camera;
      const target = scene.controls.target;
      // Look direction is target minus eye, normalised (BCF camera_direction).
      const dx = target.x - cam.position.x;
      const dy = target.y - cam.position.y;
      const dz = target.z - cam.position.z;
      const len = Math.hypot(dx, dy, dz) || 1;
      return {
        position: { x: cam.position.x, y: cam.position.y, z: cam.position.z },
        direction: { x: dx / len, y: dy / len, z: dz / len },
        up: { x: cam.up.x, y: cam.up.y, z: cam.up.z },
        // three.js PerspectiveCamera.fov is vertical degrees - the same
        // convention BCF field_of_view uses, so it maps straight through.
        fieldOfView: cam.fov,
        orthogonal: false,
      };
    },
    getSelectedGuids(): string[] {
      return getGuids();
    },
    getCanvas(): HTMLCanvasElement | null {
      return getScene()?.renderer.domElement ?? null;
    },
    getSnapshotBase64(): string | null {
      // 1600x900 keeps the base64 payload bounded (~a few hundred KB) while
      // staying legible; getScreenshot forces a synchronous render first.
      const url = getScene()?.getScreenshot({ width: 1600, height: 900 });
      if (!url) return null;
      const comma = url.indexOf(',');
      return comma >= 0 ? url.slice(comma + 1) : null;
    },
  };
}
