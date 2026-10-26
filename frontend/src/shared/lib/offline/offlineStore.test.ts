// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, beforeEach } from 'vitest';
import {
  createMemoryOfflineStore,
  isLocalId,
  newLocalId,
  pickOfflineStore,
  type LocalRecord,
  type OfflineStore,
} from './offlineStore';

function rec(over: Partial<LocalRecord> = {}): LocalRecord {
  return {
    localId: 'local-1',
    kind: 'punch',
    serverId: null,
    baseVersion: null,
    serverSnapshot: null,
    data: { title: 'Crack' },
    dirty: true,
    createdAt: 1,
    updatedAt: 1,
    ...over,
  };
}

describe('memory offline store - records', () => {
  let store: OfflineStore;
  beforeEach(() => {
    store = createMemoryOfflineStore();
  });

  it('round-trips a record by kind and local id', async () => {
    await store.putRecord(rec());
    expect((await store.getRecord('punch', 'local-1'))?.data).toEqual({ title: 'Crack' });
    expect(await store.getRecord('inspection', 'local-1')).toBeUndefined();
  });

  it('keeps kinds apart and lists by kind', async () => {
    await store.putRecord(rec());
    await store.putRecord(rec({ kind: 'inspection', localId: 'local-2' }));
    expect((await store.listRecords('punch')).map((r) => r.localId)).toEqual(['local-1']);
    expect(await store.listRecords()).toHaveLength(2);
  });

  it('finds a record by server id and keeps the 3-way merge ancestor', async () => {
    await store.putRecord(
      rec({ localId: 'srv-9', serverId: 'srv-9', baseVersion: 3, serverSnapshot: { title: 'Old' } }),
    );
    const found = await store.findByServerId('punch', 'srv-9');
    expect(found?.baseVersion).toBe(3);
    expect(found?.serverSnapshot).toEqual({ title: 'Old' });
    expect(await store.findByServerId('punch', 'nope')).toBeUndefined();
  });

  it('deletes and clears', async () => {
    await store.putRecord(rec());
    await store.deleteRecord('punch', 'local-1');
    expect(await store.listRecords()).toEqual([]);
    await store.putRecord(rec());
    await store.clear();
    expect(await store.listRecords()).toEqual([]);
  });
});

describe('memory offline store - photos', () => {
  it('stores Blobs, lists them per record in capture order, deletes after upload', async () => {
    const store = createMemoryOfflineStore();
    const blob = (s: string) => new Blob([s], { type: 'image/jpeg' });
    await store.putPhoto({ id: 'p2', kind: 'punch', localId: 'local-1', name: 'b.jpg', type: 'image/jpeg', blob: blob('b'), createdAt: 20 });
    await store.putPhoto({ id: 'p1', kind: 'punch', localId: 'local-1', name: 'a.jpg', type: 'image/jpeg', blob: blob('a'), createdAt: 10 });
    await store.putPhoto({ id: 'p3', kind: 'punch', localId: 'other', name: 'c.jpg', type: 'image/jpeg', blob: blob('c'), createdAt: 5 });

    expect((await store.listPhotosByRecord('punch', 'local-1')).map((p) => p.id)).toEqual(['p1', 'p2']);
    expect((await store.getPhoto('p1'))?.blob.size).toBe(1);

    await store.deletePhoto('p1');
    expect(await store.getPhoto('p1')).toBeUndefined();
    expect((await store.listPhotosByRecord('punch', 'local-1')).map((p) => p.id)).toEqual(['p2']);
  });
});

describe('ids and fallback', () => {
  it('marks temporary ids so they never look like server uuids', () => {
    const id = newLocalId();
    expect(isLocalId(id)).toBe(true);
    expect(isLocalId('3f2c9b1e-7d44-4c63-9d1a-0a1f1c9d2b10')).toBe(false);
    expect(isLocalId(null)).toBe(false);
    expect(newLocalId()).not.toBe(id);
  });

  it('falls back to memory when IndexedDB is missing', async () => {
    const original = (globalThis as { indexedDB?: unknown }).indexedDB;
    (globalThis as { indexedDB?: unknown }).indexedDB = undefined;
    try {
      const store = pickOfflineStore();
      await store.putRecord(rec());
      expect(await store.listRecords()).toHaveLength(1);
    } finally {
      (globalThis as { indexedDB?: unknown }).indexedDB = original;
    }
  });
});
