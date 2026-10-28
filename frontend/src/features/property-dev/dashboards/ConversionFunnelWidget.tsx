// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Conversion Funnel (v3124) — vertical SVG funnel.
 *
 * 5 steps: Leads → Qualified → Reservation → Sale → Handover. Width of
 * each trapezoid scales with the absolute count. Drop-off % is rendered
 * on the right edge between steps. Sales directors use this to validate
 * which stage is leaking and to drill down (e.g. low qualified → re-train
 * inside sales; low res→sale → re-price).
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  getConversionFunnel,
  type ConversionFunnelResponse,
  type ConversionFunnelStep,
} from '../api';
import { DashboardEmpty, DashboardSkeleton, num } from './_shared';
import { fmtPercent, fmtFixed } from '@/shared/lib/formatters';

interface ConversionFunnelWidgetProps {
  since?: string;
  until?: string;
  devId?: string;
  plotType?: string;
}

const STEP_COLOR: Record<string, string> = {
  leads: '#3b82f6',
  qualified: '#8b5cf6',
  reservation: '#f59e0b',
  sale: '#10b981',
  handover: '#0891b2',
};

const STEP_LABEL: Record<string, string> = {
  leads: 'Leads',
  qualified: 'Qualified',
  reservation: 'Reservation',
  sale: 'Sale',
  handover: 'Handover',
};

export function ConversionFunnelWidget({
  since,
  until,
  devId,
  plotType,
}: ConversionFunnelWidgetProps) {
  const { t } = useTranslation();
  const { data, isLoading, error } = useQuery<ConversionFunnelResponse>({
    queryKey: [
      'propdev-analytics-conversion-funnel',
      since,
      until,
      devId,
      plotType,
    ],
    queryFn: () =>
      getConversionFunnel({
        since,
        until,
        dev_id: devId ?? null,
        plot_type: plotType ?? null,
      }),
    staleTime: 60_000,
  });

  if (isLoading) return <DashboardSkeleton variant="bars" rows={5} />;
  if (error) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.cf.error', {
          defaultValue: 'Could not load conversion funnel',
        })}
        description={(error as Error)?.message ?? ''}
      />
    );
  }
  if (!data || data.steps.length === 0 || data.steps[0]?.count === 0) {
    return (
      <DashboardEmpty
        title={t('propdev.dashboards.cf.empty_title', {
          defaultValue: 'No leads in window',
        })}
        description={t('propdev.dashboards.cf.empty_desc', {
          defaultValue:
            'The funnel widens at the top - capture leads to see it fill in.',
        })}
      />
    );
  }

  const top = Math.max(1, data.steps[0]?.count ?? 1);
  const FUNNEL_W = 360;
  const STEP_H = 50;
  const SVG_W = FUNNEL_W + 200; // room for labels on the right

  return (
    <section
      role="region"
      aria-label={t('propdev.dashboards.cf.aria_label', {
        defaultValue: 'Conversion funnel',
      })}
      className="space-y-3"
    >
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-content-primary">
            {t('propdev.dashboards.cf.title', {
              defaultValue: 'Conversion funnel',
            })}
          </h3>
          <p className="text-xs text-content-tertiary">
            {t('propdev.dashboards.cf.subtitle', {
              defaultValue:
                'Leads → Qualified → Reservation → Sale → Handover. {{conv}}% end-to-end.',
              conv: fmtFixed(num(data.overall_conversion_pct), 1),
            })}
          </p>
        </div>
      </header>

      <div className="overflow-x-auto">
        <svg
          width={SVG_W}
          height={data.steps.length * STEP_H + 20}
          viewBox={`0 0 ${SVG_W} ${data.steps.length * STEP_H + 20}`}
          aria-hidden="true"
        >
          {data.steps.map((s, i) => {
            const next = data.steps[i + 1];
            const wThis = Math.max(20, (s.count / top) * FUNNEL_W);
            const wNext = next ? Math.max(20, (next.count / top) * FUNNEL_W) : wThis;
            const xLeftThis = (SVG_W - 200 - wThis) / 2;
            const xRightThis = xLeftThis + wThis;
            const xLeftNext = (SVG_W - 200 - wNext) / 2;
            const xRightNext = xLeftNext + wNext;
            const yTop = i * STEP_H + 10;
            const yBot = yTop + STEP_H;
            const color = STEP_COLOR[s.code] ?? '#64748b';
            const label = STEP_LABEL[s.code] ?? s.label;
            return (
              <g key={s.code}>
                <polygon
                  points={`${xLeftThis},${yTop} ${xRightThis},${yTop} ${xRightNext},${yBot} ${xLeftNext},${yBot}`}
                  fill={color}
                  opacity={0.85}
                  stroke={color}
                />
                <text
                  x={(xLeftThis + xRightThis) / 2}
                  y={yTop + STEP_H / 2 + 5}
                  textAnchor="middle"
                  fontSize="13"
                  fontWeight="600"
                  fill="white"
                >
                  {s.count}
                </text>
                <text
                  x={SVG_W - 190}
                  y={yTop + STEP_H / 2 - 2}
                  fontSize="12"
                  fontWeight="500"
                  fill="currentColor"
                  className="fill-current text-content-primary"
                >
                  {label}
                </text>
                <text
                  x={SVG_W - 190}
                  y={yTop + STEP_H / 2 + 14}
                  fontSize="10"
                  className="fill-current text-content-tertiary"
                >
                  {fmtPercent(num(s.conversion_from_top_pct))} of top
                  {i > 0 && (
                    <tspan> · ↓{fmtPercent(num(s.drop_pct))}</tspan>
                  )}
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <ul className="sr-only">
        {data.steps.map((s: ConversionFunnelStep, i: number) => (
          <li key={s.code}>
            {t('propdev.dashboards.cf.sr_step', {
              defaultValue:
                '{{label}}: {{count}} ({{conv}}% of top{{drop}})',
              label: STEP_LABEL[s.code] ?? s.label,
              count: s.count,
              conv: fmtFixed(num(s.conversion_from_top_pct), 1),
              drop: i === 0 ? '' : `, ${fmtPercent(num(s.drop_pct))} drop`,
            })}
          </li>
        ))}
      </ul>
    </section>
  );
}
