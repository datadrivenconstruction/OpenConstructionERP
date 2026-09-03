// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The programme's "Delivery" cell: what is actually attached to an activity.
 *
 * A bar on a Gantt says when work is *meant* to happen. This cell says what
 * has been raised against it and what state that work is in - so a workshop
 * build running four weeks late is visible on the programme row rather than
 * buried three clicks deep in another module.
 *
 * Chips are deliberately terse (a reference, a colour, a warning) and carry
 * the full sentence in a `title`. Clicking one opens the record it names.
 */

import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { AlertTriangle, CheckSquare, Link2, PauseCircle } from 'lucide-react';
import type { ActivityDelivery } from './delivery';
import { isRequestLate, isTaskBlocked, isTaskDone, isTaskLate } from './delivery';

const CHIP =
  'inline-flex max-w-full items-center gap-1 rounded-full border px-1.5 py-0.5 text-[10px] ' +
  'font-medium leading-none transition-colors';

export interface DeliveryCellProps {
  activityId: string;
  delivery: ActivityDelivery;
  /** Stage ids that count as done on this project's board. */
  doneStages: Set<string>;
  today: string;
  departmentColour: (key: string) => string | undefined;
  onOpenLinks: (activityId: string) => void;
  /** Neither module answered - the cell should not claim "nothing linked". */
  disabled?: boolean;
}

export function DeliveryCell({
  activityId,
  delivery,
  doneStages,
  today,
  departmentColour,
  onOpenLinks,
  disabled = false,
}: DeliveryCellProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();

  if (disabled) return null;

  const hours =
    delivery.quotedHours > 0 || delivery.loggedHours > 0
      ? `${Math.round(delivery.loggedHours)}/${Math.round(delivery.quotedHours)} h`
      : '';

  // Singular and plural are separate keys rather than one `count` string:
  // the fallback `defaultValue` a translation-less deployment falls back to
  // is not pluralised by i18next, and "1 requests" on every single-request
  // activity is exactly the kind of small wrongness people stop trusting.
  const counts: string[] = [];
  const n = delivery.requests.length;
  const m = delivery.tasks.length;
  if (n)
    counts.push(
      n === 1
        ? t('schedule.delivery.one_request', { defaultValue: '1 request' })
        : t('schedule.delivery.n_requests', { count: n, defaultValue: '{{count}} requests' }),
    );
  if (m)
    counts.push(
      m === 1
        ? t('schedule.delivery.one_task', { defaultValue: '1 task' })
        : t('schedule.delivery.n_tasks', { count: m, defaultValue: '{{count}} tasks' }),
    );

  return (
    <div className="flex flex-col gap-1" data-testid={`delivery-cell-${activityId}`}>
      <div className="flex flex-wrap items-center gap-1">
        {delivery.requests.map((r) => {
          const late = isRequestLate(r);
          const colour = departmentColour(r.department);
          return (
            <button
              key={r.id}
              type="button"
              data-testid={`delivery-request-${r.id}`}
              onClick={() => navigate(`/work-requests/${r.id}`)}
              title={[
                r.reference,
                r.title,
                r.department_name || r.department,
                r.stage_name || r.status,
                late
                  ? t('schedule.delivery.late_by', {
                      count: r.days_late ?? 0,
                      defaultValue: '{{count}} days late',
                    })
                  : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              className={`${CHIP} ${
                late
                  ? 'border-semantic-error/50 bg-semantic-error/10 text-semantic-error hover:bg-semantic-error/20'
                  : 'border-border-light bg-surface-secondary/60 text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue'
              }`}
            >
              <span
                aria-hidden
                className="h-2 w-2 shrink-0 rounded-full"
                style={{ backgroundColor: colour || 'var(--oe-blue, #2563eb)' }}
              />
              <span className="truncate">{r.reference || r.title}</span>
              {late && <AlertTriangle size={10} className="shrink-0" />}
            </button>
          );
        })}

        {delivery.tasks.map((task) => {
          const late = isTaskLate(task, doneStages, today);
          const blocked = isTaskBlocked(task, doneStages);
          const done = isTaskDone(task, doneStages);
          return (
            <button
              key={task.id}
              type="button"
              data-testid={`delivery-task-${task.id}`}
              onClick={() => navigate('/team-standup')}
              title={[
                task.title,
                task.assignee_name,
                task.due ? t('schedule.delivery.due', { defaultValue: 'due {{d}}', d: task.due }) : '',
                blocked
                  ? t('schedule.delivery.waiting_on', {
                      defaultValue: 'waiting on {{who}}',
                      who: task.waiting_on,
                    })
                  : '',
                delivery.indirectTaskIds.has(task.id)
                  ? t('schedule.delivery.via_request', {
                      defaultValue: 'linked through {{ref}}',
                      ref: task.link_ref,
                    })
                  : '',
              ]
                .filter(Boolean)
                .join(' · ')}
              className={`${CHIP} ${
                late
                  ? 'border-semantic-error/50 bg-semantic-error/10 text-semantic-error hover:bg-semantic-error/20'
                  : blocked
                    ? 'border-semantic-warning/50 bg-semantic-warning/10 text-semantic-warning hover:bg-semantic-warning/20'
                    : 'border-border-light bg-surface-secondary/60 text-content-secondary hover:border-oe-blue/40 hover:text-oe-blue'
              } ${done ? 'opacity-60 line-through' : ''}`}
            >
              {blocked ? (
                <PauseCircle size={10} className="shrink-0" />
              ) : (
                <CheckSquare size={10} className="shrink-0" />
              )}
              <span className="truncate">{task.title}</span>
              {late && <AlertTriangle size={10} className="shrink-0" />}
            </button>
          );
        })}

        <button
          type="button"
          data-testid={`delivery-link-${activityId}`}
          onClick={() => onOpenLinks(activityId)}
          title={t('schedule.delivery.manage', {
            defaultValue: 'Link work requests and standup tasks to this activity',
          })}
          className="inline-flex items-center gap-1 rounded-full border border-dashed border-border-light px-1.5 py-0.5 text-[10px] font-medium leading-none text-content-tertiary transition-colors hover:border-oe-blue/40 hover:text-oe-blue"
        >
          <Link2 size={10} className="shrink-0" />
          {delivery.requests.length + delivery.tasks.length === 0
            ? t('schedule.delivery.link_cta', { defaultValue: 'Link' })
            : t('schedule.delivery.edit_cta', { defaultValue: 'Edit' })}
        </button>
      </div>

      {(counts.length > 0 || hours) && (
        <span
          className="text-[10px] leading-none text-content-tertiary"
          data-testid={`delivery-summary-${activityId}`}
        >
          {[counts.join(' · '), hours].filter(Boolean).join(' · ')}
        </span>
      )}
    </div>
  );
}

export default DeliveryCell;
