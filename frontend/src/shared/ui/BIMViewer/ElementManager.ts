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
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js';
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
  boq_position_quantity: number | null;
  boq_position_unit: string | null;
  boq_position_unit_rate: number | null;
  boq_position_total: number | null;
  link_type: 'manual' | 'auto' | 'rule_based';
  confidence: string | null;
}

/** Brief of a Document linked to this element. */
export interface BIMDocumentLinkBrief {
  id: string;
  document_id: string;
  document_name: string | null;
  document_category: string | null;
  link_type: 'manual' | 'auto';
  confidence: string | null;
}

/** Brief of a Task linked to this element. */
export interface BIMTaskBrief {
  id: string;
  project_id: string;
  title: string;
  status: string;
  task_type: string | null;
  due_date: string | null;
}

/** Brief of a Schedule Activity linked to this element. */
export interface BIMActivityBrief {
  id: string;
  name: string;
  start_date: string | null;
  end_date: string | null;
  status: string | null;
  percent_complete: number | null;
}

/** Brief of a Requirement (EAC triplet) pinned to this element.
 *
 *  The link is stored under `Requirement.metadata_["bim_element_ids"]`
 *  on the backend; the BIM viewer surfaces it via the eager-load path
 *  in `BIMHubService.list_elements_with_links` (Step 6.5).
 */
export interface BIMRequirementBrief {
  id: string;
  requirement_set_id: string;
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  category: string;
  priority: 'must' | 'should' | 'may' | string;
  status: 'open' | 'verified' | 'linked' | 'conflict' | string;
}

/** Per-element validation summary embedded in the element response after
 *  the user runs POST /validation/check-bim-model. */
export interface BIMValidationSummary {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
}

export interface BIMElementData {
  id: string;
  /** Revit UniqueId / IFC GlobalId — stable across re-uploads. */
  stable_id?: string;
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
  /** Documents (drawings, photos, RFIs, specs) linked to this element.
   *  Same eager-load pattern as boq_links. */
  linked_documents?: BIMDocumentLinkBrief[];
  /** Tasks / defects / issues spatially pinned to this element. */
  linked_tasks?: BIMTaskBrief[];
  /** Schedule activities (4D) that affect this element. */
  linked_activities?: BIMActivityBrief[];
  /** Requirements (EAC triplets) pinned to this element — the bridge
   *  between client intent / spec and the executed model.  Surfaced as
   *  the new "Linked requirements" section in the viewer details panel. */
  linked_requirements?: BIMRequirementBrief[];
  /** Per-element validation summary from the most recent
   *  /validation/check-bim-model run. */
  validation_results?: BIMValidationSummary[];
  /** Worst-severity rollup: 'error' > 'warning' > 'pass' > 'unchecked'. */
  validation_status?: 'pass' | 'warning' | 'error' | 'unchecked';
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
  /** Storey/level count extracted during processing */
  storey_count?: number;
  /** Project this model belongs to */
  project_id?: string;
  /** Last updated ISO date */
  updated_at?: string;
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

/* ── Category Colors (for placeholder boxes) ─────────────────────────── */

/** Map element_type (Revit Category / IFC Entity) to a distinct color so
 *  placeholder boxes are immediately distinguishable by building trade.
 *  Exported for reuse in the filter panel (colored dots on chips). */
export const CATEGORY_COLORS: Record<string, number> = {
  'Walls': 0x4488cc,
  'Doors': 0x44aa44,
  'Windows': 0x66ccdd,
  'Structural Columns': 0x888888,
  'Structural Framing': 0x999999,
  'Floors': 0xccaa66,
  'Roofs': 0xcc6644,
  'Ceilings': 0xddccaa,
  'Stairs': 0xaa6644,
  'Furniture': 0x886644,
  'Curtain Wall Mullions': 0x6688aa,
  'Curtain Wall Panels': 0x88aacc,
  'Planting': 0x55bb55,
  'Rooms': 0xeeeecc,
  'Columns': 0x888888,
  'Mechanical Equipment': 0x66bb6a,
  'Electrical Equipment': 0xfdd835,
  'Plumbing Fixtures': 0xab47bc,
  'Railings': 0x9e8e7e,
  'Generic Models': 0xbbbbbb,
  'Pipes': 0xab47bc,
  'Ducts': 0x66bb6a,
  'Cable Trays': 0xfdd835,
  // IFC entities
  'IfcWall': 0x4488cc,
  'IfcWallStandardCase': 0x4488cc,
  'IfcDoor': 0x44aa44,
  'IfcWindow': 0x66ccdd,
  'IfcColumn': 0x888888,
  'IfcBeam': 0x999999,
  'IfcSlab': 0xccaa66,
  'IfcRoof': 0xcc6644,
  'IfcCovering': 0xddccaa,
  'IfcStair': 0xaa6644,
  'IfcFurnishingElement': 0x886644,
  'IfcCurtainWall': 0x88aacc,
  'IfcSpace': 0xeeeecc,
  'IfcRailing': 0x9e8e7e,
  'IfcBuildingElementProxy': 0xbbbbbb,
  // Civil infrastructure (IFC4x3)
  'Alignment': 0xe91e63,
  'Horizontal Alignment': 0xe91e63,
  'Vertical Alignment': 0xc2185b,
  'Alignment Segment': 0xf06292,
  'Bridge': 0x5d4037,
  'Bridge Part': 0x6d4c41,
  'Road': 0x455a64,
  'Road Part': 0x546e7a,
  'Railway': 0x37474f,
  'Railway Part': 0x455a64,
  'Pavement': 0x78909c,
  'Kerb': 0x607d8b,
  'Course': 0x90a4ae,
  'Earthworks Fill': 0x795548,
  'Earthworks Cut': 0xa1887f,
  'Earthworks Element': 0x8d6e63,
  'Reinforced Soil': 0x6d4c41,
  'Civil Element': 0x8d6e63,
  'Facility': 0x546e7a,
  'Surface Feature': 0x80cbc4,
  'Geotechnic Element': 0x4e342e,
  'Deep Foundation': 0x3e2723,
  'Bearing': 0x757575,
  'Tendon': 0x9e9e9e,
};

export function getCategoryColor(elementType: string): number {
  return CATEGORY_COLORS[elementType] ?? 0xdd8833; // default warm orange
}

/* ── Element Manager ───────────────────────────────────────────────────── */

export class ElementManager {
  private sceneManager: SceneManager;
  elementGroup: THREE.Group;
  private daeGroup: THREE.Group | null = null;
  /** Meshes that have been linked to an element by stable_id / bbox. */
  private meshMap = new Map<string, THREE.Mesh>();
  /** Every mesh that lives under `daeGroup`, matched or not. Needed so the
   *  filter / color-by / isolate features still work for RVT/IFC exports
   *  whose mesh nodes don't expose element stable_ids. */
  private allDaeMeshes: THREE.Mesh[] = [];
  /** BatchedMesh objects created by `batchMeshesByMaterial` for big-model
   *  perf.  Sits beside `daeGroup` directly under the scene root.  Tracked
   *  here so `clear()` can dispose their internal buffers. */
  private batchedMeshes: THREE.BatchedMesh[] = [];
  private elementDataMap = new Map<string, BIMElementData>();
  private baseMaterials = new Map<string, THREE.MeshStandardMaterial>();
  private wireframeEnabled = false;
  private geometryLoaded = false;
  /**
   * Every material we allocate via `clone()` inside `colorBy*` paths is
   * tracked here so `resetColors()` / `dispose()` can free the GPU
   * resources.  Without this set, rapid mode switching (validation →
   * default → boq_coverage → …) leaks one WebGL program per element per
   * switch — visible as VRAM growth in long sessions.
   */
  private createdMaterials = new Set<THREE.Material>();
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
    // Placeholder boxes have Z_UP→Y_UP conversion baked into
    // createBoxMesh() (Y↔Z swap), so no group rotation needed.
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

