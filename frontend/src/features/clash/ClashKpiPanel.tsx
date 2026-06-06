// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// ClashKpiPanel — Wave A4 dashboard rendering the run's aggregated
// KPIs: total clashes, severity histogram, type breakdown, MTTR,
// top clashing discipline pairs. Pure presentation — every aggregation
// is precomputed server-side (GET /runs/{id}/kpi).

import { useQuery } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';
import clsx from 'clsx';

import { Card } from '@/shared/ui/Card';

import { clashApi, type ClashKpi } from './api';

const SEVERITY_ORDER = ['critical', 'high', 'medium', 'low'] as const;
const SEVERITY_COLOR: Record<string, string> = {
  critical: 'bg-rose-500',
  high: 'bg-orange-500',
  medium: 'bg-amber-400',
  low: 'bg-emerald-500',
};

function SeverityBar({ by }: { by: Record<string, number> }) {
  const total = SEVERITY_ORDER.reduce((acc, k) => acc + (by[k] ?? 0), 0);
  if (total === 0) return <div className="text-content-tertiary text-sm">—</div>;
  return (
    <div className="space-y-2">
      <div className="flex h-3 w-full overflow-hidden rounded-full bg-surface-secondary">
        {SEVERITY_ORDER.map((k) => {
          const n = by[k] ?? 0;
          if (n === 0) return null;
          const pct = (n / total) * 100;
          return (
            <div
              key={k}
              title={`${k}: ${n}`}
              className={clsx('h-full', SEVERITY_COLOR[k])}
              style={{ width: `${pct}%` }}
            />
          );
        })}
      </div>
      <div className="flex flex-wrap gap-3 text-xs text-content-secondary">
        {SEVERITY_ORDER.map((k) => (
          <span key={k} className="inline-flex items-center gap-1.5">
            <span className={clsx('inline-block h-2 w-2 rounded-full', SEVERITY_COLOR[k])} />
            <span className="capitalize">{k}</span>
            <span className="font-medium text-content-primary">{by[k] ?? 0}</span>
          </span>
        ))}
      </div>
    </div>
  );
}

export interface ClashKpiPanelProps {
  projectId: string;
  runId: string;
}

export function ClashKpiPanel({ projectId, runId }: ClashKpiPanelProps) {
  const { t } = useTranslation();
  const { data, isLoading } = useQuery<ClashKpi>({
    queryKey: ['clash', projectId, runId, 'kpi'],
    queryFn: () => clashApi.kpi(projectId, runId),
    enabled: !!projectId && !!runId,
  });

  if (isLoading) {
    return <div className="p-6 text-content-tertiary">Loading…</div>;
  }
  if (!data) return null;

  return (
    <div className="space-y-4 p-4" data-testid="clash-kpi-panel">
      {/* Top KPI cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
          <div className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('clash.kpi.total', { defaultValue: 'Total clashes' })}
          </div>
          <div className="text-3xl font-semibold text-content-primary mt-1">
            {data.total}
          </div>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
          <div className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('clash.kpi.open', { defaultValue: 'Open' })}
          </div>
          <div className="text-3xl font-semibold text-content-primary mt-1">
            {(data.by_status.new ?? 0) +
              (data.by_status.active ?? 0) +
              (data.by_status.reviewed ?? 0)}
          </div>
        </div>
        <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
          <div className="text-xs uppercase tracking-wide text-content-tertiary">
            {t('clash.kpi.resolved', { defaultValue: 'Resolved' })}
          </div>
          <div className="text-3xl font-semibold text-content-primary mt-1">
            {(data.by_status.resolved ?? 0) + (data.by_status.approved ?? 0)}
          </div>
        </div>
        {data.mttr_hours != null && (
          <div className="rounded-xl border border-border-light bg-surface-elevated/90 p-4 shadow-xs transition-shadow duration-normal ease-oe hover:shadow-sm">
            <div className="text-xs uppercase tracking-wide text-content-tertiary">
              {t('clash.kpi.mttr', { defaultValue: 'Mean time to resolve' })}
            </div>
            <div className="text-3xl font-semibold text-content-primary mt-1">
              {data.mttr_hours.toFixed(1)}h
            </div>
          </div>
        )}
      </div>

      {/* Severity histogram */}
      <Card className="p-4">
        <div className="text-sm font-medium mb-3">
          {t('clash.kpi.by_severity', { defaultValue: 'By severity' })}
        </div>
        <SeverityBar by={data.by_severity ?? {}} />
      </Card>

      {/* Type + status breakdown side-by-side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <Card className="p-4">
          <div className="text-sm font-medium mb-3">
            {t('clash.kpi.by_type', { defaultValue: 'By type' })}
          </div>
          <ul className="space-y-1.5 text-sm">
            {Object.entries(data.by_type ?? {}).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span className="capitalize text-content-secondary">{k}</span>
                <span className="font-medium">{v}</span>
              </li>
            ))}
            {Object.keys(data.by_type ?? {}).length === 0 && (
              <li className="text-content-tertiary">—</li>
            )}
          </ul>
        </Card>
        <Card className="p-4">
          <div className="text-sm font-medium mb-3">
            {t('clash.kpi.by_status', { defaultValue: 'By status' })}
          </div>
          <ul className="space-y-1.5 text-sm">
            {Object.entries(data.by_status ?? {}).map(([k, v]) => (
              <li key={k} className="flex justify-between">
                <span className="capitalize text-content-secondary">{k}</span>
                <span className="font-medium">{v}</span>
              </li>
            ))}
            {Object.keys(data.by_status ?? {}).length === 0 && (
              <li className="text-content-tertiary">—</li>
            )}
          </ul>
        </Card>
      </div>

      {/* Top clashing pairs */}
      <Card className="p-4">
        <div className="text-sm font-medium mb-3">
          {t('clash.kpi.top_pairs', { defaultValue: 'Top clashing pairs' })}
        </div>
        {data.top_clashing_pairs.length === 0 ? (
          <div className="text-content-tertiary text-sm">—</div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-content-tertiary text-xs uppercase">
                <th className="py-1.5">{t('clash.kpi.pair', { defaultValue: 'Pair' })}</th>
                <th className="py-1.5 w-20 text-right">
                  {t('clash.kpi.count', { defaultValue: 'Count' })}
                </th>
                <th className="py-1.5 w-20 text-right">
                  {t('clash.kpi.open_short', { defaultValue: 'Open' })}
                </th>
                <th className="py-1.5 w-24 text-right">
                  {t('clash.kpi.open_share', { defaultValue: 'Open %' })}
                </th>
              </tr>
            </thead>
            <tbody>
              {data.top_clashing_pairs.map((p) => (
                <tr key={`${p.a}|${p.b}`} className="border-t border-border">
                  <td className="py-1.5">
                    {p.a} × {p.b}
                  </td>
                  <td className="py-1.5 text-right font-medium">{p.count}</td>
                  <td className="py-1.5 text-right">{p.open_count}</td>
                  <td className="py-1.5 text-right">
                    {(p.open_share * 100).toFixed(0)}%
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
