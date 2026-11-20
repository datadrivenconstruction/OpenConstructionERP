// What the shared 3D viewer must do with a design-revision GLB (contract `ddc-erp-link/1`, section 3).
// These guard the viewer patches in erp-module/frontend/patches/: without them the tests fail.
import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { ElementManager, type BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';

type Internals = { processLoadedScene: (s: THREE.Object3D, p?: unknown, isGLB?: boolean) => void };

function fakeScene(): SceneManager {
  return { scene: new THREE.Scene(), requestRender: vi.fn(), zoomToFit: vi.fn() } as unknown as SceneManager;
}

const KEYS = ['b1/s05/u4A/room-living/wall-N/0', 'b1/s05/u4A/room-living/wall-E/0', 'b1/s01/slab.1:top#2'];

function rows(): BIMElementData[] {
  return KEYS.map((k, i) => ({
    id: k,
    name: `Element ${i}`,
    element_type: 'Walls',
    discipline: 'architectural',
    mesh_ref: k,
    bounding_box: { min_x: i, min_y: 0, min_z: 0, max_x: i + 1, max_y: 1, max_z: 1 },
  }));
}

/** What GLTFLoader hands over: names sanitised by three.js, glTF extras in userData. */
function glbScene(): THREE.Group {
  const g = new THREE.Group();
  for (const k of KEYS) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(1, 1, 1), new THREE.MeshStandardMaterial());
    m.name = THREE.PropertyBinding.sanitizeNodeName(k);
    m.userData = { element_key: k, type_key: 'wall.brick.240', ifc_class: 'IfcWall' };
    g.add(m);
  }
  return g;
}

function load(axis?: 'y') {
  const mgr = new ElementManager(fakeScene());
  if (axis) mgr.setGlbUpAxis(axis);
  mgr.loadElements(rows(), { skipPlaceholders: true });
  const scene = glbScene();
  (mgr as unknown as Internals).processLoadedScene(scene, undefined, true);
  return { mgr, scene };
}

describe('design revision GLB in the shared viewer', () => {
  it('the three.js loader really mangles contract keys in node names', () => {
    expect(THREE.PropertyBinding.sanitizeNodeName(KEYS[0]!)).not.toBe(KEYS[0]);
    expect(THREE.PropertyBinding.sanitizeNodeName(KEYS[2]!)).not.toBe(KEYS[2]);
  });

  it('binds every node to its element through extras.element_key', () => {
    const { mgr } = load('y');
    for (const k of KEYS) {
      const mesh = mgr.getMesh(k);
      expect(mesh, k).toBeTruthy();
      expect((mesh!.userData as { elementId: string }).elementId).toBe(k);
    }
  });

  it('keeps the three extras on the node after loading', () => {
    const { mgr } = load('y');
    const extras = (mgr.getMesh(KEYS[0]!)!.userData as { nodeExtras?: Record<string, string> }).nodeExtras;
    expect(extras).toEqual({ element_key: KEYS[0], type_key: 'wall.brick.240', ifc_class: 'IfcWall' });
  });

  it('does not rotate an upright (Y-up) GLB, but still rotates converter output', () => {
    expect(load('y').scene.rotation.x).toBe(0);
    expect(load().scene.rotation.x).toBeCloseTo(-Math.PI / 2);
  });

  it('showAll keeps batched originals parked so nothing is drawn twice', () => {
    const { mgr, scene } = load('y');
    const mesh = mgr.getMesh(KEYS[0]!)!;
    const setVisibleAt = vi.fn();
    (mesh.userData as Record<string, unknown>).batchHandle = { batched: { setVisibleAt }, instanceId: 3 };
    mesh.visible = false;
    mgr.showAll();
    expect(mesh.visible).toBe(false);
    expect(setVisibleAt).toHaveBeenCalledWith(3, true);
    expect(scene).toBeTruthy();
  });
});

describe('other models are untouched by the design patches', () => {
  function batched(axis?: 'y') {
    const { mgr } = load(axis);
    const mesh = mgr.getMesh(KEYS[0]!)!;
    const setVisibleAt = vi.fn();
    (mesh.userData as Record<string, unknown>).batchHandle = { batched: { setVisibleAt }, instanceId: 3 };
    return { mgr, mesh, setVisibleAt };
  }

  it('hiding by storey or discipline sets mesh.visible for a converter model, as before', () => {
    const { mgr, mesh, setVisibleAt } = batched();
    mgr.setDisciplineVisible('architectural', false);
    expect(mesh.visible).toBe(false);
    expect(setVisibleAt).not.toHaveBeenCalled();
  });

  it('hiding by discipline goes through the batched mesh only for a design model', () => {
    const { mgr, setVisibleAt } = batched('y');
    mgr.setDisciplineVisible('architectural', false);
    expect(setVisibleAt).toHaveBeenCalledWith(3, false);
  });

  it('showAll treats a converter model as before: every node is made visible again', () => {
    const { mgr, mesh } = batched();
    const dae = new THREE.Group();
    const node = new THREE.Object3D();
    node.userData = { batchHandle: {} };
    node.visible = false;
    dae.add(node);
    (mgr as unknown as { daeGroup: THREE.Group }).daeGroup = dae;
    mesh.visible = false;
    mgr.showAll();
    expect(node.visible).toBe(true);
  });

  it('a converter model ignores element_key extras: no binding, no node extras', () => {
    const { mgr } = load();
    for (const k of KEYS) {
      const ud = mgr.getMesh(k)?.userData as Record<string, unknown> | undefined;
      expect(ud?.nodeExtras).toBeUndefined();
      expect(ud && 'nodeExtras' in ud).toBe(false);
    }
  });
});
