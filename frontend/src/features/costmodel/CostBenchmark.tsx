import { useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Ruler } from 'lucide-react';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Types ─────────────────────────────────────────────────────────────── */

type ProjectType = 'residential' | 'office' | 'hospital' | 'industrial' | 'retail' | 'education';

interface BenchmarkRange {
  min: number;
  max: number;
}

interface CostBenchmarkProps {
  totalBudget: number;
  currency: string;
  /** Project area in m², if already known from project metadata. */
  initialArea?: number;
}

/* ── Benchmark data per project type (EUR/m²) ─────────────────────────── */

const BENCHMARK_RANGES: Record<ProjectType, BenchmarkRange> = {
  residential: { min: 2500, max: 4500 },
  office: { min: 3000, max: 5500 },
  hospital: { min: 5000, max: 8000 },
  industrial: { min: 1500, max: 3500 },
  retail: { min: 2000, max: 4000 },
  education: { min: 2800, max: 5000 },
};

/* Module-level constant — keys are stable, labels resolved via t() in JSX */
const PROJECT_TYPE_OPTIONS: ReadonlyArray<{
  value: ProjectType;
  labelKey: string;
  defaultLabel: string;
}> = [
  { value: 'residential', labelKey: 'costmodel.benchmark_type_residential', defaultLabel: 'Residential' },
  { value: 'office', labelKey: 'costmodel.benchmark_type_office', defaultLabel: 'Office' },
  { value: 'hospital', labelKey: 'costmodel.benchmark_type_hospital', defaultLabel: 'Hospital' },
  { value: 'industrial', labelKey: 'costmodel.benchmark_type_industrial', defaultLabel: 'Industrial' },
  { value: 'retail', labelKey: 'costmodel.benchmark_type_retail', defaultLabel: 'Retail' },
  { value: 'education', labelKey: 'costmodel.benchmark_type_education', defaultLabel: 'Education' },
];

/* ── Helpers ───────────────────────────────────────────────────────────── */

