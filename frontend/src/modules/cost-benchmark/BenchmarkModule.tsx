// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useState, useMemo, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { BarChart3, Info, FolderOpen, X, Layers, Lightbulb } from 'lucide-react';
import { ModuleGuideButton } from '@/shared/ui';
import { projectsApi } from '@/features/projects/api';
import { benchmarksGuide } from '@/features/benchmarks/benchmarksGuide';
import {
  BUILDING_TYPES,
  BENCHMARK_REGIONS,
  BENCHMARKS,
  REGION_DRIVERS,
  calculatePercentile,
  splitByCostGroup,
  breakdownByElement,
  comparisonConfidence,
  type BuildingType,
  type BenchmarkRegion,
  type ElementBreakdownRow,
} from './data/benchmarks';
import { useProjectBenchmarkData } from './hooks/useProjectBenchmarkData';
import { fetchOwnPortfolio, type BenchmarkResponse } from './api';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';
import { formatCurrency as formatMoney } from '@/shared/lib/money';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/* ── Helpers ───────────────────────────────────────────────────────── */

/**
 * Whole-unit money for the benchmark tables.
 *
 * Delegates to the shared formatter rather than calling `toLocaleString` with
 * `style: 'currency'` directly. That call raises a RangeError on a blank or
 * malformed code, and every caller here renders inside JSX, so the cost of a
 * bad code was the whole panel rather than one figure. `formatCurrency`
 * validates the code and falls back to a grouped number with no symbol, which
 * is also the policy `money.ts` documents: a euro sign on a non-euro amount
 * misinforms the reader more than a missing symbol does.
 */
function formatCurrency(value: number, currency: string): string {
  return formatMoney(value, currency, getNumberLocale(), {
    maximumFractionDigits: 0,
  });
}

function getPercentileColor(pct: number): string {
  if (pct <= 25) return 'text-semantic-success';
  if (pct <= 50) return 'text-semantic-success';
  if (pct <= 75) return 'text-semantic-warning';
  return 'text-semantic-error';
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
      className: 'text-semantic-success',
    };
  }
  if (level === 'medium') {
    return {
      key: 'benchmarks.conf_medium',
      defaultValue: 'Medium',
      className: 'text-semantic-warning',
    };
  }
  return {
    key: 'benchmarks.conf_low',
    defaultValue: 'Low',
    className: 'text-content-tertiary',
  };
}

/* ── Element breakdown row ─────────────────────────────────────────── */

function ElementRow({
  row,
  max,
  currency,
  barClass,
  rateFactor,
  t,
}: {
  row: ElementBreakdownRow;
  max: number;
  currency: string;
  barClass: string;
  /**
   * Issue #270 - reciprocal area factor (1 metric, 10.7639 imperial). row.value
   * is a "currency per m2" RATE share, so it is divided by the factor for the
   * display system. The bar width uses the raw metric value (value/max), so the
   * geometry is identical in both systems.
   */
  rateFactor: number;
  t: (key: string, opts?: Record<string, unknown>) => string;
}) {
  const widthPct = max > 0 ? (row.value / max) * 100 : 0;
  const label = t(`benchmarks.elem_${row.code}`, { defaultValue: row.label });
  return (
    <div className="flex items-center gap-2 text-xs">
      <span className="w-9 shrink-0 font-mono text-2xs text-content-quaternary">{row.code}</span>
      <span className="w-40 shrink-0 truncate text-content-secondary" title={label}>
        {label}
      </span>
      <div className="relative h-3 flex-1 overflow-hidden rounded-sm bg-surface-secondary">
        <div className={`h-full rounded-sm ${barClass}`} style={{ width: `${widthPct}%` }} />
      </div>
      <span className="w-9 shrink-0 text-right tabular-nums text-content-tertiary">
        {fmtPercent(row.pct * 100, 0)}
      </span>
      <span className="w-20 shrink-0 text-right tabular-nums font-medium text-content-primary">
        {/* RATE (reciprocal): EUR/m2 element share -> EUR/ft2 for imperial */}
        {formatCurrency(row.value / rateFactor, currency)}
      </span>
    </div>
  );
}

