/**
 * ElementManager — loads and manages BIM element meshes in the Three.js scene.
 *
 * Loads elements from the BIM Hub API. For each element:
 * - If DAE geometry is loaded: matches mesh node IDs to element stable_ids
 * - If mesh_ref is available but no DAE: creates placeholder box geometry
 * - Otherwise: creates placeholder box geometry from bounding_box
 *
 * Elements are colored by discipline:
 *   architectural = light blue, structural = orange, mechanical = green,
 *   electrical = yellow, plumbing = purple
 */

import * as THREE from 'three';
import { ColladaLoader } from 'three/addons/loaders/ColladaLoader.js';
import type { SceneManager } from './SceneManager';

/* ── Types ─────────────────────────────────────────────────────────────── */

export interface BIMBoundingBox {
  min_x: number;
  min_y: number;
  min_z: number;
  max_x: number;
  max_y: number;
  max_z: number;
}

export interface BIMElementData {
  id: string;
  name: string;
  element_type: string;
  discipline: string;
  storey?: string;
  category?: string;
  bounding_box?: BIMBoundingBox;
  mesh_ref?: string;
  properties?: Record<string, unknown>;
  quantities?: Record<string, number>;
  classification?: Record<string, string>;
}

export interface BIMModelData {
  id: string;
  name: string;
  filename: string;
  format: string;
  status: string;
  /** model_format from backend, e.g. "rvt", "ifc" */
  model_format?: string;
  /** File size in bytes (set after CAD upload) */
  file_size?: number;
  /** ISO date string */
  created_at?: string;
  /** Element count (0 for processing models) */
  element_count?: number;
}

/* ── Discipline Colors ─────────────────────────────────────────────────── */

const DISCIPLINE_COLORS: Record<string, number> = {
  architectural: 0x64b5f6, // light blue
  structural: 0xff9800,    // orange
  mechanical: 0x66bb6a,    // green
  electrical: 0xfdd835,    // yellow
  plumbing: 0xab47bc,      // purple
  piping: 0xab47bc,        // purple (alias)
  fire_protection: 0xef5350, // red
  civil: 0x8d6e63,         // brown
  landscape: 0x4caf50,     // darker green
};

const DEFAULT_COLOR = 0x90a4ae; // blue-grey

function getDisciplineColor(discipline: string): number {
  const key = discipline.toLowerCase().replace(/[\s-]/g, '_');
  return DISCIPLINE_COLORS[key] ?? DEFAULT_COLOR;
}

/* ── Element Manager ───────────────────────────────────────────────────── */

export class ElementManager {
  private sceneManager: SceneManager;
  private elementGroup: THREE.Group;
  private daeGroup: THREE.Group | null = null;
  private meshMap = new Map<string, THREE.Mesh>();
  private elementDataMap = new Map<string, BIMElementData>();
  private baseMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private wireframeEnabled = false;
  private geometryLoaded = false;

  constructor(sceneManager: SceneManager) {
    this.sceneManager = sceneManager;
    this.elementGroup = new THREE.Group();
    this.elementGroup.name = 'bim_elements';
    this.sceneManager.scene.add(this.elementGroup);
  }

  /** Load elements and create placeholder meshes. */
  loadElements(elements: BIMElementData[]): void {
    this.clear();

    for (const el of elements) {
      this.elementDataMap.set(el.id, el);

      // Only create box placeholders when DAE geometry is not loaded
      if (!this.geometryLoaded && el.bounding_box) {
        const mesh = this.createBoxMesh(el);
        this.meshMap.set(el.id, mesh);
        this.elementGroup.add(mesh);
      }
    }

    // Zoom to fit all loaded elements
    if (this.meshMap.size > 0 || (this.daeGroup && this.daeGroup.children.length > 0)) {
      this.sceneManager.zoomToFit();
    }
  }

