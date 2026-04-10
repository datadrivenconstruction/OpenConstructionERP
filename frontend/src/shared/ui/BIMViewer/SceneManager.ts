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
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.updateSize();

    // Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0xf0f2f5);

    // Gradient sky via hemisphere light contribution + fog.
    // Range is tightened in zoomToFit() once the model size is known.
    this.scene.fog = new THREE.Fog(0xf0f2f5, 2_000, 20_000);

    // Camera — near/far and controls.min/maxDistance are tuned dynamically in
    // zoomToFit() so models in any unit (metres / millimetres / feet) fit
    // correctly without user zoom.
    const aspect = this.container.clientWidth / Math.max(this.container.clientHeight, 1);
    this.camera = new THREE.PerspectiveCamera(45, aspect, 0.1, 10_000);
    this.camera.position.set(30, 20, 30);
    this.camera.lookAt(0, 0, 0);

    // Controls
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.1;
    this.controls.minDistance = 0.1;
    this.controls.maxDistance = 100_000;
    this.controls.target.set(0, 0, 0);

    // Lighting
    this.setupLighting();

    // Grid
    this.gridHelper = new THREE.GridHelper(100, 100, 0xcccccc, 0xe0e0e0);
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

    // Main directional light with soft shadows
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(30, 50, 30);
    directional.castShadow = true;
    directional.shadow.mapSize.width = 2048;
    directional.shadow.mapSize.height = 2048;
    directional.shadow.camera.near = 0.5;
    directional.shadow.camera.far = 200;
    directional.shadow.camera.left = -50;
    directional.shadow.camera.right = 50;
    directional.shadow.camera.top = 50;
    directional.shadow.camera.bottom = -50;
    directional.shadow.bias = -0.0001;
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

  /**
   * Compute a bounding box of the BIM content only — excluding helpers
   * (grid, lights, cameras) that would otherwise skew the fit distance.
   */
  private computeContentBBox(): THREE.Box3 {
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    this.scene.traverse((obj) => {
      // Skip helpers, lights, cameras — they don't represent real geometry
      if (
        obj instanceof THREE.GridHelper ||
        obj instanceof THREE.Light ||
        obj instanceof THREE.Camera ||
        (obj as THREE.Object3D & { isHelper?: boolean }).isHelper
      ) {
        return;
      }
      if (obj instanceof THREE.Mesh && obj.geometry) {
        tmp.setFromObject(obj);
        if (!tmp.isEmpty()) box.union(tmp);
      }
    });
    return box;
  }

  /** Fit all objects (or a specific bounding box) into the camera view. */
  zoomToFit(bbox?: THREE.Box3): void {
    const box = bbox ?? this.computeContentBBox();
    if (box.isEmpty()) return;

    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(maxDim) || maxDim <= 0) return;

    const fov = this.camera.fov * (Math.PI / 180);
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.6;

    // Dynamically rescale camera frustum + controls distance limits based on
    // the model size. Critical for RVT/COLLADA models that ship in mm or ft —
    // without this, a 30-metre building has a 30_000-unit bbox and the
    // hard-coded camera.far=1000 / maxDistance=500 would hide the model.
    this.camera.near = Math.max(0.01, maxDim / 10_000);
    this.camera.far = Math.max(1000, dist * 50);
    this.camera.updateProjectionMatrix();

    this.controls.minDistance = Math.max(0.01, maxDim / 1000);
    this.controls.maxDistance = dist * 20;

    // Grid sizing — make the helper at least as large as the model footprint
    this.rescaleGrid(maxDim, center);

    // Fog — place it well beyond the model so we don't fog out the geometry
    if (this.scene.fog instanceof THREE.Fog) {
      this.scene.fog.near = dist * 5;
      this.scene.fog.far = dist * 25;
    }

    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + dist * 0.6,
      center.y + dist * 0.4,
      center.z + dist * 0.6,
    );
    this.camera.lookAt(center);
    this.controls.update();
  }

  /** Rebuild the grid helper so it scales with model size. */
  private rescaleGrid(maxDim: number, center: THREE.Vector3): void {
    if (!this.gridHelper) return;
    const wasVisible = this.gridHelper.visible;
    this.scene.remove(this.gridHelper);
    this.gridHelper.geometry.dispose();
    const mat = this.gridHelper.material;
    if (Array.isArray(mat)) mat.forEach((m) => m.dispose());
    else mat?.dispose();

    // Grid at least 2x model footprint, rounded up to a clean power-of-ten
    const target = Math.max(10, maxDim * 2);
    const magnitude = Math.pow(10, Math.floor(Math.log10(target)));
    const gridSize = Math.ceil(target / magnitude) * magnitude;
    const divisions = 20;
    this.gridHelper = new THREE.GridHelper(gridSize, divisions, 0xcccccc, 0xe0e0e0);
    // Place grid under the model (Three's default is Y-up; models come in
    // with varying up-axes, but the grid is a visual guide so we align to the
    // bottom of the content bbox)
    this.gridHelper.position.set(center.x, center.y - maxDim / 2 - 0.01, center.z);
    this.gridHelper.visible = wasVisible;
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
