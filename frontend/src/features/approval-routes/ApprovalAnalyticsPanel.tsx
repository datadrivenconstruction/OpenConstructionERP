// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ApprovalAnalyticsPanel - project-scoped approval-cycle analytics
// (backlog item #11). Aggregates the per-instance held-days timeline into
// KPI tiles (approval rate, cycle time, SLA breaches), a bottleneck
// ranking and by-role / by-step held-time tables. Tiles and bottleneck
// rows drill back to the Instances tab pre-filtered, so a slow spot is one
// click from the offending workflows.
//
// Read-only surface: it reads GET /approval-routes/analytics and never
// mutates. The heavy lifting (held-time classification, medians, breach
// counts) lives in the backend pure aggregate; this component only renders.

import { useState, type ReactNode } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import {
  AlertTriangle,
  CheckCircle2,
  Clock,
  Gauge,
  Hourglass,
  TimerReset,
  Workflow,
  XCircle,
} from 'lucide-react';

import {
  Card,
  EmptyState,
  KpiBand,
  RecoveryCard,
  SkeletonTable,
  type KpiBandItem,
} from '@/shared/ui';
import { approvalRoutesKeys, getApprovalAnalytics } from './api';
import type { InstanceStatus } from './types';

const RANGE_OPTIONS = [30, 90, 180] as const;

export interface ApprovalAnalyticsPanelProps {
  /** Project whose approval workflows to analyse. null = show the
   *  pick-a-project prompt (the panel is strictly project-scoped). */
  projectId: string | null;
  /** Optional target-kind filter, threaded to the endpoint and forwarded
   *  when a step bottleneck row drills to the Instances tab. */
  targetKind?: string | null;
  /** Jump to the Instances tab pre-filtered on a status and/or kind. */
  onDrill?: (filter: { status?: InstanceStatus; targetKind?: string }) => void;
}

