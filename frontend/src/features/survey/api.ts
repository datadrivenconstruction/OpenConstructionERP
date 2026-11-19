// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the survey register: project CRS, point import (preview
 * first, nothing saved until Import), points, point sets and SRV findings.
 */

import {
  API_BASE,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  extractErrorMessageFromBody,
  fetchWithAuth,
  triggerDownload,
} from '@/shared/lib/api';

const BASE = '/v1/survey-core';

export type PointKind = 'control' | 'benchmark' | 'topo' | 'stake' | 'asbuilt';
export const POINT_KINDS: PointKind[] = ['control', 'benchmark', 'topo', 'stake', 'asbuilt'];
export type FileFormat = 'csv' | 'txt' | 'geojson';
export type DuplicatePolicy = 'keep_first' | 'keep_last' | 'skip';

export interface CrsInfo {
  epsg: number;
  name: string;
  kind: string;
  unit: string;
  is_geographic: boolean;
  area?: string;
}

export interface CrsSuggestion extends CrsInfo {
  reason: 'project_location' | 'pack' | 'detected' | 'geographic';
  confidence: number | null;
  pack_country: string;
}

export interface ProjectCrs {
  project_id: string;
  horizontal_epsg: number | null;
  horizontal_name: string;
  vertical_mode: 'same_as_source' | 'epsg';
  vertical_epsg: number | null;
  is_local_grid: boolean;
  local_origin_e: number | null;
  local_origin_n: number | null;
  local_rotation_deg: number | null;
  local_scale_factor: number | null;
  source: 'user' | 'detected';
  detected_confidence: number | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
}

export interface ProjectCrsState {
  crs: ProjectCrs | null;
  suggestions: CrsSuggestion[];
  point_count: number;
}

export interface ProjectCrsInput {
  horizontal_epsg: number | null;
  vertical_mode: 'same_as_source' | 'epsg';
  vertical_epsg?: number | null;
  is_local_grid?: boolean;
  local_origin_e?: number | null;
  local_origin_n?: number | null;
  local_rotation_deg?: number | null;
  local_scale_factor?: number | null;
  source?: 'user' | 'detected';
  detected_confidence?: number | null;
  confirm_text?: string;
}

export interface SurveyPoint {
  id: string;
  point_set_id: string;
  point_id: string;
  e: number;
  n: number;
  z: number | null;
  code: string;
  kind: PointKind;
  sigma: number | null;
  description: string;
}

export interface PointSet {
  id: string;
  name: string;
  source_filename: string;
  file_format: FileFormat;
  column_preset: string;
  instrument: string;
  surveyed_by: string;
  survey_date: string | null;
  source_epsg: number | null;
  stored_epsg: number | null;
  transformed: boolean;
  rows_read: number;
  point_count: number;
  created_at: string | null;
}

export interface ImportBody {
  text: string;
  file_format: FileFormat;
  filename: string;
  delimiter: string;
  columns: string[];
  has_header: boolean;
  default_kind: PointKind;
  source_epsg: number | null;
  name: string;
  instrument: string;
  surveyed_by: string;
  survey_date: string | null;
  duplicate_policy: DuplicatePolicy;
}

export interface ImportProblem {
  rule_id: string;
  line: number;
  point_id: string;
  detail: string;
}

export interface ImportPreview {
  rows_read: number;
  problem_count: number;
  problems: ImportProblem[];
  rows: { line: number; point_id: string; e: number; n: number; z: number | null; code: string; kind: PointKind }[];
  points_to_import: number;
  source_epsg: number | null;
  target_epsg: number | null;
  will_transform: boolean;
  detected_crs: CrsSuggestion | null;
  existing_conflicts: number;
}

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion: string | null;
  element_ref: string | null;
}

export interface ValidationReport {
  status: string;
  error_count: number;
  warning_count: number;
  info_count: number;
  findings: Finding[];
}

export interface RegisterSummary {
  points: number;
  control: number;
  point_sets: number;
  findings: number;
  last_import: string | null;
}

export const searchCrs = (q: string) => apiGet<{ items: CrsInfo[] }>(`${BASE}/crs/search?q=${encodeURIComponent(q)}`).then((r) => r.items);
export const getProjectCrs = (projectId: string) => apiGet<ProjectCrsState>(`${BASE}/projects/${projectId}/crs`);
export const setProjectCrs = (projectId: string, body: ProjectCrsInput) =>
  apiPut<ProjectCrs>(`${BASE}/projects/${projectId}/crs`, body);
export const confirmProjectCrs = (projectId: string) =>
  apiPost<ProjectCrs>(`${BASE}/projects/${projectId}/crs/confirm`, {});
export const previewImport = (projectId: string, body: ImportBody) =>
  apiPost<ImportPreview>(`${BASE}/projects/${projectId}/import/preview`, body);
