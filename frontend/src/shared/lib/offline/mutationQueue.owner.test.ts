import { describe, it, expect } from 'vitest';
import {
  MutationQueue,
  createMemoryQueueStorage,
  type LastUserStore,
  type OpSender,
  type QueueOwner,
  type QueuedOp,
} from './mutationQueue';

const A: QueueOwner = { userId: 'user-a', label: 'a@site.test' };
const B: QueueOwner = { userId: 'user-b', label: 'b@site.test' };

function memoryLastUser(initial: string | null = null): LastUserStore & { value: string | null } {
  const s = {
    value: initial,
    get: () => s.value,
    set: (id: string) => {
      s.value = id;
    },
  };
  return s;
}

function setup(initialUser: QueueOwner | null, lastUser = memoryLastUser()) {
  const storage = createMemoryQueueStorage();
  const sent: QueuedOp[] = [];
  const sender: OpSender = async (op) => {
    sent.push(op);
    return { kind: 'applied', httpStatus: 201 };
  };
  const state = { user: initialUser };
  const make = () => new MutationQueue(storage, sender, { owner: () => state.user, lastUser });
  return { storage, sent, state, lastUser, queue: make(), make };
}

const input = (id: string) => ({ clientOpId: id, method: 'POST' as const, path: '/v1/x/', kind: 'k' });

describe('queue ownership', () => {
  it('stamps the signed-in user and tenant at enqueue', async () => {
    const { queue } = setup({ ...A, tenantId: 't1' });
    const op = await queue.enqueue(input('1'));
    expect(op.owner).toEqual({ ...A, tenantId: 't1' });
  });

  it('never replays the previous user captures under the next token', async () => {
    const { queue, sent, state } = setup(A);
    await queue.enqueue(input('a1'));
    state.user = B;
    const summary = await queue.drain();
    expect(sent).toHaveLength(0);
    expect(summary.applied).toBe(0);
    expect(await queue.pendingCount()).toBe(1);
    expect((await queue.held()).map((o) => o.clientOpId)).toEqual(['a1']);
    expect(await queue.pending()).toEqual([]);
  });

  it('replays them once the owner signs in again', async () => {
    const { queue, sent, state } = setup(A);
    await queue.enqueue(input('a1'));
    state.user = B;
    await queue.enqueue(input('b1'));
    await queue.drain();
    expect(sent.map((o) => o.clientOpId)).toEqual(['b1']);
    state.user = A;
    await queue.drain();
    expect(sent.map((o) => o.clientOpId)).toEqual(['b1', 'a1']);
  });

  it('does not replay when nobody is signed in', async () => {
    const { queue, sent, state } = setup(A);
    await queue.enqueue(input('a1'));
    state.user = null;
    await queue.drain();
    expect(sent).toHaveLength(0);
  });

  it('refuses to queue without a signed-in user', async () => {
    const { queue } = setup(null);
    await expect(queue.enqueue(input('x'))).rejects.toThrow();
  });

  it('stops mid-drain when the user switches', async () => {
    const storage = createMemoryQueueStorage();
    const state = { user: A as QueueOwner | null };
    const sent: string[] = [];
    const sender: OpSender = async (op) => {
      sent.push(op.clientOpId);
      state.user = B; // sign-out and sign-in while the first op is in flight
      return { kind: 'applied', httpStatus: 201 };
    };
    const queue = new MutationQueue(storage, sender, { owner: () => state.user, lastUser: memoryLastUser() });
    await queue.enqueue(input('a1'));
    await queue.enqueue(input('a2'));
    await queue.drain();
    expect(sent).toEqual(['a1']);
  });

  it('treats a different tenant of the same user id as someone else', async () => {
    const { queue, sent, state } = setup({ ...A, tenantId: 't1' });
    await queue.enqueue(input('a1'));
    state.user = { ...A, tenantId: 't2' };
    await queue.drain();
    expect(sent).toHaveLength(0);
  });

  it('exports and discards held captures', async () => {
    const { queue, state } = setup(A);
    await queue.enqueue(input('a1'));
    state.user = B;
    await queue.enqueue(input('b1'));
    const doc = JSON.parse(await queue.exportHeld()) as { ops: QueuedOp[] };
    expect(doc.ops.map((o) => o.clientOpId)).toEqual(['a1']);
    expect(await queue.discardHeld()).toBe(1);
    expect((await queue.held()).length).toBe(0);
    expect((await queue.pending()).map((o) => o.clientOpId)).toEqual(['b1']);
  });
});

describe('items from before stamping', () => {
  const legacy = (id: string): QueuedOp => ({
    seq: 1,
    clientOpId: id,
    method: 'POST',
    path: '/v1/x/',
    kind: 'k',
    queuedAt: 1,
    retries: 0,
  });

  it('go to the first user back only when it is the user of the last session', async () => {
    const { storage, queue, sent } = setup(A, memoryLastUser('user-a'));
    await storage.put(legacy('old'));
    await queue.drain();
    expect(sent.map((o) => o.clientOpId)).toEqual(['old']);
  });

  it('are held when a different user signs in first', async () => {
    const lastUser = memoryLastUser('user-a');
    const { storage, queue, sent, state, make } = setup(B, lastUser);
    await storage.put(legacy('old'));
    await queue.drain();
    expect(sent).toHaveLength(0);
    expect(lastUser.value).toBe('user-b');
    // the original user returning later does not get them back by accident
    state.user = A;
    await make().drain();
    expect(sent).toHaveLength(0);
    expect((await queue.held()).map((o) => o.clientOpId)).toEqual(['old']);
  });

  it('are held when no previous user is known', async () => {
    const { storage, queue, sent } = setup(A, memoryLastUser(null));
    await storage.put(legacy('old'));
    await queue.drain();
    expect(sent).toHaveLength(0);
    expect(await queue.held()).toHaveLength(1);
  });
});
