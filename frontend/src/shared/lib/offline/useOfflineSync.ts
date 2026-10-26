// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * React side of the record sync engine​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠.
 *
 * `useOfflineSync()` is safe to call from several components at once: a
 * reference count keeps a single sync loop alive (reconnect, interval, tab
 * focus) no matter how many pills or pages mount it. It returns the live store
 * state and the on-demand actions.
 *
 * Not to be confused with `useOfflineSync` in `shared/hooks/useOnlineStatus.ts`,
 * which replays the older generic write queue.
 */

import { useCallback, useEffect, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { isOnline, subscribeConnectivity } from './connectivity';
import { ENTITY_CONFIG, onRecordsChanged, refreshSyncCounts, runSync } from './recordSync';
import { getOfflineStore, type LocalRecord, type OfflineEntityKind } from './offlineStore';
import {
  dismissSyncProblem,
  patchOfflineSync,
  useOfflineSyncStore,
  type OfflineSyncState,
} from './offlineSyncStore';

const SYNC_INTERVAL_MS = 30_000;
const RECONNECT_DEBOUNCE_MS = 1000;

let consumers = 0;
let stopLoop: (() => void) | null = null;

function startLoop(): () => void {
  patchOfflineSync({ online: isOnline() });
  void refreshSyncCounts();
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  const unsubConn = subscribeConnectivity((online) => {
    patchOfflineSync({ online });
    if (reconnectTimer) clearTimeout(reconnectTimer);
    if (online) {
      // Let the link settle before the first request.
      reconnectTimer = setTimeout(() => void runSync({ manual: true }), RECONNECT_DEBOUNCE_MS);
    }
  });
  const interval = setInterval(() => void runSync(), SYNC_INTERVAL_MS);
  // Work waiting from a previous session goes out at once.
  if (isOnline()) void runSync();

  return () => {
    unsubConn();
    clearInterval(interval);
    if (reconnectTimer) clearTimeout(reconnectTimer);
  };
}

export interface OfflineSyncApi extends OfflineSyncState {
  /** Drain now, ignoring backoff. */
  syncNow: () => Promise<void>;
  dismissProblem: (clientOpId: string) => void;
}

/**
 * The sync loop alone, for a layout that must not re-render on every status
 * change. It re-renders only when a drain changed server data.
 */
export function useOfflineSyncLoop(): void {
  const tick = useOfflineSyncStore((s) => s.syncedTick);
  const qc = useQueryClient();

  useEffect(() => {
    consumers += 1;
    if (consumers === 1) stopLoop = startLoop();
    return () => {
      consumers -= 1;
      if (consumers === 0 && stopLoop) {
        stopLoop();
        stopLoop = null;
      }
    };
  }, []);

  // A drain changed server data: refetch the lists the affected kinds feed.
  useEffect(() => {
    if (tick === 0) return;
    const kinds = useOfflineSyncStore.getState().dirtyKinds;
    if (kinds.length === 0) return;
    for (const k of kinds) {
      for (const root of ENTITY_CONFIG[k]?.queryRoots ?? []) {
        void qc.invalidateQueries({ queryKey: root });
      }
    }
    patchOfflineSync({ dirtyKinds: [] });
  }, [tick, qc]);
}

export function useOfflineSync(): OfflineSyncApi {
  const state = useOfflineSyncStore();
  useOfflineSyncLoop();

  const syncNow = useCallback(async () => {
    await runSync({ manual: true });
  }, []);

  return { ...state, syncNow, dismissProblem: dismissSyncProblem };
}

/**
 * Device-side records of one kind that still await sync, for overlaying on a
 * server list. Re-reads whenever a capture or a drain changes them.
 */
export function useOfflineRecords(kind: OfflineEntityKind): LocalRecord[] {
  const [records, setRecords] = useState<LocalRecord[]>([]);
  useEffect(() => {
    let alive = true;
    const load = () => {
      void getOfflineStore()
        .listRecords(kind)
        .then((rs) => {
          if (alive) setRecords(rs.filter((r) => r.dirty));
        });
    };
    load();
    const off = onRecordsChanged(load);
    return () => {
      alive = false;
      off();
    };
  }, [kind]);
  return records;
}
