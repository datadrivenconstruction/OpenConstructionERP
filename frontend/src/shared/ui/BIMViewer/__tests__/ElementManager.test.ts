import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { ElementManager, type BIMElementData } from '../ElementManager';
import type { SceneManager } from '../SceneManager';

/** Build a minimal SceneManager stand-in with just what ElementManager needs. */
function makeFakeSceneManager(): SceneManager {
  const scene = new THREE.Scene();
  return {
    scene,
    requestRender: vi.fn(),
    zoomToFit: vi.fn(),
  } as unknown as SceneManager;
}

function sampleElements(): BIMElementData[] {
  return [
    {
      id: 'w1',
      name: 'Wall 1',
      element_type: 'Walls',
      discipline: 'architectural',
      bounding_box: {
        min_x: 0, min_y: 0, min_z: 0, max_x: 1, max_y: 1, max_z: 1,
      },
    },
    {
      id: 'w2',
      name: 'Wall 2',
      element_type: 'Walls',
      discipline: 'architectural',
      bounding_box: {
        min_x: 2, min_y: 0, min_z: 0, max_x: 3, max_y: 1, max_z: 1,
      },
    },
    {
      id: 'd1',
      name: 'Door 1',
      element_type: 'Doors',
      discipline: 'architectural',
      bounding_box: {
        min_x: 4, min_y: 0, min_z: 0, max_x: 5, max_y: 1, max_z: 1,
      },
    },
  ];
}

describe('ElementManager.setCategoryOpacity', () => {
  let scene: SceneManager;
  let mgr: ElementManager;

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    mgr.loadElements(sampleElements(), { skipPlaceholders: false });
  });

  it('applies opacity to every mesh of the matching category', () => {
    mgr.setCategoryOpacity('Walls', 0.4);
    const w1 = mgr.getMesh('w1')!;
    const w2 = mgr.getMesh('w2')!;
    const d1 = mgr.getMesh('d1')!;
    const w1Mat = w1.material as THREE.Material & { opacity: number };
    const w2Mat = w2.material as THREE.Material & { opacity: number };
    expect(w1Mat.opacity).toBeCloseTo(0.4);
    expect(w2Mat.opacity).toBeCloseTo(0.4);
    // Same cloned material across walls.
    expect(w1.material).toBe(w2.material);
    // Doors untouched.
    expect((d1.material as THREE.Material & { opacity?: number }).opacity).not.toBe(0.4);
  });

  it('toggles transparent=true below 1 and false at exactly 1', () => {
    mgr.setCategoryOpacity('Walls', 0.5);
    const mat = mgr.getMesh('w1')!.material as THREE.Material & {
      transparent: boolean;
      opacity: number;
    };
    expect(mat.transparent).toBe(true);
    mgr.setCategoryOpacity('Walls', 1);
    expect(mat.transparent).toBe(false);
    expect(mat.opacity).toBe(1);
  });

  it('does not allocate a new material on repeated calls to the same category', () => {
    mgr.setCategoryOpacity('Walls', 0.2);
    const firstMat = mgr.getMesh('w1')!.material;
    mgr.setCategoryOpacity('Walls', 0.7);
    mgr.setCategoryOpacity('Walls', 0.9);
    const latestMat = mgr.getMesh('w1')!.material;
    expect(latestMat).toBe(firstMat);
  });

  it('dispose() releases category-material clones', () => {
    mgr.setCategoryOpacity('Walls', 0.5);
    const wallsMat = mgr.getMesh('w1')!.material as THREE.Material;
    const disposeSpy = vi.spyOn(wallsMat, 'dispose');
    mgr.dispose();
    expect(disposeSpy).toHaveBeenCalled();
  });

  it('clamps opacity to [0, 1]', () => {
    mgr.setCategoryOpacity('Walls', 1.5);
    expect(
      (mgr.getMesh('w1')!.material as THREE.Material & { opacity: number }).opacity,
    ).toBe(1);
    mgr.setCategoryOpacity('Walls', -0.2);
    expect(
      (mgr.getMesh('w1')!.material as THREE.Material & { opacity: number }).opacity,
    ).toBe(0);
  });
});

/**
 * BIMViewer combines `isolatedIds` and `filterPredicate` by isolating
 * the intersection of the two sets (ids ∩ predicate-pass).  This test
 * confirms that passing that pre-computed intersection straight through
 * `isolate()` produces the expected mesh-visibility state — i.e. that
 * the contract the viewer relies on holds.
 */
