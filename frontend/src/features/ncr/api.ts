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

/* -- Wire <-> UI normaliser ----------------------------------------------- */

type NCRWire = Omit<
  NCR,
  | 'location'
  | 'reported_by'
  | 'cost_impact'
  | 'closed_at'
  | 'linked_inspection_number'
  | 'ncr_number'
> & {
  location?: string;
  location_description?: string | null;
  reported_by?: string | null;
  created_by?: string | null;
  cost_impact?: number | string | null;
  closed_at?: string | null;
  linked_inspection_number?: number | string | null;
  ncr_number: string | number;
};

function parseCostImpact(v: unknown): number | null {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const n = Number.parseFloat(String(v));
  return Number.isFinite(n) ? n : null;
}

function extractNumericSuffix(v: unknown): number | null {
  if (v == null) return null;
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  const match = String(v).match(/\d+/);
  return match ? Number.parseInt(match[0], 10) : null;
}

function normaliseNCR(raw: NCRWire): NCR {
  const ncr_number_num = extractNumericSuffix(raw.ncr_number) ?? 0;
  return {
    ...raw,
    ncr_number: ncr_number_num,
    location: raw.location ?? raw.location_description ?? '',
    reported_by: raw.reported_by ?? raw.created_by ?? null,
    cost_impact: parseCostImpact(raw.cost_impact),
    closed_at: raw.closed_at ?? null,
    linked_inspection_number: extractNumericSuffix(raw.linked_inspection_number),
  } as NCR;
}

/* -- API Functions --------------------------------------------------------- */

export async function fetchNCRs(filters?: NCRFilters): Promise<NCR[]> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.severity) params.set('severity', filters.severity);
  const qs = params.toString();
  const rows = await apiGet<NCRWire[]>(`/v1/ncr/${qs ? `?${qs}` : ''}`);
  return rows.map(normaliseNCR);
}

export async function createNCR(data: CreateNCRPayload): Promise<NCR> {
  const row = await apiPost<NCRWire>('/v1/ncr/', data);
  return normaliseNCR(row);
}

export async function closeNCR(id: string): Promise<NCR> {
  const row = await apiPost<NCRWire>(`/v1/ncr/${id}/close/`);
  return normaliseNCR(row);
}
