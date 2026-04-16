import { useState, useMemo, useCallback, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  ArrowLeft,
  ChevronRight,
  DollarSign,
  TrendingUp,
  TrendingDown,
  Camera,
  BarChart3,
  Banknote,
  Activity,
  LineChart,
  Wallet,
  Gauge,
  Dice5,
  GitBranch,
  Lock,
  Target,
  ShieldCheck,
  Pencil,
  Check,
  X,
  Loader2,
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, EmptyState, Skeleton, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import {
  costModelApi,
  type SCurvePoint,
  type BudgetCategorySummary,
  type EVMData,
  type WhatIfResult,
} from './api';
import { CostBenchmark } from './CostBenchmark';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────────── */

interface Project {
  id: string;
  name: string;
  description: string;
  classification_standard: string;
  currency: string;
}

interface BOQ {
  id: string;
  project_id: string;
  name: string;
  description: string;
  status: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatCurrency(amount: number, currency: string): string {
  const safe = /^[A-Z]{3}$/.test(currency) ? currency : 'EUR';
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: safe,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${amount.toFixed(0)} ${safe}`;
  }
}

function formatCompact(amount: number, currency: string): string {
  const abs = Math.abs(amount);
  if (abs >= 1_000_000) {
    return `${(amount / 1_000_000).toFixed(1)}M ${currency}`;
  }
  if (abs >= 1_000) {
    return `${(amount / 1_000).toFixed(0)}K ${currency}`;
  }
  return formatCurrency(amount, currency);
}

/**
 * Variance = planned - actual (or planned - forecast).
 * Positive variance means under budget (GOOD = green).
 * Negative variance means over budget (BAD = red).
 */
function varianceColor(variance: number): string {
  if (variance > 0) return 'text-semantic-success';
  if (variance < 0) return 'text-semantic-error';
  return 'text-content-secondary';
}

function varianceBg(variance: number): string {
  if (variance > 0) return 'bg-semantic-success-bg';
  if (variance < 0) return 'bg-semantic-error-bg';
  return 'bg-surface-secondary';
}

/* ── KPI Card ──────────────────────────────────────────────────────────── */

const KPICard = memo(function KPICard({
  label,
  amount,
  currency,
  variance,
  icon,
  accentColor,
}: {
  label: string;
  amount: number;
  currency: string;
  variance?: number;
  icon: React.ReactNode;
  accentColor?: string;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="none" className="flex-1 min-w-[200px] relative overflow-hidden">
      {/* Top accent bar */}
      <div className={`absolute top-0 left-0 right-0 h-1 ${accentColor === 'green' ? 'bg-green-500' : accentColor === 'amber' ? 'bg-amber-500' : accentColor === 'rose' ? 'bg-rose-500' : 'bg-oe-blue'}`} />
      <div className="p-5 pt-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
            {label}
          </span>
          <div className={`flex h-9 w-9 items-center justify-center rounded-xl ${
            accentColor === 'green' ? 'bg-green-50 text-green-600 dark:bg-green-950/40 dark:text-green-400'
            : accentColor === 'amber' ? 'bg-amber-50 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400'
            : accentColor === 'rose' ? 'bg-rose-50 text-rose-600 dark:bg-rose-950/40 dark:text-rose-400'
            : 'bg-oe-blue/10 text-oe-blue'
          }`}>
            {icon}
          </div>
        </div>
        <div className="text-2xl font-bold tabular-nums text-content-primary leading-tight">
          {formatCurrency(amount, currency)}
        </div>
        {variance !== undefined && variance !== 0 && (
          <div className="mt-2.5 flex items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-2xs font-semibold ${varianceBg(variance)} ${varianceColor(variance)}`}
            >
              {variance < 0 ? <TrendingUp size={10} /> : <TrendingDown size={10} />}
              {variance > 0 ? '+' : ''}
              {formatCompact(variance, currency)}
            </span>
            <span className="text-2xs text-content-tertiary">{t('costmodel.vs_budget', { defaultValue: 'vs budget' })}</span>
          </div>
        )}
      </div>
    </Card>
  );
});

/* ── SPI / CPI Indicator ───────────────────────────────────────────────── */

const PerformanceIndicator = memo(function PerformanceIndicator({
  label,
  value,
  description,
}: {
  label: string;
  value: number;
  description: string;
}) {
  const { t } = useTranslation();
  const isHealthy = value >= 1.0;
  const displayValue = value.toFixed(2);

  return (
    <div className="flex items-center gap-4">
      <div
        className={`flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl text-lg font-bold tabular-nums ${
          isHealthy
            ? 'bg-semantic-success-bg text-semantic-success'
            : 'bg-semantic-error-bg text-semantic-error'
        }`}
      >
        {displayValue}
      </div>
      <div className="min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-semibold text-content-primary">{label}</span>
          <Badge variant={isHealthy ? 'success' : 'error'} size="sm">
            {isHealthy ? t('costmodel.on_track', { defaultValue: 'On Track' }) : t('costmodel.at_risk', { defaultValue: 'At Risk' })}
          </Badge>
        </div>
        <p className="mt-0.5 text-xs text-content-secondary">{description}</p>
      </div>
    </div>
  );
});

/* ── S-Curve Chart (SVG) ───────────────────────────────────────────────── */

/** EVM S-curve chart colors — semantic names for planned/earned/actual series */
const CHART_COLORS = {
  planned: 'var(--chart-planned, #2563eb)',
  earned: 'var(--chart-earned, #16a34a)',
  actual: 'var(--chart-actual, #dc2626)',
} as const;

const SCurveChart = memo(function SCurveChart({ data }: { data: SCurvePoint[] }) {
  const { t } = useTranslation();

  const chartDimensions = useMemo(() => {
    const width = 720;
    const height = 320;
    const padding = { top: 24, right: 24, bottom: 48, left: 72 };
    const plotWidth = width - padding.left - padding.right;
    const plotHeight = height - padding.top - padding.bottom;
    return { width, height, padding, plotWidth, plotHeight };
  }, []);

  const { scales, gridLines } = useMemo(() => {
    const allValues = data.flatMap((d) => [d.planned, d.earned, d.actual]);
    const maxVal = Math.max(...allValues, 1);
    const niceMax = Math.ceil(maxVal / 100_000) * 100_000 || maxVal;

    const xScale = (i: number): number =>
      chartDimensions.padding.left +
      (i / Math.max(data.length - 1, 1)) * chartDimensions.plotWidth;
    const yScale = (v: number): number =>
      chartDimensions.padding.top +
      chartDimensions.plotHeight -
      (v / niceMax) * chartDimensions.plotHeight;

    const gridCount = 5;
    const gridLinesArr = Array.from({ length: gridCount + 1 }, (_, i) => ({
      value: (niceMax / gridCount) * i,
      y: yScale((niceMax / gridCount) * i),
    }));

    return { scales: { x: xScale, y: yScale, maxVal: niceMax }, gridLines: gridLinesArr };
  }, [data, chartDimensions]);

  const buildPath = useCallback(
    (values: number[]): string =>
      values
        .map(
          (v, i) =>
            `${i === 0 ? 'M' : 'L'} ${scales.x(i).toFixed(1)} ${scales.y(v).toFixed(1)}`,
        )
        .join(' '),
    [scales],
  );

  const { plannedPath, earnedPath, actualPath } = useMemo(
    () => ({
      plannedPath: buildPath(data.map((d) => d.planned)),
      earnedPath: buildPath(data.map((d) => d.earned)),
      actualPath: buildPath(data.map((d) => d.actual)),
    }),
    [buildPath, data],
  );

  const { padding, width, height, plotWidth, plotHeight } = chartDimensions;

  return (
    <div className="w-full overflow-x-auto">
      <svg
        viewBox={`0 0 ${width} ${height}`}
        className="w-full"
        style={{ minWidth: 480 }}
        aria-label={t('costmodel.s_curve_chart', 'S-Curve Chart')}
      >
        {/* Grid lines */}
        {gridLines.map((line) => (
          <g key={line.value}>
            <line
              x1={padding.left}
              y1={line.y}
              x2={padding.left + plotWidth}
              y2={line.y}
              stroke="currentColor"
              className="text-border-light"
              strokeWidth={0.5}
              strokeDasharray={line.value === 0 ? undefined : '4 4'}
            />
            <text
              x={padding.left - 8}
              y={line.y + 4}
              textAnchor="end"
              className="fill-content-tertiary"
              fontSize={10}
              fontFamily="system-ui"
            >
              {formatCompact(line.value, '')}
            </text>
          </g>
        ))}

        {/* X axis labels */}
        {data.map((d, i) => {
          const showLabel =
            data.length <= 12 || i % Math.ceil(data.length / 12) === 0;
          if (!showLabel) return null;
          return (
            <text
              key={d.period}
              x={scales.x(i)}
              y={padding.top + plotHeight + 24}
              textAnchor="middle"
              className="fill-content-tertiary"
              fontSize={10}
              fontFamily="system-ui"
            >
              {d.period}
            </text>
          );
        })}

        {/* Axis lines */}
        <line
          x1={padding.left}
          y1={padding.top}
          x2={padding.left}
          y2={padding.top + plotHeight}
          stroke="currentColor"
          className="text-border-light"
          strokeWidth={1}
        />
        <line
          x1={padding.left}
          y1={padding.top + plotHeight}
          x2={padding.left + plotWidth}
          y2={padding.top + plotHeight}
          stroke="currentColor"
          className="text-border-light"
          strokeWidth={1}
        />

        {/* Data lines */}
        <path
          d={plannedPath}
          fill="none"
          stroke={CHART_COLORS.planned}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={earnedPath}
          fill="none"
          stroke={CHART_COLORS.earned}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={actualPath}
          fill="none"
          stroke={CHART_COLORS.actual}
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Data points */}
        {data.map((d, i) => (
          <g key={`dots-${d.period}`}>
            <circle cx={scales.x(i)} cy={scales.y(d.planned)} r={3} fill={CHART_COLORS.planned} />
            <circle cx={scales.x(i)} cy={scales.y(d.earned)} r={3} fill={CHART_COLORS.earned} />
            <circle cx={scales.x(i)} cy={scales.y(d.actual)} r={3} fill={CHART_COLORS.actual} />
          </g>
        ))}

        {/* Legend */}
        <g transform={`translate(${padding.left + 16}, ${padding.top + 8})`}>
          <rect
            x={-8}
            y={-8}
            width={280}
            height={28}
            rx={8}
            className="fill-surface-primary"
            fillOpacity={0.92}
            stroke="currentColor"
            strokeWidth={0.5}
            strokeOpacity={0.1}
          />
          <line x1={0} y1={6} x2={16} y2={6} stroke={CHART_COLORS.planned} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={8} cy={6} r={3} fill={CHART_COLORS.planned} />
          <text
            x={22}
            y={10}
            fontSize={11}
            fontWeight={500}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.planned', 'Planned (PV)')}
          </text>
          <line x1={100} y1={6} x2={116} y2={6} stroke={CHART_COLORS.earned} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={108} cy={6} r={3} fill={CHART_COLORS.earned} />
          <text
            x={122}
            y={10}
            fontSize={11}
            fontWeight={500}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.earned', 'Earned (EV)')}
          </text>
          <line x1={196} y1={6} x2={212} y2={6} stroke={CHART_COLORS.actual} strokeWidth={2.5} strokeLinecap="round" />
          <circle cx={204} cy={6} r={3} fill={CHART_COLORS.actual} />
          <text
            x={218}
            y={10}
            fontSize={11}
            fontWeight={500}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.actual', 'Actual (AC)')}
          </text>
        </g>
      </svg>
    </div>
  );
});

