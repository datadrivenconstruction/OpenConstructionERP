/**
 * SceneManager — manages Three.js scene, camera, renderer, controls.
 *
 * Handles initialization, animation loop, lighting, and camera utilities.
 * NOTE: three.js must be installed (`npm install three @types/three`).
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';
import { CameraTween, type CameraState } from './CameraTween';
import type { BIMQualityMode } from '@/stores/useBIMViewerStore';

export interface Viewpoint {
  position: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
}

/** Canonical orientations driven by the View Cube (W6.6). */
export type ViewPreset =
  | 'top'
  | 'bottom'
  | 'front'
  | 'back'
  | 'left'
  | 'right'
  | 'iso_ne'
  | 'iso_nw'
  | 'iso_se'
  | 'iso_sw'
  | 'fit';

export class SceneManager {
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: OrbitControls;

  private animationId: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private container: HTMLElement;
  private gridHelper: THREE.GridHelper | null = null;
  /** Refs to lights created in setupLighting() so applyQualityMode()
   *  can re-tune intensities without rebuilding the scene graph. */
  private _ambientLight: THREE.AmbientLight | null = null;
  private _hemiLight: THREE.HemisphereLight | null = null;
  private _directionalLight: THREE.DirectionalLight | null = null;
  private _fillLight: THREE.DirectionalLight | null = null;
  /** Currently applied quality mode. */
  private _qualityMode: BIMQualityMode = 'default';
  /** On-demand rendering flag — drops idle CPU from 60 FPS to ~0%. */
  private _needsRender = true;
  /** Active camera tween (W6.6) — null when the camera is at rest. */
  private _tween: CameraTween | null = null;
  /** Reject the pending flyTo() promise when a new tween cancels it. */
  private _tweenReject: ((err: Error) => void) | null = null;
  /** controls.enabled value captured at tween start. Restored on cancel
   *  AND completion so a back-to-back cube click (which cancels the
   *  previous tween before it could restore controls) does not leave
   *  OrbitControls permanently disabled. */
  private _tweenWasControlsEnabled: boolean | null = null;
  /** Subscribers to camera-change events (used by the View Cube widget). */
  private _cameraChangeListeners = new Set<() => void>();
  /**
   * Last preset name + accumulated 90° rotation applied when the user
   * re-clicks the same View Cube face (Revit-style "snap-and-spin").
   */
  private _lastPreset: ViewPreset | null = null;
  private _lastPresetRotationSteps = 0;
  /** Listener refs kept so dispose() can remove them — without this,
   *  modifier-key handlers leaked on every viewer remount and the
   *  pointerup restore listener could fire AFTER dispose, leaving
   *  OrbitControls permanently disabled on the next model load. */
  private _onKeyDown: ((e: KeyboardEvent) => void) | null = null;
  private _onKeyUp: ((e: KeyboardEvent) => void) | null = null;
  private _onPointerDown: ((e: PointerEvent) => void) | null = null;
  private _canvasEl: HTMLCanvasElement | null = null;
  private _activeRestoreListeners = new Set<() => void>();
  /** True between a `webglcontextlost` event and its `webglcontextrestored`
   *  partner. While set, the animation loop skips rendering — the GL context
   *  is gone and any draw call would throw. */
  private _contextLost = false;
  /** Bound WebGL context-loss handlers, kept so dispose() can detach them. */
  private _onContextLost: ((e: Event) => void) | null = null;
  private _onContextRestored: (() => void) | null = null;
  /** Optional host callback fired with `true` on context loss and `false`
   *  on restore. The BIM viewer wires this to a non-fatal recovery banner so
   *  a transient GPU reset no longer reads as a hard crash (pdf11). */
  private _onContextStateChange: ((lost: boolean) => void) | null = null;

