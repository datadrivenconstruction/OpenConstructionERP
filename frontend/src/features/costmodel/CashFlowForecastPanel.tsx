// DDC-CWICR-OE: DataDrivenConstruction​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
// Project cash-flow forecast: monthly expected / actual in- and outflow bars,
// the cumulative position line, the peak funding requirement and the findings
// the forecast rules raise. Currencies are never summed together: with more
// than one the user picks which one to look at.
//
// Money arrives as Decimal-encoded strings. They are only coerced to numbers
// for chart geometry; every printed amount goes through formatCurrency.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { AlertTriangle, Download, Inbox, TrendingDown } from 'lucide-react';

import { Badge, Button, Card, EmptyState, Skeleton } from '@/shared/ui';
import { formatCurrency } from '@/shared/lib/money';
import { getErrorMessage } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  cashflowForecastApi,
  type CurrencyForecast,
  type ForecastFinding,
  type ForecastMonth,
} from './cashflowForecastApi';

export interface CashFlowForecastPanelProps {
  projectId: string;
}

const isNegative = (v: string | null | undefined): boolean =>
  typeof v === 'string' && v.trim().startsWith('-');

/** Source key -> label; unknown keys fall back to the raw key. */
function useSourceLabels(): Record<string, string> {
  const { t } = useTranslation();
  return useMemo(
    () => ({
      billing: t('costmodel.cf_src_billing', { defaultValue: 'Client billing' }),
      milestone: t('costmodel.cf_src_milestone', { defaultValue: 'Payment milestones' }),
      claim: t('costmodel.cf_src_claim', { defaultValue: 'Claims' }),
      receivable_invoice: t('costmodel.cf_src_receivable_invoice', { defaultValue: 'Receivable invoices' }),
      retention_release: t('costmodel.cf_src_retention_release', { defaultValue: 'Retention release' }),
      payable_invoice: t('costmodel.cf_src_payable_invoice', { defaultValue: 'Payable invoices' }),
      purchase_order: t('costmodel.cf_src_purchase_order', { defaultValue: 'Purchase orders' }),
      subcontract: t('costmodel.cf_src_subcontract', { defaultValue: 'Subcontracts' }),
      subcontract_application: t('costmodel.cf_src_subcontract_application', { defaultValue: 'Subcontract applications' }),
      subcontract_retention: t('costmodel.cf_src_subcontract_retention', { defaultValue: 'Subcontract retention' }),
      payroll: t('costmodel.cf_src_payroll', { defaultValue: 'Payroll' }),
      guarantee_fee: t('costmodel.cf_src_guarantee_fee', { defaultValue: 'Guarantee fees' }),
      plan: t('costmodel.cf_src_plan', { defaultValue: 'Budget plan' }),
    }),
    [t],
  );
}

