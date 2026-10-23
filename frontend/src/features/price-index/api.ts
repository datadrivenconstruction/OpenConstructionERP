// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Price Index (base-to-current cost adjustment).
 *
 * All endpoints are mounted at /api/v1/price-index/. Factors and money are
 * decimal strings in and out (the platform-wide "money / factor as string"
 * convention) so a precise value never loses digits through a JS Number. The
 * app runs with redirect_slashes disabled, so every path keeps its trailing
 * slash.
 */

import { apiGet, apiPost, apiPatch, apiDelete, fetchWithAuth, triggerDownload } from '@/shared/lib/api';

const BASE = '/v1/price-index';

/* -- Types ---------------------------------------------------------------- */

export interface CostIndexSeries {
  id: string;
  name: string;
  description: string;
  point_count: number;
  created_at: string;
  updated_at: string;
}

export interface CostIndexPoint {
  id: string;
  series_id: string;
  /** ISO year-month, e.g. "2026-01". */
  period: string;
  factor: string;
  created_at: string;
  updated_at: string;
}

export interface CostIndexSeriesDetail extends CostIndexSeries {
  points: CostIndexPoint[];
}

export interface LocationFactor {
  id: string;
  region_code: string;
  label: string;
  factor: string;
  created_at: string;
  updated_at: string;
}

export interface AdjustLineInput {
  amount: string;
  base_period: string;
  target_period: string;
  base_region?: string | null;
  target_region?: string | null;
}

export interface AdjustLineResult {
  amount: string;
  base_period: string;
  target_period: string;
  base_region: string | null;
  target_region: string | null;
  temporal_factor: string | null;
  location_factor: string | null;
  applied_factor: string | null;
  adjusted_amount: string | null;
  note: string | null;
  error: string | null;
}

export interface AdjustResponse {
  series_id: string;
  series_name: string;
  results: AdjustLineResult[];
}

export interface CreateSeriesPayload {
  name: string;
  description?: string;
}

export interface CreatePointPayload {
  period: string;
  factor: string;
}

export interface CreateLocationFactorPayload {
  region_code: string;
  label?: string;
  factor: string;
}

/* -- Pure helpers (unit-tested) ------------------------------------------- */

const PERIOD_RE = /^\d{4}-(0[1-9]|1[0-2])$/;

/** True when `period` is an ISO year-month string with a real month (01-12). */
export function isValidPeriod(period: string | null | undefined): boolean {
  if (!period) return false;
  return PERIOD_RE.test(period.trim());
}

/**
 * Render a factor decimal string for display, trimming trailing zeros
 * ("1.400000" -> "1.4", "1.000000" -> "1", "0.900000" -> "0.9"). Pure string
 * work - no Number parse - so an exact stored value is never rounded.
 */
export function formatFactor(raw: string | null | undefined): string {
  if (raw == null || raw === '') return '';
  const text = String(raw).trim();
  if (!text.includes('.')) return text;
  const trimmed = text.replace(/0+$/, '').replace(/\.$/, '');
  return trimmed === '' || trimmed === '-' ? '0' : trimmed;
}

export type FactorDirection = 'up' | 'down' | 'flat';

/**
 * Classify a multiplier for a display tone: above one is "up" (costs rose),
 * below one is "down", exactly one (or unparseable) is "flat". Display-only -
 * never used for money math.
 */
export function factorDirection(raw: string | null | undefined): FactorDirection {
  if (raw == null || raw === '') return 'flat';
  const n = Number(raw);
  if (!Number.isFinite(n)) return 'flat';
  if (n > 1) return 'up';
  if (n < 1) return 'down';
  return 'flat';
}

/** A blank adjust line for seeding the editor. */
export function blankAdjustLine(): AdjustLineInput {
  return {
    amount: '',
    base_period: '',
    target_period: '',
    base_region: '',
    target_region: '',
  };
}

/**
 * True when a line is complete enough to send: a non-negative amount and two
 * valid periods. Regions are optional (a blank region means the national
 * baseline of 1).
 */
