// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cost-Value Reconciliation (CVR) & Cashflow.
 *
 * The commercial monthly CVR: pick a reporting month, reconcile cost-to-date
 * against value earned per cost head, read the forecast final margin, and track
 * the project cashflow as a cumulative S-curve plus interim payment applications.
 *
 * Money arrives from the API as Decimal-as-string; it is only ever formatted for
 * display (formatCurrency) or coerced to a finite number for the chart (toNum).
 * We never do arithmetic that assumes a JS number on a wire value.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useParams } from 'react-router-dom';
import {
  Area,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Plus, Trash2, Lock, TrendingUp, TrendingDown, AlertTriangle, Pencil, Download } from 'lucide-react';
import {
  Button,
  Card,
  Badge,
  EmptyState,
  RecoveryCard,
  SkeletonTable,
  ConfirmDialog,
  SideDrawer,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { RequiresProject } from '@/shared/auth/RequiresProject';
import { apiGet, getErrorMessage } from '@/shared/lib/api';
import { formatCurrency, toNum } from '@/shared/lib/money';
import { useToastStore } from '@/stores/useToastStore';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  fetchCvrReports,
  createCvrReport,
  finalizeCvrReport,
  deleteCvrReport,
  fetchCvrSummary,
  fetchCvrLines,
  createCvrLine,
  updateCvrLine,
  deleteCvrLine,
  fetchCashflowSeries,
  fetchCashflowPoints,
  createCashflowPoint,
  updateCashflowPoint,
  deleteCashflowPoint,
  fetchPaymentApplications,
  createPaymentApplication,
  updatePaymentApplication,
  deletePaymentApplication,
  type CvrReport,
  type CvrLine,
  type CvrSummary,
  type CashflowSeries,
  type CashflowPoint,
  type PaymentApplication,
  type PaymentApplicationStatus,
} from './api';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import { buildCvrInsights } from './cvrInsights';
import { fmtList, fmtPercent } from '@/shared/lib/formatters';
import { toDecimalPayloadString } from '@/shared/lib/parseDecimal';

interface Project {
  id: string;
  name: string;
}

const INPUT_CLS =
  'w-full rounded-lg border border-border-light bg-surface-primary px-3 py-2 text-sm ' +
  'text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none ' +
  'focus:ring-2 focus:ring-blue-200 dark:focus:ring-blue-900/40';

/** Current month as YYYY-MM, the natural default for a new CVR / cash point. */
function currentPeriod(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  return `${now.getFullYear()}-${month}`;
}

/** Format a percentage string (e.g. "20.79") for display with one decimal. */
function fmtPct(pct: string): string {
  return fmtPercent(toNum(pct));
}

const PAYAPP_STATUS_TONE: Record<PaymentApplicationStatus, string> = {
  draft: 'bg-surface-secondary text-content-secondary',
  submitted: 'bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300',
  certified: 'bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300',
  paid: 'bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300',
};

/** Payment-application lifecycle in order: draft -> submitted -> certified -> paid. */
const PAYAPP_STATUSES: PaymentApplicationStatus[] = ['draft', 'submitted', 'certified', 'paid'];

/* ── Summary strip ─────────────────────────────────────────────────────── */

function SummaryStrip({ summary, currency }: { summary: CvrSummary; currency: string }) {
  const { t } = useTranslation();
  const marginPositive = toNum(summary.margin_to_date) >= 0;
  const forecastPositive = toNum(summary.forecast_margin) >= 0;

  const tiles: { label: string; value: string; sub?: string; tone?: 'good' | 'bad' }[] = [
    {
      label: t('cvr.value_to_date', { defaultValue: 'Value to date' }),
      value: formatCurrency(summary.total_value_to_date, currency),
    },
    {
      label: t('cvr.cost_to_date', { defaultValue: 'Cost to date' }),
      value: formatCurrency(summary.total_cost_to_date, currency),
    },
    {
      label: t('cvr.margin_to_date', { defaultValue: 'Margin to date' }),
      value: formatCurrency(summary.margin_to_date, currency),
      sub: fmtPct(summary.margin_to_date_pct),
      tone: marginPositive ? 'good' : 'bad',
    },
    {
      label: t('cvr.forecast_margin', { defaultValue: 'Forecast margin' }),
      value: formatCurrency(summary.forecast_margin, currency),
      sub: fmtPct(summary.forecast_margin_pct),
      tone: forecastPositive ? 'good' : 'bad',
    },
  ];

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      {tiles.map((tile) => (
        <Card key={tile.label} padding="sm">
          <div className="text-2xs uppercase tracking-wide text-content-tertiary">{tile.label}</div>
          <div
            className={
              'mt-1 text-lg font-bold tabular-nums ' +
              (tile.tone === 'good'
                ? 'text-semantic-success'
                : tile.tone === 'bad'
                  ? 'text-semantic-error'
                  : 'text-content-primary')
            }
          >
            {tile.value}
          </div>
          {tile.sub && (
            <div className="mt-0.5 flex items-center gap-1 text-xs text-content-tertiary">
              {tile.tone === 'good' ? (
                <TrendingUp size={12} className="text-semantic-success" />
              ) : tile.tone === 'bad' ? (
                <TrendingDown size={12} className="text-semantic-error" />
              ) : null}
              {tile.sub}
            </div>
          )}
        </Card>
      ))}
    </div>
  );
}

/* ── Add cost head (line) form ─────────────────────────────────────────── */

const EMPTY_LINE = {
  cost_code: '',
  description: '',
  cost_to_date: '',
  value_to_date: '',
  accruals: '',
  forecast_cost: '',
  forecast_value: '',
};