      // Create box placeholders when the caller opts in (showBoundingBoxes).
      // Normally skipped when real DAE/GLB geometry is loaded.
      if (!skipPlaceholders && el.bounding_box) {
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

  /** Return the number of elements currently loaded. */
  getElementCount(): number {
    return this.elementDataMap.size;
  }

  /**
   * Update element data in-place without recreating meshes or reloading geometry.
   * Used when element properties change (link updates, validation) but the
   * element set itself hasn't changed.
   */
  updateElementData(elements: BIMElementData[]): void {
    for (const el of elements) {
      this.elementDataMap.set(el.id, el);
      // Also update userData on matched meshes so filters see fresh data
      const mesh = this.meshMap.get(el.id);
      if (mesh) {
        const ud = mesh.userData as Record<string, unknown>;
        ud.elementData = el;
      }
    }
  }

  /**
   * Auto-detect geometry format (GLB vs DAE) and load accordingly.
   *
   * The backend now preferentially serves GLB (8.8x faster than DAE).
   * The Content-Type header determines the format:
   *   - ``model/gltf-binary`` -> GLTFLoader
   *   - ``model/vnd.collada+xml`` -> ColladaLoader (legacy fallback)
   *
   * Falls back to ColladaLoader if the Content-Type is ambiguous.
   */
  async loadGeometry(
    geometryUrl: string,
    onProgress?: (fraction: number) => void,
  ): Promise<void> {
    // Probe the Content-Type to decide which loader to use.
    // We make a HEAD request first -- cheap, avoids downloading the
    // full blob twice if we guess wrong.
    // Auto-detect format via Content-Type header. GLB preferred (2x smaller,
    // faster parsing). Node names are patched into the GLB by the backend
    // so mesh-to-element matching works with both formats.
    try {
      const resp = await fetch(geometryUrl, { method: 'HEAD' });
      if (resp.ok) {
        const ct = resp.headers.get('content-type') || '';
        if (ct.includes('gltf-binary') || ct.includes('gltf+json')) {
          return this.loadGLBGeometry(geometryUrl, onProgress);
        }
        if (ct.includes('collada') || ct.includes('xml') || ct.includes('dae')) {
          return this.loadDAEGeometry(geometryUrl, onProgress);
        }
      }
    } catch {
      // HEAD failed — fall through to GLB-first path
    }
    // Default: try GLB first (smaller + faster), DAE fallback in error handler
    return this.loadGLBGeometry(geometryUrl, onProgress);
  }

  /**
   * Load GLB/glTF geometry and bind meshes to BIM elements.
   *
   * GLTFLoader output (``gltf.scene``) is a THREE.Group just like
   * ColladaLoader's -- the downstream mesh processing (traverse,
   * match, batch) is identical.
   */
  private loadGLBGeometry(
    geometryUrl: string,
    onProgress?: (fraction: number) => void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const loader = new GLTFLoader();
      loader.load(
        geometryUrl,
        (gltf) => {
          if (!gltf || !gltf.scene) {
            reject(new Error('GLTFLoader returned empty result'));
            return;
          }
          this.processLoadedScene(gltf.scene, onProgress, true);
          resolve();
        },
        (xhr: ProgressEvent) => {
          if (!onProgress) return;
          if (xhr.lengthComputable && xhr.total > 0) {
            const fraction = Math.min(0.95, xhr.loaded / xhr.total);
            onProgress(fraction);
          } else {
            onProgress(0.5);
          }
        },
        (error) => {
          // eslint-disable-next-line no-console
          console.warn('GLB load failed, falling back to DAE:', error);
          // Fallback: try the DAE loader in case the file is actually COLLADA
          this.loadDAEGeometry(geometryUrl, onProgress).then(resolve, reject);
        },
      );
    });
  }

