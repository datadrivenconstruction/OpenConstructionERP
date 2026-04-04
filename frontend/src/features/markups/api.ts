/**
 * API helpers for Markups & Annotations.
 * Endpoints prefixed with /v1/markups/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types (matching backend schemas exactly) ────────────────────────── */

export type MarkupType =
  | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight'
  | 'distance' | 'area' | 'count' | 'stamp' | 'polygon';

export type MarkupStatus = 'active' | 'resolved' | 'archived';

export interface Markup {
  id: string;
  project_id: string;
  document_id: string | null;
  page: number;
  type: MarkupType;
  geometry: Record<string, unknown>;
  text: string | null;
  color: string;
  line_width: number;
  opacity: number;
  author_id: string;
  status: MarkupStatus;
  label: string | null;
  measurement_value: number | null;
  measurement_unit: string | null;
  stamp_template_id: string | null;
  linked_boq_position_id: string | null;
  metadata: Record<string, unknown>;
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface StampTemplate {
  id: string;
  project_id: string | null;
  owner_id: string;
  name: string;
  category: string;
  text: string;
  color: string;
  background_color: string | null;
  icon: string | null;
  include_date: boolean;
  include_name: boolean;
  is_active: boolean;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ScaleConfig {
  id: string;
  document_id: string;
  page: number;
  pixels_per_unit: number;
  unit_label: string;
  calibration_points: unknown;
  real_distance: number;
  created_by: string;
  created_at: string;
  updated_at: string;
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
  page?: number;
}

export interface CreateMarkupPayload {
  project_id: string;
  document_id?: string;
  page?: number;
  type: MarkupType;
  geometry?: Record<string, unknown>;
  text?: string;
  color?: string;
  label?: string;
  measurement_value?: number;
  measurement_unit?: string;
  stamp_template_id?: string;
}

export interface UpdateMarkupPayload {
  text?: string;
  color?: string;
  status?: MarkupStatus;
  label?: string;
  measurement_value?: number;
  measurement_unit?: string;
}

/* ── Markups CRUD ─────────────────────────────────────────────────────── */

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
  if (filters?.page) params.set('page', String(filters.page));
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

export async function linkMarkupToBoq(markupId: string, positionId: string): Promise<Markup> {
  return apiPost<Markup>(`/v1/markups/${markupId}/link-to-boq`, { position_id: positionId });
}

/* ── Stamps ───────────────────────────────────────────────────────────── */

export async function fetchStampTemplates(projectId?: string): Promise<StampTemplate[]> {
  const params = projectId ? `?project_id=${projectId}` : '';
  return apiGet<StampTemplate[]>(`/v1/markups/stamps/templates${params}`);
}

export async function createStampTemplate(data: {
  name: string;
  category?: string;
  text: string;
  color: string;
  project_id?: string;
}): Promise<StampTemplate> {
  return apiPost<StampTemplate>('/v1/markups/stamps/templates', data);
}

export async function deleteStampTemplate(id: string): Promise<void> {
  return apiDelete(`/v1/markups/stamps/templates/${id}`);
}

/* ── Scales ───────────────────────────────────────────────────────────── */

export async function fetchScales(documentId: string): Promise<ScaleConfig[]> {
  return apiGet<ScaleConfig[]>(`/v1/markups/scales/?document_id=${documentId}`);
}

/* ── Summary & Export ─────────────────────────────────────────────────── */

export async function fetchMarkupsSummary(projectId: string): Promise<MarkupsSummary> {
  return apiGet<MarkupsSummary>(`/v1/markups/summary?project_id=${projectId}`);
}

export async function exportMarkupsCSV(projectId: string): Promise<Blob> {
  const token = localStorage.getItem('oe_access_token');
  const res = await fetch(`/api/v1/markups/export?project_id=${projectId}&format=csv`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`);
  return res.blob();
}
