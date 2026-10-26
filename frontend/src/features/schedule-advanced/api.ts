// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Schedule Advanced (Last Planner / CPM) module.
 *
 * Backed by /api/v1/schedule-advanced/ — see
 * backend/app/modules/schedule_advanced/router.py
 */

import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type MasterStatus = 'active' | 'archived';
export type PhaseStatus = 'in_planning' | 'pulled' | 'active' | 'completed';
export type LookAheadStatus = 'draft' | 'reviewed' | 'published';
export type ConstraintType =
  | 'info'
  | 'material'
  | 'labor'
  | 'equipment'
  | 'permit'
  | 'predecessor'
  | 'weather'
  | 'other';
export type ConstraintStatus =
  | 'open'
  | 'in_progress'
  | 'cleared'
  | 'escalated'
  | 'cannot_clear';
export type CommitmentStatus =
  | 'planned'
  | 'committed'
  | 'in_progress'
  | 'completed'
  | 'at_risk'
  | 'missed';
export type WeeklyStatus = 'draft' | 'committed' | 'in_progress' | 'closed';
export type BaselineStatus = 'active' | 'superseded' | 'archived';
export type RNCCategory =
  | 'manpower'
  | 'material'
  | 'equipment'
  | 'info'
  | 'weather'
  | 'predecessor'
  | 'changes'
  | 'quality'
  | 'other';

export interface MasterSchedule {
  id: string;
  project_id: string;
  name: string;
  baseline_date?: string | null;
  planned_start?: string | null;
  planned_finish?: string | null;
  status: MasterStatus;
  notes: string;
  created_by?: string | null;
  created_at: string;
  updated_at: string;
}