  /**
   * Load the DAE/COLLADA geometry blob and bind every mesh to its
   * BIM element by stable_id / mesh_ref / element name.
   *
   * Kept as a public method for backward compatibility with models
   * uploaded before the GLB optimization was added.
   */
  loadDAEGeometry(
    geometryUrl: string,
    onProgress?: (fraction: number) => void,
  ): Promise<void> {
    return new Promise((resolve, reject) => {
      const loader = new ColladaLoader();
      loader.load(
        geometryUrl,
        (collada) => {
          if (!collada || !collada.scene) {
            reject(new Error('ColladaLoader returned empty result'));
            return;
          }
          this.processLoadedScene(collada.scene, onProgress);
          resolve();
        },
        (event: ProgressEvent) => {
          if (!onProgress) return;
          if (event.lengthComputable && event.total > 0) {
            const fraction = Math.min(0.95, event.loaded / event.total);
            onProgress(fraction);
          } else {
            onProgress(0.5);
          }
        },
        (error) => {
          console.warn('Failed to load DAE geometry:', error);
          reject(error);
        },
      );
    });
  }

  /**
   * Shared scene-processing logic for both GLTFLoader and ColladaLoader.
   *
   * Strips lights/cameras, matches mesh nodes to BIM elements by
   * stable_id / mesh_ref / name, disables shadows, freezes matrices,
   * and triggers BatchedMesh collapsing for large models.
   */
  private processLoadedScene(
    scene: THREE.Group | THREE.Object3D,
    onProgress?: (fraction: number) => void,
    _isGLB = false,
  ): void {
    // Remove any existing placeholder meshes for elements that have geometry
    this.clearPlaceholders();

    this.daeGroup = new THREE.Group();
    this.daeGroup.name = 'bim_dae_geometry';

    // DDC converters (RVT/IFC/DWG/DGN) ALWAYS output Z_UP geometry.
    // trimesh does NOT convert Z_UP→Y_UP when generating GLB.
    // Always apply -90° X rotation to bring the model upright in
    // Three.js Y_UP coordinate system.
    const box = new THREE.Box3().setFromObject(scene);
    const size = box.getSize(new THREE.Vector3());
    // eslint-disable-next-line no-console
    console.log(
      `[BIM orientation] bbox: X=${size.x.toFixed(1)} Y=${size.y.toFixed(1)} Z=${size.z.toFixed(1)} → rotating Z_UP→Y_UP`,
    );
    scene.rotation.x = -Math.PI / 2;
    scene.updateMatrixWorld(true);

    // Build lookups: by stable_id / mesh_ref / element name.
    // mesh_ref is the Revit ElementId string (e.g. "105545") that matches
    // the COLLADA <node id="105545"> — after the backend patches node names,
    // ColladaLoader exposes it as Object3D.name on the parent Group.
    const stableIdToElement = new Map<string, BIMElementData>();
    const nameToElement = new Map<string, BIMElementData>();
    for (const el of this.elementDataMap.values()) {
      if (el.mesh_ref) stableIdToElement.set(el.mesh_ref, el);
      stableIdToElement.set(el.id, el);
      if (el.name) nameToElement.set(el.name, el);
    }

    let matchedCount = 0;
    let strippedLights = 0;
    this.allDaeMeshes = [];

    // Strip every Light/Camera that the loader dragged into the scene.
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

    // Traverse the loaded scene and match mesh nodes.
    // IMPORTANT: do NOT replace `child.material` -- the geometry file
    // ships with real per-element materials. We only touch the material
    // when an explicit colour-by mode is on, and we cache the original
    // on `userData.originalMaterial` so `resetColors()` can restore it.
    //
    // Matching strategy (tried in order for each mesh):
    //   1. child.name          via stableIdToElement (mesh_ref / db id)
    //   2. parent.name         via stableIdToElement (DDC patched node name = ElementId)
    //   3. grandparent.name    via stableIdToElement (GLB loader may nest differently)
    //   4. child.name          via nameToElement (element display name)
    //   5. parent.name         via nameToElement
    //   6. Extract numeric ID from parent.name pattern "Type-N-suffix" (Light-1-235371-point)
    //      — this catches DDC light/node IDs embedded in composite names.
    let _debugLogCount = 0;
    scene.traverse((child) => {
      if (child instanceof THREE.Mesh) {
        const nodeName = child.name || '';
        const parentName = child.parent?.name || '';
        const grandparentName = child.parent?.parent?.name || '';

        // Debug: log first 5 mesh names for diagnostics
        if (_debugLogCount < 5) {
          // eslint-disable-next-line no-console
          console.log(
            `[BIM match debug] mesh.name="${nodeName}" parent="${parentName}" grandparent="${grandparentName}" ` +
            `inMap=${stableIdToElement.has(nodeName) || stableIdToElement.has(parentName)}`,
          );
          _debugLogCount++;
        }

        let element =
          stableIdToElement.get(nodeName) ||
          stableIdToElement.get(parentName) ||
          stableIdToElement.get(grandparentName) ||
          nameToElement.get(nodeName) ||
          nameToElement.get(parentName);

        // Fallback: try to extract a numeric ID from the parent name.
        // DDC COLLADA sometimes names nodes as "Type-N-ElementId-suffix"
        // (e.g. "Light-1-235371-point"). If the parent name contains a
        // numeric segment that matches a mesh_ref, use it.
        if (!element && parentName) {
          const segments = parentName.split('-');
          for (const seg of segments) {
            if (/^\d+$/.test(seg)) {
              const candidate = stableIdToElement.get(seg);
              if (candidate) {
                element = candidate;
                break;
              }
            }
          }
        }

        child.castShadow = false;
        child.receiveShadow = false;
        child.frustumCulled = true;
        child.matrixAutoUpdate = false;
        child.updateMatrix();
        // Pre-compute bounding sphere so Three.js frustum culling works
        // correctly even with matrixAutoUpdate = false.
        child.geometry.computeBoundingSphere();

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

        if (!child.material) {
          child.material = this.getMaterial(element?.discipline || 'other');
        }

        this.allDaeMeshes.push(child);
      }
    });

    if (strippedLights > 0) {
      // eslint-disable-next-line no-console
      console.info(`[BIM] stripped ${strippedLights} lights/cameras from loaded scene`);
    }

    // eslint-disable-next-line no-console
    console.info(
      `[BIM] mesh matching: ${matchedCount}/${this.allDaeMeshes.length} meshes matched ` +
      `to ${this.elementDataMap.size} elements ` +
      `(${this.elementDataMap.size > 0 ? Math.round((matchedCount / this.elementDataMap.size) * 100) : 0}% element coverage)`,
    );

    // FALLBACK: assign elementIds to unmatched meshes so every visible
    // mesh is selectable.  When explicit matching covers < 50% of meshes,
    // we pair remaining unmatched meshes with unmatched elements by index.
    const unmatchedMeshes = this.allDaeMeshes.filter(
      (m) => !(m.userData as { elementId?: string | null }).elementId,
    );
    const matchedElementIds = new Set(
      this.allDaeMeshes
        .map((m) => (m.userData as { elementId?: string | null }).elementId)
        .filter(Boolean),
    );
    const unmatchedElements = Array.from(this.elementDataMap.values()).filter(
      (el) => !matchedElementIds.has(el.id),
    );

    if (unmatchedMeshes.length > 0 && unmatchedElements.length > 0) {
      // Sort meshes by vertical position (Y in Three.js Y_UP = height)
      // so that meshes near the ground pair with ground-floor elements.
      const meshWithY = unmatchedMeshes.map((m) => {
        const pos = new THREE.Vector3();
        m.getWorldPosition(pos);
        return { mesh: m, y: pos.y };
      });
      meshWithY.sort((a, b) => a.y - b.y);

      // Sort elements: those WITH storey FIRST (grouped by storey name,
      // alphabetical approximates floor order for typical naming:
      // "00 - Ground", "01 - Entry Level", "02 - Floor"), then elements
      // WITHOUT storey LAST. This ensures storey-bearing elements get
      // the most spatially relevant meshes, while unassigned elements
      // consume whatever remains.
      const sortedElements = [...unmatchedElements].sort((a, b) => {
        const sa = a.storey || '';
        const sb = b.storey || '';
        // Elements with storey come before those without
        if (sa && !sb) return -1;
        if (!sa && sb) return 1;
        if (sa !== sb) return sa.localeCompare(sb);
        return (a.element_type || '').localeCompare(b.element_type || '');
      });

      const pairs = Math.min(meshWithY.length, sortedElements.length);
      for (let i = 0; i < pairs; i++) {
        const mesh = meshWithY[i]!.mesh;
        const el = sortedElements[i]!;
        mesh.userData = {
          ...(mesh.userData as object),
          elementId: el.id,
          elementData: el,
          positionalFallback: true,
        };
        this.meshMap.set(el.id, mesh);
      }
      matchedCount += pairs;
      // eslint-disable-next-line no-console
      console.info(
        `[BIM] positional fallback: paired ${pairs} meshes with element data ` +
        `(sorted by Y-position ↔ storey for better filter accuracy)`,
      );
    }

    // Assign temporary IDs to any remaining meshes that still have no
    // elementId — this ensures every visible mesh is selectable.
    let tempIdCounter = 0;
    for (const mesh of this.allDaeMeshes) {
      if (!(mesh.userData as { elementId?: string | null }).elementId) {
        const tempId = `_unmatched_${tempIdCounter++}`;
        mesh.userData = {
          ...(mesh.userData as object),
          elementId: tempId,
        };
        this.meshMap.set(tempId, mesh);
      }
    }
    if (tempIdCounter > 0) {
      matchedCount += tempIdCounter;
      // eslint-disable-next-line no-console
      console.info(`[BIM] assigned temporary IDs to ${tempIdCounter} unmatched meshes`);
    }

    const totalElements = this.elementDataMap.size;
    this.meshMatchRatio = totalElements > 0 ? matchedCount / totalElements : 0;

    this.daeGroup.add(scene);
    this.elementGroup.add(this.daeGroup);
    this.geometryLoaded = true;

    this.sceneManager.scene.updateMatrixWorld(true);

    // BatchedMesh: collapse same-material meshes into one draw call per
    // material.  Threshold raised to 10,000 so that selection highlighting
    // works for typical models (BatchedMesh doesn't support per-instance
    // material changes needed for click-to-highlight).  Only very large
    // models (10K+ meshes) trade selection UX for render performance.
    if (this.allDaeMeshes.length >= 10_000) {
      try {
        this.batchMeshesByMaterial();
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[BIM] BatchedMesh path failed, falling back to individual meshes', err);
      }
    }

    this.sceneManager.zoomToFit();
    this.sceneManager.requestRender();

    if (onProgress) onProgress(1);
  }

