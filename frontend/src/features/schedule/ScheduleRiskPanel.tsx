// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
//
// Monte-Carlo schedule risk panel (T2.1). Drives
// POST /v1/schedule-advanced/{scheduleId}/schedule-risk and renders:
//   - a run form (iterations / correlation / target confidence / optimistic
//     and pessimistic bands, plus optional cost inputs that unlock the JCL)
//   - finish-day percentile chips (P5..P95) + contingency / convergence
//   - the S-curve (cumulative distribution, recharts AreaChart)
//   - the finish-day histogram (recharts BarChart)
//   - the duration tornado (per-activity swing low/high bars)
//   - the criticality-index table
//   - the Joint Confidence Level block (only when cost inputs are supplied):
//     JCL %, prob on-time, prob on-budget and a finish-vs-cost scatter cloud
//
// Durations are work-days; the schedule has no native currency here so cost
// figures render as plain locale-grouped numbers.

import { useMemo, useState } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import {
  Area,
  AreaChart,
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
  ZAxis,
} from 'recharts';
import { Play, Loader2, TrendingUp, Activity, Target, AlertTriangle } from 'lucide-react';

import { Button, Card, Badge, EmptyState } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import { getErrorMessage } from '@/shared/lib/api';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import {
  scheduleRisk,
  type ScheduleRisk,
  type ScheduleRiskRequestBody,
} from '@/features/schedule-advanced/api';

interface ScheduleRiskPanelProps {
  scheduleId: string;
  /** Optional id -> display name map so the tornado / criticality show names. */
  activitiesById?: Record<string, string>;
}

const CRITICALITY_TOP_N = 12;
const TORNADO_TOP_N = 10;

const inputCls =
  'h-9 w-full rounded-lg border border-border bg-surface-primary px-3 text-sm focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue';
const labelCls =
  'block text-2xs font-medium uppercase tracking-wide text-content-secondary mb-1';

function fmtNum(n: number | null | undefined, digits = 0): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '-';
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      maximumFractionDigits: digits,
      minimumFractionDigits: 0,
    }).format(n);
  } catch {
    return String(Math.round(n));
  }
}

/**
 * Coerce a recharts tooltip value (``number | string | Array<...> | undefined``)
 * to a finite number. recharts types the formatter ``value`` loosely, so this
 * keeps the call sites tidy and never yields ``NaN`` downstream.
 */
function toNumLoose(value: unknown): number {
  const raw = Array.isArray(value) ? value[0] : value;
  const n = typeof raw === 'number' ? raw : Number(raw);
  return Number.isFinite(n) ? n : NaN;
}

function fmtPct(fraction: number | null | undefined): string {
  if (fraction === null || fraction === undefined || !Number.isFinite(fraction)) return '-';
  return `${Math.round(fraction * 100)}%`;
}

/** Defaults requested by the spec: 2000 / 0 / 80 / 15 / 25. */
interface RiskForm {
  iterations: number;
  correlation: number; // 0..0.95
  target_confidence: number; // 50..99
  optimistic_pct: number;
  pessimistic_pct: number;
  withCost: boolean;
  base_cost: number;
  cost_target: number | '';
}

const DEFAULT_FORM: RiskForm = {
  iterations: 2000,
  correlation: 0,
  target_confidence: 80,
  optimistic_pct: 15,
  pessimistic_pct: 25,
  withCost: false,
  base_cost: 0,
  cost_target: '',
};

