// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Tax Withholding module.
 *
 * Backed by /api/v1/tax-withholding/ — see
 * backend/app/modules/tax_withholding/router.py
 *
 * Money and percentages arrive as plain-decimal **strings**, not numbers. The
 * backend serialises them that way on purpose: a deduction reported one cent
 * light is a return that does not reconcile with the tax authority, and that
 * is not a rounding this product is entitled to make. They stay strings here
 * too, and are parsed only where one is compared.
 *
 * Only the read side plus the preview is wired. Recording and editing
 * deductions and reverse-charge determinations are deliberately absent rather
 * than half-built — see the note at the top of TaxWithholdingPanel.tsx.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

/**
 * Kept equal to the Literal in the module's schemas.py.
 *
 * The response field is a bare `str` rather than this union, deliberately: a
 * reader must not crash on a status a later version writes. So this types what
 * may be *sent* as a filter, not what may arrive.
 */
export type PartyStatusLiteral = 'pending' | 'active' | 'expired' | 'revoked';

/**
 * One rate band of a scheme.
 *
 * `requires_verification` is the load-bearing field: a band carrying it is only
 * usable by a party holding an unexpired verification, and the preview reports
 * the drop when that does not hold.
 */
export interface RateBand {
  code: string;
  label: string;
  rate_pct: string;
  requires_verification: boolean;
}

export interface Regime {
  id: string;
  country_code: string;
  scheme_code: string;
  scheme_name: string;
  legal_reference: string;
  authority: string;
  currency_code: string;
  bands: RateBand[];
  default_band_code: string;
  materials_excluded: boolean;
  vat_excluded: boolean;
  verification_validity_months: number;
  threshold_amount: string | null;
  notes: string;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface RegimeSeedResult {
  created: number;
  existing: number;
  schemes: string[];
}

export interface PartyStatus {
  id: string;
  party_id: string;
  party_type: string;
  party_name: string;
  regime_id: string;
  band_code: string;
  verification_reference: string;
  verified_on: string | null;
  valid_from: string;
  valid_to: string | null;
  evidence_document_id: string | null;
  evidence_reference: string;
  status: string;
  notes: string;
  created_at: string;
  updated_at: string;
  /**
   * Computed by the router against the date of the request, never stored, so
   * these two are as fresh as the read and not as fresh as the last job that
   * wrote them. `days_to_expiry` goes **negative** once the window has closed
   * and is null for a standing with no end date at all.
   */
  is_expired: boolean;
  days_to_expiry: number | null;
}

export interface DeductionPreviewRequest {
  regime_id: string;
  gross_amount: string;
  qualifying_materials?: string;
  vat_amount?: string;
  currency_code: string;
  band_code?: string;
  party_status_id?: string | null;
  /** The date the standing is judged against. Omitted, the server uses today. */
  as_of?: string | null;
}

export interface DeductionPreview {
  regime_id: string;
  scheme_code: string;
  band_code: string;
  rate_pct: string;
  gross_amount: string;
  qualifying_materials: string;
  vat_amount: string;
  taxable_base: string;
  tax_withheld: string;
  net_payable: string;
  currency_code: string;
  /** The payment is at or under the scheme's exemption limit. A flag, not a rate. */
  below_threshold: boolean;
  /** Non-empty when the band asked for could not be used and a higher one applied. */
  band_downgraded_from: string;
  /** Plain English prose written by the server, not i18n keys. Rendered as it came. */
  reasons: string[];
}

/* ── Calls ─────────────────────────────────────────────────────────────── */

const BASE = '/v1/tax-withholding';

function qs(params: Record<string, string | number | boolean | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === '') continue;
    search.set(key, String(value));
  }
  const rendered = search.toString();
  return rendered ? `?${rendered}` : '';
}

export function listRegimes(params: { countryCode?: string; activeOnly?: boolean } = {}): Promise<Regime[]> {
  return apiGet<Regime[]>(
    `${BASE}/regimes/${qs({ country_code: params.countryCode, active_only: params.activeOnly })}`,
  );
}

/**
 * Install the schemes that ship with the module.
 *
 * Only fills gaps: a scheme already on file is left exactly as it is, because
 * an operator who edited a rate did so for a reason.
 */
export function seedRegimes(): Promise<RegimeSeedResult> {
  return apiPost<RegimeSeedResult>(`${BASE}/regimes/seed`);
}

export function listPartyStatuses(
  params: { partyId?: string; regimeId?: string; status?: PartyStatusLiteral } = {},
): Promise<PartyStatus[]> {
  return apiGet<PartyStatus[]>(
    `${BASE}/party-status/${qs({
      party_id: params.partyId,
      regime_id: params.regimeId,
      status: params.status,
    })}`,
  );
}

/**
 * Standings that run out inside the next `withinDays` days.
 *
 * The list that has to be read *before* a payment run; afterwards it is a
 * record of deductions taken at the wrong band.
 */
export function listExpiringPartyStatuses(withinDays = 60): Promise<PartyStatus[]> {
  return apiGet<PartyStatus[]>(`${BASE}/party-status/expiring${qs({ within_days: withinDays })}`);
}

/** What would be withheld from this payment, and why. Stores nothing. */
export function previewDeduction(body: DeductionPreviewRequest): Promise<DeductionPreview> {
  return apiPost<DeductionPreview, DeductionPreviewRequest>(`${BASE}/deductions/preview`, body);
}
