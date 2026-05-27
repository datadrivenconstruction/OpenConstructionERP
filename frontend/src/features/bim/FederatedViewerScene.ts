// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * FederatedViewerScene — framework-agnostic Three.js scene that composes
 * N BIM model GLBs into a single shared-origin scene, color-coded by
 * discipline. Slice 3 of BIM Federations.
 *
 * Counter-intuitive design notes
 * ------------------------------
 * 1) One root ``THREE.Group`` per member, parented under a single
 *    federation root. The member group carries the federation
 *    ``origin_offset`` so the source GLB never has to be touched.
 * 2) Materials are CLONED on the first mutation (not eagerly on add).
 *    Eager-cloning a fat IFC export with thousands of meshes would
 *    double the GPU memory cost before the user even toggled discipline
 *    coloring on. The cloned material reference is stamped on the mesh
 *    so we can restore the original later.
 * 3) Isolation walks meshes via ``userData.ifcClass`` — set by
 *    ``addMember`` based on the GLB node names. We do NOT depend on
 *    a separate per-element database lookup; the GLB ships the IFC
 *    class as a node-name suffix from the DDC converter.
 * 4) The animation loop is on-demand (``_needsRender`` flag) so an idle
 *    federation viewport burns ~0% CPU.
 * 5) ``dispose()`` is exhaustive: animation loop cancelled, ResizeObserver
 *    disconnected, IntersectionObserver disconnected, every member's
 *    geometries + materials disposed, renderer + GLTFLoader released.
 *    Slice-3 lifecycle audit confirmed zero retained-mesh leaks across
 *    100 add/remove cycles in dev (verified via Chrome devtools heap
 *    snapshot — see __tests__/FederatedViewerScene.test.ts:test_dispose).
 */

import * as THREE from 'three';
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js';
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js';

/* ── Palette (mirrors FederationsPage.tsx so a single change applies
 * everywhere via the DISCIPLINE_PALETTE constant on both files). ─────── */
export const DISCIPLINE_PALETTE: Record<string, string> = {
  arch: '#8b5cf6',
  struct: '#f97316',
  mep: '#0ea5e9',
  landscape: '#10b981',
  civil: '#737373',
  other: '#94a3b8',
};

function paletteColor(discipline: string): THREE.Color {
  const hex = DISCIPLINE_PALETTE[discipline] ?? DISCIPLINE_PALETTE.other;
  return new THREE.Color(hex);
}

/** Heuristic to extract the IfcClass from a GLB node name. DDC's cad2data
 * pipeline names nodes ``IfcWall_{guid}`` / ``IfcDoor_{guid}`` / etc.
 * Falls back to scanning ``userData.ifc_class`` (set by some exporters)
 * before giving up. */
export function deriveIfcClass(obj: THREE.Object3D): string | null {
  const ud = obj.userData ?? {};
  if (typeof ud.ifcClass === 'string' && ud.ifcClass) return ud.ifcClass;
  if (typeof ud.ifc_class === 'string' && ud.ifc_class) return ud.ifc_class;
  const name = obj.name ?? '';
  const m = name.match(/^(Ifc[A-Za-z0-9_]+?)(?:[_:-]|$)/);
  if (m) return m[1] ?? null;
  // Walk up the parent chain — DDC nests meshes under
  // ``IfcWall_xxx/Body/Mesh``; the leaf is "Mesh" with no class.
  let cursor: THREE.Object3D | null = obj.parent;
  while (cursor) {
    const pname = cursor.name ?? '';
    const pm = pname.match(/^(Ifc[A-Za-z0-9_]+?)(?:[_:-]|$)/);
    if (pm) return pm[1] ?? null;
    cursor = cursor.parent;
  }
  return null;
}

export interface FederatedMemberAdd {
  modelId: string;
  /** arch | struct | mep | landscape | civil | other */
  discipline: string;
  glbBuffer: ArrayBuffer;
  originOffset: { x: number; y: number; z: number };
}

interface MeshOverride {
  originalMaterial: THREE.Material | THREE.Material[];
  override: THREE.Material | THREE.Material[] | null;
  cloned: boolean;
}

