// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The historical range for estimating screens: what your own past projects
// actually achieved for work with the same classification code, read from the
// same benchmark service as Analytics -> Performance.
//
// Kept visibly apart from the two other ranges an estimator meets: the market
// range (rates from cost databases and supplier prices) and the estimate class
// accuracy band (how far a whole estimate may land from the outturn). This one
// is neither: it is measured hours per unit from approved timesheets and
// reported progress, on other projects only. Nothing is written anywhere.

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Link } from 'react-router-dom';
import { ChevronDown, ChevronRight, History } from 'lucide-react';
import { Badge, InfoHint, Skeleton } from '@/shared/ui';
import {
  checkAgainstCohort,
  DEFAULT_READING,
  EMPTY_COHORT,
  fetchPositionContext,
  rangeBand,
  toNumber,
  type PerformanceCheckResponse,
  type PerformancePositionContextItem,
} from './performance';
import { fmtValue, fmtVariance, prettyUnit } from './performanceFormat';

/** Batch size the server accepts in one call. */
const MAX_POSITIONS = 500;
/** The minimum the position-context request asks for by default. */
const MIN_PROJECTS = DEFAULT_READING.min_projects;

/** True when the range rests on fewer projects or records than the minimum: shown, never judged. */
function isThin(item: PerformancePositionContextItem): boolean {
  return item.shortfall.length > 0;
}

/** The historical context of up to 500 positions, in one request. */
export function useHistoricalContext(positionIds: string[], enabled: boolean) {
  const ids = useMemo(() => [...new Set(positionIds)].sort().slice(0, MAX_POSITIONS), [positionIds]);
  const query = useQuery({
    queryKey: ['analytics', 'performance', 'position-context', ids],
    queryFn: () => fetchPositionContext({ position_ids: ids }),
    enabled: enabled && ids.length > 0,
    staleTime: 5 * 60_000,
  });
  const byId = useMemo(
    () => new Map((query.data?.items ?? []).map((item) => [item.position_id, item])),
    [query.data],
  );
  return { ...query, byId, classificationKey: query.data?.classification_key ?? null };
}

/** One position's historical median and P25-P75, with where its planned norm sits. */
export function HistoricalRangeCell({
  item,
  bandFor,
}: {
  item: PerformancePositionContextItem | undefined;
  /** Compare another figure than the planned norm, such as the norm the site achieved. */
  bandFor?: number | null;
}) {
  const { t } = useTranslation();
  if (!item) return <span className="text-content-tertiary">-</span>;
  if (item.status !== 'ok') {
    return (
      <span className="text-2xs text-content-tertiary" title={statusText(t, item.status)}>
        {t('analytics.hist.none_short', { defaultValue: 'no history' })}
      </span>
    );
  }
  const unit = item.value_unit ? ` ${prettyUnit(item.value_unit)}` : '';
  const median = fmtValue(item.median);
  const lo = fmtValue(item.p25);
  const hi = fmtValue(item.p75);
  return (
    <span className="inline-flex flex-wrap items-center gap-1 tabular-nums" data-testid="historical-range-cell">
      <span className="font-medium text-content-primary">
        {median}
        {unit}
      </span>
      {lo !== null && hi !== null && (
        <span className="text-2xs text-content-tertiary">
          ({lo} - {hi})
        </span>
      )}
      {isThin(item) ? (
        <Badge variant="warning" size="sm">
          {t('analytics.perf.insufficient', {
            defaultValue: 'Not enough evidence for a benchmark: {{have}} of {{min}} projects',
            have: item.projects,
            min: MIN_PROJECTS,
          })}
        </Badge>
      ) : bandFor !== undefined ? (
        (() => {
          const band = rangeBand(bandFor, item.p25, item.p75);
          return band ? <BandBadge band={band} /> : null;
        })()
      ) : (
        item.band && <BandBadge band={item.band} />
      )}
      <span className="text-2xs text-content-tertiary">
        {t('analytics.hist.projects_short', { defaultValue: '{{count}} proj.', count: item.projects })}
      </span>
    </span>
  );
}

function BandBadge({ band }: { band: 'below' | 'within' | 'above' }) {
  const { t } = useTranslation();
  return (
    <Badge variant={band === 'within' ? 'success' : 'warning'} size="sm">
      {t(`analytics.perf.band_${band}`, {
        defaultValue: band === 'below' ? 'Below P25' : band === 'above' ? 'Above P75' : 'Within range',
      })}
    </Badge>
  );
}

function statusText(t: ReturnType<typeof useTranslation>['t'], status: string): string {
  return t(`analytics.hist.status.${status}`, {
    defaultValue:
      status === 'no_classification'
        ? 'This position has no classification code to match past work by.'
        : status === 'no_comparable_group'
          ? 'No past project has measured work with this code and unit.'
          : status === 'no_estimate_value'
            ? 'This position has no planned labour norm to compare.'
            : 'No historical range for this position.',
  });
}

