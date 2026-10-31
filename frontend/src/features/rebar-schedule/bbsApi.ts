// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the typed bar bending schedule (/v1/rebar-schedule/bbs and /shape-codes).
 * Dimensions and weights arrive and leave as decimal strings.
 */
import { API_BASE, apiDelete, apiGet, apiPost, downloadWithAuth } from '@/shared/lib/api';

export type ShapeStandard = 'BS8666' | 'IS2502';
export type DimKey = 'dim_a' | 'dim_b' | 'dim_c' | 'dim_d' | 'dim_e';

export interface ShapeCode {
  standard: ShapeStandard;
  code: string;
  description: string;
  dimensions: string[];
  formula: string;
}

export interface BbsEntry {
  id: string;
  project_id: string;
  member: string;
  bar_mark: string;
  diameter_mm: number;
  shape_standard: ShapeStandard;
  shape_code: string;
  dim_a: string | null;
  dim_b: string | null;
  dim_c: string | null;
  dim_d: string | null;
  dim_e: string | null;
  members_count: number;
  bars_per_member: number;
  steel_grade: string | null;
  lap_length_mm: string | null;
  boq_position_id: string | null;
  notes: string | null;
  cut_length_mm: string;
  unit_weight_kg_m: string;
  total_length_m: string;
  weight_kg: string;
}

export interface BbsInput {
  project_id: string;
  member: string;
  bar_mark: string;
  diameter_mm: number;
  shape_standard: ShapeStandard;
  shape_code: string;
  dim_a?: string;
  dim_b?: string;
  dim_c?: string;
  dim_d?: string;
  dim_e?: string;
  members_count: number;
  bars_per_member: number;
  steel_grade?: string;
  lap_length_mm?: string;
  boq_position_id?: string;
  notes?: string;
}

export interface BbsDiameterTotal {
  diameter_mm: number;
  bar_count: number;
  total_length_m: string;
  weight_kg: string;
}

export interface BbsSchedule {
  items: BbsEntry[];
  totals_by_diameter: BbsDiameterTotal[];
  total_weight_kg: string;
}

export interface BbsFinding {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
  element_ref: string | null;
}

export const BBS_DIAMETERS = [6, 8, 10, 12, 16, 20, 25, 32, 40];

export const fetchShapeCodes = () => apiGet<ShapeCode[]>(`/v1/rebar-schedule/shape-codes/`);
export const fetchBbs = (projectId: string) => apiGet<BbsSchedule>(`/v1/rebar-schedule/bbs/?project_id=${projectId}`);
export const createBbsEntry = (body: BbsInput) => apiPost<BbsEntry>(`/v1/rebar-schedule/bbs/`, body);
export const deleteBbsEntry = (id: string) => apiDelete(`/v1/rebar-schedule/bbs/${id}`);
export const fetchBbsValidation = (projectId: string, lapMultiple = 50, tolerancePct = 5) =>
  apiGet<{ status: string; results: BbsFinding[] }>(
    `/v1/rebar-schedule/bbs/validation/?project_id=${projectId}&lap_multiple=${lapMultiple}&tolerance_pct=${tolerancePct}`,
  );
export const downloadBbsCsv = (projectId: string) =>
  downloadWithAuth(`${API_BASE}/v1/rebar-schedule/bbs/export.csv?project_id=${projectId}`, 'bar-bending-schedule.csv');
