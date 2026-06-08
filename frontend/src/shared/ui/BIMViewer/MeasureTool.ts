/**
 * MeasureTool — point-to-point distance measurement with vertex snapping.
 *
 * Standalone helper around the raw Three.js scene/camera/renderer: the
 * `ViewerToolbar` wires this in alongside `SectionBox` and `WalkMode`
 * without needing the full `MeasureManager` (which is tied to the
 * existing SceneManager/ElementManager + supports polygon/angle modes
 * + DOM-overlay labels).  `MeasureTool` is the simpler, BIM-coordination-tool-style
 * distance ruler that the brief asked for.
 *
 * Interaction:
 *   1. `enable()` registers a `mousedown` listener on `domElement`.
 *   2. First click → raycast against scene.children (recursive),
 *      snap to the nearest vertex of the picked face if within 8 px
 *      screen-space, record point A and drop a marker.
 *   3. Second click → repeat for point B; emit `Measurement` to all
 *      subscribers; draw a dashed line + sprite label between A and B.
 *   4. Subsequent clicks start a new pair; finished measurements
 *      persist until `clearAll()`.
 */

import * as THREE from 'three';
import { uuid } from '@/shared/lib/browser';

const SNAP_PX = 8;

export interface MeasureToolArgs {
  scene: THREE.Scene;
  camera: THREE.Camera;
  renderer: THREE.WebGLRenderer;
  domElement: HTMLElement;
}

export interface Measurement {
  id: string;
  pointA: { x: number; y: number; z: number };
  pointB: { x: number; y: number; z: number };
  /** Straight-line distance in metres (assumes model is in metres). */
  distance: number;
  axisProjections: {
    dx: number;
    dy: number;
    dz: number;
  };
}

type MeasurementHandler = (m: Measurement) => void;

interface DrawnMeasurement {
  id: string;
  line: THREE.Line;
  markers: THREE.Mesh[];
  labelSprite: THREE.Sprite | null;
}

function uid(): string {
  return uuid();
}

function formatDistance(metres: number): string {
  if (metres >= 1) return `${metres.toFixed(2)} m`;
  return `${(metres * 1000).toFixed(0)} mm`;
}

export class MeasureTool {
  private scene: THREE.Scene;
  private camera: THREE.Camera;
  // Renderer kept on the args API for symmetry with SectionBox / WalkMode,
  // but the measure tool itself never reads it — picking goes through the
  // raycaster directly against `scene.children`. Underscored to silence
  // the `noUnusedLocals` lint without losing the constructor surface.
  private _renderer: THREE.WebGLRenderer;
  private domElement: HTMLElement;

  private raycaster = new THREE.Raycaster();
  private mouseNdc = new THREE.Vector2();

  private _enabled = false;
  private pendingPoint: THREE.Vector3 | null = null;
  private pendingMarker: THREE.Mesh | null = null;
  private drawn: DrawnMeasurement[] = [];

  private subscribers = new Set<MeasurementHandler>();

  private onMouseDown = (ev: MouseEvent): void => this.handleClick(ev);
  /** Suppress the browser context menu while the tool is active so right-
   *  click can finish / cancel the current measurement. */
  private onContextMenu = (ev: MouseEvent): void => {
    if (!this._enabled) return;
    ev.preventDefault();
  };
  /** Escape cancels a pending first-point pick without forcing the user
   *  to disable the tool. Listens on `window` (not the canvas) because
   *  some browsers only deliver Escape to the focused document. */
  private onKeyDown = (ev: KeyboardEvent): void => {
    if (!this._enabled) return;
    if (ev.key === 'Escape') {
      this.clearPending();
    }
  };

  constructor(args: MeasureToolArgs) {
    this.scene = args.scene;
    this.camera = args.camera;
    this._renderer = args.renderer;
    this.domElement = args.domElement;
    void this._renderer;
  }

  isEnabled(): boolean {
    return this._enabled;
  }

  enable(): void {
    if (this._enabled) return;
    this._enabled = true;
    this.domElement.addEventListener('mousedown', this.onMouseDown);
    this.domElement.addEventListener('contextmenu', this.onContextMenu);
    window.addEventListener('keydown', this.onKeyDown);
  }

  disable(): void {
    if (!this._enabled) return;
    this._enabled = false;
    this.domElement.removeEventListener('mousedown', this.onMouseDown);
    this.domElement.removeEventListener('contextmenu', this.onContextMenu);
    window.removeEventListener('keydown', this.onKeyDown);
    this.clearPending();
  }

