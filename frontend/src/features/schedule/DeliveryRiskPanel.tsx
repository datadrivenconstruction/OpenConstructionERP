// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * "Delivery at risk" - the activities whose attached work is late or blocked.
 *
 * The Delivery column shows this per row, but a planner scrolling a
 * forty-activity programme should not have to find the flagged rows by eye.
 * This panel is the same data, listed, and it renders nothing at all when
 * nothing is at risk (an empty "all clear" card is noise on every other day).
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle } from 'lucide-react';
import { Card } from '@/shared/ui';
import type { Activity } from './api';
import { atRiskActivities, isRequestLate, isTaskBlocked, isTaskLate, type DeliveryIndex } from './delivery';

export interface DeliveryRiskPanelProps {
  index: DeliveryIndex;
  activities: Activity[];
  doneStages: Set<string>;
  today: string;
  onSelectActivity?: (activityId: string) => void;
}

export function DeliveryRiskPanel({
  index,
  activities,
  doneStages,
  today,
  onSelectActivity,
}: DeliveryRiskPanelProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const rows = atRiskActivities(index, activities);
  if (rows.length === 0) return null;

  return (
    <Card padding="sm" className="mt-4 border-semantic-error/30" data-testid="delivery-risk-panel">
      <div className="flex items-center gap-2">
        <AlertTriangle size={15} className="shrink-0 text-semantic-error" />
        <span className="text-sm font-semibold text-content-primary">
          {rows.length === 1
            ? t('schedule.delivery.risk_title_one', {
                defaultValue: 'Delivery at risk on 1 activity',
              })
            : t('schedule.delivery.risk_title', {
                count: rows.length,
                defaultValue: 'Delivery at risk on {{count}} activities',
              })}
        </span>
      </div>
      <ul className="mt-2 space-y-1.5">
        {rows.map(({ activity, delivery }) => (
          <li key={activity.id} className="flex flex-wrap items-center gap-2 text-xs">
            <button
              type="button"
              data-testid={`delivery-risk-activity-${activity.id}`}
              onClick={() => onSelectActivity?.(activity.id)}
              className="font-medium text-content-primary underline-offset-2 hover:text-oe-blue hover:underline"
            >
              {activity.wbs_code ? `${activity.wbs_code} · ` : ''}
              {activity.name}
            </button>
            <span className="flex flex-wrap gap-1">
              {delivery.requests.filter(isRequestLate).map((r) => (
                <button
                  key={r.id}
                  type="button"
                  data-testid={`delivery-risk-request-${r.id}`}
                  onClick={() => navigate(`/work-requests/${r.id}`)}
                  className="rounded-full border border-semantic-error/50 bg-semantic-error/10 px-1.5 py-0.5 text-[10px] font-medium leading-none text-semantic-error"
                >
                  {r.reference}
                  {typeof r.days_late === 'number' && r.days_late > 0
                    ? ` · ${t('schedule.delivery.days_late_short', {
                        count: r.days_late,
                        defaultValue: '{{count}}d late',
                      })}`
                    : ''}
                </button>
              ))}
              {delivery.tasks
                .filter((x) => isTaskLate(x, doneStages, today) || isTaskBlocked(x, doneStages))
                .map((x) => (
                  <button
                    key={x.id}
                    type="button"
                    data-testid={`delivery-risk-task-${x.id}`}
                    onClick={() => navigate('/team-standup')}
                    className="rounded-full border border-semantic-warning/50 bg-semantic-warning/10 px-1.5 py-0.5 text-[10px] font-medium leading-none text-semantic-warning"
                  >
                    {x.title}
                    {x.waiting_on ? ` · ${x.waiting_on}` : ''}
                  </button>
                ))}
            </span>
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default DeliveryRiskPanel;
