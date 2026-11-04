// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pending-sync review panel for the field PWA.
 *
 * Lists every captured-while-offline write still awaiting replay - both the
 * genuinely *pending* ops (never attempted) and the *failing* ops (a transient
 * error bumped their retry count and the queue keeps retrying them). For each it
 * shows the operation type, when it was captured, its status and retry count,
 * and offers two actions:
 *
 *   - Retry / Sync now: force a drain attempt (only meaningful while online).
 *   - Dismiss: drop a single op from the queue so it is never replayed - the
 *     escape hatch for a write the worker no longer wants (e.g. a duplicate
 *     punch). Dismiss is local-only; it removes the captured op, it does not
 *     undo anything already applied on the server.
 *
 * Presentational + container in one: it reads the live queue state from
 * `useFieldSync` (the single source of truth) and the pure `summariseQueue`
 * derivation. The field shell mounts it on the Profile tab; it can also be
 * rendered standalone behind a route (see the integrator notes).
 *
 * Touch-target rule: every interactive element stays at >=44px to match the
 * rest of the field shell.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  CloudOff,
  Cloud,
  RefreshCw,
  AlertTriangle,
  Clock,
  Trash2,
  CheckCircle2,
  Lock,
  Download,
} from 'lucide-react';
import {
  summariseQueue,
  sortForReview,
  formatRelativeTime,
  kindLabel,
  type SyncQueueItem,
} from './syncQueueSummary';
import type { useFieldSync } from './useFieldSync';
import { KIND_FIELD_TIME, MAX_OP_AGE_DAYS, kindLabelKey, reasonKey } from './fieldKinds';
import { StorageMeter } from './StorageMeter';
import type { QueuedOp } from '@/shared/lib/offline';

/**
 * The slice of `useFieldSync` the panel needs. Declared structurally (not as the
 * full hook return) so the panel is trivial to render in a test or a Storybook
 * with a hand-built state object.
 */
export type SyncQueuePanelState = Pick<
  ReturnType<typeof useFieldSync>,
  'online' | 'pendingOps' | 'syncing' | 'syncNow' | 'discard'
> &
  Partial<Pick<ReturnType<typeof useFieldSync>, 'lastResults' | 'heldOps' | 'exportHeld' | 'discardHeld'>> & {
    /** Crew-time ops from their own queue, listed beside the rest (display only). */
    extraItems?: SyncQueueItem[];
  };

export interface SyncQueuePanelProps {
  state: SyncQueuePanelState;
  /** Injected clock for deterministic relative-time rendering in tests. */
  now?: number;
  className?: string;
}

