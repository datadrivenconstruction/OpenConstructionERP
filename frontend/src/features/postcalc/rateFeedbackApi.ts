// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for rate feedback: proposals to update cost item rates from the
 * actuals of closed projects. Numbers cross the wire as decimal strings.
 */
import { apiGet, apiPost } from '@/shared/lib/api';

export interface RateProposal {
  id: string;
  cost_item_id: string;
  cost_item_code: string | null;
  cost_item_description: string | null;
  unit: string;
  current_rate: string;
  suggested_rate: string;
  variance_pct: string | null;
  current_hours_per_unit: string | null;
  observed_hours_per_unit: string | null;
  hours_variance_pct: string | null;
  project_count: number;
  line_count: number;
  total_quantity: string;
  spread_pct: string | null;
  confidence: string;
  status: string;
  /** Rule ids of the validation findings, e.g. `rate_feedback.low_confidence`. */
  warnings: string[];
}

export interface RefreshResult {
  closed_projects: number;
  observed_cost_items: number;
  created: number;
  unchanged: number;
}

export async function fetchRateProposals(): Promise<RateProposal[]> {
  const page = await apiGet<{ items: RateProposal[] }>('/v1/rate_feedback/proposals?status=pending&limit=500');
  return page.items;
}

export function refreshRateProposals(): Promise<RefreshResult> {
  return apiPost<RefreshResult, Record<string, never>>('/v1/rate_feedback/refresh', {});
}

export function confirmRateProposal(id: string, rate?: string): Promise<RateProposal> {
  return apiPost<RateProposal, { rate?: string }>(`/v1/rate_feedback/proposals/${id}/confirm`, rate ? { rate } : {});
}

export function rejectRateProposal(id: string): Promise<RateProposal> {
  return apiPost<RateProposal, Record<string, never>>(`/v1/rate_feedback/proposals/${id}/reject`, {});
}
