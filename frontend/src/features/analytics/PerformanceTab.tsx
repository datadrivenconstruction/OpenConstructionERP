// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Analytics -> Performance: pick projects, pick one KPI, compare what was
// actually achieved. Standalone on purpose - it needs no open estimate - and
// read from the same benchmark endpoint an estimating screen can use later.
//
// Three rules from the backend are visible here and must stay visible: a
// missing value reads "Unavailable" with its reason and is never drawn as 0,
// each unit or currency is its own block unless compatible units are
// converted (and then every conversion is printed), and the leading figure
// says which statistic it is.
//
// A benchmark set is the screen's controls saved under a name: loading one
// fills the controls, saving stores them. The figures are always computed
// fresh, over what the reader may open.
//
// A split (client, region, work type by classification, ...) turns each value
// into its own block. Money can be restated in one reporting currency with the
// platform's FX rates; the original value and the rate stay on every row. Each
// value opens the records behind it, and the comparison below reads several
// KPIs side by side for export.

import { useCallback, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  Download,
  Gauge,
  ListTree,
  Plus,
  RefreshCw,
  Save,
  Scale,
  Search,
  SlidersHorizontal,
  Trash2,
} from 'lucide-react';
import { Badge, Button, Card, ConfirmDialog, EmptyState, Skeleton } from '@/shared/ui';
import { fmtList, fmtNumber, fmtPercent } from '@/shared/lib/formatters';
import { compareNames } from '@/shared/lib/collator';
import { useToastStore } from '@/stores/useToastStore';
import { listKpis } from '@/features/bi-dashboards/api';
import { fetchSeries, listLocationFactors, listSeries } from '@/features/price-index/api';
import { CustomKpiModal } from '@/features/bi-dashboards/CustomKpiModal';
import { useProjectStatusLabel } from '@/features/projects/ProjectStatusBadge';
import { PerformanceCompare } from './PerformanceCompare';
import { PerformanceDataQuality } from './PerformanceDataQuality';
import { PerformanceDrilldown, type DrillTarget } from './PerformanceDrilldown';
import { fmtValue, fmtVariance, prettyUnit } from './performanceFormat';
import {
  DEFAULT_READING,
  EMPTY_COHORT,
  NULL_GROUP_KEY,
  activeFilterCount,
  buildPerformanceCsv,
  checkAgainstCohort,
  classificationFilter,
  classificationRowFilters,
  createBenchmarkSet,
  deleteBenchmarkSet,
  downloadCsv,
  fetchBenchmarkSets,
  fetchCohortOptions,
  fetchPerformanceBenchmark,
  fetchPerformancePresets,
  pickKpi,
  rangeBand,
  sortTableRows,
  tableRows,
  toNumber,
  updateBenchmarkSet,
  type BenchmarkCohort,
  type BenchmarkSet,
  type BenchmarkStatistic,
  type BenchmarkSetWrite,
  type PerformanceBenchmarkRequest,
  type PerformanceCheckResponse,
  type PerformanceBenchmarkResponse,
  type PerformanceGroup,
  type PerformanceProjectRow,
  type RowSort,
} from './performance';

export interface PerformanceTabProject {
  id: string;
  name: string;
}

const DEFAULT_KPI = 'labour_hours_per_installed_unit';
const STATISTICS: BenchmarkStatistic[] = ['weighted', 'mean', 'median'];

const inputClass =
  'h-8 rounded-lg border border-border-light bg-surface-primary px-2 text-xs text-content-primary focus:outline-none focus:ring-1 focus:ring-oe-blue';

/** The select value standing for "split by a classification key", whose key is typed beside it. */
const CLASSIFICATION_SPLIT = '__classification__';
const CLASS_PREFIX = 'classification.';
const CURRENCY_RE = /^[A-Z]{3}$/;
const CLASS_KEY_RE = /^[A-Za-z][A-Za-z0-9_]{0,63}$/;

