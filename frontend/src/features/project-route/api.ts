// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Work-type Route Classifier module.
 *
 * All endpoints are prefixed with /v1/project-route/.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type WorkType =
  | 'new_build'
  | 'reconstruction'
  | 'capital_repair'
  | 're_equipment'
  | 'maintenance'
  | 'demolition'
  | 'change_of_use'
  | 'other';

export type RouteOption =
  | 'full_permit'
  | 'notification'
  | 'permitted_development'
  | 'exempt'
  | 'expertise_required'
  | 'undetermined';

export type AssessmentStatus = 'draft' | 'confirmed';

export interface CodeLabel {
  code: string;
  label: string;
}

export interface ProjectRouteMeta {
  work_types: CodeLabel[];
  route_options: CodeLabel[];
  statuses: string[];
}

/**
 * Recognised generic classifier answers. The backend accepts an open
 * dict (regional packs may add keys), so this is a superset the UI knows
 * how to render as toggles - anything else round-trips untouched.
 */
export interface RouteCriteria {
  affects_structure?: boolean;
  scale?: 'minor' | 'major';
  changes_use?: boolean;
  within_permitted_limits?: boolean;
  heritage_protected?: boolean;
  [key: string]: unknown;
}

export interface ClassifyRequestPayload {
  work_type: WorkType;
  criteria: RouteCriteria;
}

export interface ClassifyResult {
  work_type: WorkType;
  determined_route: RouteOption;
  rationale: string;
  confidence: number;
}

export interface RouteAssessment {
  id: string;
  project_id: string;
  work_type: WorkType;
  criteria: RouteCriteria;
  determined_route: RouteOption;
  rationale: string;
  confidence: number;
  status: AssessmentStatus;
  classified_at: string | null;
  classified_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface RouteAssessmentFilters {
  project_id: string;
  status?: AssessmentStatus | '';
  work_type?: WorkType | '';
}

export interface CreateRouteAssessmentPayload {
  project_id: string;
  work_type: WorkType;
  criteria?: RouteCriteria;
  determined_route?: RouteOption | null;
  metadata?: Record<string, unknown>;
}

export interface UpdateRouteAssessmentPayload {
  work_type?: WorkType;
  criteria?: RouteCriteria;
  determined_route?: RouteOption | null;
  metadata?: Record<string, unknown>;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchProjectRouteMeta(): Promise<ProjectRouteMeta> {
  return apiGet<ProjectRouteMeta>('/v1/project-route/meta');
}

export async function fetchWorkTypes(): Promise<CodeLabel[]> {
  return apiGet<CodeLabel[]>('/v1/project-route/work-types');
}

export async function fetchRouteOptions(): Promise<CodeLabel[]> {
  return apiGet<CodeLabel[]>('/v1/project-route/route-options');
}

export async function classifyRoute(data: ClassifyRequestPayload): Promise<ClassifyResult> {
  return apiPost<ClassifyResult>('/v1/project-route/classify', data);
}

export async function fetchRouteAssessments(
  filters: RouteAssessmentFilters,
): Promise<RouteAssessment[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.work_type) params.set('work_type', filters.work_type);
  return apiGet<RouteAssessment[]>(`/v1/project-route/assessments?${params.toString()}`);
}

export async function fetchRouteAssessment(id: string): Promise<RouteAssessment> {
  return apiGet<RouteAssessment>(`/v1/project-route/assessments/${id}`);
}

export async function createRouteAssessment(
  data: CreateRouteAssessmentPayload,
): Promise<RouteAssessment> {
  return apiPost<RouteAssessment>('/v1/project-route/assessments', data);
}

export async function updateRouteAssessment(
  id: string,
  data: UpdateRouteAssessmentPayload,
): Promise<RouteAssessment> {
  return apiPatch<RouteAssessment>(`/v1/project-route/assessments/${id}`, data);
}

export async function confirmRouteAssessment(id: string): Promise<RouteAssessment> {
  return apiPost<RouteAssessment>(`/v1/project-route/assessments/${id}/confirm`, {});
}

export async function deleteRouteAssessment(id: string): Promise<void> {
  await apiDelete(`/v1/project-route/assessments/${id}`);
}
