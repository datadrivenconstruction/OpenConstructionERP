/**
 * PresetSyncBadge (T09 / task #192) — visual signal of preset ↔ snapshot
 * sync state.
 *
 * Three colours map to the three lifecycle states:
 *   • green  ('synced')        — preset matches the snapshot's current shape.
 *   • amber  ('stale')         — snapshot was refreshed but no sync-check
 *                                 has run yet, or only auto-fixable issues.
 *   • red    ('needs_review')  — at least one issue requires manual edit.
 *
 * Click → opens :class:`SyncReportDrawer` so the user can review the
 * findings and (where possible) auto-heal them.
 *
 * Designed to slot next to a preset's name without disturbing the
 * existing :class:`PresetPicker` tests — the badge is opt-in via the
 * ``presetId`` prop.
 */
import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';

import { Badge } from '@/shared/ui';

import { getSyncReport, type SyncReport, type SyncStatus } from './api';
import { SyncReportDrawer } from './SyncReportDrawer';

export interface PresetSyncBadgeProps {
  presetId: string;
  /** Optional cached status — short-circuits the network round-trip
   *  while the badge is still rendered in a list. */
  initialStatus?: SyncStatus;
  /** When ``false``, clicking the badge is a no-op (drawer disabled). */
  interactive?: boolean;
  /** Optional className passthrough. */
  className?: string;
}

const STATUS_TO_VARIANT: Record<SyncStatus, 'success' | 'warning' | 'error'> = {
  synced: 'success',
  stale: 'warning',
  needs_review: 'error',
};

const STATUS_TO_KEY: Record<SyncStatus, string> = {
  synced: 'dashboards.sync.status_synced',
  stale: 'dashboards.sync.status_stale',
  needs_review: 'dashboards.sync.status_needs_review',
};

const STATUS_DEFAULT_LABEL: Record<SyncStatus, string> = {
  synced: 'In sync',
  stale: 'Stale',
  needs_review: 'Needs review',
};

export function PresetSyncBadge({
  presetId,
  initialStatus,
  interactive = true,
  className,
}: PresetSyncBadgeProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  // Lazy fetch — only when the user opens the drawer or the parent
  // doesn't supply an ``initialStatus``.
  const reportQuery = useQuery<SyncReport>({
    queryKey: ['preset-sync-report', presetId],
    queryFn: () => getSyncReport(presetId),
    enabled: open || !initialStatus,
    staleTime: 30 * 1000,
  });

  const status: SyncStatus =
    reportQuery.data?.status ?? initialStatus ?? 'synced';
  const variant = STATUS_TO_VARIANT[status];
  const labelKey = STATUS_TO_KEY[status];
  const label = t(labelKey, { defaultValue: STATUS_DEFAULT_LABEL[status] });

  const onClick = interactive
    ? () => {
        setOpen(true);
      }
    : undefined;

  return (
    <>
      <button
        type="button"
        onClick={onClick}
        disabled={!interactive}
        data-testid={`preset-sync-badge-${presetId}`}
        data-status={status}
        aria-label={t('dashboards.sync.badge_aria', {
          defaultValue: 'Preset sync status: {{status}}',
          status: label,
        })}
        className={clsx(
          'inline-flex items-center',
          interactive
            ? 'cursor-pointer focus:outline-none focus:ring-2 focus:ring-oe-blue rounded-full'
            : 'cursor-default',
          className,
        )}
      >
        <Badge variant={variant} size="sm" dot>
          {label}
        </Badge>
      </button>
      {open && (
        <SyncReportDrawer
          presetId={presetId}
          report={reportQuery.data ?? null}
          isLoading={reportQuery.isLoading}
          onClose={() => setOpen(false)}
        />
      )}
    </>
  );
}
