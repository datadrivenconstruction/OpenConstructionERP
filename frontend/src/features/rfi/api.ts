// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Requests for Information (RFI).
 *
 * All endpoints are prefixed with /v1/rfi/.
 */

import {
  API_BASE,
  activeLanguageTag,
  apiGet,
  apiPost,
  apiPatch,
  downloadWithAuth,
  type Page,
} from '@/shared/lib/api';
import { downloadRegister, type DocumentFormat } from '@/shared/lib/documentExport';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type RFIStatus = 'draft' | 'open' | 'answered' | 'closed' | 'void';

export type RFIPriority = 'low' | 'normal' | 'high' | 'critical';

/**
 * Common construction disciplines for an RFI. Kept as a constant so the
 * picker and the filter dropdown stay in lockstep.
 *
 * The backend column is free-form `String(50)` so future disciplines can
 * land without a migration — this list is only what the frontend offers.
 */
export const RFI_DISCIPLINES = [
  'architectural',
  'structural',
  'mep',
  'electrical',
  'plumbing',
  'civil',
  'landscape',
] as const;

export type RFIDiscipline = (typeof RFI_DISCIPLINES)[number];

export interface RFI {
  id: string;
  project_id: string;
  rfi_number: string;
  subject: string;
  question: string;
  official_response: string | null;
  status: RFIStatus;
  raised_by: string;
  assigned_to: string | null;
  ball_in_court: string | null;
  responded_by: string | null;
  responded_at: string | null;
  cost_impact: boolean;
  cost_impact_value: string | null;
  schedule_impact: boolean;
  schedule_impact_days: number | null;
  date_required: string | null;
  response_due_date: string | null;
  linked_drawing_ids: string[];
  /**
   * Server-derived relative paths of reply attachments, under
   * `uploads/rfi/attachments/`. Download an entry by its index via
   * `GET /v1/rfi/{id}/attachments/{index}`. Always an array (never null)
   * on the wire; empty when the RFI has no reply attachments.
   */
  attachments: string[];
  change_order_id: string | null;
  created_by: string | null;
  priority: RFIPriority | null;
  /**
   * Discipline — typically one of {@link RFI_DISCIPLINES} but kept as a
   * raw string here because the backend column is free-form and might
   * already carry custom values from other clients.
   */
  discipline: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  is_overdue: boolean;
  days_open: number;
}

export interface RFIFilters {
  project_id?: string;
  status?: RFIStatus | '';
  search?: string;
  offset?: number;
  limit?: number;
}

/**
 * One row from an RFI's activity journal. Mirrors the backend
 * `RFIActivityEntry` (read-only projection of `oe_activity_log`). The RFI
 * service records a row on every status transition (respond / close /
 * reopen), so the list reconstructs the RFI lifecycle. Ordered oldest-first
 * (chronological) by the endpoint.
 */
export interface RFIActivityEntry {
  id: string;
  actor_id: string | null;
  action: string;
  from_status: string | null;
  to_status: string | null;
  reason: string | null;
  module: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
}

export interface RFIStats {
  total: number;
  by_status: Record<string, number>;
  open: number;
  overdue: number;
  avg_days_to_response: number | null;
  cost_impact_count: number;
  schedule_impact_count: number;
}

export interface CreateRFIPayload {
  project_id: string;
  subject: string;
  question: string;
  ball_in_court?: string;
  assigned_to?: string;
  response_due_date?: string;
  date_required?: string;
  cost_impact?: boolean;
  cost_impact_value?: string;
  schedule_impact?: boolean;
  schedule_impact_days?: number;
  linked_drawing_ids?: string[];
  priority?: RFIPriority;
  discipline?: string;
}

/**
 * Partial update for an existing RFI. Mirrors the backend ``RFIUpdate``
 * schema - every field is optional and only the keys present are patched
 * (the backend merges, never wholesale-replaces). Re-routing
 * ``assigned_to`` / ``ball_in_court`` is a manager+ action server-side and
 * returns 403 for editors, so the UI should only offer it to that tier.
 *
 * The backend refuses any edit once an RFI is ``closed`` / ``void`` (400),
 * so callers should gate the edit affordance on an actionable status.
 *
 * ``status`` is accepted for explicit lifecycle transitions the backend
 * validates (notably ``draft`` -> ``open`` to publish a drafted RFI).
 * Illegal jumps are rejected server-side, so the UI only offers the
 * transitions that make sense for the current status.
 */
export interface UpdateRFIPayload {
  subject?: string;
  question?: string;
  status?: RFIStatus;
  ball_in_court?: string | null;
  assigned_to?: string | null;
  response_due_date?: string | null;
  date_required?: string | null;
  cost_impact?: boolean;
  cost_impact_value?: string | null;
  schedule_impact?: boolean;
  schedule_impact_days?: number | null;
  linked_drawing_ids?: string[];
  priority?: RFIPriority;
  discipline?: string | null;
}

