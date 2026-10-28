// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Connectivity and the pending-entry queue, as one hook for the Field Time page.
 *
 * What it owes the person using it is honesty. A day recorded in a basement is
 * not saved, it is *pending*, and the difference matters: a foreman who thinks
 * the day is in the office will not look at it again. So the hook reports the
 * queue depth, drains on reconnect, and keeps the outcome of the last drain
 * broken out by kind - because "3 synced" and "3 synced, 1 refused" are
 * different sentences and only one of them needs somebody to act.
 *
 * The drain is deliberately not silent about refusals. An op the server will
 * never accept (the day was withdrawn, or the office approved it before the
 * correction arrived) leaves the queue, and if nothing said so the foreman's
 * correction would vanish with it.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useOnlineStatus } from '@/shared/hooks/useOnlineStatus';
import type { DrainSummary, QueuedOp } from '@/shared/lib/offline';
import { getFieldTimeQueue } from './offlineQueue';

/** Milliseconds to let a freshly restored link settle before draining. */
const SETTLE_MS = 800;

export interface FieldTimeOfflineSync {
  /** The browser's connectivity hint. Advisory: a captive portal can lie. */
  online: boolean;
  /** Entries still waiting to reach the server, oldest first. */
  pending: QueuedOp[];
  /** True while a drain is in flight. */
  syncing: boolean;
  /** The last drain's per-kind counts, or null if none has run this session. */
  lastSummary: DrainSummary | null;
  /** Drain now. Safe to call while one is already running; it short-circuits. */
  sync: () => Promise<void>;
  /** Re-read the queue depth without sending anything. */
  refresh: () => Promise<void>;
  /** Forget one queued op (the person chose to drop it). */
  discard: (clientOpId: string) => Promise<void>;
}

export function useFieldTimeOfflineSync(): FieldTimeOfflineSync {
  const online = useOnlineStatus();
  const [pending, setPending] = useState<QueuedOp[]>([]);
  const [syncing, setSyncing] = useState(false);
  const [lastSummary, setLastSummary] = useState<DrainSummary | null>(null);
  // Survives unmount so a drain that finishes after the page closes cannot set
  // state on a dead component.
  const mounted = useRef(true);

  const queue = useMemo(() => getFieldTimeQueue(), []);

  const refresh = useCallback(async () => {
    const ops = await queue.pending();
    if (mounted.current) setPending(ops);
  }, [queue]);

  const sync = useCallback(async () => {
    if (!mounted.current) return;
    setSyncing(true);
    try {
      const summary = await queue.drain();
      if (!mounted.current) return;
      // A short-circuited drain (one was already running) reports nothing at
      // all; showing "0 synced" then would be a lie about what happened.
      if (summary.results.length > 0) setLastSummary(summary);
    } finally {
      if (mounted.current) setSyncing(false);
      await refresh();
    }
  }, [queue, refresh]);

  const discard = useCallback(
    async (clientOpId: string) => {
      await queue.discard(clientOpId);
      await refresh();
    },
    [queue, refresh],
  );

  useEffect(() => {
    mounted.current = true;
    void refresh();
    const unsubscribe = queue.onChange(() => {
      void refresh();
    });
    return () => {
      mounted.current = false;
      unsubscribe();
    };
  }, [queue, refresh]);

  useEffect(() => {
    if (!online) return undefined;
    // Let the link settle: an `online` event fires the moment an interface
    // comes up, which on a site gate is often several seconds before anything
    // can actually be reached.
    const timer = setTimeout(() => {
      void sync();
    }, SETTLE_MS);
    return () => clearTimeout(timer);
  }, [online, sync]);

  return { online, pending, syncing, lastSummary, sync, refresh, discard };
}
