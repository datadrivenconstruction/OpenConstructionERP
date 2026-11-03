// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The field-time offline queue: a day recorded with no signal, kept on the
 * device until there is signal again. It rides the shared record queue (same
 * IndexedDB, backoff, status pill and conflict handling as diaries, punch items
 * and inspections); `jwtSender` sends these ops because they carry no
 * `meta.entity`.
 *
 * Two ids, and keeping them apart is the whole design:
 *
 *  - `entry_key` names the logical entry, one foreman's record of one
 *    project-day. It is minted once, when the day is first written down, and
 *    every later edit and every replay of that day carries the same key. The
 *    server keys its idempotency ledger on it, so a replay returns the original
 *    timesheet instead of booking the hours twice.
 *  - `clientOpId` names one queued op. It is fresh for every enqueue, because
 *    `MutationQueue.enqueue` dedups on it and *keeps the first op's body*: reuse
 *    the entry key there and the foreman's second edit of the same day would be
 *    swallowed on the device and never sent at all.
 *
 * Days queued before the queues were merged sit in the old database
 * `oe_field_time_offline`. `migrateLegacyFieldTimeQueue` copies them over (same
 * op ids, same order) and drops the old database only after every op is in.
 */

import {
  MutationQueue,
  createIndexedDbQueueStorage,
  createMemoryQueueStorage,
  getRecordQueue,
  jwtOutcomeFromResponse,
  newClientOpId,
  type QueueStorage,
  type QueuedOp,
  type ReplayOutcome,
} from '@/shared/lib/offline';
import type { OfflineEntryPayload, OfflineWithdrawPayload } from './api';

/** The pre-merge database; read once by the migration, never written. */
export const FIELD_TIME_QUEUE_DB = 'oe_field_time_offline';
const LEGACY_STORE = 'fieldMutationQueue';

/** Queue op kinds, used to group and label pending work in the UI. */
export const OP_RECORD = 'field_time.entry';
export const OP_WITHDRAW = 'field_time.withdraw';

const RECORD_PATH = '/v1/field-time/timesheets/offline/';
const WITHDRAW_PATH = '/v1/field-time/timesheets/offline/withdraw/';

/** Mint the key that identifies one logical day across all of its replays. */
export function newEntryKey(): string {
  return newClientOpId();
}

/**
 * Read the entry key back out of a queued op, for the pending list.
 *
 * Returns an empty string for a body that is not shaped like one of ours,
 * rather than throwing: a corrupt row must not break the whole list.
 */
export function entryKeyOf(op: QueuedOp): string {
  const body = op.body as { entry_key?: unknown } | null | undefined;
  return body && typeof body.entry_key === 'string' ? body.entry_key : '';
}

/** Read the work date out of a queued op, for the pending list. */
export function workDateOf(op: QueuedOp): string {
  const body = op.body as { date?: unknown } | null | undefined;
  return body && typeof body.date === 'string' ? body.date : '';
}

/**
 * Map an HTTP response to a replay outcome (2xx applied, 401 held, 409
 * conflict, other 4xx rejected, 5xx retry). Shared with every plain queued write.
 */
export function outcomeFromResponse(res: Response): Promise<ReplayOutcome> {
  return jwtOutcomeFromResponse(res);
}

/** IndexedDB where it exists, memory where it does not. Same queue either way. */
export function pickFieldTimeStorage(): QueueStorage {
  if (typeof indexedDB !== 'undefined') {
    return createIndexedDbQueueStorage(FIELD_TIME_QUEUE_DB);
  }
  return createMemoryQueueStorage();
}

/**
 * Read every op of the pre-merge database, or null when it cannot be read.
 * Unlike the queue's own adapter this never turns a failed read into an empty
 * list: an empty queue gets its database deleted.
 */
function readLegacyOps(): Promise<QueuedOp[] | null> {
  return new Promise((resolve) => {
    if (typeof indexedDB === 'undefined') {
      resolve(null);
      return;
    }
    let created = false;
    const req = indexedDB.open(FIELD_TIME_QUEUE_DB);
    req.onupgradeneeded = () => {
      created = true; // it did not exist: nothing to migrate
    };
    req.onerror = () => resolve(null);
    req.onsuccess = () => {
      const db = req.result;
      if (created || !db.objectStoreNames.contains(LEGACY_STORE)) {
        db.close();
        if (created) indexedDB.deleteDatabase(FIELD_TIME_QUEUE_DB);
        resolve([]);
        return;
      }
      const all = db.transaction(LEGACY_STORE, 'readonly').objectStore(LEGACY_STORE).getAll();
      all.onsuccess = () => {
        db.close();
        resolve(all.result as QueuedOp[]);
      };
      all.onerror = () => {
        db.close();
        resolve(null);
      };
    };
  });
}

function dropLegacyDb(): Promise<void> {
  return new Promise((resolve) => {
    const req = indexedDB.deleteDatabase(FIELD_TIME_QUEUE_DB);
    req.onsuccess = () => resolve();
    req.onerror = () => resolve();
    req.onblocked = () => resolve();
  });
}

/**
 * Move days queued in the old database into `queue`. Idempotent: ops dedup on
 * their client op id, so a run interrupted half way simply finishes next time.
 * Returns how many ops were carried over.
 */
export async function migrateLegacyFieldTimeQueue(
  queue: MutationQueue,
  io: { read: () => Promise<QueuedOp[] | null>; drop: () => Promise<void> } = {
    read: readLegacyOps,
    drop: dropLegacyDb,
  },
): Promise<number> {
  const ops = await io.read();
  if (ops === null) return 0;
  const ordered = [...ops].sort((a, b) => a.seq - b.seq);
  for (const op of ordered) {
    await queue.enqueue({
      clientOpId: op.clientOpId,
      method: op.method,
      path: op.path,
      body: op.body,
      kind: op.kind,
      ...(op.meta ? { meta: op.meta } : {}),
    });
  }
  if (ops.length > 0) await io.drop();
  return ordered.length;
}

let override: MutationQueue | null = null;
let migration: Promise<number> | null = null;

/** The shared record queue; the first call also starts the legacy migration. */
export function getFieldTimeQueue(): MutationQueue {
  if (override) return override;
  const queue = getRecordQueue();
  if (!migration) migration = migrateLegacyFieldTimeQueue(queue).catch(() => 0);
  return queue;
}

/** Resolves once days left in the old database are in the shared queue. */
export async function fieldTimeQueueReady(): Promise<void> {
  getFieldTimeQueue();
  if (migration) await migration;
}

/** Test seam: replace the queue (null restores the shared one). */
export function resetFieldTimeQueueForTests(queue: MutationQueue | null = null): void {
  override = queue;
  migration = null;
}

/** Queue one day for replay. A fresh op id every time, so an edit is never lost. */
export async function enqueueEntry(payload: OfflineEntryPayload): Promise<void> {
  await fieldTimeQueueReady();
  await getFieldTimeQueue().enqueue({
    clientOpId: newClientOpId(),
    method: 'POST',
    path: RECORD_PATH,
    body: payload,
    kind: OP_RECORD,
  });
}

/** Queue a withdrawal for replay. */
export async function enqueueWithdraw(payload: OfflineWithdrawPayload): Promise<void> {
  await fieldTimeQueueReady();
  await getFieldTimeQueue().enqueue({
    clientOpId: newClientOpId(),
    method: 'POST',
    path: WITHDRAW_PATH,
    body: payload,
    kind: OP_WITHDRAW,
  });
}
