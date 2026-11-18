// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for surfaces and volumes, traverses, survey profiles and the
 * survey plan. Volumes are bank m3; the screen shows one decimal, the BOQ three.
 */

import type { FeatureCollection } from 'geojson';
import { apiDelete, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

const BASE = '/v1/surfaces-volumes';
const CORE = '/v1/survey-core';

export type VolumeMethod = 'grid' | 'tin' | 'end_area';
export const VOLUME_METHODS: VolumeMethod[] = ['grid', 'tin', 'end_area'];
export type QuantityKind = 'cut' | 'fill' | 'net' | 'loose_cut';
export type VolumeStatus = 'draft' | 'confirmed' | 'sent';

export interface Surface {
  id: string;
  project_id: string;
  code: string;
  name: string;
  source: 'points' | 'landxml' | 'dtm';
  source_filename: string;
  epsg: number | null;
  accuracy_tier: string | null;
  point_count: number;
  triangle_count: number;
  area_m2: number;
  z_min: number | null;
  z_max: number | null;
  in_use: number;
  created_at: string | null;
}

export interface Finding {
  rule_id: string;
  severity: 'error' | 'warning' | 'info' | string;
  message: string;
  suggestion?: string | null;
  element_ref?: string | null;
}

export interface Volume {
  id: string;
  project_id: string;
  code: string;
  name: string;
  base_surface_id: string | null;
  compare_surface_id: string | null;
  base_name: string;
  compare_name: string;
  method: VolumeMethod;
  cell_size_m: number | null;
  cell_auto: boolean;
  boundary: number[][] | null;
  material: string;
  swell_factor: number;
  shrink_factor: number;
  cut_m3: number;
  fill_m3: number;
  net_m3: number;
  loose_cut_m3: number;
  calc_area_m2: number;
  coverage_pct: number;
  confidence: number | null;
  crs_epsg: number | null;
  crs_name: string;
  accuracy_tier: string | null;
  status: VolumeStatus;
  confirmed_by_name: string;
  confirmed_at: string | null;
  override_reason: string;
  duplicated_from_id: string | null;
  boq_position_id: string | null;
  findings: Finding[];
}

export interface VolumeSummary {
  calculations: number;
  confirmed: number;
  cut_m3: number;
  fill_m3: number;
  net_m3: number;
  coverage_pct: number | null;
  surfaces: number;
  findings: number;
}

export interface VolumeEvent {
  id: string;
  action: 'computed' | 'override' | 'confirmed' | 'duplicated' | 'sent_boq' | 'progress' | 'report' | string;
  target_type: string;
  target_id: string;
  quantity: number | null;
  details: Record<string, unknown>;
  user_name: string;
  created_at: string | null;
}

export interface BoqPositionHit {
  id: string;
  boq_id: string;
  boq_name: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
}

export interface SendResult {
  position_id: string;
  ordinal: string;
  description: string;
  unit: string;
  quantity: string;
  sent_m3: number;
  formula: string;
  findings: Finding[];
}

export interface VolumeInput {
  name: string;
  base_surface_id: string;
  compare_surface_id: string;
  method?: VolumeMethod;
  cell_size_m?: number | null;
  boundary?: [number, number][] | null;
  material?: string;
  swell_factor?: number;
  shrink_factor?: number;
  override_reason?: string;
}

export interface TraverseLeg {
  leg: string;
  from: string;
  to: string;
  length_m: number;
  d_e: number;
  d_n: number;
  c_e: number;
  c_n: number;
}

export interface Traverse {
  id: string;
  name: string;
  kind: 'traverse' | 'level';
  legs: TraverseLeg[];
  length_m: number;
  f_e: number | null;
  f_n: number | null;
  misclosure_m: number | null;
  ratio: number | null;
  profile_ratio: number | null;
  distance_km: number | null;
  misclosure_mm: number | null;
  k_mm: number | null;
  allowed_mm: number | null;
  verdict: 'pass' | 'fail' | 'no_profile';
  profile_label: string;
}

export interface TraverseInput {
  name: string;
  kind: 'traverse' | 'level';
  text?: string;
  distance_km?: number;
  misclosure_mm?: number;
  k_mm?: number;
}

export interface SurveyProfile {
  scope: 'project' | 'workspace' | 'none';
  source: string;
  label: string;
  traverse_min_ratio: number | null;
  level_k_mm: number | null;
  coverage_min_pct: number | null;
}

export type SurveyPlan = FeatureCollection & { properties?: { epsg: number | null; local_grid: boolean } };

const p = (projectId: string) => `${BASE}/projects/${projectId}`;

export const listSurfaces = (projectId: string) => apiGet<{ items: Surface[] }>(`${p(projectId)}/surfaces`).then((r) => r.items);
export const surfaceFromPoints = (projectId: string, body: { name: string; point_set_ids: string[] }) =>
  apiPost<Surface>(`${p(projectId)}/surfaces/from-points`, body);
export const importLandXml = (projectId: string, body: { text: string; filename: string; name?: string }) =>
  apiPost<{ surfaces: Surface[]; problems: string[] }>(`${p(projectId)}/surfaces/landxml`, body);
export const deleteSurface = (id: string) => apiDelete(`${BASE}/surfaces/${id}`);

export const listVolumes = (projectId: string, locale: string) =>
  apiGet<{ items: Volume[] }>(`${p(projectId)}/volumes?locale=${encodeURIComponent(locale)}`).then((r) => r.items);
export const getVolumeSummary = (projectId: string) => apiGet<VolumeSummary>(`${p(projectId)}/summary`);
export const createVolume = (projectId: string, body: VolumeInput) => apiPost<Volume>(`${p(projectId)}/volumes`, body);
export const updateVolume = (id: string, body: Partial<VolumeInput> & { cell_auto?: boolean }) =>
  apiPatch<Volume>(`${BASE}/volumes/${id}`, body);
export const deleteVolume = (id: string) => apiDelete(`${BASE}/volumes/${id}`);
export const confirmVolume = (id: string, acknowledge: string[], locale: string) =>
  apiPost<Volume>(`${BASE}/volumes/${id}/confirm?locale=${encodeURIComponent(locale)}`, { acknowledge });
export const duplicateVolume = (id: string, body: Partial<VolumeInput>) =>
  apiPost<Volume>(`${BASE}/volumes/${id}/duplicate`, body);
export const sendToBoq = (id: string, body: { position_id: string; mode: 'replace' | 'add'; quantity: QuantityKind }, locale: string) =>
  apiPost<SendResult>(`${BASE}/volumes/${id}/send-to-boq?locale=${encodeURIComponent(locale)}`, body);
export const recordProgress = (id: string, body: { position_id?: string; quantity: QuantityKind; period_label?: string }) =>
  apiPost<{ entry_id: string; percent_complete: number; quantity_m3: number; period_label: string }>(
    `${BASE}/volumes/${id}/record-progress`,
    body,
  );
export const volumeHistory = (id: string) => apiGet<{ items: VolumeEvent[] }>(`${BASE}/volumes/${id}/history`).then((r) => r.items);
export const searchBoqPositions = (projectId: string, q: string) =>
  apiGet<{ items: BoqPositionHit[] }>(`${p(projectId)}/boq-positions?q=${encodeURIComponent(q)}&unit=m3`).then((r) => r.items);
export const volumeReportUrl = (id: string, locale: string) =>
  `/api${BASE}/volumes/${id}/report.pdf?locale=${encodeURIComponent(locale)}`;
export const getVolumesPlan = (projectId: string, volumeId?: string | null) =>
  apiGet<SurveyPlan>(`${p(projectId)}/plan${volumeId ? `?volume_id=${volumeId}` : ''}`);

export const getRegisterPlan = (projectId: string) => apiGet<SurveyPlan>(`${CORE}/projects/${projectId}/plan`);
export const listTraverses = (projectId: string) => apiGet<{ items: Traverse[] }>(`${CORE}/projects/${projectId}/traverses`).then((r) => r.items);
export const createTraverse = (projectId: string, body: TraverseInput) =>
  apiPost<Traverse>(`${CORE}/projects/${projectId}/traverses`, body);
export const deleteTraverse = (id: string) => apiDelete(`${CORE}/traverses/${id}`);
export const getDefaultProfile = () => apiGet<SurveyProfile>(`${CORE}/profile`);
export const putDefaultProfile = (body: Omit<SurveyProfile, 'scope' | 'source'>) =>
  apiPut<SurveyProfile>(`${CORE}/profile`, body);

/** Bank m3 for display: one decimal, grouped per the reader's locale. */
export function formatM3(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(value);
}

/** Which side the net volume is on, for "1,200.0 m3 cut". */
export function netSide(net: number): 'cut' | 'fill' | 'balanced' {
  if (net > 0.05) return 'cut';
  if (net < -0.05) return 'fill';
  return 'balanced';
}
