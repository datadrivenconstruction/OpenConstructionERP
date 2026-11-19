// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the mine survey: periods, one line per unit, the actual that
 * comes from a Volumes calculation, truck loads and the claim. Volumes show
 * one decimal, tonnes two, percentages two.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { Finding } from './volumesApi';


export type UnitType = 'pit' | 'bench' | 'block' | 'stope' | 'drive';
export const UNIT_TYPES: UnitType[] = ['pit', 'bench', 'block', 'stope', 'drive'];

export interface MineActual {
  volume_id: string;
  code: string;
  status: 'draft' | 'confirmed' | 'sent';
  method: string;
  cell_size_m: number | null;
  coverage_pct: number;
  crs_epsg: number | null;
  confirmed_by_name: string;
  confirmed_at: string | null;
}

export interface MineEntry {
  id: string;
  period_id: string;
  unit_id: string;
  unit_code: string;
  unit_name: string;
  unit_type: UnitType;
  underground: boolean;
  plan_m3: number;
  plan_t: number | null;
  plan_advance_m: number | null;
  actual_advance_m: number | null;
  advance_pct: number | null;
  density_t_m3: number | null;
  actual_m3: number | null;
  actual: MineActual | null;
  compliance_pct: number | null;
  survey_t: number | null;
  truck_loads: number;
  truck_t: number | null;
  truck_factor_pct: number | null;
  truck_source: string;
  claim_entry_id: string | null;
  claimed_m3: number | null;
  claimed_by_name: string;
  findings: Finding[];
  truck_ratio_pct?: number | null;
  material_split?: MaterialSplit | null;
  drive?: DriveSummary | null;
}

export interface MaterialSplitPart {
  material: string;
  name: string;
  volume_m3: number;
  density_t_m3: number | null;
  tonnes: number | null;
}

export interface MaterialSplit {
  parts: MaterialSplitPart[];
  total_m3: number;
  assigned_m3: number;
  unassigned_m3: number;
  coverage_pct: number | null;
  tonnes: number | null;
}

export interface DriveSummary {
  faces: number;
  advance_m: number | null;
  profiles: number;
  design_area_m2: number | null;
  mean_actual_m2: number | null;
  overbreak_pct: number | null;
  excess_m3: number | null;
  excess_t: number | null;
  under_count: number;
}

export interface BlastHole {
  id: string;
  hole_id: string;
  design_e: number;
  design_n: number;
  design_depth_m: number | null;
  drilled_e: number | null;
  drilled_n: number | null;
  drilled_depth_m: number | null;
  collar_offset_m: number | null;
  depth_diff_m: number | null;
  collar_ok: boolean | null;
  depth_ok: boolean | null;
}

export interface BlastPattern {
  id: string;
  code: string;
  name: string;
  collar_tol_m: number | null;
  depth_tol_m: number | null;
  holes: number;
  drilled: number;
  failed: number;
}

export interface BlastPatternDetail extends BlastPattern {
  items: BlastHole[];
  findings: Finding[];
  problems: string[];
}

export interface MineTotals {
  plan_m3: number;
  actual_m3: number | null;
  compliance_pct: number | null;
  survey_t: number | null;
  truck_t: number | null;
  truck_factor_pct: number | null;
  units: number;
}

export interface MinePeriod {
  id: string;
  project_id: string;
  label: string;
  period_start: string;
  period_end: string;
  band_lo_pct: number | null;
  band_hi_pct: number | null;
  truck_tolerance_pct: number | null;
  profile_label: string;
  entry_count: number;
}

export interface MinePeriodDetail extends MinePeriod {
  entries: MineEntry[];
  totals: MineTotals;
}

export interface PeriodInput {
  label: string;
  band_lo_pct?: number | null;
  band_hi_pct?: number | null;
  truck_tolerance_pct?: number | null;
}

export interface EntryInput {
  unit_name: string;
  unit_type: UnitType;
  plan_m3: number;
  plan_t?: number | null;
  plan_advance_m?: number | null;
  density_t_m3?: number | null;
}

export interface ComputeActualInput {
  start_surface_id?: string;
  end_surface_id?: string;
  start_text?: string;
  start_filename?: string;
  end_text?: string;
  end_filename?: string;
  cell_size_m?: number | null;
}

export interface ClaimResult {
  entry_id: string;
  progress_entry_id: string;
  position_id: string;
  quantity_m3: number;
  period_label: string;
  percent_complete: number;
}

const loc = (locale: string) => `locale=${encodeURIComponent(locale)}`;

