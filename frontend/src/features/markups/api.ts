// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Markups & Annotations.
 * Endpoints prefixed with /v1/markups/.
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

/* ── Types (matching backend schemas exactly) ────────────────────────── */

export type MarkupType =
  | 'cloud' | 'arrow' | 'text' | 'rectangle' | 'highlight'
  | 'distance' | 'area' | 'count' | 'stamp' | 'polygon';

export type MarkupStatus = 'active' | 'resolved' | 'archived';

export interface Markup {
  id: string;
  project_id: string;
  document_id: string | null;
  /** Epic C — chain row this markup was authored against. NULL on
   *  pre-Epic-C rows; the viewer treats NULL as "current" so legacy
   *  markups render at full opacity. */
  file_version_id: string | null;
  page: number;
  type: MarkupType;
  geometry: Record<string, unknown>;
  text: string | null;
  color: string;
  line_width: number;
  opacity: number;
  author_id: string;
  /** M3 — optional follow-up owner. NULL = unassigned. */
  assignee_id: string | null;
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
  /** M3 — filter to a specific assignee. Empty string = no filter. */
  assignee_id?: string;
  /** M3 — when true, only markups with NULL assignee_id are returned.
   *  Mutually exclusive with assignee_id (the latter wins server-side). */
  unassigned?: boolean;
  document_id?: string;
  page?: number;
  /** Pagination, platform-standard offset/limit. The backend defaults to
   *  offset 0 / limit 50 (max 200) when omitted. */
  offset?: number;
  limit?: number;
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
  /** M3 — optional follow-up owner. */
  assignee_id?: string | null;
  /** Free-form JSONB. Used by the issue-tracking layer to stash
   *  ``priority`` / ``due_date`` on a markup without a schema change
   *  (the backend accepts ``metadata`` on create, storing it verbatim). */
  metadata?: Record<string, unknown>;
}

export interface UpdateMarkupPayload {
  /** Pass null to clear the column to NULL (it is nullable server-side);
   *  pass undefined / omit to leave it unchanged (PATCH semantics). */
  text?: string | null;
  color?: string;
  status?: MarkupStatus;
  /** Pass null to clear the column to NULL; omit to leave unchanged. */
  label?: string | null;
  measurement_value?: number;
  measurement_unit?: string;
  /** M3 — re-assign or clear the follow-up owner. Pass null to clear. */
  assignee_id?: string | null;
  /** Free-form JSONB patch. The backend shallow-MERGES this onto the
   *  stored metadata (it does not replace it), so a request only needs to
   *  carry the keys it changes; sibling keys such as a linked ``punch_item_id``
   *  survive. Used to persist ``priority`` / ``due_date`` / ``punch_item_id``
   *  without a dedicated column. */
  metadata?: Record<string, unknown>;
}

/* ── Markups CRUD ─────────────────────────────────────────────────────── */

export async function fetchMarkups(
  projectId: string,
  filters?: MarkupFilters,
): Promise<Markup[]> {
  if (!projectId) return [];
  const params = new URLSearchParams({ project_id: projectId });
  if (filters?.search) params.set('search', filters.search);
  if (filters?.type) params.set('type', filters.type);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.author_id) params.set('author_id', filters.author_id);
  if (filters?.assignee_id) params.set('assignee_id', filters.assignee_id);
  if (filters?.unassigned) params.set('unassigned', 'true');
  if (filters?.document_id) params.set('document_id', filters.document_id);
  // Explicit nullish check so page 0 (a valid 0-indexed page) is honoured
  // rather than dropped by a falsy check, which would over-fetch all pages.
  if (filters?.page != null) params.set('page', String(filters.page));
  // Pagination: nullish checks so offset 0 is honoured rather than dropped.
  if (filters?.offset != null) params.set('offset', String(filters.offset));
  if (filters?.limit != null) params.set('limit', String(filters.limit));
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
  return apiPost<Markup>(`/v1/markups/${markupId}/link-to-boq/`, { position_id: positionId });
}

/* ── Stamps ───────────────────────────────────────────────────────────── */

export async function fetchStampTemplates(projectId?: string): Promise<StampTemplate[]> {
  const params = projectId ? `?project_id=${projectId}` : '';
  return apiGet<StampTemplate[]>(`/v1/markups/stamps/templates/${params}`);
}

export async function createStampTemplate(data: {
  name: string;
  category?: string;
  text: string;
  color: string;
  project_id?: string;
}): Promise<StampTemplate> {
  return apiPost<StampTemplate>('/v1/markups/stamps/templates/', data);
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
  if (!projectId) return { total: 0, by_type: {}, by_status: {}, by_author: {} };
  return apiGet<MarkupsSummary>(`/v1/markups/summary/?project_id=${projectId}`);
}

export async function exportMarkupsCSV(projectId: string): Promise<Blob> {
  const token = useAuthStore.getState().accessToken;
  const res = await fetch(`/api/v1/markups/export/?project_id=${projectId}&format=csv`, {
    headers: token ? { Authorization: `Bearer ${token}`, 'X-DDC-Client': 'OE/1.0' } : { 'X-DDC-Client': 'OE/1.0' },
  });
  if (!res.ok) throw new Error(`Export failed: ${res.statusText}`);
  return res.blob();
}

/* ── Markup Comments (threaded) ────────────────────────────────────────── */

export interface MarkupComment {
  id: string;
  markup_id: string;
  user_id: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export async function fetchMarkupComments(markupId: string): Promise<MarkupComment[]> {
  return apiGet<MarkupComment[]>(`/v1/markups/${markupId}/comments/`);
}

export async function createMarkupComment(
  markupId: string,
  body: string,
): Promise<MarkupComment> {
  return apiPost<MarkupComment>(`/v1/markups/${markupId}/comments/`, { body });
}

export async function deleteMarkupComment(
  markupId: string,
  commentId: string,
): Promise<void> {
  return apiDelete(`/v1/markups/${markupId}/comments/${commentId}/`);
}

/* ── Per-page list helper for the takeoff overlay ──────────────────────── */

/** Fetches markups for a (document, page) pair. Thin wrapper around
 *  ``fetchMarkups`` used by the DWG/PDF takeoff overlays so they don't
 *  need to construct the filter object themselves. */
export async function fetchMarkupsByPage(
  projectId: string,
  documentId: string,
  page: number,
): Promise<Markup[]> {
  return fetchMarkups(projectId, { document_id: documentId, page });
}
