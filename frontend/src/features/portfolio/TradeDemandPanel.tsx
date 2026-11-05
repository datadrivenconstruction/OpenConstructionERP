// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Trade view of capacity planning: labour demand per trade and week across
 * every project (schedule activity labour plus staffing positions) against the
 * people, crews and subcontractors available. Click a cell for the activities
 * behind its demand.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { AlertTriangle, HardHat, X } from 'lucide-react';
import { Badge, Card, CardContent, EmptyState, Skeleton } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { getWorkforceDemand, type WorkforceCell, type WorkforceTradeRow } from './api';
import { getNumberLocale } from '@/stores/usePreferencesStore';

const WEEK_OPTIONS = [8, 12, 26] as const;

/** Heatmap colour for one trade-week by its status. */
export function demandCellClasses(cell: WorkforceCell | undefined): string {
  switch (cell?.status) {
    case 'short':
      return 'bg-rose-500/90 text-white font-semibold';
    case 'tight':
      return 'bg-amber-400/80 text-amber-950';
    case 'balanced':
      return 'bg-emerald-500/60 text-emerald-950';
    case 'surplus':
      return 'bg-sky-300/50 text-sky-950';
    default:
      return 'bg-surface-secondary/40 text-content-tertiary';
  }
}

function todayIso(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function fmt(raw: string, digits = 1): string {
  const n = Number(raw);
  return Number.isFinite(n) ? n.toLocaleString(getNumberLocale(), { maximumFractionDigits: digits }) : '-';
}

export function TradeDemandPanel() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const [weeks, setWeeks] = useState<number>(12);
  const start = useMemo(todayIso, []);
  const [sel, setSel] = useState<{ trade: string; week: number } | null>(null);

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['portfolio', 'workforce-demand', start, weeks],
    queryFn: () => getWorkforceDemand({ start, weeks }),
    retry: false,
  });

  const trades = data?.trades ?? [];
  const cols = `minmax(150px, 1.3fr) repeat(${Math.max(data?.weeks.length ?? 1, 1)}, minmax(48px, 1fr))`;
  const tradeLabel = (row: WorkforceTradeRow) =>
    row.unassigned ? t('workforce.no_trade', { defaultValue: 'No trade set' }) : row.label || row.trade;
  const selRow = sel ? trades.find((r) => r.trade === sel.trade) : undefined;
  const selCell = selRow?.cells[sel?.week ?? -1];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="inline-flex rounded-xl border border-border bg-surface-secondary/50 p-1">
          {WEEK_OPTIONS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setWeeks(w)}
              aria-pressed={weeks === w}
              className={`rounded-lg px-3 py-1.5 text-sm font-medium ${
                weeks === w ? 'bg-surface-primary text-content-primary shadow-sm' : 'text-content-tertiary'
              }`}
            >
              {t('workforce.weeks_n', { defaultValue: '{{count}} weeks', count: w })}
            </button>
          ))}
        </div>
        {data && (
          <span className="text-xs text-content-tertiary">
            {t('workforce.fte_note', {
              defaultValue: 'Figures are full-time people ({{hours}} h a week).',
              hours: data.hours_per_fte_week,
            })}
          </span>
        )}
      </div>

      {data && (
        <div className="flex flex-wrap gap-2">
          <Badge variant={data.short_trades > 0 ? 'error' : 'success'}>
            {t('workforce.short_trades', { defaultValue: '{{count}} trades short', count: data.short_trades })}
          </Badge>
          {data.capacity_unknown > 0 && (
            <Badge variant="warning">
              {t('workforce.capacity_unknown', {
                defaultValue: '{{count}} subcontractors without a declared head count',
                count: data.capacity_unknown,
              })}
            </Badge>
          )}
        </div>
      )}

      {data && data.findings.length > 0 && (
        <Card>
          <CardContent>
            <ul className="space-y-1.5">
              {data.findings.slice(0, 20).map((f, i) => (
                <li key={`${f.element_ref}-${i}`} className="flex gap-2 text-sm">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
                  <span>
                    {f.message}
                    {f.suggestion && <span className="block text-xs text-content-tertiary">{f.suggestion}</span>}
                  </span>
                </li>
              ))}
            </ul>
            {data.findings.length > 20 && (
              <div className="mt-1 text-xs text-content-tertiary">
                {t('workforce.more_findings', { defaultValue: 'and {{count}} more', count: data.findings.length - 20 })}
              </div>
            )}
          </CardContent>
        </Card>
      )}

      <Card>
        <CardContent>
          {isLoading && (
            <div className="space-y-2">
              {[1, 2, 3, 4].map((i) => (
                <Skeleton key={i} height={36} className="w-full" rounded="lg" />
              ))}
            </div>
          )}
          {isError && (
            <EmptyState
              icon={<AlertTriangle size={36} className="text-semantic-error" />}
              title={t('workforce.error', { defaultValue: 'Could not load trade demand' })}
              description={getErrorMessage(error)}
            />
          )}
          {data && !isLoading && trades.length === 0 && (
            <EmptyState
              icon={<HardHat size={36} className="text-content-tertiary" />}
              title={t('workforce.empty_title', { defaultValue: 'No labour demand in this window' })}
              description={t('workforce.empty_desc', {
                defaultValue:
                  'Give schedule activities a labour resource with a trade and hours or head count, or plan staffing positions, and the demand shows up here against your people and crews.',
              })}
            />
          )}
          {data && trades.length > 0 && (
            <div className="overflow-x-auto">
              <div className="min-w-[640px]">
                <div className="grid items-end gap-1 pb-2" style={{ gridTemplateColumns: cols }}>
                  <div className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
                    {t('workforce.trade', { defaultValue: 'Trade' })}
                  </div>
                  {data.weeks.map((w) => (
                    <div key={w.index} className="text-center text-[11px] text-content-tertiary" title={`${w.start} - ${w.end}`}>
                      {w.label}
                    </div>
                  ))}
                </div>
                <div className="space-y-1">
                  {trades.map((row) => (
                    <div key={row.trade || '_none'} className="grid items-center gap-1" style={{ gridTemplateColumns: cols }}>
                      <div className="min-w-0 pr-2">
                        <div className="truncate text-sm font-medium text-content-primary">{tradeLabel(row)}</div>
                        <div className="truncate text-[11px] text-content-tertiary">
                          {t('workforce.row_sub', {
                            defaultValue: '{{count}} available · peak short {{short}}',
                            count: row.available_resources,
                            short: fmt(row.peak_shortfall_fte),
                          })}
                        </div>
                      </div>
                      {row.cells.map((c) => {
                        const active = sel?.trade === row.trade && sel.week === c.week_index;
                        return (
                          <button
                            key={c.week_index}
                            type="button"
                            disabled={c.status === 'idle'}
                            onClick={() => setSel(active ? null : { trade: row.trade, week: c.week_index })}
                            title={`${t('workforce.demand', { defaultValue: 'Demand' })} ${fmt(c.demand_fte)} / ${t('workforce.available', { defaultValue: 'Available' })} ${fmt(c.available_fte)}`}
                            className={`flex h-9 items-center justify-center rounded-md text-[11px] tabular-nums ${demandCellClasses(c)} ${
                              active ? 'ring-2 ring-inset ring-oe-blue' : ''
                            }`}
                          >
                            {c.status === 'idle' ? '' : fmt(c.gap_fte)}
                          </button>
                        );
                      })}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
          {data && trades.length > 0 && (
            <div className="mt-4 flex flex-wrap gap-x-4 gap-y-2 border-t border-border pt-3 text-xs text-content-tertiary">
              <span>{t('workforce.legend_gap', { defaultValue: 'Cell = available minus demand' })}</span>
              {(['short', 'tight', 'balanced', 'surplus'] as const).map((s) => (
                <span key={s} className="inline-flex items-center gap-1.5">
                  <span className={`h-3.5 w-3.5 rounded-md ${demandCellClasses({ status: s } as WorkforceCell)}`} />
                  {t(`workforce.status_${s}`, {
                    defaultValue: { short: 'Short', tight: 'Tight', balanced: 'Covered', surplus: 'Spare people' }[s],
                  })}
                </span>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {selRow && selCell && data && (
        <Card>
          <CardContent>
            <div className="mb-2 flex items-start justify-between gap-2">
              <div>
                <h3 className="text-sm font-semibold text-content-primary">
                  {tradeLabel(selRow)} · {data.weeks[selCell.week_index]?.label}
                </h3>
                <div className="text-xs text-content-tertiary">
                  {t('workforce.cell_summary', {
                    defaultValue: 'Demand {{demand}}, available {{available}}, gap {{gap}}',
                    demand: fmt(selCell.demand_fte),
                    available: fmt(selCell.available_fte),
                    gap: fmt(selCell.gap_fte),
                  })}
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSel(null)}
                aria-label={t('common.close', { defaultValue: 'Close' })}
                className="rounded p-1 text-content-tertiary hover:text-content-primary"
              >
                <X size={16} />
              </button>
            </div>
            <ul className="divide-y divide-border-light">
              {selCell.contributors.map((c) => (
                <li key={`${c.kind}-${c.id}`} className="flex items-center justify-between gap-3 py-2 text-sm">
                  <button
                    type="button"
                    className="min-w-0 text-left hover:text-oe-blue"
                    onClick={() =>
                      navigate(
                        c.project_id
                          ? `/projects/${encodeURIComponent(c.project_id)}/${c.kind === 'activity' ? 'schedule-advanced' : 'staffing'}`
                          : '/schedule',
                      )
                    }
                  >
                    <div className="truncate font-medium">{c.name}</div>
                    <div className="truncate text-xs text-content-tertiary">
                      {c.project_name} · {c.start} - {c.end} ·{' '}
                      {c.kind === 'activity'
                        ? t('workforce.kind_activity', { defaultValue: 'Schedule activity' })
                        : t('workforce.kind_staffing', { defaultValue: 'Staffing position' })}
                    </div>
                  </button>
                  <span className="shrink-0 tabular-nums">{fmt(c.fte, 2)}</span>
                </li>
              ))}
            </ul>
            {selCell.more_contributors > 0 && (
              <div className="mt-1 text-xs text-content-tertiary">
                {t('workforce.more_findings', { defaultValue: 'and {{count}} more', count: selCell.more_contributors })}
              </div>
            )}
          </CardContent>
        </Card>
      )}
    </div>
  );
}
