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
