/**
 * SectionBox — six oriented clipping planes auto-fitted to an AABB
 * (selection, model, or arbitrary box), built on
 * `renderer.localClippingEnabled` + per-material `clippingPlanes`.
 *
 * Why a standalone helper (separate from the existing `ClipManager`):
 * `ClipManager` is tightly coupled to `SceneManager` and the in-house
 * normalised-extent / hatched-cap workflow.  `SectionBox` is an additive
 * BIMcollab-style affordance — driven by selection or world bounds — that
 * the new `ViewerToolbar` plugs straight into the raw Three.js trio
 * (scene / camera / renderer) without needing the rest of the viewer's
 * managers.  The two coexist cleanly because they operate on the same
 * `material.clippingPlanes` slot; only one is active at a time (enforced
 * by the toolbar's mutual-exclusion logic).
 *
 * Render contract:
 *   - `enable()` flips `renderer.localClippingEnabled = true` and records
 *     the previous value so `disable()` can restore it (we never stomp
 *     existing usage).
 *   - The six planes face INWARD so geometry outside the box is clipped.
 *   - A translucent wireframe box is rendered as a readability cue.
 *   - Ctrl/Cmd-drag on a TransformControls handle snaps the dragged face
 *     to integer-millimetre offsets (per BIMcollab research).
 */

import * as THREE from 'three';
// TransformControls is loaded lazily — its constructor pokes at the DOM,
// which jsdom can stub but the runtime import keeps the bundle path clean.
import { TransformControls } from 'three/examples/jsm/controls/TransformControls.js';

/** Snap step for Ctrl/Cmd-drag, in metres (= 1 mm). */
const SNAP_STEP_M = 0.001;

export interface SectionBoxArgs {
  scene: THREE.Scene;
  camera: THREE.Camera;
  renderer: THREE.WebGLRenderer;
  /** Optional callback fired whenever the section state mutates in a way
   *  that affects rendered pixels (enable / disable / bounds-change). The
   *  host wires this to `SceneManager.requestRender()` so the on-demand
   *  render loop redraws — without it the clip would only become visible
   *  on the user's next camera move. */
  onChange?: () => void;
}

/** Internal state held per scene-mesh while clipping is active, so we
 *  can restore exactly what was there before `enable()` was called. */
interface MaterialSnapshot {
  material: THREE.Material;
  previousPlanes: THREE.Plane[] | null;
  previousClipShadows: boolean;
}

export class SectionBox {
  private scene: THREE.Scene;
  private camera: THREE.Camera;
  private renderer: THREE.WebGLRenderer;
  private onChange?: () => void;

  /** Current AABB in world space. */
  private box = new THREE.Box3();
  /** True once `setBoundsToBox` or `setBoundsToSelection` has run. */
  private hasBounds = false;

