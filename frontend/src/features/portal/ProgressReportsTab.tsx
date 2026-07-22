// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { FileText, ExternalLink, Download, Loader2 } from 'lucide-react';
import { Badge, EmptyState, SkeletonTable } from '@/shared/ui';
import { openInNewTab } from '@/shared/lib/desktop';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { projectsApi } from '@/features/projects/api';
import { API_BASE, getAuthToken } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { listProgressReports, type ProgressReport } from './api';

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

/* ─── Progress reports tab ───────────────────────────────────────────────
 *
 * Mirrors what a client sees in their portal: the generated progress
 * reports for a selected project, newest first, each openable / downloadable
 * as the rendered HTML the client receives. The portal-user-facing list is
 * RLS-scoped server-side (PortalAccessRule); this internal preview reuses
 * the JWT-gated reporting endpoints.
 */
export function ProgressReportsTab() {
  const { t } = useTranslation();
  // Seed from the global project switcher and stay in sync with it, so the
  // tab reacts to the top-bar picker instead of opening on an empty selector.
  const activeProjectId = useActiveProjectId();
  const [projectId, setProjectId] = useState<string>(activeProjectId);

  useEffect(() => {
    if (activeProjectId) setProjectId(activeProjectId);
  }, [activeProjectId]);

  const projectsQ = useQuery({
    queryKey: ['portal-progress', 'projects'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
  });

  const reportsQ = useQuery({
    queryKey: ['portal-progress', 'reports', projectId],
    queryFn: () => listProgressReports(projectId),
    enabled: !!projectId,
  });

  const projects = projectsQ.data ?? [];
  const reports = reportsQ.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <div className="min-w-[220px] flex-1 max-w-md">
          <label
            htmlFor="portal-progress-project"
            className="mb-1 block text-xs font-medium uppercase tracking-wide text-content-tertiary"
          >
            {t('portal.progress_project', { defaultValue: 'Project' })}
          </label>
          <select
            id="portal-progress-project"
            value={projectId}
            onChange={(e) => setProjectId(e.target.value)}
            className={inputCls}
            disabled={projectsQ.isLoading}
          >
            <option value="">
              {t('portal.progress_select_project', {
                defaultValue: 'Select a project…',
              })}
            </option>
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
      </div>

      {!projectId ? (
        <EmptyState
          icon={<FileText size={22} />}
          title={t('portal.progress_pick_project', {
            defaultValue: 'Pick a project to see its progress reports',
          })}
          description={t('portal.progress_pick_project_desc', {
            defaultValue:
              'Scheduled progress reports are generated per project and emailed to the recipients on the template. Select a project to review what the client receives.',
          })}
        />
      ) : reportsQ.isLoading ? (
        <SkeletonTable rows={6} columns={4} />
      ) : reportsQ.error ? (
        <EmptyState
          icon={<FileText size={22} />}
          title={t('portal.progress_load_failed', {
            defaultValue: 'Could not load progress reports',
          })}
          description={getErrorMessage(reportsQ.error)}
          action={{
            label: t('common.retry', { defaultValue: 'Retry' }),
            onClick: () => void reportsQ.refetch(),
          }}
        />
      ) : reports.length === 0 ? (
        <EmptyState
          icon={<FileText size={22} />}
          title={t('portal.progress_empty', {
            defaultValue: 'No progress reports yet',
          })}
          description={t('portal.progress_empty_desc', {
            defaultValue:
              'Create a Progress Report template in Reporting, set a schedule and recipients, and generated reports will appear here for the client.',
          })}
        />
      ) : (
        <ReportList reports={reports} />
      )}
    </div>
  );
}