  /** Subscribe to completed measurements. Returns an unsubscribe fn. */
  onMeasurement(handler: MeasurementHandler): () => void {
    this.subscribers.add(handler);
    return () => {
      this.subscribers.delete(handler);
    };
  }

  /** Drop every drawn measurement from the scene + free GPU resources. */
  clearAll(): void {
    for (const d of this.drawn) {
      this.scene.remove(d.line);
      d.line.geometry.dispose();
      const lineMat = d.line.material as THREE.Material;
      lineMat.dispose();
      for (const m of d.markers) {
        this.scene.remove(m);
        m.geometry.dispose();
        (m.material as THREE.Material).dispose();
      }
      if (d.labelSprite) {
        this.scene.remove(d.labelSprite);
        const sm = d.labelSprite.material as THREE.SpriteMaterial;
        if (sm.map) sm.map.dispose();
        sm.dispose();
      }
    }
    this.drawn = [];
    this.clearPending();
  }

  /** Number of completed measurements currently in the scene. */
  count(): number {
    return this.drawn.length;
  }

  dispose(): void {
    this.disable();
    this.clearAll();
    this.subscribers.clear();
  }

  /** Test surface: directly feed two world-space points and finalise the
   *  measurement (skips raycasting + DOM events). Returns the emitted
   *  Measurement so tests can assert on its contents. */
  __testAddMeasurement(
    a: THREE.Vector3 | { x: number; y: number; z: number },
    b: THREE.Vector3 | { x: number; y: number; z: number },
  ): Measurement {
    const va = a instanceof THREE.Vector3 ? a : new THREE.Vector3(a.x, a.y, a.z);
    const vb = b instanceof THREE.Vector3 ? b : new THREE.Vector3(b.x, b.y, b.z);
    return this.finalise(va, vb);
  }

  /* ── Internals ───────────────────────────────────────────────────── */

  private handleClick(ev: MouseEvent): void {
    // Right-click (button 2) cancels the pending pick. Without this the
    // only way to back out of a half-finished measurement was to switch
    // tools — undocumented and frustrating.
    if (ev.button === 2) {
      this.clearPending();
      return;
    }
    // Middle-click is reserved for OrbitControls pan in the host viewer;
    // we ignore it here so it doesn't accidentally drop a measurement
    // point.
    if (ev.button !== 0) return;
    const point = this.pick(ev);
    if (!point) return;

    if (!this.pendingPoint) {
      this.pendingPoint = point;
      this.pendingMarker = this.addMarker(point, 0xffd400);
      return;
    }
    // Second click — finalise.
    const a = this.pendingPoint;
    const b = point;
    this.clearPending();
    this.finalise(a, b);
  }

  /** Raycast against scene.children (recursive); on hit, snap to the
   *  nearest vertex of the picked face if within 8 px screen-space. */
  private pick(ev: MouseEvent): THREE.Vector3 | null {
    const rect = this.domElement.getBoundingClientRect();
    const x = ev.clientX - rect.left;
    const y = ev.clientY - rect.top;
    this.mouseNdc.x = (x / rect.width) * 2 - 1;
    this.mouseNdc.y = -(y / rect.height) * 2 + 1;
    this.raycaster.setFromCamera(this.mouseNdc, this.camera);
    const hits = this.raycaster.intersectObjects(this.scene.children, true);
    if (hits.length === 0) return null;
    const hit = hits[0]!;
    const raw = hit.point.clone();
    const snapped = this.maybeSnapToVertex(hit, raw, rect);
    return snapped ?? raw;
  }

