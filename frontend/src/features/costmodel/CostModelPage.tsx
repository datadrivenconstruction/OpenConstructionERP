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
} from 'lucide-react';
import { Card, CardHeader, CardContent, Button, Badge, EmptyState, Skeleton, InfoHint, Breadcrumb } from '@/shared/ui';
import { apiGet, apiPost } from '@/shared/lib/api';
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
  if (variance > 0) return 'text-[#15803d]';
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
}: {
  label: string;
  amount: number;
  currency: string;
  variance?: number;
  icon: React.ReactNode;
}) {
  const { t } = useTranslation();
  return (
    <Card padding="none" className="flex-1 min-w-[200px]">
      <div className="p-5">
        <div className="flex items-center justify-between mb-3">
          <span className="text-xs font-medium uppercase tracking-wider text-content-tertiary">
            {label}
          </span>
          <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-surface-secondary text-content-tertiary">
            {icon}
          </div>
        </div>
        <div className="text-2xl font-bold tabular-nums text-content-primary">
          {formatCurrency(amount, currency)}
        </div>
        {variance !== undefined && variance !== 0 && (
          <div className="mt-2 flex items-center gap-1.5">
            <span
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-2xs font-medium ${varianceBg(variance)} ${varianceColor(variance)}`}
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
            ? 'bg-semantic-success-bg text-[#15803d]'
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
          stroke="#2563eb"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={earnedPath}
          fill="none"
          stroke="#16a34a"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />
        <path
          d={actualPath}
          fill="none"
          stroke="#dc2626"
          strokeWidth={2.5}
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Data points */}
        {data.map((d, i) => (
          <g key={`dots-${d.period}`}>
            <circle cx={scales.x(i)} cy={scales.y(d.planned)} r={3} fill="#2563eb" />
            <circle cx={scales.x(i)} cy={scales.y(d.earned)} r={3} fill="#16a34a" />
            <circle cx={scales.x(i)} cy={scales.y(d.actual)} r={3} fill="#dc2626" />
          </g>
        ))}

        {/* Legend */}
        <g transform={`translate(${padding.left + 16}, ${padding.top + 8})`}>
          <rect
            x={-8}
            y={-6}
            width={240}
            height={24}
            rx={6}
            fill="white"
            fillOpacity={0.85}
          />
          <circle cx={4} cy={6} r={4} fill="#2563eb" />
          <text
            x={14}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.planned', 'Planned')}
          </text>
          <circle cx={80} cy={6} r={4} fill="#16a34a" />
          <text
            x={90}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.earned', 'Earned')}
          </text>
          <circle cx={154} cy={6} r={4} fill="#dc2626" />
          <text
            x={164}
            y={10}
            fontSize={11}
            className="fill-content-secondary"
            fontFamily="system-ui"
          >
            {t('costmodel.actual', 'Actual')}
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
          <tr className="border-b border-border-light">
            <th className="py-3 pr-4 text-left text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.name_category', { defaultValue: 'Name / Category' })}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.planned', 'Planned')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.committed', 'Committed')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.actual', 'Actual')}
            </th>
            <th className="py-3 px-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.forecast', 'Forecast')}
            </th>
            <th className="py-3 pl-4 text-right text-xs font-medium uppercase tracking-wider text-content-tertiary">
              {t('costmodel.variance', 'Variance')}
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-light">
          {safeCategories.map((cat) => (
            <tr key={cat.category} className="transition-colors hover:bg-surface-secondary/50">
              <td className="py-3 pr-4 font-medium text-content-primary">
                <span>{categoryLabels[cat.category] || cat.category}</span>
                {categoryLabels[cat.category] && cat.category !== categoryLabels[cat.category] && (
                  <span className="block text-2xs text-content-tertiary font-normal">{cat.category}</span>
                )}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.planned, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.committed, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.actual, currency)}
              </td>
              <td className="py-3 px-4 text-right tabular-nums text-content-secondary">
                {formatCurrency(cat.forecast, currency)}
              </td>
              <td
                className={`py-3 pl-4 text-right tabular-nums font-medium ${varianceColor(cat.variance)}`}
              >
                {cat.variance > 0 ? '+' : ''}
                {formatCurrency(cat.variance, currency)}
              </td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr className="border-t-2 border-border font-semibold">
            <td className="py-3 pr-4 text-content-primary">
              {t('costmodel.total', 'Total')}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.planned, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.committed, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.actual, currency)}
            </td>
            <td className="py-3 px-4 text-right tabular-nums text-content-primary">
              {formatCurrency(totals.forecast, currency)}
            </td>
            <td
              className={`py-3 pl-4 text-right tabular-nums font-bold ${varianceColor(totals.variance)}`}
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
      colorClass = 'text-[#15803d]';
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
      colorClass = 'text-[#15803d]';
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

  if (isLoading) {
    return (
      <Card>
        <CardHeader title={t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })} />
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
      <CardHeader title={t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })} />
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
                className={`font-medium tabular-nums ${evm.sv >= 0 ? 'text-[#15803d]' : 'text-semantic-error'}`}
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
                className={`font-medium tabular-nums ${evm.cv >= 0 ? 'text-[#15803d]' : 'text-semantic-error'}`}
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
                ? 'text-[#15803d]'
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
      console.error('What-if scenario failed:', err.message);
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
                            ? 'text-[#15803d]'
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
      const data = await apiPost<MCResult>(`/v1/costmodel/projects/${projectId}/5d/monte-carlo?iterations=1000`);
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
                  {result.histogram.map((bin, i) => {
                    const pct = maxCount > 0 ? (bin.count / maxCount) * 100 : 0;
                    const isP50 = result.p50 >= bin.from && result.p50 < bin.to;
                    const isP80 = result.p80 >= bin.from && result.p80 < bin.to;
                    const isP95 = result.p95 >= bin.from && result.p95 < bin.to;
                    return (
                      <div key={i} className="flex-1 flex flex-col items-center gap-0.5">
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
      {/* 5D explanation */}
      <InfoHint className="mb-0" text={t('costmodel.what_is_5d', { defaultValue: '5D cost management adds cost tracking over time to your project. Monitor budget vs. actual spend with S-curve charts, track Earned Value (SPI = schedule efficiency, CPI = cost efficiency — both >= 1.0 means healthy), and run what-if scenarios to forecast outcomes.' })} />

      {/* Workflow Steps */}
      <Card padding="md" className="mb-6">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('costmodel.workflow', { defaultValue: 'Setup Workflow' })}
        </h3>
        <div className="flex items-start gap-4">
          {/* Step 1: Generate Budget */}
          <div className={`flex-1 rounded-lg border p-3 ${hasBudget ? 'border-semantic-success/30 bg-semantic-success-bg/30' : 'border-oe-blue/30 bg-oe-blue-subtle/20'}`}>
            <div className="flex items-center gap-2 mb-1">
              <div className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-bold ${hasBudget ? 'bg-semantic-success text-white' : 'bg-oe-blue text-white'}`}>
                {hasBudget ? '\u2713' : '1'}
              </div>
              <span className="text-xs font-medium text-content-primary">
                {t('costmodel.step_budget', { defaultValue: 'Generate Budget' })}
              </span>
            </div>
            <p className="text-2xs text-content-tertiary mb-2">
              {hasBudget
                ? t('costmodel.step_budget_done', { defaultValue: 'Budget created from BOQ' })
                : t('costmodel.step_budget_hint', { defaultValue: 'Create budget lines from your BOQ positions' })}
            </p>
            {!hasBudget && boqs && boqs.length > 0 && (
              <div className="flex items-center gap-2">
                {boqs.length > 1 && (
                  <select
                    value={selectedBoqId}
                    onChange={(e) => setSelectedBoqId(e.target.value)}
                    className="h-7 rounded border border-border bg-surface-primary px-2 text-xs"
                  >
                    {boqs.map(b => <option key={b.id} value={b.id}>{b.name}</option>)}
                  </select>
                )}
                <Button variant="primary" size="sm" loading={generateBudget.isPending}
                  onClick={() => generateBudget.mutate(selectedBoqId || (boqs[0]?.id ?? ''))}>
                  {t('costmodel.generate', { defaultValue: 'Generate' })}
                </Button>
              </div>
            )}
            {!hasBudget && (!boqs || boqs.length === 0) && (
              <p className="text-2xs text-amber-600">{t('costmodel.no_boq_warning', { defaultValue: 'Create a BOQ first \u2192' })}</p>
            )}
          </div>

          {/* Arrow */}
          <div className="pt-4 text-content-quaternary">{'\u2192'}</div>

          {/* Step 2: Track Costs */}
          <div className={`flex-1 rounded-lg border p-3 ${hasBudget ? 'border-border-light' : 'border-border-light/50 opacity-50'}`}>
            <div className="flex items-center gap-2 mb-1">
              <div className="flex h-6 w-6 items-center justify-center rounded-full bg-surface-tertiary text-xs font-bold text-content-secondary">2</div>
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
          <div className={`flex-1 rounded-lg border p-3 ${hasBudget ? 'border-border-light' : 'border-border-light/50 opacity-50'}`}>
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

        {/* Snapshot / Cash Flow actions (visible once budget exists) */}
        {hasBudget && (
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
        )}
      </Card>

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
            icon={<DollarSign size={16} />}
          />
          <KPICard
            label={t('costmodel.committed', 'Committed')}
            amount={dashboard.total_committed}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_committed}
            icon={<Banknote size={16} />}
          />
          <KPICard
            label={t('costmodel.actual_spent', 'Actual Spent')}
            amount={dashboard.total_actual}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_actual}
            icon={<TrendingUp size={16} />}
          />
          <KPICard
            label={t('costmodel.forecast_eac', 'Forecast (EAC)')}
            amount={dashboard.total_forecast}
            currency={currency}
            variance={dashboard.total_budget - dashboard.total_forecast}
            icon={<Activity size={16} />}
          />
        </div>
      ) : (
        <div className="rounded-xl border border-border-light bg-surface-secondary/30 px-5 py-8 text-center">
          <p className="text-sm text-content-secondary">
            {t('costmodel.complete_step1', { defaultValue: 'Complete Step 1 above to see cost metrics here.' })}
          </p>
        </div>
      )}

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
          <CardHeader title={t('costmodel.evm_title', { defaultValue: 'Earned Value Analysis' })} />
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
                <p className="py-6 text-center text-sm text-content-secondary">
                  {t('costmodel.performance_needs_schedule', { defaultValue: 'Link a schedule to see performance metrics.' })}
                </p>
              ) : (
                <p className="py-6 text-center text-sm text-content-secondary">
                  {t('costmodel.complete_step1', { defaultValue: 'Complete Step 1 above to see cost metrics here.' })}
                </p>
              )}
            </CardContent>
          </Card>
        </div>

        {/* S-Curve */}
        <div className="lg:col-span-2">
          <Card>
            <CardHeader title={t('costmodel.s_curve', { defaultValue: 'S-Curve (EVM)' })} />
            <CardContent>
              {sCurveLoading ? (
                <Skeleton height={320} className="w-full" rounded="lg" />
              ) : sCurveData && sCurveData.periods.length > 0 ? (
                <SCurveChart data={sCurveData.periods} />
              ) : (
                <div className="py-8 text-center">
                  <p className="text-sm text-content-secondary">
                    {hasBudget
                      ? t('costmodel.s_curve_needs_snapshots', { defaultValue: 'Create snapshots (Step 2) to build the S-Curve over time.' })
                      : t('costmodel.complete_step1', { defaultValue: 'Complete Step 1 above to see cost metrics here.' })}
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
            <div className="py-8 text-center">
              <p className="text-sm text-content-secondary">
                {t('costmodel.complete_step1', { defaultValue: 'Complete Step 1 above to see cost metrics here.' })}
              </p>
            </div>
          )}
        </CardContent>
      </Card>
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

  // Project detail view with 5D dashboard
  if (selectedProject) {
    return (
      <div className="max-w-content mx-auto animate-fade-in">
        <button
          onClick={handleBack}
          className="mb-4 flex items-center gap-1.5 text-sm text-content-secondary hover:text-content-primary transition-colors"
        >
          <ArrowLeft size={14} />
          {t('costmodel.back_to_projects', 'Back to projects')}
        </button>

        <div className="mb-6">
          <h1 className="text-2xl font-bold text-content-primary">{selectedProject.name}</h1>
          <p className="mt-1 text-sm text-content-secondary">
            {t('costmodel.dashboard_subtitle', '5D Cost Model Dashboard')}
          </p>
        </div>

        <FiveDDashboard project={selectedProject} />
      </div>
    );
  }

  // Project selector view
  return (
    <div className="max-w-content mx-auto animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.dashboard', 'Dashboard'), to: '/' }, { label: t('nav.costmodel', { defaultValue: '5D Cost Model' }) }]} className="mb-4" />
      <div className="mb-6">
        <h1 className="text-2xl font-bold text-content-primary">
          {t('costmodel.title', '5D Cost Model')}
        </h1>
        <p className="mt-1 text-sm text-content-secondary">
          {t(
            'costmodel.subtitle',
            'Select a project to view its 5D cost management dashboard',
          )}
        </p>
      </div>

      {/* 5D explanation */}
      <InfoHint className="mb-6" text={t('costmodel.what_is_5d', { defaultValue: '5D cost management adds cost tracking over time to your project. Monitor budget vs. actual spend with S-curve charts, track Earned Value (SPI = schedule efficiency, CPI = cost efficiency — both >= 1.0 means healthy), and run what-if scenarios to forecast outcomes.' })} />

      {isLoading ? (
        <div className="space-y-4">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={72} className="w-full" rounded="lg" />
          ))}
        </div>
      ) : !projects || projects.length === 0 ? (
        <EmptyState
          icon={<DollarSign size={28} strokeWidth={1.5} />}
          title={t('costmodel.no_projects', 'No projects available')}
          description={t(
            'costmodel.no_projects_hint',
            'Create a project first, then come back to manage its 5D cost model',
          )}
        />
      ) : (
        <div className="space-y-3">
          {projects.map((project) => (
            <ProjectCard
              key={project.id}
              project={project}
              onSelect={setSelectedProjectId}
            />
          ))}
        </div>
      )}
    </div>
  );
}
