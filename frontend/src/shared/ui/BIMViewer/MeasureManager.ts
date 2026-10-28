// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * MeasureManager - 3D distance tool (RFC 19 §4.4).
 *
 * State machine:
 *   idle → awaiting-first → awaiting-second → done
 * On every click while the tool is active the canvas is raycast against the
 * scene; the first hit contributes a point and after the second point a line
 * with a DOM overlay label is drawn. `Escape` cancels an in-progress
 * measurement; completed measurements persist until `clearAll()` is called.
 *
 * Note: we use a plain DOM overlay positioned via `Vector3.project(camera)`
 * rather than CSS2DObject - fewer dependencies, easy to style with Tailwind.
 */
import * as THREE from 'three';
import type { SceneManager } from './SceneManager';
import type { ElementManager } from './ElementManager';
import {
  angleBetween3,
  centroid3,
  polygonArea3,
  polygonPerimeter3,
} from './measureMath';
import { SnapDetector, type SnapKind } from './SnapDetector';
import { uuid } from '@/shared/lib/browser';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import { toDisplayQuantity } from '@/shared/lib/unitConversion';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

export type MeasureState = 'idle' | 'awaiting-first' | 'awaiting-second' | 'done';

/**
 * Measurement kinds. `distance` is the original two-point ruler (unchanged
 * behaviour / two clicks). `area` collects ≥ 3 points then double-clicks (or
 * Enter) to close the loop. `angle` is a fixed three-click vertex angle.
 */
export type MeasureKind = 'distance' | 'area' | 'angle';

export interface Measurement {
  id: string;
  /** Kind of measurement - drives how `value`/labels are interpreted. */
  kind: MeasureKind;
  /** Every clicked point. For `distance` this is exactly the two endpoints
   *  (kept as the first two entries so existing 2-tuple consumers still
   *  work); for `area` it is the full polygon ring; for `angle` it is the
   *  three vertices [a, b, c] with the angle measured at `b`. */
  points: THREE.Vector3[];
  /** Straight-line distance - only meaningful for `kind === 'distance'`.
   *  Retained as a named field for back-compat with the measurements store
   *  / Tools panel which already read `.distance`. */
  distance: number;
  /** Generic numeric result: metres (distance), m² (area), degrees (angle). */
  value: number;
  /** Closed perimeter in metres - only set for `kind === 'area'`. */
  perimeter?: number;
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
  return uuid();
}

export class MeasureManager {
  private sceneManager: SceneManager;
  private callbacks: MeasureManagerCallbacks;
  private raycaster = new THREE.Raycaster();

  private _active = false;
  private _state: MeasureState = 'idle';
  private _kind: MeasureKind = 'distance';
  private _pendingPoint: THREE.Vector3 | null = null;
  /** Accumulated points for the multi-click kinds (area / angle). */
  private _polyPoints: THREE.Vector3[] = [];
  /** Whether vertex/edge snapping is enabled (toggled from the UI). The
   *  per-feature radius lives on the SnapDetector instance. */
  private _snapEnabled = true;
  private measurements: Measurement[] = [];

  private overlayHost: HTMLDivElement | null = null;
  private pendingMarker: THREE.Mesh | null = null;
  /** Markers for in-progress polygon / angle vertices. */
  private polyMarkers: THREE.Mesh[] = [];
  /** Live rubber-band line shown while collecting polygon / angle points. */
  private rubberLine: THREE.Line | null = null;
  /** Snap refiner - converts raw raycaster hits into vertex / edge-mid /
   *  edge-perp snap points within a 12 px screen-space radius. */
  private snapDetector = new SnapDetector();
  /** Last snap kind picked by the most recent raycastPoint() call - used
   *  by the hover glyph to draw a square (vertex), circle (edge mid) or
   *  diamond (edge perp). */
  private lastSnapKind: SnapKind = 'none';
  /** Sprite that visualises the current snap target while the mouse moves
   *  over geometry with the tool active. Lazily created. */
  private snapGlyph: THREE.Sprite | null = null;
  /** PointerEvent handler - drives the live snap-glyph preview. */
  private boundOnPointerMove: (e: PointerEvent) => void;

  private canvas: HTMLCanvasElement;
  private boundOnPointerDown: (e: PointerEvent) => void;
  private boundOnPointerUp: (e: PointerEvent) => void;
  private boundOnDblClick: (e: MouseEvent) => void;
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
    this.boundOnDblClick = this.onDblClick.bind(this);
    this.boundOnPointerMove = this.onPointerMove.bind(this);

    // Overlay host for labels - absolute, full-bleed, pointer-events none so
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

