// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the survey register: project CRS, point import (preview
 * first, nothing saved until Import), points, point sets and SRV findings.
 */

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

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

export const searchCrs = (q: string) => apiGet<CrsInfo[]>(`${BASE}/crs/search?q=${encodeURIComponent(q)}`);
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
export const listPointSets = (projectId: string) => apiGet<PointSet[]>(`${BASE}/projects/${projectId}/point-sets`);
export const deletePointSet = (setId: string) => apiDelete(`${BASE}/point-sets/${setId}`);
export const declareSetCrs = (setId: string, epsg: number) =>
  apiPost<PointSet>(`${BASE}/point-sets/${setId}/declare-crs`, { epsg });
export const getSummary = (projectId: string) => apiGet<RegisterSummary>(`${BASE}/projects/${projectId}/summary`);
export const validateRegister = (projectId: string, locale: string) =>
  apiPost<ValidationReport>(`${BASE}/projects/${projectId}/validate?locale=${encodeURIComponent(locale)}`, {});
