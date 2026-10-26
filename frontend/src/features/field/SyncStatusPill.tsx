// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The sync status pill for the desktop registers that work offline (daily​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * diary, punch list, inspections). One glance answers "is my work safe":
 * synced, offline, syncing, N waiting, a problem, or a conflict that needs a
 * merge. Tapping it syncs now, or opens the merge dialog on a conflict.
 *
 * Mounting it also keeps the sync loop alive (`useOfflineSync`).
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CheckCircle2, CloudOff, GitMerge, Loader2, RefreshCw, X } from 'lucide-react';
import { useOfflineSync } from '@/shared/lib/offline/useOfflineSync';
import {
  discardConflict,
  listConflicts,
  resolveConflict,
  type ConflictView,
} from '@/shared/lib/offline/recordSync';
import type { OfflineSyncStatus } from '@/shared/lib/offline/offlineSyncStore';
import { MergeConflictDialog } from './MergeConflictDialog';

const TONE: Record<OfflineSyncStatus, string> = {
  'online-synced': 'bg-emerald-100 text-emerald-800',
  offline: 'bg-amber-100 text-amber-800',
  syncing: 'bg-sky-100 text-sky-800',
  pending: 'bg-sky-100 text-sky-800',
  error: 'bg-red-100 text-red-800',
  conflict: 'bg-orange-100 text-orange-900',
};

export interface SyncStatusPillProps {
  className?: string;
}

export function SyncStatusPill({ className = '' }: SyncStatusPillProps) {
  const { t } = useTranslation();
  const sync = useOfflineSync();
  const { status, pending, conflicts, problems, lastSyncAt } = sync;

  const [showProblems, setShowProblems] = useState(false);
  const [views, setViews] = useState<ConflictView[]>([]);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const loadConflicts = useCallback(async () => {
    setViews(await listConflicts());
  }, []);

  // Keep the conflict list current while there are conflicts.
  useEffect(() => {
    if (conflicts > 0) void loadConflicts();
    else {
      setViews([]);
      setDialogOpen(false);
    }
  }, [conflicts, loadConflicts]);

  const current = views.find((v) => v.merge.conflicts.length > 0) ?? null;

  const onClick = () => {
    if (status === 'conflict') {
      if (current) setDialogOpen(true);
      else void sync.syncNow();
      return;
    }
    if (status === 'error') {
      setShowProblems((v) => !v);
      return;
    }
    if (status === 'pending') void sync.syncNow();
  };

  const label = (() => {
    switch (status) {
      case 'online-synced':
        return t('offline_sync.status_synced', { defaultValue: 'Synced' });
      case 'offline':
        return t('offline_sync.status_offline', { defaultValue: 'Offline' });
      case 'syncing':
        return t('offline_sync.status_syncing', { defaultValue: 'Syncing…' });
      case 'error':
        return t('offline_sync.status_error', { defaultValue: 'Sync problem' });
      case 'conflict':
        return t('offline_sync.status_conflict', { defaultValue: 'Needs merge' });
      default:
        return t('offline_sync.status_pending', {
          count: pending,
          defaultValue_one: '{{count}} change waiting',
          defaultValue_other: '{{count}} changes waiting',
        });
    }
  })();

  const lastSync = lastSyncAt
    ? t('offline_sync.last_sync', {
        time: new Date(lastSyncAt).toLocaleTimeString(),
        defaultValue: 'Last sync {{time}}',
      })
    : t('offline_sync.never_synced', { defaultValue: 'Not synced yet in this session' });

  const Icon =
    status === 'online-synced'
      ? CheckCircle2
      : status === 'offline'
        ? CloudOff
        : status === 'syncing'
          ? Loader2
          : status === 'error'
            ? AlertTriangle
            : status === 'conflict'
              ? GitMerge
              : RefreshCw;

  const resolve = async (decisions: Parameters<typeof resolveConflict>[1]) => {
    if (!current) return;
    setBusy(true);
    try {
      await resolveConflict(current, decisions);
      await loadConflicts();
    } finally {
      setBusy(false);
    }
  };

  const keepTheirs = async () => {
    if (!current) return;
    setBusy(true);
    try {
      await discardConflict(current);
      await loadConflicts();
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`relative inline-flex ${className}`}>
      <button
        type="button"
        onClick={onClick}
        role="status"
        aria-live="polite"
        data-testid="sync-status-pill"
        data-state={status}
        title={lastSync}
        className={`inline-flex min-h-[44px] min-w-[44px] items-center justify-center gap-1.5 rounded-full px-3 text-xs font-semibold ${TONE[status]}`}
      >
        <Icon size={16} aria-hidden="true" className={status === 'syncing' ? 'animate-spin' : ''} />
        <span data-testid="sync-status-label">{label}</span>
      </button>

      {showProblems && status === 'error' && (
        <div
          data-testid="sync-problems"
          className="absolute right-0 top-full z-40 mt-1 w-72 max-w-[90vw] rounded-lg border border-border bg-surface-elevated p-2 shadow-lg"
        >
          <p className="px-1 pb-1 text-xs font-semibold text-content-primary">
            {t('offline_sync.problems_title', { defaultValue: 'The server refused these changes' })}
          </p>
          <ul className="space-y-1">
            {problems.map((p) => (
              <li key={p.clientOpId} className="flex items-start gap-2 rounded bg-surface-secondary p-2 text-xs">
                <span className="min-w-0 flex-1 break-words text-content-secondary">
                  {p.detail ?? t('offline_sync.problem_unknown', { defaultValue: 'Rejected by the server' })}
                </span>
                <button
                  type="button"
                  aria-label={t('offline_sync.dismiss', { defaultValue: 'Dismiss' })}
                  onClick={() => sync.dismissProblem(p.clientOpId)}
                  className="inline-flex min-h-[44px] min-w-[44px] items-center justify-center"
                >
                  <X size={14} aria-hidden="true" />
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}

      {current && (
        <MergeConflictDialog
          open={dialogOpen}
          recordLabel={current.label}
          conflicts={current.merge.conflicts}
          busy={busy}
          onResolve={(d) => void resolve(d)}
          onKeepTheirs={() => void keepTheirs()}
          onClose={() => setDialogOpen(false)}
        />
      )}
    </div>
  );
}

export default SyncStatusPill;
