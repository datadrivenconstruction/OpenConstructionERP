import { describe, it, expect, beforeEach } from 'vitest';
import { MutationQueue, createMemoryQueueStorage, type QueuedOp } from './mutationQueue';
import { createFieldSender } from './fieldQueue';
import { jwtOutcomeFromResponse, createJwtSender } from './jwtSender';
import { holdAuth, isAuthHeld, releaseAuthHold, releaseIfCredentialChanged, resetAuthHoldForTests } from './authHold';
import { ENTITY_CONFIG } from './recordSync';

const json = (status: number, body?: unknown) =>
  new Response(body === undefined ? null : JSON.stringify(body), { status });

function op(clientOpId: string, meta?: Record<string, unknown>): QueuedOp {
  return { seq: 1, clientOpId, method: 'POST', path: '/v1/x/', kind: 'k', queuedAt: 0, retries: 0, ...(meta ? { meta } : {}) };
}

beforeEach(() => resetAuthHoldForTests());

describe('held outcome', () => {
  it('keeps every op untouched and stops the drain', async () => {
    let calls = 0;
    const q = new MutationQueue(createMemoryQueueStorage(), async () => {
      calls += 1;
      return { kind: 'held', httpStatus: 401 };
    });
    await q.enqueue({ clientOpId: 'a', method: 'POST', path: '/a', kind: 'k' });
    await q.enqueue({ clientOpId: 'b', method: 'POST', path: '/b', kind: 'k' });
    const summary = await q.drain();
    expect(summary.held).toBe(1);
    expect(calls).toBe(1);
    const left = await q.pending();
    expect(left.map((o) => o.retries)).toEqual([0, 0]);
    expect(left.every((o) => o.nextAttemptAt === undefined)).toBe(true);
  });

  it('replays the backlog in order once the hold is released', async () => {
    const seen: string[] = [];
    let ok = false;
    const q = new MutationQueue(createMemoryQueueStorage(), async (o) => {
      if (!ok) return { kind: 'held' };
      seen.push(o.clientOpId);
      return { kind: 'applied', httpStatus: 200 };
    });
    await q.enqueue({ clientOpId: 'a', method: 'POST', path: '/a', kind: 'k' });
    await q.enqueue({ clientOpId: 'b', method: 'POST', path: '/b', kind: 'k' });
    await q.drain();
    ok = true;
    await q.drain();
    expect(seen).toEqual(['a', 'b']);
    expect(await q.pendingCount()).toBe(0);
  });
});

describe('jwt sender', () => {
  it('holds on 401 and keeps rejecting nothing', async () => {
    expect((await jwtOutcomeFromResponse(json(401))).kind).toBe('held');
    expect(isAuthHeld('jwt')).toBe(true);
  });

  it('does not touch the network while held', async () => {
    holdAuth('jwt', 'old');
    let called = false;
    const send = createJwtSender(async () => {
      called = true;
      return json(200);
    });
    expect((await send(op('a'))).kind).toBe('held');
    expect(called).toBe(false);
  });

  it('lifts the hold when the credential changed', () => {
    holdAuth('jwt', 'old');
    expect(releaseIfCredentialChanged('jwt', 'old')).toBe(false);
    expect(releaseIfCredentialChanged('jwt', 'new')).toBe(true);
    expect(isAuthHeld('jwt')).toBe(false);
  });

  it('reads a timesheet id from the body', async () => {
    const out = await jwtOutcomeFromResponse(json(200, { timesheet: { id: 't1' } }));
    expect(out).toEqual({ kind: 'applied', httpStatus: 200, resultId: 't1' });
  });
});

describe('field (PIN) sender', () => {
  const fetchOnce = (res: Response) => {
    globalThis.fetch = (async () => res) as typeof fetch;
  };

  it('holds on 401 and refuses to send afterwards until released', async () => {
    const send = createFieldSender(() => ({}));
    fetchOnce(json(401));
    expect((await send(op('a'))).kind).toBe('held');
    expect(isAuthHeld('field')).toBe(true);
    fetchOnce(json(200, { id: 'x' }));
    expect((await send(op('b'))).kind).toBe('held');
    releaseAuthHold('field');
    expect((await send(op('c'))).kind).toBe('applied');
  });

  it('does not send one PIN user work as another', async () => {
    const send = createFieldSender(() => ({}), { getUserId: () => 'u2' });
    fetchOnce(json(200, { id: 'x' }));
    expect((await send(op('a', { userId: 'u1' }))).kind).toBe('held');
    expect((await send(op('b', { userId: 'u2' }))).kind).toBe('applied');
  });
});

describe('checklist kind', () => {
  it('writes through the inspection endpoints with per-item merge', () => {
    expect(ENTITY_CONFIG.checklist.item('i1')).toBe('/v1/inspections/i1');
    expect(ENTITY_CONFIG.checklist.spec.checklistFields).toEqual(['checklist_data']);
  });
});
