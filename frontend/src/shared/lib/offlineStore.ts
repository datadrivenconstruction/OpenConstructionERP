/**
 * Offline data persistence using IndexedDB.
 * Provides caching for API responses and a queue for offline mutations.
 *
 * Uses the raw IndexedDB API (no dependencies) for maximum lightweight.
 */

const DB_NAME = 'oe_offline';
const DB_VERSION = 1;

// Store names
const CACHE_STORE = 'apiCache';
const MUTATION_QUEUE = 'mutationQueue';

/* ── Types ─────────────────────────────────────────────────────────── */

export interface CachedResponse {
  /** API path used as key */
  path: string;
  /** Cached response data */
  data: unknown;
  /** Timestamp of when this was cached */
  cachedAt: number;
  /** Cache expiry in ms (default 1 hour) */
  expiresAt: number;
}

export interface QueuedMutation {
  /** Auto-incremented id */
  id?: number;
  /** HTTP method */
  method: 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  /** API path */
  path: string;
  /** Request body */
  body?: unknown;
  /** Timestamp when queued */
  queuedAt: number;
  /** Number of retry attempts */
  retries: number;
}

/* ── DB initialization ─────────────────────────────────────────────── */

let dbPromise: Promise<IDBDatabase> | null = null;

function getDB(): Promise<IDBDatabase> {
  if (dbPromise) return dbPromise;

  dbPromise = new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);

    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(CACHE_STORE)) {
        db.createObjectStore(CACHE_STORE, { keyPath: 'path' });
      }
      if (!db.objectStoreNames.contains(MUTATION_QUEUE)) {
        db.createObjectStore(MUTATION_QUEUE, { keyPath: 'id', autoIncrement: true });
      }
    };

    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });

  return dbPromise;
}

/* ── Cache operations ──────────────────────────────────────────────── */

const DEFAULT_TTL = 60 * 60 * 1000; // 1 hour

/**
 * Cache an API response for offline use.
 */
export async function cacheResponse(path: string, data: unknown, ttl = DEFAULT_TTL): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(CACHE_STORE, 'readwrite');
    const store = tx.objectStore(CACHE_STORE);
    const entry: CachedResponse = {
      path,
      data,
      cachedAt: Date.now(),
      expiresAt: Date.now() + ttl,
    };
    store.put(entry);
    await new Promise<void>((resolve, reject) => {
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    // IndexedDB unavailable — silently fail
  }
}

/**
 * Retrieve a cached response. Returns null if not found or expired.
 */
export async function getCachedResponse<T>(path: string): Promise<T | null> {
  try {
    const db = await getDB();
    const tx = db.transaction(CACHE_STORE, 'readonly');
    const store = tx.objectStore(CACHE_STORE);
    const req = store.get(path);

    return new Promise<T | null>((resolve) => {
      req.onsuccess = () => {
        const entry = req.result as CachedResponse | undefined;
        if (!entry) {
          resolve(null);
          return;
        }
        if (Date.now() > entry.expiresAt) {
          // Expired — clean up
          const delTx = db.transaction(CACHE_STORE, 'readwrite');
          delTx.objectStore(CACHE_STORE).delete(path);
          resolve(null);
          return;
        }
        resolve(entry.data as T);
      };
      req.onerror = () => resolve(null);
    });
  } catch {
    return null;
  }
}

/**
 * Clear all cached responses.
 */
export async function clearCache(): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(CACHE_STORE, 'readwrite');
    tx.objectStore(CACHE_STORE).clear();
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/* ── Mutation queue operations ─────────────────────────────────────── */

/**
 * Queue a mutation for later execution when back online.
 */
export async function queueMutation(mutation: Omit<QueuedMutation, 'id'>): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    tx.objectStore(MUTATION_QUEUE).add(mutation);
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/**
 * Get all queued mutations.
 */
export async function getQueuedMutations(): Promise<QueuedMutation[]> {
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readonly');
    const store = tx.objectStore(MUTATION_QUEUE);
    const req = store.getAll();

    return new Promise<QueuedMutation[]>((resolve) => {
      req.onsuccess = () => resolve(req.result ?? []);
      req.onerror = () => resolve([]);
    });
  } catch {
    return [];
  }
}

/**
 * Remove a mutation from the queue after successful replay.
 */
export async function removeMutation(id: number): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    tx.objectStore(MUTATION_QUEUE).delete(id);
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}

/**
 * Clear the entire mutation queue.
 */
export async function clearMutationQueue(): Promise<void> {
  try {
    const db = await getDB();
    const tx = db.transaction(MUTATION_QUEUE, 'readwrite');
    tx.objectStore(MUTATION_QUEUE).clear();
    await new Promise<void>((resolve) => {
      tx.oncomplete = () => resolve();
    });
  } catch {
    // ignore
  }
}
