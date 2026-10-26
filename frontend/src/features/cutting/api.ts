// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth, fetchWithAuth } from '@/shared/lib/api';

// ---------------------------------------------------------------------------
// Types. These mirror backend/app/modules/cutting/schemas.py. Decimal columns
// arrive as JSON strings and stay strings here: they are shown and edited as
// typed, and only the diagram turns them into numbers to scale a drawing.
// ---------------------------------------------------------------------------

export type JobKind = 'linear' | 'sheet';
export type JobStatus = 'draft' | 'optimised' | 'applied';

export interface CuttingPiece {
  id?: string;
  ref: string;
  label: string;
  length_mm: string;
  width_mm: string | null;
  quantity: number;
  rotatable: boolean;
  source_ref?: string | null;
}

export interface CuttingStock {
  id?: string;
  ref: string;
  label: string;
  length_mm: string;
  width_mm: string | null;
  unit_cost: string;
  available: number | null;
  is_offcut: boolean;
  inventory_item_id: string | null;
}

export interface CuttingJob {
  id: string;
  project_id: string;
  name: string;
  kind: JobKind;
  material: string;
  kerf_mm: string;
  trim_mm: string;
  min_offcut_mm: string;
  yield_threshold_pct: string;
  unit_mass_kg: string | null;
  currency: string;
  source_type: string;
  source_ref: string | null;
  boq_position_id: string | null;
  procurement_req_item_id: string | null;
  status: JobStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
  pieces: CuttingPiece[];
  stocks: CuttingStock[];
}

export interface CuttingJobSummary {
  id: string;
  project_id: string;
  name: string;
  kind: JobKind;
  material: string;
  status: JobStatus;
  source_type: string;
  piece_count: number;
  stock_count: number;
  latest_plan_id: string | null;
  latest_yield_pct: string | null;
  latest_waste_pct: string | null;
  latest_cost: string | null;
  updated_at: string;
}

export interface LinearCut {
  ref: string;
  label: string;
  length_mm: string;
  offset_mm: string;
}

export interface LinearBar {
  index: number;
  stock_ref: string;
  stock_label: string;
  length_mm: string;
  is_offcut: boolean;
  inventory_item_id: string | null;
  cost: string;
  cuts: LinearCut[];
  remnant_mm: string;
  offcut_mm: string;
  scrap_mm: string;
}

export interface SheetPlacement {
  ref: string;
  label: string;
  x_mm: string;
  y_mm: string;
  length_mm: string;
  width_mm: string;
  rotated: boolean;
}

export interface SheetRect {
  x_mm: string;
  y_mm: string;
  length_mm: string;
  width_mm: string;
}

export interface SheetLayout {
  index: number;
  stock_ref: string;
  stock_label: string;
  length_mm: string;
  width_mm: string;
  is_offcut: boolean;
  inventory_item_id: string | null;
  cost: string;
  placements: SheetPlacement[];
  offcuts: SheetRect[];
  scrap_m2: string;
}

export interface PlanLayout {
  kind: JobKind;
  kerf_mm: string;
  trim_mm: string;
  bars?: LinearBar[];
  sheets?: SheetLayout[];
}

