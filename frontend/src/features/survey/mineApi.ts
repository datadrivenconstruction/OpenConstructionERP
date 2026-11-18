// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the mine survey: periods, one line per unit, the actual that
 * comes from a Volumes calculation, truck loads and the claim. Volumes show
 * one decimal, tonnes two, percentages two.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { Finding } from './volumesApi';

const BASE = '/v1/mine-survey';

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
const p = (projectId: string) => `${BASE}/projects/${projectId}`;

export const listPeriods = (projectId: string) => apiGet<MinePeriod[]>(`${p(projectId)}/periods`);
export const createPeriod = (projectId: string, body: PeriodInput) => apiPost<MinePeriod>(`${p(projectId)}/periods`, body);
export const getPeriod = (id: string, locale: string) => apiGet<MinePeriodDetail>(`${BASE}/periods/${id}?${loc(locale)}`);
export const deletePeriod = (id: string) => apiDelete(`${BASE}/periods/${id}`);
export const addEntry = (periodId: string, body: EntryInput, locale: string) =>
  apiPost<MineEntry>(`${BASE}/periods/${periodId}/entries?${loc(locale)}`, body);
export const updateEntry = (id: string, body: { actual_advance_m?: number | null; plan_advance_m?: number | null }, locale: string) =>
  apiPatch<MineEntry>(`${BASE}/entries/${id}?${loc(locale)}`, body);
export const deleteEntry = (id: string) => apiDelete(`${BASE}/entries/${id}`);
export const computeActual = (id: string, body: ComputeActualInput, locale: string) =>
  apiPost<MineEntry>(`${BASE}/entries/${id}/compute-actual?${loc(locale)}`, body);
export const confirmActual = (id: string, acknowledge: string[], locale: string) =>
  apiPost<MineEntry>(`${BASE}/entries/${id}/confirm-actual?${loc(locale)}`, { acknowledge });
export const importTruckLoads = (id: string, text: string, filename: string, locale: string) =>
  apiPost<MineEntry>(`${BASE}/entries/${id}/truck-loads?${loc(locale)}`, { text, filename });
export const addToClaim = (id: string, positionId: string) =>
  apiPost<ClaimResult>(`${BASE}/entries/${id}/add-to-claim`, { position_id: positionId });
export const periodReportUrl = (id: string, locale: string) => `/api${BASE}/periods/${id}/report.pdf?${loc(locale)}`;

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
