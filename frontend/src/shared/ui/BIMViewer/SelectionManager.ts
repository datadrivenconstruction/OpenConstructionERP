/**
 * SelectionManager — handles click / hover selection with highlight materials.
 *
 * Uses raycasting against BIM element meshes. Supports:
 * - Single click selection
 * - Ctrl+click multi-select (toggle)
 * - Shift+click add to selection
 * - Double-click to isolate
 * - Right-click context menu
 * - Hover highlighting (temporary)
 * - Programmatic selection from parent
 */

import * as THREE from 'three';
import type { SceneManager } from './SceneManager';
import type { ElementManager, BIMElementData } from './ElementManager';

export interface SelectionCallbacks {
  onElementSelect?: (elementId: string | null) => void;
  onElementHover?: (elementId: string | null) => void;
  /** Fired when the selection set changes (add/remove/clear). The parent
   *  uses this to drive the floating selection toolbar and context menu. */
  onSelectionChange?: (selectedIds: string[]) => void;
  /** Fired on right-click over an element (or multi-selection). */
  onContextMenu?: (event: MouseEvent, elementId: string | null) => void;
  /** Fired on double-click on an element (isolate) or empty space (show all). */
  onDoubleClick?: (elementId: string | null) => void;
}

const HIGHLIGHT_COLOR = 0x2979ff; // selection blue
const HOVER_COLOR = 0x42a5f5;    // lighter hover blue
const HIGHLIGHT_OPACITY = 0.95;
const HOVER_OPACITY = 0.9;

export class SelectionManager {
  private sceneManager: SceneManager;
  private elementManager: ElementManager;
  private callbacks: SelectionCallbacks;
  private raycaster = new THREE.Raycaster();

  private selectedIds = new Set<string>();
  private hoveredId: string | null = null;

  /** Store original materials so they can be restored after deselection. */
  private originalMaterials = new Map<string, THREE.Material>();
  private highlightMaterial: THREE.MeshStandardMaterial;
  private hoverMaterial: THREE.MeshStandardMaterial;

  private canvas: HTMLCanvasElement;
  private boundOnPointerDown: (e: PointerEvent) => void;
  private boundOnPointerUp: (e: PointerEvent) => void;
  private boundOnMouseMove: (e: MouseEvent) => void;
  private boundOnContextMenu: (e: MouseEvent) => void;
  private boundOnDblClick: (e: MouseEvent) => void;

  /** Track pointer down position to distinguish clicks from drags. */
  private pointerDownPos: { x: number; y: number } | null = null;
  private pointerDownTime = 0;
  private readonly CLICK_THRESHOLD = 5; // max px movement to count as click
  private readonly CLICK_TIME_LIMIT = 500; // max ms between down and up

  constructor(
    sceneManager: SceneManager,
    elementManager: ElementManager,
    callbacks: SelectionCallbacks,
  ) {
    this.sceneManager = sceneManager;
    this.elementManager = elementManager;
    this.callbacks = callbacks;
    this.canvas = sceneManager.renderer.domElement;

    // Highlight materials
    this.highlightMaterial = new THREE.MeshStandardMaterial({
      color: HIGHLIGHT_COLOR,
      roughness: 0.5,
      metalness: 0.2,
      transparent: true,
      opacity: HIGHLIGHT_OPACITY,
      emissive: new THREE.Color(HIGHLIGHT_COLOR),
      emissiveIntensity: 0.15,
    });

    this.hoverMaterial = new THREE.MeshStandardMaterial({
      color: HOVER_COLOR,
      roughness: 0.6,
      metalness: 0.1,
      transparent: true,
      opacity: HOVER_OPACITY,
      emissive: new THREE.Color(HOVER_COLOR),
      emissiveIntensity: 0.1,
    });

    // Bind event listeners.
    // We use pointerdown+pointerup instead of 'click' because OrbitControls
    // intercepts Ctrl+click / Shift+click for camera manipulation. By
    // tracking the pointer ourselves, we can detect short stationary clicks
    // (even with modifier keys) that OrbitControls would otherwise swallow.
    this.boundOnPointerDown = this.onPointerDown.bind(this);
    this.boundOnPointerUp = this.onPointerUp.bind(this);
    this.boundOnMouseMove = this.onMouseMove.bind(this);
    this.boundOnContextMenu = this.onContextMenu.bind(this);
    this.boundOnDblClick = this.onDblClick.bind(this);
    this.canvas.addEventListener('pointerdown', this.boundOnPointerDown);
    this.canvas.addEventListener('pointerup', this.boundOnPointerUp);
    this.canvas.addEventListener('mousemove', this.boundOnMouseMove);
    this.canvas.addEventListener('contextmenu', this.boundOnContextMenu);
    this.canvas.addEventListener('dblclick', this.boundOnDblClick);
  }

