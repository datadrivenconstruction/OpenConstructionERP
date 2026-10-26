// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Device-side store for records written offline​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: diaries, diary entries, punch
 * items and inspections, plus the photos taken for them.
 *
 * Two jobs the mutation queue cannot do on its own:
 *   - keep, per record, the server copy the edit started from (`serverSnapshot`
 *     and `baseVersion`) so a version conflict can be merged three ways;
 *   - hold photo Blobs until their record exists on the server.
 *
 * Its own database (`oe_field_records`), never a store inside `oe_field_offline`:
 * see the note on `createIndexedDbQueueStorage` about `onupgradeneeded`.
 * Falls back to memory when IndexedDB is missing, like the queue storage.
 */

export type OfflineEntityKind = 'diary' | 'diary_entry' | 'punch' | 'inspection';

export interface LocalRecord<T = Record<string, unknown>> {
  /** Client id. For a record created offline this is the temporary id. */
  localId: string;
  kind: OfflineEntityKind;
  /** Server id once known; null while the create is still queued. */
  serverId: string | null;
  /** Server `version` the device last saw; null before the first sync. */
  baseVersion: number | null;
  /** Server copy at `baseVersion`: the common ancestor for a 3-way merge. */
  serverSnapshot: T | null;
  /** What the device shows: the snapshot plus local edits. */
  data: T;
  /** True while local edits have not reached the server. */
  dirty: boolean;
  projectId?: string | null;
  createdAt: number;
  updatedAt: number;
}

export interface PhotoBlobRecord {
  id: string;
  kind: OfflineEntityKind;
  /** The record the photo belongs to (its `localId`). */
  localId: string;
  name: string;
  type: string;
  blob: Blob;
  createdAt: number;
}

export interface OfflineStore {
  getRecord(kind: OfflineEntityKind, localId: string): Promise<LocalRecord | undefined>;
  putRecord(record: LocalRecord): Promise<void>;
  deleteRecord(kind: OfflineEntityKind, localId: string): Promise<void>;
  listRecords(kind?: OfflineEntityKind): Promise<LocalRecord[]>;
  findByServerId(kind: OfflineEntityKind, serverId: string): Promise<LocalRecord | undefined>;
  putPhoto(photo: PhotoBlobRecord): Promise<void>;
  getPhoto(id: string): Promise<PhotoBlobRecord | undefined>;
  listPhotosByRecord(kind: OfflineEntityKind, localId: string): Promise<PhotoBlobRecord[]>;
  deletePhoto(id: string): Promise<void>;
  clear(): Promise<void>;
}

const recKey = (kind: OfflineEntityKind, localId: string) => `${kind}:${localId}`;

