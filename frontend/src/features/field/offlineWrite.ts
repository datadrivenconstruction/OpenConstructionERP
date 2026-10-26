// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Write-through helpers for the registers that work offline​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.
 *
 * Online, the request goes out as before. Offline, or when it fails without an
 * HTTP answer, the write is kept on the device and queued, and the caller gets
 * back the optimistic object so the screen carries on. A version conflict on an
 * online update is queued too: the drain then parks it for a merge.
 */

import { isOnline } from '@/shared/lib/offline/connectivity';
import { newClientOpId } from '@/shared/lib/offline/mutationQueue';
import type { OfflineEntityKind } from '@/shared/lib/offline/offlineStore';
import {
  classifyConflictBody,
  isNetworkError,
  queueCreate,
  queueUpdate,
  runSync,
  type UpdateBase,
} from '@/shared/lib/offline/recordSync';

export type WithOfflineFlag<T> = T & { _offline?: 'new' | 'edited' };

export interface CreateOrQueueOptions<T> {
  kind: OfflineEntityKind;
  payload: Record<string, unknown>;
  projectId?: string | null;
  /** Online path. Receives the payload with `client_op_id` set. */
  send: (payload: Record<string, unknown>) => Promise<T>;
  /** The object to show until the server's copy exists. */
  optimistic: (localId: string) => T;
}

export async function createOrQueue<T extends { id: string }>(
  opts: CreateOrQueueOptions<T>,
): Promise<WithOfflineFlag<T>> {
  // One key for the online try and the queued retry: the server dedups on it, so
  // a request that landed but lost its answer is not created twice.
  const clientOpId = newClientOpId();
  const payload = { ...opts.payload, client_op_id: clientOpId };
  const keep = async () => {
    const rec = await queueCreate(opts.kind, payload, (id) => opts.optimistic(id) as Record<string, unknown>, opts.projectId, {
      clientOpId,
    });
    return { ...(rec.data as unknown as T), id: rec.localId, _offline: 'new' as const };
  };
  if (!isOnline()) return keep();
  try {
    return await opts.send(payload);
  } catch (err) {
    if (isNetworkError(err)) return keep();
    throw err;
  }
}

export interface UpdateOrQueueOptions<T> {
  kind: OfflineEntityKind;
  base: UpdateBase;
  patch: Record<string, unknown>;
  /** Online path. `version` is the one the UI holds, for `If-Match`. */
  send: (patch: Record<string, unknown>, version?: number) => Promise<T>;
  /** Current object, shown with the patch applied when the write is queued. */
  current: T;
}

function isVersionConflictError(err: unknown): boolean {
  const e = err as { status?: number; body?: unknown } | null;
  return !!e && e.status === 409 && classifyConflictBody(e.body).isVersionConflict;
}

export async function updateOrQueue<T extends { id: string }>(
  opts: UpdateOrQueueOptions<T>,
): Promise<WithOfflineFlag<T>> {
  const keep = async () => {
    const rec = await queueUpdate(opts.kind, opts.base, opts.patch);
    return { ...opts.current, ...(rec.data as object), id: opts.current.id, _offline: 'edited' as const } as WithOfflineFlag<T>;
  };
  // A record that only exists on this device cannot be patched on the server yet.
  if (!isOnline() || opts.base.id.startsWith('local-')) return keep();
  try {
    return await opts.send(opts.patch, opts.base.version ?? undefined);
  } catch (err) {
    if (isNetworkError(err)) return keep();
    if (isVersionConflictError(err)) {
      const kept = await keep();
      // The drain hits the same 409 and parks the op with the server's copy.
      void runSync({ manual: true });
      return kept;
    }
    throw err;
  }
}
