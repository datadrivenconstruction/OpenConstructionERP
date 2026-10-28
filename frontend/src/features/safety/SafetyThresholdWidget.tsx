// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SafetyThresholdWidget — compact LTIFR/TRIR status card (item 13).
 *
 * Shows the project's current LTIFR and TRIR against safe-baselines with a
 * green/yellow/red badge. Expands to show the delta, percent-above-baseline,
 * and a 3-period LTIFR sparkline pulled from the extended-trends endpoint.
 *
 * Data: GET /v1/safety/threshold-alert and (for the sparkline, lazily on
 * expand) GET /v1/safety/trends/extended.
 */

import { useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { Line, LineChart, ResponsiveContainer } from 'recharts';
import { Card, RecoveryCard, Skeleton } from '@/shared/ui';
import { apiGet } from '@/shared/lib/api';
import { ChevronDown, ChevronUp, ShieldCheck, ShieldAlert, ShieldX, Shield } from 'lucide-react';
import type { SafetyTrendsExtendedResponse } from './SafetyTrendsChart';

/* ── Types (mirror SafetyThresholdAlertResponse) ───────────────────────── */

type RateStatus = 'green' | 'yellow' | 'red' | 'unknown';

export interface SafetyThresholdAlertResponse {
  current_ltifr: number | null;
  current_trir: number | null;
  baseline_ltifr: number;
  baseline_trir: number;
  ltifr_delta: number | null;
  trir_delta: number | null;
  ltifr_status: RateStatus;
  trir_status: RateStatus;
  message: string;
}

interface SafetyThresholdWidgetProps {
  projectId: string;
}

/* ── Status presentation ───────────────────────────────────────────────── */

const STATUS_META: Record<
  RateStatus,
  { icon: React.ElementType; badge: string; dot: string }
> = {
  green: {
    icon: ShieldCheck,
    badge: 'bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300',
    dot: 'bg-green-500',
  },
  yellow: {
    icon: ShieldAlert,
    badge: 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900/40 dark:text-yellow-300',
    dot: 'bg-yellow-500',
  },
  red: {
    icon: ShieldX,
    badge: 'bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300',
    dot: 'bg-red-500',
  },
  unknown: {
    icon: Shield,
    badge: 'bg-surface-secondary text-content-tertiary',
    dot: 'bg-surface-tertiary',
  },
};

function statusLabel(status: RateStatus, t: (k: string, o?: Record<string, unknown>) => string): string {
  switch (status) {
    case 'green':
      return t('safety.status_safe', { defaultValue: 'Safe' });
    case 'yellow':
      return t('safety.status_watch', { defaultValue: 'Watch' });
    case 'red':
      return t('safety.status_alert', { defaultValue: 'Alert' });
    default:
      return t('safety.status_no_data', { defaultValue: 'No data' });
  }
}

function pctAboveBaseline(current: number | null, baseline: number): string | null {
  if (current === null || baseline <= 0) return null;
  const pct = Math.round((current / baseline - 1) * 100);
  return pct > 0 ? `+${pct}%` : `${pct}%`;
}

/* ── One rate row ──────────────────────────────────────────────────────── */

function RateRow({
  label,
  current,
  baseline,
  status,
}: {
  label: string;
  current: number | null;
  baseline: number;
  status: RateStatus;
}) {
  const { t } = useTranslation();
  const meta = STATUS_META[status];
  return (
    <div className="flex items-center justify-between gap-3 py-1.5">
      <div className="flex items-center gap-2">
        <span className={`inline-block h-2.5 w-2.5 rounded-full ${meta.dot}`} aria-hidden="true" />
        <span className="text-sm font-medium text-content-secondary">{label}</span>
      </div>
      <div className="flex items-center gap-2 text-sm">
        <span className="font-bold tabular-nums text-content-primary">
          {current === null ? '—' : current}
        </span>
        <span className="text-xs text-content-tertiary">
          {t('safety.baseline_short', { defaultValue: 'base' })} {baseline}
        </span>
        <span className={`rounded px-1.5 py-0.5 text-2xs font-semibold ${meta.badge}`}>
          {statusLabel(status, t)}
        </span>
      </div>
    </div>
  );
}

/* ── Expanded detail (delta + sparkline) ───────────────────────────────── */

function ThresholdDetail({
  projectId,
  alert,
}: {
  projectId: string;
  alert: SafetyThresholdAlertResponse;
}) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery({
    queryKey: ['safety-trends-extended', projectId, 'monthly', 'sparkline'],
    queryFn: () =>
      apiGet<SafetyTrendsExtendedResponse>(
        `/v1/safety/trends/extended/?project_id=${projectId}&period=monthly`,
      ),
    enabled: !!projectId,
  });

  // Last 3 periods that carry a usable LTIFR for the sparkline.
  const spark = (data?.entries ?? [])
    .filter((e) => e.ltifr !== null)
    .slice(-3)
    .map((e) => ({ period: e.period, ltifr: e.ltifr }));

  const ltifrPct = pctAboveBaseline(alert.current_ltifr, alert.baseline_ltifr);
  const trirPct = pctAboveBaseline(alert.current_trir, alert.baseline_trir);

  return (
    <div className="mt-3 space-y-3 border-t border-border-light pt-3">
      <div className="grid grid-cols-2 gap-3 text-xs">
        <div>
          <div className="text-content-tertiary">
            {t('safety.ltifr_delta', { defaultValue: 'LTIFR delta' })}
          </div>
          <div className="font-semibold tabular-nums text-content-primary">
            {alert.ltifr_delta === null ? '—' : alert.ltifr_delta}
            {ltifrPct && <span className="ml-1 text-content-tertiary">({ltifrPct})</span>}
          </div>
        </div>
        <div>
          <div className="text-content-tertiary">
            {t('safety.trir_delta', { defaultValue: 'TRIR delta' })}
          </div>
          <div className="font-semibold tabular-nums text-content-primary">
            {alert.trir_delta === null ? '—' : alert.trir_delta}
            {trirPct && <span className="ml-1 text-content-tertiary">({trirPct})</span>}
          </div>
        </div>
      </div>

      <div>
        <div className="mb-1 text-2xs uppercase text-content-tertiary">
          {t('safety.ltifr_sparkline', { defaultValue: '3-period LTIFR' })}
        </div>
        {isLoading ? (
          <Skeleton className="h-10 w-full" />
        ) : spark.length > 0 ? (
          <div style={{ width: '100%', height: 40 }} data-testid="threshold-sparkline">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={spark} margin={{ top: 4, right: 4, bottom: 0, left: 4 }}>
                <Line
                  type="monotone"
                  dataKey="ltifr"
                  stroke="#ef4444"
                  strokeWidth={2}
                  dot={{ r: 2 }}
                  isAnimationActive={false}
                />
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="text-xs text-content-tertiary">
            {t('safety.no_trend_data', { defaultValue: 'No data available' })}
          </p>
        )}
      </div>

      {alert.message && (
        <p className="text-xs text-content-secondary">{alert.message}</p>
      )}
    </div>
  );
}

