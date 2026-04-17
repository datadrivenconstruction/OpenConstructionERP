import { beforeEach, describe, expect, it } from 'vitest';
import {
  addViewpoint,
  getViewpoint,
  listViewpoints,
  removeViewpoint,
  __test__,
} from '../SavedViewsStore';

const MODEL = 'model-test';

function sampleInput(name: string) {
  return {
    name,
    cameraPos: [1, 2, 3] as [number, number, number],
    target: [4, 5, 6] as [number, number, number],
  };
}

describe('SavedViewsStore', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('stores viewpoints under the oe_bim_views_{modelId} key', () => {
    const { viewpoint } = addViewpoint(MODEL, sampleInput('first'));
    expect(localStorage.getItem(__test__.storageKey(MODEL))).toContain(viewpoint.id);
  });

  it('returns an empty list for models with no saved views', () => {
    expect(listViewpoints(MODEL)).toEqual([]);
  });

  it('add + list + get round-trips the viewpoint', () => {
    const { viewpoint } = addViewpoint(MODEL, sampleInput('A'));
    const list = listViewpoints(MODEL);
    expect(list).toHaveLength(1);
    expect(list[0]?.name).toBe('A');
    expect(getViewpoint(MODEL, viewpoint.id)?.name).toBe('A');
  });

  it('remove deletes only the targeted viewpoint', () => {
    const a = addViewpoint(MODEL, sampleInput('A')).viewpoint;
    const b = addViewpoint(MODEL, sampleInput('B')).viewpoint;
    expect(removeViewpoint(MODEL, a.id)).toBe(true);
    const remaining = listViewpoints(MODEL);
    expect(remaining).toHaveLength(1);
    expect(remaining[0]?.id).toBe(b.id);
    expect(getViewpoint(MODEL, a.id)).toBeNull();
  });

  it('quota caps at 100 per model and evicts the oldest', () => {
    const cap = __test__.MAX_VIEWS_PER_MODEL;
    for (let i = 0; i < cap; i++) {
      const result = addViewpoint(MODEL, sampleInput(`v${i}`));
      expect(result.quotaExceeded).toBe(false);
    }
    const first = listViewpoints(MODEL)[0]!;
    const overflow = addViewpoint(MODEL, sampleInput('overflow'));
    expect(overflow.quotaExceeded).toBe(true);
    const after = listViewpoints(MODEL);
    expect(after).toHaveLength(cap);
    // Oldest entry should be gone after overflow
    expect(after.some((v) => v.id === first.id)).toBe(false);
    expect(after[after.length - 1]!.name).toBe('overflow');
  });

  it('ignores corrupted localStorage payloads', () => {
    localStorage.setItem(__test__.storageKey(MODEL), 'not-json');
    expect(listViewpoints(MODEL)).toEqual([]);
  });

  it('namespaces entries per model', () => {
    addViewpoint('a', sampleInput('A-1'));
    addViewpoint('b', sampleInput('B-1'));
    expect(listViewpoints('a')).toHaveLength(1);
    expect(listViewpoints('b')).toHaveLength(1);
    expect(listViewpoints('a')[0]?.name).toBe('A-1');
  });
});
