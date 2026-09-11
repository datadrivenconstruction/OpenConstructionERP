// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useCallback, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { X, Clock, RotateCcw, Loader2, Save, History, Undo2, Trash2 } from 'lucide-react';
import clsx from 'clsx';
import { boqApi, type BOQSnapshot, type ActivityEntry } from './api';
import { useToastStore } from '@/stores/useToastStore';
import { getIntlLocale } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

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

/**
 * v3.12.0 Stream A — extract per-field {old, new} pairs from an activity-log
 * `changes` JSON. The backend writes `{field: {old, new}}` for position
 * updates; other shapes (bulk, restore, snapshot) are filtered out.
 */
interface FieldChange {
  field: string;
  oldValue: unknown;
  newValue: unknown;
}

function extractFieldChanges(details: Record<string, unknown>): FieldChange[] {
  const out: FieldChange[] = [];
  for (const [key, raw] of Object.entries(details)) {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) continue;
    const rec = raw as Record<string, unknown>;
    if (!('old' in rec) || !('new' in rec)) continue;
    out.push({ field: key, oldValue: rec.old, newValue: rec.new });
  }
  return out;
}

/**
 * Pretty-print a JSON-coerced audit value: strings unwrapped, objects
 * truncated, falsy renders an em dash so empty cells stay readable.
 */
function formatAuditValue(v: unknown): string {
  if (v === null || v === undefined || v === '') return '—';
  if (typeof v === 'string') return v.length > 32 ? v.slice(0, 30) + '…' : v;
  if (typeof v === 'number' || typeof v === 'boolean') return String(v);
  try {
    const j = JSON.stringify(v);
    return j.length > 32 ? j.slice(0, 30) + '…' : j;
  } catch {
    return String(v);
  }
}

interface VersionHistoryDrawerProps {
  boqId: string;
  isOpen: boolean;
  onClose: () => void;
}

type DrawerTab = 'snapshots' | 'fields';

