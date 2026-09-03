// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * What is attached to each programme activity, worked out in one pure pass.
 *
 * Two different links feed this, and they are stored in two different places
 * for a reason worth writing down:
 *
 * - A **work request** carries `schedule_activity_id` itself. That field is
 *   the work-requests module's own, it is PATCHable, and it is the canonical
 *   answer to "which activity does this request feed".
 *
 * - A **standup task** has no such field. Its link is a `(link_kind, link_ref,
 *   link_target_id)` triple whose `link_kind` is validated server-side against
 *   a closed vocabulary - the register kinds plus `request` - and there is no
 *   `activity` kind in it. An empty kind is not a loophole either: the board
 *   service blanks the whole triple when the kind or the ref is empty. So the
 *   schedule stores its own side of that link, on its own row, in the
 *   activity's `metadata.standup_task_ids` (a shallow-merged JSON column, so
 *   writing the key keeps every sibling key). Nothing in the standup module
 *   changes and nothing here pretends to a contract it does not have.
 *
 * - A task linked to a **request** that is itself on the activity counts too,
 *   transitively. That link the board *can* express, it is the common way a
 *   task actually reaches a programme activity in practice, and reading it
 *   costs nothing.
 *
 * Everything below is a pure function of data already fetched.
 */

import type { Activity } from './api';
import type { DeliveryBoard, DeliveryRequest, DeliveryStage, DeliveryTask } from './deliveryApi';

/** The activity-metadata key holding directly linked standup task ids. */
export const TASK_IDS_META_KEY = 'standup_task_ids';

/** Statuses a request is finished in - they stop counting as late or open. */
const CLOSED_STATUSES = new Set(['complete', 'closed', 'cancelled']);

export function isRequestClosed(r: DeliveryRequest): boolean {
  return CLOSED_STATUSES.has(String(r.status || '').toLowerCase());
}

/** Hours logged, whichever of the two spellings the server used. */
export function loggedHoursOf(r: DeliveryRequest): number {
  const v = r.hours_logged ?? r.logged_hours ?? 0;
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

export function quotedHoursOf(r: DeliveryRequest): number {
  const v = r.quoted_hours ?? 0;
  return typeof v === 'number' && Number.isFinite(v) ? v : 0;
}

/** A request is late when the server says so and it has not been closed out. */
export function isRequestLate(r: DeliveryRequest): boolean {
  return r.is_late === true && !isRequestClosed(r);
}

/**
 * Directly linked standup task ids, read defensively off activity metadata.
 *
 * Metadata is free-form JSON written by several producers, so anything that
 * is not a list of non-empty strings reads as "no links" rather than throwing
 * on a render pass.
 */
export function linkedTaskIds(activity: Pick<Activity, 'metadata'>): string[] {
  const raw = (activity.metadata as Record<string, unknown> | null | undefined)?.[TASK_IDS_META_KEY];
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const v of raw) {
    if (typeof v === 'string' && v.trim() && !out.includes(v)) out.push(v);
  }
  return out;
}

/** The stage ids that mean "done", for this project's board (overrides included). */
export function doneStageIds(board: DeliveryBoard | null | undefined, projectId: string): Set<string> {
  const stages: DeliveryStage[] = board?.stage_overrides?.[projectId] ?? board?.stages ?? [];
  const out = new Set<string>();
  for (const s of stages) if (s.is_done) out.add(s.id);
  return out;
}

export function isTaskDone(task: DeliveryTask, done: Set<string>): boolean {
  return !!task.completed_at || done.has(task.stage_id);
}

/** Waiting on someone is the board's own word for blocked. */
export function isTaskBlocked(task: DeliveryTask, done: Set<string>): boolean {
  return !!task.waiting_on && !isTaskDone(task, done);
}

/** Due before today and not finished. `today` is an ISO `YYYY-MM-DD`. */
export function isTaskLate(task: DeliveryTask, done: Set<string>, today: string): boolean {
  if (!task.due || isTaskDone(task, done)) return false;
  return task.due.slice(0, 10) < today;
}

