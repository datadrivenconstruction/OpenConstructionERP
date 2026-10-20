// Isolating 1 element of a 534-element RVT model said "563 hidden": the
// stub rows made for meshes no model row claimed were counted as elements.

import { describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';
import { ElementManager, UNMATCHED_ID_PREFIX, type BIMElementData } from '../ElementManager';
import type { SceneManager } from '../SceneManager';

function fakeScene(): SceneManager {
  return { scene: new THREE.Scene(), requestRender: vi.fn(), zoomToFit: vi.fn() } as unknown as SceneManager;
}

function box(x: number) {
  return { min_x: x, min_y: 0, min_z: 0, max_x: x + 1, max_y: 1, max_z: 1 };
}

const ELEMENTS: BIMElementData[] = [
  { id: 'w1', name: 'Wall 1', element_type: 'Walls', discipline: 'architectural', bounding_box: box(0) },
  { id: 'w2', name: 'Wall 2', element_type: 'Walls', discipline: 'architectural', bounding_box: box(2) },
  { id: 'd1', name: 'Door 1', element_type: 'Doors', discipline: 'architectural', bounding_box: box(4) },
  {
    id: `${UNMATCHED_ID_PREFIX}0`,
    name: 'Unmatched element 1',
    element_type: 'Unmatched',
    discipline: 'other',
    bounding_box: box(6),
  },
];

describe('ElementManager.hiddenCount', () => {
  it('counts only real elements when isolating', () => {
    const mgr = new ElementManager(fakeScene());
    mgr.loadElements(ELEMENTS, { skipPlaceholders: false });
    mgr.isolate(['w1']);
    expect(mgr.hiddenCount()).toBe(2);
  });

  it('reports the same number to subscribers', () => {
    const mgr = new ElementManager(fakeScene());
    mgr.loadElements(ELEMENTS, { skipPlaceholders: false });
    const seen: number[] = [];
    mgr.onHiddenCountChange((n) => seen.push(n));
    mgr.isolate(['d1']);
    expect(seen.at(-1)).toBe(2);
    mgr.showAll();
    expect(seen.at(-1)).toBe(0);
  });
});
