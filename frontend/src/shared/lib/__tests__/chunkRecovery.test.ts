import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { isChunkLoadError, recoverFromStaleChunk } from '../chunkRecovery';

describe('chunkRecovery', () => {
  const reload = vi.fn();
  const unregister = vi.fn().mockResolvedValue(true);
  const del = vi.fn().mockResolvedValue(true);

  beforeEach(() => {
    sessionStorage.clear();
    reload.mockClear();
    unregister.mockClear();
    del.mockClear();
    vi.stubGlobal('location', { ...window.location, reload });
    Object.defineProperty(navigator, 'serviceWorker', {
      configurable: true,
      value: { getRegistrations: () => Promise.resolve([{ unregister }]) },
    });
    vi.stubGlobal('caches', { keys: () => Promise.resolve(['precache']), delete: del });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('recognises the stale chunk messages', () => {
    expect(isChunkLoadError('Failed to fetch dynamically imported module: /assets/ProgressPage-ab12.js')).toBe(true);
    expect(isChunkLoadError('Importing a module script failed.')).toBe(true);
    expect(isChunkLoadError('Loading chunk 12 failed')).toBe(true);
    expect(isChunkLoadError('Cannot read properties of undefined')).toBe(false);
  });

  it('drops worker and caches, then reloads once', async () => {
    expect(recoverFromStaleChunk(1_000_000)).toBe(true);
    await vi.waitFor(() => expect(reload).toHaveBeenCalledTimes(1));
    expect(unregister).toHaveBeenCalled();
    expect(del).toHaveBeenCalledWith('precache');
  });

  it('does not loop inside the guard window but allows a later one', () => {
    expect(recoverFromStaleChunk(1_000_000)).toBe(true);
    expect(recoverFromStaleChunk(1_005_000)).toBe(false);
    expect(recoverFromStaleChunk(1_011_000)).toBe(true);
  });

  it('stays quiet when storage throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    expect(recoverFromStaleChunk()).toBe(false);
    vi.restoreAllMocks();
  });
});
