// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for stockpiles: the pile, its surveys, and the inventory
 * adjustment that a person confirms. Tonnes show two decimals, volumes one.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import type { Finding } from './volumesApi';

const BASE = '/v1/stockpiles';

export type DensitySource = 'measured' | 'supplier' | 'assumed';
export const DENSITY_SOURCES: DensitySource[] = ['measured', 'supplier', 'assumed'];
export type PileSource = 'file' | 'surface' | 'typed';
export const PILE_SOURCES: PileSource[] = ['file', 'surface', 'typed'];

export interface Adjustment {
  id: string;
  survey_id: string;
  stockpile_id: string;
  delta_t: number;
  status: 'proposed' | 'confirmed' | 'cancelled';
  movement_id: string | null;
  confirmed_by_name: string;
  confirmed_at: string | null;
}

export interface PileSurvey {
  id: string;
  stockpile_id: string;
  surveyed_on: string;
  source_kind: 'surface' | 'typed';
  pile_name: string;
  volume_m3: number;
  cell_size_m: number | null;
  coverage_pct: number | null;
  density_t_m3: number;
  density_source: DensitySource;
  tonnes: number;
  book_tonnes: number | null;
  variance_t: number | null;
  variance_pct: number | null;
  status: 'open' | 'booked';
  findings: Finding[];
  adjustment: Adjustment | null;
}

export interface Stockpile {
  id: string;
  project_id: string;
  code: string;
  name: string;
  material: string;
  location_note: string;
  base_surface_id: string | null;
  base_name: string;
  book_tonnes: number | null;
  variance_tolerance_pct: number | null;
  survey_count: number;
  last_survey: PileSurvey | null;
}

export interface StockpileDetail extends Stockpile {
  surveys: PileSurvey[];
}

export interface StockpileSummary {
  stockpiles: number;
  surveyed_tonnes: number;
  book_tonnes: number;
  variance_pct: number | null;
  surveyed_stockpiles: number;
}

export interface StockpileInput {
  name: string;
  material?: string;
  base_text?: string;
  base_filename?: string;
  base_surface_id?: string;
  book_tonnes?: number | null;
  variance_tolerance_pct?: number | null;
}

export interface SurveyInput {
  surveyed_on?: string;
  pile_text?: string;
  pile_filename?: string;
  pile_surface_id?: string;
  volume_m3?: number;
  cell_size_m?: number;
  density_t_m3: number;
  density_source: DensitySource;
}


export const getStockpileSummary = (projectId: string) => apiGet<StockpileSummary>(`${BASE}/projects/${projectId}/summary`);
export const listStockpiles = (projectId: string, locale: string) =>
  apiGet<{ items: Stockpile[] }>(`${BASE}/projects/${projectId}/stockpiles?locale=${encodeURIComponent(locale)}`).then((r) => r.items);
export const getStockpile = (id: string, locale: string) =>
  apiGet<StockpileDetail>(`${BASE}/stockpiles/${id}?locale=${encodeURIComponent(locale)}`);
export const createStockpile = (projectId: string, body: StockpileInput) =>
  apiPost<StockpileDetail>(`${BASE}/projects/${projectId}/stockpiles`, body);
export const updateStockpile = (id: string, body: Partial<StockpileInput>) =>
  apiPatch<StockpileDetail>(`${BASE}/stockpiles/${id}`, body);
export const deleteStockpile = (id: string) => apiDelete(`${BASE}/stockpiles/${id}`);
export const addSurvey = (id: string, body: SurveyInput, locale: string) =>
  apiPost<PileSurvey>(`${BASE}/stockpiles/${id}/surveys?locale=${encodeURIComponent(locale)}`, body);
export const updateSurvey = (id: string, body: Partial<SurveyInput>, locale: string) =>
  apiPatch<PileSurvey>(`${BASE}/surveys/${id}?locale=${encodeURIComponent(locale)}`, body);
export const deleteSurvey = (id: string) => apiDelete(`${BASE}/surveys/${id}`);
export const proposeAdjustment = (surveyId: string) =>
  apiPost<Adjustment>(`${BASE}/surveys/${surveyId}/propose-adjustment`, {});
export const confirmAdjustment = (adjustmentId: string, locale: string) =>
  apiPost<PileSurvey>(`${BASE}/adjustments/${adjustmentId}/confirm?locale=${encodeURIComponent(locale)}`, {});
export const cancelAdjustment = (adjustmentId: string, locale: string) =>
  apiPost<PileSurvey>(`${BASE}/adjustments/${adjustmentId}/cancel?locale=${encodeURIComponent(locale)}`, {});
export const stockpileReportUrl = (surveyId: string, locale: string) =>
  `/api${BASE}/surveys/${surveyId}/report.pdf?locale=${encodeURIComponent(locale)}`;

/** Tonnes with two decimals, "8,087.04". */
export function formatTonnes(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  return new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(value);
}

/** Signed percent with two decimals, "-3.73 %" (the sign is always written). */
export function formatVariance(value: number | null | undefined, locale: string): string {
  if (value == null || !Number.isFinite(value)) return '-';
  const n = new Intl.NumberFormat(locale, { minimumFractionDigits: 2, maximumFractionDigits: 2, signDisplay: 'exceptZero' }).format(value);
  return `${n} %`;
}

/** Badge tone of a variance: within the tolerance is fine, beyond it is a warning. */
export function varianceTone(pct: number | null | undefined, tolerancePct: number | null | undefined): 'neutral' | 'success' | 'warning' {
  if (pct == null) return 'neutral';
  return Math.abs(pct) > (tolerancePct ?? 3) ? 'warning' : 'success';
}

/** "1,62" and "1.62" both read as 1.62; anything else is null. */
export function parseNumber(text: string): number | null {
  const n = Number(text.trim().replace(',', '.'));
  return text.trim() !== '' && Number.isFinite(n) ? n : null;
}