/* ── Budget Category Table ─────────────────────────────────────────────── */

const BudgetTable = memo(function BudgetTable({
  categories,
  currency,
}: {
  categories: BudgetCategorySummary[];
  currency: string;
}) {
  const { t } = useTranslation();

  const safeCategories = useMemo(
    () =>
      categories.map((cat) => ({
        ...cat,
        variance: typeof cat.variance === 'number' && !Number.isNaN(cat.variance)
          ? cat.variance
          : (cat.planned || 0) - (cat.forecast || 0),
      })),
    [categories],
  );

  const totals = useMemo(() => {
    return safeCategories.reduce(
      (acc, cat) => ({
        planned: acc.planned + cat.planned,
        committed: acc.committed + cat.committed,
        actual: acc.actual + cat.actual,
        forecast: acc.forecast + cat.forecast,
        variance: acc.variance + cat.variance,
      }),
      { planned: 0, committed: 0, actual: 0, forecast: 0, variance: 0 },
    );
  }, [safeCategories]);

  const categoryLabels = useMemo<Record<string, string>>(
    () => ({
      material: t('costmodel.cat_material', 'Material'),
      labor: t('costmodel.cat_labor', 'Labor'),
      equipment: t('costmodel.cat_equipment', 'Equipment'),
      subcontractor: t('costmodel.cat_subcontractor', 'Subcontractor'),
      overhead: t('costmodel.cat_overhead', 'Overhead'),
      contingency: t('costmodel.cat_contingency', 'Contingency'),
    }),
    [t],
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-border">
            <th className="py-3 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.name_category', { defaultValue: 'Category' })}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.planned', 'Planned')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.committed', 'Committed')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.actual', 'Actual')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.forecast', 'Forecast')}
            </th>
            <th className="py-3 px-2 text-center text-xs font-semibold uppercase tracking-wider text-content-secondary" style={{ minWidth: 80 }}>
              {t('costmodel.spent_pct', { defaultValue: 'Spent %' })}
            </th>
            <th className="py-3 pl-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.variance', 'Variance')}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {safeCategories.map((cat) => {
            const spentPct = cat.planned > 0 ? Math.min(100, (cat.actual / cat.planned) * 100) : 0;
            const spentOver = cat.planned > 0 && cat.actual > cat.planned;
            return (
              <tr key={cat.category} className="transition-colors hover:bg-surface-secondary/50">
                <td className="py-3.5 pr-4 font-medium text-content-primary">
                  <span>{categoryLabels[cat.category] || cat.category}</span>
                  {categoryLabels[cat.category] && cat.category !== categoryLabels[cat.category] && (
                    <span className="block text-2xs text-content-tertiary font-normal">{cat.category}</span>
                  )}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(cat.planned, currency)}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(cat.committed, currency)}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(cat.actual, currency)}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(cat.forecast, currency)}
                </td>
                <td className="py-3.5 px-2">
                  <div className="flex flex-col items-center gap-0.5">
                    <span className={`text-2xs font-semibold tabular-nums ${spentOver ? 'text-semantic-error' : 'text-content-secondary'}`}>
                      {spentPct.toFixed(0)}%
                    </span>
                    <div className="h-1.5 w-full max-w-[60px] rounded-full bg-surface-secondary overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${spentOver ? 'bg-semantic-error' : spentPct > 80 ? 'bg-amber-500' : 'bg-oe-blue'}`}
                        style={{ width: `${Math.min(100, spentPct)}%` }}
                      />
                    </div>
                  </div>
                </td>
                <td
                  className={`py-3.5 pl-4 text-right tabular-nums font-medium ${varianceColor(cat.variance)}`}
                >
                  {cat.variance > 0 ? '+' : ''}
                  {formatCurrency(cat.variance, currency)}
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border font-semibold">
            <td className="py-3.5 pr-4 text-content-primary">
              {t('costmodel.total', 'Total')}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.planned, currency)}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.committed, currency)}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.actual, currency)}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.forecast, currency)}
            </td>
            <td className="py-3.5 px-2">
              {totals.planned > 0 && (
                <div className="flex flex-col items-center gap-0.5">
                  <span className="text-2xs font-bold tabular-nums text-content-primary">
                    {Math.min(100, (totals.actual / totals.planned) * 100).toFixed(0)}%
                  </span>
                  <div className="h-1.5 w-full max-w-[60px] rounded-full bg-surface-secondary overflow-hidden">
                    <div
                      className={`h-full rounded-full ${totals.actual > totals.planned ? 'bg-semantic-error' : 'bg-oe-blue'}`}
                      style={{ width: `${Math.min(100, (totals.actual / totals.planned) * 100)}%` }}
                    />
                  </div>
                </div>
              )}
            </td>
            <td
              className={`py-3.5 pl-4 text-right tabular-nums font-bold ${varianceColor(totals.variance)}`}
            >
              {totals.variance > 0 ? '+' : ''}
              {formatCurrency(totals.variance, currency)}
            </td>
          </tr>
        </tfoot>
      </table>
    </div>
  );
});

/* ── EVM KPI Box ──────────────────────────────────────────────────────── */

const EVMKPIBox = memo(function EVMKPIBox({
  label,
  value,
  format = 'number',
  thresholdMode = 'none',
  currency = '',
}: {
  label: string;
  value: number;
  format?: 'number' | 'index' | 'currency';
  thresholdMode?: 'none' | 'index' | 'variance';
  currency?: string;
}) {
  let displayValue: string;
  if (format === 'index') {
    displayValue = value.toFixed(2);
  } else if (format === 'currency') {
    displayValue = formatCompact(value, currency);
  } else {
    displayValue = value.toFixed(2);
  }

  let colorClass = 'text-content-primary';
  let bgClass = 'bg-surface-secondary';

  if (thresholdMode === 'index') {
    if (value >= 1.0) {
      colorClass = 'text-semantic-success';
      bgClass = 'bg-semantic-success-bg';
    } else if (value >= 0.85) {
      colorClass = 'text-amber-600';
      bgClass = 'bg-amber-50';
    } else {
      colorClass = 'text-semantic-error';
      bgClass = 'bg-semantic-error-bg';
    }
  } else if (thresholdMode === 'variance') {
    if (value > 0) {
      colorClass = 'text-semantic-success';
      bgClass = 'bg-semantic-success-bg';
    } else if (value < 0) {
      colorClass = 'text-semantic-error';
      bgClass = 'bg-semantic-error-bg';
    }
  }

  return (
    <div className={`flex-1 min-w-[140px] rounded-xl p-4 ${bgClass}`}>
      <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
        {label}
      </div>
      <div className={`text-xl font-bold tabular-nums ${colorClass}`}>{displayValue}</div>
    </div>
  );
});

/* ── EVM Progress Bars ────────────────────────────────────────────────── */

const EVMProgressBars = memo(function EVMProgressBars({
  evm,
  currency,
}: {
  evm: EVMData;
  currency: string;
}) {
  const { t } = useTranslation();

  const maxValue = useMemo(
    () => Math.max(evm.bac, evm.pv, evm.ev, evm.ac, 1),
    [evm.bac, evm.pv, evm.ev, evm.ac],
  );

  const barWidth = useCallback(
    (value: number): string =>
      `${Math.max(0, Math.min(100, (value / maxValue) * 100))}%`,
    [maxValue],
  );

  const bars = useMemo(
    () => [
      {
        label: t('costmodel.evm_pv', { defaultValue: 'Planned Value (PV)' }),
        value: evm.pv,
        color: 'bg-blue-500',
      },
      {
        label: t('costmodel.evm_ev', { defaultValue: 'Earned Value (EV)' }),
        value: evm.ev,
        color: 'bg-green-500',
      },
      {
        label: t('costmodel.evm_ac', { defaultValue: 'Actual Cost (AC)' }),
        value: evm.ac,
        color: 'bg-red-500',
      },
    ],
    [t, evm.pv, evm.ev, evm.ac],
  );

  return (
    <div className="space-y-3">
      {bars.map((bar) => (
        <div key={bar.label}>
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-content-secondary">{bar.label}</span>
            <span className="text-xs font-semibold tabular-nums text-content-primary">
              {formatCompact(bar.value, currency)}
            </span>
          </div>
          <div className="h-3 w-full rounded-full bg-surface-secondary overflow-hidden">
            <div
              className={`h-full rounded-full transition-all duration-500 ${bar.color}`}
              style={{ width: barWidth(bar.value) }}
            />
          </div>
        </div>
      ))}
      <div className="flex items-center justify-between pt-1 border-t border-border-light">
        <span className="text-xs text-content-tertiary">
          {t('costmodel.evm_bac', { defaultValue: 'BAC (Budget At Completion)' })}
        </span>
        <span className="text-xs font-semibold tabular-nums text-content-primary">
          {formatCompact(maxValue, currency)}
        </span>
      </div>
    </div>
  );
});

