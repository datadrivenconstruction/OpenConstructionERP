/**
 * API client for the real-time collaboration-locks module (layer 1).
 *
 * Layer 1 is pessimistic row-level locking: a user acquires a lock
 * before editing an entity, heartbeats it every ~15 seconds while the
 * edit is in progress, and releases it on blur / commit / cancel.  If
 * someone else holds the lock, the server returns 409 with a
 * CollabLockConflict body so the UI can show a friendly toast.
 *
 * The WebSocket channel at /api/v1/collaboration_locks/presence/ is
 * handled in usePresenceWebSocket.ts — this file is HTTP only.
 */

import { ApiError, apiDelete, apiGet, apiPost } from '@/shared/lib/api';

// ── Types ────────────────────────────────────────────────────────────────

export interface CollabLock {
  id: string;
  entity_type: string;
  entity_id: string;
  user_id: string;
  user_name: string;
  locked_at: string;
  heartbeat_at: string;
  expires_at: string;
  remaining_seconds: number;
}

export interface CollabLockConflict {
  detail: string;
  current_holder_user_id: string;
  current_holder_name: string;
  locked_at: string;
  expires_at: string;
  remaining_seconds: number;
}

export type AcquireResult =
  | { ok: true; lock: CollabLock }
  | { ok: false; conflict: CollabLockConflict };

// ── Request helpers ──────────────────────────────────────────────────────

const BASE = '/v1/collaboration_locks';

/**
 * Attempt to acquire a lock on an entity.
 *
 * Returns a tagged union: the caller can branch on `result.ok` to
 * decide whether to start editing (ok === true) or show a conflict
 * toast (ok === false).
 *
 * On network errors the promise rejects and the caller should fall
 * back to "unknown state" — do NOT auto-release anything.
 */
export async function acquireLock(
  entityType: string,
  entityId: string,
  ttlSeconds = 60,
): Promise<AcquireResult> {
  try {
    const lock = await apiPost<CollabLock>(`${BASE}/`, {
      entity_type: entityType,
      entity_id: entityId,
      ttl_seconds: ttlSeconds,
    });
    return { ok: true, lock };
  } catch (err) {
    if (err instanceof ApiError && err.status === 409 && err.body) {
      return { ok: false, conflict: err.body as CollabLockConflict };
    }
    throw err;
  }
}

/** Extend the TTL on a lock we already hold. */
export async function heartbeatLock(
  lockId: string,
  extendSeconds = 30,
): Promise<CollabLock> {
  return apiPost<CollabLock>(`${BASE}/${lockId}/heartbeat/`, {
    extend_seconds: extendSeconds,
  });
}

/** Release a lock.  204 on success, idempotent. */
export async function releaseLock(lockId: string): Promise<void> {
  await apiDelete<void>(`${BASE}/${lockId}/`);
}

/** Read the current holder of an entity (or null if free). */
export async function getEntityLock(
  entityType: string,
  entityId: string,
): Promise<CollabLock | null> {
  const params = new URLSearchParams({
    entity_type: entityType,
    entity_id: entityId,
  });
  return apiGet<CollabLock | null>(`${BASE}/entity/?${params.toString()}`);
}

/** Locks currently held by the calling user.  Useful for "release all
 * on logout" flows. */
export async function listMyLocks(): Promise<CollabLock[]> {
  return apiGet<CollabLock[]>(`${BASE}/my/`);
}