export interface HistoricalPositionLabel {
  id: string;
  ordinal: string;
  description: string;
}

/**
 * A collapsible strip for the bill editor. Closed by default and loaded only
 * when opened, so a bill nobody asks about costs nothing.
 */
export function HistoricalRangePanel({ positions }: { positions: HistoricalPositionLabel[] }) {
  const { t } = useTranslation();
  const [open, setOpen] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const ids = useMemo(() => positions.map((p) => p.id), [positions]);
  const ctx = useHistoricalContext(ids, open);
  const rows = useMemo(() => {
    const labelled = positions
      .map((p) => ({ position: p, item: ctx.byId.get(p.id) }))
      .filter((r): r is { position: HistoricalPositionLabel; item: PerformancePositionContextItem } => Boolean(r.item));
    const ok = labelled.filter((r) => r.item.status === 'ok');
    // Well-evidenced ranges first, then the largest departures from history: the norms worth a second look.
    ok.sort(
      (a, b) =>
        Number(isThin(a.item)) - Number(isThin(b.item)) ||
        Math.abs(toNumber(b.item.variance) ?? 0) - Math.abs(toNumber(a.item.variance) ?? 0),
    );
    return { ok, withoutHistory: labelled.length - ok.length };
  }, [positions, ctx.byId]);
  const shown = showAll ? rows.ok : rows.ok.slice(0, 10);

  return (
    <div className="mt-3 rounded-lg border border-border-light bg-surface-primary" data-testid="boq-historical-range">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full items-center gap-2 px-3 py-2 text-left text-xs font-medium text-content-primary"
      >
        {open ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
        <History size={14} className="text-oe-blue" />
        {t('analytics.hist.title', { defaultValue: 'Historical actuals for these positions' })}
        <span className="font-normal text-content-tertiary">
          {t('analytics.hist.subtitle', { defaultValue: 'labour hours per unit measured on your past projects' })}
        </span>
        <span className="ms-auto" onClick={(e) => e.stopPropagation()}>
          <InfoHint
            inline
            text={t('analytics.hist.how', {
              defaultValue:
                'Matched by classification code and unit against your other projects: approved timesheet hours booked to positions over the installed quantity. The median and P25 - P75 are shown. This is not the market price range and not the estimate accuracy band. Nothing is changed in the bill.',
            })}
          />
        </span>
      </button>
      {open && (
        <div className="border-t border-border-light px-3 py-2 text-xs">
          {ctx.isLoading ? (
            <Skeleton className="h-16 w-full" />
          ) : ctx.isError ? (
            <p className="text-semantic-error">
              {t('analytics.hist.error', { defaultValue: 'Could not load the historical range.' })}
            </p>
          ) : rows.ok.length === 0 ? (
            <p className="text-content-secondary">
              {t('analytics.hist.empty', {
                defaultValue:
                  'No past project has measured work with the same classification codes yet. History builds up as timesheets are booked to positions and progress is reported.',
              })}{' '}
              <Link to="/analytics?tab=performance" className="text-oe-blue hover:underline">
                {t('analytics.hist.open_analytics', { defaultValue: 'Open historical performance' })}
              </Link>
            </p>
          ) : (
            <>
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border-light text-left text-content-tertiary">
                    <th className="py-1 pe-2 font-medium">{t('analytics.hist.col_position', { defaultValue: 'Position' })}</th>
                    <th className="px-2 py-1 font-medium">
                      {t('analytics.hist.col_code', { defaultValue: 'Code ({{key}})', key: ctx.classificationKey ?? '-' })}
                    </th>
                    <th className="px-2 py-1 text-right font-medium">{t('analytics.hist.col_planned', { defaultValue: 'Planned h/unit' })}</th>
                    <th className="px-2 py-1 font-medium">{t('analytics.hist.col_history', { defaultValue: 'History: median (P25 - P75)' })}</th>
                    <th className="px-2 py-1 text-right font-medium">{t('analytics.hist.col_variance', { defaultValue: 'Planned vs history' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {shown.map(({ position, item }) => (
                    <tr key={position.id} className="border-b border-border-light last:border-0">
                      <td className="max-w-[18rem] truncate py-1 pe-2" title={position.description}>
                        <span className="text-content-tertiary">{position.ordinal}</span> {position.description}
                      </td>
                      <td className="px-2 py-1 text-content-secondary">{item.classification_code}</td>
                      <td className="px-2 py-1 text-right tabular-nums">{fmtValue(item.estimate) ?? '-'}</td>
                      <td className="px-2 py-1">
                        <HistoricalRangeCell item={item} />
                      </td>
                      <td className="px-2 py-1 text-right tabular-nums">
                        {isThin(item) ? '-' : (fmtVariance(item.variance) ?? '-')}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <div className="mt-1 flex flex-wrap items-center gap-3 text-2xs text-content-tertiary">
                {rows.ok.length > 10 && (
                  <button type="button" className="text-oe-blue hover:underline" onClick={() => setShowAll((v) => !v)}>
                    {showAll
                      ? t('analytics.hist.show_less', { defaultValue: 'Show the ten largest differences' })
                      : t('analytics.hist.show_all', { defaultValue: 'Show all {{count}}', count: rows.ok.length })}
                  </button>
                )}
                {rows.withoutHistory > 0 && (
                  <span>
                    {t('analytics.hist.without', {
                      defaultValue: '{{count}} positions have no comparable history.',
                      count: rows.withoutHistory,
                    })}
                  </span>
                )}
              </div>
            </>
          )}
        </div>
      )}
    </div>
  );
}

/**
 * Cost per floor area of a conceptual estimate against the actual cost per
 * floor area of your completed projects (budget actuals over gross floor area).
 * Separate from the estimate class accuracy band shown beside it.
 */
export function HistoricalCostPerArea({
  costPerArea,
  currency,
}: {
  costPerArea: number | null;
  currency: string;
}) {
  const { t } = useTranslation();
  const value = costPerArea !== null && Number.isFinite(costPerArea) && costPerArea > 0 ? costPerArea : null;
  const query = useQuery({
    queryKey: ['analytics', 'performance', 'check', 'actual_cost_per_floor_area', value, currency],
    queryFn: () =>
      checkAgainstCohort({
        ...EMPTY_COHORT,
        ...DEFAULT_READING,
        statistic: 'median',
        kpi: 'actual_cost_per_floor_area',
        value: String(value),
        unit: null,
        currency: currency || null,
        reporting_currency: currency || null,
      }),
    enabled: value !== null,
    staleTime: 5 * 60_000,
  });
  if (value === null) return null;
  return (
    <div className="rounded-lg border border-border-light bg-surface-secondary px-3 py-2 text-xs" data-testid="historical-cost-per-area">
      <div className="flex items-center gap-2 font-medium text-content-primary">
        <History size={14} className="text-oe-blue" />
        {t('analytics.hist.cost_title', { defaultValue: 'Against your completed projects' })}
        <InfoHint
          inline
          text={t('analytics.hist.cost_how', {
            defaultValue:
              'Actual cost per m² of gross floor area on your past projects, from recorded budget actuals, restated into this currency where an FX rate exists. This is history, not the accuracy band of the estimate class.',
          })}
        />
      </div>
      {query.isLoading ? (
        <Skeleton className="mt-1 h-4 w-48" />
      ) : query.data ? (
        <CostCheckLine result={query.data} currency={currency} />
      ) : null}
    </div>
  );
}

function CostCheckLine({ result, currency }: { result: PerformanceCheckResponse; currency: string }) {
  const { t } = useTranslation();
  if (result.status !== 'ok' || !result.group) {
    return (
      <p className="mt-1 text-content-secondary">
        {t('analytics.hist.cost_none', {
          defaultValue:
            'Not enough completed projects with actual costs and a gross floor area yet. Record budget actuals and the floor area on finished projects to build this comparison.',
        })}
      </p>
    );
  }
  const b = result.group.benchmark;
  const unit = `${currency}/m²`;
  return (
    <div className="mt-1 flex flex-wrap items-center gap-2 text-content-secondary">
      <span>
        {t('analytics.hist.cost_median', { defaultValue: 'Median {{value}}', value: `${fmtValue(b.median) ?? '-'} ${unit}` })}
      </span>
      {b.p25 != null && b.p75 != null && (
        <span className="text-content-tertiary">
          (P25 - P75: {fmtValue(b.p25)} - {fmtValue(b.p75)})
        </span>
      )}
      {result.shortfall.length > 0 ? (
        <Badge variant="warning" size="sm">
          {t('analytics.perf.insufficient', {
            defaultValue: 'Not enough evidence for a benchmark: {{have}} of {{min}} projects',
            have: result.group.evidence.projects_with_value,
            min: MIN_PROJECTS,
          })}
        </Badge>
      ) : (
        result.band && <BandBadge band={result.band} />
      )}
      {result.variance != null && result.shortfall.length === 0 && (
        <span>
          {t('analytics.hist.cost_variance', {
            defaultValue: 'this estimate {{variance}}',
            variance: fmtVariance(result.variance) ?? '-',
          })}
        </span>
      )}
      <span className="text-content-tertiary">
        {t('analytics.perf.evidence_value', {
          defaultValue: '{{projects}} projects, {{records}} records',
          projects: result.group.evidence.projects_with_value,
          records: result.group.evidence.records,
        })}
      </span>
    </div>
  );
}
