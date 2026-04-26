import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

export interface ProjectAddress {
  street?: string | null;
  city?: string | null;
  state?: string | null;
  country?: string | null;
  postal_code?: string | null;
  /** Resolved coordinates are cached here after the first geocode so
   *  the client doesn't re-hit Nominatim on every project open. */
  lat?: number | null;
  lng?: number | null;
}

/** RFC 37 §3 — single FX rate row attached to a project.
 *  Rate stored as a Decimal-precise string (SQLite parity). */
export interface ProjectFxRate {
  code: string;
  rate: string;
  label?: string | null;
}

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
  address?: ProjectAddress | null;
  metadata: Record<string, unknown>;
  /** RFC 37 #88 — additional currencies + FX rate to project.currency. */
  fx_rates?: ProjectFxRate[];
  /** RFC 37 #89 — per-project VAT override (percentage string, e.g. "21"). */
  default_vat_rate?: string | null;
  /** RFC 37 #93 — project-scoped custom units (synced across browsers). */
  custom_units?: string[];
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
  /** Optional postal address — used to anchor the project map + weather. */
  address?: ProjectAddress | null;
}

/** Patch payload — every field is optional; only included keys are updated. */
export interface UpdateProjectData extends Partial<CreateProjectData> {
  fx_rates?: ProjectFxRate[];
  default_vat_rate?: string | null;
  custom_units?: string[];
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
  update: (id: string, data: UpdateProjectData) =>
    apiPatch<Project>(`/v1/projects/${id}`, data),
  archive: (id: string) => apiDelete(`/v1/projects/${id}`),
  restore: (id: string) => apiPost<Project>(`/v1/projects/${id}/restore/`, {}),
  dashboard: (id: string) => apiGet<ProjectDashboard>(`/v1/projects/${id}/dashboard/`),
};
