// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, beforeEach, vi } from 'vitest';

vi.mock('@/shared/lib/api', () => ({
  fetchWithAuth: vi.fn(),
  apiGet: vi.fn(),
}));

import {
  classifyConflictBody,
  createRecordSender,
  isNetworkError,
  mergePath,
  mergeAuditPath,
  overlayRecords,
} from './recordSync';
import { createMemoryOfflineStore, type LocalRecord, type OfflineStore } from './offlineStore';
import type { QueuedOp } from './mutationQueue';
import { deriveSyncStatus } from './offlineSyncStore';

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });
}

function op(over: Partial<QueuedOp> = {}): QueuedOp {
  return {
    seq: 1,
    clientOpId: 'op-1',
    method: 'POST',
    path: '/v1/punchlist/items/',
    body: { title: 'Crack' },
    kind: 'punch',
    queuedAt: 1,
    retries: 0,
    meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'create' },
    ...over,
  };
}

function rec(over: Partial<LocalRecord> = {}): LocalRecord {
  return {
    localId: 'local-1',
    kind: 'punch',
    serverId: null,
    baseVersion: null,
    serverSnapshot: null,
    data: { id: 'local-1', title: 'Crack' },
    dirty: true,
    createdAt: 1,
    updatedAt: 1,
    ...over,
  };
}

describe('classifyConflictBody', () => {
  it('reads the version_conflict detail the backend sends', () => {
    const c = classifyConflictBody({
      detail: {
        code: 'version_conflict',
        message: 'changed',
        current_version: 5,
        current: { id: 'x', version: 5 },
      },
    });
    expect(c).toEqual({
      isVersionConflict: true,
      message: 'changed',
      currentVersion: 5,
      current: { id: 'x', version: 5 },
    });
  });

  it('accepts the detail object without the FastAPI wrapper', () => {
    expect(classifyConflictBody({ code: 'version_conflict', current_version: 2 }).isVersionConflict).toBe(true);
  });

  it('leaves the idempotency 409 alone (no code, or another code)', () => {
    expect(classifyConflictBody({ detail: 'duplicate client_op_id' })).toEqual({
      isVersionConflict: false,
      message: 'duplicate client_op_id',
    });
    expect(classifyConflictBody({ detail: { code: 'duplicate' } }).isVersionConflict).toBe(false);
    expect(classifyConflictBody(null).isVersionConflict).toBe(false);
    expect(classifyConflictBody('boom').isVersionConflict).toBe(false);
  });
});

describe('isNetworkError', () => {
  it('is true for a fetch failure and a client timeout, false for an HTTP answer', () => {
    expect(isNetworkError(new TypeError('Failed to fetch'))).toBe(true);
    expect(isNetworkError(Object.assign(new Error('slow'), { isTimeout: true }))).toBe(true);
    expect(isNetworkError(Object.assign(new Error('bad'), { status: 400 }))).toBe(false);
    expect(isNetworkError(null)).toBe(false);
  });
});

describe('merge endpoints', () => {
  it('append /merge/ and /merge-audit/ to the entity update path', () => {
    expect(mergePath('punch', 'p1')).toBe('/v1/punchlist/items/p1/merge/');
    expect(mergePath('inspection', 'i1')).toBe('/v1/inspections/i1/merge/');
    expect(mergePath('diary', 'd1')).toBe('/v1/daily-diary/diaries/d1/merge/');
    expect(mergePath('diary_entry', 'e1')).toBe('/v1/daily-diary/diary-entries/e1/merge/');
    expect(mergeAuditPath('punch', 'p1')).toBe('/v1/punchlist/items/p1/merge-audit/');
  });
});