export function isAdjustLineReady(line: AdjustLineInput): boolean {
  const amount = Number(line.amount);
  if (!Number.isFinite(amount) || amount < 0 || line.amount.trim() === '') return false;
  return isValidPeriod(line.base_period) && isValidPeriod(line.target_period);
}

/* -- Series --------------------------------------------------------------- */

export async function listSeries(): Promise<CostIndexSeries[]> {
  const res = await apiGet<CostIndexSeries[]>(`${BASE}/series/`);
  return Array.isArray(res) ? res : [];
}

export async function fetchSeries(id: string): Promise<CostIndexSeriesDetail> {
  return apiGet<CostIndexSeriesDetail>(`${BASE}/series/${id}/`);
}

export async function createSeries(data: CreateSeriesPayload): Promise<CostIndexSeries> {
  return apiPost<CostIndexSeries>(`${BASE}/series/`, data);
}

export async function updateSeries(
  id: string,
  data: Partial<CreateSeriesPayload>,
): Promise<CostIndexSeries> {
  return apiPatch<CostIndexSeries>(`${BASE}/series/${id}/`, data);
}

export async function deleteSeries(id: string): Promise<void> {
  return apiDelete(`${BASE}/series/${id}/`);
}

/* -- Points --------------------------------------------------------------- */

export async function addPoint(seriesId: string, data: CreatePointPayload): Promise<CostIndexPoint> {
  return apiPost<CostIndexPoint>(`${BASE}/series/${seriesId}/points/`, data);
}

export async function deletePoint(seriesId: string, pointId: string): Promise<void> {
  return apiDelete(`${BASE}/series/${seriesId}/points/${pointId}/`);
}

/* -- Location factors ----------------------------------------------------- */

export async function listLocationFactors(): Promise<LocationFactor[]> {
  const res = await apiGet<LocationFactor[]>(`${BASE}/location-factors/`);
  return Array.isArray(res) ? res : [];
}

export async function createLocationFactor(
  data: CreateLocationFactorPayload,
): Promise<LocationFactor> {
  return apiPost<LocationFactor>(`${BASE}/location-factors/`, data);
}

export async function deleteLocationFactor(id: string): Promise<void> {
  return apiDelete(`${BASE}/location-factors/${id}/`);
}

/* -- Adjust --------------------------------------------------------------- */

export async function adjustAmounts(
  seriesId: string,
  lines: AdjustLineInput[],
): Promise<AdjustResponse> {
  const payload = {
    series_id: seriesId,
    lines: lines.map((l) => ({
      amount: l.amount,
      base_period: l.base_period,
      target_period: l.target_period,
      base_region: l.base_region || null,
      target_region: l.target_region || null,
    })),
  };
  return apiPost<AdjustResponse>(`${BASE}/adjust/`, payload);
}

/* -- Escalate stored rates (preview) -------------------------------------- */

/**
 * Selectors + target date for a read-only escalation preview. Every supplied
 * constraint is applied together (AND); the backend requires at least one of
 * `region` / `category` / `cost_item_ids` so the whole catalogue is never
 * escalated by accident. `series_id` may be omitted when exactly one series
 * exists (the backend defaults to it). Only fields the user actually sets are
 * sent (see {@link escalatePreview}).
 */
export interface EscalatePreviewInput {
  /** ISO calendar date (YYYY-MM-DD) to bring the stored rates to. */
  target_date: string;
  /** Index series to escalate against; optional when only one series exists. */
  series_id?: string | null;
  /**
   * Escalate the rates THIS project's BOQ actually references (the DISTINCT
   * cost items its positions link to) instead of the catalogue at large. A
   * region/category filter narrows the project set further.
   */
  project_id?: string | null;
  /** Filter items by region (matches `CostItem.region`). */
  region?: string | null;
  /** Filter items by category (the top classification level / collection). */
  category?: string | null;
  /** Explicit cost items to escalate, in addition to any region/category filter. */
  cost_item_ids?: string[] | null;
}

