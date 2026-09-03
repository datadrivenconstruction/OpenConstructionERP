// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The schedule's read-mostly window onto the delivery modules.
 *
 * The 4D programme is where a job is *planned*; work requests and the daily
 * standup board are where it is actually *done*. This file is the only place
 * the schedule feature talks to either, and it deliberately re-declares the
 * handful of fields it reads rather than importing the modules' own clients:
 *
 * - Those modules are optional installs. Importing their api.ts would pull
 *   their code into the schedule bundle and make a missing module a build
 *   concern instead of a runtime one.
 * - A narrow local type is a written record of exactly which fields the
 *   schedule depends on, so a field the modules drop breaks a type-check here
 *   instead of quietly rendering blank chips.
 *
 * Nothing here catches anything: a module that is not installed answers 404 and
 * that rejection travels up to `useDelivery`, which is the one place that
 * decides what an unanswered module means for the screen.
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';

const WR = '/v1/work-requests';
const TS = '/v1/team-standup';

/* ── Work requests ────────────────────────────────────────────────────── */

/** The slice of a work request the programme shows. */
export interface DeliveryRequest {
  id: string;
  reference: string;
  title: string;
  project_id: string;
  department: string;
  department_name?: string;
  stage_name?: string | null;
  status: string;
  ball_in_court?: string;
  due_date?: string | null;
  quoted_hours?: number | null;
  /** The module spells the logged total `hours_logged`; both are read. */
  hours_logged?: number | null;
  logged_hours?: number | null;
  hours_at_completion?: number | null;
  is_late?: boolean;
  days_late?: number | null;
  /** The link this whole feature hangs off. Written by `linkRequestToActivity`. */
  schedule_activity_id?: string | null;
  boq_position_ids?: string[];
}

export interface DeliveryDepartment {
  key: string;
  name: string;
  colour: string;
}

/**
 * Every request on a project, closed ones included.
 *
 * Closed requests are asked for on purpose: an activity's hours roll-up is a
 * lie without the finished work, and a completed request still explains why a
 * bar moved. The list caps at 500, matching the module's own screens.
 */
export function fetchProjectRequests(projectId: string): Promise<DeliveryRequest[]> {
  return apiGet<DeliveryRequest[]>(
    `${WR}/requests?project_id=${encodeURIComponent(projectId)}&include_closed=true&limit=500`,
  );
}

export function fetchDepartments(): Promise<DeliveryDepartment[]> {
  return apiGet<DeliveryDepartment[]>(`${WR}/departments`);
}

/** Attach (or, with `null`, detach) a request to a programme activity. */
export function linkRequestToActivity(
  requestId: string,
  activityId: string | null,
): Promise<DeliveryRequest> {
  return apiPatch<DeliveryRequest, { schedule_activity_id: string | null }>(
    `${WR}/requests/${encodeURIComponent(requestId)}`,
    { schedule_activity_id: activityId },
  );
}

/**
 * The module's own raise deep-link, with the activity carried alongside.
 *
 * `?raise=1&project=` is the shape the project hub already sends and the one
 * the work-requests page reads today. The activity parameters ride with it so
 * the dialog can prefill from them the day it learns to; until then the
 * schedule links the created request itself, which is why this is a
 * convenience and not the mechanism.
 */
export function raiseRequestHref(
  projectId: string,
  activity: { id: string; name: string; start_date?: string; end_date?: string },
): string {
  const p = new URLSearchParams({
    raise: '1',
    project: projectId,
    schedule_activity_id: activity.id,
    title: activity.name,
  });
  if (activity.start_date) p.set('scheduled_start', activity.start_date.slice(0, 10));
  if (activity.end_date) p.set('scheduled_end', activity.end_date.slice(0, 10));
  return `/work-requests?${p.toString()}`;
}

/* ── Standup board ────────────────────────────────────────────────────── */

export interface DeliveryTask {
  id: string;
  title: string;
  project_id: string;
  stage_id: string;
  assignee_id?: string;
  assignee_name?: string;
  due?: string;
  waiting_on?: string;
  link_kind?: string;
  link_ref?: string;
  link_target_id?: string;
  completed_at?: string | null;
}

export interface DeliveryStage {
  id: string;
  name: string;
  color?: string;
  is_done?: boolean;
}

export interface DeliveryBoard {
  day: string;
  today?: string;
  stages: DeliveryStage[];
  stage_overrides?: Record<string, DeliveryStage[]>;
  tasks: DeliveryTask[];
}

export function fetchStandupBoard(day: string): Promise<DeliveryBoard> {
  return apiGet<DeliveryBoard>(`${TS}/full-board?day=${encodeURIComponent(day)}`);
}

export interface StandupTaskWrite {
  title: string;
  project_id: string;
  due?: string;
  notes?: string;
  link_kind?: string;
  link_ref?: string;
  link_target_id?: string;
}

export function createStandupTask(task: StandupTaskWrite): Promise<DeliveryTask[]> {
  return apiPost<DeliveryTask[], { tasks: StandupTaskWrite[] }>(`${TS}/tasks`, { tasks: [task] });
}

/** Today as `YYYY-MM-DD` in the viewer's own timezone (the board is day-keyed). */
export function todayIso(): string {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}
