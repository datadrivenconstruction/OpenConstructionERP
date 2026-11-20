// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for surfaces and volumes, traverses, survey profiles and the
 * survey plan. Volumes are bank m3; the screen shows one decimal, the BOQ three.
 */

import type { FeatureCollection } from 'geojson';
import {
  API_BASE,
  apiDelete,
  apiGet,
  apiPatch,
  apiPost,
  apiPut,
  extractErrorMessageFromBody,
  fetchWithAuth,
} from '@/shared/lib/api';


export type VolumeMethod = 'grid' | 'tin' | 'end_area';
export const VOLUME_METHODS: VolumeMethod[] = ['grid', 'tin', 'end_area'];
export type QuantityKind = 'cut' | 'fill' | 'net' | 'loose_cut';
export type VolumeStatus = 'draft' | 'confirmed' | 'sent';

export interface Surface {
  id: string;
  project_id: string;
  code: string;
  name: string;
  source: 'points' | 'landxml' | 'dtm' | 'pointcloud';
  source_filename: string;
  epsg: number | null;
  accuracy_tier: string | null;
  point_count: number;
  triangle_count: number;
  area_m2: number;
  z_min: number | null;
  z_max: number | null;
  in_use: number;
  breakline_count?: number;
  findings?: Finding[];
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


export const listSurfaces = (projectId: string) => apiGet<{ items: Surface[] }>(`/v1/surfaces-volumes/projects/${projectId}/surfaces`).then((r) => r.items);
export interface SurfaceFromPointsBody {
  name: string;
  point_set_ids: string[];
  breakline_codes?: string[];
  boundary?: [number, number][] | null;
}
export const surfaceFromPoints = (projectId: string, body: SurfaceFromPointsBody) =>
  apiPost<Surface>(`/v1/surfaces-volumes/projects/${projectId}/surfaces/from-points`, body);
export const importLandXml = (projectId: string, body: { text: string; filename: string; name?: string }) =>
  apiPost<{ surfaces: Surface[]; problems: string[] }>(`/v1/surfaces-volumes/projects/${projectId}/surfaces/landxml`, body);
export const deleteSurface = (id: string) => apiDelete(`/v1/surfaces-volumes/surfaces/${id}`);

export const listVolumes = (projectId: string, locale: string) =>
  apiGet<{ items: Volume[] }>(`/v1/surfaces-volumes/projects/${projectId}/volumes?locale=${encodeURIComponent(locale)}`).then((r) => r.items);
export const getVolumeSummary = (projectId: string) => apiGet<VolumeSummary>(`/v1/surfaces-volumes/projects/${projectId}/summary`);
export const createVolume = (projectId: string, body: VolumeInput) => apiPost<Volume>(`/v1/surfaces-volumes/projects/${projectId}/volumes`, body);
export const updateVolume = (id: string, body: Partial<VolumeInput> & { cell_auto?: boolean }) =>
  apiPatch<Volume>(`/v1/surfaces-volumes/volumes/${id}`, body);
export const deleteVolume = (id: string) => apiDelete(`/v1/surfaces-volumes/volumes/${id}`);
export const confirmVolume = (id: string, acknowledge: string[], locale: string) =>
  apiPost<Volume>(`/v1/surfaces-volumes/volumes/${id}/confirm?locale=${encodeURIComponent(locale)}`, { acknowledge });
export const duplicateVolume = (id: string, body: Partial<VolumeInput>) =>
  apiPost<Volume>(`/v1/surfaces-volumes/volumes/${id}/duplicate`, body);
export const sendToBoq = (id: string, body: { position_id: string; mode: 'replace' | 'add'; quantity: QuantityKind }, locale: string) =>
  apiPost<SendResult>(`/v1/surfaces-volumes/volumes/${id}/send-to-boq?locale=${encodeURIComponent(locale)}`, body);
export const recordProgress = (id: string, body: { position_id?: string; quantity: QuantityKind; period_label?: string }) =>
  apiPost<{ entry_id: string; percent_complete: number; quantity_m3: number; period_label: string }>(
    `/v1/surfaces-volumes/volumes/${id}/record-progress`,
    body,
  );
export interface MeasuredFinding {
  rule_id: string;
  severity: string;
  message: string;
  key: string;
  params: Record<string, string>;
}

/** What a measured quantity would put on the open payment certificate; nothing is written yet. */
export interface MeasuredPreview {
  boq_position_id: string;
  ordinal: string;
  description: string;
  boq_quantity: string;
  boq_unit: string;
  quantity: string;
  unit: string;
  quantity_kind: QuantityKind;
  contract: { id: string; code: string; title: string; currency: string } | null;
  line: { id: string; code: string; description: string; unit: string; quantity: string; unit_rate: string; total_value: string } | null;
  claim: {
    id: string;
    number: string;
    status: string;
    currency: string;
    gross_amount: string | null;
    retention_amount: string | null;
    net_due: string | null;
  } | null;
  figures: {
    percent_to_date: string;
    capped: boolean;
    period_qty: string;
    period_value: string;
    prior_value: string;
    cumulative_value: string;
  } | null;
  findings: MeasuredFinding[];
  can_commit: boolean;
  progress_entry_id?: string | null;
}

export interface CertifyInput {
  position_id: string;
  quantity: QuantityKind;
  claim_id?: string;
}

export const certifyVolumePreview = (id: string, body: CertifyInput) =>
  apiPost<MeasuredPreview>(`/v1/surfaces-volumes/volumes/${id}/certify/preview`, body);
export const certifyVolume = (id: string, body: CertifyInput) =>
  apiPost<MeasuredPreview>(`/v1/surfaces-volumes/volumes/${id}/certify`, body);

export interface HaulBasisRow {
  basis: 'volume' | 'weighbridge' | 'capacity' | 'unresolved';
  tickets: number;
  loads: number;
  hauled_m3: string;
}

/** Excavated loose m3 of a volume or stockpile against the m3 its linked haul tickets carried. */
export interface HauledVsExcavated {
  target: 'volume' | 'stockpile';
  target_id: string;
  code: string;
  name: string;
  excavated_m3: string | null;
  excavated_basis: 'loose_cut' | 'bank_cut' | 'stockpile_survey' | 'none';
  swell_factor: string | null;
  hauled_m3: string;
  tickets: number;
  loads: number;
  by_basis: HaulBasisRow[];
  difference_m3: string | null;
  difference_pct: string | null;
  threshold_pct: number;
  within_threshold: boolean | null;
  findings: { rule_id: string; severity: string; message: string }[];
}

export const hauledVsExcavated = (projectId: string, target: { volume_id?: string; stockpile_id?: string }) =>
  apiGet<HauledVsExcavated>(
    `/v1/haul_tickets/projects/${projectId}/hauled-vs-excavated?${new URLSearchParams(target as Record<string, string>).toString()}`,
  );
export const volumeHistory = (id: string) => apiGet<{ items: VolumeEvent[] }>(`/v1/surfaces-volumes/volumes/${id}/history`).then((r) => r.items);
export const searchBoqPositions = (projectId: string, q: string) =>
  apiGet<{ items: BoqPositionHit[] }>(`/v1/surfaces-volumes/projects/${projectId}/boq-positions?q=${encodeURIComponent(q)}&unit=m3`).then((r) => r.items);
export const volumeReportUrl = (id: string, locale: string) =>
  `/api/v1/surfaces-volumes/volumes/${id}/report.pdf?locale=${encodeURIComponent(locale)}`;
export const getVolumesPlan = (projectId: string, volumeId?: string | null) =>
  apiGet<SurveyPlan>(`/v1/surfaces-volumes/projects/${projectId}/plan${volumeId ? `?volume_id=${volumeId}` : ''}`);

export const getRegisterPlan = (projectId: string) => apiGet<SurveyPlan>(`/v1/survey-core/projects/${projectId}/plan`);
export const listTraverses = (projectId: string) => apiGet<{ items: Traverse[] }>(`/v1/survey-core/projects/${projectId}/traverses`).then((r) => r.items);
export const createTraverse = (projectId: string, body: TraverseInput) =>
  apiPost<Traverse>(`/v1/survey-core/projects/${projectId}/traverses`, body);
export const deleteTraverse = (id: string) => apiDelete(`/v1/survey-core/traverses/${id}`);
export const getDefaultProfile = () => apiGet<SurveyProfile>(`/v1/survey-core/profile`);
export const putDefaultProfile = (body: Omit<SurveyProfile, 'scope' | 'source'>) =>
  apiPut<SurveyProfile>(`/v1/survey-core/profile`, body);

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

// ── Point clouds and staged volumes ─────────────────────────────────────────

export type CloudStat = 'min' | 'mean' | 'max';

export interface CloudImportResult {
  surface: Surface;
  points_read: number;
  points_used: number;
  ground_points: number;
  used_all_classes: boolean;
  cells: number;
  cell_size_m: number;
  stat: CloudStat;
  las_version: string;
  compressed: boolean;
}

export interface StageInput {
  label: string;
  surface_id?: string | null;
  strip_depth_m?: number | null;
  surveyed_on?: string;
  material?: string;
}

export interface MaterialFactors {
  loose?: number | null;
  compacted?: number | null;
}

export interface StageStep {
  index: number;
  from_label: string;
  to_label: string;
  surveyed_on: string;
  material: string;
  cut_m3: number;
  fill_m3: number;
  net_m3: number;
  coverage_pct: number;
  cut_loose_m3: number | null;
  fill_bank_needed_m3: number | null;
  cumulative_cut_m3: number;
  cumulative_fill_m3: number;
}

export interface StagedResult {
  steps: StageStep[];
  total_cut_m3: number;
  total_fill_m3: number;
  method: string;
  findings: Finding[];
}

export const CLOUD_MAX_BYTES = 2 * 1024 ** 3;

/** Upload a LAS or LAZ file; the server grids it and stores the cells as a surface. */
export async function importPointCloud(
  projectId: string,
  file: File,
  opts: { name?: string; cell_size_m: number; stat: CloudStat; ground_only: boolean; locale: string },
): Promise<CloudImportResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('name', opts.name ?? '');
  form.append('cell_size_m', String(opts.cell_size_m));
  form.append('stat', opts.stat);
  form.append('ground_only', String(opts.ground_only));
  // E57 is read by the point cloud module on the same gridding path as LAS.
  const path = file.name.toLowerCase().endsWith('.e57')
    ? `/v1/pointcloud/projects/${projectId}/surfaces/cloud`
    : `/v1/surfaces-volumes/projects/${projectId}/surfaces/point-cloud`;
  const response = await fetchWithAuth(`${API_BASE}${path}?locale=${encodeURIComponent(opts.locale)}`, {
    method: 'POST',
    body: form,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(extractErrorMessageFromBody(body) ?? `HTTP ${response.status}`);
  return body as CloudImportResult;
}

export const computeStaged = (
  projectId: string,
  body: { stages: StageInput[]; method?: VolumeMethod; cell_size_m?: number | null; factors?: Record<string, MaterialFactors> },
  locale: string,
) => apiPost<StagedResult>(`/v1/surfaces-volumes/projects/${projectId}/staged-volumes?locale=${encodeURIComponent(locale)}`, body);
