// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * ReviewDashboard - a compact, at-a-glance summary of the issue backlog for
 * the Model Review panel. Reads the already-loaded topic list (no extra
 * request), rolls it up with {@link computeIssueStats}, and shows the numbers
 * a coordination reviewer scans first: how many are open, overdue and
 * unassigned, plus the split by status, priority and the busiest assignees.
 * Sized to sit inside the narrow issues dock.
 */

import { useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, CircleDot, UserX } from 'lucide-react';

import { Badge } from '@/shared/ui';

import type { Topic } from './api';
import { computeIssueStats } from './issueStats';
import { statusVariant, priorityVariant } from './issueStatus';

function StatTile({
  icon,
  label,
  value,
  tone,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  tone: 'default' | 'warning' | 'error';
}) {
  return (
    <div className="flex flex-1 flex-col items-center rounded-lg border border-border-light bg-surface-primary px-2 py-2 text-center">
      <div
        className={
          tone === 'error'
            ? 'text-semantic-error'
            : tone === 'warning'
              ? 'text-semantic-warning'
              : 'text-content-tertiary'
        }
      >
        {icon}
      </div>
      <span className="mt-1 text-lg font-bold leading-none text-content-primary tabular-nums">
        {value}
      </span>
      <span className="mt-0.5 text-2xs uppercase tracking-wide text-content-quaternary">
        {label}
      </span>
    </div>
  );
}

export function ReviewDashboard({
  topics,
  memberName,
}: {
  topics: Topic[];
  memberName: (id: string | null) => string;
}) {
  const { t } = useTranslation();
  const stats = useMemo(() => computeIssueStats(topics), [topics]);

  if (stats.total === 0) return null;

  const statusEntries = Object.entries(stats.byStatus).sort((a, b) => b[1] - a[1]);
  const priorityEntries = Object.entries(stats.byPriority)
    .filter(([p]) => p) // hide the empty "no priority" bucket in this row
    .sort((a, b) => b[1] - a[1]);
  const topAssignees = stats.byAssignee.slice(0, 3);

  return (
    <div className="space-y-3 rounded-xl border border-border-light bg-surface-secondary/40 p-3">
      {/* Headline tiles */}
      <div className="flex gap-2">
        <StatTile
          icon={<CircleDot size={15} />}
          label={t('bcf.dashboard_open', { defaultValue: 'Open' })}
          value={stats.open}
          tone="default"
        />
        <StatTile
          icon={<AlertTriangle size={15} />}
          label={t('bcf.dashboard_overdue', { defaultValue: 'Overdue' })}
          value={stats.overdue}
          tone={stats.overdue > 0 ? 'error' : 'default'}
        />
        <StatTile
          icon={<UserX size={15} />}
          label={t('bcf.dashboard_unassigned', { defaultValue: 'Unassigned' })}
          value={stats.unassignedOpen}
          tone={stats.unassignedOpen > 0 ? 'warning' : 'default'}
        />
      </div>

      {/* Status split */}
      <div>
        <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
          {t('bcf.dashboard_by_status', { defaultValue: 'By status' })}
        </p>
        <div className="flex flex-wrap gap-1.5">
          {statusEntries.map(([status, count]) => (
            <Badge key={status} variant={statusVariant(status)} size="sm">
              {status} {count}
            </Badge>
          ))}
        </div>
      </div>

      {/* Priority split */}
      {priorityEntries.length > 0 && (
        <div>
          <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
            {t('bcf.dashboard_by_priority', { defaultValue: 'By priority' })}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {priorityEntries.map(([priority, count]) => (
              <Badge key={priority} variant={priorityVariant(priority)} size="sm">
                {priority} {count}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Busiest assignees */}
      {topAssignees.length > 0 && (
        <div>
          <p className="mb-1 text-2xs font-semibold uppercase tracking-wider text-content-quaternary">
            {t('bcf.dashboard_workload', { defaultValue: 'Open by assignee' })}
          </p>
          <ul className="space-y-1">
            {topAssignees.map(({ id, count }) => (
              <li
                key={id ?? '__unassigned'}
                className="flex items-center justify-between gap-2 text-xs text-content-secondary"
              >
                <span className="truncate">{memberName(id)}</span>
                <span className="shrink-0 font-semibold tabular-nums text-content-primary">
                  {count}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
