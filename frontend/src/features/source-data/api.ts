// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Source Data Register.
 *
 * All endpoints are prefixed with /v1/source-data/ (see
 * backend/app/modules/source_data/router.py). The register tracks the
 * prerequisite documents a delivery depends on before work can start -
 * permits, surveys, geotechnical reports, technical conditions, title
 * deeds, approvals, technical specifications - with a validity window, a
 * renewal reminder, a schedule-blocking flag and a completeness checklist.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type SourceDocType =
  | 'permit'
  | 'survey'
  | 'geotech'
  | 'tech_conditions'
  | 'title_deed'
  | 'approval'
  | 'technical_spec'
  | 'other';

export type SourceDocStatus =
  | 'requested'
  | 'received'
  | 'verified'
  | 'expiring_soon'
  | 'expired'
  | 'superseded';

/** Statuses a caller may set explicitly; the other two are server-derived. */
export type SourceDocManualStatus = 'requested' | 'received' | 'verified' | 'superseded';

export type ChecklistItemStatus = 'pending' | 'satisfied' | 'waived';

export interface SourceDocument {
  id: string;
  project_id: string;
  name: string;
  doc_type: SourceDocType;
  owner: string | null;
  authority: string | null;
  identifier: string | null;
  issued_at: string | null;
  valid_until: string | null;
  shelf_life_days: number | null;
  notify_days_before: number;
  blocks_schedule: boolean;
  status: SourceDocStatus;
  superseded_by_id: string | null;
  notes: string;
  metadata: Record<string, unknown>;
  created_by: string | null;
  created_at: string;
  updated_at: string;
  /** Computed server-side: negative once expired, 0 on expiry day, null when perpetual. */
  days_until_expiry: number | null;
}

export interface CreateSourceDocumentPayload {
  project_id: string;
  name: string;
  doc_type: SourceDocType;
  owner?: string;
  authority?: string;
  identifier?: string;
  issued_at?: string;
  valid_until?: string;
  shelf_life_days?: number;
  notify_days_before?: number;
  blocks_schedule?: boolean;
  superseded_by_id?: string | null;
  status?: SourceDocManualStatus;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface UpdateSourceDocumentPayload {
  name?: string;
  doc_type?: SourceDocType;
  owner?: string;
  authority?: string;
  identifier?: string;
  issued_at?: string | null;
  valid_until?: string | null;
  shelf_life_days?: number | null;
  notify_days_before?: number;
  blocks_schedule?: boolean;
  superseded_by_id?: string | null;
  status?: SourceDocManualStatus;
  notes?: string;
  metadata?: Record<string, unknown>;
}

export interface SourceChecklistItem {
  id: string;
  project_id: string;
  label: string;
  required: boolean;
  doc_type: SourceDocType | null;
  satisfied_by_id: string | null;
  status: ChecklistItemStatus;
  created_at: string;
  updated_at: string;
}

export interface CreateChecklistItemPayload {
  project_id: string;
  label: string;
  required?: boolean;
  doc_type?: SourceDocType | null;
  satisfied_by_id?: string | null;
  status?: ChecklistItemStatus;
}

export interface UpdateChecklistItemPayload {
  label?: string;
  required?: boolean;
  doc_type?: SourceDocType | null;
  satisfied_by_id?: string | null;
  status?: ChecklistItemStatus;
}

export interface ChecklistSummary {
  total: number;
  required: number;
  satisfied: number;
  waived: number;
  pending: number;
  complete: boolean;
  missing_required: string[];
}

export interface DefectiveInputsNotice {
  project_id: string;
  recipient: string | null;
  missing_items: string[];
  expired_documents: Record<string, unknown>[];
  summary: string;
  has_defects: boolean;
}

export interface SourceDataMetaOption {
  code: string;
  label: string;
}

export interface SourceDataMeta {
  doc_types: SourceDataMetaOption[];
  statuses: SourceDataMetaOption[];
  checklist_statuses: string[];
}

export interface DocumentListFilters {
  project_id: string;
  status?: SourceDocStatus | '';
  doc_type?: SourceDocType | '';
}

const BASE = '/v1/source-data';

/* ── Meta ──────────────────────────────────────────────────────────────── */

export async function fetchSourceDataMeta(): Promise<SourceDataMeta> {
  return apiGet<SourceDataMeta>(`${BASE}/meta`);
}

/* ── Documents ─────────────────────────────────────────────────────────── */

export async function fetchSourceDocuments(
  filters: DocumentListFilters,
): Promise<SourceDocument[]> {
  const params = new URLSearchParams();
  params.set('project_id', filters.project_id);
  if (filters.status) params.set('status', filters.status);
  if (filters.doc_type) params.set('doc_type', filters.doc_type);
  return apiGet<SourceDocument[]>(`${BASE}/documents?${params.toString()}`);
}

export async function fetchExpiringSoon(
  projectId: string,
  limit = 50,
): Promise<SourceDocument[]> {
  const params = new URLSearchParams({ project_id: projectId, limit: String(limit) });
  return apiGet<SourceDocument[]>(`${BASE}/expiring-soon?${params.toString()}`);
}

export async function fetchBlockingSchedule(projectId: string): Promise<SourceDocument[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<SourceDocument[]>(`${BASE}/blocking-schedule?${params.toString()}`);
}

export async function fetchDefectiveInputsNotice(
  projectId: string,
): Promise<DefectiveInputsNotice> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<DefectiveInputsNotice>(`${BASE}/defective-inputs-notice?${params.toString()}`);
}

export async function createSourceDocument(
  data: CreateSourceDocumentPayload,
): Promise<SourceDocument> {
  return apiPost<SourceDocument>(`${BASE}/documents`, data);
}

export async function fetchSourceDocument(id: string): Promise<SourceDocument> {
  return apiGet<SourceDocument>(`${BASE}/documents/${id}`);
}

export async function updateSourceDocument(
  id: string,
  data: UpdateSourceDocumentPayload,
): Promise<SourceDocument> {
  return apiPatch<SourceDocument>(`${BASE}/documents/${id}`, data);
}

export async function verifySourceDocument(id: string): Promise<SourceDocument> {
  return apiPost<SourceDocument>(`${BASE}/documents/${id}/verify`, {});
}

export async function deleteSourceDocument(id: string): Promise<void> {
  await apiDelete(`${BASE}/documents/${id}`);
}

/* ── Checklist ─────────────────────────────────────────────────────────── */

export async function fetchChecklistSummary(projectId: string): Promise<ChecklistSummary> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<ChecklistSummary>(`${BASE}/checklist/summary?${params.toString()}`);
}

export async function fetchChecklist(projectId: string): Promise<SourceChecklistItem[]> {
  const params = new URLSearchParams({ project_id: projectId });
  return apiGet<SourceChecklistItem[]>(`${BASE}/checklist?${params.toString()}`);
}

export async function createChecklistItem(
  data: CreateChecklistItemPayload,
): Promise<SourceChecklistItem> {
  return apiPost<SourceChecklistItem>(`${BASE}/checklist`, data);
}

export async function updateChecklistItem(
  id: string,
  data: UpdateChecklistItemPayload,
): Promise<SourceChecklistItem> {
  return apiPatch<SourceChecklistItem>(`${BASE}/checklist/${id}`, data);
}

export async function deleteChecklistItem(id: string): Promise<void> {
  await apiDelete(`${BASE}/checklist/${id}`);
}