/* ── EVM Dashboard Section ────────────────────────────────────────────── */

const EVMDashboard = memo(function EVMDashboard({
  evm,
  currency,
  isLoading,
}: {
  evm: EVMData | undefined;
  currency: string;
  isLoading: boolean;
}) {
  const { t } = useTranslation();

  const evmTooltip = t('costmodel.evm_tooltip', { defaultValue: 'Earned Value Management compares planned vs actual cost and schedule performance' });

  if (isLoading) {
    return (
      <Card>
        <div className="flex items-start justify-between gap-4">
          <h3 className="text-lg font-semibold text-content-primary truncate">
            {t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })}
            <span className="ml-1.5 inline-flex align-middle cursor-help" title={evmTooltip}>
              <Activity size={14} className="text-content-tertiary" />
            </span>
          </h3>
        </div>
        <CardContent>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} height={72} className="w-full" rounded="lg" />
              ))}
            </div>
            <Skeleton height={120} className="w-full" rounded="lg" />
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!evm || evm.bac === 0) {
    return null;
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-4">
        <h3 className="text-lg font-semibold text-content-primary truncate">
          {t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })}
          <span className="ml-1.5 inline-flex align-middle cursor-help" title={evmTooltip}>
            <Activity size={14} className="text-content-tertiary" />
          </span>
        </h3>
      </div>
      <CardContent>
        <div className="space-y-5">
          {/* EVM KPI boxes */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <EVMKPIBox
              label={t('costmodel.evm_spi', { defaultValue: 'SPI' })}
              value={evm.spi}
              format="index"
              thresholdMode="index"
            />
            <EVMKPIBox
              label={t('costmodel.evm_cpi', { defaultValue: 'CPI' })}
              value={evm.cpi}
              format="index"
              thresholdMode="index"
            />
            <EVMKPIBox
              label={t('costmodel.evm_eac_label', { defaultValue: 'EAC' })}
              value={evm.eac}
              format="currency"
              currency={currency}
            />
            <EVMKPIBox
              label={t('costmodel.evm_vac_label', { defaultValue: 'VAC' })}
              value={evm.vac}
              format="currency"
              thresholdMode="variance"
              currency={currency}
            />
          </div>

          {/* EVM Progress Bars */}
          <EVMProgressBars evm={evm} currency={currency} />

          {/* TCPI indicator */}
          {evm.tcpi > 0 && (
            <div className="rounded-xl bg-surface-secondary p-4">
              <div className="flex items-center gap-2">
                <Activity size={14} className="text-content-tertiary" />
                <span className="text-sm text-content-secondary">
                  {t('costmodel.evm_tcpi_hint', {
                    defaultValue: 'To finish on budget, you need a CPI of {{tcpi}} going forward',
                    tcpi: evm.tcpi.toFixed(2),
                  })}
                </span>
              </div>
            </div>
          )}

          {/* Secondary metrics row */}
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_sv_label', { defaultValue: 'SV' })}
              </span>
              <span
                className={`font-medium tabular-nums ${evm.sv >= 0 ? 'text-semantic-success' : 'text-semantic-error'}`}
              >
                {evm.sv >= 0 ? '+' : ''}
                {formatCompact(evm.sv, currency)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_cv_label', { defaultValue: 'CV' })}
              </span>
              <span
                className={`font-medium tabular-nums ${evm.cv >= 0 ? 'text-semantic-success' : 'text-semantic-error'}`}
              >
                {evm.cv >= 0 ? '+' : ''}
                {formatCompact(evm.cv, currency)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_etc_label', { defaultValue: 'ETC' })}
              </span>
              <span className="font-medium tabular-nums text-content-primary">
                {formatCompact(evm.etc, currency)}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_time_elapsed', { defaultValue: 'Time Elapsed' })}
              </span>
              <span className="font-medium tabular-nums text-content-primary">
                {evm.time_elapsed_pct.toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_schedule_progress', { defaultValue: 'Schedule Progress' })}
              </span>
              <span className="font-medium tabular-nums text-content-primary">
                {evm.schedule_progress_pct.toFixed(1)}%
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-content-tertiary">
                {t('costmodel.evm_status', { defaultValue: 'Status' })}
              </span>
              <Badge
                variant={
                  evm.status === 'on_track'
                    ? 'success'
                    : evm.status === 'at_risk'
                      ? 'warning'
                      : evm.status === 'critical'
                        ? 'error'
                        : 'neutral'
                }
                size="sm"
              >
                {evm.status === 'on_track'
                  ? t('costmodel.evm_on_track', { defaultValue: 'On Track' })
                  : evm.status === 'at_risk'
                    ? t('costmodel.evm_at_risk', { defaultValue: 'At Risk' })
                    : evm.status === 'critical'
                      ? t('costmodel.evm_critical', { defaultValue: 'Critical' })
                      : t('costmodel.evm_unknown', { defaultValue: 'Unknown' })}
              </Badge>
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
});

/* ── Editable Budget Lines Table ──────────────────────────────────────── */

interface EditingBudgetLine {
  id: string;
  category: string;
  description: string;
  planned_amount: number;
  actual_amount: number;
  forecast_amount: number;
}

function BudgetLinesEditor({
  projectId,
  currency,
}: {
  projectId: string;
  currency: string;
}) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<EditingBudgetLine | null>(null);

  const { data: budgetLines, isLoading } = useQuery({
    queryKey: ['costmodel', 'budget-lines', projectId],
    queryFn: () => costModelApi.getBudgetLines(projectId),
    retry: false,
  });

  const updateMutation = useMutation({
    mutationFn: (data: { id: string; updates: Partial<EditingBudgetLine> }) =>
      costModelApi.updateBudgetLine(data.id, data.updates),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
      setEditingId(null);
      setEditForm(null);
      addToast({
        type: 'success',
        title: t('costmodel.budget_line_updated', { defaultValue: 'Budget line updated' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costmodel.budget_line_update_failed', { defaultValue: 'Failed to update budget line' }),
        message: err.message,
      });
    },
  });

  const startEditing = useCallback(
    (line: {
      id: string;
      category: string;
      description: string;
      planned_amount: number;
      actual_amount: number;
      forecast_amount: number;
    }) => {
      setEditingId(line.id);
      setEditForm({
        id: line.id,
        category: line.category,
        description: line.description,
        planned_amount: line.planned_amount,
        actual_amount: line.actual_amount,
        forecast_amount: line.forecast_amount,
      });
    },
    [],
  );

  const cancelEditing = useCallback(() => {
    setEditingId(null);
    setEditForm(null);
  }, []);

  const saveEditing = useCallback(() => {
    if (!editForm) return;
    updateMutation.mutate({
      id: editForm.id,
      updates: {
        category: editForm.category,
        description: editForm.description,
        planned_amount: editForm.planned_amount,
        actual_amount: editForm.actual_amount,
        forecast_amount: editForm.forecast_amount,
      },
    });
  }, [editForm, updateMutation]);

  if (isLoading) {
    return (
      <div className="space-y-2">
        {[1, 2, 3].map((i) => (
          <Skeleton key={i} height={44} className="w-full" rounded="md" />
        ))}
      </div>
    );
  }

  if (!budgetLines || budgetLines.length === 0) {
    return null;
  }

  const lineTotal = budgetLines.reduce(
    (acc, l) => ({
      planned: acc.planned + l.planned_amount,
      actual: acc.actual + l.actual_amount,
      forecast: acc.forecast + l.forecast_amount,
    }),
    { planned: 0, actual: 0, forecast: 0 },
  );

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b-2 border-border">
            <th className="py-3 pr-4 text-left text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.bl_category', { defaultValue: 'Category' })}
            </th>
            <th className="py-3 px-4 text-left text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.bl_description', { defaultValue: 'Description' })}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.planned', 'Planned')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.actual', 'Actual')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.forecast', 'Forecast')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
              {t('costmodel.variance', 'Variance')}
            </th>
            <th className="py-3 pl-4 text-center text-xs font-semibold uppercase tracking-wider text-content-secondary w-20">
              {t('common.actions', { defaultValue: 'Actions' })}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {budgetLines.map((line) => {
            const isEditing = editingId === line.id;
            const variance = line.planned_amount - line.forecast_amount;

            if (isEditing && editForm) {
              return (
                <tr key={line.id} className="bg-oe-blue-subtle/10">
                  <td className="py-2 pr-4">
                    <input
                      value={editForm.category}
                      onChange={(e) =>
                        setEditForm((f) => f && { ...f, category: e.target.value })
                      }
                      className="h-8 w-full rounded border border-oe-blue/40 bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                  </td>
                  <td className="py-2 px-4">
                    <input
                      value={editForm.description}
                      onChange={(e) =>
                        setEditForm((f) => f && { ...f, description: e.target.value })
                      }
                      className="h-8 w-full rounded border border-oe-blue/40 bg-surface-primary px-2 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                  </td>
                  <td className="py-2 px-4">
                    <input
                      type="number"
                      step="0.01"
                      value={editForm.planned_amount}
                      onChange={(e) =>
                        setEditForm((f) =>
                          f && { ...f, planned_amount: parseFloat(e.target.value) || 0 },
                        )
                      }
                      className="h-8 w-full rounded border border-oe-blue/40 bg-surface-primary px-2 text-sm text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                  </td>
                  <td className="py-2 px-4">
                    <input
                      type="number"
                      step="0.01"
                      value={editForm.actual_amount}
                      onChange={(e) =>
                        setEditForm((f) =>
                          f && { ...f, actual_amount: parseFloat(e.target.value) || 0 },
                        )
                      }
                      className="h-8 w-full rounded border border-oe-blue/40 bg-surface-primary px-2 text-sm text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                  </td>
                  <td className="py-2 px-4">
                    <input
                      type="number"
                      step="0.01"
                      value={editForm.forecast_amount}
                      onChange={(e) =>
                        setEditForm((f) =>
                          f && { ...f, forecast_amount: parseFloat(e.target.value) || 0 },
                        )
                      }
                      className="h-8 w-full rounded border border-oe-blue/40 bg-surface-primary px-2 text-sm text-right tabular-nums focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                    />
                  </td>
                  <td className="py-2 px-4 text-right tabular-nums text-content-tertiary">
                    {formatCurrency(editForm.planned_amount - editForm.forecast_amount, currency)}
                  </td>
                  <td className="py-2 pl-4">
                    <div className="flex items-center justify-center gap-1">
                      <button
                        onClick={saveEditing}
                        disabled={updateMutation.isPending}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-semantic-success hover:bg-semantic-success-bg transition-colors"
                        title={t('common.save', { defaultValue: 'Save' })}
                      >
                        {updateMutation.isPending ? (
                          <Loader2 size={14} className="animate-spin" />
                        ) : (
                          <Check size={14} />
                        )}
                      </button>
                      <button
                        onClick={cancelEditing}
                        disabled={updateMutation.isPending}
                        className="flex h-7 w-7 items-center justify-center rounded-md text-semantic-error hover:bg-semantic-error-bg transition-colors"
                        title={t('common.cancel', { defaultValue: 'Cancel' })}
                      >
                        <X size={14} />
                      </button>
                    </div>
                  </td>
                </tr>
              );
            }

            return (
              <tr
                key={line.id}
                className="transition-colors hover:bg-surface-secondary/50 group cursor-pointer"
                onDoubleClick={() => startEditing(line)}
              >
                <td className="py-3.5 pr-4 font-medium text-content-primary">
                  {line.category}
                </td>
                <td className="py-3.5 px-4 text-content-secondary text-xs">
                  {line.description || '\u2014'}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(line.planned_amount, currency)}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(line.actual_amount, currency)}
                </td>
                <td className="py-3.5 px-4 text-right tabular-nums text-content-secondary">
                  {formatCurrency(line.forecast_amount, currency)}
                </td>
                <td
                  className={`py-3.5 px-4 text-right tabular-nums font-medium ${varianceColor(variance)}`}
                >
                  {variance > 0 ? '+' : ''}
                  {formatCurrency(variance, currency)}
                </td>
                <td className="py-3.5 pl-4 text-center">
                  <button
                    onClick={() => startEditing(line)}
                    className="invisible group-hover:visible flex h-7 w-7 mx-auto items-center justify-center rounded-md text-content-tertiary hover:text-oe-blue hover:bg-oe-blue-subtle/40 transition-colors"
                    title={t('common.edit', { defaultValue: 'Edit' })}
                  >
                    <Pencil size={13} />
                  </button>
                </td>
              </tr>
            );
          })}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border font-semibold">
            <td className="py-3.5 pr-4 text-content-primary" colSpan={2}>
              {t('costmodel.total', 'Total')}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(lineTotal.planned, currency)}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(lineTotal.actual, currency)}
            </td>
            <td className="py-3.5 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(lineTotal.forecast, currency)}
            </td>
            <td
              className={`py-3.5 px-4 text-right tabular-nums font-bold ${varianceColor(lineTotal.planned - lineTotal.forecast)}`}
            >
              {lineTotal.planned - lineTotal.forecast > 0 ? '+' : ''}
              {formatCurrency(lineTotal.planned - lineTotal.forecast, currency)}
            </td>
            <td />
          </tr>
        </tfoot>
      </table>
      <p className="mt-2 text-2xs text-content-quaternary">
        {t('costmodel.bl_edit_hint', { defaultValue: 'Double-click a row or use the edit button to modify values.' })}
      </p>
    </div>
  );
}