  constructor(canvas: HTMLCanvasElement) {
    const parent = canvas.parentElement;
    if (!parent) throw new Error('BIMViewer: canvas must have a parent element');
    this.container = parent;

    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      // Real IFC/RVT models carry many near-coplanar faces (multilayer
      // walls, slab finishes, IfcCovering over IfcWall, doubled
      // geometry from the converter). With a normal depth buffer and a
      // wide near/far range these faces get the same depth value and
      // the GPU flips which one wins every frame → "jumping"/flickering
      // triangles (z-fighting). A logarithmic depth buffer distributes
      // precision evenly across the whole range and removes the
      // artefact regardless of the model's unit/scale.
      logarithmicDepthBuffer: true,
    });
    // Pixel ratio capped at 1 — high-DPI rendering on a 5 000-mesh BIM
    // scene quadruples the per-frame fragment cost for marginal visual
    // gain on the engineering-readability use case. Users who want a
    // sharper picture can take a screenshot via the browser at any
    // zoom; the live viewport stays fluid.
    this.renderer.setPixelRatio(1);
    // Shadow map disabled — see DirectionalLight comment below.
    this.renderer.shadowMap.enabled = false;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.updateSize();

    // WebGL context-loss handling. On large models the GPU can drop the
    // context (driver reset / VRAM pressure / tab backgrounded); without
    // handling this the next render() throws and the viewer looks crashed
    // (pdf11). Calling preventDefault() on the loss event lets the browser
    // restore the context; we pause the render loop until it does, then
    // resume. The renderer rebuilds its own GL resources on restore, so we
    // only need to flag, notify the host, and re-request a frame.
    this._canvasEl = canvas;
    this._onContextLost = (e: Event) => {
      e.preventDefault();
      this._contextLost = true;
      this._onContextStateChange?.(true);
    };
    this._onContextRestored = () => {
      this._contextLost = false;
      // Three.js re-initialises its internal GL state on the next render
      // against the restored context. Force a redraw so the scene reappears.
      this._needsRender = true;
      this._onContextStateChange?.(false);
    };
    canvas.addEventListener('webglcontextlost', this._onContextLost as EventListener, false);
    canvas.addEventListener('webglcontextrestored', this._onContextRestored, false);

    // Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf0f2f5);

    // No fog. RVT/COLLADA models can ship in millimetres / centimetres /
    // feet — a fixed-distance fog either swallows the geometry whole or
    // does nothing useful, depending on the model size. Easier to skip it
    // than to keep recomputing the range every time the model changes.

    // Camera — wide near/far so any unit fits without manual zoom.
    const aspect = this.container.clientWidth / Math.max(this.container.clientHeight, 1);
    this.camera = new THREE.PerspectiveCamera(45, aspect, 0.01, 1_000_000);
    this.camera.position.set(30, 20, 30);
    this.camera.lookAt(0, 0, 0);

    // Controls — smooth, professional orbit behaviour.
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;       // smoother deceleration (was 0.1)
    this.controls.rotateSpeed = 0.8;          // slightly slower rotation for precision
    this.controls.panSpeed = 1.0;
    this.controls.zoomSpeed = 1.2;
    this.controls.minDistance = 0.01;
    this.controls.maxDistance = 100_000;
    // Prevent camera from flipping upside down — construction models
    // should always have "up" pointing up.
    this.controls.minPolarAngle = 0.05;       // ~3° from top
    this.controls.maxPolarAngle = Math.PI - 0.05; // ~3° from bottom
    this.controls.target.set(0, 0, 0);
    // Remap mouse buttons so Ctrl+Left doesn't trigger pan (which would
    // steal clicks from SelectionManager's Ctrl+Click multi-select).
    // Left=ROTATE, Middle=DOLLY, Right=PAN.  Ctrl/Shift+Left is now free
    // for the selection system.
    this.controls.mouseButtons = {
      LEFT: THREE.MOUSE.ROTATE,
      MIDDLE: THREE.MOUSE.DOLLY,
      RIGHT: THREE.MOUSE.PAN,
    };

    // Disable OrbitControls when Ctrl or Shift is held so that
    // Ctrl+Click and Shift+Click are free for multi-select in the
    // SelectionManager.  Re-enable on keyup.
    this._onKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Control' || e.key === 'Shift') {
        this.controls.enabled = false;
      }
    };
    this._onKeyUp = (e: KeyboardEvent) => {
      if (e.key === 'Control' || e.key === 'Shift') {
        this.controls.enabled = true;
      }
    };
    window.addEventListener('keydown', this._onKeyDown);
    window.addEventListener('keyup', this._onKeyUp);
    // Also handle the case where modifier was held during pointerdown
    // on the canvas — OrbitControls checks enabled on pointer events.
    this._canvasEl = canvas;
    this._onPointerDown = (e: PointerEvent) => {
      if (e.ctrlKey || e.metaKey || e.shiftKey) {
        this.controls.enabled = false;
        // Re-enable on next pointerup. The restore is tracked in a Set
        // so dispose() can drop it — otherwise a navigate-away mid-click
        // leaves OrbitControls disabled for the next model load.
        const restore = () => {
          this.controls.enabled = true;
          window.removeEventListener('pointerup', restore);
          this._activeRestoreListeners.delete(restore);
        };
        this._activeRestoreListeners.add(restore);
        window.addEventListener('pointerup', restore);
      }
    };
    canvas.addEventListener('pointerdown', this._onPointerDown, { capture: true });

    // On-demand rendering: only render when the camera moves or the
    // scene is explicitly invalidated.  Drops idle CPU from 60 FPS
    // constant rendering to ~0%.
    this.controls.addEventListener('change', () => {
      this._needsRender = true;
      this._emitCameraChange();
    });

    // Lighting
    this.setupLighting();

    // Grid — initial 20 m × 20 m with 1 m cells. Resized to fit the
    // loaded model after zoomToFit() so the grid always sits at the
    // same scale as the geometry (a 100 m grid swamps a 2 m model).
    this.gridHelper = new THREE.GridHelper(20, 20, 0xcccccc, 0xe0e0e0);
    this.gridHelper.visible = false; // hidden by default — user can toggle via toolbar
    this.scene.add(this.gridHelper);

    // Resize observer — also request a render so the new viewport is drawn.
    this.resizeObserver = new ResizeObserver(() => {
      this.updateSize();
      this._needsRender = true;
    });
    this.resizeObserver.observe(this.container);

    // Start loop
    this.animate();
  }

  private setupLighting(): void {
    // Ambient light for overall brightness
    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambient);
    this._ambientLight = ambient;

    // Hemisphere light for sky/ground color blending
    const hemi = new THREE.HemisphereLight(0xddeeff, 0xffeedd, 0.3);
    hemi.position.set(0, 50, 0);
    this.scene.add(hemi);
    this._hemiLight = hemi;

    // Main directional light. Shadow casting is DISABLED — rendering
    // shadows for thousands of BIM meshes per frame drops the viewer
    // from 60 fps to 1 fps on real Revit exports. The directional
    // contribution alone is enough for solid 3D readability without
    // the per-frame shadow map cost.
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(30, 50, 30);
    directional.castShadow = false;
    this.scene.add(directional);
    this._directionalLight = directional;

    // Fill light from opposite direction
    const fill = new THREE.DirectionalLight(0xffffff, 0.3);
    fill.position.set(-20, 30, -20);
    this.scene.add(fill);
    this._fillLight = fill;
  }

  /**
   * Apply a render-quality preset. Idempotent — safe to call on every
   * store change. Touches only renderer/lighting settings; material-side
   * adjustments live in ElementManager.applyQualityMode (called separately
   * from BIMViewer when the store value changes).
   */
  applyQualityMode(mode: BIMQualityMode): void {
    if (this._qualityMode === mode) return;
    this._qualityMode = mode;

    const dpr = typeof window !== 'undefined' ? window.devicePixelRatio || 1 : 1;
    switch (mode) {
      case 'fast':
        // Half-resolution rendering (visible jaggies on edges) +
        // single-light flat illumination → unmistakeable "performance"
        // look. Combined with ElementManager's flatShading + opaque
        // glass this mode reads visually as a draft preview.
        this.renderer.setPixelRatio(0.5);
        this.renderer.toneMapping = THREE.NoToneMapping;
        this.renderer.toneMappingExposure = 1.0;
        if (this._ambientLight) this._ambientLight.intensity = 1.1;
        if (this._hemiLight) this._hemiLight.intensity = 0;
        if (this._directionalLight) this._directionalLight.intensity = 0.35;
        if (this._fillLight) this._fillLight.intensity = 0;
        break;
      case 'visual':
        // Retina-grade pixelRatio + boosted exposure + warm sky/ground
        // hemisphere bounce. Combined with ElementManager's edge
        // overlay this reads as a presentation-quality CAD render.
        this.renderer.setPixelRatio(Math.min(2, dpr));
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.25;
        if (this._ambientLight) this._ambientLight.intensity = 0.4;
        if (this._hemiLight) this._hemiLight.intensity = 0.55;
        if (this._directionalLight) this._directionalLight.intensity = 1.15;
        if (this._fillLight) this._fillLight.intensity = 0.5;
        break;
      case 'walk':
        // Most aggressive cut — first-person navigation on phones / low-
        // spec laptops. PixelRatio 0.5 = quarter the fragment cost of
        // default; flat ambient avoids harsh directional highlights
        // crawling across walls as the camera moves.
        this.renderer.setPixelRatio(0.5);
        this.renderer.toneMapping = THREE.NoToneMapping;
        this.renderer.toneMappingExposure = 1.0;
        if (this._ambientLight) this._ambientLight.intensity = 1.25;
        if (this._hemiLight) this._hemiLight.intensity = 0;
        if (this._directionalLight) this._directionalLight.intensity = 0.25;
        if (this._fillLight) this._fillLight.intensity = 0;
        break;
      case 'default':
      default:
        // Restore constructor defaults (do NOT touch shadowMap or other
        // permanent flags — those are not part of the preset surface).
        this.renderer.setPixelRatio(1);
        this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
        this.renderer.toneMappingExposure = 1.0;
        if (this._ambientLight) this._ambientLight.intensity = 0.6;
        if (this._hemiLight) this._hemiLight.intensity = 0.3;
        if (this._directionalLight) this._directionalLight.intensity = 0.8;
        if (this._fillLight) this._fillLight.intensity = 0.3;
        break;
    }
    // PixelRatio change resets internal viewport — reapply size + render.
    this.updateSize();
    this._needsRender = true;
  }

  private updateSize(): void {
    const w = this.container.clientWidth || 1;
    const h = Math.max(this.container.clientHeight, 1);
    this.renderer.setSize(w, h);
    // Camera may not be initialized yet during constructor
    if (this.camera) {
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    }
  }

  private animate = (): void => {
    this.animationId = requestAnimationFrame(this.animate);
    // While the GL context is lost, render() would throw — pause drawing
    // until `webglcontextrestored` clears the flag. Damping/controls update
    // is cheap and harmless, but skip it too so a queued damping-dirty flag
    // doesn't try to draw against the dead context.
    if (this._contextLost) return;
    // Damping requires controls.update() every frame to animate the
    // deceleration, but we only pay the GPU render cost when something
    // actually changed.
    const dampingDirty = this.controls.update();
    if (dampingDirty) this._needsRender = true;
    if (this._needsRender) {
      this.renderer.render(this.scene, this.camera);
      this._needsRender = false;
    }
  };

  /** Mark the scene as needing a re-render on the next animation frame.
   *  Call this after selection changes, colour mutations, or visibility toggles. */
  requestRender(): void {
    this._needsRender = true;
  }

  /** Register a callback notified when the WebGL context is lost (`true`)
   *  or restored (`false`). The host wires this to a non-fatal recovery
   *  banner. Pass `null` to clear. Fires immediately with the current state
   *  so a listener attached after a loss still sees it. */
  onContextStateChange(cb: ((lost: boolean) => void) | null): void {
    this._onContextStateChange = cb;
    if (cb) cb(this._contextLost);
  }

  /** True while the WebGL context is lost (between contextlost / restored). */
  isContextLost(): boolean {
    return this._contextLost;
  }

  /** Fit all objects (or a specific bounding box) into the camera view. */
  zoomToFit(bbox?: THREE.Box3): void {
    // Build a content-only bounding box. We can't use a plain
    // setFromObject(scene) here because the scene also contains the
    // 100×100 GridHelper and the lights, and those dominate the bbox
    // for any real-world model (~30 m), making the camera distance
    // far too large and the model invisibly small in frame.
    //
    // CRITICAL: force the entire scene graph to recompute world
    // matrices BEFORE we read any mesh.matrixWorld. Otherwise the
    // first zoomToFit after a DAE load runs against stale identity
    // matrices and returns a tiny bbox, leaving the camera parked
    // 1000× too far away.
    this.scene.updateMatrixWorld(true);

    let box: THREE.Box3;
    if (bbox) {
      box = bbox;
    } else {
      box = new THREE.Box3();
      const tmp = new THREE.Box3();
      this.scene.traverse((obj) => {
        // Skip helpers, grids, lights, cameras — anything that is not
        // real BIM content. Walk INSIDE Groups so we still pick up
        // every mesh nested under the COLLADA scene root.
        if (
          obj instanceof THREE.GridHelper ||
          obj instanceof THREE.AxesHelper ||
          obj instanceof THREE.Light ||
          obj instanceof THREE.Camera
        ) {
          return;
        }
        if (obj instanceof THREE.Mesh && obj.geometry) {
          // Make sure the geometry has a bbox computed; otherwise
          // setFromObject silently returns an empty box.
          if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
          tmp.setFromObject(obj);
          if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) {
            box.union(tmp);
          }
        }
      });
    }
    if (box.isEmpty()) return;

    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(maxDim) || maxDim <= 0) return;

    const fov = this.camera.fov * (Math.PI / 180);
    // Multiplier 1.05 (was 1.4) — pull the camera in tighter so the
    // model fills the viewport instead of sitting in the middle with
    // ~40% empty margin around it. The orbit controls let users zoom
    // out anyway if they want a wider view.
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.05;

    // Tighten the depth range to the actual loaded model. The fixed
    // 0.01 / 1_000_000 default is a 1e8 ratio that wrecks depth
    // precision even before z-fighting; clamping `far` to the model
    // footprint (while keeping `near` ≥ 0.01 so close zoom never
    // clips) gives the depth buffer real precision. Combined with the
    // logarithmic depth buffer this fully removes the flicker.
    this.camera.near = Math.max(maxDim / 50_000, 0.01);
    this.camera.far = Math.max(dist * 12, maxDim * 50);
    this.camera.updateProjectionMatrix();
    // Keep orbit dolly-out within the visible depth range so the model
    // can't be pushed past the far plane and vanish.
    this.controls.maxDistance = this.camera.far * 0.5;

    // Place camera at a natural architectural viewing angle.
    // Slightly elevated (0.35 * dist up) and offset diagonally so the
    // model reads like a perspective architectural rendering.
    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + dist * 0.7,
      center.y + dist * 0.35,
      center.z + dist * 0.5,
    );
    this.camera.lookAt(center);
    this.controls.update();
    this._needsRender = true;

    // Resize the grid to match the model. We want 1-unit cells (≈ 1 m
    // when the model is in metres) and a total extent that's slightly
    // larger than the model footprint so the grid frames the geometry
    // without dwarfing it.
    this.resizeGridToBox(box);
  }

  /** Replace the grid helper with one sized to the given bounding box. */
  private resizeGridToBox(box: THREE.Box3): void {
    if (!this.gridHelper) return;
    const size = box.getSize(new THREE.Vector3());
    const center = box.getCenter(new THREE.Vector3());
    // Use the larger horizontal axis to size the grid; clamp to a sane
    // range so we never end up with a 1 cm grid (zero-divisions error)
    // or a 10 km grid (millions of lines).
    const horizontal = Math.max(size.x, size.z);
    let extent = Math.max(2, Math.ceil(horizontal * 1.6));
    extent = Math.min(extent, 500);
    // Choose a cell size that keeps the line count reasonable: 1 m for
    // anything ≤ 100 m, then scale up to keep ~100 divisions max.
    let cell = 1;
    if (extent > 100) cell = Math.ceil(extent / 100);
    const divisions = Math.max(2, Math.round(extent / cell));
    // Replace the existing grid (GridHelper has no resize API).
    // Respect dark mode by checking the scene background luminance.
    const bg = this.scene.background;
    const isDark = bg instanceof THREE.Color && bg.getHSL({ h: 0, s: 0, l: 0 }).l < 0.3;
    const centerColor = isDark ? 0x333344 : 0xcccccc;
    const lineColor = isDark ? 0x2a2a3a : 0xe0e0e0;
    this.scene.remove(this.gridHelper);
    this.gridHelper.geometry.dispose();
    const mat = this.gridHelper.material;
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
    else mat?.dispose();
    this.gridHelper = new THREE.GridHelper(extent, divisions, centerColor, lineColor);
    // Sit the grid just below the model floor so it doesn't z-fight
    // with the lowest geometry.
    this.gridHelper.position.set(center.x, box.min.y - 0.001, center.z);
    this.scene.add(this.gridHelper);
  }

  /** Zoom to specific element bounding boxes. */
  zoomToSelection(meshes: THREE.Object3D[]): void {
    if (meshes.length === 0) return;
    const box = new THREE.Box3();
    for (const mesh of meshes) {
      box.expandByObject(mesh);
    }
    this.zoomToFit(box);
  }

  /**
   * Frame the camera on an arbitrary world-space point with a small radius.
   *
   * Used by the clash-review deep-link: a clash carries a reliable world
   * centroid (`cx/cy/cz`) even for showcase IFC/RVT models whose GLB nodes
   * are numeric Revit ids that never match the DB element UUIDs (so the
   * per-element mesh resolution is only approximate).  Pointing the camera
   * at the centroid guarantees the interference is on-screen regardless of
   * whether the two element meshes resolved exactly.
   */
  focusOnPoint(world: { x: number; y: number; z: number }, radius = 3): void {
    const center = new THREE.Vector3(world.x, world.y, world.z);
    if (
      !Number.isFinite(center.x) ||
      !Number.isFinite(center.y) ||
      !Number.isFinite(center.z)
    ) {
      return;
    }
    const r = Number.isFinite(radius) && radius > 0 ? radius : 3;
    const fov = this.camera.fov * (Math.PI / 180);
    // Frame a sphere of `r` around the point: distance so the sphere fills
    // ~70% of the viewport (the 1.4 multiplier leaves breathing room so the
    // surrounding context is visible around the collision).
    const dist = (r / Math.tan(fov / 2)) * 1.4;
    this.camera.near = Math.max(r / 500, 0.01);
    this.camera.far = Math.max(dist * 50, r * 200, this.camera.far);
    this.camera.updateProjectionMatrix();
    this.controls.maxDistance = this.camera.far * 0.5;
    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + dist * 0.7,
      center.y + dist * 0.35,
      center.z + dist * 0.5,
    );
    this.camera.lookAt(center);
    this.controls.update();
    this._needsRender = true;
  }

  /** Set camera to a specific viewpoint. */
  setViewpoint(position: Viewpoint['position'], target: Viewpoint['target']): void {
    this.camera.position.set(position.x, position.y, position.z);
    this.controls.target.set(target.x, target.y, target.z);
    this.controls.update();
    this._needsRender = true;
  }

  /** Snap the camera to a canonical view of the current scene bounding box.
   *
   * `view` is one of:
   *   - `'top'`   — looking straight down (plan view)
   *   - `'front'` — looking at the +Z face
   *   - `'side'`  — looking at the +X face
   *   - `'iso'`   — the default 3/4 orthographic-ish perspective angle
   */
  setCameraPreset(view: 'top' | 'front' | 'side' | 'iso'): void {
    // Recompute the scene bounding box (same walker that zoomToFit uses,
    // minus the helpers) so the preset always matches what's currently loaded.
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    this.scene.traverse((obj) => {
      if (
        obj instanceof THREE.GridHelper ||
        obj instanceof THREE.AxesHelper ||
        obj instanceof THREE.Light ||
        obj instanceof THREE.Camera
      ) {
        return;
      }
      if (obj instanceof THREE.Mesh && obj.geometry) {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
        tmp.setFromObject(obj);
        if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) box.union(tmp);
      }
    });
    if (box.isEmpty()) return;

    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(maxDim) || maxDim <= 0) return;
    const fov = this.camera.fov * (Math.PI / 180);
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.1;

    this.controls.target.copy(center);
    switch (view) {
      case 'top':
        this.camera.position.set(center.x, center.y + dist, center.z + 0.001);
        break;
      case 'front':
        this.camera.position.set(center.x, center.y, center.z + dist);
        break;
      case 'side':
        this.camera.position.set(center.x + dist, center.y, center.z);
        break;
      case 'iso':
      default:
        this.camera.position.set(
          center.x + dist * 0.7,
          center.y + dist * 0.35,
          center.z + dist * 0.5,
        );
        break;
    }
    this.camera.lookAt(center);
    this.controls.update();
    this._needsRender = true;
  }

  /** Get current camera viewpoint. */
  getViewpoint(): Viewpoint {
    return {
      position: {
        x: this.camera.position.x,
        y: this.camera.position.y,
        z: this.camera.position.z,
      },
      target: {
        x: this.controls.target.x,
        y: this.controls.target.y,
        z: this.controls.target.z,
      },
    };
  }

  /**
   * Capture the current viewport as a PNG data-URL.
   *
   * By default returns the renderer canvas verbatim (matches what the user
   * sees on screen). When ``opts.width`` is provided we downscale into an
   * off-screen canvas first — used by the saved-views feature to attach a
   * small thumbnail (320×180 ≈ 30–60 KB) instead of a full-resolution PNG
   * (~1 MB) which would blow through the localStorage quota after a handful
   * of views.
   *
   * Three.js on-demand rendering means the back-buffer can be one frame
   * stale relative to the latest selection / colour change; we force a
   * synchronous render before reading the pixels so the screenshot matches
   * what was visible the instant the call was made.
   */
  getScreenshot(opts?: { width?: number; height?: number }): string {
    // Force a synchronous render so the back-buffer matches the current
    // scene graph — otherwise a recent selection / colour mutation that
    // hasn't tripped the on-demand render flag yet would be missing.
    this.renderer.render(this.scene, this.camera);
    const sourceCanvas = this.renderer.domElement;
    const width = opts?.width;
    const height = opts?.height;
    if (!width || !height) {
      return sourceCanvas.toDataURL('image/png');
    }
    // Downscale path — used for saved-view thumbnails. Off-screen canvas
    // keeps the live renderer untouched.
    const out = document.createElement('canvas');
    out.width = Math.max(1, Math.floor(width));
    out.height = Math.max(1, Math.floor(height));
    const ctx = out.getContext('2d');
    if (!ctx) return sourceCanvas.toDataURL('image/png');
    ctx.drawImage(sourceCanvas, 0, 0, out.width, out.height);
    return out.toDataURL('image/png');
  }

  /** Toggle grid visibility. */
  toggleGrid(): void {
    if (this.gridHelper) {
      this.gridHelper.visible = !this.gridHelper.visible;
      this._needsRender = true;
    }
  }

  /** Update the scene background and grid colors for light/dark mode.
   *
   *  Light mode: #f0f2f5 background, #cccccc / #e0e0e0 grid
   *  Dark mode:  #1a1a2e background, #333344 / #2a2a3a grid
   */
  setDarkMode(isDark: boolean): void {
    if (isDark) {
      this.scene.background = new THREE.Color(0x1a1a2e);
    } else {
      this.scene.background = new THREE.Color(0xf0f2f5);
    }
    // Rebuild the grid with matching colors — no resize API on GridHelper,
    // so we swap it in-place keeping the same position/visibility.
    if (this.gridHelper) {
      const wasVisible = this.gridHelper.visible;
      const pos = this.gridHelper.position.clone();
      // GridHelper stores its size/divisions on the geometry userData or
      // as internal state. We read the bounding box to infer size, then
      // fall back to 20/20 if it's empty or not computed.
      let size = 20;
      let divisions = 20;
      this.gridHelper.geometry.computeBoundingBox();
      const bb = this.gridHelper.geometry.boundingBox;
      if (bb && !bb.isEmpty()) {
        const gSize = bb.getSize(new THREE.Vector3());
        size = Math.round(Math.max(gSize.x, gSize.z));
        // Infer divisions from vertex count: a GridHelper with N divisions
        // has (N+1)*2*2 = 4*(N+1) vertices on each axis → total position
        // count = 4*(N+1)*2.  We approximate by taking position count / 8.
        const posAttr = this.gridHelper.geometry.getAttribute('position');
        if (posAttr) {
          const approxDiv = Math.round(posAttr.count / 8) - 1;
          if (approxDiv > 1) divisions = approxDiv;
        }
      }
      this.scene.remove(this.gridHelper);
      this.gridHelper.geometry.dispose();
      const mat = this.gridHelper.material;
      if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
      else mat?.dispose();
      const centerColor = isDark ? 0x333344 : 0xcccccc;
      const lineColor = isDark ? 0x2a2a3a : 0xe0e0e0;
      this.gridHelper = new THREE.GridHelper(size, divisions, centerColor, lineColor);
      this.gridHelper.position.copy(pos);
      this.gridHelper.visible = wasVisible;
      this.scene.add(this.gridHelper);
    }
    this._needsRender = true;
  }

  /**
   * Subscribe to camera-orientation changes (W6.6).
   *
   * The View Cube widget uses this to keep its 3-D cube synchronised with
   * the main camera. Returns an unsubscribe function for cleanup.
   */
  onCameraChange(cb: () => void): () => void {
    this._cameraChangeListeners.add(cb);
    return () => {
      this._cameraChangeListeners.delete(cb);
    };
  }

  private _emitCameraChange(): void {
    for (const listener of this._cameraChangeListeners) {
      try {
        listener();
      } catch {
        // A throwing subscriber must not break the OrbitControls loop.
      }
    }
  }

  /**
   * Smoothly fly the camera from its current pose to the requested
   * `target` over `durationMs` ms (default 600). Resolves on completion
   * and rejects with `Error('flyTo cancelled')` when a newer tween (or
   * an explicit cancellation) supersedes the current animation.
   *
   * While the tween is running OrbitControls.enabled is set to false so
   * mouse interaction can't fight the animation; it is restored on
   * completion or abort.
   */
  flyTo(target: CameraState, durationMs = 600): Promise<void> {
    // Abort any previously-running tween: reject its promise + stop rAF.
    // CRITICAL: restore controls.enabled to its pre-tween value FIRST so
    // the new tween captures the true user-visible enabled state, not
    // the "disabled-during-animation" state left behind by the previous
    // tween's start. Without this, two back-to-back cube clicks would
    // permanently freeze OrbitControls.
    if (this._tween) {
      this._tween.cancel();
      this._tween = null;
    }
    if (this._tweenWasControlsEnabled !== null) {
      this.controls.enabled = this._tweenWasControlsEnabled;
      this._tweenWasControlsEnabled = null;
    }
    if (this._tweenReject) {
      const reject = this._tweenReject;
      this._tweenReject = null;
      reject(new Error('flyTo cancelled'));
    }

    const from: CameraState = {
      position: [
        this.camera.position.x,
        this.camera.position.y,
        this.camera.position.z,
      ],
      target: [
        this.controls.target.x,
        this.controls.target.y,
        this.controls.target.z,
      ],
      up: [this.camera.up.x, this.camera.up.y, this.camera.up.z],
    };

    return new Promise<void>((resolve, reject) => {
      const tween = new CameraTween();
      this._tween = tween;
      this._tweenReject = reject;
      this._tweenWasControlsEnabled = this.controls.enabled;
      this.controls.enabled = false;

      tween.start(
        from,
        target,
        durationMs,
        (state) => {
          this.camera.position.set(
            state.position[0],
            state.position[1],
            state.position[2],
          );
          this.controls.target.set(
            state.target[0],
            state.target[1],
            state.target[2],
          );
          if (state.up) {
            this.camera.up.set(state.up[0], state.up[1], state.up[2]);
          }
          this.camera.lookAt(this.controls.target);
          this._needsRender = true;
          this._emitCameraChange();
        },
        () => {
          // Restore controls only if no newer tween has already swapped
          // _tweenWasControlsEnabled out from under us — guards against
          // a re-entrant flyTo that would otherwise be overwritten.
          if (this._tweenWasControlsEnabled !== null) {
            this.controls.enabled = this._tweenWasControlsEnabled;
            this._tweenWasControlsEnabled = null;
          }
          this.controls.update();
          this._needsRender = true;
          this._tween = null;
          this._tweenReject = null;
          resolve();
        },
      );
    });
  }

  /**
   * Snap the camera to one of the canonical View Cube orientations
   * around the current scene bounding box (W6.6).
   *
   * Re-clicking the SAME face rotates the camera by an additional 90°
   * around the view axis, matching Revit's View Cube behaviour.
   */
  setViewPreset(name: ViewPreset, durationMs = 600): Promise<void> {
    const box = this._computeContentBoundingBox();
    if (box.isEmpty()) {
      return Promise.resolve();
    }
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(maxDim) || maxDim <= 0) {
      return Promise.resolve();
    }

    if (name === 'fit') {
      // For "fit" we keep the current direction but reframe distance.
      const fov = this.camera.fov * (Math.PI / 180);
      const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.05;
      const dir = this.camera.position
        .clone()
        .sub(this.controls.target)
        .normalize();
      const newPos = center.clone().add(dir.multiplyScalar(dist));
      return this.flyTo(
        {
          position: [newPos.x, newPos.y, newPos.z],
          target: [center.x, center.y, center.z],
          up: [0, 1, 0],
        },
        durationMs,
      );
    }

    // Track Revit-style re-click rotation: only orth + iso presets rotate.
    let rotationSteps = 0;
    if (this._lastPreset === name) {
      rotationSteps = (this._lastPresetRotationSteps + 1) % 4;
    }
    this._lastPreset = name;
    this._lastPresetRotationSteps = rotationSteps;
    const rollAngle = (rotationSteps * Math.PI) / 2;

    const fov = this.camera.fov * (Math.PI / 180);
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.2;

    // The SceneManager's convention is Y-up. The bottom view needs a
    // flipped up vector so the camera doesn't look "upside-down".
    let position = new THREE.Vector3();
    let up = new THREE.Vector3(0, 1, 0);
    switch (name) {
      case 'top':
        position.set(center.x, center.y + dist, center.z);
        // Z-down so the model's "north" reads correctly looking down.
        up.set(0, 0, -1);
        break;
      case 'bottom':
        position.set(center.x, center.y - dist, center.z);
        up.set(0, 0, 1);
        break;
      case 'front':
        position.set(center.x, center.y, center.z + dist);
        up.set(0, 1, 0);
        break;
      case 'back':
        position.set(center.x, center.y, center.z - dist);
        up.set(0, 1, 0);
        break;
      case 'right':
        position.set(center.x + dist, center.y, center.z);
        up.set(0, 1, 0);
        break;
      case 'left':
        position.set(center.x - dist, center.y, center.z);
        up.set(0, 1, 0);
        break;
      case 'iso_ne':
      case 'iso_nw':
      case 'iso_se':
      case 'iso_sw': {
        // 45° elevation, azimuth chosen per corner. Y-up scene means
        // the iso direction is in the XZ-plane plus a Y component.
        const elev = Math.PI / 4; // 45° up from the horizon
        const azimuthMap: Record<string, number> = {
          iso_ne: Math.PI / 4, // +X / +Z
          iso_nw: (3 * Math.PI) / 4, // -X / +Z
          iso_se: -Math.PI / 4, // +X / -Z
          iso_sw: (-3 * Math.PI) / 4, // -X / -Z
        };
        const az = azimuthMap[name] ?? Math.PI / 4;
        const r = dist;
        position.set(
          center.x + r * Math.cos(elev) * Math.sin(az),
          center.y + r * Math.sin(elev),
          center.z + r * Math.cos(elev) * Math.cos(az),
        );
        up.set(0, 1, 0);
        break;
      }
    }

    // Apply the re-click roll: rotate `up` around the view axis (the
    // vector from target to camera). 0/90/180/270° steps.
    if (rollAngle !== 0) {
      const viewAxis = position.clone().sub(center).normalize();
      up.applyAxisAngle(viewAxis, rollAngle);
    }

    return this.flyTo(
      {
        position: [position.x, position.y, position.z],
        target: [center.x, center.y, center.z],
        up: [up.x, up.y, up.z],
      },
      durationMs,
    );
  }

  /**
   * Walk the scene graph and union all real-content mesh bounding boxes.
   * Mirrors the helper inside zoomToFit() / setCameraPreset() so the
   * View Cube presets always frame what the user actually loaded.
   */
  private _computeContentBoundingBox(): THREE.Box3 {
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    this.scene.traverse((obj) => {
      if (
        obj instanceof THREE.GridHelper ||
        obj instanceof THREE.AxesHelper ||
        obj instanceof THREE.Light ||
        obj instanceof THREE.Camera
      ) {
        return;
      }
      if (obj instanceof THREE.Mesh && obj.geometry) {
        if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox();
        tmp.setFromObject(obj);
        if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) {
          box.union(tmp);
        }
      }
    });
    return box;
  }

  /** Dispose all Three.js resources. */
  dispose(): void {
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    // Abort any in-flight camera tween before tearing the renderer down,
    // so the rAF callback can't fire against a disposed camera.
    if (this._tween) {
      this._tween.cancel();
      this._tween = null;
    }
    if (this._tweenReject) {
      const reject = this._tweenReject;
      this._tweenReject = null;
      try {
        reject(new Error('flyTo cancelled'));
      } catch {
        // Swallow — caller might not have attached a .catch().
      }
    }
    this._cameraChangeListeners.clear();
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;

    // Remove modifier-key listeners (otherwise every BIM viewer mount
    // leaked a global handler; orbit-controls state could be flipped
    // by a still-attached restore listener on a disposed scene).
    if (this._onKeyDown) window.removeEventListener('keydown', this._onKeyDown);
    if (this._onKeyUp) window.removeEventListener('keyup', this._onKeyUp);
    this._onKeyDown = null;
    this._onKeyUp = null;
    if (this._canvasEl && this._onPointerDown) {
      this._canvasEl.removeEventListener('pointerdown', this._onPointerDown, { capture: true } as EventListenerOptions);
    }
    this._onPointerDown = null;
    // Detach the WebGL context-loss listeners before releasing the canvas ref.
    if (this._canvasEl && this._onContextLost) {
      this._canvasEl.removeEventListener('webglcontextlost', this._onContextLost as EventListener, false);
    }
    if (this._canvasEl && this._onContextRestored) {
      this._canvasEl.removeEventListener('webglcontextrestored', this._onContextRestored, false);
    }
    this._onContextLost = null;
    this._onContextRestored = null;
    this._onContextStateChange = null;
    this._canvasEl = null;
    for (const restore of this._activeRestoreListeners) {
      window.removeEventListener('pointerup', restore);
    }
    this._activeRestoreListeners.clear();

    this.controls.dispose();

    // Traverse and dispose geometries + materials
    this.scene.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        obj.geometry?.dispose();
        const mat = obj.material;
        if (Array.isArray(mat)) {
          mat.forEach((m) => m.dispose());
        } else if (mat) {
          mat.dispose();
        }
      }
    });

    // Release the underlying WebGL context, not just the GPU resources.
    // renderer.dispose() frees programs/render-targets but leaves the context
    // alive; the BIM viewer mounts/unmounts on every model navigation and tab
    // switch, and browsers cap live contexts (~8-16). Without an explicit
    // forceContextLoss the oldest context gets killed and new canvases render
    // black ("Too many active WebGL contexts").
    try {
      this.renderer.forceContextLoss();
    } catch {
      // some headless / mocked renderers don't implement it - safe to ignore
    }
    this.renderer.dispose();
  }
}