/** Temporary id for a record created offline. Never collides with a server uuid. */
export function newLocalId(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  const rand =
    c && typeof c.randomUUID === 'function'
      ? c.randomUUID()
      : `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
  return `local-${rand}`;
}

export function isLocalId(id: string | null | undefined): boolean {
  return typeof id === 'string' && id.startsWith('local-');
}

/* ── memory ────────────────────────────────────────────────────────────── */

export function createMemoryOfflineStore(): OfflineStore {
  const records = new Map<string, LocalRecord>();
  const photos = new Map<string, PhotoBlobRecord>();
  return {
    getRecord: (kind, localId) => Promise.resolve(records.get(recKey(kind, localId))),
    putRecord: (r) => {
      records.set(recKey(r.kind, r.localId), r);
      return Promise.resolve();
    },
    deleteRecord: (kind, localId) => {
      records.delete(recKey(kind, localId));
      return Promise.resolve();
    },
    listRecords: (kind) =>
      Promise.resolve([...records.values()].filter((r) => !kind || r.kind === kind)),
    findByServerId: (kind, serverId) =>
      Promise.resolve([...records.values()].find((r) => r.kind === kind && r.serverId === serverId)),
    putPhoto: (p) => {
      photos.set(p.id, p);
      return Promise.resolve();
    },
    getPhoto: (id) => Promise.resolve(photos.get(id)),
    listPhotosByRecord: (kind, localId) =>
      Promise.resolve(
        [...photos.values()]
          .filter((p) => p.kind === kind && p.localId === localId)
          .sort((a, b) => a.createdAt - b.createdAt),
      ),
    deletePhoto: (id) => {
      photos.delete(id);
      return Promise.resolve();
    },
    clear: () => {
      records.clear();
      photos.clear();
      return Promise.resolve();
    },
  };
}

/* ── IndexedDB ─────────────────────────────────────────────────────────── */

const DB_NAME = 'oe_field_records';
const DB_VERSION = 1;
const RECORDS = 'records';
const PHOTOS = 'photos';

type StoredRecord = LocalRecord & { key: string };
type StoredPhoto = PhotoBlobRecord & { recKey: string };

function openDb(dbName: string): Promise<IDBDatabase> {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(dbName, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(RECORDS)) {
        const s = db.createObjectStore(RECORDS, { keyPath: 'key' });
        s.createIndex('kind', 'kind');
      }
      if (!db.objectStoreNames.contains(PHOTOS)) {
        const s = db.createObjectStore(PHOTOS, { keyPath: 'id' });
        s.createIndex('recKey', 'recKey');
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

export function createIndexedDbOfflineStore(dbName: string = DB_NAME): OfflineStore {
  let dbPromise: Promise<IDBDatabase> | null = null;
  const db = (): Promise<IDBDatabase> => {
    if (!dbPromise) dbPromise = openDb(dbName);
    return dbPromise;
  };

  // Reads degrade to empty and writes to a no-op, so a storage fault never
  // crashes a capture; the caller still holds the in-memory copy.
  async function read<T>(store: string, run: (s: IDBObjectStore) => IDBRequest, fallback: T): Promise<T> {
    try {
      const conn = await db();
      return await new Promise<T>((resolve) => {
        const req = run(conn.transaction(store, 'readonly').objectStore(store));
        req.onsuccess = () => resolve((req.result as T) ?? fallback);
        req.onerror = () => resolve(fallback);
      });
    } catch {
      return fallback;
    }
  }
  async function write(store: string, run: (s: IDBObjectStore) => void): Promise<void> {
    try {
      const conn = await db();
      await new Promise<void>((resolve) => {
        const tx = conn.transaction(store, 'readwrite');
        run(tx.objectStore(store));
        tx.oncomplete = () => resolve();
        tx.onerror = () => resolve();
        tx.onabort = () => resolve();
      });
    } catch {
      /* ignore */
    }
  }
  const strip = (r: StoredRecord | undefined): LocalRecord | undefined => {
    if (!r) return undefined;
    const { key: _key, ...rest } = r;
    void _key;
    return rest as LocalRecord;
  };
  const stripPhoto = (p: StoredPhoto | undefined): PhotoBlobRecord | undefined => {
    if (!p) return undefined;
    const { recKey: _rk, ...rest } = p;
    void _rk;
    return rest as PhotoBlobRecord;
  };

  return {
    async getRecord(kind, localId) {
      return strip(await read<StoredRecord | undefined>(RECORDS, (s) => s.get(recKey(kind, localId)), undefined));
    },
    putRecord: (r) => write(RECORDS, (s) => void s.put({ ...r, key: recKey(r.kind, r.localId) })),
    deleteRecord: (kind, localId) => write(RECORDS, (s) => void s.delete(recKey(kind, localId))),
    async listRecords(kind) {
      const all = await read<StoredRecord[]>(
        RECORDS,
        (s) => (kind ? s.index('kind').getAll(kind) : s.getAll()),
        [],
      );
      return all.map((r) => strip(r) as LocalRecord);
    },
    async findByServerId(kind, serverId) {
      const all = await this.listRecords(kind);
      return all.find((r) => r.serverId === serverId);
    },
    putPhoto: (p) => write(PHOTOS, (s) => void s.put({ ...p, recKey: recKey(p.kind, p.localId) })),
    async getPhoto(id) {
      return stripPhoto(await read<StoredPhoto | undefined>(PHOTOS, (s) => s.get(id), undefined));
    },
    async listPhotosByRecord(kind, localId) {
      const all = await read<StoredPhoto[]>(
        PHOTOS,
        (s) => s.index('recKey').getAll(recKey(kind, localId)),
        [],
      );
      return all.map((p) => stripPhoto(p) as PhotoBlobRecord).sort((a, b) => a.createdAt - b.createdAt);
    },
    deletePhoto: (id) => write(PHOTOS, (s) => void s.delete(id)),
    async clear() {
      await write(RECORDS, (s) => void s.clear());
      await write(PHOTOS, (s) => void s.clear());
    },
  };
}

export function pickOfflineStore(): OfflineStore {
  return typeof indexedDB !== 'undefined' ? createIndexedDbOfflineStore() : createMemoryOfflineStore();
}

let singleton: OfflineStore | null = null;

export function getOfflineStore(): OfflineStore {
  if (!singleton) singleton = pickOfflineStore();
  return singleton;
}

/** Test seam: install a store (or null to rebuild lazily). */
export function setOfflineStoreForTests(store: OfflineStore | null): void {
  singleton = store;
}