export function PerformanceTab({ projects }: { projects: PerformanceTabProject[] }) {
  const { t } = useTranslation();
  const qc = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);

  const [kpi, setKpi] = useState(DEFAULT_KPI);
  const [selected, setSelected] = useState<string[]>([]);
  const [filter, setFilter] = useState('');
  const [clients, setClients] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [projectTypes, setProjectTypes] = useState<string[]>([]);
  const [classKey, setClassKey] = useState('');
  const [classCode, setClassCode] = useState('');
  const [periodStart, setPeriodStart] = useState('');
  const [periodEnd, setPeriodEnd] = useState('');
  const [convertUnits, setConvertUnits] = useState(DEFAULT_READING.convert_units);
  const [minProjects, setMinProjects] = useState(DEFAULT_READING.min_projects);
  const [statistic, setStatistic] = useState<BenchmarkStatistic>(DEFAULT_READING.statistic);
  const [showMore, setShowMore] = useState(false);
  const [activeSetId, setActiveSetId] = useState('');
  const [saveOpen, setSaveOpen] = useState(false);
  const [saveName, setSaveName] = useState('');
  const [saveShared, setSaveShared] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [statuses, setStatuses] = useState<string[]>([]);
  const [splitBy, setSplitBy] = useState('');
  const [reportingCurrency, setReportingCurrency] = useState('');
  const [indexSeriesId, setIndexSeriesId] = useState('');
  const [indexPeriod, setIndexPeriod] = useState('');
  const [indexRegion, setIndexRegion] = useState('');
  const [minRecords, setMinRecords] = useState(DEFAULT_READING.min_records);
  const [drill, setDrill] = useState<DrillTarget | null>(null);
  const [kpiModalOpen, setKpiModalOpen] = useState(false);
  const statusLabel = useProjectStatusLabel();

  const customKpisQuery = useQuery({
    queryKey: ['bi', 'kpis', 'for-benchmark'],
    queryFn: () => listKpis(),
    staleTime: 60_000,
  });
  // Only KPIs defined by a spec can be benchmarked; the built-in library is computed differently.
  const customKpis = useMemo(
    () => (customKpisQuery.data ?? []).filter((k) => k.formula_ref === 'spec'),
    [customKpisQuery.data],
  );

  const presetsQuery = useQuery({
    queryKey: ['analytics', 'performance', 'presets'],
    queryFn: fetchPerformancePresets,
    staleTime: 5 * 60_000,
  });
  const optionsQuery = useQuery({
    queryKey: ['analytics', 'performance', 'cohort-options'],
    queryFn: fetchCohortOptions,
    staleTime: 5 * 60_000,
  });
  // The price index register, read only once the person opens the extra options.
  const seriesQuery = useQuery({
    queryKey: ['price-index', 'series'],
    queryFn: listSeries,
    enabled: showMore,
    staleTime: 5 * 60_000,
  });
  const seriesDetailQuery = useQuery({
    queryKey: ['price-index', 'series', indexSeriesId],
    queryFn: () => fetchSeries(indexSeriesId),
    enabled: showMore && Boolean(indexSeriesId),
    staleTime: 5 * 60_000,
  });
  const regionsQuery = useQuery({
    queryKey: ['price-index', 'location-factors'],
    queryFn: listLocationFactors,
    enabled: showMore,
    staleTime: 5 * 60_000,
  });
  const indexPeriods = useMemo(
    () => [...new Set((seriesDetailQuery.data?.points ?? []).map((p) => p.period))].sort().reverse(),
    [seriesDetailQuery.data],
  );
  const setsQuery = useQuery({
    queryKey: ['analytics', 'performance', 'benchmark-sets'],
    queryFn: fetchBenchmarkSets,
  });
  const sets = useMemo(() => setsQuery.data?.items ?? [], [setsQuery.data]);
  const activeSet = sets.find((s) => s.id === activeSetId) ?? null;

  const cohort: BenchmarkCohort = useMemo(
    () => ({
      project_ids: [...selected].sort(),
      clients,
      regions,
      project_types: projectTypes,
      statuses,
      row_filters: classificationRowFilters(classKey, classCode),
      period_start: periodStart || null,
      period_end: periodEnd || null,
    }),
    [selected, clients, regions, projectTypes, statuses, classKey, classCode, periodStart, periodEnd],
  );
  // A half-typed split key or currency is not sent: the screen keeps reading the last valid one.
  const splitKey = splitBy.startsWith(CLASS_PREFIX) ? splitBy.slice(CLASS_PREFIX.length) : '';
  const validSplit = splitBy.startsWith(CLASS_PREFIX) ? (CLASS_KEY_RE.test(splitKey) ? splitBy : null) : splitBy || null;
  const currency = reportingCurrency.trim().toUpperCase();
  const validCurrency = CURRENCY_RE.test(currency) ? currency : null;
  const request: PerformanceBenchmarkRequest = useMemo(
    () => ({
      ...cohort,
      kpi,
      convert_units: convertUnits,
      min_projects: minProjects,
      min_records: minRecords,
      statistic,
      split_by: validSplit,
      reporting_currency: validCurrency,
      index_series_id: indexSeriesId || null,
      index_target_period: indexSeriesId && indexPeriod ? indexPeriod : null,
      location_target_region: indexRegion || null,
    }),
    [
      cohort,
      kpi,
      convertUnits,
      minProjects,
      minRecords,
      statistic,
      validSplit,
      validCurrency,
      indexSeriesId,
      indexPeriod,
      indexRegion,
    ],
  );

  const benchmarkQuery = useQuery({
    queryKey: ['analytics', 'performance', 'benchmark', request],
    queryFn: () => fetchPerformanceBenchmark(request),
    enabled: Boolean(kpi),
  });

  const loadSet = (id: string) => {
    setActiveSetId(id);
    const set = sets.find((s) => s.id === id);
    if (!set) return;
    const c = { ...EMPTY_COHORT, ...set.cohort };
    const cls = classificationFilter(c);
    setKpi((current) => pickKpi(current, set.kpis));
    setSelected(c.project_ids);
    setClients(c.clients);
    setRegions(c.regions);
    setProjectTypes(c.project_types);
    setStatuses(c.statuses ?? []);
    setClassKey(cls.key);
    setClassCode(cls.code);
    setPeriodStart(c.period_start ?? '');
    setPeriodEnd(c.period_end ?? '');
    setConvertUnits(set.convert_units);
    setMinProjects(set.min_projects);
    setMinRecords(set.min_records);
    setStatistic(set.statistic);
    setSplitBy(set.split_by ?? '');
    setReportingCurrency(set.reporting_currency ?? '');
  };

  const definition = (name: string, scope: 'personal' | 'shared', kpis: string[]): BenchmarkSetWrite => ({
    name,
    scope,
    kpis,
    cohort,
    convert_units: convertUnits,
    min_projects: minProjects,
    min_records: minRecords,
    statistic,
    split_by: validSplit,
    reporting_currency: validCurrency,
  });

  const onError = (err: unknown) =>
    addToast({
      type: 'error',
      title: t('analytics.perf.set_save_failed', { defaultValue: 'Could not save the benchmark set' }),
      message: err instanceof Error ? err.message : String(err),
    });

  const createMut = useMutation({
    mutationFn: (body: BenchmarkSetWrite) => createBenchmarkSet(body),
    onSuccess: (created) => {
      qc.invalidateQueries({ queryKey: ['analytics', 'performance', 'benchmark-sets'] });
      setActiveSetId(created.id);
      setSaveOpen(false);
      setSaveName('');
      addToast({
        type: 'success',
        title: t('analytics.perf.set_saved', { defaultValue: 'Benchmark set saved' }),
        message: created.name,
      });
    },
    onError,
  });
  const updateMut = useMutation({
    mutationFn: (set: BenchmarkSet) => {
      const kpis = set.kpis.includes(kpi) ? set.kpis : [...set.kpis, kpi].slice(0, 8);
      // An empty string clears a saved split or currency; null would leave it as it was.
      const body = {
        ...definition(set.name, set.scope, kpis),
        split_by: validSplit ?? '',
        reporting_currency: validCurrency ?? '',
      };
      return updateBenchmarkSet(set.id, body);
    },
    onSuccess: (updated) => {
      qc.invalidateQueries({ queryKey: ['analytics', 'performance', 'benchmark-sets'] });
      addToast({
        type: 'success',
        title: t('analytics.perf.set_saved', { defaultValue: 'Benchmark set saved' }),
        message: updated.name,
      });
    },
    onError,
  });
  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteBenchmarkSet(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['analytics', 'performance', 'benchmark-sets'] });
      setActiveSetId('');
      setConfirmDelete(false);
    },
    onError,
  });

  const sortedProjects = useMemo(
    () => [...projects].sort((a, b) => compareNames(a.name, b.name)),
    [projects],
  );
  const visibleProjects = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return q ? sortedProjects.filter((p) => p.name.toLowerCase().includes(q)) : sortedProjects;
  }, [sortedProjects, filter]);

  const toggle = (id: string) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]));
  const selectShown = () => setSelected((prev) => Array.from(new Set([...prev, ...visibleProjects.map((p) => p.id)])));

  const kpiLabel = useCallback(
    (key: string) => {
      const custom = customKpis.find((k) => k.code === key);
      return custom ? custom.name : t(`analytics.perf.kpi.${key}`, { defaultValue: key });
    },
    [t, customKpis],
  );
  const splitLabel = useCallback(
    (name: string) =>
      name.startsWith(CLASS_PREFIX)
        ? t('analytics.perf.split.classification_key', {
            defaultValue: 'Work type ({{key}})',
            key: name.slice(CLASS_PREFIX.length),
          })
        : t(`analytics.perf.split.${name}`, { defaultValue: name }),
    [t],
  );
  const statisticLabel = useCallback(
    (s: BenchmarkStatistic) =>
      t(`analytics.perf.stat.${s}`, {
        defaultValue: s === 'weighted' ? 'Weighted (sum over sum)' : s === 'mean' ? 'Average of projects' : 'Median',
      }),
    [t],
  );
  const reasonLabel = useCallback(
    (reason: string | null) =>
      t(`analytics.perf.reason.${reason ?? 'no_data'}`, {
        defaultValue: t('analytics.perf.unavailable', { defaultValue: 'Unavailable' }),
      }),
    [t],
  );
  const groupLabel = useCallback(
    (group: PerformanceGroup) => {
      const parts = Object.entries(group.dimensions).map(([name, value]) =>
        value === null || value === NULL_GROUP_KEY || value === ''
          ? t(`analytics.perf.dim_unset.${name}`, {
              defaultValue: t('analytics.perf.dim_unset_generic', { defaultValue: 'not set' }),
            })
          : name === 'unit'
            ? prettyUnit(value)
            : name === 'status'
              ? statusLabel(value)
              : value,
      );
      return parts.length ? parts.join(' / ') : t('analytics.perf.no_dimension', { defaultValue: 'All rows' });
    },
    [t, statusLabel],
  );

  const data = benchmarkQuery.data;
  const handleExport = useCallback(() => {
    if (!data || !data.groups.length) return;
    const csv = buildPerformanceCsv(data, {
      group: t('analytics.perf.col_group', { defaultValue: 'Group' }),
      project: t('analytics.perf.col_project', { defaultValue: 'Project' }),
      value: t('analytics.perf.col_value', { defaultValue: 'Value' }),
      numerator: t('analytics.perf.col_numerator', { defaultValue: 'Numerator' }),
      denominator: t('analytics.perf.col_denominator', { defaultValue: 'Denominator' }),
      records: t('analytics.perf.col_records', { defaultValue: 'Records' }),
      status: t('analytics.perf.col_status', { defaultValue: 'Status' }),
      weighted: t('analytics.perf.weighted', { defaultValue: 'Weighted benchmark' }),
      median: t('analytics.perf.median', { defaultValue: 'Median' }),
      p25: t('analytics.perf.p25', { defaultValue: 'P25' }),
      p75: t('analytics.perf.p75', { defaultValue: 'P75' }),
      unavailable: reasonLabel,
      groupLabel,
    });
    downloadCsv(csv, `performance_${kpi}.csv`);
  }, [data, groupLabel, kpi, reasonLabel, t]);

  const presetKeys = presetsQuery.data?.map((p) => p.key) ?? [DEFAULT_KPI];
  const allKeys = [...presetKeys, ...customKpis.map((k) => k.code)];
  const kpiKeys = Array.from(new Set(activeSet ? [...activeSet.kpis, ...allKeys] : allKeys));
  const options = optionsQuery.data;
  const moreCount = activeFilterCount(cohort);
  const projectSplits = options?.project_splits ?? [];
  const splitSelect = splitBy.startsWith(CLASS_PREFIX) ? CLASSIFICATION_SPLIT : splitBy;
  const splitName = validSplit ?? '';
  const dataQualityKey = splitKey && CLASS_KEY_RE.test(splitKey) ? splitKey : classKey.trim() || null;

  return (
    <div className="space-y-4" data-testid="analytics-performance">
      <Card>
        <div className="space-y-3">
          <div>
            <h2 className="text-lg font-semibold text-content-primary">
              {t('analytics.perf.title', { defaultValue: 'Historical performance' })}
            </h2>
            <p className="mt-1 text-sm text-content-secondary">
              {t('analytics.perf.intro', {
                defaultValue:
                  'Pick projects and one KPI to compare what was actually achieved. Ratios are a sum over a sum, units are never mixed, and missing data is shown as unavailable instead of zero.',
              })}
            </p>
          </div>

          <div className="flex flex-wrap items-end gap-2 rounded-lg bg-surface-secondary p-2">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.set_label', { defaultValue: 'Benchmark set' })}
              <select
                value={activeSetId}
                onChange={(e) => (e.target.value ? loadSet(e.target.value) : setActiveSetId(''))}
                className={`${inputClass} min-w-[14rem]`}
                data-testid="analytics-performance-set"
              >
                <option value="">{t('analytics.perf.set_none', { defaultValue: 'Unsaved selection' })}</option>
                {sets.map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.scope === 'shared'
                      ? t('analytics.perf.set_shared_name', { defaultValue: '{{name}} (shared)', name: s.name })
                      : s.name}
                  </option>
                ))}
              </select>
            </label>
            <Button variant="secondary" size="sm" icon={<Save size={14} />} onClick={() => setSaveOpen((v) => !v)}>
              {t('analytics.perf.set_save_as', { defaultValue: 'Save as new set' })}
            </Button>
            {activeSet?.is_owner && (
              <>
                <Button
                  variant="secondary"
                  size="sm"
                  onClick={() => updateMut.mutate(activeSet)}
                  disabled={updateMut.isPending}
                >
                  {t('analytics.perf.set_update', { defaultValue: 'Save changes to this set' })}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  icon={<Trash2 size={14} />}
                  onClick={() => setConfirmDelete(true)}
                  aria-label={t('analytics.perf.set_delete', { defaultValue: 'Delete set' })}
                >
                  {t('analytics.perf.set_delete', { defaultValue: 'Delete set' })}
                </Button>
              </>
            )}
            {saveOpen && (
              <div className="flex w-full flex-wrap items-end gap-2">
                <label className="flex flex-col gap-1 text-xs text-content-secondary">
                  {t('analytics.perf.set_name', { defaultValue: 'Name' })}
                  <input
                    type="text"
                    value={saveName}
                    maxLength={255}
                    onChange={(e) => setSaveName(e.target.value)}
                    className={`${inputClass} w-64`}
                    placeholder={t('analytics.perf.set_name_placeholder', {
                      defaultValue: 'e.g. Drywall, client X, 2024-2026',
                    })}
                  />
                </label>
                <label className="flex items-center gap-1 text-xs text-content-secondary">
                  <input type="checkbox" checked={saveShared} onChange={(e) => setSaveShared(e.target.checked)} />
                  {t('analytics.perf.set_share', { defaultValue: 'Share with colleagues' })}
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!saveName.trim() || createMut.isPending}
                  onClick={() =>
                    createMut.mutate(definition(saveName.trim(), saveShared ? 'shared' : 'personal', [kpi]))
                  }
                >
                  {t('analytics.perf.set_save', { defaultValue: 'Save' })}
                </Button>
                <span className="text-2xs text-content-tertiary">
                  {t('analytics.perf.set_share_hint', {
                    defaultValue:
                      'A shared set shares the definition only. Each colleague sees the figures for the projects they can open.',
                  })}
                </span>
              </div>
            )}
          </div>

          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.kpi_label', { defaultValue: 'KPI' })}
              <select
                value={kpi}
                onChange={(e) => setKpi(e.target.value)}
                className={`${inputClass} min-w-[16rem]`}
                data-testid="analytics-performance-kpi"
              >
                {kpiKeys.map((key) => (
                  <option key={key} value={key}>
                    {kpiLabel(key)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="ghost"
              size="sm"
              icon={<Plus size={14} />}
              onClick={() => setKpiModalOpen(true)}
              title={t('analytics.perf.new_kpi_hint', {
                defaultValue: 'Define your own KPI from bill, schedule, timesheet or project fields. It appears in this list.',
              })}
            >
              {t('analytics.perf.new_kpi', { defaultValue: 'New KPI' })}
            </Button>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.split_label', { defaultValue: 'Split by' })}
              <select
                value={splitSelect}
                onChange={(e) =>
                  setSplitBy(
                    e.target.value === CLASSIFICATION_SPLIT
                      ? `${CLASS_PREFIX}${classKey.trim() || 'din276'}`
                      : e.target.value,
                  )
                }
                className={inputClass}
                data-testid="analytics-performance-split"
              >
                <option value="">{t('analytics.perf.split_none', { defaultValue: 'No split' })}</option>
                {projectSplits.map((name) => (
                  <option key={name} value={name}>
                    {splitLabel(name)}
                  </option>
                ))}
                <option value={CLASSIFICATION_SPLIT}>
                  {t('analytics.perf.split.classification', { defaultValue: 'Work type (classification)' })}
                </option>
              </select>
            </label>
            {splitSelect === CLASSIFICATION_SPLIT && (
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {t('analytics.perf.split_class_key', { defaultValue: 'Standard' })}
                <input
                  type="text"
                  value={splitKey}
                  maxLength={64}
                  onChange={(e) => setSplitBy(`${CLASS_PREFIX}${e.target.value.trim()}`)}
                  aria-invalid={!CLASS_KEY_RE.test(splitKey)}
                  placeholder="din276"
                  className={`${inputClass} w-28`}
                />
              </label>
            )}
            <label
              className="flex flex-col gap-1 text-xs text-content-secondary"
              title={t('analytics.perf.currency_hint', {
                defaultValue:
                  'Restate money in one currency with the FX rates in Settings. Leave empty to keep each currency apart. Currencies without a rate stay apart and are named.',
              })}
            >
              {t('analytics.perf.currency_label', { defaultValue: 'Reporting currency' })}
              <input
                type="text"
                value={reportingCurrency}
                maxLength={3}
                onChange={(e) => setReportingCurrency(e.target.value.toUpperCase().replace(/[^A-Z]/g, ''))}
                placeholder={t('analytics.perf.currency_placeholder', { defaultValue: 'e.g. EUR' })}
                aria-invalid={reportingCurrency !== '' && !validCurrency}
                className={`${inputClass} w-20`}
                data-testid="analytics-performance-currency"
              />
            </label>
            <label
              className="flex flex-col gap-1 text-xs text-content-secondary"
              title={t('analytics.perf.index_series_hint', {
                defaultValue:
                  'Restate historical money to a reference month with a cost index from Price Index. Each month of a project moves by its own factor. A month the index does not cover leaves that project out, with the reason.',
              })}
            >
              {t('analytics.perf.index_series_label', { defaultValue: 'Cost index' })}
              <select
                value={indexSeriesId}
                onChange={(e) => {
                  setIndexSeriesId(e.target.value);
                  setIndexPeriod('');
                }}
                className={inputClass}
                data-testid="analytics-performance-index-series"
              >
                <option value="">{t('analytics.perf.index_series_none', { defaultValue: 'Do not adjust' })}</option>
                {(seriesQuery.data ?? []).map((s) => (
                  <option key={s.id} value={s.id}>
                    {s.name}
                  </option>
                ))}
              </select>
            </label>
            {indexSeriesId && (
              <label className="flex flex-col gap-1 text-xs text-content-secondary">
                {t('analytics.perf.index_period_label', { defaultValue: 'Reference month' })}
                <select
                  value={indexPeriod}
                  onChange={(e) => setIndexPeriod(e.target.value)}
                  className={inputClass}
                  data-testid="analytics-performance-index-period"
                >
                  <option value="">
                    {t('analytics.perf.index_period_latest', {
                      defaultValue: 'Latest ({{period}})',
                      period: indexPeriods[0] ?? '-',
                    })}
                  </option>
                  {indexPeriods.map((p) => (
                    <option key={p} value={p}>
                      {p}
                    </option>
                  ))}
                </select>
              </label>
            )}
            <label
              className="flex flex-col gap-1 text-xs text-content-secondary"
              title={t('analytics.perf.index_region_hint', {
                defaultValue:
                  "Restate money by the ratio of this region's factor to each project's region. A project without a region or a factor is left out, with the reason.",
              })}
            >
              {t('analytics.perf.index_region_label', { defaultValue: 'Reference region' })}
              <select
                value={indexRegion}
                onChange={(e) => setIndexRegion(e.target.value)}
                className={inputClass}
                data-testid="analytics-performance-index-region"
              >
                <option value="">{t('analytics.perf.index_region_none', { defaultValue: 'No regional adjustment' })}</option>
                {(regionsQuery.data ?? []).map((r) => (
                  <option key={r.id} value={r.region_code}>
                    {r.label && r.label !== r.region_code ? `${r.region_code} · ${r.label}` : r.region_code}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.statistic_label', { defaultValue: 'Lead with' })}
              <select
                value={statistic}
                onChange={(e) => setStatistic(e.target.value as BenchmarkStatistic)}
                className={inputClass}
                data-testid="analytics-performance-statistic"
              >
                {STATISTICS.map((s) => (
                  <option key={s} value={s}>
                    {statisticLabel(s)}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.min_projects', { defaultValue: 'Minimum projects' })}
              <input
                type="number"
                min={0}
                max={500}
                value={minProjects}
                onChange={(e) => setMinProjects(Math.max(0, Math.min(500, Number(e.target.value) || 0)))}
                className={`${inputClass} w-20`}
              />
            </label>
            <label className="flex flex-col gap-1 text-xs text-content-secondary">
              {t('analytics.perf.min_records', { defaultValue: 'Minimum records' })}
              <input
                type="number"
                min={0}
                max={1000000}
                value={minRecords}
                onChange={(e) => setMinRecords(Math.max(0, Math.min(1000000, Number(e.target.value) || 0)))}
                className={`${inputClass} w-20`}
              />
            </label>
            <label
              className="flex h-8 items-center gap-1 text-xs text-content-secondary"
              title={t('analytics.perf.convert_hint', {
                defaultValue:
                  'm² and ft², m³ and yd³, kg, t and lb are converted into one unit. Every conversion is shown. Different kinds of unit and different currencies are never added.',
              })}
            >
              <input
                type="checkbox"
                checked={convertUnits}
                onChange={(e) => setConvertUnits(e.target.checked)}
                data-testid="analytics-performance-convert"
              />
              {t('analytics.perf.convert_units', { defaultValue: 'Convert compatible units' })}
            </label>
            <Button
              variant="secondary"
              size="sm"
              icon={<SlidersHorizontal size={14} />}
              onClick={() => setShowMore((v) => !v)}
              aria-expanded={showMore}
            >
              {moreCount
                ? t('analytics.perf.more_filters_count', { defaultValue: 'More filters ({{n}})', n: moreCount })
                : t('analytics.perf.more_filters', { defaultValue: 'More filters' })}
            </Button>
            <Button
              variant="secondary"
              size="sm"
              icon={<Download size={14} />}
              onClick={handleExport}
              disabled={!data || !data.groups.length}
            >
              {t('analytics.perf.export_csv', { defaultValue: 'Export CSV' })}
            </Button>
          </div>

          {showMore && (
            <div className="grid grid-cols-1 gap-3 rounded-lg border border-border-light p-3 md:grid-cols-2 lg:grid-cols-3">
              <ValuePicker
                label={t('analytics.perf.filter_clients', { defaultValue: 'Clients' })}
                options={options?.clients ?? []}
                value={clients}
                onChange={setClients}
                empty={t('analytics.perf.filter_none_recorded', { defaultValue: 'None recorded on your projects' })}
              />
              <ValuePicker
                label={t('analytics.perf.filter_regions', { defaultValue: 'Regions' })}
                options={options?.regions ?? []}
                value={regions}
                onChange={setRegions}
                empty={t('analytics.perf.filter_none_recorded', { defaultValue: 'None recorded on your projects' })}
              />
              <ValuePicker
                label={t('analytics.perf.filter_project_types', { defaultValue: 'Project types' })}
                options={options?.project_types ?? []}
                value={projectTypes}
                onChange={setProjectTypes}
                empty={t('analytics.perf.filter_none_recorded', { defaultValue: 'None recorded on your projects' })}
              />
              <ValuePicker
                label={t('analytics.perf.filter_statuses', { defaultValue: 'Project status' })}
                options={options?.statuses ?? []}
                value={statuses}
                onChange={setStatuses}
                format={statusLabel}
                empty={t('analytics.perf.filter_none_recorded', { defaultValue: 'None recorded on your projects' })}
              />
              <div className="flex flex-col gap-1 text-xs text-content-secondary">
                <span>{t('analytics.perf.filter_classification', { defaultValue: 'Work type by classification' })}</span>
                <div className="flex gap-2">
                  <input
                    type="text"
                    value={classKey}
                    onChange={(e) => setClassKey(e.target.value)}
                    placeholder={t('analytics.perf.filter_class_key', { defaultValue: 'Standard, e.g. din276' })}
                    aria-label={t('analytics.perf.filter_class_key', { defaultValue: 'Standard, e.g. din276' })}
                    className={`${inputClass} w-36`}
                  />
                  <input
                    type="text"
                    value={classCode}
                    onChange={(e) => setClassCode(e.target.value)}
                    placeholder={t('analytics.perf.filter_class_code', { defaultValue: 'Code, e.g. 330' })}
                    aria-label={t('analytics.perf.filter_class_code', { defaultValue: 'Code, e.g. 330' })}
                    className={`${inputClass} w-28`}
                  />
                </div>
                <span className="text-2xs text-content-tertiary">
                  {t('analytics.perf.filter_class_hint', {
                    defaultValue: 'Only bill positions with exactly this code count. Works for KPIs read from bill positions.',
                  })}
                </span>
              </div>
              <div className="flex flex-col gap-1 text-xs text-content-secondary">
                <span>{t('analytics.perf.filter_period', { defaultValue: 'Period' })}</span>
                <div className="flex items-center gap-2">
                  <input
                    type="date"
                    value={periodStart}
                    onChange={(e) => setPeriodStart(e.target.value)}
                    aria-label={t('analytics.perf.filter_period_from', { defaultValue: 'From' })}
                    className={inputClass}
                  />
                  <span>-</span>
                  <input
                    type="date"
                    value={periodEnd}
                    onChange={(e) => setPeriodEnd(e.target.value)}
                    aria-label={t('analytics.perf.filter_period_to', { defaultValue: 'To' })}
                    className={inputClass}
                  />
                </div>
              </div>
            </div>
          )}

          <div>
            <div className="mb-1 flex flex-wrap items-center gap-2 text-xs text-content-secondary">
              <span>{t('analytics.perf.projects_label', { defaultValue: 'Projects' })}</span>
              <Badge variant="neutral" size="sm">
                {selected.length
                  ? t('analytics.perf.selected_projects', { defaultValue: '{{count}} selected', count: selected.length })
                  : t('analytics.perf.all_projects', { defaultValue: 'All projects ({{count}})', count: projects.length })}
              </Badge>
              <button
                type="button"
                className="text-oe-blue hover:underline disabled:opacity-40"
                onClick={() => setSelected([])}
                disabled={!selected.length}
              >
                {t('analytics.perf.clear_selection', { defaultValue: 'Use all projects' })}
              </button>
              <button
                type="button"
                className="text-oe-blue hover:underline disabled:opacity-40"
                onClick={selectShown}
                disabled={!visibleProjects.length}
                title={t('analytics.perf.select_shown_hint', {
                  defaultValue: 'Tick every project the search shows, to compare a cohort you can name.',
                })}
              >
                {t('analytics.perf.select_shown', { defaultValue: 'Select all shown ({{count}})', count: visibleProjects.length })}
              </button>
              <span className="relative ms-auto">
                <Search size={12} className="pointer-events-none absolute start-2 top-1/2 -translate-y-1/2 text-content-tertiary" />
                <input
                  type="text"
                  value={filter}
                  onChange={(e) => setFilter(e.target.value)}
                  placeholder={t('analytics.search_placeholder', { defaultValue: 'Search projects...' })}
                  aria-label={t('analytics.search_placeholder', { defaultValue: 'Search projects...' })}
                  className="h-7 w-44 rounded-lg border border-border-light bg-surface-primary ps-6 pe-2 text-xs focus:outline-none focus:ring-1 focus:ring-oe-blue"
                />
              </span>
            </div>
            <div className="max-h-40 overflow-y-auto rounded-lg border border-border-light p-2">
              <div className="grid grid-cols-1 gap-1 sm:grid-cols-2 lg:grid-cols-3">
                {visibleProjects.map((p) => (
                  <label key={p.id} className="flex min-w-0 items-center gap-2 text-xs text-content-primary">
                    <input type="checkbox" checked={selected.includes(p.id)} onChange={() => toggle(p.id)} />
                    <span className="truncate">{p.name}</span>
                  </label>
                ))}
              </div>
            </div>
          </div>
          <PerformanceDataQuality cohort={cohort} classificationKey={dataQualityKey} />
        </div>
      </Card>

      {data && <BenchmarkNotices data={data} />}

      {benchmarkQuery.isLoading ? (
        <Card>
          <Skeleton className="mb-3 h-6 w-48" />
          <Skeleton className="h-24 w-full" />
        </Card>
      ) : benchmarkQuery.isError ? (
        <EmptyState
          icon={<Gauge size={28} />}
          title={t('analytics.perf.error', { defaultValue: 'Could not load the benchmark' })}
          action={
            <Button variant="primary" icon={<RefreshCw size={14} />} onClick={() => benchmarkQuery.refetch()}>
              {t('analytics.retry', { defaultValue: 'Retry' })}
            </Button>
          }
        />
      ) : !data || data.groups.length === 0 ? (
        <EmptyState
          icon={<Gauge size={28} />}
          title={t('analytics.perf.empty_title', { defaultValue: 'No data for this KPI yet' })}
          description={t('analytics.perf.empty', {
            defaultValue:
              'None of the selected projects has data for this KPI. Productivity KPIs need approved timesheet hours booked against bill positions and reported progress.',
          })}
        />
      ) : (
        data.groups.map((group) => (
          <PerformanceGroupCard
            key={group.key}
            group={group}
            title={`${kpiLabel(kpi)} · ${groupLabel(group)}`}
            selectedCount={data.projects_selected}
            projects={data.projects}
            reasonLabel={reasonLabel}
            statisticLabel={statisticLabel}
            minProjects={minProjects}
            request={request}
            splitName={splitName}
            onDrill={(row, projectName) => setDrill({ group, row, projectName })}
          />
        ))
      )}

      {kpiKeys.length > 0 && (
        <PerformanceCompare key={kpi} kpiKeys={kpiKeys} kpiLabel={kpiLabel} request={request} initial={kpi} />
      )}

      <PerformanceDrilldown target={drill} request={request} kpiLabel={kpiLabel(kpi)} onClose={() => setDrill(null)} />
      {kpiModalOpen && <CustomKpiModal onClose={() => setKpiModalOpen(false)} />}

      <ConfirmDialog
        open={confirmDelete && Boolean(activeSet)}
        onConfirm={() => activeSet && deleteMut.mutate(activeSet.id)}
        onCancel={() => setConfirmDelete(false)}
        loading={deleteMut.isPending}
        title={t('analytics.perf.set_delete_title', { defaultValue: 'Delete this benchmark set?' })}
        message={t('analytics.perf.set_delete_message', {
          defaultValue: '{{name}} is removed for everyone it was shared with. No project data is touched.',
          name: activeSet?.name ?? '',
        })}
      />
    </div>
  );
}

function ValuePicker({
  label,
  options,
  value,
  onChange,
  empty,
  format,
}: {
  label: string;
  options: string[];
  value: string[];
  onChange: (next: string[]) => void;
  empty: string;
  /** Display text for a stored value, such as a translated status. */
  format?: (value: string) => string;
}) {
  // A value saved in a set that is no longer on any project the reader can
  // open still shows, ticked, so a filter is never silently dropped.
  const all = Array.from(new Set([...options, ...value]));
  return (
    <div className="flex flex-col gap-1 text-xs text-content-secondary">
      <span>{label}</span>
      {all.length === 0 ? (
        <span className="text-content-tertiary">{empty}</span>
      ) : (
        <div className="max-h-24 overflow-y-auto rounded-lg border border-border-light p-1">
          {all.map((option) => (
            <label key={option} className="flex min-w-0 items-center gap-2 text-content-primary">
              <input
                type="checkbox"
                checked={value.includes(option)}
                onChange={() =>
                  onChange(value.includes(option) ? value.filter((v) => v !== option) : [...value, option])
                }
              />
              <span className="truncate">{format ? format(option) : option}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

function PerformanceGroupCard({
  group,
  title,
  selectedCount,
  projects,
  reasonLabel,
  statisticLabel,
  minProjects,
  request,
  splitName,
  onDrill,
}: {
  group: PerformanceGroup;
  title: string;
  selectedCount: number;
  projects: { project_id: string; name: string; currency: string }[];
  reasonLabel: (reason: string | null) => string;
  statisticLabel: (s: BenchmarkStatistic) => string;
  minProjects: number;
  request: PerformanceBenchmarkRequest;
  splitName: string;
  onDrill: (row: PerformanceProjectRow, projectName: string) => void;
}) {
  const { t } = useTranslation();
  const [sort, setSort] = useState<RowSort>('name');
  const b = group.benchmark;
  const unavailable = t('analytics.perf.unavailable', { defaultValue: 'Unavailable' });
  const leadStat = group.headline_statistic ?? 'weighted';
  const lead = fmtValue(group.headline !== undefined ? group.headline : b.weighted);
  const median = fmtValue(b.median);
  const mean = fmtValue(b.mean);
  const p25 = fmtValue(b.p25);
  const p75 = fmtValue(b.p75);
  const coverage = toNumber(group.coverage);
  const rows = sortTableRows(tableRows(group, projects), sort, compareNames);
  const unit = group.value_unit ? prettyUnit(group.value_unit) : '';
  const withUnit = (v: string | null) => (v !== null && unit ? `${v} ${unit}` : v);
  const p10 = fmtValue(b.p10);
  const p90 = fmtValue(b.p90);
  const sd = fmtValue(b.stddev);
  const cv = toNumber(b.cv);
  const excluded = Object.entries(group.excluded ?? {}).filter(([, n]) => n > 0);
  const nextSort: Record<RowSort, RowSort> = { name: 'value_desc', value_desc: 'value_asc', value_asc: 'name' };
  const min = toNumber(b.min);
  const max = toNumber(b.max);
  const insufficient = group.sufficient === false;

  return (
    <Card padding="none">
      <div className="border-b border-border-light px-6 py-4">
        <div className="flex flex-wrap items-center gap-2">
          <h3 className="text-base font-semibold text-content-primary">{title}</h3>
          {unit && (
            <Badge variant="neutral" size="sm" data-testid="analytics-performance-value-unit">
              {unit}
            </Badge>
          )}
          {insufficient && (
            <Badge variant="warning" size="sm">
              {t('analytics.perf.insufficient', {
                defaultValue: 'Not enough evidence for a benchmark: {{have}} of {{min}} projects',
                have: group.evidence.projects_with_value,
                min: minProjects,
              })}
            </Badge>
          )}
        </div>
        {group.conversions && group.conversions.length > 0 && (
          <p className="mt-1 text-xs text-content-secondary" data-testid="analytics-performance-conversions">
            {t('analytics.perf.converted', { defaultValue: 'Converted:' })}{' '}
            {group.conversions
              .map(
                (c) =>
                  `1 ${prettyUnit(c.from_unit)} = ${fmtNumber(toNumber(c.factor) ?? 0, 6)} ${prettyUnit(c.to_unit)}`,
              )
              .join('; ')}
          </p>
        )}
        {group.currency_conversions && group.currency_conversions.length > 0 && (
          <p className="mt-1 text-xs text-content-secondary" data-testid="analytics-performance-fx">
            {t('analytics.perf.fx_converted', { defaultValue: 'Restated at FX rates:' })}{' '}
            {group.currency_conversions
              // Codes, a number, a date and a source name: nothing in it to translate.
              .map(
                (c) =>
                  `1 ${c.from_currency} = ${fmtNumber(toNumber(c.rate) ?? 0, 6)} ${c.to_currency} (${c.as_of ?? '-'}, ${c.source || '-'})`,
              )
              .join('; ')}
          </p>
        )}
        <div className="mt-3 grid grid-cols-2 gap-3 text-xs sm:grid-cols-4">
          <Figure
            label={statisticLabel(leadStat)}
            value={
              withUnit(lead) ??
              (leadStat === 'weighted'
                ? `${unavailable} (${reasonLabel(b.weighted_unavailable_reason)})`
                : unavailable)
            }
            muted={insufficient}
            hint={
              leadStat === 'weighted'
                ? t('analytics.perf.weighted_hint', { defaultValue: 'Sum over sum across the projects with a value' })
                : t('analytics.perf.mean_hint', {
                    defaultValue: 'Average of projects {{mean}}, every project counts once',
                    mean: mean ?? '-',
                  })
            }
          />
          <Figure label={t('analytics.perf.median', { defaultValue: 'Median' })} value={median ?? unavailable} />
          <Figure
            label={t('analytics.perf.range', { defaultValue: 'Normal range (P25 - P75)' })}
            value={p25 !== null && p75 !== null ? `${p25} - ${p75}` : unavailable}
          />
          <Figure
            label={t('analytics.perf.evidence', { defaultValue: 'Evidence' })}
            value={t('analytics.perf.evidence_value', {
              defaultValue: '{{projects}} projects, {{records}} records',
              projects: group.evidence.projects_with_value,
              records: group.evidence.records,
            })}
            hint={t('analytics.perf.coverage', {
              defaultValue: 'Coverage {{pct}}: {{count}} of {{selected}} projects have a value',
              pct: coverage === null ? '-' : fmtPercent(coverage * 100),
              count: group.evidence.projects_with_value,
              selected: selectedCount,
            })}
          />
        </div>
        <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-2xs text-content-tertiary" data-testid="analytics-performance-spread">
          <span>
            P10 - P90:{' '}
            {p10 !== null && p90 !== null
              ? `${p10} - ${p90}`
              : t('analytics.perf.tails_need', { defaultValue: 'from 10 projects' })}
          </span>
          <span>
            {t('analytics.perf.stddev', { defaultValue: 'Standard deviation' })}: {sd ?? '-'}
          </span>
          <span title={t('analytics.perf.cv_hint', { defaultValue: 'Standard deviation over the mean. Above 30 % the projects differ a lot.' })}>
            {t('analytics.perf.cv', { defaultValue: 'Spread (CV)' })}: {cv === null ? '-' : fmtPercent(cv * 100)}
          </span>
          {min !== null && max !== null && (
            <span>
              {t('analytics.perf.min_max', { defaultValue: 'Min - max' })}: {fmtValue(b.min)} - {fmtValue(b.max)}
            </span>
          )}
          {excluded.length > 0 && (
            <span data-testid="analytics-performance-excluded">
              {t('analytics.perf.excluded', { defaultValue: 'Left out:' })}{' '}
              {fmtList(excluded.map(([reason, n]) => `${reasonLabel(reason)} ${n}`))}
            </span>
          )}
        </div>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-xs text-content-tertiary">
              <th className="px-6 py-2 font-medium">{t('analytics.perf.col_project', { defaultValue: 'Project' })}</th>
              <th className="px-3 py-2 text-right font-medium">
                <button
                  type="button"
                  onClick={() => setSort(nextSort[sort])}
                  className="inline-flex items-center gap-1 hover:text-content-primary"
                  aria-label={t('analytics.perf.sort_by_value', { defaultValue: 'Sort by value' })}
                >
                  {t('analytics.perf.col_value', { defaultValue: 'Value' })}
                  {sort === 'value_desc' ? <ArrowDown size={12} /> : sort === 'value_asc' ? <ArrowUp size={12} /> : <ArrowUpDown size={12} />}
                </button>
              </th>
              <th className="px-3 py-2 text-right font-medium">
                {t('analytics.perf.col_variance', { defaultValue: 'vs benchmark' })}
              </th>
              <th className="px-3 py-2 font-medium">{t('analytics.perf.col_range', { defaultValue: 'Against the range' })}</th>
              <th className="px-3 py-2 text-right font-medium">{t('analytics.perf.col_records', { defaultValue: 'Records' })}</th>
              <th className="px-3 py-2 font-medium">
                <span className="sr-only">{t('analytics.perf.drill_open', { defaultValue: 'Show records' })}</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ projectId, name, row }) => {
              const value = fmtValue(row?.value);
              const band = rangeBand(row?.value, b.p25, b.p75);
              const n = toNumber(row?.value);
              const pos = n !== null && min !== null && max !== null && max > min ? ((n - min) / (max - min)) * 100 : 50;
              const from = row?.converted_from ?? [];
              const variance = fmtVariance(row?.variance);
              return (
                <tr key={projectId} className="border-b border-border-light last:border-0">
                  <td className="max-w-[18rem] truncate px-6 py-2">
                    <Link to={`/projects/${projectId}`} className="text-content-primary hover:text-oe-blue hover:underline">
                      {name}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {value ?? (
                      <span className="text-content-tertiary" title={reasonLabel(row?.unavailable_reason ?? null)}>
                        {unavailable}
                        <span className="ms-1 text-2xs">({reasonLabel(row?.unavailable_reason ?? null)})</span>
                      </span>
                    )}
                    {from.length > 0 && (
                      <div className="text-2xs text-content-tertiary">
                        {t('analytics.perf.converted_from', {
                          defaultValue: 'converted from {{units}}',
                          units: fmtList(from.map(prettyUnit)),
                        })}
                      </div>
                    )}
                    {(row?.index_factor != null || row?.location_factor != null) && (
                      <div className="text-2xs text-content-tertiary" data-testid="analytics-performance-index-provenance">
                        {t('analytics.perf.index_was', {
                          defaultValue: 'was {{value}}',
                          value: fmtValue(row.unadjusted_value ?? null) ?? '-',
                        })}
                        {row.index_factor != null && (
                          <span className="ms-1">
                            {t('analytics.perf.index_provenance', {
                              defaultValue: 'x{{factor}} {{series}}, {{from}} to {{to}}',
                              factor: fmtNumber(toNumber(row.index_factor) ?? 0, 4),
                              series: row.index_series ?? '',
                              from: periodSpan(row.index_base_periods ?? []),
                              to: row.index_target_period ?? '',
                            })}
                          </span>
                        )}
                        {row.location_factor != null && (
                          <span className="ms-1">
                            {t('analytics.perf.location_provenance', {
                              defaultValue: 'x{{factor}} region {{region}}',
                              factor: fmtNumber(toNumber(row.location_factor) ?? 0, 4),
                              region: row.location_region ?? '',
                            })}
                          </span>
                        )}
                      </div>
                    )}
                    {(row?.index_missing_periods ?? []).length > 0 && (
                      <div className="text-2xs text-content-tertiary">
                        {t('analytics.perf.index_missing', {
                          defaultValue: 'the index has no point for {{periods}}',
                          periods: fmtList(row?.index_missing_periods ?? []),
                        })}
                      </div>
                    )}
                    {row?.original_currency && row.original_value != null && (
                      <div className="text-2xs text-content-tertiary">
                        {t('analytics.perf.fx_original', {
                          defaultValue: 'was {{value}} {{currency}} at {{rate}}',
                          value: fmtValue(row.original_value) ?? '-',
                          currency: row.original_currency,
                          rate: fmtNumber(toNumber(row.fx_rate) ?? 0, 6),
                        })}
                      </div>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{variance ?? '-'}</td>
                  <td className="px-3 py-2">
                    {band ? (
                      <div className="flex items-center gap-2">
                        <div className="relative h-1.5 w-24 rounded-full bg-surface-tertiary" aria-hidden="true">
                          <span
                            className="absolute top-1/2 h-2.5 w-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-oe-blue"
                            style={{ left: `${pos}%` }}
                          />
                        </div>
                        <Badge variant={band === 'within' ? 'success' : 'warning'} size="sm">
                          {t(`analytics.perf.band_${band}`, {
                            defaultValue: band === 'below' ? 'Below P25' : band === 'above' ? 'Above P75' : 'Within range',
                          })}
                        </Badge>
                      </div>
                    ) : (
                      <span className="text-content-tertiary">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-content-secondary">{row?.records ?? 0}</td>
                  <td className="px-3 py-2">
                    {row && row.records > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        icon={<ListTree size={14} />}
                        onClick={() => onDrill(row, name)}
                        aria-label={t('analytics.perf.drill_open', { defaultValue: 'Show records' })}
                        title={t('analytics.perf.drill_open', { defaultValue: 'Show records' })}
                      />
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <EstimateCheck group={group} request={request} statisticLabel={statisticLabel} splitName={splitName} />
    </Card>
  );
}

/** Type an estimate, see where it sits in this group's range. Nothing is written anywhere. */
function EstimateCheck({
  group,
  request,
  statisticLabel,
  splitName,
}: {
  group: PerformanceGroup;
  request: PerformanceBenchmarkRequest;
  statisticLabel: (s: BenchmarkStatistic) => string;
  splitName: string;
}) {
  const { t } = useTranslation();
  const splitValue = splitName ? (group.dimensions[splitName] ?? null) : null;
  const groupUnit = group.dimensions.unit ?? null;
  const groupCurrency = group.dimensions.currency ?? null;
  const [value, setValue] = useState('');
  const [unit, setUnit] = useState(groupUnit && groupUnit !== NULL_GROUP_KEY ? groupUnit : '');
  const checkMut = useMutation({
    mutationFn: () =>
      checkAgainstCohort({
        ...request,
        value: value.trim().replace(',', '.'),
        unit: unit.trim() || null,
        currency: groupCurrency && groupCurrency !== NULL_GROUP_KEY ? groupCurrency : null,
        split_value: splitValue === NULL_GROUP_KEY ? null : splitValue,
      }),
  });
  const parsed = Number(value.trim().replace(',', '.'));
  const canCheck = value.trim() !== '' && Number.isFinite(parsed) && parsed > 0;

  return (
    <div className="border-t border-border-light bg-surface-secondary px-6 py-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-xs text-content-secondary">
          {t('analytics.perf.check_label', { defaultValue: 'Check an estimate against this range' })}
          <input
            type="text"
            inputMode="decimal"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder={t('analytics.perf.check_value', { defaultValue: 'Your value' })}
            aria-label={t('analytics.perf.check_value', { defaultValue: 'Your value' })}
            className={`${inputClass} w-32`}
          />
        </label>
        {groupUnit !== null && (
          <label className="flex flex-col gap-1 text-xs text-content-secondary">
            {t('analytics.perf.check_unit', { defaultValue: 'Unit' })}
            <input
              type="text"
              value={unit}
              maxLength={30}
              onChange={(e) => setUnit(e.target.value)}
              className={`${inputClass} w-20`}
            />
          </label>
        )}
        <Button
          variant="secondary"
          size="sm"
          icon={<Scale size={14} />}
          disabled={!canCheck || checkMut.isPending}
          onClick={() => checkMut.mutate()}
        >
          {t('analytics.perf.check_button', { defaultValue: 'Check' })}
        </Button>
        {checkMut.data && <CheckResult result={checkMut.data} statisticLabel={statisticLabel} />}
        {checkMut.isError && (
          <span className="text-xs text-semantic-error">
            {t('analytics.perf.check_failed', { defaultValue: 'Could not check this value' })}
          </span>
        )}
      </div>
      <p className="mt-1 text-2xs text-content-tertiary">
        {t('analytics.perf.check_hint', {
          defaultValue:
            'A suggestion to weigh, not a correction: nothing in the estimate is changed. Confidence follows the number of projects behind the range: under 3 low, under 10 medium, 10 or more high, and low whenever the minimum is not met.',
        })}
      </p>
    </div>
  );
}

function CheckResult({
  result,
  statisticLabel,
}: {
  result: PerformanceCheckResponse;
  statisticLabel: (s: BenchmarkStatistic) => string;
}) {
  const { t } = useTranslation();
  if (result.status !== 'ok') {
    return (
      <span className="text-xs text-content-secondary">
        {t(`analytics.perf.check_status.${result.status}`, {
          defaultValue: 'This value cannot be compared with this range.',
        })}
      </span>
    );
  }
  const variance = toNumber(result.variance);
  const rank = toNumber(result.percentile_rank);
  const factor = toNumber(result.unit_factor);
  return (
    <div className="flex flex-wrap items-center gap-2 text-xs text-content-primary" data-testid="analytics-performance-check">
      {result.band && (
        <Badge variant={result.band === 'within' ? 'success' : 'warning'} size="sm">
          {t(`analytics.perf.band_${result.band}`, {
            defaultValue: result.band === 'below' ? 'Below P25' : result.band === 'above' ? 'Above P75' : 'Within range',
          })}
        </Badge>
      )}
      {factor !== null && factor !== 1 && (
        <span>
          {t('analytics.perf.check_converted', {
            defaultValue: 'converted to {{value}}',
            value: fmtValue(result.value) ?? '-',
          })}
        </span>
      )}
      {result.cost_index?.applicable && (result.cost_index.target_period || result.cost_index.target_region) && (
        <span className="text-content-tertiary">
          {t('analytics.perf.check_indexed', {
            defaultValue: 'against history brought to {{reference}}',
            reference: [result.cost_index.target_period, result.cost_index.target_region].filter(Boolean).join(' / '),
          })}
        </span>
      )}
      {rank !== null && (
        <span>
          {t('analytics.perf.check_rank', { defaultValue: 'percentile {{rank}}', rank: fmtNumber(rank, 0) })}
        </span>
      )}
      {variance !== null && result.statistic && (
        <span>
          {t('analytics.perf.check_variance', {
            defaultValue: '{{variance}} vs {{statistic}}',
            variance: `${variance > 0 ? '+' : ''}${fmtPercent(variance * 100)}`,
            statistic: statisticLabel(result.statistic),
          })}
        </span>
      )}
      {result.confidence && (
        <Badge variant={result.confidence === 'high' ? 'success' : result.confidence === 'medium' ? 'neutral' : 'warning'} size="sm">
          {t(`analytics.perf.confidence_${result.confidence}`, {
            defaultValue:
              result.confidence === 'high'
                ? 'High confidence'
                : result.confidence === 'medium'
                  ? 'Medium confidence'
                  : 'Low confidence',
          })}
        </Badge>
      )}
      {result.group && (
        <span className="text-content-tertiary">
          {t('analytics.perf.evidence_value', {
            defaultValue: '{{projects}} projects, {{records}} records',
            projects: result.group.evidence.projects_with_value,
            records: result.group.evidence.records,
          })}
        </span>
      )}
    </div>
  );
}

/** `2020-06` for one month, `2020-06 - 2022-11` for several. */
function periodSpan(periods: string[]): string {
  if (periods.length === 0) return '';
  const sorted = [...periods].sort();
  const first = sorted[0] ?? '';
  const last = sorted[sorted.length - 1] ?? '';
  return first === last ? first : `${first} - ${last}`;
}

/** What the response left out or could not convert, so a missing block is never a silent one. */
function BenchmarkNotices({ data }: { data: PerformanceBenchmarkResponse }) {
  const { t } = useTranslation();
  const unconverted = data.currencies_unconverted ?? [];
  const omitted = data.groups_omitted ?? 0;
  const without = data.projects_without_data ?? 0;
  const index = data.cost_index ?? null;
  if (!unconverted.length && !omitted && !without && !index) return null;
  return (
    <div className="space-y-1 rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs text-content-secondary">
      {index && !index.applicable && (
        <p>
          {t('analytics.perf.index_not_applicable', {
            defaultValue: 'This KPI carries no money, so the cost index does not change it.',
          })}
        </p>
      )}
      {index && index.applicable && index.series_name && (
        <p data-testid="analytics-performance-index-notice">
          {t('analytics.perf.index_notice', {
            defaultValue:
              'Money is brought to {{period}} with {{series}}, each month by its own factor. Projects with a month the index does not cover are left out.',
            period: index.target_period ?? '',
            series: index.series_name,
          })}
        </p>
      )}
      {index && index.applicable && index.target_region && (
        <p>
          {t('analytics.perf.index_region_notice', {
            defaultValue: 'Money is brought to region {{region}}. Projects without a region or a regional factor are left out.',
            region: index.target_region,
          })}
        </p>
      )}
      {unconverted.length > 0 && (
        <p>
          {t('analytics.perf.fx_missing', {
            defaultValue: 'No FX rate to {{to}} for {{currencies}}: those values stay in their own currency.',
            to: data.reporting_currency ?? '',
            currencies: fmtList(unconverted),
          })}
        </p>
      )}
      {omitted > 0 && (
        <p>
          {t('analytics.perf.groups_omitted', {
            defaultValue: '{{count}} more groups are not shown. Narrow the projects or choose a coarser split.',
            count: omitted,
          })}
        </p>
      )}
      {without > 0 && (
        <p>
          {t('analytics.perf.projects_without_data', {
            defaultValue: '{{count}} selected projects have no records for this KPI.',
            count: without,
          })}
        </p>
      )}
    </div>
  );
}

function Figure({ label, value, hint, muted }: { label: string; value: string; hint?: string; muted?: boolean }) {
  return (
    <div className="min-w-0">
      <div className="text-content-tertiary">{label}</div>
      <div
        className={`truncate text-sm font-semibold tabular-nums ${muted ? 'text-content-tertiary' : 'text-content-primary'}`}
        title={value}
      >
        {value}
      </div>
      {hint && <div className="mt-0.5 text-2xs text-content-tertiary">{hint}</div>}
    </div>
  );
}