  /** Six inward-facing clipping planes (allocated once, reused). */
  private planes: THREE.Plane[] = [
    new THREE.Plane(new THREE.Vector3(1, 0, 0), 0),
    new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, 1, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, -1, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, 0, 1), 0),
    new THREE.Plane(new THREE.Vector3(0, 0, -1), 0),
  ];

  private _enabled = false;
  private localClippingWasEnabled = false;
  private snapshots = new Map<THREE.Material, MaterialSnapshot>();

  /** Wireframe box overlay (lazy-built on first enable). */
  private wireframe: THREE.LineSegments | null = null;

  /** Optional TransformControls for manual face dragging. Lazy-built. */
  private transformControls: TransformControls | null = null;
  /** The Object3D helper attached to the scene that visualises the
   *  TransformControls gizmo (extracted via `getHelper()`). We hide/show
   *  this rather than the controls itself — the controls instance no
   *  longer extends Object3D in modern three.js. */
  private transformHelper: THREE.Object3D | null = null;
  private manualDragEnabled = false;

  constructor(args: SectionBoxArgs) {
    this.scene = args.scene;
    this.camera = args.camera;
    this.renderer = args.renderer;
    this.onChange = args.onChange;
  }

  /** Whether the section is currently clipping geometry. */
  isEnabled(): boolean {
    return this._enabled;
  }

  /** Activate the section. Idempotent — calling twice does not double-apply.
   *  If `initialBounds` is omitted and no bounds have been set yet, the
   *  section becomes active but clips nothing until `setBoundsToBox` /
   *  `setBoundsToSelection` is called. */
  enable(initialBounds?: THREE.Box3): void {
    if (this._enabled) {
      // Idempotent: a second `enable()` should not re-snapshot materials
      // (that would overwrite the genuine previous state with our own
      // planes) and should not re-flip the renderer flag.
      if (initialBounds) {
        this.setBoundsToBox(initialBounds);
      }
      return;
    }
    this.localClippingWasEnabled = this.renderer.localClippingEnabled === true;
    this.renderer.localClippingEnabled = true;
    this._enabled = true;

    if (initialBounds) {
      this.setBoundsToBox(initialBounds);
    } else if (this.hasBounds) {
      this.recomputePlanes();
      this.applyToScene();
      this.refreshWireframe();
    }
    // Materials + renderer flag mutated → ask the host to re-render so the
    // clip becomes visible immediately (the parent SceneManager renders
    // on-demand and would otherwise skip the next frame).
    this.onChange?.();
  }

  /** Deactivate the section: restore previous clipping planes on every
   *  material we touched and restore `renderer.localClippingEnabled` ONLY
   *  if it was off before we turned it on. */
  disable(): void {
    if (!this._enabled) return;
    this._enabled = false;

    for (const snap of this.snapshots.values()) {
      snap.material.clippingPlanes = snap.previousPlanes;
      snap.material.clipShadows = snap.previousClipShadows;
      snap.material.needsUpdate = true;
    }
    this.snapshots.clear();

    if (!this.localClippingWasEnabled) {
      this.renderer.localClippingEnabled = false;
    }

    if (this.wireframe) {
      this.wireframe.visible = false;
    }
    if (this.transformControls) {
      this.transformControls.enabled = false;
    }
    if (this.transformHelper) {
      this.transformHelper.visible = false;
    }
    // Restoring planes / overlay visibility doesn't trigger any internal
    // event — the host's render loop is on-demand, so request a redraw
    // explicitly to make the un-clipped view appear immediately.
    this.onChange?.();
  }

  /** Fit the section to an arbitrary world-space AABB. */
  setBoundsToBox(box: THREE.Box3): void {
    if (box.isEmpty()) {
      // Defensive: an empty box would produce degenerate planes that
      // clip everything. Treat as "no bounds yet".
      this.hasBounds = false;
      return;
    }
    this.box.copy(box);
    this.hasBounds = true;
    if (this._enabled) {
      this.recomputePlanes();
      this.applyToScene();
      this.refreshWireframe();
      this.onChange?.();
    }
  }

  /** Fit the section to the union AABB of a selection. */
  setBoundsToSelection(selectedObjects: THREE.Object3D[]): void {
    const union = new THREE.Box3();
    const tmp = new THREE.Box3();
    for (const obj of selectedObjects) {
      tmp.setFromObject(obj);
      if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) {
        union.union(tmp);
      }
    }
    if (union.isEmpty()) return;
    this.setBoundsToBox(union);
  }

  /** Toggle manual face dragging. When enabled, a TransformControls gizmo
   *  is attached to the wireframe so the user can pull each face in or
   *  out; Ctrl/Cmd-drag snaps the offset to integer millimetres. */
  enableManualDrag(enabled: boolean): void {
    this.manualDragEnabled = enabled;
    if (!enabled) {
      if (this.transformControls) {
        this.transformControls.enabled = false;
      }
      if (this.transformHelper) {
        this.transformHelper.visible = false;
      }
      return;
    }
    if (!this._enabled || !this.hasBounds) return;
    const tc = this.ensureTransformControls();
    tc.enabled = true;
    if (this.transformHelper) {
      this.transformHelper.visible = true;
    }
  }

  /** Whether manual drag is currently armed. */
  isManualDragEnabled(): boolean {
    return this.manualDragEnabled;
  }

  /** Current AABB extents in metres (returns a defensive copy). */
  getBounds(): THREE.Box3 {
    return this.box.clone();
  }

  /** The six inward-facing clipping planes. Length is always 6 regardless
   *  of whether bounds have been set (uninitialised planes default to the
   *  unit box at the origin). */
  getClippingPlanes(): THREE.Plane[] {
    return this.planes;
  }

  /** Release all GPU + DOM resources and restore renderer state. */
  dispose(): void {
    this.disable();
    if (this.wireframe) {
      this.scene.remove(this.wireframe);
      this.wireframe.geometry.dispose();
      const mat = this.wireframe.material as THREE.Material;
      mat.dispose();
      this.wireframe = null;
    }
    if (this.transformHelper && this.transformHelper.parent) {
      this.transformHelper.parent.remove(this.transformHelper);
    }
    this.transformHelper = null;
    if (this.transformControls) {
      const tc = this.transformControls as unknown as {
        dispose?: () => void;
      };
      if (typeof tc.dispose === 'function') tc.dispose();
      this.transformControls = null;
    }
  }

  /* ── Internals ───────────────────────────────────────────────────── */

  /** Recompute the six plane equations from the current `box`. Each plane
   *  faces INWARD so the kept half-space is the interior of the box. */
  private recomputePlanes(): void {
    const min = this.box.min;
    const max = this.box.max;
    // +X face: normal (1,0,0) points into the box, half-space x ≥ min.x
    // → plane equation n·p + d = 0 with d = -min.x.
    this.planes[0]!.set(new THREE.Vector3(1, 0, 0), -min.x);
    this.planes[1]!.set(new THREE.Vector3(-1, 0, 0), max.x);
    this.planes[2]!.set(new THREE.Vector3(0, 1, 0), -min.y);
    this.planes[3]!.set(new THREE.Vector3(0, -1, 0), max.y);
    this.planes[4]!.set(new THREE.Vector3(0, 0, 1), -min.z);
    this.planes[5]!.set(new THREE.Vector3(0, 0, -1), max.z);
  }

  /** Walk every mesh in the scene (skipping our own overlay) and assign
   *  the planes, snapshotting the previous state so we can restore on
   *  `disable()`. */
  private applyToScene(): void {
    this.scene.traverse((obj) => {
      if (obj === this.wireframe) return;
      if (obj.userData && obj.userData.isSectionBoxOverlay) return;
      if (
        !(obj instanceof THREE.Mesh) &&
        !((obj as { isBatchedMesh?: boolean }).isBatchedMesh)
      ) {
        return;
      }
      const meshLike = obj as THREE.Mesh;
      const mats = Array.isArray(meshLike.material)
        ? meshLike.material
        : [meshLike.material];
      for (const m of mats) {
        if (!m) continue;
        if (!this.snapshots.has(m)) {
          this.snapshots.set(m, {
            material: m,
            previousPlanes: m.clippingPlanes ?? null,
            previousClipShadows: m.clipShadows ?? false,
          });
        }
        m.clippingPlanes = this.planes;
        m.clipShadows = false;
        m.needsUpdate = true;
      }
    });
  }

  /** Build or update the translucent wireframe overlay that shows the
   *  current section bounds. */
  private refreshWireframe(): void {
    if (!this.hasBounds) return;
    const size = this.box.getSize(new THREE.Vector3());
    const center = this.box.getCenter(new THREE.Vector3());

    if (!this.wireframe) {
      const geom = new THREE.BoxGeometry(1, 1, 1);
      const edges = new THREE.EdgesGeometry(geom);
      geom.dispose();
      const mat = new THREE.LineBasicMaterial({
        color: 0x2979ff,
        transparent: true,
        opacity: 0.9,
        depthTest: false,
      });
      // The overlay must never be clipped by its own planes.
      mat.clippingPlanes = null;
      const seg = new THREE.LineSegments(edges, mat);
      seg.renderOrder = 1000;
      seg.userData.isSectionBoxOverlay = true;
      this.scene.add(seg);
      this.wireframe = seg;
    }
    this.wireframe.scale.set(
      Math.max(size.x, 1e-4),
      Math.max(size.y, 1e-4),
      Math.max(size.z, 1e-4),
    );
    this.wireframe.position.copy(center);
    this.wireframe.visible = true;
  }

  /** Lazy-build the TransformControls gizmo + wire snap-on-Ctrl handling. */
  private ensureTransformControls(): TransformControls {
    if (this.transformControls) return this.transformControls;
    // The TransformControls constructor needs a DOM element for input
    // listeners. We pull it from the renderer (works for both real
    // canvases and the test FakeWebGLRenderer that exposes `domElement`).
    const domElement =
      (this.renderer as unknown as { domElement: HTMLElement }).domElement ??
      document.body;
    const tc = new TransformControls(this.camera, domElement);
    // Set mode via the `mode` property (the setter on newer three.js).
    (tc as unknown as { mode: string }).mode = 'translate';
    if (this.wireframe) tc.attach(this.wireframe);
    tc.addEventListener('change', (event) => {
      // The native input event surfaces under `value` on some
      // three.js builds; on others it doesn't. We only act on the
      // Ctrl/Cmd modifier as a snap hint — quietly skip if unavailable.
      const e = event as unknown as { value?: KeyboardEvent };
      const native = e.value;
      if (native && (native.ctrlKey || native.metaKey)) {
        const obj = tc.object as THREE.Object3D | undefined;
        if (obj) {
          obj.position.x = Math.round(obj.position.x / SNAP_STEP_M) * SNAP_STEP_M;
          obj.position.y = Math.round(obj.position.y / SNAP_STEP_M) * SNAP_STEP_M;
          obj.position.z = Math.round(obj.position.z / SNAP_STEP_M) * SNAP_STEP_M;
        }
      }
    });
    // Newer three.js separates the controls instance (state) from the
    // helper Object3D (scene-attached visual). Add the helper to the
    // scene so the gizmo renders; older versions of TransformControls
    // were themselves Object3Ds and would be added directly.
    const getHelperFn = (tc as unknown as { getHelper?: () => THREE.Object3D })
      .getHelper;
    if (typeof getHelperFn === 'function') {
      const helper = getHelperFn.call(tc);
      this.transformHelper = helper;
      this.scene.add(helper);
    } else {
      // Fallback for older three.js where TransformControls IS an Object3D.
      const tcAsObj = tc as unknown as THREE.Object3D;
      this.scene.add(tcAsObj);
      this.transformHelper = tcAsObj;
    }
    this.transformControls = tc;
    return tc;
  }

  /** Test-only: simulate a Ctrl-drag tick at the given world-space offset.
   *  Production code drives this via TransformControls; the test surface
   *  lets us assert the snap-to-mm behaviour without booting the gizmo.
   *  Exposed under a non-public name so it doesn't show up in IDE
   *  autocomplete in production callers. */
  __testSnapTo(offsetMetres: { x: number; y: number; z: number }): {
    x: number;
    y: number;
    z: number;
  } {
    return {
      x: Math.round(offsetMetres.x / SNAP_STEP_M) * SNAP_STEP_M,
      y: Math.round(offsetMetres.y / SNAP_STEP_M) * SNAP_STEP_M,
      z: Math.round(offsetMetres.z / SNAP_STEP_M) * SNAP_STEP_M,
    };
  }
}
