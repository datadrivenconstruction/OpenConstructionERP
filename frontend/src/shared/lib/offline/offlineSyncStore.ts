// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Zustand store behind the sync pill​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠: one status for the whole device, plus the
 * counts that explain it. The sync engine (`recordSync.ts`) writes to it; React
 * only reads.
 */

import { create } from 'zustand';
import type { OfflineEntityKind } from './offlineStore';

export type OfflineSyncStatus = 'online-synced' | 'offline' | 'syncing' | 'pending' | 'error' | 'conflict';

export interface SyncProblem {
  clientOpId: string;
  kind: string;
  detail?: string;
  httpStatus?: number;
}

export interface OfflineSyncState {
  status: OfflineSyncStatus;
  online: boolean;
  syncing: boolean;
  /** Ops waiting to go (includes conflicted ones). */
  pending: number;
  /** Ops parked on a version conflict. */
  conflicts: number;
  /** Photos still on the device. */
  photos: number;
  /** Ops the server refused, until the user dismisses them. */
  problems: SyncProblem[];
  /** Epoch ms of the last drain that left nothing waiting. */
  lastSyncAt: number | null;
  /** Entity kinds whose server copy changed since the UI last refetched. */
  dirtyKinds: OfflineEntityKind[];
  /** Bumped when a conflict or sync outcome should re-run the UI queries. */
  syncedTick: number;
}

/**
 * Priority, highest first: a conflict needs a person, so it outranks everything;
 * offline explains why nothing moves; then the live activity; then the problems.
 */
export function deriveSyncStatus(s: {
  online: boolean;
  syncing: boolean;
  pending: number;
  conflicts: number;
  problems: number;
}): OfflineSyncStatus {
  if (s.conflicts > 0) return 'conflict';
  if (!s.online) return 'offline';
  if (s.syncing) return 'syncing';
  if (s.problems > 0) return 'error';
  if (s.pending > 0) return 'pending';
  return 'online-synced';
}

const initial: OfflineSyncState = {
  status: 'online-synced',
  online: true,
  syncing: false,
  pending: 0,
  conflicts: 0,
  photos: 0,
  problems: [],
  lastSyncAt: null,
  dirtyKinds: [],
  syncedTick: 0,
};

export const useOfflineSyncStore = create<OfflineSyncState>(() => ({ ...initial }));

/** Merge a partial change and recompute `status` in one set. */
export function patchOfflineSync(patch: Partial<Omit<OfflineSyncState, 'status'>>): void {
  useOfflineSyncStore.setState((prev) => {
    const next = { ...prev, ...patch };
    return {
      ...patch,
      status: deriveSyncStatus({
        online: next.online,
        syncing: next.syncing,
        pending: next.pending,
        conflicts: next.conflicts,
        problems: next.problems.length,
      }),
    };
  });
}

export function dismissSyncProblem(clientOpId: string): void {
  const problems = useOfflineSyncStore.getState().problems.filter((p) => p.clientOpId !== clientOpId);
  patchOfflineSync({ problems });
}

export function resetOfflineSyncStoreForTests(): void {
  useOfflineSyncStore.setState({ ...initial });
}
