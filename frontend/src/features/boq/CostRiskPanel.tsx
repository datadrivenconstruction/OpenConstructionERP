// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, keepPreviousData } from '@tanstack/react-query';
import { ChevronDown, ChevronRight, Dices, Loader2, Inbox, CheckCircle2, AlertTriangle } from 'lucide-react';
import {
  boqApi,
  type CostRiskHistogramBin,
  type CostRiskDriver,
  type CostRiskCdfPoint,
} from './api';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Helpers ─────────────────────────────────────────────────────────── */

function createCRFormatter(locale: string) {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  });
}

/** Money fields cross the wire as Decimal-as-strings (v3 §10); coerce safely. */
function num(v: number | string | undefined | null): number {
  if (typeof v === 'number') return v;
  const n = parseFloat(String(v ?? ''));
  return Number.isFinite(n) ? n : 0;
}

function fmtCurrency(n: number, fmt: Intl.NumberFormat): string {
  const abs = Math.abs(n);
  if (abs >= 1_000_000) {
    return `${n < 0 ? '-' : ''}${fmtFixed(abs / 1_000_000, 2)}M`;
  }
  if (abs >= 10_000) {
    return `${n < 0 ? '-' : ''}${fmt.format(Math.round(abs / 1_000))}K`;
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
      ? 'rounded-lg border border-emerald-400/50 bg-emerald-50/50 dark:bg-emerald-950/20'
      : variant === 'orange'
        ? 'rounded-lg border border-amber-400/50 bg-amber-50/50 dark:bg-amber-950/20'
        : 'rounded-xl border border-border-light bg-surface-elevated/90 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm';

  const valueClass =
    variant === 'green'
      ? 'text-emerald-700 dark:text-emerald-400'
      : variant === 'orange'
        ? 'text-amber-700 dark:text-amber-400'
        : 'text-content-primary';

  return (
    <div className={`px-2.5 py-2 ${borderClass}`}>
      <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
        {label}
      </div>
      <div className={`text-sm font-bold tabular-nums mt-0.5 ${valueClass}`}>
        {fmtCurrency(value, fmt)}
      </div>
    </div>
  );
}

/* ── Stat tile (mean / sigma / CV / prob) ────────────────────────────── */

function StatTile({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="rounded-lg border border-border-light bg-surface-elevated/90 px-3 py-2">
      <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">{label}</div>
      <div className="text-sm font-bold text-content-primary tabular-nums mt-0.5">{value}</div>
      {hint && <div className="text-[10px] text-content-quaternary mt-0.5">{hint}</div>}
    </div>
  );
}

/* ── Convergence badge ───────────────────────────────────────────────── */

function ConvergenceBadge({
  status,
  marginPct,
  t,
}: {
  status: string;
  marginPct: number;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const map = {
    converged: {
      cls: 'border-emerald-400/50 bg-emerald-50/60 dark:bg-emerald-950/20 text-emerald-700 dark:text-emerald-400',
      icon: CheckCircle2,
      label: t('boq.cost_risk_converged', { defaultValue: 'Converged' }),
    },
    marginal: {
      cls: 'border-amber-400/50 bg-amber-50/60 dark:bg-amber-950/20 text-amber-700 dark:text-amber-400',
      icon: AlertTriangle,
      label: t('boq.cost_risk_marginal', { defaultValue: 'Marginal' }),
    },
    insufficient: {
      cls: 'border-rose-400/50 bg-rose-50/60 dark:bg-rose-950/20 text-rose-700 dark:text-rose-400',
      icon: AlertTriangle,
      label: t('boq.cost_risk_low_confidence', { defaultValue: 'Low confidence' }),
    },
  };
  const cfg = map[status as keyof typeof map] ?? map.marginal;
  const Icon = cfg.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-2xs font-medium ${cfg.cls}`}
      title={t('boq.cost_risk_convergence_hint', {
        defaultValue: 'Split-half stability of the P80 estimate ({{margin}}% of P50). Lower is better.',
        margin: fmtFixed(marginPct, 2),
      })}
    >
      <Icon size={11} strokeWidth={2} />
      {cfg.label}
      {marginPct > 0 && <span className="tabular-nums opacity-70">±{fmtPercent(marginPct)}</span>}
    </span>
  );
}

/* ── Correlation control ─────────────────────────────────────────────── */

function CorrelationControl({
  value,
  onChange,
  t,
}: {
  value: number;
  onChange: (v: number) => void;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const opts = [
    { v: 0, label: t('boq.cost_risk_corr_independent', { defaultValue: 'Independent' }) },
    { v: 0.2, label: t('boq.cost_risk_corr_moderate', { defaultValue: 'Moderate' }) },
    { v: 0.5, label: t('boq.cost_risk_corr_high', { defaultValue: 'High' }) },
  ];
  return (
    <div className="flex flex-col gap-1">
      <div className="flex items-center gap-2">
        <span className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
          {t('boq.cost_risk_correlation', { defaultValue: 'Risk correlation' })}
        </span>
        <div className="inline-flex rounded-lg border border-border-light overflow-hidden">
          {opts.map((o) => (
            <button
              key={o.v}
              onClick={() => onChange(o.v)}
              className={`px-2.5 py-1 text-2xs font-medium transition-colors ${
                Math.abs(value - o.v) < 1e-6
                  ? 'bg-oe-blue text-white'
                  : 'bg-surface-elevated text-content-secondary hover:bg-surface-secondary'
              }`}
            >
              {o.label}
            </button>
          ))}
        </div>
      </div>
      <p className="text-[10px] text-content-quaternary max-w-md">
        {t('boq.cost_risk_correlation_hint', {
          defaultValue:
            'Systemic drivers (escalation, market, weather) move many lines together. Higher correlation widens the band - independent lines unrealistically cancel out.',
        })}
      </p>
    </div>
  );
}

/* ── Contingency Card ────────────────────────────────────────────────── */

function ContingencyCard({
  contingency,
  contingencyPct,
  recommendedBudget,
  targetConfidence,
  probWithinBase,
  fmt,
  t,
}: {
  contingency: number;
  contingencyPct: number;
  recommendedBudget: number;
  targetConfidence: number;
  probWithinBase: number;
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  return (
    <div className="rounded-lg border border-blue-400/50 bg-blue-50/50 dark:bg-blue-950/20 px-4 py-3 space-y-2">
      <div className="flex items-center justify-between">
        <div>
          <div className="text-2xs font-medium text-content-tertiary uppercase tracking-wide">
            {t('boq.cost_risk_contingency_target', {
              defaultValue: 'Contingency to reach P{{p}}',
              p: targetConfidence,
            })}
          </div>
          <div className="text-lg font-bold text-blue-700 dark:text-blue-400 tabular-nums mt-0.5">
            {fmtCurrency(contingency, fmt)}{' '}
            <span className="text-sm font-medium text-blue-600/70 dark:text-blue-400/70">
              (+{fmtPercent(contingencyPct)})
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
      <p className="text-[11px] leading-snug text-content-secondary border-t border-blue-400/20 pt-2">
        {t('boq.cost_risk_guidance', {
          defaultValue:
            'Budgeting at P{{p}} gives {{p}}% confidence the final cost will not exceed this amount. There is a {{base}}% chance it lands at or below the deterministic base estimate.',
          p: targetConfidence,
          base: fmtFixed(probWithinBase, 0),
        })}
      </p>
    </div>
  );
}

/* ── Histogram + S-curve combo ───────────────────────────────────────── */

function DistributionChart({
  bins,
  cdf,
  p50,
  p80,
  fmt,
  t,
}: {
  bins: CostRiskHistogramBin[];
  cdf: CostRiskCdfPoint[];
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
  const range = maxVal - minVal || 1;

  const p50Pct = ((p50 - minVal) / range) * 100;
  const p80Pct = ((p80 - minVal) / range) * 100;

  // S-curve overlay (cumulative probability) drawn in the same 100x100 space.
  const curve = useMemo(() => {
    if (!cdf || cdf.length < 2) return '';
    return cdf
      .map((pt) => {
        const x = ((pt.cost - minVal) / range) * 100;
        const y = 100 - pt.cumulative_prob * 100;
        return `${Math.min(Math.max(x, 0), 100).toFixed(2)},${y.toFixed(2)}`;
      })
      .join(' ');
  }, [cdf, minVal, range]);

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('boq.cost_risk_distribution', { defaultValue: 'Cost distribution & S-curve' })}
      </h4>
      <div className="relative">
        {/* Histogram bars */}
        <div className="flex items-stretch gap-px h-36">
          {bins.map((bin) => {
            const heightPct = (bin.count / maxCount) * 100;
            const binMid = (bin.bin_start + bin.bin_end) / 2;
            const isLeftOfP50 = binMid < p50;
            const isRightOfP80 = binMid > p80;

            let barColor = 'bg-blue-400/60 hover:bg-blue-500';
            if (isLeftOfP50) barColor = 'bg-emerald-400/50 hover:bg-emerald-500';
            else if (isRightOfP80) barColor = 'bg-rose-400/50 hover:bg-rose-500';

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

        {/* S-curve overlay */}
        {curve && (
          <svg
            viewBox="0 0 100 100"
            preserveAspectRatio="none"
            className="pointer-events-none absolute inset-0 h-36 w-full overflow-visible"
            aria-hidden="true"
          >
            {/* 50% / 80% horizontal guides */}
            <line x1="0" y1="50" x2="100" y2="50" className="stroke-content-quaternary" strokeWidth="0.5" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
            <line x1="0" y1="20" x2="100" y2="20" className="stroke-content-quaternary" strokeWidth="0.5" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
            <polyline
              points={curve}
              fill="none"
              className="stroke-oe-blue"
              strokeWidth="1.5"
              strokeLinejoin="round"
              vectorEffect="non-scaling-stroke"
            />
          </svg>
        )}

        {/* P50 / P80 marker lines */}
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
      </div>

      {/* X-axis labels */}
      <div className="flex justify-between text-[10px] text-content-quaternary tabular-nums">
        <span>{fmtCurrency(minVal, fmt)}</span>
        <span>{fmtCurrency(maxVal, fmt)}</span>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap items-center justify-center gap-x-5 gap-y-1 pt-1">
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-emerald-400/60" />
          <span className="text-2xs text-content-tertiary">{'< P50'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-blue-400/60" />
          <span className="text-2xs text-content-tertiary">P50 - P80</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-2.5 w-5 rounded-sm bg-rose-400/50" />
          <span className="text-2xs text-content-tertiary">{'> P80'}</span>
        </div>
        <div className="flex items-center gap-1.5">
          <div className="h-0.5 w-5 rounded bg-oe-blue" />
          <span className="text-2xs text-content-tertiary">
            {t('boq.cost_risk_cumulative', { defaultValue: 'Cumulative %' })}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Risk Drivers Table ──────────────────────────────────────────────── */

function RiskDriversTable({
  drivers,
  fmt,
  t,
}: {
  drivers: CostRiskDriver[];
  fmt: Intl.NumberFormat;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  if (drivers.length === 0) return null;
  const maxContribution = Math.max(...drivers.map((d) => d.contribution_pct), 1);

  return (
    <div className="space-y-2">
      <h4 className="text-xs font-semibold text-content-tertiary uppercase tracking-wide">
        {t('boq.cost_risk_drivers', { defaultValue: 'Top Risk Drivers' })}
      </h4>
      <div className="border border-border-light rounded-lg overflow-hidden overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="bg-surface-tertiary/50">
              <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.ordinal')}</th>
              <th className="px-3 py-2 text-left font-medium text-content-secondary">{t('boq.description')}</th>
              <th className="px-3 py-2 text-right font-medium text-content-secondary">
                {t('boq.cost_risk_swing', { defaultValue: 'P10 - P90 swing' })}
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
                className={`hover:bg-surface-secondary/30 transition-colors ${idx % 2 === 0 ? 'bg-surface-primary/50' : ''}`}
              >
                <td className="px-3 py-2 font-mono text-content-tertiary">{driver.ordinal}</td>
                <td className="px-3 py-2 text-content-primary max-w-[220px] truncate" title={driver.description}>
                  {driver.description || '-'}
                </td>
                <td className="px-3 py-2 text-right tabular-nums text-content-secondary whitespace-nowrap">
                  {driver.swing_low != null && driver.swing_high != null ? (
                    <>
                      <span className="text-emerald-600">{fmtCurrency(driver.swing_low, fmt)}</span>
                      {' / '}
                      <span className="text-rose-600">+{fmtCurrency(driver.swing_high, fmt)}</span>
                    </>
                  ) : (
                    '-'
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <div className="w-20 h-2 bg-surface-tertiary rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full bg-rose-500/70 transition-all"
                        style={{ width: `${(driver.contribution_pct / maxContribution) * 100}%` }}
                      />
                    </div>
                    <span className="tabular-nums font-medium text-content-secondary w-12 text-right">
                      {fmtPercent(driver.contribution_pct)}
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
  // Collapsed by default and simulated on expand: the Monte Carlo run is a
  // heavy call consumed only inside this panel, so it must not be part of
  // the editor's first-paint request burst (see SensitivityChart).
  const [collapsed, setCollapsed] = useState(true);
  const [correlation, setCorrelation] = useState(0.2);

  const { data, isLoading, isError, isFetching } = useQuery({
    queryKey: ['boq-cost-risk', boqId, correlation],
    queryFn: () => boqApi.getCostRisk(boqId, correlation),
    enabled: !!boqId && !collapsed,
    placeholderData: keepPreviousData,
  });

  const hasData = data && num(data.base_total) > 0;

  function cvLabel(cv: number): string {
    if (cv < 10) return t('boq.cost_risk_cv_tight', { defaultValue: 'Tight estimate' });
    if (cv < 25) return t('boq.cost_risk_cv_normal', { defaultValue: 'Normal uncertainty' });
    if (cv < 50) return t('boq.cost_risk_cv_high', { defaultValue: 'High uncertainty' });
    return t('boq.cost_risk_cv_very_high', { defaultValue: 'Very high uncertainty' });
  }

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
              {data.iterations.toLocaleString(getNumberLocale())} {t('boq.cost_risk_iterations_label', { defaultValue: 'iter.' })}
            </span>
          )}
          {hasData && data.convergence_status && (
            <ConvergenceBadge status={data.convergence_status} marginPct={data.convergence_margin_pct ?? 0} t={t} />
          )}
        </div>
        <div className="flex items-center gap-1 text-content-tertiary">
          {isFetching && <Loader2 size={12} className="animate-spin" />}
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
                {t('boq.cost_risk_loading', { defaultValue: 'Running Monte Carlo simulation...' })}
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
                    defaultValue: 'Add positions with costs to run the Monte Carlo simulation.',
                  })}
                </p>
              </div>
            </div>
          ) : (
            <div className="px-5 py-4 space-y-5">
              {/* ── Controls + base total ────────────────────────────── */}
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <div className="flex items-center gap-4 text-xs text-content-secondary">
                  <span>
                    {t('boq.cost_risk_base_total', { defaultValue: 'Base Total' })}:{' '}
                    <span className="font-semibold text-content-primary tabular-nums">
                      {fmtCurrency(num(data.base_total), fmt)}
                    </span>
                  </span>
                </div>
                <CorrelationControl value={correlation} onChange={setCorrelation} t={t} />
              </div>

              {/* ── Percentile cards ─────────────────────────────────── */}
              <div className="grid grid-cols-4 gap-2 sm:grid-cols-8">
                {data.percentiles.p5 != null && (
                  <PercentileCard label="P5" value={data.percentiles.p5} fmt={fmt} />
                )}
                <PercentileCard label="P10" value={data.percentiles.p10} fmt={fmt} />
                <PercentileCard label="P25" value={data.percentiles.p25} fmt={fmt} />
                <PercentileCard label="P50" value={data.percentiles.p50} fmt={fmt} variant="green" />
                <PercentileCard label="P75" value={data.percentiles.p75} fmt={fmt} />
                <PercentileCard label="P80" value={data.percentiles.p80} fmt={fmt} variant="orange" />
                <PercentileCard label="P90" value={data.percentiles.p90} fmt={fmt} />
                {data.percentiles.p95 != null && (
                  <PercentileCard label="P95" value={data.percentiles.p95} fmt={fmt} />
                )}
              </div>

              {/* ── Stats row ────────────────────────────────────────── */}
              {data.mean != null && (
                <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                  <StatTile
                    label={t('boq.cost_risk_mean', { defaultValue: 'Mean (expected)' })}
                    value={fmtCurrency(num(data.mean), fmt)}
                  />
                  <StatTile
                    label={t('boq.cost_risk_std_dev', { defaultValue: 'Std deviation' })}
                    value={fmtCurrency(num(data.std_dev), fmt)}
                  />
                  <StatTile
                    label={t('boq.cost_risk_cv', { defaultValue: 'Variability (CV)' })}
                    value={fmtPercent(data.cv_pct ?? 0)}
                    hint={cvLabel(data.cv_pct ?? 0)}
                  />
                  <StatTile
                    label={t('boq.cost_risk_prob_base', { defaultValue: 'Chance <= base' })}
                    value={fmtPercent(data.prob_within_base ?? 0, 0)}
                  />
                </div>
              )}

              {/* ── Contingency card ─────────────────────────────────── */}
              <ContingencyCard
                contingency={data.contingency_p80}
                contingencyPct={data.contingency_pct}
                recommendedBudget={num(data.recommended_budget)}
                targetConfidence={data.target_confidence ?? 80}
                probWithinBase={data.prob_within_base ?? 0}
                fmt={fmt}
                t={t}
              />

              {/* ── Distribution + S-curve ───────────────────────────── */}
              {data.histogram.length > 0 && (
                <DistributionChart
                  bins={data.histogram}
                  cdf={data.cdf ?? []}
                  p50={data.percentiles.p50}
                  p80={data.percentiles.p80}
                  fmt={fmt}
                  t={t}
                />
              )}

              {/* ── Risk Drivers ─────────────────────────────────────── */}
              <RiskDriversTable drivers={data.risk_drivers} fmt={fmt} t={t} />
            </div>
          )}
        </div>
      )}
    </div>
  );
}