export interface PhasePlan {
  id: string;
  master_schedule_id: string;
  name: string;
  planned_start?: string | null;
  planned_finish?: string | null;
  milestone_target_id?: string | null;
  pulled_status: PhaseStatus;
  pull_session_at?: string | null;
  facilitator_id?: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface LookAheadPlan {
  id: string;
  master_schedule_id: string;
  period_start: string;
  period_end: string;
  window_weeks: number;
  generated_at?: string | null;
  status: LookAheadStatus;
  created_at: string;
  updated_at: string;
}

export type ConstraintLinkedType = 'rfi' | 'submittal' | 'purchase_order' | 'goods_receipt';

export interface Constraint {
  linked_type?: ConstraintLinkedType | null;
  linked_id?: string | null;
  id: string;
  look_ahead_id?: string | null;
  task_ref: string;
  constraint_type: ConstraintType;
  description: string;
  owner_user_id?: string | null;
  target_clear_date?: string | null;
  cleared_at?: string | null;
  cleared_by?: string | null;
  status: ConstraintStatus;
  created_at: string;
  updated_at: string;
}

export interface WeeklyWorkPlan {
  id: string;
  master_schedule_id: string;
  week_start_date: string;
  week_end_date: string;
  generated_at?: string | null;
  facilitator_id?: string | null;
  status: WeeklyStatus;
  ppc_percent?: string | number | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface Commitment {
  id: string;
  week_plan_id: string;
  task_ref: string;
  worker_or_crew: string;
  subcontractor_id?: string | null;
  target_progress_pct?: string | number | null;
  promised_qty: string | number;
  unit: string;
  planned_start?: string | null;
  planned_finish?: string | null;
  status: CommitmentStatus;
  made_by_user_id?: string | null;
  made_at?: string | null;
  completed_at?: string | null;
  actual_qty?: string | number | null;
  created_at: string;
  updated_at: string;
}

export interface RNC {
  id: string;
  commitment_id: string;
  category: RNCCategory;
  description: string;
  recorded_at?: string | null;
  recorded_by?: string | null;
  root_cause_notes: string;
  created_at: string;
  updated_at: string;
}

export interface Baseline {
  id: string;
  master_schedule_id: string;
  name: string;
  captured_at?: string | null;
  captured_by?: string | null;
  snapshot: Record<string, unknown> | Array<Record<string, unknown>>;
  notes: string;
  status: BaselineStatus;
  created_at: string;
  updated_at: string;
}

export interface BaselineDeltaEntry {
  task_ref: string;
  planned_start_baseline?: string | null;
  planned_start_current?: string | null;
  planned_finish_baseline?: string | null;
  planned_finish_current?: string | null;
  schedule_variance_days: number;
  /**
   * Display name of the task at baseline-capture time. Carried through
   * the snapshot row so the UI can render "Foundation +5d" instead of
   * the raw UUID. Populated when :func:`captureBaseline` auto-snapshots
   * phases (see ``captureBaseline``).
   */
  name?: string | null;
}

export interface BaselineDelta {
  baseline_id: string;
  current_master_id: string;
  entries: BaselineDeltaEntry[];
  total_tasks: number;
  delayed_tasks: number;
  accelerated_tasks: number;
}

export interface ScheduleCalendar {
  id: string;
  project_id: string;
  name: string;
  work_days: number[];
  work_hours_per_day: string | number;
  holidays: string[];
  special_shifts: Record<string, unknown>;
  is_default: boolean;
  created_at: string;
  updated_at: string;
}

export interface PPC {
  week_start_date?: string | null;
  total_commitments: number;
  completed_commitments: number;
  ppc_percent: string | number;
}

export interface LPSDashboard {
  project_id: string;
  ppc_trend: PPC[];
  open_constraints: number;
  constraints_by_type: Record<string, number>;
  rnc_pareto: Record<string, number>;
  active_master_schedules: number;
  active_baselines: number;
  current_week_commitments: number;
}

/* ── Master schedules ─────────────────────────────────────────────────── */

export function listMasterSchedules(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<MasterSchedule[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<MasterSchedule[]>(
    `/v1/schedule-advanced/master-schedules/?${qs.toString()}`,
  );
}

export function createMasterSchedule(data: {
  project_id: string;
  name: string;
  planned_start?: string;
  planned_finish?: string;
  notes?: string;
}): Promise<MasterSchedule> {
  return apiPost<MasterSchedule>(
    '/v1/schedule-advanced/master-schedules/',
    data,
  );
}

export function updateMasterSchedule(
  masterId: string,
  data: {
    name?: string;
    planned_start?: string | null;
    planned_finish?: string | null;
    baseline_date?: string | null;
    status?: MasterStatus;
    notes?: string | null;
  },
): Promise<MasterSchedule> {
  return apiPatch<MasterSchedule>(
    `/v1/schedule-advanced/master-schedules/${masterId}`,
    data,
  );
}

export function deleteMasterSchedule(masterId: string): Promise<void> {
  return apiDelete(`/v1/schedule-advanced/master-schedules/${masterId}`);
}

export function projectDashboard(projectId: string): Promise<LPSDashboard> {
  return apiGet<LPSDashboard>(
    `/v1/schedule-advanced/dashboard/project/${projectId}`,
  );
}

/* ── Named work calendars (#348) ──────────────────────────────────────────
 *
 * Project-scoped named work calendars: a work-week (``work_days`` as Mon=0 ..
 * Sun=6), hours per day and a holiday list (ISO dates). One calendar per
 * project may be the default; individual activities can override it through
 * ``scheduleApi.setActivityCalendar`` (schedule module). The working-day
 * duration math the schedule uses honours whichever calendar applies, so a
 * calendar edit / assignment is followed by a reschedule at the call site.
 * Backed by /v1/schedule-advanced/calendars/.
 */

/** Body for creating a named work calendar (``project_id`` is required). */
export interface ScheduleCalendarCreateBody {
  project_id: string;
  name: string;
  /** Working weekdays as ints, Mon=0 .. Sun=6. */
  work_days: number[];
  work_hours_per_day?: number;
  /** Non-working ISO dates (YYYY-MM-DD). */
  holidays?: string[];
  is_default?: boolean;
}

/** Partial update for a named work calendar. */
export interface ScheduleCalendarUpdateBody {
  name?: string;
  work_days?: number[];
  work_hours_per_day?: number;
  holidays?: string[];
  is_default?: boolean;
}

/** List the project's named work calendars. */
export function listCalendars(projectId: string): Promise<ScheduleCalendar[]> {
  return apiGet<ScheduleCalendar[]>(
    `/v1/schedule-advanced/calendars/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Create a named work calendar in the project. */
export function createCalendar(
  body: ScheduleCalendarCreateBody,
): Promise<ScheduleCalendar> {
  return apiPost<ScheduleCalendar, ScheduleCalendarCreateBody>(
    '/v1/schedule-advanced/calendars/',
    body,
  );
}

/** Patch a named work calendar (partial update). */
export function updateCalendar(
  calendarId: string,
  patch: ScheduleCalendarUpdateBody,
): Promise<ScheduleCalendar> {
  return apiPatch<ScheduleCalendar, ScheduleCalendarUpdateBody>(
    `/v1/schedule-advanced/calendars/${encodeURIComponent(calendarId)}`,
    patch,
  );
}

/** Delete a named work calendar. */
export function deleteCalendar(calendarId: string): Promise<void> {
  return apiDelete(
    `/v1/schedule-advanced/calendars/${encodeURIComponent(calendarId)}`,
  );
}

/* ── Phase plans ──────────────────────────────────────────────────────── */

export function listPhasePlans(masterScheduleId: string): Promise<PhasePlan[]> {
  return apiGet<PhasePlan[]>(
    `/v1/schedule-advanced/phase-plans/?master_schedule_id=${encodeURIComponent(
      masterScheduleId,
    )}`,
  );
}

export function createPhasePlan(data: {
  master_schedule_id: string;
  name: string;
  planned_start?: string;
  planned_finish?: string;
  notes?: string;
  pulled_status?: PhaseStatus;
}): Promise<PhasePlan> {
  return apiPost<PhasePlan>('/v1/schedule-advanced/phase-plans/', data);
}

export function updatePhasePlan(
  phaseId: string,
  data: {
    name?: string;
    planned_start?: string | null;
    planned_finish?: string | null;
    notes?: string | null;
  },
): Promise<PhasePlan> {
  return apiPatch<PhasePlan>(
    `/v1/schedule-advanced/phase-plans/${phaseId}`,
    data,
  );
}

export function deletePhasePlan(phaseId: string): Promise<void> {
  return apiDelete(`/v1/schedule-advanced/phase-plans/${phaseId}`);
}

/**
 * Standard construction-phase templates. Day-counts are conservative
 * defaults — users edit each phase after seeding.
 */
export const PHASE_TEMPLATES: Record<
  'residential' | 'commercial' | 'infrastructure',
  { name: string; days: number }[]
> = {
  residential: [
    { name: 'Site preparation', days: 14 },
    { name: 'Foundation', days: 28 },
    { name: 'Structure', days: 56 },
    { name: 'Roofing', days: 14 },
    { name: 'MEP rough-in', days: 35 },
    { name: 'Drywall and finishes', days: 42 },
    { name: 'Handover', days: 7 },
  ],
  commercial: [
    { name: 'Demolition', days: 14 },
    { name: 'Site preparation', days: 21 },
    { name: 'Foundation', days: 42 },
    { name: 'Structure', days: 90 },
    { name: 'Building envelope', days: 35 },
    { name: 'MEP rough-in', days: 56 },
    { name: 'Interior fit-out', days: 70 },
    { name: 'Commissioning', days: 21 },
    { name: 'Handover', days: 7 },
  ],
  infrastructure: [
    { name: 'Site survey and clearing', days: 21 },
    { name: 'Earthworks', days: 56 },
    { name: 'Subgrade and drainage', days: 42 },
    { name: 'Base layers', days: 28 },
    { name: 'Surfacing', days: 21 },
    { name: 'Signage and markings', days: 14 },
    { name: 'Final inspection', days: 7 },
  ],
};

/**
 * Seed the standard construction phases for a master schedule in one call.
 * Used by the "Apply template" affordance on the Phase Plans tab.
 */
export async function applyPhaseTemplate(
  masterScheduleId: string,
  template: keyof typeof PHASE_TEMPLATES,
  planStart?: string,
): Promise<PhasePlan[]> {
  const phases = PHASE_TEMPLATES[template];
  const startBase = planStart ? new Date(planStart) : new Date();
  const created: PhasePlan[] = [];
  let cursor = new Date(startBase);
  for (const p of phases) {
    const phaseStart = new Date(cursor);
    const phaseEnd = new Date(cursor);
    phaseEnd.setDate(phaseEnd.getDate() + p.days);
    const c = await createPhasePlan({
      master_schedule_id: masterScheduleId,
      name: p.name,
      planned_start: phaseStart.toISOString().slice(0, 10),
      planned_finish: phaseEnd.toISOString().slice(0, 10),
    });
    created.push(c);
    cursor = phaseEnd;
  }
  return created;
}

export function pullPhase(phaseId: string): Promise<PhasePlan> {
  return apiPost<PhasePlan>(
    `/v1/schedule-advanced/phase-plans/${phaseId}/pull`,
    {},
  );
}

export function startPhase(phaseId: string): Promise<PhasePlan> {
  return apiPost<PhasePlan>(
    `/v1/schedule-advanced/phase-plans/${phaseId}/start`,
    {},
  );
}

export function completePhase(phaseId: string): Promise<PhasePlan> {
  return apiPost<PhasePlan>(
    `/v1/schedule-advanced/phase-plans/${phaseId}/complete`,
    {},
  );
}

/* ── Look-aheads ──────────────────────────────────────────────────────── */

export function listLookAheads(
  masterScheduleId: string,
): Promise<LookAheadPlan[]> {
  return apiGet<LookAheadPlan[]>(
    `/v1/schedule-advanced/look-aheads/?master_schedule_id=${encodeURIComponent(
      masterScheduleId,
    )}`,
  );
}

export function createLookAhead(data: {
  master_schedule_id: string;
  period_start: string;
  period_end: string;
  window_weeks?: number;
}): Promise<LookAheadPlan> {
  return apiPost<LookAheadPlan>('/v1/schedule-advanced/look-aheads/', data);
}

export function publishLookAhead(lookAheadId: string): Promise<LookAheadPlan> {
  return apiPost<LookAheadPlan>(
    `/v1/schedule-advanced/look-aheads/${lookAheadId}/publish`,
    {},
  );
}

/* ── Constraints ──────────────────────────────────────────────────────── */

export function listConstraints(lookAheadId: string): Promise<Constraint[]> {
  return apiGet<Constraint[]>(
    `/v1/schedule-advanced/constraints/?look_ahead_id=${encodeURIComponent(
      lookAheadId,
    )}`,
  );
}

export function createConstraint(data: {
  look_ahead_id?: string;
  task_ref: string;
  constraint_type: ConstraintType;
  description?: string;
  target_clear_date?: string;
  linked_type?: ConstraintLinkedType;
  linked_id?: string;
}): Promise<Constraint> {
  return apiPost<Constraint>('/v1/schedule-advanced/constraints/', data);
}

export function clearConstraint(id: string): Promise<Constraint> {
  return apiPost<Constraint>(
    `/v1/schedule-advanced/constraints/${id}/clear`,
    {},
  );
}

export function escalateConstraint(id: string): Promise<Constraint> {
  return apiPost<Constraint>(
    `/v1/schedule-advanced/constraints/${id}/escalate`,
    {},
  );
}

export function deleteConstraint(id: string): Promise<void> {
  return apiDelete(`/v1/schedule-advanced/constraints/${id}`);
}

/* ── Weekly work plans + commitments ──────────────────────────────────── */

export function listWeeklyPlans(
  masterScheduleId: string,
  limit = 52,
): Promise<WeeklyWorkPlan[]> {
  return apiGet<WeeklyWorkPlan[]>(
    `/v1/schedule-advanced/weekly-work-plans/?master_schedule_id=${encodeURIComponent(
      masterScheduleId,
    )}&limit=${limit}`,
  );
}

export function createWeeklyPlan(data: {
  master_schedule_id: string;
  week_start_date: string;
  week_end_date: string;
}): Promise<WeeklyWorkPlan> {
  return apiPost<WeeklyWorkPlan>(
    '/v1/schedule-advanced/weekly-work-plans/',
    data,
  );
}

export function commitWeeklyPlan(id: string): Promise<WeeklyWorkPlan> {
  return apiPost<WeeklyWorkPlan>(
    `/v1/schedule-advanced/weekly-work-plans/${id}/commit`,
    {},
  );
}

export function closeWeeklyPlan(id: string): Promise<WeeklyWorkPlan> {
  return apiPost<WeeklyWorkPlan>(
    `/v1/schedule-advanced/weekly-work-plans/${id}/close`,
    {},
  );
}

export function listCommitments(weekPlanId: string): Promise<Commitment[]> {
  return apiGet<Commitment[]>(
    `/v1/schedule-advanced/commitments/?week_plan_id=${encodeURIComponent(
      weekPlanId,
    )}`,
  );
}

export function createCommitment(data: {
  week_plan_id: string;
  task_ref: string;
  worker_or_crew?: string;
  promised_qty?: string;
  unit?: string;
  subcontractor_id?: string;
  target_progress_pct?: string;
}): Promise<Commitment> {
  return apiPost<Commitment>('/v1/schedule-advanced/commitments/', data);
}

export function commitCommitment(id: string): Promise<Commitment> {
  return apiPost<Commitment>(
    `/v1/schedule-advanced/commitments/${id}/commit`,
    {},
  );
}

export function completeCommitment(
  id: string,
  actualQty?: string,
): Promise<Commitment> {
  return apiPost<Commitment>(
    `/v1/schedule-advanced/commitments/${id}/complete`,
    actualQty != null && actualQty !== '' ? { actual_qty: actualQty } : {},
  );
}

/**
 * Mark a commitment missed. The backend requires a paired
 * Reason-for-Non-Completion (LPS RNC) so ``category`` is mandatory.
 */
export function missCommitment(
  id: string,
  rnc: { category: RNCCategory; description?: string; root_cause_notes?: string },
): Promise<Commitment> {
  return apiPost<Commitment>(
    `/v1/schedule-advanced/commitments/${id}/miss`,
    { commitment_id: id, ...rnc },
  );
}

/* ── Baselines ────────────────────────────────────────────────────────── */

export function listBaselines(masterScheduleId: string): Promise<Baseline[]> {
  return apiGet<Baseline[]>(
    `/v1/schedule-advanced/baselines/?master_schedule_id=${encodeURIComponent(
      masterScheduleId,
    )}`,
  );
}

export function captureBaseline(data: {
  master_schedule_id: string;
  name: string;
  notes?: string;
  /**
   * Optional pre-built snapshot of tasks/phases to freeze. When omitted,
   * the helper auto-pulls the master's current phase plans and uses each
   * phase id as task_ref. This is what makes :func:`baselineDelta` return
   * something other than an empty list later.
   */
  snapshot?: Array<Record<string, unknown>>;
}): Promise<Baseline> {
  let snapshot = data.snapshot;
  if (snapshot === undefined) {
    // Auto-snapshot the current phases as task_refs so the variance
    // calculation has something to compare against later. If the network
    // call fails we still capture an empty baseline rather than aborting
    // — the user clicked Capture for a reason.
    snapshot = [];
    // Intentionally not awaited at top-level; we'll await before POST.
  }
  return (async () => {
    if (data.snapshot === undefined) {
      try {
        const phases = await listPhasePlans(data.master_schedule_id);
        snapshot = phases.map((p) => ({
          task_ref: p.id,
          name: p.name,
          planned_start: p.planned_start,
          planned_finish: p.planned_finish,
        }));
      } catch {
        snapshot = [];
      }
    }
    return apiPost<Baseline>('/v1/schedule-advanced/baselines/capture', {
      master_schedule_id: data.master_schedule_id,
      name: data.name,
      notes: data.notes,
      snapshot,
    });
  })();
}

/**
 * Build a fresh "current tasks" payload from a master schedule's phases.
 * Used by the Baselines tab so the compare call has real data to diff
 * against the captured snapshot.
 */
export async function currentTasksForMaster(
  masterScheduleId: string,
): Promise<Array<Record<string, unknown>>> {
  const phases = await listPhasePlans(masterScheduleId);
  return phases.map((p) => ({
    task_ref: p.id,
    name: p.name,
    planned_start: p.planned_start,
    planned_finish: p.planned_finish,
  }));
}

export function baselineDelta(
  baselineId: string,
  currentTasks: Array<Record<string, unknown>> = [],
): Promise<BaselineDelta> {
  return apiPost<BaselineDelta>(
    `/v1/schedule-advanced/baselines/${baselineId}/delta`,
    currentTasks,
  );
}

/* ── Takt / line-of-balance ───────────────────────────────────────────── */

export type TaktStatus = 'draft' | 'active' | 'completed' | 'archived';
export type TaktActivityStatus = 'planned' | 'in_progress' | 'completed';

export interface TaktLocation {
  id: string;
  takt_schedule_id: string;
  sequence_order: number;
  name: string;
  description: string;
  work_area_sqm?: string | number | null;
  created_at: string;
  updated_at: string;
}

export interface TaktSchedule {
  id: string;
  master_schedule_id: string;
  name: string;
  description: string;
  target_cycle_days: number;
  takt_rhythm_tolerance_days: number;
  location_sequence_count: number;
  status: TaktStatus;
  created_by?: string | null;
  locations: TaktLocation[];
  created_at: string;
  updated_at: string;
}

export interface TaktActivity {
  id: string;
  takt_schedule_id: string;
  name: string;
  activity_code: string;
  sequence_order: number;
  planned_cycle_duration_days: number;
  crew_size: number;
  crew_skill_codes: string[];
  buffer_days_before: number;
  sequence_predecessor_activity_id?: string | null;
  status: TaktActivityStatus;
  actual_cycle_duration_days?: string | number | null;
  created_at: string;
  updated_at: string;
}

export interface LineOfBalanceBar {
  activity_id: string;
  location_id: string;
  activity_name: string;
  location_name: string;
  sequence_order: number;
  start_day: number;
  end_day: number;
  crew_size: number;
  is_critical: boolean;
  has_rhythm_break: boolean;
}

export interface TaktViolation {
  activity_id: string;
  location_id?: string | null;
  activity_name: string;
  location_name: string;
  violation_type: 'rhythm_break' | 'overlap' | 'buffer_infeasible';
  deviation_days: number;
  severity: 'warning' | 'error';
  message: string;
}

export interface LineOfBalance {
  takt_schedule_id: string;
  total_makespan_days: number;
  bars: LineOfBalanceBar[];
  violations: TaktViolation[];
  critical_path: string[];
  total_locations: number;
  total_activities: number;
  average_cycle_days: number;
}

export interface TaktLocationInput {
  sequence_order: number;
  name: string;
  description?: string;
  work_area_sqm?: number | null;
}

export interface TaktActivityInput {
  name: string;
  activity_code?: string;
  sequence_order?: number;
  planned_cycle_duration_days: number;
  crew_size?: number;
  crew_skill_codes?: string[];
  buffer_days_before?: number;
}

export function listTaktSchedules(
  masterScheduleId: string,
): Promise<TaktSchedule[]> {
  return apiGet<TaktSchedule[]>(
    `/v1/schedule-advanced/masters/${encodeURIComponent(
      masterScheduleId,
    )}/takt-schedules`,
  );
}

export function getTaktSchedule(taktId: string): Promise<TaktSchedule> {
  return apiGet<TaktSchedule>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(taktId)}`,
  );
}

export function createTaktSchedule(data: {
  master_schedule_id: string;
  name: string;
  description?: string;
  target_cycle_days?: number;
  takt_rhythm_tolerance_days?: number;
  locations: TaktLocationInput[];
}): Promise<TaktSchedule> {
  return apiPost<TaktSchedule>('/v1/schedule-advanced/takt-schedules', data);
}

export function updateTaktSchedule(
  taktId: string,
  data: {
    name?: string;
    description?: string;
    target_cycle_days?: number;
    takt_rhythm_tolerance_days?: number;
    status?: TaktStatus;
  },
): Promise<TaktSchedule> {
  return apiPatch<TaktSchedule>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(taktId)}`,
    data,
  );
}

export function deleteTaktSchedule(taktId: string): Promise<void> {
  return apiDelete(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(taktId)}`,
  );
}

export function listTaktActivities(taktId: string): Promise<TaktActivity[]> {
  return apiGet<TaktActivity[]>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/activities`,
  );
}

export function importTaktActivities(
  taktId: string,
  activities: TaktActivityInput[],
): Promise<TaktActivity[]> {
  return apiPost<TaktActivity[]>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/activities/import`,
    { activities },
  );
}

