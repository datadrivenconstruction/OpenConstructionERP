// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cost​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ benchmarks: compare an estimate against the cost per m2 (or per
 * functional unit) of completed projects, element by element. Bands come from
 * the company's own history; when it is too thin the server falls back to an
 * open reference set and says so.
 */
import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import clsx from 'clsx';
import { BarChart3, Download, Loader2, Network, Plus, Trash2 } from 'lucide-react';
import {
  Badge,
  Breadcrumb,
  Button,
  Card,
  CollapsibleSection,
  EmptyState,
  Input,
} from '@/shared/ui';
import { PageHeader } from '@/shared/ui/PageHeader';
import { useToastStore } from '@/stores/useToastStore';
import { useActiveProjectId } from '@/shared/hooks/useActiveProjectId';
import { getErrorMessage } from '@/shared/lib/api';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { InsightsPanel, InsightsToggleButton, useModuleInsights } from '@/features/insights';
import type { InsightDataset, InsightDef } from '@/features/insights';
import {
  captureProject,
  compareEstimate,
  deleteRecord,
  downloadAnonymised,
  fetchRecords,
} from './api';
import type {
  Band,
  BenchmarkMeasure,
  BenchmarkPosition,
  BenchmarkRecord,
  CompareElement,
  CompareRequest,
  CompareResult,
} from './api';

/* ── Helpers ───────────────────────────────────────────────────────────── */

type Translate = ReturnType<typeof useTranslation>['t'];

function toNum(v: string | number | null | undefined): number | null {
  if (v === null || v === undefined || v === '') return null;
  const n = typeof v === 'number' ? v : Number(v);
  return Number.isFinite(n) ? n : null;
}

function fmt(v: string | number | null | undefined, digits = 2): string {
  const n = toNum(v);
  if (n === null) return '-';
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      minimumFractionDigits: digits,
      maximumFractionDigits: digits,
    }).format(n);
  } catch {
    return n.toFixed(digits);
  }
}

function yearOf(date: string | null): string {
  return date ? date.slice(0, 4) : '-';
}

/** Cost per m2 of a stored record; null when there is no floor area. */
export function costPerM2(r: BenchmarkRecord): number | null {
  const total = toNum(r.total_cost);
  const gfa = toNum(r.gfa_m2);
  if (total === null || gfa === null || gfa <= 0) return null;
  return total / gfa;
}

const SELECT_CLASS =
  'h-9 rounded-lg border border-border bg-surface-primary px-2 text-sm text-content-primary ' +
  'transition-all duration-normal ease-oe hover:border-content-tertiary ' +
  'focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';

function positionLabel(p: BenchmarkPosition, t: Translate): string {
  switch (p) {
    case 'below':
      return t('cost_benchmarks.pos_below', { defaultValue: 'Below range' });
    case 'above':
      return t('cost_benchmarks.pos_above', { defaultValue: 'Above range' });
    case 'within':
      return t('cost_benchmarks.pos_within', { defaultValue: 'Within range' });
    default:
      return t('cost_benchmarks.pos_unknown', { defaultValue: 'No benchmark' });
  }
}

/* ── Band bar: P10 - P50 - P90 with the estimate marker ───────────────── */

export function BandBar({ band, value, position }: { band: Band; value: string | null; position: BenchmarkPosition }) {
  const p10 = toNum(band.p10);
  const p50 = toNum(band.p50);
  const p90 = toNum(band.p90);
  const v = toNum(value);
  if (p10 === null || p90 === null || p90 < p10) {
    return <span className="text-2xs text-content-quaternary">-</span>;
  }
  const lo = Math.min(p10, v ?? p10);
  const hi = Math.max(p90, v ?? p90);
  const span = hi - lo || 1;
  const pct = (x: number) => `${(((x - lo) / span) * 100).toFixed(2)}%`;
  return (
    <div className="relative h-4 w-full min-w-[120px]" data-testid="band-bar">
      <div className="absolute top-1/2 h-1 w-full -translate-y-1/2 rounded bg-surface-secondary" />
      <div
        className="absolute top-1/2 h-2 -translate-y-1/2 rounded bg-oe-blue/30"
        style={{ left: pct(p10), width: `${(((p90 - p10) / span) * 100).toFixed(2)}%` }}
      />
      {p50 !== null && (
        <div
          className="absolute top-0 h-4 w-0.5 bg-oe-blue"
          style={{ left: pct(p50) }}
        />
      )}
      {v !== null && (
        <div
          className={clsx(
            'absolute top-1/2 h-3 w-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-white',
            position === 'within' || position === 'unknown' ? 'bg-content-primary' : 'bg-semantic-error',
          )}
          style={{ left: pct(v) }}
        />
      )}
    </div>
  );
}

