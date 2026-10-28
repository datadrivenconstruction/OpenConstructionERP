// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * SubmittalsPendingCard - compact dashboard widget summarising the
 * submittal review status for the active project.
 *
 * There is no server-side stats endpoint for submittals, so this card
 * fetches the project's submittal list (`GET /v1/submittals/?project_id=`)
 * and aggregates the counts client-side:
 *   - pending review  = in-review statuses (submitted, under_review),
 *   - approved        = approved statuses (approved, approved_as_noted),
 *   - overdue         = date_required already past and not yet resolved
 *                       (the wire carries date_required as the due date).
 *
 * The card SELF-HIDES (returns null) when there is no active project,
 * while the list is loading, or when the project has zero submittals,
 * so it never clutters the dashboard for projects that do not use the
 * submittals workflow.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchSubmittals, type Submittal, type SubmittalStatus } from '@/features/submittals/api';
import { KpiStrip } from './KpiStrip';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/** In-review statuses awaiting a reviewer decision. */
const PENDING_STATUSES = new Set<SubmittalStatus>(['submitted', 'under_review']);

/** Statuses that count as an approval. */
const APPROVED_STATUSES = new Set<SubmittalStatus>(['approved', 'approved_as_noted']);

/**
 * Statuses that resolve the review so an overdue date_required is no
 * longer actionable (approved either way, or closed / rejected).
 */
const RESOLVED_STATUSES = new Set<SubmittalStatus>([
  'approved',
  'approved_as_noted',
  'closed',
  'rejected',
]);

/** UTC-day difference in days between date_required and today. */
function daysUntilUtc(isoYmd: string): number | null {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(isoYmd);
  if (!m) return null;
  const year = Number(m[1]);
  const month = Number(m[2]);
  const day = Number(m[3]);
  const target = Date.UTC(year, month - 1, day);
  const now = new Date();
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((target - today) / 86_400_000);
}

interface Buckets {
  pending: number;
  approved: number;
  overdue: number;
}

function bucketize(rows: Submittal[]): Buckets {
  let pending = 0;
  let approved = 0;
  let overdue = 0;
  for (const row of rows) {
    if (PENDING_STATUSES.has(row.status)) pending += 1;
    if (APPROVED_STATUSES.has(row.status)) approved += 1;
    if (row.date_required && !RESOLVED_STATUSES.has(row.status)) {
      const days = daysUntilUtc(row.date_required);
      if (days !== null && days < 0) overdue += 1;
    }
  }
  return { pending, approved, overdue };
}

export function SubmittalsPendingCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const { data, isLoading } = useQuery({
    queryKey: ['submittals', 'dashboard-card', projectId],
    queryFn: () => fetchSubmittals({ project_id: projectId }),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  const rows = data ?? [];
  const buckets = useMemo(() => bucketize(rows), [rows]);

  // Self-hide for the no-project, loading, and empty-project cases so the
  // card never adds noise to the dashboard.
  if (!projectId) return null;
  if (isLoading) return null;
  if (rows.length === 0) return null;

  const nf = new Intl.NumberFormat(getNumberLocale());

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.submittals_title', { defaultValue: 'Submittals for review' })}
        subtitle={t('dashboard.submittals_subtitle', {
          defaultValue: 'Where each submittal sits in the review',
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/submittals')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.submittals_open', { defaultValue: 'Open submittals' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.submittals_pending', { defaultValue: 'Pending review' }),
              value: nf.format(buckets.pending),
            },
            {
              label: t('dashboard.submittals_approved', { defaultValue: 'Approved' }),
              value: nf.format(buckets.approved),
              tone: 'text-emerald-600',
            },
            {
              label: t('dashboard.submittals_overdue', { defaultValue: 'Overdue' }),
              value: nf.format(buckets.overdue),
              tone: buckets.overdue > 0 ? 'text-rose-600' : 'text-content-secondary',
            },
          ]}
        />
        <InfoHint
          className="mt-3"
          text={t('dashboard.submittals_help', {
            defaultValue:
              'Pending review counts submittals that have been sent in and are waiting for a reviewer decision. Approved includes both approved and approved as noted. Overdue are submittals past their required date that are not yet approved, closed or rejected.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default SubmittalsPendingCard;
