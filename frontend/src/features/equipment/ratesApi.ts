// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the equipment rate catalogue.
 *
 * Backed by /api/v1/equipment/rate-catalogues/ - see
 * backend/app/modules/equipment/rate_router.py. Decimals are strings.
 */

import { API_BASE, ApiError, apiGet, apiPost, fetchWithAuth } from '@/shared/lib/api';

export interface RateCatalogue {
  id: string;
  family_id: string;
  name: string;
  source_label: string;
  licence_note: string;
  currency: string;
  valid_from: string;
  interest_convention: string;
  is_synthetic: boolean;
  superseded: boolean;
  machines: number;
}

export interface RateItem {
  id: string;
  catalogue_id: string;
  code: string;
  name: string;
  category: string;
  size_key: string;
  value: string;
  residual: string;
  life_years: string;
  months_per_year: string;
  interest: string;
  repair: string;
  hours_per_month: string | null;
  override_monthly_rate: string | null;
  is_synthetic: boolean;
}

export interface RateCatalogueDetail extends RateCatalogue {
  items: RateItem[];
}

export interface RateBreakdown {
  depreciation: string | null;
  interest: string | null;
  repair: string | null;
  monthly: string | null;
  hourly: string | null;
  daily: string | null;
  manual: boolean;
}

export interface RateIssue {
  rule_id: string;
  severity: string;
  message: string;
  field: string | null;
  row: number | null;
}

export interface RatePreview {
  valid: boolean;
  rates: RateBreakdown;
  issues: RateIssue[];
}

export interface RateLayout {
  key: string;
  label_key: string;
  mapping: Record<string, string>;
  decimal_comma: boolean;
  interest_convention: string;
}

export interface RateImportPreview {
  headers: string[];
  sample: string[][];
  total_rows: number;
  suggested_mapping: Record<string, string>;
  layouts: RateLayout[];
  fields: string[];
  required_fields: string[];
}

export interface RateImportResult {
  ready: number;
  error_rows: number;
  total_rows: number;
  issues: RateIssue[];
  catalogue_id: string | null;
}

const BASE = '/v1/equipment/rate-catalogues';

export const listRateCatalogues = () => apiGet<RateCatalogue[]>(`${BASE}/`);
export const getRateCatalogue = (id: string) => apiGet<RateCatalogueDetail>(`${BASE}/${id}/`);
export const loadDemoCatalogue = (currency: string) => apiPost<RateCatalogue>(`${BASE}/demo/?currency=${currency}`);
export const createEmptyCatalogue = (name: string, currency: string) =>
  apiPost<RateCatalogue>(`${BASE}/`, { name, currency });
export const previewRate = (body: Record<string, string | null>) => apiPost<RatePreview>(`${BASE}/preview/`, body);

async function upload<T>(path: string, form: FormData): Promise<T> {
  const res = await fetchWithAuth(`${API_BASE}${path}`, { method: 'POST', body: form });
  const payload: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new ApiError(res.status, res.statusText, payload);
  return payload as T;
}

export function previewRateImport(file: File): Promise<RateImportPreview> {
  const form = new FormData();
  form.append('file', file);
  return upload<RateImportPreview>(`${BASE}/import/preview/`, form);
}

export function importRateTable(
  file: File,
  opts: {
    mapping: Record<string, string>;
    decimalComma: boolean;
    dryRun: boolean;
    name: string;
    validFrom: string;
    licenceNote: string;
    currency: string;
    interestConvention: string;
  },
): Promise<RateImportResult> {
  const form = new FormData();
  form.append('file', file);
  form.append('mapping', JSON.stringify(opts.mapping));
  form.append('decimal_comma', String(opts.decimalComma));
  form.append('dry_run', String(opts.dryRun));
  form.append('name', opts.name);
  form.append('valid_from', opts.validFrom);
  form.append('licence_note', opts.licenceNote);
  form.append('currency', opts.currency);
  form.append('interest_convention', opts.interestConvention);
  return upload<RateImportResult>(`${BASE}/import/`, form);
}

/** Fractions are stored (0.06); the UI shows percent. */
export function fractionToPercent(value: string | null | undefined): string {
  if (value === null || value === undefined || value === '') return '';
  const n = Number(value);
  return Number.isFinite(n) ? String(Math.round(n * 10000) / 100) : '';
}

export function percentToFraction(value: string): string | null {
  const n = Number(value.replace(',', '.'));
  return value.trim() !== '' && Number.isFinite(n) ? String(n / 100) : null;
}