  /**
   * Big-model perf optimisation: collapse same-material meshes into one
   * `THREE.BatchedMesh` per material.  Replaces N draw calls with
   * (number of unique materials) draw calls — typically 5 000 → ~30
   * for a real Revit export.
   *
   * The original `THREE.Mesh` objects stay in `meshMap` and `allDaeMeshes`
   * (so raycasting and the existing per-mesh API keep working) but they
   * are REMOVED from the scene graph so the renderer doesn't draw them
   * twice.  Every batched mesh gets a `userData.batchHandle` pointing
   * back at its (BatchedMesh, instanceId) pair so visibility/colour
   * updates can be forwarded.
   *
   * Groups with fewer than 10 meshes are left as individual draw calls
   * — the BatchedMesh fixed-size buffer overhead isn't worth it.
   */
  private batchMeshesByMaterial(): void {
    interface Group {
      material: THREE.Material;
      meshes: THREE.Mesh[];
      totalVertices: number;
      totalIndices: number;
    }
    const groups = new Map<string, Group>();

    for (const mesh of this.allDaeMeshes) {
      const mat = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
      if (!mat) continue;
      const key = mat.uuid;
      const posCount = (mesh.geometry.attributes.position as THREE.BufferAttribute | undefined)?.count ?? 0;
      const idxCount = mesh.geometry.index?.count ?? posCount;
      let g = groups.get(key);
      if (!g) {
        g = { material: mat, meshes: [], totalVertices: 0, totalIndices: 0 };
        groups.set(key, g);
      }
      g.meshes.push(mesh);
      g.totalVertices += posCount;
      g.totalIndices += idxCount;
    }

    let batchedMeshes = 0;
    let batchedInstances = 0;
    let drawCallsBefore = this.allDaeMeshes.length;
    let drawCallsAfter = 0;

    for (const group of groups.values()) {
      if (group.meshes.length < 10) {
        // Tiny group — leave as individual meshes
        drawCallsAfter += group.meshes.length;
        continue;
      }

      // BatchedMesh constructor: (maxInstanceCount, maxVertexCount, maxIndexCount, material)
      // Add a small slack (10%) so we don't run out mid-batch.
      const maxInstances = Math.ceil(group.meshes.length * 1.1);
      const maxVertices = Math.ceil(group.totalVertices * 1.1);
      const maxIndices = Math.ceil(group.totalIndices * 1.1);

      let batched: THREE.BatchedMesh;
      try {
        batched = new THREE.BatchedMesh(
          maxInstances,
          maxVertices,
          maxIndices,
          group.material,
        );
      } catch (err) {
        // eslint-disable-next-line no-console
        console.warn('[BIM] BatchedMesh ctor failed for material group, falling back', err);
        drawCallsAfter += group.meshes.length;
        continue;
      }
      batched.frustumCulled = true;
      batched.castShadow = false;
      batched.receiveShadow = false;
      batched.name = `bim_batched_${group.material.uuid.slice(0, 8)}`;

      let added = 0;
      for (const mesh of group.meshes) {
        try {
          const geomId = batched.addGeometry(mesh.geometry);
          const instId = batched.addInstance(geomId);
          batched.setMatrixAt(instId, mesh.matrixWorld);
          (mesh.userData as { batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } }).batchHandle = {
            batched,
            instanceId: instId,
          };
          // Hide the original mesh from rendering — the BatchedMesh draws
          // it now. We KEEP it in the scene graph (don't reparent) so its
          // matrixWorld + bbox stay accurate for zoomToSelection / picking.
          mesh.visible = false;
          added++;
        } catch (err) {
          // Geometry didn't fit (e.g. because of mismatched attribute formats
          // between source meshes); leave this one as an individual mesh.
          // eslint-disable-next-line no-console
          console.warn('[BIM] addInstance failed, leaving mesh standalone', err);
        }
      }

      if (added > 0) {
        // Add the BatchedMesh to the SCENE ROOT, not to daeGroup, so the
        // per-instance world matrices we set via setMatrixAt aren't double-
        // transformed by the daeGroup's parent chain.  daeGroup keeps the
        // un-batched leftover meshes; the BatchedMesh sits beside it.
        this.sceneManager.scene.add(batched);
        this.batchedMeshes.push(batched);
        batchedMeshes++;
        batchedInstances += added;
        drawCallsAfter += 1; // one draw call per BatchedMesh
      } else {
        // Nothing added — drop the empty batched mesh and keep originals
        drawCallsAfter += group.meshes.length;
      }
    }

