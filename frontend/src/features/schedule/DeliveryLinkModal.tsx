// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Attach delivery work to a programme activity.
 *
 * Four actions, all of them starting from the activity the planner is looking
 * at rather than from the other module's list:
 *
 *  - link an existing work request (writes the request's own
 *    `schedule_activity_id`, which is the canonical field);
 *  - raise a NEW work request from the activity, prefilled through the
 *    work-requests module's existing `?raise=1&project=` deep link;
 *  - link an existing standup task (recorded on the activity's metadata -
 *    see `delivery.ts` for why the board cannot carry it);
 *  - create a standup task for the activity and link it in one go.
 *
 * A section whose module did not answer is not rendered. Nothing here guesses.
 */

import { useMemo, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { ExternalLink, Plus, Search } from 'lucide-react';
import { Button, Input, WideModal } from '@/shared/ui';
import { useToastStore } from '@/stores/useToastStore';
import type { Activity } from './api';
import type { ActivityDelivery } from './delivery';
import { isRequestClosed } from './delivery';
import { raiseRequestHref, type DeliveryRequest, type DeliveryTask } from './deliveryApi';
import type { DeliveryWrites } from './useDelivery';

function matches(haystack: Array<string | null | undefined>, needle: string): boolean {
  if (!needle) return true;
  const q = needle.toLowerCase();
  return haystack.some((h) => (h ?? '').toLowerCase().includes(q));
}

export interface DeliveryLinkModalProps {
  open: boolean;
  onClose: () => void;
  activity: Activity;
  projectId: string;
  delivery: ActivityDelivery;
  requests: DeliveryRequest[];
  tasks: DeliveryTask[];
  requestsAvailable: boolean;
  standupAvailable: boolean;
  writes: DeliveryWrites;
}

export function DeliveryLinkModal({
  open,
  onClose,
  activity,
  projectId,
  delivery,
  requests,
  tasks,
  requestsAvailable,
  standupAvailable,
  writes,
}: DeliveryLinkModalProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const addToast = useToastStore((s) => s.addToast);
  const [reqQuery, setReqQuery] = useState('');
  const [taskQuery, setTaskQuery] = useState('');
  const [newTaskTitle, setNewTaskTitle] = useState('');

  const linkedRequestIds = useMemo(
    () => new Set(delivery.requests.map((r) => r.id)),
    [delivery.requests],
  );
  const linkedTaskIdSet = useMemo(() => new Set(delivery.tasks.map((x) => x.id)), [delivery.tasks]);

  // Linked first, then open, then the rest - the rows a planner acts on sit
  // at the top instead of being hunted for in reference order.
  const requestRows = useMemo(() => {
    const rows = requests.filter((r) =>
      matches([r.reference, r.title, r.department_name, r.department, r.stage_name], reqQuery),
    );
    return rows
      .slice()
      .sort((a, b) => {
        const rank = (r: DeliveryRequest) =>
          linkedRequestIds.has(r.id) ? 0 : isRequestClosed(r) ? 2 : 1;
        return rank(a) - rank(b) || (a.reference || '').localeCompare(b.reference || '');
      })
      .slice(0, 60);
  }, [requests, reqQuery, linkedRequestIds]);

  const taskRows = useMemo(() => {
    const rows = tasks.filter((x) => matches([x.title, x.assignee_name, x.link_ref], taskQuery));
    return rows
      .slice()
      .sort((a, b) => {
        const rank = (x: DeliveryTask) => (linkedTaskIdSet.has(x.id) ? 0 : 1);
        return rank(a) - rank(b) || (a.title || '').localeCompare(b.title || '');
      })
      .slice(0, 60);
  }, [tasks, taskQuery, linkedTaskIdSet]);

  const fail = (error: unknown) =>
    addToast({
      type: 'error',
      title: t('toasts.error', { defaultValue: 'Error' }),
      message: error instanceof Error ? error.message : String(error),
    });

  const toggleRequest = async (r: DeliveryRequest) => {
    const attach = !linkedRequestIds.has(r.id);
    try {
      await writes.linkRequest(r.id, attach ? activity.id : null);
      addToast({
        type: 'success',
        title: attach
          ? t('schedule.delivery.linked', { defaultValue: 'Linked to this activity' })
          : t('schedule.delivery.unlinked', { defaultValue: 'Link removed' }),
        message: r.reference,
      });
    } catch (error) {
      fail(error);
    }
  };

  const toggleTask = async (x: DeliveryTask) => {
    const attach = !linkedTaskIdSet.has(x.id);
    try {
      await writes.linkTask(activity, x.id, attach);
    } catch (error) {
      fail(error);
    }
  };

  const createTask = async () => {
    const title = newTaskTitle.trim() || activity.name;
    try {
      await writes.createTaskForActivity(activity, {
        title,
        project_id: projectId,
        due: activity.end_date?.slice(0, 10),
        notes: t('schedule.delivery.task_note', {
          defaultValue: 'Raised from programme activity {{wbs}} {{name}}',
          wbs: activity.wbs_code || '',
          name: activity.name,
        }),
      });
      setNewTaskTitle('');
      addToast({
        type: 'success',
        title: t('schedule.delivery.task_created', { defaultValue: 'Task added to the board' }),
        message: title,
      });
    } catch (error) {
      fail(error);
    }
  };

  return (
    <WideModal
      open={open}
      onClose={onClose}
      busy={writes.pending}
      testId="delivery-link-modal"
      size="lg"
      title={t('schedule.delivery.modal_title', { defaultValue: 'Delivery for this activity' })}
      subtitle={`${activity.wbs_code ? `${activity.wbs_code} · ` : ''}${activity.name}`}
      footer={
        <Button variant="secondary" onClick={onClose}>
          {t('common.close', { defaultValue: 'Close' })}
        </Button>
      }
    >
      <div className="space-y-6">
        {requestsAvailable && (
          <section>
            <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
              <h3 className="text-sm font-semibold text-content-primary">
                {t('schedule.delivery.requests_heading', { defaultValue: 'Work requests' })}
              </h3>
              <Button
                variant="secondary"
                size="sm"
                icon={<ExternalLink size={14} />}
                data-testid="delivery-raise-request"
                onClick={() => navigate(raiseRequestHref(projectId, activity))}
              >
                {t('schedule.delivery.raise_cta', {
                  defaultValue: 'Raise a work request from this activity',
                })}
              </Button>
            </div>
            <Input
              value={reqQuery}
              onChange={(e) => setReqQuery(e.target.value)}
              placeholder={t('schedule.delivery.search_requests', {
                defaultValue: 'Search requests by reference, title or department',
              })}
              data-testid="delivery-request-search"
              icon={<Search size={14} />}
            />
            <ul className="mt-2 max-h-56 divide-y divide-border-light overflow-y-auto rounded-lg border border-border-light">
              {requestRows.length === 0 ? (
                <li className="px-3 py-3 text-xs text-content-tertiary">
                  {t('schedule.delivery.no_requests', {
                    defaultValue: 'No work requests match on this project.',
                  })}
                </li>
              ) : (
                requestRows.map((r) => {
                  const linked = linkedRequestIds.has(r.id);
                  const elsewhere = !linked && !!r.schedule_activity_id;
                  return (
                    <li key={r.id} className="flex items-center gap-2 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-content-primary">
                          {r.reference} · {r.title}
                        </div>
                        <div className="truncate text-2xs text-content-tertiary">
                          {[r.department_name || r.department, r.stage_name || r.status]
                            .filter(Boolean)
                            .join(' · ')}
                          {elsewhere &&
                            ` · ${t('schedule.delivery.on_other_activity', {
                              defaultValue: 'currently on another activity',
                            })}`}
                        </div>
                      </div>
                      <Button
                        variant={linked ? 'secondary' : 'primary'}
                        size="sm"
                        disabled={writes.pending}
                        data-testid={`delivery-toggle-request-${r.id}`}
                        onClick={() => void toggleRequest(r)}
                      >
                        {linked
                          ? t('schedule.delivery.unlink', { defaultValue: 'Unlink' })
                          : t('schedule.delivery.link', { defaultValue: 'Link' })}
                      </Button>
                    </li>
                  );
                })
              )}
            </ul>
          </section>
        )}

        {standupAvailable && (
          <section>
            <h3 className="mb-2 text-sm font-semibold text-content-primary">
              {t('schedule.delivery.tasks_heading', { defaultValue: 'Standup tasks' })}
            </h3>
            <div className="flex flex-wrap items-end gap-2">
              <div className="min-w-[200px] flex-1">
                <Input
                  value={newTaskTitle}
                  onChange={(e) => setNewTaskTitle(e.target.value)}
                  placeholder={activity.name}
                  data-testid="delivery-new-task-title"
                  label={t('schedule.delivery.new_task_label', {
                    defaultValue: 'Create a standup task for this activity',
                  })}
                />
              </div>
              <Button
                variant="primary"
                size="sm"
                icon={<Plus size={14} />}
                disabled={writes.pending}
                data-testid="delivery-create-task"
                onClick={() => void createTask()}
              >
                {t('schedule.delivery.create_task', { defaultValue: 'Add task' })}
              </Button>
            </div>
            <div className="mt-3">
              <Input
                value={taskQuery}
                onChange={(e) => setTaskQuery(e.target.value)}
                placeholder={t('schedule.delivery.search_tasks', {
                  defaultValue: 'Search the board for a task to link',
                })}
                data-testid="delivery-task-search"
                icon={<Search size={14} />}
              />
            </div>
            <ul className="mt-2 max-h-56 divide-y divide-border-light overflow-y-auto rounded-lg border border-border-light">
              {taskRows.length === 0 ? (
                <li className="px-3 py-3 text-xs text-content-tertiary">
                  {t('schedule.delivery.no_tasks', {
                    defaultValue: 'No tasks on this job match.',
                  })}
                </li>
              ) : (
                taskRows.map((x) => {
                  const linked = linkedTaskIdSet.has(x.id);
                  const indirect = delivery.indirectTaskIds.has(x.id);
                  return (
                    <li key={x.id} className="flex items-center gap-2 px-3 py-2">
                      <div className="min-w-0 flex-1">
                        <div className="truncate text-xs font-medium text-content-primary">
                          {x.title}
                        </div>
                        <div className="truncate text-2xs text-content-tertiary">
                          {[x.assignee_name, x.due, x.waiting_on].filter(Boolean).join(' · ')}
                          {indirect &&
                            ` · ${t('schedule.delivery.via_request', {
                              defaultValue: 'linked through {{ref}}',
                              ref: x.link_ref,
                            })}`}
                        </div>
                      </div>
                      <Button
                        variant={linked ? 'secondary' : 'primary'}
                        size="sm"
                        // A task that reaches this activity through a request
                        // is not the schedule's link to remove - it would come
                        // straight back on the next read.
                        disabled={writes.pending || (linked && indirect)}
                        data-testid={`delivery-toggle-task-${x.id}`}
                        onClick={() => void toggleTask(x)}
                      >
                        {linked
                          ? t('schedule.delivery.unlink', { defaultValue: 'Unlink' })
                          : t('schedule.delivery.link', { defaultValue: 'Link' })}
                      </Button>
                    </li>
                  );
                })
              )}
            </ul>
          </section>
        )}
      </div>
    </WideModal>
  );
}

export default DeliveryLinkModal;