/* ── Component ─────────────────────────────────────────────────────── */

export default function BenchmarkModule() {
  const { t } = useTranslation();

  // Issue #270 - every monetary figure on this page is a "currency per m2" RATE
  // (cost/m2, the benchmark quartiles, the KG split, the element shares, the
  // portfolio distribution). For imperial we relabel them per-ft2 and divide by
  // the area factor (reciprocal) so the verdict reads the same way. The GFA
  // INPUT stays metric/editable (m2) and is never converted. metric => factor 1
  // and unit "m2", i.e. byte-identical output to before.
  const q = useDisplayQuantity();
  const rateUnit = q.unitFor('m²');
  const rateFactor = q.convert(1, 'm²').value; // 1 (metric) / 10.7639 (imperial)
  // RATE display helper: reciprocal-convert a "currency per m2" value into the
  // display system (factor 1 for metric => byte-identical). Currency is passed
  // explicitly because the portfolio block can use a different currency.
  const fmtRate = (rate: number, currency: string) => formatCurrency(rate / rateFactor, currency);

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

  // ── Element-level breakdown (DIN 276) of the user's cost/m2 ──────────
  const elementRows = useMemo(
    () => breakdownByElement(analysis.costPerM2, buildingType, benchmarkRange.split),
    [analysis.costPerM2, buildingType, benchmarkRange.split],
  );
  const kg300Rows = useMemo(
    () => elementRows.filter((r) => r.kg === 'KG300').sort((a, b) => b.value - a.value),
    [elementRows],
  );
  const kg400Rows = useMemo(
    () => elementRows.filter((r) => r.kg === 'KG400').sort((a, b) => b.value - a.value),
    [elementRows],
  );
  const maxElementValue = useMemo(() => Math.max(...elementRows.map((r) => r.value), 1), [elementRows]);

  // Plain-language reading inputs.
  const pctLabel = getPercentileLabelKey(analysis.percentile);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex h-10 w-10 items-center justify-center rounded-xl bg-indigo-100 dark:bg-indigo-900/30">
          <BarChart3 className="h-5 w-5 text-indigo-600 dark:text-indigo-400" />
        </div>
        <div className="min-w-0">
          <h1 className="text-xl font-semibold text-content-primary">
            {t('benchmarks.title', { defaultValue: 'Cost Benchmarks' })}
          </h1>
          <p className="text-sm text-content-tertiary">
            {t('benchmarks.subtitle', { defaultValue: 'Compare your estimate against industry benchmarks' })}
          </p>
        </div>
        {/* Guidance cluster. No guided Tour is registered for this module, so
            the "How it works" guide is the single entry point here. It keeps
            the shared pill geometry so it reads like the Tour button on other
            module headers. */}
        <div className="ml-auto flex items-center gap-2">
          <ModuleGuideButton content={benchmarksGuide} />
        </div>
      </div>

      {/* Source line + data-basis honesty note */}
      <div data-guide="benchmarks-source" className="rounded-xl border border-border bg-surface-secondary/40 px-4 py-3">
        <p className="text-xs text-content-tertiary">
          <span className="font-medium text-content-secondary">
            {t('benchmarks.source', { defaultValue: 'Source' })}:
          </span>{' '}
          {benchmarkRange.source} ({benchmarkRange.sourceYear}), {regionInfo.label}, {regionInfo.currency}
        </p>
        <p className="mt-1.5 text-xs text-content-secondary">
          <span className="font-medium">
            {t('benchmarks.why_region', { defaultValue: 'Why {{region}}', region: regionInfo.label })}:
          </span>{' '}
          {t(`benchmarks.driver.${region}`, { defaultValue: REGION_DRIVERS[region] })}
        </p>
        <p className="mt-1 text-xs text-content-quaternary">
          {t('benchmarks.data_basis', {
            defaultValue:
              'These are typical planning benchmarks compiled from the named public sources, not a live feed. The KG split and per-unit figures are typical planning values. Actual costs vary by location, specification and market.',
          })}
        </p>
      </div>

      {/* How these benchmarks work - on-page methodology, collapsed by default.
          The module also has a full guide behind the header button; this makes
          the essentials readable without leaving the page. */}
      <details className="rounded-xl border border-border bg-surface-secondary/40">
        <summary className="cursor-pointer px-4 py-3 text-sm font-medium text-content-primary">
          {t('benchmarks.how.title', { defaultValue: 'How these benchmarks work' })}
        </summary>
        <div className="space-y-3 border-t border-border px-4 py-3 text-xs leading-relaxed text-content-secondary">
          <p>
            {t('benchmarks.how.what', {
              defaultValue:
                'Each figure is a construction cost per m2 of gross floor area (GFA), covering DIN 276 KG300 (building construction) plus KG400 (technical building systems). It is a planning reference, not a live market feed.',
            })}
          </p>
          <p>
            {t('benchmarks.how.read', {
              defaultValue:
                'Enter your floor area and total cost. The module places your cost per m2 on the reference band and reads off a percentile: below the 25th is cost-effective, near the 50th is typical, above the 75th is premium.',
            })}
          </p>
          <p>
            {t('benchmarks.how.quartiles', {
              defaultValue:
                'The band shows five points: the minimum, lower quartile (Q1), median, upper quartile (Q3) and maximum across reference projects. Half of projects sit between Q1 and Q3.',
            })}
          </p>
          <p>
            {t('benchmarks.how.split', {
              defaultValue:
                'The KG300 vs KG400 split and the deeper DIN 276 element breakdown (facade, slabs, HVAC, electrical and so on) show roughly where the money sits for this building type.',
            })}
          </p>
          <p>
            {t('benchmarks.how.confidence', {
              defaultValue:
                'Confidence is high, medium or low, derived from how large the planning sample is, how tight the range is and how recent the source is.',
            })}
          </p>
          <div>
            <p className="mb-1 font-medium text-content-primary">
              {t('benchmarks.how.sources_title', { defaultValue: 'Sources by region' })}
            </p>
            <ul className="space-y-0.5">
              {BENCHMARK_REGIONS.map((r) => (
                <li key={r.id}>
                  <span className="font-medium text-content-primary">{r.label}</span>:{' '}
                  {BENCHMARKS[r.id].office.source} ({r.currency})
                </li>
              ))}
            </ul>
          </div>
        </div>
      </details>

      {/* Input controls */}
      <div data-guide="benchmarks-inputs" className="rounded-xl border border-border bg-surface-primary p-5">
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
          <p className="mb-3 text-xs text-semantic-warning">
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
      <div data-guide="benchmarks-results" className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        {/* Cost per m2 */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.your_cost_unit', { defaultValue: 'Your Cost / {{unit}}', unit: rateUnit })}
          </p>
          <p className="text-2xl font-semibold text-content-primary">
            {/* RATE (reciprocal) */}
            {fmtRate(analysis.costPerM2, regionInfo.currency)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {/* RATE (reciprocal) + per-unit suffix follows the display system */}
            {t('benchmarks.median', { defaultValue: 'Median' })}: {fmtRate(benchmarkRange.median, regionInfo.currency)}/{rateUnit}
          </p>
        </div>

        {/* Percentile vs industry */}
        <div className="rounded-xl border border-border bg-surface-primary p-5">
          <p className="text-xs text-content-tertiary mb-1">
            {t('benchmarks.percentile_industry', { defaultValue: 'Percentile vs Industry' })}
          </p>
          <p className={`text-2xl font-semibold ${getPercentileColor(analysis.percentile)}`}>
            P{fmtFixed(analysis.percentile, 0)}
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
              <p className={`text-2xl font-semibold ${getPercentileColor(percentileVsOwn)}`}>
                P{fmtFixed(percentileVsOwn, 0)}
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
              <p className="text-2xl font-semibold text-content-quaternary">—</p>
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
          <p className={`text-2xl font-semibold ${analysis.diffFromMedian > 0 ? 'text-semantic-error' : 'text-semantic-success'}`}>
            {/* RATE (reciprocal): difference of two EUR/m2 rates is itself EUR/m2 */}
            {analysis.diffFromMedian > 0 ? '+' : ''}{fmtRate(analysis.diffFromMedian, regionInfo.currency)}
          </p>
          <p className="text-xs text-content-tertiary mt-1">
            {/* diffPct is a percentage - passes through unchanged in both systems */}
            {analysis.diffPct > 0 ? '+' : ''}{fmtPercent(analysis.diffPct)} {t('benchmarks.vs_median', { defaultValue: 'vs median' })}
          </p>
        </div>
      </div>

      {/* Plain-language reading: ties the four KPIs together so the page is
          self-explanatory without opening the guide. */}
      <div className="rounded-xl border border-indigo-200 dark:border-indigo-900/40 bg-indigo-50/50 dark:bg-indigo-950/20 p-5">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-indigo-100 dark:bg-indigo-900/40">
            <Lightbulb className="h-4 w-4 text-indigo-600 dark:text-indigo-400" />
          </div>
          <div className="min-w-0 space-y-1.5 text-sm text-content-secondary">
            <p className="font-semibold text-content-primary">
              {t('benchmarks.reading_title', { defaultValue: 'How to read your result' })}
            </p>
            <p>
              {/* RATE interpolations (cost, median) reciprocal-converted; the
                  /unit suffix follows the display system. */}
              {t('benchmarks.reading_position_v2', {
                defaultValue:
                  'At {{cost}}/{{unit}}, your {{type}} in {{region}} sits at P{{pct}} of the {{source}} reference - {{label}}. That is {{sign}}{{diff}}% versus the median of {{median}}/{{unit}}.',
                cost: fmtRate(analysis.costPerM2, regionInfo.currency),
                unit: rateUnit,
                type: buildingInfo.label,
                region: regionInfo.label,
                pct: fmtFixed(analysis.percentile, 0),
                // Not lowercased: the label is a translated string, and casing is
                // not a safe transform across locales. German keeps nouns capital
                // mid-sentence, and Turkish maps I to i rather than the dotless
                // form. It follows a dash here, so sentence case reads correctly.
                label: t(pctLabel.key, { defaultValue: pctLabel.defaultValue }),
                sign: analysis.diffPct > 0 ? '+' : '',
                diff: fmtFixed(analysis.diffPct, 1),
                median: fmtRate(benchmarkRange.median, regionInfo.currency),
                source: benchmarkRange.source,
              })}
            </p>
            <p>
              {/* RATE interpolations (kg300, kg400) reciprocal-converted. */}
              {t('benchmarks.reading_split_v2', {
                defaultValue:
                  'Of that, construction works (KG300) are about {{kg300}}/{{unit}} and technical systems (KG400) about {{kg400}}/{{unit}} - see the element breakdown below for where the money concentrates.',
                kg300: fmtRate(kgSplit.kg300, regionInfo.currency),
                kg400: fmtRate(kgSplit.kg400, regionInfo.currency),
                unit: rateUnit,
              })}
            </p>
            <p className="text-xs text-content-tertiary">
              {t('benchmarks.reading_confidence', {
                defaultValue:
                  'Reference confidence: {{conf}}. Benchmarks are typical planning values from {{source}} ({{year}}), not a live market feed.',
                conf: t(dataConfidence.key, { defaultValue: dataConfidence.defaultValue }),
                source: benchmarkRange.source,
                year: benchmarkRange.sourceYear,
              })}
            </p>
          </div>
        </div>
      </div>

      {/* Visual benchmark bar */}
      <div data-guide="benchmarks-bar" className="rounded-xl border border-border bg-surface-primary p-5">
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
            <div className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-content-primary px-2 py-0.5 text-2xs font-semibold text-white">
              {/* RATE (reciprocal); marker POSITION (markerLeft) stays metric */}
              {fmtRate(analysis.costPerM2, regionInfo.currency)}
            </div>
            <div className="absolute -bottom-1 left-1/2 -translate-x-1/2 h-2 w-2 rotate-45 bg-content-primary" />
          </div>

          {/* Labels below - all RATE (reciprocal) */}
          <div className="flex justify-between mt-2 text-2xs text-content-quaternary">
            <span>{fmtRate(benchmarkRange.min, regionInfo.currency)}</span>
            <span>{t('benchmarks.q1_short', { defaultValue: 'Q1' })}: {fmtRate(benchmarkRange.q1, regionInfo.currency)}</span>
            <span>{t('benchmarks.median', { defaultValue: 'Median' })}: {fmtRate(benchmarkRange.median, regionInfo.currency)}</span>
            <span>{t('benchmarks.q3_short', { defaultValue: 'Q3' })}: {fmtRate(benchmarkRange.q3, regionInfo.currency)}</span>
            <span>{fmtRate(benchmarkRange.max, regionInfo.currency)}</span>
          </div>
        </div>

        {/* Range details table - all RATE (reciprocal) */}
        <div className="mt-4 grid grid-cols-5 gap-2 text-center text-xs">
          <div className="rounded-lg bg-semantic-success-bg p-2">
            <p className="text-content-tertiary">{t('benchmarks.min', { defaultValue: 'Min' })}</p>
            <p className="font-semibold text-content-primary">{fmtRate(benchmarkRange.min, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-semantic-success-bg p-2">
            <p className="text-content-tertiary">{t('benchmarks.q1', { defaultValue: 'Q1 (25th)' })}</p>
            <p className="font-semibold text-content-primary">{fmtRate(benchmarkRange.q1, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-blue-50 dark:bg-blue-950/20 p-2 ring-1 ring-blue-200 dark:ring-blue-800">
            <p className="text-content-tertiary">{t('benchmarks.median', { defaultValue: 'Median' })}</p>
            <p className="font-semibold text-content-primary">{fmtRate(benchmarkRange.median, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-semantic-warning-bg p-2">
            <p className="text-content-tertiary">{t('benchmarks.q3', { defaultValue: 'Q3 (75th)' })}</p>
            <p className="font-semibold text-content-primary">{fmtRate(benchmarkRange.q3, regionInfo.currency)}</p>
          </div>
          <div className="rounded-lg bg-semantic-error-bg p-2">
            <p className="text-content-tertiary">{t('benchmarks.max', { defaultValue: 'Max' })}</p>
            <p className="font-semibold text-content-primary">{fmtRate(benchmarkRange.max, regionInfo.currency)}</p>
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
            {/* The server composes `note` in English and we cannot translate a
                sentence that arrives at render time, so translate the code it
                sends instead and keep the prose as the fallback for a server
                that predates it. */}
            <p className="mb-4 text-xs text-content-tertiary">
              {ownPortfolio.note_code
                ? t(`benchmarks.portfolio_note_${ownPortfolio.note_code}`, {
                    defaultValue: ownPortfolio.note,
                    count: ownPortfolio.project_count,
                  })
                : ownPortfolio.note}
            </p>

            {/* Distribution bar: P25-P75 band with a median tick and your marker */}
            <div className="relative">
              <div className="relative h-4 w-full overflow-hidden rounded-full bg-surface-secondary">
                <div
                  className="absolute h-full rounded-full bg-oe-blue/30"
                  style={{ left: `${pos(pP25)}%`, width: `${Math.max(0, pos(pP75) - pos(pP25))}%` }}
                />
                <div className="absolute h-full w-0.5 bg-oe-blue" style={{ left: `${pos(pMed)}%` }} />
              </div>
              {/* Your value marker - RATE (reciprocal); youPct position stays metric */}
              <div className="absolute top-0 h-4 w-0.5 bg-content-primary" style={{ left: `${youPct}%` }}>
                <div className="absolute -top-6 left-1/2 -translate-x-1/2 whitespace-nowrap rounded bg-content-primary px-2 py-0.5 text-2xs font-semibold text-white">
                  {fmtRate(analysis.costPerM2, cur)}
                </div>
              </div>
              {/* Distribution labels - all RATE (reciprocal) */}
              <div className="mt-2 flex justify-between text-2xs text-content-quaternary">
                <span>{fmtRate(pMin, cur)}</span>
                <span>{t('benchmarks.q1_short', { defaultValue: 'Q1' })}: {fmtRate(pP25, cur)}</span>
                <span>{t('benchmarks.median', { defaultValue: 'Median' })}: {fmtRate(pMed, cur)}</span>
                <span>{t('benchmarks.q3_short', { defaultValue: 'Q3' })}: {fmtRate(pP75, cur)}</span>
                <span>{fmtRate(pMax, cur)}</span>
              </div>
            </div>

            {portfolioQuery.data?.explanation && (
              <p className="mt-3 text-xs font-medium text-content-secondary">
                {portfolioQuery.data.explanation_code
                  ? t(`benchmarks.portfolio_reading_${portfolioQuery.data.explanation_code}`, {
                      defaultValue: portfolioQuery.data.explanation,
                      currency: portfolioQuery.data.currency,
                    })
                  : portfolioQuery.data.explanation}
              </p>
            )}
          </div>
        );
      })()}

      {/* KG300 / KG400 split strip + optional secondary metric */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        {/* KG split strip */}
        <div data-guide="benchmarks-split" className={`rounded-xl border border-border bg-surface-primary p-5 ${buildingInfo.secondaryUnitId ? 'lg:col-span-2' : 'lg:col-span-3'}`}>
          <h3 className="mb-1 text-sm font-semibold text-content-primary">
            {t('benchmarks.kg_split_title_v2', { defaultValue: 'Cost group split of your cost / {{unit}}', unit: rateUnit })}
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
              className="flex items-center justify-center bg-semantic-warning/80 text-2xs font-semibold text-white"
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
              <p className="mt-1 text-base font-semibold text-content-primary">
                {/* RATE (reciprocal) + per-unit suffix follows display system */}
                {fmtRate(kgSplit.kg300, regionInfo.currency)}/{rateUnit}
              </p>
            </div>
            <div className="rounded-lg bg-surface-secondary p-3">
              <div className="flex items-center gap-2">
                <span className="h-2.5 w-2.5 rounded-sm bg-semantic-warning/80" />
                <span className="text-xs font-medium text-content-secondary">
                  {t('benchmarks.kg400', { defaultValue: 'KG400 Technical' })}
                </span>
              </div>
              <p className="mt-1 text-base font-semibold text-content-primary">
                {/* RATE (reciprocal) + per-unit suffix follows display system */}
                {fmtRate(kgSplit.kg400, regionInfo.currency)}/{rateUnit}
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
            <p className="mt-3 text-2xl font-semibold text-content-primary">
              {/* Per-unit rate is "currency per bed/room/pupil/dwelling" - the
                  secondary unit is a COUNT with no metric->imperial mapping, so
                  this value is left canonical (NOT an m2 rate). */}
              {formatCurrency(benchmarkRange.secondary.median, regionInfo.currency)}
            </p>
            <p className="mt-1 text-xs text-content-quaternary">
              {/* areaPerUnit is an ABSOLUTE area (m2 GFA per unit) -> q.convert
                  (multiply) to ft2 for imperial; the unit label follows. */}
              {t('benchmarks.secondary_basis_v2', {
                defaultValue: 'Median basis, about {{area}} {{unit}} GFA per unit.',
                area: q.convert(benchmarkRange.secondary.areaPerUnit, 'm²').value.toLocaleString(getNumberLocale(), { maximumFractionDigits: 0 }),
                unit: rateUnit,
              })}
            </p>
          </div>
        )}
      </div>

      {/* DIN 276 element-level breakdown: one level deeper than KG300/KG400,
          showing where the cost/m2 actually concentrates. */}
      <div className="rounded-xl border border-border bg-surface-primary p-5">
        <div className="mb-1 flex items-center gap-2">
          <Layers className="h-4 w-4 text-content-tertiary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('benchmarks.elements_title', { defaultValue: 'Cost breakdown by DIN 276 element group' })}
          </h3>
        </div>
        <p className="mb-4 text-xs text-content-tertiary">
          {/* RATE interpolation (cost) reciprocal-converted; /unit follows system */}
          {t('benchmarks.elements_hint_v2', {
            defaultValue:
              'Typical planning distribution of your {{cost}}/{{unit}} across DIN 276 element groups for this building type. Indicative shares, not a live feed - use them to see where the budget concentrates.',
            cost: fmtRate(analysis.costPerM2, regionInfo.currency),
            unit: rateUnit,
          })}
        </p>

        <div className="grid grid-cols-1 gap-x-8 gap-y-4 lg:grid-cols-2">
          {/* KG300 column */}
          <div>
            <div className="mb-2 flex items-center justify-between border-b border-border pb-1.5">
              <span className="text-xs font-semibold text-content-secondary">
                {t('benchmarks.kg300', { defaultValue: 'KG300 Construction' })}
              </span>
              <span className="text-xs font-semibold text-content-primary tabular-nums">
                {/* RATE (reciprocal) + per-unit suffix follows display system */}
                {fmtRate(kgSplit.kg300, regionInfo.currency)}/{rateUnit}
              </span>
            </div>
            <div className="space-y-1.5">
              {kg300Rows.map((row) => (
                <ElementRow
                  key={row.code}
                  row={row}
                  max={maxElementValue}
                  currency={regionInfo.currency}
                  barClass="bg-oe-blue/70"
                  rateFactor={rateFactor}
                  t={t}
                />
              ))}
            </div>
          </div>

          {/* KG400 column */}
          <div>
            <div className="mb-2 flex items-center justify-between border-b border-border pb-1.5">
              <span className="text-xs font-semibold text-content-secondary">
                {t('benchmarks.kg400', { defaultValue: 'KG400 Technical' })}
              </span>
              <span className="text-xs font-semibold text-content-primary tabular-nums">
                {/* RATE (reciprocal) + per-unit suffix follows display system */}
                {fmtRate(kgSplit.kg400, regionInfo.currency)}/{rateUnit}
              </span>
            </div>
            <div className="space-y-1.5">
              {kg400Rows.map((row) => (
                <ElementRow
                  key={row.code}
                  row={row}
                  max={maxElementValue}
                  currency={regionInfo.currency}
                  barClass="bg-semantic-warning/70"
                  rateFactor={rateFactor}
                  t={t}
                />
              ))}
            </div>
          </div>
        </div>

        <p className="mt-4 text-2xs text-content-quaternary">
          {t('benchmarks.elements_note_v2', {
            defaultValue:
              'Element shares are typical DIN 276 planning ratios grouped by building profile and sum back to your cost/{{unit}}. Actual splits vary with design, specification and procurement.',
            unit: rateUnit,
          })}
        </p>
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
                  {/* RATE (reciprocal); the Q1-Q3 bar positions stay metric */}
                  {fmtRate(range.median, regionInfo.currency)}
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
            {t('benchmarks.disclaimer_v2', {
              defaultValue:
                'Values represent DIN 276 KG 300+400 (construction plus technical systems) costs per m2 GFA, compiled from recognised public cost sources per region (listed under How these benchmarks work). Actual costs vary by location, specification and market conditions.',
            })}
          </p>
        </div>
      </div>
    </div>
  );
}
