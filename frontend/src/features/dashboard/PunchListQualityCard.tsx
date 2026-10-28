// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * PunchListQualityCard - compact dashboard widget showing punch-list
 * (snagging) quality for the active project: how many items are still
 * open, how many are overdue, and the average number of days it takes to
 * close an item.
 *
 * Data comes from `GET /v1/punchlist/summary/?project_id=...`
 * (`fetchPunchSummary` -> `PunchSummary`).
 *
 * "Open" is derived as total minus the done statuses. The punchlist
 * module treats "verified" and "closed" as the done states (an item is
 * driven through to a verified close-out), so everything else - open,
 * in progress and resolved-but-not-yet-verified - still counts as open
 * work here.
 *
 * The card hides itself (returns null) when there is no active project,
 * while the summary is loading, or when the project has zero punch items,
 * so it never clutters the dashboard for projects that do not track
 * snags.
 */

import { useTranslation } from 'react-i18next';
import { useQuery } from '@tanstack/react-query';
import { useNavigate } from 'react-router-dom';
import { ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, InfoHint } from '@/shared/ui';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { fetchPunchSummary, type PunchStatus } from '@/features/punchlist/api';
import { KpiStrip } from './KpiStrip';
import { fmtFixed } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';

/**
 * Statuses the punchlist module treats as "done". Everything else counts
 * as open work. Mirrors the module FSM where an item ends in verified or
 * closed.
 */
const DONE_STATUSES: PunchStatus[] = ['verified', 'closed'];

function formatCount(value: number): string {
  if (!Number.isFinite(value)) return '0';
  try {
    return new Intl.NumberFormat(getNumberLocale()).format(value);
  } catch {
    return String(Math.round(value));
  }
}

export function PunchListQualityCard() {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const projectId = useProjectContextStore((s) => s.activeProjectId) ?? '';

  const { data, isLoading } = useQuery({
    queryKey: ['punchlist', 'summary', projectId],
    queryFn: () => fetchPunchSummary(projectId),
    enabled: Boolean(projectId),
    staleTime: 60 * 1000,
  });

  // Self-hide: no project, still loading, no data yet, or nothing to snag.
  if (!projectId) return null;
  if (isLoading) return null;
  if (!data || data.total === 0) return null;

  const byStatus = data.by_status ?? {};
  const done = DONE_STATUSES.reduce((sum, status) => sum + (byStatus[status] ?? 0), 0);
  const open = Math.max(0, data.total - done);
  const overdue = data.overdue ?? 0;
  const hasOverdue = overdue > 0;

  const avgDays = data.avg_days_to_close;
  const hasAvgDays = typeof avgDays === 'number' && Number.isFinite(avgDays) && avgDays > 0;

  return (
    <Card className="h-full">
      <CardHeader
        title={t('dashboard.punch_title', { defaultValue: 'Punch list quality' })}
        subtitle={t('dashboard.punch_subtitle', {
          defaultValue: '{{count}} items tracked in this project',
          count: data.total,
        })}
        action={
          <button
            type="button"
            onClick={() => navigate('/punchlist')}
            className="inline-flex items-center gap-1.5 text-xs text-oe-blue hover:underline"
          >
            {t('dashboard.punch_open', { defaultValue: 'Open punch list' })}
            <ArrowRight size={11} />
          </button>
        }
      />
      <CardContent>
        <KpiStrip
          stats={[
            {
              label: t('dashboard.punch_open_items', { defaultValue: 'Open items' }),
              value: formatCount(open),
            },
            {
              label: t('dashboard.punch_overdue', { defaultValue: 'Overdue' }),
              value: formatCount(overdue),
              tone: hasOverdue ? 'text-rose-600' : 'text-content-secondary',
            },
            {
              label: t('dashboard.punch_avg_label', { defaultValue: 'Avg to close' }),
              value: hasAvgDays ? fmtFixed(avgDays, 1) : '-',
              tone: 'text-content-secondary',
            },
          ]}
        />
        <InfoHint
          className="mt-3"
          text={t('dashboard.punch_help', {
            defaultValue:
              'Open items are everything not yet verified or closed, so items that are open, in progress or resolved but awaiting a final check all count here. Overdue are open items past their due date. The average is how long closed items took, from raised to closed, in days.',
          })}
        />
      </CardContent>
    </Card>
  );
}

export default PunchListQualityCard;
