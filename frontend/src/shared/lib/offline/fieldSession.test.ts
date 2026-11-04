import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { FIELD_CLEAR_MESSAGE, purgeFieldUserData } from './fieldSession';
import { getRef, putRef, resetRefCacheForTests } from './refCache';

describe('purgeFieldUserData', () => {
  beforeEach(() => resetRefCacheForTests());
  afterEach(() => vi.unstubAllGlobals());

  it('deletes field data caches, tells the worker and empties the ref store', async () => {
    const del = vi.fn().mockResolvedValue(true);
    vi.stubGlobal('caches', {
      keys: vi.fn().mockResolvedValue(['oe-field-data-v1', 'oe-field-shell-v1', 'other']),
      delete: del,
    });
    const post = vi.fn();
    vi.stubGlobal('navigator', {
      serviceWorker: { getRegistrations: vi.fn().mockResolvedValue([{ active: { postMessage: post } }]) },
    });
    await putRef('p1', 'punch_items', [1], null, 1);

    await purgeFieldUserData();

    expect(del).toHaveBeenCalledTimes(1);
    expect(del).toHaveBeenCalledWith('oe-field-data-v1');
    expect(post).toHaveBeenCalledWith({ type: FIELD_CLEAR_MESSAGE });
    expect(await getRef('p1', 'punch_items', 1)).toBeNull();
  });

  it('never throws without caches or a worker', async () => {
    vi.stubGlobal('navigator', {});
    await expect(purgeFieldUserData()).resolves.toBeUndefined();
  });
});
