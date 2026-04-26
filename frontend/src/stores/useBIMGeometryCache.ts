/**
 * useBIMGeometryCache — in-memory LRU cache of geometry blobs keyed by modelId.
 *
 * Purpose: navigating away from /bim/{id} and back used to re-download the
 * geometry from scratch every time, even though the underlying file hadn't
 * changed (RFC 19 §UX-1). This store keeps a small LRU of recently-loaded
 * geometry blobs in memory so the second mount can parse them locally and
 * skip the network round-trip + progress bar entirely.
 *
 * Storage: in-memory only — geometry blobs routinely run 50–150 MB and
 * localStorage's 5–10 MB quota would never hold them. The cache is lost
 * on page reload, which is fine: a hard refresh is a strong signal that
 * the user wants a fresh fetch.
 *
 * Eviction: capped at MAX_ENTRIES models *and* MAX_TOTAL_BYTES total. When
 * either ceiling is exceeded the oldest entry by `cachedAt` is evicted
 * until both invariants hold again.
 */
import { create } from 'zustand';

const MAX_ENTRIES = 4;
const MAX_TOTAL_BYTES = 200 * 1024 * 1024; // ~200 MB

export type GeometryFormat = 'glb' | 'dae';

export interface GeometryCacheEntry {
  buffer: ArrayBuffer;
  format: GeometryFormat;
  cachedAt: number;
  /** The original URL the blob was fetched from. Used as a sanity check
   *  (different URLs for the same modelId mean the geometry was re-uploaded
   *  and the cache entry is stale). */
  url: string;
}

interface BIMGeometryCacheState {
  entries: Map<string, GeometryCacheEntry>;
  get: (modelId: string, url: string) => GeometryCacheEntry | null;
  put: (modelId: string, entry: GeometryCacheEntry) => void;
  clear: () => void;
  /** Test helper: total bytes currently held. */
  totalBytes: () => number;
}

function evict(entries: Map<string, GeometryCacheEntry>): void {
  let total = 0;
  for (const e of entries.values()) total += e.buffer.byteLength;

  while (entries.size > MAX_ENTRIES || total > MAX_TOTAL_BYTES) {
    let oldestKey: string | null = null;
    let oldestAt = Infinity;
    for (const [k, v] of entries) {
      if (v.cachedAt < oldestAt) {
        oldestAt = v.cachedAt;
        oldestKey = k;
      }
    }
    if (!oldestKey) break;
    const evicted = entries.get(oldestKey);
    if (evicted) total -= evicted.buffer.byteLength;
    entries.delete(oldestKey);
  }
}

export const useBIMGeometryCache = create<BIMGeometryCacheState>((set, get) => ({
  entries: new Map(),

  get: (modelId, url) => {
    const e = get().entries.get(modelId);
    if (!e) return null;
    // URL changed under us — drop the stale entry so the caller refetches.
    if (e.url !== url) {
      const next = new Map(get().entries);
      next.delete(modelId);
      set({ entries: next });
      return null;
    }
    return e;
  },

  put: (modelId, entry) => {
    const next = new Map(get().entries);
    next.set(modelId, entry);
    evict(next);
    set({ entries: next });
  },

  clear: () => set({ entries: new Map() }),

  totalBytes: () => {
    let total = 0;
    for (const e of get().entries.values()) total += e.buffer.byteLength;
    return total;
  },
}));

export const __test__ = {
  MAX_ENTRIES,
  MAX_TOTAL_BYTES,
};
