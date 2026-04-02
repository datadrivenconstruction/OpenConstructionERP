import { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Clock, RotateCcw, Loader2, Save } from 'lucide-react';
import clsx from 'clsx';
import { boqApi, type BOQSnapshot } from './api';
import { useToastStore } from '@/stores/useToastStore';

/* ── Snapshot diff helpers ─────────────────────────────────────────────── */

interface SnapshotDiff {
  positionDelta: number | null;
  totalDelta: number | null;
  trend: 'up' | 'down' | 'neutral';
}

/**
 * Compute diff between a snapshot and the one that came before it.
 * Snapshots are assumed to be sorted newest-first (index 0 = latest).
 * We compare snapshot[i] against snapshot[i+1] (the older one).
 */
function computeSnapshotDiffs(snapshots: BOQSnapshot[]): Map<string, SnapshotDiff> {
  const diffs = new Map<string, SnapshotDiff>();

  for (let i = 0; i < snapshots.length; i++) {
    const current = snapshots[i]!;
    const previous = snapshots[i + 1]; // older snapshot

    if (!previous) {
      // Oldest snapshot — no diff to show
      diffs.set(current.id, { positionDelta: null, totalDelta: null, trend: 'neutral' });
      continue;
    }

    const positionDelta =
      current.position_count != null && previous.position_count != null
        ? current.position_count - previous.position_count
        : null;

    const totalDelta =
      current.grand_total != null && previous.grand_total != null
        ? current.grand_total - previous.grand_total
        : null;

    let trend: 'up' | 'down' | 'neutral' = 'neutral';
    if ((positionDelta != null && positionDelta > 0) || (totalDelta != null && totalDelta > 0)) {
      trend = 'up';
    } else if (
      (positionDelta != null && positionDelta < 0) ||
      (totalDelta != null && totalDelta < 0)
    ) {
      trend = 'down';
    }

    diffs.set(current.id, { positionDelta, totalDelta, trend });
  }

  return diffs;
}

interface VersionHistoryDrawerProps {
  boqId: string;
  isOpen: boolean;
  onClose: () => void;
}