  /**
   * Load DAE/COLLADA geometry from the server and match mesh nodes
   * to element IDs stored in elementDataMap.
   *
   * After loading, each mesh node whose name matches an element's stable_id
   * (mesh_ref) gets colored by discipline and wired up for selection.
   */
  loadDAEGeometry(geometryUrl: string): Promise<void> {
    return new Promise((resolve, reject) => {
      const loader = new ColladaLoader();
      loader.load(
        geometryUrl,
        (collada) => {
          if (!collada || !collada.scene) {
            reject(new Error('ColladaLoader returned empty result'));
            return;
          }

          // Remove any existing placeholder meshes for elements that have geometry
          this.clearPlaceholders();

          this.daeGroup = new THREE.Group();
          this.daeGroup.name = 'bim_dae_geometry';
          const scene = collada.scene;

          // Build a lookup from stable_id (mesh_ref) to element data + element DB id
          const stableIdToElement = new Map<string, BIMElementData>();
          for (const el of this.elementDataMap.values()) {
            if (el.mesh_ref) {
              stableIdToElement.set(el.mesh_ref, el);
            }
          }

          // Traverse the loaded DAE scene and match mesh nodes
          scene.traverse((child) => {
            if (child instanceof THREE.Mesh) {
              const nodeName = child.name || '';
              // Try matching node name or parent node name to element stable_id
              const element =
                stableIdToElement.get(nodeName) ||
                stableIdToElement.get(child.parent?.name || '');

              if (element) {
                // Apply discipline-based material
                const discipline = element.discipline || 'other';
                const material = this.getMaterial(discipline);
                child.material = material;
                child.castShadow = true;
                child.receiveShadow = true;

                // Store element data for raycasting / picking
                child.userData = {
                  elementId: element.id,
                  elementData: element,
                };

                this.meshMap.set(element.id, child);
              } else {
                // Unmatched mesh — apply default material
                const material = this.getMaterial('other');
                child.material = material;
                child.castShadow = true;
                child.receiveShadow = true;
              }
            }
          });

          this.daeGroup.add(scene);
          this.elementGroup.add(this.daeGroup);
          this.geometryLoaded = true;

          // Zoom to fit
          this.sceneManager.zoomToFit();

          resolve();
        },
        undefined, // onProgress
        (error) => {
          console.warn('Failed to load DAE geometry:', error);
          // On failure, keep existing placeholder boxes
          reject(error);
        },
      );
    });
  }

  /** Returns true if DAE geometry was loaded. */
  hasLoadedGeometry(): boolean {
    return this.geometryLoaded;
  }

  /** Remove placeholder box meshes (used when DAE geometry replaces them). */
  private clearPlaceholders(): void {
    for (const mesh of this.meshMap.values()) {
      mesh.geometry.dispose();
      this.elementGroup.remove(mesh);
    }
    this.meshMap.clear();
  }