export const importPoints = (projectId: string, body: ImportBody) =>
  apiPost<{ point_set: PointSet; imported: number; problems: ImportProblem[] }>(
    `${BASE}/projects/${projectId}/import`,
    body,
  );
export const listPoints = (projectId: string, params: { kind?: string; set_id?: string; q?: string } = {}) => {
  const qs = new URLSearchParams({ limit: '1000' });
  if (params.kind) qs.set('kind', params.kind);
  if (params.set_id) qs.set('set_id', params.set_id);
  if (params.q) qs.set('q', params.q);
  return apiGet<{ items: SurveyPoint[]; total: number }>(`${BASE}/projects/${projectId}/points?${qs.toString()}`);
};
export const listPointSets = (projectId: string) => apiGet<{ items: PointSet[] }>(`${BASE}/projects/${projectId}/point-sets`).then((r) => r.items);
export const deletePointSet = (setId: string) => apiDelete(`${BASE}/point-sets/${setId}`);
export const declareSetCrs = (setId: string, epsg: number) =>
  apiPost<PointSet>(`${BASE}/point-sets/${setId}/declare-crs`, { epsg });
export const getSummary = (projectId: string) => apiGet<RegisterSummary>(`${BASE}/projects/${projectId}/summary`);
export const validateRegister = (projectId: string, locale: string) =>
  apiPost<ValidationReport>(`${BASE}/projects/${projectId}/validate?locale=${encodeURIComponent(locale)}`, {});

// ── Register v2: point detail, bulk actions, export, control checks ─────────

export interface UsedBy {
  kind: string;
  code: string;
  name: string;
  locked: boolean;
}

export interface PointDetail extends SurveyPoint {
  set_name: string;
  source_filename: string;
  source_line: number | null;
  survey_date: string | null;
  stored_epsg: number | null;
  used_by: UsedBy[];
  locked: boolean;
}

export type PointUpdate = Partial<Pick<SurveyPoint, 'point_id' | 'e' | 'n' | 'z' | 'code' | 'kind' | 'description'>> & {
  clear_z?: boolean;
};
export type BulkAction = 'set_code' | 'set_kind' | 'move_to_set' | 'delete';
export interface BulkResult {
  action: BulkAction;
  affected: number;
  skipped_locked: number;
}
export type ExportFormat = 'csv' | 'dxf' | 'landxml';

export interface ControlCheck {
  id: string;
  control_point_id: string;
  measured_point_id: string | null;
  e: number;
  n: number;
  z: number | null;
  de_mm: number;
  dn_mm: number;
  dz_mm: number | null;
  d2d_mm: number;
  verdict: 'pass' | 'fail' | 'no_tolerance';
  note: string;
  created_at: string | null;
}

export interface ControlRow {
  point: SurveyPoint;
  checks: ControlCheck[];
  latest: ControlCheck | null;
}

export interface ControlList {
  items: ControlRow[];
  total: number;
  tolerance_mm: number | null;
  profile_label: string;
  failing: number;
}

export interface ControlCheckInput {
  control_point_id: string;
  measured_point_id?: string | null;
  e?: number | null;
  n?: number | null;
  z?: number | null;
  note?: string;
}

export const getPoint = (id: string) => apiGet<PointDetail>(`${BASE}/points/${id}`);
export const updatePoint = (id: string, body: PointUpdate) => apiPatch<PointDetail>(`${BASE}/points/${id}`, body);
export const deletePoint = (id: string) => apiDelete(`${BASE}/points/${id}`);
export const bulkPoints = (
  projectId: string,
  body: { ids: string[]; action: BulkAction; value?: string; target_set_id?: string },
) => apiPost<BulkResult>(`${BASE}/projects/${projectId}/points/bulk`, body);
export const getControl = (projectId: string) => apiGet<ControlList>(`${BASE}/projects/${projectId}/control`);
export const addControlCheck = (projectId: string, body: ControlCheckInput) =>
  apiPost<ControlCheck>(`${BASE}/projects/${projectId}/control/checks`, body);
export const deleteControlCheck = (projectId: string, checkId: string) =>
  apiDelete(`${BASE}/projects/${projectId}/control/checks/${checkId}`);

/** POST the selection (or every point when `ids` is empty) and save the file the server returns. */
export async function exportPoints(
  projectId: string,
  body: { ids?: string[]; format: ExportFormat; preset?: 'PNEZD' | 'PENZD'; delimiter?: string; header?: boolean },
): Promise<void> {
  const response = await fetchWithAuth(`${API_BASE}${BASE}/projects/${projectId}/points/export`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      detail = extractErrorMessageFromBody(await response.json()) ?? detail;
    } catch {
      // Not JSON; keep the status.
    }
    throw new Error(detail);
  }
  const ext = body.format === 'landxml' ? 'xml' : body.format;
  triggerDownload(await response.blob(), `survey_points.${ext}`);
}
