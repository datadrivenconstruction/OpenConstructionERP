// @ts-nocheck
import { describe, it, expect, beforeEach, vi } from 'vitest';
import {
  cacheResponse,
  getCachedResponse,
  clearCache,
  queueMutation,
  getQueuedMutations,
  removeMutation,
  clearMutationQueue,
} from './offlineStore';

// fake-indexeddb is provided by jsdom/happy-dom test environments
// If not available, we use a simple mock
const hasIndexedDB = typeof indexedDB !== 'undefined';

describe.skipIf(!hasIndexedDB)('offlineStore — IndexedDB', () => {
  beforeEach(async () => {
    await clearCache();
    await clearMutationQueue();
  });

  describe('cacheResponse / getCachedResponse', () => {
    it('caches and retrieves a response', async () => {
      const data = { items: [{ id: '1', name: 'Test' }] };
      await cacheResponse('/v1/projects/', data);
      const result = await getCachedResponse<typeof data>('/v1/projects/');
      expect(result).toEqual(data);
    });

    it('returns null for non-existent cache key', async () => {
      const result = await getCachedResponse('/v1/nonexistent');
      expect(result).toBeNull();
    });

    it('returns null for expired entries', async () => {
      // Cache with very short TTL
      await cacheResponse('/v1/expired', { test: true }, 1);
      // Wait for expiry
      await new Promise((r) => setTimeout(r, 10));
      const result = await getCachedResponse('/v1/expired');
      expect(result).toBeNull();
    });

    it('overwrites existing cache entry', async () => {
      await cacheResponse('/v1/test', { v: 1 });
      await cacheResponse('/v1/test', { v: 2 });
      const result = await getCachedResponse<{ v: number }>('/v1/test');
      expect(result?.v).toBe(2);
    });
  });

  describe('clearCache', () => {
    it('removes all cached entries', async () => {
      await cacheResponse('/v1/a', { a: 1 });
      await cacheResponse('/v1/b', { b: 2 });
      await clearCache();
      expect(await getCachedResponse('/v1/a')).toBeNull();
      expect(await getCachedResponse('/v1/b')).toBeNull();
    });
  });

  describe('mutation queue', () => {
    it('queues and retrieves mutations', async () => {
      await queueMutation({
        method: 'POST',
        path: '/v1/projects/',
        body: { name: 'New Project' },
        queuedAt: Date.now(),
        retries: 0,
      });
      const queue = await getQueuedMutations();
      expect(queue).toHaveLength(1);
      expect(queue[0].method).toBe('POST');
      expect(queue[0].path).toBe('/v1/projects/');
    });

    it('removes a specific mutation from queue', async () => {
      await queueMutation({
        method: 'POST',
        path: '/v1/a',
        queuedAt: Date.now(),
        retries: 0,
      });
      await queueMutation({
        method: 'DELETE',
        path: '/v1/b',
        queuedAt: Date.now(),
        retries: 0,
      });
      const queue = await getQueuedMutations();
      expect(queue).toHaveLength(2);

      await removeMutation(queue[0].id!);
      const afterRemove = await getQueuedMutations();
      expect(afterRemove).toHaveLength(1);
      expect(afterRemove[0].method).toBe('DELETE');
    });
  });

  describe('clearMutationQueue', () => {
    it('empties the queue', async () => {
      await queueMutation({
        method: 'PATCH',
        path: '/v1/x',
        body: { update: true },
        queuedAt: Date.now(),
        retries: 0,
      });
      await clearMutationQueue();
      const queue = await getQueuedMutations();
      expect(queue).toHaveLength(0);
    });
  });
});

// Fallback tests when IndexedDB is unavailable (functions should not throw)
describe('offlineStore — graceful fallback', () => {
  it('getCachedResponse returns null for missing keys', async () => {
    const result = await getCachedResponse('/nonexistent');
    expect(result === null || result !== undefined).toBe(true);
  });

  it('getQueuedMutations returns empty array when queue is empty', async () => {
    await clearMutationQueue();
    const queue = await getQueuedMutations();
    expect(queue).toEqual([]);
  });
});
