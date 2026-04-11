/**
 * useEntityLock — React hook wrapping the layer-1 collaboration-locks API.
 *
 * Responsibilities
 * ----------------
 *
 * * Acquire a lock on mount when `autoAcquire` is true.
 * * Heartbeat every 15s while the lock is held.
 * * Release on unmount (fire-and-forget so the unmount is not blocked).
 * * Expose imperative `acquire()` / `release()` so consumers can wire
 *   the hook to focus/blur events instead of lifecycle if they prefer.
 *
 * The hook never throws — every network failure becomes a state
 * transition (`state === 'error'`) and a toast.  Consumers should
 * never render "lock failed" modal dialogs; a broken lock subsystem
 * must still allow read-only viewing.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { useToastStore } from '@/stores/useToastStore';
import i18n from '@/app/i18n';

import {
  acquireLock as apiAcquire,
  heartbeatLock as apiHeartbeat,
  releaseLock as apiRelease,
  type CollabLock,
  type CollabLockConflict,
} from './api';

export type EntityLockState =
  | 'idle'
  | 'acquiring'
  | 'held'
  | 'conflict'
  | 'released'
  | 'error';

export interface UseEntityLockOptions {
  /** If true, call `acquire()` on mount / entity change. */
  autoAcquire?: boolean;
  /** TTL to request on acquire.  Defaults to 60s. */
  ttlSeconds?: number;
  /** Interval between heartbeats while held.  Defaults to 15s. */
  heartbeatIntervalMs?: number;
}

export interface UseEntityLockResult {
  state: EntityLockState;
  lock: CollabLock | null;
  conflict: CollabLockConflict | null;
  acquire: () => Promise<void>;
  release: () => Promise<void>;
}

const DEFAULT_HEARTBEAT_MS = 15_000;

/**
 * Wire a component's lifecycle to a single entity's soft lock.
 *
 * Passing `entityId === null` leaves the hook idle — useful while
 * the parent is still loading the id from the URL.
 */
export function useEntityLock(
  entityType: string,
  entityId: string | null,
  opts: UseEntityLockOptions = {},
): UseEntityLockResult {
  const {
    autoAcquire = false,
    ttlSeconds = 60,
    heartbeatIntervalMs = DEFAULT_HEARTBEAT_MS,
  } = opts;

  const [state, setState] = useState<EntityLockState>('idle');
  const [lock, setLock] = useState<CollabLock | null>(null);
  const [conflict, setConflict] = useState<CollabLockConflict | null>(null);

  const lockRef = useRef<CollabLock | null>(null);
  const heartbeatTimerRef = useRef<number | null>(null);
  const addToast = useToastStore((s) => s.addToast);

  const clearHeartbeat = useCallback(() => {
    if (heartbeatTimerRef.current !== null) {
      window.clearInterval(heartbeatTimerRef.current);
      heartbeatTimerRef.current = null;
    }
  }, []);

  const startHeartbeat = useCallback(
    (extendSeconds: number) => {
      clearHeartbeat();
      heartbeatTimerRef.current = window.setInterval(async () => {
        const current = lockRef.current;
        if (current === null) return;
        try {
          const refreshed = await apiHeartbeat(current.id, extendSeconds);
          lockRef.current = refreshed;
          setLock(refreshed);
        } catch {
          // Lost the lock under our feet (network drop, server
          // restart, sweeper removed us).  Transition to 'released'
          // so the consumer re-acquires on the next focus event.
          clearHeartbeat();
          lockRef.current = null;
          setLock(null);
          setState('released');
        }
      }, heartbeatIntervalMs);
    },
    [clearHeartbeat, heartbeatIntervalMs],
  );

  const acquire = useCallback(async () => {
    if (entityId === null) return;
    setState('acquiring');
    setConflict(null);
    try {
      const result = await apiAcquire(entityType, entityId, ttlSeconds);
      if (result.ok) {
        lockRef.current = result.lock;
        setLock(result.lock);
        setState('held');
        // Extend by roughly 2× the heartbeat interval so a missed
        // heartbeat does not immediately expire the lock.
        startHeartbeat(Math.max(30, Math.ceil(heartbeatIntervalMs / 500)));
      } else {
        setConflict(result.conflict);
        setLock(null);
        lockRef.current = null;
        setState('conflict');
        addToast({
          type: 'warning',
          title: i18n.t('collab_locks.lock_conflict_title', {
            defaultValue: 'Someone is editing this',
          }),
          message: i18n.t('collab_locks.lock_conflict_toast', {
            defaultValue:
              'Locked by {{name}}. Try again in {{seconds}} seconds.',
            name: result.conflict.current_holder_name,
            seconds: result.conflict.remaining_seconds,
          }),
        });
      }
    } catch {
      setState('error');
      addToast({
        type: 'error',
        title: i18n.t('collab_locks.lock_error_title', {
          defaultValue: 'Collaboration service unavailable',
        }),
        message: i18n.t('collab_locks.lock_error_toast', {
          defaultValue:
            'Could not reach the lock service. You can still edit, but changes may conflict with other users.',
        }),
      });
    }
  }, [
    addToast,
    entityId,
    entityType,
    heartbeatIntervalMs,
    startHeartbeat,
    ttlSeconds,
  ]);

  const release = useCallback(async () => {
    const current = lockRef.current;
    clearHeartbeat();
    lockRef.current = null;
    setLock(null);
    setConflict(null);
    setState('released');
    if (current === null) return;
    try {
      await apiRelease(current.id);
    } catch {
      // Best-effort — a missed release will be reaped by the sweeper.
    }
  }, [clearHeartbeat]);

  // Auto-acquire on mount / entity change.
  useEffect(() => {
    if (!autoAcquire || entityId === null) return;
    void acquire();
    // Capture the current release function so the cleanup closes over
    // the *same* lock ref instance even after re-renders.
    return () => {
      const current = lockRef.current;
      clearHeartbeat();
      lockRef.current = null;
      if (current !== null) {
        // Fire-and-forget — unmount must not await a network call.
        apiRelease(current.id).catch(() => undefined);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoAcquire, entityId, entityType]);

  return { state, lock, conflict, acquire, release };
}