describe('record sender', () => {
  let store: OfflineStore;
  const fetcher = vi.fn();
  const send = (o: QueuedOp) => createRecordSender({ fetcher, store: () => store })(o);

  beforeEach(() => {
    store = createMemoryOfflineStore();
    fetcher.mockReset();
  });

  it('create: sends client_op_id and records the server id, version and snapshot', async () => {
    await store.putRecord(rec());
    fetcher.mockResolvedValue(json(201, { id: 'srv-1', version: 1, title: 'Crack' }));

    const out = await send(op());

    expect(out).toEqual({ kind: 'applied', httpStatus: 201, resultId: 'srv-1' });
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('/api/v1/punchlist/items/');
    expect(JSON.parse(init.body)).toEqual({ title: 'Crack', client_op_id: 'op-1' });
    const saved = await store.getRecord('punch', 'local-1');
    expect(saved?.serverId).toBe('srv-1');
    expect(saved?.baseVersion).toBe(1);
    expect(saved?.serverSnapshot).toMatchObject({ id: 'srv-1' });
  });

  it('update: sends If-Match and version, using the id the create got', async () => {
    await store.putRecord(rec({ serverId: 'srv-1', baseVersion: 4 }));
    fetcher.mockResolvedValue(json(200, { id: 'srv-1', version: 5 }));

    const out = await send(
      op({
        method: 'PATCH',
        path: '/v1/punchlist/items/local-1',
        body: { description: 'new' },
        meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'update' },
      }),
    );

    expect(out.kind).toBe('applied');
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('/api/v1/punchlist/items/srv-1');
    expect(init.headers['If-Match']).toBe('4');
    expect(JSON.parse(init.body)).toEqual({ description: 'new', version: 4 });
    expect((await store.getRecord('punch', 'local-1'))?.baseVersion).toBe(5);
  });

  it('update on a record whose create has not landed waits (retry)', async () => {
    await store.putRecord(rec());
    const out = await send(
      op({
        method: 'PATCH',
        path: '/v1/punchlist/items/local-1',
        meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'update' },
      }),
    );
    expect(out.kind).toBe('retry');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('update: a version_conflict 409 becomes merge_conflict carrying the server copy', async () => {
    await store.putRecord(rec({ serverId: 'srv-1', baseVersion: 4 }));
    const current = { id: 'srv-1', version: 6, description: 'theirs' };
    fetcher.mockResolvedValue(
      json(409, { detail: { code: 'version_conflict', message: 'stale', current_version: 6, current } }),
    );
    const out = await send(
      op({
        method: 'PATCH',
        path: '/v1/punchlist/items/srv-1',
        meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'update' },
      }),
    );
    expect(out).toEqual({
      kind: 'merge_conflict',
      httpStatus: 409,
      detail: 'stale',
      currentVersion: 6,
      current,
    });
  });

  it('create: a plain 409 stays the old idempotency conflict', async () => {
    await store.putRecord(rec());
    fetcher.mockResolvedValue(json(409, { detail: 'already exists' }));
    const out = await send(op());
    expect(out).toEqual({ kind: 'conflict', httpStatus: 409, detail: 'already exists' });
  });

  it('maps 4xx to rejected and 5xx / 429 to retry', async () => {
    await store.putRecord(rec());
    fetcher.mockResolvedValueOnce(json(422, { detail: 'bad title' }));
    expect(await send(op())).toMatchObject({ kind: 'rejected', httpStatus: 422, detail: 'bad title' });
    fetcher.mockResolvedValueOnce(json(503, {}));
    expect((await send(op())).kind).toBe('retry');
    fetcher.mockResolvedValueOnce(json(429, {}));
    expect((await send(op())).kind).toBe('retry');
  });

  it('create on a local diary resolves the diary id, or waits for it', async () => {
    const entry = op({
      path: '/v1/daily-diary/diary-entries/',
      kind: 'diary_entry',
      body: { diary_id: 'local-d', title: 'Pour' },
      meta: { recordKey: 'diary_entry:local-e', entity: 'diary_entry', localId: 'local-e', action: 'create' },
    });
    await store.putRecord(rec({ kind: 'diary', localId: 'local-d', serverId: null }));
    expect((await send(entry)).kind).toBe('retry');

    await store.putRecord(rec({ kind: 'diary', localId: 'local-d', serverId: 'srv-d' }));
    await store.putRecord(rec({ kind: 'diary_entry', localId: 'local-e' }));
    fetcher.mockResolvedValue(json(201, { id: 'srv-e', version: 1 }));
    await send(entry);
    expect(JSON.parse(fetcher.mock.calls[0]![1].body).diary_id).toBe('srv-d');
  });

  it('photo: uploads the stored Blob as multipart, then drops it from the device', async () => {
    await store.putRecord(rec({ serverId: 'srv-1', baseVersion: 1 }));
    await store.putPhoto({
      id: 'photo-1',
      kind: 'punch',
      localId: 'local-1',
      name: 'crack.jpg',
      type: 'image/jpeg',
      blob: new Blob(['x'], { type: 'image/jpeg' }),
      createdAt: 1,
    });
    fetcher.mockResolvedValue(json(200, { id: 'srv-1' }));

    const out = await send(
      op({
        path: '/v1/punchlist/items/local-1/photos/',
        kind: 'punch:photo',
        body: undefined,
        meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'photo', photoId: 'photo-1' },
      }),
    );

    expect(out.kind).toBe('applied');
    const [url, init] = fetcher.mock.calls[0]!;
    expect(url).toBe('/api/v1/punchlist/items/srv-1/photos/');
    expect(init.body).toBeInstanceOf(FormData);
    expect((init.body as FormData).get('file')).toBeInstanceOf(Blob);
    expect(init.headers['Content-Type']).toBeUndefined();
    expect(await store.getPhoto('photo-1')).toBeUndefined();
  });

  it('photo: keeps the Blob when the upload fails', async () => {
    await store.putRecord(rec({ serverId: 'srv-1' }));
    await store.putPhoto({
      id: 'photo-1',
      kind: 'punch',
      localId: 'local-1',
      name: 'a.jpg',
      type: 'image/jpeg',
      blob: new Blob(['x']),
      createdAt: 1,
    });
    fetcher.mockResolvedValue(json(500, {}));
    const out = await send(
      op({
        path: '/v1/punchlist/items/local-1/photos/',
        body: undefined,
        meta: { recordKey: 'punch:local-1', entity: 'punch', localId: 'local-1', action: 'photo', photoId: 'photo-1' },
      }),
    );
    expect(out.kind).toBe('retry');
    expect(await store.getPhoto('photo-1')).toBeDefined();
  });
});