/**
 * One cost item's stored rate previewed at the target date. Money and the
 * factor are decimal strings (never floats). When the rate cannot be escalated
 * (`escalatable` is false) `base_date` / `base_period` / `factor` /
 * `escalated_rate` may be null and `note` explains why, so one unusable item
 * never voids the batch. `base_rate` is still present unless the stored rate is
 * itself not a number.
 */
export interface EscalatePreviewLine {
  cost_item_id: string;
  code: string;
  /**
   * Optional human-readable description. The current escalate-preview payload
   * does not carry one, so the CSV export omits the column unless a description
   * is present (forward-compatible if the backend starts sending it).
   */
  description?: string | null;
  unit: string;
  region: string | null;
  currency: string;
  base_rate: string | null;
  /** ISO date the rate was captured (`price_as_of`), or null when unknown. */
  base_date: string | null;
  /** ISO year-month derived from `base_date`, or null. */
  base_period: string | null;
  factor: string | null;
  escalated_rate: string | null;
  escalatable: boolean;
  note: string | null;
}

export interface EscalatePreviewResponse {
  series_id: string;
  series_name: string;
  /** ISO calendar date the rates were brought to. */
  target_date: string;
  /** ISO year-month derived from `target_date`. */
  target_period: string;
  item_count: number;
  escalatable_count: number;
  /** Which selection ran: `'catalogue'` (region/category/ids) or `'project'`. */
  scope: string;
  /** The project the rates were scoped to, or null in catalogue scope. */
  project_id: string | null;
  /** The project's name, for labelling the results in project scope. */
  project_name: string | null;
  /**
   * True when project scope found no typed cost-item link on any position and
   * fell back to the project's own region as the regional proxy.
   */
  project_fallback: boolean;
  results: EscalatePreviewLine[];
}

const ISO_DATE_RE = /^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$/;

/** True when `value` is a well-formed ISO calendar date (YYYY-MM-DD). */
export function isValidIsoDate(value: string | null | undefined): boolean {
  if (!value) return false;
  return ISO_DATE_RE.test(value.trim());
}

/**
 * True when the request carries at least one item selector (an explicit
 * region, category, or cost-item id). The backend rejects a request with no
 * selector so the whole catalogue is never escalated by accident.
 */
export function hasEscalateSelector(input: {
  region?: string | null;
  category?: string | null;
  cost_item_ids?: string[] | null;
}): boolean {
  const region = (input.region ?? '').trim();
  const category = (input.category ?? '').trim();
  const ids = input.cost_item_ids ?? [];
  return region !== '' || category !== '' || ids.length > 0;
}

/**
 * Preview the estimate's own stored rates escalated to a target date. Strictly
 * read-only: nothing is written back to the cost items or the BOQ. Only fields
 * the caller actually set are sent, so an empty region/category/series is
 * omitted rather than posted as an empty string.
 */
export async function escalatePreview(
  input: EscalatePreviewInput,
): Promise<EscalatePreviewResponse> {
  const payload: Record<string, unknown> = { target_date: input.target_date };
  if (input.series_id) payload.series_id = input.series_id;
  if (input.project_id) payload.project_id = input.project_id;
  if (input.region && input.region.trim() !== '') payload.region = input.region.trim();
  if (input.category && input.category.trim() !== '') payload.category = input.category.trim();
  if (input.cost_item_ids && input.cost_item_ids.length > 0) {
    payload.cost_item_ids = input.cost_item_ids;
  }
  return apiPost<EscalatePreviewResponse>(`${BASE}/escalate-preview/`, payload);
}

/* -- Escalate export (client-side CSV) ------------------------------------ */

/**
 * Build a spreadsheet-friendly CSV from the fetched escalate-preview rows.
 *
 * Pure and client-side: no server round-trip. Base rate, escalation factor and
 * escalated rate are the exact Decimal strings the backend served, written
 * verbatim so a cent is never lost to a float. A `Description` column is emitted
 * only when at least one row carries one ("if present"), and a trailing
 * `Currency` column carries the money's currency so the rates read
 * unambiguously. Any comma / quote / newline / semicolon in a field is escaped
 * so it stays a single field, and rows use CRLF for maximal spreadsheet
 * compatibility.
 */