/* ── Widget ────────────────────────────────────────────────────────────── */

export function SafetyThresholdWidget({ projectId }: SafetyThresholdWidgetProps) {
  const { t } = useTranslation();
  const [expanded, setExpanded] = useState(false);

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['safety-threshold-alert', projectId],
    queryFn: () =>
      apiGet<SafetyThresholdAlertResponse>(
        `/v1/safety/threshold-alert/?project_id=${projectId}`,
      ),
    enabled: !!projectId,
  });

  if (isLoading) {
    return (
      <Card className="p-4">
        <Skeleton className="h-20 w-full" />
      </Card>
    );
  }
  if (isError) return <RecoveryCard error={error} onRetry={() => refetch()} />;
  if (!data) return null;

  // Headline status = the worse of the two rates.
  const order: Record<RateStatus, number> = { red: 3, yellow: 2, green: 1, unknown: 0 };
  const headline: RateStatus =
    order[data.ltifr_status] >= order[data.trir_status] ? data.ltifr_status : data.trir_status;
  const HeadlineIcon = STATUS_META[headline].icon;

  return (
    <Card padding="none" className="overflow-hidden">
      <div className="p-4">
        <div className="mb-2 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <HeadlineIcon size={18} className="text-content-secondary" />
            <h3 className="text-sm font-semibold text-content-primary">
              {t('safety.threshold_title', { defaultValue: 'Safety thresholds' })}
            </h3>
          </div>
          <button
            type="button"
            onClick={() => setExpanded((v) => !v)}
            aria-expanded={expanded}
            aria-label={
              expanded
                ? t('common.collapse', { defaultValue: 'Collapse' })
                : t('common.expand', { defaultValue: 'Expand' })
            }
            className="flex h-7 w-7 items-center justify-center rounded-md text-content-tertiary hover:bg-surface-secondary hover:text-content-primary"
            data-testid="threshold-expand-toggle"
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>

        <RateRow
          label="LTIFR"
          current={data.current_ltifr}
          baseline={data.baseline_ltifr}
          status={data.ltifr_status}
        />
        <RateRow
          label="TRIR"
          current={data.current_trir}
          baseline={data.baseline_trir}
          status={data.trir_status}
        />

        {expanded && <ThresholdDetail projectId={projectId} alert={data} />}
      </div>
    </Card>
  );
}
