// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Offline/online indicator + "N pending sync" badge for the field shell.
 *
 * Compact, framework-light, touch-friendly. Three visual states:
 *   - online,  nothing pending  -> a small green "Online" pill (or hidden)
 *   - online,  N pending        -> blue "Syncing N" / "N to sync" pill
 *   - offline                   -> amber "Offline" pill, always shown, with the
 *                                  pending count so the worker knows their taps
 *                                  are safely captured
 *
 * Pure presentational: the caller passes the live state from `useFieldSync`.
 */

import { Cloud, CloudOff, RefreshCw } from 'lucide-react';
import { useTranslation } from 'react-i18next';

export interface OfflineStatusBadgeProps {
  online: boolean;
  pending: number;
  syncing: boolean;
  /** Optional manual "sync now" trigger; shown only when online with a backlog. */
  onSyncNow?: () => void;
  /** Hide entirely when online with an empty queue (default false). */
  hideWhenClean?: boolean;
  className?: string;
}

export function OfflineStatusBadge({
  online,
  pending,
  syncing,
  onSyncNow,
  hideWhenClean = false,
  className = '',
}: OfflineStatusBadgeProps) {
  const { t } = useTranslation();

  const clean = online && pending === 0 && !syncing;
  if (clean && hideWhenClean) return null;

  /* Offline. */
  if (!online) {
    return (
      <span
        role="status"
        aria-live="polite"
        data-testid="field-status-badge"
        data-state="offline"
        className={`inline-flex items-center gap-1.5 rounded-full bg-amber-100 px-3 py-1.5 text-xs font-semibold text-amber-800 ${className}`}
      >
        <CloudOff size={14} aria-hidden="true" />
        <span>{t('field.offline', { defaultValue: 'Offline' })}</span>
        {pending > 0 && (
          <span
            data-testid="field-pending-count"
            className="ml-0.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-amber-800 px-1.5 text-[11px] font-bold text-white"
          >
            {pending}
          </span>
        )}
      </span>
    );
  }

  /* Online with a backlog (queued or actively syncing). */
  if (pending > 0 || syncing) {
    return (
      <button
        type="button"
        onClick={onSyncNow}
        disabled={syncing || !onSyncNow}
        role="status"
        aria-live="polite"
        data-testid="field-status-badge"
        data-state={syncing ? 'syncing' : 'pending'}
        className={`inline-flex min-h-[2rem] items-center gap-1.5 rounded-full bg-sky-100 px-3 py-1.5 text-xs font-semibold text-sky-800 disabled:opacity-80 ${className}`}
      >
        <RefreshCw size={14} aria-hidden="true" className={syncing ? 'animate-spin' : ''} />
        <span>
          {syncing
            ? t('field.syncing', { defaultValue: 'Syncing…' })
            : t('field.pending_sync', { defaultValue: '{{count}} to sync', count: pending })}
        </span>
        {pending > 0 && (
          <span
            data-testid="field-pending-count"
            className="ml-0.5 inline-flex min-w-[1.25rem] items-center justify-center rounded-full bg-sky-700 px-1.5 text-[11px] font-bold text-white"
          >
            {pending}
          </span>
        )}
      </button>
    );
  }

  /* Online and clean. */
  return (
    <span
      role="status"
      aria-live="polite"
      data-testid="field-status-badge"
      data-state="online"
      className={`inline-flex items-center gap-1.5 rounded-full bg-emerald-100 px-3 py-1.5 text-xs font-semibold text-emerald-800 ${className}`}
    >
      <Cloud size={14} aria-hidden="true" />
      <span>{t('field.online', { defaultValue: 'Online' })}</span>
    </span>
  );
}

export default OfflineStatusBadge;