function formatCurrencyValue(amount: number, currency: string): string {
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

type BenchmarkStatus = 'within' | 'near_edge' | 'outside';

function getBenchmarkStatus(
  costPerM2: number,
  range: BenchmarkRange,
): BenchmarkStatus {
  if (costPerM2 >= range.min && costPerM2 <= range.max) {
    return 'within';
  }
  // "Near edge" = within 10% of the range boundary
  const tolerance = (range.max - range.min) * 0.1;
  if (costPerM2 >= range.min - tolerance && costPerM2 <= range.max + tolerance) {
    return 'near_edge';
  }
  return 'outside';
}

function getStatusColor(status: BenchmarkStatus): {
  text: string;
  bg: string;
  indicator: string;
  bar: string;
} {
  switch (status) {
    case 'within':
      return {
        text: 'text-semantic-success',
        bg: 'bg-semantic-success-bg',
        indicator: 'bg-green-500',
        bar: 'bg-green-500',
      };
    case 'near_edge':
      return {
        text: 'text-amber-600',
        bg: 'bg-amber-50',
        indicator: 'bg-amber-500',
        bar: 'bg-amber-500',
      };
    case 'outside':
      return {
        text: 'text-semantic-error',
        bg: 'bg-semantic-error-bg',
        indicator: 'bg-red-500',
        bar: 'bg-red-500',
      };
  }
}

/* ── Range Indicator (visual bar) ────────────────────────────────────── */

const RangeIndicator = memo(function RangeIndicator({
  costPerM2,
  range,
  status,
}: {
  costPerM2: number;
  range: BenchmarkRange;
  status: BenchmarkStatus;
}) {
  const { t } = useTranslation();
  const colors = getStatusColor(status);

  // Calculate the display range: extend 20% beyond the benchmark range on each side
  const rangeSpan = range.max - range.min;
  const displayMin = Math.max(0, range.min - rangeSpan * 0.2);
  const displayMax = range.max + rangeSpan * 0.2;
  const displaySpan = displayMax - displayMin;

  // Position of the benchmark range within the display range (as percentages)
  const rangeStartPct = ((range.min - displayMin) / displaySpan) * 100;
  const rangeEndPct = ((range.max - displayMin) / displaySpan) * 100;

  // Position of the current cost/m² indicator (clamped to display range)
  const clampedCost = Math.max(displayMin, Math.min(displayMax, costPerM2));
  const indicatorPct = ((clampedCost - displayMin) / displaySpan) * 100;

  return (
    <div className="space-y-2">
      {/* Labels for range boundaries */}
      <div className="relative h-4 text-2xs text-content-tertiary tabular-nums">
        <span
          className="absolute -translate-x-1/2"
          style={{ left: `${rangeStartPct}%` }}
        >
          {formatCurrencyValue(range.min, 'EUR')}
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: `${rangeEndPct}%` }}
        >
          {formatCurrencyValue(range.max, 'EUR')}
        </span>
      </div>

      {/* Bar */}
      <div className="relative h-3 w-full rounded-full bg-surface-secondary overflow-hidden">
        {/* Benchmark range highlight */}
        <div
          className="absolute top-0 h-full bg-green-100 dark:bg-green-900/30"
          style={{
            left: `${rangeStartPct}%`,
            width: `${rangeEndPct - rangeStartPct}%`,
          }}
        />
        {/* Range boundary markers */}
        <div
          className="absolute top-0 h-full w-px bg-green-400"
          style={{ left: `${rangeStartPct}%` }}
        />
        <div
          className="absolute top-0 h-full w-px bg-green-400"
          style={{ left: `${rangeEndPct}%` }}
        />
        {/* Current cost indicator */}
        <div
          className={`absolute top-1/2 -translate-y-1/2 -translate-x-1/2 h-5 w-5 rounded-full border-2 border-white shadow-sm ${colors.indicator}`}
          style={{ left: `${indicatorPct}%` }}
          title={t('costmodel.benchmark_current_cost', {
            defaultValue: 'Current: {{value}}/m\u00B2',
            value: formatCurrencyValue(costPerM2, 'EUR'),
          })}
        />
      </div>

      {/* Legend below bar */}
      <div className="flex items-center justify-between text-2xs text-content-tertiary">
        <span>{formatCurrencyValue(displayMin, 'EUR')}</span>
        <span>{formatCurrencyValue(displayMax, 'EUR')}</span>
      </div>
    </div>
  );
});

/* ── Main Component ───────────────────────────────────────────────────── */

