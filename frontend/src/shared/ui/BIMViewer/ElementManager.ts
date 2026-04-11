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

/** Brief of a BOQ position linked to this element, embedded in the element
 *  response by the backend. See `BOQElementLinkBrief` in `features/bim/api.ts`. */
export interface BIMBOQLinkBrief {
  id: string;
  boq_position_id: string;
  boq_position_ordinal: string | null;
  boq_position_description: string | null;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
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
  /** Links to BOQ positions — populated by the backend with every element
   *  fetch so the viewer can render link state without a second round-trip. */
  boq_links?: BIMBOQLinkBrief[];
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
  /** Meshes that have been linked to an element by stable_id / bbox. */
  private meshMap = new Map<string, THREE.Mesh>();
  /** Every mesh that lives under `daeGroup`, matched or not. Needed so the
   *  filter / color-by / isolate features still work for RVT/IFC exports
   *  whose mesh nodes don't expose element stable_ids. */
  private allDaeMeshes: THREE.Mesh[] = [];
  private elementDataMap = new Map<string, BIMElementData>();
  private baseMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private wireframeEnabled = false;
  private geometryLoaded = false;
  /**
   * Fraction of loaded elements that the viewer was able to match to DAE
   * mesh nodes by stable_id. < 0.02 means we effectively have no mesh-level
   * mapping — the parent UI uses this to show a hint explaining why
   * per-element filters don't affect the viewport.
   */
  private meshMatchRatio = 0;

  constructor(sceneManager: SceneManager) {
    this.sceneManager = sceneManager;
    this.elementGroup = new THREE.Group();
    this.elementGroup.name = 'bim_elements';
    this.sceneManager.scene.add(this.elementGroup);
  }

