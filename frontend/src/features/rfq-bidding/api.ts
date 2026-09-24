// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import { apiGet, apiPost, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

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

export interface RFQ {
  id: string;
  project_id: string;
  title: string;
  description: string;
  status: RFQStatus;
  due_date: string | null;
  issued_at: string | null;
  awarded_at: string | null;
  currency_code: string;
  total_estimated: string | number;
  vendors_count: number;
  bids_count: number;
  created_at: string;
  updated_at: string;
}

export interface RFQCreatePayload {
  project_id: string;
  title: string;
  description?: string;
  due_date?: string;
  currency_code?: string;
}

export interface RFQUpdatePayload {
  title?: string;
  description?: string;
  due_date?: string;
  status?: RFQStatus;
}

/* ── Scope lines ──────────────────────────────────────────────────────── */

export interface ScopeLine {
  id: string;
  rfq_id: string;
  description: string;
  quantity: number;
  unit: string;
  estimated_rate: string | number;
}

export interface ScopeLineCreatePayload {
  description: string;
  quantity: number;
  unit: string;
  estimated_rate?: number;
}

/* ── Bids ─────────────────────────────────────────────────────────────── */

export interface Bid {
  id: string;
  rfq_id: string;
  vendor_name: string;
  vendor_contact_id: string | null;
  total_amount: string | number;
  currency_code: string;
  status: string;
  submitted_at: string | null;
  notes: string;
  line_prices: Record<string, number>;
  created_at: string;
  updated_at: string;
}

export interface BidCreatePayload {
  rfq_id: string;
  vendor_name: string;
  vendor_contact_id?: string;
  total_amount: number;
  currency_code?: string;
  notes?: string;
  line_prices?: Record<string, number>;
}

/* ── Comparison & award ───────────────────────────────────────────────── */

export interface ComparisonMatrix {
  rfq_id: string;
  scope_lines: ScopeLine[];
  bids: Bid[];
  matrix: Record<string, Record<string, number>>;
}

export interface AwardDecision {
  rfq_id: string;
  awarded_bid_id: string | null;
  vendor_name: string | null;
  total_amount: string | number | null;
  currency_code: string;
  awarded_at: string | null;
  reason: string;
}

export interface ValidationReport {
  rfq_id: string;
  valid: boolean;
  issues: { field: string; message: string; severity: string }[];
}

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
  return apiPost<RFQ>(`/v1/rfq-bidding/${id}/issue`);
}

export async function validateRFQ(id: string): Promise<ValidationReport> {
  return apiGet<ValidationReport>(`/v1/rfq-bidding/${id}/validate`);
}

export async function fetchScopeLines(rfqId: string): Promise<ScopeLine[]> {
  return apiGet<ScopeLine[]>(`/v1/rfq-bidding/${rfqId}/lines`);
}

export async function addScopeLine(
  rfqId: string,
  payload: ScopeLineCreatePayload,
): Promise<ScopeLine> {
  return apiPost<ScopeLine, ScopeLineCreatePayload>(`/v1/rfq-bidding/${rfqId}/lines`, payload);
}

export async function fetchComparison(rfqId: string): Promise<ComparisonMatrix> {
  return apiGet<ComparisonMatrix>(`/v1/rfq-bidding/${rfqId}/comparison`);
}

export async function fetchAward(rfqId: string): Promise<AwardDecision> {
  return apiGet<AwardDecision>(`/v1/rfq-bidding/${rfqId}/award`);
}

export async function fetchBids(rfqId?: string): Promise<Page<Bid>> {
  const params = new URLSearchParams();
  if (rfqId) params.set('rfq_id', rfqId);
  const qs = params.toString();
  return apiGet<Page<Bid>>(`/v1/rfq-bidding/bids${qs ? `?${qs}` : ''}`);
}

export async function submitBid(payload: BidCreatePayload): Promise<Bid> {
  return apiPost<Bid, BidCreatePayload>('/v1/rfq-bidding/bids', payload);
}

export async function evaluateBid(bidId: string): Promise<Bid> {
  return apiPost<Bid>(`/v1/rfq-bidding/bids/${bidId}/evaluate`);
}

export async function awardBid(bidId: string): Promise<Bid> {
  return apiPost<Bid>(`/v1/rfq-bidding/bids/${bidId}/award`);
}
