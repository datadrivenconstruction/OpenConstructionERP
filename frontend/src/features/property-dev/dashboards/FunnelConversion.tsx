// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Funnel Conversion (task #140) — 5-stage funnel.
 *
 * Lead → Reservation → SPA draft → SPA signed → Handover.
 * Drop-off colour quartile (green/yellow/orange/red) is derived from
 * each stage's drop_pct.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useTabKeyboardNav } from '@/shared/hooks/useTabKeyboardNav';
import type { FunnelConversionResponse } from '../api';
import { getFunnelConversion } from '../api';
import {
  DashboardEmpty,
  DashboardError,
  DashboardSkeleton,
  dropQuartile,
  num,
} from './_shared';
import { fmtFixed } from '@/shared/lib/formatters';

interface FunnelConversionProps {
  developmentId: string;
}

const QUARTILE_COLORS: Record<0 | 1 | 2 | 3, string> = {
  0: '#10b981', // green
  1: '#f59e0b', // amber
  2: '#f97316', // orange
  3: '#ef4444', // red
};

const PERIOD_OPTIONS = [30, 90, 180, 365];

export function FunnelConversion({ developmentId }: FunnelConversionProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<FunnelConversionResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [periodDays, setPeriodDays] = useState<number>(90);
  const periodIds = useMemo(() => PERIOD_OPTIONS.map((d) => String(d)), []);
  const onPeriodKeyDown = useTabKeyboardNav<string>({
    ids: periodIds,
    activeId: String(periodDays),
    onChange: (next) => setPeriodDays(Number(next)),
    orientation: 'horizontal',
  });

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getFunnelConversion(developmentId, { period_days: periodDays })
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load funnel');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [developmentId, periodDays, reloadKey]);

  const max = useMemo(() => {
    if (!data) return 1;
    return Math.max(1, ...data.stages.map((s) => s.count));
  }, [data]);

  if (loading) return <DashboardSkeleton variant="bars" rows={5} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.funnel.error', {
          defaultValue: 'Could not load funnel',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || data.totals.leads === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.funnel.empty_title', {
          defaultValue: 'No leads in window',
        })}
        description={t('propdev.dashboards.funnel.empty_desc', {
          defaultValue:
            'Add leads to see the conversion funnel populate.',
        })}
      />
    );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.funnel.title', {
              defaultValue: 'Conversion funnel',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.funnel.subtitle', {
              defaultValue:
                'Lead → Reservation → SPA → Handover. {{conv}}% end-to-end conversion.',
              conv: fmtFixed(num(data.totals.conversion_pct), 1),
            })}
          </p>
        </div>
        <div
          role="tablist"
          aria-label={t('propdev.dashboards.funnel.window', {
            defaultValue: 'Window',
          })}
          onKeyDown={onPeriodKeyDown}
          className="flex rounded-lg border border-divider bg-surface-secondary p-0.5 text-xs"
        >
          {PERIOD_OPTIONS.map((d) => (
            <button
              key={d}
              type="button"
              role="tab"
              id={`funnel-window-tab-${d}`}
              aria-selected={periodDays === d}
              aria-controls={`funnel-window-panel-${d}`}
              tabIndex={periodDays === d ? 0 : -1}
              onClick={() => setPeriodDays(d)}
              className={
                periodDays === d
                  ? 'rounded-md bg-surface-primary px-2.5 py-1 font-medium shadow-sm'
                  : 'rounded-md px-2.5 py-1 text-content-tertiary hover:text-content-primary'
              }
            >
              {t('propdev.dashboards.funnel.last_n_days', {
                defaultValue: 'Last {{n}}d',
                n: d,
              })}
            </button>
          ))}
        </div>
      </div>

      <div className="space-y-1.5">
        {data.stages.map((stage, idx) => {
          const pct = max <= 0 ? 0 : Math.min(100, (stage.count / max) * 100);
          const drop = num(stage.drop_pct);
          const color = QUARTILE_COLORS[dropQuartile(drop)];
          return (
            <div
              key={stage.code}
              className="flex items-center gap-2"
              aria-label={t('propdev.dashboards.funnel.stage_label', {
                defaultValue:
                  '{{label}}: {{count}} ({{drop}}% drop from previous)',
                label: stage.label,
                count: stage.count,
                drop: fmtFixed(drop, 1),
              })}
            >
              <div className="w-28 shrink-0 text-xs font-medium text-content-secondary">
                {t(`propdev.dashboards.funnel.stage_${stage.code}`, {
                  defaultValue: stage.label,
                })}
              </div>
              <div
                className="relative h-7 flex-1 overflow-hidden rounded-md bg-surface-secondary"
                role="progressbar"
                aria-valuenow={Math.round(pct)}
                aria-valuemin={0}
                aria-valuemax={100}
              >
                <span
                  className="absolute inset-y-0 left-0 rounded-md"
                  style={{
                    width: `${pct}%`,
                    backgroundColor: color,
                    opacity: 0.85,
                  }}
                />
                <span className="absolute inset-0 flex items-center px-2 text-xs font-medium text-white drop-shadow">
                  {stage.count}
                </span>
              </div>
              <div className="w-16 shrink-0 text-right text-2xs text-content-tertiary">
                {idx === 0
                  ? '—'
                  : t('propdev.dashboards.funnel.drop_pct', {
                      defaultValue: '↓ {{pct}}%',
                      pct: fmtFixed(drop, 1),
                    })}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