export function VersionHistoryDrawer({ boqId, isOpen, onClose }: VersionHistoryDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState('');
  const [confirmRestoreId, setConfirmRestoreId] = useState<string | null>(null);

  const { data: snapshots, isLoading, isError } = useQuery({
    queryKey: ['boq-snapshots', boqId],
    queryFn: () => boqApi.getSnapshots(boqId),
    enabled: isOpen && !!boqId,
  });

  // Close on Escape
  useEffect(() => {
    if (!isOpen) return;
    function handleKeyDown(e: KeyboardEvent) {
      if (e.key === 'Escape') { e.preventDefault(); onClose(); }
    }
    document.addEventListener('keydown', handleKeyDown, { capture: true });
    return () => document.removeEventListener('keydown', handleKeyDown, { capture: true });
  }, [isOpen, onClose]);

  const createMutation = useMutation({
    mutationFn: (label?: string) => boqApi.createSnapshot(boqId, label),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq-snapshots', boqId] });
      setNewLabel('');
      useToastStore.getState().addToast({
        type: 'success',
        title: t('boq.snapshot_created', { defaultValue: 'Snapshot saved' }),
      });
    },
    onError: () => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.snapshot_failed', { defaultValue: 'Failed to save snapshot' }),
      });
    },
  });

  const restoreMutation = useMutation({
    mutationFn: (snapshotId: string) => boqApi.restoreSnapshot(boqId, snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-snapshots', boqId] });
      setConfirmRestoreId(null);
      useToastStore.getState().addToast({
        type: 'success',
        title: t('boq.snapshot_restored', { defaultValue: 'Snapshot restored' }),
      });
    },
    onError: () => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.restore_failed', { defaultValue: 'Failed to restore snapshot' }),
      });
    },
  });

  const handleCreate = useCallback(() => {
    createMutation.mutate(newLabel.trim() || undefined);
  }, [createMutation, newLabel]);

  const formatDate = useCallback((dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(undefined, {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  }, []);

  const fmt = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

  const fmtSigned = new Intl.NumberFormat(undefined, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
    signDisplay: 'always',
  });

  const snapshotDiffs = useMemo(
    () => computeSnapshotDiffs(snapshots ?? []),
    [snapshots],
  );

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />

      {/* Drawer */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.version_history', { defaultValue: 'Version History' })}
        className="relative ml-auto flex h-full w-80 flex-col bg-surface-elevated border-l border-border shadow-2xl animate-slide-in-right"
      >
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <div className="flex items-center gap-2">
            <Clock size={16} className="text-oe-blue" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('boq.version_history', { defaultValue: 'Version History' })}
            </h3>
          </div>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:text-content-primary hover:bg-surface-secondary transition-colors"
          >
            <X size={16} />
          </button>
        </div>

        {/* Create snapshot */}
        <div className="border-b border-border p-3">
          <div className="flex items-center gap-2">
            <input
              type="text"
              value={newLabel}
              onChange={(e) => setNewLabel(e.target.value)}
              placeholder={t('boq.snapshot_label', { defaultValue: 'Snapshot label (optional)...' })}
              aria-label={t('boq.snapshot_label', { defaultValue: 'Snapshot label (optional)...' })}
              className="flex-1 h-8 rounded-md border border-border bg-surface-primary px-2 text-xs text-content-primary placeholder:text-content-tertiary focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
              onKeyDown={(e) => {
                if (e.key === 'Enter') handleCreate();
              }}
            />
            <button
              onClick={handleCreate}
              disabled={createMutation.isPending}
              aria-label={t('boq.save_snapshot', { defaultValue: 'Save snapshot' })}
              className="flex h-8 items-center gap-1.5 rounded-md bg-oe-blue px-3 text-xs font-medium text-white hover:bg-oe-blue-hover disabled:opacity-50 transition-colors"
            >
              {createMutation.isPending ? (
                <Loader2 size={12} className="animate-spin" />
              ) : (
                <Save size={12} />
              )}
              {t('common.save', { defaultValue: 'Save' })}
            </button>
          </div>
        </div>

        {/* Snapshot list */}
        <div className="flex-1 overflow-y-auto">
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 size={20} className="animate-spin text-content-tertiary" />
            </div>
          ) : isError ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <Clock size={32} className="text-semantic-error/50 mb-3" />
              <p className="text-sm text-content-secondary">
                {t('boq.snapshots_error', { defaultValue: 'Failed to load version history.' })}
              </p>
            </div>
          ) : !snapshots || snapshots.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
              <Clock size={32} className="text-content-quaternary mb-3" />
              <p className="text-sm text-content-secondary mb-1">
                {t('boq.no_snapshots', { defaultValue: 'No snapshots yet' })}
              </p>
              <p className="text-xs text-content-tertiary">
                {t('boq.snapshot_hint', {
                  defaultValue: 'Save a snapshot to create a restore point for your BOQ.',
                })}
              </p>
            </div>
          ) : (
            <div className="divide-y divide-border-light">
              {snapshots.map((snap: BOQSnapshot) => {
                const diff = snapshotDiffs.get(snap.id);
                const hasDiff =
                  diff && (diff.positionDelta !== null || diff.totalDelta !== null);
                const dotColor =
                  diff?.trend === 'up'
                    ? 'bg-emerald-500'
                    : diff?.trend === 'down'
                      ? 'bg-red-500'
                      : 'bg-gray-400';

                return (
                <div
                  key={snap.id}
                  className="px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex items-start gap-2 flex-1 min-w-0">
                      {/* Trend dot */}
                      <span
                        className={clsx(
                          'mt-1.5 h-2 w-2 shrink-0 rounded-full',
                          dotColor,
                        )}
                        aria-hidden="true"
                      />

                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-content-primary truncate">
                          {snap.name || t('boq.auto_snapshot', { defaultValue: 'Auto-save' })}
                        </p>
                        <p className="text-2xs text-content-tertiary mt-0.5">
                          {formatDate(snap.created_at)}
                        </p>
                        {(snap.position_count != null || snap.grand_total != null) && (
                        <div className="flex items-center gap-3 mt-1.5">
                          {snap.position_count != null && (
                          <span className="text-2xs text-content-tertiary">
                            {snap.position_count}{' '}
                            {t('boq.positions', { defaultValue: 'positions' })}
                          </span>
                          )}
                          {snap.grand_total != null && (
                          <span className="text-2xs font-mono text-content-secondary">
                            {fmt.format(snap.grand_total)}
                          </span>
                          )}
                        </div>
                        )}

                        {/* Diff summary compared to the previous (older) snapshot */}
                        {hasDiff && (
                          <div className="flex flex-wrap items-center gap-x-2 gap-y-0.5 mt-1">
                            {diff.positionDelta !== null && diff.positionDelta !== 0 && (
                              <span
                                className={clsx(
                                  'text-2xs font-medium',
                                  diff.positionDelta > 0
                                    ? 'text-emerald-600 dark:text-emerald-400'
                                    : 'text-red-600 dark:text-red-400',
                                )}
                              >
                                {diff.positionDelta > 0
                                  ? t('boq.positions_added', {
                                      count: diff.positionDelta,
                                      defaultValue: '{{count}} pos added',
                                    })
                                  : t('boq.positions_removed', {
                                      count: Math.abs(diff.positionDelta),
                                      defaultValue: '{{count}} pos removed',
                                    })}
                              </span>
                            )}
                            {diff.totalDelta !== null && diff.totalDelta !== 0 && (
                              <span
                                className={clsx(
                                  'text-2xs font-mono font-medium',
                                  diff.totalDelta > 0
                                    ? 'text-emerald-600 dark:text-emerald-400'
                                    : 'text-red-600 dark:text-red-400',
                                )}
                              >
                                {fmtSigned.format(diff.totalDelta)}
                              </span>
                            )}
                            {diff.positionDelta === 0 && diff.totalDelta === 0 && (
                              <span className="text-2xs text-content-quaternary">
                                {t('boq.no_changes', { defaultValue: 'No changes' })}
                              </span>
                            )}
                          </div>
                        )}
                      </div>
                    </div>

                    {confirmRestoreId === snap.id ? (
                      <div className="flex items-center gap-1 shrink-0">
                        <button
                          onClick={() => restoreMutation.mutate(snap.id)}
                          disabled={restoreMutation.isPending}
                          className="flex h-6 items-center gap-1 rounded bg-amber-500 px-2 text-[10px] font-medium text-white hover:bg-amber-600 transition-colors"
                        >
                          {restoreMutation.isPending ? (
                            <Loader2 size={10} className="animate-spin" />
                          ) : (
                            <RotateCcw size={10} />
                          )}
                          {t('boq.restore', { defaultValue: 'Restore' })}
                        </button>
                        <button
                          onClick={() => setConfirmRestoreId(null)}
                          className="flex h-6 items-center rounded bg-surface-secondary px-2 text-[10px] font-medium text-content-secondary hover:bg-surface-tertiary transition-colors"
                        >
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </button>
                      </div>
                    ) : (
                      <button
                        onClick={() => setConfirmRestoreId(snap.id)}
                        className="shrink-0 flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors"
                        title={t('boq.restore_snapshot', { defaultValue: 'Restore this version' })}
                      >
                        <RotateCcw size={13} />
                      </button>
                    )}
                  </div>
                </div>
                );
              })}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
