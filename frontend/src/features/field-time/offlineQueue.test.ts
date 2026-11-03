// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The device half of the promise: a day recorded with no signal is kept, sent
 * once, and never quietly rewritten by its own replay.
 *
 * The case worth a test rather than a comment is the two ids. The queue dedups
 * on `clientOpId` and returns the FIRST op without replacing its body, so using
 * the entry key there would swallow the foreman's correction on the device and
 * the server would never even be asked. Every op therefore gets a fresh op id
 * while the entry key stays put, and both halves are asserted here.
 */

import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import { MutationQueue, createMemoryQueueStorage, type QueuedOp } from '@/shared/lib/offline';
import {
  enqueueEntry,
  enqueueWithdraw,
  entryKeyOf,
  workDateOf,
  newEntryKey,
  outcomeFromResponse,
  resetFieldTimeQueueForTests,
  OP_RECORD,
  OP_WITHDRAW,
} from './offlineQueue';
import type { OfflineEntryPayload } from './api';

function entry(key: string, hours: string, date = '2026-06-11'): OfflineEntryPayload {
  return {
    entry_key: key,
    project_id: 'p1',
    date,
    lines: [{ resource_id: 'r1', hours, cost_code: '01.100' }],
    submit: true,
  };
}

/**
 * The single element of a one-item array, narrowed.
 *
 * `noUncheckedIndexedAccess` types `arr[0]` as possibly undefined, and the
 * build runs `tsc -b` while vitest does not, so an unchecked index passes the
 * test run and fails the gate. Throwing here also gives a better failure than
 * a null dereference when the array is unexpectedly empty.
 */
function only<T>(items: readonly T[]): T {
  const first = items[0];
  if (first === undefined) throw new Error('expected exactly one item');
  return first;
}

/** A response object good enough for the outcome mapper. */
function res(status: number, body?: unknown): Response {
  return new Response(body === undefined ? null : JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });
}

describe('field-time offline queue - two ids', () => {
  let sent: QueuedOp[];
  let queue: MutationQueue;

  beforeEach(() => {
    sent = [];
    queue = new MutationQueue(createMemoryQueueStorage(), async (op) => {
      sent.push(op);
      return { kind: 'applied', httpStatus: 200 };
    });
    resetFieldTimeQueueForTests(queue);
  });

  afterEach(() => {
    resetFieldTimeQueueForTests(null);
  });

  it('keeps a corrected day as a second op instead of swallowing it', async () => {
    const key = newEntryKey();
    await enqueueEntry(entry(key, '8'));
    await enqueueEntry(entry(key, '6.5'));

    const pending = await queue.pending();
    expect(pending).toHaveLength(2);
    // Same entry, different ops. Both carry the key that ties them together.
    expect(new Set(pending.map((o) => o.clientOpId)).size).toBe(2);
    expect(pending.map(entryKeyOf)).toEqual([key, key]);
  });

  it('replays in the order the days were recorded', async () => {
    const first = newEntryKey();
    const second = newEntryKey();
    await enqueueEntry(entry(first, '8', '2026-06-11'));
    await enqueueEntry(entry(second, '4', '2026-06-12'));

    await queue.drain();

    expect(sent.map(workDateOf)).toEqual(['2026-06-11', '2026-06-12']);
    expect(await queue.pendingCount()).toBe(0);
  });

  it('sends the body exactly as it was recorded', async () => {
    const key = newEntryKey();
    await enqueueEntry(entry(key, '8'));
    await queue.drain();

    expect(sent).toHaveLength(1);
    const op = only(sent);
    expect(op.kind).toBe(OP_RECORD);
    expect(op.path).toBe('/v1/field-time/timesheets/offline/');
    expect(op.body).toEqual(entry(key, '8'));
  });

  it('queues a withdrawal under its own kind', async () => {
    const key = newEntryKey();
    await enqueueWithdraw({ entry_key: key, project_id: 'p1' });
    const pending = await queue.pending();

    expect(pending).toHaveLength(1);
    const op = only(pending);
    expect(op.kind).toBe(OP_WITHDRAW);
    expect(entryKeyOf(op)).toBe(key);
  });

  it('mints a different key for every day', () => {
    const keys = new Set(Array.from({ length: 50 }, () => newEntryKey()));
    expect(keys.size).toBe(50);
  });

  it('reads nothing rather than throwing on a body it does not recognise', () => {
    const op = { clientOpId: 'x', kind: OP_RECORD, seq: 1, method: 'POST', path: '/', retries: 0, queuedAt: 0 };
    expect(entryKeyOf({ ...op, body: undefined } as QueuedOp)).toBe('');
    expect(entryKeyOf({ ...op, body: { entry_key: 42 } } as QueuedOp)).toBe('');
    expect(workDateOf({ ...op, body: null } as QueuedOp)).toBe('');
  });
});