export function CashFlowForecastPanel({ projectId }: CashFlowForecastPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const sourceLabels = useSourceLabels();

  const [delay, setDelay] = useState('0');
  const [overrun, setOverrun] = useState('0');
  const [picked, setPicked] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);

  const params = { receiptDelayDays: delay, costOverrunPct: overrun };

  const { data, isLoading, error } = useQuery({
    queryKey: ['costmodel', 'cashflow-forecast', projectId, delay, overrun],
    queryFn: () => cashflowForecastApi.getProjectForecast(projectId, params),
    retry: false,
  });

  const currencies = data?.currencies ?? [];
  const current: CurrencyForecast | undefined =
    currencies.find((c) => c.currency === picked) ?? currencies[0];

  const onExport = async () => {
    setExporting(true);
    try {
      await cashflowForecastApi.exportProject(projectId, params, 'cashflow-forecast.xlsx');
    } catch (err) {
      addToast({
        type: 'error',
        title: t('costmodel.cf_export_failed', { defaultValue: 'Could not create the Excel file' }),
        message: getErrorMessage(err),
      });
    } finally {
      setExporting(false);
    }
  };

  const chartData = useMemo(
    () =>
      (current?.months ?? []).map((m) => ({
        period: m.period,
        in: Number(m.is_past ? m.actual_in : m.expected_in),
        out: Number(m.is_past ? m.actual_out : m.expected_out),
        cumulative: Number(m.cumulative),
      })),
    [current],
  );

  const inputClass =
    'mt-1 block w-32 rounded-md border border-border bg-surface-primary px-2 py-1 text-sm';

  return (
    <Card>
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('costmodel.cf_title', { defaultValue: 'Cash-flow forecast' })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('costmodel.cf_subtitle', {
              defaultValue: 'Expected receipts and payments by month, and the funding the project needs.',
            })}
          </p>
        </div>
        <Button
          variant="secondary"
          size="sm"
          icon={<Download size={14} />}
          loading={exporting}
          disabled={!data?.has_inputs}
          onClick={onExport}
        >
          {t('costmodel.cf_export', { defaultValue: 'Export to Excel' })}
        </Button>
      </div>

      <div className="mt-3 flex flex-wrap items-end gap-3">
        <label className="text-xs text-content-secondary">
          {t('costmodel.cf_delay', { defaultValue: 'Receipt delay (days)' })}
          <input
            type="number"
            min={0}
            step={1}
            value={delay}
            onChange={(e) => setDelay(e.target.value)}
            aria-label={t('costmodel.cf_delay', { defaultValue: 'Receipt delay (days)' })}
            className={inputClass}
          />
        </label>
        <label className="text-xs text-content-secondary">
          {t('costmodel.cf_overrun', { defaultValue: 'Cost overrun (%)' })}
          <input
            type="number"
            min={0}
            step="any"
            value={overrun}
            onChange={(e) => setOverrun(e.target.value)}
            aria-label={t('costmodel.cf_overrun', { defaultValue: 'Cost overrun (%)' })}
            className={inputClass}
          />
        </label>
        {currencies.length > 1 && (
          <label className="text-xs text-content-secondary">
            {t('costmodel.cf_currency', { defaultValue: 'Currency' })}
            <select
              value={current?.currency ?? ''}
              onChange={(e) => setPicked(e.target.value)}
              aria-label={t('costmodel.cf_currency', { defaultValue: 'Currency' })}
              className={inputClass}
            >
              {currencies.map((c) => (
                <option key={c.currency} value={c.currency}>
                  {c.currency}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>

      {isLoading ? (
        <div className="mt-4 space-y-3">
          <Skeleton height={72} className="w-full" rounded="lg" />
          <Skeleton height={240} className="w-full" rounded="lg" />
        </div>
      ) : error ? (
        <div className="mt-4 flex items-start gap-3 rounded-lg border border-semantic-error/30 bg-semantic-error-bg/30 p-3">
          <AlertTriangle size={18} className="mt-0.5 shrink-0 text-semantic-error" />
          <div>
            <p className="text-sm font-medium text-content-primary">
              {t('costmodel.cf_load_failed', { defaultValue: 'Could not load the cash-flow forecast' })}
            </p>
            <p className="text-xs text-content-secondary">{getErrorMessage(error)}</p>
          </div>
        </div>
      ) : !data || !data.has_inputs || !current ? (
        <EmptyState
          icon={<Inbox size={24} strokeWidth={1.5} />}
          title={t('costmodel.cf_empty_title', { defaultValue: 'No cash-flow inputs yet' })}
          description={t('costmodel.cf_empty_desc', {
            defaultValue:
              'Add payment milestones, invoices, purchase orders or contracts with due dates to see the forecast.',
          })}
        />
      ) : (
        <div className="mt-4 space-y-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            <div
              data-testid="cf-peak-funding"
              className={`rounded-lg border p-3 ${
                current.peak_funding
                  ? 'border-semantic-error/40 bg-semantic-error-bg/30'
                  : 'border-border-light bg-surface-secondary'
              }`}
            >
              <div className="flex items-center gap-1.5 text-xs text-content-secondary">
                <TrendingDown size={14} />
                {t('costmodel.cf_peak_funding', { defaultValue: 'Peak funding requirement' })}
              </div>
              {current.peak_funding ? (
                <>
                  <div className="mt-1 text-xl font-semibold tabular-nums text-semantic-error">
                    {formatCurrency(current.peak_funding.amount, current.currency)}
                  </div>
                  <div className="text-xs text-content-tertiary">
                    {t('costmodel.cf_peak_month', {
                      defaultValue: 'Lowest point in {{period}}',
                      period: current.peak_funding.period,
                    })}
                  </div>
                </>
              ) : (
                <div className="mt-1 text-sm text-content-secondary">
                  {t('costmodel.cf_no_funding', { defaultValue: 'No external funding needed' })}
                </div>
              )}
            </div>
            <div className="rounded-lg border border-border-light bg-surface-secondary p-3">
              <div className="text-xs text-content-secondary">
                {t('costmodel.cf_closing', { defaultValue: 'Closing position' })}
              </div>
              <div
                className={`mt-1 text-xl font-semibold tabular-nums ${
                  isNegative(current.closing_position) ? 'text-semantic-error' : 'text-content-primary'
                }`}
              >
                {formatCurrency(current.closing_position, current.currency)}
              </div>
            </div>
          </div>

          <div className="h-64 w-full" data-testid="cf-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={chartData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="period" fontSize={11} />
                <YAxis fontSize={11} width={70} />
                <Tooltip />
                <Legend />
                <Bar dataKey="in" name={t('costmodel.cf_inflow', { defaultValue: 'Inflow' })} fill="#16a34a" />
                <Bar dataKey="out" name={t('costmodel.cf_outflow', { defaultValue: 'Outflow' })} fill="#dc2626" />
                <Line
                  type="monotone"
                  dataKey="cumulative"
                  name={t('costmodel.cf_cumulative', { defaultValue: 'Cumulative position' })}
                  stroke="#2563eb"
                  strokeWidth={2}
                  dot={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>

          <MonthsTable months={current.months} currency={current.currency} />

          <div>
            <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
              {t('costmodel.cf_sources', { defaultValue: 'Sources' })}
            </h4>
            <ul className="divide-y divide-border-light rounded-lg border border-border-light text-sm">
              {current.sources.map((s) => (
                <li key={`${s.source}-${s.direction}`} className="flex items-center justify-between px-3 py-1.5">
                  <span className="text-content-secondary">
                    {sourceLabels[s.source] ?? s.source}{' '}
                    <span className="text-xs text-content-tertiary">
                      {s.direction === 'in'
                        ? t('costmodel.cf_dir_in', { defaultValue: 'in' })
                        : t('costmodel.cf_dir_out', { defaultValue: 'out' })}
                    </span>
                  </span>
                  <span className="tabular-nums">{formatCurrency(s.amount, current.currency)}</span>
                </li>
              ))}
            </ul>
          </div>

          <FindingsList findings={data.findings} />
        </div>
      )}
    </Card>
  );
}

function MonthsTable({ months, currency }: { months: ForecastMonth[]; currency: string }) {
  const { t } = useTranslation();
  const fmt = (v: string) => formatCurrency(v, currency);
  const th = 'px-2 py-1.5 text-right font-medium';
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead className="bg-surface-secondary text-content-secondary">
          <tr>
            <th className="px-2 py-1.5 text-left font-medium">{t('costmodel.cf_col_month', { defaultValue: 'Month' })}</th>
            <th className={th}>{t('costmodel.cf_col_planned_in', { defaultValue: 'Planned in' })}</th>
            <th className={th}>{t('costmodel.cf_col_actual_in', { defaultValue: 'Actual / expected in' })}</th>
            <th className={th}>{t('costmodel.cf_col_var_in', { defaultValue: 'Variance in' })}</th>
            <th className={th}>{t('costmodel.cf_col_planned_out', { defaultValue: 'Planned out' })}</th>
            <th className={th}>{t('costmodel.cf_col_actual_out', { defaultValue: 'Actual / expected out' })}</th>
            <th className={th}>{t('costmodel.cf_col_var_out', { defaultValue: 'Variance out' })}</th>
            <th className={th}>{t('costmodel.cf_col_net', { defaultValue: 'Net' })}</th>
            <th className={th}>{t('costmodel.cf_col_cumulative', { defaultValue: 'Cumulative' })}</th>
          </tr>
        </thead>
        <tbody>
          {months.map((m) => (
            <tr key={m.period} className="border-t border-border-light tabular-nums">
              <td className="px-2 py-1.5 text-left">{m.period}</td>
              <td className="px-2 py-1.5 text-right">{fmt(m.planned_in)}</td>
              <td className="px-2 py-1.5 text-right">{fmt(m.is_past ? m.actual_in : m.expected_in)}</td>
              <td className="px-2 py-1.5 text-right">{m.is_past ? fmt(m.variance_in) : ''}</td>
              <td className="px-2 py-1.5 text-right">{fmt(m.planned_out)}</td>
              <td className="px-2 py-1.5 text-right">{fmt(m.is_past ? m.actual_out : m.expected_out)}</td>
              <td className="px-2 py-1.5 text-right">{m.is_past ? fmt(m.variance_out) : ''}</td>
              <td className="px-2 py-1.5 text-right">{fmt(m.net)}</td>
              <td className={`px-2 py-1.5 text-right ${isNegative(m.cumulative) ? 'text-semantic-error' : ''}`}>
                {fmt(m.cumulative)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function FindingsList({ findings }: { findings: ForecastFinding[] }) {
  const { t } = useTranslation();
  if (findings.length === 0) return null;
  const variant = { error: 'error', warning: 'warning', info: 'neutral' } as const;
  const severityLabel = {
    error: t('costmodel.cf_sev_error', { defaultValue: 'Error' }),
    warning: t('costmodel.cf_sev_warning', { defaultValue: 'Warning' }),
    info: t('costmodel.cf_sev_info', { defaultValue: 'Info' }),
  };
  return (
    <div>
      <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
        {t('costmodel.cf_findings', { defaultValue: 'Findings' })}
      </h4>
      <ul className="space-y-2">
        {findings.map((f, i) => (
          <li key={`${f.rule_id}-${i}`} className="rounded-lg border border-border-light p-2 text-sm">
            <div className="flex items-center gap-2">
              <Badge variant={variant[f.severity]} size="sm">
                {severityLabel[f.severity]}
              </Badge>
              <span className="text-content-primary">{f.message}</span>
            </div>
            {f.suggestion && <p className="mt-1 text-xs text-content-tertiary">{f.suggestion}</p>}
          </li>
        ))}
      </ul>
    </div>
  );
}

export default CashFlowForecastPanel;
