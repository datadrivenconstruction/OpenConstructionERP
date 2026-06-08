/**
 * ClipManager — interactive section box + single clipping plane
 * (coordination-tool grade) built on Three.js `renderer.localClippingEnabled` +
 * per-material `clippingPlanes`.
 *
 * Two independent, mutually-exclusive cut modes:
 *
 *   - **Section box** — six axis-aligned planes that carve a rectangular
 *     volume out of the model.  A wireframe `Box3` helper shows the live
 *     extent; the user shrinks/grows each face with the control sliders.
 *   - **Single plane** — one arbitrary half-space cut.  The user picks the
 *     axis (X / Y / Z) and slides the offset; the cut direction can be
 *     flipped to keep either side.
 *
 * Why a manager (not inline in BIMViewer): the cut planes have to be applied
 * to *every* material in the scene — placeholder boxes, COLLADA meshes, and
 * the BatchedMesh perf path — and re-applied whenever geometry streams in
 * after the user already enabled clipping.  Centralising that here keeps the
 * BIMViewer wrapper thin and mirrors how SceneManager / ElementManager own
 * their slice of Three.js state.
 *
 * Clean cut: the planes slice geometry exactly at the plane (no capping
 * surface).  Capping a soup of open/non-manifold IFC/RVT meshes reliably is
 * out of scope and would need a stencil pre-pass per frame — explicitly a
 * non-goal per the brief ("capping optional but at least clean cut").
 */

import * as THREE from 'three';
import type { SceneManager } from './SceneManager';

export type ClipMode = 'none' | 'box' | 'plane';
export type ClipAxis = 'x' | 'y' | 'z';

/** Adjustable hatching cap appearance.
 *
 *   - `density` — stripe cycles per world unit (default 8).
 *   - `angleDeg` — rotation of the stripe pattern within the cap plane (0–360).
 *   - `alpha`    — opacity of the hatch fill in [0, 1].
 */
export interface ClipCapStyle {
  density?: number;
  angleDeg?: number;
  alpha?: number;
}

/** Normalised box extent in [0, 1] per face (1 = full model on that face). */
export interface ClipBoxExtent {
  minX: number;
  maxX: number;
  minY: number;
  maxY: number;
  minZ: number;
  maxZ: number;
}

export interface ClipPlaneState {
  axis: ClipAxis;
  /** Normalised offset in [0, 1] along the axis (0 = min, 1 = max). */
  offset: number;
  /** When true the kept half-space is flipped. */
  flipped: boolean;
}

export interface ClipManagerCallbacks {
  /** Fired whenever the active mode changes so the React layer can mirror it. */
  onModeChange?: (mode: ClipMode) => void;
}

const FULL_BOX: ClipBoxExtent = {
  minX: 0,
  maxX: 1,
  minY: 0,
  maxY: 1,
  minZ: 0,
  maxZ: 1,
};