  /** If the closest vertex of the picked face projects within
   *  `SNAP_PX` of the click in screen-space, return it; else null. */
  private maybeSnapToVertex(
    hit: THREE.Intersection,
    _raw: THREE.Vector3,
    rect: DOMRect,
  ): THREE.Vector3 | null {
    const face = hit.face;
    const obj = hit.object as THREE.Mesh | undefined;
    if (!face || !obj || !obj.geometry) return null;
    const geom = obj.geometry as THREE.BufferGeometry;
    const posAttr = geom.getAttribute('position') as THREE.BufferAttribute | undefined;
    if (!posAttr) return null;

    const candidates = [face.a, face.b, face.c];
    let bestVertex: THREE.Vector3 | null = null;
    let bestPxDist = Infinity;
    const clickPx = new THREE.Vector2(
      (rect.width * (this.mouseNdc.x + 1)) / 2,
      (rect.height * (1 - this.mouseNdc.y)) / 2,
    );

    for (const idx of candidates) {
      const v = new THREE.Vector3().fromBufferAttribute(posAttr, idx);
      v.applyMatrix4(obj.matrixWorld);
      // Project to NDC then to pixels (in element-local coords).
      const ndc = v.clone().project(this.camera);
      const px = (ndc.x + 1) * 0.5 * rect.width;
      const py = (1 - ndc.y) * 0.5 * rect.height;
      const dx = px - clickPx.x;
      const dy = py - clickPx.y;
      const pxDist = Math.hypot(dx, dy);
      if (pxDist < bestPxDist) {
        bestPxDist = pxDist;
        bestVertex = v;
      }
    }
    if (bestVertex && bestPxDist <= SNAP_PX) return bestVertex;
    return null;
  }

  private finalise(a: THREE.Vector3, b: THREE.Vector3): Measurement {
    const dx = b.x - a.x;
    const dy = b.y - a.y;
    const dz = b.z - a.z;
    const distance = Math.sqrt(dx * dx + dy * dy + dz * dz);
    const id = uid();
    const m: Measurement = {
      id,
      pointA: { x: a.x, y: a.y, z: a.z },
      pointB: { x: b.x, y: b.y, z: b.z },
      distance,
      axisProjections: { dx, dy, dz },
    };

    const line = this.buildDashedLine(a, b);
    const markers = [this.addMarker(a, 0xffd400), this.addMarker(b, 0xffd400)];
    const label = this.buildLabel(a, b, formatDistance(distance));
    this.scene.add(line);
    if (label) this.scene.add(label);
    this.drawn.push({ id, line, markers, labelSprite: label });

    for (const sub of this.subscribers) {
      try {
        sub(m);
      } catch {
        // Subscriber errors should not break the tool.
      }
    }
    return m;
  }

  private buildDashedLine(a: THREE.Vector3, b: THREE.Vector3): THREE.Line {
    const geom = new THREE.BufferGeometry().setFromPoints([a.clone(), b.clone()]);
    const mat = new THREE.LineDashedMaterial({
      color: 0xffd400,
      dashSize: 0.05,
      gapSize: 0.03,
      depthTest: false,
      transparent: true,
    });
    const line = new THREE.Line(geom, mat);
    // Required so dashed lines actually render dashed.
    line.computeLineDistances();
    line.renderOrder = 1002;
    line.userData.isMeasureLine = true;
    return line;
  }

  private addMarker(p: THREE.Vector3, color: number): THREE.Mesh {
    const geom = new THREE.SphereGeometry(0.04, 8, 6);
    const mat = new THREE.MeshBasicMaterial({
      color,
      depthTest: false,
      transparent: true,
    });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.copy(p);
    mesh.renderOrder = 1003;
    mesh.userData.isMeasureMarker = true;
    this.scene.add(mesh);
    return mesh;
  }

  private buildLabel(
    a: THREE.Vector3,
    b: THREE.Vector3,
    text: string,
  ): THREE.Sprite | null {
    if (typeof document === 'undefined') return null;
    const canvas = document.createElement('canvas');
    canvas.width = 256;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (!ctx) return null;
    ctx.fillStyle = 'rgba(0, 0, 0, 0.65)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.fillStyle = '#ffd400';
    ctx.font = '24px sans-serif';
    ctx.textBaseline = 'middle';
    ctx.textAlign = 'center';
    ctx.fillText(text, canvas.width / 2, canvas.height / 2);
    const tex = new THREE.CanvasTexture(canvas);
    const mat = new THREE.SpriteMaterial({
      map: tex,
      depthTest: false,
      transparent: true,
    });
    const sprite = new THREE.Sprite(mat);
    sprite.position.set((a.x + b.x) / 2, (a.y + b.y) / 2, (a.z + b.z) / 2);
    sprite.scale.set(0.6, 0.15, 1);
    sprite.renderOrder = 1004;
    sprite.userData.isMeasureLabel = true;
    return sprite;
  }

  private clearPending(): void {
    if (this.pendingMarker) {
      this.scene.remove(this.pendingMarker);
      this.pendingMarker.geometry.dispose();
      (this.pendingMarker.material as THREE.Material).dispose();
      this.pendingMarker = null;
    }
    this.pendingPoint = null;
  }
}
