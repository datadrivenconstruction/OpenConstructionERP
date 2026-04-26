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
