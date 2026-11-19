// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Award terms, negotiation rounds and the bidder gate of a tender package.
 *
 * Backed by backend/app/modules/tendering/award_router.py. Money and percent
 * values are decimal strings both ways; the server does every sum, so the
 * figure the panel shows is the figure the contract is drafted with.
 */

import { ApiError, apiDelete, apiGet, apiPost, apiPut, type Page } from '@/shared/lib/api';

export type PricingMode = 'unit_price' | 'lump_sum';

export interface AwardTerms {
  bid_id: string;
  round_id: string | null;
  discount_percent: string;
  lump_sum: string | null;
  retention_percent: string | null;
  retention_cap_percent: string | null;
  payment_discount_percent: string | null;
  payment_discount_days: number | null;
  note: string;
}

export interface GateFinding {
  rule_id: string;
  severity: 'error' | 'warning';
  code: string;
  document_type: string | null;
  state: string | null;
  lapsed_on: string | null;
}

export interface BidderGate {
  subcontractor_id: string | null;
  subcontractor_name: string | null;
  blocked: boolean;
  required_types: string[];
  requirements_source: string;
  requirements_reference: string | null;
  findings: GateFinding[];
}

export interface AwardRule {
  rule_id: string;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface AwardLine {
  index: number;
  description: string;
  unit: string;
  quantity: string;
  offer_rate: string;
  offer_total: string;
  contract_rate: string;
  contract_total: string;
}

export interface AwardPreview {
  package_id: string;
  bid_id: string;
  company_name: string;
  currency: string;
  pricing_mode: PricingMode;
  contract_type: string;
  lines_total: string;
  offer_total: string;
  discount_percent: string;
  discount_amount: string;
  contract_sum: string;
  lump_sum_source: string | null;
  retention_percent: string | null;
  retention_cap_percent: string | null;
  retention_cap_amount: string | null;
  payment_discount_percent: string | null;
  payment_discount_days: number | null;
  round_id: string | null;
  round_no: number | null;
  rounds_count: number;
  revisions_count: number;
  lines: AwardLine[];
  gate: BidderGate;
  blockers: AwardRule[];
  warnings: AwardRule[];
  can_award: boolean;
}

export interface AwardTermsState {
  package_id: string;
  package_status: string;
  terms: AwardTerms | null;
  preview: AwardPreview | null;
  contract_id: string | null;
  contract_code: string | null;
}

export interface NegotiationRound {
  id: string;
  package_id: string;
  bid_id: string;
  round_no: number;
  pricing_mode: PricingMode;
  lines_total: string;
  lump_sum: string | null;
  discount_percent: string;
  offer_total: string;
  contract_sum: string;
  note: string;
  is_final: boolean;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string | null;
}

export interface RoundInput {
  pricing_mode: PricingMode;
  lump_sum: string | null;
  discount_percent: string;
  note: string;
}

export function getAwardTerms(packageId: string): Promise<AwardTermsState> {
  return apiGet<AwardTermsState>(`/v1/tendering/packages/${packageId}/award-terms/`);
}

export function saveAwardTerms(packageId: string, terms: AwardTerms): Promise<AwardTermsState> {
  return apiPut<AwardTermsState, AwardTerms>(`/v1/tendering/packages/${packageId}/award-terms/`, terms);
}

export function previewAwardTerms(packageId: string, terms: AwardTerms): Promise<AwardPreview> {
  return apiPost<AwardPreview, AwardTerms>(`/v1/tendering/packages/${packageId}/award-terms/preview/`, terms);
}

export function listRounds(packageId: string): Promise<NegotiationRound[]> {
  return apiGet<Page<NegotiationRound>>(`/v1/tendering/packages/${packageId}/rounds/`).then((page) => page.items);
}

export function addRound(packageId: string, bidId: string, round: RoundInput): Promise<NegotiationRound> {
  return apiPost<NegotiationRound, RoundInput>(`/v1/tendering/packages/${packageId}/bids/${bidId}/rounds/`, round);
}

export function markRoundFinal(packageId: string, roundId: string, final = true): Promise<NegotiationRound> {
  return apiPost<NegotiationRound>(`/v1/tendering/packages/${packageId}/rounds/${roundId}/final/?final=${final}`, {});
}

export function approveRound(packageId: string, roundId: string): Promise<NegotiationRound> {
  return apiPost<NegotiationRound>(`/v1/tendering/packages/${packageId}/rounds/${roundId}/approve/`, {});
}

export function deleteRound(packageId: string, roundId: string): Promise<void> {
  return apiDelete(`/v1/tendering/packages/${packageId}/rounds/${roundId}/`);
}

/** Empty terms for a bid: no discount, no lump sum, nothing agreed yet. */
export function emptyTerms(bidId: string): AwardTerms {
  return {
    bid_id: bidId,
    round_id: null,
    discount_percent: '0',
    lump_sum: null,
    retention_percent: null,
    retention_cap_percent: null,
    payment_discount_percent: null,
    payment_discount_days: null,
    note: '',
  };
}

/** Terms prefilled from a round the firm offered: its lump sum and discount. */
export function termsFromRound(terms: AwardTerms, round: NegotiationRound): AwardTerms {
  return {
    ...terms,
    bid_id: round.bid_id,
    round_id: round.id,
    discount_percent: round.discount_percent,
    lump_sum: round.pricing_mode === 'lump_sum' ? round.lump_sum : null,
  };
}

/** The i18n key of an award rule id: `award.bidder_blocked` -> `tendering.award_rule.bidder_blocked`. */
export function ruleKey(ruleId: string): string {
  return `tendering.award_rule.${ruleId.replace(/^award\./, '')}`;
}

/** The gate a 409 refusal carries (invite or award), if it carries one. */
export function gateOfError(error: unknown): { code: string; gate: BidderGate | null } | null {
  if (!(error instanceof ApiError)) return null;
  const detail = (error.body as { detail?: unknown } | null)?.detail;
  if (!detail || typeof detail !== 'object' || !('code' in detail)) return null;
  const d = detail as { code: string; gate?: BidderGate };
  if (!d.code.startsWith('award.')) return null;
  return { code: d.code, gate: d.gate ?? null };
}