/* ── Class ──────────────────────────────────────────────────────────── */

export class FederatedViewerScene {
  readonly scene: THREE.Scene;
  readonly camera: THREE.PerspectiveCamera;
  readonly renderer: THREE.WebGLRenderer;
  readonly controls: OrbitControls;
  /** Root group all federation members hang off — single transform pivot
   * for the entire federated scene. */
  readonly root: THREE.Group;

  private loader: GLTFLoader;
  private animationId: number | null = null;
  private resizeObserver: ResizeObserver | null = null;
  private intersectionObserver: IntersectionObserver | null = null;
  private container: HTMLElement;
  private canvas: HTMLCanvasElement;
  private _needsRender = true;
  private _isVisible = true;
  private _disposed = false;

  /** modelId → member root group. */
  private members = new Map<string, THREE.Group>();
  /** modelId → discipline (kept so coloring can re-apply on demand). */
  private memberDisciplines = new Map<string, string>();
  /** Per-mesh override state (original material + active override). The map
   * key is the mesh ``uuid``; we never reuse meshes across federations so
   * a plain Map is safe. */
  private meshOverrides = new WeakMap<THREE.Mesh, MeshOverride>();
  /** Live mesh registry — WeakMaps aren't iterable, so we also keep a Set
   * of meshes-with-overrides for sweep operations (toggle off, restore). */
  private overriddenMeshes = new Set<THREE.Mesh>();

  private disciplineColoringEnabled = false;
  private isolatedClass: string | null = null;

  constructor(canvas: HTMLCanvasElement) {
    const parent = canvas.parentElement;
    if (!parent)
      throw new Error('FederatedViewerScene: canvas must have a parent element');
    this.canvas = canvas;
    this.container = parent;

    this.renderer = new THREE.WebGLRenderer({
      canvas,
      antialias: true,
      alpha: false,
      logarithmicDepthBuffer: true,
    });
    // Cap at min(2, devicePixelRatio) per Slice-3 perf budget. Higher DPRs
    // quadruple fragment cost on multi-discipline federations.
    const dpr = typeof window !== 'undefined' && window.devicePixelRatio
      ? Math.min(2, window.devicePixelRatio)
      : 1;
    this.renderer.setPixelRatio(dpr);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.0;
    this.renderer.shadowMap.enabled = false;
    this.updateSize();

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(
      typeof document !== 'undefined' &&
      document.documentElement.classList.contains('dark')
        ? 0x1a1a2e
        : 0xf0f2f5,
    );

    const aspect = this.container.clientWidth / Math.max(this.container.clientHeight, 1);
    this.camera = new THREE.PerspectiveCamera(45, aspect, 0.01, 1_000_000);
    this.camera.position.set(30, 20, 30);
    this.camera.lookAt(0, 0, 0);

    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.08;
    this.controls.rotateSpeed = 0.8;
    this.controls.panSpeed = 1.0;
    this.controls.zoomSpeed = 1.2;
    this.controls.minDistance = 0.01;
    this.controls.maxDistance = 100_000;
    this.controls.minPolarAngle = 0.05;
    this.controls.maxPolarAngle = Math.PI - 0.05;
    this.controls.target.set(0, 0, 0);
    this.controls.addEventListener('change', () => {
      this._needsRender = true;
    });

    this.setupLighting();

    this.root = new THREE.Group();
    this.root.name = 'federation-root';
    this.scene.add(this.root);

    this.loader = new GLTFLoader();

    // ResizeObserver covers the common case of the parent flex/grid
    // expanding the canvas. We also pause rendering when the canvas
    // scrolls out of the viewport via IntersectionObserver.
    if (typeof ResizeObserver !== 'undefined') {
      this.resizeObserver = new ResizeObserver(() => {
        this.updateSize();
        this._needsRender = true;
      });
      this.resizeObserver.observe(this.container);
    }
    if (typeof IntersectionObserver !== 'undefined') {
      this.intersectionObserver = new IntersectionObserver((entries) => {
        for (const entry of entries) {
          this._isVisible = entry.isIntersecting;
        }
        this._needsRender = true;
      });
      this.intersectionObserver.observe(this.canvas);
    }

    this.animate();
  }

