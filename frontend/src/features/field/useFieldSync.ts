// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Field offline-sync hook.
 *
 * The field equivalent of the desktop `useOfflineSync`, but it runs inside the
 * field shell (`/field`) which deliberately does not mount `AppLayout`. It:
 *
 *   - tracks connectivity via the framework-light connectivity store,
 *   - drains the field mutation queue FIFO when the device comes back online,
 *   - exposes the live pending count for the "N pending sync" badge,
 *   - surfaces per-item success/failure from the last drain so the UI can show
 *     "M synced, K conflicts" and offer a review path.
 *
 * Correctness (no duplicate rows on a double drain) comes from the queue's
 * `clientOpId` dedup plus the server-side idempotency ledger, not from this
 * hook; the hook only schedules drains.
 */

import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import {
  getFieldQueue,
  subscribeConnectivity,
  isOnline,
  type DrainResult,
  type DrainSummary,
  type EnqueueInput,
  type FieldHeadersProvider,
  type QueuedOp,
} from '@/shared/lib/offline';

/* ── Connectivity hook ─────────────────────────────────────────────────── */

/** Reactive online/offline status backed by the connectivity store. */
export function useConnectivity(): boolean {
  return useSyncExternalStore(
    (cb) => subscribeConnectivity(() => cb()),
    () => isOnline(),
    () => true,
  );
}

/* ── Field sync hook ───────────────────────────────────────────────────── */

export interface FieldSyncState {
  online: boolean;
  /** Number of captured writes still awaiting replay (drives the badge). */
  pending: number;
  /**
   * The captured writes still awaiting replay, in FIFO order. Drives the
   * pending-sync review panel (item type, time, status, retry count). Kept in
   * sync with `pending` via the queue's change events.
   */
  pendingOps: QueuedOp[];
  /** True while a drain is running. */
  syncing: boolean;
  /** Per-item outcomes from the most recent drain (for the review surface). */
  lastResults: DrainResult[];
  /** Capture a write: queue it now, replayed on reconnect / next drain. */
  enqueue: (input: EnqueueInput) => Promise<void>;
  /** Force a drain attempt (e.g. a manual "sync now" button). */
  syncNow: () => Promise<DrainSummary | null>;
  /** Drop a single queued/conflicted op. */
  discard: (clientOpId: string) => Promise<void>;
}

const DRAIN_DEBOUNCE_MS = 1000;

/**
 * Mount the field sync loop. Pass a headers provider that returns the field
 * session auth headers (Bearer session token + `X-Field-PIN`); these are
 * attached to every replayed request.
 */
export function useFieldSync(getHeaders: FieldHeadersProvider): FieldSyncState {
  const online = useConnectivity();
  const [pending, setPending] = useState(0);
  const [pendingOps, setPendingOps] = useState<QueuedOp[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [lastResults, setLastResults] = useState<DrainResult[]>([]);

  const queue = getFieldQueue(getHeaders);

  const refreshPending = useCallback(async () => {
    // Pull the full op list once and derive the count from it so the badge and
    // the review panel can never disagree (single source of truth per refresh).
    const ops = await queue.pending();
    setPendingOps(ops);
    setPending(ops.length);
  }, [queue]);

  const syncNow = useCallback(async (): Promise<DrainSummary | null> => {
    if (!isOnline()) return null;
    setSyncing(true);
    try {
      const summary = await queue.drain();
      if (summary.results.length > 0) {
        setLastResults(summary.results);
      }
      await refreshPending();
      return summary;
    } finally {
      setSyncing(false);
    }
  }, [queue, refreshPending]);

  const enqueue = useCallback(
    async (input: EnqueueInput) => {
      await queue.enqueue(input);
      await refreshPending();
      // If we are online, try to flush straight away; offline, it stays queued.
      if (isOnline()) {
        void syncNow();
      }
    },
    [queue, refreshPending, syncNow],
  );

  const discard = useCallback(
    async (clientOpId: string) => {
      await queue.discard(clientOpId);
      await refreshPending();
    },
    [queue, refreshPending],
  );

  // Keep the badge in sync with queue-size changes from any source.
  useEffect(() => {
    void refreshPending();
    const unsub = queue.onChange(() => {
      void refreshPending();
    });
    return unsub;
  }, [queue, refreshPending]);

  // Drain shortly after coming online (debounced to let the link settle).
  useEffect(() => {
    if (!online) return undefined;
    const timer = setTimeout(() => {
      void syncNow();
    }, DRAIN_DEBOUNCE_MS);
    return () => clearTimeout(timer);
  }, [online, syncNow]);

  return { online, pending, pendingOps, syncing, lastResults, enqueue, syncNow, discard };
}