/* ── How it fits the workflow ──────────────────────────────────────────── */

function HowBenchmarksWork() {
  const { t } = useTranslation();
  return (
    <CollapsibleSection
      storageKey="cost_benchmarks.how"
      icon={<Network size={15} className="text-oe-blue" />}
      title={t('cost_benchmarks.flow_title', { defaultValue: 'How this fits the workflow' })}
    >
      <ol className="list-decimal space-y-1 pl-5 text-xs text-content-tertiary">
        <li>
          {t('cost_benchmarks.flow_1', {
            defaultValue: 'Finish a project: its bill of quantities becomes a record of cost per m2, element by element.',
          })}
        </li>
        <li>
          {t('cost_benchmarks.flow_2', {
            defaultValue: 'Pick an estimate and narrow the cohort by type, country, floor area and year.',
          })}
        </li>
        <li>
          {t('cost_benchmarks.flow_3', {
            defaultValue: 'Costs are indexed to one base date, one region and one currency so projects from different years compare fairly.',
          })}
        </li>
        <li>
          {t('cost_benchmarks.flow_4', {
            defaultValue: 'Each element shows the P10-P50-P90 band of your own history. Rows outside the band need a second look; you decide what to change.',
          })}
        </li>
      </ol>
      <p className="mt-2 text-2xs text-content-quaternary">
        {t('cost_benchmarks.flow_note', {
          defaultValue: 'With fewer completed projects than the minimum, the band comes from an open reference set and is marked as such.',
        })}
      </p>
    </CollapsibleSection>
  );
}

/* ── Insights (KPIs over the completed records) ───────────────────────── */

function buildInsights(records: BenchmarkRecord[], t: Translate) {
  const seen = new Set<string>();
  const rows = records.map((r) => {
    const first = seen.has(r.country) ? 0 : 1;
    seen.add(r.country);
    return {
      name: r.name,
      type: r.project_type,
      country: r.country,
      year: yearOf(r.cost_date),
      per_m2: costPerM2(r) ?? 0,
      has_m2: costPerM2(r) === null ? 0 : 1,
      first_in_country: first,
    };
  });
  const dataset: InsightDataset = {
    id: 'benchmarks',
    label: t('cost_benchmarks.insights.ds', { defaultValue: 'Completed projects' }),
    currency: '',
    fields: [
      { key: 'name', label: t('cost_benchmarks.insights.f_name', { defaultValue: 'Project' }), kind: 'dimension' },
      { key: 'type', label: t('cost_benchmarks.insights.f_type', { defaultValue: 'Type' }), kind: 'dimension' },
      { key: 'country', label: t('cost_benchmarks.insights.f_country', { defaultValue: 'Country' }), kind: 'dimension' },
      { key: 'year', label: t('cost_benchmarks.insights.f_year', { defaultValue: 'Year' }), kind: 'dimension' },
      { key: 'per_m2', label: t('cost_benchmarks.insights.f_per_m2', { defaultValue: 'Cost per m2' }), kind: 'measure', format: 'number' },
      { key: 'first_in_country', label: t('cost_benchmarks.insights.f_countries', { defaultValue: 'Countries' }), kind: 'measure', format: 'number' },
    ],
    rows,
  };
  const base = { datasetId: 'benchmarks', builtin: true } as const;
  const builtins: InsightDef[] = [
    { ...base, id: 'kpi-records', title: t('cost_benchmarks.insights.k_records', { defaultValue: 'Records' }), chart: 'kpi', agg: 'count', color: 0 },
    { ...base, id: 'kpi-countries', title: t('cost_benchmarks.insights.k_countries', { defaultValue: 'Countries' }), chart: 'kpi', measure: 'first_in_country', agg: 'sum', color: 1 },
    { ...base, id: 'kpi-per-m2', title: t('cost_benchmarks.insights.k_per_m2', { defaultValue: 'Average cost per m2' }), chart: 'kpi', measure: 'per_m2', agg: 'avg', color: 2 },
    { ...base, id: 'bar-by-country', title: t('cost_benchmarks.insights.c_by_country', { defaultValue: 'Average cost per m2 by country' }), chart: 'bar', dimension: 'country', measure: 'per_m2', agg: 'avg', color: 1 },
  ];
  return { datasets: [dataset], builtins };
}