export const CostBenchmark = memo(function CostBenchmark({ totalBudget, currency, initialArea }: CostBenchmarkProps) {
  const { t } = useTranslation();
  const [area, setArea] = useState<string>(initialArea ? String(initialArea) : '');
  const [projectType, setProjectType] = useState<ProjectType>('residential');

  // projectTypeOptions defined at module level as PROJECT_TYPE_OPTIONS — avoids re-allocation on every render

  const areaNum = parseFloat(area);
  const hasValidArea = !isNaN(areaNum) && areaNum > 0;

  const benchmark = useMemo(() => {
    if (!hasValidArea) return null;

    const costPerM2 = totalBudget / areaNum;
    const range = BENCHMARK_RANGES[projectType];
    const status = getBenchmarkStatus(costPerM2, range);

    return { costPerM2, range, status };
  }, [totalBudget, areaNum, hasValidArea, projectType]);

  const statusLabel = useMemo(() => {
    if (!benchmark) return '';
    switch (benchmark.status) {
      case 'within':
        return t('costmodel.benchmark_status_within', { defaultValue: 'Within range' });
      case 'near_edge':
        return t('costmodel.benchmark_status_near_edge', { defaultValue: 'Near boundary' });
      case 'outside':
        return t('costmodel.benchmark_status_outside', { defaultValue: 'Outside range' });
    }
  }, [benchmark, t]);

  return (
    <Card>
      <CardHeader
        title={t('costmodel.benchmark_title', { defaultValue: 'Cost per m\u00B2 Benchmark' })}
      />
      <CardContent>
        <div className="space-y-5">
          {/* Inputs row */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            {/* Project area input */}
            <div>
              <label
                htmlFor="benchmark-area"
                className="block text-xs font-medium text-content-secondary mb-1.5"
              >
                {t('costmodel.benchmark_project_area', { defaultValue: 'Project Area (m\u00B2)' })}
              </label>
              <input
                id="benchmark-area"
                type="number"
                min={1}
                step="any"
                value={area}
                onChange={(e) => setArea(e.target.value)}
                placeholder={t('costmodel.benchmark_area_placeholder', {
                  defaultValue: 'e.g. 1200',
                })}
                className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary placeholder:text-content-tertiary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue tabular-nums"
              />
            </div>

            {/* Project type selector */}
            <div>
              <label
                htmlFor="benchmark-type"
                className="block text-xs font-medium text-content-secondary mb-1.5"
              >
                {t('costmodel.benchmark_project_type', { defaultValue: 'Project Type' })}
              </label>
              <select
                id="benchmark-type"
                value={projectType}
                onChange={(e) => setProjectType(e.target.value as ProjectType)}
                className="w-full rounded-lg border border-border bg-surface-primary px-3 py-2 text-sm text-content-primary focus:border-oe-blue focus:outline-none focus:ring-1 focus:ring-oe-blue"
              >
                {PROJECT_TYPE_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>
                    {t(opt.labelKey, { defaultValue: opt.defaultLabel })}
                  </option>
                ))}
              </select>
            </div>
          </div>

          {/* Results */}
          {hasValidArea && benchmark ? (
            <div className="space-y-4">
              {/* Cost per m² KPI */}
              <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
                {/* Current cost/m² */}
                <div
                  className={`rounded-xl p-4 ${getStatusColor(benchmark.status).bg}`}
                >
                  <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('costmodel.benchmark_cost_per_m2', { defaultValue: 'Cost / m\u00B2' })}
                  </div>
                  <div
                    className={`text-xl font-bold tabular-nums ${getStatusColor(benchmark.status).text}`}
                  >
                    {formatCurrencyValue(benchmark.costPerM2, currency)}
                  </div>
                  <div className="mt-1 flex items-center gap-1.5">
                    <div
                      className={`h-2 w-2 rounded-full ${getStatusColor(benchmark.status).indicator}`}
                    />
                    <span className="text-2xs font-medium text-content-secondary">
                      {statusLabel}
                    </span>
                  </div>
                </div>

                {/* Benchmark range */}
                <div className="rounded-xl bg-surface-secondary p-4">
                  <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('costmodel.benchmark_range_label', { defaultValue: 'Benchmark Range' })}
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-content-primary">
                    {formatCurrencyValue(benchmark.range.min, currency)} &ndash;{' '}
                    {formatCurrencyValue(benchmark.range.max, currency)}
                  </div>
                  <div className="mt-1 text-2xs text-content-tertiary">
                    {t('costmodel.benchmark_per_m2', { defaultValue: 'per m\u00B2' })}
                  </div>
                </div>

                {/* Total budget / area summary */}
                <div className="rounded-xl bg-surface-secondary p-4">
                  <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('costmodel.benchmark_total_budget', { defaultValue: 'Total Budget' })}
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-content-primary">
                    {formatCurrencyValue(totalBudget, currency)}
                  </div>
                  <div className="mt-1 text-2xs text-content-tertiary">
                    {t('costmodel.benchmark_area_value', {
                      defaultValue: '{{area}} m\u00B2',
                      area: areaNum.toLocaleString(),
                    })}
                  </div>
                </div>
              </div>

              {/* Visual range indicator */}
              <RangeIndicator
                costPerM2={benchmark.costPerM2}
                range={benchmark.range}
                status={benchmark.status}
              />
            </div>
          ) : (
            /* Empty state when no area entered */
            <div className="flex flex-col items-center justify-center py-6 text-center">
              <div className="flex h-12 w-12 items-center justify-center rounded-2xl bg-surface-secondary text-content-tertiary mb-3">
                <Ruler size={20} />
              </div>
              <p className="text-sm text-content-secondary">
                {t('costmodel.benchmark_enter_area', {
                  defaultValue:
                    'Enter the project area to see the cost per m\u00B2 benchmark comparison',
                })}
              </p>
            </div>
          )}
        </div>
      </CardContent>
    </Card>
  );
});
