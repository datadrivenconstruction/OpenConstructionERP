import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Dices, Loader2, Inbox } from 'lucide-react';
import {
  boqApi,
  type CostRiskHistogramBin,
  type CostRiskDriver,
} from './api';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function createCRFormatter(locale: string) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

function fmtCurrency(n: number, fmt: Intl.NumberFormat): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${n < 0 ? '-' : ''}${(n / 1_000_000).toFixed(2)}M`;
  }
  if (abs >= 10_000) {
    return `${n < 0 ? '-' : ''}${fmt.format(Math.round(n / 1_000))}K`;
  }
  return fmt.format(n);
}

/* ── Percentile Card ─────────────────────────────────────────────────── */

function PercentileCard({
  label,
  value,
  fmt,
  variant = 'default',
}: {
  label: string;
  value: number;
  fmt: Intl.NumberFormat;
  variant?: 'default' | 'green' | 'orange';
}) {
  const borderClass =
    variant === 'green'
      ? 'border-emerald-400/50 bg-emerald-50/50 dark:bg-emerald-950/20'
      : variant === 'orange'
        ? 'border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20'
        : 'border-border-light bg-surface-secondary/30';

  const valueClass =
    variant === 'green'
      ? 'text-emerald-700 dark:text-emerald-400'
      : variant === 'orange'
        ? 'text-amber-700 dark:text-amber-400'
        : 'text-content-primary';

  return (
    <div className={`rounded-lg border px-3 py-2.5 ${borderClass}`}>
      <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
        {label}
      </div>
      <div className={`text-sm font-bold tabular-nums mt-0.5 ${valueClass}`}>
        {fmtCurrency(value, fmt)}
      </div>
    </div>
  );
}

/* ── Contingency Card ────────────────────────────────────────────────── */

function ContingencyCard({
  contingency,
  contingencyPct,
  recommendedBudget,
  fmt,
  t,
}: {
  contingency: number;
  contingencyPct: number;
  recommendedBudget: number;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  return (
    <div className="rounded-lg border border-blue-400/50 bg-blue-50/50 dark:bg-blue-950/20 px-4 py-3">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('boq.cost_risk_contingency', { defaultValue: 'Contingency (P80 - P50)' })}
          </div>
          <div className="text-lg font-bold text-blue-700 dark:text-blue-400 tabular-nums mt-0.5">
            {fmtCurrency(contingency, fmt)}{' '}
            <span className="text-sm font-medium text-blue-600/70 dark:text-blue-400/70">
              ({contingencyPct}%)
            </span>
          </div>
        </div>
        <div className="text-right">
          <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('boq.cost_risk_recommended_budget', { defaultValue: 'Recommended Budget' })}
          </div>
          <div className="text-lg font-bold text-content-primary tabular-nums mt-0.5">
            {fmtCurrency(recommendedBudget, fmt)}
          </div>
        </div>
      </div>
    </div>
  );
}

/* ── Histogram ───────────────────────────────────────────────────────── */

function Histogram({
  bins,
  p50,
  p80,
  fmt,
  t,
}: {
  bins: CostRiskHistogramBin[];
  p50: number;
  p80: number;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const maxCount = useMemo(() => Math.max(...bins.map((b) => b.count), 1), [bins]);
  const firstBin = bins[0];
  const lastBin = bins[bins.length - 1];
  const minVal = firstBin ? firstBin.bin_start : 0;
  const maxVal = lastBin ? lastBin.bin_end : 0;
  const range = maxVal - minVal;

  // Calculate P50 and P80 positions as percentage of the histogram range
  const p50Pct = range > 0 ? ((p50 - minVal) / range) * 100 : 50;
  const p80Pct = range > 0 ? ((p80 - minVal) / range) * 100 : 80;

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('boq.cost_risk_distribution', { defaultValue: 'Cost Distribution' })}
      </h4>
      <div className="relative">
        {/* Bar chart */}
        <div className="flex items-stretch gap-px h-32">
          {bins.map((bin) => {
            const heightPct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
            const binMid = (bin.bin_start + bin.bin_end) / 2;
            const isLeftOfP50 = binMid < p50;
            const isRightOfP80 = binMid > p80;

            let barColor = 'bg-blue-400/70 hover:bg-blue-500';
            if (isLeftOfP50) {
              barColor = 'bg-emerald-400/60 hover:bg-emerald-500';
            } else if (isRightOfP80) {
              barColor = 'bg-rose-400/60 hover:bg-rose-500';
            }

            return (
              <div
                key={`${bin.bin_start}-${bin.bin_end}`}
                className="flex-1 flex flex-col justify-end"
                title={`${fmtCurrency(bin.bin_start, fmt)} - ${fmtCurrency(bin.bin_end, fmt)}: ${bin.count}`}
              >
                <div
                  className={`w-full rounded-t-sm transition-colors ${barColor}`}
                  style={{ height: `${Math.max(heightPct, 1)}%` }}
                />
              </div>
            );
          })}
        </div>

        {/* P50 and P80 marker lines */}
        {range > 0 && (
          <>
            <div
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-emerald-600 dark:border-emerald-400 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p50Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-[10px] font-semibold text-emerald-700 dark:text-emerald-400 whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P50
              </span>
            </div>
            <div
              className="absolute bottom-0 top-0 w-px border-l-2 border-dashed border-amber-600 dark:border-amber-400 pointer-events-none"
              style={{ left: `${Math.min(Math.max(p80Pct, 0), 100)}%` }}
            >
              <span className="absolute -top-5 -translate-x-1/2 text-[10px] font-semibold text-amber-700 dark:text-amber-400 whitespace-nowrap bg-surface-primary/80 px-1 rounded">
                P80
              </span>
            </div>
          </>
        )}
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between text-[10px] text-content-quaternary tabular-nums">
        <span>{fmtCurrency(minVal, fmt)}</span>
        <span>{fmtCurrency(maxVal, fmt)}</span>
      </div>

      {/* Legend */}
      <div className="flex items-center justify-center gap-5 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-emerald-400/60" />
          <span className="text-2xs text-content-tertiary">
            {'< P50'}
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-blue-400/70" />
          <span className="text-2xs text-content-tertiary">
            P50 - P80
          </span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-rose-400/60" />
          <span className="text-2xs text-content-tertiary">
            {'> P80'}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Risk Drivers Table ──────────────────────────────────────────────── */

function RiskDriversTable({
  drivers,
  t,
}: {
  drivers: CostRiskDriver[];
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  if (drivers.length === 0) return null;

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('boq.cost_risk_drivers', { defaultValue: 'Top Risk Drivers' })}
      </h4>
      <div className="border border-border-light rounded-lg overflow-hidden">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-tertiary/50">
              <th className="px-3 py-2 text-left font-medium text-content-secondary">
                {t('boq.ordinal')}
              </th>
              <th className="px-3 py-2 text-left font-medium text-content-secondary">
                {t('boq.description')}
              </th>
              <th className="px-3 py-2 text-right font-medium text-content-secondary">
                {t('boq.cost_risk_variance_share', { defaultValue: 'Variance Share' })}
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {drivers.map((driver, idx) => (
              <tr
                key={`${driver.ordinal}-${idx}`}
                className={`hover:bg-surface-secondary/30 transition-colors ${
                  idx % 2 === 0 ? 'bg-surface-primary/50' : ''
                }`}
              >
                <td className="px-3 py-2 font-mono text-content-tertiary">
                  {driver.ordinal}
                </td>
                <td
                  className="px-3 py-2 text-content-primary max-w-[240px] truncate"
                  title={driver.description}
                >
                  {driver.description || '-'}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 h-2 bg-surface-tertiary rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-rose-500/70 transition-all"
                        style={{ width: `${Math.min(driver.contribution_pct, 100)}%` }}
                      />
                    </div>
                    <span className="tabular-nums font-medium text-content-secondary w-12 text-right">
                      {driver.contribution_pct.toFixed(1)}%
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

/* ── Main Component ──────────────────────────────────────────────────── */

export function CostRiskPanel({ boqId, locale = 'de-DE' }: { boqId: string; locale?: string }) {
  const { t } = useTranslation();
  const fmt = useMemo(() => createCRFormatter(locale), [locale]);
  const [collapsed, setCollapsed] = useState(false);

  const { data, isLoading, isError } = useQuery({
    queryKey: ['boq-cost-risk', boqId],
    queryFn: () => boqApi.getCostRisk(boqId),
    enabled: !!boqId,
  });

  const hasData = data && data.base_total > 0;

  return (
    <div className="mt-6 rounded-xl border border-border-light bg-surface-elevated shadow-xs overflow-hidden transition-all">
      {/* ── Toggle header ──────────────────────────────────────────── */}
      <button
        onClick={() => setCollapsed((prev) => !prev)}
        aria-expanded={!collapsed}
        aria-label={t('boq.cost_risk_title', { defaultValue: 'Monte Carlo Cost Risk' })}
        className="flex w-full items-center justify-between px-5 py-3.5 hover:bg-surface-secondary/50 transition-colors"
      >
        <div className="flex items-center gap-2.5">
          <Dices size={16} className="text-content-tertiary" strokeWidth={1.75} />
          <span className="text-sm font-semibold text-content-primary">
            {t('boq.cost_risk_title', { defaultValue: 'Monte Carlo Cost Risk' })}
          </span>
          {hasData && (
            <span className="flex h-5 min-w-[20px] items-center justify-center rounded-full bg-surface-secondary px-1.5 text-2xs font-medium text-content-secondary tabular-nums">
              {data.iterations.toLocaleString()}
              {' '}
              {t('boq.cost_risk_iterations_label', { defaultValue: 'iter.' })}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1 text-content-tertiary">
          {collapsed ? <ChevronRight size={14} /> : <ChevronDown size={14} />}
        </div>
      </button>

      {/* ── Content ────────────────────────────────────────────────── */}
      {!collapsed && (
        <div className="border-t border-border-light">
          {isLoading ? (
            <div className="px-5 py-8 text-center">
              <Loader2 size={20} className="mx-auto mb-2 animate-spin text-oe-blue" />
              <p className="text-xs text-content-tertiary">
                {t('boq.cost_risk_loading', {
                  defaultValue: 'Running Monte Carlo simulation...',
                })}
              </p>
            </div>
          ) : isError ? (
            <div className="px-5 py-8 text-center">
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-semantic-error/10 mx-auto mb-2">
                <Inbox size={18} className="text-semantic-error" />
              </div>
              <p className="text-xs text-content-secondary">
                {t('boq.cost_risk_error', { defaultValue: 'Failed to load cost risk analysis. Please try again.' })}
              </p>
            </div>
          ) : !hasData ? (
            <div className="px-5 pb-5 pt-1">
              <div className="flex flex-col items-center gap-2 py-6 text-center">
                <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary">
                  <Inbox size={18} className="text-content-tertiary" />
                </div>
                <p className="text-xs text-content-tertiary">
                  {t('boq.cost_risk_empty', {
                    defaultValue:
                      'Add positions with costs to run the Monte Carlo simulation.',
                  })}
                </p>
              </div>
            </div>
          ) : (
            <div className="px-5 py-4 space-y-5">
              {/* ── Base Total info ──────────────────────────────────── */}
              <div className="flex items-center gap-4 text-xs text-content-secondary">
                <span>
                  {t('boq.cost_risk_base_total', { defaultValue: 'Base Total' })}:{' '}
                  <span className="font-semibold text-content-primary tabular-nums">
                    {fmtCurrency(data.base_total, fmt)}
                  </span>
                </span>
                <span className="text-content-quaternary">|</span>
                <span>
                  {t('boq.cost_risk_iterations', { defaultValue: 'Iterations' })}:{' '}
                  <span className="font-semibold text-content-primary">
                    {data.iterations.toLocaleString()}
                  </span>
                </span>
              </div>

              {/* ── Percentile cards (6) ─────────────────────────────── */}
              <div className="grid grid-cols-3 gap-2 sm:grid-cols-6">
                <PercentileCard label="P10" value={data.percentiles.p10} fmt={fmt} />
                <PercentileCard label="P25" value={data.percentiles.p25} fmt={fmt} />
                <PercentileCard
                  label="P50"
                  value={data.percentiles.p50}
                  fmt={fmt}
                  variant="green"
                />
                <PercentileCard label="P75" value={data.percentiles.p75} fmt={fmt} />
                <PercentileCard
                  label="P80"
                  value={data.percentiles.p80}
                  fmt={fmt}
                  variant="orange"
                />
                <PercentileCard label="P90" value={data.percentiles.p90} fmt={fmt} />
              </div>

              {/* ── Contingency card ─────────────────────────────────── */}
              <ContingencyCard
                contingency={data.contingency_p80}
                contingencyPct={data.contingency_pct}
                recommendedBudget={data.recommended_budget}
                fmt={fmt}
                t={t}
              />

              {/* ── Histogram ────────────────────────────────────────── */}
              {data.histogram.length > 0 && (
                <Histogram
                  bins={data.histogram}
                  p50={data.percentiles.p50}
                  p80={data.percentiles.p80}
                  fmt={fmt}
                  t={t}
                />
              )}

              {/* ── Risk Drivers ─────────────────────────────────────── */}
              <RiskDriversTable drivers={data.risk_drivers} t={t} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