    // eslint-disable-next-line no-console
    console.info(
      `[BIM] BatchedMesh: ${batchedMeshes} batches holding ${batchedInstances} instances; ` +
        `draw calls ${drawCallsBefore} → ${drawCallsAfter} ` +
        `(${Math.round((1 - drawCallsAfter / Math.max(1, drawCallsBefore)) * 100)}% reduction)`,
    );
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
    // DDC converters (Revit/IFC) output Z_UP coordinates (Z = height).
    // Three.js uses Y_UP (Y = height).  Swap Y ↔ Z so the model stands
    // upright instead of being perpendicular to the ground plane.
    const width = Math.abs(bb.max_x - bb.min_x) || 0.1;
    const height = Math.abs(bb.max_z - bb.min_z) || 0.1; // Z → Y (height)
    const depth = Math.abs(bb.max_y - bb.min_y) || 0.1;  // Y → Z (depth)

    const geometry = new THREE.BoxGeometry(width, height, depth);
    // Color by element category (type) for immediate visual distinction,
    // falling back to discipline color if no category mapping exists.
    const catColor = getCategoryColor(element.element_type);
    const material = this.getOrCreateCategoryMaterial(element.element_type, catColor);

    const mesh = new THREE.Mesh(geometry, material);
    mesh.position.set(
      (bb.min_x + bb.max_x) / 2,
      (bb.min_z + bb.max_z) / 2,  // Z → Y (height)
      (bb.min_y + bb.max_y) / 2,  // Y → Z (depth)
    );
    mesh.castShadow = true;
    mesh.receiveShadow = true;