export function SyncQueuePanel({ state, now, className = '' }: SyncQueuePanelProps) {
  const { t } = useTranslation();
  const { online, pendingOps, syncing, syncNow, discard, lastResults, extraItems, heldOps, exportHeld, discardHeld } =
    state;

  // Track in-flight dismissals so the row's button can disable while its async
  // discard resolves (the queue change event then drops the row entirely).
  const [dismissing, setDismissing] = useState<Set<string>>(new Set());

  // `now` is captured once per render when not injected; relative times are
  // coarse (minutes/hours) so this does not need to tick.
  const clock = now ?? Date.now();
  const summary = useMemo(() => {
    const base = summariseQueue(pendingOps);
    if (!extraItems || extraItems.length === 0) return base;
    const items = sortForReview([...base.items, ...extraItems]);
    const failing = items.filter((i) => i.status === 'failing').length;
    return { items, total: items.length, pending: items.length - failing, failing, isEmpty: false };
  }, [pendingOps, extraItems]);
  const refused = (lastResults ?? []).filter((r) => r.status === 'rejected');

  const onDismiss = async (clientOpId: string) => {
    setDismissing((prev) => new Set(prev).add(clientOpId));
    try {
      await discard(clientOpId);
    } finally {
      setDismissing((prev) => {
        const next = new Set(prev);
        next.delete(clientOpId);
        return next;
      });
    }
  };

  return (
    <section
      data-testid="sync-queue-panel"
      aria-label={t('field.sync_queue.title', { defaultValue: 'Pending sync' })}
      className={`flex w-full flex-col gap-3 px-4 py-4 ${className}`}
    >
      {/* Header: title + connectivity + sync-now. */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <h2 className="truncate text-base font-semibold text-slate-900">
            {t('field.sync_queue.title', { defaultValue: 'Pending sync' })}
          </h2>
          {summary.total > 0 && (
            <span
              data-testid="sync-queue-total"
              className="inline-flex min-w-[1.5rem] items-center justify-center rounded-full bg-slate-100 px-2 py-0.5 text-xs font-semibold text-slate-700"
            >
              {summary.total}
            </span>
          )}
        </div>
        <span
          data-testid="sync-queue-connectivity"
          data-state={online ? 'online' : 'offline'}
          className={`inline-flex shrink-0 items-center gap-1 rounded-full px-2.5 py-1 text-xs font-semibold ${
            online ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'
          }`}
        >
          {online ? (
            <Cloud size={14} aria-hidden="true" />
          ) : (
            <CloudOff size={14} aria-hidden="true" />
          )}
          {online
            ? t('field.online', { defaultValue: 'Online' })
            : t('field.offline', { defaultValue: 'Offline' })}
        </span>
      </div>

      {/* Status line: counts of pending vs failing. */}
      {!summary.isEmpty && (
        <p className="text-sm text-slate-500">
          {summary.failing > 0
            ? t('field.sync_queue.summary_with_failing', {
                defaultValue: '{{pending}} waiting, {{failing}} need attention',
                pending: summary.pending,
                failing: summary.failing,
              })
            : t('field.sync_queue.summary_pending', {
                defaultValue: '{{count}} waiting to sync',
                count: summary.pending,
              })}
        </p>
      )}

      <StorageMeter ops={pendingOps} now={clock} />

      {/* Sync-now action (whole-queue). */}
      <button
        type="button"
        data-testid="sync-queue-sync-now"
        onClick={() => {
          void syncNow();
        }}
        disabled={summary.isEmpty || syncing || !online}
        className="flex h-11 items-center justify-center gap-2 rounded-xl bg-sky-600 px-4 text-sm font-semibold text-white disabled:opacity-50"
      >
        <RefreshCw size={18} aria-hidden="true" className={syncing ? 'animate-spin' : ''} />
        {syncing
          ? t('field.syncing', { defaultValue: 'Syncing…' })
          : t('field.sync_queue.sync_now', { defaultValue: 'Sync now' })}
      </button>
      {!online && !summary.isEmpty && (
        <p className="-mt-1 text-xs text-amber-700">
          {t('field.sync_queue.offline_hint', {
            defaultValue: 'You are offline. These will sync automatically when you reconnect.',
          })}
        </p>
      )}

      {refused.length > 0 && (
        <ul data-testid="sync-queue-refused" className="flex flex-col gap-1 rounded-xl border border-rose-200 bg-rose-50/60 p-3">
          {refused.map((r) => {
            const key = reasonKey(r.detail);
            return (
              <li key={r.clientOpId} className="text-xs text-rose-700">
                <span className="font-medium">
                  {t(kindLabelKey(r.kind) ?? `field.sync_queue.kind.${r.kind}`, { defaultValue: kindLabel(r.kind) })}
                </span>
                {': '}
                {key
                  ? t(key, { days: MAX_OP_AGE_DAYS, defaultValue: 'Too old to sync (over {{days}} days). Please enter it again.' })
                  : (r.detail ?? t('offline_sync.problem_unknown', { defaultValue: 'Rejected by the server' }))}
              </li>
            );
          })}
        </ul>
      )}

      {heldOps && heldOps.length > 0 && (
        <HeldSection ops={heldOps} exportHeld={exportHeld} discardHeld={discardHeld} />
      )}

      {/* Empty state. */}
      {summary.isEmpty ? (
        <div
          data-testid="sync-queue-empty"
          className="flex flex-col items-center gap-2 rounded-xl border border-dashed border-slate-200 py-8 text-center"
        >
          <CheckCircle2 size={28} className="text-emerald-500" aria-hidden="true" />
          <p className="text-sm font-medium text-slate-700">
            {t('field.sync_queue.empty_title', { defaultValue: 'Everything is synced' })}
          </p>
          <p className="px-6 text-xs text-slate-400">
            {t('field.sync_queue.empty_body', {
              defaultValue: 'Captures you make offline will appear here until they reach the server.',
            })}
          </p>
        </div>
      ) : (
        <ul className="flex flex-col gap-2" data-testid="sync-queue-list">
          {summary.items.map((row) => (
            <SyncQueueRow
              key={row.clientOpId}
              row={row}
              now={clock}
              dismissing={dismissing.has(row.clientOpId)}
              onDismiss={() => void onDismiss(row.clientOpId)}
            />
          ))}
        </ul>
      )}
    </section>
  );
}

/* ── Captures of other users ───────────────────────────────────────────── */

function HeldSection({
  ops,
  exportHeld,
  discardHeld,
}: {
  ops: QueuedOp[];
  exportHeld?: () => Promise<string>;
  discardHeld?: () => Promise<void>;
}) {
  const { t } = useTranslation();
  const [confirming, setConfirming] = useState(false);
  const who = new Map<string, number>();
  for (const op of ops) {
    const name = op.owner?.label || op.owner?.userId || '';
    who.set(name, (who.get(name) ?? 0) + 1);
  }

  const onExport = async () => {
    if (!exportHeld) return;
    const url = URL.createObjectURL(new Blob([await exportHeld()], { type: 'application/json' }));
    const a = document.createElement('a');
    a.href = url;
    a.download = 'pending-captures.json';
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div data-testid="sync-queue-held" className="flex flex-col gap-2 rounded-xl border border-amber-200 bg-amber-50/60 p-3">
      <p className="flex items-center gap-2 text-sm font-semibold text-amber-900">
        <Lock size={16} aria-hidden="true" />
        {t('field.sync_queue.held_title', { defaultValue: 'Captures of other users' })}
      </p>
      <ul className="flex flex-col gap-0.5">
        {[...who.entries()].map(([name, count]) => (
          <li key={name} data-testid="sync-queue-held-owner" className="text-xs text-amber-800">
            {name
              ? t('field.sync_queue.held_waiting', {
                  defaultValue: '{{n}} waiting for {{name}} to sign in',
                  n: count,
                  name,
                })
              : t('field.sync_queue.held_unknown', {
                  defaultValue: '{{n}} from an earlier session, owner unknown',
                  n: count,
                })}
          </li>
        ))}
      </ul>
      <p className="text-xs text-amber-800">
        {t('field.sync_queue.held_hint', {
          defaultValue: 'They are never sent under your sign-in. Export them or discard them on this device.',
        })}
      </p>
      {confirming ? (
        <div className="flex flex-col gap-2" data-testid="sync-queue-held-confirm">
          <p className="text-xs font-medium text-rose-700">
            {t('field.sync_queue.held_confirm', {
              defaultValue: 'Discard {{n}} captures of other users? This cannot be undone.',
              n: ops.length,
            })}
          </p>
          <div className="flex gap-2">
            <button
              type="button"
              data-testid="sync-queue-held-discard-yes"
              onClick={() => {
                setConfirming(false);
                void discardHeld?.();
              }}
              className="flex h-11 flex-1 items-center justify-center rounded-xl bg-rose-600 px-3 text-sm font-semibold text-white"
            >
              {t('field.sync_queue.held_discard', { defaultValue: 'Discard' })}
            </button>
            <button
              type="button"
              onClick={() => setConfirming(false)}
              className="flex h-11 flex-1 items-center justify-center rounded-xl border border-slate-300 px-3 text-sm font-semibold text-slate-700"
            >
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </button>
          </div>
        </div>
      ) : (
        <div className="flex gap-2">
          {exportHeld && (
            <button
              type="button"
              data-testid="sync-queue-held-export"
              onClick={() => void onExport()}
              className="flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-amber-300 px-3 text-sm font-semibold text-amber-900"
            >
              <Download size={16} aria-hidden="true" />
              {t('field.sync_queue.held_export', { defaultValue: 'Export' })}
            </button>
          )}
          {discardHeld && (
            <button
              type="button"
              data-testid="sync-queue-held-discard"
              onClick={() => setConfirming(true)}
              className="flex h-11 flex-1 items-center justify-center gap-2 rounded-xl border border-rose-300 px-3 text-sm font-semibold text-rose-700"
            >
              <Trash2 size={16} aria-hidden="true" />
              {t('field.sync_queue.held_discard', { defaultValue: 'Discard' })}
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/* ── Row ───────────────────────────────────────────────────────────────── */

function SyncQueueRow({
  row,
  now,
  dismissing,
  onDismiss,
}: {
  row: SyncQueueItem;
  now: number;
  dismissing: boolean;
  onDismiss: () => void;
}) {
  const { t } = useTranslation();
  const failing = row.status === 'failing';

  return (
    <li
      data-testid="sync-queue-row"
      data-status={row.status}
      className={`flex items-start gap-3 rounded-xl border p-3 ${
        failing ? 'border-rose-200 bg-rose-50/60' : 'border-slate-200'
      }`}
    >
      {/* Status icon. */}
      <div className="mt-0.5 shrink-0">
        {failing ? (
          <AlertTriangle size={18} className="text-rose-500" aria-hidden="true" />
        ) : (
          <Clock size={18} className="text-slate-400" aria-hidden="true" />
        )}
      </div>

      {/* Body. */}
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2">
          <p className="truncate text-sm font-medium text-slate-900">
            {t(kindLabelKey(row.kind) ?? `field.sync_queue.kind.${row.kind}`, { defaultValue: kindLabel(row.kind) })}
          </p>
          <span className="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 text-[11px] font-medium uppercase tracking-wide text-slate-500">
            {row.method}
          </span>
        </div>
        <p className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-slate-500">
          <span>{formatRelativeTime(row.queuedAt, now)}</span>
          <span aria-hidden="true">·</span>
          {failing ? (
            <span data-testid="sync-queue-row-status" className="font-medium text-rose-600">
              {t('field.sync_queue.status_failing', {
                defaultValue: 'Retry {{count}}',
                count: row.retries,
              })}
            </span>
          ) : (
            <span data-testid="sync-queue-row-status" className="text-slate-500">
              {t('field.sync_queue.status_pending', { defaultValue: 'Waiting' })}
            </span>
          )}
        </p>
      </div>

      {/* Dismiss. Crew-time rows replay through their own queue and are not dismissed here. */}
      {row.kind !== KIND_FIELD_TIME && (
      <button
        type="button"
        data-testid="sync-queue-dismiss"
        onClick={onDismiss}
        disabled={dismissing}
        aria-label={t('field.sync_queue.dismiss', { defaultValue: 'Dismiss' })}
        title={t('field.sync_queue.dismiss', { defaultValue: 'Dismiss' })}
        className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-slate-400 hover:bg-slate-100 hover:text-rose-600 disabled:opacity-50"
      >
        <Trash2 size={16} aria-hidden="true" />
      </button>
      )}
    </li>
  );
}

export default SyncQueuePanel;
