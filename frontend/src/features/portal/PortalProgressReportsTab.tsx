// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Subcontractor / client portal — Progress Reports tab (magic-link surface).
 *
 * Portal-user-facing (magic-link SESSION token, NOT the internal JWT). Lets an
 * external client or subcontractor browse the progress reports for any project
 * they hold a `project` access rule on, and open or download the rendered HTML
 * body of one. Both the project list and the report list are RLS-scoped
 * server-side; a project the caller was not granted 404s.
 *
 * Mobile-first: single-column stacked cards at 375px, a light table from sm+.
 * Money / dates are rendered through the shared helpers; no hardcoded strings.
 */

import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileText, ExternalLink, Download, Loader2, AlertCircle } from 'lucide-react';
import { Badge, Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { openInNewTab } from '@/shared/lib/desktop';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useToastStore } from '@/stores/useToastStore';
import {
  listMyProjects,
  listMyProgressReports,
  fetchMyProgressReportHtml,
  type PortalProgressReport,
} from './api';

const inputCls =
  'h-10 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

export function PortalProgressReportsTab() {
  const { t } = useTranslation();
  const [projectId, setProjectId] = useState('');

  const projectsQ = useQuery({
    queryKey: ['portal-progress', 'projects'],
    queryFn: () => listMyProjects(),
    staleTime: 60_000,
  });

  const projects = projectsQ.data ?? [];

  // Auto-select the single accessible project so a one-project client lands
  // straight on their reports without a redundant pick.
  useEffect(() => {
    const first = projects[0];
    if (!projectId && projects.length === 1 && first) setProjectId(first.id);
  }, [projects, projectId]);

  const reportsQ = useQuery({
    queryKey: ['portal-progress', 'reports', projectId],
    queryFn: () => listMyProgressReports(projectId),
    enabled: !!projectId,
  });

  const reports = reportsQ.data?.items ?? [];

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold text-content-primary">
          {t('payportal.progress_title', { defaultValue: 'Progress Reports' })}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t('payportal.progress_subtitle', {
            defaultValue: 'Open and download the progress reports shared with you.',
          })}
        </p>
      </div>

      {projectsQ.isLoading ? (
        <Card padding="md">
          <SkeletonTable rows={3} columns={2} />
        </Card>
      ) : projectsQ.error ? (
        <Card padding="none">
          <EmptyState
            icon={<AlertCircle size={22} />}
            title={t('payportal.progress_load_failed', {
              defaultValue: 'Could not load progress reports',
            })}
            description={projectsQ.error instanceof Error ? projectsQ.error.message : ''}
            action={{
              label: t('common.retry', { defaultValue: 'Retry' }),
              onClick: () => void projectsQ.refetch(),
            }}
          />
        </Card>
      ) : projects.length === 0 ? (
        <Card padding="none">
          <EmptyState
            icon={<FileText size={22} />}
            title={t('payportal.progress_no_projects', {
              defaultValue: 'No projects shared with you yet',
            })}
            description={t('payportal.progress_no_projects_desc', {
              defaultValue:
                'When a project team shares progress reports with you, the project will appear here.',
            })}
          />
        </Card>
      ) : (
        <>
          {projects.length > 1 ? (
            <div className="max-w-md">
              <label
                htmlFor="portal-progress-project"
                className="mb-1 block text-2xs font-medium uppercase tracking-wide text-content-tertiary"
              >
                {t('payportal.progress_project', { defaultValue: 'Project' })}
              </label>
              <select
                id="portal-progress-project"
                value={projectId}
                onChange={(e) => setProjectId(e.target.value)}
                className={inputCls}
              >
                <option value="">
                  {t('payportal.progress_select_project', { defaultValue: 'Select a project…' })}
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                    {p.project_code ? ` (${p.project_code})` : ''}
                  </option>
                ))}
              </select>
            </div>
          ) : null}

          {!projectId ? (
            <Card padding="none">
              <EmptyState
                icon={<FileText size={22} />}
                title={t('payportal.progress_pick_project', {
                  defaultValue: 'Pick a project to see its progress reports',
                })}
              />
            </Card>
          ) : reportsQ.isLoading ? (
            <Card padding="md">
              <SkeletonTable rows={4} columns={3} />
            </Card>
          ) : reportsQ.error ? (
            <Card padding="none">
              <EmptyState
                icon={<AlertCircle size={22} />}
                title={t('payportal.progress_load_failed', {
                  defaultValue: 'Could not load progress reports',
                })}
                description={reportsQ.error instanceof Error ? reportsQ.error.message : ''}
                action={{
                  label: t('common.retry', { defaultValue: 'Retry' }),
                  onClick: () => void reportsQ.refetch(),
                }}
              />
            </Card>
          ) : reports.length === 0 ? (
            <Card padding="none">
              <EmptyState
                icon={<FileText size={22} />}
                title={t('payportal.progress_empty', {
                  defaultValue: 'No progress reports yet',
                })}
                description={t('payportal.progress_empty_desc', {
                  defaultValue: 'Progress reports shared with you for this project will appear here.',
                })}
              />
            </Card>
          ) : (
            <ul className="space-y-3">
              {reports.map((r) => (
                <ProgressReportCard key={r.id} projectId={projectId} report={r} />
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  );
}

function ProgressReportCard({
  projectId,
  report,
}: {
  projectId: string;
  report: PortalProgressReport;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState<'open' | 'download' | null>(null);
  const ready = report.has_content;

  const withHtml = async (
    use: (html: string) => void,
  ): Promise<void> => {
    try {
      const html = await fetchMyProgressReportHtml(projectId, report.id);
      if (html === null) {
        addToast({
          type: 'error',
          title: t('payportal.progress_not_rendered', {
            defaultValue: 'This report has no rendered body yet.',
          }),
        });
        return;
      }
      use(html);
    } catch (err) {
      addToast({
        type: 'error',
        title: err instanceof Error ? err.message : t('payportal.progress_open_failed', {
          defaultValue: 'Could not open the report.',
        }),
      });
    }
  };

  const onOpen = async () => {
    setBusy('open');
    await withHtml((html) => {
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
      openInNewTab(url);
      setTimeout(() => URL.revokeObjectURL(url), 60_000);
    });
    setBusy(null);
  };

  const onDownload = async () => {
    setBusy('download');
    await withHtml((html) => {
      const url = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `${report.title || 'progress-report'}.html`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
    });
    setBusy(null);
  };

  return (
    <li className="rounded-xl border border-border bg-surface-primary p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <FileText size={16} className="shrink-0 text-content-tertiary" />
          <span className="truncate text-sm font-medium text-content-primary">{report.title}</span>
        </div>
        {ready ? (
          <Badge variant="success" dot>
            {t('payportal.progress_ready', { defaultValue: 'Ready' })}
          </Badge>
        ) : (
          <Badge variant="neutral" dot>
            {t('payportal.progress_pending', { defaultValue: 'Pending' })}
          </Badge>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-2xs text-content-tertiary">
        <span>
          {t('payportal.progress_generated', { defaultValue: 'Generated' })}:{' '}
          <DateDisplay value={report.generated_at} />
        </span>
        {report.period ? (
          <span>
            {t('payportal.progress_period', { defaultValue: 'Period' })}: {report.period}
          </span>
        ) : null}
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button
          type="button"
          disabled={!ready || busy !== null}
          onClick={onOpen}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'open' ? <Loader2 size={12} className="animate-spin" /> : <ExternalLink size={12} />}
          {t('payportal.progress_open', { defaultValue: 'Open' })}
        </button>
        <button
          type="button"
          disabled={!ready || busy !== null}
          onClick={onDownload}
          className="inline-flex items-center gap-1 rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
        >
          {busy === 'download' ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <Download size={12} />
          )}
          {t('payportal.progress_download', { defaultValue: 'Download' })}
        </button>
      </div>
    </li>
  );
}
