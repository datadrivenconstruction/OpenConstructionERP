// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Tax rate resolver API types and calls.
 *
 * The types mirror the Pydantic models in
 * `backend/app/modules/i18n_foundation/schemas.py` field for field. The one
 * that carries the design is `combined_rate_pct: string | null`. It is null on
 * every unresolved status, and that null is the answer rather than a hole to
 * be filled in with something more presentable on the way to the screen.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

const BASE = '/v1/i18n-foundation';

/** How a rate combines with the federal rate of the same country. */
export type TaxCombination =
  | 'national'
  | 'federal'
  | 'replaces_federal'
  | 'stacks_on_federal'
  | 'compounds_on_federal';

/**
 * How the resolver reached its answer, or why it declined to give one.
 *
 * Mirrors `ResolutionStatus` in `tax_rules.py`. Deliberately a closed union:
 * a status added on the server should be a compile error here rather than a
 * panel that silently renders nothing.
 */
export type TaxResolutionStatus =
  | 'harmonised'
  | 'stacked'
  | 'compounded'
  | 'federal_only'
  | 'national'
  | 'subdivision_unknown'
  | 'no_configuration'
  | 'default_rate_ambiguous'
  | 'default_rate_not_in_force'
  | 'awaiting_confirmation';

export interface TaxRateComponent {
  tax_code: string | null;
  tax_name: string;
  rate_pct: string;
  combination: TaxCombination;
  /**
   * What the rate was charged on. `consideration` is the pre-tax amount;
   * `consideration_plus_federal` is the federal-inclusive amount, which is
   * what makes a compounded total exceed the sum of its rates.
   */
  base: 'consideration' | 'consideration_plus_federal';
  /**
   * What this component adds to the total. Equal to `rate_pct` except for a
   * compounding rate, where it is the grossed-up figure. The components
   * always sum to `combined_rate_pct`, which is why the table shows this
   * column and not only the headline rate of each row.
   */
  effective_rate_pct: string;
}

export interface TaxResolution {
  country_code: string;
  subdivision_code: string | null;
  subdivision_name: string | null;
  status: TaxResolutionStatus;
  resolved: boolean;
  combined_rate_pct: string | null;
  federal_rate_pct: string | null;
  as_of: string;
  components: TaxRateComponent[];
  /**
   * The server's own English sentence, for diagnostics.
   *
   * Never rendered. It is prose composed on the server, so printing it puts
   * an untranslated sentence on an otherwise translated page; the localised
   * copy keyed off the classification carries the same meaning. Kept on the
   * type because it is genuinely useful in a bug report.
   */
  reason: string | null;
}

export interface Subdivision {
  code: string;
  name: string;
}

export interface SubdivisionListResponse {
  country_code: string;
  items: Subdivision[];
  total: number;
}

export interface CountryOption {
  iso_code: string;
  name_en: string;
}

export interface CountryListResponse {
  items: CountryOption[];
  total: number;
}

export interface TaxConfigRow {
  id: string;
  country_code: string;
  tax_name: string;
  tax_code: string | null;
  rate_pct: string;
  combination: TaxCombination;
  subdivision_code: string | null;
  effective_from: string | null;
  effective_to: string | null;
  is_default: boolean;
  /** `local_confirmation` is set on a rate that a local specialist must confirm before it is used. */
  metadata?: { local_confirmation?: LocalConfirmation } & Record<string, unknown>;
}

/** A rate's local confirmation, as `tax_rules.LOCAL_CONFIRMATION_KEY` stores it. */
export interface LocalConfirmation {
  required: boolean;
  status: 'pending' | 'confirmed';
  accountant_name?: string;
  source_reference?: string;
  confirmed_at?: string;
}

export interface TaxConfigListResponse {
  items: TaxConfigRow[];
  total: number;
}

export function listCountries(): Promise<CountryListResponse> {
  return apiGet<CountryListResponse>(`${BASE}/countries/`);
}

/**
 * Subdivisions the platform keeps a registry for.
 *
 * An empty list does not mean the country has no subdivisions, and it does not
 * mean a subdivision is unnecessary. It means there is no registry, which is
 * the United States today: one Californian rate is on file and no register of
 * states exists to offer. `offerableSubdivisions` in `resolution.ts` is what
 * the picker should actually use.
 */
export function listSubdivisions(countryCode: string): Promise<SubdivisionListResponse> {
  return apiGet<SubdivisionListResponse>(`${BASE}/subdivisions/${encodeURIComponent(countryCode)}`);
}

export function listTaxConfigsByCountry(countryCode: string): Promise<TaxConfigListResponse> {
  return apiGet<TaxConfigListResponse>(
    `${BASE}/tax-configs/by-country/${encodeURIComponent(countryCode)}`,
  );
}

/** Every rate on file for a country, unconfirmed ones included. */
export function listTaxConfigs(countryCode: string): Promise<TaxConfigListResponse> {
  return apiGet<TaxConfigListResponse>(
    `${BASE}/tax-configs/?country_code=${encodeURIComponent(countryCode)}`,
  );
}

/** Record that a local specialist confirmed a rate. Admin only; the server audits it. */
export function confirmTaxConfig(
  id: string,
  body: { accountant_name: string; source_reference: string },
): Promise<TaxConfigRow> {
  return apiPost<TaxConfigRow>(`${BASE}/tax-configs/${encodeURIComponent(id)}/confirm`, body);
}

export function resolveTaxRate(
  countryCode: string,
  subdivisionCode: string | null,
  onDate: string | null,
): Promise<TaxResolution> {
  const params = new URLSearchParams();
  if (subdivisionCode) params.set('subdivision_code', subdivisionCode);
  if (onDate) params.set('on_date', onDate);
  const query = params.toString();
  return apiGet<TaxResolution>(
    `${BASE}/tax-configs/resolve/${encodeURIComponent(countryCode)}${query ? `?${query}` : ''}`,
  );
}
