// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ helpers for Cost benchmarks.
 *
 * All endpoints are prefixed with /v1/cost_benchmarks/. Money and quantities
 * are returned as Decimal-as-string; the UI parses with Number(...) only for
 * display.
 */

import { apiDelete, apiGet, apiPost, fetchWithAuth, triggerDownload } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type BenchmarkKind = 'completed' | 'estimate';
export type BenchmarkStandard = 'din276' | 'nrm1' | 'masterformat' | 'uniformat';
export type BenchmarkMeasure = 'gfa' | 'unit';
export type BenchmarkPosition = 'below' | 'within' | 'above' | 'unknown';

export interface BenchmarkElement {
  code: string;
  label: string;
  amount: string;
}

export interface BenchmarkRecord {
  id: string;
  kind: BenchmarkKind;
  project_id: string | null;
  name: string;
  project_type: string;
  country: string;
  region: string;
  currency: string;
  cost_date: string | null;
  standard: BenchmarkStandard;
  gfa_m2: string | null;
  functional_unit: string;
  functional_units: string | null;
  total_cost: string;
  is_synthetic: boolean;
  source: string;
  elements: BenchmarkElement[];
}

export interface CreateRecordPayload {
  kind: BenchmarkKind;
  name: string;
  project_type: string;
  country: string;
  region?: string;
  currency: string;
  cost_date: string;
  standard: BenchmarkStandard;
  gfa_m2?: string | null;
  functional_unit?: string;
  functional_units?: string | null;
  total_cost?: string | null;
  elements: BenchmarkElement[];
}

export interface CompareRequest {
  estimate_id?: string;
  project_id?: string;
  project_type?: string;
  countries?: string[];
  region?: string;
  gfa_min?: string;
  gfa_max?: string;
  year_from?: number;
  year_to?: number;
  base_date?: string;
  base_region?: string;
  reporting_currency: string;
  fx_date?: string;
  measure: BenchmarkMeasure;
  min_projects: number;
  stale_months: number;
}

export interface Band {
  count: number;
  p10: string | null;
  p50: string | null;
  p90: string | null;
}

export interface CompareElement {
  code: string;
  label: string;
  estimate_per_unit: string | null;
  estimate_amount: string;
  band: Band;
  band_source: 'own' | 'reference';
  position: BenchmarkPosition;
}

export interface CompareFinding {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
}

export interface CohortProject {
  id: string;
  name: string;
  country: string;
  year: number | null;
  gfa_m2: string | null;
  total_per_unit: string | null;
  factor: string | null;
}

export interface CompareResult {
  estimate: {
    id: string;
    name: string;
    project_type: string;
    country: string;
    gfa_m2: string | null;
    functional_unit: string;
    functional_units: string | null;
    total: string;
    total_per_unit: string | null;
    total_position: BenchmarkPosition;
  };
  measure: BenchmarkMeasure;
  basis: {
    base_date: string | null;
    base_region: string | null;
    reporting_currency: string;
    index_series: string | null;
    index_latest_period: string | null;
    fx_rate_date: string | null;
    location_factors: boolean;
    stale: boolean;
  };
  cohort: {
    count: number;
    min_projects: number;
    low_confidence: boolean;
    source: 'own' | 'reference';
    reference_source: string | null;
    missing_quantity: string[];
    projects: CohortProject[];
  };
  total_band: Band;
  elements: CompareElement[];
  findings: CompareFinding[];
}

/* ── API functions ─────────────────────────────────────────────────────── */

export interface RecordFilters {
  kind: BenchmarkKind;
  project_type?: string;
  country?: string;
}

export async function fetchRecords(filters: RecordFilters): Promise<BenchmarkRecord[]> {
  const q = new URLSearchParams({ kind: filters.kind });
  if (filters.project_type) q.set('project_type', filters.project_type);
  if (filters.country) q.set('country', filters.country);
  const res = await apiGet<BenchmarkRecord[]>(`/v1/cost_benchmarks/records/?${q.toString()}`);
  return Array.isArray(res) ? res : [];
}

export async function createRecord(payload: CreateRecordPayload): Promise<BenchmarkRecord> {
  return apiPost<BenchmarkRecord, CreateRecordPayload>('/v1/cost_benchmarks/records/', payload);
}

export async function deleteRecord(recordId: string): Promise<void> {
  await apiDelete(`/v1/cost_benchmarks/records/${encodeURIComponent(recordId)}`);
}

/** Turn a completed project's BOQ into a benchmark record. */
export async function captureProject(projectId: string): Promise<BenchmarkRecord> {
  return apiPost<BenchmarkRecord>(
    `/v1/cost_benchmarks/projects/${encodeURIComponent(projectId)}/capture/`,
  );
}

export async function compareEstimate(payload: CompareRequest): Promise<CompareResult> {
  return apiPost<CompareResult, CompareRequest>('/v1/cost_benchmarks/compare/', payload);
}

/** Download the anonymised cohort data; the endpoint is auth-gated, so fetch the blob. */
export async function downloadAnonymised(
  format: 'json' | 'csv',
  reportingCurrency: string,
): Promise<void> {
  const q = new URLSearchParams({ format, reporting_currency: reportingCurrency });
  const res = await fetchWithAuth(`/api/v1/cost_benchmarks/export/anonymised?${q.toString()}`);
  if (!res.ok) {
    throw new Error(`Export failed (${res.status})`);
  }
  triggerDownload(await res.blob(), `cost-benchmarks-anonymised.${format}`);
}
