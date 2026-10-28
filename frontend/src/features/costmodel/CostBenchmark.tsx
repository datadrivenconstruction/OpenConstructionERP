// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, memo } from 'react';
import { useTranslation } from 'react-i18next';
import { Ruler } from 'lucide-react';
import { Card, CardHeader, CardContent } from '@/shared/ui';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { getNumberLocale } from '@/stores/usePreferencesStore';

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

/* Module-level constant - keys are stable, labels resolved via t() in JSX */
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
    return new Intl.NumberFormat(getNumberLocale(), {
      style: 'currency',
      currency: safe,
      minimumFractionDigits: 0,
      maximumFractionDigits: 0,
    }).format(amount);
  } catch {
    return `${Number(amount).toFixed(0)} ${safe}`;
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
  currency,
  rateFactor,
  rateUnit,
}: {
  costPerM2: number;
  range: BenchmarkRange;
  status: BenchmarkStatus;
  currency: string;
  /**
   * Issue #270 - reciprocal area factor for the display measurement system
   * (1 for metric, 10.7639 for m2->ft2). Every value rendered here is a
   * "currency per m2" RATE, so the displayed figure is divided by the factor
   * (EUR/m2 -> EUR/ft2) and only the unit label changes. The bar geometry
   * keeps using the raw metric values, so marker/segment positions are
   * identical in both systems.
   */
  rateFactor: number;
  /** Display unit the rates are relabelled to ("m2" / "ft2", superscripted). */
  rateUnit: string;
}) {
  const { t } = useTranslation();
  const colors = getStatusColor(status);

  // RATE display helper: reciprocal-convert a EUR/m2 value into the display
  // system, leaving metric byte-identical (factor === 1).
  const fmtRate = (rate: number) => formatCurrencyValue(rate / rateFactor, currency);

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
          {fmtRate(range.min)}
        </span>
        <span
          className="absolute -translate-x-1/2"
          style={{ left: `${rangeEndPct}%` }}
        >
          {fmtRate(range.max)}
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
          title={t('costmodel.benchmark_current_cost_v2', {
            defaultValue: 'Current: {{value}}/{{unit}}',
            value: fmtRate(costPerM2),
            unit: rateUnit,
          })}
        />
      </div>

      {/* Legend below bar */}
      <div className="flex items-center justify-between text-2xs text-content-tertiary">
        <span>{fmtRate(displayMin)}</span>
        <span>{fmtRate(displayMax)}</span>
      </div>
    </div>
  );
});

/* ── Main Component ───────────────────────────────────────────────────── */

