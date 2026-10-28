// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import {
  Activity,
  AlertTriangle,
  HeartPulse,
  TrendingUp,
  TrendingDown,
  Minus,
} from 'lucide-react';
import { Card, EmptyState, SkeletonTable } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import {
  getHealthAnalytics,
  type HealthBand,
  type MaintenanceTrend,
} from '../api';
import { FailureForecastCard } from './FailureForecastCard';
import { fmtFixed } from '@/shared/lib/formatters';

/**
 * Health & Analytics tab for the equipment detail drawer.
 *
 * Plain-English predictive view: a 0-100 Health Score gauge (red/amber/green),
 * the maintenance trend, an anomaly list and the failure forecast. Everything
 * is computed server-side on the fly from the unit's telemetry history.
 */

const BAND_RING: Record<HealthBand, string> = {
  green: 'text-emerald-500',
  amber: 'text-amber-500',
  red: 'text-rose-500',
};

const BAND_TEXT: Record<HealthBand, string> = {
  green: 'text-emerald-600 dark:text-emerald-400',
  amber: 'text-amber-600 dark:text-amber-400',
  red: 'text-rose-600 dark:text-rose-400',
};

const TREND_ICON: Record<MaintenanceTrend, React.ElementType> = {
  improving: TrendingUp,
  stable: Minus,
  deteriorating: TrendingDown,
};

const TREND_COLOR: Record<MaintenanceTrend, string> = {
  improving: 'text-emerald-600 dark:text-emerald-400',
  stable: 'text-content-secondary',
  deteriorating: 'text-rose-600 dark:text-rose-400',
};

function RiskGauge({ score, band }: { score: number; band: HealthBand }) {
  const { t } = useTranslation();
  const clamped = Math.max(0, Math.min(100, score));
  const radius = 52;
  const circumference = 2 * Math.PI * radius;
  const dash = (clamped / 100) * circumference;
  return (
    <div className="relative flex h-36 w-36 shrink-0 items-center justify-center">
      <svg viewBox="0 0 120 120" className="h-36 w-36 -rotate-90">
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          strokeWidth="10"
          className="stroke-border-light"
        />
        <circle
          cx="60"
          cy="60"
          r={radius}
          fill="none"
          strokeWidth="10"
          strokeLinecap="round"
          strokeDasharray={`${dash} ${circumference}`}
          className={clsx('transition-all duration-700', BAND_RING[band])}
          stroke="currentColor"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span
          className={clsx('text-3xl font-bold tabular-nums', BAND_TEXT[band])}
        >
          {fmtFixed(clamped, 0)}
        </span>
        <span className="text-2xs uppercase tracking-wide text-content-tertiary">
          {t('equipment.health.score_label', { defaultValue: 'Health Score' })}
        </span>
      </div>
    </div>
  );
}

