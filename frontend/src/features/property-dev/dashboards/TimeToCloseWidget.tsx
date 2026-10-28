// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Time to Close (v3124) — days Lead → Reservation → Sale → Handover.
 *
 * Horizontal bar per stage shows mean days (the bar) with p50 / p90
 * whiskers overlaid. Sales directors use this to pinpoint which stage
 * is dragging the funnel and where to invest sales-enablement effort.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  getTimeToClose,
  type StageDistribution,
  type TimeToCloseResponse,
} from '../api';
import { DashboardEmpty, DashboardSkeleton, num } from './_shared';
import { fmtFixed } from '@/shared/lib/formatters';

interface TimeToCloseWidgetProps {
  since?: string;
  until?: string;
}

const STAGE_LABELS: Record<string, string> = {
  lead_to_reservation: 'Lead → Reservation',
  reservation_to_sale: 'Reservation → Sale',
  sale_to_handover: 'Sale → Handover',
  lead_to_handover: 'Lead → Handover (end-to-end)',
};

const STAGE_COLOR: Record<string, string> = {
  lead_to_reservation: '#3b82f6',
  reservation_to_sale: '#8b5cf6',
  sale_to_handover: '#10b981',
  lead_to_handover: '#f59e0b',
};

export function TimeToCloseWidget({ since, until }: TimeToCloseWidgetProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery<TimeToCloseResponse>({
    queryKey: ['propdev-analytics-time-to-close', since, until],
    queryFn: () => getTimeToClose({ since, until }),
    staleTime: 60_000,
  });

  if (isLoading) return <DashboardSkeleton variant="bars" rows={4} />;
  if (error) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.ttc.error', {
          defaultValue: 'Could not load time-to-close',
        })}
        description={(error as Error)?.message ?? ''}
      />
    );
  }
  if (!data || data.closed_sales === 0) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.ttc.empty_title', {
          defaultValue: 'No closed sales yet',
        })}
        description={t('propdev.dashboards.ttc.empty_desc', {
          defaultValue:
            'Time-to-close needs at least one SPA in (signed / countersigned / registered).',
        })}
      />
    );
  }

  // Scale: max p90 across stages, rounded up so the longest whisker
  // doesn't clip the right edge.
  const maxP90 = Math.max(
    1,
    ...data.stages.map((s) => num(s.p90_days)),
  );

  return (
    <section
      role="region"
      aria-label={t('propdev.dashboards.ttc.aria_label', {
        defaultValue: 'Time-to-close per stage',
      })}
      className="space-y-3"
    >
      <header className="flex items-center justify-between">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.ttc.title', {
              defaultValue: 'Time to close',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.ttc.subtitle', {
              defaultValue:
                'Mean (bar) + p50 (white tick) + p90 (whisker) days per stage.',
            })}
          </p>
        </div>
        <span className="text-2xs text-content-tertiary">
          {t('propdev.dashboards.ttc.sample_size', {
            defaultValue: '{{count}} closed sales',
            count: data.closed_sales,
          })}
        </span>
      </header>

      <div className="space-y-2.5">
        {data.stages.map((s) => (
          <StageBar key={s.stage} stage={s} max={maxP90} />
        ))}
      </div>
    </section>
  );
}

function StageBar({ stage, max }: { stage: StageDistribution; max: number }) {
  const { t } = useTranslation();
  const mean = num(stage.mean_days);
  const p50 = num(stage.p50_days);
  const p90 = num(stage.p90_days);

  const meanPct = max <= 0 ? 0 : Math.min(100, (mean / max) * 100);
  const p50Pct = max <= 0 ? 0 : Math.min(100, (p50 / max) * 100);
  const p90Pct = max <= 0 ? 0 : Math.min(100, (p90 / max) * 100);
  const color = STAGE_COLOR[stage.stage] ?? '#64748b';
  const label = STAGE_LABELS[stage.stage] ?? stage.stage;

  return (
    <div
      className="rounded-lg border border-divider/50 p-2"
      aria-label={t('propdev.dashboards.ttc.bar_label', {
        defaultValue:
          '{{label}}: mean {{mean}}d, p50 {{p50}}d, p90 {{p90}}d ({{n}} samples)',
        label,
        mean: fmtFixed(mean, 1),
        p50: fmtFixed(p50, 1),
        p90: fmtFixed(p90, 1),
        n: stage.sample_size,
      })}
    >
      <div className="mb-1 flex items-center justify-between text-2xs">
        <span className="font-medium text-content-primary">{label}</span>
        <span className="text-content-tertiary">
          {t('propdev.dashboards.ttc.bar_stats', {
            defaultValue: 'mean {{m}}d • p50 {{p50}}d • p90 {{p90}}d • n={{n}}',
            m: fmtFixed(mean, 1),
            p50: fmtFixed(p50, 1),
            p90: fmtFixed(p90, 1),
            n: stage.sample_size,
          })}
        </span>
      </div>
      <div
        className="relative h-5 overflow-hidden rounded-md bg-surface-secondary"
        role="progressbar"
        aria-valuenow={Math.round(mean)}
        aria-valuemin={0}
        aria-valuemax={Math.max(1, Math.round(max))}
      >
        {/* Mean bar */}
        <span
          className="absolute inset-y-0 left-0"
          style={{ width: `${meanPct}%`, backgroundColor: color, opacity: 0.85 }}
        />
        {/* p50 white tick */}
        <span
          className="absolute inset-y-0 w-px bg-white"
          style={{ left: `calc(${p50Pct}% - 0.5px)` }}
        />
        {/* p90 whisker (dashed vertical line beyond mean) */}
        <span
          className="absolute inset-y-0 w-px bg-content-tertiary"
          style={{ left: `calc(${p90Pct}% - 0.5px)`, opacity: 0.7 }}
        />
      </div>
    </div>
  );
}