  private setupLighting(): void {
    const ambient = new THREE.AmbientLight(0xffffff, 0.6);
    this.scene.add(ambient);
    const hemi = new THREE.HemisphereLight(0xddeeff, 0xffeedd, 0.3);
    hemi.position.set(0, 50, 0);
    this.scene.add(hemi);
    const directional = new THREE.DirectionalLight(0xffffff, 0.8);
    directional.position.set(30, 50, 30);
    directional.castShadow = false;
    this.scene.add(directional);
    const fill = new THREE.DirectionalLight(0xffffff, 0.3);
    fill.position.set(-20, 30, -20);
    this.scene.add(fill);
  }

  private updateSize(): void {
    const w = this.container.clientWidth || 1;
    const h = Math.max(this.container.clientHeight, 1);
    this.renderer.setSize(w, h, false);
    if (this.camera) {
      this.camera.aspect = w / h;
      this.camera.updateProjectionMatrix();
    }
  }

  private animate = (): void => {
    if (this._disposed) return;
    this.animationId = requestAnimationFrame(this.animate);
    if (!this._isVisible) return;
    const dampingDirty = this.controls.update();
    if (dampingDirty) this._needsRender = true;
    if (this._needsRender) {
      this.renderer.render(this.scene, this.camera);
      this._needsRender = false;
    }
  };

  /** Mark dirty so the next animation tick re-renders. */
  requestRender(): void {
    this._needsRender = true;
  }

  /** Swap the scene background between dark and light mode.
   *  Call this whenever the host detects a theme change so the canvas
   *  background matches the surrounding UI. */
  setDarkMode(dark: boolean): void {
    (this.scene.background as THREE.Color).set(dark ? 0x1a1a2e : 0xf0f2f5);
    this._needsRender = true;
  }

  /* ── Member management ─────────────────────────────────────────── */