describe('ElementManager.isolate (intersection with filter predicate)', () => {
  let scene: SceneManager;
  let mgr: ElementManager;
  let elements: BIMElementData[];

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    elements = sampleElements();
    mgr.loadElements(elements, { skipPlaceholders: false });
  });

  it('isolates only ids that appear in BOTH isolatedIds and filterPredicate', () => {
    // Scenario: user saved a group of { w1, w2 } and then typed a
    // search that only matches walls with a "1" suffix. The
    // intersection should leave just w1 visible.
    const isolatedIds = ['w1', 'w2'];
    const predicate = (el: BIMElementData) => el.name?.endsWith('1') ?? false;
    const idSet = new Set(isolatedIds);
    const intersectIds = elements
      .filter((e) => idSet.has(e.id) && predicate(e))
      .map((e) => e.id);
    mgr.isolate(intersectIds);
    expect(mgr.getMesh('w1')!.visible).toBe(true);
    expect(mgr.getMesh('w2')!.visible).toBe(false);
    expect(mgr.getMesh('d1')!.visible).toBe(false);
  });

  it('hides everything when the intersection is empty', () => {
    // isolatedIds = [w1], filter keeps only doors → no overlap
    const isolatedIds = ['w1'];
    const predicate = (el: BIMElementData) => el.element_type === 'Doors';
    const idSet = new Set(isolatedIds);
    const intersectIds = elements
      .filter((e) => idSet.has(e.id) && predicate(e))
      .map((e) => e.id);
    mgr.isolate(intersectIds);
    expect(mgr.getMesh('w1')!.visible).toBe(false);
    expect(mgr.getMesh('w2')!.visible).toBe(false);
    expect(mgr.getMesh('d1')!.visible).toBe(false);
  });
});

/**
 * applyFilter direction — selecting groups in the in-viewer filter panel
 * ISOLATES them (shows ONLY the selected groups, hides everything else).
 * A non-empty predicate keeps the elements it returns true for; everything
 * else is hidden. Clearing the filter (predicate that matches all) restores
 * full visibility. These tests pin the direction so a future refactor can
 * never silently invert it back into a hide-list.
 */
describe('ElementManager.applyFilter (isolate direction)', () => {
  let scene: SceneManager;
  let mgr: ElementManager;

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    mgr.loadElements(sampleElements(), { skipPlaceholders: false });
  });

  it('keeps ONLY the predicate-true elements visible (placeholder boxes)', () => {
    // User selects the "Walls" category chip -> predicate true for walls.
    const visible = mgr.applyFilter((el) => el.element_type === 'Walls');
    expect(visible).toBe(2);
    expect(mgr.getMesh('w1')!.visible).toBe(true);
    expect(mgr.getMesh('w2')!.visible).toBe(true);
    // The unselected door must be hidden, NOT the other way around.
    expect(mgr.getMesh('d1')!.visible).toBe(false);
  });

  it('treats multi-select as a union (Walls OR Doors keeps both)', () => {
    const selected = new Set(['Walls', 'Doors']);
    const visible = mgr.applyFilter((el) => selected.has(el.element_type ?? ''));
    expect(visible).toBe(3);
    expect(mgr.getMesh('w1')!.visible).toBe(true);
    expect(mgr.getMesh('w2')!.visible).toBe(true);
    expect(mgr.getMesh('d1')!.visible).toBe(true);
  });

  it('restores full visibility when the filter is cleared (match-all)', () => {
    mgr.applyFilter((el) => el.element_type === 'Walls'); // isolate walls
    expect(mgr.getMesh('d1')!.visible).toBe(false);
    // An empty selection emits a match-all predicate -> everything visible.
    const visible = mgr.applyFilter(() => true);
    expect(visible).toBe(3);
    expect(mgr.getMesh('w1')!.visible).toBe(true);
    expect(mgr.getMesh('w2')!.visible).toBe(true);
    expect(mgr.getMesh('d1')!.visible).toBe(true);
  });
});

/**
 * applyFilter on a DAE/GLB-loaded scene — the large Revit/IFC path. After
 * geometry parses, meshes live under `daeGroup` keyed by `userData.elementId`.
 * The filter must isolate the selected category there too (the in-viewer
 * panel reported the opposite on these models). Built by driving the same
 * private `processLoadedScene` the other suites use.
 */
