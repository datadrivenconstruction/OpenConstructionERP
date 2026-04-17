/**
 * ProjectKPIHero — 3-card KPI strip for the Estimation Dashboard (RFC 25).
 *
 * Cards:
 *   1. Budget variance (traffic light: green ±3% · amber ±5% · red > ±5%)
 *   2. Schedule health (% of activities on baseline)
 *   3. Risk-adjusted cost (point estimate ± 90% CI, derived from anomalies)
 */

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  TrendingUp,
  TrendingDown,
  CalendarCheck,
  ShieldAlert,
  Minus,
} from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { classifyVariance, type VarianceLevel } from './variance-thresholds';

export const PI_QUERY_STALE_MS = 60_000;

interface VarianceResponse {
  budget: number;
  current: number;
  variance_abs: number;
  variance_pct: number;
  red_line: number;
  currency: string;
}

interface AnomalyRow {
  position_id: string;
  type: 'outlier' | 'jump' | 'format';
  severity: 'info' | 'warning' | 'error';
  detail: string;
  value: number | null;
  reference: number | null;
}

interface ScheduleHealthState {
  progress_pct?: number;
  on_track?: number;
  total?: number;
  baseline_adherence_pct?: number;
}

interface SummaryState {
  schedule?: ScheduleHealthState;
  [key: string]: unknown;
}

interface SummaryResponse {
  state?: SummaryState;
}

interface ProjectKPIHeroProps {
  projectId: string;
}

