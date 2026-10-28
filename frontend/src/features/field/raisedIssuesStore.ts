// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Durable store for issues raised from the field shell.
 *
 * Why a second store rather than the mutation queue: the offline mutation queue
 * (`shared/lib/offline`) is JSON-only - its sender serialises every op body as
 * `application/json` - so it cannot carry a photo, and it has no way to feed the
 * server-assigned punch id of one op into a later op. A field defect therefore
 * splits in two:
 *
 *   1. the punch CREATE goes through the queue (idempotent on `client_op_id`,
 *      replayed with the field-session headers), and
 *   2. the PHOTO is parked here as a durable record keyed by that same
 *      `client_op_id`, then uploaded on the next online sync once the created
 *      punch id is known (from the drain result or the server sync ledger).
 *
 * Keeping the raised-issue log here also lets the tab show recently-raised
 * issues - including ones that already synced - across a reload, which a
 * queue-only view cannot: the queue drops an op the moment it drains.
 *
 * Storage mirrors the mutation queue's approach: IndexedDB in the browser (it
 * stores a `Blob`/`File` natively via structured clone), with an in-memory
 * fallback so private mode, SSR and tests never crash. Every method degrades to
 * a no-op / empty result on a storage error rather than throwing into a capture.
 */

import type { PunchPriority } from '../punchlist/api';

/** One issue raised from the field shell, plus its optional pending photo. */
export interface RaisedIssueRecord {
  /** The create op's `client_op_id` - the join key to the queue + the photo. */
  clientOpId: string;
  title: string;
  priority: PunchPriority;
  /** Epoch ms when the issue was raised on the device. */
  createdAt: number;
  /** Whether a photo was attached when the issue was raised. */
  hasPhoto: boolean;
  /** True while the photo blob still needs uploading to the created punch. */
  photoPending: boolean;
  /** The photo bytes, kept only while `photoPending`; cleared after upload. */
  photo?: Blob;
  photoName?: string;
  /** The server punch id, filled once the create has synced and resolved. */
  punchId?: string;
}

const DB_NAME = 'oe_field_raise_issue';
const DB_VERSION = 1;
const STORE = 'raisedIssues';

// In-memory fallback: backs tests / SSR and any realm without IndexedDB. The
// public API is identical either way.
const memory = new Map<string, RaisedIssueRecord>();
const hasIdb = (): boolean => typeof indexedDB !== 'undefined';

let dbPromise: Promise<IDBDatabase> | null = null;

function openDb(): Promise<IDBDatabase> {
  return new Promise<IDBDatabase>((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = () => {
      const db = req.result;
      if (!db.objectStoreNames.contains(STORE)) {
        db.createObjectStore(STORE, { keyPath: 'clientOpId' });
      }
    };
    req.onsuccess = () => resolve(req.result);
    req.onerror = () => reject(req.error);
  });
}

function db(): Promise<IDBDatabase> {
  if (!dbPromise) dbPromise = openDb();
  return dbPromise;
}

async function readAll(): Promise<RaisedIssueRecord[]> {
  if (!hasIdb()) return [...memory.values()];
  try {
    const conn = await db();
    return await new Promise<RaisedIssueRecord[]>((resolve) => {
      const tx = conn.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).getAll();
      req.onsuccess = () => resolve((req.result as RaisedIssueRecord[]) ?? []);
      req.onerror = () => resolve([]);
    });
  } catch {
    return [...memory.values()];
  }
}

async function write(rec: RaisedIssueRecord): Promise<void> {
  memory.set(rec.clientOpId, rec);
  if (!hasIdb()) return;
  try {
    const conn = await db();
    await new Promise<void>((resolve, reject) => {
      const tx = conn.transaction(STORE, 'readwrite');
      tx.objectStore(STORE).put(rec);
      tx.oncomplete = () => resolve();
      tx.onerror = () => reject(tx.error);
    });
  } catch {
    /* storage unavailable - the in-memory copy above keeps the tab working */
  }
}

async function readOne(clientOpId: string): Promise<RaisedIssueRecord | undefined> {
  if (!hasIdb()) return memory.get(clientOpId);
  try {
    const conn = await db();
    return await new Promise<RaisedIssueRecord | undefined>((resolve) => {
      const tx = conn.transaction(STORE, 'readonly');
      const req = tx.objectStore(STORE).get(clientOpId);
      req.onsuccess = () => resolve((req.result as RaisedIssueRecord | undefined) ?? undefined);
      req.onerror = () => resolve(undefined);
    });
  } catch {
    return memory.get(clientOpId);
  }
}

/** Persist a freshly-raised issue (with its photo blob, if any). */
export async function saveRaisedIssue(rec: RaisedIssueRecord): Promise<void> {
  await write(rec);
}

/** All raised issues, newest first (drives the "recently raised" list). */
export async function listRaisedIssues(): Promise<RaisedIssueRecord[]> {
  const all = await readAll();
  return all.sort((a, b) => b.createdAt - a.createdAt);
}

/** Records still holding a photo blob that has not yet been uploaded. */
export async function pendingPhotoRecords(): Promise<RaisedIssueRecord[]> {
  const all = await readAll();
  return all.filter((r) => r.photoPending && r.photo instanceof Blob);
}

/**
 * Mark a record's photo as uploaded: clear the (now redundant) blob and pin the
 * resolved punch id. Idempotent - a missing record is a no-op.
 */
export async function markPhotoUploaded(clientOpId: string, punchId: string): Promise<void> {
  const rec = await readOne(clientOpId);
  if (!rec) return;
  const next: RaisedIssueRecord = { ...rec, photoPending: false, punchId };
  // Drop the now-redundant blob so a synced issue does not keep its bytes.
  delete next.photo;
  await write(next);
}
