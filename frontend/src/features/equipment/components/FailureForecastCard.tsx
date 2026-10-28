// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import clsx from 'clsx';
import { CalendarClock, Gauge, AlertTriangle } from 'lucide-react';
import { Card, SkeletonTable } from '@/shared/ui';
import { DateDisplay } from '@/shared/ui/DateDisplay';
import { getErrorMessage } from '@/shared/lib/api';
import { getFailureForecast } from '../api';
import { fmtFixed } from '@/shared/lib/formatters';

/**
 * Forecast card: predicted next-service date, confidence and recent daily use.
 *
 * Used inside the Health & Analytics tab. Plain-English wording (no MTBF).
 */
export function FailureForecastCard({ equipmentId }: { equipmentId: string }) {
  const { t } = useTranslation();

  const fcQ = useQuery({
    queryKey: ['equipment', 'forecast', equipmentId],
    queryFn: () => getFailureForecast(equipmentId),
    enabled: !!equipmentId,
  });

  if (fcQ.isLoading) {
    return <SkeletonTable rows={2} columns={3} />;
  }
  if (fcQ.isError || !fcQ.data) {
    return (
      <Card padding="sm">
        <p className="flex items-center gap-1.5 text-xs text-content-secondary">
          <AlertTriangle size={13} className="text-amber-500" />
          {fcQ.error
            ? getErrorMessage(fcQ.error)
            : t('equipment.forecast.unavailable', {
                defaultValue: 'Forecast unavailable',
              })}
        </p>
      </Card>
    );
  }

  const fc = fcQ.data;
  const confidencePct = Math.round(fc.failure_confidence * 100);
  const confidenceBand =
    confidencePct >= 66 ? 'high' : confidencePct >= 33 ? 'medium' : 'low';
  const confidenceColor =
    confidenceBand === 'high'
      ? 'bg-emerald-500'
      : confidenceBand === 'medium'
        ? 'bg-amber-500'
        : 'bg-rose-500';
  const confidenceLabel =
    confidenceBand === 'high'
      ? t('equipment.forecast.confidence_high', { defaultValue: 'High' })
      : confidenceBand === 'medium'
        ? t('equipment.forecast.confidence_medium', { defaultValue: 'Medium' })
        : t('equipment.forecast.confidence_low', { defaultValue: 'Low' });

  const basisLabel =
    fc.basis === 'projected_usage_to_service'
      ? t('equipment.forecast.basis_usage', {
          defaultValue: 'Projected from recent running hours to the next service.',
        })
      : t('equipment.forecast.basis_health', {
          defaultValue: 'Estimated from the current health band (no service schedule set).',
        });

  return (
    <Card padding="md">
      <div className="flex items-center gap-1.5">
        <CalendarClock size={15} className="text-oe-blue" />
        <h4 className="text-sm font-semibold text-content-primary">
          {t('equipment.forecast.title', {
            defaultValue: 'Predicted next service',
          })}
        </h4>
      </div>

      <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
        <div>
          <p className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('equipment.forecast.predicted_date', {
              defaultValue: 'Predicted date',
            })}
          </p>
          <p className="mt-1 text-base font-semibold text-content-primary">
            {fc.predicted_failure_date ? (
              <DateDisplay value={fc.predicted_failure_date} format="date" />
            ) : (
              '-'
            )}
          </p>
          {fc.days_to_failure != null && (
            <p className="text-2xs text-content-tertiary">
              {t('equipment.forecast.days_out', {
                defaultValue: 'in ~{{count}} day(s)',
                count: fc.days_to_failure,
              })}
            </p>
          )}
        </div>

        <div>
          <p className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('equipment.forecast.confidence', { defaultValue: 'Confidence' })}
          </p>
          <div className="mt-1 flex items-center gap-2">
            <span className="text-base font-semibold tabular-nums text-content-primary">
              {confidencePct}%
            </span>
            <span className="text-2xs font-medium text-content-secondary">
              {confidenceLabel}
            </span>
          </div>
          <div className="mt-1.5 h-1.5 w-full overflow-hidden rounded-full bg-border-light">
            <div
              className={clsx('h-full rounded-full', confidenceColor)}
              style={{ width: `${confidencePct}%` }}
            />
          </div>
        </div>

        <div>
          <p className="text-2xs uppercase tracking-wide text-content-tertiary">
            {t('equipment.forecast.daily_usage', {
              defaultValue: 'Recent daily use',
            })}
          </p>
          <p className="mt-1 flex items-center gap-1 text-base font-semibold tabular-nums text-content-primary">
            <Gauge size={13} className="text-content-tertiary" />
            {fmtFixed(fc.daily_usage, 1)}
            <span className="text-2xs font-normal text-content-tertiary">
              {t('equipment.forecast.hours_per_day', {
                defaultValue: 'h/day',
              })}
            </span>
          </p>
        </div>
      </div>

      <p className="mt-3 text-2xs leading-relaxed text-content-tertiary">
        {basisLabel}
      </p>
    </Card>
  );
}
