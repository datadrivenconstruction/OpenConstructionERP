// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';
import { normalizeListResponse } from '@/shared/lib/apiHelpers';

/* ── RFQ types ────────────────────────────────────────────────────────── */

/**
 * The statuses the server's RFQ status machine uses (`rfq` in
 * `backend/app/core/fsm/registry.py`). `issued`, `evaluating` and `closed`
 * are older values the page used to count by; the server never writes
 * `evaluating` or `closed`, and reads `issued` only as another open status,
 * so they stay in the type for rows that may still carry them.
 */
export type RFQStatus =
  | 'draft'
  | 'published'
  | 'bids_received'
  | 'awarded'
  | 'po_issued'
  | 'completed'
  | 'cancelled'
  | 'issued'
  | 'evaluating'
  | 'closed';

/** Statuses in which vendors may still bid. Mirrors `_BID_SUBMISSION_OPEN_STATUSES`. */
export const RFQ_OPEN_STATUSES: ReadonlySet<RFQStatus> = new Set<RFQStatus>(['published', 'issued', 'bids_received']);

/** Statuses of an RFQ that has been awarded, including the steps after the award. */
export const RFQ_AWARDED_STATUSES: ReadonlySet<RFQStatus> = new Set<RFQStatus>(['awarded', 'po_issued', 'completed']);

/** The status machine's statuses, in lifecycle order, for the status filter. */
export const RFQ_FILTER_STATUSES: readonly RFQStatus[] = [
  'draft',
  'published',
  'bids_received',
  'awarded',
  'po_issued',
  'completed',
  'cancelled',
];

/*
 * Every shape below mirrors a response or request model in
 * backend/app/modules/rfq_bidding/schemas.py. Decimal fields arrive as
 * strings. The request models ignore unknown keys, so a misspelt field is not
 * refused, it is silently dropped: keep the names exactly as the server has them.
 */

/** RFQResponse. The list embeds each RFQ's lines and bids. */
export interface RFQ {
  id: string;
  project_id: string;
  rfq_number: string;
  title: string;
  description: string | null;
  scope_of_work: string | null;
  submission_deadline: string | null;
  currency_code: string;
  status: RFQStatus;
  /** Contact ids the RFQ was sent to. */
  issued_to_contacts: string[];
  evaluation_method: string;
  technical_weight: string;
  require_full_scope: boolean;
  lines: ScopeLine[];
  bids: Bid[];
  created_at: string;
  updated_at: string;
}

/** RFQCreate. */
export interface RFQCreatePayload {
  project_id: string;
  title: string;
  description?: string;
  submission_deadline?: string;
  currency_code?: string;
}

/** RFQUpdate. */
export interface RFQUpdatePayload {
  title?: string;
  description?: string;
  submission_deadline?: string;
  status?: RFQStatus;
}

/* ── Scope lines ──────────────────────────────────────────────────────── */

