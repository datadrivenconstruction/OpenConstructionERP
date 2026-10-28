// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Lead Source Attribution (v3124) — pie + table side-by-side.
 *
 * Pie shows lead distribution by source (web_form, walk_in, broker,
 * referral, portal, other). Table on the right surfaces conversion rates,
 * attributed revenue and CPA (cost-per-acquisition) when source_cost
 * data is populated.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from 'recharts';
import {
  getLeadSourceAttribution,
  type LeadSourceAttributionResponse,
  type LeadSourceRow,
} from '../api';
import {
  DashboardEmpty,
  DashboardSkeleton,
  fmtCompactNumber,
  num,
} from './_shared';
import { fmtPercent } from '@/shared/lib/formatters';

interface LeadSourceAttributionWidgetProps {
  since?: string;
  until?: string;
}

const SOURCE_PALETTE = [
  '#3b82f6', // blue — web_form
  '#10b981', // green — walk_in
  '#f59e0b', // amber — broker
  '#8b5cf6', // violet — referral
  '#ec4899', // pink — portal
  '#94a3b8', // slate — other
];

const SOURCE_LABEL: Record<string, string> = {
  web_form: 'Web form',
  walk_in: 'Walk-in',
  broker: 'Broker',
  referral: 'Referral',
  portal: 'Portal',
  other: 'Other',
};

export function LeadSourceAttributionWidget({
  since,
  until,
}: LeadSourceAttributionWidgetProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery<LeadSourceAttributionResponse>({
    queryKey: ['propdev-analytics-lead-source', since, until],
    queryFn: () => getLeadSourceAttribution({ since, until }),
    staleTime: 60_000,
  });

  if (isLoading) return <DashboardSkeleton variant="bars" rows={5} />;
  if (error) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.lsa.error', {
          defaultValue: 'Could not load lead-source attribution',
        })}
        description={(error as Error)?.message ?? ''}
      />
    );
  }
  if (!data || data.total_leads === 0) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.lsa.empty_title', {
          defaultValue: 'No leads in window',
        })}
        description={t('propdev.dashboards.lsa.empty_desc', {
          defaultValue:
            'Once leads start flowing in, the attribution breakdown appears here.',
        })}
      />
    );
  }

  const pieData = data.rows.map((r, i) => ({
    name: SOURCE_LABEL[r.source] ?? r.source,
    value: r.leads,
    color: SOURCE_PALETTE[i % SOURCE_PALETTE.length],
  }));

  return (
    <section
      role="region"
      aria-label={t('propdev.dashboards.lsa.aria_label', {
        defaultValue: 'Lead source attribution',
      })}
      className="space-y-3"
    >
      <header>
        <h3 className="text-sm font-semibold text-content-primary">
          {t('propdev.dashboards.lsa.title', {
            defaultValue: 'Lead source attribution',
          })}
        </h3>
        <p className="text-xs text-content-tertiary">
          {t('propdev.dashboards.lsa.subtitle', {
            defaultValue:
              'Conversion + revenue + CPA per acquisition channel.',
          })}
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-[200px_1fr]">
        <div className="h-[200px]">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={pieData}
                dataKey="value"
                nameKey="name"
                innerRadius={36}
                outerRadius={72}
                paddingAngle={2}
                isAnimationActive={false}
              >
                {pieData.map((d, i) => (
                  <Cell key={i} fill={d.color} />
                ))}
              </Pie>
              <Tooltip
                formatter={(value, name) => [
                  `${Number(value ?? 0)} leads`,
                  String(name ?? ''),
                ]}
              />
            </PieChart>
          </ResponsiveContainer>
        </div>

        <div className="overflow-x-auto">
          <table className="min-w-full border-collapse text-xs">
            <thead>
              <tr className="border-b border-divider text-content-tertiary">
                <th className="px-2 py-1.5 text-left font-medium">
                  {t('propdev.dashboards.lsa.col_source', {
                    defaultValue: 'Source',
                  })}
                </th>
                <th className="px-2 py-1.5 text-right font-medium">
                  {t('propdev.dashboards.lsa.col_leads', {
                    defaultValue: 'Leads',
                  })}
                </th>
                <th className="px-2 py-1.5 text-right font-medium">
                  {t('propdev.dashboards.lsa.col_conv_res', {
                    defaultValue: '→ Res %',
                  })}
                </th>
                <th className="px-2 py-1.5 text-right font-medium">
                  {t('propdev.dashboards.lsa.col_conv_sale', {
                    defaultValue: '→ Sale %',
                  })}
                </th>
                <th className="px-2 py-1.5 text-right font-medium">
                  {t('propdev.dashboards.lsa.col_revenue', {
                    defaultValue: 'Revenue',
                  })}
                </th>
                <th className="px-2 py-1.5 text-right font-medium">
                  {t('propdev.dashboards.lsa.col_cpa', {
                    defaultValue: 'CPA',
                  })}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.rows.map((r: LeadSourceRow, i: number) => (
                <tr
                  key={r.source}
                  className="border-b border-divider/50"
                >
                  <td className="px-2 py-1.5 font-medium text-content-primary">
                    <span className="mr-1.5 inline-block h-2 w-2 rounded-full" style={{ backgroundColor: SOURCE_PALETTE[i % SOURCE_PALETTE.length] }} aria-hidden="true" />
                    {SOURCE_LABEL[r.source] ?? r.source}
                  </td>
                  <td className="px-2 py-1.5 text-right text-content-secondary">
                    {r.leads}
                  </td>
                  <td className="px-2 py-1.5 text-right text-content-secondary">
                    {fmtPercent(num(r.conversion_to_reservation_pct))}
                  </td>
                  <td className="px-2 py-1.5 text-right text-content-secondary">
                    {fmtPercent(num(r.conversion_to_sale_pct))}
                  </td>
                  <td className="px-2 py-1.5 text-right">
                    {r.revenue.length === 0 ? (
                      <span className="text-content-tertiary">—</span>
                    ) : (
                      <div className="flex flex-wrap justify-end gap-1">
                        {r.revenue.map((c) => (
                          <span
                            key={c.currency}
                            className="rounded bg-surface-secondary px-1.5 py-0.5 text-2xs"
                          >
                            <span className="font-medium">{c.currency}</span>{' '}
                            {fmtCompactNumber(num(c.amount))}
                          </span>
                        ))}
                      </div>
                    )}
                  </td>
                  <td className="px-2 py-1.5 text-right text-content-secondary">
                    {r.cpa == null ? (
                      <span className="text-content-tertiary">—</span>
                    ) : (
                      <span title={r.cpa_currency || ''}>
                        {r.cpa_currency ? `${r.cpa_currency} ` : ''}
                        {fmtCompactNumber(num(r.cpa))}
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