describe('ElementManager.applyFilter on a DAE-loaded scene', () => {
  let scene: SceneManager;
  let mgr: ElementManager;

  function manyElements(): BIMElementData[] {
    const out: BIMElementData[] = [];
    for (let i = 0; i < 3; i++) {
      out.push({
        id: `wall_${i}`,
        name: `Wall ${i}`,
        element_type: 'Walls',
        discipline: 'architectural',
        mesh_ref: `wall_${i}`,
        bounding_box: { min_x: i, min_y: 0, min_z: 0, max_x: i + 1, max_y: 1, max_z: 1 },
      });
    }
    for (let i = 0; i < 2; i++) {
      out.push({
        id: `door_${i}`,
        name: `Door ${i}`,
        element_type: 'Doors',
        discipline: 'architectural',
        mesh_ref: `door_${i}`,
        bounding_box: { min_x: 10 + i, min_y: 0, min_z: 0, max_x: 11 + i, max_y: 1, max_z: 1 },
      });
    }
    return out;
  }

  function buildDaeScene(elements: BIMElementData[]): THREE.Group {
    const g = new THREE.Group();
    for (const el of elements) {
      const mesh = new THREE.Mesh(
        new THREE.BoxGeometry(1, 1, 1),
        new THREE.MeshStandardMaterial(),
      );
      // Backend patches DAE node names to equal mesh_ref so the matcher binds.
      mesh.name = el.mesh_ref!;
      g.add(mesh);
    }
    return g;
  }

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    const all = manyElements();
    mgr.loadElements(all, { skipPlaceholders: true });
    (
      mgr as unknown as {
        processLoadedScene: (s: THREE.Object3D, p?: unknown, isGLB?: boolean) => void;
      }
    ).processLoadedScene(buildDaeScene(all), undefined, true);
  });

  it('isolates the selected category (Walls visible, Doors hidden)', () => {
    const visible = mgr.applyFilter((el) => el.element_type === 'Walls');
    expect(visible).toBe(3);
    for (let i = 0; i < 3; i++) expect(mgr.getMesh(`wall_${i}`)!.visible).toBe(true);
    for (let i = 0; i < 2; i++) expect(mgr.getMesh(`door_${i}`)!.visible).toBe(false);
  });

  it('clearing the filter shows the whole model again', () => {
    mgr.applyFilter((el) => el.element_type === 'Walls');
    mgr.applyFilter(() => true);
    for (let i = 0; i < 3; i++) expect(mgr.getMesh(`wall_${i}`)!.visible).toBe(true);
    for (let i = 0; i < 2; i++) expect(mgr.getMesh(`door_${i}`)!.visible).toBe(true);
  });
});

/**
 * Up-axis handling in `processLoadedScene` — branch by loader.
 *
 *  - GLB scenes need an explicit -90° X rotation: GLTFLoader does no
 *    auto-rotation and our trimesh export keeps the source Z_UP frame.
 *  - DAE scenes from ColladaLoader are pre-rotated to Y_UP by the loader
 *    when the COLLADA `<up_axis>` is `Z_UP`, so we MUST NOT rotate again
 *    (regression of fix 1f80522 / 1f0530f produced an upside-down model).
 *  - DAE scenes that arrive un-rotated (writer omitted `<up_axis>` or
 *    declared Y_UP) are detected via a bbox heuristic — Y extent ≥ Z
 *    extent ⇒ already upright ⇒ skip rotation.
 */
