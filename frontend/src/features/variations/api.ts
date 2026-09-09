// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Variations module.
 *
 * Backed by /api/v1/variations/ — see
 * backend/app/modules/variations/router.py
 */

import { apiGet, apiPost, apiPut, apiPatch, apiDelete, type Page } from '@/shared/lib/api';

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
  /** The bill that was in front of the approver, frozen at submission. */
  submitted_boq_id: string | null;
  /**
   * What that bill priced at, read once at submission and never recomputed.
   * Null when the request carries no bill of its own, which is a different
   * statement from a bill that prices at nothing.
   */
  submitted_boq_total: string | null;
  /**
   * The submitted bill as a snapshot in the bill's own version history, which
   * is what makes the total above openable: the bill itself keeps being
   * revised while the variation is negotiated, so reading it today does not
   * tell anyone what the approver saw. The API has served this since the
   * commercial approval boundary landed and this interface did not declare
   * it, so the field arrived on the wire and every reader here was blind to
   * it. Null for a request with no bill and for one submitted before the
   * snapshot was taken.
   */
  submitted_boq_snapshot_id: string | null;
  /** What was actually agreed. Null until somebody has decided. */
  agreed_cost_impact: string | null;
  /** 'negotiated' | 'priced_boq' | 'headline_estimate', or '' when undecided. */
  agreed_basis: string;
  /** Why the agreed amount departs from the pricing state it was agreed against. */
  agreed_variance_note: string;
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
  // Soft link to the contract this order amends. Completing an order that
  // names one is what moves the contract sum, so an order created without
  // it can never post.
  affected_contract_id?: string | null;
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
  affected_contract_id?: string | null;
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
}): Promise<Page<Notice>> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Page<Notice>>(`/v1/variations/notices/?${qs.toString()}`);
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
}): Promise<Page<VariationRequest>> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Page<VariationRequest>>(`/v1/variations/variation-requests/?${qs.toString()}`);
}

export function createVR(data: CreateVRPayload): Promise<VariationRequest> {
  return apiPost<VariationRequest>('/v1/variations/variation-requests/', data);
}

export function submitVR(id: string): Promise<VariationRequest> {
  return apiPost<VariationRequest>(`/v1/variations/variation-requests/${id}/submit`, {});
}

/**
 * What one approval decides, in the shape the approve route reads.
 *
 * The wire name of the money is `decided_amount`, not `agreed_cost_impact`:
 * the latter is what the server writes down and serves back, and sending it
 * as the request key is accepted with a 200 and silently dropped, which
 * records the bill total as the agreed value and looks exactly like success.
 */
export interface ApproveVRPayload {
  decision_notes?: string;
  /**
   * The amount actually agreed, when it is not simply the pricing state that
   * was submitted. Sent as the string the approver typed so the server parses
   * the decimal they saw rather than a float that has been through binary.
   * Left out entirely to approve on the submitted pricing state, which the
   * server then records as `priced_boq` or `headline_estimate`.
   */
  decided_amount?: string;
  /**
   * Why the agreed amount departs from the submitted bill total. The server
   * refuses a departure without one, because the gap between the two figures
   * is the only part of the decision nobody can reconstruct afterwards.
   */
  agreed_variance_note?: string;
}

export function approveVR(
  id: string,
  payload: ApproveVRPayload = {},
): Promise<VariationRequest> {
  return apiPost<VariationRequest>(
    `/v1/variations/variation-requests/${id}/approve`,
    payload,
  );
}

export function rejectVR(
  id: string,
  decision_notes?: string,
): Promise<VariationRequest> {
  return apiPost<VariationRequest>(`/v1/variations/variation-requests/${id}/reject`, {
    decision_notes,
  });
}

/**
 * Promote an approved request into an order.
 *
 * Anything left out is carried over from the request itself by the backend
 * (title, estimated cost impact, schedule days, currency), so a caller only
 * names the fields it wants to differ from the request. A zero cost impact or
 * zero schedule days is taken at face value; an empty title or currency reads
 * as "left out".
 */
