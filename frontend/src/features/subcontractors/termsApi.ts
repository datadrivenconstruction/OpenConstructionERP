// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Levies, payment discount and the bidder radius search.
 *
 * Backed by backend/app/modules/subcontractors/terms_router.py. Money and
 * percentages travel as Decimal strings and are never parsed into floats here.
 */

import { apiDelete, apiGet, apiPost, apiPut } from '@/shared/lib/api';

export type LevyBasis = 'percent' | 'fixed';
export type LevyAppliesAt = 'each_invoice' | 'final_account';
export type DeductionOrder = 'levies_then_retention' | 'retention_then_levies';

export interface LevyCatalogueItem {
  id: string;
  code: string;
  name: string;
  basis: LevyBasis;
  default_percent: string | null;
  default_fixed_amount: string | null;
  applies_at: LevyAppliesAt;
  is_active: boolean;
  sort_order: number;
  notes: string | null;
  source: string;
}

export interface PackLevyDefault {
  code: string;
  name: string;
  basis: LevyBasis;
  applies_at: LevyAppliesAt;
  country: string;
  pack: string;
  source_note: string;
  in_catalogue: boolean;
}

export interface LevyCatalogue {
  items: LevyCatalogueItem[];
  pack_defaults: PackLevyDefault[];
}

export interface SubcontractLevy {
  id?: string;
  catalogue_id?: string | null;
  code: string;
  name: string;
  basis: LevyBasis;
  rate_percent: string | null;
  fixed_amount: string | null;
  applies_at: LevyAppliesAt;
}

export interface SubcontractTerms {
  id?: string | null;
  agreement_id?: string | null;
  contract_id?: string | null;
  deduction_order: DeductionOrder;
  retention_cap_percent: string | null;
  payment_discount_percent: string | null;
  payment_discount_days: number | null;
  payment_discount_agreed: boolean;
  source?: string;
  levies: SubcontractLevy[];
  is_default?: boolean;
}

export interface StatementLine {
  kind: 'work_value' | 'levy' | 'after_levies' | 'retention' | 'payable' | 'payment_discount';
  code?: string;
  name?: string;
  amount: string;
  running?: string;
}

export interface ValidationRow {
  rule_id: string;
  severity: 'error' | 'warning' | 'info';
  passed: boolean;
  message: string;
  element_ref?: string | null;
  suggestion?: string | null;
}

export interface DeductionStatement {
  agreement_id: string;
  payment_application_id: string | null;
  application_number: string | null;
  currency: string;
  contract_sum: string;
  work_value: string;
  deduction_order: DeductionOrder;
  levies_total: string;
  retention_percent: string;
  retention_amount: string;
  retention_capped: boolean;
  retention_cap_amount: string | null;
  payable: string;
  payment_discount_percent: string | null;
  payment_discount_days: number | null;
  payment_discount_agreed: boolean;
  payment_discount_amount: string;
  payable_with_discount: string;
  discount_due_date: string | null;
  discount_applies: boolean | null;
  amount_to_pay: string;
  lines: StatementLine[];
  validation: ValidationRow[];
}

export interface BidderRow {
  id: string;
  legal_name: string;
  trade_categories: string[];
  prequalification_status: string;
  city: string | null;
  has_coordinates: boolean;
  distance_km: string | null;
  within_radius: boolean | null;
  is_favourite: boolean;
}

export interface BidderSearch {
  items: BidderRow[];
  total: number;
  radius_km: string | null;
  site_has_coordinates: boolean;
  without_coordinates: number;
  hidden_blocked: number;
  validation: ValidationRow[];
}

const BASE = '/v1/subcontractors';

export const getLevyCatalogue = () => apiGet<LevyCatalogue>(`${BASE}/levy-catalogue`);

export const createLevy = (body: Omit<LevyCatalogueItem, 'id' | 'source'>) =>
  apiPost<LevyCatalogueItem>(`${BASE}/levy-catalogue`, body);

export const updateLevy = (id: string, body: Omit<LevyCatalogueItem, 'id' | 'source'>) =>
  apiPut<LevyCatalogueItem>(`${BASE}/levy-catalogue/${id}`, body);

export const deleteLevy = (id: string) => apiDelete(`${BASE}/levy-catalogue/${id}`);

export const importPackLevies = () => apiPost<{ added: number }>(`${BASE}/levy-catalogue/import-pack`, {});

export const getAgreementTerms = (agreementId: string) =>
  apiGet<SubcontractTerms>(`${BASE}/agreements/${agreementId}/terms`);

export const putAgreementTerms = (agreementId: string, body: SubcontractTerms) =>
  apiPut<SubcontractTerms>(`${BASE}/agreements/${agreementId}/terms`, body);

export function getDeductions(
  agreementId: string,
  params: { payment_application_id?: string; work_value?: string; final_account?: boolean },
): Promise<DeductionStatement> {
  const q = new URLSearchParams();
  if (params.payment_application_id) q.set('payment_application_id', params.payment_application_id);
  if (params.work_value) q.set('work_value', params.work_value);
  if (params.final_account) q.set('final_account', 'true');
  return apiGet<DeductionStatement>(`${BASE}/agreements/${agreementId}/deductions?${q.toString()}`);
}

export const recordDeductions = (agreementId: string, paymentApplicationId: string) =>
  apiPost<DeductionStatement>(
    `${BASE}/agreements/${agreementId}/payment-applications/${paymentApplicationId}/deductions`,
    {},
  );

export function searchBidders(params: {
  project_id: string;
  trade?: string;
  radius_km?: number | null;
  favourites_only?: boolean;
  include_outside?: boolean;
}): Promise<BidderSearch> {
  const q = new URLSearchParams({ project_id: params.project_id });
  if (params.trade) q.set('trade', params.trade);
  if (params.radius_km) q.set('radius_km', String(params.radius_km));
  if (params.favourites_only) q.set('favourites_only', 'true');
  if (params.include_outside) q.set('include_outside', 'true');
  return apiGet<BidderSearch>(`${BASE}/bidder-search?${q.toString()}`);
}

export const addFavourite = (subcontractorId: string, trade: string) =>
  apiPost<void>(`${BASE}/favourites`, { subcontractor_id: subcontractorId, trade });

export const removeFavourite = (subcontractorId: string, trade: string) =>
  apiDelete(
    `${BASE}/favourites?subcontractor_id=${encodeURIComponent(subcontractorId)}&trade=${encodeURIComponent(trade)}`,
  );

export const geocodeFirm = (subcontractorId: string) =>
  apiPost<{ has_coordinates: boolean; reason: string | null }>(`${BASE}/subcontractors/${subcontractorId}/geocode`, {});
