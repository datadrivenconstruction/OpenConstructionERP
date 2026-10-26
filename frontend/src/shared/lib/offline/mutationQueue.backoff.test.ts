// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import {
  MutationQueue,
  computeBackoffDelay,
  createMemoryQueueStorage,
  type OpSender,
  type QueuedOp,
  type ReplayOutcome,
} from './mutationQueue';

function harness(outcomeFor: (op: QueuedOp) => ReplayOutcome, opts: { random?: () => number } = {}) {
  let now = 1_000_000;
  const calls: string[] = [];
  const sender: OpSender = (op) => {
    calls.push(op.clientOpId);
    return Promise.resolve(outcomeFor(op));
  };
  const q = new MutationQueue(createMemoryQueueStorage(), sender, {
    backoff: true,
    now: () => now,
    random: opts.random ?? (() => 1),
  });
  return {
    q,
    calls,
    advance: (ms: number) => {
      now += ms;
    },
    get now() {
      return now;
    },
  };
}

describe('computeBackoffDelay', () => {
  it('doubles from 2 s and caps at 5 min (no jitter at random=1)', () => {
    const d = (n: number) => computeBackoffDelay(n, {}, () => 1);
    expect([1, 2, 3, 4].map(d)).toEqual([2000, 4000, 8000, 16000]);
    expect(d(8)).toBe(256_000);
    expect(d(9)).toBe(300_000);
    expect(d(30)).toBe(300_000);
  });

  it('jitters into the upper half of the delay', () => {
    expect(computeBackoffDelay(3, {}, () => 0)).toBe(4000);
    expect(computeBackoffDelay(3, {}, () => 0.5)).toBe(6000);
    expect(computeBackoffDelay(3, {}, () => 1)).toBe(8000);
  });

  it('honours custom base, factor and cap', () => {
    expect(computeBackoffDelay(3, { baseMs: 100, factor: 3, capMs: 500 }, () => 1)).toBe(500);
  });
});

describe('MutationQueue - backoff scheduling', () => {
  it('stamps nextAttemptAt after a transient failure and skips the op until due', async () => {
    const h = harness(() => ({ kind: 'retry', httpStatus: 503 }));
    await h.q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });

    const first = await h.q.drain();
    expect(first.retry).toBe(1);
    const [op] = await h.q.pending();
    expect(op?.retries).toBe(1);
    expect(op?.nextAttemptAt).toBe(h.now + 2000);

    const second = await h.q.drain();
    expect(second.results).toEqual([]); // not due yet
    expect(h.calls).toEqual(['a']);

    h.advance(2000);
    await h.q.drain();
    expect(h.calls).toEqual(['a', 'a']);
    const [again] = await h.q.pending();
    expect(again?.nextAttemptAt).toBe(h.now + 4000);
  });

  it('a manual drain ignores the backoff', async () => {
    const h = harness(() => ({ kind: 'retry' }));
    await h.q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });
    await h.q.drain();
    await h.q.drain({ ignoreBackoff: true });
    expect(h.calls).toEqual(['a', 'a']);
  });

  it('a waiting op does not hold back unrelated ops', async () => {
    const h = harness((op) => (op.clientOpId === 'a' ? { kind: 'retry' } : { kind: 'applied', httpStatus: 200 }));
    await h.q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });
    await h.q.enqueue({ clientOpId: 'b', method: 'POST', path: '/y', kind: 'k' });
    await h.q.drain();
    h.advance(10);
    const s = await h.q.drain();
    expect(s.results).toEqual([]);
    expect(h.calls).toEqual(['a', 'b']);
    expect((await h.q.pending()).map((o) => o.clientOpId)).toEqual(['a']);
  });

  it('keeps ops of one record in order while the first waits', async () => {
    const h = harness((op) => (op.clientOpId === 'create' ? { kind: 'retry' } : { kind: 'applied', httpStatus: 200 }));
    const meta = { recordKey: 'punch:local-1' };
    await h.q.enqueue({ clientOpId: 'create', method: 'POST', path: '/x', kind: 'k', meta });
    await h.q.enqueue({ clientOpId: 'photo', method: 'POST', path: '/x/photos', kind: 'k', meta });
    await h.q.drain();
    // The photo must not overtake the record, in this pass or while it backs off.
    expect(h.calls).toEqual(['create']);
    h.advance(1);
    await h.q.drain();
    expect(h.calls).toEqual(['create']);
    h.advance(2000);
    await h.q.drain();
    expect(h.calls).toEqual(['create', 'create']);
  });

  it('still gives up after max retries', async () => {
    const h = harness(() => ({ kind: 'retry' }));
    const q = new MutationQueue(createMemoryQueueStorage(), () => Promise.resolve({ kind: 'retry' }), {
      backoff: true,
      maxRetries: 2,
    });
    await q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });
    await q.drain();
    const s = await q.drain({ ignoreBackoff: true });
    expect(s.rejected).toBe(1);
    expect(await q.pendingCount()).toBe(0);
    void h;
  });

  it('reports the earliest due time', async () => {
    const h = harness(() => ({ kind: 'retry' }));
    await h.q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });
    expect(await h.q.nextDueAt()).toBeNull();
    await h.q.drain();
    expect(await h.q.nextDueAt()).toBe(h.now + 2000);
  });

  it('without the backoff option a retry stays immediately due (legacy behaviour)', async () => {
    const calls: string[] = [];
    const q = new MutationQueue(createMemoryQueueStorage(), (op) => {
      calls.push(op.clientOpId);
      return Promise.resolve({ kind: 'retry' } as ReplayOutcome);
    });
    await q.enqueue({ clientOpId: 'a', method: 'POST', path: '/x', kind: 'k' });
    await q.drain();
    await q.drain();
    expect(calls).toEqual(['a', 'a']);
    expect((await q.pending())[0]?.nextAttemptAt).toBeUndefined();
  });
});

