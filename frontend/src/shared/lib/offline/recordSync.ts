// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Offline-first sync engine for diaries, diary entries, punch items and​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * inspections (desktop session, JWT auth).
 *
 * The field-session queue (`fieldQueue.ts`) is a separate instance and stays as
 * is. This one differs in what it sends: versioned updates (`If-Match` plus
 * `version` in the body), creates tagged with `client_op_id`, photo uploads from
 * stored Blobs, and a version 409 that parks the op for a merge instead of
 * dropping it.
 *
 * Ordering: one FIFO queue. A record's create is queued before its edits and its
 * photos, and ops sharing a `meta.recordKey` never overtake each other, so
 * "record, then photo" holds even across backoff.
 */

import { apiGet, fetchWithAuth } from '@/shared/lib/api';
import { isOnline } from './connectivity';
import {
  MutationQueue,
  createIndexedDbQueueStorage,
  createMemoryQueueStorage,
  newClientOpId,
  type DrainSummary,
  type OpSender,
  type QueuedOp,
  type ReplayOutcome,
} from './mutationQueue';
import {
  getOfflineStore,
  isLocalId,
  newLocalId,
  type LocalRecord,
  type OfflineEntityKind,
  type OfflineStore,
} from './offlineStore';
import { patchOfflineSync, useOfflineSyncStore } from './offlineSyncStore';
import {
  applyDecisions,
  computeThreeWayMerge,
  type ConflictDecisions,
  type MergeSpec,
  type ThreeWayMergeResult,
} from './threeWayMerge';

/* ── Entity registry ───────────────────────────────────────────────────── */

export interface EntityConfig {
  kind: OfflineEntityKind;
  /** POST target for a create. */
  collection: string;
  /** PATCH target for an update (also the base of `/merge/` and `/merge-audit/`). */
  item: (id: string) => string;
  /** Multipart photo upload target, when the entity takes photos. */
  photos?: (id: string) => string;
  spec: MergeSpec;
  /** React Query key roots to refetch after a sync. */
  queryRoots: string[][];
}

export const ENTITY_CONFIG: Record<OfflineEntityKind, EntityConfig> = {
  diary: {
    kind: 'diary',
    collection: '/v1/daily-diary/diaries/',
    item: (id) => `/v1/daily-diary/diaries/${id}`,
    spec: { longTextFields: ['notes'] },
    queryRoots: [['daily-diary']],
  },
  diary_entry: {
    kind: 'diary_entry',
    collection: '/v1/daily-diary/diary-entries/',
    item: (id) => `/v1/daily-diary/diary-entries/${id}`,
    spec: { longTextFields: ['description'] },
    queryRoots: [['daily-diary']],
  },
  punch: {
    kind: 'punch',
    collection: '/v1/punchlist/items/',
    item: (id) => `/v1/punchlist/items/${id}`,
    photos: (id) => `/v1/punchlist/items/${id}/photos/`,
    spec: { longTextFields: ['description'] },
    queryRoots: [['punchlist'], ['punchlist-summary'], ['punchlist-pins']],
  },
  inspection: {
    kind: 'inspection',
    collection: '/v1/inspections/',
    item: (id) => `/v1/inspections/${id}`,
    spec: { longTextFields: ['notes'], checklistFields: ['checklist_data'] },
    queryRoots: [['inspections']],
  },
};

export const mergePath = (kind: OfflineEntityKind, id: string): string => `${ENTITY_CONFIG[kind].item(id)}/merge/`;
export const mergeAuditPath = (kind: OfflineEntityKind, id: string): string =>
  `${ENTITY_CONFIG[kind].item(id)}/merge-audit/`;

const recordKeyOf = (kind: OfflineEntityKind, localId: string) => `${kind}:${localId}`;

/* ── Small helpers ─────────────────────────────────────────────────────── */

const DEVICE_KEY = 'oe_device_id';
let memoryDeviceId: string | null = null;

/** Stable per-browser id sent with merges so the audit trail names the device. */
export function getDeviceId(): string {
  try {
    const existing = localStorage.getItem(DEVICE_KEY);
    if (existing) return existing;
    const id = `dev-${newClientOpId()}`;
    localStorage.setItem(DEVICE_KEY, id);
    return id;
  } catch {
    if (!memoryDeviceId) memoryDeviceId = `dev-${newClientOpId()}`;
    return memoryDeviceId;
  }
}

