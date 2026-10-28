// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/** Drawing revision compare API client (`/api/v1/drawing-compare`). */

import type { Page } from '@/shared/lib/apiHelpers';
import { API_BASE, apiDelete, apiGet, apiPatch, apiPost, downloadWithAuth } from '@/shared/lib/api';
import type { Affine, Pt } from './lib/transform';

const BASE = '/v1/drawing-compare';

export type ChangeKind = 'added' | 'removed' | 'modified' | 'text';
export type ChangeStatus = 'open' | 'relevant' | 'not_relevant';
export type SourceKind = 'pdf' | 'dwg';

export interface DrawingChange {
  id: string;
  comparison_id: string;
  seq: number;
  kind: ChangeKind;
  page: number | null;
  x: number;
  y: number;
  w: number;
  h: number;
  score: number | null;
  old_text: string | null;
  new_text: string | null;
  layer: string | null;
  entity_type: string | null;
  details: Record<string, unknown>;
  thumbnail: string | null;
  status: ChangeStatus;
  comment: string | null;
  rfi_id: string | null;
  markup_id: string | null;
  flagged_at: string | null;
  flagged_measurement_ids: string[];
  flagged_annotation_ids: string[];
  flagged_position_ids: string[];
  reviewed_by: string | null;
  updated_at: string;
}

export interface ComparisonAlignment {
  method?: 'none' | 'auto' | 'manual';
  matrix?: Affine;
  confidence?: number | null;
  points_old?: Pt[];
  points_new?: Pt[];
}

export interface ComparisonSummary {
  id: string;
  project_id: string;
  name: string;
  source_kind: SourceKind;
  old_ref_id: string;
  new_ref_id: string;
  old_page: number | null;
  new_page: number | null;
  old_label: string;
  new_label: string;
  old_revision: string | null;
  new_revision: string | null;
  page_width: number | null;
  page_height: number | null;
  alignment: ComparisonAlignment;
  settings: Record<string, unknown>;
  summary: {
    added?: number;
    removed?: number;
    modified?: number;
    text?: number;
    total?: number;
    by_layer?: Array<{ layer: string; entity_type: string; added: number; removed: number; modified: number }>;
    entities?: Record<'added' | 'removed' | 'modified' | 'unchanged', number>;
  };
  created_by: string;
  created_at: string;
  updated_at: string;
}

export interface Comparison extends ComparisonSummary {
  changes: DrawingChange[];
}

export interface PdfComparisonPayload {
  project_id: string;
  name?: string;
  old_ref_id: string;
  new_ref_id: string;
  old_page: number;
  new_page: number;
  page_width: number;
  page_height: number;
  alignment: ComparisonAlignment;
  settings: Record<string, unknown>;
  changes: Array<{
    kind: ChangeKind;
    page?: number;
    x: number;
    y: number;
    w: number;
    h: number;
    score?: number | null;
    old_text?: string | null;
    new_text?: string | null;
    details?: Record<string, unknown>;
    thumbnail?: string | null;
  }>;
}

export interface DwgComparisonPayload {
  project_id: string;
  name?: string;
  old_drawing_id: string;
  new_drawing_id: string;
  old_version_id?: string | null;
  new_version_id?: string | null;
}

export interface AffectedItem {
  id: string;
  source: 'takeoff' | 'dwg_annotation' | 'markup';
  document_id: string | null;
  page: number | null;
  label: string;
  revision: 'old' | 'new';
  linked_boq_position_id: string | null;
}

export interface RemeasureResult {
  change_id: string;
  dry_run: boolean;
  items: AffectedItem[];
  positions: Array<{ id: string; ordinal: string; description: string }>;
  flagged_at: string | null;
}

export interface FollowUp {
  target_id: string;
  label: string;
  change: DrawingChange;
}

export interface ValidationResultRow {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface ComparisonValidation {
  status: string;
  score: number | null;
  errors: number;
  warnings: number;
  results: ValidationResultRow[];
}

export interface PreviousRevision {
  document_id: string;
  previous_document_id: string | null;
  previous_label: string | null;
  source: 'documents_chain' | 'none';
}

export const drawingCompareApi = {
  list: (projectId: string, refId?: string) => {
    const qs = refId ? `&ref_id=${encodeURIComponent(refId)}` : '';
    return apiGet<Page<ComparisonSummary>>(
      `${BASE}/comparisons/?project_id=${encodeURIComponent(projectId)}${qs}`,
    ).then((page) => page.items);
  },
  get: (id: string) => apiGet<Comparison>(`${BASE}/comparisons/${id}`),
  createPdf: (payload: PdfComparisonPayload) => apiPost<Comparison>(`${BASE}/comparisons/`, payload),
  createDwg: (payload: DwgComparisonPayload) => apiPost<Comparison>(`${BASE}/comparisons/dwg/`, payload),
  remove: (id: string) => apiDelete(`${BASE}/comparisons/${id}`),
  validate: (id: string) => apiGet<ComparisonValidation>(`${BASE}/comparisons/${id}/validation/`),
  downloadReport: (id: string, filename: string) =>
    downloadWithAuth(`${API_BASE}${BASE}/comparisons/${id}/report.pdf`, filename),
  updateChange: (id: string, body: { status?: ChangeStatus; comment?: string | null }) =>
    apiPatch<DrawingChange>(`${BASE}/changes/${id}`, body),
  createRfi: (id: string, body: { subject?: string; question?: string; priority?: string } = {}) =>
    apiPost<FollowUp>(`${BASE}/changes/${id}/rfi/`, body),
  createMarkup: (id: string, body: { text?: string } = {}) => apiPost<FollowUp>(`${BASE}/changes/${id}/markup/`, body),
  remeasure: (id: string, dryRun: boolean) =>
    apiPost<RemeasureResult>(`${BASE}/changes/${id}/remeasure/?dry_run=${dryRun ? 'true' : 'false'}`, {}),
  clearRemeasure: (id: string) => apiDelete<DrawingChange>(`${BASE}/changes/${id}/remeasure/`),
  previousRevision: (projectId: string, documentId: string) =>
    apiGet<PreviousRevision>(
      `${BASE}/previous-revision/?project_id=${encodeURIComponent(projectId)}&document_id=${encodeURIComponent(documentId)}`,
    ),
};