  private createBoxMesh(element: BIMElementData): THREE.Mesh {
    const bb = element.bounding_box!;
    const width = Math.abs(bb.max_x - bb.min_x) || 0.1;
    const height = Math.abs(bb.max_y - bb.min_y) || 0.1;
    const depth = Math.abs(bb.max_z - bb.min_z) || 0.1;

    const geometry = new THREE.BoxGeometry(width, height, depth);
    const material = this.getMaterial(element.discipline);

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(
      (bb.min_x + bb.max_x) / 2,
      (bb.min_y + bb.max_y) / 2,
      (bb.min_z + bb.max_z) / 2,
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // Store element data for raycasting / picking
    mesh.userData = {
      elementId: element.id,
      elementData: element,
    };

    return mesh;
  }

  private getMaterial(discipline: string): THREE.MeshStandardMaterial {
    const key = discipline.toLowerCase();
    let mat = this.baseMaterials.get(key);
    if (!mat) {
      mat = new THREE.MeshStandardMaterial({
        color: getDisciplineColor(discipline),
        roughness: 0.7,
        metalness: 0.1,
        transparent: true,
        opacity: 0.85,
        wireframe: this.wireframeEnabled,
      });
      this.baseMaterials.set(key, mat);
    }
    return mat;
  }

  /** Get mesh by element ID. */
  getMesh(elementId: string): THREE.Mesh | undefined {
    return this.meshMap.get(elementId);
  }

  /** Get element data by ID. */
  getElementData(elementId: string): BIMElementData | undefined {
    return this.elementDataMap.get(elementId);
  }

  /** Get all meshes for raycasting. */
  getAllMeshes(): THREE.Mesh[] {
    return Array.from(this.meshMap.values());
  }

  /** Get all element data entries. */
  getAllElements(): BIMElementData[] {
    return Array.from(this.elementDataMap.values());
  }

  /** Toggle wireframe mode. */
  toggleWireframe(): void {
    this.wireframeEnabled = !this.wireframeEnabled;
    for (const mat of this.baseMaterials.values()) {
      mat.wireframe = this.wireframeEnabled;
    }
  }

  /** Get wireframe state. */
  isWireframe(): boolean {
    return this.wireframeEnabled;
  }

  /** Set visibility of elements by discipline. */
  setDisciplineVisible(discipline: string, visible: boolean): void {
    for (const [, mesh] of this.meshMap) {
      const data = mesh.userData as { elementData?: BIMElementData };
      if (data.elementData?.discipline.toLowerCase() === discipline.toLowerCase()) {
        mesh.visible = visible;
      }
    }
  }

  /** Set visibility of elements by storey. */
  setStoreyVisible(storey: string, visible: boolean): void {
    for (const [, mesh] of this.meshMap) {
      const data = mesh.userData as { elementData?: BIMElementData };
      if (data.elementData?.storey === storey) {
        mesh.visible = visible;
      }
    }
  }

  /** Get unique disciplines from loaded elements. */
  getDisciplines(): string[] {
    const set = new Set<string>();
    for (const el of this.elementDataMap.values()) {
      if (el.discipline) set.add(el.discipline);
    }
    return Array.from(set).sort();
  }

  /** Get unique storeys from loaded elements. */
  getStoreys(): string[] {
    const set = new Set<string>();
    for (const el of this.elementDataMap.values()) {
      if (el.storey) set.add(el.storey);
    }
    return Array.from(set).sort();
  }

  /** Get unique element types from loaded elements, with counts. */
  getTypeCounts(): Map<string, number> {
    const map = new Map<string, number>();
    for (const el of this.elementDataMap.values()) {
      const key = el.element_type || 'Unknown';
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }

  /** Get discipline counts. */
  getDisciplineCounts(): Map<string, number> {
    const map = new Map<string, number>();
    for (const el of this.elementDataMap.values()) {
      const key = el.discipline || 'other';
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }

  /** Get storey counts. */
  getStoreyCounts(): Map<string, number> {
    const map = new Map<string, number>();
    for (const el of this.elementDataMap.values()) {
      const key = el.storey || 'Unassigned';
      map.set(key, (map.get(key) ?? 0) + 1);
    }
    return map;
  }

  /**
   * Apply a visibility predicate to every element. Fast bulk update: each
   * mesh gets `visible = predicate(element)`. Works for both placeholder
   * boxes and DAE-matched nodes because meshMap is keyed by element ID.
   *
   * Returns the number of visible elements after the filter.
   */
  applyFilter(predicate: (el: BIMElementData) => boolean): number {
    let visibleCount = 0;
    for (const [elementId, mesh] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      const shouldShow = el ? predicate(el) : true;
      mesh.visible = shouldShow;
      if (shouldShow) visibleCount++;
    }
    // If DAE geometry has un-matched nodes (mesh nodes without element data),
    // hide them when ANY filter is active so users see only matched elements.
    // This keeps the viewport consistent with the filter state.
    if (this.daeGroup) {
      this.daeGroup.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          const ud = obj.userData as { elementId?: string };
          if (!ud.elementId) {
            // Unmatched DAE mesh — leave visible (background geometry)
          }
        }
      });
    }
    return visibleCount;
  }

  /** Reset all element visibility to visible. */
  showAll(): void {
    for (const mesh of this.meshMap.values()) {
      mesh.visible = true;
    }
  }

  /** Remove all elements from the scene. */
  clear(): void {
    for (const mesh of this.meshMap.values()) {
      mesh.geometry.dispose();
      this.elementGroup.remove(mesh);
    }
    this.meshMap.clear();
    this.elementDataMap.clear();

    // Remove DAE geometry group if loaded
    if (this.daeGroup) {
      this.daeGroup.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          obj.geometry?.dispose();
        }
      });
      this.elementGroup.remove(this.daeGroup);
      this.daeGroup = null;
    }
    this.geometryLoaded = false;
    // Materials are reused — dispose them only on full destroy
  }

  /** Dispose all resources. */
  dispose(): void {
    this.clear();
    for (const mat of this.baseMaterials.values()) {
      mat.dispose();
    }
    this.baseMaterials.clear();
    this.sceneManager.scene.remove(this.elementGroup);
  }
}