/* ── Snapshots List (with editable notes) ────────────────────────────── */

function SnapshotsList({ projectId, currency }: { projectId: string; currency: string }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [editingNotes, setEditingNotes] = useState<string | null>(null);
  const [notesValue, setNotesValue] = useState('');

  const { data: snapshots, isLoading } = useQuery({
    queryKey: ['costmodel', 'snapshots', projectId],
    queryFn: () => costModelApi.getSnapshots(projectId),
    retry: false,
  });

  const updateSnapshotMutation = useMutation({
    mutationFn: (data: { id: string; notes: string }) =>
      apiPatch(`/v1/costmodel/5d/snapshots/${data.id}`, { notes: data.notes }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel', 'snapshots', projectId] });
      setEditingNotes(null);
      addToast({
        type: 'success',
        title: t('costmodel.snapshot_updated', { defaultValue: 'Snapshot notes updated' }),
      });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costmodel.snapshot_update_failed', { defaultValue: 'Failed to update snapshot' }),
        message: err.message,
      });
    },
  });

  if (isLoading || !snapshots || snapshots.length === 0) return null;

  return (
    <Card>
      <CardHeader title={t('costmodel.snapshots_title', { defaultValue: 'Cost Snapshots' })} />
      <CardContent>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border-light">
                <th className="py-2 pr-3 text-left text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.period', { defaultValue: 'Period' })}
                </th>
                <th className="py-2 px-3 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.planned', 'Planned')}
                </th>
                <th className="py-2 px-3 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.snapshot_ev', { defaultValue: 'EV' })}
                </th>
                <th className="py-2 px-3 text-right text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.snapshot_ac', { defaultValue: 'AC' })}
                </th>
                <th className="py-2 px-3 text-center text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.snapshot_spi', { defaultValue: 'SPI' })}
                </th>
                <th className="py-2 px-3 text-center text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.snapshot_cpi', { defaultValue: 'CPI' })}
                </th>
                <th className="py-2 pl-3 text-left text-xs font-semibold uppercase tracking-wider text-content-secondary">
                  {t('costmodel.notes', { defaultValue: 'Notes' })}
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border-light">
              {snapshots.map((snap) => (
                <tr key={snap.id} className="hover:bg-surface-secondary/50 transition-colors group">
                  <td className="py-2.5 pr-3 font-mono text-xs text-content-primary">
                    {snap.period}
                  </td>
                  <td className="py-2.5 px-3 text-right tabular-nums text-content-secondary">
                    {formatCompact(snap.planned_cost, currency)}
                  </td>
                  <td className="py-2.5 px-3 text-right tabular-nums text-content-secondary">
                    {formatCompact(snap.earned_value, currency)}
                  </td>
                  <td className="py-2.5 px-3 text-right tabular-nums text-content-secondary">
                    {formatCompact(snap.actual_cost, currency)}
                  </td>
                  <td className={`py-2.5 px-3 text-center tabular-nums font-medium ${snap.spi >= 1 ? 'text-semantic-success' : 'text-semantic-error'}`}>
                    {snap.spi.toFixed(2)}
                  </td>
                  <td className={`py-2.5 px-3 text-center tabular-nums font-medium ${snap.cpi >= 1 ? 'text-semantic-success' : 'text-semantic-error'}`}>
                    {snap.cpi.toFixed(2)}
                  </td>
                  <td className="py-2.5 pl-3 min-w-[160px]">
                    {editingNotes === snap.id ? (
                      <div className="flex items-center gap-1">
                        <input
                          value={notesValue}
                          onChange={(e) => setNotesValue(e.target.value)}
                          className="h-7 flex-1 rounded border border-oe-blue/40 bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30"
                          autoFocus
                          onKeyDown={(e) => {
                            if (e.key === 'Enter') {
                              updateSnapshotMutation.mutate({ id: snap.id, notes: notesValue });
                            }
                            if (e.key === 'Escape') setEditingNotes(null);
                          }}
                        />
                        <button
                          onClick={() => updateSnapshotMutation.mutate({ id: snap.id, notes: notesValue })}
                          className="flex h-6 w-6 items-center justify-center rounded text-semantic-success hover:bg-semantic-success-bg"
                          disabled={updateSnapshotMutation.isPending}
                        >
                          {updateSnapshotMutation.isPending ? (
                            <Loader2 size={12} className="animate-spin" />
                          ) : (
                            <Check size={12} />
                          )}
                        </button>
                        <button
                          onClick={() => setEditingNotes(null)}
                          className="flex h-6 w-6 items-center justify-center rounded text-semantic-error hover:bg-semantic-error-bg"
                        >
                          <X size={12} />
                        </button>
                      </div>
                    ) : (
                      <div
                        className="flex items-center gap-1 cursor-pointer group/notes"
                        onClick={() => {
                          setEditingNotes(snap.id);
                          setNotesValue(snap.notes || '');
                        }}
                      >
                        <span className="text-xs text-content-tertiary truncate max-w-[200px]">
                          {snap.notes || t('costmodel.click_to_add_notes', { defaultValue: 'Click to add notes...' })}
                        </span>
                        <Pencil
                          size={11}
                          className="invisible group-hover/notes:visible shrink-0 text-content-quaternary"
                        />
                      </div>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}

/* ── Slider Control (extracted to module scope to avoid remount on re-render) ── */

const SliderControl = memo(function SliderControl({
  label,
  value,
  onChange,
  min,
  max,
  unit,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  unit: string;
}) {
  return (
    <div>
      <div className="flex items-center justify-between mb-2">
        <span className="text-sm font-medium text-content-secondary">{label}</span>
        <span
          className={`text-sm font-bold tabular-nums ${
            value > 0
              ? 'text-semantic-error'
              : value < 0
                ? 'text-semantic-success'
                : 'text-content-primary'
          }`}
        >
          {value > 0 ? '+' : ''}
          {value}
          {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={1}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-2 rounded-full appearance-none cursor-pointer bg-surface-secondary accent-oe-blue"
        aria-label={label}
      />
      <div className="flex justify-between mt-1">
        <span className="text-2xs text-content-tertiary">
          {min}
          {unit}
        </span>
        <span className="text-2xs text-content-tertiary">0{unit}</span>
        <span className="text-2xs text-content-tertiary">
          +{max}
          {unit}
        </span>
      </div>
    </div>
  );
});

/* ── What-If Scenario Panel ───────────────────────────────────────────── */

function WhatIfPanel({
  projectId,
  currency,
  currentBAC: _currentBAC,
}: {
  projectId: string;
  currency: string;
  currentBAC: number;
}) {
  void _currentBAC;
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [isExpanded, setIsExpanded] = useState(false);
  const [materialPct, setMaterialPct] = useState(0);
  const [laborPct, setLaborPct] = useState(0);
  const [durationPct, setDurationPct] = useState(0);
  const [result, setResult] = useState<WhatIfResult | null>(null);

  const whatIfMutation = useMutation({
    mutationFn: () =>
      costModelApi.createWhatIfScenario(projectId, {
        name: t('costmodel.whatif_scenario_name', {
          defaultValue: 'What-If: M{{material}}% L{{labor}}% D{{duration}}%',
          material: materialPct >= 0 ? `+${materialPct}` : materialPct,
          labor: laborPct >= 0 ? `+${laborPct}` : laborPct,
          duration: durationPct >= 0 ? `+${durationPct}` : durationPct,
        }),
        material_cost_pct: materialPct,
        labor_cost_pct: laborPct,
        duration_pct: durationPct,
      }),
    onSuccess: (data: WhatIfResult) => {
      setResult(data);
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
    onError: (err: Error) => {
      addToast({
        type: 'error',
        title: t('costmodel.whatif_failed', { defaultValue: 'What-if scenario failed' }),
        message: err.message,
      });
    },
  });

  const handleToggle = useCallback(() => setIsExpanded((v) => !v), []);
  const handleToggleKey = useCallback(
    (e: React.KeyboardEvent) => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        setIsExpanded((v) => !v);
      }
    },
    [],
  );
  const handleReset = useCallback(() => {
    setMaterialPct(0);
    setLaborPct(0);
    setDurationPct(0);
    setResult(null);
  }, []);

  return (
    <Card>
      <div
        className="flex items-center justify-between cursor-pointer px-5 py-4"
        onClick={handleToggle}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        onKeyDown={handleToggleKey}
      >
        <div className="flex items-center gap-2">
          <TrendingUp size={16} className="text-content-tertiary" />
          <span className="text-sm font-semibold text-content-primary">
            {t('costmodel.whatif_title', { defaultValue: 'What-If Scenarios' })}
          </span>
        </div>
        <ChevronRight
          size={16}
          className={`text-content-tertiary transition-transform ${isExpanded ? 'rotate-90' : ''}`}
        />
      </div>

      {isExpanded && (
        <CardContent>
          <div className="space-y-5">
            {/* Presets */}
            <div className="flex flex-wrap gap-2">
              <button onClick={() => { setMaterialPct(-10); setLaborPct(-5); setDurationPct(-10); setResult(null); }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-green-300 text-green-700 hover:bg-green-50 dark:border-green-700 dark:text-green-400 dark:hover:bg-green-900/20 transition-colors">
                {t('costmodel.preset_optimistic', { defaultValue: 'Optimistic (-10%)' })}
              </button>
              <button onClick={() => { setMaterialPct(0); setLaborPct(0); setDurationPct(0); setResult(null); }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-border text-content-secondary hover:bg-surface-secondary transition-colors">
                {t('costmodel.preset_baseline', { defaultValue: 'Baseline (0%)' })}
              </button>
              <button onClick={() => { setMaterialPct(5); setLaborPct(3); setDurationPct(5); setResult(null); }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-amber-300 text-amber-700 hover:bg-amber-50 dark:border-amber-700 dark:text-amber-400 dark:hover:bg-amber-900/20 transition-colors">
                {t('costmodel.preset_moderate', { defaultValue: 'Moderate (+5%)' })}
              </button>
              <button onClick={() => { setMaterialPct(15); setLaborPct(10); setDurationPct(20); setResult(null); }}
                className="px-3 py-1.5 text-xs font-medium rounded-lg border border-red-300 text-red-700 hover:bg-red-50 dark:border-red-700 dark:text-red-400 dark:hover:bg-red-900/20 transition-colors">
                {t('costmodel.preset_pessimistic', { defaultValue: 'Pessimistic (+15%)' })}
              </button>
            </div>

            {/* Sliders */}
            <div className="grid grid-cols-1 gap-5 sm:grid-cols-3">
              <SliderControl
                label={t('costmodel.whatif_material', { defaultValue: 'Material Cost' })}
                value={materialPct}
                onChange={setMaterialPct}
                min={-20}
                max={20}
                unit="%"
              />
              <SliderControl
                label={t('costmodel.whatif_labor', { defaultValue: 'Labor Cost' })}
                value={laborPct}
                onChange={setLaborPct}
                min={-20}
                max={20}
                unit="%"
              />
              <SliderControl
                label={t('costmodel.whatif_duration', { defaultValue: 'Duration' })}
                value={durationPct}
                onChange={setDurationPct}
                min={-30}
                max={30}
                unit="%"
              />
            </div>

            {/* Calculate button */}
            <div className="flex items-center gap-3">
              <Button
                variant="primary"
                size="sm"
                icon={<BarChart3 size={14} />}
                loading={whatIfMutation.isPending}
                onClick={() => whatIfMutation.mutate()}
                disabled={materialPct === 0 && laborPct === 0 && durationPct === 0}
              >
                {t('costmodel.whatif_calculate', { defaultValue: 'Calculate Impact' })}
              </Button>
              {(materialPct !== 0 || laborPct !== 0 || durationPct !== 0) && (
                <button
                  className="text-xs text-content-tertiary hover:text-content-secondary transition-colors"
                  onClick={handleReset}
                >
                  {t('costmodel.whatif_reset', { defaultValue: 'Reset' })}
                </button>
              )}
            </div>

            {/* Results */}
            {result && (
              <div className="rounded-xl border border-border-light p-4 space-y-3">
                <div className="flex items-center gap-2">
                  <Badge variant="blue" size="sm">
                    {result.scenario_name}
                  </Badge>
                </div>
                <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
                  <div>
                    <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-0.5">
                      {t('costmodel.whatif_original_bac', { defaultValue: 'Original BAC' })}
                    </div>
                    <div className="text-sm font-semibold tabular-nums text-content-primary">
                      {formatCompact(result.original_bac, currency)}
                    </div>
                  </div>
                  <div>
                    <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-0.5">
                      {t('costmodel.whatif_adjusted_bac', { defaultValue: 'Adjusted BAC' })}
                    </div>
                    <div className="text-sm font-semibold tabular-nums text-content-primary">
                      {formatCompact(result.adjusted_bac, currency)}
                    </div>
                  </div>
                  <div>
                    <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-0.5">
                      {t('costmodel.whatif_adjusted_eac', { defaultValue: 'Adjusted EAC' })}
                    </div>
                    <div className="text-sm font-semibold tabular-nums text-content-primary">
                      {formatCompact(result.adjusted_eac, currency)}
                    </div>
                  </div>
                  <div>
                    <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-0.5">
                      {t('costmodel.whatif_impact', { defaultValue: 'Impact' })}
                    </div>
                    <div
                      className={`text-sm font-bold tabular-nums ${
                        result.delta > 0
                          ? 'text-semantic-error'
                          : result.delta < 0
                            ? 'text-semantic-success'
                            : 'text-content-primary'
                      }`}
                    >
                      {result.delta > 0 ? '+' : ''}
                      {formatCompact(result.delta, currency)}
                      <span className="text-xs font-medium ml-1">
                        ({result.delta_pct > 0 ? '+' : ''}
                        {result.delta_pct.toFixed(1)}%)
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {whatIfMutation.isError && (
              <div className="rounded-lg bg-semantic-error-bg p-3 text-sm text-semantic-error">
                {t('costmodel.whatif_error', {
                  defaultValue: 'Failed to calculate scenario. Please try again.',
                })}
              </div>
            )}
          </div>
        </CardContent>
      )}
    </Card>
  );
}

/* ── Monte Carlo Panel ─────────────────────────────────────────────────── */

interface MCResult {
  iterations: number;
  bac: number;
  min: number;
  max: number;
  mean: number;
  p50: number;
  p80: number;
  p95: number;
  std_dev: number;
  histogram: Array<{ from: number; to: number; count: number }>;
}

function MonteCarloPanel({ projectId, currency }: { projectId: string; currency: string }) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);
  const [isExpanded, setIsExpanded] = useState(false);
  const [result, setResult] = useState<MCResult | null>(null);
  const [loading, setLoading] = useState(false);

  const fmt = useCallback(
    (n: number) => new Intl.NumberFormat(getIntlLocale(), { style: 'currency', currency: currency || 'EUR', maximumFractionDigits: 0 }).format(n),
    [currency],
  );

  const runSimulation = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiPost<MCResult>(`/v1/costmodel/projects/${projectId}/5d/monte-carlo/?iterations=1000`);
      setResult(data);
    } catch (err) {
      addToast({ type: 'error', title: t('costmodel.mc_failed', { defaultValue: 'Simulation failed' }), message: err instanceof Error ? err.message : '' });
    } finally {
      setLoading(false);
    }
  }, [projectId, addToast, t]);

  const maxCount = result ? Math.max(...result.histogram.map((b) => b.count)) : 0;

  return (
    <Card>
      <div
        className="flex items-center justify-between cursor-pointer px-5 py-4"
        onClick={() => setIsExpanded((v) => !v)}
        role="button"
        tabIndex={0}
        aria-expanded={isExpanded}
        onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setIsExpanded((v) => !v); } }}
      >
        <div className="flex items-center gap-2">
          <BarChart3 size={16} className="text-content-tertiary" />
          <span className="text-sm font-semibold text-content-primary">
            {t('costmodel.mc_title', { defaultValue: 'Cost Risk Simulation (Monte Carlo)' })}
          </span>
        </div>
        <ChevronRight size={16} className={`text-content-tertiary transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
      </div>

      {isExpanded && (
        <CardContent>
          <p className="text-xs text-content-tertiary mb-4">
            {t('costmodel.mc_desc', { defaultValue: 'Runs 1,000 random simulations with category-level cost uncertainty to estimate probable total cost ranges.' })}
          </p>

          <Button variant="primary" size="sm" icon={<BarChart3 size={14} />} loading={loading} onClick={runSimulation}>
            {t('costmodel.mc_run', { defaultValue: 'Run Simulation (1,000 iterations)' })}
          </Button>

          {result && (
            <div className="mt-5 space-y-5 animate-fade-in">
              {/* P50 / P80 / P95 cards */}
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                {[
                  { label: t('costmodel.mc_bac', { defaultValue: 'Budget (BAC)' }), value: result.bac, color: 'text-content-primary' },
                  { label: 'P50', value: result.p50, color: 'text-oe-blue' },
                  { label: 'P80', value: result.p80, color: 'text-semantic-warning' },
                  { label: 'P95', value: result.p95, color: 'text-semantic-error' },
                ].map((item) => (
                  <div key={item.label} className="rounded-xl border border-border-light bg-surface-secondary/50 px-3 py-2.5">
                    <p className="text-2xs font-semibold uppercase tracking-wider text-content-tertiary">{item.label}</p>
                    <p className={`text-lg font-bold tabular-nums ${item.color}`}>{fmt(item.value)}</p>
                  </div>
                ))}
              </div>

              {/* Histogram */}
              <div>
                <h4 className="text-xs font-medium text-content-secondary mb-2">
                  {t('costmodel.mc_distribution', { defaultValue: 'Cost Distribution' })}
                </h4>
                <div className="flex items-end gap-1 h-32">
                  {result.histogram.map((bin) => {
                    const pct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
                    const isP50 = result.p50 >= bin.from && result.p50 < bin.to;
                    const isP80 = result.p80 >= bin.from && result.p80 < bin.to;
                    const isP95 = result.p95 >= bin.from && result.p95 < bin.to;
                    return (
                      <div key={`${bin.from}-${bin.to}`} className="flex-1 flex flex-col items-center gap-0.5">
                        <span className="text-2xs text-content-quaternary tabular-nums">{bin.count}</span>
                        <div
                          className={`w-full rounded-t transition-all ${
                            isP95 ? 'bg-semantic-error' : isP80 ? 'bg-semantic-warning' : isP50 ? 'bg-oe-blue' : 'bg-oe-blue/30'
                          }`}
                          style={{ height: `${Math.max(2, pct)}%` }}
                          title={`${fmt(bin.from)} — ${fmt(bin.to)}: ${bin.count} iterations`}
                        />
                      </div>
                    );
                  })}
                </div>
                <div className="flex justify-between text-2xs text-content-quaternary mt-1">
                  <span>{fmt(result.min)}</span>
                  <span>{fmt(result.max)}</span>
                </div>
              </div>

              {/* Summary */}
              <div className="flex flex-wrap gap-3 text-xs text-content-tertiary">
                <span>{t('costmodel.mc_mean', { defaultValue: 'Mean' })}: {fmt(result.mean)}</span>
                <span>{t('costmodel.mc_stddev', { defaultValue: 'Std Dev' })}: {fmt(result.std_dev)}</span>
                <span>{t('costmodel.mc_range', { defaultValue: 'Range' })}: {fmt(result.min)} — {fmt(result.max)}</span>
                <span>{result.iterations} {t('costmodel.mc_iterations', { defaultValue: 'iterations' })}</span>
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}

/* ── 5D Dashboard ──────────────────────────────────────────────────────── */

function FiveDDashboard({ project }: { project: Project }) {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const [selectedBoqId, setSelectedBoqId] = useState('');

  const { data: dashboard, isLoading: dashboardLoading } = useQuery({
    queryKey: ['costmodel', 'dashboard', project.id],
    queryFn: () => costModelApi.getDashboard(project.id),
    retry: false,
  });

  const { data: sCurveData, isLoading: sCurveLoading } = useQuery({
    queryKey: ['costmodel', 's-curve', project.id],
    queryFn: () => costModelApi.getSCurve(project.id),
    retry: false,
  });

  const { data: budgetData, isLoading: budgetLoading } = useQuery({
    queryKey: ['costmodel', 'budget', project.id],
    queryFn: () => costModelApi.getBudgetSummary(project.id),
    retry: false,
  });

  const { data: evmData, isLoading: evmLoading } = useQuery({
    queryKey: ['costmodel', 'evm', project.id],
    queryFn: () => costModelApi.getEVM(project.id),
    retry: false,
  });

  const { data: boqs } = useQuery({
    queryKey: ['boqs', project.id],
    queryFn: () => apiGet<BOQ[]>(`/v1/boq/boqs/?project_id=${project.id}`),
    retry: false,
  });

  const generateBudget = useMutation({
    mutationFn: (boqId: string) => costModelApi.generateBudgetFromBoq(project.id, boqId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('costmodel.budget_failed', { defaultValue: 'Failed to generate budget' }), message: err.message });
    },
  });

  const createSnapshot = useMutation({
    mutationFn: () => {
      const now = new Date();
      const period = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      return costModelApi.createSnapshot(project.id, { period });
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('costmodel.snapshot_failed', { defaultValue: 'Failed to create snapshot' }), message: err.message });
    },
  });

  const generateCashFlow = useMutation({
    mutationFn: () => costModelApi.generateCashFlow(project.id),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['costmodel'] });
    },
    onError: (err: Error) => {
      addToast({ type: 'error', title: t('costmodel.cashflow_failed', { defaultValue: 'Failed to generate cash flow' }), message: err.message });
    },
  });

  const currency = dashboard?.currency || project.currency || 'EUR';
  const hasBudget = (dashboard?.total_budget ?? 0) > 0;

  const handleCreateSnapshot = useCallback(() => {
    createSnapshot.mutate();
  }, [createSnapshot]);

  const handleGenerateCashFlow = useCallback(() => {
    generateCashFlow.mutate();
  }, [generateCashFlow]);

  return (
    <div className="space-y-6">
      {/* ── Empty state: no budget yet ────────────────────────────────────── */}
      {!hasBudget && (
        <div className="rounded-2xl border-2 border-dashed border-oe-blue/30 bg-gradient-to-br from-oe-blue-subtle/10 via-surface-primary to-violet-50/10 dark:from-oe-blue-subtle/5 dark:to-violet-950/5 p-8">
          <div className="mx-auto max-w-2xl text-center">
            {/* Icon cluster */}
            <div className="mb-5 flex items-center justify-center gap-3">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-oe-blue/10 text-oe-blue">
                <DollarSign size={24} />
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-green-100 text-green-600 dark:bg-green-950/40 dark:text-green-400">
                <LineChart size={18} />
              </div>
              <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-amber-100 text-amber-600 dark:bg-amber-950/40 dark:text-amber-400">
                <Gauge size={18} />
              </div>
            </div>

            <h2 className="text-xl font-bold text-content-primary">
              {t('costmodel.empty_title', { defaultValue: '5D Cost Model' })}
            </h2>
            <p className="mt-2 text-sm leading-relaxed text-content-secondary">
              {t('costmodel.empty_desc', { defaultValue: 'Earned Value Management with S-curves, cash flow forecasting, and what-if analysis. Transform your BOQ estimate into a living cost control dashboard with SPI, CPI, EAC, and Monte Carlo risk simulation.' })}
            </p>

            {/* Feature pills */}
            <div className="mt-5 flex flex-wrap items-center justify-center gap-2">
              {[
                { icon: <Target size={12} />, label: t('costmodel.feat_budget', { defaultValue: 'Budget Tracking' }) },
                { icon: <LineChart size={12} />, label: t('costmodel.feat_scurve', { defaultValue: 'S-Curve Analysis' }) },
                { icon: <Wallet size={12} />, label: t('costmodel.feat_cashflow', { defaultValue: 'Cash Flow' }) },
                { icon: <Gauge size={12} />, label: t('costmodel.feat_evm', { defaultValue: 'EVM (SPI / CPI / EAC)' }) },
                { icon: <Dice5 size={12} />, label: t('costmodel.feat_montecarlo', { defaultValue: 'Monte Carlo' }) },
                { icon: <GitBranch size={12} />, label: t('costmodel.feat_whatif', { defaultValue: 'What-If Scenarios' }) },
              ].map((pill) => (
                <span
                  key={pill.label}
                  className="inline-flex items-center gap-1.5 rounded-full border border-border-light bg-surface-primary px-3 py-1 text-2xs font-medium text-content-secondary shadow-sm"
                >
                  {pill.icon}
                  {pill.label}
                </span>
              ))}
            </div>

            {/* CTA area */}
            <div className="mt-6 rounded-xl border border-border-light bg-surface-primary p-5 shadow-sm">
              {boqs && boqs.length > 0 ? (
                <div>
                  <div className="mb-3 flex items-center justify-center gap-2">
                    <ShieldCheck size={16} className="text-oe-blue" />
                    <span className="text-sm font-semibold text-content-primary">
                      {t('costmodel.ready_to_generate', { defaultValue: 'Ready to generate budget from your BOQ' })}
                    </span>
                  </div>
                  <div className="flex items-center justify-center gap-2">
                    {boqs.length > 1 && (
                      <select
                        value={selectedBoqId}
                        onChange={(e) => setSelectedBoqId(e.target.value)}
                        className="h-9 rounded-lg border border-border bg-surface-primary px-3 text-sm"
                      >
                        {boqs.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                      </select>
                    )}
                    <Button variant="primary" size="md" icon={<BarChart3 size={16} />} loading={generateBudget.isPending}
                      onClick={() => generateBudget.mutate(selectedBoqId || (boqs[0]?.id ?? ''))}>
                      {t('costmodel.generate_budget_cta', { defaultValue: 'Generate Budget from BOQ' })}
                    </Button>
                  </div>
                </div>
              ) : (
                <div>
                  <div className="mb-2 flex items-center justify-center gap-2">
                    <Lock size={16} className="text-amber-500" />
                    <span className="text-sm font-semibold text-content-primary">
                      {t('costmodel.prereq_boq', { defaultValue: 'BOQ estimate required' })}
                    </span>
                  </div>
                  <p className="text-xs text-content-tertiary">
                    {t('costmodel.prereq_boq_desc', { defaultValue: 'Create and finalize your Bill of Quantities first, then generate the project budget to unlock all 5D analytics.' })}
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ── Workflow stepper (visible when budget exists) ─────────────────── */}
      {hasBudget && (
        <Card padding="md">
          <div className="flex items-center gap-2 mb-4">
            <ShieldCheck size={16} className="text-semantic-success" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('costmodel.workflow', { defaultValue: 'Cost Model Active' })}
            </h3>
          </div>
          <div className="flex items-start gap-4">
            {/* Step 1: Budget (complete) */}
            <div className="flex-1 rounded-lg border border-semantic-success/30 bg-semantic-success-bg/30 p-3">
              <div className="flex items-center gap-2 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-semantic-success text-white text-xs font-bold">{'\u2713'}</div>
                <span className="text-xs font-medium text-content-primary">
                  {t('costmodel.step_budget', { defaultValue: 'Budget Generated' })}
                </span>
              </div>
              <p className="text-2xs text-content-tertiary">
                {t('costmodel.step_budget_done', { defaultValue: 'Budget created from BOQ' })}
              </p>
            </div>

            <div className="pt-4 text-content-quaternary">{'\u2192'}</div>

            {/* Step 2: Track Costs */}
            <div className="flex-1 rounded-lg border border-oe-blue/30 bg-oe-blue-subtle/20 p-3">
              <div className="flex items-center gap-2 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-oe-blue text-white text-xs font-bold">2</div>
                <span className="text-xs font-medium text-content-primary">
                  {t('costmodel.step_track', { defaultValue: 'Track Costs' })}
                </span>
              </div>
              <p className="text-2xs text-content-tertiary">
                {t('costmodel.step_track_hint', { defaultValue: 'Update actual costs in the budget table below' })}
              </p>
            </div>

            <div className="pt-4 text-content-quaternary">{'\u2192'}</div>

            {/* Step 3: Analyze */}
            <div className="flex-1 rounded-lg border border-border-light p-3">
              <div className="flex items-center gap-2 mb-1">
                <div className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-tertiary text-xs font-bold text-content-secondary">3</div>
                <span className="text-xs font-medium text-content-primary">
                  {t('costmodel.step_analyze', { defaultValue: 'Analyze & Forecast' })}
                </span>
              </div>
              <p className="text-2xs text-content-tertiary">
                {t('costmodel.step_analyze_hint', { defaultValue: 'Use What-If, Monte Carlo, and EVM to forecast outcomes' })}
              </p>
            </div>
          </div>

          {/* Snapshot / Cash Flow actions */}
          <div className="flex flex-wrap items-center gap-3 mt-4 pt-3 border-t border-border-light">
            <Button
              variant="secondary"
              size="sm"
              icon={<Camera size={14} />}
              loading={createSnapshot.isPending}
              onClick={handleCreateSnapshot}
            >
              {t('costmodel.create_snapshot', { defaultValue: 'Create Snapshot' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Banknote size={14} />}
              loading={generateCashFlow.isPending}
              onClick={handleGenerateCashFlow}
            >
              {t('costmodel.generate_cash_flow', { defaultValue: 'Generate Cash Flow' })}
            </Button>
          </div>
        </Card>
      )}

      {/* KPI Cards */}
      {dashboardLoading ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <Skeleton key={i} height={120} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : dashboard ? (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 xl:grid-cols-4">
          <KPICard
            label={t('costmodel.total_budget', 'Total Budget')}
            amount={dashboard.total_budget}
            currency={currency}
            icon={<DollarSign size={18} />}
          />
          <KPICard
            label={t('costmodel.committed', 'Committed')}
            amount={dashboard.total_committed}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_committed}
            icon={<Banknote size={18} />}
            accentColor="green"
          />
          <KPICard
            label={t('costmodel.actual_spent', 'Actual Spent')}
            amount={dashboard.total_actual}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_actual}
            icon={<TrendingUp size={18} />}
            accentColor="amber"
          />
          <KPICard
            label={t('costmodel.forecast_eac', 'Forecast (EAC)')}
            amount={dashboard.total_forecast}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_forecast}
            icon={<Activity size={18} />}
            accentColor="rose"
          />
        </div>
      ) : null}

      {/* Cost per m² Benchmark */}
      {dashboard && (
        <CostBenchmark
          totalBudget={dashboard.total_budget}
          currency={currency}
        />
      )}

      {/* Earned Value Analysis */}
      {evmData && evmData.bac > 0 && evmData.spi > 0 ? (
        <EVMDashboard evm={evmData} currency={currency} isLoading={evmLoading} />
      ) : hasBudget ? (
        <Card>
          <div className="flex items-start justify-between gap-4">
            <h3 className="text-lg font-semibold text-content-primary truncate">
              {t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })}
              <span className="ml-1.5 inline-flex align-middle cursor-help" title={t('costmodel.evm_tooltip', { defaultValue: 'Earned Value Management compares planned vs actual cost and schedule performance' })}>
                <Activity size={14} className="text-content-tertiary" />
              </span>
            </h3>
          </div>
          <CardContent>
            <p className="text-sm text-content-tertiary">
              {t('costmodel.evm_needs_schedule', { defaultValue: 'Create a 4D Schedule and track activity progress to see EVM performance metrics (SPI, CPI).' })}
            </p>
          </CardContent>
        </Card>
      ) : null}

      {/* What-If Scenarios */}
      <WhatIfPanel
        projectId={project.id}
        currency={currency}
        currentBAC={evmData?.bac ?? dashboard?.total_budget ?? 0}
      />

      {/* Monte Carlo Cost Risk Simulation */}
      <MonteCarloPanel projectId={project.id} currency={currency} />

      {/* Performance Indicators + S-Curve row */}
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        {/* SPI / CPI */}
        <div>
          <Card>
            <CardHeader title={t('costmodel.performance', { defaultValue: 'Performance' })} />
            <CardContent>
              {dashboardLoading ? (
                <div className="space-y-4">
                  <Skeleton height={56} className="w-full" rounded="lg" />
                  <Skeleton height={56} className="w-full" rounded="lg" />
                </div>
              ) : dashboard && dashboard.spi > 0 && dashboard.cpi > 0 ? (
                <div className="space-y-5">
                  <PerformanceIndicator
                    label="SPI"
                    value={dashboard.spi}
                    description={t(
                      'costmodel.spi_desc',
                      'Schedule Performance Index',
                    )}
                  />
                  <div className="border-t border-border-light" />
                  <PerformanceIndicator
                    label="CPI"
                    value={dashboard.cpi}
                    description={t('costmodel.cpi_desc', 'Cost Performance Index')}
                  />
                  {dashboard.variance !== 0 && (
                    <>
                      <div className="border-t border-border-light" />
                      <div className="flex items-center justify-between">
                        <span className="text-sm text-content-secondary">
                          {t('costmodel.overall_variance', { defaultValue: 'Overall Variance' })}
                        </span>
                        <span
                          className={`text-sm font-semibold tabular-nums ${varianceColor(dashboard.variance)}`}
                        >
                          {dashboard.variance > 0 ? '+' : ''}
                          {dashboard.variance_pct.toFixed(1)}%
                        </span>
                      </div>
                    </>
                  )}
                </div>
              ) : hasBudget ? (
                <div className="flex flex-col items-center py-8 text-center">
                  <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary text-content-quaternary">
                    <Gauge size={18} />
                  </div>
                  <p className="text-sm font-medium text-content-secondary">
                    {t('costmodel.perf_needs_schedule', { defaultValue: 'Schedule not linked yet' })}
                  </p>
                  <p className="mt-1 text-xs text-content-tertiary max-w-[200px]">
                    {t('costmodel.perf_needs_schedule_desc', { defaultValue: 'Link a 4D schedule and track progress to see SPI/CPI indicators.' })}
                  </p>
                </div>
              ) : (
                <div className="flex flex-col items-center py-8 text-center">
                  <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-xl bg-surface-secondary text-content-quaternary">
                    <Gauge size={18} />
                  </div>
                  <p className="text-xs text-content-tertiary">
                    {t('costmodel.perf_needs_budget', { defaultValue: 'Generate a budget to see performance metrics.' })}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* S-Curve */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader title={t('costmodel.s_curve', { defaultValue: 'S-Curve (Planned vs Earned vs Actual)' })} />
            <CardContent>
              {sCurveLoading ? (
                <Skeleton height={320} className="w-full" rounded="lg" />
              ) : sCurveData && sCurveData.periods.length > 0 ? (
                <SCurveChart data={sCurveData.periods} />
              ) : (
                <div className="flex flex-col items-center py-12 text-center">
                  <div className="mb-3 flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary text-content-quaternary">
                    <LineChart size={22} />
                  </div>
                  <p className="text-sm font-medium text-content-secondary">
                    {t('costmodel.s_curve_empty_title', { defaultValue: 'No S-curve data yet' })}
                  </p>
                  <p className="mt-1 max-w-xs text-xs text-content-tertiary">
                    {hasBudget
                      ? t('costmodel.s_curve_needs_snapshots', { defaultValue: 'Create periodic snapshots to build the S-Curve chart over time. Each snapshot captures planned, earned, and actual values.' })
                      : t('costmodel.s_curve_needs_budget', { defaultValue: 'Generate a budget first, then create snapshots to build the S-Curve.' })}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      </div>

      {/* Budget by Category */}
      <Card>
        <CardHeader title={t('costmodel.budget_by_category', 'Budget by Category')} />
        <CardContent>
          {budgetLoading ? (
            <div className="space-y-3">
              {[1, 2, 3, 4, 5].map((i) => (
                <Skeleton key={i} height={40} className="w-full" rounded="md" />
              ))}
            </div>
          ) : budgetData && budgetData.categories.length > 0 ? (
            <BudgetTable categories={budgetData.categories} currency={currency} />
          ) : (
            <div className="flex flex-col items-center py-10 text-center">
              <div className="mb-3 flex h-11 w-11 items-center justify-center rounded-xl bg-surface-secondary text-content-quaternary">
                <BarChart3 size={20} />
              </div>
              <p className="text-sm font-medium text-content-secondary">
                {t('costmodel.budget_table_empty_title', { defaultValue: 'No budget categories yet' })}
              </p>
              <p className="mt-1 max-w-xs text-xs text-content-tertiary">
                {t('costmodel.budget_table_empty_desc', { defaultValue: 'Budget categories (Material, Labor, Equipment, etc.) will appear here once you generate a budget from your BOQ.' })}
              </p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Editable Budget Lines */}
      {hasBudget && (
        <Card>
          <CardHeader
            title={t('costmodel.budget_lines_title', { defaultValue: 'Budget Lines (Editable)' })}
          />
          <CardContent>
            <BudgetLinesEditor projectId={project.id} currency={currency} />
          </CardContent>
        </Card>
      )}

      {/* Cost Snapshots */}
      {hasBudget && (
        <SnapshotsList projectId={project.id} currency={currency} />
      )}
    </div>
  );
}

/* ── Project Selector Card ─────────────────────────────────────────────── */

const ProjectCard = memo(function ProjectCard({
  project,
  onSelect,
}: {
  project: Project;
  onSelect: (id: string) => void;
}) {
  const handleClick = useCallback(() => onSelect(project.id), [onSelect, project.id]);
  return (
    <Card
      hoverable
      padding="none"
      className="cursor-pointer"
      onClick={handleClick}
    >
      <div className="flex items-center gap-3 px-5 py-4">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-oe-blue-subtle text-oe-blue font-bold">
          {project.name.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0 flex-1">
          <h2 className="text-sm font-semibold text-content-primary truncate">
            {project.name}
          </h2>
          {project.description && (
            <p className="mt-0.5 text-xs text-content-secondary truncate">
              {project.description}
            </p>
          )}
        </div>
        <Badge variant="blue" size="sm">
          {project.currency || 'EUR'}
        </Badge>
        <Badge variant="neutral" size="sm">
          {project.classification_standard === 'din276' ? 'DIN 276' : project.classification_standard?.toUpperCase() || '—'}
        </Badge>
        <ChevronRight size={16} className="shrink-0 text-content-tertiary" />
      </div>
    </Card>
  );
});

/* ── Main Page ─────────────────────────────────────────────────────────── */

export function CostModelPage() {
  const { t } = useTranslation();
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  const { data: projects, isLoading } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<Project[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });

  // Auto-select if there's only one project
  const effectiveProjectId = useMemo(
    () => selectedProjectId ?? (projects?.length === 1 ? projects[0]!.id : null),
    [selectedProjectId, projects],
  );

  const selectedProject = useMemo(
    () => (effectiveProjectId ? projects?.find((p) => p.id === effectiveProjectId) : null),
    [effectiveProjectId, projects],
  );

  const handleBack = useCallback(() => setSelectedProjectId(null), []);

  // Feature cards for the empty/intro state
  const featureCards = useMemo(
    () => [
      {
        icon: <Target size={20} />,
        title: t('costmodel.feat_budget', { defaultValue: 'Budget Tracking' }),
        desc: t('costmodel.feat_budget_desc', { defaultValue: 'Generate budget lines from BOQ positions. Track planned, committed, actual, and forecast costs in real time.' }),
        color: 'text-blue-600 bg-blue-50 dark:text-blue-400 dark:bg-blue-950/40',
      },
      {
        icon: <LineChart size={20} />,
        title: t('costmodel.feat_scurve', { defaultValue: 'S-Curve Analysis' }),
        desc: t('costmodel.feat_scurve_desc', { defaultValue: 'Visualize planned vs earned vs actual cost over time with cumulative S-curve charts.' }),
        color: 'text-green-600 bg-green-50 dark:text-green-400 dark:bg-green-950/40',
      },
      {
        icon: <Wallet size={20} />,
        title: t('costmodel.feat_cashflow', { defaultValue: 'Cash Flow' }),
        desc: t('costmodel.feat_cashflow_desc', { defaultValue: 'Forecast project cash inflows and outflows period by period to manage liquidity.' }),
        color: 'text-violet-600 bg-violet-50 dark:text-violet-400 dark:bg-violet-950/40',
      },
      {
        icon: <Gauge size={20} />,
        title: t('costmodel.feat_evm', { defaultValue: 'EVM (SPI / CPI / EAC)' }),
        desc: t('costmodel.feat_evm_desc', { defaultValue: 'Earned Value Management with Schedule and Cost Performance Indexes, Estimate at Completion, and variance analysis.' }),
        color: 'text-amber-600 bg-amber-50 dark:text-amber-400 dark:bg-amber-950/40',
      },
      {
        icon: <Dice5 size={20} />,
        title: t('costmodel.feat_montecarlo', { defaultValue: 'Monte Carlo Simulation' }),
        desc: t('costmodel.feat_montecarlo_desc', { defaultValue: 'Run 1,000 probabilistic iterations to estimate P50, P80, and P95 cost confidence levels.' }),
        color: 'text-rose-600 bg-rose-50 dark:text-rose-400 dark:bg-rose-950/40',
      },
      {
        icon: <GitBranch size={20} />,
        title: t('costmodel.feat_whatif', { defaultValue: 'What-If Scenarios' }),
        desc: t('costmodel.feat_whatif_desc', { defaultValue: 'Adjust material, labor, and duration costs to instantly see impact on budget and forecasts.' }),
        color: 'text-teal-600 bg-teal-50 dark:text-teal-400 dark:bg-teal-950/40',
      },
    ],
    [t],
  );

  // Project detail view with 5D dashboard
  if (selectedProject) {
    return (
      <div className="w-full animate-fade-in">
        <button
          onClick={handleBack}
          className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
        >
          <ArrowLeft size={14} />
          {t('costmodel.back_to_projects', 'Back to projects')}
        </button>

        <div className="mb-6 flex items-start gap-4">
          <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl bg-oe-blue-subtle text-oe-blue">
            <BarChart3 size={22} />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-content-primary">{selectedProject.name}</h1>
            <p className="mt-0.5 text-sm text-content-secondary">
              {t('costmodel.dashboard_subtitle', '5D Cost Model -- Budget tracking, EVM, S-curves, and forecasting')}
            </p>
          </div>
        </div>

        <FiveDDashboard project={selectedProject} />
      </div>
    );
  }

  // Project selector view
  return (
    <div className="w-full animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.costmodel', { defaultValue: '5D Cost Model' }) }]} className="mb-4" />

      {/* Hero header */}
      <div className="mb-8">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('costmodel.title', '5D Cost Model')}
        </h1>
        <p className="mt-2 text-sm text-content-secondary max-w-2xl leading-relaxed">
          {t(
            'costmodel.hero_desc',
            'Earned Value Management with S-curves, cash flow forecasting, Monte Carlo risk simulation, and what-if scenario analysis. Transform your BOQ estimate into a living cost control dashboard.',
          )}
        </p>
      </div>

      {/* Feature cards grid -- always visible as intro */}
      {(!projects || projects.length === 0) && !isLoading && (
        <div className="mb-8">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {featureCards.map((feat) => (
              <div key={feat.title} className="rounded-xl border border-border-light bg-surface-primary p-5 transition-colors hover:bg-surface-secondary/40">
                <div className={`mb-3 flex h-10 w-10 items-center justify-center rounded-xl ${feat.color}`}>
                  {feat.icon}
                </div>
                <h3 className="text-sm font-semibold text-content-primary">{feat.title}</h3>
                <p className="mt-1 text-xs leading-relaxed text-content-tertiary">{feat.desc}</p>
              </div>
            ))}
          </div>

          {/* Prerequisites callout */}
          <div className="mt-6 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50/60 p-4 dark:border-amber-800/50 dark:bg-amber-950/20">
            <Lock size={18} className="mt-0.5 shrink-0 text-amber-600 dark:text-amber-400" />
            <div>
              <p className="text-sm font-medium text-amber-800 dark:text-amber-300">
                {t('costmodel.prereq_title', { defaultValue: 'Getting Started' })}
              </p>
              <p className="mt-0.5 text-xs text-amber-700/80 dark:text-amber-400/70">
                {t('costmodel.prereq_desc', { defaultValue: 'Create a project and build your BOQ estimate first. Once your BOQ is ready, generate the project budget to unlock the full 5D cost model with all analytics capabilities.' })}
              </p>
            </div>
          </div>
        </div>
      )}

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<DollarSign size={28} strokeWidth={1.5} />}
          title={t('costmodel.no_projects', 'No projects yet')}
          description={t(
            'costmodel.no_projects_hint',
            'Create your first project to start tracking costs with the 5D model.',
          )}
        />
      ) : (
        <>
          {/* Compact feature strip when projects exist */}
          <div className="mb-6 flex flex-wrap gap-2">
            {featureCards.map((feat) => (
              <span key={feat.title} className="inline-flex items-center gap-1.5 rounded-lg bg-surface-secondary px-3 py-1.5 text-2xs font-medium text-content-secondary">
                <span className={`flex h-5 w-5 items-center justify-center rounded ${feat.color}`}>
                  {feat.icon}
                </span>
                {feat.title}
              </span>
            ))}
          </div>

          <h2 className="mb-3 text-sm font-semibold text-content-secondary uppercase tracking-wider">
            {t('costmodel.select_project', { defaultValue: 'Select a project' })}
          </h2>
          <div className="space-y-3">
            {projects.map((project) => (
              <ProjectCard
                key={project.id}
                project={project}
                onSelect={setSelectedProjectId}
              />
            ))}
          </div>
        </>
      )}
    </div>
  );
}