/**
 * True when a failed request never got an HTTP answer: the signal to keep the
 * write on the device instead of showing an error. An `ApiError` carries a
 * status and is a real answer; anything else from fetch is a transport fault.
 */
export function isNetworkError(err: unknown): boolean {
  if (!err || typeof err !== 'object') return false;
  if ('status' in err && typeof (err as { status: unknown }).status === 'number') return false;
  if ((err as { isTimeout?: boolean }).isTimeout) return true;
  const name = (err as { name?: string }).name;
  return err instanceof TypeError || name === 'TypeError' || name === 'NetworkError';
}

export interface VersionConflictBody {
  isVersionConflict: boolean;
  message?: string;
  currentVersion?: number;
  current?: unknown;
}

/**
 * Read a 409 body. The backend's version conflict is
 * `{"detail": {"code": "version_conflict", "message", "current_version", "current"}}`
 * (FastAPI wraps `detail`; a bare object is accepted too). Any other 409, such as
 * the idempotency hit, comes back `isVersionConflict: false`.
 */
export function classifyConflictBody(body: unknown): VersionConflictBody {
  const root = body && typeof body === 'object' ? (body as Record<string, unknown>) : null;
  const detail = root && 'detail' in root ? root.detail : root;
  if (detail && typeof detail === 'object' && (detail as Record<string, unknown>).code === 'version_conflict') {
    const d = detail as Record<string, unknown>;
    return {
      isVersionConflict: true,
      message: typeof d.message === 'string' ? d.message : undefined,
      currentVersion: typeof d.current_version === 'number' ? d.current_version : undefined,
      current: d.current,
    };
  }
  return { isVersionConflict: false, message: typeof detail === 'string' ? detail : undefined };
}

type Fetcher = (input: string, init?: RequestInit) => Promise<Response>;

async function readJson(res: Response): Promise<unknown> {
  try {
    return await res.clone().json();
  } catch {
    return null;
  }
}

/* ── Sender ────────────────────────────────────────────────────────────── */

interface SenderDeps {
  fetcher?: Fetcher;
  store?: () => OfflineStore;
}

/** Fields the sender owns; never part of a user patch. */
const SERVER_ONLY = new Set(['version', 'client_op_id']);

export function createRecordSender(deps: SenderDeps = {}): OpSender {
  const fetcher: Fetcher = deps.fetcher ?? fetchWithAuth;
  const getStore = deps.store ?? getOfflineStore;

  return async (op: QueuedOp): Promise<ReplayOutcome> => {
    const store = getStore();
    const meta = op.meta ?? {};
    const entity = meta.entity as OfflineEntityKind | undefined;
    const localId = typeof meta.localId === 'string' ? meta.localId : null;
    const action = typeof meta.action === 'string' ? meta.action : 'create';
    const rec = entity && localId ? await store.getRecord(entity, localId) : undefined;

    let path = op.path;
    if (action !== 'create' && localId) {
      const serverId = rec?.serverId ?? (isLocalId(localId) ? null : localId);
      if (!serverId) return { kind: 'retry', detail: 'record not on the server yet' };
      if (serverId !== localId) path = path.split(localId).join(serverId);
    }

    const headers: Record<string, string> = {
      Accept: 'application/json',
      'X-Client-Op-Id': op.clientOpId,
      'X-DDC-Client': 'OE/1.0',
    };
    let body: BodyInit | undefined;

    if (action === 'photo') {
      const photoId = typeof meta.photoId === 'string' ? meta.photoId : '';
      const photo = await store.getPhoto(photoId);
      if (!photo) return { kind: 'applied', httpStatus: 204 }; // already uploaded or discarded
      const form = new FormData();
      form.append('file', photo.blob, photo.name);
      body = form;
    } else {
      headers['Content-Type'] = 'application/json';
      const payload: Record<string, unknown> = { ...((op.body as Record<string, unknown>) ?? {}) };
      if (action === 'create') {
        payload.client_op_id = op.clientOpId;
        // An entry made on a diary that only existed on this device points at its
        // temporary id; swap in the server id once the diary has been created.
        const parent = payload.diary_id;
        if (typeof parent === 'string' && isLocalId(parent)) {
          const parentRec = await store.getRecord('diary', parent);
          if (!parentRec?.serverId) return { kind: 'retry', detail: 'parent diary not on the server yet' };
          payload.diary_id = parentRec.serverId;
        }
      } else if (rec?.baseVersion != null) {
        // The version the device last saw; the server refuses with 409 if moved on.
        headers['If-Match'] = String(rec.baseVersion);
        payload.version = rec.baseVersion;
      }
      body = JSON.stringify(payload);
    }

    const res = await fetcher(`/api${path}`, { method: op.method, headers, body });

    if (res.ok) {
      const data = (await readJson(res)) as Record<string, unknown> | null;
      if (action === 'photo') {
        const photoId = typeof meta.photoId === 'string' ? meta.photoId : '';
        if (photoId) await store.deletePhoto(photoId);
      } else if (rec && data && typeof data.id === 'string') {
        const version = typeof data.version === 'number' ? data.version : null;
        await store.putRecord({
          ...rec,
          serverId: data.id,
          baseVersion: version,
          serverSnapshot: data,
          updatedAt: Date.now(),
        });
      }
      return {
        kind: 'applied',
        httpStatus: res.status,
        resultId: data && typeof data.id === 'string' ? data.id : null,
      };
    }

    const errBody = await readJson(res);
    if (res.status === 409) {
      const c = classifyConflictBody(errBody);
      if (c.isVersionConflict && action === 'update') {
        return {
          kind: 'merge_conflict',
          httpStatus: 409,
          detail: c.message,
          currentVersion: c.currentVersion,
          current: c.current,
        };
      }
      return { kind: 'conflict', httpStatus: 409, detail: c.message };
    }
    const detail = classifyConflictBody(errBody).message;
    if (res.status >= 400 && res.status < 500 && res.status !== 408 && res.status !== 429) {
      return { kind: 'rejected', httpStatus: res.status, detail };
    }
    return { kind: 'retry', httpStatus: res.status, detail };
  };
}

