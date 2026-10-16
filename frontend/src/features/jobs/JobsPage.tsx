// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  ChevronLeft,
  ChevronRight,
  Clock,
  Download,
  Loader2,
  ListChecks,
  Search,
  X,
  XCircle,
} from 'lucide-react';
import { Link } from 'react-router-dom';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';
import { Badge, CollapsibleSection, EmptyState } from '@/shared/ui';
import type { BadgeVariant } from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useJobs, useJob, useCancelJob, type JobRun, type JobStatus, type JobListFilters } from './api';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LIMIT = 50;

const STATUS_OPTIONS: JobStatus[] = ['pending', 'started', 'success', 'failure', 'cancelled'];

const STATUS_BADGE_VARIANT: Record<JobStatus, BadgeVariant> = {
  success: 'success',
  failure: 'error',
  pending: 'warning',
  started: 'blue',
  cancelled: 'neutral',
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function fullDateTime(iso: string | null): string {
  if (!iso) return '-';
  return new Date(iso).toLocaleString(getIntlLocale(), {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function durationLabel(start: string | null, end: string | null): string {
  if (!start) return '-';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const diff = Math.max(0, e - s);
  if (diff < 1_000) return `${diff}ms`;
  if (diff < 60_000) return `${fmtFixed(diff / 1_000, 1)}s`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ${Math.floor((diff % 60_000) / 1_000)}s`;
  return `${Math.floor(diff / 3_600_000)}h ${Math.floor((diff % 3_600_000) / 60_000)}m`;
}

function canCancel(status: JobStatus): boolean {
  return status === 'pending' || status === 'started';
}

// ---------------------------------------------------------------------------
// Explainer
// ---------------------------------------------------------------------------

function JobsExplainer() {
  const { t } = useTranslation();

  const steps = [
    {
      num: 1,
      title: t('jobs.flow_step_1', { defaultValue: 'Tasks are queued' }),
      desc: t('jobs.flow_step_1_desc', {
        defaultValue:
          'Long-running operations such as PDF generation, data imports and cost recalculations are sent to the background queue instead of blocking the UI.',
      }),
    },
    {
      num: 2,
      title: t('jobs.flow_step_2', { defaultValue: 'Monitor progress' }),
      desc: t('jobs.flow_step_2_desc', {
        defaultValue:
          'Each job shows its kind, status and a live progress bar. Click a row to see timing, the Celery task ID, result payload or error details.',
      }),
    },
    {
      num: 3,
      title: t('jobs.flow_step_3', { defaultValue: 'Cancel or export' }),
      desc: t('jobs.flow_step_3_desc', {
        defaultValue:
          'Stuck or unnecessary jobs can be cancelled while they are pending or running. Finished jobs let you download the result or error payload as JSON.',
      }),
    },
    {
      num: 4,
      title: t('jobs.flow_step_4', { defaultValue: 'Filter and page' }),
      desc: t('jobs.flow_step_4_desc', {
        defaultValue:
          'Narrow the list by status or job kind, and search across the current page. Server-side pagination keeps the view responsive even with thousands of runs.',
      }),
    },
  ];

  return (
    <CollapsibleSection
      storageKey="jobs.how"
      icon={<ListChecks size={15} className="text-oe-blue" />}
      title={t('jobs.flow_title', { defaultValue: 'How background jobs work' })}
    >
      <p className="text-xs text-content-tertiary">
        {t('jobs.flow_intro', {
          defaultValue:
            'Background jobs handle heavy work off the main thread so the interface stays responsive. This page is the single place to watch, cancel and inspect every queued task.',
        })}
      </p>
      <ol className="mt-3 space-y-2">
        {steps.map((s) => (
          <li key={s.num} className="flex gap-3 text-xs">
            <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-oe-blue/10 text-[10px] font-bold text-oe-blue-text">
              {s.num}
            </span>
            <div>
              <span className="font-medium text-content-primary">{s.title}</span>
              <span className="text-content-tertiary"> - {s.desc}</span>
            </div>
          </li>
        ))}
      </ol>
      <div className="mt-3 border-t border-border-light pt-3 text-2xs text-content-tertiary">
        <span className="font-medium text-content-secondary">
          {t('jobs.flow_related', { defaultValue: 'Related:' })}
        </span>{' '}
        <Link to="/schedule" className="font-medium text-oe-blue-text hover:underline">
          {t('jobs.mod_schedule', { defaultValue: 'Schedule' })}
        </Link>
        {' · '}
        <Link to="/settings" className="font-medium text-oe-blue-text hover:underline">
          {t('jobs.mod_settings', { defaultValue: 'Settings' })}
        </Link>
        {' · '}
        <Link to="/timeline" className="font-medium text-oe-blue-text hover:underline">
          {t('jobs.mod_timeline', { defaultValue: 'Timeline' })}
        </Link>
      </div>
    </CollapsibleSection>
  );
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function JobsPage() {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // Filters
  const [statusFilter, setStatusFilter] = useState<JobStatus | ''>('');
  const [kindFilter, setKindFilter] = useState('');
  const [search, setSearch] = useState('');
  const [offset, setOffset] = useState(0);

  // Selected row for detail panel
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const filters: JobListFilters = useMemo(() => ({
    status: statusFilter || undefined,
    kind: kindFilter || undefined,
    limit: LIMIT,
    offset,
  }), [statusFilter, kindFilter, offset]);

  const { data, isLoading, error } = useJobs(filters);
  const { data: selectedJob } = useJob(selectedId);
  const cancelMutation = useCancelJob();

  const items = data?.items ?? [];
  const total = data?.total ?? 0;
  const pageCount = Math.ceil(total / LIMIT);
  const currentPage = Math.floor(offset / LIMIT) + 1;

  // Client-side search within the loaded page
  const filtered = useMemo(() => {
    if (!search) return items;
    const q = search.toLowerCase();
    return items.filter(
      (j) =>
        j.kind.toLowerCase().includes(q) ||
        j.status.toLowerCase().includes(q) ||
        (j.progress_message && j.progress_message.toLowerCase().includes(q)) ||
        j.id.toLowerCase().includes(q),
    );
  }, [items, search]);

  // Distinct kinds from the current page for the kind filter dropdown
  const kinds = useMemo(() => {
    const set = new Set<string>();
    items.forEach((j) => set.add(j.kind));
    return Array.from(set).sort();
  }, [items]);

  const handleCancel = useCallback(
    (id: string) => {
      cancelMutation.mutate(id, {
        onSuccess: () => {
          addToast({
            type: 'success',
            title: t('jobs.cancel_success', { defaultValue: 'Job cancelled' }),
          });
        },
        onError: (err: Error) => {
          addToast({
            type: 'error',
            title: t('jobs.cancel_failed', { defaultValue: 'Cancel failed' }),
            message: err.message,
          });
        },
      });
    },
    [cancelMutation, addToast, t],
  );

  const handleExportResult = useCallback(
    (job: JobRun) => {
      const payload = job.result_jsonb ?? job.error_jsonb ?? {};
      const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
      const url = URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `job-${job.id}-result.json`;
      a.click();
      URL.revokeObjectURL(url);
    },
    [],
  );

  return (
    <div className="space-y-5">
      <PageHeader
        srTitle={t('jobs.page_title', { defaultValue: 'Background Jobs' })}
        subtitle={t('jobs.subtitle', {
          defaultValue: 'Monitor and manage background tasks running on the server',
        })}
      />

      <JobsExplainer />

      {/* Filter bar */}
      <div className="flex flex-wrap items-center gap-3">
        <div className="relative min-w-[200px] flex-1">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
          <input
            type="text"
            placeholder={t('jobs.search', { defaultValue: 'Search jobs...' })}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-gray-200 bg-white py-2 pe-4 ps-10 text-sm
              focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500
              dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
          />
          {search && (
            <button
              onClick={() => setSearch('')}
              className="absolute right-3 top-1/2 -translate-y-1/2"
              aria-label={t('common.clear_search', { defaultValue: 'Clear search' })}
            >
              <X className="h-4 w-4 text-gray-400 hover:text-gray-600" aria-hidden />
            </button>
          )}
        </div>

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as JobStatus | ''); setOffset(0); }}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('jobs.all_statuses', { defaultValue: 'All statuses' })}</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {t(`jobs.status_${s}`, { defaultValue: s.charAt(0).toUpperCase() + s.slice(1) })}
            </option>
          ))}
        </select>

        <select
          value={kindFilter}
          onChange={(e) => { setKindFilter(e.target.value); setOffset(0); }}
          className="rounded-lg border border-gray-200 bg-white px-3 py-2 text-sm
            dark:border-gray-700 dark:bg-gray-900 dark:text-gray-100"
        >
          <option value="">{t('jobs.all_kinds', { defaultValue: 'All kinds' })}</option>
          {kinds.map((k) => (
            <option key={k} value={k}>{k}</option>
          ))}
        </select>
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="py-16 text-center text-gray-500">
          <Clock className="mx-auto mb-2 h-6 w-6 animate-spin" />
          {t('common.loading', { defaultValue: 'Loading...' })}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {t('jobs.load_error', { defaultValue: 'Could not load background jobs' })}
        </div>
      )}

      {/* Empty */}
      {!isLoading && !error && filtered.length === 0 && (
        <EmptyState
          icon={<ListChecks className="h-12 w-12" />}
          title={t('jobs.empty', { defaultValue: 'No jobs found' })}
          description={t('jobs.empty_desc', {
            defaultValue: 'Background jobs will appear here when tasks are queued.',
          })}
        />
      )}

      {/* Table */}
      {!isLoading && filtered.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-gray-200 dark:border-gray-700">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-gray-200 bg-gray-50 text-xs font-medium uppercase text-gray-500 dark:border-gray-700 dark:bg-gray-800 dark:text-gray-400">
              <tr>
                <th className="px-4 py-3">{t('jobs.col_kind', { defaultValue: 'Kind' })}</th>
                <th className="px-4 py-3">{t('jobs.col_status', { defaultValue: 'Status' })}</th>
                <th className="px-4 py-3">{t('jobs.col_progress', { defaultValue: 'Progress' })}</th>
                <th className="px-4 py-3">{t('jobs.col_created', { defaultValue: 'Created' })}</th>
                <th className="px-4 py-3">{t('jobs.col_duration', { defaultValue: 'Duration' })}</th>
                <th className="px-4 py-3">{t('jobs.col_actions', { defaultValue: 'Actions' })}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-800">
              {filtered.map((job) => (
                <tr
                  key={job.id}
                  onClick={() => setSelectedId(selectedId === job.id ? null : job.id)}
                  className={`cursor-pointer transition-colors
                    ${selectedId === job.id
                      ? 'bg-blue-50 dark:bg-blue-950/30'
                      : 'bg-white hover:bg-gray-50 dark:bg-gray-900 dark:hover:bg-gray-800/50'}`}
                >
                  <td className="px-4 py-3 font-medium text-gray-900 dark:text-gray-100">
                    {job.kind}
                  </td>
                  <td className="px-4 py-3">
                    <Badge variant={STATUS_BADGE_VARIANT[job.status]} dot size="sm">
                      {t(`jobs.status_${job.status}`, {
                        defaultValue: job.status.charAt(0).toUpperCase() + job.status.slice(1),
                      })}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <ProgressCell job={job} />
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-500 dark:text-gray-400">
                    {fullDateTime(job.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-4 py-3 text-gray-500 dark:text-gray-400">
                    {durationLabel(job.started_at, job.finished_at)}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      {canCancel(job.status) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleCancel(job.id); }}
                          disabled={cancelMutation.isPending}
                          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium
                            text-red-600 hover:bg-red-50 disabled:opacity-50
                            dark:text-red-400 dark:hover:bg-red-950/30"
                          title={t('jobs.cancel', { defaultValue: 'Cancel job' })}
                        >
                          {cancelMutation.isPending ? (
                            <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
                          ) : (
                            <XCircle className="h-3.5 w-3.5" aria-hidden />
                          )}
                          {t('jobs.cancel', { defaultValue: 'Cancel' })}
                        </button>
                      )}
                      {(job.result_jsonb || job.error_jsonb) && (
                        <button
                          onClick={(e) => { e.stopPropagation(); handleExportResult(job); }}
                          className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium
                            text-gray-600 hover:bg-gray-100
                            dark:text-gray-400 dark:hover:bg-gray-800"
                          title={t('jobs.export_result', { defaultValue: 'Download result JSON' })}
                        >
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          JSON
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Detail panel */}
      {selectedId && selectedJob && (
        <JobDetailPanel
          job={selectedJob}
          onClose={() => setSelectedId(null)}
          onCancel={handleCancel}
          onExport={handleExportResult}
          cancelPending={cancelMutation.isPending}
        />
      )}

      {/* Pagination */}
      {total > LIMIT && (
        <div className="mt-4 flex items-center justify-between text-sm text-gray-500">
          <span>
            {t('jobs.showing', {
              defaultValue: '{{from}}-{{to}} of {{total}}',
              from: offset + 1,
              to: Math.min(offset + LIMIT, total),
              total,
            })}
          </span>
          <div className="flex gap-1">
            <button
              onClick={() => setOffset(Math.max(0, offset - LIMIT))}
              disabled={offset === 0}
              className="rounded p-1.5 hover:bg-gray-100 disabled:opacity-30 dark:hover:bg-gray-800"
              aria-label={t('common.previous_page', { defaultValue: 'Previous page' })}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden />
            </button>
            <span className="px-2 py-1">{currentPage} / {pageCount}</span>
            <button
              onClick={() => setOffset(offset + LIMIT)}
              disabled={offset + LIMIT >= total}
              className="rounded p-1.5 hover:bg-gray-100 disabled:opacity-30 dark:hover:bg-gray-800"
              aria-label={t('common.next_page', { defaultValue: 'Next page' })}
            >
              <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function ProgressCell({ job }: { job: JobRun }) {
  const { t } = useTranslation();

  if (job.status !== 'started' && job.status !== 'pending') {
    return <span className="text-xs text-gray-400">-</span>;
  }

  const pct = job.progress_pct ?? 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 overflow-hidden rounded-full bg-gray-200 dark:bg-gray-700">
        <div
          className="h-full rounded-full bg-blue-500 transition-all duration-300"
          style={{ width: `${Math.min(100, Math.max(0, pct))}%` }}
        />
      </div>
      <span className="text-xs text-gray-500 dark:text-gray-400">
        {pct > 0 ? `${pct}%` : t('jobs.waiting', { defaultValue: 'Waiting' })}
      </span>
    </div>
  );
}

function JobDetailPanel({
  job,
  onClose,
  onCancel,
  onExport,
  cancelPending,
}: {
  job: JobRun;
  onClose: () => void;
  onCancel: (id: string) => void;
  onExport: (job: JobRun) => void;
  cancelPending: boolean;
}) {
  const { t } = useTranslation();

  return (
    <div className="mt-4 rounded-lg border border-blue-200 bg-blue-50/50 p-4 dark:border-blue-900 dark:bg-blue-950/30">
      <div className="mb-3 flex items-center justify-between">
        <h3 className="text-sm font-semibold text-gray-900 dark:text-gray-100">
          {t('jobs.detail_title', { defaultValue: 'Job Details' })}
        </h3>
        <button onClick={onClose} aria-label={t('common.close', { defaultValue: 'Close' })}>
          <X className="h-4 w-4 text-gray-400 hover:text-gray-600" aria-hidden />
        </button>
      </div>

      <div className="grid gap-2 text-sm sm:grid-cols-2">
        <div>
          <span className="text-gray-500">{t('jobs.detail_id', { defaultValue: 'ID' })}:</span>{' '}
          <span className="font-mono text-xs">{job.id}</span>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_kind', { defaultValue: 'Kind' })}:</span>{' '}
          <span className="font-medium">{job.kind}</span>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_status', { defaultValue: 'Status' })}:</span>{' '}
          <Badge variant={STATUS_BADGE_VARIANT[job.status]} dot size="sm">
            {t(`jobs.status_${job.status}`, {
              defaultValue: job.status.charAt(0).toUpperCase() + job.status.slice(1),
            })}
          </Badge>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_created', { defaultValue: 'Created' })}:</span>{' '}
          <span className="font-medium">{fullDateTime(job.created_at)}</span>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_started', { defaultValue: 'Started' })}:</span>{' '}
          <span className="font-medium">{fullDateTime(job.started_at)}</span>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_finished', { defaultValue: 'Finished' })}:</span>{' '}
          <span className="font-medium">{fullDateTime(job.finished_at)}</span>
        </div>
        <div>
          <span className="text-gray-500">{t('jobs.detail_duration', { defaultValue: 'Duration' })}:</span>{' '}
          <span className="font-medium">{durationLabel(job.started_at, job.finished_at)}</span>
        </div>
        {job.celery_task_id && (
          <div>
            <span className="text-gray-500">{t('jobs.detail_celery_id', { defaultValue: 'Celery Task' })}:</span>{' '}
            <span className="font-mono text-xs">{job.celery_task_id}</span>
          </div>
        )}

        {/* Progress for active jobs */}
        {canCancel(job.status) && (
          <div className="sm:col-span-2">
            <span className="text-gray-500">{t('jobs.detail_progress', { defaultValue: 'Progress' })}:</span>{' '}
            <ProgressCell job={job} />
            {job.progress_message && (
              <p className="mt-1 text-xs text-gray-500">{job.progress_message}</p>
            )}
          </div>
        )}

        {/* Result data */}
        {job.result_jsonb && Object.keys(job.result_jsonb).length > 0 && (
          <div className="sm:col-span-2">
            <p className="mb-1 text-gray-500">{t('jobs.detail_result', { defaultValue: 'Result' })}:</p>
            <pre className="max-h-48 overflow-auto rounded bg-gray-100 p-2 text-xs text-gray-700 dark:bg-gray-800 dark:text-gray-300">
              {JSON.stringify(job.result_jsonb, null, 2)}
            </pre>
          </div>
        )}

        {/* Error data */}
        {job.error_jsonb && Object.keys(job.error_jsonb).length > 0 && (
          <div className="sm:col-span-2">
            <p className="mb-1 text-red-600 dark:text-red-400">{t('jobs.detail_error', { defaultValue: 'Error' })}:</p>
            <pre className="max-h-48 overflow-auto rounded bg-red-50 p-2 text-xs text-red-700 dark:bg-red-950/50 dark:text-red-300">
              {JSON.stringify(job.error_jsonb, null, 2)}
            </pre>
          </div>
        )}

        {/* Actions */}
        <div className="flex gap-2 sm:col-span-2">
          {canCancel(job.status) && (
            <button
              onClick={() => onCancel(job.id)}
              disabled={cancelPending}
              className="inline-flex items-center gap-1.5 rounded-lg bg-red-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-red-700 disabled:opacity-50"
            >
              {cancelPending ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              ) : (
                <XCircle className="h-3.5 w-3.5" aria-hidden />
              )}
              {t('jobs.cancel', { defaultValue: 'Cancel' })}
            </button>
          )}
          {(job.result_jsonb || job.error_jsonb) && (
            <button
              onClick={() => onExport(job)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-gray-200 px-3 py-1.5 text-xs font-medium text-gray-600 hover:bg-gray-100 dark:border-gray-700 dark:text-gray-400 dark:hover:bg-gray-800"
            >
              <Download className="h-3.5 w-3.5" aria-hidden />
              {t('jobs.export_result', { defaultValue: 'Download JSON' })}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
