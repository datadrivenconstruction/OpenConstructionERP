// The ids "Show in 3D" hands to the viewer are the element ids the viewer isolates by (BIMElementData.id).
import { beforeEach, describe, expect, it, vi } from 'vitest';
import * as THREE from 'three';

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', async (orig) => ({ ...(await orig<object>()), apiGet: (...a: unknown[]) => apiGet(...a) }));

import { fetchBIMUnlinkedElementIds } from '../api';
import { ElementManager, type BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';
import type { SceneManager } from '@/shared/ui/BIMViewer/SceneManager';

const box = { min_x: 0, min_y: 0, min_z: 0, max_x: 1, max_y: 1, max_z: 1 };
const el = (id: string, name: string): BIMElementData => ({
  id,
  name,
  element_type: 'Walls',
  discipline: 'architectural',
  bounding_box: box,
});

describe('unlinked elements to the viewer', () => {
  beforeEach(() => apiGet.mockReset());

  it('isolates exactly the elements the endpoint returns, keyed by the element id', async () => {
    // Element ids as the elements endpoint returns them (UUID id; stable_id is a different field).
    const a = '11111111-1111-4111-8111-111111111111';
    const b = '22222222-2222-4222-8222-222222222222';
    const c = '33333333-3333-4333-8333-333333333333';
    apiGet.mockResolvedValue({ model_id: 'm1', element_ids: [b, c] });

    const ids = await fetchBIMUnlinkedElementIds('m1');
    expect(apiGet).toHaveBeenCalledWith('/v1/bim_hub/models/m1/unlinked-elements/');
    expect(ids).toEqual([b, c]);

    const mgr = new ElementManager({
      scene: new THREE.Scene(),
      requestRender: vi.fn(),
      zoomToFit: vi.fn(),
    } as unknown as SceneManager);
    mgr.loadElements([el(a, 'linked'), el(b, 'open 1'), el(c, 'open 2')], { skipPlaceholders: false });
    mgr.isolate(ids);
    expect(mgr.getMesh(a)!.visible).toBe(false);
    expect(mgr.getMesh(b)!.visible).toBe(true);
    expect(mgr.getMesh(c)!.visible).toBe(true);
  });
});