export function ScheduleRiskPanel({ scheduleId, activitiesById }: ScheduleRiskPanelProps) {
  const { t } = useTranslation();
  const addToast = useToastStore((s) => s.addToast);

  const [form, setForm] = useState<RiskForm>(DEFAULT_FORM);
  const [result, setResult] = useState<ScheduleRisk | null>(null);

  const nameFor = useMemo(
    () => (id: string) => activitiesById?.[id] ?? id,
    [activitiesById],
  );

  const runMut = useMutation({
    mutationFn: () => {
      const body: ScheduleRiskRequestBody = {
        iterations: form.iterations,
        correlation: form.correlation,
        target_confidence: form.target_confidence,
        optimistic_pct: form.optimistic_pct,
        pessimistic_pct: form.pessimistic_pct,
      };
      if (form.withCost && form.base_cost > 0) {
        body.cost_inputs = {
          base_cost: form.base_cost,
          ...(form.cost_target !== '' && Number.isFinite(form.cost_target)
            ? { cost_target: Number(form.cost_target) }
            : {}),
        };
      }
      return scheduleRisk(scheduleId, body);
    },
    onSuccess: (data) => {
      setResult(data);
      addToast({
        type: 'success',
        title: t('schedule.risk.run_done', { defaultValue: 'Simulation complete' }),
        message: t('schedule.risk.run_done_detail', {
          defaultValue: '{{iterations}} iterations - {{status}}',
          iterations: data.iterations.toLocaleString(getNumberLocale()),
          status: data.convergence_status || '-',
        }),
      });
    },
    onError: (e) => {
      addToast({
        type: 'error',
        title: t('common.error', { defaultValue: 'Error' }),
        message: getErrorMessage(e),
      });
    },
  });

  /* ── Derived chart shapes ─────────────────────────────────────────── */

  const cdfData = useMemo(() => {
    if (!result) return [];
    return result.cdf.map((p) => ({ x: p.x, prob: p.cumulative_prob * 100 }));
  }, [result]);

  const histData = useMemo(() => {
    if (!result) return [];
    return result.histogram.map((h) => ({
      label: fmtNum((h.bin_start + h.bin_end) / 2, 0),
      count: h.count,
    }));
  }, [result]);

  // Tornado: order by absolute swing magnitude, widest first.
  const tornadoData = useMemo(() => {
    if (!result) return [];
    return [...result.drivers]
      .map((d) => ({
        id: d.activity_id,
        name: nameFor(d.activity_id),
        low: d.swing_low,
        high: d.swing_high,
        span: Math.abs(d.swing_high) + Math.abs(d.swing_low),
        rank: d.rank_correlation,
      }))
      .sort((a, b) => b.span - a.span)
      .slice(0, TORNADO_TOP_N);
  }, [result, nameFor]);

  const criticality = useMemo(() => {
    if (!result) return [];
    return [...result.criticality]
      .sort((a, b) => b.criticality_index - a.criticality_index)
      .slice(0, CRITICALITY_TOP_N);
  }, [result]);

  const scatterData = useMemo(() => {
    if (!result?.joint_confidence) return [];
    return result.joint_confidence.scatter.map((p) => ({ finish: p.finish, cost: p.cost }));
  }, [result]);

  const pct = result?.percentiles ?? {};

  return (
    <div className="space-y-4" data-testid="schedule-risk-panel">
      {/* ── Run form ──────────────────────────────────────────────── */}
      <Card padding="md">
        <div className="mb-3 flex items-center gap-2">
          <Activity size={16} className="text-content-secondary" />
          <h3 className="text-sm font-semibold text-content-primary">
            {t('schedule.risk.title', { defaultValue: 'Monte-Carlo schedule risk' })}
          </h3>
        </div>

        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
          <div>
            <label htmlFor="risk-iters" className={labelCls}>
              {t('schedule.risk.iterations', { defaultValue: 'Iterations' })}
            </label>
            <input
              id="risk-iters"
              type="number"
              min={100}
              max={100000}
              step={500}
              value={form.iterations}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  iterations: clampInt(e.target.value, 100, 100000, f.iterations),
                }))
              }
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="risk-corr" className={labelCls}>
              {t('schedule.risk.correlation', { defaultValue: 'Correlation' })}
            </label>
            <input
              id="risk-corr"
              type="number"
              min={0}
              max={0.95}
              step={0.05}
              value={form.correlation}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  correlation: clampFloat(e.target.value, 0, 0.95, f.correlation),
                }))
              }
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="risk-conf" className={labelCls}>
              {t('schedule.risk.target_confidence', { defaultValue: 'Target confidence %' })}
            </label>
            <input
              id="risk-conf"
              type="number"
              min={50}
              max={99}
              step={1}
              value={form.target_confidence}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  target_confidence: clampInt(e.target.value, 50, 99, f.target_confidence),
                }))
              }
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="risk-opt" className={labelCls}>
              {t('schedule.risk.optimistic', { defaultValue: 'Optimistic -%' })}
            </label>
            <input
              id="risk-opt"
              type="number"
              min={0}
              max={100}
              step={1}
              value={form.optimistic_pct}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  optimistic_pct: clampFloat(e.target.value, 0, 100, f.optimistic_pct),
                }))
              }
              className={inputCls}
            />
          </div>
          <div>
            <label htmlFor="risk-pess" className={labelCls}>
              {t('schedule.risk.pessimistic', { defaultValue: 'Pessimistic +%' })}
            </label>
            <input
              id="risk-pess"
              type="number"
              min={0}
              max={300}
              step={1}
              value={form.pessimistic_pct}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  pessimistic_pct: clampFloat(e.target.value, 0, 300, f.pessimistic_pct),
                }))
              }
              className={inputCls}
            />
          </div>
        </div>

        {/* Optional cost inputs (unlock the Joint Confidence Level) */}
        <div className="mt-3 rounded-lg border border-border-light bg-surface-secondary/30 p-3">
          <label className="flex cursor-pointer items-center gap-2 text-sm text-content-secondary">
            <input
              type="checkbox"
              checked={form.withCost}
              onChange={(e) => setForm((f) => ({ ...f, withCost: e.target.checked }))}
              className="h-4 w-4 rounded border-border accent-oe-blue"
            />
            {t('schedule.risk.with_cost', {
              defaultValue: 'Add cost inputs for a Joint Confidence Level (cost + schedule)',
            })}
          </label>
          {form.withCost && (
            <div className="mt-3 grid grid-cols-2 gap-3 sm:grid-cols-3">
              <div>
                <label htmlFor="risk-base-cost" className={labelCls}>
                  {t('schedule.risk.base_cost', { defaultValue: 'Base cost' })}
                </label>
                <input
                  id="risk-base-cost"
                  type="number"
                  min={0}
                  step={1000}
                  value={form.base_cost}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      base_cost: clampFloat(e.target.value, 0, Number.MAX_SAFE_INTEGER, f.base_cost),
                    }))
                  }
                  className={inputCls}
                />
              </div>
              <div>
                <label htmlFor="risk-cost-target" className={labelCls}>
                  {t('schedule.risk.cost_target', { defaultValue: 'Cost target (optional)' })}
                </label>
                <input
                  id="risk-cost-target"
                  type="number"
                  min={0}
                  step={1000}
                  value={form.cost_target}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      cost_target: e.target.value === '' ? '' : Number(e.target.value),
                    }))
                  }
                  className={inputCls}
                />
              </div>
            </div>
          )}
          {form.withCost && form.base_cost <= 0 && (
            <p className="mt-2 flex items-center gap-1.5 text-2xs text-semantic-warning">
              <AlertTriangle size={12} />
              {t('schedule.risk.base_cost_required', {
                defaultValue: 'Enter a base cost above zero to include the cost side.',
              })}
            </p>
          )}
        </div>

        <div className="mt-3 flex items-center gap-3">
          <Button
            variant="primary"
            onClick={() => runMut.mutate()}
            disabled={runMut.isPending || !scheduleId}
            icon={
              runMut.isPending ? (
                <Loader2 size={16} className="animate-spin" />
              ) : (
                <Play size={16} />
              )
            }
          >
            {runMut.isPending
              ? t('schedule.risk.running', { defaultValue: 'Running...' })
              : t('schedule.risk.run', { defaultValue: 'Run simulation' })}
          </Button>
          <p className="text-2xs text-content-tertiary">
            {t('schedule.risk.run_hint', {
              defaultValue: 'Latin-Hypercube sampling over activity durations. Read-only.',
            })}
          </p>
        </div>
      </Card>

      {/* ── Empty state ───────────────────────────────────────────── */}
      {!result && !runMut.isPending && (
        <Card padding="md">
          <EmptyState
            icon={<TrendingUp size={28} strokeWidth={1.5} />}
            title={t('schedule.risk.empty', { defaultValue: 'No simulation run yet' })}
            description={t('schedule.risk.empty_desc', {
              defaultValue:
                'Run a Monte-Carlo simulation to turn your activity durations into a finish-date probability distribution. The P5-P95 band, S-curve, contingency and criticality index tell you how much schedule reserve to hold and which activities drive the risk.',
            })}
          />
        </Card>
      )}

      {result && (
        <>
          {/* ── Percentile + summary chips ──────────────────────────── */}
          <Card padding="md">
            <div className="mb-3 flex items-center gap-2">
              <Target size={16} className="text-content-secondary" />
              <h3 className="text-sm font-semibold text-content-primary">
                {t('schedule.risk.finish_dist', {
                  defaultValue: 'Finish-day distribution (work-days)',
                })}
              </h3>
              <ConvergenceBadge status={result.convergence_status} margin={result.convergence_margin_pct} />
            </div>
            <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <Chip label="P5" value={fmtNum(pct.p5)} tone="success" />
              <Chip label="P50" value={fmtNum(pct.p50)} tone="neutral" />
              <Chip label="P80" value={fmtNum(pct.p80)} tone="warning" />
              <Chip label="P95" value={fmtNum(pct.p95)} tone="error" />
              <Chip
                label={t('schedule.risk.deterministic', { defaultValue: 'Deterministic' })}
                value={fmtNum(result.deterministic_finish)}
                tone="neutral"
              />
              <Chip
                label={t('schedule.risk.mean', { defaultValue: 'Mean +/- SD' })}
                value={`${fmtNum(result.mean)} +/- ${fmtNum(result.std_dev, 1)}`}
                tone="neutral"
              />
            </div>
            <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
              <MiniStat
                label={t('schedule.risk.recommended', {
                  defaultValue: 'Recommended (P{{c}})',
                  c: result.target_confidence,
                })}
                value={fmtNum(result.recommended_finish)}
              />
              <MiniStat
                label={t('schedule.risk.contingency', { defaultValue: 'Contingency (days)' })}
                value={`${fmtNum(result.contingency)} (${fmtNum(result.contingency_pct, 1)}%)`}
              />
              <MiniStat
                label={t('schedule.risk.prob_within', {
                  defaultValue: 'P(<= deterministic)',
                })}
                value={fmtPct(result.prob_within_deterministic)}
              />
              <MiniStat
                label={t('schedule.risk.cv', { defaultValue: 'Coefficient of variation' })}
                value={`${fmtNum(result.cv_pct, 1)}%`}
              />
            </dl>
          </Card>

          {/* ── S-curve (CDF) ───────────────────────────────────────── */}
          {cdfData.length > 0 && (
            <Card padding="md">
              <h3 className="mb-3 text-sm font-semibold text-content-primary">
                {t('schedule.risk.scurve', { defaultValue: 'S-curve (cumulative probability)' })}
              </h3>
              <ResponsiveContainer width="100%" height={240}>
                <AreaChart data={cdfData} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
                  <defs>
                    <linearGradient id="scurveFill" x1="0" y1="0" x2="0" y2="1">
                      <stop offset="0%" stopColor="#3b82f6" stopOpacity={0.4} />
                      <stop offset="100%" stopColor="#3b82f6" stopOpacity={0.02} />
                    </linearGradient>
                  </defs>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis
                    dataKey="x"
                    type="number"
                    domain={['dataMin', 'dataMax']}
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v) => fmtNum(Number(v))}
                  />
                  <YAxis
                    domain={[0, 100]}
                    tick={{ fontSize: 10 }}
                    tickFormatter={(v) => `${v}%`}
                  />
                  <Tooltip
                    formatter={(value) => [`${fmtNum(toNumLoose(value), 1)}%`, t('schedule.risk.cum_prob', { defaultValue: 'Cumulative' })]}
                    labelFormatter={(label) => `${t('schedule.risk.finish_day', { defaultValue: 'Finish day' })} ${fmtNum(toNumLoose(label))}`}
                  />
                  {Number.isFinite(result.recommended_finish) && (
                    <ReferenceLine
                      x={result.recommended_finish}
                      stroke="#f59e0b"
                      strokeDasharray="4 4"
                      label={{ value: `P${result.target_confidence}`, fontSize: 10, fill: '#b45309' }}
                    />
                  )}
                  <Area
                    type="monotone"
                    dataKey="prob"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    fill="url(#scurveFill)"
                  />
                </AreaChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* ── Histogram ───────────────────────────────────────────── */}
          {histData.length > 0 && (
            <Card padding="md">
              <h3 className="mb-3 text-sm font-semibold text-content-primary">
                {t('schedule.risk.histogram', { defaultValue: 'Finish-day histogram' })}
              </h3>
              <ResponsiveContainer width="100%" height={220}>
                <BarChart data={histData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis
                    dataKey="label"
                    tick={{ fontSize: 10 }}
                    interval={Math.max(0, Math.floor(histData.length / 12))}
                    angle={-30}
                    textAnchor="end"
                    height={54}
                  />
                  <YAxis tick={{ fontSize: 10 }} allowDecimals={false} />
                  <Tooltip
                    labelFormatter={(label) => `${t('schedule.risk.finish_day', { defaultValue: 'Finish day' })} ~${label}`}
                  />
                  <Bar dataKey="count" fill="#6366f1" radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* ── Tornado ─────────────────────────────────────────────── */}
          {tornadoData.length > 0 && (
            <Card padding="md">
              <h3 className="mb-1 text-sm font-semibold text-content-primary">
                {t('schedule.risk.tornado', { defaultValue: 'Duration sensitivity (tornado)' })}
              </h3>
              <p className="mb-3 text-2xs text-content-tertiary">
                {t('schedule.risk.tornado_hint', {
                  defaultValue:
                    'Each bar is an activity\'s swing on the project finish between its P10 and P90 duration.',
                })}
              </p>
              <ResponsiveContainer width="100%" height={Math.max(180, tornadoData.length * 30)}>
                <BarChart data={tornadoData} layout="vertical" stackOffset="sign" margin={{ left: 8, right: 12 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                  <XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={(v) => fmtNum(Number(v), 1)} />
                  <YAxis
                    type="category"
                    dataKey="name"
                    tick={{ fontSize: 10 }}
                    width={130}
                    interval={0}
                  />
                  <Tooltip
                    formatter={(value, key) => [
                      `${fmtNum(toNumLoose(value), 1)} ${t('schedule.risk.days_short', { defaultValue: 'd' })}`,
                      key === 'low'
                        ? t('schedule.risk.swing_low', { defaultValue: 'Swing low' })
                        : t('schedule.risk.swing_high', { defaultValue: 'Swing high' }),
                    ]}
                  />
                  <ReferenceLine x={0} stroke="#94a3b8" />
                  <Bar dataKey="low" stackId="swing" fill="#22c55e" radius={[3, 0, 0, 3]} />
                  <Bar dataKey="high" stackId="swing" fill="#ef4444" radius={[0, 3, 3, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </Card>
          )}

          {/* ── Criticality index ───────────────────────────────────── */}
          {criticality.length > 0 && (
            <Card padding="none">
              <div className="border-b border-border-light px-4 py-3">
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('schedule.risk.criticality', { defaultValue: 'Criticality index' })}
                </h3>
              </div>
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead className="bg-surface-secondary text-2xs uppercase tracking-wide text-content-tertiary">
                    <tr>
                      <th className="px-4 py-2 text-left">{t('schedule.risk.activity', { defaultValue: 'Activity' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule.risk.ci', { defaultValue: 'Criticality' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule.risk.cruciality', { defaultValue: 'Cruciality' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule.risk.sensitivity', { defaultValue: 'Sensitivity' })}</th>
                      <th className="px-4 py-2 text-right">{t('schedule.risk.mean_dur', { defaultValue: 'Mean dur. (d)' })}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {criticality.map((c) => (
                      <tr key={c.activity_id} className="border-t border-border-light">
                        <td className="px-4 py-2">
                          <span className="block max-w-xs truncate" title={c.activity_id}>
                            {nameFor(c.activity_id)}
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right">
                          <span className="inline-flex items-center gap-2">
                            <span className="hidden h-1.5 w-16 overflow-hidden rounded-full bg-surface-secondary sm:inline-block">
                              <span
                                className="block h-full rounded-full bg-oe-blue"
                                style={{ width: `${Math.round(Math.max(0, Math.min(1, c.criticality_index)) * 100)}%` }}
                              />
                            </span>
                            <span className="font-mono tabular-nums">{fmtPct(c.criticality_index)}</span>
                          </span>
                        </td>
                        <td className="px-4 py-2 text-right font-mono tabular-nums">{fmtNum(c.cruciality, 2)}</td>
                        <td className="px-4 py-2 text-right font-mono tabular-nums">{fmtNum(c.duration_sensitivity, 2)}</td>
                        <td className="px-4 py-2 text-right font-mono tabular-nums">{fmtNum(c.mean_duration, 1)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          )}

          {/* ── Joint Confidence Level ──────────────────────────────── */}
          {result.joint_confidence && (
            <Card padding="md" data-testid="risk-jcl">
              <div className="mb-3 flex items-center gap-2">
                <Target size={16} className="text-content-secondary" />
                <h3 className="text-sm font-semibold text-content-primary">
                  {t('schedule.risk.jcl', { defaultValue: 'Joint Confidence Level' })}
                </h3>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                <Chip
                  label={t('schedule.risk.jcl_value', { defaultValue: 'JCL' })}
                  value={fmtPct(result.joint_confidence.jcl)}
                  tone={
                    result.joint_confidence.jcl >= 0.7
                      ? 'success'
                      : result.joint_confidence.jcl >= 0.5
                        ? 'warning'
                        : 'error'
                  }
                />
                <Chip
                  label={t('schedule.risk.prob_on_time', { defaultValue: 'P(on time)' })}
                  value={fmtPct(result.joint_confidence.prob_on_time)}
                  tone="neutral"
                />
                <Chip
                  label={t('schedule.risk.prob_on_budget', { defaultValue: 'P(on budget)' })}
                  value={fmtPct(result.joint_confidence.prob_on_budget)}
                  tone="neutral"
                />
              </div>
              <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
                <MiniStat
                  label={t('schedule.risk.target_finish', { defaultValue: 'Target finish (d)' })}
                  value={fmtNum(result.joint_confidence.target_finish)}
                />
                <MiniStat
                  label={t('schedule.risk.target_cost', { defaultValue: 'Target cost' })}
                  value={fmtNum(result.joint_confidence.target_cost)}
                />
                <MiniStat
                  label={t('schedule.risk.cost_mean', { defaultValue: 'Mean cost' })}
                  value={fmtNum(result.joint_confidence.cost_mean)}
                />
                <MiniStat
                  label={t('schedule.risk.cost_p80', { defaultValue: 'Cost P80' })}
                  value={fmtNum(result.joint_confidence.cost_percentiles?.p80)}
                />
              </dl>
              {scatterData.length > 0 && (
                <div className="mt-4">
                  <p className="mb-2 text-2xs uppercase tracking-wide text-content-tertiary">
                    {t('schedule.risk.scatter', { defaultValue: 'Finish vs cost (sampled draws)' })}
                  </p>
                  <ResponsiveContainer width="100%" height={260}>
                    <ScatterChart margin={{ top: 8, right: 12, bottom: 8, left: 4 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
                      <XAxis
                        type="number"
                        dataKey="finish"
                        name={t('schedule.risk.finish_day', { defaultValue: 'Finish day' })}
                        tick={{ fontSize: 10 }}
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={(v) => fmtNum(Number(v))}
                      />
                      <YAxis
                        type="number"
                        dataKey="cost"
                        name={t('schedule.risk.cost', { defaultValue: 'Cost' })}
                        tick={{ fontSize: 10 }}
                        domain={['dataMin', 'dataMax']}
                        tickFormatter={(v) => fmtNum(Number(v))}
                        width={70}
                      />
                      <ZAxis range={[14, 14]} />
                      <Tooltip
                        cursor={{ strokeDasharray: '3 3' }}
                        formatter={(value) => fmtNum(toNumLoose(value))}
                      />
                      <ReferenceLine
                        x={result.joint_confidence.target_finish}
                        stroke="#f59e0b"
                        strokeDasharray="4 4"
                      />
                      <ReferenceLine
                        y={result.joint_confidence.target_cost}
                        stroke="#f59e0b"
                        strokeDasharray="4 4"
                      />
                      <Scatter data={scatterData} fill="#6366f1" fillOpacity={0.45}>
                        {scatterData.map((p, i) => {
                          const jc = result.joint_confidence!;
                          const onBoth = p.finish <= jc.target_finish && p.cost <= jc.target_cost;
                          return (
                            <Cell key={i} fill={onBoth ? '#22c55e' : '#94a3b8'} fillOpacity={onBoth ? 0.6 : 0.35} />
                          );
                        })}
                      </Scatter>
                    </ScatterChart>
                  </ResponsiveContainer>
                  <p className="mt-1 text-2xs text-content-tertiary">
                    {t('schedule.risk.scatter_legend', {
                      defaultValue:
                        'Green = draws that hit both the finish and cost targets; the dashed lines mark the targets.',
                    })}
                  </p>
                </div>
              )}
            </Card>
          )}
        </>
      )}
    </div>
  );
}

/* ── helpers ─────────────────────────────────────────────────────────── */

function clampInt(raw: string, min: number, max: number, fallback: number): number {
  const v = parseInt(raw, 10);
  if (!Number.isFinite(v)) return fallback;
  return Math.max(min, Math.min(max, v));
}

function clampFloat(raw: string, min: number, max: number, fallback: number): number {
  const v = parseFloat(raw);
  if (!Number.isFinite(v)) return fallback;
  return Math.max(min, Math.min(max, v));
}

interface ChipProps {
  label: string;
  value: string;
  tone: 'success' | 'warning' | 'error' | 'neutral';
}

function Chip({ label, value, tone }: ChipProps) {
  const toneCls: Record<ChipProps['tone'], string> = {
    success: 'bg-green-50 dark:bg-green-950/30 text-semantic-success',
    warning: 'bg-amber-50 dark:bg-amber-950/30 text-amber-700 dark:text-amber-300',
    error: 'bg-red-50 dark:bg-red-950/30 text-semantic-error',
    neutral: 'bg-surface-secondary/60 text-content-primary',
  };
  return (
    <div className={`rounded-lg px-3 py-2 ${toneCls[tone]}`}>
      <p className="text-2xs uppercase tracking-wide opacity-80">{label}</p>
      <p className="mt-0.5 text-base font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-2xs uppercase tracking-wide text-content-tertiary">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium tabular-nums text-content-primary">{value}</dd>
    </div>
  );
}

function ConvergenceBadge({ status, margin }: { status: string; margin: number }) {
  const { t } = useTranslation();
  if (!status) return null;
  const converged = status.toLowerCase() === 'converged';
  return (
    <Badge variant={converged ? 'success' : 'warning'} dot>
      {converged
        ? t('schedule.risk.converged', {
            defaultValue: 'Converged (+/-{{m}}%)',
            m: fmtNum(margin, 2),
          })
        : t('schedule.risk.not_converged', {
            defaultValue: 'Not converged (+/-{{m}}%)',
            m: fmtNum(margin, 2),
          })}
    </Badge>
  );
}

export default ScheduleRiskPanel;