export function updateTaktActivity(
  taktId: string,
  activityId: string,
  data: {
    planned_cycle_duration_days?: number;
    actual_cycle_duration_days?: number | null;
    status?: TaktActivityStatus;
  },
): Promise<TaktActivity> {
  return apiPatch<TaktActivity>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/activities/${encodeURIComponent(activityId)}`,
    data,
  );
}

export function deleteTaktActivity(
  taktId: string,
  activityId: string,
): Promise<void> {
  return apiDelete(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/activities/${encodeURIComponent(activityId)}`,
  );
}

export function computeLOB(taktId: string): Promise<LineOfBalance> {
  return apiPost<LineOfBalance>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/compute-lob`,
    {},
  );
}

export function getLOB(taktId: string): Promise<LineOfBalance> {
  return apiGet<LineOfBalance>(
    `/v1/schedule-advanced/takt-schedules/${encodeURIComponent(
      taktId,
    )}/line-of-balance`,
  );
}

/* ── Claims-grade schedule quality (T1.2) ─────────────────────────────────
 *
 * Read-only forensic analysis of a base ``schedule`` (its Activity +
 * ScheduleRelationship rows) - NOT a Last Planner master schedule. The
 * ``scheduleId`` is therefore a /v1/schedule schedule id. One CPM pass over
 * the four PDM link types yields the Longest Path, the ranked float-path
 * decomposition, the scheduling QA log and per-activity explain strings.
 * Backend: POST /v1/schedule-advanced/{schedule_id}/schedule-quality
 * (schemas: ScheduleQualityResponse, FloatPathSchema, QAFindingSchema,
 * ActivityExplanationSchema).
 */

/** One ranked float path. Index 0 is the Longest (driving) path. */
export interface FloatPath {
  index: number;
  activity_ids: string[];
  length_days: number;
  relative_float: number;
}

/** One scheduling-quality finding (a row in the QA log). */
export interface QAFinding {
  code: string;
  /** Numeric severity: higher is worse. 3 = error, 2 = warning, 1 = info. */
  severity: number;
  activity_id: string;
  message: string;
}

/** Generated, numbers-faithful explain strings for one activity. */
export interface ActivityExplanation {
  activity_id: string;
  why_critical: string;
  float_explanation: string;
}

export interface ScheduleQuality {
  schedule_id: string;
  project_finish_workday: number;
  num_activities: number;
  num_critical: number;
  longest_path: string[];
  longest_path_length_days: number;
  critical_activity_ids: string[];
  float_paths: FloatPath[];
  qa_log: QAFinding[];
  explanations: ActivityExplanation[];
}

/**
 * Run the claims-grade schedule-quality analysis for a base schedule.
 * The endpoint takes no request body; the schedule is read server-side.
 */
export function scheduleQuality(scheduleId: string): Promise<ScheduleQuality> {
  return apiPost<ScheduleQuality>(
    `/v1/schedule-advanced/${encodeURIComponent(scheduleId)}/schedule-quality`,
    {},
  );
}

/* ── Monte-Carlo schedule risk + Joint Confidence Level (T2.1) ────────────
 *
 * Correlated Monte-Carlo schedule-risk simulation for a base ``schedule``.
 * Activity durations are sampled (Latin Hypercube by default) around their
 * stored value, returning finish-date percentiles, an S-curve, a histogram,
 * the per-activity criticality index, a duration tornado and - when
 * ``cost_inputs`` is supplied - the Joint Confidence Level.
 * Backend: POST /v1/schedule-advanced/{schedule_id}/schedule-risk
 * (schemas: ScheduleRiskRequest, ScheduleRiskResponse).
 */

export type RiskDistribution =
  | 'pert'
  | 'triangular'
  | 'uniform'
  | 'normal'
  | 'lognormal';

/** Optional cost side of a run - enables the Joint Confidence Level. */
export interface CostRiskInput {
  base_cost: number;
  cost_low?: number | null;
  cost_mode?: number | null;
  cost_high?: number | null;
  cost_target?: number | null;
  distribution?: RiskDistribution;
}

/** Optional per-activity three-point duration override for a risk run. */
export interface ActivityRiskInput {
  activity_id: string;
  low?: number | null;
  mode?: number | null;
  high?: number | null;
  distribution?: RiskDistribution;
}

export interface ScheduleRiskRequestBody {
  iterations?: number;
  correlation?: number;
  seed?: number | null;
  sampling?: 'lhs' | 'mc';
  target_confidence?: number;
  optimistic_pct?: number;
  pessimistic_pct?: number;
  activity_risks?: ActivityRiskInput[];
  cost_inputs?: CostRiskInput | null;
}

/** How often an activity drives the schedule, and how strongly. */
export interface CriticalityStat {
  activity_id: string;
  criticality_index: number;
  cruciality: number;
  duration_sensitivity: number;
  mean_duration: number;
}

/** A tornado entry: an activity's rank correlation to the finish. */
export interface ScheduleDriver {
  activity_id: string;
  rank_correlation: number;
  swing_low: number;
  swing_high: number;
}

/** One histogram bar over the simulated finish-day distribution. */
export interface HistBin {
  bin_start: number;
  bin_end: number;
  count: number;
}

/** One point on the cumulative S-curve (``x`` = finish work-day). */
export interface CdfPoint {
  x: number;
  cumulative_prob: number;
}

/** One sampled (finish, cost) draw for the JCL scatter cloud. */
export interface ScatterPoint {
  finish: number;
  cost: number;
}

export interface JointConfidence {
  target_finish: number;
  target_cost: number;
  jcl: number;
  prob_on_time: number;
  prob_on_budget: number;
  cost_mean: number;
  cost_percentiles: Record<string, number>;
  correlation: number;
  scatter: ScatterPoint[];
}

export interface ScheduleRisk {
  schedule_id: string;
  iterations: number;
  deterministic_finish: number;
  mean: number;
  std_dev: number;
  cv_pct: number;
  percentiles: Record<string, number>;
  contingency: number;
  contingency_pct: number;
  recommended_finish: number;
  target_confidence: number;
  prob_within_deterministic: number;
  correlation: number;
  seed: number;
  convergence_status: string;
  convergence_margin_pct: number;
  histogram: HistBin[];
  cdf: CdfPoint[];
  criticality: CriticalityStat[];
  drivers: ScheduleDriver[];
  joint_confidence: JointConfidence | null;
}

/** Run a Monte-Carlo schedule-risk simulation for a base schedule. */
export function scheduleRisk(
  scheduleId: string,
  body: ScheduleRiskRequestBody = {},
): Promise<ScheduleRisk> {
  return apiPost<ScheduleRisk, ScheduleRiskRequestBody>(
    `/v1/schedule-advanced/${encodeURIComponent(scheduleId)}/schedule-risk`,
    body,
  );
}

/* ── Guided forensic delay analysis (T2.2) ────────────────────────────────
 *
 * Persisted, exhibit-producing delay-analysis flow over a base ``schedule``
 * (its Activity + ScheduleRelationship rows). An analysis carries a method
 * (TIA, windows, as-planned-vs-as-built, impacted-as-planned, collapsed-as-
 * built), a set of causative delay events (with optional fragnets), and -
 * once computed - per-window attribution + the total entitlement (excusable /
 * compensable) days. The full contract derived from the backend
 * (backend/app/modules/schedule_advanced/router.py + schemas.py + delay_service.py):
 *
 *   POST   /v1/schedule-advanced/delay-analyses?project_id=<uuid>
 *            body DelayAnalysisCreate -> DelayAnalysisResponse (201)
 *            (project_id is a QUERY param; the body must NOT include it)
 *   GET    /v1/schedule-advanced/delay-analyses?project_id=<uuid>
 *            -> DelayAnalysisListItem[]
 *   GET    /v1/schedule-advanced/delay-analyses/{id} -> DelayAnalysisResponse
 *   PATCH  /v1/schedule-advanced/delay-analyses/{id}  (draft only)
 *   DELETE /v1/schedule-advanced/delay-analyses/{id}  (not issued) -> 204
 *   POST   /v1/schedule-advanced/delay-analyses/{id}/events
 *            body DelayEventCreate -> DelayEventResponse (201, draft only)
 *   PATCH  /v1/schedule-advanced/delay-analyses/{id}/events/{eventId}
 *   DELETE /v1/schedule-advanced/delay-analyses/{id}/events/{eventId} -> 204
 *   PUT    /v1/schedule-advanced/delay-analyses/{id}/events/{eventId}/fragnet
 *   POST   /v1/schedule-advanced/delay-analyses/{id}/auto-fragnet
 *            body AutoFragnetRequest -> FragnetResponse
 *   POST   /v1/schedule-advanced/delay-analyses/{id}/compute
 *            body DelayComputeRequest (optional apportionment override)
 *            -> DelayAnalysisResponse (status -> "computed", fills windows + totals)
 *   POST   /v1/schedule-advanced/delay-analyses/{id}/issue
 *            -> DelayAnalysisResponse (e-sign; computed -> "issued", immutable)
 *   POST   /v1/schedule-advanced/delay-analyses/{id}/raise-eot-claim
 *            -> RaiseEotClaimResponse (computed|issued only)
 *
 * The headline numbers (total_entitlement_days, concurrent_days, window_count,
 * status) live as first-class fields on DelayAnalysisResponse; per-window
 * attribution lives in ``windows`` (DelayWindowResponse). ``result_json`` is a
 * method-dependent exhibit blob (loosely typed here as a record).
 */

export type DelayMethod =
  | 'tia'
  | 'windows'
  | 'as_planned_vs_as_built'
  | 'impacted_as_planned'
  | 'collapsed_as_built';
export type DelayResponsibility = 'employer' | 'contractor' | 'neutral' | 'shared';
export type DelayApportionment = 'none' | 'dominant_cause' | 'time_but_for' | 'malmaison';
export type DelayOosMode = 'retained_logic' | 'progress_override';
export type DelayStatus = 'draft' | 'computed' | 'issued';
export type FragnetInsertMode =
  | 'lengthen_activity'
  | 'insert_after'
  | 'insert_parallel'
  | 'suspend_resume';

export interface DelayFragnet {
  id: string;
  delay_event_id: string;
  insert_mode: string;
  insert_at_activity_ref: string;
  added_duration_days: number;
  fragnet_activities: Array<Record<string, unknown>>;
  rewires: Array<Record<string, unknown>>;
  applies_in_window?: number | null;
}

export interface DelayEvent {
  id: string;
  analysis_id: string;
  code: string;
  title: string;
  description: string;
  root_cause: string;
  responsibility: DelayResponsibility;
  risk_event_category: string;
  is_concurrent: boolean;
  concurrency_group: string;
  is_pacing: boolean;
  source_ref_type?: string | null;
  source_ref_id?: string | null;
  insert_at_activity_ref: string;
  event_start?: string | null;
  event_end?: string | null;
  start_workday?: number | null;
  end_workday?: number | null;
  fragnets: DelayFragnet[];
}

/** One analysis window: gross slip decomposed into responsibility buckets. */
export interface DelayWindow {
  id: string;
  sequence_order: number;
  window_start?: string | null;
  window_end?: string | null;
  finish_at_open: number;
  finish_at_close: number;
  gross_slip_days: number;
  employer_days: number;
  contractor_days: number;
  neutral_days: number;
  concurrent_days: number;
  net_entitlement_days: number;
  narrative: string;
}

/** A row in the analyses list. */
export interface DelayAnalysisListItem {
  id: string;
  project_id: string;
  schedule_id?: string | null;
  method: DelayMethod;
  name: string;
  status: DelayStatus;
  total_entitlement_days: number;
  window_count: number;
  issued_at?: string | null;
}

/** A full analysis with its events, windows and exhibit result. */
export interface DelayAnalysis {
  id: string;
  project_id: string;
  schedule_id?: string | null;
  method: DelayMethod;
  name: string;
  description: string;
  as_planned_baseline_id?: string | null;
  as_built_snapshot_id?: string | null;
  oos_mode: DelayOosMode;
  data_date?: string | null;
  apportionment_method: DelayApportionment;
  status: DelayStatus;
  window_count: number;
  total_entitlement_days: number;
  concurrent_days: number;
  result_json: Record<string, unknown>;
  issued_at?: string | null;
  issued_by?: string | null;
  signature_sha256?: string | null;
  eot_claim_id?: string | null;
  events: DelayEvent[];
  windows: DelayWindow[];
}

export interface DelayAnalysisCreateBody {
  name: string;
  method?: DelayMethod;
  schedule_id?: string | null;
  description?: string;
  apportionment_method?: DelayApportionment;
  oos_mode?: DelayOosMode;
  data_date?: string | null;
}

export interface DelayEventCreateBody {
  title: string;
  code?: string;
  description?: string;
  root_cause?: string;
  responsibility?: DelayResponsibility;
  risk_event_category?: string;
  is_concurrent?: boolean;
  is_pacing?: boolean;
  insert_at_activity_ref?: string;
  event_start?: string | null;
  event_end?: string | null;
  start_workday?: number | null;
  end_workday?: number | null;
}

export interface AutoFragnetBody {
  delay_event_id: string;
  insert_mode?: FragnetInsertMode;
  insert_at_activity_ref: string;
  added_days: number;
}

export interface RaiseEotClaimResult {
  eot_claim_id: string;
  delay_analysis_id: string;
  requested_days: number;
}

/** List the forensic delay analyses for a project. */
export function listDelayAnalyses(
  projectId: string,
): Promise<DelayAnalysisListItem[]> {
  return apiGet<DelayAnalysisListItem[]>(
    `/v1/schedule-advanced/delay-analyses?project_id=${encodeURIComponent(projectId)}`,
  );
}

/** Fetch one analysis with its events, windows and exhibit result. */
export function getDelayAnalysis(analysisId: string): Promise<DelayAnalysis> {
  return apiGet<DelayAnalysis>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}`,
  );
}

