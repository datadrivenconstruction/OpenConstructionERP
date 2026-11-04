// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * Read-only reference data kept on the device so the lists a site manager opens
 * first (open punch items, today's checklists, the crew) are not blank offline.
 *
 * One record per project and kind, stamped with the SERVER time of the fetch.
 * Age is judged against a server-derived "now" (device clock plus the offset
 * seen at fetch), so a phone with a wrong clock does not show stale data as
 * fresh. A record past its TTL is still returned, flagged stale: old data on a
 * site beats an empty screen, as long as the person is told.
 *
 * Own IndexedDB database. A new object store inside the queue database would
 * never be created on a browser that already holds it at version 1.
 */

export type RefKind = 'punch_items' | 'inspections' | 'roster';

export const REF_DB = 'oe_ref_cache';
export const REF_TTL_MS = 7 * 86_400_000;

export interface RefRecord<T = unknown> {
  key: string;
  projectId: string;
  kind: RefKind;
  /** Server clock at fetch, epoch ms. */
  fetchedAt: number;
  /** Device clock minus server clock at fetch, ms: lets age ignore a wrong phone clock. */
  clockOffset: number;
  payload: T;
}

export interface RefRead<T> {
  payload: T;
  fetchedAt: number;
  ageMs: number;
  stale: boolean;
}

const keyOf = (projectId: string, kind: RefKind) => `${projectId}:${kind}`;

interface RefStorage {
  get(key: string): Promise<RefRecord | undefined>;
  put(rec: RefRecord): Promise<void>;
  clearProject(projectId: string): Promise<void>;
  clearAll(): Promise<void>;
}

function memoryStorage(): RefStorage {
  const map = new Map<string, RefRecord>();
  return {
    get: async (k) => map.get(k),
    put: async (r) => {
      map.set(r.key, r);
    },
    clearAll: async () => {
      map.clear();
    },
    clearProject: async (p) => {
      for (const k of [...map.keys()]) if (k.startsWith(`${p}:`)) map.delete(k);
    },
  };
}

function idbStorage(): RefStorage {
  let dbp: Promise<IDBDatabase> | null = null;
  const open = () => {
    if (!dbp) {
      dbp = new Promise((resolve, reject) => {
        const req = indexedDB.open(REF_DB, 1);
        req.onupgradeneeded = () => req.result.createObjectStore('refs', { keyPath: 'key' });
        req.onsuccess = () => resolve(req.result);
        req.onerror = () => reject(req.error);
      });
    }
    return dbp;
  };
  const run = async <R>(mode: IDBTransactionMode, fn: (s: IDBObjectStore) => IDBRequest<R> | void): Promise<R | undefined> => {
    const db = await open();
    return new Promise((resolve, reject) => {
      const tx = db.transaction('refs', mode);
      const req = fn(tx.objectStore('refs'));
      tx.oncomplete = () => resolve(req ? (req.result as R) : undefined);
      tx.onerror = () => reject(tx.error);
      tx.onabort = () => reject(tx.error);
    });
  };
  return {
    get: async (k) => (await run<RefRecord | undefined>('readonly', (s) => s.get(k))) ?? undefined,
    put: async (r) => {
      await run('readwrite', (s) => s.put(r));
    },
    clearAll: async () => {
      await run('readwrite', (s) => s.clear());
    },
    clearProject: async (p) => {
      const db = await open();
      await new Promise<void>((resolve, reject) => {
        const tx = db.transaction('refs', 'readwrite');
        const store = tx.objectStore('refs');
        const cursor = store.openCursor();
        cursor.onsuccess = () => {
          const c = cursor.result;
          if (!c) return;
          if (String((c.value as RefRecord).key).startsWith(`${p}:`)) c.delete();
          c.continue();
        };
        tx.oncomplete = () => resolve();
        tx.onerror = () => reject(tx.error);
      });
    },
  };
}

let storage: RefStorage | null = null;
function getStorage(): RefStorage {
  if (!storage) storage = typeof indexedDB !== 'undefined' ? idbStorage() : memoryStorage();
  return storage;
}

/** Test seam. */
export function resetRefCacheForTests(): void {
  storage = memoryStorage();
}

/** Parse the server's ISO `server_time`; falls back to the device clock when unreadable. */
export function serverNowMs(serverTime: string | null | undefined, deviceNow: number): number {
  const t = serverTime ? Date.parse(serverTime) : NaN;
  return Number.isFinite(t) ? t : deviceNow;
}

/** Store one list for a project, stamped with the server time it was read at. */
export async function putRef<T>(
  projectId: string,
  kind: RefKind,
  payload: T,
  serverTime: string | null | undefined,
  deviceNow: number = Date.now(),
): Promise<void> {
  const fetchedAt = serverNowMs(serverTime, deviceNow);
  try {
    await getStorage().put({
      key: keyOf(projectId, kind),
      projectId,
      kind,
      fetchedAt,
      clockOffset: deviceNow - fetchedAt,
      payload,
    });
  } catch {
    /* storage refused (private mode, quota): the list simply is not available offline */
  }
}

/** Read a stored list with its age. Null when nothing is stored for that project and kind. */
export async function getRef<T>(
  projectId: string,
  kind: RefKind,
  deviceNow: number = Date.now(),
  ttlMs: number = REF_TTL_MS,
): Promise<RefRead<T> | null> {
  try {
    const rec = await getStorage().get(keyOf(projectId, kind));
    if (!rec) return null;
    // Device clock now, shifted by the offset seen at fetch, is server time now.
    const ageMs = Math.max(0, deviceNow - rec.clockOffset - rec.fetchedAt);
    return { payload: rec.payload as T, fetchedAt: rec.fetchedAt, ageMs, stale: ageMs > ttlMs };
  } catch {
    return null;
  }
}

/** Forget everything stored for a project (sign-out, project switch). */
export async function clearProjectRefs(projectId: string): Promise<void> {
  try {
    await getStorage().clearProject(projectId);
  } catch {
    /* nothing to clear */
  }
}

/** Forget every stored list (sign-out, user switch on a shared device). */
export async function clearAllRefs(): Promise<void> {
  try {
    await getStorage().clearAll();
  } catch {
    /* nothing to clear */
  }
}