export function convertVRToVO(
  id: string,
  payload: {
    title?: string;
    final_cost_impact?: number | string;
    final_schedule_days?: number;
    currency?: string;
    affected_contract_id?: string | null;
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

/* ── A request's own bill of quantities (Issue #435) ───────────────────── */

/**
 * What a variation line does to the source it traces to.
 *
 * `added` is scope the contract never held; `removed` is contracted scope the
 * variation omits, carried as a negative quantity against the schedule of
 * values; `modified` is the same contract line kept at a different quantity
 * or rate. Stated by the estimator, never inferred from the numbers: the
 * server's `variations.change_kind_matches_numbers` rule reports a
 * contradiction between the two, it does not resolve it.
 */
export type VariationChangeKind = 'added' | 'removed' | 'modified';

export const VARIATION_CHANGE_KINDS: readonly VariationChangeKind[] = ['added', 'removed', 'modified'];

/** Where one line of a variation's bill came from, and what it does to it. */
export interface VariationBOQTrace {
  id: string;
  variation_request_id: string;
  boq_id: string;
  position_id: string;
  /** 'boq_position' | 'contract_line' | 'manual' */
  origin: string;
  source_boq_id: string | null;
  source_position_id: string | null;
  contract_id: string | null;
  contract_line_id: string | null;
  /** `added` on every row written before the kind existed. */
  change_kind: VariationChangeKind;
  note: string;
  created_at: string;
}

/** The lines of one change kind and what they add up to (direct cost, base currency). */
export interface VariationBOQKindSubtotal {
  line_count: number;
  total: string;
}

/**
 * The bill's direct cost split by what each line does to the contract. The
 * net is the sum of the three, so an omission carried as a negative line
 * comes off and the figure reads as arithmetic a person can check. A line
 * with no trace row counts as `added`.
 */
export interface VariationBOQChangeSummary {
  added: VariationBOQKindSubtotal;
  removed: VariationBOQKindSubtotal;
  modified: VariationBOQKindSubtotal;
  net_total: string;
}

/** One validation finding about the bill, from the variations rule set. */
export interface VariationBOQCheck {
  rule_id: string;
  severity: string;
  passed: boolean;
  message: string;
}

/**
 * A variation request's dedicated bill, priced and traced.
 *
 * `has_boq` false is the state every request was in before this existed and
 * still the state of most: the money fields are then null rather than zero,
 * because a request with no bill has no priced total and that is a different
 * statement from "priced at nothing".
 */
export interface VariationBOQ {
  variation_request_id: string;
  has_boq: boolean;
  boq_id: string | null;
  name: string;
  status: string;
  is_locked: boolean;
  parent_estimate_id: string | null;
  position_count: number;
  base_currency: string;
  direct_cost: string | null;
  markups_total: string | null;
  grand_total: string | null;
  is_mixed_currency: boolean;
  estimated_cost_impact: string;
  estimate_matches_boq: boolean;
  traces: VariationBOQTrace[];
  /** Null when there is no bill, for the same reason the money fields are. */
  change_summary: VariationBOQChangeSummary | null;
  checks: VariationBOQCheck[];
}

export interface CreateVariationBOQPayload {
  name?: string;
  description?: string;
  base_date?: string | null;
  source_positions?: {
    position_id: string;
    quantity?: number | string;
    /** Left out to mean `added`, which is what the server records for it. */
    change_kind?: VariationChangeKind;
    note?: string;
  }[];
  source_contract_lines?: {
    contract_line_id: string;
    quantity?: number | string;
    change_kind?: VariationChangeKind;
    note?: string;
  }[];
}

/**
 * One line's provenance as the trace PUT reads it. Every field is sent on
 * every write, including the nulls: the server replaces the row whole, and a
 * body that named only the new reference would still read as a full answer,
 * so the client says the whole answer too rather than relying on that.
 */
export interface SetVariationBOQLineTracePayload {
  contract_line_id: string | null;
  source_position_id: string | null;
  change_kind: VariationChangeKind;
  note: string;
}

export function getVariationRequestBOQ(id: string): Promise<VariationBOQ> {
  return apiGet<VariationBOQ>(`/v1/variations/variation-requests/${id}/boq/`);
}

/**
 * Open the request's own bill. The response is the BOQ row itself, so the
 * caller can navigate straight into the editor with its id.
 */
export function createVariationRequestBOQ(
  id: string,
  payload: CreateVariationBOQPayload = {},
): Promise<{ id: string; name: string; project_id: string }> {
  return apiPost<{ id: string; name: string; project_id: string }>(
    `/v1/variations/variation-requests/${id}/boq/`,
    payload,
  );
}

/** Replace the request's headline estimate with what its bill prices. */
export function adoptVariationRequestBOQ(id: string): Promise<VariationRequest> {
  return apiPost<VariationRequest>(
    `/v1/variations/variation-requests/${id}/boq/adopt`,
    {},
  );
}

/**
 * Record where one line of the request's bill came from and what it does to
 * that source. The route exists for every line typed into the bill after it
 * was opened, which is most of them; until the editor called it, such a line
 * could never acquire provenance from the product at all.
 */
export function setVariationBOQLineTrace(
  requestId: string,
  positionId: string,
  payload: SetVariationBOQLineTracePayload,
): Promise<VariationBOQTrace> {
  return apiPut<VariationBOQTrace>(
    `/v1/variations/variation-requests/${requestId}/boq/lines/${positionId}/trace`,
    payload,
  );
}

/**
 * Withdraw a line's provenance. The row survives as `manual` / `added` with
 * no references, so "somebody said this derives from nothing" stays
 * distinguishable from "nobody has looked".
 */
export function clearVariationBOQLineTrace(
  requestId: string,
  positionId: string,
): Promise<VariationBOQTrace> {
  return apiDelete<VariationBOQTrace>(
    `/v1/variations/variation-requests/${requestId}/boq/lines/${positionId}/trace`,
  );
}

/* ── Variation Orders ──────────────────────────────────────────────────── */

export function listVariationOrders(params: {
  project_id: string;
  status?: string;
  limit?: number;
}): Promise<Page<VariationOrder>> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Page<VariationOrder>>(`/v1/variations/variation-orders/?${qs.toString()}`);
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
}): Promise<Page<DayworkSheet>> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Page<DayworkSheet>>(`/v1/variations/daywork-sheets/?${qs.toString()}`);
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
}): Promise<Page<ExtensionOfTimeClaim>> {
  const qs = new URLSearchParams();
  qs.set('project_id', params.project_id);
  if (params.status) qs.set('status', params.status);
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return apiGet<Page<ExtensionOfTimeClaim>>(`/v1/variations/eot-claims/?${qs.toString()}`);
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