/** One activity's attachments, and what they add up to. */
export interface ActivityDelivery {
  requests: DeliveryRequest[];
  tasks: DeliveryTask[];
  /** Tasks reached through a linked request rather than pinned to the activity. */
  indirectTaskIds: Set<string>;
  quotedHours: number;
  loggedHours: number;
  lateRequests: number;
  lateTasks: number;
  blockedTasks: number;
  /** Anything attached is late or blocked - the row flag. */
  atRisk: boolean;
}

export type DeliveryIndex = Record<string, ActivityDelivery>;

export function emptyDelivery(): ActivityDelivery {
  return {
    requests: [],
    tasks: [],
    indirectTaskIds: new Set(),
    quotedHours: 0,
    loggedHours: 0,
    lateRequests: 0,
    lateTasks: 0,
    blockedTasks: 0,
    atRisk: false,
  };
}

/**
 * Build the activity -> attachments index.
 *
 * Only activities in `activities` get an entry: a request pointing at an
 * activity on another schedule is not this programme's business, and silently
 * inventing a row for it would be worse than dropping it.
 */
export function buildDeliveryIndex(input: {
  activities: Array<Pick<Activity, 'id' | 'metadata'>>;
  requests: DeliveryRequest[];
  tasks: DeliveryTask[];
  doneStages: Set<string>;
  today: string;
}): DeliveryIndex {
  const { activities, requests, tasks, doneStages, today } = input;
  const index: DeliveryIndex = {};
  const wantedTaskIds = new Map<string, string>(); // task id -> activity id
  for (const a of activities) {
    index[a.id] = emptyDelivery();
    for (const tid of linkedTaskIds(a)) wantedTaskIds.set(tid, a.id);
  }

  // Requests first: they also decide which tasks come along transitively.
  const activityByRequestId = new Map<string, string>();
  for (const r of requests) {
    const aid = r.schedule_activity_id;
    if (!aid || !index[aid]) continue;
    index[aid].requests.push(r);
    activityByRequestId.set(r.id, aid);
  }

  for (const task of tasks) {
    const direct = wantedTaskIds.get(task.id);
    const viaRequest =
      task.link_kind === 'request' && task.link_target_id
        ? activityByRequestId.get(task.link_target_id)
        : undefined;
    const aid = direct ?? viaRequest;
    if (!aid || !index[aid]) continue;
    if (index[aid].tasks.some((t) => t.id === task.id)) continue;
    index[aid].tasks.push(task);
    if (!direct) index[aid].indirectTaskIds.add(task.id);
  }

  for (const entry of Object.values(index)) {
    for (const r of entry.requests) {
      entry.quotedHours += quotedHoursOf(r);
      entry.loggedHours += loggedHoursOf(r);
      if (isRequestLate(r)) entry.lateRequests += 1;
    }
    for (const t of entry.tasks) {
      if (isTaskLate(t, doneStages, today)) entry.lateTasks += 1;
      if (isTaskBlocked(t, doneStages)) entry.blockedTasks += 1;
    }
    entry.atRisk = entry.lateRequests + entry.lateTasks + entry.blockedTasks > 0;
  }
  return index;
}

/** Activities carrying a late or blocked attachment, worst first. */
export function atRiskActivities(
  index: DeliveryIndex,
  activities: Array<Pick<Activity, 'id' | 'name' | 'wbs_code' | 'start_date' | 'end_date'>>,
): Array<{ activity: (typeof activities)[number]; delivery: ActivityDelivery }> {
  const rows = activities
    .map((activity) => ({ activity, delivery: index[activity.id] }))
    .filter((row): row is { activity: (typeof activities)[number]; delivery: ActivityDelivery } =>
      Boolean(row.delivery?.atRisk),
    );
  rows.sort((a, b) => {
    const score = (d: ActivityDelivery) => d.lateRequests * 2 + d.lateTasks * 2 + d.blockedTasks;
    return score(b.delivery) - score(a.delivery);
  });
  return rows;
}

/** `"2 requests · 1 task"`, or `''` when nothing is attached. */
export function summaryLabel(
  d: ActivityDelivery,
  plural: (n: number, one: string, many: string) => string,
): string {
  const bits: string[] = [];
  if (d.requests.length) bits.push(plural(d.requests.length, 'request', 'requests'));
  if (d.tasks.length) bits.push(plural(d.tasks.length, 'task', 'tasks'));
  return bits.join(' · ');
}
