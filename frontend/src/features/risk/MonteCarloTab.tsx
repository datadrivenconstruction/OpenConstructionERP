// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Monte Carlo simulation tab for the Risk Register page.
 *
 * Renders three blocks of UI driven by the
 * ``POST /v1/risk/projects/{id}/simulate`` endpoint:
 *
 *   1. A "Run simulation" panel with iterations input + mode selector.
 *   2. A "Last run" summary strip — P50 / P80 / P95 chips (cost +
 *      schedule), confidence bands familiar to anyone who's used
 *      schedule risk analysis tools.
 *   3. A histogram (Recharts BarChart, 10 equal-width bins) of the
 *      simulated contingency distribution + a tornado chart (top 8
 *      sensitivity contributors, sorted desc).
 *
 * Currency is data-driven — when the project has no currency set we
 * render currency-less numbers rather than mislabelling.
 */

import { useEffect, useMemo, useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { Play, Loader2, TrendingUp, AlertTriangle } from 'lucide-react';

import { Button, Card, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { toNum } from '@/shared/lib/money';
import { useHasPermission } from '@/shared/lib/permissionGates';
import { getNumberLocale } from '@/stores/usePreferencesStore';

import {
  fetchLastSimulation,
  simulateRisk,
  type RiskHistogramBin,
  type RiskSimulateMode,
  type RiskSimulationResult,
} from './api';

interface MonteCarloTabProps {
  projectId: string;
  /** Currency from project context — fed into the chips' label. */
  currency: string;
}

const ITERATIONS_MIN = 1000;
const ITERATIONS_MAX = 100_000;
const ITERATIONS_DEFAULT = 10_000;
const TORNADO_TOP_N = 8;
export const CONFIDENCE_MIN = 50;
export const CONFIDENCE_MAX = 99;
export const RANGE_LOW_MAX = 90;
export const RANGE_HIGH_MAX = 300;

/** A whole number inside [min, max] from a typed value, or null when it is not one. */
export function parseBounded(raw: string, min: number, max: number, integer = false): number | null {
  const text = raw.trim().replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  const v = Number(text);
  if (!Number.isFinite(v) || v < min || v > max) return null;
  if (integer && !Number.isInteger(v)) return null;
  return v;
}

function fmtCurrencyOrPlain(
  n: number | string | null | undefined,
  currency: string,
): string {
  if (n === null || n === undefined) return '—';
  // Backend money arrives as a Decimal-rendered string; coerce safely so a
  // raw string never reaches Intl.NumberFormat (which would render "NaN").
  const value = toNum(n);
  const safe = /^[A-Z]{3}$/.test(currency) ? currency : '';
  try {
    if (safe) {
      return new Intl.NumberFormat(getNumberLocale(), {
        style: 'currency',
        currency: safe,
        minimumFractionDigits: 0,
        maximumFractionDigits: 0,
      }).format(value);
    }
    // No currency known — render a bare number with locale grouping.
    return new Intl.NumberFormat(getNumberLocale(), {
      maximumFractionDigits: 0,
    }).format(value);
  } catch {
    return `${Math.round(value)}`;
  }
}

function fmtDays(n: number | null, t: (k: string, o?: Record<string, unknown>) => string): string {
  if (n === null || n === undefined) return '—';
  return t('risk.montecarlo.days_value', { defaultValue: '{{count}} days', count: n });
}

/**
 * Format a histogram bin's midpoint label.
 *
 * ``lower``/``upper`` arrive as Decimal-rendered strings on the wire, so both
 * operands are coerced with ``Number()`` *before* the addition — using the raw
 * values would string-concatenate ("100000.00" + "150000.00") and then ``/ 2``
 * would yield ``NaN``, rendering every bar's label as "NaN". Exported for a
 * focused regression test of that coercion.
 */
export function binMidpointLabel(
  bin: Pick<RiskHistogramBin, 'lower' | 'upper'>,
  currency: string,
): string {
  return fmtCurrencyOrPlain((Number(bin.lower) + Number(bin.upper)) / 2, currency);
}

export function MonteCarloTab({ projectId, currency }: MonteCarloTabProps) {
  const { t } = useTranslation();
  // The simulate call needs risk.update; a viewer would only collect a 403.
  const canRun = useHasPermission('risk.update');
  const addToast = useToastStore((s) => s.addToast);

  const qc = useQueryClient();
  const [iterations, setIterations] = useState<number>(ITERATIONS_DEFAULT);
  const [mode, setMode] = useState<RiskSimulateMode>('both');
  const [result, setResult] = useState<RiskSimulationResult | null>(null);
  const [confidenceText, setConfidenceText] = useState('80');
  const [lowText, setLowText] = useState('0');
  const [highText, setHighText] = useState('0');
  const confidence = parseBounded(confidenceText, CONFIDENCE_MIN, CONFIDENCE_MAX, true);
  const rangeLow = parseBounded(lowText, 0, RANGE_LOW_MAX);
  const rangeHigh = parseBounded(highText, 0, RANGE_HIGH_MAX);
  const settingsValid = confidence !== null && rangeLow !== null && rangeHigh !== null;

  // The last run is stored with the settings it used; reopening the tab shows
  // it again and puts those settings back in the form.
  const last = useQuery({
    queryKey: ['risk-simulation-last', projectId],
    queryFn: () => fetchLastSimulation(projectId),
    enabled: Boolean(projectId),
    staleTime: 60_000,
  });
  useEffect(() => {
    const snap = last.data;
    if (!snap || result) return;
    setResult(snap);
    setMode(snap.mode);
    setIterations(snap.iterations);
    setConfidenceText(String(snap.confidence ?? 80));
    setLowText(String(snap.range_low_pct ?? 0));
    setHighText(String(snap.range_high_pct ?? 0));
    // Only the first load seeds the form; later runs set the result directly.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [last.data]);

  const ranAt = {
    confidence: result?.confidence ?? 80,
    low: result?.range_low_pct ?? 0,
    high: result?.range_high_pct ?? 0,
  };
  const settingsChanged =
    result !== null &&
    settingsValid &&
    (confidence !== ranAt.confidence || rangeLow !== ranAt.low || rangeHigh !== ranAt.high || mode !== result.mode);

  const runMut = useMutation({
    mutationFn: () =>
      simulateRisk(projectId, {
        iterations,
        mode,
        confidence: confidence ?? 80,
        range_low_pct: rangeLow ?? 0,
        range_high_pct: rangeHigh ?? 0,
      }),
    onSuccess: (data) => {
      setResult(data);
      qc.setQueryData(['risk-simulation-last', projectId], data);
      addToast({
        type: 'success',
        title: t('risk.montecarlo.run_done', {
          defaultValue: 'Simulation complete',
        }),
        message: t('risk.montecarlo.run_done_detail', {
          defaultValue: '{{iterations}} iterations across {{risks}} risks',
          iterations: data.iterations.toLocaleString(getNumberLocale()),
          risks: data.risk_count,
        }),
      });
    },
    onError: (e: Error) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: e.message,
      });
    },
  });

  // Build histogram data shape for Recharts — bins[i] -> { label, count }.
  const histogramData = useMemo(() => {
    if (!result || result.histogram_bins.length === 0) return [];
    return result.histogram_bins.map((b) => ({
      // Compact bin label — midpoint formatted with the project currency.
      label: binMidpointLabel(b, currency),
      count: b.count,
    }));
  }, [result, currency]);

  const tornadoData = useMemo(() => {
    if (!result) return [];
    return result.tornado.slice(0, TORNADO_TOP_N).map((e) => ({
      code: e.code,
      // Decimal-as-string on the wire; coerce so the bar lengths are numeric.
      contribution: toNum(e.contribution),
    }));
  }, [result]);

  const showCostChips = result && (result.mode === 'cost' || result.mode === 'both');
  const showScheduleChips = result && (result.mode === 'schedule' || result.mode === 'both');

  return (
    <div className="space-y-4">
      {/* ── Controls ──────────────────────────────────────────────── */}
      <Card className="p-4">
        <div className="flex flex-wrap items-end gap-4">
          <div>
            <label
              htmlFor="mc-iterations"
              className="oe-label"
            >
              {t('risk.montecarlo.iterations', { defaultValue: 'Iterations' })}
            </label>
            <input
              id="mc-iterations"
              type="number"
              min={ITERATIONS_MIN}
              max={ITERATIONS_MAX}
              step={1000}
              value={iterations}
              onChange={(e) => {
                const v = parseInt(e.target.value, 10);
                if (Number.isFinite(v)) {
                  setIterations(Math.max(ITERATIONS_MIN, Math.min(v, ITERATIONS_MAX)));
                }
              }}
              className="oe-input oe-input-lg w-32"
            />
            <p className="mt-1 text-2xs text-content-tertiary">
              {t('risk.montecarlo.iterations_hint', {
                defaultValue: '1,000 – 100,000',
              })}
            </p>
          </div>

          <div>
            <label
              htmlFor="mc-mode"
              className="oe-label"
            >
              {t('risk.montecarlo.mode', { defaultValue: 'Mode' })}
            </label>
            <select
              id="mc-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value as RiskSimulateMode)}
              className="oe-select oe-input-lg"
            >
              <option value="both">
                {t('risk.montecarlo.mode_both', { defaultValue: 'Cost + Schedule' })}
              </option>
              <option value="cost">
                {t('risk.montecarlo.mode_cost', { defaultValue: 'Cost only' })}
              </option>
              <option value="schedule">
                {t('risk.montecarlo.mode_schedule', { defaultValue: 'Schedule only' })}
              </option>
            </select>
          </div>

          <div>
            <label htmlFor="mc-confidence" className="oe-label">
              {t('risk.montecarlo.confidence', { defaultValue: 'Confidence level (P)' })}
            </label>
            <div className="flex items-center gap-1">
              <input
                id="mc-confidence"
                type="text"
                inputMode="numeric"
                value={confidenceText}
                onChange={(e) => setConfidenceText(e.target.value)}
                aria-invalid={confidence === null || undefined}
                aria-describedby="mc-confidence-hint"
                className={`oe-input oe-input-lg w-20 tabular-nums ${confidence === null ? 'border-semantic-error' : ''}`}
              />
              <span className="text-sm text-content-tertiary">%</span>
            </div>
            <p id="mc-confidence-hint" className={`mt-1 text-2xs ${confidence === null ? 'text-semantic-error' : 'text-content-tertiary'}`}>
              {confidence === null
                ? t('risk.montecarlo.confidence_invalid', {
                    defaultValue: 'Enter a whole number from {{min}} to {{max}}.',
                    min: CONFIDENCE_MIN,
                    max: CONFIDENCE_MAX,
                  })
                : t('risk.montecarlo.confidence_hint', {
                    defaultValue: '{{min}} – {{max}}, usually 80',
                    min: CONFIDENCE_MIN,
                    max: CONFIDENCE_MAX,
                  })}
            </p>
          </div>

          <fieldset>
            <legend className="oe-label">
              {t('risk.montecarlo.range', { defaultValue: 'Range for single-figure risks' })}
            </legend>
            <div className="flex items-center gap-1">
              <span className="text-sm text-content-tertiary">−</span>
              <input
                id="mc-range-low"
                type="text"
                inputMode="decimal"
                value={lowText}
                onChange={(e) => setLowText(e.target.value)}
                aria-label={t('risk.montecarlo.range_low', { defaultValue: 'Below the figure, per cent' })}
                aria-invalid={rangeLow === null || undefined}
                className={`oe-input oe-input-lg w-16 tabular-nums ${rangeLow === null ? 'border-semantic-error' : ''}`}
              />
              <span className="text-sm text-content-tertiary">% / +</span>
              <input
                id="mc-range-high"
                type="text"
                inputMode="decimal"
                value={highText}
                onChange={(e) => setHighText(e.target.value)}
                aria-label={t('risk.montecarlo.range_high', { defaultValue: 'Above the figure, per cent' })}
                aria-invalid={rangeHigh === null || undefined}
                className={`oe-input oe-input-lg w-16 tabular-nums ${rangeHigh === null ? 'border-semantic-error' : ''}`}
              />
              <span className="text-sm text-content-tertiary">%</span>
            </div>
            <p className={`mt-1 text-2xs ${rangeLow === null || rangeHigh === null ? 'text-semantic-error' : 'text-content-tertiary'}`}>
              {rangeLow === null || rangeHigh === null
                ? t('risk.montecarlo.range_invalid', {
                    defaultValue: 'Below: 0 to {{low}} %. Above: 0 to {{high}} %.',
                    low: RANGE_LOW_MAX,
                    high: RANGE_HIGH_MAX,
                  })
                : t('risk.montecarlo.range_hint', { defaultValue: '0 / 0 keeps those risks fixed' })}
            </p>
          </fieldset>

          <Button
            variant="primary"
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !projectId || !canRun || !settingsValid}
            title={
              !canRun
                ? t('risk.montecarlo.run_needs_editor', {
                    defaultValue: 'Running a simulation needs the editor role.',
                  })
                : !settingsValid
                  ? t('risk.montecarlo.fix_settings', { defaultValue: 'Correct the highlighted settings first.' })
                  : undefined
            }
            icon={
              runMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )
            }
          >
            {runMut.isPending
              ? t('risk.montecarlo.running', { defaultValue: 'Running…' })
              : t('risk.montecarlo.run', { defaultValue: 'Run simulation' })}
          </Button>
        </div>
        <p className="mt-3 text-xs text-content-secondary" data-testid="mc-explainer">
          {t('risk.montecarlo.confidence_explainer', {
            defaultValue:
              'The confidence level is the share of simulated outcomes the reserve covers. At P{{p}}, {{p}} of every 100 runs cost no more than the figure; raising it gives a larger, safer reserve, lowering it a leaner one. The range spreads risks that have one cost or delay figure instead of an optimistic, likely and pessimistic estimate.',
            p: confidence ?? CONFIDENCE_MIN,
          })}
        </p>
        {settingsChanged && (
          <p className="mt-2 text-xs text-semantic-warning" role="status">
            {t('risk.montecarlo.settings_changed', {
              defaultValue: 'The settings differ from the last run. Run the simulation again to update the figures.',
            })}
          </p>
        )}
      </Card>

      {/* ── Last-run chips ────────────────────────────────────────── */}
      {result && (
        <Card className="p-4">
          <div className="flex items-center gap-2 mb-3">
            <TrendingUp size={14} className="text-content-tertiary" />
            <h3 className="oe-card-title">
              {t('risk.montecarlo.last_run', {
                defaultValue: 'Last run - {{risks}} risks, {{iterations}} iterations',
                risks: result.risk_count,
                iterations: result.iterations.toLocaleString(getNumberLocale()),
              })}
            </h3>
          </div>
          {result.risk_count > 0 && (
            <p className="-mt-1 mb-3 text-xs text-content-tertiary" data-testid="mc-ran-at">
              {t('risk.montecarlo.ran_at', {
                defaultValue: 'Planned to P{{p}}; single-figure risks spread −{{low}} % / +{{high}} %.',
                p: ranAt.confidence,
                low: ranAt.low,
                high: ranAt.high,
              })}
            </p>
          )}
          {result.risk_count > 0 && (result.point_estimate_risks ?? 0) > 0 && ranAt.low === 0 && ranAt.high === 0 && (
            <p className="mb-3 rounded-lg bg-semantic-warning-bg px-3 py-2 text-xs text-semantic-warning" data-testid="mc-point-warning">
              {t('risk.montecarlo.point_estimates_fixed', {
                defaultValue:
                  'Risks with a single figure: {{n}} of {{total}}. They do not vary, so P50, P80 and P95 can come out equal. Give them an optimistic and a pessimistic estimate, or set a range above.',
                n: result.point_estimate_risks,
                total: result.risk_count,
              })}
            </p>
          )}

          {result.risk_count === 0 ? (
            <EmptyState
              icon={<AlertTriangle size={24} strokeWidth={1.5} />}
              title={t('risk.montecarlo.no_risks', {
                defaultValue: 'No risks to simulate',
              })}
              description={t('risk.montecarlo.no_risks_desc', {
                defaultValue:
                  'Add risks to the register first; the simulation has nothing to sample.',
              })}
            />
          ) : (
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {showCostChips && (
                <>
                  <Chip
                    label={t('risk.montecarlo.target_cost', { defaultValue: 'P{{p}} Cost (plan)', p: ranAt.confidence })}
                    value={fmtCurrencyOrPlain(result.target_cost ?? result.p80_cost, currency)}
                    tone="info"
                  />
                  <Chip
                    label={t('risk.montecarlo.p50_cost', { defaultValue: 'P50 Cost' })}
                    value={fmtCurrencyOrPlain(result.p50_cost, currency)}
                    tone="success"
                  />
                  <Chip
                    label={t('risk.montecarlo.p80_cost', { defaultValue: 'P80 Cost' })}
                    value={fmtCurrencyOrPlain(result.p80_cost, currency)}
                    tone="warning"
                  />
                  <Chip
                    label={t('risk.montecarlo.p90_cost', { defaultValue: 'P90 Cost' })}
                    value={fmtCurrencyOrPlain(result.p90_cost ?? null, currency)}
                    tone="error"
                  />
                  <Chip
                    label={t('risk.montecarlo.p95_cost', { defaultValue: 'P95 Cost' })}
                    value={fmtCurrencyOrPlain(result.p95_cost, currency)}
                    tone="error"
                  />
                </>
              )}
              {showScheduleChips && (
                <>
                  <Chip
                    label={t('risk.montecarlo.target_schedule', {
                      defaultValue: 'P{{p}} Schedule (plan)',
                      p: ranAt.confidence,
                    })}
                    value={fmtDays(result.target_schedule_days ?? result.p80_schedule_days, t)}
                    tone="info"
                  />
                  <Chip
                    label={t('risk.montecarlo.p50_schedule', {
                      defaultValue: 'P50 Schedule',
                    })}
                    value={fmtDays(result.p50_schedule_days, t)}
                    tone="success"
                  />
                  <Chip
                    label={t('risk.montecarlo.p80_schedule', {
                      defaultValue: 'P80 Schedule',
                    })}
                    value={fmtDays(result.p80_schedule_days, t)}
                    tone="warning"
                  />
                  <Chip
                    label={t('risk.montecarlo.p90_schedule', { defaultValue: 'P90 Schedule' })}
                    value={fmtDays(result.p90_schedule_days ?? null, t)}
                    tone="error"
                  />
                  <Chip
                    label={t('risk.montecarlo.p95_schedule', {
                      defaultValue: 'P95 Schedule',
                    })}
                    value={fmtDays(result.p95_schedule_days, t)}
                    tone="error"
                  />
                </>
              )}
            </div>
          )}
        </Card>
      )}

      {/* ── Histogram ─────────────────────────────────────────────── */}
      {result && histogramData.length > 0 && (
        <Card className="p-4">
          <h3 className="oe-card-title mb-3">
            {t('risk.montecarlo.histogram', {
              defaultValue: 'Contingency distribution',
            })}
          </h3>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={histogramData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis
                dataKey="label"
                tick={{ fontSize: 10 }}
                interval={0}
                angle={-30}
                textAnchor="end"
                height={60}
              />
              <YAxis tick={{ fontSize: 10 }} />
              <Tooltip />
              <Bar dataKey="count" fill="#3b82f6" radius={[4, 4, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* ── Tornado ───────────────────────────────────────────────── */}
      {result && tornadoData.length > 0 && (
        <Card className="p-4">
          <h3 className="oe-card-title mb-3">
            {t('risk.montecarlo.tornado', {
              defaultValue: 'Top contributors (tornado)',
            })}
          </h3>
          <ResponsiveContainer width="100%" height={Math.max(200, tornadoData.length * 32)}>
            <BarChart data={tornadoData} layout="vertical">
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis type="number" tick={{ fontSize: 10 }} />
              <YAxis type="category" dataKey="code" tick={{ fontSize: 10 }} width={70} />
              <Tooltip
                formatter={(value) =>
                  fmtCurrencyOrPlain(typeof value === 'number' ? value : Number(value), currency)
                }
              />
              <Bar dataKey="contribution" fill="#f59e0b" radius={[0, 4, 4, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </Card>
      )}

      {/* ── Empty state when no run yet ────────────────────────────── */}
      {!result && !runMut.isPending && !last.isLoading && (
        <Card className="p-6">
          <EmptyState
            icon={<TrendingUp size={28} strokeWidth={1.5} />}
            title={t('risk.montecarlo.empty', {
              defaultValue: 'No simulation run yet',
            })}
            description={t('risk.montecarlo.empty_desc', {
              defaultValue:
                'Run a Monte Carlo simulation to model project contingency from your risk register. P50, P80 and P95 confidence bands tell you how much budget reserve to hold against cost and schedule risk.',
            })}
          />
        </Card>
      )}
    </div>
  );
}

/* ── Chip helper ───────────────────────────────────────────────────── */

interface ChipProps {
  label: string;
  value: string;
  tone: 'success' | 'warning' | 'error' | 'info';
}

function Chip({ label, value, tone }: ChipProps) {
  const toneCls: Record<ChipProps['tone'], string> = {
    success: 'bg-semantic-success-bg text-semantic-success',
    warning: 'bg-semantic-warning-bg text-semantic-warning',
    error: 'bg-semantic-error-bg text-semantic-error',
    info: 'bg-semantic-info-bg text-semantic-info ring-1 ring-semantic-info/30',
  };
  return (
    <div className={`rounded-lg px-3 py-2 ${toneCls[tone]}`}>
      <p className="text-2xs uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-0.5 text-base font-semibold tabular-nums">{value}</p>
    </div>
  );
}

export default MonteCarloTab;