/**
 * Create a draft analysis under a project. ``project_id`` is a query param on
 * the backend (the body schema does not carry it), so it is passed separately.
 */
export function createDelayAnalysis(
  projectId: string,
  body: DelayAnalysisCreateBody,
): Promise<DelayAnalysis> {
  return apiPost<DelayAnalysis, DelayAnalysisCreateBody>(
    `/v1/schedule-advanced/delay-analyses?project_id=${encodeURIComponent(projectId)}`,
    body,
  );
}

/** Add a causative delay event to a draft analysis. */
export function addDelayEvent(
  analysisId: string,
  body: DelayEventCreateBody,
): Promise<DelayEvent> {
  return apiPost<DelayEvent, DelayEventCreateBody>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}/events`,
    body,
  );
}

/** Wizard helper: synthesise + attach a default fragnet for an event. */
export function autoDelayFragnet(
  analysisId: string,
  body: AutoFragnetBody,
): Promise<DelayFragnet> {
  return apiPost<DelayFragnet, AutoFragnetBody>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}/auto-fragnet`,
    body,
  );
}

/**
 * Run the analysis method, persisting windows + totals + the exhibit result.
 * The body only carries an optional apportionment override; the schedule and
 * events are read server-side.
 */
export function computeDelayAnalysis(
  analysisId: string,
  apportionmentMethod?: DelayApportionment,
): Promise<DelayAnalysis> {
  return apiPost<DelayAnalysis, { apportionment_method?: DelayApportionment }>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}/compute`,
    apportionmentMethod ? { apportionment_method: apportionmentMethod } : {},
  );
}

/** Freeze + e-sign a computed analysis (issued analyses are immutable). */
export function issueDelayAnalysis(analysisId: string): Promise<DelayAnalysis> {
  return apiPost<DelayAnalysis>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}/issue`,
    {},
  );
}