/* ── Queue singleton ───────────────────────────────────────────────────── */

const QUEUE_DB = 'oe_field_record_queue';
let queue: MutationQueue | null = null;

export function getRecordQueue(): MutationQueue {
  if (!queue) {
    const storage =
      typeof indexedDB !== 'undefined' ? createIndexedDbQueueStorage(QUEUE_DB) : createMemoryQueueStorage();
    queue = new MutationQueue(storage, createRecordSender(), { backoff: true });
    queue.onChange(() => {
      void refreshSyncCounts();
      notifyRecordsChanged();
    });
  }
  return queue;
}

/** Test seam. */
export function setRecordQueueForTests(q: MutationQueue | null): void {
  queue = q;
}

/* ── Change notifications (local records) ──────────────────────────────── */

const recordListeners = new Set<() => void>();

export function onRecordsChanged(listener: () => void): () => void {
  recordListeners.add(listener);
  return () => {
    recordListeners.delete(listener);
  };
}

function notifyRecordsChanged(): void {
  for (const l of [...recordListeners]) l();
}

/* ── Capture (write side) ──────────────────────────────────────────────── */

function opMeta(kind: OfflineEntityKind, localId: string, action: 'create' | 'update' | 'photo', extra = {}) {
  return { recordKey: recordKeyOf(kind, localId), entity: kind, localId, action, ...extra };
}

/**
 * Keep a create on the device and queue it. `build` receives the temporary id and
 * returns the optimistic object the UI shows until the server's copy replaces it.
 */
export async function queueCreate(
  kind: OfflineEntityKind,
  payload: Record<string, unknown>,
  build: (localId: string) => Record<string, unknown>,
  projectId?: string | null,
  opts: { clientOpId?: string } = {},
): Promise<LocalRecord> {
  const localId = newLocalId();
  const now = Date.now();
  const rec: LocalRecord = {
    localId,
    kind,
    serverId: null,
    baseVersion: null,
    serverSnapshot: null,
    data: build(localId),
    dirty: true,
    projectId: projectId ?? null,
    createdAt: now,
    updatedAt: now,
  };
  await getOfflineStore().putRecord(rec);
  await getRecordQueue().enqueue({
    method: 'POST',
    path: ENTITY_CONFIG[kind].collection,
    body: payload,
    kind,
    clientOpId: opts.clientOpId,
    meta: opMeta(kind, localId, 'create'),
  });
  notifyRecordsChanged();
  return rec;
}

export interface UpdateBase {
  /** Server id, or the temporary id of a record that has not synced yet. */
  id: string;
  /** `version` the UI holds for this record, when it has one. */
  version?: number | null;
  /** The server copy the UI holds: the ancestor for a later merge. */
  snapshot?: Record<string, unknown> | null;
  projectId?: string | null;
}

