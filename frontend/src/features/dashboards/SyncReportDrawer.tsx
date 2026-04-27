/**
 * SyncReportDrawer (T09 / task #192) — review pane for preset sync
 * issues.
 *
 * Presents the four issue groups (column renames, dropped columns,
 * dropped filter values, dtype changes) with severity-coded styling.
 * Emits an "Auto-heal" action that calls :func:`applySyncHeal` and
 * invalidates the preset-list query so the page picks up the patched
 * config + new ``sync_status``.
 */
import { useTranslation } from 'react-i18next';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { AlertCircle, AlertTriangle, RefreshCw, X } from 'lucide-react';
import clsx from 'clsx';

import { Button } from '@/shared/ui';

import {
  applySyncHeal,
  type SyncIssue,
  type SyncReport,
  type SyncSeverity,
} from './api';

export interface SyncReportDrawerProps {
  presetId: string;
  report: SyncReport | null;
  isLoading: boolean;
  onClose: () => void;
}

const SEVERITY_TONE: Record<SyncSeverity, string> = {
  warning: 'bg-semantic-warning-bg text-[#b45309] border-semantic-warning',
  error: 'bg-semantic-error-bg text-semantic-error border-semantic-error',
};

export function SyncReportDrawer({
  presetId,
  report,
  isLoading,
  onClose,
}: SyncReportDrawerProps) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();

  const healMutation = useMutation({
    mutationFn: () => applySyncHeal(presetId),
    onSuccess: () => {
      // Refresh the preset list and the per-preset report cache so
      // the badge falls back to its post-heal status.
      queryClient.invalidateQueries({ queryKey: ['dashboard-presets'] });
      queryClient.invalidateQueries({
        queryKey: ['preset-sync-report', presetId],
      });
      onClose();
    },
  });

  const allIssues = collectIssues(report);
  const hasAutoHealable =
    allIssues.some(
      (i) => i.suggested_fix === 'auto_rename' || i.suggested_fix === 'drop_filter',
    );

  return (
    <div
      className="fixed inset-0 z-40 flex justify-end bg-black/40"
      role="dialog"
      aria-modal="true"
      data-testid="sync-report-drawer"
      onClick={onClose}
    >
      <aside
        className="w-[440px] max-w-[95vw] bg-surface-primary shadow-xl flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <header className="flex items-center justify-between border-b border-border-light px-4 py-3">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('dashboards.sync.drawer_title', {
              defaultValue: 'Preset sync report',
            })}
          </h3>
          <button
            type="button"
            onClick={onClose}
            data-testid="sync-report-drawer-close"
            aria-label={t('common.close', { defaultValue: 'Close' })}
            className="rounded p-1 hover:bg-surface-secondary"
          >
            <X className="h-4 w-4" />
          </button>
        </header>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {isLoading && (
            <div
              data-testid="sync-report-loading"
              className="text-xs text-content-tertiary"
            >
              {t('common.loading', { defaultValue: 'Loading…' })}
            </div>
          )}

          {!isLoading && report && report.is_in_sync && (
            <div
              data-testid="sync-report-in-sync"
              className="rounded border border-semantic-success bg-semantic-success-bg p-3 text-xs text-semantic-success"
            >
              {t('dashboards.sync.in_sync_msg', {
                defaultValue: 'This preset is in sync with the current snapshot.',
              })}
            </div>
          )}

          {!isLoading && report && !report.is_in_sync && (
            <>
              <IssueGroup
                title={t('dashboards.sync.group_dropped_columns', {
                  defaultValue: 'Dropped columns',
                })}
                issues={report.dropped_columns}
                testId="dropped-columns"
              />
              <IssueGroup
                title={t('dashboards.sync.group_renames', {
                  defaultValue: 'Renamed columns',
                })}
                issues={report.column_renames}
                testId="column-renames"
              />
              <IssueGroup
                title={t('dashboards.sync.group_dropped_values', {
                  defaultValue: 'Filter values no longer present',
                })}
                issues={report.dropped_filter_values}
                testId="dropped-filter-values"
              />
              <IssueGroup
                title={t('dashboards.sync.group_dtype_changes', {
                  defaultValue: 'Data type changes',
                })}
                issues={report.dtype_changes}
                testId="dtype-changes"
              />
            </>
          )}
        </div>

        <footer className="border-t border-border-light px-4 py-3 flex justify-end gap-2">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={onClose}
            data-testid="sync-report-cancel"
          >
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button
            type="button"
            size="sm"
            disabled={!hasAutoHealable || healMutation.isPending}
            onClick={() => healMutation.mutate()}
            data-testid="sync-report-auto-heal"
          >
            <RefreshCw
              className={clsx(
                'mr-1 h-3 w-3',
                healMutation.isPending && 'animate-spin',
              )}
            />
            {t('dashboards.sync.auto_heal', {
              defaultValue: 'Auto-heal',
            })}
          </Button>
        </footer>
      </aside>
    </div>
  );
}

interface IssueGroupProps {
  title: string;
  issues: SyncIssue[];
  testId: string;
}

function IssueGroup({ title, issues, testId }: IssueGroupProps) {
  if (issues.length === 0) return null;
  return (
    <section data-testid={`sync-issue-group-${testId}`}>
      <h4 className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-content-tertiary">
        {title}
      </h4>
      <ul className="space-y-1.5">
        {issues.map((issue, idx) => (
          <li key={`${issue.column}-${idx}`}>
            <IssueRow issue={issue} />
          </li>
        ))}
      </ul>
    </section>
  );
}

function IssueRow({ issue }: { issue: SyncIssue }) {
  const Icon = issue.severity === 'error' ? AlertCircle : AlertTriangle;
  return (
    <div
      className={clsx(
        'flex items-start gap-2 rounded border px-2 py-1.5 text-xs',
        SEVERITY_TONE[issue.severity],
      )}
      data-testid={`sync-issue-${issue.kind}-${issue.column}`}
    >
      <Icon className="mt-0.5 h-3.5 w-3.5 shrink-0" />
      <div className="flex-1">
        <div className="font-medium">{issue.column}</div>
        <div className="text-[11px] opacity-80">
          {issue.message ||
            (issue.kind === 'column_rename' && issue.new_column
              ? `→ ${issue.new_column}`
              : issue.kind === 'dropped_filter_value'
                ? issue.dropped_values.slice(0, 3).join(', ')
                : issue.kind === 'dtype_change'
                  ? `${issue.old_dtype ?? '?'} → ${issue.new_dtype ?? '?'}`
                  : '')}
        </div>
        <div className="text-[10px] opacity-60 mt-0.5">
          {issue.suggested_fix === 'manual'
            ? 'Manual review required'
            : 'Auto-healable'}
        </div>
      </div>
    </div>
  );
}

function collectIssues(report: SyncReport | null): SyncIssue[] {
  if (!report) return [];
  return [
    ...report.column_renames,
    ...report.dropped_columns,
    ...report.dropped_filter_values,
    ...report.dtype_changes,
  ];
}