/** RFQLineResponse. */
export interface ScopeLine {
  id: string;
  rfq_id: string;
  line_no: number;
  code: string | null;
  description: string;
  unit: string;
  quantity: string;
  is_optional: boolean;
  cost_line_id: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

/** RFQLineCreate. */
export interface ScopeLineCreatePayload {
  description: string;
  unit: string;
  quantity?: string | number;
  code?: string;
  is_optional?: boolean;
  notes?: string;
}

/* ── Bids ─────────────────────────────────────────────────────────────── */

/** RFQBidResponse. The bidder is a contact id; the page resolves its name. */
export interface Bid {
  id: string;
  rfq_id: string;
  bidder_contact_id: string;
  bid_amount: string;
  currency_code: string;
  submitted_at: string | null;
  validity_days: number;
  technical_score: string | null;
  commercial_score: string | null;
  notes: string | null;
  is_awarded: boolean;
  status: string;
  is_late: boolean;
  created_at: string;
  updated_at: string;
}

/** BidCreate: bidder_contact_id and bid_amount are required, the rest defaults. */
export interface BidCreatePayload {
  rfq_id: string;
  bidder_contact_id: string;
  bid_amount: string;
  currency_code?: string;
  submitted_at?: string;
  validity_days?: number;
  technical_score?: string;
  commercial_score?: string;
  notes?: string;
}

/* ── Comparison & award ───────────────────────────────────────────────── */

/** QuoteComparisonResponse: one quote restated on the RFQ's basis. */
export interface QuoteComparison {
  bid_id: string;
  bidder_contact_id: string;
  status: string;
  is_late: boolean;
  admitted: boolean;
  currency_code: string;
  headline_amount: string | null;
  exchange_rate: string | null;
  converted_amount: string | null;
  adjustments_applied: string;
  adjustments_included: number;
  /** The amount the ranking compares, in the basis currency. */
  normalised_amount: string | null;
  lines_required: number;
  lines_covered: number;
  coverage: string;
  uncovered_lines: string[];
  excluded_lines: string[];
  extra_lines: number;
  line_total: string | null;
  technical_score: string | null;
  price_score: string | null;
  total_score: string | null;
  comparable: boolean;
  /** Why a quote was excluded from the ranking. */
  reasons: string[];
  notes: string[];
  rank: number | null;
}

/** ComparisonResponse: ranked quotes, and the ones that could not be ranked. */
export interface ComparisonResponse {
  rfq_id: string;
  rfq_number: string;
  basis_currency: string;
  method: string;
  technical_weight: string;
  require_full_scope: boolean;
  as_of: string | null;
  lines_required: number;
  recommended_bid_id: string | null;
  ranked: QuoteComparison[];
  excluded: QuoteComparison[];
}

/** RFQAwardResponse. */
export interface AwardDecision {
  id: string;
  rfq_id: string;
  bid_id: string;
  awarded_by: string | null;
  awarded_at: string;
  method: string;
  reason: string | null;
  recommended_bid_id: string | null;
  is_override: boolean;
  awarded_amount: string;
  awarded_currency: string;
  created_at: string;
  updated_at: string;
}

/** The validate route answers a plain dict of findings; its keys vary by stage. */
export type ValidationReport = Record<string, unknown>;

/* ── API functions ────────────────────────────────────────────────────── */

export async function fetchRFQs(
  projectId?: string,
  status?: RFQStatus,
): Promise<Page<RFQ>> {
  const params = new URLSearchParams();
  if (projectId) params.set('project_id', projectId);
  if (status) params.set('status', status);
  const qs = params.toString();
  return apiGet<Page<RFQ>>(`/v1/rfq-bidding/${qs ? `?${qs}` : ''}`);
}

export async function fetchRFQ(id: string): Promise<RFQ> {
  return apiGet<RFQ>(`/v1/rfq-bidding/${id}`);
}

export async function createRFQ(payload: RFQCreatePayload): Promise<RFQ> {
  return apiPost<RFQ, RFQCreatePayload>('/v1/rfq-bidding/', payload);
}

export async function updateRFQ(id: string, payload: RFQUpdatePayload): Promise<RFQ> {
  return apiPatch<RFQ, RFQUpdatePayload>(`/v1/rfq-bidding/${id}`, payload);
}

export async function deleteRFQ(id: string): Promise<void> {
  return apiDelete(`/v1/rfq-bidding/${id}`);
}

export async function issueRFQ(id: string): Promise<RFQ> {
  return apiPost<RFQ>(`/v1/rfq-bidding/${id}/issue/`);
}

export async function validateRFQ(id: string): Promise<ValidationReport> {
  return apiGet<ValidationReport>(`/v1/rfq-bidding/${id}/validate/`);
}

export async function fetchScopeLines(rfqId: string): Promise<ScopeLine[]> {
  // The server answers with {items, total}.
  const page = await apiGet<ScopeLine[] | { items: ScopeLine[] }>(`/v1/rfq-bidding/${rfqId}/lines/`);
  return normalizeListResponse(page);
}

export async function addScopeLine(
  rfqId: string,
  payload: ScopeLineCreatePayload,
): Promise<ScopeLine> {
  return apiPost<ScopeLine, ScopeLineCreatePayload>(`/v1/rfq-bidding/${rfqId}/lines/`, payload);
}

export async function fetchComparison(rfqId: string): Promise<ComparisonResponse> {
  return apiGet<ComparisonResponse>(`/v1/rfq-bidding/${rfqId}/comparison/`);
}

export async function fetchAward(rfqId: string): Promise<AwardDecision> {
  return apiGet<AwardDecision>(`/v1/rfq-bidding/${rfqId}/award/`);
}

export async function fetchBids(rfqId?: string): Promise<Page<Bid>> {
  const params = new URLSearchParams();
  if (rfqId) params.set('rfq_id', rfqId);
  const qs = params.toString();
  return apiGet<Page<Bid>>(`/v1/rfq-bidding/bids/${qs ? `?${qs}` : ''}`);
}

export async function submitBid(payload: BidCreatePayload): Promise<Bid> {
  return apiPost<Bid, BidCreatePayload>('/v1/rfq-bidding/bids/', payload);
}

export async function evaluateBid(bidId: string): Promise<Bid> {
  return apiPost<Bid>(`/v1/rfq-bidding/bids/${bidId}/evaluate/`);
}

export async function awardBid(bidId: string): Promise<Bid> {
  return apiPost<Bid>(`/v1/rfq-bidding/bids/${bidId}/award/`);
}
