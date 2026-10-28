// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
/**
 * Persistent IndexedDB cache for geometry tiles.
 *
 * Tiles are content-addressed (the URL is the sha256 of the bytes), so they
 * are immutable and safe to cache forever. This is the persistence the
 * monolithic GLB path can never have (it is served no-store because its node
 * names can be re-patched): a revisit - or a job-site tablet that went
 * offline - reads tiles straight from disk instead of re-downloading the
 * whole model.
 *
 * Every operation degrades gracefully: if IndexedDB is unavailable (private
 * mode, SSR, a quota error), reads return null and writes are no-ops, so the
 * streaming loader simply falls back to the network.
 */

const DB_NAME = 'oce-bim-tiles';
const STORE = 'tiles';
// Bump alongside a backend TILER_VERSION change. Tiles are addressed by the
// hash of their bytes, so a re-bake gives every tile a new address and the
// blobs already on the device become unreachable: no manifest will ever name
// them again, and nothing else evicts them. A device that had saved a large
// model for offline use would carry that dead weight forever. Opening at a
// higher version clears the store once, which is always safe because tiles are
// pure cache and re-downloadable.
const DB_VERSION = 2;

let dbPromise: Promise<IDBDatabase | null> | null = null;

function openDb(): Promise<IDBDatabase | null> {
  if (dbPromise) return dbPromise;
  dbPromise = new Promise<IDBDatabase | null>((resolve) => {
    try {
      if (typeof indexedDB === 'undefined') {
        resolve(null);
        return;
      }
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains(STORE)) {
          db.createObjectStore(STORE);
          return;
        }
        // Existing cache from an older tiler: drop the now-unreachable blobs.
        // Guarded because the upgrade transaction is absent in some fakes.
        try {
          req.transaction?.objectStore(STORE).clear();
        } catch {
          // A failed purge only costs disk space; never block opening the cache.
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => resolve(null);
      req.onblocked = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
  return dbPromise;
}

/** Cache key for one tile: model-scoped so per-model eviction is possible. */
export function tileCacheKey(modelId: string, hash: string): string {
  return `${modelId}:${hash}`;
}

/** Return a cached tile's bytes, or null on a miss / any error. */
export async function getCachedTile(key: string): Promise<ArrayBuffer | null> {
  const db = await openDb();
  if (!db) return null;
  return new Promise<ArrayBuffer | null>((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(key);
      req.onsuccess = () => {
        const val = req.result;
        resolve(val instanceof ArrayBuffer ? val : null);
      };
      req.onerror = () => resolve(null);
    } catch {
      resolve(null);
    }
  });
}

/** Store a tile's bytes. Fire-and-forget: failures are swallowed. */
export async function putCachedTile(key: string, buffer: ArrayBuffer): Promise<void> {
  const db = await openDb();
  if (!db) return;
  return new Promise<void>((resolve) => {
    try {
      const tx = db.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(buffer, key);
      tx.oncomplete = () => resolve();
      tx.onerror = () => resolve();
      tx.onabort = () => resolve();
    } catch {
      resolve();
    }
  });
}
