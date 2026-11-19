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
  digitSystemHeader,
  extractErrorMessageFromBody,
  fetchWithAuth,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';

const BASE = '/v1/survey-core';

export type PointKind = 'control' | 'benchmark' | 'topo' | 'stake' | 'asbuilt';
export const POINT_KINDS: PointKind[] = ['control', 'benchmark', 'topo', 'stake', 'asbuilt'];
export type FileFormat = 'csv' | 'txt' | 'geojson' | 'gsi' | 'jobxml' | 'landxml';
export type LinearUnit = 'm' | 'ft' | 'ftUS';
export type FootDefinition = '' | 'ft' | 'ftUS';
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
  /** National systems: primary, a zone of it, or a legacy grid still found on drawings. */
  role?: 'primary' | 'zone' | 'legacy' | '';
  note?: string;
  vertical_epsg?: number | null;
  vertical_name?: string | null;
  geoid_grid?: string | null;
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
  /** A feet file for a metre project names its foot (SRV-031). */
  foot_definition?: FootDefinition;
  /** `local`: the file is in the site grid and goes through the project's local grid tie. */
  coords?: 'grid' | 'local';
}

export interface ImportProblem {
  rule_id: string;
  line: number;
  point_id: string;
  detail: string;
  message?: string;
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
  file_unit?: string;
  project_unit?: string;
  unit_converted?: boolean;
  heights_converted?: boolean;
  missing_grids?: string[];
  local_grid_applied?: boolean;
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

// ── Geodesy: unit, local grid, grid/ground, export ────────────────────────────

export interface LocalGridPoint {
  point_id: string;
  x: number;
  y: number;
  e: number;
  n: number;
  use: boolean;
}

export interface LocalGridResidual {
  point_id: string;
  de_mm: number;
  dn_mm: number;
  r_mm: number;
  used: boolean;
}

export interface LocalGridSolution {
  scale: number;
  scale_ppm: number;
  rotation_deg: number;
  te: number;
  tn: number;
  rms_mm: number;
  fitted: number;
  residuals: LocalGridResidual[];
}

export interface ScaleFactor {
  epsg: number;
  e: number;
  n: number;
  height_m: number;
  k: number;
  elevation_factor: number;
  csf: number;
  distance_m: number;
  grid_m: number;
  ground_m: number;
  diff_mm: number;
  height_source: 'setting' | 'points' | 'none';
}

export interface GeodesyInput {
  linear_unit: '' | LinearUnit;
  local_grid_epsg: number | null;
  local_points: LocalGridPoint[];
  apply_local_grid: boolean;
  residual_tol_mm: number | null;
  scale_tol_ppm: number | null;
  csf_height_m: number | null;
  reference_distance_m: number | null;
}

export interface Geodesy extends GeodesyInput {
  project_id: string;
  effective_unit: LinearUnit;
  solution: LocalGridSolution | null;
  scale: ScaleFactor | null;
}

export type ExportFormat = 'csv' | 'geojson' | 'gsi' | 'landxml' | 'dxf';
export const EXPORT_FORMATS: ExportFormat[] = ['csv', 'geojson', 'gsi', 'landxml', 'dxf'];
export const CSV_PRESETS = ['PNEZD', 'PENZD', 'ENZ', 'NEZ'] as const;

export const getGeodesy = (projectId: string) => apiGet<Geodesy>(`${BASE}/projects/${projectId}/geodesy`);
export const setGeodesy = (projectId: string, body: GeodesyInput) => apiPut<Geodesy>(`${BASE}/projects/${projectId}/geodesy`, body);
export const solveLocalGrid = (points: LocalGridPoint[]) => apiPost<LocalGridSolution>(`${BASE}/local-grid/solve`, { points });
export const getScaleFactor = (projectId: string, distance?: number) =>
  apiGet<ScaleFactor | null>(`${BASE}/projects/${projectId}/scale-factor${distance ? `?d=${distance}` : ''}`);

export interface ExportOptions {
  format: ExportFormat;
  preset?: string;
  delimiter?: string;
  kind?: string;
  set_id?: string;
  target_epsg?: number | null;
  local?: boolean;
  locale?: string;
}

export function exportQuery(o: ExportOptions): string {
  const qs = new URLSearchParams({ format: o.format });
  if (o.format === 'csv') {
    if (o.preset) qs.set('preset', o.preset);
    if (o.delimiter) qs.set('delimiter', o.delimiter);
  }
  if (o.kind) qs.set('kind', o.kind);
  if (o.set_id) qs.set('set_id', o.set_id);
  if (o.local) qs.set('local', 'true');
  else if (o.target_epsg) qs.set('target_epsg', String(o.target_epsg));
  if (o.locale) qs.set('locale', o.locale);
  return qs.toString();
}

export const registerExportUrl = (projectId: string, o: ExportOptions) => `/api${BASE}/projects/${projectId}/export?${exportQuery(o)}`;
export const stakeExportUrl = (requestId: string, o: ExportOptions) =>
  `/api/v1/setting-out/requests/${requestId}/export?${exportQuery({ format: o.format, locale: o.locale })}`;

/** Download an export and return the rule ids the server flagged (e.g. SRV-110 for another CRS). */
export async function downloadSurveyExport(url: string, fallbackFilename: string): Promise<string[]> {
  const headers: Record<string, string> = { Accept: 'application/octet-stream' };
  const token = getAuthToken();
  if (token) headers['Authorization'] = `Bearer ${token}`;
  const digits = digitSystemHeader();
  if (digits) headers['X-Digit-System'] = digits;
  const response = await fetch(url, { method: 'GET', headers });
  if (!response.ok) {
    let detail = `Download failed (HTTP ${response.status})`;
    try {
      detail = extractErrorMessageFromBody(await response.json()) ?? detail;
    } catch {
      // Not JSON; keep the status message.
    }
    throw new Error(detail);
  }
  const blob = await response.blob();
  const name = response.headers.get('Content-Disposition')?.match(/filename="?([^";]+)"?/)?.[1];
  triggerDownload(blob, name || fallbackFilename);
  return (response.headers.get('X-Survey-Warnings') ?? '').split(',').filter(Boolean);
}

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