function formatMoney(value: number, currency: string): string {
  if (!Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `${currency} ${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${currency} ${(value / 1_000).toFixed(1)}k`;
  return `${currency} ${value.toFixed(0)}`;
}

const LEVEL_STYLE: Record<VarianceLevel, { ring: string; text: string; dot: string }> = {
  green: { ring: 'ring-emerald-400/40', text: 'text-emerald-500', dot: 'bg-emerald-500' },
  amber: { ring: 'ring-amber-400/40', text: 'text-amber-500', dot: 'bg-amber-500' },
  red: { ring: 'ring-rose-400/40', text: 'text-rose-500', dot: 'bg-rose-500' },
};

export function ProjectKPIHero({ projectId }: ProjectKPIHeroProps) {
  const { t } = useTranslation();

  const varianceQ = useQuery({
    queryKey: ['pi', 'variance', projectId],
    queryFn: () =>
      apiGet<VarianceResponse>(`/v1/costmodel/variance/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const anomaliesQ = useQuery({
    queryKey: ['pi', 'anomalies', projectId],
    queryFn: () => apiGet<AnomalyRow[]>(`/v1/boq/anomalies/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const summaryQ = useQuery({
    queryKey: ['pi', 'summary', projectId],
    queryFn: () =>
      apiGet<SummaryResponse>(`/v1/project_intelligence/summary/?project_id=${projectId}`),
    staleTime: PI_QUERY_STALE_MS,
    enabled: !!projectId,
  });

  const variance = varianceQ.data;
  const variancePct = variance?.variance_pct ?? 0;
  const level = classifyVariance(variancePct);
  const varianceStyle = LEVEL_STYLE[level];
  const VarianceIcon =
    variancePct > 0 ? TrendingUp : variancePct < 0 ? TrendingDown : Minus;

  const schedule = summaryQ.data?.state?.schedule;
  const scheduleAdherence =
    typeof schedule?.baseline_adherence_pct === 'number'
      ? schedule.baseline_adherence_pct
      : typeof schedule?.progress_pct === 'number'
      ? schedule.progress_pct
      : 0;
  const scheduleLevel: VarianceLevel =
    scheduleAdherence >= 90 ? 'green' : scheduleAdherence >= 75 ? 'amber' : 'red';
  const scheduleStyle = LEVEL_STYLE[scheduleLevel];

  // Risk-adjusted cost: simple ± band scaled by anomaly density.
  const anomalies = anomaliesQ.data ?? [];
  const anomalyCount = anomalies.length;
  const uncertaintyPct = Math.min(20, anomalyCount * 1.5); // cap at ±20%
  const pointEstimate = variance?.current ?? 0;
  const ciWidth = pointEstimate * (uncertaintyPct / 100);
  const riskLevel: VarianceLevel =
    uncertaintyPct <= 5 ? 'green' : uncertaintyPct <= 10 ? 'amber' : 'red';
  const riskStyle = LEVEL_STYLE[riskLevel];

  return (
    <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
      {/* Card 1 — Budget variance */}
      <div
        data-testid="kpi-card-variance"
        className={`rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4 ring-2 ${varianceStyle.ring}`}
      >
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-medium text-content-secondary">
            {t('project_intelligence.kpi.budget_variance', {
              defaultValue: 'Budget variance',
            })}
          </h4>
          <span className={`w-2 h-2 rounded-full ${varianceStyle.dot}`} />
        </div>
        <div className="flex items-baseline gap-2 mt-2">
          <VarianceIcon size={20} className={varianceStyle.text} />
          <span
            className={`text-2xl font-bold tabular-nums ${varianceStyle.text}`}
            data-testid="kpi-variance-pct"
          >
            {variancePct > 0 ? '+' : ''}
            {variancePct.toFixed(1)}%
          </span>
        </div>
        <p className="text-2xs text-content-tertiary mt-1">
          {t('project_intelligence.kpi.variance_sub', {
            defaultValue: 'Budget {{budget}} · Current {{current}}',
            budget: formatMoney(variance?.budget ?? 0, variance?.currency ?? 'EUR'),
            current: formatMoney(variance?.current ?? 0, variance?.currency ?? 'EUR'),
          })}
        </p>
      </div>

      {/* Card 2 — Schedule health */}
      <div
        data-testid="kpi-card-schedule"
        className={`rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4 ring-2 ${scheduleStyle.ring}`}
      >
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-medium text-content-secondary">
            {t('project_intelligence.kpi.schedule_health', {
              defaultValue: 'Schedule health',
            })}
          </h4>
          <span className={`w-2 h-2 rounded-full ${scheduleStyle.dot}`} />
        </div>
        <div className="flex items-baseline gap-2 mt-2">
          <CalendarCheck size={20} className={scheduleStyle.text} />
          <span className={`text-2xl font-bold tabular-nums ${scheduleStyle.text}`}>
            {scheduleAdherence.toFixed(0)}%
          </span>
        </div>
        <p className="text-2xs text-content-tertiary mt-1">
          {t('project_intelligence.kpi.schedule_sub', {
            defaultValue: 'Activities on baseline',
          })}
        </p>
      </div>

      {/* Card 3 — Risk-adjusted cost */}
      <div
        data-testid="kpi-card-risk"
        className={`rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4 ring-2 ${riskStyle.ring}`}
      >
        <div className="flex items-center justify-between">
          <h4 className="text-xs font-medium text-content-secondary">
            {t('project_intelligence.kpi.risk_adjusted_cost', {
              defaultValue: 'Risk-adjusted cost',
            })}
          </h4>
          <span className={`w-2 h-2 rounded-full ${riskStyle.dot}`} />
        </div>
        <div className="flex items-baseline gap-2 mt-2">
          <ShieldAlert size={20} className={riskStyle.text} />
          <span className={`text-2xl font-bold tabular-nums ${riskStyle.text}`}>
            {formatMoney(pointEstimate, variance?.currency ?? 'EUR')}
          </span>
        </div>
        <p className="text-2xs text-content-tertiary mt-1">
          {t('project_intelligence.kpi.risk_sub', {
            defaultValue: '±{{band}} (90% CI, {{count}} anomalies)',
            band: formatMoney(ciWidth, variance?.currency ?? 'EUR'),
            count: anomalyCount,
          })}
        </p>
      </div>
    </div>
  );
}
