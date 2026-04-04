/**
 * API helpers for Markups & Annotations.
 *
 * All endpoints are prefixed with /v1/markups/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type MarkupType = 'cloud' | 'arrow' | 'text' | 'stamp' | 'measurement' | 'highlight' | 'freehand';
export type MarkupStatus = 'active' | 'resolved' | 'archived';

export interface Markup {
  id: string;
  project_id: string;
  document_id: string;
  document_name: string;
  page: number;
  type: MarkupType;
  label: string;
  full_text: string;
  author: string;
  author_id: string;
  status: MarkupStatus;
  measurement_value: string | null;
  measurement_unit: string | null;
  geometry: Record<string, unknown> | null;
  linked_position_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface StampTemplate {
  id: string;
  project_id: string | null;
  name: string;
  label: string;
  color: string;
  icon: string | null;
  is_system: boolean;
  created_at: string;
}

export interface MarkupsSummary {
  total: number;
  by_type: Record<string, number>;
  by_status: Record<string, number>;
  by_author: Record<string, number>;
}

export interface MarkupFilters {
  search?: string;
  type?: MarkupType | '';
  status?: MarkupStatus | '';
  author_id?: string;
  document_id?: string;
}

export interface CreateMarkupPayload {
  project_id: string;
  document_id: string;
  page: number;
  type: MarkupType;
  label: string;
  full_text?: string;
  measurement_value?: string;
  measurement_unit?: string;
  geometry?: Record<string, unknown>;
  linked_position_id?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateMarkupPayload {
  label?: string;
  full_text?: string;
  status?: MarkupStatus;
  measurement_value?: string;
  measurement_unit?: string;
  linked_position_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface CreateStampTemplatePayload {
  project_id?: string;
  name: string;
  label: string;
  color: string;
  icon?: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function fetchMarkups(
  projectId: string,
  filters?: MarkupFilters,
): Promise<Markup[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.search) params.set('search', filters.search);
  if (filters?.type) params.set('type', filters.type);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.author_id) params.set('author_id', filters.author_id);
  if (filters?.document_id) params.set('document_id', filters.document_id);
  return apiGet<Markup[]>(`/v1/markups/?${params.toString()}`);
}

export async function createMarkup(data: CreateMarkupPayload): Promise<Markup> {
  return apiPost<Markup>('/v1/markups/', data);
}

export async function updateMarkup(id: string, data: UpdateMarkupPayload): Promise<Markup> {
  return apiPatch<Markup>(`/v1/markups/${id}`, data);
}

export async function deleteMarkup(id: string): Promise<void> {
  return apiDelete(`/v1/markups/${id}`);
}

export async function fetchStampTemplates(projectId: string): Promise<StampTemplate[]> {
  return apiGet<StampTemplate[]>(`/v1/markups/stamps?project_id=${projectId}`);
}

export async function createStampTemplate(data: CreateStampTemplatePayload): Promise<StampTemplate> {
  return apiPost<StampTemplate>('/v1/markups/stamps', data);
}

export async function exportMarkupsCSV(projectId: string): Promise<Blob> {
  const token = localStorage.getItem('oe_access_token');
  const res = await fetch(`/api/v1/markups/export/csv?project_id=${projectId}`, {
    headers: {
      Authorization: token ? `Bearer ${token}` : '',
      'X-DDC-Client': 'OE/1.0',
    },
  });
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`);
  return res.blob();
}

export async function fetchMarkupsSummary(projectId: string): Promise<MarkupsSummary> {
  return apiGet<MarkupsSummary>(`/v1/markups/summary?project_id=${projectId}`);
}
