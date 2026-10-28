// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SafetyTrendsChart — rolling LTIFR/TRIR time series (item 13).
 *
 * Renders a Recharts ComposedChart with dual Y-axes:
 *   - Left axis  : incident count (bars)
 *   - Right axis : LTIFR / TRIR frequency rates (two lines)
 *
 * Data comes from GET /v1/safety/trends/extended. Periods with no man-hours
 * carry `null` rates so the rate lines show a gap rather than a misleading 0.
 * A monthly/weekly toggle re-queries; loading/error/empty states are handled.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Legend,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Card, EmptyState, RecoveryCard, SkeletonTable } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { TrendingDown, TrendingUp, Minus, HelpCircle } from 'lucide-react';

/* ── Types (mirror SafetyTrendsExtendedResponse) ───────────────────────── */

export interface SafetyTrendEntryExtended {
  period: string;
  incident_count: number;
  observation_count: number;
  days_lost: number;
  ltifr: number | null;
  trir: number | null;
  man_hours_total: number;
  recordable_incidents: number;
  lost_time_incidents: number;
}

export interface SafetyTrendsExtendedResponse {
  period_type: string;
  entries: SafetyTrendEntryExtended[];
  rolling_12_month_ltifr: number | null;
  rolling_12_month_trir: number | null;
  current_period_ltifr: number | null;
  current_period_trir: number | null;
  trend_direction: 'improving' | 'stable' | 'declining' | 'unknown';
}

type TrendPeriod = 'monthly' | 'weekly';

interface SafetyTrendsChartProps {
  projectId: string;
  period?: TrendPeriod;
}

/* ── Trend-direction chip ──────────────────────────────────────────────── */

function TrendDirectionChip({
  direction,
}: {
  direction: SafetyTrendsExtendedResponse['trend_direction'];
}) {
  const { t } = useTranslation();
  // A falling LTIFR is good: 'improving' is green, 'declining' is red.
  const cfg: Record<
    SafetyTrendsExtendedResponse['trend_direction'],
    { icon: React.ElementType; cls: string; label: string }
  > = {
    improving: {
      icon: TrendingDown,
      cls: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
      label: t('safety.trend_improving', { defaultValue: 'Improving' }),
    },
    declining: {
      icon: TrendingUp,
      cls: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
      label: t('safety.trend_declining', { defaultValue: 'Declining' }),
    },
    stable: {
      icon: Minus,
      cls: 'bg-surface-secondary text-content-secondary',
      label: t('safety.trend_stable', { defaultValue: 'Stable' }),
    },
    unknown: {
      icon: HelpCircle,
      cls: 'bg-surface-secondary text-content-tertiary',
      label: t('safety.trend_unknown', { defaultValue: 'Not enough data' }),
    },
  };
  const c = cfg[direction];
  const Icon = c.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${c.cls}`}
      data-testid="safety-trend-direction"
    >
      <Icon size={13} />
      {c.label}
    </span>
  );
}

/* ── Main chart ────────────────────────────────────────────────────────── */

export function SafetyTrendsChart({ projectId, period: initialPeriod = 'monthly' }: SafetyTrendsChartProps) {
  const { t } = useTranslation();
  const [period, setPeriod] = useState<TrendPeriod>(initialPeriod);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['safety-trends-extended', projectId, period],
    queryFn: () =>
      apiGet<SafetyTrendsExtendedResponse>(
        `/v1/safety/trends/extended/?project_id=${projectId}&period=${period}`,
      ),
    enabled: !!projectId,
  });

  if (isLoading) return <SkeletonTable rows={5} columns={4} />;
  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;

  const entries = data?.entries ?? [];
  const hasData = entries.length > 0;

  return (
    <Card padding="none">
      {/* Header: rolling KPIs + trend chip + period toggle */}
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border-light p-4">
        <div className="flex flex-wrap items-center gap-4">
          <div>
            <div className="text-2xs uppercase text-content-tertiary">
              {t('safety.rolling_ltifr', { defaultValue: 'Rolling LTIFR' })}
            </div>
            <div className="text-lg font-bold tabular-nums text-content-primary" data-testid="rolling-ltifr">
              {data?.rolling_12_month_ltifr ?? '—'}
            </div>
          </div>
          <div>
            <div className="text-2xs uppercase text-content-tertiary">
              {t('safety.rolling_trir', { defaultValue: 'Rolling TRIR' })}
            </div>
            <div className="text-lg font-bold tabular-nums text-content-primary" data-testid="rolling-trir">
              {data?.rolling_12_month_trir ?? '—'}
            </div>
          </div>
          {data && <TrendDirectionChip direction={data.trend_direction} />}
        </div>

        <div
          className="inline-flex rounded-lg border border-border-light p-0.5"
          role="group"
          aria-label={t('safety.trend_period', { defaultValue: 'Trend period' })}
        >
          {(['monthly', 'weekly'] as const).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              aria-pressed={period === p}
              className={`rounded-md px-3 py-1 text-xs font-medium transition-colors ${
                period === p
                  ? 'bg-oe-blue text-white'
                  : 'text-content-tertiary hover:text-content-primary'
              }`}
            >
              {p === 'monthly'
                ? t('safety.period_monthly', { defaultValue: 'Monthly' })
                : t('safety.period_weekly', { defaultValue: 'Weekly' })}
            </button>
          ))}
        </div>
      </div>

      {/* Chart body */}
      <div className="p-4">
        {!hasData ? (
          <EmptyState
            title={t('safety.no_trend_data', { defaultValue: 'No data available' })}
            description={t('safety.no_trend_data_desc', {
              defaultValue:
                'Report incidents with man-hours recorded to chart LTIFR and TRIR over time.',
            })}
          />
        ) : (
          <div style={{ width: '100%', height: 360 }} data-testid="safety-trends-chart">
            <ResponsiveContainer width="100%" height="100%">
              <ComposedChart data={entries} margin={{ top: 8, right: 16, bottom: 8, left: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-light, #e5e7eb)" />
                <XAxis dataKey="period" tick={{ fontSize: 11 }} />
                <YAxis
                  yAxisId="count"
                  orientation="left"
                  tick={{ fontSize: 11 }}
                  allowDecimals={false}
                  label={{
                    value: t('safety.incidents', { defaultValue: 'Incidents' }),
                    angle: -90,
                    position: 'insideLeft',
                    style: { fontSize: 11 },
                  }}
                />
                <YAxis
                  yAxisId="rate"
                  orientation="right"
                  tick={{ fontSize: 11 }}
                  label={{
                    value: t('safety.rate_label', { defaultValue: 'Rate' }),
                    angle: 90,
                    position: 'insideRight',
                    style: { fontSize: 11 },
                  }}
                />
                <Tooltip
                  contentStyle={{ fontSize: 12 }}
                  labelStyle={{ fontWeight: 600 }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                <Bar
                  yAxisId="count"
                  dataKey="incident_count"
                  name={t('safety.incidents', { defaultValue: 'Incidents' })}
                  fill="#3b82f6"
                  radius={[3, 3, 0, 0]}
                  maxBarSize={36}
                />
                <Line
                  yAxisId="rate"
                  type="monotone"
                  dataKey="ltifr"
                  name="LTIFR"
                  stroke="#ef4444"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
                <Line
                  yAxisId="rate"
                  type="monotone"
                  dataKey="trir"
                  name="TRIR"
                  stroke="#f59e0b"
                  strokeWidth={2}
                  dot={{ r: 3 }}
                  connectNulls={false}
                />
              </ComposedChart>
            </ResponsiveContainer>
          </div>
        )}
      </div>
    </Card>
  );
}
