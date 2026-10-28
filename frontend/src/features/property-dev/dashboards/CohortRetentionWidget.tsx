// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cohort Retention (v3124) — reservation cohort × age heatmap.
 *
 * Rows = reservation-month cohorts. Columns = age in days (+30/+60/+90/
 * +180). Cells colour-coded green→amber→red on retention %. Sales
 * directors use this to spot churn waves and to time campaign reruns.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  getCohortRetention,
  type CohortRetentionResponse,
  type CohortRetentionRow,
} from '../api';
import { DashboardEmpty, DashboardSkeleton, num } from './_shared';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

interface CohortRetentionWidgetProps {
  since?: string;
  until?: string;
}

const OFFSETS: Array<{
  key: keyof Pick<
    CohortRetentionRow,
    | 'retention_pct_d30'
    | 'retention_pct_d60'
    | 'retention_pct_d90'
    | 'retention_pct_d180'
  >;
  label: string;
}> = [
  { key: 'retention_pct_d30', label: '+30d' },
  { key: 'retention_pct_d60', label: '+60d' },
  { key: 'retention_pct_d90', label: '+90d' },
  { key: 'retention_pct_d180', label: '+180d' },
];

function retentionColour(pct: number): string {
  if (pct >= 80) return '#10b981'; // green
  if (pct >= 60) return '#84cc16'; // lime
  if (pct >= 40) return '#f59e0b'; // amber
  if (pct >= 20) return '#f97316'; // orange
  return '#ef4444'; // red
}

export function CohortRetentionWidget({
  since,
  until,
}: CohortRetentionWidgetProps) {
  const { t } = useTranslation();
  const [showWindow] = useState({ since, until });

  const { data, isLoading, error } = useQuery<CohortRetentionResponse>({
    queryKey: [
      'propdev-analytics-cohort-retention',
      showWindow.since,
      showWindow.until,
    ],
    queryFn: () =>
      getCohortRetention({
        since: showWindow.since,
        until: showWindow.until,
        cohort_period: 'month',
      }),
    staleTime: 60_000,
  });

  if (isLoading) return <DashboardSkeleton variant="timeline" rows={6} />;
  if (error) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.cohort.error', {
          defaultValue: 'Could not load cohort retention',
        })}
        description={(error as Error)?.message ?? ''}
      />
    );
  }
  if (!data || data.cohorts.length === 0) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.cohort.empty_title', {
          defaultValue: 'No cohorts in window',
        })}
        description={t('propdev.dashboards.cohort.empty_desc', {
          defaultValue:
            'Once reservations are recorded, cohorts appear month by month.',
        })}
      />
    );
  }

  return (
    <section
      role="region"
      aria-label={t('propdev.dashboards.cohort.aria_label', {
        defaultValue: 'Cohort retention heatmap',
      })}
      className="space-y-3"
    >
      <header>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('propdev.dashboards.cohort.title', {
            defaultValue: 'Cohort retention',
          })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('propdev.dashboards.cohort.subtitle', {
            defaultValue:
              'Share of each reservation cohort still active at +N days.',
          })}
        </p>
      </header>

      <div className="overflow-x-auto">
        <table className="min-w-full border-collapse text-xs">
          <thead>
            <tr className="border-b border-divider text-content-tertiary">
              <th className="px-2 py-1.5 text-left font-medium">
                {t('propdev.dashboards.cohort.col_cohort', {
                  defaultValue: 'Cohort',
                })}
              </th>
              <th className="px-2 py-1.5 text-right font-medium">
                {t('propdev.dashboards.cohort.col_total', {
                  defaultValue: 'Total',
                })}
              </th>
              {OFFSETS.map((o) => (
                <th
                  key={o.key}
                  className="px-2 py-1.5 text-right font-medium"
                >
                  {o.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.cohorts.map((c) => (
              <tr key={c.cohort_month} className="border-b border-divider/50">
                <td className="px-2 py-1.5 font-medium text-content-primary">
                  {c.cohort_month}
                </td>
                <td className="px-2 py-1.5 text-right text-content-secondary">
                  {c.total}
                </td>
                {OFFSETS.map((o) => {
                  const pct = num(c[o.key]);
                  return (
                    <td
                      key={o.key}
                      className="px-2 py-1.5 text-right"
                      aria-label={t(
                        'propdev.dashboards.cohort.cell_label',
                        {
                          defaultValue:
                            'Cohort {{cohort}}: {{pct}}% retained at {{offset}}',
                          cohort: c.cohort_month,
                          pct: fmtFixed(pct, 1),
                          offset: o.label,
                        },
                      )}
                    >
                      <span
                        className="inline-block min-w-[3rem] rounded px-1.5 py-0.5 text-2xs font-medium text-white"
                        style={{ backgroundColor: retentionColour(pct) }}
                      >
                        {fmtPercent(pct, 0)}
                      </span>
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
