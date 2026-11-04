import { afterEach, describe, expect, it, vi } from 'vitest';
import { createFieldSender } from './fieldQueue';
import type { QueuedOp } from './mutationQueue';

const op: QueuedOp = {
  seq: 1,
  clientOpId: 'c1',
  method: 'POST',
  path: '/v1/x/',
  kind: 'k',
  queuedAt: 1,
  retries: 0,
  owner: { userId: 'user-a' },
};

function reply(status: number, body: unknown) {
  const fetchMock = vi.fn(async () => new Response(JSON.stringify(body), { status }));
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}

afterEach(() => vi.unstubAllGlobals());

describe('field sender and the queue owner header', () => {
  it('names the owner on every replay', async () => {
    const f = reply(201, { id: 'r1' });
    await createFieldSender(() => ({}))(op);
    const headers = (f.mock.calls[0] as unknown as [string, RequestInit])[1].headers as Record<string, string>;
    expect(headers['X-Queue-Owner']).toBe('user-a');
  });

  it('turns an owner mismatch into held, not rejected', async () => {
    reply(403, { detail: { code: 'queue_owner_mismatch', message: 'x' } });
    const out = await createFieldSender(() => ({}))(op);
    expect(out.kind).toBe('held');
  });

  it('keeps other 403s as rejected', async () => {
    reply(403, { detail: 'Forbidden' });
    const out = await createFieldSender(() => ({}))(op);
    expect(out.kind).toBe('rejected');
  });
});
