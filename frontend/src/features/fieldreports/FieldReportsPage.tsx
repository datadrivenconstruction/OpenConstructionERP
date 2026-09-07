// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
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
  Cloudy,
  Haze,
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
  LayoutTemplate,
  CloudSun,
  Lock,
  Info,
} from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  Breadcrumb,
  ConfirmDialog,
  RecoveryCard,
  WideModal,
  WideModalSection,
  WideModalField,
  SkeletonGrid,
  DismissibleInfo,
  IntroRichText,
  ModuleGuideButton,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { useConfirm } from '@/shared/hooks/useConfirm';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { todayLocalISO } from '@/shared/lib/dates';
import { useWeekStartsOn, type WeekStartsOn } from '@/shared/lib/weekStart';
import {
  fetchFieldReports,
  fetchFieldReportSummary,
  fetchFieldReportCalendar,
  createFieldReport,
  updateFieldReport,
  deleteFieldReport,
  submitFieldReport,
  approveFieldReport,
  exportFieldReportPdf,
  importFieldReportsFile,
  exportFieldReports,
  downloadFieldReportsTemplate,
  fetchWeather,
  weatherConditionFromDescription,
  REPORT_TYPES,
  WEATHER_CONDITIONS,
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
  FieldReportTemplate,
} from './api';
import {
  TemplatePicker,
  TemplateFieldEditor,
  ReportAttachments,
  type TemplateFieldValues,
} from './ReportTemplateFields';
import { ManageTemplatesModal } from './ManageTemplatesModal';
import { SiteLogEditor } from './SiteLogEditor';
import { SignaturePad } from './SignaturePad';
import { fieldreportsGuide } from './fieldreportsGuide';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildFieldReportsInsights } from './fieldReportsInsights';
import { fmtList, getIntlLocale } from '@/shared/lib/formatters';

declare global {
  interface Window {
    __fieldreportPrefillDate?: string;
  }
}

/* ── Constants ─────────────────────────────────────────────────────────── */


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
  partly_cloudy: CloudSun,
  cloudy: Cloud,
  overcast: Cloudy,
  rain: CloudRain,
  snow: Snowflake,
  fog: CloudFog,
  hazy: Haze,
  storm: CloudLightning,
};

const STATUS_BADGE_VARIANT: Record<ReportStatus, 'neutral' | 'blue' | 'success'> = {
  draft: 'neutral',
  submitted: 'blue',
  approved: 'success',
};

const STATUS_DOT_COLOR: Record<ReportStatus, string> = {
  draft: 'bg-content-tertiary',
  submitted: 'bg-semantic-info',
  approved: 'bg-semantic-success',
};

/* ── Helper: format date for display ───────────────────────────────────── */

function formatDate(dateStr: string): string {
  try {
    return new Date(dateStr + 'T00:00:00').toLocaleDateString(getIntlLocale(), {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
    });
  } catch {
    return dateStr;
  }
}

// Local calendar date (NOT the UTC slice of toISOString()). A field report
// "for today" must track the viewer's local day — using UTC would drift the
// highlighted day and the "Today" cell by ±1 near midnight for any user
// away from UTC. Shared with daily-diary via shared/lib/dates.ts.
function todayStr(): string {
  return todayLocalISO();
}

const WEEKDAYS: ReadonlyArray<{ key: string; label: string }> = [
  { key: 'sun', label: 'Sun' },
  { key: 'mon', label: 'Mon' },
  { key: 'tue', label: 'Tue' },
  { key: 'wed', label: 'Wed' },
  { key: 'thu', label: 'Thu' },
  { key: 'fri', label: 'Fri' },
  { key: 'sat', label: 'Sat' },
];