    // Add thin wireframe outline for depth / edge visibility
    const edgeGeo = new THREE.EdgesGeometry(geometry);
    const edgeMat = new THREE.LineBasicMaterial({
      color: 0x222222,
      transparent: true,
      opacity: 0.25,
    });
    const wireframe = new THREE.LineSegments(edgeGeo, edgeMat);
    mesh.add(wireframe);

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

  /** Get or create a material keyed by category name + color.
   *  Placeholder boxes use this so each Revit/IFC category gets a
   *  unique color without duplicating material allocations. */
  private getOrCreateCategoryMaterial(
    category: string,
    color: number,
  ): THREE.MeshStandardMaterial {
    const key = `cat_${category}`;
    let mat = this.baseMaterials.get(key);
    if (!mat) {
      mat = new THREE.MeshStandardMaterial({
        color,
        roughness: 0.6,
        metalness: 0.08,
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

  /** Toggle wireframe mode for ALL meshes — both box placeholders
   *  (baseMaterials) and DAE/COLLADA-loaded geometry. */
  toggleWireframe(): void {
    this.wireframeEnabled = !this.wireframeEnabled;
    for (const mat of this.baseMaterials.values()) {
      mat.wireframe = this.wireframeEnabled;
    }
    // Also toggle DAE-loaded meshes whose materials are NOT in baseMaterials
    for (const mesh of this.allDaeMeshes) {
      const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
      for (const mat of mats) {
        if (mat && 'wireframe' in mat) {
          (mat as THREE.MeshStandardMaterial).wireframe = this.wireframeEnabled;
        }
      }
    }
    this.sceneManager.requestRender();
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
    let noDataCount = 0;

    // Build a set of element IDs that pass the filter
    const visibleIds = new Set<string>();
    for (const [elementId] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      const elFromUserData = this.meshMap.get(elementId);
      const effectiveEl = el || (elFromUserData?.userData as { elementData?: BIMElementData })?.elementData;
      if (!effectiveEl) {
        noDataCount++;
        continue;
      }
      if (predicate(effectiveEl)) {
        visibleIds.add(elementId);
        visibleCount++;
      }
    }
    // eslint-disable-next-line no-console
    console.info(
      `[BIM filter] meshMap=${this.meshMap.size} visible=${visibleCount} hidden=${this.meshMap.size - visibleCount - noDataCount} noData=${noDataCount}`,
    );

    // Apply visibility to meshMap entries (placeholder boxes + matched DAE)
    for (const [elementId, mesh] of this.meshMap) {
      const shouldShow = visibleIds.has(elementId);
      const handle = (mesh.userData as { batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } }).batchHandle;
      if (handle) {
        handle.batched.setVisibleAt(handle.instanceId, shouldShow);
      } else {
        mesh.visible = shouldShow;
      }
    }

    // ALSO walk the entire DAE scene graph and hide/show meshes there.
    // This catches meshes that are in the scene graph but may not be
    // the same object reference as meshMap (Three.js ColladaLoader
    // can nest meshes inside intermediate Group nodes).
    if (this.daeGroup) {
      this.daeGroup.traverse((obj) => {
        if (obj instanceof THREE.Mesh) {
          const ud = obj.userData as { elementId?: string | null };
          if (ud.elementId) {
            obj.visible = visibleIds.has(ud.elementId);
          } else {
            // Unmatched mesh — hide when filter is active
            obj.visible = false;
          }
        }
      });
      this.daeGroup.visible = true;
    }

    this.sceneManager.requestRender();
    return visibleCount;
  }

  /** Hide specific elements by ID. Sets mesh.visible = false for each.
   *  Other elements remain unaffected. */
  hideElements(ids: Set<string>): void {
    for (const id of ids) {
      const mesh = this.meshMap.get(id);
      if (!mesh) continue;
      const handle = (mesh.userData as { batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } }).batchHandle;
      if (handle) {
        handle.batched.setVisibleAt(handle.instanceId, false);
      } else {
        mesh.visible = false;
      }
    }
    this.sceneManager.requestRender();
  }

  /** Reset all element visibility to visible. */
  showAll(): void {
    for (const mesh of this.meshMap.values()) {
      const handle = (mesh.userData as { batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } }).batchHandle;
      if (handle) {
        handle.batched.setVisibleAt(handle.instanceId, true);
      } else {
        mesh.visible = true;
      }
    }
    // Walk the full DAE scene graph and make everything visible again
    if (this.daeGroup) {
      this.daeGroup.traverse((obj) => {
        obj.visible = true;
      });
      this.daeGroup.visible = true;
    }
    this.sceneManager.requestRender();
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
    // Dispose previous colorBy/highlight materials before applying new ones
    this.disposeCreatedMaterials();

    const highlightColor = new THREE.Color(0xff9500); // orange
    const keep = new Set(elementIds);
    for (const [id, mesh] of this.meshMap) {
      if (keep.has(id)) {
        const ud = mesh.userData as {
          customMaterial?: boolean;
          originalMaterial?: THREE.Material | THREE.Material[];
        };
        // Clone material so we can recolour independently of the base.
        const base = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        if (base && 'clone' in base) {
          const cloned = (base as THREE.Material & { clone(): THREE.Material }).clone();
          mesh.material = cloned;
          this.createdMaterials.add(cloned);
          ud.customMaterial = true;
        }
        const mat = mesh.material as THREE.MeshStandardMaterial | THREE.MeshPhongMaterial;
        if (mat && 'color' in mat && mat.color) {
          mat.color.copy(highlightColor);
        }
      }
    }
    this.sceneManager.requestRender();
  }

  /** Isolate given element IDs — hide everything else. */
  isolate(elementIds: string[]): void {
    const keep = new Set(elementIds);
    for (const [id, mesh] of this.meshMap) {
      const v = keep.has(id);
      const handle = (mesh.userData as { batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } }).batchHandle;
      if (handle) {
        handle.batched.setVisibleAt(handle.instanceId, v);
      } else {
        mesh.visible = v;
      }
    }
    // When isolating specific elements, hide unmatched DAE background so the
    // isolated part actually stands out. If no meshes are matched at all we
    // keep the DAE group visible — users still need to see the model.
    if (this.meshMap.size > 0) {
      for (const mesh of this.allDaeMeshes) {
        const ud = mesh.userData as { elementId?: string | null; batchHandle?: { batched: THREE.BatchedMesh; instanceId: number } };
        if (!ud.elementId) {
          if (ud.batchHandle) {
            ud.batchHandle.batched.setVisibleAt(ud.batchHandle.instanceId, false);
          } else {
            mesh.visible = false;
          }
        }
      }
    }
    this.sceneManager.requestRender();
  }