/** Create an Extension-of-Time claim pre-filled from a computed analysis. */
export function raiseEotClaim(analysisId: string): Promise<RaiseEotClaimResult> {
  return apiPost<RaiseEotClaimResult>(
    `/v1/schedule-advanced/delay-analyses/${encodeURIComponent(analysisId)}/raise-eot-claim`,
    {},
  );
}

/* ----- T3.1 resource depth ------------------------------------------------
 *
 * Two distinct backends, two distinct id-spaces - kept honest in the UI:
 *
 *   1. Time-phased histogram lives on the Resources module, NOT
 *      schedule-advanced. It is keyed by a *Resource entity* UUID (a row in the
 *      resources table), and reads that resource's bookings/assignments, rates
 *      and availability windows:
 *        GET  /v1/resources/                         -> ResourceListItem[]
 *               (tenant-wide; filterable by ?type / ?status only - there is no
 *                project_id filter on the backend list endpoint)
 *        GET  /v1/resources/{resource_id}/histogram  -> ResourceHistogram
 *               query: start, end (ISO datetimes, required), bucket=week|month,
 *               rate_type=cost|billing|overtime, hours_per_day (>0, <=24)
 *      Backend: resources/resource_depth_router.py + resource_depth_schemas.py.
 *      ``demand_cost`` is money (Decimal-as-string, v3 §10).
 *
 *   2. Leveling lives on schedule-advanced and is keyed by the *schedule* id.
 *      Its resource "limits" are keyed by the resource *name string* embedded in
 *      each activity's resources JSON (e.g. "Crew A" -> 3) - a separate id-space
 *      from the Resource entities above:
 *        POST /v1/schedule-advanced/{schedule_id}/level-preview -> LevelPreview
 *        POST /v1/schedule-advanced/{schedule_id}/level-apply   -> LevelApply
 *      Body (both): { resource_limits: {name: max}, splittable: activityId[] }.
 *      Backend: schedule_advanced/router.py + resource_leveling_schemas.py.
 */