function ReportList({ reports }: { reports: ProgressReport[] }) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead className="bg-surface-secondary text-content-tertiary text-xs uppercase tracking-wide">
          <tr>
            <th className="px-4 py-2.5 text-left">
              {t('portal.progress_report_title', { defaultValue: 'Report' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.progress_generated', { defaultValue: 'Generated' })}
            </th>
            <th className="px-4 py-2.5 text-left">
              {t('portal.progress_status', { defaultValue: 'Status' })}
            </th>
            <th className="px-4 py-2.5 text-right">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody>
          {reports.map((r) => (
            <ReportRow key={r.id} report={r} />
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ReportRow({ report }: { report: ProgressReport }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [busy, setBusy] = useState<'open' | 'download' | null>(null);
  const ready = !!report.storage_key;

  // Fetch the rendered HTML with the bearer token (the endpoint returns
  // text/html, not JSON, so we bypass apiGet) and either open it in a new
  // tab or download it as a file.
  const fetchHtml = async (): Promise<string | null> => {
    const token = getAuthToken();
    const res = await fetch(
      `${API_BASE}/v1/reporting/reports/${report.id}/content`,
      {
        method: 'GET',
        headers: {
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
          Accept: 'text/html',
          'X-DDC-Client': 'OE/1.0',
        },
      },
    );
    if (res.status === 410) {
      addToast({
        type: 'error',
        title: t('portal.progress_not_rendered', {
          defaultValue: 'This report has no rendered body yet.',
        }),
      });
      return null;
    }
    if (!res.ok) {
      addToast({
        type: 'error',
        title: t('portal.progress_open_failed', {
          defaultValue: 'Could not open the report.',
        }),
      });
      return null;
    }
    return res.text();
  };

  const onOpen = async () => {
    setBusy('open');
    try {
      const html = await fetchHtml();
      if (html) {
        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        openInNewTab(url);
        // Revoke a little later so the new tab has time to load.
        setTimeout(() => URL.revokeObjectURL(url), 60_000);
      }
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  const onDownload = async () => {
    setBusy('download');
    try {
      const html = await fetchHtml();
      if (html) {
        const blob = new Blob([html], { type: 'text/html' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `${report.title || 'progress-report'}.html`;
        a.click();
        URL.revokeObjectURL(url);
      }
    } catch (err) {
      addToast({ type: 'error', title: getErrorMessage(err) });
    } finally {
      setBusy(null);
    }
  };

  return (
    <tr className="border-t border-border-light">
      <td className="px-4 py-2 font-medium text-content-primary">
        <div className="flex items-center gap-2">
          <FileText size={14} className="shrink-0 text-content-tertiary" />
          <span className="truncate max-w-[320px]">{report.title}</span>
        </div>
      </td>
      <td className="px-4 py-2 text-xs text-content-secondary">
        <DateDisplay value={report.generated_at} />
      </td>
      <td className="px-4 py-2">
        {ready ? (
          <Badge variant="success" dot>
            {t('portal.progress_ready', { defaultValue: 'Ready' })}
          </Badge>
        ) : (
          <Badge variant="neutral" dot>
            {t('portal.progress_pending', { defaultValue: 'Pending' })}
          </Badge>
        )}
      </td>
      <td className="px-4 py-2">
        <div className="flex items-center justify-end gap-1.5">
          <button
            type="button"
            disabled={!ready || busy !== null}
            onClick={onOpen}
            className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === 'open' ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <ExternalLink size={12} />
            )}
            {t('portal.progress_open', { defaultValue: 'Open' })}
          </button>
          <button
            type="button"
            disabled={!ready || busy !== null}
            onClick={onDownload}
            className="inline-flex items-center gap-1 rounded-md border border-border-light bg-surface-primary px-2.5 py-1 text-xs font-medium text-content-secondary transition-colors hover:border-oe-blue hover:text-oe-blue disabled:cursor-not-allowed disabled:opacity-50"
          >
            {busy === 'download' ? (
              <Loader2 size={12} className="animate-spin" />
            ) : (
              <Download size={12} />
            )}
            {t('portal.progress_download', { defaultValue: 'Download' })}
          </button>
        </div>
      </td>
    </tr>
  );
}
