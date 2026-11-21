// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Tenders page: one list over native bid packages and
 * the copies of tendering packages and supplier RFQs.
 *
 * Backed by /api/v1/bid-management/tenders/ (backend/app/modules/bid_management/tenders.py).
 */

import { apiGet } from '@/shared/lib/api';

export type TenderKind = 'subcontract' | 'supply';
export type TenderSource = 'native' | 'tendering' | 'rfq_bidding';

export interface TenderSummary {
  id: string;
  project_id: string;
  code: string;
  title: string;
  status: string;
  kind: TenderKind | string;
  source: TenderSource | string;
  source_id: string | null;
  currency: string;
  submission_deadline: string | null;
  bid_count: number;
  lowest_total: string | null;
  awarded_amount: string | null;
  awarded_bidder: string | null;
}

export interface TenderFilters {
  kind?: TenderKind | '';
  source?: TenderSource | '';
}

export function tendersQueryKey(projectId: string, filters: TenderFilters) {
  return ['tenders', projectId, filters.kind || '', filters.source || ''] as const;
}

export function fetchTenders(projectId: string, filters: TenderFilters = {}): Promise<TenderSummary[]> {
  const params = new URLSearchParams({ project_id: projectId });
  if (filters.kind) params.set('kind', filters.kind);
  if (filters.source) params.set('source', filters.source);
  return apiGet<{ items: TenderSummary[] }>(`/v1/bid-management/tenders/?${params.toString()}`).then((page) => page.items);
}

export interface TenderLine {
  id: string;
  code: string;
  description: string;
  unit: string;
  quantity: string;
  order_index: number;
}

export interface TenderBidder {
  id: string;
  company_name: string;
  contact_email: string;
  status: string;
}

export interface TenderInvitation {
  id: string;
  bidder_ref_id: string | null;
  invitee_company_name: string;
  sent_at: string | null;
  submission_received_at: string | null;
  declined_at: string | null;
}

export interface TenderSubmission {
  id: string;
  bidder_id: string;
  submitted_at: string | null;
  total_amount: string;
  currency: string;
  validity_days: number | null;
  late_reason: string | null;
}

export interface TenderQuestion {
  id: string;
  question: string;
  answer: string;
  asked_at: string | null;
  answered_at: string | null;
}

export interface TenderComparison {
  id: string;
  computed_at: string | null;
  normalized_low: string;
  normalized_high: string;
  commercial_weight_pct: number;
  technical_weight_pct: number;
  recommended_bidder_id: string | null;
  recommended_reason: string;
}

export interface TenderAward {
  id: string;
  awarded_bidder_id: string;
  awarded_amount: string;
  currency: string;
  decision_summary: string;
  decision_signed_at: string | null;
  method: string | null;
}

export interface TenderDetail {
  package: {
    id: string;
    project_id: string;
    code: string;
    title: string;
    status: string;
    package_type: string;
    currency: string;
    scope_description?: string;
    submission_deadline: string | null;
  };
  source: TenderSource | string;
  source_id: string | null;
  read_only: boolean;
  line_items: TenderLine[];
  invitations: TenderInvitation[];
  bidders: TenderBidder[];
  submissions: TenderSubmission[];
  award: TenderAward | null;
  questions: TenderQuestion[];
  comparison: TenderComparison | null;
}

export interface TenderResolve {
  package_id: string;
  source: string;
}

export function fetchTender(id: string): Promise<TenderDetail> {
  return apiGet<TenderDetail>(`/v1/bid-management/tenders/${id}`);
}

export type LegacyTable = 'oe_tendering_package' | 'oe_rfq_rfq';

export function resolveLegacyTender(table: LegacyTable, sourceId: string): Promise<TenderResolve> {
  const params = new URLSearchParams({ source_table: table, source_id: sourceId });
  return apiGet<TenderResolve>(`/v1/bid-management/tenders/resolve/?${params.toString()}`);
}

/** The card of one tender. */
export function tenderCardPath(id: string): string {
  return `/tenders/${id}`;
}

/**
 * Where a tender is edited. Copies of old tenders keep their editor until the
 * old module is retired; it now lives under /tenders, so /tendering and
 * /rfq-bidding can redirect without losing the editor.
 */
export function tenderEditPath(row: Pick<TenderSummary, 'source' | 'project_id' | 'source_id' | 'id'>): string {
  if (row.source === 'tendering') {
    return `/tenders/edit/tendering${row.source_id ? `?package=${row.source_id}` : ''}`;
  }
  if (row.source === 'rfq_bidding') {
    return `/projects/${row.project_id}/tenders/edit/rfq${row.source_id ? `?rfq=${row.source_id}` : ''}`;
  }
  return `/projects/${row.project_id}/bid-management?highlight=${row.id}`;
}
