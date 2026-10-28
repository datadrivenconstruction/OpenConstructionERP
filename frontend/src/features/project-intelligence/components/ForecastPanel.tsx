// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ForecastPanel — predictive EVM forecast + alert surface (TOP-30 #19).
 *
 * Rendered inside the Estimation Dashboard's "Forecasts" tab. Shows:
 *   1. SPI / CPI performance chips with a tiny CSS-bar sparkline (no
 *      charting dependency — keeps the bundle lean).
 *   2. Forecast-to-Completion card: Baseline (BAC) vs forecast (EAC) with
 *      the overrun / underrun delta and a proportional bar.
 *   3. Contingency / overrun gauge (green when EAC ≤ BAC, red when over).
 *   4. Active Alerts table with Acknowledge / Snooze / View actions.
 *
 * Determinism: every number comes straight from the backend forecast +
 * EVM snapshot history. No AI, no auto-actions — the user acknowledges or
 * snoozes each alert themselves.
 */

import { useCallback, useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Link } from 'react-router-dom';
import {
  TrendingUp,
  TrendingDown,
  Activity,
  Target,
  AlertTriangle,
  CheckCircle2,
  BellOff,
  ExternalLink,
  RefreshCw,
} from 'lucide-react';
import { apiGet, apiPost } from '@/shared/lib/api';
import { useToastStore } from '@/stores/useToastStore';
import { MoneyDisplay } from '@/shared/ui/MoneyDisplay';
import { getIntlLocale, fmtFixed } from '@/shared/lib/formatters';

interface SparklinePoint {
  date: string;
  spi: number;
  cpi: number;
  eac: number;
  ev: number;
  ac: number;
}

interface AlertRow {
  forecast_id: string;
  forecast_date: string;
  alert_status: string;
  triggered_at: string | null;
  snoozed_until: string | null;
  severity: string;
  eac: string;
  vac: string;
  tcpi: string;
  summary: string;
}

interface LatestForecast {
  forecast_id: string;
  forecast_date: string;
  method: string;
  etc: string;
  eac: string;
  vac: string;
  tcpi: string;
  bac: string;
  spi: string;
  cpi: string;
  eac_over_bac: number;
  alert_status: string | null;
}

interface ForecastsResponse {
  project_id: string;
  currency: string;
  latest_forecast: LatestForecast | null;
  active_alerts: AlertRow[];
  sparkline: SparklinePoint[];
}

interface ForecastPanelProps {
  projectId: string;
  /** Notifies the parent when the active-alert count changes (banner sync). */
  onAlertCountChange?: (count: number) => void;
}