/** Keep an edit on the device and queue the versioned PATCH. */
export async function queueUpdate(
  kind: OfflineEntityKind,
  base: UpdateBase,
  patch: Record<string, unknown>,
): Promise<LocalRecord> {
  const store = getOfflineStore();
  const now = Date.now();
  const clean: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(patch)) if (!SERVER_ONLY.has(k)) clean[k] = v;

  const existing = await store.getRecord(kind, base.id);
  const rec: LocalRecord = existing
    ? { ...existing, data: { ...existing.data, ...clean }, dirty: true, updatedAt: now }
    : {
        localId: base.id,
        kind,
        serverId: isLocalId(base.id) ? null : base.id,
        baseVersion: base.version ?? null,
        serverSnapshot: base.snapshot ?? null,
        data: { ...(base.snapshot ?? {}), ...clean },
        dirty: true,
        projectId: base.projectId ?? null,
        createdAt: now,
        updatedAt: now,
      };
  await store.putRecord(rec);
  await getRecordQueue().enqueue({
    method: 'PATCH',
    path: ENTITY_CONFIG[kind].item(base.id),
    body: clean,
    kind,
    meta: opMeta(kind, base.id, 'update'),
  });
  notifyRecordsChanged();
  return rec;
}

/** Keep a photo Blob on the device and queue its upload behind the record's ops. */
export async function queuePhoto(kind: OfflineEntityKind, recordId: string, file: File | Blob): Promise<string> {
  const photos = ENTITY_CONFIG[kind].photos;
  if (!photos) throw new Error(`${kind} takes no photos`);
  const photoId = `photo-${newClientOpId()}`;
  await getOfflineStore().putPhoto({
    id: photoId,
    kind,
    localId: recordId,
    name: (file as File).name || `${photoId}.jpg`,
    type: file.type || 'image/jpeg',
    blob: file,
    createdAt: Date.now(),
  });
  await getRecordQueue().enqueue({
    method: 'POST',
    path: photos(recordId),
    kind: `${kind}:photo`,
    meta: opMeta(kind, recordId, 'photo', { photoId }),
  });
  notifyRecordsChanged();
  return photoId;
}

/* ── Overlay (read side) ───────────────────────────────────────────────── */

export type OfflineFlag = 'new' | 'edited';

/**
 * Lay device-side records over a server list: queued creates first (flagged
 * `new`), queued edits applied on the matching row (flagged `edited`). A row the
 * cache already got from the optimistic write is replaced, never doubled.
 */
export function overlayRecords<T extends { id: string }>(
  items: readonly T[],
  records: readonly LocalRecord[],
  opts: { projectId?: string | null } = {},
): Array<T & { _offline?: OfflineFlag }> {
  const dirty = records.filter((r) => r.dirty);
  if (dirty.length === 0) return items as Array<T & { _offline?: OfflineFlag }>;
  const byServerId = new Map(dirty.filter((r) => r.serverId).map((r) => [r.serverId as string, r]));
  const localIds = new Set(dirty.map((r) => r.localId));
  const out: Array<T & { _offline?: OfflineFlag }> = [];
  for (const r of dirty) {
    if (r.serverId) continue;
    if (opts.projectId && r.projectId && r.projectId !== opts.projectId) continue;
    out.push({ ...(r.data as unknown as T), id: r.localId, _offline: 'new' });
  }
  for (const it of items) {
    if (localIds.has(it.id) && !byServerId.has(it.id)) continue;
    const rec = byServerId.get(it.id) ?? (localIds.has(it.id) ? dirty.find((r) => r.localId === it.id) : undefined);
    out.push(rec ? { ...it, ...(rec.data as object), id: it.id, _offline: 'edited' } : it);
  }
  return out;
}

/* ── Counting ──────────────────────────────────────────────────────────── */

export async function refreshSyncCounts(): Promise<void> {
  const ops = await getRecordQueue().pending();
  const conflicts = ops.filter((o) => o.conflict).length;
  patchOfflineSync({
    pending: ops.length,
    conflicts,
    photos: ops.filter((o) => o.meta?.action === 'photo').length,
    online: isOnline(),
  });
}

