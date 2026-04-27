/**
 * Compact inline snapshot picker.
 *
 * Drop into other dashboards components (Quick Insights, Cascade
 * Filter, Integrity Overview) so the user can switch which snapshot
 * is feeding the surrounding panel without leaving the page. Shows
 * the current active snapshot's label + a dropdown of every other
 * snapshot in the project, newest-first.
 *
 * Tiny on purpose — no inline diff, no completeness chip; the full
 * timeline + diff live in their own panels. Switching snapshots is
 * a 200ms operation; we don't want to make the user wait on a fat
 * widget every time.
 */
import { useCallback, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import { Check, ChevronDown, Clock, Loader2 } from 'lucide-react';

import { Button } from '@/shared/ui';

import { getSnapshotTimeline } from './api';

export interface SnapshotPickerInlineProps {
  projectId: string;
  /** Currently active snapshot id. Marked with a check icon and
   * surfaced in the trigger button's label. */
  activeSnapshotId: string | null;
  onChange: (snapshotId: string) => void;
  /** Override the page size — defaults to 25 to keep the dropdown
   * scrollable but bounded. */
  pageSize?: number;
}

export function SnapshotPickerInline({
  projectId,
  activeSnapshotId,
  onChange,
  pageSize = 25,
}: SnapshotPickerInlineProps) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);

  const timelineQuery = useQuery({
    queryKey: ['dashboards-snapshot-picker-inline', projectId, pageSize],
    queryFn: () => getSnapshotTimeline({ projectId, limit: pageSize }),
    enabled: !!projectId,
    staleTime: 60 * 1000,
  });

  const items = timelineQuery.data?.items ?? [];
  const active = items.find((i) => i.id === activeSnapshotId) ?? null;

  const handlePick = useCallback(
    (id: string) => {
      onChange(id);
      setOpen(false);
    },
    [onChange],
  );

  return (
    <div className="relative inline-block" data-testid="snapshot-picker-inline">
      <Button
        size="sm"
        variant="ghost"
        onClick={() => setOpen((o) => !o)}
        aria-haspopup="listbox"
        aria-expanded={open}
        data-testid="snapshot-picker-inline-trigger"
        className="flex items-center gap-1.5"
      >
        <Clock className="h-3 w-3 text-content-tertiary" />
        <span className="max-w-[200px] truncate" data-testid="snapshot-picker-inline-current">
          {active?.label ??
            (timelineQuery.isLoading
              ? t('common.loading', { defaultValue: 'Loading…' })
              : t('dashboards.picker_no_active', {
                  defaultValue: 'No snapshot selected',
                }))}
        </span>
        <ChevronDown className="h-3 w-3 text-content-tertiary" />
      </Button>

      {open && (
        <div
          role="listbox"
          aria-label={t('dashboards.picker_listbox_aria', {
            defaultValue: 'Choose snapshot',
          })}
          data-testid="snapshot-picker-inline-listbox"
          className="absolute z-30 mt-1 max-h-72 w-72 overflow-y-auto rounded border border-border-light bg-surface-primary py-1 shadow-lg"
        >
          {timelineQuery.isLoading && (
            <div
              className="flex items-center justify-center gap-1 px-3 py-2 text-xs text-content-tertiary"
              data-testid="snapshot-picker-inline-loading"
            >
              <Loader2 className="h-3 w-3 animate-spin" />
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}

          {!timelineQuery.isLoading && items.length === 0 && (
            <div
              className="px-3 py-2 text-xs text-content-tertiary"
              data-testid="snapshot-picker-inline-empty"
            >
              {t('dashboards.picker_empty', {
                defaultValue: 'No snapshots in this project yet.',
              })}
            </div>
          )}

          {items.map((item) => {
            const isActive = item.id === activeSnapshotId;
            return (
              <button
                key={item.id}
                type="button"
                role="option"
                aria-selected={isActive}
                onClick={() => handlePick(item.id)}
                data-testid={`snapshot-picker-inline-option-${item.id}`}
                className={`flex w-full items-center gap-2 px-3 py-1.5 text-left text-xs hover:bg-surface-secondary ${
                  isActive ? 'bg-emerald-500/5 text-emerald-200' : 'text-content-primary'
                }`}
              >
                <span className="flex h-3 w-3 flex-shrink-0 items-center justify-center">
                  {isActive && <Check className="h-3 w-3 text-emerald-400" />}
                </span>
                <span className="flex-1 truncate" title={item.label}>
                  {item.label}
                </span>
                <span className="flex-shrink-0 text-[10px] text-content-tertiary">
                  {formatDate(item.created_at)}
                </span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

function formatDate(iso: string): string {
  try {
    return new Date(iso).toLocaleDateString();
  } catch {
    return iso;
  }
}
