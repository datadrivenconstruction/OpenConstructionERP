/**
 * SceneManager — manages Three.js scene, camera, renderer, controls.
 *
 * Handles initialization, animation loop, lighting, and camera utilities.
 * NOTE: three.js must be installed (`npm install three @types/three`).
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/addons/controls/OrbitControls.js';

export interface Viewpoint {
  position: { x: number; y: number; z: number };
  target: { x: number; y: number; z: number };
}

export class SceneManager {
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: OrbitControls;

  private animationId: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private container: HTMLElement;
  private gridHelper: THREE.GridHelper | null = null;

  constructor(canvas: HTMLCanvasElement) {
    const parent = canvas.parentElement;
    if (!parent) throw new Error('BIMViewer: canvas must have a parent element');
    this.container = parent;

    // Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
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

    // Controls — equally generous distance limits.
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.1;
    this.controls.minDistance = 0.001;
    this.controls.maxDistance = 1_000_000;
    this.controls.target.set(0, 0, 0);

    // Lighting
    this.setupLighting();

    // Grid — initial 20 m × 20 m with 1 m cells. Resized to fit the
    // loaded model after zoomToFit() so the grid always sits at the
    // same scale as the geometry (a 100 m grid swamps a 2 m model).
    this.gridHelper = new THREE.GridHelper(20, 20, 0xcccccc, 0xe0e0e0);
    this.scene.add(this.gridHelper);

    // Resize observer
    this.resizeObserver = new ResizeObserver(() => this.updateSize());
    this.resizeObserver.observe(this.container);

    // Start loop
    this.animate();
  }

  private setupLighting(): void {
    // Ambient light for overall brightness
    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambient);

    // Hemisphere light for sky/ground color blending
    const hemi = new THREE.HemisphereLight(0xddeeff, 0xffeedd, 0.3);
    hemi.position.set(0, 50, 0);
    this.scene.add(hemi);

    // Main directional light. Shadow casting is DISABLED — rendering
    // shadows for thousands of BIM meshes per frame drops the viewer
    // from 60 fps to 1 fps on real Revit exports. The directional
    // contribution alone is enough for solid 3D readability without
    // the per-frame shadow map cost.
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(30, 50, 30);
    directional.castShadow = false;
    this.scene.add(directional);

    // Fill light from opposite direction
    const fill = new THREE.DirectionalLight(0xffffff, 0.3);
    fill.position.set(-20, 30, -20);
    this.scene.add(fill);
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
    this.controls.update();
    this.renderer.render(this.scene, this.camera);
  };

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

    // Place camera at a 3/4 angle, looking at the model centre.
    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + dist * 0.6,
      center.y + dist * 0.5,
      center.z + dist * 0.6,
    );
    this.camera.lookAt(center);
    this.controls.update();

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
    this.scene.remove(this.gridHelper);
    this.gridHelper.geometry.dispose();
    const mat = this.gridHelper.material;
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
    else mat?.dispose();
    this.gridHelper = new THREE.GridHelper(extent, divisions, 0xcccccc, 0xe0e0e0);
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

  /** Set camera to a specific viewpoint. */
  setViewpoint(position: Viewpoint['position'], target: Viewpoint['target']): void {
    this.camera.position.set(position.x, position.y, position.z);
    this.controls.target.set(target.x, target.y, target.z);
    this.controls.update();
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

  /** Toggle grid visibility. */
  toggleGrid(): void {
    if (this.gridHelper) {
      this.gridHelper.visible = !this.gridHelper.visible;
    }
  }

  /** Dispose all Three.js resources. */
  dispose(): void {
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    this.resizeObserver?.disconnect();
    this.resizeObserver = null;

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

    this.renderer.dispose();
  }
}