/** Drop records the server has caught up with; flag the rest dirty. */
async function reconcileRecords(): Promise<void> {
  const store = getOfflineStore();
  const ops = await getRecordQueue().pending();
  const pendingKeys = new Set(ops.map((o) => (typeof o.meta?.recordKey === 'string' ? o.meta.recordKey : '')));
  const opText = ops.map((o) => `${o.path} ${JSON.stringify(o.body ?? '')}`);
  for (const rec of await store.listRecords()) {
    const stillQueued = pendingKeys.has(recordKeyOf(rec.kind, rec.localId));
    // A synced record is kept while a queued op still names its temporary id
    // (an entry on a diary created offline needs the diary's server id).
    const referenced = isLocalId(rec.localId) && opText.some((t) => t.includes(rec.localId));
    if (!stillQueued && !referenced && rec.serverId) await store.deleteRecord(rec.kind, rec.localId);
    else if (rec.dirty !== stillQueued) await store.putRecord({ ...rec, dirty: stillQueued });
  }
  notifyRecordsChanged();
}

/* ── Drain ─────────────────────────────────────────────────────────────── */

let syncInFlight: Promise<DrainSummary | null> | null = null;

/**
 * Replay the queue once. `manual` ignores backoff (the user pressed "sync now").
 * Concurrent calls share one run.
 */
export function runSync(opts: { manual?: boolean } = {}): Promise<DrainSummary | null> {
  if (syncInFlight) return syncInFlight;
  syncInFlight = (async () => {
    patchOfflineSync({ online: isOnline() });
    if (!isOnline()) {
      await refreshSyncCounts();
      return null;
    }
    patchOfflineSync({ syncing: true });
    try {
      const q = getRecordQueue();
      const summary = await q.drain({ ignoreBackoff: opts.manual });
      const prev = useOfflineSyncStore.getState();
      const problems = [...prev.problems];
      const touched = new Set(prev.dirtyKinds);
      for (const r of summary.results) {
        const root = r.kind.split(':')[0] as OfflineEntityKind;
        if (r.status === 'applied' || r.status === 'merge_conflict') touched.add(root);
        if (r.status === 'rejected' && !problems.some((p) => p.clientOpId === r.clientOpId)) {
          problems.push({ clientOpId: r.clientOpId, kind: r.kind, detail: r.detail, httpStatus: r.httpStatus });
        }
      }
      patchOfflineSync({ problems, dirtyKinds: [...touched] });
      await autoMergeConflicts();
      await reconcileRecords();
      await refreshSyncCounts();
      const left = useOfflineSyncStore.getState();
      if (summary.results.length > 0) {
        patchOfflineSync({ syncedTick: left.syncedTick + 1 });
      }
      if (left.pending === 0 && summary.retry === 0) patchOfflineSync({ lastSyncAt: Date.now() });
      return summary;
    } finally {
      patchOfflineSync({ syncing: false });
    }
  })().finally(() => {
    syncInFlight = null;
  });
  return syncInFlight;
}

/* ── Conflicts ─────────────────────────────────────────────────────────── */

export interface ConflictView {
  op: QueuedOp;
  kind: OfflineEntityKind;
  recordId: string;
  /** Short label for the record, from the device copy. */
  label: string;
  merge: ThreeWayMergeResult;
}

function patchOf(op: QueuedOp): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries((op.body as Record<string, unknown>) ?? {})) {
    if (!SERVER_ONLY.has(k)) out[k] = v;
  }
  return out;
}

async function buildConflictView(op: QueuedOp): Promise<ConflictView | null> {
  const kind = op.meta?.entity as OfflineEntityKind | undefined;
  const recordId = typeof op.meta?.localId === 'string' ? op.meta.localId : null;
  if (!kind || !recordId || !op.conflict) return null;
  const rec = await getOfflineStore().getRecord(kind, recordId);
  const theirs = (op.conflict.current as Record<string, unknown> | undefined) ?? {};
  const merge = computeThreeWayMerge({
    base: rec?.serverSnapshot ?? null,
    mine: patchOf(op),
    theirs,
    spec: ENTITY_CONFIG[kind].spec,
  });
  const data = (rec?.data ?? theirs) as Record<string, unknown>;
  const label = String(data.title ?? data.inspection_number ?? data.diary_date ?? data.name ?? recordId);
  return { op, kind, recordId, label, merge };
}

export async function listConflicts(): Promise<ConflictView[]> {
  const views: ConflictView[] = [];
  for (const op of await getRecordQueue().conflicts()) {
    const v = await buildConflictView(op);
    if (v) views.push(v);
  }
  return views;
}

/**
 * POST the merge. `fields` holds the final value of every field this device
 * edited; `resolutions` says which side each came from.
 */