export function EquipmentHealthDashboard({
  equipmentId,
}: {
  equipmentId: string;
}) {
  const { t } = useTranslation();

  const healthQ = useQuery({
    queryKey: ['equipment', 'health', equipmentId],
    queryFn: () => getHealthAnalytics(equipmentId),
    enabled: !!equipmentId,
  });

  if (healthQ.isLoading) {
    return <SkeletonTable rows={5} columns={3} />;
  }
  if (healthQ.isError || !healthQ.data) {
    return (
      <EmptyState
        icon={<AlertTriangle size={20} />}
        title={t('equipment.health.load_error', {
          defaultValue: 'Could not load health analytics',
        })}
        description={
          healthQ.error ? getErrorMessage(healthQ.error) : undefined
        }
        action={{
          label: t('common.retry', { defaultValue: 'Retry' }),
          onClick: () => {
            void healthQ.refetch();
          },
        }}
      />
    );
  }

  const h = healthQ.data;
  const TrendIcon = TREND_ICON[h.maintenance_trend];

  const bandLabel: Record<HealthBand, string> = {
    green: t('equipment.health.band_good', { defaultValue: 'Good' }),
    amber: t('equipment.health.band_watch', { defaultValue: 'Needs watching' }),
    red: t('equipment.health.band_attention', {
      defaultValue: 'Needs attention',
    }),
  };
  const trendLabel: Record<MaintenanceTrend, string> = {
    improving: t('equipment.health.trend_improving', {
      defaultValue: 'Improving',
    }),
    stable: t('equipment.health.trend_stable', { defaultValue: 'Stable' }),
    deteriorating: t('equipment.health.trend_deteriorating', {
      defaultValue: 'Deteriorating',
    }),
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-1.5">
        <HeartPulse size={15} className="text-oe-blue" />
        <h3 className="text-sm font-semibold text-content-primary">
          {t('equipment.health.section_title', {
            defaultValue: 'Health & predictive analytics',
          })}
        </h3>
      </div>
      <p className="text-xs leading-relaxed text-content-secondary">
        {t('equipment.health.section_desc', {
          defaultValue:
            'A single Health Score (0-100) summarising this asset from its telemetry history, open work orders and inspection status. Higher is healthier. We also flag unusual readings and forecast when the next service is likely due.',
        })}
      </p>

      <Card padding="md">
        <div className="flex flex-col items-center gap-5 sm:flex-row sm:items-center">
          <RiskGauge score={h.health_score} band={h.band} />
          <div className="min-w-0 flex-1 space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              <span
                className={clsx(
                  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold',
                  h.band === 'green' &&
                    'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300',
                  h.band === 'amber' &&
                    'bg-amber-50 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300',
                  h.band === 'red' &&
                    'bg-rose-50 text-rose-700 dark:bg-rose-950/40 dark:text-rose-300',
                )}
              >
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {bandLabel[h.band]}
              </span>
              <span
                className={clsx(
                  'inline-flex items-center gap-1 text-xs font-medium',
                  TREND_COLOR[h.maintenance_trend],
                )}
              >
                <TrendIcon size={13} />
                {trendLabel[h.maintenance_trend]}
              </span>
            </div>
            <ul className="space-y-1">
              {h.reasons.map((r, i) => (
                <li
                  key={i}
                  className="flex items-start gap-1.5 text-xs text-content-secondary"
                >
                  <span className="mt-1.5 h-1 w-1 shrink-0 rounded-full bg-content-tertiary" />
                  {r}
                </li>
              ))}
            </ul>
            <p className="text-2xs text-content-tertiary">
              {t('equipment.health.sample_count', {
                defaultValue: 'Based on {{count}} telemetry reading(s)',
                count: h.sample_count,
              })}
            </p>
          </div>
        </div>
      </Card>

      <FailureForecastCard equipmentId={equipmentId} />

      <div>
        <div className="mb-2 flex items-center gap-1.5">
          <Activity size={14} className="text-content-tertiary" />
          <h4 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary">
            {t('equipment.health.anomalies_title', {
              defaultValue: 'Unusual readings',
            })}
          </h4>
        </div>
        {h.anomalies.length === 0 ? (
          <p className="rounded-lg border border-border-light bg-surface-secondary/40 px-3 py-2.5 text-xs text-content-secondary">
            {t('equipment.health.no_anomalies', {
              defaultValue: 'No unusual readings detected in recent telemetry.',
            })}
          </p>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-border-light">
            <table className="w-full text-xs">
              <thead className="bg-surface-secondary text-content-tertiary uppercase tracking-wide">
                <tr>
                  <th className="px-3 py-2 text-left">
                    {t('equipment.recorded_at', { defaultValue: 'Recorded at' })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('equipment.health.anomaly_signal', {
                      defaultValue: 'Signal',
                    })}
                  </th>
                  <th className="px-3 py-2 text-left">
                    {t('equipment.health.anomaly_reason', {
                      defaultValue: 'Why it stood out',
                    })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {h.anomalies.map((a, i) => (
                  <tr key={i} className="border-t border-border-light">
                    <td className="px-3 py-2 text-content-secondary whitespace-nowrap">
                      <DateDisplay value={a.recorded_at} />
                    </td>
                    <td className="px-3 py-2">
                      <span className="inline-flex items-center gap-1.5 font-medium text-rose-600 dark:text-rose-400">
                        <AlertTriangle size={11} />
                        {a.metric}
                      </span>
                    </td>
                    <td className="px-3 py-2 text-content-secondary">
                      {a.reason}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