export interface ValidationFinding {
  rule_id: string;
  rule_name: string;
  severity: string;
  category: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface ValidationReport {
  status: string;
  score: number | null;
  errors: number;
  warnings: number;
  infos: number;
  results: ValidationFinding[];
}

export interface StockUsage {
  ref: string;
  label: string;
  length_mm: string;
  width_mm: string | null;
  count: number;
  unit_cost: string;
  cost: string;
  is_offcut: boolean;
  inventory_item_id: string | null;
}

export interface CuttingPlan {
  id: string;
  job_id: string;
  project_id: string;
  kind: JobKind;
  algorithm: string;
  stock_count: number;
  pieces_placed: number;
  pieces_unplaced: number;
  stock_total: string;
  pieces_total: string;
  offcut_total: string;
  scrap_total: string;
  yield_pct: string;
  waste_pct: string;
  cost: string;
  currency: string;
  exact: boolean;
  proven_optimal: boolean;
  elapsed_ms: number;
  layout: PlanLayout;
  stock_usage: StockUsage[];
  offcuts: { length_mm: string; width_mm: string | null; quantity: number }[];
  unplaced: { ref: string; label: string; quantity: number }[];
  validation: ValidationReport;
  inventory_synced_at: string | null;
  applied_at: string | null;
  created_at: string;
}

export interface CuttingPlanSummary {
  id: string;
  algorithm: string;
  stock_count: number;
  pieces_unplaced: number;
  yield_pct: string;
  waste_pct: string;
  cost: string;
  currency: string;
  proven_optimal: boolean;
  applied_at: string | null;
  inventory_synced_at: string | null;
  created_at: string;
}

export interface LineProposal {
  target: 'boq_position' | 'requisition_item';
  target_id: string;
  label: string;
  unit: string;
  current_quantity: string;
  proposed_quantity: string;
  basis: string;
  appliable: boolean;
  reason: string | null;
}

export interface PlanProposal {
  plan_id: string;
  waste_factor: string;
  waste_pct: string;
  yield_pct: string;
  confidence: number;
  lines: LineProposal[];
}

export interface ApplyResponse {
  plan_id: string;
  results: { target: string; target_id: string; applied: boolean; reason: string | null }[];
}

export interface ImportResult {
  imported: number;
  skipped: number;
  messages: string[];
  job: CuttingJob;
}

export interface InventoryOffcut {
  inventory_item_id: string;
  name: string;
  material: string;
  kind: JobKind;
  length_mm: string;
  width_mm: string | null;
  on_hand: number;
}

export interface JobSettings {
  name: string;
  material: string;
  kerf_mm: string;
  trim_mm: string;
  min_offcut_mm: string;
  yield_threshold_pct: string;
  unit_mass_kg: string | null;
  currency: string;
  boq_position_id: string | null;
  procurement_req_item_id: string | null;
  notes: string | null;
}

export interface JobCreateBody extends Partial<JobSettings> {
  project_id: string;
  name: string;
  kind: JobKind;
}

// ---------------------------------------------------------------------------
// Fetchers
// ---------------------------------------------------------------------------

const BASE = '/v1/cutting';

export async function fetchJobs(projectId: string): Promise<CuttingJobSummary[]> {
  const page = await apiGet<{ items: CuttingJobSummary[]; total: number }>(
    `${BASE}/jobs/?project_id=${encodeURIComponent(projectId)}&limit=200`,
  );
  return page.items;
}

export const fetchJob = (jobId: string) => apiGet<CuttingJob>(`${BASE}/jobs/${jobId}`);

export const createJob = (body: JobCreateBody) => apiPost<CuttingJob, JobCreateBody>(`${BASE}/jobs/`, body);

export const updateJob = (jobId: string, body: Partial<JobSettings>) =>
  apiPatch<CuttingJob, Partial<JobSettings>>(`${BASE}/jobs/${jobId}`, body);

export const deleteJob = (jobId: string) => apiDelete(`${BASE}/jobs/${jobId}`);

export const savePieces = (jobId: string, pieces: CuttingPiece[]) =>
  apiPut<CuttingJob>(`${BASE}/jobs/${jobId}/pieces`, { pieces: pieces.map(pieceBody) });

export const saveStocks = (jobId: string, stocks: CuttingStock[]) =>
  apiPut<CuttingJob>(`${BASE}/jobs/${jobId}/stocks`, { stocks: stocks.map(stockBody) });

export const importRebar = (jobId: string, importId: string, diameterMm: string) =>
  apiPost<ImportResult>(`${BASE}/jobs/${jobId}/import/rebar`, { import_id: importId, diameter_mm: diameterMm });

export const importTakeoff = (jobId: string, groupName: string | null) =>
  apiPost<ImportResult>(`${BASE}/jobs/${jobId}/import/takeoff`, { group_name: groupName || null });

export const importBoq = (jobId: string, positionId: string, pieceLengthMm: string, pieceWidthMm: string | null) =>
  apiPost<ImportResult>(`${BASE}/jobs/${jobId}/import/boq`, {
    position_id: positionId,
    piece_length_mm: pieceLengthMm,
    piece_width_mm: pieceWidthMm || null,
  });

export async function importFile(jobId: string, file: File): Promise<ImportResult> {
  const form = new FormData();
  form.append('upload', file);
  const res = await fetchWithAuth(`/api${BASE}/jobs/${jobId}/import/file`, { method: 'POST', body: form });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    let detail = text;
    try {
      const parsed = JSON.parse(text) as { detail?: unknown };
      if (typeof parsed.detail === 'string') detail = parsed.detail;
    } catch {
      // not JSON; keep the raw text
    }
    throw new ApiError(res.status, res.statusText, { detail });
  }
  return (await res.json()) as ImportResult;
}