/** A resource row from the tenant-wide resources list (histogram picker). */
export interface ResourceListItem {
  id: string;
  code: string;
  name: string;
  resource_type: string;
  home_project_id?: string | null;
  default_cost_rate: string | number;
  currency: string;
  capacity_percent?: number | null;
  status: string;
}

/** One assignment's contribution to a histogram bucket. */
export interface ResourceHistogramBooking {
  assignment_id: string;
  project_id?: string | null;
  units: number;
  unit_kind: string;
}

/** One time bucket of a resource's histogram (a calendar window, not a bin). */
export interface ResourceHistogramCell {
  bucket_index: number;
  start: string;
  end: string;
  label: string;
  demand_units: number;
  /** Money: Decimal-as-string (cents-faithful), v3 §10. */
  demand_cost: string | number;
  /** Availability units for the bucket; null when capacity is unknown. */
  available: number | null;
  capacity_unknown: boolean;
  over_allocated: boolean;
  bookings: ResourceHistogramBooking[];
}

export interface ResourceHistogram {
  resource_id: string;
  bucket: string;
  capacity_units: number | null;
  peak_demand: number;
  over_allocated_buckets: number;
  cells: ResourceHistogramCell[];
}

export type HistogramBucket = 'week' | 'month';
export type HistogramRateType = 'cost' | 'billing' | 'overtime';

