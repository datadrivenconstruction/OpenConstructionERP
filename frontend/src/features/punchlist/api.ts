/**
 * API helpers for Punch List.
 *
 * All endpoints are prefixed with /v1/punchlist/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type PunchPriority = 'low' | 'medium' | 'high' | 'critical';
export type PunchStatus = 'open' | 'in_progress' | 'resolved' | 'verified' | 'closed';
export type PunchCategory =
  | 'structural'
  | 'mechanical'
  | 'electrical'
  | 'plumbing'
  | 'finishing'
  | 'fire_safety'
  | 'hvac'
  | 'exterior'
  | 'landscaping'
  | 'general';

export interface PunchItem {
  id: string;
  project_id: string;
  title: string;
  description: string;
  priority: PunchPriority;
  status: PunchStatus;
  category: PunchCategory;
  assigned_to_id: string | null;
  assigned_to_name: string | null;
  due_date: string | null;
  document_id: string | null;
  document_name: string | null;
  page: number | null;
  photos_count: number;
  location: string | null;
  metadata: Record<string, unknown>;
  created_by: string;
  created_by_name: string;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  verified_at: string | null;
  closed_at: string | null;
}

export interface PunchSummary {
  total: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_category: Record<string, number>;
  overdue: number;
}

export interface PunchFilters {
  search?: string;
  priority?: PunchPriority | '';
  status?: PunchStatus | '';
  category?: PunchCategory | '';
  assigned_to_id?: string;
}

export interface CreatePunchPayload {
  project_id: string;
  title: string;
  description?: string;
  priority: PunchPriority;
  category: PunchCategory;
  assigned_to_id?: string;
  due_date?: string;
  document_id?: string;
  location?: string;
}

export interface UpdatePunchPayload {
  title?: string;
  description?: string;
  priority?: PunchPriority;
  category?: PunchCategory;
  assigned_to_id?: string | null;
  due_date?: string | null;
  document_id?: string | null;
  location?: string;
}

export interface TeamMember {
  id: string;
  name: string;
  email: string;
  avatar_url: string | null;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchPunchItems(
  projectId: string,
  filters?: PunchFilters,
): Promise<PunchItem[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.search) params.set('search', filters.search);
  if (filters?.priority) params.set('priority', filters.priority);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.category) params.set('category', filters.category);
  if (filters?.assigned_to_id) params.set('assigned_to_id', filters.assigned_to_id);
  return apiGet<PunchItem[]>(`/v1/punchlist/items?${params.toString()}`);
}

export async function createPunchItem(data: CreatePunchPayload): Promise<PunchItem> {
  return apiPost<PunchItem>('/v1/punchlist/items', data);
}

export async function updatePunchItem(id: string, data: UpdatePunchPayload): Promise<PunchItem> {
  return apiPatch<PunchItem>(`/v1/punchlist/items/${id}`, data);
}

export async function deletePunchItem(id: string): Promise<void> {
  return apiDelete(`/v1/punchlist/items/${id}`);
}

export async function transitionPunchStatus(
  id: string,
  newStatus: PunchStatus,
): Promise<PunchItem> {
  return apiPost<PunchItem>(`/v1/punchlist/items/${id}/transition`, { new_status: newStatus });
}

export async function uploadPunchPhoto(id: string, file: File): Promise<{ url: string }> {
  const formData = new FormData();
  formData.append('file', file);
  const token = localStorage.getItem('oe_access_token');
  const res = await fetch(`/api/v1/punchlist/items/${id}/photos`, {
    method: 'POST',
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      'X-DDC-Client': 'OE/1.0',
    },
    body: formData,
  });
  if (!res.ok) throw new Error(`Upload failed: ${res.statusText}`);
  return res.json();
}

export async function fetchPunchSummary(projectId: string): Promise<PunchSummary> {
  return apiGet<PunchSummary>(`/v1/punchlist/summary?project_id=${projectId}`);
}

export async function fetchTeamMembers(projectId: string): Promise<TeamMember[]> {
  return apiGet<TeamMember[]>(`/v1/projects/${projectId}/members`);
}
