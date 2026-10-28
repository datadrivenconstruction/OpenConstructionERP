// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cash-flow Waterfall (task #140) — month-by-month projection.
 *
 * Three series per month bucket, currency-aware:
 *   - ``scheduled``        = sum of Instalment.amount due in month
 *   - ``actual_collected`` = sum of EscrowTransaction direction=credit
 *   - ``actual_disbursed`` = sum of EscrowTransaction direction=debit
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type {
  CashflowMonthBucket,
  CashflowWaterfallResponse,
  CurrencyAmount,
} from '../api';
import { getCashflowWaterfall } from '../api';
import {
  DashboardEmpty,
  DashboardError,
  DashboardSkeleton,
  fmtCompactNumber,
  num,
} from './_shared';

interface CashFlowWaterfallProps {
  developmentId: string;
  monthsWindow?: number;
}

const SERIES_COLORS = {
  scheduled: '#94a3b8',
  collected: '#10b981',
  disbursed: '#f59e0b',
};

export function CashFlowWaterfall({
  developmentId,
  monthsWindow = 12,
}: CashFlowWaterfallProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<CashflowWaterfallResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getCashflowWaterfall(developmentId, { months: monthsWindow })
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load cash-flow');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [developmentId, monthsWindow, reloadKey]);

  const rows = useMemo(() => {
    if (!data) return [];
    return data.series.map((m) => ({
      month: m.month,
      scheduledTotal: m.scheduled.reduce((s, r) => s + num(r.amount), 0),
      collectedTotal: m.actual_collected.reduce(
        (s, r) => s + num(r.amount),
        0,
      ),
      disbursedTotal: m.actual_disbursed.reduce(
        (s, r) => s + num(r.amount),
        0,
      ),
      raw: m,
    }));
  }, [data]);

  const maxValue = rows.length
    ? Math.max(
        1,
        ...rows.flatMap((r) => [
          r.scheduledTotal,
          r.collectedTotal,
          r.disbursedTotal,
        ]),
      )
    : 1;

  if (loading) return <DashboardSkeleton variant="bars" rows={monthsWindow ? Math.min(monthsWindow, 6) : 6} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.cashflow.error', {
          defaultValue: 'Could not load cash-flow waterfall',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || data.series.length === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.cashflow.empty_title', {
          defaultValue: 'No cash-flow data yet',
        })}
        description={t('propdev.dashboards.cashflow.empty_desc', {
          defaultValue:
            'Cash-flow comes from instalments + escrow transactions.',
        })}
      />
    );

  return (
    <div className="space-y-4">
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('propdev.dashboards.cashflow.title', {
            defaultValue: 'Cash-flow waterfall',
          })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('propdev.dashboards.cashflow.subtitle', {
            defaultValue:
              '{{months}} months from {{start}} - scheduled vs collected vs disbursed.',
            months: data.months,
            start: data.start_month,
          })}
        </p>
      </div>

      <SeriesLegend />

      <div className="space-y-2">
        {rows.map((r) => (
          <div
            key={r.month}
            className="rounded-lg border border-divider/50 p-2"
          >
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-medium text-content-primary">{r.month}</span>
              <CashflowMonthChips bucket={r.raw} />
            </div>
            <CashflowBar
              label={t('propdev.dashboards.cashflow.scheduled', {
                defaultValue: 'Scheduled',
              })}
              value={r.scheduledTotal}
              max={maxValue}
              color={SERIES_COLORS.scheduled}
            />
            <CashflowBar
              label={t('propdev.dashboards.cashflow.collected', {
                defaultValue: 'Collected',
              })}
              value={r.collectedTotal}
              max={maxValue}
              color={SERIES_COLORS.collected}
            />
            <CashflowBar
              label={t('propdev.dashboards.cashflow.disbursed', {
                defaultValue: 'Disbursed',
              })}
              value={r.disbursedTotal}
              max={maxValue}
              color={SERIES_COLORS.disbursed}
            />
          </div>
        ))}
      </div>

      <CashflowTotals totals={data.totals} currencies={data.currencies} />
    </div>
  );
}

