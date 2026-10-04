// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useSyncExternalStore } from 'react';
import i18next from 'i18next';
import {
  getQueuedMutations,
  removeMutation,
} from '../lib/offlineStore';
import { useToastStore } from '../../stores/useToastStore';
import { useAuthStore } from '../../stores/useAuthStore';

/* ── Online/Offline reactive store ──────────────────────────────────── */

let listeners: Array<() => void> = [];

function subscribe(listener: () => void) {
  listeners.push(listener);
  window.addEventListener('online', listener);
  window.addEventListener('offline', listener);
  return () => {
    listeners = listeners.filter((l) => l !== listener);
    window.removeEventListener('online', listener);
    window.removeEventListener('offline', listener);
  };
}

function getSnapshot() {
  return navigator.onLine;
}

/**
 * React hook that reactively tracks online/offline status.
 * Uses `useSyncExternalStore` for tear-free reads.
 */
export function useOnlineStatus(): boolean {
  return useSyncExternalStore(subscribe, getSnapshot, () => true);
}

/* ── Mutation replay ────────────────────────────────────────────────── */

let isReplaying = false;

/**
 * Replay queued offline mutations when back online.
 * Runs each mutation sequentially. Failed mutations stay in queue.
 */
async function replayMutations(): Promise<{ replayed: number; failed: number }> {
  if (isReplaying) return { replayed: 0, failed: 0 };
  isReplaying = true;

  let replayed = 0;
  let failed = 0;

  try {
    const queue = await getQueuedMutations();
    if (queue.length === 0) return { replayed: 0, failed: 0 };

    const token = useAuthStore.getState().accessToken;
    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };
    if (token) headers['Authorization'] = `Bearer ${token}`;

    for (const mutation of queue) {
      try {
        const res = await fetch(`/api${mutation.path}`, {
          method: mutation.method,
          headers,
          body: mutation.body ? JSON.stringify(mutation.body) : undefined,
        });
        if (res.ok || res.status === 409) {
          // Success or conflict (already applied) — remove from queue
          await removeMutation(mutation.id!);
          replayed++;
        } else {
          failed++;
        }
      } catch {
        failed++;
      }
    }
  } finally {
    isReplaying = false;
  }

  return { replayed, failed };
}

/**
 * Hook that automatically replays offline mutations when coming back online.
 */
export function useOfflineSync(): void {
  const isOnline = useOnlineStatus();
  const addToast = useToastStore((s) => s.addToast);

  useEffect(() => {
    if (!isOnline) return;

    // Small delay to let network stabilize
    const timer = setTimeout(async () => {
      const { replayed, failed } = await replayMutations();
      // `i18next.t` rather than a hook's `t`: a language switch must not
      // re-run this effect, because re-running it schedules another replay.
      if (replayed > 0) {
        addToast({
          type: 'success',
          title: i18next.t('offline.synced_changes', {
            count: replayed,
            defaultValue_one: 'Synced {{count}} offline change',
            defaultValue_other: 'Synced {{count}} offline changes',
          }),
        });
      }
      if (failed > 0) {
        addToast({
          type: 'warning',
          title: i18next.t('offline.failed_changes', {
            count: failed,
            defaultValue_one: '{{count}} change failed to sync',
            defaultValue_other: '{{count}} changes failed to sync',
          }),
        });
      }
    }, 1000);

    return () => clearTimeout(timer);
  }, [isOnline, addToast]);
}
