/**
 * API helpers for the Variations module.
 *
 * Backed by /api/v1/variations/ — see
 * backend/app/modules/variations/router.py
 */

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type NoticeStatus = 'issued' | 'acknowledged' | 'responded' | 'closed';
export type NoticeRecipient =
  | 'owner'
  | 'contractor'
  | 'architect'
  | 'engineer'
  | 'consultant';
export type VRStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'approved'
  | 'rejected'
  | 'converted_to_vo';
export type VRClassification =
  | 'scope_change'
  | 'unforeseen'
  | 'owner_change'
  | 'design_dev'
  | 'regulatory'
  | 'other';
export type VRUrgency = 'low' | 'med' | 'high';
export type VOStatus = 'issued' | 'in_progress' | 'completed' | 'voided';
export type DayworkStatus = 'draft' | 'signed' | 'disputed' | 'billed';
export type DisruptionStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'agreed'
  | 'rejected';
export type EotStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'granted'
  | 'rejected';
export type EotCause =
  | 'employer_caused'
  | 'neutral'
  | 'contractor_caused'
  | 'concurrent';

export interface Notice {
  id: string;
  project_id: string;
  code: string;
  title: string;
  description: string;
  raised_at: string | null;
  raised_by: string | null;
  recipient_type: NoticeRecipient;
  recipient_name: string;
  target_response_date: string | null;
  response_received_at: string | null;
  response_summary: string;
  status: NoticeStatus;
  reference_change_order_id: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface VariationRequest {
  id: string;
  project_id: string;
  notice_id: string | null;
  code: string;
  title: string;
  description: string;
  requested_by: string | null;
  requested_at: string | null;
  classification: VRClassification;
  urgency: VRUrgency;
  estimated_cost_impact: number | string;
  estimated_schedule_days: number;
  currency: string;
  status: VRStatus;
  submitted_at: string | null;
  decision_at: string | null;
  decision_notes: string;
  decided_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface VariationOrder {
  id: string;
  project_id: string;
  variation_request_id: string | null;
  code: string;
  title: string;
  final_cost_impact: number | string;
  final_schedule_days: number;
  currency: string;
  agreed_at: string | null;
  signed_by: string | null;
  status: VOStatus;
  reference_change_order_id: string | null;
  affected_contract_id: string | null;
  implementation_started_at: string | null;
  implementation_completed_at: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface DayworkSheet {
  id: string;
  project_id: string;
  sheet_number: string;
  work_date: string | null;
  description: string;
  total_amount: number | string;
  currency: string;
  status: DayworkStatus;
  signed_by: string | null;
  signed_at: string | null;
  owner_signature_ref: string;
  supplied_via_contract_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface ExtensionOfTimeClaim {
  id: string;
  project_id: string;
  raised_at: string | null;
  raised_by: string | null;
  claim_period_start: string | null;
  claim_period_end: string | null;
  description: string;
  root_cause_category: EotCause;
  requested_days: number;
  granted_days: number | null;
  critical_path_impact: boolean;
  status: EotStatus;
  decision_at: string | null;
  decision_notes: string;
  created_at: string;
  updated_at: string;
}

export interface VariationDashboard {
  project_id: string;
  notices_total: number;
  notices_open: number;
  requests_total: number;
  requests_pending: number;
  requests_approved: number;
  requests_rejected: number;
  variation_orders_total: number;
  variation_orders_active: number;
  variation_orders_completed: number;
  cost_impact_total: number | string;
  schedule_impact_days: number;
  daywork_sheets_total: number;
  daywork_sheets_signed: number;
  daywork_value_signed: number | string;
  disruption_claims_open: number;
  eot_claims_open: number;
  final_account_status: string;
  currency: string;
}

/* ── Create payloads ────────────────────────────────────────────────────── */

export interface CreateNoticePayload {
  project_id: string;
  title?: string;
  description?: string;
  recipient_type?: NoticeRecipient;
  recipient_name?: string;
  target_response_date?: string;
}

export interface CreateVRPayload {
  project_id: string;
  notice_id?: string | null;
  title?: string;
  description?: string;
  classification?: VRClassification;
  urgency?: VRUrgency;
  estimated_cost_impact?: number | string;
  estimated_schedule_days?: number;
  currency?: string;
}

export interface CreateVOPayload {
  project_id: string;
  variation_request_id?: string | null;
  title?: string;
  final_cost_impact?: number | string;
  final_schedule_days?: number;
  currency?: string;
}

export interface CreateDayworkPayload {
  project_id: string;
  work_date?: string;
  description?: string;
  currency?: string;
}

export interface CreateEoTPayload {
  project_id: string;
  description?: string;
  root_cause_category?: EotCause;
  requested_days?: number;
  critical_path_impact?: boolean;
  claim_period_start?: string;
  claim_period_end?: string;
}

/* ── Update payloads ────────────────────────────────────────────────────── */
// Mirror the backend *Update Pydantic schemas (all fields optional/PATCH).

export interface UpdateNoticePayload {
  title?: string;
  description?: string;
  recipient_type?: NoticeRecipient;
  recipient_name?: string;
  target_response_date?: string | null;
}

export interface UpdateVRPayload {
  title?: string;
  description?: string;
  classification?: VRClassification;
  urgency?: VRUrgency;
  estimated_cost_impact?: number | string;
  estimated_schedule_days?: number;
  currency?: string;
}

export interface UpdateVOPayload {
  title?: string;
  final_cost_impact?: number | string;
  final_schedule_days?: number;
  currency?: string;
}

export interface UpdateDayworkPayload {
  work_date?: string | null;
  description?: string;
  currency?: string;
}

export interface UpdateEoTPayload {
  description?: string;
  root_cause_category?: EotCause;
  requested_days?: number;
  critical_path_impact?: boolean;
}

/* ── Notices ───────────────────────────────────────────────────────────── */

export function listNotices(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<Notice[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Notice[]>(`/v1/variations/notices/?${qs.toString()}`);
}

export function createNotice(data: CreateNoticePayload): Promise<Notice> {
  return apiPost<Notice>('/v1/variations/notices/', data);
}

export function acknowledgeNotice(id: string): Promise<Notice> {
  return apiPost<Notice>(`/v1/variations/notices/${id}/acknowledge`, {});
}

export function respondNotice(id: string, response_summary?: string): Promise<Notice> {
  return apiPost<Notice>(`/v1/variations/notices/${id}/respond`, {
    response_summary,
  });
}

export function closeNotice(id: string): Promise<Notice> {
  return apiPost<Notice>(`/v1/variations/notices/${id}/close`, {});
}

export function updateNotice(
  id: string,
  data: UpdateNoticePayload,
): Promise<Notice> {
  return apiPatch<Notice>(`/v1/variations/notices/${id}`, data);
}

export function deleteNotice(id: string): Promise<void> {
  return apiDelete(`/v1/variations/notices/${id}`);
}

/* ── Variation Requests ────────────────────────────────────────────────── */

export function listVariationRequests(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<VariationRequest[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<VariationRequest[]>(`/v1/variations/variation-requests/?${qs.toString()}`);
}

export function createVR(data: CreateVRPayload): Promise<VariationRequest> {
  return apiPost<VariationRequest>('/v1/variations/variation-requests/', data);
}

export function submitVR(id: string): Promise<VariationRequest> {
  return apiPost<VariationRequest>(`/v1/variations/variation-requests/${id}/submit`, {});
}

export function approveVR(
  id: string,
  decision_notes?: string,
): Promise<VariationRequest> {
  return apiPost<VariationRequest>(`/v1/variations/variation-requests/${id}/approve`, {
    decision_notes,
  });
}

export function rejectVR(
  id: string,
  decision_notes?: string,
): Promise<VariationRequest> {
  return apiPost<VariationRequest>(`/v1/variations/variation-requests/${id}/reject`, {
    decision_notes,
  });
}

export function convertVRToVO(
  id: string,
  payload: {
    title?: string;
    final_cost_impact?: number | string;
    final_schedule_days?: number;
    currency?: string;
  } = {},
): Promise<VariationOrder> {
  return apiPost<VariationOrder>(
    `/v1/variations/variation-requests/${id}/convert-to-vo`,
    payload,
  );
}

export function updateVR(
  id: string,
  data: UpdateVRPayload,
): Promise<VariationRequest> {
  return apiPatch<VariationRequest>(
    `/v1/variations/variation-requests/${id}`,
    data,
  );
}

export function deleteVR(id: string): Promise<void> {
  return apiDelete(`/v1/variations/variation-requests/${id}`);
}

/* ── Variation Orders ──────────────────────────────────────────────────── */

export function listVariationOrders(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<VariationOrder[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<VariationOrder[]>(`/v1/variations/variation-orders/?${qs.toString()}`);
}

export function createVO(data: CreateVOPayload): Promise<VariationOrder> {
  return apiPost<VariationOrder>('/v1/variations/variation-orders/', data);
}

export function startVO(id: string): Promise<VariationOrder> {
  return apiPost<VariationOrder>(`/v1/variations/variation-orders/${id}/start`, {});
}

export function completeVO(id: string): Promise<VariationOrder> {
  return apiPost<VariationOrder>(`/v1/variations/variation-orders/${id}/complete`, {});
}

export function voidVO(id: string): Promise<VariationOrder> {
  return apiPost<VariationOrder>(`/v1/variations/variation-orders/${id}/void`, {});
}

export function updateVO(
  id: string,
  data: UpdateVOPayload,
): Promise<VariationOrder> {
  return apiPatch<VariationOrder>(
    `/v1/variations/variation-orders/${id}`,
    data,
  );
}

export function deleteVO(id: string): Promise<void> {
  return apiDelete(`/v1/variations/variation-orders/${id}`);
}

/* ── Daywork ───────────────────────────────────────────────────────────── */

export function listDaywork(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<DayworkSheet[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<DayworkSheet[]>(`/v1/variations/daywork-sheets/?${qs.toString()}`);
}

export function createDaywork(data: CreateDayworkPayload): Promise<DayworkSheet> {
  return apiPost<DayworkSheet>('/v1/variations/daywork-sheets/', data);
}

export function signDaywork(id: string): Promise<DayworkSheet> {
  return apiPost<DayworkSheet>(`/v1/variations/daywork-sheets/${id}/sign`, {});
}

export function disputeDaywork(id: string): Promise<DayworkSheet> {
  return apiPost<DayworkSheet>(`/v1/variations/daywork-sheets/${id}/dispute`, {});
}

export function billDaywork(id: string): Promise<DayworkSheet> {
  return apiPost<DayworkSheet>(`/v1/variations/daywork-sheets/${id}/bill`, {});
}

export function updateDaywork(
  id: string,
  data: UpdateDayworkPayload,
): Promise<DayworkSheet> {
  return apiPatch<DayworkSheet>(`/v1/variations/daywork-sheets/${id}`, data);
}

export function deleteDaywork(id: string): Promise<void> {
  return apiDelete(`/v1/variations/daywork-sheets/${id}`);
}

/* ── EoT Claims ────────────────────────────────────────────────────────── */

export function listEoTClaims(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<ExtensionOfTimeClaim[]> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<ExtensionOfTimeClaim[]>(`/v1/variations/eot-claims/?${qs.toString()}`);
}

export function createEoT(data: CreateEoTPayload): Promise<ExtensionOfTimeClaim> {
  return apiPost<ExtensionOfTimeClaim>('/v1/variations/eot-claims/', data);
}

export function submitEoT(id: string): Promise<ExtensionOfTimeClaim> {
  return apiPost<ExtensionOfTimeClaim>(`/v1/variations/eot-claims/${id}/submit`, {});
}

export function grantEoT(
  id: string,
  granted_days: number,
  decision_notes?: string,
): Promise<ExtensionOfTimeClaim> {
  return apiPost<ExtensionOfTimeClaim>(`/v1/variations/eot-claims/${id}/grant`, {
    granted_days,
    decision_notes,
  });
}

export function rejectEoT(
  id: string,
  decision_notes?: string,
): Promise<ExtensionOfTimeClaim> {
  return apiPost<ExtensionOfTimeClaim>(`/v1/variations/eot-claims/${id}/reject`, {
    decision_notes,
  });
}

export function updateEoT(
  id: string,
  data: UpdateEoTPayload,
): Promise<ExtensionOfTimeClaim> {
  return apiPatch<ExtensionOfTimeClaim>(
    `/v1/variations/eot-claims/${id}`,
    data,
  );
}

export function deleteEoT(id: string): Promise<void> {
  return apiDelete(`/v1/variations/eot-claims/${id}`);
}

/* ── Dashboard ─────────────────────────────────────────────────────────── */

export function projectDashboard(projectId: string): Promise<VariationDashboard> {
  return apiGet<VariationDashboard>(`/v1/variations/dashboard/project/${projectId}`);
}