/** Clamp helper — keeps the two faces of an axis from crossing over. */
function clamp01(v: number): number {
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

export class ClipManager {
  private sceneManager: SceneManager;
  private callbacks: ClipManagerCallbacks;

  private _mode: ClipMode = 'none';
  private _boxExtent: ClipBoxExtent = { ...FULL_BOX };
  private _plane: ClipPlaneState = { axis: 'y', offset: 0.5, flipped: false };

  /** World-space bounding box of the loaded model. Recomputed lazily. */
  private modelBox = new THREE.Box3();
  private modelBoxValid = false;

  /** The six box planes (reused across updates — never reallocated). */
  private boxPlanes: THREE.Plane[] = [
    new THREE.Plane(new THREE.Vector3(1, 0, 0), 0),
    new THREE.Plane(new THREE.Vector3(-1, 0, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, 1, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, -1, 0), 0),
    new THREE.Plane(new THREE.Vector3(0, 0, 1), 0),
    new THREE.Plane(new THREE.Vector3(0, 0, -1), 0),
  ];
  private singlePlane = new THREE.Plane(new THREE.Vector3(0, -1, 0), 0);

  /** Live wireframe box that visualises the section volume. */
  private boxHelper: THREE.LineSegments | null = null;

  /** Section cap state. One mesh per active clip plane is reused across
   *  updates; in `plane` mode there is exactly one cap, in `box` mode there
   *  are up to six (one per face). We do not render box caps yet — the box
   *  helper itself is a sufficient readability cue — but the array is keyed
   *  by plane index to make a future extension trivial.
   *
   *  Implementation note (re: the brief): three.js' material clipping uses
   *  `gl.clipDistance`, not the stencil buffer; a true stencil cap would
   *  require us to monkey-patch the renderer's render-list to inject the
   *  back/front face passes per material, which is brittle across three.js
   *  releases. We therefore went with the "translucent finite quad on the
   *  plane with a hatch shader" approach the brief explicitly allows as the
   *  simpler fallback — it reads as an engineering section because the cut
   *  interior behind the quad is invisible.
   */
  private capMeshes: THREE.Mesh[] = [];
  private _capEnabled = true;
  private _capColor = new THREE.Color(0x2979ff);
  private _capStyle: Required<ClipCapStyle> = {
    density: 8,
    angleDeg: 45,
    alpha: 0.5,
  };

  constructor(sceneManager: SceneManager, callbacks: ClipManagerCallbacks = {}) {
    this.sceneManager = sceneManager;
    this.callbacks = callbacks;
    // Local clipping is opt-in per renderer; turning it on once is harmless
    // when no planes are assigned (the default state).
    this.sceneManager.renderer.localClippingEnabled = true;
  }

  get mode(): ClipMode {
    return this._mode;
  }

  getBoxExtent(): ClipBoxExtent {
    return { ...this._boxExtent };
  }

  getPlaneState(): ClipPlaneState {
    return { ...this._plane };
  }

  /** Recompute the model bounding box from current scene content. Skips
   *  helpers / lights / grid the same way SceneManager.zoomToFit does. */
  private ensureModelBox(): void {
    if (this.modelBoxValid) return;
    this.sceneManager.scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    this.sceneManager.scene.traverse((obj) => {
      if (
        obj instanceof THREE.GridHelper ||
        obj instanceof THREE.AxesHelper ||
        obj instanceof THREE.Light ||
        obj instanceof THREE.Camera ||
        obj === this.boxHelper
      ) {
        return;
      }
      if (obj instanceof THREE.Mesh && obj.geometry) {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
        tmp.setFromObject(obj);
        if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) box.union(tmp);
      }
    });
    if (!box.isEmpty()) {
      this.modelBox.copy(box);
      this.modelBoxValid = true;
    }
  }

  /** Invalidate the cached model box — call after geometry (re)loads so the
   *  next clip update fits the new model rather than the old footprint. */
  invalidateModelBox(): void {
    this.modelBoxValid = false;
    if (this._mode !== 'none') {
      // Geometry that streamed in after clipping was enabled has fresh
      // materials with no clippingPlanes set — re-apply so the new meshes
      // are also cut.
      this.apply();
    }
  }

  /** Switch cut mode. Passing the current mode again is a no-op. */
  setMode(mode: ClipMode): void {
    if (this._mode === mode) return;
    this._mode = mode;
    this.apply();
    this.callbacks.onModeChange?.(mode);
  }

  /** Reset extents/plane to defaults AND disable clipping entirely. */
  reset(): void {
    this._boxExtent = { ...FULL_BOX };
    this._plane = { axis: 'y', offset: 0.5, flipped: false };
    this.setMode('none');
  }

  /** Update one or more box faces (normalised 0..1). Opposing faces are
   *  clamped so they can never cross (min always ≤ max with a 1 % gap). */
  setBoxExtent(patch: Partial<ClipBoxExtent>): void {
    const gap = 0.01;
    const next: ClipBoxExtent = { ...this._boxExtent, ...patch };
    next.minX = clamp01(next.minX);
    next.maxX = clamp01(next.maxX);
    next.minY = clamp01(next.minY);
    next.maxY = clamp01(next.maxY);
    next.minZ = clamp01(next.minZ);
    next.maxZ = clamp01(next.maxZ);
    if (next.minX > next.maxX - gap) next.minX = next.maxX - gap;
    if (next.minY > next.maxY - gap) next.minY = next.maxY - gap;
    if (next.minZ > next.maxZ - gap) next.minZ = next.maxZ - gap;
    next.minX = clamp01(next.minX);
    next.minY = clamp01(next.minY);
    next.minZ = clamp01(next.minZ);
    this._boxExtent = next;
    if (this._mode === 'box') this.apply();
  }

  /** Toggle the hatched section cap. When disabled the cap mesh is disposed
   *  immediately; re-enabling rebuilds it on the next apply(). */
  setCapEnabled(enabled: boolean): void {
    if (this._capEnabled === enabled) return;
    this._capEnabled = enabled;
    if (!enabled) {
      this.disposeCapMeshes();
      this.sceneManager.requestRender();
    } else if (this._mode !== 'none') {
      this.apply();
    }
  }

  /** Whether the section cap is currently enabled. */
  get capEnabled(): boolean {
    return this._capEnabled;
  }

  /** Update the hatch fill colour. Accepts anything THREE.Color accepts
   *  (hex number, CSS string, Color instance). Updates live materials in
   *  place so the change is visible without a full re-apply. */
  setCapColor(color: THREE.ColorRepresentation): void {
    this._capColor.set(color);
    for (const m of this.capMeshes) {
      const mat = m.material as THREE.ShaderMaterial;
      const uColor = mat.uniforms['uColor'];
      if (uColor) uColor.value.copy(this._capColor);
    }
    this.sceneManager.requestRender();
  }

  /** Update one or more hatch style fields. Out-of-range values are clamped
   *  silently (density ≥ 1e-4, alpha into [0, 1], angle mod 360) so the UI
   *  layer can wire sliders directly without pre-validating. */
  setCapStyle(style: ClipCapStyle): void {
    if (style.density !== undefined && Number.isFinite(style.density)) {
      this._capStyle.density = Math.max(1e-4, style.density);
    }
    if (style.angleDeg !== undefined && Number.isFinite(style.angleDeg)) {
      let a = style.angleDeg % 360;
      if (a < 0) a += 360;
      this._capStyle.angleDeg = a;
    }
    if (style.alpha !== undefined && Number.isFinite(style.alpha)) {
      this._capStyle.alpha = Math.min(1, Math.max(0, style.alpha));
    }
    for (const m of this.capMeshes) {
      const mat = m.material as THREE.ShaderMaterial;
      const uDensity = mat.uniforms['uDensity'];
      const uAngle = mat.uniforms['uAngleRad'];
      const uAlpha = mat.uniforms['uAlpha'];
      if (uDensity) uDensity.value = this._capStyle.density;
      if (uAngle) uAngle.value = (this._capStyle.angleDeg * Math.PI) / 180;
      if (uAlpha) uAlpha.value = this._capStyle.alpha;
    }
    this.sceneManager.requestRender();
  }

  /** Current cap appearance — useful for round-tripping into Saved Views. */
  getCapStyle(): Required<ClipCapStyle> {
    return { ...this._capStyle };
  }

  /** Update the single-plane state (axis / offset / flipped). */
  setPlaneState(patch: Partial<ClipPlaneState>): void {
    this._plane = {
      ...this._plane,
      ...patch,
      offset:
        patch.offset !== undefined ? clamp01(patch.offset) : this._plane.offset,
    };
    if (this._mode === 'plane') this.apply();
  }

  /** Recompute plane constants from the current model box + state and assign
   *  the active plane set to every material in the scene. */
  private apply(): void {
    this.ensureModelBox();

    if (this._mode === 'none' || !this.modelBoxValid) {
      this.assignPlanes(null);
      this.removeBoxHelper();
      this.disposeCapMeshes();
      this.sceneManager.requestRender();
      return;
    }

    const min = this.modelBox.min;
    const max = this.modelBox.max;
    const sx = max.x - min.x;
    const sy = max.y - min.y;
    const sz = max.z - min.z;

    if (this._mode === 'box') {
      const e = this._boxExtent;
      const x0 = min.x + sx * e.minX;
      const x1 = min.x + sx * e.maxX;
      const y0 = min.y + sy * e.minY;
      const y1 = min.y + sy * e.maxY;
      const z0 = min.z + sz * e.minZ;
      const z1 = min.z + sz * e.maxZ;

      // Each plane keeps the half-space its normal points INTO.
      // +X face: normal (1,0,0), keep x ≥ x0  → constant = -x0
      this.boxPlanes[0]!.set(new THREE.Vector3(1, 0, 0), -x0);
      this.boxPlanes[1]!.set(new THREE.Vector3(-1, 0, 0), x1);
      this.boxPlanes[2]!.set(new THREE.Vector3(0, 1, 0), -y0);
      this.boxPlanes[3]!.set(new THREE.Vector3(0, -1, 0), y1);
      this.boxPlanes[4]!.set(new THREE.Vector3(0, 0, 1), -z0);
      this.boxPlanes[5]!.set(new THREE.Vector3(0, 0, -1), z1);

      this.assignPlanes(this.boxPlanes);
      this.updateBoxHelper(
        new THREE.Box3(
          new THREE.Vector3(x0, y0, z0),
          new THREE.Vector3(x1, y1, z1),
        ),
      );
      // Section caps for the box are intentionally omitted — the live wireframe
      // already disambiguates the clip volume and stacking six hatch quads
      // (one per face) clutters the view. Leave the array empty so the
      // box-mode render path stays cap-free.
      this.disposeCapMeshes();
    } else {
      // Single plane.
      const axis = this._plane.axis;
      const normal = new THREE.Vector3(
        axis === 'x' ? 1 : 0,
        axis === 'y' ? 1 : 0,
        axis === 'z' ? 1 : 0,
      );
      const lo = axis === 'x' ? min.x : axis === 'y' ? min.y : min.z;
      const span = axis === 'x' ? sx : axis === 'y' ? sy : sz;
      const cut = lo + span * this._plane.offset;
      if (this._plane.flipped) normal.negate();
      // Keep the half-space the normal points into → constant = -n·p where
      // p is any point on the plane (here the axis-aligned cut coordinate).
      const constant = this._plane.flipped ? cut : -cut;
      this.singlePlane.set(normal, constant);
      this.assignPlanes([this.singlePlane]);
      this.removeBoxHelper();
      if (this._capEnabled) {
        this.updateSinglePlaneCap();
      } else {
        this.disposeCapMeshes();
      }
    }

    this.sceneManager.requestRender();
  }

  /** Build (or refresh) the single hatched cap quad for the active clip plane.
   *
   *  Sized to the current model bounding box so the hatch covers the entire
   *  visible cross-section regardless of how the user pans the plane. The
   *  quad is placed exactly on the plane and oriented so its +Z normal
   *  matches the plane's normal — that puts the hatched face toward the
   *  retained half-space, which is what an engineer expects to see when
   *  looking AT the cut.
   */
  private updateSinglePlaneCap(): void {
    const plane = this.singlePlane;
    const normal = plane.normal.clone().normalize();
    // Point on the plane: project the model centre onto the plane.
    const centre = this.modelBox.getCenter(new THREE.Vector3());
    const distance = plane.distanceToPoint(centre);
    const origin = centre.clone().sub(normal.clone().multiplyScalar(distance));

    // Quad sized to slightly exceed the model bounding-sphere diameter so
    // the cap covers any rotated cross-section.
    const size = this.modelBox.getSize(new THREE.Vector3());
    const diag = size.length();
    const quadSize = Math.max(diag * 1.05, 1);

    let cap = this.capMeshes[0];
    if (!cap) {
      cap = this.makeCapMesh();
      this.sceneManager.scene.add(cap);
      this.capMeshes = [cap];
    }
    cap.scale.set(quadSize, quadSize, 1);
    cap.position.copy(origin);
    cap.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), normal);
    cap.visible = true;
    const mat = cap.material as THREE.ShaderMaterial;
    const uColor = mat.uniforms['uColor'];
    if (uColor) uColor.value.copy(this._capColor);
  }

  /** Build a 1×1 quad mesh on Z=0 with the hatching ShaderMaterial. The
   *  caller scales / positions / orients it per-frame. */
  private makeCapMesh(): THREE.Mesh {
    const geom = new THREE.PlaneGeometry(1, 1);
    const mat = new THREE.ShaderMaterial({
      uniforms: {
        uColor: { value: this._capColor.clone() },
        uAlpha: { value: this._capStyle.alpha },
        uDensity: { value: this._capStyle.density },
        uAngleRad: { value: (this._capStyle.angleDeg * Math.PI) / 180 },
      },
      vertexShader: `
        varying vec2 vUv;
        void main() {
          vUv = uv;
          gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
        }
      `,
      fragmentShader: `
        precision mediump float;
        varying vec2 vUv;
        uniform vec3 uColor;
        uniform float uAlpha;
        uniform float uDensity;
        uniform float uAngleRad;
        void main() {
          // Rotate the UV inside the quad plane so the stripes can be tilted
          // independently of the clip-plane orientation.
          float c = cos(uAngleRad);
          float s = sin(uAngleRad);
          vec2 uv = vUv - 0.5;
          vec2 rotated = vec2(c * uv.x - s * uv.y, s * uv.x + c * uv.y);
          float coord = (rotated.x - rotated.y);
          float h = step(0.5, fract(coord * uDensity));
          // Mix the stripe band with the background so the cap is hatched,
          // not solid: alpha rides only on the stripe.
          gl_FragColor = vec4(uColor, h * uAlpha);
        }
      `,
      transparent: true,
      side: THREE.DoubleSide,
      depthWrite: false,
      depthTest: true,
    });
    // The cap itself must NEVER be clipped by the plane it visualises —
    // otherwise it disappears the instant the user activates clipping.
    mat.clippingPlanes = null;
    const mesh = new THREE.Mesh(geom, mat);
    mesh.renderOrder = 1001;
    mesh.userData.isClipCap = true;
    return mesh;
  }

  /** Detach + dispose every cap mesh. Safe to call from any state. */
  private disposeCapMeshes(): void {
    for (const m of this.capMeshes) {
      this.sceneManager.scene.remove(m);
      m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[];
      if (Array.isArray(mat)) mat.forEach((mm) => mm.dispose());
      else mat.dispose();
    }
    this.capMeshes = [];
  }

  /** Walk every mesh and set (or clear) its material clippingPlanes. The
   *  box helper and the section cap meshes are excluded — both visualise the
   *  clip itself and must never be clipped by their own planes. */
  private assignPlanes(planes: THREE.Plane[] | null): void {
    this.sceneManager.scene.traverse((obj) => {
      if (obj === this.boxHelper) return;
      if (obj.userData && obj.userData.isClipCap) return;
      if (!(obj instanceof THREE.Mesh) && !(obj instanceof THREE.BatchedMesh)) {
        return;
      }
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material];
      for (const mat of mats) {
        if (!mat) continue;
        mat.clippingPlanes = planes;
        mat.clipShadows = false;
        mat.needsUpdate = true;
      }
    });
  }

  private ensureBoxHelper(): THREE.LineSegments {
    if (this.boxHelper) return this.boxHelper;
    // Unit cube edges; scaled/positioned per-update to match the section box.
    const geom = new THREE.BoxGeometry(1, 1, 1);
    const edges = new THREE.EdgesGeometry(geom);
    geom.dispose();
    const mat = new THREE.LineBasicMaterial({
      color: 0x2979ff,
      transparent: true,
      opacity: 0.9,
      depthTest: false,
    });
    const seg = new THREE.LineSegments(edges, mat);
    seg.renderOrder = 1000;
    // The helper itself must never be clipped by the planes it visualises.
    mat.clippingPlanes = null;
    this.sceneManager.scene.add(seg);
    this.boxHelper = seg;
    return seg;
  }

  private updateBoxHelper(box: THREE.Box3): void {
    const helper = this.ensureBoxHelper();
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    helper.scale.set(
      Math.max(size.x, 1e-4),
      Math.max(size.y, 1e-4),
      Math.max(size.z, 1e-4),
    );
    helper.position.copy(center);
    helper.visible = true;
  }

  private removeBoxHelper(): void {
    if (!this.boxHelper) return;
    this.boxHelper.visible = false;
  }

  /** Dispose all GPU resources and detach planes from every material. */
  dispose(): void {
    this.assignPlanes(null);
    if (this.boxHelper) {
      this.sceneManager.scene.remove(this.boxHelper);
      this.boxHelper.geometry.dispose();
      (this.boxHelper.material as THREE.Material).dispose();
      this.boxHelper = null;
    }
    this.disposeCapMeshes();
  }
}