const SEVERITY_STYLE: Record<string, { chip: string; dot: string; label: string }> = {
  critical: { chip: 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300', dot: 'bg-rose-500', label: 'Critical' },
  error: { chip: 'bg-rose-50 text-rose-700 dark:bg-rose-950/30 dark:text-rose-300', dot: 'bg-rose-500', label: 'Error' },
  warning: { chip: 'bg-amber-50 text-amber-700 dark:bg-amber-950/30 dark:text-amber-300', dot: 'bg-amber-500', label: 'Warning' },
  info: { chip: 'bg-sky-50 text-sky-700 dark:bg-sky-950/30 dark:text-sky-300', dot: 'bg-sky-500', label: 'Info' },
};

/** Classify a performance index: ≥1.0 healthy, ≥0.95 caution, else red. */
function indexLevel(value: number): 'green' | 'amber' | 'red' {
  if (value >= 1.0) return 'green';
  if (value >= 0.95) return 'amber';
  return 'red';
}

const INDEX_COLOR: Record<'green' | 'amber' | 'red', string> = {
  green: 'text-emerald-500',
  amber: 'text-amber-500',
  red: 'text-rose-500',
};
const INDEX_BAR: Record<'green' | 'amber' | 'red', string> = {
  green: 'bg-emerald-400',
  amber: 'bg-amber-400',
  red: 'bg-rose-400',
};

function num(value: string | number | null | undefined): number {
  const n = typeof value === 'number' ? value : parseFloat(String(value ?? ''));
  return Number.isFinite(n) ? n : 0;
}

/** Tiny inline CSS-bar sparkline (last N values, normalised to the max). */
function Sparkline({ values, color }: { values: number[]; color: string }) {
  if (values.length === 0) {
    return <div className="h-8" />;
  }
  const max = Math.max(...values, 0.0001);
  const min = Math.min(...values, 0);
  const range = max - min || 1;
  return (
    <div className="flex items-end gap-0.5 h-8" aria-hidden="true">
      {values.map((v, i) => {
        const h = Math.max(8, Math.round(((v - min) / range) * 100));
        return (
          <div
            key={i}
            className={`w-1.5 rounded-sm ${color}`}
            style={{ height: `${h}%` }}
          />
        );
      })}
    </div>
  );
}

export function ForecastPanel({ projectId, onAlertCountChange }: ForecastPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [data, setData] = useState<ForecastsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!projectId) return;
    try {
      setError(null);
      const resp = await apiGet<ForecastsResponse>(
        `/v1/project-intelligence/forecasts/?project_id=${projectId}`,
      );
      setData(resp);
      onAlertCountChange?.(resp.active_alerts.length);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load forecast');
    } finally {
      setLoading(false);
    }
  }, [projectId, onAlertCountChange]);

  useEffect(() => {
    setLoading(true);
    fetchData();
  }, [fetchData]);

  const handleAcknowledge = useCallback(
    async (forecastId: string) => {
      setBusyId(forecastId);
      try {
        await apiPost(`/v1/project-intelligence/forecasts/${forecastId}/acknowledge/`);
        addToast({
          type: 'success',
          title: t('project_intelligence.forecast.ack_done', {
            defaultValue: 'Alert acknowledged',
          }),
        });
        await fetchData();
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('project_intelligence.forecast.ack_failed', {
            defaultValue: 'Could not acknowledge the alert',
          }),
          message: err instanceof Error ? err.message : '',
        });
      } finally {
        setBusyId(null);
      }
    },
    [fetchData, addToast, t],
  );

  const handleSnooze = useCallback(
    async (forecastId: string) => {
      setBusyId(forecastId);
      try {
        await apiPost(`/v1/project-intelligence/forecasts/${forecastId}/snooze/`, {
          hours: 24,
        });
        addToast({
          type: 'success',
          title: t('project_intelligence.forecast.snooze_done', {
            defaultValue: 'Snoozed for 24 hours',
          }),
        });
        await fetchData();
      } catch (err: unknown) {
        addToast({
          type: 'error',
          title: t('project_intelligence.forecast.snooze_failed', {
            defaultValue: 'Could not snooze the alert',
          }),
          message: err instanceof Error ? err.message : '',
        });
      } finally {
        setBusyId(null);
      }
    },
    [fetchData, addToast, t],
  );

  if (loading) {
    return (
      <div className="py-12 text-center text-sm text-content-tertiary animate-pulse">
        <Activity size={28} className="mx-auto mb-2 text-oe-blue" />
        {t('project_intelligence.forecast.loading', {
          defaultValue: 'Computing forecast…',
        })}
      </div>
    );
  }

  if (error) {
    return (
      <div className="py-10 text-center space-y-3">
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

  const fc = data?.latest_forecast ?? null;
  const currency = data?.currency || 'EUR';

  if (!fc) {
    return (
      <div className="py-12 text-center space-y-2">
        <Target size={28} className="mx-auto text-content-quaternary" />
        <p className="text-sm font-medium text-content-primary">
          {t('project_intelligence.forecast.empty_title', {
            defaultValue: 'No forecast yet',
          })}
        </p>
        <p className="text-2xs text-content-tertiary max-w-md mx-auto">
          {t('project_intelligence.forecast.empty_body', {
            defaultValue:
              'A predictive EAC/ETC forecast appears once this project has at least one EVM snapshot. Capture earned value in the Cost model to begin.',
          })}
        </p>
      </div>
    );
  }

  const spi = num(fc.spi);
  const cpi = num(fc.cpi);
  const bac = num(fc.bac);
  const eac = num(fc.eac);
  const vac = num(fc.vac);
  const overrunRatio = fc.eac_over_bac || (bac ? eac / bac : 0);
  const overBudget = vac < 0;

  const spiLevel = indexLevel(spi);
  const cpiLevel = indexLevel(cpi);
  const spiSeries = (data?.sparkline ?? []).map((p) => p.spi);
  const cpiSeries = (data?.sparkline ?? []).map((p) => p.cpi);

  // Forecast-to-Completion bar: how far EAC extends past BAC.
  const barMax = Math.max(eac, bac, 1);
  const bacPct = (bac / barMax) * 100;
  const eacPct = (eac / barMax) * 100;

  const alerts = data?.active_alerts ?? [];

  return (
    <div className="space-y-4">
      {/* Performance index chips + Forecast-to-Completion */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        {/* SPI chip */}
        <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-medium text-content-secondary">
              {t('project_intelligence.forecast.spi', {
                defaultValue: 'Schedule Performance (SPI)',
              })}
            </h4>
            {spi >= 1 ? (
              <TrendingUp size={16} className={INDEX_COLOR[spiLevel]} />
            ) : (
              <TrendingDown size={16} className={INDEX_COLOR[spiLevel]} />
            )}
          </div>
          <div className="flex items-end justify-between mt-2">
            <span className={`text-2xl font-bold tabular-nums ${INDEX_COLOR[spiLevel]}`}>
              {fmtFixed(spi, 3)}
            </span>
            <Sparkline values={spiSeries} color={INDEX_BAR[spiLevel]} />
          </div>
          <p className="text-2xs text-content-tertiary mt-1">
            {t('project_intelligence.forecast.index_hint', {
              defaultValue: '1.00 = on plan · below = behind',
            })}
          </p>
        </div>

        {/* CPI chip */}
        <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-medium text-content-secondary">
              {t('project_intelligence.forecast.cpi', {
                defaultValue: 'Cost Performance (CPI)',
              })}
            </h4>
            {cpi >= 1 ? (
              <TrendingUp size={16} className={INDEX_COLOR[cpiLevel]} />
            ) : (
              <TrendingDown size={16} className={INDEX_COLOR[cpiLevel]} />
            )}
          </div>
          <div className="flex items-end justify-between mt-2">
            <span
              className={`text-2xl font-bold tabular-nums ${INDEX_COLOR[cpiLevel]}`}
              data-testid="forecast-cpi"
            >
              {fmtFixed(cpi, 3)}
            </span>
            <Sparkline values={cpiSeries} color={INDEX_BAR[cpiLevel]} />
          </div>
          <p className="text-2xs text-content-tertiary mt-1">
            {t('project_intelligence.forecast.index_hint', {
              defaultValue: '1.00 = on plan · below = behind',
            })}
          </p>
        </div>

        {/* Contingency / overrun gauge */}
        <div
          className={`rounded-xl bg-white dark:bg-gray-800/60 border shadow-sm p-4 ${
            overBudget ? 'border-rose-300 dark:border-rose-900/50' : 'border-emerald-300 dark:border-emerald-900/50'
          }`}
        >
          <div className="flex items-center justify-between">
            <h4 className="text-xs font-medium text-content-secondary">
              {t('project_intelligence.forecast.forecast_variance', {
                defaultValue: 'Variance at Completion (VAC)',
              })}
            </h4>
            <span className={`w-2 h-2 rounded-full ${overBudget ? 'bg-rose-500' : 'bg-emerald-500'}`} />
          </div>
          <div className="mt-2">
            <MoneyDisplay
              amount={vac}
              currency={currency}
              colorize
              className="text-2xl font-bold tabular-nums"
            />
          </div>
          <p className="text-2xs text-content-tertiary mt-1">
            {overBudget
              ? t('project_intelligence.forecast.over_budget', {
                  defaultValue: 'Forecast to finish {{pct}}% over budget',
                  pct: fmtFixed((overrunRatio - 1) * 100, 1),
                })
              : t('project_intelligence.forecast.under_budget', {
                  defaultValue: 'Forecast within budget',
                })}
          </p>
        </div>
      </div>

      {/* Forecast-to-Completion card */}
      <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
        <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2 mb-3">
          <Target size={15} className="text-oe-blue" />
          {t('project_intelligence.forecast.ftc_title', {
            defaultValue: 'Forecast to Completion',
          })}
          <span className="ml-auto text-2xs font-normal text-content-tertiary">
            {t('project_intelligence.forecast.method', {
              defaultValue: 'Method: {{method}}',
              method: fc.method === 'spi_cpi' ? 'SPI×CPI' : 'CPI',
            })}
          </span>
        </h3>

        <div className="space-y-3">
          {/* Baseline (BAC) bar */}
          <div>
            <div className="flex items-center justify-between text-2xs text-content-secondary mb-1">
              <span>
                {t('project_intelligence.forecast.bac', { defaultValue: 'Baseline (BAC)' })}
              </span>
              <MoneyDisplay amount={bac} currency={currency} className="tabular-nums font-medium" />
            </div>
            <div className="h-3 rounded-full bg-surface-tertiary overflow-hidden">
              <div className="h-full bg-oe-blue/70 rounded-full" style={{ width: `${bacPct}%` }} />
            </div>
          </div>

          {/* Forecast (EAC) bar */}
          <div>
            <div className="flex items-center justify-between text-2xs text-content-secondary mb-1">
              <span>
                {t('project_intelligence.forecast.eac', {
                  defaultValue: 'Forecast at completion (EAC)',
                })}
              </span>
              <MoneyDisplay
                amount={eac}
                currency={currency}
                className={`tabular-nums font-semibold ${overBudget ? 'text-rose-500' : 'text-emerald-500'}`}
              />
            </div>
            <div className="h-3 rounded-full bg-surface-tertiary overflow-hidden">
              <div
                className={`h-full rounded-full ${overBudget ? 'bg-rose-400' : 'bg-emerald-400'}`}
                style={{ width: `${eacPct}%` }}
                data-testid="forecast-eac-bar"
              />
            </div>
          </div>

          <div className="flex flex-wrap gap-x-6 gap-y-1 pt-1 text-2xs text-content-tertiary">
            <span>
              {t('project_intelligence.forecast.etc', { defaultValue: 'ETC (to complete)' })}:{' '}
              <MoneyDisplay amount={num(fc.etc)} currency={currency} className="font-medium text-content-secondary" />
            </span>
            <span>
              {t('project_intelligence.forecast.tcpi', { defaultValue: 'TCPI' })}:{' '}
              <span className="font-medium text-content-secondary tabular-nums">
                {fc.tcpi === 'inf'
                  ? t('project_intelligence.forecast.tcpi_unachievable', {
                      defaultValue: 'Not achievable',
                    })
                  : fmtFixed(num(fc.tcpi), 3)}
              </span>
            </span>
            <span>
              {t('project_intelligence.forecast.as_of', { defaultValue: 'As of' })}:{' '}
              <span className="font-medium text-content-secondary">{fc.forecast_date}</span>
            </span>
          </div>
        </div>
      </div>

      {/* Active Alerts table */}
      <div className="rounded-xl bg-white dark:bg-gray-800/60 border border-border-light shadow-sm p-4">
        <h3 className="text-sm font-semibold text-content-primary flex items-center gap-2 mb-3">
          <AlertTriangle size={15} className={alerts.length ? 'text-rose-400' : 'text-content-quaternary'} />
          {t('project_intelligence.forecast.active_alerts', {
            defaultValue: 'Active Forecast Alerts',
          })}
          <span className="ml-auto text-2xs font-normal text-content-tertiary">{alerts.length}</span>
        </h3>

        {alerts.length === 0 ? (
          <div className="py-6 text-center">
            <CheckCircle2 size={24} className="mx-auto text-emerald-400 mb-2" />
            <p className="text-sm font-medium text-content-primary">
              {t('project_intelligence.forecast.no_alerts_title', {
                defaultValue: 'No active alerts',
              })}
            </p>
            <p className="text-2xs text-content-tertiary mt-1">
              {t('project_intelligence.forecast.no_alerts_body', {
                defaultValue:
                  'The latest forecast is within every threshold set for this project.',
              })}
            </p>
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-content-tertiary text-left border-b border-border-light">
                  <th className="py-2 pr-3 font-medium">
                    {t('project_intelligence.forecast.col_severity', { defaultValue: 'Severity' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('project_intelligence.forecast.col_reason', { defaultValue: 'Reason' })}
                  </th>
                  <th className="py-2 pr-3 font-medium text-right">
                    {t('project_intelligence.forecast.col_eac', { defaultValue: 'EAC' })}
                  </th>
                  <th className="py-2 pr-3 font-medium">
                    {t('project_intelligence.forecast.col_when', { defaultValue: 'Triggered' })}
                  </th>
                  <th className="py-2 font-medium text-right">
                    {t('project_intelligence.forecast.col_actions', { defaultValue: 'Actions' })}
                  </th>
                </tr>
              </thead>
              <tbody>
                {alerts.map((a) => {
                  const sev = SEVERITY_STYLE[a.severity] ?? SEVERITY_STYLE.warning!;
                  const isSnoozed = a.alert_status === 'snoozed';
                  return (
                    <tr
                      key={a.forecast_id}
                      className="border-b border-border-light/60 last:border-0"
                      data-testid="forecast-alert-row"
                    >
                      <td className="py-2.5 pr-3">
                        <span className={`inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-2xs font-medium ${sev.chip}`}>
                          <span className={`w-1.5 h-1.5 rounded-full ${sev.dot}`} />
                          {t(`project_intelligence.forecast.sev_${a.severity}`, {
                            defaultValue: sev.label,
                          })}
                        </span>
                        {isSnoozed && (
                          <span className="ml-1 inline-flex items-center gap-1 text-2xs text-content-quaternary">
                            <BellOff size={11} />
                            {t('project_intelligence.forecast.snoozed', { defaultValue: 'Snoozed' })}
                          </span>
                        )}
                      </td>
                      <td className="py-2.5 pr-3 text-content-secondary">
                        {a.summary ||
                          t('project_intelligence.forecast.generic_reason', {
                            defaultValue: 'Forecast breached a configured threshold',
                          })}
                      </td>
                      <td className="py-2.5 pr-3 text-right">
                        <MoneyDisplay amount={num(a.eac)} currency={currency} className="tabular-nums" />
                      </td>
                      <td className="py-2.5 pr-3 text-content-tertiary whitespace-nowrap">
                        {a.triggered_at ? new Date(a.triggered_at).toLocaleDateString(getIntlLocale()) : '—'}
                      </td>
                      <td className="py-2.5 text-right whitespace-nowrap">
                        <div className="inline-flex items-center gap-1.5">
                          <button
                            onClick={() => handleAcknowledge(a.forecast_id)}
                            disabled={busyId === a.forecast_id}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md bg-oe-blue text-white text-2xs font-medium hover:bg-oe-blue-dark transition-colors disabled:opacity-50"
                          >
                            <CheckCircle2 size={12} />
                            {t('project_intelligence.forecast.acknowledge', {
                              defaultValue: 'Acknowledge',
                            })}
                          </button>
                          {!isSnoozed && (
                            <button
                              onClick={() => handleSnooze(a.forecast_id)}
                              disabled={busyId === a.forecast_id}
                              className="inline-flex items-center gap-1 px-2 py-1 rounded-md border border-border-light text-content-secondary text-2xs font-medium hover:bg-surface-secondary transition-colors disabled:opacity-50"
                            >
                              <BellOff size={12} />
                              {t('project_intelligence.forecast.snooze_24h', {
                                defaultValue: 'Snooze 24h',
                              })}
                            </button>
                          )}
                          {/* The cost model page is mounted at /5d. This pointed at
                              /costmodel, which is only ever an API prefix and has no
                              route, so the link landed on the catch-all NotFound. */}
                          <Link
                            to={`/5d?project_id=${projectId}`}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded-md text-content-tertiary text-2xs font-medium hover:text-oe-blue transition-colors"
                          >
                            <ExternalLink size={12} />
                            {t('project_intelligence.forecast.view', { defaultValue: 'View' })}
                          </Link>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