/* ── Records table ─────────────────────────────────────────────────────── */

function RecordsTable({
  records,
  onDelete,
  busy,
  deletable,
}: {
  records: BenchmarkRecord[];
  onDelete?: (id: string) => void;
  busy: boolean;
  deletable: boolean;
}) {
  const { t } = useTranslation();
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border-light text-left text-2xs uppercase text-content-tertiary">
            <th className="py-2 pr-3">{t('cost_benchmarks.col_name', { defaultValue: 'Name' })}</th>
            <th className="py-2 pr-3">{t('cost_benchmarks.col_type', { defaultValue: 'Type' })}</th>
            <th className="py-2 pr-3">{t('cost_benchmarks.col_country', { defaultValue: 'Country' })}</th>
            <th className="py-2 pr-3">{t('cost_benchmarks.col_year', { defaultValue: 'Year' })}</th>
            <th className="py-2 pr-3 text-right">{t('cost_benchmarks.col_gfa', { defaultValue: 'GFA (m2)' })}</th>
            <th className="py-2 pr-3 text-right">{t('cost_benchmarks.col_per_m2', { defaultValue: 'Cost per m2' })}</th>
            {deletable && <th className="py-2" />}
          </tr>
        </thead>
        <tbody>
          {records.map((r) => (
            <tr key={r.id} className="border-b border-border-light/60" data-testid="record-row">
              <td className="py-2 pr-3 font-medium text-content-primary">
                {r.name}
                {r.is_synthetic && (
                  <Badge variant="neutral" size="sm" className="ml-2">
                    {t('cost_benchmarks.synthetic', { defaultValue: 'Sample data' })}
                  </Badge>
                )}
              </td>
              <td className="py-2 pr-3">{r.project_type}</td>
              <td className="py-2 pr-3">{r.country}</td>
              <td className="py-2 pr-3">{yearOf(r.cost_date)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{fmt(r.gfa_m2, 0)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">
                {fmt(costPerM2(r))} {r.currency}
              </td>
              {deletable && (
                <td className="py-2 text-right">
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => onDelete?.(r.id)}
                    aria-label={t('cost_benchmarks.delete', { defaultValue: 'Delete record' })}
                  >
                    <Trash2 size={14} />
                  </Button>
                </td>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/* ── Compare result ────────────────────────────────────────────────────── */

function CompareResultView({ result, onExport }: { result: CompareResult; onExport: (f: 'json' | 'csv') => void }) {
  const { t } = useTranslation();
  const unit =
    result.measure === 'gfa'
      ? t('cost_benchmarks.per_m2', { defaultValue: 'per m2' })
      : t('cost_benchmarks.per_unit', { defaultValue: 'per functional unit' });
  const { cohort, basis } = result;
  return (
    <Card className="space-y-4 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('cost_benchmarks.result_title', { defaultValue: 'Result for {{name}}', name: result.estimate.name })}
        </h2>
        {cohort.low_confidence && (
          <span data-testid="low-confidence">
            <Badge variant="warning">
              {t('cost_benchmarks.low_confidence', { defaultValue: 'Low confidence' })}
            </Badge>
          </span>
        )}
        {basis.stale && (
          <span data-testid="stale-index">
            <Badge variant="warning">
              {t('cost_benchmarks.stale_index', { defaultValue: 'Stale cost index' })}
            </Badge>
          </span>
        )}
        <Badge variant={cohort.source === 'own' ? 'success' : 'blue'}>
          {cohort.source === 'own'
            ? t('cost_benchmarks.source_own', { defaultValue: 'Band from your own history' })
            : t('cost_benchmarks.source_reference', {
                defaultValue: 'Band from open reference data{{source}}',
                source: cohort.reference_source ? ` (${cohort.reference_source})` : '',
              })}
        </Badge>
        <span className="text-xs text-content-tertiary">
          {t('cost_benchmarks.cohort_count', {
            defaultValue_one: '{{count}} project in the cohort (minimum {{min}})',
            defaultValue_other: '{{count}} projects in the cohort (minimum {{min}})',
            count: cohort.count,
            min: cohort.min_projects,
          })}
        </span>
      </div>

      {cohort.low_confidence && (
        <p className="text-xs text-content-secondary">
          {t('cost_benchmarks.low_confidence_hint', {
            defaultValue: 'The cohort is smaller than the minimum, so treat the bands as a hint only. Widen the filters or lower the minimum.',
          })}
        </p>
      )}
      {cohort.missing_quantity.length > 0 && (
        <p className="text-xs text-content-tertiary">
          {t('cost_benchmarks.missing_quantity', {
            defaultValue: 'Left out for missing floor area or quantity: {{names}}',
            names: cohort.missing_quantity.join(', '),
          })}
        </p>
      )}

      <div className="grid gap-3 sm:grid-cols-3">
        <div>
          <div className="text-2xs uppercase text-content-tertiary">
            {t('cost_benchmarks.estimate_total', { defaultValue: 'Estimate total' })}
          </div>
          <div className="text-lg font-semibold tabular-nums">
            {fmt(result.estimate.total)} {basis.reporting_currency}
          </div>
        </div>
        <div>
          <div className="text-2xs uppercase text-content-tertiary">
            {t('cost_benchmarks.estimate_per_unit', { defaultValue: 'Estimate {{unit}}', unit })}
          </div>
          <div className="text-lg font-semibold tabular-nums">{fmt(result.estimate.total_per_unit)}</div>
        </div>
        <div>
          <div className="text-2xs uppercase text-content-tertiary">
            {t('cost_benchmarks.total_band', { defaultValue: 'Cohort P10 / P50 / P90 {{unit}}', unit })}
          </div>
          <div className="text-sm tabular-nums">
            {fmt(result.total_band.p10, 0)} / {fmt(result.total_band.p50, 0)} / {fmt(result.total_band.p90, 0)}
          </div>
          <BandBar band={result.total_band} value={result.estimate.total_per_unit} position={result.estimate.total_position} />
        </div>
      </div>

      <p className="text-2xs text-content-quaternary">
        {t('cost_benchmarks.basis', {
          defaultValue: 'Basis: prices at {{date}}, region {{region}}, currency {{currency}}, FX rate of {{fx}}.',
          date: basis.base_date ?? '-',
          region: basis.base_region ?? '-',
          currency: basis.reporting_currency,
          fx: basis.fx_rate_date ?? '-',
        })}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border-light text-left text-2xs uppercase text-content-tertiary">
              <th className="py-2 pr-3">{t('cost_benchmarks.col_element', { defaultValue: 'Element' })}</th>
              <th className="py-2 pr-3 text-right">{t('cost_benchmarks.col_estimate', { defaultValue: 'Estimate' })}</th>
              <th className="py-2 pr-3">{t('cost_benchmarks.col_band', { defaultValue: 'P10 - P50 - P90' })}</th>
              <th className="py-2 pr-3">{t('cost_benchmarks.col_position', { defaultValue: 'Position' })}</th>
            </tr>
          </thead>
          <tbody>
            {result.elements.map((el: CompareElement) => {
              const outlier = el.position === 'below' || el.position === 'above';
              return (
                <tr
                  key={el.code}
                  data-testid={`band-row-${el.code}`}
                  data-position={el.position}
                  className={clsx(
                    'border-b border-border-light/60',
                    outlier && 'bg-semantic-error-bg/40',
                  )}
                >
                  <td className="py-2 pr-3">
                    <span className="font-mono text-2xs text-content-tertiary">{el.code}</span>{' '}
                    <span className="font-medium text-content-primary">{el.label}</span>
                  </td>
                  <td className="py-2 pr-3 text-right tabular-nums">{fmt(el.estimate_per_unit)}</td>
                  <td className="py-2 pr-3">
                    <BandBar band={el.band} value={el.estimate_per_unit} position={el.position} />
                    <div className="mt-0.5 flex items-center gap-2 text-2xs text-content-quaternary tabular-nums">
                      <span>
                        {fmt(el.band.p10, 0)} / {fmt(el.band.p50, 0)} / {fmt(el.band.p90, 0)}
                      </span>
                      <span>
                        {el.band_source === 'own'
                          ? t('cost_benchmarks.src_own_short', { defaultValue: 'own history' })
                          : t('cost_benchmarks.src_ref_short', { defaultValue: 'open reference' })}
                      </span>
                    </div>
                  </td>
                  <td className="py-2 pr-3">
                    <Badge variant={outlier ? 'error' : el.position === 'within' ? 'success' : 'neutral'} size="sm">
                      {positionLabel(el.position, t)}
                    </Badge>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {result.findings.length > 0 && (
        <div>
          <h3 className="mb-1 text-xs font-semibold text-content-primary">
            {t('cost_benchmarks.findings', { defaultValue: 'Findings' })}
          </h3>
          <ul className="space-y-1" data-testid="findings">
            {result.findings.map((f, i) => (
              <li key={`${f.rule_id}-${i}`} className="flex items-start gap-2 text-xs text-content-secondary">
                <Badge variant={f.severity === 'error' ? 'error' : f.severity === 'warning' ? 'warning' : 'neutral'} size="sm">
                  {f.severity}
                </Badge>
                <span>{f.message}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-wrap gap-2 border-t border-border-light pt-3">
        <Button variant="secondary" size="sm" onClick={() => onExport('csv')}>
          <Download size={14} className="mr-1.5" />
          {t('cost_benchmarks.export_csv', { defaultValue: 'Export anonymised (CSV)' })}
        </Button>
        <Button variant="secondary" size="sm" onClick={() => onExport('json')}>
          <Download size={14} className="mr-1.5" />
          {t('cost_benchmarks.export_json', { defaultValue: 'Export anonymised (JSON)' })}
        </Button>
      </div>
    </Card>
  );
}

/* ── Page ──────────────────────────────────────────────────────────────── */

export default function CostBenchmarksPage() {
  const { t } = useTranslation();
  const queryClient = useQueryClient();
  const addToast = useToastStore((s) => s.addToast);
  const activeProjectId = useActiveProjectId();

  const [estimateId, setEstimateId] = useState('');
  const [projectType, setProjectType] = useState('');
  const [countries, setCountries] = useState('');
  const [gfaMin, setGfaMin] = useState('');
  const [gfaMax, setGfaMax] = useState('');
  const [yearFrom, setYearFrom] = useState('');
  const [yearTo, setYearTo] = useState('');
  const [baseDate, setBaseDate] = useState('');
  const [currency, setCurrency] = useState('EUR');
  const [measure, setMeasure] = useState<BenchmarkMeasure>('gfa');
  const [minProjects, setMinProjects] = useState('5');
  const [result, setResult] = useState<CompareResult | null>(null);

  const completedQuery = useQuery({
    queryKey: ['cost-benchmarks', 'records', 'completed'],
    queryFn: () => fetchRecords({ kind: 'completed' }),
  });
  const estimatesQuery = useQuery({
    queryKey: ['cost-benchmarks', 'records', 'estimate'],
    queryFn: () => fetchRecords({ kind: 'estimate' }),
  });
  const completed = completedQuery.data ?? [];
  const estimates = estimatesQuery.data ?? [];

  const onError = (err: unknown) =>
    addToast({ type: 'error', title: t('common.error', { defaultValue: 'Error' }), message: getErrorMessage(err) });

  const compareMut = useMutation({
    mutationFn: (req: CompareRequest) => compareEstimate(req),
    onSuccess: (res) => setResult(res),
    onError,
  });

  const captureMut = useMutation({
    mutationFn: (projectId: string) => captureProject(projectId),
    onSuccess: () => {
      addToast({
        type: 'success',
        title: '',
        message: t('cost_benchmarks.captured', { defaultValue: 'Project added to your benchmark history.' }),
      });
      void queryClient.invalidateQueries({ queryKey: ['cost-benchmarks', 'records'] });
    },
    onError,
  });

  const deleteMut = useMutation({
    mutationFn: (id: string) => deleteRecord(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['cost-benchmarks', 'records'] }),
    onError,
  });

  const insights = useModuleInsights('cost_benchmarks', { defaultOpen: true });
  const { datasets, builtins } = useMemo(() => buildInsights(completed, t), [completed, t]);

  const runCompare = () => {
    if (!estimateId) return;
    const req: CompareRequest = {
      estimate_id: estimateId,
      reporting_currency: currency.trim().toUpperCase() || 'EUR',
      measure,
      min_projects: Math.max(1, Number(minProjects) || 5),
      stale_months: 12,
    };
    if (projectType.trim()) req.project_type = projectType.trim();
    const list = countries.split(',').map((c) => c.trim().toUpperCase()).filter(Boolean);
    if (list.length) req.countries = list;
    if (gfaMin) req.gfa_min = gfaMin;
    if (gfaMax) req.gfa_max = gfaMax;
    if (yearFrom) req.year_from = Number(yearFrom);
    if (yearTo) req.year_to = Number(yearTo);
    if (baseDate) req.base_date = baseDate;
    compareMut.mutate(req);
  };

  const handleExport = async (format: 'json' | 'csv') => {
    try {
      await downloadAnonymised(format, result?.basis.reporting_currency || currency || 'EUR');
    } catch (err) {
      onError(err);
    }
  };

  return (
    <div className="space-y-5 animate-fade-in">
      <Breadcrumb items={[{ label: t('nav.cost_benchmarks', { defaultValue: 'Cost benchmarks' }) }]} />
      <PageHeader
        srTitle={t('cost_benchmarks.title', { defaultValue: 'Cost benchmarks' })}
        subtitle={t('cost_benchmarks.subtitle', {
          defaultValue: 'Check an estimate against the cost per m2 of your completed projects, element by element.',
        })}
        actions={
          <>
            <InsightsToggleButton open={insights.open} onClick={insights.toggle} />
            {activeProjectId && (
              <Button
                variant="secondary"
                size="sm"
                disabled={captureMut.isPending}
                onClick={() => captureMut.mutate(activeProjectId)}
              >
                {captureMut.isPending ? <Loader2 className="h-4 w-4 animate-spin" /> : <Plus size={14} className="mr-1.5" />}
                {t('cost_benchmarks.capture', { defaultValue: 'Add this project to history' })}
              </Button>
            )}
          </>
        }
      />

      <InsightsPanel
        open={insights.open}
        title={t('cost_benchmarks.insights.title', { defaultValue: 'Benchmark insights' })}
        datasets={datasets}
        builtins={builtins}
        custom={insights.custom}
        onAdd={insights.addCustom}
        onUpdate={insights.updateCustom}
        onRemove={insights.removeCustom}
        onCollapse={() => insights.setOpen(false)}
      />

      <HowBenchmarksWork />

      <Card className="space-y-3 p-4">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-content-primary">
          <BarChart3 size={16} className="text-oe-blue" />
          {t('cost_benchmarks.compare_title', { defaultValue: 'Compare an estimate' })}
        </h2>
        {estimates.length === 0 ? (
          <EmptyState
            title={t('cost_benchmarks.no_estimates', { defaultValue: 'No estimates to compare yet' })}
            description={t('cost_benchmarks.no_estimates_desc', {
              defaultValue: 'Estimates appear here once a bill of quantities is saved as a benchmark record.',
            })}
          />
        ) : (
          <>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              <label className="text-xs text-content-secondary">
                {t('cost_benchmarks.f_estimate', { defaultValue: 'Estimate' })}
                <select
                  className={clsx(SELECT_CLASS, 'mt-1 w-full')}
                  value={estimateId}
                  onChange={(e) => setEstimateId(e.target.value)}
                  aria-label={t('cost_benchmarks.f_estimate', { defaultValue: 'Estimate' })}
                >
                  <option value="">{t('cost_benchmarks.pick_estimate', { defaultValue: 'Choose an estimate' })}</option>
                  {estimates.map((e) => (
                    <option key={e.id} value={e.id}>
                      {e.name}
                    </option>
                  ))}
                </select>
              </label>
              <Input
                label={t('cost_benchmarks.f_type', { defaultValue: 'Project type' })}
                value={projectType}
                onChange={(e) => setProjectType(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_countries', { defaultValue: 'Countries (comma separated)' })}
                value={countries}
                onChange={(e) => setCountries(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_currency', { defaultValue: 'Reporting currency' })}
                value={currency}
                onChange={(e) => setCurrency(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_gfa_min', { defaultValue: 'GFA from (m2)' })}
                inputMode="decimal"
                value={gfaMin}
                onChange={(e) => setGfaMin(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_gfa_max', { defaultValue: 'GFA to (m2)' })}
                inputMode="decimal"
                value={gfaMax}
                onChange={(e) => setGfaMax(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_year_from', { defaultValue: 'Year from' })}
                inputMode="numeric"
                value={yearFrom}
                onChange={(e) => setYearFrom(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_year_to', { defaultValue: 'Year to' })}
                inputMode="numeric"
                value={yearTo}
                onChange={(e) => setYearTo(e.target.value)}
              />
              <Input
                label={t('cost_benchmarks.f_base_date', { defaultValue: 'Base date for prices' })}
                type="date"
                value={baseDate}
                onChange={(e) => setBaseDate(e.target.value)}
              />
              <label className="text-xs text-content-secondary">
                {t('cost_benchmarks.f_measure', { defaultValue: 'Measure' })}
                <select
                  className={clsx(SELECT_CLASS, 'mt-1 w-full')}
                  value={measure}
                  onChange={(e) => setMeasure(e.target.value as BenchmarkMeasure)}
                  aria-label={t('cost_benchmarks.f_measure', { defaultValue: 'Measure' })}
                >
                  <option value="gfa">{t('cost_benchmarks.m_gfa', { defaultValue: 'Per m2 of floor area' })}</option>
                  <option value="unit">{t('cost_benchmarks.m_unit', { defaultValue: 'Per functional unit' })}</option>
                </select>
              </label>
              <Input
                label={t('cost_benchmarks.f_min_projects', { defaultValue: 'Minimum projects' })}
                inputMode="numeric"
                value={minProjects}
                onChange={(e) => setMinProjects(e.target.value)}
              />
            </div>
            <Button variant="primary" size="sm" onClick={runCompare} disabled={!estimateId || compareMut.isPending}>
              {compareMut.isPending && <Loader2 className="mr-1.5 h-4 w-4 animate-spin" />}
              {t('cost_benchmarks.run', { defaultValue: 'Compare' })}
            </Button>
          </>
        )}
      </Card>

      {result && <CompareResultView result={result} onExport={(f) => void handleExport(f)} />}

      <Card className="space-y-2 p-4">
        <h2 className="text-sm font-semibold text-content-primary">
          {t('cost_benchmarks.completed_title', { defaultValue: 'Completed projects' })}
          <span className="ml-2 text-xs font-normal text-content-tertiary">
            {t('cost_benchmarks.record_count', {
              defaultValue_one: '{{count}} record',
              defaultValue_other: '{{count}} records',
              count: completed.length,
            })}
          </span>
        </h2>
        {completed.length === 0 ? (
          <EmptyState
            title={t('cost_benchmarks.no_completed', { defaultValue: 'No completed projects yet' })}
            description={t('cost_benchmarks.no_completed_desc', {
              defaultValue: 'Add a finished project to your history to build your own cost bands.',
            })}
          />
        ) : (
          <RecordsTable records={completed} onDelete={(id) => deleteMut.mutate(id)} busy={deleteMut.isPending} deletable />
        )}
      </Card>

      {estimates.length > 0 && (
        <Card className="space-y-2 p-4">
          <h2 className="text-sm font-semibold text-content-primary">
            {t('cost_benchmarks.estimates_title', { defaultValue: 'Estimates' })}
          </h2>
          <RecordsTable records={estimates} busy={false} deletable={false} />
        </Card>
      )}
    </div>
  );
}
