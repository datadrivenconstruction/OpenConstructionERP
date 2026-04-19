/**
 * MeasureManager — 3D distance tool (RFC 19 §4.4).
 *
 * State machine:
 *   idle → awaiting-first → awaiting-second → done
 * On every click while the tool is active the canvas is raycast against the
 * scene; the first hit contributes a point and after the second point a line
 * with a DOM overlay label is drawn. `Escape` cancels an in-progress
 * measurement; completed measurements persist until `clearAll()` is called.
 *
 * Note: we use a plain DOM overlay positioned via `Vector3.project(camera)`
 * rather than CSS2DObject — fewer dependencies, easy to style with Tailwind.
 */
import * as THREE from 'three';
import type { SceneManager } from './SceneManager';
import type { ElementManager } from './ElementManager';

export type MeasureState = 'idle' | 'awaiting-first' | 'awaiting-second' | 'done';

export interface Measurement {
  id: string;
  points: [THREE.Vector3, THREE.Vector3];
  distance: number;
  line: THREE.Line;
  labelEl: HTMLDivElement;
}

export interface MeasureManagerCallbacks {
  onStateChange?: (state: MeasureState) => void;
  onMeasurementAdded?: (measurement: Measurement) => void;
  onMeasurementsChanged?: (count: number) => void;
  /** Fired when a click while the tool is active missed the model geometry.
   *  The viewer surfaces this as a toast so users know their click registered
   *  but did not land on a raycastable surface. */
  onMiss?: () => void;
}

const DASH_COLOR = 0xffd400;
const DOT_COLOR = 0xffffff;
const DOT_RADIUS = 0.08;