export function buildEscalatePreviewCsv(result: EscalatePreviewResponse): string {
  const cell = (val: string | number | null | undefined): string => {
    const s = val === null || val === undefined ? '' : String(val);
    return /[",\n;]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const rows = result.results;
  const withDescription = rows.some((r) => (r.description ?? '').trim() !== '');

  const header = ['Code'];
  if (withDescription) header.push('Description');
  header.push('Unit', 'Base rate', 'Base date', 'Escalation factor', 'Escalated rate', 'Currency');

  const lines: string[] = [header.map(cell).join(',')];
  for (const r of rows) {
    const record: (string | number | null | undefined)[] = [r.code];
    if (withDescription) record.push(r.description ?? '');
    record.push(
      r.unit,
      r.base_rate ?? '',
      r.base_date ?? '',
      r.factor ?? '',
      r.escalated_rate ?? '',
      r.currency,
    );
    lines.push(record.map(cell).join(','));
  }
  return lines.join('\r\n');
}

/** Deterministic download filename for an escalate-preview CSV. */
export function escalatePreviewCsvName(result: EscalatePreviewResponse): string {
  const safe = (value: string | null | undefined, max: number): string =>
    String(value ?? '').replace(/[^a-zA-Z0-9_-]/g, '').slice(0, max);
  const period = safe(result.target_period, 7);
  const scopeTag =
    result.scope === 'project' && result.project_id ? safe(result.project_id, 12) || 'project' : 'catalogue';
  return `escalated-rates-${scopeTag}${period ? `-${period}` : ''}.csv`;
}

/**
 * Download the escalate-preview results as CSV, built entirely on the client
 * from the already-fetched rows (the money strings are printed verbatim). A
 * UTF-8 BOM is prepended so spreadsheets open non-ASCII codes / units correctly.
 */
export function downloadEscalatePreviewCsv(result: EscalatePreviewResponse): void {
  const csv = buildEscalatePreviewCsv(result);
  const blob = new Blob([String.fromCharCode(0xfeff), csv], { type: 'text/csv;charset=utf-8;' });
  triggerDownload(blob, escalatePreviewCsvName(result));
}

/* -- Cost-catalogue facets (populate the escalate selectors) -------------- */

/**
 * Distinct loaded regions on the cost catalogue. Reused to populate the
 * escalate panel's region selector so it offers the same region codes the
 * escalate-preview endpoint filters on (`CostItem.region`).
 */
export async function listCostRegions(): Promise<string[]> {
  const res = await apiGet<string[]>('/v1/costs/regions/');
  return Array.isArray(res) ? res : [];
}

/**
 * Distinct categories (the top classification level / `classification.collection`),
 * optionally scoped to a region. Populates the escalate panel's category
 * selector; the same values feed the escalate-preview `category` filter.
 */
export async function listCostCategories(region?: string | null): Promise<string[]> {
  const params = new URLSearchParams();
  if (region && region.trim() !== '') params.set('region', region.trim());
  const qs = params.toString();
  const res = await apiGet<string[]>(`/v1/costs/categories/${qs ? `?${qs}` : ''}`);
  return Array.isArray(res) ? res : [];
}

/** Result of importing Stats SA P0151.1 Table 1 (one series per CPAP work group). */
export interface P0151ImportResult {
  series_created: number;
  points_created: number;
  points_updated: number;
  points_unchanged: number;
  series: string[];
  skipped: string[];
}

/** Upload a Stats SA P0151.1 release (.xlsx or .csv); nothing is fetched from the web. */
export async function importStatsSaP0151(file: File): Promise<P0151ImportResult> {
  const form = new FormData();
  form.append('file', file);
  const res = await fetchWithAuth(`/api${BASE}/import/statssa-p0151/`, {
    method: 'POST',
    headers: { Accept: 'application/json' },
    body: form,
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const detail = (body as { detail?: { message?: string } | string }).detail;
    throw new Error(typeof detail === 'string' ? detail : (detail?.message ?? res.statusText));
  }
  return body as P0151ImportResult;
}
