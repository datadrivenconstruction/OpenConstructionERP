// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Non-Conformance Reports (NCR).
 *
 * All endpoints are prefixed with /v1/ncr/.
 */

import { apiGet, apiPatch, apiPost, type Page } from '@/shared/lib/api';

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
  root_cause_category: string | null;
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
  /** Free-form metadata. Auto-raised NCRs carry `source` ("clash" | "qms")
   *  and the originating record id (`result_id`, `source_finding_id`). */
  metadata?: Record<string, unknown> | null;
}

export interface NCRFilters {
  project_id?: string;
  status?: NCRStatus | '';
  severity?: NCRSeverity | '';
  /** Row to start from. The route defaults to 0. */
  offset?: number;
  /** Rows to read. The route defaults to 50 and refuses more than 100. */
  limit?: number;
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

/** Partial edit for an existing NCR. Every field is optional; only the keys
 *  present are sent (PATCH semantics). `status` drives the lifecycle stepper -
 *  the backend validates each transition against its FSM and rejects illegal
 *  moves with a 400, so the UI only ever offers moves ncrFsm reports as legal.
 *  `cost_impact` is a decimal string on the wire (Decimal-as-string). */
export interface UpdateNCRPayload {
  title?: string;
  description?: string;
  ncr_type?: NCRType;
  severity?: NCRSeverity;
  status?: NCRStatus;
  root_cause?: string;
  root_cause_category?: string;
  corrective_action?: string;
  preventive_action?: string;
  cost_impact?: string | null;
  location_description?: string;
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

/**
 * One page of the NCR register, with `total` counting everything the filters
 * matched. The route caps `limit` at 100 and defaults to 50, and quality
 * records accumulate for the life of a project, so the rows are a slice and
 * `total` is the only thing that says by how much.
 */
export async function fetchNCRs(filters?: NCRFilters): Promise<Page<NCR>> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.severity) params.set('severity', filters.severity);
  // Written as a typeof test rather than a truthiness one: offset 0 is the
  // first page and must survive.
  if (typeof filters?.offset === 'number') params.set('offset', String(filters.offset));
  if (typeof filters?.limit === 'number') params.set('limit', String(filters.limit));
  const qs = params.toString();
  const page = await apiGet<Page<NCRWire>>(`/v1/ncr/${qs ? `?${qs}` : ''}`);
  return { ...page, items: page.items.map(normaliseNCR) };
}

export async function createNCR(data: CreateNCRPayload): Promise<NCR> {
  const row = await apiPost<NCRWire>('/v1/ncr/', data);
  return normaliseNCR(row);
}

export async function updateNCR(id: string, data: UpdateNCRPayload): Promise<NCR> {
  const row = await apiPatch<NCRWire, UpdateNCRPayload>(`/v1/ncr/${id}`, data);
  return normaliseNCR(row);
}

export async function closeNCR(id: string): Promise<NCR> {
  const row = await apiPost<NCRWire>(`/v1/ncr/${id}/close/`);
  return normaliseNCR(row);
}
