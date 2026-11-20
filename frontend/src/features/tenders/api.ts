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
  return apiGet<TenderSummary[]>(`/v1/bid-management/tenders/?${params.toString()}`);
}

/** Where a tender is edited: copies stay owned by the module they came from until it is retired. */
export function tenderEditPath(row: Pick<TenderSummary, 'source' | 'project_id'>): string {
  if (row.source === 'tendering') return '/tendering';
  if (row.source === 'rfq_bidding') return `/projects/${row.project_id}/rfq-bidding`;
  return `/projects/${row.project_id}/bid-management`;
}
