// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ForecastInsightsPanel — live predictive cost + schedule + risk analytics
 * (TOP-30 #19).
 *
 * Fetches GET /v1/project-intelligence/{projectId}/forecast and renders:
 *   1. Cost tiles: CPI, SPI, EAC, VAC (recomputed Earned Value).
 *   2. Schedule slip: baseline vs forecast finish, finish-variance days and
 *      at-risk task count.
 *   3. Cost-overrun risk gauge: 0..1 score with a RAG band, a confidence
 *      readout, and a human-readable rationale bullet list.
 *
 * Determinism + philosophy: every number is a closed-form forecast computed
 * server-side; nothing here triggers an action. The panel is permanently
 * stamped "forecast - review required" so the user knows this is guidance,
 * not a commitment.
 *
 * This is distinct from ForecastPanel.tsx (which reads persisted EVMForecast
 * rows and exposes acknowledge/snooze on threshold alerts). This panel is a
 * read-only, live recompute with no side effects.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import {
  Activity,
  AlertTriangle,
  CalendarClock,
  Gauge,
  Info,
  RefreshCw,
  ShieldQuestion,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { fmtFixed } from '@/shared/lib/formatters';

interface CostForecast {
  available: boolean;
  reason: string | null;
  currency: string;
  snapshot_date: string | null;
  bac: string | null;
  ev: string | null;
  ac: string | null;
  pv: string | null;
  cpi: number | null;
  spi: number | null;
  eac: string | null;
  etc: string | null;
  vac: string | null;
  tcpi: string | null;
  eac_over_bac: number | null;
}

interface ScheduleSlip {
  available: boolean;
  reason: string | null;
  activities_total: number;
  activities_complete: number;
  planned_pct_complete: number | null;
  actual_pct_complete: number | null;
  baseline_finish: string | null;
  forecast_finish: string | null;
  finish_variance_days: number | null;
  at_risk_task_count: number;
}

interface CostOverrunRisk {
  score: number;
  band: string;
  confidence: number;
  rationale: string[];
}

interface ProjectForecast {
  project_id: string;
  project_name: string;
  currency: string;
  generated_at: string;
  cost: CostForecast;
  schedule: ScheduleSlip;
  risk: CostOverrunRisk;
  review_required: boolean;
}

interface ForecastInsightsPanelProps {
  projectId: string;
}

const BAND_STYLE: Record<string, { ring: string; text: string; chip: string; label: string }> = {
  green: {
    ring: 'text-emerald-500',
    text: 'text-emerald-600 dark:text-emerald-400',
    chip: 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-300',
    label: 'Low',
  },
  amber: {
    ring: 'text-amber-500',
    text: 'text-amber-600 dark:text-amber-400',
    chip: 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300',
    label: 'Moderate',
  },
  red: {
    ring: 'text-rose-500',
    text: 'text-rose-600 dark:text-rose-400',
    chip: 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300',
    label: 'High',
  },
};

/** Classify a performance index: >=1.0 healthy, >=0.95 caution, else red. */
function indexColor(value: number | null): string {
  if (value === null) return 'text-content-tertiary';
  if (value >= 1.0) return 'text-emerald-500';
  if (value >= 0.95) return 'text-amber-500';
  return 'text-rose-500';
}

function num(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : parseFloat(String(value ?? ''));
  return Number.isFinite(n) ? n : 0;
}

export function ForecastInsightsPanel({ projectId }: ForecastInsightsPanelProps) {
  const { t } = useTranslation();
  const [data, setData] = useState<ProjectForecast | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!projectId) return;
    try {
      setError(null);
      const resp = await apiGet<ProjectForecast>(
        `/v1/project-intelligence/${projectId}/forecast`,
      );
      setData(resp);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load forecast');
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  if (loading) {
    return (
      <div
        className="py-12 text-center text-sm text-content-tertiary animate-pulse"
        data-testid="forecast-insights-loading"
      >
        <Activity size={28} className="mx-auto mb-2 text-oe-blue" />
        {t('project_intelligence.insights.loading', {
          defaultValue: 'Computing predictive analytics…',
        })}
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-10 text-center space-y-3" data-testid="forecast-insights-error">
        <AlertTriangle size={24} className="mx-auto text-amber-500" />
        <p className="text-sm text-content-secondary">{error}</p>
        <button
          onClick={() => {
            setLoading(true);
            fetchData();
          }}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 text-xs bg-oe-blue text-white rounded-lg hover:bg-oe-blue-dark transition-colors"
        >
          <RefreshCw size={13} />
          {t('common.retry', { defaultValue: 'Retry' })}
        </button>
      </div>
    );
  }

  if (!data) return null;

  const { cost, schedule, risk } = data;
  const currency = data.currency || cost.currency || 'EUR';
  const band = BAND_STYLE[risk.band] ?? BAND_STYLE.green!;
  const scorePct = Math.round(risk.score * 100);
  const confidencePct = Math.round(risk.confidence * 100);
  const lateFinish = (schedule.finish_variance_days ?? 0) > 0;

  return (
    <div className="space-y-4" data-testid="forecast-insights-panel">
      {/* Forecast - review required banner (always shown) */}
      <div
        className="flex items-center gap-2 rounded-lg border border-oe-blue/15 bg-oe-blue-subtle/20 px-3 py-2"
        data-testid="forecast-insights-disclaimer"
      >
        <Info size={14} className="shrink-0 text-oe-blue" />
        <p className="text-2xs text-content-secondary">
          {t('project_intelligence.insights.review_required', {
            defaultValue:
              'Forecast - review required. These are deterministic projections to guide your review, not committed values. No action is taken automatically.',
          })}
        </p>
      </div>

      {/* Cost tiles */}
      {cost.available ? (
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3" data-testid="forecast-insights-cost-tiles">
          {/* CPI */}
          <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-3">
            <div className="flex items-center justify-between">
              <h4 className="text-2xs font-medium text-content-secondary">
                {t('project_intelligence.insights.cpi', { defaultValue: 'CPI' })}
              </h4>
              {(cost.cpi ?? 0) >= 1 ? (
                <TrendingUp size={14} className={indexColor(cost.cpi)} />
              ) : (
                <TrendingDown size={14} className={indexColor(cost.cpi)} />
              )}
            </div>
            <span
              className={`mt-1 block text-xl font-bold tabular-nums ${indexColor(cost.cpi)}`}
              data-testid="forecast-insights-cpi"
            >
              {cost.cpi !== null ? fmtFixed(cost.cpi, 2) : '—'}
            </span>
          </div>

          {/* SPI */}
          <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-3">
            <div className="flex items-center justify-between">
              <h4 className="text-2xs font-medium text-content-secondary">
                {t('project_intelligence.insights.spi', { defaultValue: 'SPI' })}
              </h4>
              {(cost.spi ?? 0) >= 1 ? (
                <TrendingUp size={14} className={indexColor(cost.spi)} />
              ) : (
                <TrendingDown size={14} className={indexColor(cost.spi)} />
              )}
            </div>
            <span
              className={`mt-1 block text-xl font-bold tabular-nums ${indexColor(cost.spi)}`}
              data-testid="forecast-insights-spi"
            >
              {cost.spi !== null ? fmtFixed(cost.spi, 2) : '—'}
            </span>
          </div>

          {/* EAC */}
          <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-3">
            <h4 className="text-2xs font-medium text-content-secondary">
              {t('project_intelligence.insights.eac', {
                defaultValue: 'EAC (forecast)',
              })}
            </h4>
            <div className="mt-1" data-testid="forecast-insights-eac">
              <MoneyDisplay
                amount={num(cost.eac)}
                currency={currency}
                className="text-xl font-bold tabular-nums"
              />
            </div>
          </div>

          {/* VAC */}
          <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-3">
            <h4 className="text-2xs font-medium text-content-secondary">
              {t('project_intelligence.insights.vac', {
                defaultValue: 'VAC (variance)',
              })}
            </h4>
            <div className="mt-1" data-testid="forecast-insights-vac">
              <MoneyDisplay
                amount={num(cost.vac)}
                currency={currency}
                colorize
                className="text-xl font-bold tabular-nums"
              />
            </div>
          </div>
        </div>
      ) : (
        <div
          className="rounded-xl border border-dashed border-border-light p-6 text-center"
          data-testid="forecast-insights-cost-degraded"
        >
          <Target size={24} className="mx-auto mb-2 text-content-quaternary" />
          <p className="text-sm font-medium text-content-primary">
            {t('project_intelligence.insights.cost_unavailable_title', {
              defaultValue: 'Cost forecast not available yet',
            })}
          </p>
          <p className="text-2xs text-content-tertiary mt-1 max-w-md mx-auto">
            {t(`project_intelligence.insights.reason_${cost.reason ?? 'unknown'}`, {
              defaultValue:
                'Capture an Earned Value snapshot in the Cost model to unlock the CPI/SPI/EAC forecast.',
            })}
          </p>
        </div>
      )}

      {/* Schedule slip + Risk gauge */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {/* Schedule slip */}
        <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
          <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2 mb-3">
            <CalendarClock size={15} className="text-oe-blue" />
            {t('project_intelligence.insights.schedule_title', {
              defaultValue: 'Schedule slip projection',
            })}
          </h3>
          {schedule.available ? (
            <div className="space-y-2 text-xs" data-testid="forecast-insights-schedule">
              <div className="flex items-center justify-between">
                <span className="text-content-secondary">
                  {t('project_intelligence.insights.finish_variance', {
                    defaultValue: 'Forecast finish variance',
                  })}
                </span>
                {schedule.finish_variance_days !== null ? (
                  <span
                    className={`font-semibold tabular-nums ${
                      lateFinish
                        ? 'text-rose-500'
                        : schedule.finish_variance_days < 0
                          ? 'text-emerald-500'
                          : 'text-content-secondary'
                    }`}
                    data-testid="forecast-insights-finish-variance"
                  >
                    {t('project_intelligence.insights.variance_days', {
                      defaultValue: '{{count}} day(s)',
                      count: schedule.finish_variance_days,
                    })}
                  </span>
                ) : (
                  <span className="text-content-tertiary">—</span>
                )}
              </div>
              <div className="flex items-center justify-between">
                <span className="text-content-secondary">
                  {t('project_intelligence.insights.baseline_finish', {
                    defaultValue: 'Baseline finish',
                  })}
                </span>
                <span className="text-content-secondary">{schedule.baseline_finish ?? '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-content-secondary">
                  {t('project_intelligence.insights.forecast_finish', {
                    defaultValue: 'Forecast finish',
                  })}
                </span>
                <span className="text-content-secondary">{schedule.forecast_finish ?? '—'}</span>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-content-secondary">
                  {t('project_intelligence.insights.at_risk_tasks', {
                    defaultValue: 'At-risk tasks',
                  })}
                </span>
                <span
                  className={`font-semibold tabular-nums ${
                    schedule.at_risk_task_count > 0 ? 'text-amber-500' : 'text-content-secondary'
                  }`}
                  data-testid="forecast-insights-at-risk"
                >
                  {schedule.at_risk_task_count} / {schedule.activities_total}
                </span>
              </div>
            </div>
          ) : (
            <p
              className="text-2xs text-content-tertiary py-4 text-center"
              data-testid="forecast-insights-schedule-degraded"
            >
              {t('project_intelligence.insights.schedule_unavailable', {
                defaultValue:
                  'No schedule with dated activities yet - add a schedule to project a finish variance.',
              })}
            </p>
          )}
        </div>

        {/* Risk gauge */}
        <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
          <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2 mb-3">
            <Gauge size={15} className="text-oe-blue" />
            {t('project_intelligence.insights.risk_title', {
              defaultValue: 'Cost-overrun risk',
            })}
          </h3>
          <div className="flex items-center gap-4">
            <div className="shrink-0 text-center">
              <span
                className={`block text-3xl font-bold tabular-nums ${band.text}`}
                data-testid="forecast-insights-risk-score"
              >
                {scorePct}
              </span>
              <span
                className={`mt-1 inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-2xs font-medium ${band.chip}`}
                data-testid="forecast-insights-risk-band"
              >
                {t(`project_intelligence.insights.band_${risk.band}`, {
                  defaultValue: band.label,
                })}
              </span>
            </div>
            <div className="flex-1 min-w-0">
              {/* RAG bar */}
              <div className="h-2 rounded-full bg-surface-tertiary overflow-hidden">
                <div
                  className={`h-full rounded-full ${
                    risk.band === 'red'
                      ? 'bg-rose-400'
                      : risk.band === 'amber'
                        ? 'bg-amber-400'
                        : 'bg-emerald-400'
                  }`}
                  style={{ width: `${Math.min(100, scorePct)}%` }}
                />
              </div>
              <p
                className="mt-2 flex items-center gap-1 text-2xs text-content-tertiary"
                data-testid="forecast-insights-confidence"
              >
                <ShieldQuestion size={12} />
                {t('project_intelligence.insights.confidence', {
                  defaultValue: 'Confidence: {{pct}}%',
                  pct: confidencePct,
                })}
              </p>
            </div>
          </div>

          {/* Rationale bullets */}
          <ul
            className="mt-3 space-y-1 border-t border-border-light pt-3"
            data-testid="forecast-insights-rationale"
          >
            {risk.rationale.map((line, i) => (
              <li key={i} className="flex items-start gap-1.5 text-2xs text-content-secondary">
                <span className="mt-1 h-1 w-1 shrink-0 rounded-full bg-content-quaternary" />
                <span>{line}</span>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