function AddLineForm({
  reportId,
  disabled,
  onAdded,
}: {
  reportId: string;
  disabled: boolean;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({ ...EMPTY_LINE });

  const mutation = useMutation({
    mutationFn: () =>
      createCvrLine(reportId, {
        cost_code: form.cost_code,
        description: form.description,
        cost_to_date: toDecimalPayloadString(form.cost_to_date),
        value_to_date: toDecimalPayloadString(form.value_to_date),
        accruals: toDecimalPayloadString(form.accruals),
        forecast_cost: toDecimalPayloadString(form.forecast_cost),
        forecast_value: toDecimalPayloadString(form.forecast_value),
      }),
    onSuccess: () => {
      setForm({ ...EMPTY_LINE });
      onAdded();
      addToast({ type: 'success', title: t('cvr.line_added', { defaultValue: 'Cost head added' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.line_add_failed', { defaultValue: 'Could not add cost head' }), message: getErrorMessage(err) }),
  });

  if (disabled) return null;

  const set = (key: keyof typeof form, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  return (
    <div className="grid grid-cols-2 items-end gap-2 rounded-lg border border-dashed border-border-light p-3 sm:grid-cols-8">
      <input className={INPUT_CLS} placeholder={t('cvr.col_code', { defaultValue: 'Code' })} value={form.cost_code} onChange={(e) => set('cost_code', e.target.value)} />
      <input className={`${INPUT_CLS} sm:col-span-2`} placeholder={t('cvr.col_description', { defaultValue: 'Description' })} value={form.description} onChange={(e) => set('description', e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_cost_to_date', { defaultValue: 'Cost' })} value={form.cost_to_date} onChange={(e) => set('cost_to_date', e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_value_to_date', { defaultValue: 'Value' })} value={form.value_to_date} onChange={(e) => set('value_to_date', e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_forecast_cost', { defaultValue: 'FC cost' })} value={form.forecast_cost} onChange={(e) => set('forecast_cost', e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_forecast_value', { defaultValue: 'FC value' })} value={form.forecast_value} onChange={(e) => set('forecast_value', e.target.value)} />
      <Button variant="secondary" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
        <Plus size={14} className="mr-1 shrink-0" />
        {t('cvr.add', { defaultValue: 'Add' })}
      </Button>
    </div>
  );
}

/* ── Lines table ───────────────────────────────────────────────────────── */

function LinesTable({
  lines,
  summary,
  currency,
  canEdit,
  onDelete,
  onEdit,
}: {
  lines: CvrLine[];
  summary: CvrSummary | undefined;
  currency: string;
  canEdit: boolean;
  onDelete: (lineId: string) => void;
  onEdit: (line: CvrLine) => void;
}) {
  const { t } = useTranslation();

  if (lines.length === 0) {
    return (
      <EmptyState
        title={t('cvr.no_lines', { defaultValue: 'No cost heads yet' })}
        description={t('cvr.no_lines_desc', {
          defaultValue: 'Add the cost heads you are reconciling this month to see margin roll up.',
        })}
      />
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[720px] text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
            <th className="py-2 pr-3 font-medium">{t('cvr.col_code', { defaultValue: 'Code' })}</th>
            <th className="py-2 pr-3 font-medium">{t('cvr.col_description', { defaultValue: 'Description' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_cost_to_date', { defaultValue: 'Cost to date' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_value_to_date', { defaultValue: 'Value to date' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_forecast_cost', { defaultValue: 'Forecast cost' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_forecast_value', { defaultValue: 'Forecast value' })}</th>
            <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_margin', { defaultValue: 'Margin' })}</th>
            {canEdit && <th className="py-2 pl-1" />}
          </tr>
        </thead>
        <tbody>
          {lines.map((line) => {
            const marginPositive = toNum(line.margin_to_date) >= 0;
            return (
              <tr key={line.id} className="border-b border-border-light/60 hover:bg-surface-secondary/40">
                <td className="py-2 pr-3 font-medium text-content-primary">{line.cost_code || '-'}</td>
                <td className="py-2 pr-3 text-content-secondary">
                  <span className="inline-flex items-center gap-1.5">
                    {line.description || '-'}
                    {line.flags.length > 0 && (
                      <span title={fmtList(line.flags)}>
                        <AlertTriangle size={13} className="text-amber-500" />
                      </span>
                    )}
                  </span>
                </td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{formatCurrency(line.cost_to_date, currency)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{formatCurrency(line.value_to_date, currency)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-tertiary">{formatCurrency(line.forecast_cost, currency)}</td>
                <td className="py-2 pr-3 text-right tabular-nums text-content-tertiary">{formatCurrency(line.forecast_value, currency)}</td>
                <td className={'py-2 pr-3 text-right font-semibold tabular-nums ' + (marginPositive ? 'text-semantic-success' : 'text-semantic-error')}>
                  {formatCurrency(line.margin_to_date, currency)}
                </td>
                {canEdit && (
                  <td className="py-2 pl-1 text-right">
                    <div className="flex items-center justify-end gap-1">
                      <button
                        type="button"
                        onClick={() => onEdit(line)}
                        className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                        aria-label={t('cvr.edit_line', { defaultValue: 'Edit cost head' })}
                      >
                        <Pencil size={14} />
                      </button>
                      <button
                        type="button"
                        onClick={() => onDelete(line.id)}
                        className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                        aria-label={t('cvr.delete_line', { defaultValue: 'Delete cost head' })}
                      >
                        <Trash2 size={14} />
                      </button>
                    </div>
                  </td>
                )}
              </tr>
            );
          })}
        </tbody>
        {summary && (
          <tfoot>
            <tr className="border-t-2 border-border-light font-semibold text-content-primary">
              <td className="py-2 pr-3" colSpan={2}>{t('cvr.totals', { defaultValue: 'Totals' })}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(summary.total_cost_to_date, currency)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(summary.total_value_to_date, currency)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(summary.total_forecast_cost, currency)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{formatCurrency(summary.total_forecast_value, currency)}</td>
              <td className={'py-2 pr-3 text-right tabular-nums ' + (toNum(summary.margin_to_date) >= 0 ? 'text-semantic-success' : 'text-semantic-error')}>
                {formatCurrency(summary.margin_to_date, currency)}
              </td>
              {canEdit && <td />}
            </tr>
          </tfoot>
        )}
      </table>
    </div>
  );
}

/* ── Cashflow S-curve ──────────────────────────────────────────────────── */

function CashflowChart({ series }: { series: CashflowSeries }) {
  const { t } = useTranslation();
  const currency = series.currency;
  const data = useMemo(
    () =>
      series.points.map((p) => ({
        period: p.period,
        cumIn: toNum(p.cumulative_cash_in),
        cumOut: toNum(p.cumulative_cash_out),
        cumNet: toNum(p.cumulative_net),
      })),
    [series.points],
  );

  if (data.length === 0) {
    return (
      <EmptyState
        title={t('cvr.no_cashflow', { defaultValue: 'No cashflow points yet' })}
        description={t('cvr.no_cashflow_desc', {
          defaultValue: 'Add monthly cash-in and cash-out to plot the cumulative S-curve.',
        })}
      />
    );
  }

  return (
    <div style={{ width: '100%', height: 320 }} data-testid="cvr-cashflow-chart">
      <ResponsiveContainer width="100%" height="100%">
        <ComposedChart data={data} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
          <defs>
            <linearGradient id="cvrCumIn" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#22c55e" stopOpacity={0.35} />
              <stop offset="95%" stopColor="#22c55e" stopOpacity={0} />
            </linearGradient>
            <linearGradient id="cvrCumOut" x1="0" y1="0" x2="0" y2="1">
              <stop offset="5%" stopColor="#ef4444" stopOpacity={0.3} />
              <stop offset="95%" stopColor="#ef4444" stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light, #e5e7eb)" />
          <XAxis dataKey="period" tick={{ fontSize: 11 }} />
          <YAxis tick={{ fontSize: 11 }} width={72} tickFormatter={(v: number) => formatCurrency(v, currency, undefined, { maximumFractionDigits: 0 })} />
          <Tooltip
            contentStyle={{ fontSize: 12 }}
            formatter={(value: unknown): string => formatCurrency(value as string | number, currency)}
          />
          <Legend wrapperStyle={{ fontSize: 12 }} />
          <Area
            type="monotone"
            dataKey="cumIn"
            name={t('cvr.cumulative_cash_in', { defaultValue: 'Cumulative cash in' })}
            stroke="#22c55e"
            fill="url(#cvrCumIn)"
            strokeWidth={2}
          />
          <Area
            type="monotone"
            dataKey="cumOut"
            name={t('cvr.cumulative_cash_out', { defaultValue: 'Cumulative cash out' })}
            stroke="#ef4444"
            fill="url(#cvrCumOut)"
            strokeWidth={2}
          />
          <Line
            type="monotone"
            dataKey="cumNet"
            name={t('cvr.cumulative_net', { defaultValue: 'Cumulative net' })}
            stroke="#3b82f6"
            strokeWidth={2}
            dot={{ r: 2 }}
          />
        </ComposedChart>
      </ResponsiveContainer>
    </div>
  );
}

/* ── Main page ─────────────────────────────────────────────────────────── */

export function CvrPage() {
  const { t } = useTranslation();
  const { projectId: routeProjectId } = useParams<{ projectId: string }>();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  const projectId = routeProjectId || activeProjectId || projects[0]?.id || '';

  const [selectedReportId, setSelectedReportId] = useState<string>('');
  const [showNewReport, setShowNewReport] = useState(false);
  const [newPeriod, setNewPeriod] = useState(currentPeriod());
  const [newCurrency, setNewCurrency] = useState('');
  // Cost head being edited in the side drawer (null = drawer closed).
  const [editLine, setEditLine] = useState<CvrLine | null>(null);

  // Reports
  const {
    data: reportList,
    isLoading: reportsLoading,
    isError: reportsError,
    error: reportsErr,
    refetch: refetchReports,
  } = useQuery({
    queryKey: ['cvr-reports', projectId],
    queryFn: () => fetchCvrReports(projectId),
    enabled: !!projectId,
  });

  const reports = useMemo<CvrReport[]>(() => reportList?.items ?? [], [reportList]);

  // Keep a valid report selected as the list changes.
  useEffect(() => {
    if (reports.length === 0) {
      if (selectedReportId) setSelectedReportId('');
      return;
    }
    if (!reports.some((r) => r.id === selectedReportId)) {
      setSelectedReportId(reports[0]?.id ?? '');
    }
  }, [reports, selectedReportId]);

  const selectedReport = useMemo(
    () => reports.find((r) => r.id === selectedReportId),
    [reports, selectedReportId],
  );
  const reportCurrency = selectedReport?.currency ?? '';
  const canEdit = selectedReport?.status !== 'final';

  // Selected report detail
  const { data: summary } = useQuery({
    queryKey: ['cvr-summary', selectedReportId],
    queryFn: () => fetchCvrSummary(selectedReportId),
    enabled: !!selectedReportId,
  });
  const { data: lines = [] } = useQuery({
    queryKey: ['cvr-lines', selectedReportId],
    queryFn: () => fetchCvrLines(selectedReportId),
    enabled: !!selectedReportId,
  });

  // Cashflow (project-scoped): the cumulative S-curve series for the chart, plus
  // the raw individual points (each with an id) so they can be edited / removed.
  const { data: cashflow } = useQuery({
    queryKey: ['cvr-cashflow-series', projectId],
    queryFn: () => fetchCashflowSeries(projectId),
    enabled: !!projectId,
  });
  const { data: cashPoints = [] } = useQuery({
    queryKey: ['cvr-cashflow-points', projectId],
    queryFn: () => fetchCashflowPoints(projectId),
    enabled: !!projectId,
  });

  // Payment applications (project-scoped)
  const { data: payappList } = useQuery({
    queryKey: ['cvr-payapps', projectId],
    queryFn: () => fetchPaymentApplications(projectId),
    enabled: !!projectId,
  });
  const payapps = useMemo<PaymentApplication[]>(() => payappList?.items ?? [], [payappList]);

  const invalidateReport = () => {
    qc.invalidateQueries({ queryKey: ['cvr-summary', selectedReportId] });
    qc.invalidateQueries({ queryKey: ['cvr-lines', selectedReportId] });
    qc.invalidateQueries({ queryKey: ['cvr-reports', projectId] });
  };

  // Cashflow edits touch both the aggregated series (the chart) and the raw
  // point list (the editable table), so refresh both together.
  const invalidateCashflow = () => {
    qc.invalidateQueries({ queryKey: ['cvr-cashflow-series', projectId] });
    qc.invalidateQueries({ queryKey: ['cvr-cashflow-points', projectId] });
  };

  // Mutations
  const createReportMut = useMutation({
    mutationFn: () =>
      createCvrReport({ project_id: projectId, period: newPeriod, currency: newCurrency || undefined }),
    onSuccess: (created) => {
      setShowNewReport(false);
      setNewCurrency('');
      setSelectedReportId(created.id);
      qc.invalidateQueries({ queryKey: ['cvr-reports', projectId] });
      addToast({ type: 'success', title: t('cvr.report_created', { defaultValue: 'CVR report created' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.report_create_failed', { defaultValue: 'Could not create report' }), message: getErrorMessage(err) }),
  });

  const finalizeMut = useMutation({
    mutationFn: () => finalizeCvrReport(selectedReportId),
    onSuccess: () => {
      invalidateReport();
      addToast({ type: 'success', title: t('cvr.report_finalized', { defaultValue: 'Report finalized' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.finalize_failed', { defaultValue: 'Could not finalize report' }), message: getErrorMessage(err) }),
  });

  const deleteReportMut = useMutation({
    mutationFn: () => deleteCvrReport(selectedReportId),
    onSuccess: () => {
      setSelectedReportId('');
      qc.invalidateQueries({ queryKey: ['cvr-reports', projectId] });
      addToast({ type: 'success', title: t('cvr.report_deleted', { defaultValue: 'Report deleted' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.delete_failed', { defaultValue: 'Could not delete report' }), message: getErrorMessage(err) }),
  });

  const deleteLineMut = useMutation({
    mutationFn: (lineId: string) => deleteCvrLine(lineId),
    onSuccess: () => invalidateReport(),
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.line_delete_failed', { defaultValue: 'Could not delete cost head' }), message: getErrorMessage(err) }),
  });

  // Client-side CSV of the cost-head table + a totals row. Money is emitted as
  // the raw Decimal-as-string the wire carries (precise, re-importable); we never
  // round it or do float math here. Single-currency per report is guaranteed by
  // the backend, so the currency lives in the file name, not a repeated column.
  const handleExportCsv = useCallback(() => {
    if (lines.length === 0) return;
    const esc = (s: string) => `"${(s ?? '').replace(/"/g, '""')}"`;
    const headers = [
      t('cvr.col_code', { defaultValue: 'Code' }),
      t('cvr.col_description', { defaultValue: 'Description' }),
      t('cvr.col_cost_to_date', { defaultValue: 'Cost to date' }),
      t('cvr.col_value_to_date', { defaultValue: 'Value to date' }),
      t('cvr.col_accruals', { defaultValue: 'Accruals' }),
      t('cvr.col_forecast_cost', { defaultValue: 'Forecast cost' }),
      t('cvr.col_forecast_value', { defaultValue: 'Forecast value' }),
      t('cvr.col_margin', { defaultValue: 'Margin to date' }),
      t('cvr.col_forecast_margin', { defaultValue: 'Forecast margin' }),
      t('cvr.col_flags', { defaultValue: 'Flags' }),
    ];
    const rows = lines.map((l) =>
      [
        esc(l.cost_code),
        esc(l.description),
        l.cost_to_date,
        l.value_to_date,
        l.accruals,
        l.forecast_cost,
        l.forecast_value,
        l.margin_to_date,
        l.forecast_margin,
        esc(l.flags.join('; ')),
      ].join(','),
    );
    if (summary) {
      rows.push(
        [
          esc(t('cvr.totals', { defaultValue: 'Totals' })),
          esc(''),
          summary.total_cost_to_date,
          summary.total_value_to_date,
          summary.total_accruals,
          summary.total_forecast_cost,
          summary.total_forecast_value,
          summary.margin_to_date,
          summary.forecast_margin,
          esc(''),
        ].join(','),
      );
    }
    const csv = [headers.join(','), ...rows].join('\n');
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    const period = selectedReport?.period ?? 'export';
    a.download = reportCurrency ? `cvr_${period}_${reportCurrency}.csv` : `cvr_${period}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }, [lines, summary, selectedReport, reportCurrency, t]);

  // Module Insights - the toggleable visualization panel for this module. The
  // CvrReport list carries no money on its rows, so the panel charts the
  // project's payment applications (the money-bearing register the page also
  // loads): gross, retention and net due, by status and over time. When the
  // project has none the panel draws nothing rather than inventing rows to
  // fill it. Open state and any user-built charts persist per module via
  // useModuleInsights. Declared above the no-project early return below so the
  // hook order stays stable.
  const insights = useModuleInsights('cvr', { defaultOpen: true });
  const { datasets: insightDatasets, builtins: insightBuiltins } = useMemo(
    () => buildCvrInsights(payapps, reportCurrency || payapps[0]?.currency || '', t),
    [payapps, reportCurrency, t],
  );

  if (!projectId) {
    return <RequiresProject>{null}</RequiresProject>;
  }

  return (
    <div className="space-y-6">
      <PageHeader
        srTitle={t('cvr.title', { defaultValue: 'Cost-Value Reconciliation' })}
        subtitle={t('cvr.subtitle', {
          defaultValue:
            'Reconcile cost against value earned per cost head, forecast the final margin, and track project cashflow.',
        })}
        actions={
          <>
            {/* Insights toggle - shows or hides this module's visualization
                panel. Leads the cluster so charts are one obvious click away. */}
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            <Button variant="primary" size="sm" onClick={() => setShowNewReport((v) => !v)}>
              <Plus size={16} className="mr-1.5 shrink-0" />
              {t('cvr.new_report', { defaultValue: 'New CVR month' })}
            </Button>
          </>
        }
      />

      {/* Module Insights panel - toggled by the header button. Placed high so
          its charts are visible the moment the page opens. */}
      <InsightsPanel
        open={insights.open}
        title={t('cvr.insights.title', { defaultValue: 'Payment insights' })}
        datasets={insightDatasets}
        builtins={insightBuiltins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      {/* New report inline form */}
      {showNewReport && (
        <Card padding="md">
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">{t('cvr.period', { defaultValue: 'Period (YYYY-MM)' })}</label>
              <input className={INPUT_CLS} value={newPeriod} onChange={(e) => setNewPeriod(e.target.value)} placeholder="2026-06" />
            </div>
            <div>
              <label className="mb-1 block text-xs font-medium text-content-secondary">{t('cvr.currency', { defaultValue: 'Currency' })}</label>
              <input className={INPUT_CLS} value={newCurrency} onChange={(e) => setNewCurrency(e.target.value.toUpperCase())} placeholder="USD" maxLength={3} />
            </div>
            <Button variant="primary" size="sm" disabled={createReportMut.isPending || !/^\d{4}-\d{2}$/.test(newPeriod)} onClick={() => createReportMut.mutate()}>
              {t('cvr.create', { defaultValue: 'Create' })}
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setShowNewReport(false)}>
              {t('common.cancel', { defaultValue: 'Cancel' })}
            </Button>
          </div>
        </Card>
      )}

      {reportsLoading ? (
        <SkeletonTable rows={4} columns={5} />
      ) : reportsError ? (
        <RecoveryCard error={reportsErr} onRetry={() => refetchReports()} />
      ) : reports.length === 0 ? (
        <EmptyState
          title={t('cvr.no_reports', { defaultValue: 'No CVR reports yet' })}
          description={t('cvr.no_reports_desc', {
            defaultValue: 'Create your first monthly CVR to reconcile cost against value and forecast the final margin.',
          })}
        />
      ) : (
        <>
          {/* Report picker + report-level actions */}
          <Card padding="md">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <label className="text-sm text-content-secondary">{t('cvr.report', { defaultValue: 'Report' })}</label>
                <select
                  className={INPUT_CLS + ' w-auto'}
                  value={selectedReportId}
                  onChange={(e) => setSelectedReportId(e.target.value)}
                  aria-label={t('cvr.select_report', { defaultValue: 'Select CVR report' })}
                >
                  {reports.map((r) => (
                    <option key={r.id} value={r.id}>
                      {r.period}
                      {r.status === 'final' ? ` (${t('cvr.status_final', { defaultValue: 'final' })})` : ''}
                    </option>
                  ))}
                </select>
                {selectedReport && (
                  <Badge variant={selectedReport.status === 'final' ? 'success' : 'warning'}>
                    {selectedReport.status === 'final'
                      ? t('cvr.status_final', { defaultValue: 'Final' })
                      : t('cvr.status_draft', { defaultValue: 'Draft' })}
                  </Badge>
                )}
                {/* The picker lists the newest 50 periods. On a job running
                    longer than that the earliest CVRs are not in the dropdown
                    and there is no other way into them from here. */}
                {reportList && <TruncationNotice page={reportList} />}
              </div>
              <div className="flex items-center gap-2">
                {canEdit && (
                  <Button variant="secondary" size="sm" disabled={finalizeMut.isPending} onClick={() => finalizeMut.mutate()}>
                    <Lock size={14} className="mr-1 shrink-0" />
                    {t('cvr.finalize', { defaultValue: 'Finalize' })}
                  </Button>
                )}
                <button
                  type="button"
                  onClick={() => deleteReportMut.mutate()}
                  disabled={deleteReportMut.isPending}
                  className="rounded p-1.5 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                  aria-label={t('cvr.delete_report', { defaultValue: 'Delete report' })}
                >
                  <Trash2 size={16} />
                </button>
              </div>
            </div>
          </Card>

          {/* Summary strip */}
          {summary && <SummaryStrip summary={summary} currency={reportCurrency} />}

          {/* Advisory warnings */}
          {summary && summary.warnings.length > 0 && (
            <Card padding="sm">
              <div className="flex items-start gap-2 text-sm text-amber-700 dark:text-amber-300">
                <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                <div>
                  <div className="font-medium">{t('cvr.forecast_warnings', { defaultValue: 'Forecast checks' })}</div>
                  <div className="text-content-tertiary">
                    {t('cvr.forecast_warnings_desc', {
                      defaultValue: 'Some lines forecast below what is already spent or earned. Review the flagged cost heads.',
                    })}
                  </div>
                </div>
              </div>
            </Card>
          )}

          {/* CVR table */}
          <Card padding="md">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-content-primary">
                {t('cvr.cost_heads', { defaultValue: 'Cost heads' })}
              </h2>
              <Button
                variant="ghost"
                size="sm"
                onClick={handleExportCsv}
                disabled={lines.length === 0}
              >
                <Download size={14} className="mr-1 shrink-0" />
                {t('cvr.export_csv', { defaultValue: 'Export CSV' })}
              </Button>
            </div>
            <LinesTable
              lines={lines}
              summary={summary}
              currency={reportCurrency}
              canEdit={canEdit}
              onDelete={(id) => deleteLineMut.mutate(id)}
              onEdit={(line) => setEditLine(line)}
            />
            {selectedReportId && (
              <div className="mt-3">
                <AddLineForm reportId={selectedReportId} disabled={!canEdit} onAdded={invalidateReport} />
              </div>
            )}
          </Card>
        </>
      )}

      {/* Cashflow S-curve (project-scoped) */}
      <Card padding="md">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-sm font-semibold text-content-primary">{t('cvr.cashflow', { defaultValue: 'Cashflow forecast' })}</h2>
          {cashflow && (
            <div className="text-xs text-content-tertiary">
              {t('cvr.net_position', { defaultValue: 'Net position' })}:{' '}
              <span className={'font-semibold tabular-nums ' + (toNum(cashflow.net_position) >= 0 ? 'text-semantic-success' : 'text-semantic-error')}>
                {formatCurrency(cashflow.net_position, cashflow.currency)}
              </span>
            </div>
          )}
        </div>
        {cashflow ? <CashflowChart series={cashflow} /> : <SkeletonTable rows={3} columns={3} />}
        <CashflowPointsTable points={cashPoints} onChanged={invalidateCashflow} />
        <CashflowPointForm projectId={projectId} defaultCurrency={reportCurrency} onAdded={invalidateCashflow} />
      </Card>

      {/* Payment applications (project-scoped) */}
      <Card padding="md">
        <h2 className="mb-3 text-sm font-semibold text-content-primary">
          {t('cvr.payment_applications', { defaultValue: 'Payment applications' })}
        </h2>
        <PaymentApplicationsSection
          projectId={projectId}
          applications={payapps}
          defaultCurrency={reportCurrency}
          onChanged={() => qc.invalidateQueries({ queryKey: ['cvr-payapps', projectId] })}
        />
        {/* The roll-up strip inside the section sums the applications it was
            handed, so the reader has to be able to see that the server sent a
            slice of them. Reads the server page, not the rendered array. */}
        {payappList && <TruncationNotice page={payappList} className="mt-2" />}
      </Card>

      {/* Row-level cost head editor (opens from the pencil icon in the table) */}
      {editLine && (
        <EditLineDrawer
          line={editLine}
          currency={reportCurrency}
          onClose={() => setEditLine(null)}
          onSaved={invalidateReport}
        />
      )}
    </div>
  );
}

/* ── Edit cost head (line) drawer ──────────────────────────────────────── */

function EditLineDrawer({
  line,
  currency,
  onClose,
  onSaved,
}: {
  line: CvrLine;
  currency: string;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [form, setForm] = useState({
    cost_code: line.cost_code,
    description: line.description,
    cost_to_date: line.cost_to_date,
    value_to_date: line.value_to_date,
    accruals: line.accruals,
    forecast_cost: line.forecast_cost,
    forecast_value: line.forecast_value,
  });

  const mutation = useMutation({
    mutationFn: () =>
      updateCvrLine(line.id, {
        cost_code: form.cost_code,
        description: form.description,
        cost_to_date: toDecimalPayloadString(form.cost_to_date),
        value_to_date: toDecimalPayloadString(form.value_to_date),
        accruals: toDecimalPayloadString(form.accruals),
        forecast_cost: toDecimalPayloadString(form.forecast_cost),
        forecast_value: toDecimalPayloadString(form.forecast_value),
      }),
    onSuccess: () => {
      onSaved();
      onClose();
      addToast({ type: 'success', title: t('cvr.line_updated', { defaultValue: 'Cost head updated' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.line_update_failed', { defaultValue: 'Could not update cost head' }), message: getErrorMessage(err) }),
  });

  const set = (key: keyof typeof form, value: string) => setForm((prev) => ({ ...prev, [key]: value }));

  // Live margin preview so the estimator sees the effect before saving. This is
  // a display-only coercion via toNum (never wire arithmetic on the raw string).
  const marginPreview = toNum(form.value_to_date) - toNum(form.cost_to_date);
  const marginPositive = marginPreview >= 0;

  const field = (label: string, key: keyof typeof form, decimal = false) => (
    <div>
      <label className="mb-1 block text-xs font-medium text-content-secondary">{label}</label>
      <input
        className={INPUT_CLS}
        inputMode={decimal ? 'decimal' : undefined}
        value={form[key]}
        onChange={(e) => set(key, e.target.value)}
      />
    </div>
  );

  return (
    <SideDrawer
      open
      onClose={onClose}
      busy={mutation.isPending}
      backdropCloses={false}
      title={t('cvr.edit_line', { defaultValue: 'Edit cost head' })}
      subtitle={line.cost_code || line.description || undefined}
    >
      <div className="space-y-4 p-5">
        {field(t('cvr.col_code', { defaultValue: 'Code' }), 'cost_code')}
        {field(t('cvr.col_description', { defaultValue: 'Description' }), 'description')}
        <div className="grid grid-cols-2 gap-3">
          {field(t('cvr.col_cost_to_date', { defaultValue: 'Cost to date' }), 'cost_to_date', true)}
          {field(t('cvr.col_value_to_date', { defaultValue: 'Value to date' }), 'value_to_date', true)}
          {field(t('cvr.col_accruals', { defaultValue: 'Accruals' }), 'accruals', true)}
          {field(t('cvr.col_forecast_cost', { defaultValue: 'Forecast cost' }), 'forecast_cost', true)}
          {field(t('cvr.col_forecast_value', { defaultValue: 'Forecast value' }), 'forecast_value', true)}
        </div>
        <div className="flex items-center justify-between rounded-lg bg-surface-secondary/50 px-3 py-2 text-sm">
          <span className="text-content-secondary">{t('cvr.margin_to_date', { defaultValue: 'Margin to date' })}</span>
          <span className={'font-semibold tabular-nums ' + (marginPositive ? 'text-semantic-success' : 'text-semantic-error')}>
            {formatCurrency(marginPreview, currency)}
          </span>
        </div>
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" size="sm" disabled={mutation.isPending} onClick={onClose}>
            {t('common.cancel', { defaultValue: 'Cancel' })}
          </Button>
          <Button variant="primary" size="sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
            {t('common.save', { defaultValue: 'Save' })}
          </Button>
        </div>
      </div>
    </SideDrawer>
  );
}

/* ── Cashflow point add form ───────────────────────────────────────────── */

function CashflowPointForm({
  projectId,
  defaultCurrency,
  onAdded,
}: {
  projectId: string;
  defaultCurrency: string;
  onAdded: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [period, setPeriod] = useState(currentPeriod());
  const [cashIn, setCashIn] = useState('');
  const [cashOut, setCashOut] = useState('');

  const mutation = useMutation({
    mutationFn: () =>
      createCashflowPoint({
        project_id: projectId,
        period,
        cash_in: toDecimalPayloadString(cashIn),
        cash_out: toDecimalPayloadString(cashOut),
        currency: defaultCurrency || undefined,
      }),
    onSuccess: () => {
      setCashIn('');
      setCashOut('');
      onAdded();
      addToast({ type: 'success', title: t('cvr.cash_point_added', { defaultValue: 'Cashflow point added' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.cash_point_failed', { defaultValue: 'Could not add cashflow point' }), message: getErrorMessage(err) }),
  });

  return (
    <div className="mt-3 grid grid-cols-2 items-end gap-2 rounded-lg border border-dashed border-border-light p-3 sm:grid-cols-4">
      <input className={INPUT_CLS} placeholder={t('cvr.period', { defaultValue: 'Period (YYYY-MM)' })} value={period} onChange={(e) => setPeriod(e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.cash_in', { defaultValue: 'Cash in' })} value={cashIn} onChange={(e) => setCashIn(e.target.value)} />
      <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.cash_out', { defaultValue: 'Cash out' })} value={cashOut} onChange={(e) => setCashOut(e.target.value)} />
      <Button variant="secondary" size="sm" disabled={mutation.isPending || !/^\d{4}-\d{2}$/.test(period)} onClick={() => mutation.mutate()}>
        <Plus size={14} className="mr-1 shrink-0" />
        {t('cvr.add_point', { defaultValue: 'Add point' })}
      </Button>
    </div>
  );
}

/* ── Recorded cashflow points (inline edit + delete) ───────────────────── */

function CashflowPointsTable({
  points,
  onChanged,
}: {
  points: CashflowPoint[];
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [editId, setEditId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ cash_in: string; cash_out: string }>({ cash_in: '', cash_out: '' });
  const [deleteTarget, setDeleteTarget] = useState<CashflowPoint | null>(null);

  const updateMut = useMutation({
    mutationFn: (vars: { id: string; cash_in: string; cash_out: string }) =>
      updateCashflowPoint(vars.id, {
        cash_in: toDecimalPayloadString(vars.cash_in),
        cash_out: toDecimalPayloadString(vars.cash_out),
      }),
    onSuccess: () => {
      setEditId(null);
      onChanged();
      addToast({ type: 'success', title: t('cvr.cash_point_updated', { defaultValue: 'Cashflow point updated' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.cash_point_update_failed', { defaultValue: 'Could not update cashflow point' }), message: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteCashflowPoint(id),
    onSuccess: () => {
      setDeleteTarget(null);
      onChanged();
      addToast({ type: 'success', title: t('cvr.cash_point_deleted', { defaultValue: 'Cashflow point deleted' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.cash_point_delete_failed', { defaultValue: 'Could not delete cashflow point' }), message: getErrorMessage(err) }),
  });

  if (points.length === 0) return null;

  const startEdit = (p: CashflowPoint) => {
    setEditId(p.id);
    setDraft({ cash_in: p.cash_in, cash_out: p.cash_out });
  };

  return (
    <div className="mt-4">
      <div className="mb-2 text-2xs font-medium uppercase tracking-wide text-content-tertiary">
        {t('cvr.cashflow_points', { defaultValue: 'Recorded points' })}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[520px] text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
              <th className="py-2 pr-3 font-medium">{t('cvr.col_period', { defaultValue: 'Period' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('cvr.cash_in', { defaultValue: 'Cash in' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('cvr.cash_out', { defaultValue: 'Cash out' })}</th>
              <th className="py-2 pr-3 text-right font-medium">{t('cvr.point_net', { defaultValue: 'Net' })}</th>
              <th className="py-2 pl-1" />
            </tr>
          </thead>
          <tbody>
            {points.map((p) => {
              const editing = editId === p.id;
              const netPreview = editing
                ? toNum(draft.cash_in) - toNum(draft.cash_out)
                : toNum(p.net);
              return (
                <tr key={p.id} className="border-b border-border-light/60">
                  <td className="py-2 pr-3 text-content-secondary">{p.period}</td>
                  {editing ? (
                    <>
                      <td className="py-1 pr-3">
                        <input
                          className={INPUT_CLS + ' text-right'}
                          inputMode="decimal"
                          value={draft.cash_in}
                          onChange={(e) => setDraft((d) => ({ ...d, cash_in: e.target.value }))}
                          aria-label={t('cvr.cash_in', { defaultValue: 'Cash in' })}
                        />
                      </td>
                      <td className="py-1 pr-3">
                        <input
                          className={INPUT_CLS + ' text-right'}
                          inputMode="decimal"
                          value={draft.cash_out}
                          onChange={(e) => setDraft((d) => ({ ...d, cash_out: e.target.value }))}
                          aria-label={t('cvr.cash_out', { defaultValue: 'Cash out' })}
                        />
                      </td>
                    </>
                  ) : (
                    <>
                      <td className="py-2 pr-3 text-right tabular-nums text-semantic-success">{formatCurrency(p.cash_in, p.currency)}</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-semantic-error">{formatCurrency(p.cash_out, p.currency)}</td>
                    </>
                  )}
                  <td className={'py-2 pr-3 text-right font-semibold tabular-nums ' + (netPreview >= 0 ? 'text-content-primary' : 'text-semantic-error')}>
                    {formatCurrency(netPreview, p.currency)}
                  </td>
                  <td className="py-2 pl-1 text-right">
                    {editing ? (
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="primary"
                          size="sm"
                          disabled={updateMut.isPending}
                          onClick={() => updateMut.mutate({ id: p.id, cash_in: draft.cash_in, cash_out: draft.cash_out })}
                        >
                          {t('common.save', { defaultValue: 'Save' })}
                        </Button>
                        <Button variant="ghost" size="sm" disabled={updateMut.isPending} onClick={() => setEditId(null)}>
                          {t('common.cancel', { defaultValue: 'Cancel' })}
                        </Button>
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-1">
                        <button
                          type="button"
                          onClick={() => startEdit(p)}
                          className="rounded p-1 text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
                          aria-label={t('cvr.edit_point', { defaultValue: 'Edit cashflow point' })}
                        >
                          <Pencil size={14} />
                        </button>
                        <button
                          type="button"
                          onClick={() => setDeleteTarget(p)}
                          className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                          aria-label={t('cvr.delete_point', { defaultValue: 'Delete cashflow point' })}
                        >
                          <Trash2 size={14} />
                        </button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        title={t('cvr.delete_point_title', { defaultValue: 'Delete cashflow point' })}
        message={t('cvr.delete_point_msg', {
          defaultValue: 'This removes the recorded cash in and cash out for this period from the S-curve.',
        })}
        loading={deleteMut.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteMut.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
}

/* ── Payment applications ──────────────────────────────────────────────── */

function PaymentApplicationsSection({
  projectId,
  applications,
  defaultCurrency,
  onChanged,
}: {
  projectId: string;
  applications: PaymentApplication[];
  defaultCurrency: string;
  onChanged: () => void;
}) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [period, setPeriod] = useState(currentPeriod());
  const [number, setNumber] = useState('');
  const [gross, setGross] = useState('');
  const [retention, setRetention] = useState('');

  const [deleteTarget, setDeleteTarget] = useState<PaymentApplication | null>(null);

  const mutation = useMutation({
    mutationFn: () =>
      createPaymentApplication({
        project_id: projectId,
        period,
        application_number: number || undefined,
        gross_value: toDecimalPayloadString(gross),
        retention: toDecimalPayloadString(retention),
        currency: defaultCurrency || undefined,
      }),
    onSuccess: () => {
      setNumber('');
      setGross('');
      setRetention('');
      onChanged();
      addToast({ type: 'success', title: t('cvr.payapp_added', { defaultValue: 'Payment application added' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.payapp_failed', { defaultValue: 'Could not add payment application' }), message: getErrorMessage(err) }),
  });

  // Advance / correct an application's status along draft -> submitted ->
  // certified -> paid. net_value is recomputed server-side, nothing else changes.
  const statusMut = useMutation({
    mutationFn: (vars: { id: string; status: PaymentApplicationStatus }) =>
      updatePaymentApplication(vars.id, { status: vars.status }),
    onSuccess: () => {
      onChanged();
      addToast({ type: 'success', title: t('cvr.payapp_status_updated', { defaultValue: 'Status updated' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.payapp_update_failed', { defaultValue: 'Could not update application' }), message: getErrorMessage(err) }),
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deletePaymentApplication(id),
    onSuccess: () => {
      setDeleteTarget(null);
      onChanged();
      addToast({ type: 'success', title: t('cvr.payapp_deleted', { defaultValue: 'Payment application deleted' }) });
    },
    onError: (err) =>
      addToast({ type: 'error', title: t('cvr.payapp_delete_failed', { defaultValue: 'Could not delete application' }), message: getErrorMessage(err) }),
  });

  return (
    <div className="space-y-3">
      {applications.length > 0 && <PayappRollup applications={applications} />}

      {applications.length === 0 ? (
        <EmptyState
          title={t('cvr.no_payapps', { defaultValue: 'No payment applications yet' })}
          description={t('cvr.no_payapps_desc', {
            defaultValue: 'Log interim applications for payment to track gross, retention and the net due.',
          })}
        />
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full min-w-[620px] text-sm">
            <thead>
              <tr className="border-b border-border-light text-left text-2xs uppercase tracking-wide text-content-tertiary">
                <th className="py-2 pr-3 font-medium">{t('cvr.col_application', { defaultValue: 'Application' })}</th>
                <th className="py-2 pr-3 font-medium">{t('cvr.col_period', { defaultValue: 'Period' })}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_gross', { defaultValue: 'Gross' })}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_retention', { defaultValue: 'Retention' })}</th>
                <th className="py-2 pr-3 text-right font-medium">{t('cvr.col_net', { defaultValue: 'Net due' })}</th>
                <th className="py-2 pr-3 font-medium">{t('cvr.col_status', { defaultValue: 'Status' })}</th>
                <th className="py-2 pl-1" />
              </tr>
            </thead>
            <tbody>
              {applications.map((app) => (
                <tr key={app.id} className="border-b border-border-light/60">
                  <td className="py-2 pr-3 font-medium text-content-primary">{app.application_number || '-'}</td>
                  <td className="py-2 pr-3 text-content-secondary">{app.period}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-content-secondary">{formatCurrency(app.gross_value, app.currency)}</td>
                  <td className="py-2 pr-3 text-right tabular-nums text-content-tertiary">{formatCurrency(app.retention, app.currency)}</td>
                  <td className="py-2 pr-3 text-right font-semibold tabular-nums text-content-primary">{formatCurrency(app.net_value, app.currency)}</td>
                  <td className="py-2 pr-3">
                    <select
                      value={app.status}
                      disabled={statusMut.isPending}
                      onChange={(e) => statusMut.mutate({ id: app.id, status: e.target.value as PaymentApplicationStatus })}
                      aria-label={t('cvr.payapp_status_label', { defaultValue: 'Payment application status' })}
                      className={
                        'cursor-pointer rounded-full border-0 px-2 py-1 text-2xs font-semibold ' +
                        'focus:outline-none focus:ring-2 focus:ring-blue-200 disabled:opacity-50 ' +
                        PAYAPP_STATUS_TONE[app.status]
                      }
                    >
                      {PAYAPP_STATUSES.map((s) => (
                        <option key={s} value={s}>
                          {t(`cvr.payapp_status_${s}`, { defaultValue: s })}
                        </option>
                      ))}
                    </select>
                  </td>
                  <td className="py-2 pl-1 text-right">
                    <button
                      type="button"
                      onClick={() => setDeleteTarget(app)}
                      className="rounded p-1 text-content-tertiary hover:bg-red-50 hover:text-semantic-error dark:hover:bg-red-900/20"
                      aria-label={t('cvr.delete_payapp', { defaultValue: 'Delete payment application' })}
                    >
                      <Trash2 size={14} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="grid grid-cols-2 items-end gap-2 rounded-lg border border-dashed border-border-light p-3 sm:grid-cols-5">
        <input className={INPUT_CLS} placeholder={t('cvr.col_application', { defaultValue: 'IPA-001' })} value={number} onChange={(e) => setNumber(e.target.value)} />
        <input className={INPUT_CLS} placeholder={t('cvr.period', { defaultValue: 'Period (YYYY-MM)' })} value={period} onChange={(e) => setPeriod(e.target.value)} />
        <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_gross', { defaultValue: 'Gross' })} value={gross} onChange={(e) => setGross(e.target.value)} />
        <input className={INPUT_CLS} inputMode="decimal" placeholder={t('cvr.col_retention', { defaultValue: 'Retention' })} value={retention} onChange={(e) => setRetention(e.target.value)} />
        <Button variant="secondary" size="sm" disabled={mutation.isPending || !/^\d{4}-\d{2}$/.test(period)} onClick={() => mutation.mutate()}>
          <Plus size={14} className="mr-1 shrink-0" />
          {t('cvr.add', { defaultValue: 'Add' })}
        </Button>
      </div>

      <ConfirmDialog
        open={!!deleteTarget}
        title={t('cvr.delete_payapp_title', { defaultValue: 'Delete payment application' })}
        message={t('cvr.delete_payapp_msg', {
          defaultValue: 'This removes the interim application and its figures. This cannot be undone.',
        })}
        loading={deleteMut.isPending}
        onCancel={() => setDeleteTarget(null)}
        onConfirm={() => {
          if (deleteTarget) deleteMut.mutate(deleteTarget.id);
        }}
      />
    </div>
  );
}

/* ── Payment applications roll-up strip ────────────────────────────────── */

/** One small figure tile inside the payapp roll-up (matches SummaryStrip). */
function RollupTile({
  label,
  value,
  sub,
  emphasize,
}: {
  label: string;
  value: string;
  sub?: string;
  emphasize?: boolean;
}) {
  return (
    <Card padding="sm">
      <div className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</div>
      <div className={'mt-1 text-base font-bold tabular-nums ' + (emphasize ? 'text-content-primary' : 'text-content-secondary')}>
        {value}
      </div>
      {sub && <div className="mt-0.5 text-2xs text-content-tertiary">{sub}</div>}
    </Card>
  );
}

/**
 * Gross / retention / net-due and net-vs-certified totals from the already
 * loaded applications. Grouped by currency so figures in different currencies
 * are never blended into one total; each toNum coercion is display-only.
 * "Certified" counts net due once an application reaches certified or paid.
 */
function PayappRollup({ applications }: { applications: PaymentApplication[] }) {
  const { t } = useTranslation();

  const groups = useMemo(() => {
    const map = new Map<
      string,
      { currency: string; gross: number; retention: number; net: number; certified: number }
    >();
    for (const a of applications) {
      const cur = (a.currency || '').toUpperCase();
      const g = map.get(cur) ?? { currency: cur, gross: 0, retention: 0, net: 0, certified: 0 };
      g.gross += toNum(a.gross_value);
      g.retention += toNum(a.retention);
      g.net += toNum(a.net_value);
      if (a.status === 'certified' || a.status === 'paid') g.certified += toNum(a.net_value);
      map.set(cur, g);
    }
    return Array.from(map.values());
  }, [applications]);

  if (groups.length === 0) return null;

  return (
    <div className="space-y-3">
      {groups.map((g) => {
        const awaiting = g.net - g.certified;
        return (
          <div key={g.currency || 'na'} className="space-y-2">
            {groups.length > 1 && (
              <div className="text-2xs font-semibold uppercase tracking-wide text-content-tertiary">
                {g.currency || t('cvr.currency', { defaultValue: 'Currency' })}
              </div>
            )}
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
              <RollupTile label={t('cvr.rollup_gross', { defaultValue: 'Gross applied' })} value={formatCurrency(g.gross, g.currency)} />
              <RollupTile label={t('cvr.rollup_retention', { defaultValue: 'Retention held' })} value={formatCurrency(g.retention, g.currency)} />
              <RollupTile label={t('cvr.rollup_net_due', { defaultValue: 'Net due' })} value={formatCurrency(g.net, g.currency)} emphasize />
              <RollupTile
                label={t('cvr.rollup_certified', { defaultValue: 'Certified' })}
                value={formatCurrency(g.certified, g.currency)}
                sub={`${t('cvr.rollup_awaiting', { defaultValue: 'Awaiting' })}: ${formatCurrency(awaiting, g.currency)}`}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}
