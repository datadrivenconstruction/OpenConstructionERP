import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface Project {
  id: string;
  name: string;
  description: string;
  region: string;
  classification_standard: string;
  currency: string;
  locale: string;
  validation_rule_sets: string[];
  status: string;
  owner_id: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CreateProjectData {
  name: string;
  description?: string;
  region?: string;
  classification_standard?: string;
  currency?: string;
  locale?: string;
  regional_factor?: number;
}

/* ── Unified Project Dashboard types ─────────────────────────────────── */

export interface DashboardBudget {
  original: string;
  revised: string;
  committed: string;
  actual: string;
  forecast: string;
  consumed_pct: string;
  warning_level: 'normal' | 'warning' | 'critical';
}

export interface DashboardSchedule {
  total_activities: number;
  completed: number;
  in_progress: number;
  delayed: number;
  progress_pct: string;
  critical_activities: number;
  next_milestone: { name: string; date: string } | null;
}

export interface DashboardQuality {
  open_defects: number;
  open_observations: number;
  high_risk_observations: number;
  pending_inspections: number;
  ncrs_open: number;
  validation_score: string;
}

export interface DashboardDocuments {
  total: number;
  wip: number;
  shared: number;
  published: number;
  pending_transmittals: number;
}

export interface DashboardCommunication {
  open_rfis: number;
  overdue_rfis: number;
  open_submittals: number;
  open_tasks: number;
  next_meeting: string | null;
  unresolved_action_items: number;
}

export interface DashboardProcurement {
  active_pos: number;
  pending_delivery: number;
  total_committed: string;
}

export interface DashboardActivity {
  type: string;
  title: string;
  date: string;
  user?: string;
}

export interface ProjectDashboard {
  project: { id: string; name: string; status: string; phase: string | null; currency: string };
  budget: DashboardBudget;
  schedule: DashboardSchedule;
  quality: DashboardQuality;
  documents: DashboardDocuments;
  communication: DashboardCommunication;
  procurement: DashboardProcurement;
  recent_activity: DashboardActivity[];
  // Legacy flat fields
  boq_count: number;
  boq_total_value: number;
  position_count: number;
  punch_items: Record<string, number>;
}

export const projectsApi = {
  list: () => apiGet<Project[]>('/v1/projects/'),
  get: (id: string) => apiGet<Project>(`/v1/projects/${id}`),
  create: (data: CreateProjectData) => apiPost<Project>('/v1/projects/', data),
  update: (id: string, data: Partial<CreateProjectData>) =>
    apiPatch<Project>(`/v1/projects/${id}`, data),
  archive: (id: string) => apiDelete(`/v1/projects/${id}`),
  restore: (id: string) => apiPost<Project>(`/v1/projects/${id}/restore/`, {}),
  dashboard: (id: string) => apiGet<ProjectDashboard>(`/v1/projects/${id}/dashboard/`),
};
