// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for setting-out: requests, design import, stakes, measured
 * records with their verdict, NCR drafts and the setting-out sheet.
 */

import { API_BASE, activeLanguageTag, apiDelete, apiGet, apiPatch, apiPost, downloadWithAuth } from '@/shared/lib/api';

const BASE = '/v1/setting-out';

export type ItemType = 'column' | 'wall' | 'pile' | 'anchor_bolt' | 'kerb' | 'centreline' | 'grid_line' | 'other';
export const ITEM_TYPES: ItemType[] = ['column', 'wall', 'pile', 'anchor_bolt', 'kerb', 'centreline', 'grid_line', 'other'];
export type RefType = '' | 'boq' | 'bim' | 'cad';
export type Verdict = 'pass' | 'fail' | 'no_tolerance';
export type StakeState = Verdict | 'open';

export interface ToleranceProfile {
  key: string;
  name: string;
  source: 'demo' | 'pack' | 'project';
  country: string;
  reference: string;
  items: Record<string, { h_mm: number; v_mm: number | null }>;
}

export interface StakeRecord {
  id: string;
  point_id: string;
  measured_e: number;
  measured_n: number;
  measured_z: number | null;
  de_mm: number;
  dn_mm: number;
  d_mm: number;
  dz_mm: number | null;
  tol_h_mm: number | null;
  tol_v_mm: number | null;
  verdict: Verdict;
  instrument: string;
  control_ref: string;
  measured_by: string;
  measured_at: string;
  note: string;
  ncr_id: string | null;
}

export interface Stake {
  id: string;
  point_id: string;
  design_e: number;
  design_n: number;
  design_z: number | null;
  chainage: number | null;
  offset_m: number | null;
  code: string;
  verdict: StakeState;
  latest: StakeRecord | null;
  record_count: number;
}

export interface StakeoutRequest {
  id: string;
  project_id: string;
  code: string;
  name: string;
  item_type: ItemType;
  tolerance_key: string;
  tolerance_label: string;
  tolerance_source: string;
  tol_h_mm: number | null;
  tol_v_mm: number | null;
  element_ref_type: RefType;
  element_ref_id: string;
  element_ref_label: string;
  alignment: { name: string; start_chainage: number; length: number } | null;
  instrument: string;
  control_ref: string;
  source_filename: string;
  note: string;
  created_at: string;
  point_count: number;
  open_count: number;
  pass_count: number;
  fail_count: number;
}

export interface StakeoutRequestDetail extends StakeoutRequest {
  stakes: Stake[];
}

export interface RequestInput {
  name: string;
  item_type: ItemType;
  tolerance_key: string;
  tol_h_mm?: number | null;
  tol_v_mm?: number | null;
  element_ref_type?: RefType;
  element_ref_id?: string;
  element_ref_label?: string;
  instrument?: string;
  control_ref?: string;
  note?: string;
}

export interface DesignImportInput {
  text: string;
  filename: string;
  file_format: 'csv' | 'landxml';
  mode?: 'add' | 'replace';
}

export interface ImportProblem {
  line: number;
  point_id: string;
  message: string;
}

export interface DesignPreview {
  rows_read: number;
  points: { point_id: string; e: number; n: number; z: number | null; chainage: number | null; offset_m: number | null }[];
  alignment: { name: string; length: number } | null;
  problems: ImportProblem[];
  problem_count: number;
}

export interface RecordInput {
  measured_e: number;
  measured_n: number;
  measured_z?: number | null;
  instrument?: string | null;
  control_ref?: string | null;
  note?: string;
}

export interface Finding {
  rule_id: string;
  severity: string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface ValidationReport {
  status: string;
  error_count: number;
  warning_count: number;
  info_count: number;
  findings: Finding[];
}

export interface Summary {
  requests: number;
  open: number;
  passed: number;
  failed: number;
  ncr_drafts: number;
}

export const listProfiles = (projectId: string) => apiGet<ToleranceProfile[]>(`${BASE}/projects/${projectId}/profiles`);
export const listRequests = (projectId: string) => apiGet<StakeoutRequest[]>(`${BASE}/projects/${projectId}/requests`);
export const createRequest = (projectId: string, body: RequestInput) =>
  apiPost<StakeoutRequest, RequestInput>(`${BASE}/projects/${projectId}/requests`, body);
export const getSummary = (projectId: string) => apiGet<Summary>(`${BASE}/projects/${projectId}/summary`);
export const validateSettingOut = (projectId: string, locale: string) =>
  apiPost<ValidationReport>(`${BASE}/projects/${projectId}/validate?locale=${encodeURIComponent(locale)}`);
export const loadDemo = (projectId: string) =>
  apiPost<StakeoutRequestDetail>(`${BASE}/projects/${projectId}/demo/riverside`);
export const getRequest = (id: string) => apiGet<StakeoutRequestDetail>(`${BASE}/requests/${id}`);
export const updateRequest = (id: string, body: Partial<RequestInput>) =>
  apiPatch<StakeoutRequest, Partial<RequestInput>>(`${BASE}/requests/${id}`, body);
export const deleteRequest = (id: string) => apiDelete(`${BASE}/requests/${id}`);
export const previewDesign = (id: string, body: DesignImportInput) =>
  apiPost<DesignPreview, DesignImportInput>(`${BASE}/requests/${id}/design/preview`, body);
export const importDesign = (id: string, body: DesignImportInput) =>
  apiPost<StakeoutRequestDetail, DesignImportInput>(`${BASE}/requests/${id}/design`, body);
export const recordStake = (stakeId: string, body: RecordInput) =>
  apiPost<StakeRecord, RecordInput>(`${BASE}/stakes/${stakeId}/records`, body);
export const stakeHistory = (stakeId: string) => apiGet<StakeRecord[]>(`${BASE}/stakes/${stakeId}/records`);
export const createNcrDraft = (recordId: string, locale: string) =>
  apiPost<{ ncr_id: string; ncr_number: string; record_id: string }>(
    `${BASE}/records/${recordId}/ncr?locale=${encodeURIComponent(locale)}`,
  );

export async function downloadSheet(id: string, code: string): Promise<void> {
  const lang = activeLanguageTag();
  const query = lang ? `?locale=${encodeURIComponent(lang)}` : '';
  await downloadWithAuth(`${API_BASE}${BASE}/requests/${encodeURIComponent(id)}/sheet.pdf${query}`, `setting-out-${code}.pdf`);
}