// Rotated weekday headers for a given week start (0=Sun through 6=Sat).
// Returns a 7-element array, never indexing a tuple by an unprovable number,
// so it stays clean under noUncheckedIndexedAccess.
function rotatedWeekdays(weekStart: WeekStartsOn): Array<{ key: string; label: string }> {
  const out: Array<{ key: string; label: string }> = [];
  for (let i = 0; i < 7; i++) {
    const entry = WEEKDAYS[(i + weekStart) % 7];
    if (entry) out.push(entry);
  }
  return out;
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
  const navigate = useNavigate();
  const weekStart = useWeekStartsOn();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const projectId = activeProjectId ?? '';
  const { confirm, ...confirmProps } = useConfirm();

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
  const [showTemplatesModal, setShowTemplatesModal] = useState(false);
  const [editingReport, setEditingReport] = useState<FieldReport | null>(null);

  // ── Queries ──────────────────────────────────────────────────────────

  const calMonthStr = `${calYear}-${String(calMonth).padStart(2, '0')}`;

  const { data: calendarReports = [], isLoading: isCalendarLoading } = useQuery({
    queryKey: ['fieldreports', 'calendar', projectId, calMonthStr],
    queryFn: () => fetchFieldReportCalendar(projectId, calMonthStr),
    enabled: !!projectId && view === 'calendar',
  });

  const {
    data: listReports = [],
    isLoading: isListLoading,
    isError: isListError,
    error: listError,
    refetch: refetchList,
  } = useQuery({
    queryKey: ['fieldreports', 'list', projectId, statusFilter, typeFilter],
    queryFn: () =>
      fetchFieldReports(projectId, {
        status: statusFilter || undefined,
        type: typeFilter || undefined,
      }),
    enabled: !!projectId && view === 'list',
  });

  const isLoading = view === 'calendar' ? isCalendarLoading : isListLoading;

  const { data: summary } = useQuery({
    queryKey: ['fieldreports', 'summary', projectId],
    queryFn: () => fetchFieldReportSummary(projectId),
    enabled: !!projectId,
  });

  // ── Module Insights ──────────────────────────────────────────────────
  // Built off the already-loaded list rows; until the list view has some the
  // panel draws nothing rather than inventing reports to fill it.
  const insights = useModuleInsights('fieldreports', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildFieldReportsInsights(listReports, '', t),
    [listReports, t],
  );

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
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  const submitMut = useMutation({
    mutationFn: submitFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.submitted', { defaultValue: 'Report submitted for approval' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
    },
  });

  const approveMut = useMutation({
    mutationFn: approveFieldReport,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
      addToast({ type: 'success', title: '', message: t('fieldreports.approved', { defaultValue: 'Report approved' }) });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: err.message });
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

  // Per-report PDF download (bearer-authenticated; not a plain link)
  const pdfMut = useMutation({
    mutationFn: (id: string) => exportFieldReportPdf(id),
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
    // Leading blank cells before day 1, rotated for the locale's week start
    // (0 = Sunday through 6 = Saturday). For a Monday-first calendar, Sunday
    // (getDay() === 0) sits at the end of the week, so it needs 6 leading
    // cells. The arithmetic is general over all seven starts.
    const startDow = (firstDay.getDay() - weekStart + 7) % 7;
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
  }, [calYear, calMonth, calendarReports, weekStart]);

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
    async (id: string) => {
      const ok = await confirm({
        title: t('fieldreports.confirm_delete_title', { defaultValue: 'Delete field report?' }),
        message: t('fieldreports.confirm_delete', { defaultValue: 'Delete this field report?' }),
      });
      if (ok) {
        deleteMut.mutate(id);
      }
    },
    [deleteMut, t, confirm],
  );

  // Approval is irreversible (the backend rejects edits once approved), so
  // gate it behind a confirm dialog. Returns whether it proceeded so callers
  // can close the modal only on a real approval.
  const handleApprove = useCallback(
    async (id: string): Promise<boolean> => {
      const ok = await confirm({
        title: t('fieldreports.confirm_approve_title', { defaultValue: 'Approve this report?' }),
        message: t('fieldreports.confirm_approve', {
          defaultValue:
            'Approving locks the report permanently. Once approved it can no longer be edited. Continue?',
        }),
        confirmLabel: t('fieldreports.approve', { defaultValue: 'Approve' }),
        variant: 'warning',
      });
      if (ok) {
        approveMut.mutate(id);
      }
      return ok;
    },
    [approveMut, t, confirm],
  );

  // ── Month label ─────────────────────────────────────────────────────

  const monthLabel = new Date(calYear, calMonth - 1).toLocaleDateString(getIntlLocale(), {
    year: 'numeric',
    month: 'long',
  });

  return (
    <div className="space-y-5 animate-fade-in">
      {/* Breadcrumb */}
      <Breadcrumb
        items={[
          ...(activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${projectId}` }]
            : []),
          { label: t('nav.field_reports', { defaultValue: 'Field Reports' }) },
        ]}
      />

      {/* Header */}
      <PageHeader
        srTitle={t('fieldreports.title', { defaultValue: 'Field Reports' })}
        subtitle={t('fieldreports.subtitle', {
          defaultValue:
            'Log the daily site diary - weather, workforce, work performed, delays and safety incidents.',
        })}
        actions={
          <>
          <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
          <ModuleGuideButton content={fieldreportsGuide} />
          {/* View toggle */}
          <div className="flex rounded-lg border border-border-light bg-surface-primary p-0.5">
            <button
              onClick={() => setView('calendar')}
              aria-label={t('fieldreports.calendar_view', { defaultValue: 'Calendar' })}
              aria-pressed={view === 'calendar'}
              className={clsx(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                view === 'calendar'
                  ? 'bg-oe-blue-subtle text-oe-blue-text'
                  : 'text-content-tertiary hover:text-content-primary',
              )}
            >
              <Calendar size={15} />
              {t('fieldreports.calendar_view', { defaultValue: 'Calendar' })}
            </button>
            <button
              onClick={() => setView('list')}
              aria-label={t('fieldreports.list_view', { defaultValue: 'List' })}
              aria-pressed={view === 'list'}
              className={clsx(
                'flex items-center gap-1.5 rounded-md px-3 py-1.5 text-sm font-medium transition-colors',
                view === 'list'
                  ? 'bg-oe-blue-subtle text-oe-blue-text'
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
          <Button
            variant="secondary"
            size="sm"
            onClick={() => setShowTemplatesModal(true)}
            className="shrink-0 whitespace-nowrap"
          >
            <LayoutTemplate size={14} className="mr-1.5 shrink-0" />
            <span className="whitespace-nowrap">{t('fieldreports.templates', { defaultValue: 'Templates' })}</span>
          </Button>
          <Button variant="primary" size="sm" onClick={handleOpenNew} className="shrink-0 whitespace-nowrap" icon={<Plus size={14} />}>
            {t('fieldreports.new_report', { defaultValue: 'New Report' })}
          </Button>
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('fieldreports.insights.title', { defaultValue: 'Field report insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* Info block */}
      <DismissibleInfo
        storageKey="field-reports"
        title={t('fieldreports.intro_title', {
          defaultValue: 'A defensible record of each site day',
        })}
        more={
          t('fieldreports.intro_more', { defaultValue: '' })
            ? <IntroRichText text={t('fieldreports.intro_more')} />
            : undefined
        }
        links={[
          {
            label: t('fieldreports.intro_link_daily_diary', { defaultValue: 'Daily Diary' }),
            onClick: () => navigate('/daily-diary'),
          },
          {
            label: t('fieldreports.intro_link_payroll', { defaultValue: 'Payroll' }),
            onClick: () => navigate('/payroll'),
          },
        ]}
      >
        {t('fieldreports.intro_body', {
          defaultValue:
            'Capture daily, inspection, safety and concrete-pour reports with weather, workforce hours by trade, work performed and delays, then move each from draft to submitted to approved with a signature. Reports roll up workforce hours for payroll and progress, and unlike the legally sealed Daily Diary they are structured, templated forms you can export to PDF or Excel.',
        })}
      </DismissibleInfo>

      {/* Project gate: keep the canonical top block above, then show the
          select-a-project empty state as a rhythm child (instead of a
          full-page short-circuit that dropped the breadcrumb / header). */}
      {!projectId ? (
        <Card className="py-12">
          <RequiresProject
            emptyHint={t('fieldreports.no_project_desc', {
              defaultValue: 'Choose a project from the sidebar to view field reports.',
            })}
          >{null}</RequiresProject>
        </Card>
      ) : (
        <>

      {/* Stats cards */}
      {summary && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-5">
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

            {/* Day headers — rotated for the active locale's week start */}
            <div className="grid grid-cols-7 gap-px mb-1">
              {rotatedWeekdays(weekStart).map((d) => (
                <div
                  key={d.key}
                  className="py-2 text-center text-xs font-medium uppercase text-content-tertiary"
                >
                  {t(`fieldreports.day_${d.key}`, { defaultValue: d.label })}
                </div>
              ))}
            </div>

            {/* Calendar loading state */}
            {isCalendarLoading && (
              <SkeletonGrid items={14} gridCols="grid-cols-7" className="rounded-lg" />
            )}

            {/* Calendar grid */}
            {!isCalendarLoading && <div className="grid grid-cols-7 gap-px rounded-lg border border-border-light bg-border-light overflow-hidden">
              {calendarDays.map((cell, idx) => (
                <div
                  key={cell.day !== null ? `day-${cell.day}` : `empty-${idx}`}
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
                      window.__fieldreportPrefillDate = cell.dateStr;
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
                          <button
                            key={r.id}
                            type="button"
                            onClick={(e) => {
                              // Each dot opens its own report so days with
                              // more than one report are never a dead-end
                              // (cell click alone always opened reports[0]).
                              e.stopPropagation();
                              handleOpenEdit(r);
                            }}
                            className={clsx(
                              'h-2.5 w-2.5 rounded-full ring-offset-1 transition-transform hover:scale-125 hover:ring-1 hover:ring-oe-blue',
                              STATUS_DOT_COLOR[r.status],
                            )}
                            title={`${t(`fieldreports.type_${r.report_type}`, { defaultValue: r.report_type })} - ${t(`fieldreports.status_${r.status}`, { defaultValue: r.status })}`}
                            aria-label={`${t(`fieldreports.type_${r.report_type}`, { defaultValue: r.report_type })} - ${t(`fieldreports.status_${r.status}`, { defaultValue: r.status })}`}
                          />
                        ))}
                      </div>
                    </>
                  )}
                </div>
              ))}
            </div>}

            {/* Legend */}
            <div className="mt-3 flex items-center gap-4 text-xs text-content-tertiary">
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-content-tertiary" />
                {t('fieldreports.status_draft', { defaultValue: 'Draft' })}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-semantic-info" />
                {t('fieldreports.status_submitted', { defaultValue: 'Submitted' })}
              </span>
              <span className="flex items-center gap-1.5">
                <span className="h-2 w-2 rounded-full bg-semantic-success" />
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
              aria-label={t('fieldreports.filter_status', { defaultValue: 'Filter by status' })}
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
              aria-label={t('fieldreports.filter_type', { defaultValue: 'Filter by type' })}
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
          {isLoading ? (
            <div className="space-y-3 p-4">
              {Array.from({ length: 5 }).map((_, i) => (
                <div key={i} className="h-12 animate-pulse rounded-lg bg-surface-secondary" />
              ))}
            </div>
          ) : isListError ? (
            <div className="p-4">
              <RecoveryCard error={listError} onRetry={() => refetchList()} />
            </div>
          ) : listReports.length === 0 ? (
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
                                className="rounded p-1.5 text-semantic-info hover:bg-semantic-info-bg"
                                title={t('fieldreports.submit', { defaultValue: 'Submit' })}
                                aria-label={t('fieldreports.submit', { defaultValue: 'Submit' })}
                              >
                                <Send size={15} />
                              </button>
                            )}
                            {report.status === 'submitted' && (
                              <button
                                onClick={() => void handleApprove(report.id)}
                                className="rounded p-1.5 text-semantic-success hover:bg-semantic-success-bg"
                                title={t('fieldreports.approve_hint', { defaultValue: 'Approve (locks the report permanently)' })}
                                aria-label={t('fieldreports.approve', { defaultValue: 'Approve' })}
                              >
                                <CheckCircle2 size={15} />
                              </button>
                            )}
                            <button
                              onClick={() => pdfMut.mutate(report.id)}
                              disabled={pdfMut.isPending}
                              className="rounded p-1.5 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary disabled:opacity-50"
                              title={t('fieldreports.export_pdf', { defaultValue: 'Export PDF' })}
                              aria-label={t('fieldreports.export_pdf', { defaultValue: 'Export PDF' })}
                            >
                              <Download size={15} />
                            </button>
                            {report.status !== 'approved' && (
                              <button
                                onClick={() => handleDelete(report.id)}
                                className="rounded p-1.5 text-semantic-error hover:bg-semantic-error-bg"
                                title={t('common.delete', { defaultValue: 'Delete' })}
                                aria-label={t('common.delete', { defaultValue: 'Delete' })}
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
            delete window.__fieldreportPrefillDate;
          }}
          onCreate={(data) => createMut.mutate(data)}
          onCreateDraft={async (data) => {
            // Persist a draft so attachments can be added before the user's
            // first explicit Save. Deliberately does NOT close the modal or
            // swap ``editingReport`` (that would remount the form and lose
            // in-progress edits); the modal tracks the draft internally.
            try {
              const created = await createFieldReport(data);
              queryClient.invalidateQueries({ queryKey: ['fieldreports'] });
              return created;
            } catch (e) {
              addToast({
                type: 'error',
                title: t('common.error', { defaultValue: 'Error' }),
                message: e instanceof Error ? e.message : String(e),
              });
              return null;
            }
          }}
          onUpdate={(id, data) => updateMut.mutate({ id, data })}
          onSubmit={(id) => {
            submitMut.mutate(id);
            setShowModal(false);
            setEditingReport(null);
          }}
          onApprove={async (id) => {
            const ok = await handleApprove(id);
            if (ok) {
              setShowModal(false);
              setEditingReport(null);
            }
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

      {/* Manage templates modal */}
      {showTemplatesModal && (
        <ManageTemplatesModal
          projectId={projectId}
          onClose={() => setShowTemplatesModal(false)}
        />
      )}
      <ConfirmDialog {...confirmProps} />
        </>
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
      setError(err instanceof Error ? err.message : t('fieldreports.import_failed_generic', { defaultValue: 'Import failed' }));
    } finally {
      setIsPending(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-lg animate-fade-in">
      <div className="w-full max-w-lg bg-surface-elevated rounded-xl shadow-xl border border-border animate-card-in mx-4 max-h-[90vh] overflow-y-auto" role="dialog" aria-label={t('fieldreports.import_reports', { defaultValue: 'Import Field Reports' })}>
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-border-light">
          <h2 className="text-lg font-semibold text-content-primary">
            {t('fieldreports.import_reports', { defaultValue: 'Import Field Reports' })}
          </h2>
          <button
            onClick={onClose}
            aria-label={t('common.close', { defaultValue: 'Close' })}
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
              {t('fieldreports.file_types', { defaultValue: '.xlsx, .csv' })}
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
          <p className="text-xs text-content-tertiary">
            {t('fieldreports.import_scope_hint', {
              defaultValue:
                'Only the "Field Reports" sheet is imported. Add detailed workforce and equipment logs per report in the app after import.',
            })}
          </p>

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
                    {result.errors.slice(0, 20).map((err) => (
                      <li key={`row-${err.row}`}>
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

/** Every field the report modal holds, in the shape the inputs use. */
export interface FieldReportFormState {
  reportDate: string;
  reportType: ReportType;
  weatherCondition: WeatherCondition;
  temperatureC: string;
  windSpeed: string;
  precipitation: string;
  humidity: string;
  workforce: WorkforceEntry[];
  workPerformed: string;
  delays: string;
  delayHours: string;
  safetyIncidents: string;
  visitors: string;
  deliveries: string;
  notes: string;
  /** Newline-separated, one item per line. */
  equipmentOnSite: string;
  materialsUsed: string;
  signatureBy: string;
  signatureData: string | null;
  templateId: string;
  templateValues: TemplateFieldValues;
}

/**
 * The form state a report opens with.
 *
 * Exported and pure so the save can rebuild the same baseline the fields were
 * seeded from and send only what the user actually changed. Correcting the
 * delay note used to write the whole report back, weather and workforce and
 * signature included, exactly as they stood when this copy was read, undoing
 * anyone else's edit to them without a word or an error.
 *
 * Both sides have to come from one definition. A blank workforce becomes one
 * empty row so the table has something to render, and the template binding is
 * dug out of the metadata blob; do either of those a second way and a field
 * nobody touched starts reading as changed.
 */
export function fieldReportFormState(
  report: FieldReport | null,
  prefillDate: string,
): FieldReportFormState {
  const meta = (report?.metadata ?? {}) as Record<string, unknown>;
  return {
    reportDate: report?.report_date ?? prefillDate,
    reportType: report?.report_type ?? 'daily',
    weatherCondition: report?.weather_condition ?? 'clear',
    temperatureC: report?.temperature_c != null ? String(report.temperature_c) : '',
    windSpeed: report?.wind_speed ?? '',
    precipitation: report?.precipitation ?? '',
    humidity: report?.humidity != null ? String(report.humidity) : '',
    workforce: report?.workforce?.length ? report.workforce : [{ trade: '', count: 0, hours: 8 }],
    workPerformed: report?.work_performed ?? '',
    delays: report?.delays ?? '',
    delayHours: report?.delay_hours != null ? String(report.delay_hours) : '0',
    safetyIncidents: report?.safety_incidents ?? '',
    visitors: report?.visitors ?? '',
    deliveries: report?.deliveries ?? '',
    notes: report?.notes ?? '',
    equipmentOnSite: (report?.equipment_on_site ?? []).join('\n'),
    materialsUsed: (report?.materials_used ?? []).join('\n'),
    signatureBy: report?.signature_by ?? '',
    signatureData: report?.signature_data ?? null,
    templateId: typeof meta.template_id === 'string' ? meta.template_id : '',
    templateValues: (meta.template_fields as TemplateFieldValues) ?? {},
  };
}

/** Compared by content, not identity: rebuilding the baseline makes fresh
 *  objects every time, so a reference test would resend them on every save. */
function sameContent(a: unknown, b: unknown): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/**
 * The body of an edit save: only the fields the user actually changed.
 *
 * `full` is the payload describing the whole form, which is what used to go
 * back on every save. The update route dumps with `exclude_unset=True`, so a
 * field left out of the body is left alone in the database, which is what
 * makes omission the right tool here.
 *
 * `metadata` is a blob, so there is no partial write of it: it goes whole or
 * not at all, and it goes only when the template binding moved.
 */
export function buildFieldReportPatch(
  form: FieldReportFormState,
  base: FieldReportFormState,
  full: UpdateFieldReportPayload,
): UpdateFieldReportPayload {
  const patch: UpdateFieldReportPayload = {};
  if (form.reportDate !== base.reportDate) patch.report_date = full.report_date;
  if (form.reportType !== base.reportType) patch.report_type = full.report_type;
  if (form.weatherCondition !== base.weatherCondition) {
    patch.weather_condition = full.weather_condition;
  }
  if (form.temperatureC !== base.temperatureC) patch.temperature_c = full.temperature_c;
  if (form.windSpeed !== base.windSpeed) patch.wind_speed = full.wind_speed;
  if (form.precipitation !== base.precipitation) patch.precipitation = full.precipitation;
  if (form.humidity !== base.humidity) patch.humidity = full.humidity;
  if (form.workPerformed !== base.workPerformed) patch.work_performed = full.work_performed;
  if (form.delays !== base.delays) patch.delays = full.delays;
  if (form.delayHours !== base.delayHours) patch.delay_hours = full.delay_hours;
  if (form.safetyIncidents !== base.safetyIncidents) patch.safety_incidents = full.safety_incidents;
  if (form.visitors !== base.visitors) patch.visitors = full.visitors;
  if (form.deliveries !== base.deliveries) patch.deliveries = full.deliveries;
  if (form.notes !== base.notes) patch.notes = full.notes;
  if (form.equipmentOnSite !== base.equipmentOnSite) {
    patch.equipment_on_site = full.equipment_on_site;
  }
  if (form.materialsUsed !== base.materialsUsed) patch.materials_used = full.materials_used;
  if (form.signatureBy !== base.signatureBy) patch.signature_by = full.signature_by;
  if (form.signatureData !== base.signatureData) patch.signature_data = full.signature_data;
  if (!sameContent(form.workforce, base.workforce)) patch.workforce = full.workforce;
  if (
    form.templateId !== base.templateId ||
    !sameContent(form.templateValues, base.templateValues)
  ) {
    patch.metadata = full.metadata;
  }
  return patch;
}

function ReportModal({
  report,
  projectId,
  onClose,
  onCreate,
  onCreateDraft,
  onUpdate,
  onSubmit,
  onApprove,
  loading,
}: {
  report: FieldReport | null;
  projectId: string;
  onClose: () => void;
  onCreate: (data: CreateFieldReportPayload) => void;
  // Create a draft report WITHOUT closing the modal, returning the saved row
  // so attachments can target its id. Resolves null on failure.
  onCreateDraft: (data: CreateFieldReportPayload) => Promise<FieldReport | null>;
  onUpdate: (id: string, data: UpdateFieldReportPayload) => void;
  onSubmit: (id: string) => void;
  onApprove: (id: string) => void | Promise<unknown>;
  loading: boolean;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  // A report created mid-session purely so attachments can be added before
  // the user's first explicit Save (the attachments API needs a report id).
  // Once it exists the modal behaves exactly like editing an existing draft:
  // ``effectiveReport`` is the report we save / gate attachments on.
  const [draftReport, setDraftReport] = useState<FieldReport | null>(null);
  const effectiveReport = report ?? draftReport;
  const isEdit = effectiveReport != null;
  const [creatingDraft, setCreatingDraft] = useState(false);

  // Prefill date from calendar click
  const prefillDate =
    window.__fieldreportPrefillDate || todayStr();

  // Seeded from the same function the save compares against, so the two can
  // never drift apart. See `fieldReportFormState`.
  const seed = fieldReportFormState(report, prefillDate);
  const [reportDate, setReportDate] = useState(seed.reportDate);
  const [reportType, setReportType] = useState<ReportType>(seed.reportType);
  const [weatherCondition, setWeatherCondition] = useState<WeatherCondition>(
    seed.weatherCondition,
  );
  const [temperatureC, setTemperatureC] = useState<string>(seed.temperatureC);
  const [windSpeed, setWindSpeed] = useState(seed.windSpeed);
  const [precipitation, setPrecipitation] = useState(seed.precipitation);
  const [humidity, setHumidity] = useState<string>(seed.humidity);
  const [workforce, setWorkforce] = useState<WorkforceEntry[]>(seed.workforce);
  const [workPerformed, setWorkPerformed] = useState(seed.workPerformed);
  const [delays, setDelays] = useState(seed.delays);
  const [delayHours, setDelayHours] = useState<string>(seed.delayHours);
  const [safetyIncidents, setSafetyIncidents] = useState(seed.safetyIncidents);
  const [visitors, setVisitors] = useState(seed.visitors);
  const [deliveries, setDeliveries] = useState(seed.deliveries);
  const [notes, setNotes] = useState(seed.notes);

  // Equipment-on-site and materials-used are persisted string lists that
  // surface in the PDF/Excel exports; they had no UI before. Edited as a
  // newline-separated textarea (one item per line) for simplicity.
  const [equipmentOnSite, setEquipmentOnSite] = useState<string>(seed.equipmentOnSite);
  const [materialsUsed, setMaterialsUsed] = useState<string>(seed.materialsUsed);
  const [signatureBy, setSignatureBy] = useState(seed.signatureBy);
  const [signatureData, setSignatureData] = useState<string | null>(seed.signatureData);

  // Weather auto-fetch (uses the existing GET /weather/ endpoint via the
  // browser geolocation API; the endpoint needs OPENWEATHERMAP_API_KEY).
  const [weatherBusy, setWeatherBusy] = useState(false);

  // Template state. Existing reports carry their template id + filled
  // values inside metadata (the report table itself is untouched).
  const reportMeta = (report?.metadata ?? {}) as Record<string, unknown>;
  const [templateId, setTemplateId] = useState<string>(seed.templateId);
  const [selectedTemplate, setSelectedTemplate] =
    useState<FieldReportTemplate | null>(null);
  const [templateValues, setTemplateValues] = useState<TemplateFieldValues>(
    seed.templateValues,
  );

  const handleTemplateChange = useCallback(
    (id: string, tpl: FieldReportTemplate | null) => {
      setTemplateId(id);
      setSelectedTemplate(tpl);
      if (tpl && id !== templateId) {
        // Seed empty values for the new template's keys without losing
        // any already-entered value whose key still exists.
        setTemplateValues((prev) => {
          const next: TemplateFieldValues = {};
          for (const f of tpl.fields) {
            next[f.key] = prev[f.key] ?? (f.type === 'checkbox' ? false : '');
          }
          return next;
        });
      }
      if (!tpl) setTemplateValues({});
    },
    [templateId],
  );

  const handleTemplateValueChange = useCallback(
    (key: string, value: string | number | boolean) => {
      setTemplateValues((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

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

  const handleFetchWeather = useCallback(() => {
    if (!('geolocation' in navigator)) {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: t('fieldreports.geo_unsupported', {
          defaultValue: 'Geolocation is not available in this browser.',
        }),
      });
      return;
    }
    setWeatherBusy(true);
    navigator.geolocation.getCurrentPosition(
      async (pos) => {
        try {
          const wx = await fetchWeather(pos.coords.latitude, pos.coords.longitude);
          if (!wx.available) {
            addToast({
              type: 'info',
              title: t('fieldreports.weather', { defaultValue: 'Weather Conditions' }),
              message:
                wx.error ||
                t('fieldreports.weather_unavailable', {
                  defaultValue: 'Live weather is not configured on this server.',
                }),
            });
            return;
          }
          setWeatherCondition(weatherConditionFromDescription(wx.description, wx.icon));
          if (wx.temperature_c != null) setTemperatureC(String(Math.round(wx.temperature_c)));
          if (wx.humidity_pct != null) setHumidity(String(Math.round(wx.humidity_pct)));
          if (wx.wind_speed_ms != null) {
            const kmh = Math.round(wx.wind_speed_ms * 3.6);
            setWindSpeed(`${kmh} km/h${wx.wind_direction ? ` ${wx.wind_direction}` : ''}`);
          }
          if (wx.precipitation_mm != null && wx.precipitation_mm > 0) {
            setPrecipitation(`${wx.precipitation_mm} mm`);
          }
          addToast({
            type: 'success',
            title: '',
            message: t('fieldreports.weather_filled', {
              defaultValue: 'Weather filled from current location',
            }),
          });
        } catch (err: unknown) {
          addToast({
            type: 'error',
            title: t('common.error', { defaultValue: 'Error' }),
            message:
              err instanceof Error
                ? err.message
                : t('fieldreports.weather_fetch_failed', { defaultValue: 'Weather fetch failed' }),
          });
        } finally {
          setWeatherBusy(false);
        }
      },
      (geoErr) => {
        setWeatherBusy(false);
        addToast({
          type: 'error',
          title: t('common.error', { defaultValue: 'Error' }),
          message:
            geoErr.code === geoErr.PERMISSION_DENIED
              ? t('fieldreports.geo_denied', {
                  defaultValue: 'Location permission denied. Enter weather manually below.',
                })
              : t('fieldreports.geo_failed', {
                  defaultValue: 'Could not determine your location. Enter weather manually below.',
                }),
        });
      },
      { timeout: 10000, maximumAge: 600000 },
    );
  }, [addToast, t]);

  const handleSave = useCallback(() => {
    // Enforce required template fields so the template "required" flag is
    // meaningful (previously a "required" field could be left blank with no
    // warning). Only validate against the resolved template's definitions.
    if (selectedTemplate && selectedTemplate.id === templateId) {
      const missing = selectedTemplate.fields.filter((f) => {
        if (!f.required) return false;
        const v = templateValues[f.key];
        if (f.type === 'checkbox') return v !== true;
        return v == null || String(v).trim() === '';
      });
      if (missing.length > 0) {
        addToast({
          type: 'error',
          title: t('fieldreports.required_fields_title', { defaultValue: 'Required fields missing' }),
          message: t('fieldreports.required_fields_msg', {
            defaultValue: 'Please fill the required template fields: {{fields}}',
            fields: fmtList(missing.map((f) => f.label)),
          }),
        });
        return;
      }
    }

    const cleanWorkforce = workforce.filter((e) => e.trade.trim() !== '');
    const splitLines = (s: string): string[] =>
      s
        .split('\n')
        .map((line) => line.trim())
        .filter((line) => line !== '');
    // Preserve any pre-existing metadata keys; only (re)write the
    // template binding so nothing else (e.g. imported flags) is lost.
    const baseMeta = { ...reportMeta } as Record<string, unknown>;
    if (templateId) {
      baseMeta.template_id = templateId;
      baseMeta.template_fields = templateValues;
    } else {
      delete baseMeta.template_id;
      delete baseMeta.template_fields;
    }
    const payload = {
      report_date: reportDate,
      report_type: reportType,
      weather_condition: weatherCondition,
      temperature_c: temperatureC ? parseFloat(temperatureC) : null,
      wind_speed: windSpeed || null,
      precipitation: precipitation || null,
      humidity: humidity ? parseInt(humidity, 10) : null,
      workforce: cleanWorkforce,
      equipment_on_site: splitLines(equipmentOnSite),
      materials_used: splitLines(materialsUsed),
      work_performed: workPerformed,
      delays: delays || null,
      delay_hours: parseFloat(delayHours) || 0,
      safety_incidents: safetyIncidents || null,
      visitors: visitors || null,
      deliveries: deliveries || null,
      notes: notes || null,
      signature_by: signatureBy || null,
      signature_data: signatureData || null,
      metadata: baseMeta,
    };

    if (isEdit && effectiveReport) {
      // Rebuild the baseline this modal was seeded from, so the save carries
      // only what the user actually edited. See `buildFieldReportPatch`. A
      // report first created as a mid-session draft has no seed of its own, so
      // the baseline is that saved row and the diff runs from there.
      onUpdate(
        effectiveReport.id,
        buildFieldReportPatch(
          {
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
            equipmentOnSite,
            materialsUsed,
            signatureBy,
            signatureData,
            templateId,
            templateValues,
          },
          fieldReportFormState(effectiveReport, prefillDate),
          payload,
        ),
      );
    } else {
      onCreate({ ...payload, project_id: projectId } as CreateFieldReportPayload);
    }
  }, [
    isEdit,
    effectiveReport,
    prefillDate,
    projectId,
    reportDate,
    reportType,
    weatherCondition,
    temperatureC,
    windSpeed,
    precipitation,
    humidity,
    workforce,
    equipmentOnSite,
    materialsUsed,
    workPerformed,
    delays,
    delayHours,
    safetyIncidents,
    visitors,
    deliveries,
    notes,
    signatureBy,
    signatureData,
    reportMeta,
    templateId,
    templateValues,
    selectedTemplate,
    addToast,
    t,
    onCreate,
    onUpdate,
  ]);

  // Lazily persist a draft so attachments can be added before the user's
  // first explicit Save. No-op once a report already exists. Seeds the draft
  // with the date/type already chosen so it is not an empty shell; the rest
  // of the form is written on the next Save (which now updates this draft).
  const handleEnsureDraft = useCallback(async (): Promise<FieldReport | null> => {
    if (effectiveReport) return effectiveReport;
    if (!reportDate) {
      addToast({
        type: 'error',
        title: t('fieldreports.date_required_for_attach', {
          defaultValue: 'Pick a report date before attaching files.',
        }),
      });
      return null;
    }
    setCreatingDraft(true);
    try {
      const created = await onCreateDraft({
        project_id: projectId,
        report_date: reportDate,
        report_type: reportType,
      } as CreateFieldReportPayload);
      if (created) setDraftReport(created);
      return created;
    } finally {
      setCreatingDraft(false);
    }
  }, [effectiveReport, reportDate, reportType, projectId, onCreateDraft, addToast, t]);

  const inputCls = 'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary';
  const textareaCls = 'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm text-content-primary resize-y';

  return (
    <WideModal
      open
      onClose={onClose}
      busy={loading}
      size="2xl"
      title={
        isEdit
          ? t('fieldreports.edit_report', { defaultValue: 'Edit Field Report' })
          : t('fieldreports.new_report', { defaultValue: 'New Field Report' })
      }
      subtitle={
        isEdit && effectiveReport
          ? t(`fieldreports.status_${effectiveReport.status}`, {
              defaultValue: effectiveReport.status,
            })
          : undefined
      }
      footer={
        <>
          <div className="mr-auto flex items-center gap-2">
            {isEdit && effectiveReport?.status === 'draft' && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onSubmit(effectiveReport.id)}
                className="shrink-0 whitespace-nowrap"
                title={t('fieldreports.submit_hint', {
                  defaultValue: 'Submitting sends the report for approval.',
                })}
              >
                <Send size={14} className="mr-1.5 shrink-0" />
                <span className="whitespace-nowrap">{t('fieldreports.submit', { defaultValue: 'Submit for Approval' })}</span>
              </Button>
            )}
            {isEdit && effectiveReport?.status === 'submitted' && (
              <Button
                size="sm"
                variant="secondary"
                onClick={() => onApprove(effectiveReport.id)}
                className="shrink-0 whitespace-nowrap"
                title={t('fieldreports.approve_hint', {
                  defaultValue: 'Approve (locks the report permanently)',
                })}
              >
                <CheckCircle2 size={14} className="mr-1.5 shrink-0" />
                <span className="whitespace-nowrap">{t('fieldreports.approve', { defaultValue: 'Approve' })}</span>
              </Button>
            )}
            {isEdit && (effectiveReport?.status === 'draft' || effectiveReport?.status === 'submitted') && (
              <span className="hidden items-center gap-1 text-xs text-content-tertiary sm:flex">
                <Info size={12} className="shrink-0" />
                {effectiveReport?.status === 'draft'
                  ? t('fieldreports.submit_hint', {
                      defaultValue: 'Submitting sends the report for approval.',
                    })
                  : t('fieldreports.approve_lock_hint', {
                      defaultValue: 'Approving locks the report permanently.',
                    })}
              </span>
            )}
          </div>
          <Button size="sm" variant="ghost" onClick={onClose} disabled={loading}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          {(!isEdit || effectiveReport?.status !== 'approved') && (
            <Button size="sm" onClick={handleSave} disabled={loading || !reportDate}>
              {isEdit
                ? t('common.save', { defaultValue: 'Save' })
                : t('fieldreports.create', { defaultValue: 'Create Report' })}
            </Button>
          )}
        </>
      }
    >
      {isEdit && effectiveReport?.status === 'approved' && (
        <div className="mb-5 flex items-start gap-2 rounded-lg border border-border-light bg-surface-secondary/50 p-3 text-xs text-content-secondary">
          <Lock size={14} className="mt-0.5 shrink-0 text-content-tertiary" />
          <span>
            {t('fieldreports.approved_locked', {
              defaultValue:
                'This report is approved and locked. It can be viewed and exported but no longer edited.',
            })}
          </span>
        </div>
      )}

      <WideModalSection columns={2}>
        <TemplatePicker
          projectId={projectId}
          value={templateId}
          onChange={handleTemplateChange}
          onResolve={setSelectedTemplate}
          disabled={isEdit && effectiveReport?.status === 'approved'}
        />
        <WideModalField label={t('fieldreports.report_date', { defaultValue: 'Date' })}>
          <input
            type="date"
            value={reportDate}
            onChange={(e) => setReportDate(e.target.value)}
            className={inputCls}
            disabled={isEdit && effectiveReport?.status === 'approved'}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.report_type', { defaultValue: 'Report Type' })}>
          <select
            value={reportType}
            onChange={(e) => setReportType(e.target.value as ReportType)}
            className={inputCls}
            disabled={isEdit && effectiveReport?.status === 'approved'}
          >
            {REPORT_TYPES.map((rt) => (
              <option key={rt} value={rt}>
                {t(`fieldreports.type_${rt}`, { defaultValue: rt.replace(/_/g, ' ') })}
              </option>
            ))}
          </select>
        </WideModalField>
      </WideModalSection>

      {selectedTemplate && selectedTemplate.id === templateId && (
        <TemplateFieldEditor
          template={selectedTemplate}
          values={templateValues}
          onChange={handleTemplateValueChange}
        />
      )}

      {effectiveReport ? (
        // A report (existing or just-created draft) exists, so its id can
        // anchor uploaded photos/documents.
        <ReportAttachments reportId={effectiveReport.id} projectId={projectId} />
      ) : (
        // No report yet: offer to start attaching now. The first click
        // persists a draft (date/type only) so the existing uploader can
        // target it - no need to fully save first.
        <WideModalSection
          title={t('fieldreports.attachments', { defaultValue: 'Attachments' })}
          columns={1}
        >
          <WideModalField
            label={t('fieldreports.attachments', { defaultValue: 'Attachments' })}
            className="sm:[&>label]:hidden"
          >
            <div className="flex flex-col items-start gap-2">
              <Button
                size="sm"
                variant="secondary"
                disabled={creatingDraft || !reportDate}
                onClick={() => void handleEnsureDraft()}
              >
                {creatingDraft ? (
                  <Loader2 size={14} className="mr-1.5 animate-spin" />
                ) : (
                  <Upload size={14} className="mr-1.5" />
                )}
                {t('fieldreports.start_attaching', {
                  defaultValue: 'Add photos & documents',
                })}
              </Button>
              <p className="text-xs text-content-tertiary">
                {t('fieldreports.attachments_autodraft_hint', {
                  defaultValue:
                    'Saves a draft so you can attach files right away; finish the rest of the report and Save when ready.',
                })}
              </p>
            </div>
          </WideModalField>
        </WideModalSection>
      )}

      <WideModalSection
        title={t('fieldreports.weather', { defaultValue: 'Weather Conditions' })}
        columns={2}
      >
        <WideModalField
          label={t('fieldreports.weather', { defaultValue: 'Weather Conditions' })}
          span={2}
          className="sm:[&>label]:hidden"
        >
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={handleFetchWeather}
              disabled={weatherBusy}
              className="flex items-center gap-1.5 rounded-lg border border-border-light px-3 py-1.5 text-sm text-content-secondary hover:bg-surface-secondary disabled:opacity-50 transition-colors"
            >
              {weatherBusy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <CloudSun size={14} />
              )}
              {t('fieldreports.fetch_weather', { defaultValue: 'Fetch current weather' })}
            </button>
            <span className="text-xs text-content-tertiary">
              {t('fieldreports.fetch_weather_hint', {
                defaultValue: 'Uses your current location; falls back to manual entry below.',
              })}
            </span>
          </div>
        </WideModalField>
        <WideModalField label={t('fieldreports.condition', { defaultValue: 'Condition' })}>
          <select
            value={weatherCondition}
            onChange={(e) => setWeatherCondition(e.target.value as WeatherCondition)}
            className={inputCls}
          >
            {WEATHER_CONDITIONS.map((wc) => (
              <option key={wc} value={wc}>
                {t(`fieldreports.weather_${wc}`, { defaultValue: wc })}
              </option>
            ))}
          </select>
        </WideModalField>
        <WideModalField label={t('fieldreports.temperature', { defaultValue: 'Temp (\u00B0C)' })}>
          <input
            type="number"
            value={temperatureC}
            onChange={(e) => setTemperatureC(e.target.value)}
            placeholder="--"
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.wind', { defaultValue: 'Wind' })}>
          <input
            type="text"
            value={windSpeed}
            onChange={(e) => setWindSpeed(e.target.value)}
            placeholder={t('fieldreports.wind_placeholder', { defaultValue: 'e.g. 15 km/h NW' })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.humidity_label', { defaultValue: 'Humidity (%)' })}>
          <input
            type="number"
            value={humidity}
            onChange={(e) => setHumidity(e.target.value)}
            placeholder="--"
            min={0}
            max={100}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('fieldreports.precipitation_label', { defaultValue: 'Precipitation' })}
          span={2}
        >
          <input
            type="text"
            value={precipitation}
            onChange={(e) => setPrecipitation(e.target.value)}
            placeholder={t('fieldreports.precipitation_placeholder', {
              defaultValue: 'e.g. 5 mm rain, light snow…',
            })}
            className={inputCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('fieldreports.workforce_section', { defaultValue: 'Workforce' })}
        columns={1}
      >
        <WideModalField
          label={t('fieldreports.trade', { defaultValue: 'Trade' })}
          className="!flex-row !items-center !gap-2 sm:[&>label]:hidden"
        >
          <div className="w-full space-y-2">
            {workforce.map((entry, idx) => (
              <div key={`workforce-${entry.trade}-${idx}`} className="flex items-center gap-2">
                <div className="flex-1">
                  <input
                    type="text"
                    list="trades-list"
                    value={entry.trade}
                    onChange={(e) => handleWorkforceChange(idx, 'trade', e.target.value)}
                    placeholder={t('fieldreports.trade', { defaultValue: 'Trade' })}
                    className={inputCls}
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
                    className={inputCls}
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
                    className={inputCls}
                  />
                </div>
                <button
                  onClick={() => handleRemoveWorkforce(idx)}
                  className="rounded p-1 text-content-tertiary hover:text-semantic-error hover:bg-semantic-error-bg"
                  title={t('common.remove', { defaultValue: 'Remove' })}
                  aria-label={t('common.remove', { defaultValue: 'Remove' })}
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
        </WideModalField>
      </WideModalSection>

      <WideModalSection
        title={t('fieldreports.equipment_materials', { defaultValue: 'Equipment & Materials' })}
        description={t('fieldreports.equipment_materials_help', {
          defaultValue: 'One item per line. These appear in the PDF and Excel exports.',
        })}
        columns={2}
      >
        <WideModalField
          label={t('fieldreports.equipment_on_site', { defaultValue: 'Equipment on site' })}
          hint={t('fieldreports.one_per_line', { defaultValue: 'One item per line' })}
        >
          <textarea
            value={equipmentOnSite}
            onChange={(e) => setEquipmentOnSite(e.target.value)}
            rows={3}
            placeholder={t('fieldreports.equipment_on_site_placeholder', {
              defaultValue: 'Tower crane\nExcavator CAT 320\nConcrete pump',
            })}
            className={textareaCls}
          />
        </WideModalField>
        <WideModalField
          label={t('fieldreports.materials_used', { defaultValue: 'Materials used' })}
          hint={t('fieldreports.one_per_line', { defaultValue: 'One item per line' })}
        >
          <textarea
            value={materialsUsed}
            onChange={(e) => setMaterialsUsed(e.target.value)}
            rows={3}
            placeholder={t('fieldreports.materials_used_placeholder', {
              defaultValue: 'C30/37 concrete 12 m³\nRebar 1.8 t\nFormwork panels',
            })}
            className={textareaCls}
          />
        </WideModalField>
      </WideModalSection>

      <WideModalSection columns={2}>
        <WideModalField
          label={t('fieldreports.work_performed', { defaultValue: 'Work Performed' })}
          span={2}
        >
          <textarea
            value={workPerformed}
            onChange={(e) => setWorkPerformed(e.target.value)}
            rows={3}
            placeholder={t('fieldreports.work_performed_placeholder', {
              defaultValue: 'Describe work activities completed today...',
            })}
            className={textareaCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.delays_label', { defaultValue: 'Delays' })}>
          <textarea
            value={delays}
            onChange={(e) => setDelays(e.target.value)}
            rows={2}
            placeholder={t('fieldreports.delays_placeholder', {
              defaultValue: 'Describe any delays encountered...',
            })}
            className={textareaCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.delay_hours', { defaultValue: 'Delay Hours' })}>
          <input
            type="number"
            value={delayHours}
            onChange={(e) => setDelayHours(e.target.value)}
            min={0}
            step={0.5}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField
          label={t('fieldreports.safety_incidents', { defaultValue: 'Safety Incidents' })}
          span={2}
        >
          <textarea
            value={safetyIncidents}
            onChange={(e) => setSafetyIncidents(e.target.value)}
            rows={2}
            placeholder={t('fieldreports.safety_placeholder', {
              defaultValue: 'Report any safety incidents or near-misses...',
            })}
            className={textareaCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.visitors', { defaultValue: 'Visitors' })}>
          <input
            type="text"
            value={visitors}
            onChange={(e) => setVisitors(e.target.value)}
            placeholder={t('fieldreports.visitors_placeholder', {
              defaultValue: 'Site visitors today...',
            })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.deliveries', { defaultValue: 'Deliveries' })}>
          <input
            type="text"
            value={deliveries}
            onChange={(e) => setDeliveries(e.target.value)}
            placeholder={t('fieldreports.deliveries_placeholder', {
              defaultValue: 'Materials or equipment delivered...',
            })}
            className={inputCls}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.notes', { defaultValue: 'Notes' })} span={2}>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            placeholder={t('fieldreports.notes_placeholder', {
              defaultValue: 'Additional notes or observations...',
            })}
            className={textareaCls}
          />
        </WideModalField>
      </WideModalSection>

      {/* Structured workforce / equipment logs - only for saved reports
          (existing or a just-created draft), since the rows attach to an
          existing report id. These drive the detailed CRUD endpoints that
          feed the labour-cost rollup. */}
      {effectiveReport && (
        <SiteLogEditor
          reportId={effectiveReport.id}
          disabled={effectiveReport.status === 'approved'}
        />
      )}

      <WideModalSection
        title={t('fieldreports.signature', { defaultValue: 'Signature' })}
        columns={2}
      >
        <WideModalField label={t('fieldreports.signature_by', { defaultValue: 'Signed by' })}>
          <input
            type="text"
            value={signatureBy}
            onChange={(e) => setSignatureBy(e.target.value)}
            placeholder={t('fieldreports.signature_by_placeholder', {
              defaultValue: 'Name of site representative',
            })}
            className={inputCls}
            disabled={isEdit && report?.status === 'approved'}
          />
        </WideModalField>
        <WideModalField label={t('fieldreports.signature', { defaultValue: 'Signature' })} span={2}>
          <SignaturePad
            value={signatureData}
            onChange={setSignatureData}
            disabled={isEdit && report?.status === 'approved'}
          />
        </WideModalField>
      </WideModalSection>
    </WideModal>
  );
}