export function VersionHistoryDrawer({ boqId, isOpen, onClose }: VersionHistoryDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const [newLabel, setNewLabel] = useState('');
  const [confirmRestoreId, setConfirmRestoreId] = useState<string | null>(null);
  // v3.12.0 Stream A — drawer now has two tabs: snapshots + field history.
  const [tab, setTab] = useState<DrawerTab>('snapshots');

  const { data: snapshots, isLoading, isError } = useQuery({
    queryKey: ['boq-snapshots', boqId],
    queryFn: () => boqApi.getSnapshots(boqId),
    enabled: isOpen && !!boqId,
  });

  // v3.12.0 — load activity log for the "Field history" tab. Hidden until
  // the tab is selected so we don't pay the GET on every drawer open.
  const { data: activity, isLoading: isActLoading, isError: isActError } = useQuery({
    queryKey: ['boq-activity', boqId],
    queryFn: () => boqApi.getActivity(boqId),
    enabled: isOpen && !!boqId && tab === 'fields',
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
    onError: (e: Error) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.snapshot_failed', { defaultValue: 'Failed to save snapshot' }),
        message: e.message,
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
    onError: (e: Error) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.restore_failed', { defaultValue: 'Failed to restore snapshot' }),
        message: e.message,
      });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (snapshotId: string) => boqApi.deleteSnapshot(boqId, snapshotId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['boq-snapshots', boqId] });
      useToastStore.getState().addToast({
        type: 'success',
        title: t('boq.snapshot_deleted', { defaultValue: 'Snapshot deleted' }),
      });
    },
    onError: (e: Error) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.snapshot_delete_failed', { defaultValue: 'Failed to delete snapshot' }),
        message: e.message,
      });
    },
  });

  /**
   * v3.12.0 Stream A — per-field restore: revert ONE field on ONE position
   * back to its `old` value as recorded in the supplied log entry.
   */
  const fieldRestoreMutation = useMutation({
    mutationFn: (args: {
      positionId: string;
      field: string;
      value: unknown;
      logId: string;
    }) =>
      boqApi.restorePositionField(boqId, args.positionId, {
        field: args.field,
        value: args.value,
        log_id: args.logId,
      }),
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ['boq', boqId] });
      queryClient.invalidateQueries({ queryKey: ['boq-activity', boqId] });
      useToastStore.getState().addToast({
        type: 'success',
        title: t('boq.field_restored', {
          defaultValue: 'Restored field "{{field}}"',
          field: variables.field,
        } as Record<string, string>),
      });
    },
    onError: (e: Error) => {
      useToastStore.getState().addToast({
        type: 'error',
        title: t('boq.field_restore_failed', {
          defaultValue: 'Could not restore field',
        }),
        message: e.message,
      });
    },
  });

  const handleCreate = useCallback(() => {
    createMutation.mutate(newLabel.trim() || undefined);
  }, [createMutation, newLabel]);

  const formatDate = useCallback((dateStr: string) => {
    try {
      const d = new Date(dateStr);
      return d.toLocaleDateString(getIntlLocale(), {
        month: 'short',
        day: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return dateStr;
    }
  }, []);

  const fmt = new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });

  const fmtSigned = new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
    signDisplay: 'always',
  });

  const snapshotDiffs = useMemo(
    () => computeSnapshotDiffs(snapshots ?? []),
    [snapshots],
  );

  /**
   * v3.12.0 — flatten the activity log into per-field rows. Each ActivityEntry
   * with diff-shaped `details` produces N FieldRow entries (one per changed
   * column). Bulk + snapshot + restore entries are skipped because their
   * `changes` payload does not match the {old, new} contract.
   */
  interface FieldRow {
    logId: string;
    positionId: string;
    field: string;
    oldValue: unknown;
    newValue: unknown;
    when: string;
    summary: string;
  }
  const fieldRows = useMemo<FieldRow[]>(() => {
    if (!activity?.activities) return [];
    const out: FieldRow[] = [];
    for (const entry of activity.activities as ActivityEntry[]) {
      if (entry.target_type !== 'position') continue;
      if (!entry.target_id) continue;
      const changes = extractFieldChanges(entry.details ?? {});
      for (const change of changes) {
        out.push({
          logId: entry.id,
          positionId: entry.target_id,
          field: change.field,
          oldValue: change.oldValue,
          newValue: change.newValue,
          when: entry.created_at,
          summary: entry.description,
        });
      }
    }
    return out;
  }, [activity]);

  if (!isOpen) return null;

  return (
    <div className="fixed inset-y-0 right-0 z-50 flex">
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/20" onClick={onClose} aria-hidden="true" />

      {/* Drawer — widened to accommodate the field-restore rows. */}
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('boq.version_history', { defaultValue: 'Version History' })}
        className="relative ml-auto flex h-full w-96 flex-col bg-surface-elevated border-l border-border shadow-2xl animate-slide-in-right"
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

        {/* v3.12.0 — tab switcher (Snapshots / Field history) */}
        <div className="flex items-center gap-1 border-b border-border px-3 py-1.5 bg-surface-secondary/40">
          <button
            type="button"
            onClick={() => setTab('snapshots')}
            aria-pressed={tab === 'snapshots'}
            className={clsx(
              'flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors',
              tab === 'snapshots'
                ? 'bg-surface-elevated text-oe-blue shadow-xs'
                : 'text-content-secondary hover:text-content-primary hover:bg-surface-tertiary',
            )}
          >
            <Save size={12} />
            {t('boq.tab_snapshots', { defaultValue: 'Snapshots' })}
          </button>
          <button
            type="button"
            onClick={() => setTab('fields')}
            aria-pressed={tab === 'fields'}
            className={clsx(
              'flex h-7 items-center gap-1.5 rounded-md px-2 text-xs font-medium transition-colors',
              tab === 'fields'
                ? 'bg-surface-elevated text-oe-blue shadow-xs'
                : 'text-content-secondary hover:text-content-primary hover:bg-surface-tertiary',
            )}
          >
            <History size={12} />
            {t('boq.tab_field_history', { defaultValue: 'Field history' })}
          </button>
        </div>

        {tab === 'snapshots' && (
          <>
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
                  <Clock size={32} className="text-semantic-error mb-3" />
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
                      defaultValue: 'Type a label above and click Save to create your first snapshot.',
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
                            {snap.description && (
                              <p className="text-2xs text-content-secondary mt-0.5 line-clamp-2">
                                {snap.description}
                              </p>
                            )}
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
                          <div className="flex items-center gap-0.5 shrink-0">
                            <button
                              onClick={() => setConfirmRestoreId(snap.id)}
                              className="flex h-6 w-6 items-center justify-center rounded text-content-tertiary hover:text-amber-600 hover:bg-amber-50 dark:hover:bg-amber-900/20 transition-colors"
                              title={t('boq.restore_snapshot', { defaultValue: 'Restore this version' })}
                            >
                              <RotateCcw size={13} />
                            </button>
                            <button
                              onClick={() => deleteMutation.mutate(snap.id)}
                              disabled={deleteMutation.isPending}
                              className="flex h-6 w-6 items-center justify-center rounded text-content-quaternary hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 transition-colors"
                              title={t('boq.delete_snapshot', { defaultValue: 'Delete snapshot' })}
                            >
                              {deleteMutation.isPending ? (
                                <Loader2 size={12} className="animate-spin" />
                              ) : (
                                <Trash2 size={12} />
                              )}
                            </button>
                          </div>
                        )}
                      </div>
                    </div>
                    );
                  })}
                </div>
              )}
            </div>
          </>
        )}

        {tab === 'fields' && (
          <div className="flex-1 overflow-y-auto">
            {isActLoading ? (
              <div className="flex items-center justify-center py-12">
                <Loader2 size={20} className="animate-spin text-content-tertiary" />
              </div>
            ) : isActError ? (
              <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                <History size={32} className="text-semantic-error mb-3" />
                <p className="text-sm text-content-secondary">
                  {t('boq.activity_error', { defaultValue: 'Failed to load field history.' })}
                </p>
              </div>
            ) : fieldRows.length === 0 ? (
              <div className="flex flex-col items-center justify-center py-12 px-4 text-center">
                <History size={32} className="text-content-quaternary mb-3" />
                <p className="text-sm text-content-secondary mb-1">
                  {t('boq.no_field_history', { defaultValue: 'No field-level edits yet' })}
                </p>
                <p className="text-xs text-content-tertiary">
                  {t('boq.field_history_hint', {
                    defaultValue: 'Each position cell edit appears here and can be reverted to its previous value.',
                  })}
                </p>
              </div>
            ) : (
              <ul className="divide-y divide-border-light">
                {fieldRows.map((row, idx) => (
                  <li
                    key={`${row.logId}-${row.field}-${idx}`}
                    className="px-4 py-3 hover:bg-surface-secondary/50 transition-colors"
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="flex-1 min-w-0">
                        <p className="text-xs font-medium text-content-primary">
                          <span className="font-mono text-oe-blue">{row.field}</span>
                          <span className="ml-1 text-content-tertiary">
                            {formatAuditValue(row.oldValue)}
                          </span>
                          <span className="mx-1 text-content-quaternary">→</span>
                          <span className="text-content-primary">
                            {formatAuditValue(row.newValue)}
                          </span>
                        </p>
                        <p className="text-2xs text-content-tertiary mt-0.5 truncate" title={row.summary}>
                          {formatDate(row.when)} · {row.summary}
                        </p>
                      </div>
                      <button
                        type="button"
                        onClick={() =>
                          fieldRestoreMutation.mutate({
                            positionId: row.positionId,
                            field: row.field,
                            value: row.oldValue,
                            logId: row.logId,
                          })
                        }
                        disabled={
                          fieldRestoreMutation.isPending &&
                          fieldRestoreMutation.variables?.logId === row.logId &&
                          fieldRestoreMutation.variables?.field === row.field
                        }
                        title={t('boq.restore_field_title', {
                          defaultValue: 'Restore "{{field}}" to {{value}}',
                          field: row.field,
                          value: formatAuditValue(row.oldValue),
                        } as Record<string, string>)}
                        aria-label={t('boq.restore_field_title', {
                          defaultValue: 'Restore "{{field}}" to {{value}}',
                          field: row.field,
                          value: formatAuditValue(row.oldValue),
                        } as Record<string, string>)}
                        className="shrink-0 flex h-6 items-center gap-1 rounded bg-amber-500/10 px-2 text-[10px] font-medium text-amber-700 dark:text-amber-300 hover:bg-amber-500/20 disabled:opacity-50 transition-colors"
                      >
                        {fieldRestoreMutation.isPending &&
                        fieldRestoreMutation.variables?.logId === row.logId &&
                        fieldRestoreMutation.variables?.field === row.field ? (
                          <Loader2 size={10} className="animate-spin" />
                        ) : (
                          <Undo2 size={10} />
                        )}
                        {t('boq.restore', { defaultValue: 'Restore' })}
                      </button>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