export const fetchInventoryOffcuts = (projectId: string, kind: JobKind, material: string) =>
  apiGet<InventoryOffcut[]>(
    `${BASE}/inventory-offcuts/?project_id=${encodeURIComponent(projectId)}&kind=${kind}` +
      (material ? `&material=${encodeURIComponent(material)}` : ''),
  );

export const addInventoryStock = (jobId: string, itemIds: string[]) =>
  apiPost<CuttingJob>(`${BASE}/jobs/${jobId}/stocks/from-inventory`, { inventory_item_ids: itemIds });

export const validateJob = (jobId: string) => apiGet<ValidationReport>(`${BASE}/jobs/${jobId}/validate`);

export const optimiseJob = (jobId: string) => apiPost<CuttingPlan>(`${BASE}/jobs/${jobId}/optimise`);

export const fetchPlans = (jobId: string) => apiGet<CuttingPlanSummary[]>(`${BASE}/jobs/${jobId}/plans`);

export const fetchPlan = (planId: string) => apiGet<CuttingPlan>(`${BASE}/plans/${planId}`);

export const fetchProposal = (planId: string) => apiGet<PlanProposal>(`${BASE}/plans/${planId}/proposal`);

export const applyPlan = (planId: string, applyBoq: boolean, applyProcurement: boolean) =>
  apiPost<ApplyResponse>(`${BASE}/plans/${planId}/apply`, {
    apply_boq: applyBoq,
    apply_procurement: applyProcurement,
  });

export const returnOffcuts = (planId: string) =>
  apiPost<{ plan_id: string; returned: number; consumed: number; item_ids: string[] }>(
    `${BASE}/plans/${planId}/return-offcuts`,
    {},
  );

export function downloadPlan(planId: string, format: 'pdf' | 'xlsx', locale: string): Promise<void> {
  return downloadWithAuth(
    `/api${BASE}/plans/${planId}/export?format=${format}&locale=${encodeURIComponent(locale)}`,
    `cutting-list.${format}`,
  );
}

function pieceBody(p: CuttingPiece) {
  return {
    ref: p.ref.trim(),
    label: p.label.trim(),
    length_mm: p.length_mm,
    width_mm: p.width_mm || null,
    quantity: p.quantity,
    rotatable: p.rotatable,
    source_ref: p.source_ref ?? null,
  };
}

function stockBody(s: CuttingStock) {
  return {
    ref: s.ref.trim(),
    label: s.label.trim(),
    length_mm: s.length_mm,
    width_mm: s.width_mm || null,
    unit_cost: s.unit_cost || '0',
    available: s.available,
    is_offcut: s.is_offcut,
    inventory_item_id: s.inventory_item_id,
  };
}
