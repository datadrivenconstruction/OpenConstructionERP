// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Foreman productivity tab: per bill position for a period, what was installed,
 * the hours it took, the rate against the estimate norm, and the hours left at
 * the rate the crew is actually running. Cards on a phone, a table on a desk.
 */

import { Fragment, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, ChevronDown, ChevronRight, Gauge, Info, Timer, Truck } from 'lucide-react';
import { Badge, Card, CardContent, EmptyState, KpiBand, Skeleton } from '@/shared/ui';
import type { KpiBandItem } from '@/shared/ui';
import { getErrorMessage } from '@/shared/lib/api';
import { useProductivity, type ProductivityRow, type ProductivityWeek } from './productivityApi';
import { LIGHT_DOT, barHeight, fmtFactorPct, fmtNum, periodFor, type PeriodPreset } from './productivityView';

const PRESETS: PeriodPreset[] = ['this_week', 'last_week', 'last_4_weeks', 'month'];

export function ProductivityPanel({ projectId }: { projectId: string }) {
  const { t, i18n } = useTranslation();
  const lang = i18n.language;
  const [preset, setPreset] = useState<PeriodPreset | 'custom'>('last_4_weeks');
  const initial = useMemo(() => periodFor('last_4_weeks'), []);
  const [range, setRange] = useState(initial);
  const [open, setOpen] = useState<string | null>(null);
  const q = useProductivity(projectId, range.from, range.to);

  const pick = (p: PeriodPreset) => {
    setPreset(p);
    setRange(periodFor(p));
  };

  const presetLabel: Record<PeriodPreset, string> = {
    this_week: t('field_productivity.period_this_week', { defaultValue: 'This week' }),
    last_week: t('field_productivity.period_last_week', { defaultValue: 'Last week' }),
    last_4_weeks: t('field_productivity.period_last_4_weeks', { defaultValue: 'Last 4 weeks' }),
    month: t('field_productivity.period_month', { defaultValue: 'This month' }),
  };

  const data = q.data;
  const rows = data?.rows ?? [];
  const totals = data?.totals;
  const kpis: KpiBandItem[] = totals
    ? [
        {
          key: 'factor',
          label: t('field_productivity.kpi_factor', { defaultValue: 'Hours vs norm' }),
          value: fmtFactorPct(totals.productivity_factor, lang),
          sub: t('field_productivity.kpi_factor_sub', { defaultValue: 'Spent over earned hours; above 100% is slower than the norm' }),
          icon: Gauge,
          tone: totals.light === 'red' ? 'danger' : totals.light === 'amber' ? 'warning' : totals.light === 'green' ? 'success' : 'default',
        },
        {
          key: 'earned',
          label: t('field_productivity.kpi_earned', { defaultValue: 'Earned hours' }),
          value: fmtNum(totals.earned_hours, 0, lang),
          sub: t('field_productivity.kpi_spent', {
            defaultValue: '{{hours}} h spent on positions with a norm',
            hours: fmtNum(totals.spent_hours_with_norm, 0, lang),
          }),
          icon: Timer,
        },
        {
          key: 'labour',
          label: t('field_productivity.kpi_labour', { defaultValue: 'Labour hours' }),
          value: fmtNum(totals.labour_hours, 0, lang),
          icon: Timer,
        },
        {
          key: 'plant',
          label: t('field_productivity.kpi_plant', { defaultValue: 'Plant hours' }),
          value: fmtNum(totals.plant_hours, 0, lang),
          icon: Truck,
        },
      ]
    : [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => (
          <button
            key={p}
            type="button"
            onClick={() => pick(p)}
            aria-pressed={preset === p}
            className={
              'min-h-[40px] rounded-full border px-3 text-sm font-medium transition-colors ' +
              (preset === p
                ? 'border-oe-blue bg-oe-blue/10 text-oe-blue-text'
                : 'border-border text-content-secondary hover:text-content-primary')
            }
          >
            {presetLabel[p]}
          </button>
        ))}
        <label className="flex items-center gap-1 text-sm text-content-secondary">
          <span className="sr-only">{t('field_productivity.from', { defaultValue: 'From' })}</span>
          <input
            type="date"
            value={range.from}
            onChange={(e) => {
              setPreset('custom');
              setRange((r) => ({ ...r, from: e.target.value }));
            }}
            className="min-h-[40px] rounded-lg border border-border bg-surface-primary px-2"
          />
        </label>
        <label className="flex items-center gap-1 text-sm text-content-secondary">
          <span aria-hidden>-</span>
          <span className="sr-only">{t('field_productivity.to', { defaultValue: 'To' })}</span>
          <input
            type="date"
            value={range.to}
            onChange={(e) => {
              setPreset('custom');
              setRange((r) => ({ ...r, to: e.target.value }));
            }}
            className="min-h-[40px] rounded-lg border border-border bg-surface-primary px-2"
          />
        </label>
      </div>

      {q.isLoading && (
        <div className="space-y-2">
          {[1, 2, 3].map((i) => (
            <Skeleton key={i} height={56} className="w-full" rounded="lg" />
          ))}
        </div>
      )}

      {q.isError && (
        <EmptyState
          icon={<AlertTriangle size={32} className="text-semantic-error" />}
          title={t('field_productivity.error', { defaultValue: 'Could not load productivity' })}
          description={getErrorMessage(q.error)}
        />
      )}

      {data && <KpiBand items={kpis} />}

      {data && data.weeks.length > 1 && <WeekTrend weeks={data.weeks} lang={lang} />}

      {data && data.findings.length > 0 && (
        <Card>
          <CardContent>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">
              {t('field_productivity.findings', { defaultValue: 'Checks' })}
            </h3>
            <ul className="space-y-1.5">
              {data.findings.map((f, i) => (
                <li key={`${f.rule_id}-${f.element_ref}-${i}`} className="flex gap-2 text-sm">
                  {f.severity === 'warning' ? (
                    <AlertTriangle size={16} className="mt-0.5 shrink-0 text-semantic-warning" />
                  ) : (
                    <Info size={16} className="mt-0.5 shrink-0 text-oe-blue" />
                  )}
                  <span>
                    <span className="text-content-primary">{f.message}</span>
                    {f.suggestion && <span className="block text-xs text-content-tertiary">{f.suggestion}</span>}
                  </span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      )}

      {data && rows.length === 0 && (
        <EmptyState
          icon={<Gauge size={32} className="text-content-tertiary" />}
          title={t('field_productivity.empty_title', { defaultValue: 'Nothing booked or installed in this period' })}
          description={t('field_productivity.empty_desc', {
            defaultValue:
              'Approved timesheet hours booked to a bill position, and progress or measurements on it, show up here.',
          })}
        />
      )}

      {rows.length > 0 && (
        <>
          {/* Phone: one card per position, tap for crews and forecast. */}
          <div className="space-y-2 md:hidden">
            {rows.map((r) => {
              const key = r.position_id ?? `code:${r.cost_code}`;
              return (
                <Card key={key} padding="none">
                  <button
                    type="button"
                    onClick={() => setOpen(open === key ? null : key)}
                    aria-expanded={open === key}
                    className="w-full p-3 text-left"
                  >
                    <div className="flex items-start gap-2">
                      <span className={`mt-1.5 h-3 w-3 shrink-0 rounded-full ${LIGHT_DOT[r.light]}`} aria-hidden />
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-sm font-semibold text-content-primary">
                          {r.ref || t('field_productivity.no_code', { defaultValue: 'No cost code' })}
                        </div>
                        <div className="truncate text-xs text-content-tertiary">{r.description}</div>
                      </div>
                      <div className="text-right">
                        <div className="text-base font-bold tabular-nums">{fmtFactorPct(r.productivity_factor, lang)}</div>
                        <StatusBadge row={r} />
                      </div>
                    </div>
                    <div className="mt-2 grid grid-cols-3 gap-2 text-xs">
                      <Stat label={t('field_productivity.col_installed', { defaultValue: 'Installed' })} value={`${fmtNum(r.installed_quantity, 2, lang)} ${r.unit}`} />
                      <Stat label={t('field_productivity.col_hours', { defaultValue: 'Hours' })} value={fmtNum(r.labour_hours, 1, lang)} />
                      <Stat label={t('field_productivity.col_earned', { defaultValue: 'Earned' })} value={fmtNum(r.earned_hours, 1, lang)} />
                    </div>
                  </button>
                  {open === key && (
                    <div className="border-t border-border-light p-3">
                      <RowDetail row={r} lang={lang} />
                    </div>
                  )}
                </Card>
              );
            })}
          </div>

          {/* Desk: one table, expand a row for crews, weeks and forecast. */}
          <Card padding="none" className="hidden md:block">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-content-tertiary">
                    <th className="w-6 px-2 py-2" />
                    <th className="px-2 py-2">{t('field_productivity.col_position', { defaultValue: 'Position' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_installed', { defaultValue: 'Installed' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_hours', { defaultValue: 'Hours' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_plant', { defaultValue: 'Plant h' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_rate', { defaultValue: 'h / unit' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_norm', { defaultValue: 'Norm h / unit' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_units_per_mh', { defaultValue: 'Units / man-hour' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_earned', { defaultValue: 'Earned' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_factor', { defaultValue: 'vs norm' })}</th>
                    <th className="px-2 py-2 text-right">{t('field_productivity.col_forecast', { defaultValue: 'Hours to complete' })}</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((r) => {
                    const key = r.position_id ?? `code:${r.cost_code}`;
                    const isOpen = open === key;
                    return (
                      <Fragment key={key}>
                        <tr
                          className="cursor-pointer border-b border-border-light hover:bg-surface-secondary/50"
                          onClick={() => setOpen(isOpen ? null : key)}
                        >
                          <td className="px-2 py-2 text-content-tertiary">
                            {isOpen ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                          </td>
                          <td className="max-w-[280px] px-2 py-2">
                            <div className="flex items-center gap-2">
                              <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${LIGHT_DOT[r.light]}`} aria-hidden />
                              <span className="font-medium text-content-primary">
                                {r.ref || t('field_productivity.no_code', { defaultValue: 'No cost code' })}
                              </span>
                              <StatusBadge row={r} />
                            </div>
                            <div className="truncate text-xs text-content-tertiary">{r.description}</div>
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">
                            {fmtNum(r.installed_quantity, 2, lang)} <span className="text-content-tertiary">{r.unit}</span>
                          </td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.labour_hours, 1, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.plant_hours, 1, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.actual_hours_per_unit, 3, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.norm_labour_hours_per_unit, 3, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.units_per_man_hour, 2, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.earned_hours, 1, lang)}</td>
                          <td className="px-2 py-2 text-right font-semibold tabular-nums">{fmtFactorPct(r.productivity_factor, lang)}</td>
                          <td className="px-2 py-2 text-right tabular-nums">{fmtNum(r.forecast_hours_to_complete, 0, lang)}</td>
                        </tr>
                        {isOpen && (
                          <tr className="border-b border-border-light bg-surface-secondary/30">
                            <td />
                            <td colSpan={10} className="px-2 py-3">
                              <RowDetail row={r} lang={lang} />
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-content-tertiary">{label}</div>
      <div className="font-medium tabular-nums text-content-primary">{value}</div>
    </div>
  );
}

function StatusBadge({ row }: { row: ProductivityRow }) {
  const { t } = useTranslation();
  const label: Record<string, string> = {
    on_plan: t('field_productivity.status_on_plan', { defaultValue: 'On norm' }),
    under_productive: t('field_productivity.status_under', { defaultValue: 'Slower than norm' }),
    over_productive: t('field_productivity.status_over', { defaultValue: 'Faster than norm' }),
    no_progress: t('field_productivity.status_no_progress', { defaultValue: 'Hours, no progress' }),
    no_baseline: t('field_productivity.status_no_baseline', { defaultValue: 'No norm' }),
    no_actuals: t('field_productivity.status_no_actuals', { defaultValue: 'No hours yet' }),
  };
  const variant =
    row.light === 'red' ? 'error' : row.light === 'amber' ? 'warning' : row.light === 'green' ? 'success' : 'neutral';
  return (
    <Badge variant={variant} size="sm">
      {label[row.status] ?? row.status}
    </Badge>
  );
}

function RowDetail({ row, lang }: { row: ProductivityRow; lang: string }) {
  const { t } = useTranslation();
  const basis: Record<ProductivityRow['forecast_basis'], string> = {
    to_date_rate: t('field_productivity.basis_to_date', { defaultValue: 'at the rate achieved to date' }),
    period_rate: t('field_productivity.basis_period', { defaultValue: 'at this period\'s rate' }),
    norm: t('field_productivity.basis_norm', { defaultValue: 'at the estimate norm (no rate measured yet)' }),
    none: t('field_productivity.basis_none', { defaultValue: 'no rate to forecast from' }),
  };
  const source =
    row.quantity_source === 'measurement'
      ? t('field_productivity.source_measurement', { defaultValue: 'Quantity from the measurement book' })
      : row.quantity_source === 'progress'
        ? t('field_productivity.source_progress', { defaultValue: 'Quantity from reported progress' })
        : t('field_productivity.source_none', { defaultValue: 'No quantity recorded' });
  return (
    <div className="grid gap-4 md:grid-cols-3">
      <div className="space-y-1 text-sm">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('field_productivity.forecast', { defaultValue: 'Forecast' })}
        </h4>
        <div>
          {t('field_productivity.remaining', {
            defaultValue: '{{qty}} {{unit}} left of {{planned}}',
            qty: fmtNum(row.remaining_quantity, 2, lang),
            unit: row.unit,
            planned: fmtNum(row.planned_quantity, 2, lang),
          })}
        </div>
        <div className="font-semibold">
          {t('field_productivity.forecast_hours', {
            defaultValue: '{{hours}} h to complete',
            hours: fmtNum(row.forecast_hours_to_complete, 0, lang),
          })}{' '}
          <span className="font-normal text-content-tertiary">{basis[row.forecast_basis]}</span>
        </div>
        <div className="text-content-secondary">
          {t('field_productivity.budget_hours', {
            defaultValue: 'Norm allows {{hours}} h',
            hours: fmtNum(row.budget_hours_to_complete, 0, lang),
          })}
        </div>
        <div className="text-xs text-content-tertiary">{source}</div>
      </div>
      <div className="text-sm">
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('field_productivity.crews', { defaultValue: 'Crews' })}
        </h4>
        {row.crews.length === 0 ? (
          <div className="text-content-tertiary">-</div>
        ) : (
          <ul className="space-y-1">
            {row.crews.map((c) => (
              <li key={c.crew_id ?? 'none'} className="flex justify-between gap-2">
                <span className="truncate">
                  {c.crew_name || t('field_productivity.no_crew', { defaultValue: 'Not in a crew' })}{' '}
                  <span className="text-content-tertiary">
                    {t('field_productivity.workers', { defaultValue: '{{count}} workers', count: c.workers })}
                  </span>
                </span>
                <span className="tabular-nums">
                  {fmtNum(c.labour_hours, 1, lang)} h · {fmtNum(c.share_pct, 0, lang)}%
                </span>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="text-sm">
        <h4 className="mb-1 text-xs font-semibold uppercase tracking-wide text-content-tertiary">
          {t('field_productivity.by_week', { defaultValue: 'By week' })}
        </h4>
        <ul className="space-y-1">
          {row.weeks.map((w) => (
            <li key={w.week_start} className="flex justify-between gap-2 tabular-nums">
              <span className="text-content-tertiary">{w.week_start}</span>
              <span>
                {fmtNum(w.quantity, 2, lang)} {row.unit} · {fmtNum(w.labour_hours, 1, lang)} h ·{' '}
                {fmtFactorPct(w.productivity_factor, lang)}
              </span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function WeekTrend({ weeks, lang }: { weeks: ProductivityWeek[]; lang: string }) {
  const { t } = useTranslation();
  const max = Math.max(1, ...weeks.map((w) => Math.max(Number(w.labour_hours ?? 0), Number(w.earned_hours ?? 0))));
  return (
    <Card>
      <CardContent>
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-sm font-semibold text-content-primary">
            {t('field_productivity.trend', { defaultValue: 'Trend by week' })}
          </h3>
          <div className="flex gap-3 text-xs text-content-tertiary">
            <span className="inline-flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm bg-oe-blue" />
              {t('field_productivity.legend_spent', { defaultValue: 'Hours spent' })}
            </span>
            <span className="inline-flex items-center gap-1">
              <span className="h-2.5 w-2.5 rounded-sm bg-emerald-400" />
              {t('field_productivity.legend_earned', { defaultValue: 'Hours earned' })}
            </span>
          </div>
        </div>
        <div className="flex h-32 items-end gap-2 overflow-x-auto">
          {weeks.map((w) => (
            <div key={w.week_start} className="flex min-w-[44px] flex-1 flex-col items-center gap-1">
              <div className="text-[11px] font-semibold tabular-nums">{fmtFactorPct(w.productivity_factor, lang)}</div>
              <div className="flex h-20 w-full items-end justify-center gap-0.5">
                <div
                  className="w-3 rounded-t bg-oe-blue"
                  style={{ height: `${barHeight(w.labour_hours, max)}%` }}
                  title={`${fmtNum(w.labour_hours, 1, lang)} h`}
                />
                <div
                  className="w-3 rounded-t bg-emerald-400"
                  style={{ height: `${barHeight(w.earned_hours, max)}%` }}
                  title={`${fmtNum(w.earned_hours, 1, lang)} h`}
                />
              </div>
              <div className="text-[10px] text-content-tertiary">{w.week_start.slice(5)}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