describe('ElementManager.processLoadedScene up-axis handling', () => {
  let scene: SceneManager;
  let mgr: ElementManager;

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    mgr.loadElements(sampleElements(), { skipPlaceholders: true });
  });

  /** Build a Group whose bbox extends mostly along the chosen axis. */
  function makeSceneTallOn(axis: 'y' | 'z'): THREE.Group {
    const group = new THREE.Group();
    // 1×1 mesh in xy, then make it tall along the chosen axis. The other
    // axis is left small so the bbox heuristic has a clear winner.
    const big = axis === 'z' ? 10 : 1;
    const tall = axis === 'y' ? 10 : 1;
    const geom = new THREE.BoxGeometry(1, tall, big);
    const mesh = new THREE.Mesh(geom, new THREE.MeshBasicMaterial());
    group.add(mesh);
    return group;
  }

  it('GLB-loaded scene gets rotation.x = -PI/2', () => {
    const glbScene = makeSceneTallOn('z'); // bbox shape irrelevant when isGLB=true
    // processLoadedScene is private; test via bracket access.
    (mgr as unknown as {
      processLoadedScene: (s: THREE.Object3D, p?: unknown, isGLB?: boolean) => void;
    }).processLoadedScene(glbScene, undefined, true);
    expect(glbScene.rotation.x).toBeCloseTo(-Math.PI / 2);
  });

  it('DAE-loaded scene with Z_UP-pre-rotated bbox (Y > Z) is NOT rotated', () => {
    // ColladaLoader pre-rotates Z_UP → Y_UP, so the loaded scene's bbox
    // should now have larger Y extent than Z extent. We must NOT rotate again.
    const daeScene = makeSceneTallOn('y');
    (mgr as unknown as {
      processLoadedScene: (s: THREE.Object3D, p?: unknown, isGLB?: boolean) => void;
    }).processLoadedScene(daeScene, undefined, false);
    expect(daeScene.rotation.x).toBe(0);
  });

  it('DAE-loaded scene with Y_UP bbox (Y >= Z) is NOT rotated', () => {
    // Y_UP DAE: arrives un-rotated by ColladaLoader, but is already upright.
    const daeScene = makeSceneTallOn('y');
    (mgr as unknown as {
      processLoadedScene: (s: THREE.Object3D, p?: unknown, isGLB?: boolean) => void;
    }).processLoadedScene(daeScene, undefined, false);
    expect(daeScene.rotation.x).toBe(0);
  });
});

/**
 * Ghost mode — non-kept meshes get the shared translucent material; the
 * original is parked and restored exactly on clearGhost(). Verifies the
 * clean-state-restore contract the brief requires.
 */
describe('ElementManager.ghost / clearGhost', () => {
  let scene: SceneManager;
  let mgr: ElementManager;

  beforeEach(() => {
    scene = makeFakeSceneManager();
    mgr = new ElementManager(scene);
    mgr.loadElements(sampleElements(), { skipPlaceholders: false });
  });

  it('ghosts every element except the kept set', () => {
    const w1Orig = mgr.getMesh('w1')!.material;
    mgr.ghost(['w1']);
    expect(mgr.isGhostActive()).toBe(true);
    // Kept element keeps its original material.
    expect(mgr.getMesh('w1')!.material).toBe(w1Orig);
    // Non-kept share the single ghost material instance.
    const w2Mat = mgr.getMesh('w2')!.material;
    const d1Mat = mgr.getMesh('d1')!.material;
    expect(w2Mat).toBe(d1Mat);
    expect((w2Mat as THREE.Material).transparent).toBe(true);
  });

  it('restores every original material on clearGhost()', () => {
    const w2Orig = mgr.getMesh('w2')!.material;
    const d1Orig = mgr.getMesh('d1')!.material;
    mgr.ghost(['w1']);
    mgr.clearGhost();
    expect(mgr.isGhostActive()).toBe(false);
    expect(mgr.getMesh('w2')!.material).toBe(w2Orig);
    expect(mgr.getMesh('d1')!.material).toBe(d1Orig);
  });

  it('re-ghosting a new keep set restores the now-kept mesh', () => {
    const w2Orig = mgr.getMesh('w2')!.material;
    mgr.ghost(['w1']); // w2 ghosted
    mgr.ghost(['w2']); // w2 now kept → must be restored, w1 ghosted
    expect(mgr.getMesh('w2')!.material).toBe(w2Orig);
    const w1Mat = mgr.getMesh('w1')!.material as THREE.Material;
    expect(w1Mat.transparent).toBe(true);
  });

  it('treats an empty keep set as clearGhost (no-op contrast)', () => {
    const w1Orig = mgr.getMesh('w1')!.material;
    mgr.ghost([]);
    expect(mgr.isGhostActive()).toBe(false);
    expect(mgr.getMesh('w1')!.material).toBe(w1Orig);
  });

  it('dispose() releases the shared ghost material', () => {
    mgr.ghost(['w1']);
    const ghostMat = mgr.getMesh('w2')!.material as THREE.Material;
    const spy = vi.spyOn(ghostMat, 'dispose');
    mgr.dispose();
    expect(spy).toHaveBeenCalled();
  });
});
