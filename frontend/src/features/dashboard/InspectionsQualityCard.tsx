// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * InspectionsQualityCard - compact dashboard widget summarising the active
 * project's quality inspections.
 *
 * There is no server-side stats endpoint, so this aggregates the inspection
 * list client-side (GET /v1/inspections/?project_id=...). That list comes back
 * one page at a time, so the figures below describe the page, not necessarily
 * the project - hence the truncation notice under them:
 *   - pass rate  = passed / (passed + failed), guarded against divide-by-zero
 *                  and clamped to 0..100 (never NaN),
 *   - open count = inspections still scheduled or in progress,
 *   - failed     = inspections with a failing result.
 *
 * The card self-hides (returns null) when there is no active project, while
 * the list is loading, or when the project has zero inspections, so the
 * dashboard stays uncluttered for projects that have not logged any yet.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ClipboardCheck, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { TruncationNotice } from '@/shared/ui/TruncationNotice';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchInspections, type Inspection } from '@/features/inspections/api';
import { KpiStrip } from './KpiStrip';
import { getNumberLocale } from '@/stores/usePreferencesStore';

interface InspectionStats {
  total: number;
  /** scheduled + in_progress */
  open: number;
  /** result === 'pass' */
  passed: number;
  /** result === 'fail' */
  failed: number;
  /** passed + failed - the pool the pass rate is measured against */
  evaluated: number;
  /** 0..100, integer, never NaN */
  passRate: number;
}

function aggregate(inspections: Inspection[]): InspectionStats {
  let open = 0;
  let passed = 0;
  let failed = 0;
  for (const ins of inspections) {
    if (ins.status === 'scheduled' || ins.status === 'in_progress') open += 1;
    if (ins.result === 'pass') passed += 1;
    else if (ins.result === 'fail') failed += 1;
  }
  const evaluated = passed + failed;
  const passRate = evaluated > 0 ? Math.max(0, Math.min(100, Math.round((passed / evaluated) * 100))) : 0;
  return { total: inspections.length, open, passed, failed, evaluated, passRate };
}

export function InspectionsQualityCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const { data, isLoading } = useQuery({
    queryKey: ['inspections', 'dashboard-quality', projectId],
    queryFn: () => fetchInspections({ project_id: projectId }),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  const stats = useMemo(() => aggregate(data?.items ?? []), [data]);

  // Self-hide on no project / loading / empty so the dashboard is not
  // cluttered for projects that have not logged any inspections.
  if (!projectId) return null;
  if (isLoading) return null;
  if (!data || stats.total === 0) return null;

  const nf = new Intl.NumberFormat(getNumberLocale());
  const hasEvaluated = stats.evaluated > 0;

  const rateColor =
    stats.passRate >= 90
      ? 'text-emerald-600'
      : stats.passRate >= 70
        ? 'text-amber-600'
        : 'text-rose-600';

  return (
    <Card className="h-full">
      <CardHeader
        title={
          <span className="inline-flex items-center gap-2">
            <ClipboardCheck size={18} strokeWidth={1.75} className="text-oe-blue" />
            {t('dashboard.inspections_title', { defaultValue: 'Inspection quality' })}
          </span>
        }
        subtitle={t('dashboard.inspections_subtitle', {
          defaultValue: 'How inspections are passing on this project',
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/inspections')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.inspections_open', { defaultValue: 'Open inspections' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.inspections_pass_rate', { defaultValue: 'Pass rate' }),
              value: hasEvaluated ? `${stats.passRate}%` : '-',
              tone: hasEvaluated ? rateColor : 'text-content-tertiary',
            },
            {
              label: t('dashboard.inspections_open_short', { defaultValue: 'Open' }),
              value: nf.format(stats.open),
            },
            {
              label: t('dashboard.inspections_failed', { defaultValue: 'Failed' }),
              value: nf.format(stats.failed),
              tone: stats.failed > 0 ? 'text-rose-600' : 'text-content-secondary',
            },
          ]}
        />
        {hasEvaluated && (
          <p className="mt-2 text-2xs text-content-tertiary">
            {t('dashboard.inspections_passed_of', {
              defaultValue: '{{passed}} of {{evaluated}} evaluated passed',
              passed: nf.format(stats.passed),
              evaluated: nf.format(stats.evaluated),
            })}
          </p>
        )}
        {/* A rate computed from one page is a rate over a sample, and a sample
            presented as a project figure is the more misleading the further
            the register runs past it. */}
        <TruncationNotice page={data} className="mt-2 text-2xs" />
        <InfoHint
          className="mt-3"
          text={t('dashboard.inspections_help', {
            defaultValue:
              'Pass rate is passed inspections divided by those that already have a result, passed or failed. Inspections still scheduled or in progress do not affect the rate yet, so until the first result comes in the card shows the open count instead. Failed counts inspections with a failing result.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default InspectionsQualityCard;
