/**
 * Unit tests for the BIM geometry-cache LRU. Confirms entry/eviction
 * invariants so the cache stays small in practice.
 */
import { beforeEach, describe, expect, it } from 'vitest';
import { useBIMGeometryCache, __test__ } from './useBIMGeometryCache';

const makeBuffer = (size: number): ArrayBuffer => new ArrayBuffer(size);

describe('useBIMGeometryCache', () => {
  beforeEach(() => {
    useBIMGeometryCache.getState().clear();
  });

  it('returns null on miss', () => {
    expect(useBIMGeometryCache.getState().get('m1', '/g/m1')).toBeNull();
  });

  it('round-trips buffer + format on hit', () => {
    const buf = makeBuffer(1024);
    useBIMGeometryCache.getState().put('m1', {
      buffer: buf,
      format: 'glb',
      url: '/g/m1',
      cachedAt: 1,
    });
    const hit = useBIMGeometryCache.getState().get('m1', '/g/m1');
    expect(hit).not.toBeNull();
    expect(hit!.buffer.byteLength).toBe(1024);
    expect(hit!.format).toBe('glb');
  });

  it('drops the entry when the URL diverges (re-uploaded model)', () => {
    useBIMGeometryCache.getState().put('m1', {
      buffer: makeBuffer(16),
      format: 'glb',
      url: '/g/m1?v=1',
      cachedAt: 1,
    });
    expect(useBIMGeometryCache.getState().get('m1', '/g/m1?v=2')).toBeNull();
    // And the entry is evicted, so a re-lookup with the original URL also misses.
    expect(useBIMGeometryCache.getState().get('m1', '/g/m1?v=1')).toBeNull();
  });

  it('evicts the oldest entry beyond MAX_ENTRIES', () => {
    for (let i = 0; i < __test__.MAX_ENTRIES + 1; i++) {
      useBIMGeometryCache.getState().put(`m${i}`, {
        buffer: makeBuffer(8),
        format: 'glb',
        url: `/g/m${i}`,
        cachedAt: i,
      });
    }
    // m0 is the oldest — it should be gone.
    expect(useBIMGeometryCache.getState().get('m0', '/g/m0')).toBeNull();
    // The most recent must still be there.
    const last = __test__.MAX_ENTRIES;
    expect(
      useBIMGeometryCache.getState().get(`m${last}`, `/g/m${last}`),
    ).not.toBeNull();
  });

  it('evicts when total bytes exceed MAX_TOTAL_BYTES', () => {
    // Three entries of 90MB each = 270MB > 200MB cap. The oldest must drop.
    const ninetyMB = 90 * 1024 * 1024;
    useBIMGeometryCache.getState().put('a', {
      buffer: makeBuffer(ninetyMB),
      format: 'glb',
      url: '/g/a',
      cachedAt: 1,
    });
    useBIMGeometryCache.getState().put('b', {
      buffer: makeBuffer(ninetyMB),
      format: 'glb',
      url: '/g/b',
      cachedAt: 2,
    });
    useBIMGeometryCache.getState().put('c', {
      buffer: makeBuffer(ninetyMB),
      format: 'glb',
      url: '/g/c',
      cachedAt: 3,
    });
    expect(useBIMGeometryCache.getState().get('a', '/g/a')).toBeNull();
    expect(useBIMGeometryCache.getState().totalBytes()).toBeLessThanOrEqual(
      __test__.MAX_TOTAL_BYTES,
    );
  });
});
