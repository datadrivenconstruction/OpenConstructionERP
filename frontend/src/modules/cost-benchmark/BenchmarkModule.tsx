import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Info, FolderOpen, X } from 'lucide-react';
import { projectsApi } from '@/features/projects/api';
import {
  BUILDING_TYPES,
  BENCHMARK_REGIONS,
  BENCHMARKS,
  calculatePercentile,
  splitByCostGroup,
  comparisonConfidence,
  type BuildingType,
  type BenchmarkRegion,
} from './data/benchmarks';
import { useProjectBenchmarkData } from './hooks/useProjectBenchmarkData';
import { fetchOwnPortfolio, type BenchmarkResponse } from './api';

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

function getConfidenceMeta(level: 'high' | 'medium' | 'low'): {
  key: string;
  defaultValue: string;
  className: string;
} {
  if (level === 'high') {
    return {
      key: 'benchmarks.conf_high',
      defaultValue: 'High',
      className: 'text-emerald-600 dark:text-emerald-400',
    };
  }
  if (level === 'medium') {
    return {
      key: 'benchmarks.conf_medium',
      defaultValue: 'Medium',
      className: 'text-amber-600 dark:text-amber-400',
    };
  }
  return {
    key: 'benchmarks.conf_low',
    defaultValue: 'Low',
    className: 'text-content-tertiary',
  };
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function BenchmarkModule() {
  const { t } = useTranslation();

  const [buildingType, setBuildingType] = useState<BuildingType>('office');
  const [region, setRegion] = useState<BenchmarkRegion>('DE');
  const [gfa, setGfa] = useState(5000);
  const [totalCost, setTotalCost] = useState(13250000);

  // ── Project picker (Phase 2): auto-fill inputs from a real project ──
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);

  // List the tenant's projects. Hidden entirely when the call fails or there
  // are none, so the page behaves exactly as today (manual mode).
  const projectsQuery = useQuery({
    queryKey: ['cost-benchmark', 'projects'],
    queryFn: () => projectsApi.list(),
    staleTime: 60_000,
  });
  const projects = projectsQuery.data ?? [];

  const projectData = useProjectBenchmarkData(selectedProjectId);

  // When a project resolves, auto-fill the four inputs. They stay editable;
  // the user can tweak any value or clear the picker to return to manual mode.
  // GFA is only pre-filled when the project actually records an area.
  useEffect(() => {
    const d = projectData.data;
    if (!d) return;
    setRegion(d.region);
    setBuildingType(d.buildingType);
    if (d.totalCost > 0) setTotalCost(d.totalCost);
    if (d.gfa && d.gfa > 0) setGfa(d.gfa);
  }, [projectData.data]);

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

  // ── Your own portfolio (Phase 3): real distribution from your projects ──
  // The endpoint enriches the page; the static industry table above is the
  // offline fallback. Round the user value so tiny input jitter does not
  // refetch. Any failure resolves to null and only the industry view shows.
  const roundedCostPerM2 = Math.round(analysis.costPerM2);
  const portfolioQuery = useQuery<BenchmarkResponse | null>({
    queryKey: ['cost-benchmark', 'portfolio', buildingType, region, regionInfo.currency, roundedCostPerM2],
    queryFn: () =>
      fetchOwnPortfolio({
        building_type: buildingType,
        region,
        currency: regionInfo.currency,
        cost_per_m2: roundedCostPerM2 > 0 ? roundedCostPerM2 : undefined,
      }),
    staleTime: 30_000,
  });
  const ownPortfolio = portfolioQuery.data?.own_portfolio ?? null;
  const percentileVsOwn = portfolioQuery.data?.percentile_vs_own ?? null;

  // KG300 vs KG400 split of the user's own cost/m2 (sums to the user value).
  const kgSplit = useMemo(
    () => splitByCostGroup(analysis.costPerM2, benchmarkRange.split),
    [analysis.costPerM2, benchmarkRange.split],
  );

  const cmpConfidence = useMemo(() => comparisonConfidence(benchmarkRange), [benchmarkRange]);
  const dataConfidence = getConfidenceMeta(benchmarkRange.confidence);

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

      {/* Source line + data-basis honesty note */}
      <div className="rounded-xl border border-border bg-surface-secondary/40 px-4 py-3">
        <p className="text-xs text-content-tertiary">
          <span className="font-medium text-content-secondary">
            {t('benchmarks.source', { defaultValue: 'Source' })}:
          </span>{' '}
          {benchmarkRange.source} ({benchmarkRange.sourceYear}), {regionInfo.label}, {regionInfo.currency}
        </p>
        <p className="mt-1 text-xs text-content-quaternary">
          {t('benchmarks.data_basis', {
            defaultValue:
              'These are typical planning benchmarks compiled from the named public sources, not a live feed. The KG split and per-unit figures are typical planning values. Actual costs vary by location, specification and market.',
          })}
        </p>
      </div>

      {/* Input controls */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        {/* Project picker (Phase 2): auto-fill from a real project.
            Hidden entirely when the tenant has no projects, so the page
            behaves exactly as the manual-only flow. */}
        {projects.length > 0 && (
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-end">
            <div className="flex-1">
              <label className="mb-1 block text-xs font-medium text-content-tertiary">
                <span className="inline-flex items-center gap-1.5">
                  <FolderOpen className="h-3.5 w-3.5" />
                  {t('benchmarks.pick_project', { defaultValue: 'Compare a project' })}
                </span>
              </label>
              <select
                value={selectedProjectId ?? ''}
                onChange={(e) => setSelectedProjectId(e.target.value || null)}
                className="w-full rounded-lg border border-border bg-surface-secondary px-3 py-2 text-sm text-content-primary"
              >
                <option value="">
                  {t('benchmarks.pick_project_manual', { defaultValue: 'Manual entry' })}
                </option>
                {projects.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}
                  </option>
                ))}
              </select>
            </div>
            {selectedProjectId && (
              <button
                type="button"
                onClick={() => setSelectedProjectId(null)}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-medium text-content-secondary hover:bg-surface-secondary"
              >
                <X className="h-3.5 w-3.5" />
                {t('benchmarks.pick_project_clear', { defaultValue: 'Clear' })}
              </button>
            )}
          </div>
        )}

        {/* Auto-fill hint: when a project is selected but has no recorded
            area, tell the user the area is theirs to enter. */}
        {selectedProjectId && projectData.data && !projectData.data.gfa && (
          <p className="mb-3 text-xs text-amber-600 dark:text-amber-400">
            {t('benchmarks.no_area_hint', {
              defaultValue:
                'This project has no recorded floor area yet. Enter the area below to complete the comparison.',
            })}
          </p>
        )}

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
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
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

        {/* Percentile vs industry */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.percentile_industry', { defaultValue: 'Percentile vs Industry' })}
          </p>
          <p className={`text-2xl font-bold ${getPercentileColor(analysis.percentile)}`}>
            P{analysis.percentile.toFixed(0)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {(() => { const lbl = getPercentileLabelKey(analysis.percentile); return t(lbl.key, { defaultValue: lbl.defaultValue }); })()}
          </p>
        </div>

        {/* Percentile vs your own portfolio (Phase 3). Degrades to a quiet
            placeholder when the tenant has no projects with cost and area. */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.percentile_portfolio', { defaultValue: 'Percentile vs Your Portfolio' })}
          </p>
          {ownPortfolio && percentileVsOwn !== null ? (
            <>
              <p className={`text-2xl font-bold ${getPercentileColor(percentileVsOwn)}`}>
                P{percentileVsOwn.toFixed(0)}
              </p>
              <p className="text-xs text-content-tertiary mt-1">
                {t('benchmarks.portfolio_basis', {
                  defaultValue: 'Across {{count}} of your projects',
                  count: ownPortfolio.project_count,
                })}
              </p>
            </>
          ) : (
            <>
              <p className="text-2xl font-bold text-content-quaternary">—</p>
              <p className="text-xs text-content-tertiary mt-1">
                {portfolioQuery.isLoading
                  ? t('benchmarks.portfolio_loading', { defaultValue: 'Loading your projects...' })
                  : t('benchmarks.portfolio_empty', {
                      defaultValue:
                        'Your portfolio comparison appears once you have projects with both a cost and an area.',
                    })}
              </p>
            </>
          )}
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
          {buildingInfo.label}, {regionInfo.label} ({benchmarkRange.source} {benchmarkRange.sourceYear})
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

      {/* Your own portfolio distribution (Phase 3). Real numbers from your
          projects, shown only when there is enough data. The static industry
          bar above always renders, so an empty portfolio just hides this. */}
      {ownPortfolio && (() => {
        const pMin = Number(ownPortfolio.min);
        const pMax = Number(ownPortfolio.max);
        const pP25 = Number(ownPortfolio.p25);
        const pMed = Number(ownPortfolio.median);
        const pP75 = Number(ownPortfolio.p75);
        const span = pMax - pMin;
        const pos = (v: number) => (span > 0 ? Math.max(0, Math.min(100, ((v - pMin) / span) * 100)) : 50);
        const youPct = pos(analysis.costPerM2);
        const cur = portfolioQuery.data?.currency || regionInfo.currency;
        const confMeta = getConfidenceMeta(ownPortfolio.confidence);
        return (
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('benchmarks.portfolio_title', { defaultValue: 'Your own portfolio distribution' })}
              </h3>
              <span className={`text-xs font-medium ${confMeta.className}`}>
                {t('benchmarks.data_confidence', { defaultValue: 'Data confidence' })}:{' '}
                {t(confMeta.key, { defaultValue: confMeta.defaultValue })}
              </span>
            </div>
            <p className="mb-4 text-xs text-content-tertiary">{ownPortfolio.note}</p>

            {/* Distribution bar: P25-P75 band with a median tick and your marker */}
            <div className="relative">
              <div className="relative h-4 w-full overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="absolute h-full rounded-full bg-oe-blue/30"
                  style={{ left: `${pos(pP25)}%`, width: `${Math.max(0, pos(pP75) - pos(pP25))}%` }}
                />
                <div className="absolute h-full w-0.5 bg-oe-blue" style={{ left: `${pos(pMed)}%` }} />
              </div>
              {/* Your value marker */}
              <div className="absolute top-0 h-4 w-0.5 bg-content-primary" style={{ left: `${youPct}%` }}>
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-content-primary px-2 py-0.5 text-2xs font-bold text-white">
                  {formatCurrency(analysis.costPerM2, cur)}
                </div>
              </div>
              <div className="mt-2 flex justify-between text-2xs text-content-quaternary">
                <span>{formatCurrency(pMin, cur)}</span>
                <span>{t('benchmarks.q1_short', { defaultValue: 'Q1' })}: {formatCurrency(pP25, cur)}</span>
                <span>{t('benchmarks.median', { defaultValue: 'Median' })}: {formatCurrency(pMed, cur)}</span>
                <span>{t('benchmarks.q3_short', { defaultValue: 'Q3' })}: {formatCurrency(pP75, cur)}</span>
                <span>{formatCurrency(pMax, cur)}</span>
              </div>
            </div>

            {portfolioQuery.data?.explanation && (
              <p className="mt-3 text-xs font-medium text-content-secondary">
                {t('benchmarks.portfolio_reading', { defaultValue: portfolioQuery.data.explanation })}
              </p>
            )}
          </div>
        );
      })()}

      {/* KG300 / KG400 split strip + optional secondary metric */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* KG split strip */}
        <div className={`rounded-xl border border-border bg-surface-primary p-5 ${buildingInfo.secondaryUnitId ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          <h3 className="mb-1 text-sm font-semibold text-content-primary">
            {t('benchmarks.kg_split_title', { defaultValue: 'Cost group split of your cost / m2' })}
          </h3>
          <p className="mb-4 text-xs text-content-tertiary">
            {t('benchmarks.kg_split_hint', {
              defaultValue: 'DIN 276 KG300 construction works versus KG400 technical systems, typical split for this type.',
            })}
          </p>

          {/* Two-segment bar */}
          <div className="flex h-9 w-full overflow-hidden rounded-lg" role="img"
            aria-label={t('benchmarks.kg_split_aria', {
              defaultValue: 'KG300 {{kg300}} percent, KG400 {{kg400}} percent',
              kg300: Math.round(benchmarkRange.split.kg300Pct * 100),
              kg400: Math.round(benchmarkRange.split.kg400Pct * 100),
            })}
          >
            <div
              className="flex items-center justify-center bg-oe-blue/80 text-2xs font-semibold text-white"
              style={{ width: `${benchmarkRange.split.kg300Pct * 100}%` }}
            >
              {Math.round(benchmarkRange.split.kg300Pct * 100)}%
            </div>
            <div
              className="flex items-center justify-center bg-amber-500/80 text-2xs font-semibold text-white"
              style={{ width: `${benchmarkRange.split.kg400Pct * 100}%` }}
            >
              {Math.round(benchmarkRange.split.kg400Pct * 100)}%
            </div>
          </div>

          {/* Labels + values */}
          <div className="mt-3 grid grid-cols-2 gap-3">
            <div className="rounded-lg bg-surface-secondary p-3">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-oe-blue/80" />
                <span className="text-xs font-medium text-content-secondary">
                  {t('benchmarks.kg300', { defaultValue: 'KG300 Construction' })}
                </span>
              </div>
              <p className="mt-1 text-base font-bold text-content-primary">
                {formatCurrency(kgSplit.kg300, regionInfo.currency)}/m2
              </p>
            </div>
            <div className="rounded-lg bg-surface-secondary p-3">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-amber-500/80" />
                <span className="text-xs font-medium text-content-secondary">
                  {t('benchmarks.kg400', { defaultValue: 'KG400 Technical' })}
                </span>
              </div>
              <p className="mt-1 text-base font-bold text-content-primary">
                {formatCurrency(kgSplit.kg400, regionInfo.currency)}/m2
              </p>
            </div>
          </div>
        </div>

        {/* Secondary metric card (only when the type defines one) */}
        {buildingInfo.secondaryUnitId && benchmarkRange.secondary && (
          <div className="rounded-xl border border-border bg-surface-primary p-5">
            <h3 className="mb-1 text-sm font-semibold text-content-primary">
              {t('benchmarks.secondary_title', { defaultValue: 'Per-unit benchmark' })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t(`benchmarks.unit_${benchmarkRange.secondary.unitId}`, {
                defaultValue: benchmarkRange.secondary.label,
              })}
            </p>
            <p className="mt-3 text-2xl font-bold text-content-primary">
              {formatCurrency(benchmarkRange.secondary.median, regionInfo.currency)}
            </p>
            <p className="mt-1 text-xs text-content-quaternary">
              {t('benchmarks.secondary_basis', {
                defaultValue: 'Median basis, about {{area}} m2 GFA per unit.',
                area: benchmarkRange.secondary.areaPerUnit,
              })}
            </p>
          </div>
        )}
      </div>

      {/* All building types comparison */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <h3 className="text-sm font-semibold text-content-primary mb-3">
          {t('benchmarks.all_types', { defaultValue: 'All Building Types' })}, {regionInfo.label}
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

      {/* Data and confidence footer */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-quaternary">
              {t('benchmarks.source', { defaultValue: 'Source' })}
            </p>
            <p className="mt-0.5 text-sm font-medium text-content-primary break-words">{benchmarkRange.source}</p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-quaternary">
              {t('benchmarks.year', { defaultValue: 'Year' })}
            </p>
            <p className="mt-0.5 text-sm font-medium text-content-primary">{benchmarkRange.sourceYear}</p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-quaternary">
              {t('benchmarks.sample_size', { defaultValue: 'Planning sample' })}
            </p>
            <p className="mt-0.5 text-sm font-medium text-content-primary">
              {t('benchmarks.sample_count', {
                defaultValue: 'about {{count}} projects',
                count: benchmarkRange.sampleSize,
              })}
            </p>
          </div>
          <div>
            <p className="text-2xs uppercase tracking-wide text-content-quaternary">
              {t('benchmarks.data_confidence', { defaultValue: 'Data confidence' })}
            </p>
            <p className={`mt-0.5 text-sm font-semibold ${dataConfidence.className}`}>
              {t(dataConfidence.key, { defaultValue: dataConfidence.defaultValue })}
            </p>
          </div>
        </div>

        {/* Comparison confidence for the user's entered cost */}
        <div className="mt-4 border-t border-border pt-3">
          <p className="text-xs text-content-tertiary">
            <span className="font-medium text-content-secondary">
              {t('benchmarks.comparison_confidence', { defaultValue: 'Comparison confidence' })}:
            </span>{' '}
            {t(cmpConfidence.key, { defaultValue: cmpConfidence.label })}
          </p>
        </div>

        {/* Standing disclaimer */}
        <div className="mt-3 flex items-start gap-2 text-xs text-content-quaternary">
          <Info className="mt-0.5 h-4 w-4 shrink-0" />
          <p>
            {t('benchmarks.disclaimer', {
              defaultValue:
                'Benchmark data from BKI (DE), Statistik Austria (AT), SIA / BFS (CH), BCIS (UK) and ENR (US). Values represent KG 300+400 (construction plus technical systems) costs per m2 GFA. Actual costs vary by location, specification and market conditions.',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}
