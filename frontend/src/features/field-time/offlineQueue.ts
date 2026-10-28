// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The field-time offline queue — a day recorded with no signal, kept on the
 * device until there is signal again.
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
 * The queue is transport-agnostic, so this file supplies the piece it cannot
 * know: a sender that carries the desktop JWT. The field PWA's sender
 * (`shared/lib/offline/fieldQueue`) carries a field session token instead and
 * therefore cannot drain these ops, which is why field time has its own queue
 * rather than borrowing that one.
 *
 * Storage is a database of its own, `oe_field_time_offline`. A second object
 * store inside the field PWA's database would never be created on a browser
 * that had already opened it at version 1, and the storage adapter swallows the
 * resulting error — the queue would accept every entry and lose every one.
 */

import {
  MutationQueue,
  createIndexedDbQueueStorage,
  createMemoryQueueStorage,
  newClientOpId,
  type OpSender,
  type QueueStorage,
  type QueuedOp,
  type ReplayOutcome,
} from '@/shared/lib/offline';
import { getAuthToken, API_BASE } from '@/shared/lib/api';
import type { OfflineEntryPayload, OfflineEntryResult, OfflineWithdrawPayload } from './api';

/** Its own IndexedDB database, never a new store in the field PWA's. */
export const FIELD_TIME_QUEUE_DB = 'oe_field_time_offline';

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

async function safeDetail(res: Response): Promise<string | undefined> {
  try {
    const data = (await res.clone().json()) as { detail?: unknown } | null;
    if (data && typeof data.detail === 'string') return data.detail;
  } catch {
    /* a non-JSON body is not worth a failure */
  }
  return undefined;
}

/**
 * Map an HTTP response to a replay outcome.
 *
 *  - 2xx           applied. The server answers 200 for a first write and for a
 *                  redelivery alike, because a draining device has to treat
 *                  both as success and stop resending.
 *  - 409           conflict. The day was withdrawn, or the office has already
 *                  approved it and the correction was not applied. Permanent,
 *                  and the person has to be told - it is not a silent drop.
 *  - other 4xx     rejected. The payload can never be stored; retrying it
 *                  forever would only hide it.
 *  - 5xx / thrown  retry. The server or the link is having a moment.
 */
export async function outcomeFromResponse(res: Response): Promise<ReplayOutcome> {
  if (res.ok) {
    let resultId: string | null = null;
    try {
      const data = (await res.clone().json()) as OfflineEntryResult | null;
      resultId = data?.timesheet?.id ?? null;
    } catch {
      /* an empty body still means it landed */
    }
    return { kind: 'applied', httpStatus: res.status, resultId };
  }
  if (res.status === 409) {
    return { kind: 'conflict', httpStatus: res.status, detail: await safeDetail(res) };
  }
  if (res.status >= 400 && res.status < 500) {
    return { kind: 'rejected', httpStatus: res.status, detail: await safeDetail(res) };
  }
  return { kind: 'retry', httpStatus: res.status };
}

/**
 * Build the HTTP sender. The body is sent exactly as it was queued: the entry
 * key already lives inside it, and overwriting anything at replay time would
 * mean the op that finally lands is not the op the foreman recorded.
 */
export function createFieldTimeSender(): OpSender {
  return async (op: QueuedOp): Promise<ReplayOutcome> => {
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    const token = getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
    const res = await fetch(`${API_BASE}${op.path}`, {
      method: op.method,
      headers,
      body: op.body === undefined ? undefined : JSON.stringify(op.body),
    });
    return outcomeFromResponse(res);
  };
}

/** IndexedDB where it exists, memory where it does not. Same queue either way. */
export function pickFieldTimeStorage(): QueueStorage {
  if (typeof indexedDB !== 'undefined') {
    return createIndexedDbQueueStorage(FIELD_TIME_QUEUE_DB);
  }
  return createMemoryQueueStorage();
}

let singleton: MutationQueue | null = null;

/** The process-wide field-time queue, built on first use. */
export function getFieldTimeQueue(): MutationQueue {
  if (!singleton) {
    singleton = new MutationQueue(pickFieldTimeStorage(), createFieldTimeSender());
  }
  return singleton;
}

/** Test seam: drop the singleton so the next call rebuilds it. */
export function resetFieldTimeQueueForTests(queue: MutationQueue | null = null): void {
  singleton = queue;
}

/** Queue one day for replay. A fresh op id every time, so an edit is never lost. */
export async function enqueueEntry(payload: OfflineEntryPayload): Promise<void> {
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
  await getFieldTimeQueue().enqueue({
    clientOpId: newClientOpId(),
    method: 'POST',
    path: WITHDRAW_PATH,
    body: payload,
    kind: OP_WITHDRAW,
  });
}