export interface ResourceHistogramParams {
  start: string;
  end: string;
  bucket?: HistogramBucket;
  rate_type?: HistogramRateType;
  hours_per_day?: number;
}

/** List resources for the histogram picker.
 *
 *  `project_id` narrows to that project's own roster plus the unhomed company
 *  pool, which is what a picker on a project's schedule wants. Without it the
 *  server answers tenant-wide.
 */
export function listResources(params?: {
  type?: string;
  status?: string;
  limit?: number;
  project_id?: string;
}): Promise<Page<ResourceListItem>> {
  const qs = new URLSearchParams();
  if (params?.type) qs.set('type', params.type);
  if (params?.status) qs.set('status', params.status);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  if (params?.project_id) qs.set('project_id', params.project_id);
  const q = qs.toString();
  /* Same route as listResources in features/resources/api.ts, which is why
     both moved to the envelope together. The `?` is inside the template
     rather than in a conditional suffix so the URL scan in
     scripts/check_page_envelope_consumers.py can see the route at all: it
     stops at the first whitespace, and the suffix idiom puts one inside the
     literal. */
  return apiGet<Page<ResourceListItem>>(`/v1/resources/resources/?${q}`);
}

/** Time-phased demand / availability / cost histogram for one resource. */
export function resourceHistogram(
  resourceId: string,
  params: ResourceHistogramParams,
): Promise<ResourceHistogram> {
  const qs = new URLSearchParams();
  qs.set('start', params.start);
  qs.set('end', params.end);
  qs.set('bucket', params.bucket ?? 'week');
  qs.set('rate_type', params.rate_type ?? 'cost');
  qs.set('hours_per_day', String(params.hours_per_day ?? 8));
  return apiGet<ResourceHistogram>(
    `/v1/resources/resources/${encodeURIComponent(resourceId)}/histogram?${qs.toString()}`,
  );
}

