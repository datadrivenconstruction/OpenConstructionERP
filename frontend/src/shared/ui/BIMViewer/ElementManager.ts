/**
 * ElementManager — loads and manages BIM element meshes in the Three.js scene.
 *
 * Loads elements from the BIM Hub API. For each element:
 * - If mesh_ref is available: loads GLB via GLTFLoader (future)
 * - Otherwise: creates placeholder box geometry from bounding_box
 *
 * Elements are colored by discipline:
 *   architectural = light blue, structural = orange, mechanical = green,
 *   electrical = yellow, plumbing = purple
 */

import * as THREE from 'three';
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
  private meshMap = new Map<string, THREE.Mesh>();
  private elementDataMap = new Map<string, BIMElementData>();
  private baseMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private wireframeEnabled = false;

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

      if (el.bounding_box) {
        const mesh = this.createBoxMesh(el);
        this.meshMap.set(el.id, mesh);
        this.elementGroup.add(mesh);
      }
    }

    // Zoom to fit all loaded elements
    if (this.meshMap.size > 0) {
      this.sceneManager.zoomToFit();
    }
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

  /** Remove all elements from the scene. */
  clear(): void {
    for (const mesh of this.meshMap.values()) {
      mesh.geometry.dispose();
      this.elementGroup.remove(mesh);
    }
    this.meshMap.clear();
    this.elementDataMap.clear();
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
