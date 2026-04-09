/**
 * API helpers for Non-Conformance Reports (NCR).
 *
 * All endpoints are prefixed with /v1/ncr/.
 */

import { apiGet, apiPost } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

export type NCRType = 'material' | 'workmanship' | 'design' | 'documentation' | 'safety';

export type NCRSeverity = 'critical' | 'major' | 'minor' | 'observation';

export type NCRStatus = 'identified' | 'under_review' | 'corrective_action' | 'verification' | 'closed' | 'void';

export interface NCR {
  id: string;
  project_id: string;
  ncr_number: number;
  title: string;
  ncr_type: NCRType;
  severity: NCRSeverity;
  status: NCRStatus;
  description: string;
  root_cause: string;
  corrective_action: string;
  preventive_action: string;
  cost_impact: number | null;
  location: string;
  linked_inspection_id: string | null;
  linked_inspection_number: number | null;
  change_order_id: string | null;
  reported_by: string | null;
  created_at: string;
  updated_at: string;
  closed_at: string | null;
}

export interface NCRFilters {
  project_id?: string;
  status?: NCRStatus | '';
  severity?: NCRSeverity | '';
}

export interface CreateNCRPayload {
  project_id: string;
  title: string;
  ncr_type: NCRType;
  severity: NCRSeverity;
  description: string;
  location_description?: string;
  root_cause?: string;
}

/* -- API Functions --------------------------------------------------------- */

export async function fetchNCRs(filters?: NCRFilters): Promise<NCR[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.severity) params.set('severity', filters.severity);
  const qs = params.toString();
  return apiGet<NCR[]>(`/v1/ncr/${qs ? `?${qs}` : ''}`);
}

export async function createNCR(data: CreateNCRPayload): Promise<NCR> {
  return apiPost<NCR>('/v1/ncr/', data);
}

export async function closeNCR(id: string): Promise<NCR> {
  return apiPost<NCR>(`/v1/ncr/${id}/close`);
}