describe('overlayRecords', () => {
  const server = [
    { id: 's1', title: 'One', project_id: 'p' },
    { id: 's2', title: 'Two', project_id: 'p' },
  ];

  it('puts queued creates first, flagged new', () => {
    const out = overlayRecords(server, [rec({ data: { title: 'Local', project_id: 'p' } })]);
    expect(out.map((i) => i.id)).toEqual(['local-1', 's1', 's2']);
    expect(out[0]?._offline).toBe('new');
  });

  it('applies a queued edit on the matching row, flagged edited', () => {
    const out = overlayRecords(server, [rec({ localId: 's2', serverId: 's2', data: { title: 'Two (edited)' } })]);
    expect(out[1]).toMatchObject({ id: 's2', title: 'Two (edited)', _offline: 'edited' });
    expect(out[0]?._offline).toBeUndefined();
  });

  it('ignores synced records and other projects', () => {
    expect(overlayRecords(server, [rec({ dirty: false })])).toEqual(server);
    const out = overlayRecords(server, [rec({ projectId: 'other' })], { projectId: 'p' });
    expect(out).toHaveLength(2);
  });

  it('does not double a row the cache already holds under the temporary id', () => {
    const cached = [{ id: 'local-1', title: 'Local' }, ...server];
    const out = overlayRecords(cached, [rec({ data: { title: 'Local' } })]);
    expect(out.filter((i) => i.id === 'local-1')).toHaveLength(1);
  });
});

describe('deriveSyncStatus', () => {
  const base = { online: true, syncing: false, pending: 0, conflicts: 0, problems: 0 };
  it('ranks conflict over offline over syncing over error over pending', () => {
    expect(deriveSyncStatus(base)).toBe('online-synced');
    expect(deriveSyncStatus({ ...base, pending: 2 })).toBe('pending');
    expect(deriveSyncStatus({ ...base, pending: 2, problems: 1 })).toBe('error');
    expect(deriveSyncStatus({ ...base, pending: 2, problems: 1, syncing: true })).toBe('syncing');
    expect(deriveSyncStatus({ ...base, online: false, pending: 2, syncing: true })).toBe('offline');
    expect(deriveSyncStatus({ ...base, online: false, conflicts: 1 })).toBe('conflict');
  });
});