function SeriesLegend() {
  const { t } = useTranslation();
  const items = [
    { code: 'scheduled', color: SERIES_COLORS.scheduled },
    { code: 'collected', color: SERIES_COLORS.collected },
    { code: 'disbursed', color: SERIES_COLORS.disbursed },
  ];
  return (
    <div className="flex flex-wrap gap-3 text-2xs text-content-tertiary">
      {items.map((i) => (
        <div key={i.code} className="flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-3 rounded-sm"
            style={{ backgroundColor: i.color }}
            aria-hidden="true"
          />
          <span>
            {t(`propdev.dashboards.cashflow.${i.code}`, {
              defaultValue: i.code,
            })}
          </span>
        </div>
      ))}
    </div>
  );
}

function CashflowMonthChips({ bucket }: { bucket: CashflowMonthBucket }) {
  const merge = new Map<string, { sched: number; coll: number; disb: number }>();
  for (const r of bucket.scheduled) {
    const e = merge.get(r.currency) ?? { sched: 0, coll: 0, disb: 0 };
    e.sched += num(r.amount);
    merge.set(r.currency, e);
  }
  for (const r of bucket.actual_collected) {
    const e = merge.get(r.currency) ?? { sched: 0, coll: 0, disb: 0 };
    e.coll += num(r.amount);
    merge.set(r.currency, e);
  }
  for (const r of bucket.actual_disbursed) {
    const e = merge.get(r.currency) ?? { sched: 0, coll: 0, disb: 0 };
    e.disb += num(r.amount);
    merge.set(r.currency, e);
  }
  return (
    <div className="flex flex-wrap gap-1.5 text-2xs text-content-tertiary">
      {Array.from(merge.entries()).map(([currency, { sched, coll, disb }]) => (
        <span
          key={currency}
          className="rounded bg-surface-secondary px-1.5 py-0.5"
        >
          <strong className="font-medium">{currency}</strong>{' '}
          {fmtCompactNumber(sched)}/{fmtCompactNumber(coll)}/
          {fmtCompactNumber(disb)}
        </span>
      ))}
    </div>
  );
}

function CashflowBar({
  label,
  value,
  max,
  color,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
}) {
  const pct = max <= 0 ? 0 : Math.min(100, (value / max) * 100);
  return (
    <div className="mt-1 flex items-center gap-2 text-2xs">
      <span className="w-20 shrink-0 text-content-tertiary">{label}</span>
      <div
        className="relative h-3 flex-1 overflow-hidden rounded-full bg-surface-secondary"
        role="progressbar"
        aria-valuenow={Math.round(pct)}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span
          className="absolute inset-y-0 left-0 rounded-full"
          style={{ width: `${pct}%`, backgroundColor: color }}
        />
      </div>
      <span className="w-16 shrink-0 text-right font-medium text-content-primary">
        {fmtCompactNumber(value)}
      </span>
    </div>
  );
}

function CashflowTotals({
  totals,
  currencies,
}: {
  totals: CashflowWaterfallResponse['totals'];
  currencies: string[];
}) {
  const { t } = useTranslation();
  const renderRow = (label: string, rows: CurrencyAmount[]) => (
    <div className="text-xs">
      <span className="text-content-tertiary">{label}</span>{' '}
      <span className="ml-1 inline-flex flex-wrap gap-1.5">
        {rows.length === 0 ? (
          <span className="text-content-tertiary">—</span>
        ) : (
          rows.map((r) => (
            <span key={r.currency} className="rounded bg-surface-primary px-1.5 py-0.5">
              <strong className="font-medium">{r.currency}</strong>{' '}
              {fmtCompactNumber(num(r.amount))}
            </span>
          ))
        )}
      </span>
    </div>
  );
  return (
    <div className="space-y-1 rounded-lg border border-divider bg-surface-secondary p-3">
      <h4 className="text-sm font-semibold text-content-primary">
        {t('propdev.dashboards.cashflow.totals', {
          defaultValue: 'Window totals',
        })}
      </h4>
      {renderRow(
        t('propdev.dashboards.cashflow.scheduled', { defaultValue: 'Scheduled' }),
        totals.scheduled,
      )}
      {renderRow(
        t('propdev.dashboards.cashflow.collected', { defaultValue: 'Collected' }),
        totals.actual_collected,
      )}
      {renderRow(
        t('propdev.dashboards.cashflow.disbursed', { defaultValue: 'Disbursed' }),
        totals.actual_disbursed,
      )}
      {currencies.length > 1 && (
        <p className="text-2xs text-content-tertiary">
          {t('propdev.dashboards.cashflow.mixed_currencies', {
            defaultValue:
              'Currencies are reported side-by-side (no FX conversion).',
          })}
        </p>
      )}
    </div>
  );
}