export const CostBenchmark = memo(function CostBenchmark({ totalBudget, currency, initialArea }: CostBenchmarkProps) {
  const { t } = useTranslation();
  const q = useDisplayQuantity();
  const [area, setArea] = useState<string>(initialArea ? String(initialArea) : '');
  const [projectType, setProjectType] = useState<ProjectType>('residential');

  // Issue #270 - the benchmark figures are all "currency per m2" RATES. For an
  // imperial user we relabel them per-ft2 and divide by the area factor so the
  // verdict stays consistent (a cheaper-per-ft2 number reads the same way as a
  // cheaper-per-m2 one). The area INPUT below stays metric/editable (m2): we do
  // not convert it, so its echoed value is also left metric. metric => factor 1
  // and unit "m2", i.e. byte-identical output to before.
  const rateUnit = q.unitFor('m²');
  const rateFactor = q.convert(1, 'm²').value; // 1 (metric) / 10.7639 (imperial)
  const fmtRate = (rate: number) => formatCurrencyValue(rate / rateFactor, currency);

  // projectTypeOptions defined at module level as PROJECT_TYPE_OPTIONS - avoids re-allocation on every render

  const areaNum = parseFloat(area);
  const hasValidArea = !isNaN(areaNum) && areaNum > 0;

  // Benchmark ranges are expressed in EUR/m². If the project uses a different
  // (valid) currency, the pass/fail verdict would be meaningless, so we hide it.
  const isValidCurrency = /^[A-Z]{3}$/.test(currency);
  const currencyMismatch = isValidCurrency && currency !== 'EUR';

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
                  className={`rounded-xl p-4 ${currencyMismatch ? 'bg-surface-secondary' : getStatusColor(benchmark.status).bg}`}
                >
                  <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('costmodel.benchmark_cost_per_unit', { defaultValue: 'Cost / {{unit}}', unit: rateUnit })}
                  </div>
                  <div
                    className={`text-xl font-bold tabular-nums ${currencyMismatch ? 'text-content-primary' : getStatusColor(benchmark.status).text}`}
                  >
                    {/* RATE (reciprocal): EUR/m2 -> EUR/ft2 for imperial */}
                    {fmtRate(benchmark.costPerM2)}
                  </div>
                  {!currencyMismatch && (
                    <div className="mt-1 flex items-center gap-1.5">
                      <div
                        className={`h-2 w-2 rounded-full ${getStatusColor(benchmark.status).indicator}`}
                      />
                      <span className="text-2xs font-medium text-content-secondary">
                        {statusLabel}
                      </span>
                    </div>
                  )}
                </div>

                {/* Benchmark range \u2014 only meaningful when the project currency matches the band */}
                {!currencyMismatch && (
                  <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
                    <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                      {t('costmodel.benchmark_range_label', { defaultValue: 'Benchmark Range' })}
                    </div>
                    <div className="text-sm font-semibold tabular-nums text-content-primary">
                      {/* RATE (reciprocal): benchmark band is EUR/m2 -> EUR/ft2 for imperial */}
                      {fmtRate(benchmark.range.min)}{' '}
                      {t('costmodel.benchmark_range_to', { defaultValue: 'to' })}{' '}
                      {fmtRate(benchmark.range.max)}
                    </div>
                    <div className="mt-1 text-2xs text-content-tertiary">
                      {/* Reuse the already-translated parametrized key so the
                          unit follows the measurement system in every locale. */}
                      {t('costs.per_unit', { defaultValue: 'per {{unit}}', unit: rateUnit })}
                    </div>
                  </div>
                )}

                {/* Total budget / area summary */}
                <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
                  <div className="text-2xs font-medium uppercase tracking-wider text-content-tertiary mb-1">
                    {t('costmodel.benchmark_total_budget', { defaultValue: 'Total Budget' })}
                  </div>
                  <div className="text-sm font-semibold tabular-nums text-content-primary">
                    {formatCurrencyValue(totalBudget, currency)}
                  </div>
                  <div className="mt-1 text-2xs text-content-tertiary">
                    {/* ABSOLUTE area, but left metric on purpose: it echoes the
                        m2 value the user typed into the (non-converted, editable)
                        area input above, so relabelling it to ft2 here would
                        contradict the number they entered. */}
                    {t('costmodel.benchmark_area_value', {
                      defaultValue: '{{area}} m\u00B2',
                      area: areaNum.toLocaleString(getNumberLocale()),
                    })}
                  </div>
                </div>
              </div>

              {/* Visual range indicator - hidden for non-EUR currencies (bands are EUR) */}
              {currencyMismatch ? (
                <p className="text-2xs text-content-tertiary">
                  {t('costmodel.benchmark_no_currency_band', {
                    defaultValue:
                      'No benchmark range for {{currency}} - showing cost per {{unit}} only. Benchmark ranges are available in EUR.',
                    currency,
                    unit: rateUnit,
                  })}
                </p>
              ) : (
                <RangeIndicator
                  costPerM2={benchmark.costPerM2}
                  range={benchmark.range}
                  status={benchmark.status}
                  currency={currency}
                  rateFactor={rateFactor}
                  rateUnit={rateUnit}
                />
              )}
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