  private getMouseCoords(e: MouseEvent): THREE.Vector2 {
    const rect = this.canvas.getBoundingClientRect();
    return new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1,
    );
  }

  private raycast(mouseCoords: THREE.Vector2): THREE.Intersection | null {
    this.raycaster.setFromCamera(mouseCoords, this.sceneManager.camera);

    // Raycast against the ENTIRE scene recursively. This catches:
    // - Individual meshes (placeholder boxes)
    // - DAE-loaded meshes still in scene graph
    // - BatchedMesh objects (which replace individual meshes for perf)
    // We cannot raycast against allDaeMeshes because batchMeshesByMaterial
    // removes them from the scene graph (no valid world matrix).
    const intersects = this.raycaster.intersectObjects(
      this.sceneManager.scene.children,
      true,
    );

    for (const hit of intersects) {
      // Skip non-mesh hits (grid, lights, helpers)
      if (!(hit.object instanceof THREE.Mesh)) continue;

      // Walk up hierarchy to find elementId
      let obj: THREE.Object3D | null = hit.object;
      while (obj) {
        const eid = (obj.userData as { elementId?: string | null }).elementId;
        if (eid) {
          if (obj !== hit.object) {
            (hit.object.userData as Record<string, unknown>).elementId = eid;
          }
          return hit;
        }
        obj = obj.parent;
      }

      // For BatchedMesh hits: try to resolve via instanceId
      if ((hit as { instanceId?: number }).instanceId != null) {
        // BatchedMesh — the individual mesh that was batched still lives
        // in meshMap/allDaeMeshes with a batchHandle. Find it by scanning
        // allDaeMeshes for one whose batchHandle.batchedMesh === hit.object.
        const batchedObj = hit.object;
        const instId = (hit as { instanceId?: number }).instanceId;
        for (const mesh of this.elementManager.getAllMeshes()) {
          const handle = (mesh.userData as { batchHandle?: { batched: unknown; instanceId: number } }).batchHandle;
          if (handle && handle.batched === batchedObj && handle.instanceId === instId) {
            const eid = (mesh.userData as { elementId?: string }).elementId;
            if (eid) {
              (hit.object.userData as Record<string, unknown>).elementId = eid;
              return hit;
            }
          }
        }
      }
    }
    return null;
  }

  /** Raycast from a mouse event and return the element ID under the cursor. */
  raycastElementId(e: MouseEvent): string | null {
    const coords = this.getMouseCoords(e);
    const hit = this.raycast(coords);
    if (!hit) return null;
    return (hit.object.userData as { elementId?: string }).elementId ?? null;
  }

  private onPointerDown(e: PointerEvent): void {
    if (e.button !== 0) return; // only left button
    this.pointerDownPos = { x: e.clientX, y: e.clientY };
    this.pointerDownTime = Date.now();
  }

  private onPointerUp(e: PointerEvent): void {
    if (e.button !== 0 || !this.pointerDownPos) return;

    // Check if this was a click (short, stationary) or a drag
    const dx = e.clientX - this.pointerDownPos.x;
    const dy = e.clientY - this.pointerDownPos.y;
    const dist = Math.sqrt(dx * dx + dy * dy);
    const elapsed = Date.now() - this.pointerDownTime;
    this.pointerDownPos = null;

    if (dist > this.CLICK_THRESHOLD || elapsed > this.CLICK_TIME_LIMIT) {
      return; // was a drag, not a click
    }

    // This is a genuine click — handle selection
    const coords = this.getMouseCoords(e);
    const hit = this.raycast(coords);

    if (!hit) {
      // Click on empty space -- deselect all (unless Ctrl is held)
      if (!e.ctrlKey && !e.metaKey) {
        this.clearSelection();
        this.callbacks.onElementSelect?.(null);
        this.notifySelectionChange();
      }
      return;
    }

    const elementId = (hit.object.userData as { elementId?: string }).elementId;
    if (!elementId) return;

    if (e.ctrlKey || e.metaKey) {
      // Multi-select toggle
      if (this.selectedIds.has(elementId)) {
        this.deselectElement(elementId);
      } else {
        this.selectElement(elementId);
      }
    } else if (e.shiftKey) {
      // Shift+click: add to selection (no toggle -- always add)
      if (!this.selectedIds.has(elementId)) {
        this.selectElement(elementId);
      }
    } else {
      // Single select -- clear others first
      this.clearSelection();
      this.selectElement(elementId);
    }

    // Report the most recently clicked element
    this.callbacks.onElementSelect?.(elementId);
    this.notifySelectionChange();
  }

  private onContextMenu(e: MouseEvent): void {
    e.preventDefault();
    const coords = this.getMouseCoords(e);
    const hit = this.raycast(coords);
    const elementId = hit
      ? (hit.object.userData as { elementId?: string }).elementId ?? null
      : null;

    // If right-clicking on an element not in the selection, select it
    if (elementId && !this.selectedIds.has(elementId)) {
      if (!e.ctrlKey && !e.metaKey) {
        this.clearSelection();
      }
      this.selectElement(elementId);
      this.callbacks.onElementSelect?.(elementId);
      this.notifySelectionChange();
    }

    this.callbacks.onContextMenu?.(e, elementId);
  }

  private onDblClick(e: MouseEvent): void {
    const coords = this.getMouseCoords(e);
    const hit = this.raycast(coords);
    const elementId = hit
      ? (hit.object.userData as { elementId?: string }).elementId ?? null
      : null;

    this.callbacks.onDoubleClick?.(elementId);
  }

  private onMouseMove(e: MouseEvent): void {
    const coords = this.getMouseCoords(e);
    const hit = this.raycast(coords);
    const elementId = hit
      ? (hit.object.userData as { elementId?: string }).elementId ?? null
      : null;

    if (elementId === this.hoveredId) return;

    // Remove previous hover
    if (this.hoveredId && !this.selectedIds.has(this.hoveredId)) {
      this.restoreMaterial(this.hoveredId);
    }

    this.hoveredId = elementId;

    // Apply hover highlight (only if not already selected)
    if (elementId && !this.selectedIds.has(elementId)) {
      const mesh = this.elementManager.getMesh(elementId);
      if (mesh) {
        this.saveMaterial(elementId, mesh);
        mesh.material = this.hoverMaterial;
      }
    }

    this.canvas.style.cursor = elementId ? 'pointer' : 'default';
    this.callbacks.onElementHover?.(elementId);
  }

  /** Select an element programmatically. */
  selectElement(elementId: string): void {
    const mesh = this.elementManager.getMesh(elementId);
    if (!mesh) return;

    this.saveMaterial(elementId, mesh);
    mesh.material = this.highlightMaterial;
    this.selectedIds.add(elementId);
  }

  /** Deselect an element. */
  deselectElement(elementId: string): void {
    this.restoreMaterial(elementId);
    this.selectedIds.delete(elementId);
  }

  /** Clear all selections. */
  clearSelection(): void {
    for (const id of this.selectedIds) {
      this.restoreMaterial(id);
    }
    this.selectedIds.clear();
  }

  /** Set selection from external (parent component). */
  setSelection(elementIds: string[]): void {
    this.clearSelection();
    for (const id of elementIds) {
      this.selectElement(id);
    }
  }

  /** Get currently selected element IDs. */
  getSelectedIds(): string[] {
    return Array.from(this.selectedIds);
  }

  /** Get count of selected elements. */
  getSelectedCount(): number {
    return this.selectedIds.size;
  }

  /** Get selected element data. */
  getSelectedElements(): BIMElementData[] {
    const result: BIMElementData[] = [];
    for (const id of this.selectedIds) {
      const data = this.elementManager.getElementData(id);
      if (data) result.push(data);
    }
    return result;
  }

  private saveMaterial(elementId: string, mesh: THREE.Mesh): void {
    if (!this.originalMaterials.has(elementId)) {
      this.originalMaterials.set(elementId, mesh.material as THREE.Material);
    }
  }

  private restoreMaterial(elementId: string): void {
    const original = this.originalMaterials.get(elementId);
    if (!original) return;
    const mesh = this.elementManager.getMesh(elementId);
    if (mesh) {
      mesh.material = original;
    }
    // Always remove from map — even if the mesh was removed, keeping the
    // entry would leak the material reference indefinitely.
    this.originalMaterials.delete(elementId);
  }

  /** Notify parent about selection changes. */
  private notifySelectionChange(): void {
    this.callbacks.onSelectionChange?.(this.getSelectedIds());
  }

  /** Dispose event listeners and materials. */
  dispose(): void {
    this.canvas.removeEventListener('pointerdown', this.boundOnPointerDown);
    this.canvas.removeEventListener('pointerup', this.boundOnPointerUp);
    this.canvas.removeEventListener('mousemove', this.boundOnMouseMove);
    this.canvas.removeEventListener('contextmenu', this.boundOnContextMenu);
    this.canvas.removeEventListener('dblclick', this.boundOnDblClick);
    this.highlightMaterial.dispose();
    this.hoverMaterial.dispose();
    this.originalMaterials.clear();
    this.selectedIds.clear();
    this.canvas.style.cursor = 'default';
  }
}
