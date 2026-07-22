// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Physical Progress page.
 *
 * Surfaces the progress-tracking analytics module: the actual-vs-planned
 * S-curve, per-period completion deltas with a running cumulative percent, and
 * a design-vs-earned quantity variance table with a project rollup. This is
 * PHYSICAL progress (percent complete, installed quantity), distinct from the
 * cost / EVM 5D surface which reads the same field entries in money terms.
 *
 * Charting is a dependency-free inline SVG so the page adds no new library.
 * Quantity figures arrive as Decimal strings and are formatted at the edge,
 * never coerced into money/quantity math (only a parseFloat for a bar width).
 */

import { type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  Activity,
  Inbox,
  Layers,
  ListChecks,
  Ruler,
  Target,
  TrendingDown,
  TrendingUp,
} from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import {
  Badge,
  Breadcrumb,
  Card,
  DismissibleInfo,
  EmptyState,
  PageHeader,
  RecoveryCard,
  SkeletonTable,
  StatCard,
} from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import {
  getProgressCumulative,
  getProgressSCurve,
  getQuantityVariance,
  type PositionQuantityVarianceItem,
  type SCurvePoint,
} from './api';

interface ProjectLite {
  id: string;
}

/* ── Formatting helpers ─────────────────────────────────────────────────── */