export const listPeriods = (projectId: string) => apiGet<{ items: MinePeriod[] }>(`/v1/mine-survey/projects/${projectId}/periods`).then((r) => r.items);
export const createPeriod = (projectId: string, body: PeriodInput) => apiPost<MinePeriod>(`/v1/mine-survey/projects/${projectId}/periods`, body);
export const getPeriod = (id: string, locale: string) => apiGet<MinePeriodDetail>(`/v1/mine-survey/periods/${id}?${loc(locale)}`);
export const deletePeriod = (id: string) => apiDelete(`/v1/mine-survey/periods/${id}`);
export const addEntry = (periodId: string, body: EntryInput, locale: string) =>
  apiPost<MineEntry>(`/v1/mine-survey/periods/${periodId}/entries?${loc(locale)}`, body);
export const updateEntry = (id: string, body: { actual_advance_m?: number | null; plan_advance_m?: number | null }, locale: string) =>
  apiPatch<MineEntry>(`/v1/mine-survey/entries/${id}?${loc(locale)}`, body);
export const deleteEntry = (id: string) => apiDelete(`/v1/mine-survey/entries/${id}`);
export const computeActual = (id: string, body: ComputeActualInput, locale: string) =>
  apiPost<MineEntry>(`/v1/mine-survey/entries/${id}/compute-actual?${loc(locale)}`, body);
export const confirmActual = (id: string, acknowledge: string[], locale: string) =>
  apiPost<MineEntry>(`/v1/mine-survey/entries/${id}/confirm-actual?${loc(locale)}`, { acknowledge });
export const importTruckLoads = (id: string, text: string, filename: string, locale: string) =>
  apiPost<MineEntry>(`/v1/mine-survey/entries/${id}/truck-loads?${loc(locale)}`, { text, filename });
export const addToClaim = (id: string, positionId: string) =>
  apiPost<ClaimResult>(`/v1/mine-survey/entries/${id}/add-to-claim`, { position_id: positionId });
export const periodReportUrl = (id: string, locale: string) => `/api/v1/mine-survey/periods/${id}/report.pdf?${loc(locale)}`;

/** Percent with two decimals, "94.96 %". */
export function formatPct(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return `${new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value)} %`;
}

/** Signed percent, "+4.47 %"; the sign is always written. */
export function formatSigned(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  const n = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format(value);
  return `${n} %`;
}

/** Tonnes with two decimals, "23,740.00". */
export function formatTonnes(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

/** Whether a compliance value lies outside the period's band; null when there is nothing to judge by. */
export function outsideBand(pct: number | null, lo: number | null, hi: number | null): boolean | null {
  if (pct == null || lo == null || hi == null) return null;
  return pct < lo || pct > hi;
}

/** "1,05" and "1.05" both read as 1.05; anything else is null. */
export function parseNumber(text: string): number | null {
  const n = Number(text.trim().replace(',', '.'));
  return text.trim() !== '' && Number.isFinite(n) ? n : null;
}

/** The current month as "YYYY-MM". */
export function currentMonth(now: Date = new Date()): string {
  return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
}

/** "2026-10" shown as the course names it, "Oct 2026". */
export function periodTitle(label: string, locale: string): string {
  const m = /^(\d{4})-(\d{2})$/.exec(label);
  if (!m) return label;
  return new Intl.DateTimeFormat(locale, { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(Date.UTC(+m[1]!, +m[2]! - 1, 1)));
}

export const splitByMaterial = (entryId: string, locale: string) =>
  apiPost<MineEntry>(`/v1/mine-survey/entries/${entryId}/material-split?${loc(locale)}`, {});
export const importMaterials = (unitId: string, text: string, filename: string) =>
  apiPost<{ items: unknown[]; problems: string[] }>(`/v1/mine-survey/units/${unitId}/materials/import`, { text, filename, replace: true });
export const listPatterns = (projectId: string) =>
  apiGet<{ items: BlastPattern[] }>(`/v1/mine-survey/projects/${projectId}/blast-patterns`).then((r) => r.items);
export const createPattern = (
  projectId: string,
  body: { name: string; collar_tol_m: number | null; depth_tol_m: number | null; design_text: string },
  locale: string,
) => apiPost<BlastPatternDetail>(`/v1/mine-survey/projects/${projectId}/blast-patterns?${loc(locale)}`, body);
export const getPattern = (id: string, locale: string) => apiGet<BlastPatternDetail>(`/v1/mine-survey/blast-patterns/${id}?${loc(locale)}`);
export const importAsDrilled = (id: string, text: string, locale: string) =>
  apiPost<BlastPatternDetail>(`/v1/mine-survey/blast-patterns/${id}/as-drilled?${loc(locale)}`, { text });
export const deletePattern = (id: string) => apiDelete(`/v1/mine-survey/blast-patterns/${id}`);
export const stakeListUrl = (id: string) => `/api/v1/mine-survey/blast-patterns/${id}/stake-list.csv`;