describe('field-time offline queue - what the server said', () => {
  it('treats a first write and a redelivery alike, because both mean stop resending', async () => {
    const created = await outcomeFromResponse(res(200, { outcome: 'created', timesheet: { id: 'ts1' } }));
    const replayed = await outcomeFromResponse(res(200, { outcome: 'replayed', timesheet: { id: 'ts1' } }));

    expect(created).toEqual({ kind: 'applied', httpStatus: 200, resultId: 'ts1' });
    expect(replayed).toEqual({ kind: 'applied', httpStatus: 200, resultId: 'ts1' });
  });

  it('reports a withdrawn or already-approved day as a conflict, with the reason', async () => {
    const outcome = await outcomeFromResponse(res(409, { detail: 'This day was withdrawn on the device' }));
    expect(outcome.kind).toBe('conflict');
    expect(outcome).toHaveProperty('detail', 'This day was withdrawn on the device');
  });

  it('gives up on a payload that can never be stored', async () => {
    expect((await outcomeFromResponse(res(422, { detail: 'line is neither labour nor plant' }))).kind).toBe(
      'rejected',
    );
    expect((await outcomeFromResponse(res(403))).kind).toBe('rejected');
  });

  it('keeps trying when the server or the link is the problem', async () => {
    expect((await outcomeFromResponse(res(500))).kind).toBe('retry');
    expect((await outcomeFromResponse(res(502))).kind).toBe('retry');
  });

  it('still counts a 2xx with no usable body as applied', async () => {
    const outcome = await outcomeFromResponse(res(200));
    expect(outcome).toEqual({ kind: 'applied', httpStatus: 200, resultId: null });
  });

  it('leaves a queued day alone when the link is dead', async () => {
    const queue = new MutationQueue(createMemoryQueueStorage(), () => {
      throw new Error('network down');
    });
    resetFieldTimeQueueForTests(queue);
    try {
      await enqueueEntry(entry(newEntryKey(), '8'));
      const summary = await queue.drain();

      expect(summary.retry).toBe(1);
      expect(summary.applied).toBe(0);
      // The day is still here. That is the entire point.
      expect(await queue.pendingCount()).toBe(1);
    } finally {
      resetFieldTimeQueueForTests(null);
    }
  });
});

describe('field-time offline queue - storage', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('falls back to memory where IndexedDB is missing, rather than dropping writes', async () => {
    vi.stubGlobal('indexedDB', undefined);
    const { pickFieldTimeStorage } = await import('./offlineQueue');
    const storage = pickFieldTimeStorage();
    await storage.put({
      seq: 1,
      clientOpId: 'a',
      method: 'POST',
      path: '/',
      kind: OP_RECORD,
      queuedAt: 0,
      retries: 0,
    });
    expect(await storage.getAll()).toHaveLength(1);
  });
});

describe('field-time offline queue - legacy migration', () => {
  it('carries queued days over with their ids and order, then drops the old database', async () => {
    const { migrateLegacyFieldTimeQueue } = await import('./offlineQueue');
    const target = new MutationQueue(createMemoryQueueStorage(), async () => ({ kind: 'applied', httpStatus: 200 }));
    const mk = (id: string, seq: number): QueuedOp => ({
      seq,
      clientOpId: id,
      method: 'POST',
      path: '/v1/field-time/timesheets/offline/',
      body: entry('k-' + id, '8'),
      kind: OP_RECORD,
      queuedAt: 0,
      retries: 2,
    });
    let dropped = 0;
    const io = { read: async () => [mk('b', 20), mk('a', 10)], drop: async () => void (dropped += 1) };
    expect(await migrateLegacyFieldTimeQueue(target, io)).toBe(2);
    expect((await target.pending()).map((o) => o.clientOpId)).toEqual(['a', 'b']);
    // A second run finds the same ops, dedups them, and loses nothing.
    expect(await migrateLegacyFieldTimeQueue(target, io)).toBe(2);
    expect(await target.pendingCount()).toBe(2);
    expect(dropped).toBe(2);
  });

  it('keeps the old database when it could not be read', async () => {
    const { migrateLegacyFieldTimeQueue } = await import('./offlineQueue');
    const target = new MutationQueue(createMemoryQueueStorage(), async () => ({ kind: 'applied', httpStatus: 200 }));
    let dropped = false;
    const n = await migrateLegacyFieldTimeQueue(target, { read: async () => null, drop: async () => void (dropped = true) });
    expect(n).toBe(0);
    expect(dropped).toBe(false);
  });
});
