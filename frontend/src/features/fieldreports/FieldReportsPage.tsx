import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  ClipboardList,
  Plus,
  Calendar,
  LayoutList,
  ChevronLeft,
  ChevronRight,
  Sun,
  Cloud,
  CloudRain,
  Snowflake,
  CloudFog,
  CloudLightning,
  Users,
  FileText,
  CheckCircle2,
  Send,
  Trash2,
  X,
  Download,
  Upload,
  FileDown,
  Loader2,
  AlertTriangle,
  HardHat,
  Thermometer,
} from 'lucide-react';
import { Button, Card, Badge, EmptyState, Breadcrumb } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchFieldReports,
  fetchFieldReportSummary,
  fetchFieldReportCalendar,
  createFieldReport,
  updateFieldReport,
  deleteFieldReport,
  submitFieldReport,
  approveFieldReport,
  getFieldReportPdfUrl,
  importFieldReportsFile,
  exportFieldReports,
  downloadFieldReportsTemplate,
} from './api';
import type {
  FieldReport,
  ReportType,
  ReportStatus,
  WeatherCondition,
  WorkforceEntry,
  CreateFieldReportPayload,
  UpdateFieldReportPayload,
  ImportResult,
} from './api';

/* ── Constants ─────────────────────────────────────────────────────────── */

const REPORT_TYPES: ReportType[] = ['daily', 'inspection', 'safety', 'concrete_pour'];
const WEATHER_CONDITIONS: WeatherCondition[] = ['clear', 'cloudy', 'rain', 'snow', 'fog', 'storm'];

const COMMON_TRADES = [
  'Concrete',
  'Carpentry',
  'Electrical',
  'Plumbing',
  'HVAC',
  'Steel',
  'Masonry',
  'Painting',
  'Roofing',
  'Excavation',
  'General Labor',
];

const WEATHER_ICONS: Record<WeatherCondition, typeof Sun> = {
  clear: Sun,
  cloudy: Cloud,
  rain: CloudRain,
  snow: Snowflake,
  fog: CloudFog,
  storm: CloudLightning,
};

const STATUS_BADGE_VARIANT: Record<ReportStatus, 'neutral' | 'blue' | 'success'> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
};

const STATUS_DOT_COLOR: Record<ReportStatus, string> = {
  draft: 'bg-gray-400',
  submitted: 'bg-blue-500',
  approved: 'bg-green-500',
};

