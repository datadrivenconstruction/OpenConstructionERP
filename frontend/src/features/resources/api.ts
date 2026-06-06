/**
 * API helpers for the Resources module.
 *
 * Backed by /api/v1/resources/ — see backend/app/modules/resources/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ResourceType = 'person' | 'crew' | 'equipment' | 'subcontractor';
export type ResourceStatus = 'active' | 'inactive' | 'on_leave';
export type AssignmentStatus =
  | 'proposed'
  | 'confirmed'
  | 'in_progress'
  | 'completed'
  | 'cancelled';
export type RequestStatus = 'open' | 'fulfilled' | 'cancelled';
export type RequestPriority = 'low' | 'med' | 'high' | 'critical';
export type WindowType = 'available' | 'unavailable' | 'holiday' | 'sick';
export type SkillCategory = 'trade' | 'certification' | 'language' | 'other';

export interface Resource {
  id: string;
  code: string;
  name: string;
  resource_type: ResourceType;
  home_project_id?: string | null;
  contact_id?: string | null;
  default_cost_rate: number | string;
  currency: string;
  status: ResourceStatus;
  avatar_url?: string | null;
  notes: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Skill {
  id: string;
  code: string;
  name: string;
  category: SkillCategory;
  description: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResourceSkill {
  id: string;
  resource_id: string;
  skill_id: string;
  level: 'basic' | 'competent' | 'expert';
  acquired_at?: string | null;
  expires_at?: string | null;
  notes: string;
  created_at: string;
  updated_at: string;
}

export interface Certification {
  id: string;
  resource_id: string;
  cert_type: string;
  cert_number?: string | null;
  issued_by?: string | null;
  issue_date?: string | null;
  valid_until?: string | null;
  document_url?: string | null;
  status: 'valid' | 'expired' | 'revoked';
  notes: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface AvailabilityWindow {
  id: string;
  resource_id: string;
  window_type: WindowType;
  start_at: string;
  end_at: string;
  recurrence_rule?: string | null;
  note: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface Assignment {
  id: string;
  resource_id: string;
  project_id?: string | null;
  /** Human-readable project label - populated by the board endpoint only. */
  project_name?: string;
  task_id?: string | null;
  /** Human-readable task label - populated by the board endpoint only. */
  task_name?: string;
  work_order_id?: string | null;
  start_at: string;
  end_at: string;
  allocation_percent: number;
  status: AssignmentStatus;
  cost_rate: number | string;
  currency: string;
  notes: string;
  created_by?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ResourceRequest {
  id: string;
  project_id: string;
  requested_by?: string | null;
  title: string;
  description: string;
  required_skills: string[];
  start_at: string;
  end_at: string;
  quantity: number;
  priority: RequestPriority;
  status: RequestStatus;
  fulfilled_assignment_id?: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ConflictDetail {
  resource_id: string;
  conflicting_assignment_id?: string | null;
  reason: string;
  overlap_start?: string | null;
  overlap_end?: string | null;
  total_allocation_percent?: number | null;
}

export interface BoardConflict {
  resource_id: string;
  resource_name: string;
  conflicts: ConflictDetail[];
}

export interface BoardEntry {
  resource: Resource;
  assignments: Assignment[];
}

export interface BoardResponse {
  period_start: string;
  period_end: string;
  project_id?: string | null;
  entries: BoardEntry[];
}

export interface UtilizationResponse {
  resource_id: string;
  period_start: string;
  period_end: string;
  utilization_percent: number;
  hours_assigned: number;
  hours_available: number;
}

export interface ResourceDashboard {
  resource: Resource;
  active_assignments: Assignment[];
  upcoming_assignments: Assignment[];
  certifications: Certification[];
  skills: ResourceSkill[];
  expiring_certifications_count: number;
  utilization_30d: UtilizationResponse | null;
}

export interface ProposeAssignmentPayload {
  resource_id: string;
  project_id?: string | null;
  task_id?: string | null;
  start_at: string;
  end_at: string;
  allocation_percent?: number;
  required_skills?: string[];
  cost_rate?: number | string;
  currency?: string;
  notes?: string;
}

export interface CreateResourcePayload {
  code: string;
  name: string;
  resource_type?: ResourceType;
  default_cost_rate?: number | string;
  currency?: string;
  status?: ResourceStatus;
  notes?: string;
}

export interface CreateRequestPayload {
  project_id: string;
  title: string;
  description?: string;
  required_skills?: string[];
  start_at: string;
  end_at: string;
  quantity?: number;
  priority?: RequestPriority;
}

/* ── Resources ──────────────────────────────────────────────────────────── */

export function listResources(params?: {
  type?: ResourceType | '';
  status?: ResourceStatus | '';
  offset?: number;
  limit?: number;
}): Promise<Resource[]> {
  const qs = new URLSearchParams();
  if (params?.type) qs.set('type', params.type);
  if (params?.status) qs.set('status', params.status);
  if (params?.offset !== undefined) qs.set('offset', String(params.offset));
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<Resource[]>(`/v1/resources/resources/${q ? `?${q}` : ''}`);
}

export function getResource(id: string): Promise<Resource> {
  return apiGet<Resource>(`/v1/resources/resources/${id}`);
}

export function createResource(data: CreateResourcePayload): Promise<Resource> {
  return apiPost<Resource>('/v1/resources/resources/', data);
}

export function updateResource(
  id: string,
  data: Partial<CreateResourcePayload>,
): Promise<Resource> {
  return apiPatch<Resource>(`/v1/resources/resources/${id}`, data);
}

export function deleteResource(id: string): Promise<void> {
  return apiDelete(`/v1/resources/resources/${id}`);
}

export function getResourceDashboard(id: string): Promise<ResourceDashboard> {
  return apiGet<ResourceDashboard>(`/v1/resources/resources/${id}/dashboard`);
}

/* ── Skills ─────────────────────────────────────────────────────────────── */

export function listSkills(params?: { category?: string; limit?: number }): Promise<Skill[]> {
  const qs = new URLSearchParams();
  if (params?.category) qs.set('category', params.category);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  const q = qs.toString();
  return apiGet<Skill[]>(`/v1/resources/skills/${q ? `?${q}` : ''}`);
}

/* ── Assignments ────────────────────────────────────────────────────────── */

export function listAssignmentsForResource(
  resourceId: string,
  params?: { status?: AssignmentStatus | ''; limit?: number },
): Promise<Assignment[]> {
  const qs = new URLSearchParams();
  qs.set('resource_id', resourceId);
  if (params?.status) qs.set('status', params.status);
  if (params?.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Assignment[]>(`/v1/resources/assignments/?${qs.toString()}`);
}

export function proposeAssignment(
  data: ProposeAssignmentPayload,
): Promise<Assignment> {
  return apiPost<Assignment>('/v1/resources/assignments/propose', data);
}

export function confirmAssignment(id: string): Promise<Assignment> {
  return apiPost<Assignment>(`/v1/resources/assignments/${id}/confirm`, {});
}

export function cancelAssignment(id: string, reason = ''): Promise<Assignment> {
  const qs = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiPost<Assignment>(`/v1/resources/assignments/${id}/cancel${qs}`, {});
}

export function completeAssignment(id: string): Promise<Assignment> {
  return apiPost<Assignment>(`/v1/resources/assignments/${id}/complete`, {});
}

/** Partial update for an existing assignment. */
export interface UpdateAssignmentPayload {
  project_id?: string | null;
  task_id?: string | null;
  start_at?: string;
  end_at?: string;
  allocation_percent?: number;
  status?: AssignmentStatus;
  cost_rate?: number | string;
  currency?: string;
  notes?: string;
}

export function updateAssignment(
  id: string,
  data: UpdateAssignmentPayload,
): Promise<Assignment> {
  return apiPatch<Assignment>(`/v1/resources/assignments/${id}`, data);
}

export function deleteAssignment(id: string): Promise<void> {
  return apiDelete(`/v1/resources/assignments/${id}`);
}

/* ── Requests ───────────────────────────────────────────────────────────── */

export function listRequests(params: {
  project_id: string;
  status?: RequestStatus | '';
  limit?: number;
}): Promise<ResourceRequest[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<ResourceRequest[]>(`/v1/resources/requests/?${qs.toString()}`);
}

export function createRequest(data: CreateRequestPayload): Promise<ResourceRequest> {
  return apiPost<ResourceRequest>('/v1/resources/requests/', data);
}

export interface UpdateRequestPayload {
  title?: string;
  description?: string;
  required_skills?: string[];
  start_at?: string;
  end_at?: string;
  quantity?: number;
  priority?: RequestPriority;
  status?: RequestStatus;
}

export function updateRequest(
  id: string,
  data: UpdateRequestPayload,
): Promise<ResourceRequest> {
  return apiPatch<ResourceRequest>(`/v1/resources/requests/${id}`, data);
}

export function deleteRequest(id: string): Promise<void> {
  return apiDelete(`/v1/resources/requests/${id}`);
}

export function fulfillRequest(
  id: string,
  payload: {
    resource_id: string;
    cost_rate?: number | string;
    currency?: string;
    allocation_percent?: number;
    notes?: string;
  },
): Promise<Assignment> {
  return apiPost<Assignment>(`/v1/resources/requests/${id}/fulfill`, payload);
}

/* ── Availability / Time off ────────────────────────────────────────────── */

export function listWindows(
  resourceId: string,
  params?: { start_at?: string; end_at?: string },
): Promise<AvailabilityWindow[]> {
  const qs = new URLSearchParams();
  qs.set('resource_id', resourceId);
  if (params?.start_at) qs.set('start_at', params.start_at);
  if (params?.end_at) qs.set('end_at', params.end_at);
  return apiGet<AvailabilityWindow[]>(`/v1/resources/availability/?${qs.toString()}`);
}

/* ── Board / conflicts ──────────────────────────────────────────────────── */

export function getBoard(params: {
  start: string;
  end: string;
  project_id?: string;
}): Promise<BoardResponse> {
  const qs = new URLSearchParams();
  qs.set('start', params.start);
  qs.set('end', params.end);
  if (params.project_id) qs.set('project_id', params.project_id);
  return apiGet<BoardResponse>(`/v1/resources/board/?${qs.toString()}`);
}

export function listBoardConflicts(params: {
  start: string;
  end: string;
}): Promise<BoardConflict[]> {
  const qs = new URLSearchParams();
  qs.set('start', params.start);
  qs.set('end', params.end);
  return apiGet<BoardConflict[]>(`/v1/resources/board/conflicts?${qs.toString()}`);
}
