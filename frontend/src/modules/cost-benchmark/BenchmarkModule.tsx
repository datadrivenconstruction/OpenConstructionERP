import { useState, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { BarChart3, Info } from 'lucide-react';
import {
  BUILDING_TYPES,
  BENCHMARK_REGIONS,
  BENCHMARKS,
  calculatePercentile,
  type BuildingType,
  type BenchmarkRegion,
} from './data/benchmarks';

/* ── Helpers ───────────────────────────────────────────────────────── */

function formatCurrency(value: number, currency: string): string {
  return value.toLocaleString('en', {
    style: 'currency',
    currency,
    maximumFractionDigits: 0,
  });
}

function getPercentileColor(pct: number): string {
  if (pct <= 25) return 'text-emerald-600 dark:text-emerald-400';
  if (pct <= 50) return 'text-green-600 dark:text-green-400';
  if (pct <= 75) return 'text-amber-600 dark:text-amber-400';
  return 'text-red-600 dark:text-red-400';
}

function getPercentileLabelKey(pct: number): { key: string; defaultValue: string } {
  if (pct <= 25) return { key: 'benchmarks.pct_below_avg', defaultValue: 'Below average (cost-effective)' };
  if (pct <= 50) return { key: 'benchmarks.pct_below_median', defaultValue: 'Below median' };
  if (pct <= 75) return { key: 'benchmarks.pct_above_median', defaultValue: 'Above median' };
  return { key: 'benchmarks.pct_above_avg', defaultValue: 'Above average (premium)' };
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function BenchmarkModule() {
  const { t } = useTranslation();

  const [buildingType, setBuildingType] = useState<BuildingType>('office');
  const [region, setRegion] = useState<BenchmarkRegion>('DE');
  const [gfa, setGfa] = useState(5000);
  const [totalCost, setTotalCost] = useState(13250000);

  const regionInfo = BENCHMARK_REGIONS.find((r) => r.id === region)!;
  const buildingInfo = BUILDING_TYPES.find((b) => b.id === buildingType)!;
  const benchmarkRange = BENCHMARKS[region][buildingType];

  const analysis = useMemo(() => {
    const costPerM2 = gfa > 0 ? totalCost / gfa : 0;
    const percentile = calculatePercentile(costPerM2, benchmarkRange);
    const diffFromMedian = costPerM2 - benchmarkRange.median;
    const diffPct = benchmarkRange.median > 0 ? (diffFromMedian / benchmarkRange.median) * 100 : 0;
    return { costPerM2, percentile, diffFromMedian, diffPct };
  }, [totalCost, gfa, benchmarkRange]);

  // Percentile marker position (for the visual bar)
  const markerLeft = useMemo(() => {
    const range = benchmarkRange.max - benchmarkRange.min;
    if (range <= 0) return 50;
    const pos = ((analysis.costPerM2 - benchmarkRange.min) / range) * 100;
    return Math.max(0, Math.min(100, pos));
  }, [analysis.costPerM2, benchmarkRange]);

  // Quartile widths for the colored bar segments
  const segments = useMemo(() => {
    const range = benchmarkRange.max - benchmarkRange.min;
    if (range <= 0) return { q1W: 25, q2W: 25, q3W: 25, q4W: 25 };
    return {
      q1W: ((benchmarkRange.q1 - benchmarkRange.min) / range) * 100,
      q2W: ((benchmarkRange.median - benchmarkRange.q1) / range) * 100,
      q3W: ((benchmarkRange.q3 - benchmarkRange.median) / range) * 100,
      q4W: ((benchmarkRange.max - benchmarkRange.q3) / range) * 100,
    };
  }, [benchmarkRange]);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100 dark:bg-indigo-900/30">
          <BarChart3 className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
        </div>
        <div>
          <h1 className="text-xl font-bold text-content-primary">
            {t('benchmarks.title', { defaultValue: 'Cost Benchmarks' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('benchmarks.subtitle', { defaultValue: 'Compare your estimate against industry benchmarks' })}
          </p>
        </div>
      </div>

      {/* Input controls */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Building type */}
          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('benchmarks.building_type', { defaultValue: 'Building Type' })}
            </label>
            <select
              value={buildingType}
              onChange={(e) => setBuildingType(e.target.value as BuildingType)}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
            >
              {BUILDING_TYPES.map((bt) => (
                <option key={bt.id} value={bt.id}>{bt.label}</option>
              ))}
            </select>
          </div>

          {/* Region */}
          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('benchmarks.region', { defaultValue: 'Region' })}
            </label>
            <select
              value={region}
              onChange={(e) => setRegion(e.target.value as BenchmarkRegion)}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
            >
              {BENCHMARK_REGIONS.map((r) => (
                <option key={r.id} value={r.id}>{r.label} ({r.currency})</option>
              ))}
            </select>
          </div>

          {/* GFA */}
          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('benchmarks.gfa', { defaultValue: 'Gross Floor Area (m2)' })}
            </label>
            <input
              type="number"
              value={gfa}
              onChange={(e) => setGfa(Number(e.target.value) || 0)}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
            />
          </div>

          {/* Total cost */}
          <div>
            <label className="block text-xs font-medium text-content-tertiary mb-1">
              {t('benchmarks.total_cost', { defaultValue: 'Your Total Cost' })} ({regionInfo.currency})
            </label>
            <input
              type="number"
              value={totalCost}
              onChange={(e) => setTotalCost(Number(e.target.value) || 0)}
              className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
            />
          </div>
        </div>
      </div>

      {/* Results */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {/* Cost per m2 */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.your_cost_m2', { defaultValue: 'Your Cost / m2' })}
          </p>
          <p className="text-2xl font-bold text-content-primary">
            {formatCurrency(analysis.costPerM2, regionInfo.currency)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {t('benchmarks.median', { defaultValue: 'Median' })}: {formatCurrency(benchmarkRange.median, regionInfo.currency)}/m2
          </p>
        </div>

        {/* Percentile */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.percentile', { defaultValue: 'Percentile Position' })}
          </p>
          <p className={`text-2xl font-bold ${getPercentileColor(analysis.percentile)}`}>
            P{analysis.percentile.toFixed(0)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {(() => { const lbl = getPercentileLabelKey(analysis.percentile); return t(lbl.key, { defaultValue: lbl.defaultValue }); })()}
          </p>
        </div>

        {/* Diff from median */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.diff_median', { defaultValue: 'Difference from Median' })}
          </p>
          <p className={`text-2xl font-bold ${analysis.diffFromMedian > 0 ? 'text-red-600' : 'text-emerald-600'}`}>
            {analysis.diffFromMedian > 0 ? '+' : ''}{formatCurrency(analysis.diffFromMedian, regionInfo.currency)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {analysis.diffPct > 0 ? '+' : ''}{analysis.diffPct.toFixed(1)}% {t('benchmarks.vs_median', { defaultValue: 'vs median' })}
          </p>
        </div>
      </div>

      {/* Visual benchmark bar */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-4">
          {buildingInfo.label} — {regionInfo.label} ({benchmarkRange.source})
        </h3>

        {/* Bar chart */}
        <div className="relative">
          {/* Colored segments */}
          <div className="flex h-8 rounded-lg overflow-hidden">
            <div className="bg-emerald-400 dark:bg-emerald-600" style={{ width: `${segments.q1W}%` }} />
            <div className="bg-green-400 dark:bg-green-600" style={{ width: `${segments.q2W}%` }} />
            <div className="bg-amber-400 dark:bg-amber-600" style={{ width: `${segments.q3W}%` }} />
            <div className="bg-red-400 dark:bg-red-600" style={{ width: `${segments.q4W}%` }} />
          </div>

          {/* Marker */}
          <div
            className="absolute top-0 h-8 w-0.5 bg-content-primary"
            style={{ left: `${markerLeft}%` }}
          >
            <div className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-content-primary px-2 py-0.5 text-2xs font-bold text-white">
              {formatCurrency(analysis.costPerM2, regionInfo.currency)}
            </div>
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 h-2 w-2 rotate-45 bg-content-primary" />
          </div>

          {/* Labels below */}
          <div className="flex justify-between mt-2 text-2xs text-content-quaternary">
            <span>{formatCurrency(benchmarkRange.min, regionInfo.currency)}</span>
            <span>{t('benchmarks.q1_short', { defaultValue: 'Q1' })}: {formatCurrency(benchmarkRange.q1, regionInfo.currency)}</span>
            <span>{t('benchmarks.median', { defaultValue: 'Median' })}: {formatCurrency(benchmarkRange.median, regionInfo.currency)}</span>
            <span>{t('benchmarks.q3_short', { defaultValue: 'Q3' })}: {formatCurrency(benchmarkRange.q3, regionInfo.currency)}</span>
            <span>{formatCurrency(benchmarkRange.max, regionInfo.currency)}</span>
          </div>
        </div>

        {/* Range details table */}
        <div className="mt-4 grid grid-cols-5 gap-2 text-center text-xs">
          <div className="rounded-lg bg-emerald-50 dark:bg-emerald-950/20 p-2">
            <p className="text-content-tertiary">{t('benchmarks.min', { defaultValue: 'Min' })}</p>
            <p className="font-semibold text-content-primary">{formatCurrency(benchmarkRange.min, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-green-50 dark:bg-green-950/20 p-2">
            <p className="text-content-tertiary">{t('benchmarks.q1', { defaultValue: 'Q1 (25th)' })}</p>
            <p className="font-semibold text-content-primary">{formatCurrency(benchmarkRange.q1, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 p-2 ring-1 ring-blue-200 dark:ring-blue-800">
            <p className="text-content-tertiary">{t('benchmarks.median', { defaultValue: 'Median' })}</p>
            <p className="font-bold text-content-primary">{formatCurrency(benchmarkRange.median, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-amber-50 dark:bg-amber-950/20 p-2">
            <p className="text-content-tertiary">{t('benchmarks.q3', { defaultValue: 'Q3 (75th)' })}</p>
            <p className="font-semibold text-content-primary">{formatCurrency(benchmarkRange.q3, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-red-50 dark:bg-red-950/20 p-2">
            <p className="text-content-tertiary">{t('benchmarks.max', { defaultValue: 'Max' })}</p>
            <p className="font-semibold text-content-primary">{formatCurrency(benchmarkRange.max, regionInfo.currency)}</p>
          </div>
        </div>
      </div>

      {/* All building types comparison */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('benchmarks.all_types', { defaultValue: 'All Building Types' })} — {regionInfo.label}
        </h3>
        <div className="space-y-2">
          {BUILDING_TYPES.map((bt) => {
            const range = BENCHMARKS[region][bt.id];
            const isSelected = bt.id === buildingType;
            return (
              <button
                key={bt.id}
                onClick={() => setBuildingType(bt.id)}
                className={`w-full flex items-center gap-3 rounded-lg px-3 py-2 text-left transition-all ${
                  isSelected ? 'bg-oe-blue/10 ring-1 ring-oe-blue' : 'hover:bg-surface-secondary'
                }`}
                aria-pressed={isSelected}
                aria-label={t('benchmarks.select_type', { defaultValue: 'Select {{type}}', type: bt.label })}
              >
                <span className="w-44 text-sm text-content-primary truncate">{bt.label}</span>
                <div className="flex-1 h-4 bg-surface-secondary rounded-full overflow-hidden relative">
                  {/* Q1-Q3 range bar */}
                  <div
                    className="absolute h-full bg-oe-blue/30 rounded-full"
                    style={{
                      left: `${((range.q1 - range.min) / (range.max - range.min)) * 100}%`,
                      width: `${((range.q3 - range.q1) / (range.max - range.min)) * 100}%`,
                    }}
                  />
                  {/* Median marker */}
                  <div
                    className="absolute h-full w-0.5 bg-oe-blue"
                    style={{ left: `${((range.median - range.min) / (range.max - range.min)) * 100}%` }}
                  />
                </div>
                <span className="w-24 text-right text-xs font-mono text-content-tertiary">
                  {formatCurrency(range.median, regionInfo.currency)}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Data source disclaimer */}
      <div className="flex items-start gap-2 text-xs text-content-quaternary">
        <Info className="h-4 w-4 mt-0.5 shrink-0" />
        <p>
          {t('benchmarks.disclaimer', {
            defaultValue: 'Benchmark data from BKI (DE), BCIS (UK), ENR (US), Stat. Austria (AT), SIA/BFS (CH). Values represent KG 300+400 (construction + technical systems) costs per m2 GFA. Actual costs vary by location, specification, and market conditions.',
          })}
        </p>
      </div>
    </div>
  );
}
