// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Sales Velocity (task #140) - SPAs signed per period (week/month/quarter).
 *
 * Primary source = ``SalesContract.signing_date`` for status in {signed,
 * countersigned}. Falls back to ``Buyer.contract_signed_at`` for legacy
 * buyer rows. Revenue is per-currency (multi-currency aware).
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import { useDisplayQuantity } from '@/shared/hooks/useDisplayQuantity';
import type {
  CurrencyAmount,
  SalesVelocityResponse,
} from '../api';
import { getSalesVelocity } from '../api';
import {
  DashboardEmpty,
  DashboardError,
  DashboardSkeleton,
  fmtCompactNumber,
  num,
} from './_shared';
import { getNumberLocale } from '@/stores/usePreferencesStore';

const VELOCITY_GRANULARITY_IDS = ['week', 'month', 'quarter'] as const;

interface SalesVelocityProps {
  developmentId: string;
}

type Granularity = 'week' | 'month' | 'quarter';

export function SalesVelocity({ developmentId }: SalesVelocityProps) {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  const [data, setData] = useState<SalesVelocityResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [granularity, setGranularity] = useState<Granularity>('month');
  const onGranularityKeyDown = useTabKeyboardNav<Granularity>({
    ids: VELOCITY_GRANULARITY_IDS,
    activeId: granularity,
    onChange: setGranularity,
    orientation: 'horizontal',
  });

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSalesVelocity(developmentId, { granularity })
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load sales velocity');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [developmentId, granularity, reloadKey]);

  const chartData = useMemo(() => {
    if (!data) return [];
    return data.series.map((b) => ({
      period: b.period,
      units: b.units,
      area: num(b.area_m2),
      revenueTotal: b.revenue.reduce((s, r) => s + num(r.amount), 0),
      revenueByCurrency: b.revenue,
    }));
  }, [data]);

  const maxRevenue = chartData.length
    ? Math.max(...chartData.map((b) => b.revenueTotal), 1)
    : 1;
  const maxUnits = chartData.length
    ? Math.max(...chartData.map((b) => b.units), 1)
    : 1;

  if (loading) return <DashboardSkeleton variant="bars" rows={6} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.velocity.error', {
          defaultValue: 'Could not load sales velocity',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || data.series.length === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.velocity.empty_title', {
          defaultValue: 'No signed contracts yet',
        })}
        description={t('propdev.dashboards.velocity.empty_desc', {
          defaultValue:
            'Velocity rolls SPAs that have been signed or countersigned.',
        })}
      />
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.velocity.title', {
              defaultValue: 'Sales velocity',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.velocity.subtitle', {
              defaultValue: 'SPAs signed per period.',
            })}
          </p>
        </div>
        <div
          role="tablist"
          aria-label={t('propdev.dashboards.velocity.granularity', {
            defaultValue: 'Granularity',
          })}
          onKeyDown={onGranularityKeyDown}
          className="flex rounded-lg border border-divider bg-surface-secondary p-0.5 text-xs"
        >
          {VELOCITY_GRANULARITY_IDS.map((g) => (
            <button
              key={g}
              type="button"
              role="tab"
              id={`velocity-granularity-tab-${g}`}
              aria-selected={granularity === g}
              aria-controls={`velocity-granularity-panel-${g}`}
              tabIndex={granularity === g ? 0 : -1}
              onClick={() => setGranularity(g)}
              className={
                granularity === g
                  ? 'rounded-md bg-surface-primary px-2.5 py-1 font-medium shadow-sm'
                  : 'rounded-md px-2.5 py-1 text-content-tertiary hover:text-content-primary'
              }
            >
              {t(`propdev.dashboards.velocity.gran_${g}`, {
                defaultValue: g,
              })}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-2">
        {chartData.map((b) => (
          <div key={b.period} className="rounded-lg border border-divider/50 p-2">
            <div className="mb-1 flex items-center justify-between text-xs">
              <span className="font-medium text-content-primary">{b.period}</span>
              <span className="text-content-tertiary">
                {t('propdev.dashboards.velocity.units_short_u', {
                  defaultValue: '{{count}} units • {{area}} {{unit}}',
                  count: b.units,
                  area: fmtCompactNumber(dq.convert(b.area, 'm²').value),
                  unit: dq.unitFor('m²'),
                })}
              </span>
            </div>
            <div className="flex flex-wrap gap-2 text-2xs">
              {b.revenueByCurrency.map((r) => (
                <div
                  key={r.currency}
                  className="flex items-center gap-1.5 rounded bg-surface-secondary px-1.5 py-0.5"
                >
                  <span className="font-medium">{r.currency}</span>
                  <span className="text-content-secondary">
                    {fmtCompactNumber(num(r.amount))}
                  </span>
                </div>
              ))}
            </div>
            <BarRow
              label={t('propdev.dashboards.velocity.bar_units', {
                defaultValue: 'units',
              })}
              value={b.units}
              max={maxUnits}
              color="#3b82f6"
            />
            <BarRow
              label={t('propdev.dashboards.velocity.bar_revenue', {
                defaultValue: 'revenue',
              })}
              value={b.revenueTotal}
              max={maxRevenue}
              color="#10b981"
              fmt={fmtCompactNumber}
            />
          </div>
        ))}
      </div>

      <VelocityTotals
        currencies={data.currencies}
        totals={data.totals}
        seriesLen={data.series.length}
      />
    </div>
  );
}

function BarRow({
  label,
  value,
  max,
  color,
  fmt,
}: {
  label: string;
  value: number;
  max: number;
  color: string;
  fmt?: (v: number) => string;
}) {
  const pct = max <= 0 ? 0 : Math.min(100, (value / max) * 100);
  return (
    <div className="mt-1.5 flex items-center gap-2 text-2xs">
      <span className="w-14 shrink-0 text-content-tertiary">{label}</span>
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
        {fmt ? fmt(value) : value.toLocaleString(getNumberLocale())}
      </span>
    </div>
  );
}

function VelocityTotals({
  currencies,
  totals,
  seriesLen,
}: {
  currencies: string[];
  totals: SalesVelocityResponse['totals'];
  seriesLen: number;
}) {
  const { t } = useTranslation();
  const dq = useDisplayQuantity();
  return (
    <div className="rounded-lg border border-divider bg-surface-secondary p-3">
      <div className="mb-1 flex items-center justify-between text-xs">
        <span className="font-medium text-content-primary">
          {t('propdev.dashboards.velocity.totals_label', {
            defaultValue: 'Window totals',
          })}
        </span>
        <span className="text-content-tertiary">
          {t('propdev.dashboards.velocity.totals_periods', {
            defaultValue: '{{count}} periods',
            count: seriesLen,
          })}
        </span>
      </div>
      <div className="text-xs text-content-secondary">
        {t('propdev.dashboards.velocity.totals_units_u', {
          defaultValue: '{{count}} units • {{area}} {{unit}}',
          count: totals.units,
          area: fmtCompactNumber(dq.convert(num(totals.area_m2), 'm²').value),
          unit: dq.unitFor('m²'),
        })}
      </div>
      {currencies.length > 0 && (
        <div className="mt-1 flex flex-wrap gap-1.5">
          {totals.revenue.map((r: CurrencyAmount) => (
            <span
              key={r.currency}
              className="rounded bg-surface-primary px-1.5 py-0.5 text-2xs"
            >
              <span className="font-medium">{r.currency}</span>{' '}
              <span className="text-content-secondary">
                {fmtCompactNumber(num(r.amount))}
              </span>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