  /** Load elements and (optionally) create placeholder meshes.
   *
   * @param skipPlaceholders  When true, no box placeholders are
   *   created from `el.bounding_box`. Use this when a real DAE/COLLADA
   *   geometry URL is about to load — the placeholders would briefly
   *   render at the BIM bounding-box coordinates (which can be in a
   *   different scale than the COLLADA scene) and produce a
   *   wrong-distance camera fit on the first frame.
   */
  loadElements(
    elements: BIMElementData[],
    options: { skipPlaceholders?: boolean } = {},
  ): void {
    this.clear();

    const skipPlaceholders = options.skipPlaceholders === true;

    for (const el of elements) {
      this.elementDataMap.set(el.id, el);

      // Only create box placeholders when DAE geometry is not loaded
      // AND the caller didn't explicitly opt out.
      if (!skipPlaceholders && !this.geometryLoaded && el.bounding_box) {
        const mesh = this.createBoxMesh(el);
        this.meshMap.set(el.id, mesh);
        this.elementGroup.add(mesh);
      }
    }

    // Zoom to fit only when we actually have visible content. Without
    // placeholders the scene is empty until the DAE loader finishes
    // — BIMViewer schedules its own zoomToFit chain at that point.
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

          // Build two lookups: by stable_id (mesh_ref) and by element name.
          // Different converters emit different node-name schemes:
          //   · IFC       → nodes named after IfcGlobalId (matches stable_id)
          //   · DDC RVT   → nodes named after numeric Revit IDs (no match)
          //   · GLB / FBX → nodes named after mesh/asset names
          const stableIdToElement = new Map<string, BIMElementData>();
          const nameToElement = new Map<string, BIMElementData>();
          for (const el of this.elementDataMap.values()) {
            if (el.mesh_ref) stableIdToElement.set(el.mesh_ref, el);
            // Sometimes converters use the raw stable_id as the node name
            stableIdToElement.set(el.id, el);
            if (el.name) nameToElement.set(el.name, el);
          }

          let matchedCount = 0;
          let strippedLights = 0;
          this.allDaeMeshes = [];

          // Strip every Light/Camera that COLLADA dragged into the scene.
          // DDC RvtExporter exports ~40 spot lights inside the DAE which
          // ColladaLoader happily adds to the THREE scene — combined with
          // our 4 application lights this turns into a 50-light shadow
          // catastrophe (1 fps on a 5 000-mesh model).
          const lightsToRemove: THREE.Object3D[] = [];
          scene.traverse((obj) => {
            if (obj instanceof THREE.Light || obj instanceof THREE.Camera) {
              lightsToRemove.push(obj);
            }
          });
          for (const obj of lightsToRemove) {
            if (obj.parent) obj.parent.remove(obj);
            strippedLights++;
          }

          // Traverse the loaded DAE scene and match mesh nodes.
          //
          // IMPORTANT: do NOT replace `child.material`. The COLLADA file
          // ships with real per-element materials (colours, opacities,
          // textures) authored in the source CAD tool. Replacing them
          // with our default discipline `MeshStandardMaterial` produces
          // the white-everything regression users reported. We only
          // touch the material when an explicit colour-by mode is on
          // (`colorBy` / `isolate` mutate clones, not the originals),
          // and we cache the COLLADA original on the mesh as
          // `userData.originalMaterial` so `resetColors()` can restore
          // it after a colour-by toggle.
          scene.traverse((child) => {
            if (child instanceof THREE.Mesh) {
              const nodeName = child.name || '';
              const parentName = child.parent?.name || '';
              const element =
                stableIdToElement.get(nodeName) ||
                stableIdToElement.get(parentName) ||
                nameToElement.get(nodeName) ||
                nameToElement.get(parentName);

              // Shadows DISABLED on DAE meshes — drawing 5 000 shadow
              // casters per frame is the difference between 60 fps and
              // 1 fps on real Revit exports. Shadows on the BIM viewer
              // were never load-bearing visually and the perf cost is
              // catastrophic.
              child.castShadow = false;
              child.receiveShadow = false;

              // Static geometry — lock the world matrix so Three.js doesn't
              // recompute 5 000+ matrices every frame. The COLLADA loader
              // has already set the local transform; we just need to push it
              // to world once and then freeze.
              child.matrixAutoUpdate = false;
              child.updateMatrix();

              // Cache the original material so colour-by / reset can
              // toggle without losing the COLLADA visual.
              const originalMaterial = child.material;

              if (element) {
                child.userData = {
                  elementId: element.id,
                  elementData: element,
                  originalMaterial,
                };
                this.meshMap.set(element.id, child);
                matchedCount++;
              } else {
                child.userData = { elementId: null, originalMaterial };
              }

              // Only apply our default material when the COLLADA mesh
              // came in with no material at all (rare — usually a
              // converter bug).
              if (!child.material) {
                child.material = this.getMaterial(element?.discipline || 'other');
              }

              // Track every mesh for bulk operations (filter / color-by / isolate)
              this.allDaeMeshes.push(child);
            }
          });

          if (strippedLights > 0) {
            // eslint-disable-next-line no-console
            console.info(`[BIM] stripped ${strippedLights} lights/cameras from COLLADA scene`);
          }

          // POSITIONAL FALLBACK: when the converter (looking at you, DDC
          // RvtExporter) drops node ids and we get 0% explicit matches,
          // pair DAE meshes with element data by index. The order is not
          // guaranteed correct, but it gives every mesh an `elementId`
          // and lets the filter / colour-by / isolate paths actually do
          // their job. Without this, every filter chip is a no-op for
          // models exported by DDC.
          if (matchedCount === 0 && this.allDaeMeshes.length > 0 && this.elementDataMap.size > 0) {
            const elementsArr = Array.from(this.elementDataMap.values());
            const pairs = Math.min(this.allDaeMeshes.length, elementsArr.length);
            for (let i = 0; i < pairs; i++) {
              const mesh = this.allDaeMeshes[i]!;
              const el = elementsArr[i]!;
              mesh.userData = {
                ...(mesh.userData as object),
                elementId: el.id,
                elementData: el,
                positionalFallback: true,
              };
              this.meshMap.set(el.id, mesh);
            }
            matchedCount = pairs;
            // eslint-disable-next-line no-console
            console.info(
              `[BIM] positional fallback: paired ${pairs} DAE meshes with element data ` +
              `(node names were generic, real mesh_ref matching unavailable)`,
            );
          }

          const totalElements = this.elementDataMap.size;
          this.meshMatchRatio = totalElements > 0 ? matchedCount / totalElements : 0;

          this.daeGroup.add(scene);
          this.elementGroup.add(this.daeGroup);
          this.geometryLoaded = true;

          // Fit camera to the newly added geometry
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

  /**
   * Ratio of elements whose DAE mesh was successfully identified by
   * stable_id/name. The parent UI surfaces a hint when this is very low
   * (i.e. filter chips can't hide individual objects in the viewport).
   */
  getMeshMatchRatio(): number {
    return this.meshMatchRatio;
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

  /** Get all meshes for raycasting — includes both matched element meshes
   *  and un-matched DAE background meshes so clicking the model always
   *  hits something. */
  getAllMeshes(): THREE.Mesh[] {
    if (this.allDaeMeshes.length > 0) return this.allDaeMeshes;
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
   * matched mesh gets `visible = predicate(element)`.
   *
   * Behaviour when DAE geometry is loaded but mesh-to-element matching is
   * sparse (e.g. RVT exports where nodes are numeric IDs unrelated to
   * element stable_ids): we still update matched meshes, but we also
   * KEEP the un-matched DAE group fully visible so users at least see the
   * rest of the model as a "context" background. If a mesh-level filter
   * matters, the parent UI surfaces a hint via getMeshMatchRatio().
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
    // Un-matched DAE meshes act as background context. Ensure they are
    // visible so the scene isn't blanked out by an active filter on a model
    // without mesh mapping.
    for (const mesh of this.allDaeMeshes) {
      const ud = mesh.userData as { elementId?: string | null };
      if (!ud.elementId) mesh.visible = true;
    }
    if (this.daeGroup) this.daeGroup.visible = true;
    return visibleCount;
  }

  /** Reset all element visibility to visible. */
  showAll(): void {
    for (const mesh of this.meshMap.values()) {
      mesh.visible = true;
    }
    // DAE background meshes (unmatched) should also be restored
    for (const mesh of this.allDaeMeshes) {
      mesh.visible = true;
    }
    if (this.daeGroup) this.daeGroup.visible = true;
  }

  /**
   * Highlight elements without hiding the rest of the model.  Used to show
   * which BIM elements are linked to the currently-selected BOQ position:
   * the caller passes the `cad_element_ids` list and the viewer colours
   * every matching mesh orange while leaving the rest at normal colour.
   *
   * Passing an empty array clears the highlight and restores original colours.
   */
  highlight(elementIds: string[]): void {
    const highlightColor = new THREE.Color(0xff9500); // orange
    const keep = new Set(elementIds);
    for (const [id, mesh] of this.meshMap) {
      const ud = mesh.userData as {
        customMaterial?: boolean;
        originalMaterial?: THREE.Material | THREE.Material[];
      };
      if (keep.has(id)) {
        // Clone material so we can recolour independently of the base.
        if (!ud.customMaterial) {
          const base = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
          if (base && 'clone' in base) {
            mesh.material = (base as THREE.Material & { clone(): THREE.Material }).clone();
            ud.customMaterial = true;
          }
        }
        const mat = mesh.material as THREE.MeshStandardMaterial | THREE.MeshPhongMaterial;
        if (mat && 'color' in mat && mat.color) {
          mat.color.copy(highlightColor);
        }
      } else if (ud.customMaterial) {
        // Restore original material on meshes that were previously highlighted.
        const old = mesh.material;
        if (old && 'dispose' in old) {
          (old as THREE.Material & { dispose(): void }).dispose();
        }
        if (ud.originalMaterial) {
          mesh.material = ud.originalMaterial;
        }
        ud.customMaterial = false;
      }
    }
  }

  /** Isolate given element IDs — hide everything else. */
  isolate(elementIds: string[]): void {
    const keep = new Set(elementIds);
    for (const [id, mesh] of this.meshMap) {
      mesh.visible = keep.has(id);
    }
    // When isolating specific elements, hide unmatched DAE background so the
    // isolated part actually stands out. If no meshes are matched at all we
    // keep the DAE group visible — users still need to see the model.
    if (this.meshMap.size > 0) {
      for (const mesh of this.allDaeMeshes) {
        const ud = mesh.userData as { elementId?: string | null };
        if (!ud.elementId) mesh.visible = false;
      }
    }
  }

  /**
   * Re-color every mesh based on a key-extractor function. A distinct color
   * is assigned to each unique key via a simple hash-to-hue mapping.
   * Used to implement "color by storey" and "color by type" modes.
   */
  colorBy(keyFn: (el: BIMElementData) => string): void {
    // Collect unique keys for stable color assignment
    const keys = new Set<string>();
    for (const el of this.elementDataMap.values()) {
      keys.add(keyFn(el));
    }
    const keyList = Array.from(keys).sort();
    const colorMap = new Map<string, THREE.Color>();
    for (let i = 0; i < keyList.length; i++) {
      const hue = (i * 137.5) % 360; // golden angle for distinct hues
      const color = new THREE.Color().setHSL(hue / 360, 0.55, 0.55);
      colorMap.set(keyList[i]!, color);
    }

    // Apply per-mesh material clone (so we can color independently)
    for (const [elementId, mesh] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      if (!el) continue;
      const key = keyFn(el);
      const color = colorMap.get(key);
      if (!color) continue;

      // Clone material on first recolor so we don't mutate the shared one
      const ud = mesh.userData as { customMaterial?: boolean };
      if (!ud.customMaterial) {
        const base = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        if (base instanceof THREE.MeshStandardMaterial) {
          mesh.material = base.clone();
          ud.customMaterial = true;
        }
      }
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mat && mat.color) {
        mat.color.copy(color);
      }
    }
  }

  /** Reset mesh colors back to their discipline-based material. */
  resetColors(): void {
    for (const [elementId, mesh] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      if (!el) continue;
      const ud = mesh.userData as {
        customMaterial?: boolean;
        originalMaterial?: THREE.Material | THREE.Material[];
      };
      if (ud.customMaterial) {
        // Dispose the cloned material we created in colorBy()...
        const old = mesh.material;
        if (old instanceof THREE.MeshStandardMaterial) {
          old.dispose();
        }
        // ...and restore the COLLADA original if we cached one
        // (loadDAEGeometry stashes it on userData), otherwise fall
        // back to our flat discipline material so the mesh stays visible.
        if (ud.originalMaterial) {
          mesh.material = ud.originalMaterial;
        } else {
          mesh.material = this.getMaterial(el.discipline || 'other');
        }
        ud.customMaterial = false;
      }
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
    this.allDaeMeshes = [];
    this.meshMatchRatio = 0;
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