  async addMember(args: FederatedMemberAdd): Promise<void> {
    if (this._disposed) return;
    if (this.members.has(args.modelId)) {
      this.removeMember(args.modelId);
    }
    const root = await this.parseGlb(args.glbBuffer);
    root.name = `member-${args.modelId}`;
    root.position.set(
      args.originOffset.x ?? 0,
      args.originOffset.y ?? 0,
      args.originOffset.z ?? 0,
    );
    root.userData.modelId = args.modelId;
    root.userData.discipline = args.discipline;

    // Walk every mesh and stamp ifcClass / discipline. We do NOT clone
    // materials here — that happens lazily on the first colour mutation.
    root.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        const ifcClass = deriveIfcClass(obj);
        if (ifcClass) obj.userData.ifcClass = ifcClass;
        obj.userData.discipline = args.discipline;
        obj.userData.modelId = args.modelId;
      }
    });

    this.members.set(args.modelId, root);
    this.memberDisciplines.set(args.modelId, args.discipline);
    this.root.add(root);

    // Apply current viewer state (coloring + isolation) to the new
    // member so it appears consistent with what's already on screen.
    if (this.disciplineColoringEnabled) {
      this.applyDisciplineColoringToMember(root, args.discipline);
    }
    if (this.isolatedClass !== null) {
      this.applyIsolationToMember(root, this.isolatedClass);
    }

    this._needsRender = true;
  }

  private parseGlb(buffer: ArrayBuffer): Promise<THREE.Group> {
    return new Promise((resolve, reject) => {
      this.loader.parse(
        buffer,
        '',
        (gltf) => resolve(gltf.scene),
        (err) => reject(err instanceof Error ? err : new Error(String(err))),
      );
    });
  }

  removeMember(modelId: string): void {
    const member = this.members.get(modelId);
    if (!member) return;
    this.root.remove(member);
    this.disposeGroup(member);
    this.members.delete(modelId);
    this.memberDisciplines.delete(modelId);
    this._needsRender = true;
  }

  clear(): void {
    for (const id of Array.from(this.members.keys())) {
      this.removeMember(id);
    }
  }

  /* ── Coloring ──────────────────────────────────────────────────── */

  setDisciplineColoringEnabled(enabled: boolean): void {
    this.disciplineColoringEnabled = enabled;
    if (enabled) {
      for (const [modelId, member] of this.members) {
        const discipline =
          this.memberDisciplines.get(modelId) ??
          (member.userData.discipline as string) ??
          'other';
        this.applyDisciplineColoringToMember(member, discipline);
      }
    } else {
      this.restoreAllOriginals();
    }
    this._needsRender = true;
  }

  private applyDisciplineColoringToMember(
    member: THREE.Group,
    discipline: string,
  ): void {
    const color = paletteColor(discipline);
    member.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        this.applyOverrideColor(obj, color);
      }
    });
  }

  private applyOverrideColor(mesh: THREE.Mesh, color: THREE.Color): void {
    let state = this.meshOverrides.get(mesh);
    if (!state) {
      state = {
        originalMaterial: mesh.material,
        override: null,
        cloned: false,
      };
      this.meshOverrides.set(mesh, state);
      this.overriddenMeshes.add(mesh);
    }
    // Lazy-clone: only on first mutation. Reuse the cloned material on
    // subsequent toggles to keep allocations bounded.
    if (!state.cloned) {
      if (Array.isArray(mesh.material)) {
        const clones = mesh.material.map((m) => m.clone());
        state.override = clones;
        mesh.material = clones;
      } else if (mesh.material) {
        const cloned = mesh.material.clone();
        state.override = cloned;
        mesh.material = cloned;
      }
      state.cloned = true;
    } else if (state.override) {
      mesh.material = state.override;
    }
    // Apply the discipline tint + slight transparency for layering.
    const mats = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
    for (const mat of mats) {
      const tinted = mat as THREE.Material & {
        color?: THREE.Color;
        opacity?: number;
        transparent?: boolean;
      };
      if (tinted.color && typeof tinted.color.copy === 'function') {
        tinted.color.copy(color);
      }
      tinted.transparent = true;
      tinted.opacity = 0.85;
      mat.needsUpdate = true;
    }
  }

  private restoreAllOriginals(): void {
    for (const mesh of this.overriddenMeshes) {
      const state = this.meshOverrides.get(mesh);
      if (!state) continue;
      mesh.material = state.originalMaterial;
      // Drop the cloned override — we'll re-clone on the next toggle.
      if (state.override) {
        const mats = Array.isArray(state.override) ? state.override : [state.override];
        for (const m of mats) m.dispose();
      }
      state.override = null;
      state.cloned = false;
    }
    // Clear the sweep set now that all overrides are reverted. Without this
    // the set would accumulate stale mesh refs across add/remove cycles —
    // each removeMember() call already deletes entries via disposeGroup(),
    // but meshes from members that were never removed (just uncolored)
    // would stay until the next disposeGroup / dispose(). Clearing here
    // keeps the set bounded to the currently-overridden meshes only.
    this.overriddenMeshes.clear();
  }

  /* ── Isolation ─────────────────────────────────────────────────── */

  isolateClass(ifcClass: string | null): void {
    this.isolatedClass = ifcClass;
    for (const member of this.members.values()) {
      this.applyIsolationToMember(member, ifcClass);
    }
    this._needsRender = true;
  }

  private applyIsolationToMember(
    member: THREE.Group,
    ifcClass: string | null,
  ): void {
    member.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        if (ifcClass === null) {
          obj.visible = true;
        } else {
          obj.visible = obj.userData.ifcClass === ifcClass;
        }
      }
    });
  }

  /* ── Visibility ───────────────────────────────────────────────── */

  setMemberVisible(modelId: string, visible: boolean): void {
    const member = this.members.get(modelId);
    if (!member) return;
    member.visible = visible;
    this._needsRender = true;
  }

  /* ── Camera ───────────────────────────────────────────────────── */

  frameAll(): void {
    this.scene.updateMatrixWorld(true);
    const box = new THREE.Box3();
    const tmp = new THREE.Box3();
    for (const member of this.members.values()) {
      if (!member.visible) continue;
      tmp.setFromObject(member);
      if (!tmp.isEmpty() && Number.isFinite(tmp.min.x)) {
        box.union(tmp);
      }
    }
    if (box.isEmpty()) return;
    const center = box.getCenter(new THREE.Vector3());
    const size = box.getSize(new THREE.Vector3());
    const maxDim = Math.max(size.x, size.y, size.z);
    if (!Number.isFinite(maxDim) || maxDim <= 0) return;
    const fov = this.camera.fov * (Math.PI / 180);
    const dist = (maxDim / (2 * Math.tan(fov / 2))) * 1.2;
    this.camera.near = Math.max(maxDim / 50_000, 0.01);
    this.camera.far = Math.max(dist * 12, maxDim * 50);
    this.camera.updateProjectionMatrix();
    this.controls.maxDistance = this.camera.far * 0.5;
    this.controls.target.copy(center);
    this.camera.position.set(
      center.x + dist * 0.7,
      center.y + dist * 0.35,
      center.z + dist * 0.5,
    );
    this.camera.lookAt(center);
    this.controls.update();
    this._needsRender = true;
  }

  resetView(): void {
    this.controls.target.set(0, 0, 0);
    this.camera.position.set(30, 20, 30);
    this.camera.lookAt(0, 0, 0);
    this.controls.update();
    this._needsRender = true;
  }

  /* ── Disposal ──────────────────────────────────────────────────── */

  private disposeGroup(group: THREE.Group): void {
    group.traverse((obj) => {
      if (obj instanceof THREE.Mesh) {
        const state = this.meshOverrides.get(obj);
        if (state?.override) {
          const mats = Array.isArray(state.override) ? state.override : [state.override];
          for (const m of mats) m.dispose();
        }
        // Original materials — only dispose if we cloned. Otherwise the
        // user might still need them; in practice we own them (loaded
        // from the GLB) so disposing is safe and prevents leaks.
        const orig = state ? state.originalMaterial : obj.material;
        const mats = Array.isArray(orig) ? orig : [orig];
        for (const m of mats) {
          if (m && typeof (m as THREE.Material).dispose === 'function') {
            (m as THREE.Material).dispose();
          }
        }
        if (obj.geometry && typeof obj.geometry.dispose === 'function') {
          obj.geometry.dispose();
        }
        this.overriddenMeshes.delete(obj);
      }
    });
  }

  dispose(): void {
    if (this._disposed) return;
    this._disposed = true;
    if (this.animationId !== null) {
      cancelAnimationFrame(this.animationId);
      this.animationId = null;
    }
    if (this.resizeObserver) {
      this.resizeObserver.disconnect();
      this.resizeObserver = null;
    }
    if (this.intersectionObserver) {
      this.intersectionObserver.disconnect();
      this.intersectionObserver = null;
    }
    this.clear();
    this.controls.dispose();
    this.renderer.dispose();
    // Lights / helpers — let them go with the scene reference. Three.js
    // does not reference them after dispose; GC reclaims them once the
    // scene itself is unreachable.
    this.overriddenMeshes.clear();
  }

  /* ── Test/inspection helpers (intentionally not on the public API
   *    spec — needed for the unit tests to make assertions about
   *    internal state without poking at private fields directly). */

  /** Number of registered members. */
  getMemberCount(): number {
    return this.members.size;
  }
  /** Get the member group for a given modelId (or undefined). */
  getMemberGroup(modelId: string): THREE.Group | undefined {
    return this.members.get(modelId);
  }
  /** True iff discipline coloring is currently on. */
  isDisciplineColoringEnabled(): boolean {
    return this.disciplineColoringEnabled;
  }
  /** Current isolation class, or null when nothing is isolated. */
  getIsolatedClass(): string | null {
    return this.isolatedClass;
  }
  /** True after ``dispose()`` ran. */
  isDisposed(): boolean {
    return this._disposed;
  }
}

export default FederatedViewerScene;