  get kind(): MeasureKind {
    return this._kind;
  }

  /** Switch measurement kind. Any in-progress measurement is dropped so the
   *  new kind starts clean (a half-traced polygon must not bleed into an
   *  angle, etc). No-op when the kind is unchanged. */
  setKind(kind: MeasureKind): void {
    if (this._kind === kind) return;
    this._kind = kind;
    this.cancelPending();
  }

  get snapEnabled(): boolean {
    return this._snapEnabled;
  }

  setSnapEnabled(on: boolean): void {
    this._snapEnabled = on;
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
      this.canvas.addEventListener('pointermove', this.boundOnPointerMove);
      this.canvas.addEventListener('dblclick', this.boundOnDblClick);
      this.setState('awaiting-first');
      this.canvas.style.cursor = 'crosshair';
    } else {
      this.canvas.removeEventListener('pointerdown', this.boundOnPointerDown);
      this.canvas.removeEventListener('pointerup', this.boundOnPointerUp);
      this.canvas.removeEventListener('pointermove', this.boundOnPointerMove);
      this.canvas.removeEventListener('dblclick', this.boundOnDblClick);
      this.cancelPending();
      this.hideSnapGlyph();
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
    this.clearPolyScratch();
    if (this._active) this.setState('awaiting-first');
    this.sceneManager.requestRender();
  }

