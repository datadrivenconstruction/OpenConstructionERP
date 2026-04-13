import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface Schedule {
  id: string;
  project_id: string;
  name: string;
  description: string;
  start_date: string | null;
  end_date: string | null;
  status: string;
  created_at: string;
  updated_at: string;
}

export interface Activity {
  id: string;
  schedule_id: string;
  parent_id: string | null;
  name: string;
  description: string;
  wbs_code: string;
  start_date: string;
  end_date: string;
  duration_days: number;
  progress_pct: number;
  status: string;
  activity_type: string;
  dependencies: Array<{ activity_id: string; type: string; lag_days: number }>;
  resources: Array<{ name: string; type: string; allocation_pct: number }>;
  boq_position_ids: string[];
  /** BIM elements pinned to this activity for 4D scheduling.  Backend
   *  populates this from the `Activity.bim_element_ids` JSON column. */
  bim_element_ids?: string[] | null;
  color: string;
  sort_order: number;
}

export interface WorkOrder {
  id: string;
  activity_id: string;
  assembly_id: string | null;
  boq_position_id: string | null;
  code: string;
  description: string;
  assigned_to: string;
  planned_start: string | null;
  planned_end: string | null;
  actual_start: string | null;
  actual_end: string | null;
  planned_cost: number;
  actual_cost: number;
  status: string;
}

export interface GanttData {
  activities: Activity[];
  summary: {
    total_activities: number;
    completed: number;
    in_progress: number;
    delayed: number;
  };
}

export interface CPMActivityResult {
  activity_id: string;
  name: string;
  duration_days: number;
  early_start: number;
  early_finish: number;
  late_start: number;
  late_finish: number;
  total_float: number;
  is_critical: boolean;
}

export interface CriticalPathResponse {
  schedule_id: string;
  project_duration_days: number;
  critical_path: CPMActivityResult[];
  all_activities: CPMActivityResult[];
}

export interface RiskAnalysisResponse {
  schedule_id: string;
  deterministic_days: number;
  p50_days: number;
  p80_days: number;
  p95_days: number;
  mean_days: number;
  std_dev_days: number;
  risk_buffer_days: number;
  activity_risks: Array<{
    activity_id: string;
    name: string;
    duration_days: number;
    optimistic: number;
    most_likely: number;
    pessimistic: number;
    expected: number;
    std_dev: number;
    is_critical: boolean;
  }>;
}

/** Defensive unwrap: handle both plain array and paginated {items, total} responses. */
function unwrapList<T>(res: T[] | { items: T[] }): T[] {
  return Array.isArray(res) ? res : res.items ?? [];
}

export const scheduleApi = {
  // Schedules
  listSchedules: (projectId: string) =>
    apiGet<Schedule[] | { items: Schedule[] }>(`/v1/schedule/schedules/?project_id=${projectId}`).then(unwrapList),
  getSchedule: (id: string) => apiGet<Schedule>(`/v1/schedule/schedules/${id}`),
  createSchedule: (data: { project_id: string; name: string; description?: string; start_date?: string; end_date?: string }) =>
    apiPost<Schedule>('/v1/schedule/schedules/', data),

  // Activities
  getGantt: (scheduleId: string) =>
    apiGet<GanttData>(`/v1/schedule/schedules/${scheduleId}/gantt/`),
  createActivity: (scheduleId: string, data: Partial<Activity>) =>
    apiPost<Activity>(`/v1/schedule/schedules/${scheduleId}/activities/`, data),
  updateActivity: (activityId: string, data: Partial<Activity>) =>
    apiPatch<Activity>(`/v1/schedule/activities/${activityId}`, data),
  deleteActivity: (activityId: string) =>
    apiDelete(`/v1/schedule/activities/${activityId}`),
  linkPosition: (activityId: string, positionId: string) =>
    apiPost(`/v1/schedule/activities/${activityId}/link-position/`, { boq_position_id: positionId }),
  updateProgress: (activityId: string, progressPct: number) =>
    apiPatch(`/v1/schedule/activities/${activityId}/progress/`, { progress_pct: progressPct }),

  // CPM & BOQ Generation
  generateFromBOQ: (scheduleId: string, boqId: string, totalProjectDays?: number) =>
    apiPost<Activity[]>(`/v1/schedule/schedules/${scheduleId}/generate-from-boq/`, {
      boq_id: boqId,
      ...(totalProjectDays != null ? { total_project_days: totalProjectDays } : {}),
    }),
  calculateCPM: (scheduleId: string) =>
    apiPost<CriticalPathResponse>(`/v1/schedule/schedules/${scheduleId}/calculate-cpm/`),
  getRiskAnalysis: (scheduleId: string) =>
    apiGet<RiskAnalysisResponse>(`/v1/schedule/schedules/${scheduleId}/risk-analysis/`),

  // Work Orders
  listWorkOrders: (params: { schedule_id?: string; activity_id?: string }) =>
    apiGet<WorkOrder[] | { items: WorkOrder[] }>(`/v1/schedule/work-orders/?${new URLSearchParams(params as Record<string, string>)}`).then(unwrapList),
  createWorkOrder: (activityId: string, data: Partial<WorkOrder>) =>
    apiPost<WorkOrder>(`/v1/schedule/activities/${activityId}/work-orders/`, data),
  updateWorkOrder: (id: string, data: Partial<WorkOrder>) =>
    apiPatch<WorkOrder>(`/v1/schedule/work-orders/${id}`, data),
};