/* ── Helper: format date for display ───────────────────────────────────── */

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString(undefined, {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

function todayStr(): string {
  return new Date().toISOString().slice(0, 10);
}

/* ── Compute total workforce from entries ──────────────────────────────── */

function totalWorkforce(workforce: WorkforceEntry[]): { workers: number; hours: number } {
  let workers = 0;
  let hours = 0;
  for (const e of workforce) {
    workers += e.count || 0;
    hours += (e.count || 0) * (e.hours || 0);
  }
  return { workers, hours: Math.round(hours * 10) / 10 };
}

/* ══════════════════════════════════════════════════════════════════════════
   Main Page
   ══════════════════════════════════════════════════════════════════════════ */

export function FieldReportsPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const projectId = activeProjectId ?? '';

  // View mode: calendar vs list
  const [view, setView] = useState<'calendar' | 'list'>('calendar');

  // Calendar state
  const now = new Date();
  const [calYear, setCalYear] = useState(now.getFullYear());
  const [calMonth, setCalMonth] = useState(now.getMonth() + 1);

  // Filters for list view
  const [statusFilter, setStatusFilter] = useState<ReportStatus | ''>('');
  const [typeFilter, setTypeFilter] = useState<ReportType | ''>('');

  // Modal state
  const [showModal, setShowModal] = useState(false);
  const [showImportModal, setShowImportModal] = useState(false);
  const [editingReport, setEditingReport] = useState<FieldReport | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────

  const calMonthStr = `${calYear}-${String(calMonth).padStart(2, '0')}`;

  const { data: calendarReports = [] } = useQuery({
    queryKey: ['fieldreports', 'calendar', projectId, calMonthStr],
    queryFn: () => fetchFieldReportCalendar(projectId, calMonthStr),
    enabled: !!projectId && view === 'calendar',
  });

  const { data: listReports = [] } = useQuery({
    queryKey: ['fieldreports', 'list', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchFieldReports(projectId, {
        status: statusFilter || undefined,
        type: typeFilter || undefined,
      }),
    enabled: !!projectId && view === 'list',
  });

  const { data: summary } = useQuery({
    queryKey: ['fieldreports', 'summary', projectId],
    queryFn: () => fetchFieldReportSummary(projectId),
    enabled: !!projectId,
  });

  // ── Mutations ────────────────────────────────────────────────────────

  const createMut = useMutation({
    mutationFn: createFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.created', { defaultValue: 'Field report created' }) });
      setShowModal(false);
      setEditingReport(null);
    },
    onError: (e: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message });
    },
  });

  const updateMut = useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateFieldReportPayload }) =>
      updateFieldReport(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.updated', { defaultValue: 'Field report updated' }) });
      setShowModal(false);
      setEditingReport(null);
    },
    onError: (e: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: e.message });
    },
  });

  const deleteMut = useMutation({
    mutationFn: deleteFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.deleted', { defaultValue: 'Field report deleted' }) });
    },
  });

  const submitMut = useMutation({
    mutationFn: submitFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.submitted', { defaultValue: 'Report submitted for approval' }) });
    },
  });

  const approveMut = useMutation({
    mutationFn: approveFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.approved', { defaultValue: 'Report approved' }) });
    },
  });

  // Export mutation
  const exportMut = useMutation({
    mutationFn: () => exportFieldReports(projectId),
    onSuccess: () =>
      addToast({
        type: 'success',
        title: t('fieldreports.export_success', { defaultValue: 'Export complete' }),
        message: t('fieldreports.export_success_msg', { defaultValue: 'Excel file downloaded.' }),
      }),
    onError: (e: Error) =>
      addToast({
        type: 'error',
        title: t('fieldreports.export_failed', { defaultValue: 'Export failed' }),
        message: e.message,
      }),
  });

  // ── Calendar navigation ──────────────────────────────────────────────

  const prevMonth = useCallback(() => {
    if (calMonth === 1) {
      setCalYear((y) => y - 1);
      setCalMonth(12);
    } else {
      setCalMonth((m) => m - 1);
    }
  }, [calMonth]);

  const nextMonth = useCallback(() => {
    if (calMonth === 12) {
      setCalYear((y) => y + 1);
      setCalMonth(1);
    } else {
      setCalMonth((m) => m + 1);
    }
  }, [calMonth]);

  // ── Calendar grid data ───────────────────────────────────────────────

  const calendarDays = useMemo(() => {
    const firstDay = new Date(calYear, calMonth - 1, 1);
    const startDow = firstDay.getDay(); // 0=Sun
    const daysInMonth = new Date(calYear, calMonth, 0).getDate();

    // Map reports by date string
    const reportsByDate: Record<string, FieldReport[]> = {};
    for (const r of calendarReports) {
      const d = r.report_date;
      if (!reportsByDate[d]) reportsByDate[d] = [];
      reportsByDate[d].push(r);
    }

    const cells: Array<{ day: number | null; dateStr: string; reports: FieldReport[] }> = [];

    // Leading empty cells
    for (let i = 0; i < startDow; i++) {
      cells.push({ day: null, dateStr: '', reports: [] });
    }

    for (let d = 1; d <= daysInMonth; d++) {
      const dateStr = `${calYear}-${String(calMonth).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
      cells.push({ day: d, dateStr, reports: reportsByDate[dateStr] || [] });
    }

    return cells;
  }, [calYear, calMonth, calendarReports]);

  // ── Handlers ─────────────────────────────────────────────────────────

  const handleOpenNew = useCallback(() => {
    setEditingReport(null);
    setShowModal(true);
  }, []);

  const handleOpenEdit = useCallback((report: FieldReport) => {
    setEditingReport(report);
    setShowModal(true);
  }, []);

  const handleDelete = useCallback(
    (id: string) => {
      if (window.confirm(t('fieldreports.confirm_delete', { defaultValue: 'Delete this field report?' }))) {
        deleteMut.mutate(id);
      }
    },
    [deleteMut, t],
  );

  // ── No project selected ─────────────────────────────────────────────

  if (!projectId) {
    return (
      <div className="p-6">
        <EmptyState
          icon={<ClipboardList size={28} strokeWidth={1.5} />}
          title={t('fieldreports.no_project', { defaultValue: 'Select a project' })}
          description={t('fieldreports.no_project_desc', { defaultValue: 'Choose a project from the sidebar to view field reports.' })}
        />
      </div>
    );
  }

  // ── Month label ─────────────────────────────────────────────────────

  const monthLabel = new Date(calYear, calMonth - 1).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'long',
  });

  return (
    <div className="flex flex-col gap-6 p-6 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          { label: t('nav.dashboard', { defaultValue: 'Dashboard' }), to: '/' },
          { label: t('fieldreports.title', { defaultValue: 'Field Reports' }) },
        ]}
      />

      {/* Header */}
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-400">
            <ClipboardList size={22} />
          </div>
          <div>
            <h1 className="text-xl font-semibold text-content-primary">
              {t('fieldreports.title', { defaultValue: 'Field Reports' })}
            </h1>
            <p className="text-sm text-content-tertiary">
              {activeProjectName}
            </p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          {/* View toggle */}
          <div className="flex rounded-lg border border-border-light bg-surface-primary p-0.5">
            <button
              onClick={() => setView('calendar')}
              className={clsx(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                view === 'calendar'
                  ? 'bg-oe-blue-subtle text-oe-blue'
                  : 'text-content-tertiary hover:text-content-primary',
              )}
            >
              <Calendar size={15} />
              {t('fieldreports.calendar_view', { defaultValue: 'Calendar' })}
            </button>
            <button
              onClick={() => setView('list')}
              className={clsx(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                view === 'list'
                  ? 'bg-oe-blue-subtle text-oe-blue'
                  : 'text-content-tertiary hover:text-content-primary',
              )}
            >
              <LayoutList size={15} />
              {t('fieldreports.list_view', { defaultValue: 'List' })}
            </button>
          </div>

          <Button
            variant="secondary"
            size="sm"
            onClick={() => exportMut.mutate()}
            disabled={exportMut.isPending}
            className="shrink-0 whitespace-nowrap"
          >
            {exportMut.isPending ? (
              <Loader2 size={14} className="mr-1.5 animate-spin shrink-0" />
            ) : (
              <Download size={14} className="mr-1.5 shrink-0" />
            )}
            <span className="whitespace-nowrap">{t('fieldreports.export', { defaultValue: 'Export' })}</span>
          </Button>
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowImportModal(true)}
            className="shrink-0 whitespace-nowrap"
          >
            <Upload size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('fieldreports.import', { defaultValue: 'Import' })}</span>
          </Button>
          <Button variant="primary" size="sm" onClick={handleOpenNew} className="shrink-0 whitespace-nowrap" icon={<Plus size={14} />}>
            {t('fieldreports.new_report', { defaultValue: 'New Report' })}
          </Button>
        </div>
      </div>

      {/* Stats cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-5">
          <StatCard
            label={t('fieldreports.stat_total', { defaultValue: 'Total Reports' })}
            value={summary.total}
            icon={FileText}
          />
          <StatCard
            label={t('fieldreports.stat_draft', { defaultValue: 'Draft' })}
            value={summary.by_status?.draft ?? 0}
            icon={FileText}
            color="gray"
          />
          <StatCard
            label={t('fieldreports.stat_submitted', { defaultValue: 'Submitted' })}
            value={summary.by_status?.submitted ?? 0}
            icon={Send}
            color="blue"
          />
          <StatCard
            label={t('fieldreports.stat_approved', { defaultValue: 'Approved' })}
            value={summary.by_status?.approved ?? 0}
            icon={CheckCircle2}
            color="green"
          />
          <StatCard
            label={t('fieldreports.stat_workforce_hours', { defaultValue: 'Workforce Hours' })}
            value={summary.total_workforce_hours}
            icon={Users}
            color="amber"
          />
        </div>
      )}

      {/* Calendar view */}
      {view === 'calendar' && (
        <Card>
          <div className="p-4">
            {/* Month navigation */}
            <div className="mb-4 flex items-center justify-between">
              <button
                onClick={prevMonth}
                className="rounded-lg p-2 text-content-secondary hover:bg-surface-secondary transition-colors"
                aria-label={t('common.previous', { defaultValue: 'Previous' })}
              >
                <ChevronLeft size={20} />
              </button>
              <h2 className="text-lg font-semibold text-content-primary">{monthLabel}</h2>
              <button
                onClick={nextMonth}
                className="rounded-lg p-2 text-content-secondary hover:bg-surface-secondary transition-colors"
                aria-label={t('common.next', { defaultValue: 'Next' })}
              >
                <ChevronRight size={20} />
              </button>
            </div>

            {/* Day headers */}
            <div className="grid grid-cols-7 gap-px mb-1">
              {['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'].map((d) => (
                <div
                  key={d}
                  className="py-2 text-center text-xs font-medium uppercase text-content-tertiary"
                >
                  {t(`fieldreports.day_${d.toLowerCase()}`, { defaultValue: d })}
                </div>
              ))}
            </div>

            {/* Calendar grid */}
            <div className="grid grid-cols-7 gap-px rounded-lg border border-border-light bg-border-light overflow-hidden">
              {calendarDays.map((cell, idx) => (
                <div
                  key={idx}
                  className={clsx(
                    'min-h-[80px] bg-surface-primary p-2 transition-colors',
                    cell.day !== null && 'hover:bg-surface-secondary cursor-pointer',
                    cell.day === null && 'bg-surface-secondary/50',
                  )}
                  onClick={() => {
                    if (cell.day === null) return;
                    if (cell.reports.length > 0) {
                      handleOpenEdit(cell.reports[0]!);
                    } else {
                      setEditingReport(null);
                      setShowModal(true);
                      // The modal will pick up the date from the cell
                      (window as any).__fieldreport_prefill_date = cell.dateStr;
                    }
                  }}
                >
                  {cell.day !== null && (
                    <>
                      <span
                        className={clsx(
                          'text-sm font-medium',
                          cell.dateStr === todayStr()
                            ? 'flex h-6 w-6 items-center justify-center rounded-full bg-oe-blue text-white'
                            : 'text-content-secondary',
                        )}
                      >
                        {cell.day}
                      </span>
                      <div className="mt-1 flex flex-wrap gap-1">
                        {cell.reports.map((r) => (
                          <span
                            key={r.id}
                            className={clsx('h-2 w-2 rounded-full', STATUS_DOT_COLOR[r.status])}
                            title={`${r.report_type} — ${r.status}`}
                          />
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>

            {/* Legend */}
            <div className="mt-3 flex items-center gap-4 text-xs text-content-tertiary">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-gray-400" />
                {t('fieldreports.status_draft', { defaultValue: 'Draft' })}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-blue-500" />
                {t('fieldreports.status_submitted', { defaultValue: 'Submitted' })}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-green-500" />
                {t('fieldreports.status_approved', { defaultValue: 'Approved' })}
              </span>
            </div>
          </div>
        </Card>
      )}

      {/* List view */}
      {view === 'list' && (
        <Card>
          {/* List filters */}
          <div className="flex flex-wrap items-center gap-3 border-b border-border-light p-4">
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as ReportStatus | '')}
              className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm text-content-primary"
            >
              <option value="">{t('fieldreports.all_statuses', { defaultValue: 'All Statuses' })}</option>
              <option value="draft">{t('fieldreports.status_draft', { defaultValue: 'Draft' })}</option>
              <option value="submitted">{t('fieldreports.status_submitted', { defaultValue: 'Submitted' })}</option>
              <option value="approved">{t('fieldreports.status_approved', { defaultValue: 'Approved' })}</option>
            </select>
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value as ReportType | '')}
              className="rounded-lg border border-border-light bg-surface-primary px-3 py-1.5 text-sm text-content-primary"
            >
              <option value="">{t('fieldreports.all_types', { defaultValue: 'All Types' })}</option>
              {REPORT_TYPES.map((rt) => (
                <option key={rt} value={rt}>
                  {t(`fieldreports.type_${rt}`, { defaultValue: rt.replace(/_/g, ' ') })}
                </option>
              ))}
            </select>
          </div>

          {/* Table */}
          {listReports.length === 0 ? (
            <div className="p-8">
              <EmptyState
                icon={<ClipboardList size={28} strokeWidth={1.5} />}
                title={
                  statusFilter || typeFilter
                    ? t('fieldreports.no_match', { defaultValue: 'No matching reports' })
                    : t('fieldreports.empty', { defaultValue: 'No field reports yet' })
                }
                description={
                  statusFilter || typeFilter
                    ? t('fieldreports.no_match_desc', { defaultValue: 'Try adjusting your status or type filters.' })
                    : t('fieldreports.empty_desc', { defaultValue: 'Create your first daily field report to track site activities.' })
                }
                action={
                  statusFilter || typeFilter
                    ? undefined
                    : (
                      <Button variant="primary" size="sm" onClick={handleOpenNew} className="shrink-0 whitespace-nowrap" icon={<Plus size={14} />}>
                        {t('fieldreports.new_report', { defaultValue: 'New Report' })}
                      </Button>
                    )
                }
              />
            </div>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/50">
                    <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                      {t('fieldreports.col_date', { defaultValue: 'Date' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                      {t('fieldreports.col_type', { defaultValue: 'Type' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                      {t('fieldreports.col_weather', { defaultValue: 'Weather' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                      {t('fieldreports.col_workforce', { defaultValue: 'Workforce' })}
                    </th>
                    <th className="px-4 py-3 text-left font-medium text-content-tertiary">
                      {t('fieldreports.col_status', { defaultValue: 'Status' })}
                    </th>
                    <th className="px-4 py-3 text-right font-medium text-content-tertiary">
                      {t('common.actions', { defaultValue: 'Actions' })}
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {listReports.map((report) => {
                    const wf = totalWorkforce(report.workforce || []);
                    const WeatherIcon = WEATHER_ICONS[report.weather_condition] || Sun;
                    return (
                      <tr
                        key={report.id}
                        className="border-b border-border-light last:border-b-0 hover:bg-surface-secondary/30 transition-colors cursor-pointer"
                        onClick={() => handleOpenEdit(report)}
                      >
                        <td className="px-4 py-3 font-medium text-content-primary">
                          {formatDate(report.report_date)}
                        </td>
                        <td className="px-4 py-3 text-content-secondary capitalize">
                          {t(`fieldreports.type_${report.report_type}`, {
                            defaultValue: report.report_type.replace(/_/g, ' '),
                          })}
                        </td>
                        <td className="px-4 py-3">
                          <span className="flex items-center gap-1.5 text-content-secondary">
                            <WeatherIcon size={16} />
                            {t(`fieldreports.weather_${report.weather_condition}`, {
                              defaultValue: report.weather_condition,
                            })}
                            {report.temperature_c != null && (
                              <span className="text-content-tertiary">
                                {report.temperature_c}&deg;C
                              </span>
                            )}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-content-secondary">
                          {wf.workers > 0
                            ? `${wf.workers} ${t('fieldreports.workers', { defaultValue: 'workers' })}`
                            : '-'}
                        </td>
                        <td className="px-4 py-3">
                          <Badge variant={STATUS_BADGE_VARIANT[report.status]}>
                            {t(`fieldreports.status_${report.status}`, {
                              defaultValue: report.status,
                            })}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-right">
                          <div
                            className="flex items-center justify-end gap-1"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {report.status === 'draft' && (
                              <button
                                onClick={() => submitMut.mutate(report.id)}
                                className="rounded p-1.5 text-blue-600 hover:bg-blue-50 dark:text-blue-400 dark:hover:bg-blue-900/20"
                                title={t('fieldreports.submit', { defaultValue: 'Submit' })}
                              >
                                <Send size={15} />
                              </button>
                            )}
                            {report.status === 'submitted' && (
                              <button
                                onClick={() => approveMut.mutate(report.id)}
                                className="rounded p-1.5 text-green-600 hover:bg-green-50 dark:text-green-400 dark:hover:bg-green-900/20"
                                title={t('fieldreports.approve', { defaultValue: 'Approve' })}
                              >
                                <CheckCircle2 size={15} />
                              </button>
                            )}
                            <a
                              href={getFieldReportPdfUrl(report.id)}
                              target="_blank"
                              rel="noopener noreferrer"
                              className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                              title={t('fieldreports.export_pdf', { defaultValue: 'Export PDF' })}
                            >
                              <Download size={15} />
                            </a>
                            {report.status !== 'approved' && (
                              <button
                                onClick={() => handleDelete(report.id)}
                                className="rounded p-1.5 text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20"
                                title={t('common.delete', { defaultValue: 'Delete' })}
                              >
                                <Trash2 size={15} />
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}

      {/* Report modal */}
      {showModal && (
        <ReportModal
          report={editingReport}
          projectId={projectId}
          onClose={() => {
            setShowModal(false);
            setEditingReport(null);
            delete (window as any).__fieldreport_prefill_date;
          }}
          onCreate={(data) => createMut.mutate(data)}
          onUpdate={(id, data) => updateMut.mutate({ id, data })}
          onSubmit={(id) => {
            submitMut.mutate(id);
            setShowModal(false);
            setEditingReport(null);
          }}
          onApprove={(id) => {
            approveMut.mutate(id);
            setShowModal(false);
            setEditingReport(null);
          }}
          loading={createMut.isPending || updateMut.isPending}
        />
      )}

      {/* Import modal */}
      {showImportModal && (
        <ImportFieldReportsModal
          projectId={projectId}
          onClose={() => setShowImportModal(false)}
          onSuccess={() => {
            queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
          }}
        />
      )}
    </div>
  );
}

/* ── Import Field Reports Modal ─────────────────────────────────────────── */

function ImportFieldReportsModal({
  projectId,
  onClose,
  onSuccess,
}: {
  projectId: string;
  onClose: () => void;
  onSuccess: (result: ImportResult) => void;
}) {
  const { t } = useTranslation();
  const [file, setFile] = useState<File | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<ImportResult | null>(null);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const dropped = e.dataTransfer.files[0];
    if (dropped) setFile(dropped);
  }, []);

  const handleImport = async () => {
    if (!file) return;
    setIsPending(true);
    setError(null);
    try {
      const res = await importFieldReportsFile(file, projectId);
      setResult(res);
      onSuccess(res);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Import failed');
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm animate-fade-in">
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto">
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('fieldreports.import_reports', { defaultValue: 'Import Field Reports' })}
          </h2>
          <button
            onClick={onClose}
            className="flex h-8 w-8 items-center justify-center rounded-lg text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors"
          >
            <X size={18} />
          </button>
        </div>

        {/* Body */}
        <div className="px-6 py-4 space-y-4">
          {/* Drop zone */}
          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            className={clsx(
              'flex flex-col items-center justify-center rounded-lg border-2 border-dashed p-8 transition-colors cursor-pointer',
              dragActive
                ? 'border-oe-blue bg-oe-blue-subtle/20'
                : 'border-border hover:border-oe-blue/50',
            )}
            onClick={() => {
              const input = document.createElement('input');
              input.type = 'file';
              input.accept = '.xlsx,.csv,.xls';
              input.onchange = (e) => {
                const f = (e.target as HTMLInputElement).files?.[0];
                if (f) setFile(f);
              };
              input.click();
            }}
          >
            <Upload size={24} className="text-content-tertiary mb-2" />
            <p className="text-sm text-content-secondary text-center">
              {file
                ? file.name
                : t('fieldreports.drop_file', {
                    defaultValue: 'Drop Excel or CSV file here, or click to browse',
                  })}
            </p>
            <p className="text-xs text-content-quaternary mt-1">
              {t('fieldreports.file_types', { defaultValue: '.xlsx, .csv — max 10 MB' })}
            </p>
          </div>

          {/* Template download */}
          <button
            onClick={(e) => {
              e.stopPropagation();
              downloadFieldReportsTemplate();
            }}
            className="flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            <FileDown size={13} />
            {t('fieldreports.download_template', { defaultValue: 'Download import template' })}
          </button>

          {/* Error */}
          {error && (
            <div className="rounded-lg bg-red-50 dark:bg-red-950/20 border border-red-200 dark:border-red-800 p-3 text-sm text-semantic-error">
              {error}
            </div>
          )}

          {/* Result */}
          {result && (
            <div className="rounded-lg bg-green-50 dark:bg-green-950/20 border border-green-200 dark:border-green-800 p-3 text-sm text-content-primary space-y-1">
              <p>
                {t('fieldreports.import_result', {
                  defaultValue: 'Imported: {{imported}}, Skipped: {{skipped}}, Errors: {{errors}}',
                  imported: result.imported,
                  skipped: result.skipped,
                  errors: result.errors.length,
                })}
              </p>
              {result.errors.length > 0 && (
                <details className="text-xs text-content-tertiary">
                  <summary className="cursor-pointer">
                    {t('fieldreports.show_errors', { defaultValue: 'Show error details' })}
                  </summary>
                  <ul className="mt-1 space-y-0.5 max-h-32 overflow-y-auto">
                    {result.errors.slice(0, 20).map((err, i) => (
                      <li key={i}>
                        {t('fieldreports.row_error', {
                          defaultValue: 'Row {{row}}: {{error}}',
                          row: err.row,
                          error: err.error,
                        })}
                      </li>
                    ))}
                  </ul>
                </details>
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 px-6 py-4 border-t border-border-light">
          <Button variant="ghost" onClick={onClose}>
            {result
              ? t('common.close', { defaultValue: 'Close' })
              : t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {!result && (
            <Button
              variant="primary"
              onClick={handleImport}
              disabled={!file || isPending}
            >
              {isPending ? (
                <Loader2 size={16} className="animate-spin mr-1.5" />
              ) : (
                <Upload size={16} className="mr-1.5" />
              )}
              <span>{t('fieldreports.import_btn', { defaultValue: 'Import' })}</span>
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Stat Card ──────────────────────────────────────────────────────────── */

function StatCard({
  label,
  value,
  icon: Icon,
  color = 'default',
}: {
  label: string;
  value: number;
  icon: typeof FileText;
  color?: 'default' | 'gray' | 'blue' | 'green' | 'amber';
}) {
  const colorCls = {
    default: 'text-content-primary',
    gray: 'text-gray-500',
    blue: 'text-blue-600 dark:text-blue-400',
    green: 'text-green-600 dark:text-green-400',
    amber: 'text-amber-600 dark:text-amber-400',
  };

  return (
    <Card>
      <div className="flex items-center gap-3 p-4">
        <Icon size={20} className={clsx('shrink-0', colorCls[color])} />
        <div>
          <p className="text-2xl font-bold text-content-primary">{value}</p>
          <p className="text-xs text-content-tertiary">{label}</p>
        </div>
      </div>
    </Card>
  );
}

/* ══════════════════════════════════════════════════════════════════════════
   Report Modal (Create / Edit)
   ══════════════════════════════════════════════════════════════════════════ */

function ReportModal({
  report,
  projectId,
  onClose,
  onCreate,
  onUpdate,
  onSubmit,
  onApprove,
  loading,
}: {
  report: FieldReport | null;
  projectId: string;
  onClose: () => void;
  onCreate: (data: CreateFieldReportPayload) => void;
  onUpdate: (id: string, data: UpdateFieldReportPayload) => void;
  onSubmit: (id: string) => void;
  onApprove: (id: string) => void;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const isEdit = report != null;

  // Prefill date from calendar click
  const prefillDate =
    (window as any).__fieldreport_prefill_date || todayStr();

  const [reportDate, setReportDate] = useState(report?.report_date ?? prefillDate);
  const [reportType, setReportType] = useState<ReportType>(report?.report_type ?? 'daily');
  const [weatherCondition, setWeatherCondition] = useState<WeatherCondition>(
    report?.weather_condition ?? 'clear',
  );
  const [temperatureC, setTemperatureC] = useState<string>(
    report?.temperature_c != null ? String(report.temperature_c) : '',
  );
  const [windSpeed, setWindSpeed] = useState(report?.wind_speed ?? '');
  const [precipitation, _setPrecipitation] = useState(report?.precipitation ?? '');
  const [humidity, setHumidity] = useState<string>(
    report?.humidity != null ? String(report.humidity) : '',
  );
  const [workforce, setWorkforce] = useState<WorkforceEntry[]>(
    report?.workforce?.length ? report.workforce : [{ trade: '', count: 0, hours: 8 }],
  );
  const [workPerformed, setWorkPerformed] = useState(report?.work_performed ?? '');
  const [delays, setDelays] = useState(report?.delays ?? '');
  const [delayHours, setDelayHours] = useState<string>(
    report?.delay_hours != null ? String(report.delay_hours) : '0',
  );
  const [safetyIncidents, setSafetyIncidents] = useState(report?.safety_incidents ?? '');
  const [visitors, setVisitors] = useState(report?.visitors ?? '');
  const [deliveries, setDeliveries] = useState(report?.deliveries ?? '');
  const [notes, setNotes] = useState(report?.notes ?? '');

  const handleAddWorkforce = useCallback(() => {
    setWorkforce((prev) => [...prev, { trade: '', count: 0, hours: 8 }]);
  }, []);

  const handleRemoveWorkforce = useCallback((idx: number) => {
    setWorkforce((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleWorkforceChange = useCallback(
    (idx: number, field: keyof WorkforceEntry, value: string | number) => {
      setWorkforce((prev) =>
        prev.map((e, i) => (i === idx ? { ...e, [field]: value } : e)),
      );
    },
    [],
  );

  const handleSave = useCallback(() => {
    const cleanWorkforce = workforce.filter((e) => e.trade.trim() !== '');
    const payload = {
      report_date: reportDate,
      report_type: reportType,
      weather_condition: weatherCondition,
      temperature_c: temperatureC ? parseFloat(temperatureC) : null,
      wind_speed: windSpeed || null,
      precipitation: precipitation || null,
      humidity: humidity ? parseInt(humidity, 10) : null,
      workforce: cleanWorkforce,
      work_performed: workPerformed,
      delays: delays || null,
      delay_hours: parseFloat(delayHours) || 0,
      safety_incidents: safetyIncidents || null,
      visitors: visitors || null,
      deliveries: deliveries || null,
      notes: notes || null,
    };

    if (isEdit && report) {
      onUpdate(report.id, payload);
    } else {
      onCreate({ ...payload, project_id: projectId } as CreateFieldReportPayload);
    }
  }, [
    isEdit,
    report,
    projectId,
    reportDate,
    reportType,
    weatherCondition,
    temperatureC,
    windSpeed,
    precipitation,
    humidity,
    workforce,
    workPerformed,
    delays,
    delayHours,
    safetyIncidents,
    visitors,
    deliveries,
    notes,
    onCreate,
    onUpdate,
  ]);

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto bg-black/40 p-4 pt-12 backdrop-blur-sm">
      <div className="w-full max-w-2xl rounded-2xl border border-border-light bg-surface-primary shadow-2xl animate-fade-in">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-border-light px-6 py-4">
          <h2 className="text-lg font-semibold text-content-primary">
            {isEdit
              ? t('fieldreports.edit_report', { defaultValue: 'Edit Field Report' })
              : t('fieldreports.new_report', { defaultValue: 'New Field Report' })}
          </h2>
          <div className="flex items-center gap-2">
            {isEdit && report && (
              <Badge variant={STATUS_BADGE_VARIANT[report.status]}>
                {t(`fieldreports.status_${report.status}`, { defaultValue: report.status })}
              </Badge>
            )}
            <button onClick={onClose} className="rounded-lg p-2 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary transition-colors">
              <X size={20} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div className="max-h-[70vh] overflow-y-auto px-6 py-4 space-y-5">
          {/* Date + Type */}
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.report_date', { defaultValue: 'Date' })}
              </label>
              <input
                type="date"
                value={reportDate}
                onChange={(e) => setReportDate(e.target.value)}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                disabled={isEdit && report?.status === 'approved'}
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.report_type', { defaultValue: 'Report Type' })}
              </label>
              <select
                value={reportType}
                onChange={(e) => setReportType(e.target.value as ReportType)}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                disabled={isEdit && report?.status === 'approved'}
              >
                {REPORT_TYPES.map((rt) => (
                  <option key={rt} value={rt}>
                    {t(`fieldreports.type_${rt}`, { defaultValue: rt.replace(/_/g, ' ') })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Weather section */}
          <fieldset className="rounded-lg border border-border-light p-4">
            <legend className="flex items-center gap-2 px-2 text-sm font-semibold text-content-primary">
              <Thermometer size={16} />
              {t('fieldreports.weather', { defaultValue: 'Weather Conditions' })}
            </legend>
            <div className="mt-2 grid grid-cols-2 gap-3 sm:grid-cols-4">
              <div className="col-span-2 sm:col-span-1">
                <label className="mb-1 block text-xs text-content-tertiary">
                  {t('fieldreports.condition', { defaultValue: 'Condition' })}
                </label>
                <select
                  value={weatherCondition}
                  onChange={(e) => setWeatherCondition(e.target.value as WeatherCondition)}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                >
                  {WEATHER_CONDITIONS.map((wc) => (
                    <option key={wc} value={wc}>
                      {t(`fieldreports.weather_${wc}`, { defaultValue: wc })}
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label className="mb-1 block text-xs text-content-tertiary">
                  {t('fieldreports.temperature', { defaultValue: 'Temp (\u00B0C)' })}
                </label>
                <input
                  type="number"
                  value={temperatureC}
                  onChange={(e) => setTemperatureC(e.target.value)}
                  placeholder="--"
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-content-tertiary">
                  {t('fieldreports.wind', { defaultValue: 'Wind' })}
                </label>
                <input
                  type="text"
                  value={windSpeed}
                  onChange={(e) => setWindSpeed(e.target.value)}
                  placeholder={t('fieldreports.wind_placeholder', { defaultValue: 'e.g. 15 km/h NW' })}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                />
              </div>
              <div>
                <label className="mb-1 block text-xs text-content-tertiary">
                  {t('fieldreports.humidity_label', { defaultValue: 'Humidity (%)' })}
                </label>
                <input
                  type="number"
                  value={humidity}
                  onChange={(e) => setHumidity(e.target.value)}
                  placeholder="--"
                  min={0}
                  max={100}
                  className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                />
              </div>
            </div>
          </fieldset>

          {/* Workforce section */}
          <fieldset className="rounded-lg border border-border-light p-4">
            <legend className="flex items-center gap-2 px-2 text-sm font-semibold text-content-primary">
              <HardHat size={16} />
              {t('fieldreports.workforce_section', { defaultValue: 'Workforce' })}
            </legend>
            <div className="mt-2 space-y-2">
              {workforce.map((entry, idx) => (
                <div key={idx} className="flex items-center gap-2">
                  <div className="flex-1">
                    <input
                      type="text"
                      list="trades-list"
                      value={entry.trade}
                      onChange={(e) => handleWorkforceChange(idx, 'trade', e.target.value)}
                      placeholder={t('fieldreports.trade', { defaultValue: 'Trade' })}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                    />
                  </div>
                  <div className="w-24">
                    <input
                      type="number"
                      value={entry.count || ''}
                      onChange={(e) =>
                        handleWorkforceChange(idx, 'count', parseInt(e.target.value, 10) || 0)
                      }
                      placeholder={t('fieldreports.count', { defaultValue: 'Count' })}
                      min={0}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                    />
                  </div>
                  <div className="w-24">
                    <input
                      type="number"
                      value={entry.hours || ''}
                      onChange={(e) =>
                        handleWorkforceChange(idx, 'hours', parseFloat(e.target.value) || 0)
                      }
                      placeholder={t('fieldreports.hours', { defaultValue: 'Hours' })}
                      min={0}
                      step={0.5}
                      className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
                    />
                  </div>
                  <button
                    onClick={() => handleRemoveWorkforce(idx)}
                    className="rounded p-1 text-red-400 hover:text-red-600 hover:bg-red-50 dark:hover:bg-red-900/20"
                    title={t('common.remove', { defaultValue: 'Remove' })}
                  >
                    <X size={16} />
                  </button>
                </div>
              ))}
              <datalist id="trades-list">
                {COMMON_TRADES.map((trade) => (
                  <option key={trade} value={trade} />
                ))}
              </datalist>
              <button
                onClick={handleAddWorkforce}
                className="flex items-center gap-1.5 text-sm text-oe-blue hover:text-oe-blue/80 transition-colors"
              >
                <Plus size={14} />
                {t('fieldreports.add_trade', { defaultValue: 'Add trade' })}
              </button>
            </div>
          </fieldset>

          {/* Work Performed */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-secondary">
              {t('fieldreports.work_performed', { defaultValue: 'Work Performed' })}
            </label>
            <textarea
              value={workPerformed}
              onChange={(e) => setWorkPerformed(e.target.value)}
              rows={3}
              placeholder={t('fieldreports.work_performed_placeholder', {
                defaultValue: 'Describe work activities completed today...',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary resize-y"
            />
          </div>

          {/* Delays */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.delays_label', { defaultValue: 'Delays' })}
              </label>
              <textarea
                value={delays}
                onChange={(e) => setDelays(e.target.value)}
                rows={2}
                placeholder={t('fieldreports.delays_placeholder', {
                  defaultValue: 'Describe any delays encountered...',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary resize-y"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.delay_hours', { defaultValue: 'Delay Hours' })}
              </label>
              <input
                type="number"
                value={delayHours}
                onChange={(e) => setDelayHours(e.target.value)}
                min={0}
                step={0.5}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
              />
            </div>
          </div>

          {/* Safety Incidents */}
          <div>
            <label className="mb-1.5 flex items-center gap-1.5 text-sm font-medium text-content-secondary">
              <AlertTriangle size={14} className="text-amber-500" />
              {t('fieldreports.safety_incidents', { defaultValue: 'Safety Incidents' })}
            </label>
            <textarea
              value={safetyIncidents}
              onChange={(e) => setSafetyIncidents(e.target.value)}
              rows={2}
              placeholder={t('fieldreports.safety_placeholder', {
                defaultValue: 'Report any safety incidents or near-misses...',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary resize-y"
            />
          </div>

          {/* Visitors + Deliveries */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.visitors', { defaultValue: 'Visitors' })}
              </label>
              <input
                type="text"
                value={visitors}
                onChange={(e) => setVisitors(e.target.value)}
                placeholder={t('fieldreports.visitors_placeholder', {
                  defaultValue: 'Site visitors today...',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-content-secondary">
                {t('fieldreports.deliveries', { defaultValue: 'Deliveries' })}
              </label>
              <input
                type="text"
                value={deliveries}
                onChange={(e) => setDeliveries(e.target.value)}
                placeholder={t('fieldreports.deliveries_placeholder', {
                  defaultValue: 'Materials or equipment delivered...',
                })}
                className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary"
              />
            </div>
          </div>

          {/* Notes */}
          <div>
            <label className="mb-1.5 block text-sm font-medium text-content-secondary">
              {t('fieldreports.notes', { defaultValue: 'Notes' })}
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder={t('fieldreports.notes_placeholder', {
                defaultValue: 'Additional notes or observations...',
              })}
              className="w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary resize-y"
            />
          </div>
        </div>

        {/* Footer */}
        <div className="flex items-center justify-between border-t border-border-light px-6 py-4">
          <div className="flex items-center gap-2">
            {isEdit && report?.status === 'draft' && (
              <Button size="sm" variant="secondary" onClick={() => onSubmit(report.id)} className="shrink-0 whitespace-nowrap">
                <Send size={14} className="mr-1.5 shrink-0" />
                <span className="whitespace-nowrap">{t('fieldreports.submit', { defaultValue: 'Submit for Approval' })}</span>
              </Button>
            )}
            {isEdit && report?.status === 'submitted' && (
              <Button size="sm" variant="secondary" onClick={() => onApprove(report.id)} className="shrink-0 whitespace-nowrap">
                <CheckCircle2 size={14} className="mr-1.5 shrink-0" />
                <span className="whitespace-nowrap">{t('fieldreports.approve', { defaultValue: 'Approve' })}</span>
              </Button>
            )}
          </div>
          <div className="flex items-center gap-2">
            <Button size="sm" variant="ghost" onClick={onClose}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
            {(!isEdit || report?.status !== 'approved') && (
              <Button size="sm" onClick={handleSave} disabled={loading || !reportDate}>
                {isEdit
                  ? t('common.save', { defaultValue: 'Save' })
                  : t('fieldreports.create', { defaultValue: 'Create Report' })}
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
