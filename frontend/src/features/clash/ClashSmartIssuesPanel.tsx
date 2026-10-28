// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// ClashSmartIssuesPanel - project-wide Smart Issues management view.
//
// A "smart issue" is the PERSISTENT, signature-scoped identity of a clash
// across re-runs (see backend ClashIssue). Unlike a ClashResult (one
// geometric pair in one run), a smart issue tracks the same physical clash
// over time, which is what suppression acts on: suppressing an issue stops
// its signature auto-resurfacing in future runs.
//
// This panel surfaces three previously-orphaned backend endpoints:
//   GET  /v1/clash/issues                     (project-wide list + counts)
//   POST /v1/clash/issues/{id}/suppress       (flip to "ignored" + reason)
//   POST /v1/clash/issues/{id}/unsuppress     (flip back to "persisted")
//
// It is intentionally an isolated, project-scoped component (toggled inline
// from the run header, like the KPI dashboard) rather than inlined into the
// already-large ClashDetectionPage. Suppression here complements the
// review-table bulk "Suppress selected" path (which acts on result ids);
// this view lets a coordinator audit + manage the suppression list itself.

import { useMemo, useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';
import {
  ListChecks,
  EyeOff,
  Eye,
  Loader2,
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  X,
} from 'lucide-react';

import { Card } from '@/shared/ui/Card';
import { Button } from '@/shared/ui/Button';
import { Badge } from '@/shared/ui/Badge';
import { EmptyState } from '@/shared/ui/EmptyState';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';

import {
  clashApi,
  type ClashIssue,
  type ClashIssuePage,
  type ClashIssueStatus,
} from './api';

const PAGE_SIZE = 50;
const MAX_REASON = 500;

/** Status filter chips. `all` is the synthetic "no filter" option. */
const STATUS_FILTERS: Array<ClashIssueStatus | 'all'> = [
  'all',
  'new',
  'persisted',
  'resolved',
  'ignored',
  'archived',
];

type BadgeVariant = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

const STATUS_VARIANT: Record<ClashIssueStatus, BadgeVariant> = {
  new: 'blue',
  persisted: 'warning',
  resolved: 'success',
  ignored: 'neutral',
  archived: 'neutral',
};

const PRIORITY_VARIANT: Record<ClashIssue['priority'], BadgeVariant> = {
  critical: 'error',
  high: 'warning',
  medium: 'blue',
  low: 'neutral',
};

export interface ClashSmartIssuesPanelProps {
  projectId: string;
}

export function ClashSmartIssuesPanel({ projectId }: ClashSmartIssuesPanelProps) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [statusFilter, setStatusFilter] = useState<ClashIssueStatus | 'all'>(
    'all',
  );
  const [page, setPage] = useState(0);
  // Issue id currently showing the inline "reason" input (suppress flow);
  // null when no row is in suppress-edit mode.
  const [suppressingId, setSuppressingId] = useState<string | null>(null);
  const [reason, setReason] = useState('');

  const queryKey = useMemo(
    () => ['clash-issues', projectId, statusFilter, page] as const,
    [projectId, statusFilter, page],
  );

  const issuesQuery = useQuery<ClashIssuePage>({
    queryKey,
    queryFn: () =>
      clashApi.issues(projectId, {
        status: statusFilter === 'all' ? undefined : statusFilter,
        offset: page * PAGE_SIZE,
        limit: PAGE_SIZE,
      }),
    enabled: !!projectId,
  });

  // Invalidate every page/status slice of the project's issue list (the
  // status counts shift after a suppress/unsuppress) plus the run-diff
  // badge, whose "ignored" bucket is derived from these same identities.
  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['clash-issues', projectId] });
    void qc.invalidateQueries({ queryKey: ['clash', projectId] });
  };

  const suppressMut = useMutation({
    mutationFn: ({ id, reason: r }: { id: string; reason: string }) =>
      clashApi.suppressIssue(projectId, id, r),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('clash.issues.suppressed', {
          defaultValue: 'Issue suppressed',
        }),
      });
      setSuppressingId(null);
      setReason('');
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const unsuppressMut = useMutation({
    mutationFn: (id: string) => clashApi.unsuppressIssue(projectId, id),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: t('clash.issues.unsuppressed', {
          defaultValue: 'Suppression lifted',
        }),
      });
      invalidate();
    },
    onError: (e: Error) => addToast({ type: 'error', title: e.message }),
  });

  const items = issuesQuery.data?.items ?? [];
  const total = issuesQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const busy = suppressMut.isPending || unsuppressMut.isPending;

  const trimmedReason = reason.trim();

  function openSuppress(id: string) {
    setSuppressingId(id);
    setReason('');
  }

  function cancelSuppress() {
    setSuppressingId(null);
    setReason('');
  }

  function statusLabel(s: ClashIssueStatus | 'all'): string {
    switch (s) {
      case 'all':
        return t('clash.issues.status_all', { defaultValue: 'All' });
      case 'new':
        return t('clash.issues.status_new', { defaultValue: 'New' });
      case 'persisted':
        return t('clash.issues.status_persisted', {
          defaultValue: 'Persisting',
        });
      case 'resolved':
        return t('clash.issues.status_resolved', { defaultValue: 'Resolved' });
      case 'ignored':
        return t('clash.issues.status_ignored', { defaultValue: 'Suppressed' });
      case 'archived':
        return t('clash.issues.status_archived', { defaultValue: 'Archived' });
      default:
        return s;
    }
  }

  return (
    <Card className="p-4 space-y-4" data-testid="clash-smart-issues-panel">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <ListChecks className="h-4 w-4 text-content-tertiary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('clash.issues.title', { defaultValue: 'Smart issues' })}
          </h3>
          {!issuesQuery.isLoading && !issuesQuery.isError && (
            <span className="text-xs text-content-tertiary tabular-nums">
              {t('clash.issues.count', {
                defaultValue: '{{count}} total',
                count: total,
              })}
            </span>
          )}
        </div>
        {/* Status filter chips */}
        <div className="flex flex-wrap items-center gap-1.5">
          {STATUS_FILTERS.map((s) => {
            const active = s === statusFilter;
            return (
              <button
                key={s}
                type="button"
                aria-pressed={active}
                onClick={() => {
                  setStatusFilter(s);
                  setPage(0);
                }}
                className={clsx(
                  'rounded-full px-2.5 py-1 text-xs font-medium ring-1 transition-colors',
                  active
                    ? 'bg-oe-blue text-content-inverse ring-oe-blue'
                    : 'bg-surface-secondary text-content-secondary ring-border hover:bg-surface-tertiary',
                )}
                data-testid={`clash-issues-filter-${s}`}
              >
                {statusLabel(s)}
              </button>
            );
          })}
        </div>
      </div>

      {/* Body: loading / error / empty / list */}
      {issuesQuery.isLoading ? (
        <div className="flex items-center justify-center gap-2 py-10 text-content-tertiary">
          <Loader2 className="h-4 w-4 animate-spin" />
          <span className="text-sm">
            {t('common.loading', { defaultValue: 'Loading...' })}
          </span>
        </div>
      ) : issuesQuery.isError ? (
        <div className="flex flex-col items-center gap-3 py-8 text-center">
          <AlertTriangle className="h-6 w-6 text-semantic-error" />
          <p className="text-sm text-content-secondary">
            {t('clash.issues.load_error', {
              defaultValue: 'Could not load smart issues.',
            })}
          </p>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => void issuesQuery.refetch()}
          >
            {t('common.retry', { defaultValue: 'Retry' })}
          </Button>
        </div>
      ) : items.length === 0 ? (
        <EmptyState
          icon={<ListChecks className="h-6 w-6" />}
          title={t('clash.issues.empty_title', {
            defaultValue: 'No smart issues',
          })}
          description={
            statusFilter === 'all'
              ? t('clash.issues.empty_all', {
                  defaultValue:
                    'Smart issues are created automatically when you run clash detection. Run a detection to start tracking clashes across re-runs.',
                })
              : t('clash.issues.empty_filtered', {
                  defaultValue: 'No issues match the selected status filter.',
                })
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-content-tertiary text-xs uppercase tracking-wide">
                  <th className="py-2 pr-3 font-medium">
                    {t('clash.issues.col_issue', { defaultValue: 'Issue' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('clash.issues.col_status', { defaultValue: 'Status' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('clash.issues.col_priority', {
                      defaultValue: 'Priority',
                    })}
                  </th>
                  <th className="py-2 pr-3 font-medium text-right">
                    {t('clash.issues.col_members', { defaultValue: 'Clashes' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('clash.issues.col_last_seen', {
                      defaultValue: 'Last seen',
                    })}
                  </th>
                  <th className="py-2 font-medium text-right">
                    {t('clash.issues.col_actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {items.map((issue) => {
                  const suppressed = issue.status === 'ignored';
                  const isSuppressingRow = suppressingId === issue.id;
                  return (
                    <tr
                      key={issue.id}
                      className="border-t border-border align-top"
                      data-testid={`clash-issue-row-${issue.id}`}
                    >
                      <td className="py-2.5 pr-3">
                        <div className="font-medium text-content-primary">
                          {issue.server_assigned_id ||
                            t('clash.issues.unlabelled', {
                              defaultValue: 'Issue',
                            })}
                        </div>
                        <div
                          className="font-mono text-2xs text-content-tertiary truncate max-w-[16ch]"
                          title={issue.signature_hash}
                        >
                          {issue.signature_hash.slice(0, 12)}
                        </div>
                        {isSuppressingRow && (
                          <div className="mt-2 flex flex-col gap-1.5">
                            <label
                              htmlFor={`suppress-reason-${issue.id}`}
                              className="text-2xs font-medium text-content-secondary"
                            >
                              {t('clash.issues.reason_label', {
                                defaultValue: 'Suppression reason (required)',
                              })}
                            </label>
                            <input
                              id={`suppress-reason-${issue.id}`}
                              type="text"
                              value={reason}
                              maxLength={MAX_REASON}
                              autoFocus
                              onChange={(e) => setReason(e.target.value)}
                              onKeyDown={(e) => {
                                if (
                                  e.key === 'Enter' &&
                                  trimmedReason &&
                                  !busy
                                ) {
                                  suppressMut.mutate({
                                    id: issue.id,
                                    reason: trimmedReason,
                                  });
                                } else if (e.key === 'Escape') {
                                  cancelSuppress();
                                }
                              }}
                              placeholder={t('clash.issues.reason_placeholder', {
                                defaultValue: 'e.g. known false positive',
                              })}
                              className="w-full max-w-xs rounded-md border border-border bg-surface-primary px-2 py-1 text-xs text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
                              data-testid={`clash-issue-reason-${issue.id}`}
                            />
                            <div className="flex items-center gap-2">
                              <Button
                                variant="primary"
                                size="sm"
                                disabled={!trimmedReason}
                                loading={
                                  suppressMut.isPending &&
                                  suppressMut.variables?.id === issue.id
                                }
                                onClick={() =>
                                  suppressMut.mutate({
                                    id: issue.id,
                                    reason: trimmedReason,
                                  })
                                }
                                data-testid={`clash-issue-confirm-suppress-${issue.id}`}
                              >
                                {t('clash.issues.confirm_suppress', {
                                  defaultValue: 'Suppress',
                                })}
                              </Button>
                              <button
                                type="button"
                                onClick={cancelSuppress}
                                className="inline-flex items-center gap-1 text-2xs text-content-tertiary hover:text-content-secondary"
                              >
                                <X className="h-3 w-3" />
                                {t('common.cancel', { defaultValue: 'Cancel' })}
                              </button>
                            </div>
                          </div>
                        )}
                      </td>
                      <td className="py-2.5 pr-3">
                        <Badge variant={STATUS_VARIANT[issue.status]} size="sm">
                          {statusLabel(issue.status)}
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-3">
                        <Badge
                          variant={PRIORITY_VARIANT[issue.priority]}
                          size="sm"
                        >
                          <span className="capitalize">{issue.priority}</span>
                        </Badge>
                      </td>
                      <td className="py-2.5 pr-3 text-right tabular-nums">
                        {issue.member_count}
                      </td>
                      <td className="py-2.5 pr-3 text-content-secondary">
                        <DateDisplay value={issue.updated_at} format="relative" />
                      </td>
                      <td className="py-2.5 text-right">
                        {suppressed ? (
                          <Button
                            variant="secondary"
                            size="sm"
                            loading={
                              unsuppressMut.isPending &&
                              unsuppressMut.variables === issue.id
                            }
                            disabled={busy && !isSuppressingRow}
                            onClick={() => unsuppressMut.mutate(issue.id)}
                            data-testid={`clash-issue-unsuppress-${issue.id}`}
                          >
                            <Eye className="h-3.5 w-3.5" />
                            {t('clash.issues.unsuppress', {
                              defaultValue: 'Unsuppress',
                            })}
                          </Button>
                        ) : (
                          !isSuppressingRow && (
                            <Button
                              variant="ghost"
                              size="sm"
                              disabled={busy}
                              onClick={() => openSuppress(issue.id)}
                              data-testid={`clash-issue-suppress-${issue.id}`}
                            >
                              <EyeOff className="h-3.5 w-3.5" />
                              {t('clash.issues.suppress', {
                                defaultValue: 'Suppress',
                              })}
                            </Button>
                          )
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {total > PAGE_SIZE && (
            <div className="flex items-center justify-between pt-1">
              <span className="text-xs text-content-tertiary tabular-nums">
                {t('clash.issues.page_of', {
                  defaultValue: 'Page {{page}} of {{total}}',
                  page: page + 1,
                  total: totalPages,
                })}
              </span>
              <div className="flex items-center gap-2">
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page === 0}
                  onClick={() => setPage((p) => Math.max(0, p - 1))}
                  data-testid="clash-issues-prev"
                >
                  <ChevronLeft className="h-4 w-4" />
                  {t('common.previous', { defaultValue: 'Previous' })}
                </Button>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={page + 1 >= totalPages}
                  onClick={() =>
                    setPage((p) => Math.min(totalPages - 1, p + 1))
                  }
                  data-testid="clash-issues-next"
                >
                  {t('common.next', { defaultValue: 'Next' })}
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </Card>
  );
}