describe('MutationQueue - version conflicts', () => {
  const conflict: ReplayOutcome = {
    kind: 'merge_conflict',
    httpStatus: 409,
    detail: 'stale',
    currentVersion: 7,
    current: { id: 'srv', version: 7, notes: 'theirs' },
  };

  it('parks the op with the server copy instead of dropping it', async () => {
    const h = harness(() => conflict);
    await h.q.enqueue({ clientOpId: 'u', method: 'PATCH', path: '/x/srv', body: { notes: 'mine' }, kind: 'k' });
    const s = await h.q.drain();
    expect(s.merge_conflict).toBe(1);
    expect(s.results[0]?.status).toBe('merge_conflict');

    const [op] = await h.q.conflicts();
    expect(op?.body).toEqual({ notes: 'mine' });
    expect(op?.conflict?.currentVersion).toBe(7);
    expect(op?.conflict?.current).toEqual({ id: 'srv', version: 7, notes: 'theirs' });
    expect(await h.q.pendingCount()).toBe(1);
  });

  it('does not replay a parked op, nor later ops on the same record', async () => {
    const h = harness((op) => (op.clientOpId === 'u1' ? conflict : { kind: 'applied', httpStatus: 200 }));
    const meta = { recordKey: 'punch:srv' };
    await h.q.enqueue({ clientOpId: 'u1', method: 'PATCH', path: '/x', kind: 'k', meta });
    await h.q.enqueue({ clientOpId: 'u2', method: 'PATCH', path: '/x', kind: 'k', meta });
    await h.q.enqueue({ clientOpId: 'other', method: 'POST', path: '/y', kind: 'k' });
    await h.q.drain({ ignoreBackoff: true });
    await h.q.drain({ ignoreBackoff: true });
    expect(h.calls).toEqual(['u1', 'other']);
  });

  it('resolving the conflict frees the record', async () => {
    const h = harness(() => conflict);
    await h.q.enqueue({ clientOpId: 'u', method: 'PATCH', path: '/x', kind: 'k' });
    await h.q.drain();
    await h.q.resolveMergeConflict('u');
    expect(await h.q.pendingCount()).toBe(0);
  });

  it('markConflict refreshes the server copy on a parked op', async () => {
    const h = harness(() => conflict);
    await h.q.enqueue({ clientOpId: 'u', method: 'PATCH', path: '/x', kind: 'k' });
    await h.q.drain();
    await h.q.markConflict('u', { currentVersion: 9, current: { version: 9 } });
    expect((await h.q.conflicts())[0]?.conflict?.currentVersion).toBe(9);
  });

  it('the old idempotency conflict still drops the op', async () => {
    const h = harness(() => ({ kind: 'conflict', httpStatus: 409, detail: 'duplicate' }));
    await h.q.enqueue({ clientOpId: 'c', method: 'POST', path: '/x', kind: 'k' });
    const s = await h.q.drain();
    expect(s.conflict).toBe(1);
    expect(await h.q.pendingCount()).toBe(0);
  });
});