function randomId(): string {
  if (typeof crypto !== 'undefined' && 'randomUUID' in crypto) {
    return crypto.randomUUID();
  }
  return `m_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
}

export class MeasureManager {
  private sceneManager: SceneManager;
  private callbacks: MeasureManagerCallbacks;
  private raycaster = new THREE.Raycaster();

  private _active = false;
  private _state: MeasureState = 'idle';
  private _pendingPoint: THREE.Vector3 | null = null;
  private measurements: Measurement[] = [];

  private overlayHost: HTMLDivElement | null = null;
  private pendingMarker: THREE.Mesh | null = null;

  private canvas: HTMLCanvasElement;
  private boundOnPointerDown: (e: PointerEvent) => void;
  private boundOnPointerUp: (e: PointerEvent) => void;
  private pointerDownPos: { x: number; y: number } | null = null;
  private pointerDownTime = 0;
  private readonly CLICK_THRESHOLD = 5;
  private readonly CLICK_TIME_LIMIT = 400;

  private rafId: number | null = null;

  constructor(
    sceneManager: SceneManager,
    // Kept for call-site compatibility; the ruler now raycasts against the
    // full scene graph so BatchedMesh hits register without touching the
    // ElementManager registry.
    _elementManager: ElementManager,
    callbacks: MeasureManagerCallbacks = {},
  ) {
    this.sceneManager = sceneManager;
    this.callbacks = callbacks;
    this.canvas = sceneManager.renderer.domElement;

    this.boundOnPointerDown = this.onPointerDown.bind(this);
    this.boundOnPointerUp = this.onPointerUp.bind(this);

    // Overlay host for labels — absolute, full-bleed, pointer-events none so
    // clicks still reach the canvas underneath.
    this.ensureOverlayHost();
    this.scheduleOverlayLoop();
  }

  get active(): boolean {
    return this._active;
  }

  get state(): MeasureState {
    return this._state;
  }

  getMeasurements(): Measurement[] {
    return this.measurements.slice();
  }

  /** Toggle the measure tool. When disabled any pending point is dropped. */
  setActive(active: boolean): void {
    if (this._active === active) return;
    this._active = active;
    if (active) {
      this.canvas.addEventListener('pointerdown', this.boundOnPointerDown);
      this.canvas.addEventListener('pointerup', this.boundOnPointerUp);
      this.setState('awaiting-first');
      this.canvas.style.cursor = 'crosshair';
    } else {
      this.canvas.removeEventListener('pointerdown', this.boundOnPointerDown);
      this.canvas.removeEventListener('pointerup', this.boundOnPointerUp);
      this.cancelPending();
      this.setState('idle');
      this.canvas.style.cursor = '';
    }
  }

  /** Abort an in-progress measurement (Escape, tool disable, etc). */
  cancelPending(): void {
    this._pendingPoint = null;
    if (this.pendingMarker) {
      this.sceneManager.scene.remove(this.pendingMarker);
      this.pendingMarker.geometry.dispose();
      const m = this.pendingMarker.material as THREE.Material | THREE.Material[];
      if (Array.isArray(m)) m.forEach((mm) => mm.dispose());
      else m.dispose();
      this.pendingMarker = null;
    }
    if (this._active) this.setState('awaiting-first');
    this.sceneManager.requestRender();
  }

  /** Drop every stored measurement and any in-progress point. */
  clearAll(): void {
    for (const m of this.measurements) {
      this.sceneManager.scene.remove(m.line);
      m.line.geometry.dispose();
      const mat = m.line.material as THREE.Material | THREE.Material[];
      if (Array.isArray(mat)) mat.forEach((mm) => mm.dispose());
      else mat.dispose();
      m.labelEl.remove();
    }
    this.measurements = [];
    this.cancelPending();
    this.callbacks.onMeasurementsChanged?.(0);
  }

  /** Public: remove a single measurement by id. */
  removeMeasurement(id: string): void {
    const idx = this.measurements.findIndex((m) => m.id === id);
    if (idx < 0) return;
    const m = this.measurements[idx]!;
    this.sceneManager.scene.remove(m.line);
    m.line.geometry.dispose();
    const mat = m.line.material as THREE.Material | THREE.Material[];
    if (Array.isArray(mat)) mat.forEach((mm) => mm.dispose());
    else mat.dispose();
    m.labelEl.remove();
    this.measurements.splice(idx, 1);
    this.callbacks.onMeasurementsChanged?.(this.measurements.length);
    this.sceneManager.requestRender();
  }

  /** Handle a global keydown — called by the React wrapper. */
  handleKeyDown(e: KeyboardEvent): boolean {
    if (!this._active) return false;
    if (e.key === 'Escape') {
      if (this._pendingPoint) {
        this.cancelPending();
        return true;
      }
      // No pending point — disable the whole tool.
      this.setActive(false);
      return true;
    }
    return false;
  }

  /** Dispose DOM, scene, and event handlers. */
  dispose(): void {
    this.setActive(false);
    this.clearAll();
    if (this.rafId !== null) {
      cancelAnimationFrame(this.rafId);
      this.rafId = null;
    }
    if (this.overlayHost) {
      this.overlayHost.remove();
      this.overlayHost = null;
    }
  }

  /* ── Internals ─────────────────────────────────────────────────────── */

  private setState(next: MeasureState): void {
    if (this._state === next) return;
    this._state = next;
    this.callbacks.onStateChange?.(next);
  }

  private ensureOverlayHost(): void {
    if (this.overlayHost) return;
    const parent = this.canvas.parentElement;
    if (!parent) return;
    const host = document.createElement('div');
    host.className = 'oe-bim-measure-overlay';
    host.style.position = 'absolute';
    host.style.inset = '0';
    host.style.pointerEvents = 'none';
    host.style.overflow = 'hidden';
    parent.appendChild(host);
    this.overlayHost = host;
  }

  private scheduleOverlayLoop(): void {
    // Piggy-back on rAF — the SceneManager's render loop is on-demand, so we
    // run a lightweight rAF to reposition labels when the camera moves.
    const loop = () => {
      this.updateLabelPositions();
      this.rafId = requestAnimationFrame(loop);
    };
    this.rafId = requestAnimationFrame(loop);
  }

  private onPointerDown(e: PointerEvent): void {
    if (e.button !== 0) return;
    this.pointerDownPos = { x: e.clientX, y: e.clientY };
    this.pointerDownTime = Date.now();
  }

  private onPointerUp(e: PointerEvent): void {
    if (e.button !== 0 || !this.pointerDownPos) return;
    const dx = e.clientX - this.pointerDownPos.x;
    const dy = e.clientY - this.pointerDownPos.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const elapsed = Date.now() - this.pointerDownTime;
    this.pointerDownPos = null;
    if (dist > this.CLICK_THRESHOLD || elapsed > this.CLICK_TIME_LIMIT) return;

    const hitPoint = this.raycastPoint(e);
    if (!hitPoint) {
      this.callbacks.onMiss?.();
      return;
    }

    if (!this._pendingPoint) {
      this._pendingPoint = hitPoint.clone();
      this.placePendingMarker(hitPoint);
      this.setState('awaiting-second');
      this.sceneManager.requestRender();
      return;
    }
    // Second click — finalise the measurement.
    this.finaliseMeasurement(this._pendingPoint, hitPoint);
    this._pendingPoint = null;
    if (this.pendingMarker) {
      this.sceneManager.scene.remove(this.pendingMarker);
      this.pendingMarker.geometry.dispose();
      const m = this.pendingMarker.material as THREE.Material | THREE.Material[];
      if (Array.isArray(m)) m.forEach((mm) => mm.dispose());
      else m.dispose();
      this.pendingMarker = null;
    }
    this.setState('done');
    // Loop back immediately so the user can chain measurements without
    // re-clicking the toolbar button.
    this.setState('awaiting-first');
  }

  private raycastPoint(e: MouseEvent): THREE.Vector3 | null {
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.sceneManager.camera);
    // Recurse through the whole scene so BatchedMesh hits register — the
    // individual per-element meshes returned by ElementManager.getAllMeshes()
    // are removed from the scene graph after batching and have no valid
    // world matrix, so raycasting directly against them returns nothing.
    const hits = this.raycaster.intersectObjects(
      this.sceneManager.scene.children,
      true,
    );
    for (const h of hits) {
      if (!(h.object instanceof THREE.Mesh)) continue;
      return h.point.clone();
    }
    return null;
  }

  private placePendingMarker(point: THREE.Vector3): void {
    const geom = new THREE.SphereGeometry(DOT_RADIUS, 10, 10);
    const mat = new THREE.MeshBasicMaterial({ color: DOT_COLOR });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.copy(point);
    mesh.renderOrder = 999;
    this.sceneManager.scene.add(mesh);
    this.pendingMarker = mesh;
  }

  private finaliseMeasurement(p0: THREE.Vector3, p1: THREE.Vector3): void {
    const dist = p0.distanceTo(p1);
    // Dashed line between the two clicked points.
    const geom = new THREE.BufferGeometry().setFromPoints([p0, p1]);
    const mat = new THREE.LineDashedMaterial({
      color: DASH_COLOR,
      linewidth: 1,
      dashSize: 0.3,
      gapSize: 0.15,
      transparent: true,
      opacity: 0.9,
    });
    const line = new THREE.Line(geom, mat);
    line.computeLineDistances();
    line.renderOrder = 998;
    this.sceneManager.scene.add(line);

    // HTML label — we project the midpoint every frame in updateLabelPositions.
    const label = document.createElement('div');
    label.className = 'oe-bim-measure-label';
    label.style.position = 'absolute';
    label.style.transform = 'translate(-50%, -50%)';
    label.style.padding = '2px 6px';
    label.style.fontSize = '11px';
    label.style.fontWeight = '600';
    label.style.borderRadius = '6px';
    label.style.background = 'rgba(17, 24, 39, 0.92)';
    label.style.color = '#ffd400';
    label.style.border = '1px solid rgba(255, 212, 0, 0.5)';
    label.style.whiteSpace = 'nowrap';
    label.style.pointerEvents = 'none';
    label.textContent = `${dist.toFixed(2)} m`;
    if (this.overlayHost) this.overlayHost.appendChild(label);

    const measurement: Measurement = {
      id: randomId(),
      points: [p0.clone(), p1.clone()],
      distance: dist,
      line,
      labelEl: label,
    };
    this.measurements.push(measurement);
    this.callbacks.onMeasurementAdded?.(measurement);
    this.callbacks.onMeasurementsChanged?.(this.measurements.length);
    this.sceneManager.requestRender();
  }

  private updateLabelPositions(): void {
    if (!this.overlayHost) return;
    const camera = this.sceneManager.camera;
    const rect = this.canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    for (const m of this.measurements) {
      const mid = m.points[0].clone().add(m.points[1]).multiplyScalar(0.5);
      const projected = mid.project(camera);
      // Hide label when behind camera (z > 1 after projection).
      if (projected.z > 1 || projected.z < -1) {
        m.labelEl.style.display = 'none';
        continue;
      }
      m.labelEl.style.display = '';
      const x = (projected.x * 0.5 + 0.5) * width;
      const y = (1 - (projected.y * 0.5 + 0.5)) * height;
      m.labelEl.style.left = `${x}px`;
      m.labelEl.style.top = `${y}px`;
    }
  }
}