/** Format a plain float percentage (0-100). Returns "-" when absent. */
function fmtPct(value: number | null | undefined, frac = 1): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${value.toFixed(frac)}%`;
}

/** Format a Decimal-string (or number) quantity locale-aware. Returns "-" when absent. */
function fmtQty(value: string | number | null | undefined, frac = 2): string {
  if (value == null) return '-';
  const n = typeof value === 'string' ? parseFloat(value) : value;
  if (!Number.isFinite(n)) return '-';
  return n.toLocaleString(undefined, { maximumFractionDigits: frac });
}

/** Format a Decimal-string percentage. Returns "-" when null/unparseable. */
function fmtPctStr(value: string | null | undefined, frac = 1): string {
  if (value == null) return '-';
  const n = parseFloat(value);
  if (!Number.isFinite(n)) return '-';
  return `${n.toFixed(frac)}%`;
}

/** Clamp a parsed percent into [0, 100] for a progress-bar width. */
function clampPct(n: number): number {
  if (!Number.isFinite(n)) return 0;
  return Math.max(0, Math.min(100, n));
}

/* ── Section state wrapper (loading / error / empty) ────────────────────── */

function SectionState({
  loading,
  error,
  onRetry,
  empty,
  emptyIcon,
  emptyTitle,
  emptyDescription,
  children,
}: {
  loading: boolean;
  error: unknown;
  onRetry: () => void;
  empty: boolean;
  emptyIcon: ReactNode;
  emptyTitle: string;
  emptyDescription: string;
  children: ReactNode;
}) {
  if (loading) return <SkeletonTable rows={4} columns={4} />;
  // RecoveryCard renders the friendly access-required state on 403 and a retry
  // on other errors - this is what covers the progress.read permission gate on
  // the quantity-variance endpoint.
  if (error) return <RecoveryCard error={error} onRetry={onRetry} />;
  if (empty) return <EmptyState icon={emptyIcon} title={emptyTitle} description={emptyDescription} />;
  return <>{children}</>;
}

/* ── S-curve chart (dependency-free inline SVG) ─────────────────────────── */

function SCurveChart({ points }: { points: SCurvePoint[] }) {
  const { t } = useTranslation();

  const W = 760;
  const H = 260;
  const padL = 40;
  const padR = 16;
  const padT = 16;
  const padB = 34;
  const innerW = W - padL - padR;
  const innerH = H - padT - padB;
  const n = points.length;

  const xAt = (i: number): number =>
    n <= 1 ? padL + innerW / 2 : padL + (i / (n - 1)) * innerW;
  const yAt = (pct: number): number =>
    padT + (1 - clampPct(pct) / 100) * innerH;

  const gridYs = [0, 25, 50, 75, 100];
  const bottom = padT + innerH;

  const actualPoints = points.map((p, i) => `${xAt(i)},${yAt(p.actual_cumulative_pct)}`).join(' ');
  const planned = points
    .map((p, i) => ({ p, i }))
    .filter((e) => e.p.planned_cumulative_pct != null);
  const plannedPoints = planned
    .map((e) => `${xAt(e.i)},${yAt(e.p.planned_cumulative_pct as number)}`)
    .join(' ');
  const areaPoints = `${padL},${bottom} ${actualPoints} ${xAt(n - 1)},${bottom}`;

  // Cap the count of x-axis labels so dense period sets stay legible.
  const maxLabels = 7;
  const step = n <= maxLabels ? 1 : Math.ceil(n / maxLabels);

  return (
    <div className="space-y-3">
      {/* Legend */}
      <div className="flex flex-wrap items-center gap-4 text-xs text-content-secondary">
        <span className="inline-flex items-center gap-1.5">
          <svg width="20" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="20" y2="4" stroke="currentColor" className="text-oe-blue" strokeWidth="2.5" strokeLinecap="round" />
          </svg>
          {t('progress.series_actual', { defaultValue: 'Actual' })}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <svg width="20" height="8" aria-hidden="true">
            <line x1="0" y1="4" x2="20" y2="4" stroke="currentColor" className="text-content-tertiary" strokeWidth="2" strokeDasharray="4 3" />
          </svg>
          {t('progress.series_planned', { defaultValue: 'Planned' })}
        </span>
      </div>

      <div className="w-full overflow-x-auto">
        <svg
          viewBox={`0 0 ${W} ${H}`}
          className="w-full"
          style={{ minWidth: 480 }}
          role="img"
          aria-label={t('progress.s_curve_aria', {
            defaultValue: 'Actual versus planned cumulative progress over periods',
          })}
        >
          {/* Grid + y labels */}
          {gridYs.map((g) => (
            <g key={g}>
              <line
                x1={padL}
                y1={yAt(g)}
                x2={W - padR}
                y2={yAt(g)}
                stroke="currentColor"
                className="text-border-light"
                strokeWidth={0.5}
                strokeDasharray={g === 0 ? undefined : '4 4'}
              />
              <text
                x={padL - 8}
                y={yAt(g) + 3}
                textAnchor="end"
                className="fill-content-tertiary"
                fontSize={10}
                fontFamily="system-ui"
              >
                {g}%
              </text>
            </g>
          ))}

          {/* Area under the actual line */}
          {n >= 2 && (
            <polygon points={areaPoints} fill="currentColor" className="text-oe-blue" fillOpacity={0.08} />
          )}

          {/* Planned line (dashed, only the points that carry a plan) */}
          {planned.length >= 2 && (
            <polyline
              points={plannedPoints}
              fill="none"
              stroke="currentColor"
              className="text-content-tertiary"
              strokeWidth={1.75}
              strokeDasharray="5 4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Actual line (solid) */}
          {n >= 2 && (
            <polyline
              points={actualPoints}
              fill="none"
              stroke="currentColor"
              className="text-oe-blue"
              strokeWidth={2.5}
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          )}

          {/* Markers */}
          {points.map((p, i) => (
            <circle
              key={`actual-${i}`}
              cx={xAt(i)}
              cy={yAt(p.actual_cumulative_pct)}
              r={2.75}
              fill="currentColor"
              className="text-oe-blue"
            />
          ))}
          {planned.map((e) => (
            <circle
              key={`planned-${e.i}`}
              cx={xAt(e.i)}
              cy={yAt(e.p.planned_cumulative_pct as number)}
              r={2.25}
              fill="currentColor"
              className="text-content-tertiary"
            />
          ))}

          {/* X labels */}
          {points.map((p, i) =>
            i % step === 0 || i === n - 1 ? (
              <text
                key={`x-${i}`}
                x={xAt(i)}
                y={bottom + 20}
                textAnchor="middle"
                className="fill-content-tertiary"
                fontSize={10}
                fontFamily="system-ui"
              >
                {p.period_label}
              </text>
            ) : null,
          )}
        </svg>
      </div>
    </div>
  );
}

/* ── Status badge ───────────────────────────────────────────────────────── */

function StatusBadge({ status }: { status: string }) {
  const { t } = useTranslation();
  if (status === 'over_run') {
    return <Badge variant="warning">{t('progress.status_over_run', { defaultValue: 'Over-run' })}</Badge>;
  }
  if (status === 'under_run') {
    return <Badge variant="neutral">{t('progress.status_under_run', { defaultValue: 'Under-run' })}</Badge>;
  }
  return <Badge variant="success">{t('progress.status_on_target', { defaultValue: 'On target' })}</Badge>;
}

/* ── Variance row ───────────────────────────────────────────────────────── */

function VarianceRow({ item }: { item: PositionQuantityVarianceItem }) {
  const pc = clampPct(parseFloat(item.percent_complete));
  const varianceTone = item.is_over_run
    ? 'text-amber-600 dark:text-amber-400'
    : item.is_under_run
      ? 'text-content-secondary'
      : 'text-content-primary';
  return (
    <tr className="border-t border-border-light hover:bg-surface-secondary/40">
      <td className="px-3 py-2 font-medium text-content-primary tabular-nums whitespace-nowrap">
        {item.ordinal || '-'}
      </td>
      <td className="px-3 py-2 text-content-secondary">
        <span className="line-clamp-2">{item.description || '-'}</span>
      </td>
      <td className="px-3 py-2 text-content-tertiary whitespace-nowrap">{item.unit || '-'}</td>
      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtQty(item.design_quantity)}</td>
      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">{fmtQty(item.earned_quantity)}</td>
      <td className="px-3 py-2">
        <div className="flex items-center justify-end gap-2">
          <div className="h-1.5 w-16 overflow-hidden rounded-full bg-surface-secondary">
            <div className="h-full rounded-full bg-oe-blue" style={{ width: `${pc}%` }} />
          </div>
          <span className="tabular-nums text-xs text-content-secondary">{fmtPctStr(item.percent_complete)}</span>
        </div>
      </td>
      <td className={`px-3 py-2 text-right tabular-nums whitespace-nowrap ${varianceTone}`}>
        {fmtQty(item.variance)}
      </td>
      <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap text-content-tertiary">
        {fmtPctStr(item.variance_percent)}
      </td>
      <td className="px-3 py-2 whitespace-nowrap">
        <StatusBadge status={item.status} />
      </td>
    </tr>
  );
}

/* ── Page ───────────────────────────────────────────────────────────────── */

export function ProgressPage() {
  const { t } = useTranslation();
  const activeProjectId = useProjectContextStore((s) => s.activeProjectId);
  const activeProjectName = useProjectContextStore((s) => s.activeProjectName);

  const { data: projects = [] } = useQuery({
    queryKey: ['projects'],
    queryFn: () => apiGet<ProjectLite[]>('/v1/projects/'),
    staleTime: 5 * 60_000,
  });
  const projectId = activeProjectId || projects[0]?.id || '';

  const cumulativeQ = useQuery({
    queryKey: ['progress', 'cumulative', projectId],
    queryFn: () => getProgressCumulative(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const sCurveQ = useQuery({
    queryKey: ['progress', 's-curve', projectId],
    queryFn: () => getProgressSCurve(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });
  const varianceQ = useQuery({
    queryKey: ['progress', 'quantity-variance', projectId],
    queryFn: () => getQuantityVariance(projectId),
    enabled: !!projectId,
    retry: false,
    staleTime: 30_000,
  });

  const cumulative = cumulativeQ.data;
  const sCurve = sCurveQ.data;
  const variance = varianceQ.data;
  const rollup = variance?.rollup;

  return (
    <div className="animate-fade-in space-y-5">
      <Breadcrumb
        items={[
          ...(activeProjectId && activeProjectName
            ? [{ label: activeProjectName, to: `/projects/${activeProjectId}` }]
            : []),
          { label: t('progress.title', { defaultValue: 'Progress' }) },
        ]}
      />

      <PageHeader
        srTitle={t('progress.title', { defaultValue: 'Progress' })}
        subtitle={t('progress.subtitle', {
          defaultValue:
            'Physical progress across the project - the actual versus planned S-curve, per-period completion, and design versus earned quantity variance.',
        })}
      />

      <DismissibleInfo
        storageKey="progress"
        title={t('progress.intro_title', { defaultValue: 'Track physical progress, not just cost' })}
      >
        {t('progress.intro_body', {
          defaultValue:
            'Field percent-complete entries roll up here into an actual versus planned S-curve, per-period completion deltas with a running cumulative percent, and a design versus earned quantity variance for every tracked position. This is the physical view of delivery, separate from the cost and earned-value 5D page that reads the same entries in money terms.',
        })}
      </DismissibleInfo>

      {!projectId ? (
        <EmptyState
          icon={<Inbox className="h-6 w-6" />}
          title={t('progress.no_project', { defaultValue: 'No project selected' })}
          description={t('progress.no_project_desc', {
            defaultValue: 'Select an active project to see its physical progress.',
          })}
        />
      ) : (
        <>
          {/* KPI header */}
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 xl:grid-cols-6">
            <StatCard
              label={t('progress.kpi_cumulative', { defaultValue: 'Physical progress' })}
              value={fmtPct(cumulative?.current_cumulative_pct)}
              icon={Activity}
              tone="blue"
              tintValue
            />
            <StatCard
              label={t('progress.kpi_positions', { defaultValue: 'Positions tracked' })}
              value={rollup ? rollup.position_count : '-'}
              icon={Layers}
            />
            <StatCard
              label={t('progress.kpi_on_target', { defaultValue: 'On target' })}
              value={rollup ? rollup.on_target_count : '-'}
              icon={Target}
              tone="success"
              tintValue
            />
            <StatCard
              label={t('progress.kpi_over_run', { defaultValue: 'Over-run' })}
              value={rollup ? rollup.over_run_count : '-'}
              icon={TrendingUp}
              tone="warning"
              tintValue
            />
            <StatCard
              label={t('progress.kpi_under_run', { defaultValue: 'Under-run' })}
              value={rollup ? rollup.under_run_count : '-'}
              icon={TrendingDown}
            />
            <StatCard
              label={t('progress.kpi_earned', { defaultValue: 'Earned quantity' })}
              value={rollup ? fmtQty(rollup.earned_quantity_total) : '-'}
              sub={
                rollup
                  ? t('progress.kpi_earned_sub', {
                      defaultValue: 'of {{design}} design',
                      design: fmtQty(rollup.design_quantity_total),
                    })
                  : undefined
              }
              icon={Ruler}
            />
          </div>

          {/* S-curve + per-period breakdown */}
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[2fr_1fr]">
            <Card className="p-4">
              <div className="mb-3 flex items-center gap-2">
                <Activity className="h-4 w-4 text-oe-blue" />
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('progress.s_curve_title', { defaultValue: 'Progress S-curve' })}
                </h2>
              </div>
              <SectionState
                loading={sCurveQ.isLoading}
                error={sCurveQ.isError ? sCurveQ.error : null}
                onRetry={() => void sCurveQ.refetch()}
                empty={!sCurve || sCurve.points.length === 0}
                emptyIcon={<Activity className="h-6 w-6" />}
                emptyTitle={t('progress.s_curve_empty_title', { defaultValue: 'No progress recorded yet' })}
                emptyDescription={t('progress.s_curve_empty_desc', {
                  defaultValue:
                    'Record field percent-complete entries to plot actual against planned progress.',
                })}
              >
                {sCurve && <SCurveChart points={sCurve.points} />}
              </SectionState>
            </Card>

            <Card className="p-4">
              <div className="mb-3 flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-content-tertiary" />
                <h2 className="text-sm font-semibold text-content-primary">
                  {t('progress.periods_title', { defaultValue: 'By period' })}
                </h2>
              </div>
              <SectionState
                loading={cumulativeQ.isLoading}
                error={cumulativeQ.isError ? cumulativeQ.error : null}
                onRetry={() => void cumulativeQ.refetch()}
                empty={!cumulative || cumulative.periods.length === 0}
                emptyIcon={<ListChecks className="h-6 w-6" />}
                emptyTitle={t('progress.periods_empty_title', { defaultValue: 'No periods yet' })}
                emptyDescription={t('progress.periods_empty_desc', {
                  defaultValue: 'Per-period completion appears once progress is recorded.',
                })}
              >
                <div className="overflow-x-auto">
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                        <th className="px-2 py-1.5 font-medium">
                          {t('progress.col_period', { defaultValue: 'Period' })}
                        </th>
                        <th className="px-2 py-1.5 text-right font-medium">
                          {t('progress.col_delta', { defaultValue: 'Delta' })}
                        </th>
                        <th className="px-2 py-1.5 text-right font-medium">
                          {t('progress.col_cumulative', { defaultValue: 'Cumulative' })}
                        </th>
                        <th className="px-2 py-1.5 text-right font-medium">
                          {t('progress.col_entries', { defaultValue: 'Entries' })}
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {cumulative?.periods.map((p) => (
                        <tr key={p.period_label} className="border-t border-border-light">
                          <td className="px-2 py-1.5 font-medium text-content-primary whitespace-nowrap">
                            {p.period_label}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-content-secondary">
                            {fmtPct(p.delta_pct)}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums font-medium text-content-primary">
                            {fmtPct(p.cumulative_pct)}
                          </td>
                          <td className="px-2 py-1.5 text-right tabular-nums text-content-tertiary">
                            {p.entry_count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </SectionState>
            </Card>
          </div>

          {/* Quantity variance */}
          <Card className="p-4">
            <div className="mb-3 flex items-center gap-2">
              <Ruler className="h-4 w-4 text-content-tertiary" />
              <h2 className="text-sm font-semibold text-content-primary">
                {t('progress.variance_title', { defaultValue: 'Quantity variance' })}
              </h2>
            </div>
            <SectionState
              loading={varianceQ.isLoading}
              error={varianceQ.isError ? varianceQ.error : null}
              onRetry={() => void varianceQ.refetch()}
              empty={!variance || variance.positions.length === 0}
              emptyIcon={<Ruler className="h-6 w-6" />}
              emptyTitle={t('progress.variance_empty_title', { defaultValue: 'No tracked positions yet' })}
              emptyDescription={t('progress.variance_empty_desc', {
                defaultValue:
                  'Design versus earned quantity appears for every BOQ position with a recorded progress entry.',
              })}
            >
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="text-left text-2xs uppercase tracking-wide text-content-tertiary">
                      <th className="px-3 py-2 font-medium">
                        {t('progress.col_ordinal', { defaultValue: 'Ordinal' })}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t('progress.col_description', { defaultValue: 'Description' })}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t('progress.col_unit', { defaultValue: 'Unit' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('progress.col_design_qty', { defaultValue: 'Design qty' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('progress.col_earned_qty', { defaultValue: 'Earned qty' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('progress.col_percent', { defaultValue: 'Percent complete' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('progress.col_variance', { defaultValue: 'Variance' })}
                      </th>
                      <th className="px-3 py-2 text-right font-medium">
                        {t('progress.col_variance_pct', { defaultValue: 'Variance %' })}
                      </th>
                      <th className="px-3 py-2 font-medium">
                        {t('progress.col_status', { defaultValue: 'Status' })}
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {variance?.positions.map((item) => (
                      <VarianceRow key={item.boq_position_id} item={item} />
                    ))}
                  </tbody>
                  {rollup && (
                    <tfoot>
                      <tr className="border-t-2 border-border bg-surface-secondary/40 font-medium">
                        <td className="px-3 py-2 text-content-primary" colSpan={3}>
                          {t('progress.rollup_total', {
                            defaultValue: 'Total ({{count}} positions)',
                            count: rollup.position_count,
                          })}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
                          {fmtQty(rollup.design_quantity_total)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
                          {fmtQty(rollup.earned_quantity_total)}
                        </td>
                        <td className="px-3 py-2" />
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap">
                          {fmtQty(rollup.variance_total)}
                        </td>
                        <td className="px-3 py-2 text-right tabular-nums whitespace-nowrap text-content-tertiary">
                          {fmtPctStr(rollup.variance_percent)}
                        </td>
                        <td className="px-3 py-2" />
                      </tr>
                    </tfoot>
                  )}
                </table>
              </div>
            </SectionState>
          </Card>
        </>
      )}
    </div>
  );
}