export function ApprovalAnalyticsPanel({
  projectId,
  targetKind,
  onDrill,
}: ApprovalAnalyticsPanelProps) {
  const { t } = useTranslation();
  const [days, setDays] = useState<number>(180);

  const query = useQuery({
    queryKey: approvalRoutesKeys.analytics(projectId, targetKind ?? null, days),
    queryFn: () =>
      getApprovalAnalytics({ projectId: projectId as string, targetKind, days }),
    enabled: projectId != null,
    staleTime: 30_000,
  });

  if (projectId == null) {
    return (
      <EmptyState
        icon={<Gauge size={28} strokeWidth={1.5} />}
        title={t('approvalRoutes.analytics_pick_project', {
          defaultValue: 'Select a project to see its approval-cycle analytics.',
        })}
      />
    );
  }

  if (query.isLoading) return <SkeletonTable rows={3} columns={4} />;
  if (query.isError) {
    return (
      <RecoveryCard error={query.error as Error} onRetry={() => query.refetch()} />
    );
  }

  const data = query.data;
  if (!data || data.sample_size === 0) {
    return (
      <div className="space-y-3">
        <RangeSelector days={days} onChange={setDays} />
        <EmptyState
          icon={<Workflow size={28} strokeWidth={1.5} />}
          title={t('approvalRoutes.analytics_empty_title', {
            defaultValue: 'No approval workflows in range',
          })}
          description={t('approvalRoutes.analytics_empty_desc', {
            defaultValue:
              "Approval workflows on this project's routes will show cycle-time and breach analytics here.",
          })}
        />
      </div>
    );
  }

  const k = data.kpis;
  const fmtDays = (n: number | null) =>
    n == null ? '—' : t('approvalRoutes.unit_days', { n, defaultValue: '{{n}} d' });
  const fmtHours = (n: number) =>
    t('approvalRoutes.unit_hours', { n, defaultValue: '{{n}} h' });
  const fmtPct = (rate: number | null) =>
    rate == null ? '—' : `${Math.round(rate * 100)}%`;
  const roleLabel = (role: string | null) =>
    role ??
    t('approvalRoutes.analytics_role_unassigned', { defaultValue: 'Specific user' });

  const tiles: KpiBandItem[] = [
    {
      label: t('approvalRoutes.kpi_total', { defaultValue: 'Workflows' }),
      value: k.total_instances,
      icon: Workflow,
    },
    {
      label: t('approvalRoutes.kpi_pending', { defaultValue: 'Pending' }),
      value: k.pending,
      icon: Clock,
      onClick: onDrill ? () => onDrill({ status: 'pending' }) : undefined,
    },
    {
      label: t('approvalRoutes.kpi_approved', { defaultValue: 'Approved' }),
      value: k.approved,
      icon: CheckCircle2,
      tone: 'success',
      onClick: onDrill ? () => onDrill({ status: 'approved' }) : undefined,
    },
    {
      label: t('approvalRoutes.kpi_rejected', { defaultValue: 'Rejected' }),
      value: k.rejected,
      icon: XCircle,
      tone: 'danger',
      onClick: onDrill ? () => onDrill({ status: 'rejected' }) : undefined,
    },
    {
      label: t('approvalRoutes.kpi_approval_rate', { defaultValue: 'Approval rate' }),
      value: fmtPct(k.approval_rate),
      icon: Gauge,
    },
    {
      label: t('approvalRoutes.kpi_avg_cycle', { defaultValue: 'Avg cycle' }),
      value: fmtDays(k.avg_cycle_days),
      icon: TimerReset,
    },
    {
      label: t('approvalRoutes.kpi_median_cycle', { defaultValue: 'Median cycle' }),
      value: fmtDays(k.median_cycle_days),
      icon: TimerReset,
    },
    {
      label: t('approvalRoutes.kpi_breaches', { defaultValue: 'SLA breaches' }),
      value: k.breached_steps_total,
      icon: AlertTriangle,
      tone: 'warning',
      tintValue: k.breached_steps_total > 0,
      sub: t('approvalRoutes.kpi_breaches_sub', {
        n: k.instances_with_breach,
        defaultValue: '{{n}} workflows affected',
      }),
    },
    {
      label: t('approvalRoutes.kpi_open_overdue', { defaultValue: 'Overdue now' }),
      value: k.open_overdue_now,
      icon: Hourglass,
      tone: 'danger',
      tintValue: k.open_overdue_now > 0,
      onClick: onDrill ? () => onDrill({ status: 'pending' }) : undefined,
    },
  ];

  return (
    <div className="space-y-4">
      <RangeSelector days={days} onChange={setDays} />

      <KpiBand items={tiles} columns={4} size="sm" />

      {data.truncated && (
        <p className="text-2xs text-content-tertiary">
          {t('approvalRoutes.analytics_truncated', {
            n: data.sample_size,
            defaultValue: 'Showing the most recent {{n}} workflows.',
          })}
        </p>
      )}

      {/* Bottlenecks */}
      <section>
        <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-1.5">
          {t('approvalRoutes.analytics_bottlenecks', { defaultValue: 'Bottlenecks' })}
        </h3>
        {data.bottlenecks.length === 0 ? (
          <p className="text-xs text-content-tertiary">
            {t('approvalRoutes.analytics_bottlenecks_empty', {
              defaultValue: 'No completed steps in range yet.',
            })}
          </p>
        ) : (
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/40">
                    <Th>{t('approvalRoutes.analytics_col_step', { defaultValue: 'Step' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_median', { defaultValue: 'Median' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_avg', { defaultValue: 'Avg' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_breach_rate', { defaultValue: 'Breach %' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_count', { defaultValue: 'Decided' })}</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {data.bottlenecks.map((b) => {
                    const drillable = b.kind === 'step' && typeof onDrill === 'function';
                    return (
                      <tr
                        key={`${b.kind}:${b.ref}`}
                        onClick={
                          drillable
                            ? () => onDrill?.({ targetKind: targetKind ?? undefined })
                            : undefined
                        }
                        className={
                          drillable
                            ? 'cursor-pointer hover:bg-surface-secondary/50 transition-colors'
                            : undefined
                        }
                      >
                        <Td>{b.label}</Td>
                        <Td right>{fmtHours(b.median_hours)}</Td>
                        <Td right muted>{fmtHours(b.avg_hours)}</Td>
                        <Td right>{fmtPct(b.breach_rate)}</Td>
                        <Td right muted>{b.sample_size}</Td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </Card>
        )}
      </section>

      {/* Time by role */}
      {data.by_role.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-1.5">
            {t('approvalRoutes.analytics_by_role', { defaultValue: 'Time by role' })}
          </h3>
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/40">
                    <Th>{t('approvalRoutes.analytics_col_role', { defaultValue: 'Role' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_count', { defaultValue: 'Decided' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_avg', { defaultValue: 'Avg' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_median', { defaultValue: 'Median' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_breach_rate', { defaultValue: 'Breach %' })}</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {data.by_role.map((r) => (
                    <tr key={r.role ?? '__none__'}>
                      <Td>{roleLabel(r.role)}</Td>
                      <Td right muted>{r.decided_count}</Td>
                      <Td right muted>{fmtHours(r.avg_hours)}</Td>
                      <Td right>{fmtHours(r.median_hours)}</Td>
                      <Td right>{fmtPct(r.breach_rate)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </section>
      )}

      {/* Time by step */}
      {data.by_step.length > 0 && (
        <section>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-content-tertiary mb-1.5">
            {t('approvalRoutes.analytics_by_step', { defaultValue: 'Time by step' })}
          </h3>
          <Card padding="none" className="overflow-hidden">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border-light bg-surface-secondary/40">
                    <Th>{t('approvalRoutes.col_name', { defaultValue: 'Name' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_step', { defaultValue: 'Step' })}</Th>
                    <Th>{t('approvalRoutes.analytics_col_role', { defaultValue: 'Role' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_count', { defaultValue: 'Decided' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_avg', { defaultValue: 'Avg' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_median', { defaultValue: 'Median' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_breach_rate', { defaultValue: 'Breach %' })}</Th>
                    <Th right>{t('approvalRoutes.analytics_col_sla', { defaultValue: 'SLA' })}</Th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border-light">
                  {data.by_step.map((s) => (
                    <tr key={`${s.route_id}:${s.ordinal}`}>
                      <Td>{s.route_name}</Td>
                      <Td right muted>{s.ordinal}</Td>
                      <Td>{roleLabel(s.approver_role)}</Td>
                      <Td right muted>{s.decided_count}</Td>
                      <Td right muted>{fmtHours(s.avg_hours)}</Td>
                      <Td right>{fmtHours(s.median_hours)}</Td>
                      <Td right>{fmtPct(s.breach_rate)}</Td>
                      <Td right muted>{s.sla_hours == null ? '—' : fmtHours(s.sla_hours)}</Td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </section>
      )}
    </div>
  );
}

/* ── Small presentational helpers (local to this panel) ─────────────── */

function RangeSelector({
  days,
  onChange,
}: {
  days: number;
  onChange: (d: number) => void;
}) {
  const { t } = useTranslation();
  const label = (d: number) =>
    t(`approvalRoutes.analytics_range_${d}`, { defaultValue: `Last ${d} days` });
  return (
    <div className="flex items-center gap-2">
      <label className="text-xs text-content-secondary">
        {t('approvalRoutes.analytics_range_label', { defaultValue: 'Window' })}
      </label>
      <select
        value={days}
        onChange={(e) => onChange(Number(e.target.value))}
        className="h-8 rounded-md border border-border bg-surface-primary px-2 text-xs focus:outline-none focus:ring-2 focus:ring-oe-blue/30 focus:border-oe-blue cursor-pointer"
        aria-label={t('approvalRoutes.analytics_range_label', { defaultValue: 'Window' })}
      >
        {RANGE_OPTIONS.map((d) => (
          <option key={d} value={d}>
            {label(d)}
          </option>
        ))}
      </select>
    </div>
  );
}

function Th({ children, right }: { children: ReactNode; right?: boolean }) {
  return (
    <th
      className={`px-3 py-2 text-2xs font-semibold uppercase tracking-wider text-content-tertiary ${
        right ? 'text-right' : 'text-left'
      }`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  right,
  muted,
}: {
  children: ReactNode;
  right?: boolean;
  muted?: boolean;
}) {
  return (
    <td
      className={`px-3 py-2.5 text-xs tabular-nums ${right ? 'text-right' : 'text-left'} ${
        muted ? 'text-content-tertiary' : 'text-content-secondary'
      }`}
    >
      {children}
    </td>
  );
}
