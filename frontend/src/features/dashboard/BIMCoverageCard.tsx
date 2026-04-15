/**
 * BIMCoverageCard — dashboard widget showing how complete the active
 * project's BIM↔everything integration is.
 *
 * Calls the new `GET /api/v1/bim_hub/coverage-summary/?project_id=...`
 * endpoint and renders six progress bars (linked to BOQ, costed,
 * validated, has docs, has tasks, has activities) plus a headline
 * percentage.  Hides itself entirely when the active project has zero
 * BIM elements — no point cluttering the dashboard for projects that
 * haven't uploaded a model yet.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { Cuboid, Link2, FileText, ShieldCheck, CheckSquare, Calendar, ArrowRight } from 'lucide-react';
import { apiGet } from '@/shared/lib/api';
import { useProjectContextStore } from '@/stores/useProjectContextStore';

interface BIMCoverageSummary {
  project_id: string;
  elements_total: number;
  elements_linked_to_boq: number;
  elements_costed: number;
  elements_validated: number;
  elements_with_documents: number;
  elements_with_tasks: number;
  elements_with_activities: number;
  percent_linked_to_boq: number;
  percent_costed: number;
  percent_validated: number;
  percent_with_documents: number;
  percent_with_tasks: number;
  percent_with_activities: number;
}

interface MetricRowProps {
  icon: React.ReactNode;
  label: string;
  count: number;
  total: number;
  percent: number;
  color: string;
}

function MetricRow({ icon, label, count, total, percent, color }: MetricRowProps) {
  const pctDisplay = Math.round(percent * 100);
  return (
    <div className="flex items-center gap-3">
      <div className={`shrink-0 h-7 w-7 rounded-md ${color} flex items-center justify-center`}>
        {icon}
      </div>
      <div className="flex-1 min-w-0">
        <div className="flex items-baseline justify-between gap-2 mb-1">
          <span className="text-xs font-medium text-content-secondary truncate">
            {label}
          </span>
          <span className="text-xs font-mono text-content-tertiary tabular-nums shrink-0">
            {count.toLocaleString()} / {total.toLocaleString()}{' '}
            <span className="text-content-quaternary">({pctDisplay}%)</span>
          </span>
        </div>
        <div className="h-1.5 rounded-full bg-surface-secondary overflow-hidden">
          <div
            className={`h-full transition-all duration-700 ease-out ${color}`}
            style={{ width: `${pctDisplay}%` }}
          />
        </div>
      </div>
    </div>
  );
}

export default function BIMCoverageCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId);

  const { data, isLoading } = useQuery({
    queryKey: ['bim-coverage-summary', projectId],
    queryFn: () =>
      apiGet<BIMCoverageSummary>(
        `/v1/bim_hub/coverage-summary/?project_id=${encodeURIComponent(projectId!)}`,
      ),
    enabled: !!projectId,
    staleTime: 60 * 1000,
    // The endpoint returns 0 totals for projects with no BIM model — we
    // hide the card in that case via the early return below.
  });

  const totalElements = data?.elements_total ?? 0;

  // Headline % = average of the six covered metrics.  Gives one
  // at-a-glance number for the dashboard summary.
  const headlinePercent = useMemo(() => {
    if (!data || totalElements === 0) return 0;
    const parts = [
      data.percent_linked_to_boq,
      data.percent_costed,
      data.percent_validated,
      data.percent_with_documents,
      data.percent_with_tasks,
      data.percent_with_activities,
    ];
    const avg = parts.reduce((s, v) => s + v, 0) / parts.length;
    return Math.round(avg * 100);
  }, [data, totalElements]);

  // Hide entirely on empty / loading / no-model projects so the
  // dashboard isn't cluttered for users who haven't uploaded a BIM file
  // yet.  Estimators on pure BOQ projects shouldn't see this card at
  // all.
  if (!projectId) return null;
  if (isLoading) return null;
  if (!data || totalElements === 0) return null;

  const headlineColor =
    headlinePercent >= 75
      ? 'text-emerald-600'
      : headlinePercent >= 40
        ? 'text-amber-600'
        : 'text-rose-600';

  return (
    <div
      className="mb-6 rounded-xl border border-border-light bg-surface-primary p-5 animate-card-in"
      style={{ animationDelay: '120ms' }}
    >
      <div className="flex items-start justify-between gap-3 mb-4">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-amber-50 dark:bg-amber-950/40 flex items-center justify-center text-amber-600">
            <Cuboid size={20} strokeWidth={1.75} />
          </div>
          <div>
            <h3 className="text-sm font-semibold text-content-primary">
              {t('dashboard.bim_coverage_title', {
                defaultValue: 'BIM Integration Coverage',
              })}
            </h3>
            <p className="text-xs text-content-tertiary">
              {t('dashboard.bim_coverage_subtitle', {
                defaultValue:
                  '{{count}} elements across all BIM models in this project',
                count: totalElements,
              })}
            </p>
          </div>
        </div>
        <div className="text-right">
          <div className={`text-2xl font-bold tabular-nums ${headlineColor}`}>
            {headlinePercent}%
          </div>
          <div className="text-[10px] uppercase tracking-wider text-content-quaternary">
            {t('dashboard.bim_coverage_headline', { defaultValue: 'avg coverage' })}
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <MetricRow
          icon={<Link2 size={12} className="text-blue-600" />}
          label={t('dashboard.bim_linked_boq', {
            defaultValue: 'Linked to BOQ',
          })}
          count={data.elements_linked_to_boq}
          total={totalElements}
          percent={data.percent_linked_to_boq}
          color="bg-blue-50 dark:bg-blue-950/40"
        />
        <MetricRow
          icon={<ShieldCheck size={12} className="text-emerald-600" />}
          label={t('dashboard.bim_costed', { defaultValue: 'Costed' })}
          count={data.elements_costed}
          total={totalElements}
          percent={data.percent_costed}
          color="bg-emerald-50 dark:bg-emerald-950/40"
        />
        <MetricRow
          icon={<ShieldCheck size={12} className="text-amber-600" />}
          label={t('dashboard.bim_validated', { defaultValue: 'Validated' })}
          count={data.elements_validated}
          total={totalElements}
          percent={data.percent_validated}
          color="bg-amber-50 dark:bg-amber-950/40"
        />
        <MetricRow
          icon={<FileText size={12} className="text-violet-600" />}
          label={t('dashboard.bim_with_documents', {
            defaultValue: 'With documents',
          })}
          count={data.elements_with_documents}
          total={totalElements}
          percent={data.percent_with_documents}
          color="bg-violet-50 dark:bg-violet-950/40"
        />
        <MetricRow
          icon={<CheckSquare size={12} className="text-rose-600" />}
          label={t('dashboard.bim_with_tasks', { defaultValue: 'With tasks' })}
          count={data.elements_with_tasks}
          total={totalElements}
          percent={data.percent_with_tasks}
          color="bg-rose-50 dark:bg-rose-950/40"
        />
        <MetricRow
          icon={<Calendar size={12} className="text-cyan-600" />}
          label={t('dashboard.bim_with_activities', {
            defaultValue: 'With 4D activities',
          })}
          count={data.elements_with_activities}
          total={totalElements}
          percent={data.percent_with_activities}
          color="bg-cyan-50 dark:bg-cyan-950/40"
        />
      </div>

      <div className="mt-4 flex justify-end">
        <button
          type="button"
          onClick={() => navigate('/bim')}
          className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
        >
          {t('dashboard.bim_open_viewer', { defaultValue: 'Open BIM viewer' })}
          <ArrowRight size={11} />
        </button>
      </div>
    </div>
  );
}
