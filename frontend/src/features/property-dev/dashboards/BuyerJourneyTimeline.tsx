// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Buyer Journey Timeline (task #140) — cross-entity chronological events.
 *
 * Walks Lead → Reservation → SalesContract → PaymentSchedule + Instalments
 * (clustered) → Handover → Snags → Warranty. Each node is clickable and
 * deep-links to the underlying entity.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import type { BuyerJourneyEvent, BuyerJourneyResponse } from '../api';
import { getBuyerJourney } from '../api';
import { DashboardEmpty, DashboardError, DashboardSkeleton } from './_shared';

interface BuyerJourneyTimelineProps {
  buyerId: string;
  onNodeClick?: (event: BuyerJourneyEvent) => void;
}

const STATE_COLOR: Record<BuyerJourneyEvent['state'], string> = {
  completed: '#10b981',
  in_progress: '#3b82f6',
  upcoming: '#94a3b8',
};

export function BuyerJourneyTimeline({
  buyerId,
  onNodeClick,
}: BuyerJourneyTimelineProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<BuyerJourneyResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const [reloadKey, setReloadKey] = useState(0);
  const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getBuyerJourney(buyerId)
      .then((r) => {
        if (!cancelled) setData(r);
      })
      .catch((e) => {
        if (!cancelled) setError(e?.message ?? 'Failed to load journey');
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [buyerId, reloadKey]);

  if (loading) return <DashboardSkeleton variant="timeline" rows={5} />;
  if (error)
    return (
      <DashboardError
        title={t('propdev.dashboards.journey.error', {
          defaultValue: 'Could not load buyer journey',
        })}
        message={error}
        onRetry={refetch}
      />
    );
  if (!data || data.events.length === 0)
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.journey.empty_title', {
          defaultValue: 'No events yet',
        })}
        description={t('propdev.dashboards.journey.empty_desc', {
          defaultValue:
            'Once this buyer enters the pipeline, events will appear here.',
        })}
      />
    );

  return (
    <div className="space-y-3">
      <div>
        <h3 className="text-sm font-semibold text-content-primary">
          {data.full_name || t('propdev.dashboards.journey.title', {
            defaultValue: 'Buyer journey',
          })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('propdev.dashboards.journey.event_count', {
            defaultValue: '{{count}} events',
            count: data.event_count,
          })}
        </p>
      </div>
      <ol className="relative space-y-3 border-l-2 border-divider pl-5">
        {data.events.map((ev, idx) => (
          <li key={`${ev.code}-${idx}`} className="relative">
            <span
              className="absolute -left-[27px] top-1.5 inline-block h-3 w-3 rounded-full border-2 border-surface-primary"
              style={{ backgroundColor: STATE_COLOR[ev.state] }}
              aria-hidden="true"
            />
            <button
              type="button"
              onClick={() => onNodeClick?.(ev)}
              className="flex w-full flex-col items-start gap-0.5 rounded-md px-2 py-1.5 text-left hover:bg-surface-secondary/60 focus:outline-none focus:ring-2 focus:ring-offset-1"
              aria-label={t('propdev.dashboards.journey.event_label', {
                defaultValue: '{{label}} ({{state}}) - {{ts}}',
                label: ev.label,
                state: ev.state,
                ts: ev.timestamp ?? '—',
              })}
            >
              <span className="text-xs font-medium text-content-primary">
                {t(`propdev.dashboards.journey.event_${ev.code}`, {
                  defaultValue: ev.label,
                })}
              </span>
              <span className="text-2xs text-content-tertiary">
                {ev.timestamp ?? t('propdev.dashboards.journey.undated', {
                  defaultValue: 'No date',
                })}
                {ev.entity && (
                  <span className="ml-2 rounded bg-surface-secondary px-1 py-0.5 text-2xs">
                    {ev.entity}
                  </span>
                )}
                <span
                  className="ml-2 rounded px-1 py-0.5 text-2xs"
                  style={{
                    backgroundColor: `${STATE_COLOR[ev.state]}22`,
                    color: STATE_COLOR[ev.state],
                  }}
                >
                  {t(`propdev.dashboards.journey.state_${ev.state}`, {
                    defaultValue: ev.state.replace(/_/g, ' '),
                  })}
                </span>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