  /** Drop the in-progress polygon/angle markers + rubber-band line. */
  private clearPolyScratch(): void {
    for (const m of this.polyMarkers) {
      this.sceneManager.scene.remove(m);
      m.geometry.dispose();
      const mat = m.material as THREE.Material | THREE.Material[];
      if (Array.isArray(mat)) mat.forEach((mm) => mm.dispose());
      else mat.dispose();
    }
    this.polyMarkers = [];
    this._polyPoints = [];
    if (this.rubberLine) {
      this.sceneManager.scene.remove(this.rubberLine);
      this.rubberLine.geometry.dispose();
      const mat = this.rubberLine.material as THREE.Material | THREE.Material[];
      if (Array.isArray(mat)) mat.forEach((mm) => mm.dispose());
      else mat.dispose();
      this.rubberLine = null;
    }
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

  /** Toggle whether a measurement is rendered (line + label hidden when
   *  visible=false, but the entry remains in the list). */
  setMeasurementVisible(id: string, visible: boolean): void {
    const m = this.measurements.find((x) => x.id === id);
    if (!m) return;
    m.line.visible = visible;
    m.labelEl.style.display = visible ? '' : 'none';
    this.sceneManager.requestRender();
  }

  /** Frame the camera on a single measurement's bounding span. */
  focusMeasurement(id: string): void {
    const m = this.measurements.find((x) => x.id === id);
    if (!m) return;
    const box = new THREE.Box3();
    for (const p of m.points) box.expandByPoint(p);
    // Fall back to the scene's zoomToFit-like behaviour by computing a
    // sensible bounding sphere for the points.
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const radius = Math.max(size.length() * 0.5, 1.0);
    const camera = this.sceneManager.camera;
    const offset = camera.position.clone().sub(center).normalize();
    if (offset.lengthSq() < 1e-6) offset.set(1, 1, 1).normalize();
    camera.position.copy(center.clone().add(offset.multiplyScalar(radius * 4)));
    camera.lookAt(center);
    camera.updateProjectionMatrix();
    this.sceneManager.requestRender();
  }

  /** Handle a global keydown - called by the React wrapper. */
  handleKeyDown(e: KeyboardEvent): boolean {
    if (!this._active) return false;
    if (e.key === 'Enter' && this._kind === 'area' && this._polyPoints.length >= 3) {
      // Enter closes the polygon (alternative to double-click).
      this.finalisePolygon();
      return true;
    }
    if (e.key === 'Escape') {
      if (this._pendingPoint || this._polyPoints.length > 0) {
        this.cancelPending();
        return true;
      }
      // No pending point - disable the whole tool.
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
    if (this.snapGlyph) {
      this.sceneManager.scene.remove(this.snapGlyph);
      const mat = this.snapGlyph.material as THREE.SpriteMaterial;
      mat.map?.dispose();
      mat.dispose();
      this.snapGlyph = null;
    }
    this.snapDetector.clearCache();
  }

  /** Public: drop cached snap triangles. Callers (BIMViewer) should invoke
   *  this after a geometry reload so the next refine() rebuilds against the
   *  new mesh data. */
  invalidateSnapCache(): void {
    this.snapDetector.clearCache();
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
    // Piggy-back on rAF - the SceneManager's render loop is on-demand, so we
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

    if (this._kind === 'distance') {
      this.handleDistanceClick(hitPoint);
      return;
    }
    // area / angle: accumulate a point ring.
    this._polyPoints.push(hitPoint.clone());
    this.placePolyMarker(hitPoint);
    this.refreshRubberLine();
    this.setState(
      this._polyPoints.length >= (this._kind === 'angle' ? 1 : 2)
        ? 'awaiting-second'
        : 'awaiting-first',
    );
    // The angle tool is a fixed three-click gesture: auto-finalise on the
    // third point so the user never has to double-click for a simple angle.
    if (this._kind === 'angle' && this._polyPoints.length === 3) {
      this.finaliseAngle();
    }
    this.sceneManager.requestRender();
  }

  private handleDistanceClick(hitPoint: THREE.Vector3): void {
    if (!this._pendingPoint) {
      this._pendingPoint = hitPoint.clone();
      this.placePendingMarker(hitPoint);
      this.setState('awaiting-second');
      this.sceneManager.requestRender();
      return;
    }
    // Second click - finalise the measurement.
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

  /** Double-click closes an in-progress area polygon (≥ 3 points). For the
   *  other kinds it is a no-op so the SelectionManager's own dblclick
   *  isolate behaviour is unaffected (this listener is only attached while
   *  the measure tool is active anyway). */
  private onDblClick(e: MouseEvent): void {
    if (!this._active || this._kind !== 'area') return;
    if (this._polyPoints.length < 3) return;
    e.preventDefault();
    e.stopPropagation();
    this.finalisePolygon();
  }

  private raycastPoint(e: MouseEvent): THREE.Vector3 | null {
    const rect = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
    this.raycaster.setFromCamera(ndc, this.sceneManager.camera);
    // Recurse through the whole scene so BatchedMesh hits register - the
    // individual per-element meshes returned by ElementManager.getAllMeshes()
    // are removed from the scene graph after batching and have no valid
    // world matrix, so raycasting directly against them returns nothing.
    const hits = this.raycaster.intersectObjects(
      this.sceneManager.scene.children,
      true,
    );
    for (const h of hits) {
      if (!(h.object instanceof THREE.Mesh)) continue;
      const surface = h.point.clone();
      if (!this._snapEnabled || !h.face) {
        this.lastSnapKind = 'none';
        return surface;
      }
      const result = this.snapDetector.refine(
        surface,
        h.face,
        h.object,
        this.sceneManager.camera,
        this.canvas,
        // THREE.Intersection.faceIndex is nullable when the geometry has no
        // index buffer; in that case we fall back to the synthesized key
        // inside SnapDetector.
        h.faceIndex ?? undefined,
      );
      this.lastSnapKind = result.kind;
      return result.point;
    }
    this.lastSnapKind = 'none';
    return null;
  }

  /** Hover handler - runs the snap pipeline against the geometry under the
   *  cursor and draws a small glyph (square = vertex, circle = edge midpoint,
   *  diamond = edge perpendicular) at the snap point so the user sees what
   *  they will get on click. No state mutation here - clicks still drive the
   *  pending-point machinery via raycastPoint(). */
  private onPointerMove(e: PointerEvent): void {
    if (!this._active) return;
    const snapped = this.raycastPoint(e);
    if (!snapped || this.lastSnapKind === 'none') {
      this.hideSnapGlyph();
      return;
    }
    this.showSnapGlyph(snapped, this.lastSnapKind);
  }

  /** Lazily build a single sprite-based glyph and reuse its texture across
   *  kinds by repainting the offscreen canvas. The sprite is parented to the
   *  scene so it inherits the same world coordinates as the geometry under
   *  the cursor - no DOM overlay math needed. */
  private showSnapGlyph(point: THREE.Vector3, kind: SnapKind): void {
    if (kind === 'none') {
      this.hideSnapGlyph();
      return;
    }
    if (!this.snapGlyph) {
      const tex = this.makeSnapGlyphTexture('vertex');
      const mat = new THREE.SpriteMaterial({
        map: tex,
        depthTest: false,
        transparent: true,
        sizeAttenuation: false,
      });
      const sprite = new THREE.Sprite(mat);
      // sizeAttenuation:false → scale interpreted as NDC. 0.04 ≈ 12 px on a
      // 600-px-tall canvas; the integrator can fine-tune later.
      sprite.scale.set(0.04, 0.04, 0.04);
      sprite.renderOrder = 1000;
      sprite.userData.kind = 'vertex';
      // TODO(W6.6 integration): expects an "overlay" group on SceneManager -
      // until then we attach directly to the scene root.
      this.sceneManager.scene.add(sprite);
      this.snapGlyph = sprite;
    }
    // Repaint texture only when the glyph kind actually changes.
    if (this.snapGlyph.userData.kind !== kind) {
      const tex = this.makeSnapGlyphTexture(kind);
      const mat = this.snapGlyph.material as THREE.SpriteMaterial;
      mat.map?.dispose();
      mat.map = tex;
      mat.needsUpdate = true;
      this.snapGlyph.userData.kind = kind;
    }
    this.snapGlyph.position.copy(point);
    this.snapGlyph.visible = true;
    this.sceneManager.requestRender();
  }

  private hideSnapGlyph(): void {
    if (!this.snapGlyph) return;
    if (this.snapGlyph.visible) {
      this.snapGlyph.visible = false;
      this.sceneManager.requestRender();
    }
  }

  /** Paint a 32×32 glyph for the given snap kind onto an offscreen canvas
   *  and wrap it in a CanvasTexture. The three kinds use distinct shapes so
   *  experienced users can identify snap type at a glance:
   *    - vertex        → filled square
   *    - edge_midpoint → filled circle
   *    - edge_perp     → diamond (square rotated 45°)
   */
  private makeSnapGlyphTexture(kind: SnapKind): THREE.CanvasTexture {
    const size = 32;
    const canvas = document.createElement('canvas');
    canvas.width = size;
    canvas.height = size;
    const ctx = canvas.getContext('2d');
    // jsdom-friendly fallback: if 2D context is unavailable (rare in browsers,
    // common in jest-style environments) build an empty texture anyway -
    // tests don't exercise the glyph rendering.
    if (ctx) {
      ctx.clearRect(0, 0, size, size);
      ctx.fillStyle = 'rgba(255, 212, 0, 0.95)';
      ctx.strokeStyle = 'rgba(17, 24, 39, 0.95)';
      ctx.lineWidth = 2;
      const cx = size / 2;
      const cy = size / 2;
      const r = size / 2 - 4;
      if (kind === 'vertex') {
        ctx.fillRect(cx - r, cy - r, r * 2, r * 2);
        ctx.strokeRect(cx - r, cy - r, r * 2, r * 2);
      } else if (kind === 'edge_midpoint') {
        ctx.beginPath();
        ctx.arc(cx, cy, r, 0, Math.PI * 2);
        ctx.fill();
        ctx.stroke();
      } else if (kind === 'edge_perp') {
        ctx.beginPath();
        ctx.moveTo(cx, cy - r);
        ctx.lineTo(cx + r, cy);
        ctx.lineTo(cx, cy + r);
        ctx.lineTo(cx - r, cy);
        ctx.closePath();
        ctx.fill();
        ctx.stroke();
      }
    }
    const texture = new THREE.CanvasTexture(canvas);
    texture.needsUpdate = true;
    return texture;
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

  /** Build a styled overlay label element (shared by every kind). */
  private makeLabel(text: string): HTMLDivElement {
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
    label.textContent = text;
    if (this.overlayHost) this.overlayHost.appendChild(label);
    return label;
  }

  private dashedMaterial(): THREE.LineDashedMaterial {
    return new THREE.LineDashedMaterial({
      color: DASH_COLOR,
      linewidth: 1,
      dashSize: 0.3,
      gapSize: 0.15,
      transparent: true,
      opacity: 0.9,
    });
  }

  private finaliseMeasurement(p0: THREE.Vector3, p1: THREE.Vector3): void {
    const dist = p0.distanceTo(p1);
    const geom = new THREE.BufferGeometry().setFromPoints([p0, p1]);
    const line = new THREE.Line(geom, this.dashedMaterial());
    line.computeLineDistances();
    line.renderOrder = 998;
    this.sceneManager.scene.add(line);

    // Storage stays metric-canonical (`dist` in metres); only the overlay
    // label is converted to the user's measurement system for display.
    const system = usePreferencesStore.getState().measurementSystem;
    const d = toDisplayQuantity(dist, 'm', system);
    const label = this.makeLabel(`${fmtFixed(d.value, 2)} ${d.unit}`);
    const measurement: Measurement = {
      id: randomId(),
      kind: 'distance',
      points: [p0.clone(), p1.clone()],
      distance: dist,
      value: dist,
      line,
      labelEl: label,
    };
    this.commitMeasurement(measurement);
  }

  /** Close + persist the in-progress area polygon. */
  private finalisePolygon(): void {
    const pts = this._polyPoints.map((p) => p.clone());
    if (pts.length < 3) {
      this.cancelPending();
      return;
    }
    const area = polygonArea3(pts);
    const perimeter = polygonPerimeter3(pts);
    // Closed loop: repeat the first point so the outline renders shut.
    const geom = new THREE.BufferGeometry().setFromPoints([...pts, pts[0]!]);
    const line = new THREE.Line(geom, this.dashedMaterial());
    line.computeLineDistances();
    line.renderOrder = 998;
    this.sceneManager.scene.add(line);

    // Storage stays metric-canonical (`area` in m²); only the overlay label
    // is converted to the user's measurement system for display.
    const system = usePreferencesStore.getState().measurementSystem;
    const a = toDisplayQuantity(area, 'm²', system);
    const label = this.makeLabel(
      `${a.value.toLocaleString(getNumberLocale(), { maximumFractionDigits: 2 })} ${a.unit}`,
    );
    const measurement: Measurement = {
      id: randomId(),
      kind: 'area',
      points: pts,
      distance: 0,
      value: area,
      perimeter,
      line,
      labelEl: label,
    };
    this.clearPolyScratch();
    this.commitMeasurement(measurement);
  }

  /** Persist the three-point angle once the third vertex is clicked. */
  private finaliseAngle(): void {
    const pts = this._polyPoints.map((p) => p.clone());
    if (pts.length < 3) return;
    const [a, b, c] = pts as [THREE.Vector3, THREE.Vector3, THREE.Vector3];
    const deg = angleBetween3(a, b, c);
    const geom = new THREE.BufferGeometry().setFromPoints([a, b, c]);
    const line = new THREE.Line(geom, this.dashedMaterial());
    line.computeLineDistances();
    line.renderOrder = 998;
    this.sceneManager.scene.add(line);

    const label = this.makeLabel(`${fmtFixed(deg, 1)}°`);
    const measurement: Measurement = {
      id: randomId(),
      kind: 'angle',
      points: [a, b, c],
      distance: 0,
      value: deg,
      line,
      labelEl: label,
    };
    this.clearPolyScratch();
    this.commitMeasurement(measurement);
  }

  private commitMeasurement(measurement: Measurement): void {
    this.measurements.push(measurement);
    this.callbacks.onMeasurementAdded?.(measurement);
    this.callbacks.onMeasurementsChanged?.(this.measurements.length);
    // Chain the next measurement of the same kind without re-clicking.
    this.setState('done');
    this.setState('awaiting-first');
    this.sceneManager.requestRender();
  }

  private polyMarkerMesh(point: THREE.Vector3): THREE.Mesh {
    const geom = new THREE.SphereGeometry(DOT_RADIUS, 10, 10);
    const mat = new THREE.MeshBasicMaterial({ color: DOT_COLOR });
    const mesh = new THREE.Mesh(geom, mat);
    mesh.position.copy(point);
    mesh.renderOrder = 999;
    return mesh;
  }

  private placePolyMarker(point: THREE.Vector3): void {
    const mesh = this.polyMarkerMesh(point);
    this.sceneManager.scene.add(mesh);
    this.polyMarkers.push(mesh);
  }

  /** Redraw the open scratch line connecting the collected polygon/angle
   *  points (no closing segment until the user finalises). */
  private refreshRubberLine(): void {
    if (this.rubberLine) {
      this.sceneManager.scene.remove(this.rubberLine);
      this.rubberLine.geometry.dispose();
      (this.rubberLine.material as THREE.Material).dispose();
      this.rubberLine = null;
    }
    if (this._polyPoints.length < 2) return;
    const geom = new THREE.BufferGeometry().setFromPoints(this._polyPoints);
    const mat = new THREE.LineBasicMaterial({
      color: DASH_COLOR,
      transparent: true,
      opacity: 0.7,
    });
    const line = new THREE.Line(geom, mat);
    line.renderOrder = 997;
    this.sceneManager.scene.add(line);
    this.rubberLine = line;
  }

  /** Anchor point in world space for a measurement's overlay label. */
  private labelAnchor(m: Measurement): THREE.Vector3 {
    if (m.kind === 'distance') {
      return m.points[0]!.clone().add(m.points[1]!).multiplyScalar(0.5);
    }
    if (m.kind === 'angle') {
      // Sit the angle label on the vertex itself.
      return m.points[1]!.clone();
    }
    // area → centroid
    const c = centroid3(m.points);
    return new THREE.Vector3(c.x, c.y, c.z);
  }

  private updateLabelPositions(): void {
    if (!this.overlayHost) return;
    const camera = this.sceneManager.camera;
    const rect = this.canvas.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    for (const m of this.measurements) {
      const projected = this.labelAnchor(m).project(camera);
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