  /**
   * Dispose all cloned materials from previous colorBy* calls.
   * Must be called at the start of every colorBy method to prevent
   * leaking one WebGL program per element per mode switch.
   */
  private disposeCreatedMaterials(): void {
    for (const mat of this.createdMaterials) {
      mat.dispose();
    }
    this.createdMaterials.clear();
    // Reset customMaterial flag on all meshes so the next colorBy pass
    // knows it needs to clone again from the original material.
    for (const [, mesh] of this.meshMap) {
      const ud = mesh.userData as {
        customMaterial?: boolean;
        originalMaterial?: THREE.Material | THREE.Material[];
      };
      if (ud.customMaterial) {
        if (ud.originalMaterial) {
          mesh.material = ud.originalMaterial;
        }
        ud.customMaterial = false;
      }
    }
  }

  /**
   * Re-color every mesh using a direct (element → Color | null) function.
   * Returning null leaves the mesh at its original colour.  This is the
   * fixed-palette path used by the "color by validation" / "color by BOQ
   * coverage" / "color by document coverage" modes — where we want a
   * meaningful red/amber/green colour scale, not the hash-to-hue rainbow
   * the existing `colorBy()` produces.
   */
  colorByDirect(colorFn: (el: BIMElementData) => THREE.Color | null): void {
    // Dispose all previously created materials to prevent memory leaks
    // when switching between colorBy modes.
    this.disposeCreatedMaterials();
    for (const [elementId, mesh] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      if (!el) continue;
      const color = colorFn(el);

      const ud = mesh.userData as {
        customMaterial?: boolean;
        originalMaterial?: THREE.Material | THREE.Material[];
      };

      if (color === null) {
        // Restore original material if we'd previously cloned one
        if (ud.customMaterial) {
          const old = mesh.material;
          if (old instanceof THREE.Material) {
            this.createdMaterials.delete(old);
            old.dispose();
          }
          if (ud.originalMaterial) mesh.material = ud.originalMaterial;
          ud.customMaterial = false;
        }
        continue;
      }

      // Clone material on first recolor so we don't mutate the shared one
      if (!ud.customMaterial) {
        const base = Array.isArray(mesh.material) ? mesh.material[0] : mesh.material;
        if (base && 'clone' in base) {
          const cloned = (
            base as THREE.Material & { clone(): THREE.Material }
          ).clone();
          mesh.material = cloned;
          this.createdMaterials.add(cloned);
          ud.customMaterial = true;
        }
      }
      const mat = mesh.material as THREE.MeshStandardMaterial | THREE.MeshPhongMaterial;
      if (mat && 'color' in mat && mat.color) {
        mat.color.copy(color);
      }
    }
    this.sceneManager.requestRender();
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

    // Dispose all previously created materials to prevent memory leaks
    // when switching between colorBy modes.
    this.disposeCreatedMaterials();

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
          const cloned = base.clone();
          mesh.material = cloned;
          this.createdMaterials.add(cloned);
          ud.customMaterial = true;
        }
      }
      const mat = mesh.material as THREE.MeshStandardMaterial;
      if (mat && mat.color) {
        mat.color.copy(color);
      }
    }
    this.sceneManager.requestRender();
  }

  /** Reset mesh colors back to their discipline-based material. */
  resetColors(): void {
    // Dispose all cloned materials and restore originals in one pass.
    this.disposeCreatedMaterials();
    // For meshes that had no originalMaterial cached, fall back to the
    // flat discipline material so they stay visible.
    for (const [elementId, mesh] of this.meshMap) {
      const el = this.elementDataMap.get(elementId);
      if (!el) continue;
      const ud = mesh.userData as {
        originalMaterial?: THREE.Material | THREE.Material[];
      };
      if (!ud.originalMaterial) {
        mesh.material = this.getMaterial(el.discipline || 'other');
      }
    }
    this.sceneManager.requestRender();
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
    // Dispose every BatchedMesh added by the big-model perf path
    for (const batched of this.batchedMeshes) {
      this.sceneManager.scene.remove(batched);
      batched.dispose();
    }
    this.batchedMeshes = [];
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
    // Dispose any per-mesh material clones still alive from colorBy* paths
    for (const mat of this.createdMaterials) {
      mat.dispose();
    }
    this.createdMaterials.clear();
    this.sceneManager.scene.remove(this.elementGroup);
  }
}