/** One activity whose early start moved under a leveling preview. */
export interface LevelPreviewShift {
  activity_id: string;
  base_es: number;
  new_es: number;
  delta: number;
}

/** One placed day-run of a split activity (work-day indices). */
export interface LevelPreviewSegmentRun {
  start: number;
  finish: number;
}

/** A splittable activity placed across multiple day-runs. */
export interface LevelPreviewSegment {
  activity_id: string;
  runs: LevelPreviewSegmentRun[];
}

/** A single-activity self-overload leveling cannot clear by shifting. */
export interface LevelPreviewUnresolvable {
  activity_id: string;
  resource: string;
  required: number;
  limit: number;
}

export interface LevelPreviewResult {
  schedule_id: string;
  num_shifted: number;
  finish_delta_days: number;
  base_finish_workday: number;
  leveled_finish_workday: number;
  shifts: LevelPreviewShift[];
  segments: LevelPreviewSegment[];
  unresolvable: LevelPreviewUnresolvable[];
  /** Per-resource peak concurrent demand before leveling (name -> units). */
  peak_before: Record<string, number>;
  /** Per-resource peak concurrent demand after leveling (name -> units). */
  peak_after: Record<string, number>;
}

export interface LevelApplyResult {
  schedule_id: string;
  num_shifted: number;
  num_applied: number;
  num_skipped: number;
  finish_delta_days: number;
  base_finish_workday: number;
  leveled_finish_workday: number;
}

/** Request body shared by level-preview and level-apply. */
export interface LevelPreviewBody {
  /** Resource name -> max concurrent units; resources absent are unconstrained. */
  resource_limits: Record<string, number>;
  /** Activity ids that may be split into multiple day-runs to fit a ceiling. */
  splittable: string[];
}

/**
 * Read-only resource-leveling preview. Honours all four PDM link types,
 * splittable activities and fractional units, and returns the honest
 * finish-date impact computed from a copy of the network. Nothing is written.
 */
export function levelPreview(
  scheduleId: string,
  body: LevelPreviewBody,
): Promise<LevelPreviewResult> {
  return apiPost<LevelPreviewResult, LevelPreviewBody>(
    `/v1/schedule-advanced/${encodeURIComponent(scheduleId)}/level-preview`,
    body,
  );
}

/**
 * Commit a leveling run: persist each shifted activity's start / end dates
 * (moved by its leveling delta in calendar days, span preserved). Same pure
 * arithmetic as the preview; this one writes.
 */
export function levelApply(
  scheduleId: string,
  body: LevelPreviewBody,
): Promise<LevelApplyResult> {
  return apiPost<LevelApplyResult, LevelPreviewBody>(
    `/v1/schedule-advanced/${encodeURIComponent(scheduleId)}/level-apply`,
    body,
  );
}

/* ── Last Planner board, constraints log, PPC history, validation ─────── */

export interface LpsConstraintRow {
  id: string;
  task_ref: string;
  task_name: string;
  constraint_type: ConstraintType;
  description: string;
  owner_user_id?: string | null;
  target_clear_date?: string | null;
  status: ConstraintStatus;
  cleared_at?: string | null;
  linked_type?: ConstraintLinkedType | null;
  linked_id?: string | null;
  linked_label?: string | null;
  linked_status?: string | null;
  link_resolved_at?: string | null;
}

export interface LpsBoardTask {
  task_ref: string;
  name: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  week_start: string;
  /** Decimal-as-string. */
  progress_pct: string;
  is_ready: boolean;
  open_constraints: number;
  committed: boolean;
  constraints: LpsConstraintRow[];
}

export interface LpsBoard {
  look_ahead_id: string;
  master_schedule_id: string;
  project_id: string;
  period_start: string;
  period_end: string;
  weeks: string[];
  tasks: LpsBoardTask[];
  ready_count: number;
  blocked_count: number;
}

export interface LpsPpcWeek {
  week_plan_id: string;
  week_start_date: string;
  status: string;
  committed: number;
  completed: number;
  /** Decimal-as-string, null when nothing was committed. */
  ppc_percent: string | null;
}

export interface LpsParetoRow {
  category: string;
  count: number;
  percent: string;
  cumulative_percent: string;
}

export interface LpsPpcHistory {
  master_schedule_id: string;
  weeks: LpsPpcWeek[];
  average_ppc: string | null;
  pareto: LpsParetoRow[];
}

export interface LpsValidationResult {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref?: string | null;
  suggestion?: string | null;
}

export interface LpsValidation {
  master_schedule_id: string;
  status: string;
  errors: number;
  warnings: number;
  results: LpsValidationResult[];
}

export function getLookAheadBoard(lookAheadId: string): Promise<LpsBoard> {
  return apiGet<LpsBoard>(`/v1/schedule-advanced/look-aheads/${encodeURIComponent(lookAheadId)}/board`);
}

export function getConstraintsLog(masterId: string): Promise<LpsConstraintRow[]> {
  return apiGet<LpsConstraintRow[]>(
    `/v1/schedule-advanced/master-schedules/${encodeURIComponent(masterId)}/constraints-log`,
  );
}

export function getPpcHistory(masterId: string): Promise<LpsPpcHistory> {
  return apiGet<LpsPpcHistory>(
    `/v1/schedule-advanced/master-schedules/${encodeURIComponent(masterId)}/ppc-history`,
  );
}

export function getLpsValidation(masterId: string, locale = 'en'): Promise<LpsValidation> {
  return apiGet<LpsValidation>(
    `/v1/schedule-advanced/master-schedules/${encodeURIComponent(masterId)}/lps-validation?locale=${encodeURIComponent(locale)}`,
  );
}

export function useLookAheadBoard(lookAheadId: string) {
  return useQuery({
    queryKey: ['schedule-advanced', 'board', lookAheadId],
    queryFn: () => getLookAheadBoard(lookAheadId),
    enabled: !!lookAheadId,
  });
}

export function useConstraintsLog(masterId: string) {
  return useQuery({
    queryKey: ['schedule-advanced', 'constraints-log', masterId],
    queryFn: () => getConstraintsLog(masterId),
    enabled: !!masterId,
  });
}

export function usePpcHistory(masterId: string) {
  return useQuery({
    queryKey: ['schedule-advanced', 'ppc-history', masterId],
    queryFn: () => getPpcHistory(masterId),
    enabled: !!masterId,
  });
}

export function useLpsValidation(masterId: string, locale = 'en') {
  return useQuery({
    queryKey: ['schedule-advanced', 'lps-validation', masterId, locale],
    queryFn: () => getLpsValidation(masterId, locale),
    enabled: !!masterId,
  });
}