export async function postMerge(
  view: ConflictView,
  merged: ThreeWayMergeResult,
  deps: { fetcher?: Fetcher } = {},
): Promise<'merged' | 'stale' | 'error'> {
  const fetcher = deps.fetcher ?? fetchWithAuth;
  const store = getOfflineStore();
  const rec = await store.getRecord(view.kind, view.recordId);
  const serverId = rec?.serverId ?? view.recordId;
  const theirs = (view.op.conflict?.current as Record<string, unknown> | undefined) ?? {};
  const against =
    view.op.conflict?.currentVersion ?? (typeof theirs.version === 'number' ? theirs.version : undefined);
  try {
    const res = await fetcher(`/api${mergePath(view.kind, serverId)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-DDC-Client': 'OE/1.0' },
      body: JSON.stringify({
        base_version: rec?.baseVersion ?? 0,
        against_version: against,
        fields: merged.fields,
        resolutions: merged.resolutions,
        device_id: getDeviceId(),
      }),
    });
    if (res.ok) {
      const data = (await readJson(res)) as Record<string, unknown> | null;
      if (rec && data) {
        await store.putRecord({
          ...rec,
          serverId: typeof data.id === 'string' ? data.id : serverId,
          baseVersion: typeof data.version === 'number' ? data.version : rec.baseVersion,
          serverSnapshot: data,
          data: { ...rec.data, ...merged.fields },
          updatedAt: Date.now(),
        });
      }
      await getRecordQueue().resolveMergeConflict(view.op.clientOpId);
      await reconcileRecords();
      await refreshSyncCounts();
      patchOfflineSync({
        dirtyKinds: [...new Set([...useOfflineSyncStore.getState().dirtyKinds, view.kind])],
        syncedTick: useOfflineSyncStore.getState().syncedTick + 1,
        lastSyncAt: Date.now(),
      });
      return 'merged';
    }
    if (res.status === 409) {
      // The server moved again while the merge was in flight: refresh theirs.
      const c = classifyConflictBody(await readJson(res));
      if (c.isVersionConflict) {
        await getRecordQueue().markConflict(view.op.clientOpId, {
          message: c.message,
          currentVersion: c.currentVersion,
          current: c.current,
        });
        return 'stale';
      }
    }
    return 'error';
  } catch {
    return 'error';
  }
}

/** Resolve conflicts that need no human: simple fields, text edited on one side. */
export async function autoMergeConflicts(): Promise<number> {
  let n = 0;
  for (const view of await listConflicts()) {
    if (view.merge.conflicts.length > 0) continue;
    if ((await postMerge(view, view.merge)) === 'merged') n += 1;
  }
  return n;
}

/** Apply the user's picks from the dialog and post the merge. */
export async function resolveConflict(
  view: ConflictView,
  decisions: ConflictDecisions,
): Promise<'merged' | 'stale' | 'error' | 'incomplete'> {
  const merged = applyDecisions(view.merge, decisions);
  if (merged.conflicts.length > 0) return 'incomplete';
  return postMerge(view, merged);
}

/** Give up this device's edit and keep the server copy. */
export async function discardConflict(view: ConflictView): Promise<void> {
  const store = getOfflineStore();
  const rec = await store.getRecord(view.kind, view.recordId);
  const theirs = view.op.conflict?.current as Record<string, unknown> | undefined;
  if (rec && theirs) {
    await store.putRecord({
      ...rec,
      serverSnapshot: theirs,
      baseVersion: typeof theirs.version === 'number' ? theirs.version : rec.baseVersion,
      data: theirs,
    });
  }
  await getRecordQueue().resolveMergeConflict(view.op.clientOpId);
  await reconcileRecords();
  await refreshSyncCounts();
  patchOfflineSync({ syncedTick: useOfflineSyncStore.getState().syncedTick + 1 });
}

/* ── Merge history ─────────────────────────────────────────────────────── */

export interface MergeAuditRow {
  id?: string;
  created_at?: string;
  device_id?: string | null;
  user_id?: string | null;
  base_version?: number | null;
  against_version?: number | null;
  resolutions?: Record<string, string> | null;
  fields?: Record<string, unknown> | null;
}

export async function fetchMergeAudit(kind: OfflineEntityKind, id: string): Promise<MergeAuditRow[]> {
  const res = await apiGet<MergeAuditRow[] | { items: MergeAuditRow[] }>(mergeAuditPath(kind, id));
  return Array.isArray(res) ? res : (res?.items ?? []);
}