export interface RespondRFIPayload {
  official_response: string;
}

/**
 * Response from `POST /v1/rfi/{id}/create-variation/`. Mirrors the backend
 * `RFIVariationResponse`. Returned both when a new change order is minted
 * (201) and, idempotently, when one is already linked to the RFI.
 */
export interface CreateVariationResponse {
  change_order_id: string;
  code: string;
  rfi_id: string;
  title: string;
}

/* ── API Functions ─────────────────────────────────────────────────────── */

export async function getRFI(id: string): Promise<RFI> {
  // The route is GET /{rfi_id} with NO trailing slash (router.py) and the
  // app runs with redirect_slashes=False, so a trailing slash here 404s
  // and the detail page permanently shows "RFI not found".
  return apiGet<RFI>(`/v1/rfi/${id}`);
}

/**
 * One page of the RFI register, with `total` counting everything the
 * filters matched. The endpoint caps `limit` at 100, so a register with
 * three hundred open questions always answers with a slice and the caller
 * has to read `total` to know that.
 */
export async function fetchRFIs(filters?: RFIFilters): Promise<Page<RFI>> {
  const params = new URLSearchParams();
  if (filters?.project_id) params.set('project_id', filters.project_id);
  if (filters?.status) params.set('status', filters.status);
  if (filters?.search && filters.search.trim()) params.set('search', filters.search.trim());
  if (typeof filters?.offset === 'number') params.set('offset', String(filters.offset));
  if (typeof filters?.limit === 'number') params.set('limit', String(filters.limit));
  const qs = params.toString();
  return apiGet<Page<RFI>>(`/v1/rfi/${qs ? `?${qs}` : ''}`);
}

export async function fetchRFIStats(projectId: string): Promise<RFIStats> {
  return apiGet<RFIStats>(`/v1/rfi/stats/?project_id=${encodeURIComponent(projectId)}`);
}

export async function createRFI(data: CreateRFIPayload): Promise<RFI> {
  return apiPost<RFI>('/v1/rfi/', data);
}

export async function updateRFI(id: string, data: UpdateRFIPayload): Promise<RFI> {
  // Route is PATCH /{rfi_id} with NO trailing slash (router.py); with
  // redirect_slashes=False a trailing slash would 404.
  return apiPatch<RFI, UpdateRFIPayload>(`/v1/rfi/${id}`, data);
}

export async function respondToRFI(id: string, data: RespondRFIPayload): Promise<RFI> {
  return apiPost<RFI>(`/v1/rfi/${id}/respond/`, data);
}

export async function closeRFI(id: string): Promise<RFI> {
  return apiPost<RFI>(`/v1/rfi/${id}/close/`);
}

export async function downloadRFIPdf(id: string, rfiNumber: string, locale?: string): Promise<void> {
  // Route is GET /{rfi_id}/export/pdf/ WITH a trailing slash (router.py).
  // The download skips apiGet and the Accept-Language header it attaches,
  // so the UI language travels as ?locale= or the form would follow the
  // browser's language instead of the one the reader picked. A caller may
  // name another language: the form is sent to people who do not read the
  // sender's.
  const lang = locale || activeLanguageTag();
  const query = lang ? `?locale=${encodeURIComponent(lang)}` : '';
  await downloadWithAuth(
    `${API_BASE}/v1/rfi/${encodeURIComponent(id)}/export/pdf/${query}`,
    `${rfiNumber || 'rfi'}.pdf`,
  );
}

/**
 * Download the RFI log of a project in the document language asked for.
 *
 * Route is GET /export/register/ (trailing slash, export_routes.py). The older
 * GET /export/ is still served and prints English only, whatever the reader's
 * language, so the screen no longer calls it. The route takes no filter: the
 * log is exported whole.
 */
export function downloadRFIRegister(
  projectId: string,
  format: DocumentFormat,
  locale: string,
): Promise<void> {
  return downloadRegister('/v1/rfi/export/register/', projectId, format, locale, 'rfi_log');
}

export async function createVariationFromRFI(id: string): Promise<CreateVariationResponse> {
  // Route is POST /{rfi_id}/create-variation/ WITH a trailing slash
  // (router.py); with redirect_slashes=False the no-slash form 404s.
  return apiPost<CreateVariationResponse>(`/v1/rfi/${id}/create-variation/`, {});
}

export async function fetchRFIActivity(id: string, limit = 50): Promise<Page<RFIActivityEntry>> {
  // Route is GET /{rfi_id}/activity/ WITH a trailing slash (router.py); with
  // redirect_slashes=False the no-slash form 404s. Returns the RFI's activity
  // journal oldest-first, so `total` is what tells the caller that the entries
  // it is missing are the RECENT ones rather than the old ones.
  return apiGet<Page<RFIActivityEntry>>(`/v1/rfi/${id}/activity/?limit=${limit}`);
}
