/**
 * API helpers for the Quality Management System (QMS) module.
 *
 * Backed by /api/v1/qms/ — see backend/app/modules/qms/router.py
 */

import { apiGet, apiPost, apiPatch } from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type ITPStatus = 'draft' | 'active' | 'superseded' | 'closed';
export type InspectionStatus =
  | 'scheduled'
  | 'in_progress'
  | 'passed'
  | 'failed'
  | 'conditional';
export type NCRStatus =
  | 'open'
  | 'action_pending'
  | 'verifying'
  | 'closed'
  | 'cancelled';
export type NCRSeverity = 'minor' | 'major' | 'critical';
export type PunchStatus =
  | 'open'
  | 'assigned'
  | 'in_progress'
  | 'ready_for_inspection'
  | 'closed'
  | 'rejected';
export type PunchCategory =
  | 'architectural'
  | 'mechanical'
  | 'electrical'
  | 'finishes'
  | 'structure';
export type AuditType = 'internal' | 'external' | 'supplier';
export type AuditStatus = 'planned' | 'in_progress' | 'completed' | 'closed';
export type FindingType = 'observation' | 'minor' | 'major' | 'critical';

export interface ITPPlan {
  id: string;
  project_id: string;
  name: string;
  work_type: string;
  wbs_ref: string | null;
  status: ITPStatus;
  version: number;
  created_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface ITPItem {
  id: string;
  itp_plan_id: string;
  sequence: number;
  control_point_name: string;
  criteria: string | null;
  frequency: string | null;
  method: string | null;
  acceptance_criteria: string | null;
  hold_witness_point: 'hold' | 'witness' | 'review';
  responsible_role: string | null;
  signatories_required: number;
  boq_position_id: string | null;
  csi_section_ref: string | null;
  spec_drawing_ref: string | null;
  bim_element_id: string | null;
  predecessor_itp_item_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface HoldPointStatus {
  inspection_id: string;
  itp_item_id: string | null;
  is_hold_point: boolean;
  predecessor_itp_item_id: string | null;
  predecessor_passed: boolean;
  blocked: boolean;
  blocking_reason: string | null;
  released: boolean;
}

export interface InspectionAttachment {
  id: string;
  inspection_id: string;
  document_id: string;
  caption: string | null;
  file_hash_sha256: string | null;
  uploaded_by: string | null;
  attached_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface HoldPointRelease {
  id: string;
  inspection_id: string;
  released_by: string | null;
  released_at: string | null;
  justification: string | null;
  approval_route_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface Inspection {
  id: string;
  project_id: string;
  itp_item_id: string | null;
  location_ref: string | null;
  inspector_user_id: string | null;
  scheduled_at: string | null;
  performed_at: string | null;
  status: InspectionStatus;
  bim_element_ref: string | null;
  drawing_ref: string | null;
  notes: string | null;
  photos_json: Array<Record<string, unknown>>;
  attachment_document_ids: string[];
  created_at: string;
  updated_at: string;
}

export interface InspectionSignature {
  id: string;
  inspection_id: string;
  signer_user_id: string;
  signer_role: 'GC' | 'designer' | 'client' | 'subcontractor' | 'inspector' | 'other';
  signed_at: string | null;
  signature_method: 'electronic' | 'wet' | 'biometric';
  comments: string | null;
  timestamp_utc: string | null;
  signer_ip: string | null;
  signer_user_agent: string | null;
  created_at: string;
  updated_at: string;
}

export interface NCR {
  id: string;
  project_id: string;
  raised_by: string | null;
  raised_at: string | null;
  title: string;
  description: string;
  severity: NCRSeverity;
  root_cause: string | null;
  status: NCRStatus;
  cost_impact_currency: string;
  cost_impact_amount: number | string | null;
  linked_variation_id: string | null;
  linked_inspection_id: string | null;
  created_at: string;
  updated_at: string;
}

export interface NCRAction {
  id: string;
  ncr_id: string;
  description: string;
  responsible_user_id: string | null;
  due_date: string | null;
  status: 'assigned' | 'in_progress' | 'done';
  verification_method: string | null;
  verified_by: string | null;
  verified_at: string | null;
  completed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface PunchItem {
  id: string;
  project_id: string;
  raised_at: string | null;
  raised_by: string | null;
  title: string;
  description: string | null;
  room_ref: string | null;
  drawing_ref: string | null;
  bim_element_ref: string | null;
  status: PunchStatus;
  severity: NCRSeverity;
  assigned_to: string | null;
  due_date: string | null;
  closed_at: string | null;
  photos_json: Array<Record<string, unknown>>;
  source: 'manual' | 'inspection' | 'walkthrough';
  category: PunchCategory | null;
  created_at: string;
  updated_at: string;
}

export interface Audit {
  id: string;
  project_id: string;
  audit_type: AuditType;
  planned_date: string | null;
  performed_at: string | null;
  auditor_user_id: string | null;
  audit_scope: string | null;
  standard_ref: string | null;
  status: AuditStatus;
  overall_rating: number | null;
  created_at: string;
  updated_at: string;
}

export interface AuditFinding {
  id: string;
  audit_id: string;
  finding_type: FindingType;
  description: string;
  clause_ref: string | null;
  corrective_action_required: string | null;
  status: 'open' | 'in_progress' | 'verified' | 'closed';
  due_date: string | null;
  closed_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface COPQReport {
  project_id: string;
  ncr_cost_total: number | string;
  open_punch_count: number;
  rework_cost_estimate: number | string;
  copq_total: number | string;
  currency: string;
}

export interface FirstPassYieldReport {
  project_id: string;
  inspections_total: number;
  inspections_passed_first_time: number;
  first_pass_yield: number;
}

/* ── Create / update payloads ──────────────────────────────────────────── */

export interface CreateITPPlanPayload {
  project_id: string;
  name: string;
  work_type: string;
  wbs_ref?: string;
  status?: ITPStatus;
  version?: number;
}

export interface CreateITPItemPayload {
  sequence?: number;
  control_point_name: string;
  criteria?: string;
  frequency?: string;
  method?: string;
  acceptance_criteria?: string;
  hold_witness_point?: 'hold' | 'witness' | 'review';
  responsible_role?: string;
  signatories_required?: number;
  boq_position_id?: string;
  csi_section_ref?: string;
  spec_drawing_ref?: string;
  bim_element_id?: string;
  predecessor_itp_item_id?: string;
}

export interface LinkITPItemSpecPayload {
  boq_position_id?: string | null;
  csi_section_ref?: string | null;
  spec_drawing_ref?: string | null;
  bim_element_id?: string | null;
  predecessor_itp_item_id?: string | null;
}

export interface AttachEvidencePayload {
  document_id: string;
  caption?: string;
  file_hash_sha256?: string;
}

export interface ReleaseHoldPointPayload {
  justification: string;
  approval_route_id?: string;
}

export interface CreateInspectionPayload {
  project_id: string;
  itp_item_id?: string;
  location_ref?: string;
  inspector_user_id?: string;
  scheduled_at?: string;
  bim_element_ref?: string;
  drawing_ref?: string;
  notes?: string;
}

export interface SignInspectionPayload {
  /**
   * Omit to sign as the authenticated caller (the backend fills it from
   * the auth context). Supply a real member UUID only to record a sign-off
   * on behalf of someone else.
   */
  signer_user_id?: string;
  signer_role: InspectionSignature['signer_role'];
  signature_method?: InspectionSignature['signature_method'];
  comments?: string;
}

export interface CreateNCRPayload {
  project_id: string;
  title: string;
  description: string;
  severity?: NCRSeverity;
  root_cause?: string;
  cost_impact_currency?: string;
  cost_impact_amount?: number | string;
  linked_inspection_id?: string;
}

export interface UpdateNCRPayload {
  title?: string;
  description?: string;
  severity?: NCRSeverity;
  root_cause?: string;
  status?: NCRStatus;
  cost_impact_currency?: string;
  cost_impact_amount?: number | string;
}

export interface CreateNCRActionPayload {
  description: string;
  responsible_user_id?: string;
  due_date?: string;
  verification_method?: string;
}

export interface CreatePunchItemPayload {
  project_id: string;
  title: string;
  description?: string;
  room_ref?: string;
  drawing_ref?: string;
  bim_element_ref?: string;
  severity?: NCRSeverity;
  assigned_to?: string;
  due_date?: string;
  source?: 'manual' | 'inspection' | 'walkthrough';
  category?: PunchCategory;
}

export interface CreateAuditPayload {
  project_id: string;
  audit_type?: AuditType;
  planned_date?: string;
  auditor_user_id?: string;
  audit_scope?: string;
  standard_ref?: string;
}

export interface CreateAuditFindingPayload {
  finding_type?: FindingType;
  description: string;
  clause_ref?: string;
  corrective_action_required?: string;
  due_date?: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function buildQs(params: Record<string, string | number | undefined>): string {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '' && v !== null) qs.set(k, String(v));
  }
  const s = qs.toString();
  return s ? `?${s}` : '';
}

/* ── ITP Plans ─────────────────────────────────────────────────────────── */

export function listITPPlans(params: {
  project_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<ITPPlan[]> {
  return apiGet<ITPPlan[]>(`/v1/qms/itp-plans${buildQs(params)}`);
}

export function createITPPlan(data: CreateITPPlanPayload): Promise<ITPPlan> {
  return apiPost<ITPPlan>('/v1/qms/itp-plans', data);
}

export function listITPItems(planId: string): Promise<ITPItem[]> {
  return apiGet<ITPItem[]>(`/v1/qms/itp-plans/${planId}/items`);
}

export function addITPItem(
  planId: string,
  data: CreateITPItemPayload,
): Promise<ITPItem> {
  return apiPost<ITPItem>(`/v1/qms/itp-plans/${planId}/items`, data);
}

export function linkITPItemToSpec(
  planId: string,
  itemId: string,
  data: LinkITPItemSpecPayload,
): Promise<ITPItem> {
  return apiPatch<ITPItem>(
    `/v1/qms/itp-plans/${planId}/items/${itemId}/link-spec`,
    data,
  );
}

export function activateITPPlan(planId: string): Promise<ITPPlan> {
  return apiPost<ITPPlan>(`/v1/qms/itp-plans/${planId}/activate`, {});
}

/* ── Inspections ───────────────────────────────────────────────────────── */

export function listInspections(params: {
  project_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<Inspection[]> {
  return apiGet<Inspection[]>(`/v1/qms/inspections${buildQs(params)}`);
}

export function createInspection(
  data: CreateInspectionPayload,
): Promise<Inspection> {
  return apiPost<Inspection>('/v1/qms/inspections', data);
}

export interface InspectionSignaturesEnvelope {
  inspection_id: string;
  required: number;
  collected: number;
  signatures: InspectionSignature[];
}

export function listInspectionSignatures(
  inspectionId: string,
): Promise<InspectionSignaturesEnvelope> {
  return apiGet<InspectionSignaturesEnvelope>(
    `/v1/qms/inspections/${inspectionId}/signatures`,
  );
}

export function signInspection(
  inspectionId: string,
  data: SignInspectionPayload,
): Promise<InspectionSignature> {
  return apiPost<InspectionSignature>(
    `/v1/qms/inspections/${inspectionId}/sign`,
    data,
  );
}

export function completeInspection(
  inspectionId: string,
  result: 'passed' | 'failed' | 'conditional',
  notes?: string,
): Promise<Inspection> {
  return apiPost<Inspection>(
    `/v1/qms/inspections/${inspectionId}/complete${buildQs({ result, notes })}`,
    {},
  );
}

export function updateInspection(
  inspectionId: string,
  data: Partial<CreateInspectionPayload> & { status?: InspectionStatus },
): Promise<Inspection> {
  return apiPatch<Inspection>(`/v1/qms/inspections/${inspectionId}`, data);
}

/* ── Hold points + evidence (item 12) ──────────────────────────────────── */

export function checkHoldPointStatus(
  inspectionId: string,
): Promise<HoldPointStatus> {
  return apiGet<HoldPointStatus>(
    `/v1/qms/inspections/${inspectionId}/hold-point-status`,
  );
}

export function listInspectionEvidence(
  inspectionId: string,
): Promise<InspectionAttachment[]> {
  return apiGet<InspectionAttachment[]>(
    `/v1/qms/inspections/${inspectionId}/evidence`,
  );
}

export function attachInspectionEvidence(
  inspectionId: string,
  data: AttachEvidencePayload,
): Promise<InspectionAttachment> {
  return apiPost<InspectionAttachment>(
    `/v1/qms/inspections/${inspectionId}/attach-evidence`,
    data,
  );
}

export function releaseHoldPoint(
  inspectionId: string,
  data: ReleaseHoldPointPayload,
): Promise<HoldPointRelease> {
  return apiPost<HoldPointRelease>(
    `/v1/qms/inspections/${inspectionId}/release`,
    data,
  );
}

export function getHoldPointRelease(
  inspectionId: string,
): Promise<HoldPointRelease> {
  return apiGet<HoldPointRelease>(
    `/v1/qms/inspections/${inspectionId}/release`,
  );
}

/* ── Quality-gate enforcement + compliance export (item 12) ────────────── */

export interface ITPItemGateStatus {
  itp_item_id: string;
  is_hold_point: boolean;
  satisfied: boolean;
  reason: string | null;
}

/**
 * Resolve whether a control point's hold point blocks downstream work.
 * Used to render the gate traffic-light next to each control point and to
 * explain why dependent work cannot proceed yet.
 */
export function fetchITPItemGateStatus(
  planId: string,
  itemId: string,
): Promise<ITPItemGateStatus> {
  return apiGet<ITPItemGateStatus>(
    `/v1/qms/itp-plans/${planId}/items/${itemId}/gate-status`,
  );
}

export interface ComplianceSignature {
  signer_user_id: string;
  signer_role: string;
  signed_at: string | null;
  signature_method: string;
  timestamp_utc: string | null;
  signer_ip: string | null;
  comments: string | null;
}

export interface ComplianceEvidence {
  document_id: string;
  caption: string | null;
  file_hash_sha256: string | null;
  uploaded_by: string | null;
  attached_at: string | null;
}

export interface ComplianceRecord {
  inspection_id: string;
  project_id: string;
  status: string;
  scheduled_at: string | null;
  performed_at: string | null;
  location_ref: string | null;
  control_point_name: string | null;
  hold_witness_point: string | null;
  responsible_role: string | null;
  acceptance_criteria: string | null;
  csi_section_ref: string | null;
  spec_drawing_ref: string | null;
  boq_position_id: string | null;
  bim_element_id: string | null;
  signatures: ComplianceSignature[];
  evidence: ComplianceEvidence[];
  released: boolean;
  released_by: string | null;
  released_at: string | null;
  release_justification: string | null;
}

export interface PlanComplianceExport {
  plan_id: string;
  project_id: string;
  name: string;
  work_type: string;
  status: string;
  generated_at: string;
  records: ComplianceRecord[];
}

export function fetchInspectionComplianceRecord(
  inspectionId: string,
): Promise<ComplianceRecord> {
  return apiGet<ComplianceRecord>(
    `/v1/qms/inspections/${inspectionId}/compliance-export${buildQs({ format: 'json' })}`,
  );
}

export function fetchPlanComplianceExport(
  planId: string,
): Promise<PlanComplianceExport> {
  return apiGet<PlanComplianceExport>(
    `/v1/qms/itp-plans/${planId}/compliance-export${buildQs({ format: 'json' })}`,
  );
}

/**
 * Path for the CSV compliance export of an ITP plan. The endpoint requires a
 * JWT Bearer token (qms.report.read), so it CANNOT be opened with a plain
 * anchor - a top-level navigation cannot send the Authorization header and the
 * request returns 401. Callers must fetch it with an authed request and pass
 * the resulting blob to triggerDownload (see QMSPage.tsx).
 */
export function planComplianceCsvUrl(planId: string): string {
  return `/api/v1/qms/itp-plans/${planId}/compliance-export?format=csv`;
}

export function inspectionComplianceCsvUrl(inspectionId: string): string {
  return `/api/v1/qms/inspections/${inspectionId}/compliance-export?format=csv`;
}

/* ── NCRs ──────────────────────────────────────────────────────────────── */

export function listNCRs(params: {
  project_id: string;
  status?: string;
  severity?: string;
  offset?: number;
  limit?: number;
}): Promise<NCR[]> {
  return apiGet<NCR[]>(`/v1/qms/ncrs${buildQs(params)}`);
}

export function createNCR(data: CreateNCRPayload): Promise<NCR> {
  return apiPost<NCR>('/v1/qms/ncrs', data);
}

export function updateNCR(ncrId: string, data: UpdateNCRPayload): Promise<NCR> {
  return apiPatch<NCR>(`/v1/qms/ncrs/${ncrId}`, data);
}

export function addNCRAction(
  ncrId: string,
  data: CreateNCRActionPayload,
): Promise<NCRAction> {
  return apiPost<NCRAction>(`/v1/qms/ncrs/${ncrId}/actions`, data);
}

export function listNCRActions(ncrId: string): Promise<NCRAction[]> {
  return apiGet<NCRAction[]>(`/v1/qms/ncrs/${ncrId}/actions`);
}

export function verifyNCRAction(
  ncrId: string,
  actionId: string,
): Promise<NCRAction> {
  return apiPost<NCRAction>(
    `/v1/qms/ncrs/${ncrId}/actions/${actionId}/verify`,
    {},
  );
}

export function escalateNCRToVariation(
  ncrId: string,
  variationId?: string,
): Promise<NCR> {
  return apiPost<NCR>(
    `/v1/qms/ncrs/${ncrId}/escalate-to-variation${buildQs({ variation_id: variationId })}`,
    {},
  );
}

export function closeNCR(ncrId: string): Promise<NCR> {
  return apiPost<NCR>(`/v1/qms/ncrs/${ncrId}/close`, {});
}

/* ── Punch items ───────────────────────────────────────────────────────── */

export function listPunchItems(params: {
  project_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<PunchItem[]> {
  return apiGet<PunchItem[]>(`/v1/qms/punch-items${buildQs(params)}`);
}

export function createPunchItem(
  data: CreatePunchItemPayload,
): Promise<PunchItem> {
  return apiPost<PunchItem>('/v1/qms/punch-items', data);
}

export function assignPunchItem(
  punchId: string,
  assignedTo: string,
): Promise<PunchItem> {
  return apiPatch<PunchItem>(
    `/v1/qms/punch-items/${punchId}/assign${buildQs({ assigned_to: assignedTo })}`,
    {},
  );
}

export function closePunchItem(punchId: string): Promise<PunchItem> {
  return apiPost<PunchItem>(`/v1/qms/punch-items/${punchId}/close`, {});
}

/* ── Audits ────────────────────────────────────────────────────────────── */

export function listAudits(params: {
  project_id: string;
  status?: string;
  offset?: number;
  limit?: number;
}): Promise<Audit[]> {
  return apiGet<Audit[]>(`/v1/qms/audits${buildQs(params)}`);
}

export function createAudit(data: CreateAuditPayload): Promise<Audit> {
  return apiPost<Audit>('/v1/qms/audits', data);
}

export function addAuditFinding(
  auditId: string,
  data: CreateAuditFindingPayload,
): Promise<AuditFinding> {
  return apiPost<AuditFinding>(`/v1/qms/audits/${auditId}/findings`, data);
}

export function completeAudit(
  auditId: string,
  overallRating?: number,
): Promise<Audit> {
  return apiPost<Audit>(
    `/v1/qms/audits/${auditId}/complete${buildQs({ overall_rating: overallRating })}`,
    {},
  );
}

/* ── Reports ───────────────────────────────────────────────────────────── */

export function fetchCOPQ(
  projectId: string,
  currency = '',
): Promise<COPQReport> {
  return apiGet<COPQReport>(
    `/v1/qms/reports/copq${buildQs({ project_id: projectId, currency })}`,
  );
}

export function fetchFirstPassYield(
  projectId: string,
): Promise<FirstPassYieldReport> {
  return apiGet<FirstPassYieldReport>(
    `/v1/qms/reports/first-pass-yield${buildQs({ project_id: projectId })}`,
  );
}
