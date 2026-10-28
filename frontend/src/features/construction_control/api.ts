// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed API client for the construction-control (QA/QC) module.
//
// Covers all five pillars mounted at /v1/construction_control:
//   1. Acceptance criteria + inspections (MIR/WIR/IR/hidden-works, UER element
//      link, a failed result auto-raises an NCR).
//   2. Material records (EN 10204 digital passport, CE/UKCA, traceability) +
//      ISO/IEC 17025 lab test results.
//   3. As-built records (metrology tolerance, e-signed legal-record attestation,
//      import from a point-cloud scan).
//   4. Handover / acceptance packages (regime-aware taking-over / substantial /
//      practical completion, auto-assembled evidence manifest, completion gate,
//      e-signed certificate).
//   5. Hold / witness / surveillance / review gating (party-role hierarchy,
//      can-proceed check).
//
// Every list/create call carries a project context. Most reads pass project_id
// as a query parameter; creates pass it in the body. Money-like values are not
// used here, but any string-serialised numeric (measured values, tolerances)
// is kept as a string and rendered as-is.

import { apiGet, apiPost, apiPatch, apiDelete } from '@/shared/lib/api';

const BASE = '/v1/construction_control';

/** Build a query string from a record, skipping null/undefined/empty values. */
function qs(params: Record<string, string | number | boolean | null | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value === null || value === undefined || value === '') continue;
    search.append(key, String(value));
  }
  const str = search.toString();
  return str ? `?${str}` : '';
}

// ── Shared types ──────────────────────────────────────────────────────────

/** Inbound Universal Element Reference (UER). Any subset resolves server-side. */
export interface ElementRefIn {
  bim_element_id?: string | null;
  model_id?: string | null;
  stable_id?: string | null;
  source_format?: string | null;
  ifc_global_id?: string | null;
  native_id?: string | null;
  model_version?: string | null;
  element_name?: string | null;
  element_type?: string | null;
  bbox?: Record<string, unknown> | null;
  viewpoint?: Record<string, unknown> | null;
  metadata?: Record<string, unknown>;
}

/** A resolved Universal Element Reference returned from the API. */
export interface ElementRef {
  id: string;
  owner_type: string;
  owner_id: string;
  project_id: string;
  bim_element_id: string | null;
  model_id: string | null;
  stable_id: string | null;
  source_format: string | null;
  ifc_global_id: string | null;
  native_id: string | null;
  model_version: string | null;
  element_name: string | null;
  element_type: string | null;
  bbox: Record<string, unknown> | null;
  viewpoint: Record<string, unknown> | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Result grammar shared by inspections, material review and lab tests. */
export type ResultDecision = 'pass' | 'fail' | 'conditional';
/** NCR severity used when a failed check auto-raises a non-conformance. */
export type NcrSeverity = 'critical' | 'major' | 'minor' | 'observation';
/** Party-role hierarchy: qc < qa < tpi < ahj. */
export type PartyRole = 'qc' | 'qa' | 'tpi' | 'ahj';

const LIST_LIMIT = 100;

// ── Pillar 1: Acceptance criteria ──────────────────────────────────────────

export type AcceptanceRule = 'range' | 'min' | 'max' | 'boolean' | 'text';

export interface AcceptanceCriterion {
  id: string;
  project_id: string;
  code: string;
  title: string;
  description: string | null;
  standard_ref: string | null;
  discipline: string | null;
  category: string | null;
  characteristic: string | null;
  method: string | null;
  unit: string | null;
  acceptance_rule: AcceptanceRule;
  nominal_value: string | null;
  tolerance_lower: string | null;
  tolerance_upper: string | null;
  is_active: boolean;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface CriterionCreatePayload {
  project_id: string;
  code: string;
  title: string;
  description?: string | null;
  standard_ref?: string | null;
  discipline?: string | null;
  category?: string | null;
  characteristic?: string | null;
  method?: string | null;
  unit?: string | null;
  acceptance_rule?: AcceptanceRule;
  nominal_value?: string | null;
  tolerance_lower?: string | null;
  tolerance_upper?: string | null;
  is_active?: boolean;
  metadata?: Record<string, unknown>;
}

export type CriterionUpdatePayload = Partial<Omit<CriterionCreatePayload, 'project_id'>>;

export function listCriteria(
  projectId: string,
  opts: { category?: string; is_active?: boolean; offset?: number; limit?: number } = {},
): Promise<AcceptanceCriterion[]> {
  return apiGet<AcceptanceCriterion[]>(
    `${BASE}/criteria${qs({
      project_id: projectId,
      category: opts.category,
      is_active: opts.is_active,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createCriterion(payload: CriterionCreatePayload): Promise<AcceptanceCriterion> {
  return apiPost<AcceptanceCriterion>(`${BASE}/criteria`, payload);
}

export function getCriterion(criterionId: string): Promise<AcceptanceCriterion> {
  return apiGet<AcceptanceCriterion>(`${BASE}/criteria/${criterionId}`);
}

export function updateCriterion(
  criterionId: string,
  payload: CriterionUpdatePayload,
): Promise<AcceptanceCriterion> {
  return apiPatch<AcceptanceCriterion>(`${BASE}/criteria/${criterionId}`, payload);
}

export function deleteCriterion(criterionId: string): Promise<void> {
  return apiDelete(`${BASE}/criteria/${criterionId}`);
}

// ── Pillar 1: Inspections ──────────────────────────────────────────────────

export type InspectionType = 'mir' | 'wir' | 'ir' | 'hidden_works' | 'acceptance';
export type InterventionPoint = 'hold' | 'witness' | 'surveillance' | 'review';
export type InspectionStatus =
  | 'draft'
  | 'scheduled'
  | 'in_progress'
  | 'passed'
  | 'failed'
  | 'closed'
  | 'void';

export interface Inspection {
  id: string;
  project_id: string;
  inspection_number: string;
  inspection_type: InspectionType;
  party_role: PartyRole;
  intervention_point: InterventionPoint | null;
  title: string;
  description: string | null;
  location_description: string | null;
  activity_id: string | null;
  criterion_id: string | null;
  status: InspectionStatus;
  result: ResultDecision | null;
  measured_value: string | null;
  result_notes: string | null;
  raised_ncr_id: string | null;
  scheduled_at: string | null;
  performed_at: string | null;
  performed_by: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  elements: ElementRef[];
}

export interface InspectionCreatePayload {
  project_id: string;
  inspection_type: InspectionType;
  party_role?: PartyRole;
  intervention_point?: InterventionPoint | null;
  title: string;
  description?: string | null;
  location_description?: string | null;
  activity_id?: string | null;
  criterion_id?: string | null;
  scheduled_at?: string | null;
  element?: ElementRefIn | null;
  metadata?: Record<string, unknown>;
}

export interface InspectionUpdatePayload {
  inspection_type?: InspectionType;
  party_role?: PartyRole;
  intervention_point?: InterventionPoint | null;
  title?: string;
  description?: string | null;
  location_description?: string | null;
  activity_id?: string | null;
  criterion_id?: string | null;
  status?: InspectionStatus;
  scheduled_at?: string | null;
  metadata?: Record<string, unknown>;
}

export interface InspectionResultPayload {
  result: ResultDecision;
  measured_value?: string | null;
  notes?: string | null;
  performed_at?: string | null;
  ncr_severity?: NcrSeverity | null;
}

export function listInspections(
  projectId: string,
  opts: {
    type?: InspectionType;
    status?: InspectionStatus;
    party_role?: PartyRole;
    offset?: number;
    limit?: number;
  } = {},
): Promise<Inspection[]> {
  return apiGet<Inspection[]>(
    `${BASE}/inspections${qs({
      project_id: projectId,
      type: opts.type,
      status: opts.status,
      party_role: opts.party_role,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createInspection(payload: InspectionCreatePayload): Promise<Inspection> {
  return apiPost<Inspection>(`${BASE}/inspections`, payload);
}

export function getInspection(inspectionId: string): Promise<Inspection> {
  return apiGet<Inspection>(`${BASE}/inspections/${inspectionId}`);
}

export function updateInspection(
  inspectionId: string,
  payload: InspectionUpdatePayload,
): Promise<Inspection> {
  return apiPatch<Inspection>(`${BASE}/inspections/${inspectionId}`, payload);
}

export function deleteInspection(inspectionId: string): Promise<void> {
  return apiDelete(`${BASE}/inspections/${inspectionId}`);
}

/** Record a pass/fail/conditional outcome. A fail (or conditional) raises an NCR. */
export function recordInspectionResult(
  inspectionId: string,
  payload: InspectionResultPayload,
): Promise<Inspection> {
  return apiPost<Inspection>(`${BASE}/inspections/${inspectionId}/record-result`, payload);
}

// ── Pillar 2: Material records (EN 10204 digital passport) ───────────────────

export type CertType = '2.1' | '2.2' | '3.1' | '3.2' | 'dop' | 'ce' | 'ukca' | 'coc' | 'other';
export type MaterialStatus =
  | 'draft'
  | 'submitted'
  | 'under_review'
  | 'accepted'
  | 'rejected'
  | 'expired'
  | 'superseded';

export interface MaterialRecord {
  id: string;
  project_id: string;
  record_number: string;
  name: string;
  material_type: string | null;
  spec_grade: string | null;
  manufacturer: string | null;
  supplier: string | null;
  supplier_id: string | null;
  product_code: string | null;
  cert_type: CertType | null;
  cert_number: string | null;
  cert_issuer: string | null;
  cert_document_id: string | null;
  dop_number: string | null;
  ce_marking: boolean;
  ukca_marking: boolean;
  issued_at: string | null;
  valid_from: string | null;
  valid_until: string | null;
  batch_number: string | null;
  heat_number: string | null;
  lot_number: string | null;
  quantity: string | null;
  unit: string | null;
  criterion_id: string | null;
  po_id: string | null;
  gr_id: string | null;
  gr_item_id: string | null;
  status: MaterialStatus;
  review_notes: string | null;
  raised_ncr_id: string | null;
  received_at: string | null;
  received_by: string | null;
  reviewed_at: string | null;
  reviewed_by: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  /** Service-computed: the certificate validity window has lapsed. */
  is_expired: boolean;
  elements: ElementRef[];
}

export interface MaterialCreatePayload {
  project_id: string;
  name: string;
  material_type?: string | null;
  spec_grade?: string | null;
  manufacturer?: string | null;
  supplier?: string | null;
  supplier_id?: string | null;
  product_code?: string | null;
  cert_type?: CertType | null;
  cert_number?: string | null;
  cert_issuer?: string | null;
  cert_document_id?: string | null;
  dop_number?: string | null;
  ce_marking?: boolean;
  ukca_marking?: boolean;
  issued_at?: string | null;
  valid_from?: string | null;
  valid_until?: string | null;
  batch_number?: string | null;
  heat_number?: string | null;
  lot_number?: string | null;
  quantity?: string | null;
  unit?: string | null;
  criterion_id?: string | null;
  po_id?: string | null;
  gr_id?: string | null;
  gr_item_id?: string | null;
  /** A material may only be created into a pre-decision state. */
  status?: 'draft' | 'submitted';
  received_at?: string | null;
  element?: ElementRefIn | null;
  metadata?: Record<string, unknown>;
}

export type MaterialUpdatePayload = Partial<Omit<MaterialCreatePayload, 'project_id' | 'element' | 'status'>> & {
  status?: 'draft' | 'submitted' | 'under_review' | 'superseded';
};

/** Record a conformity decision. A reject (or conditional) raises a material NCR. */
export interface MaterialReviewPayload {
  decision: ResultDecision;
  notes?: string | null;
  reviewed_at?: string | null;
  ncr_severity?: NcrSeverity | null;
}

export function listMaterials(
  projectId: string,
  opts: {
    status?: MaterialStatus;
    material_type?: string;
    gr_id?: string;
    offset?: number;
    limit?: number;
  } = {},
): Promise<MaterialRecord[]> {
  return apiGet<MaterialRecord[]>(
    `${BASE}/materials${qs({
      project_id: projectId,
      status: opts.status,
      material_type: opts.material_type,
      gr_id: opts.gr_id,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createMaterial(payload: MaterialCreatePayload): Promise<MaterialRecord> {
  return apiPost<MaterialRecord>(`${BASE}/materials`, payload);
}

export function getMaterial(materialId: string): Promise<MaterialRecord> {
  return apiGet<MaterialRecord>(`${BASE}/materials/${materialId}`);
}

export function updateMaterial(
  materialId: string,
  payload: MaterialUpdatePayload,
): Promise<MaterialRecord> {
  return apiPatch<MaterialRecord>(`${BASE}/materials/${materialId}`, payload);
}

export function deleteMaterial(materialId: string): Promise<void> {
  return apiDelete(`${BASE}/materials/${materialId}`);
}

export function reviewMaterial(
  materialId: string,
  payload: MaterialReviewPayload,
): Promise<MaterialRecord> {
  return apiPost<MaterialRecord>(`${BASE}/materials/${materialId}/review`, payload);
}

// ── Pillar 2: Test results (ISO/IEC 17025 lab) ──────────────────────────────

export type TestStatus = 'draft' | 'recorded' | 'void';

export interface TestResult {
  id: string;
  project_id: string;
  result_number: string;
  title: string;
  description: string | null;
  material_record_id: string | null;
  inspection_id: string | null;
  criterion_id: string | null;
  sample_id: string | null;
  test_method: string | null;
  lab_name: string | null;
  lab_accreditation: string | null;
  is_accredited: boolean;
  measured_value: string | null;
  unit: string | null;
  specimen_age_days: number | null;
  status: TestStatus;
  result: ResultDecision | null;
  result_notes: string | null;
  raised_ncr_id: string | null;
  sampled_at: string | null;
  tested_at: string | null;
  performed_by: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  elements: ElementRef[];
}

export interface TestResultCreatePayload {
  project_id: string;
  title: string;
  description?: string | null;
  material_record_id?: string | null;
  inspection_id?: string | null;
  criterion_id?: string | null;
  sample_id?: string | null;
  test_method?: string | null;
  lab_name?: string | null;
  lab_accreditation?: string | null;
  is_accredited?: boolean;
  measured_value?: string | null;
  unit?: string | null;
  specimen_age_days?: number | null;
  sampled_at?: string | null;
  element?: ElementRefIn | null;
  metadata?: Record<string, unknown>;
}

export type TestResultUpdatePayload = Partial<Omit<TestResultCreatePayload, 'project_id' | 'element'>> & {
  status?: TestStatus;
};

export interface TestResultRecordPayload {
  result: ResultDecision;
  measured_value?: string | null;
  notes?: string | null;
  tested_at?: string | null;
  ncr_severity?: NcrSeverity | null;
}

export function listTestResults(
  projectId: string,
  opts: {
    status?: TestStatus;
    result?: ResultDecision;
    material_record_id?: string;
    offset?: number;
    limit?: number;
  } = {},
): Promise<TestResult[]> {
  return apiGet<TestResult[]>(
    `${BASE}/test-results${qs({
      project_id: projectId,
      status: opts.status,
      result: opts.result,
      material_record_id: opts.material_record_id,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createTestResult(payload: TestResultCreatePayload): Promise<TestResult> {
  return apiPost<TestResult>(`${BASE}/test-results`, payload);
}

export function getTestResult(resultId: string): Promise<TestResult> {
  return apiGet<TestResult>(`${BASE}/test-results/${resultId}`);
}

export function updateTestResult(
  resultId: string,
  payload: TestResultUpdatePayload,
): Promise<TestResult> {
  return apiPatch<TestResult>(`${BASE}/test-results/${resultId}`, payload);
}

export function deleteTestResult(resultId: string): Promise<void> {
  return apiDelete(`${BASE}/test-results/${resultId}`);
}

/** Record a test outcome. A fail (or conditional) raises a linked NCR. */
export function recordTestResult(
  resultId: string,
  payload: TestResultRecordPayload,
): Promise<TestResult> {
  return apiPost<TestResult>(`${BASE}/test-results/${resultId}/record-result`, payload);
}

// ── Pillar 3: As-built records ──────────────────────────────────────────────

export type CaptureMethod =
  | 'laser_scan'
  | 'photogrammetry'
  | 'total_station'
  | 'gnss'
  | 'tape'
  | 'drone_lidar'
  | 'model_extract'
  | 'manual';
export type AccuracyClass = 'survey' | 'standard' | 'coarse';
export type SourceKind =
  | 'pointcloud_scan'
  | 'pointcloud_registration'
  | 'takeoff_measurement'
  | 'cde_document'
  | 'manual';
export type AsBuiltStatus = 'draft' | 'surveyed' | 'verified' | 'recorded' | 'superseded' | 'void';
export type ToleranceResult = 'within' | 'out_of_tolerance' | 'not_assessed';

export interface AsBuiltRecord {
  id: string;
  project_id: string;
  record_number: string;
  title: string;
  discipline: string | null;
  location_description: string | null;
  capture_method: CaptureMethod;
  instrument: string | null;
  instrument_calibration_ref: string | null;
  accuracy_class: AccuracyClass;
  accuracy_value: string | null;
  accuracy_unit: string | null;
  coordinate_system: string | null;
  survey_date: string | null;
  surveyed_by: string | null;
  criterion_id: string | null;
  measured_value: string | null;
  deviation_value: string | null;
  tolerance_result: ToleranceResult | null;
  valid_for_legal_record: boolean;
  validity_signed_by: string | null;
  validity_signed_at: string | null;
  validity_signature_ip: string | null;
  validity_signature_sha256: string | null;
  source_kind: SourceKind;
  source_ref: string | null;
  deviation_map_uri: string | null;
  status: AsBuiltStatus;
  raised_ncr_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  elements: ElementRef[];
}

export interface AsBuiltCreatePayload {
  project_id: string;
  title: string;
  discipline?: string | null;
  location_description?: string | null;
  capture_method?: CaptureMethod;
  instrument?: string | null;
  instrument_calibration_ref?: string | null;
  accuracy_class?: AccuracyClass;
  accuracy_value?: string | null;
  accuracy_unit?: string | null;
  coordinate_system?: string | null;
  survey_date?: string | null;
  surveyed_by?: string | null;
  criterion_id?: string | null;
  measured_value?: string | null;
  source_kind?: SourceKind;
  source_ref?: string | null;
  deviation_map_uri?: string | null;
  element?: ElementRefIn | null;
  metadata?: Record<string, unknown>;
}

export type AsBuiltUpdatePayload = Partial<Omit<AsBuiltCreatePayload, 'project_id' | 'element'>> & {
  status?: 'draft' | 'surveyed' | 'verified' | 'superseded';
};

export interface AsBuiltImportFromScanPayload {
  project_id: string;
  registration_id: string;
  title: string;
  discipline?: string | null;
  criterion_id?: string | null;
  metadata?: Record<string, unknown>;
}

export interface AsBuiltSurveyPayload {
  measured_value?: string | null;
  deviation_value?: string | null;
  accuracy_value?: string | null;
  accuracy_unit?: string | null;
  survey_date?: string | null;
  notes?: string | null;
}

export interface AsBuiltVerifyPayload {
  notes?: string | null;
  ncr_severity?: NcrSeverity | null;
}

export interface AsBuiltSignPayload {
  valid?: boolean;
  notes?: string | null;
  signed_at?: string | null;
}

export function listAsBuilt(
  projectId: string,
  opts: {
    status?: AsBuiltStatus;
    discipline?: string;
    source_kind?: SourceKind;
    offset?: number;
    limit?: number;
  } = {},
): Promise<AsBuiltRecord[]> {
  return apiGet<AsBuiltRecord[]>(
    `${BASE}/asbuilt${qs({
      project_id: projectId,
      status: opts.status,
      discipline: opts.discipline,
      source_kind: opts.source_kind,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createAsBuilt(payload: AsBuiltCreatePayload): Promise<AsBuiltRecord> {
  return apiPost<AsBuiltRecord>(`${BASE}/asbuilt`, payload);
}

export function importAsBuiltFromScan(
  payload: AsBuiltImportFromScanPayload,
): Promise<AsBuiltRecord> {
  return apiPost<AsBuiltRecord>(`${BASE}/asbuilt/import-from-scan`, payload);
}

export function getAsBuilt(recordId: string): Promise<AsBuiltRecord> {
  return apiGet<AsBuiltRecord>(`${BASE}/asbuilt/${recordId}`);
}

export function updateAsBuilt(
  recordId: string,
  payload: AsBuiltUpdatePayload,
): Promise<AsBuiltRecord> {
  return apiPatch<AsBuiltRecord>(`${BASE}/asbuilt/${recordId}`, payload);
}

export function deleteAsBuilt(recordId: string): Promise<void> {
  return apiDelete(`${BASE}/asbuilt/${recordId}`);
}

/** Record the captured value and compute the tolerance result. */
export function recordAsBuiltSurvey(
  recordId: string,
  payload: AsBuiltSurveyPayload,
): Promise<AsBuiltRecord> {
  return apiPost<AsBuiltRecord>(`${BASE}/asbuilt/${recordId}/record-survey`, payload);
}

/** Verify a surveyed as-built. An out-of-tolerance record raises a workmanship NCR. */
export function verifyAsBuilt(
  recordId: string,
  payload: AsBuiltVerifyPayload,
): Promise<AsBuiltRecord> {
  return apiPost<AsBuiltRecord>(`${BASE}/asbuilt/${recordId}/verify`, payload);
}

/** E-sign the legal-record attestation. Only a verified record can be signed valid. */
export function signAsBuiltValidity(
  recordId: string,
  payload: AsBuiltSignPayload,
): Promise<AsBuiltRecord> {
  return apiPost<AsBuiltRecord>(`${BASE}/asbuilt/${recordId}/sign-validity`, payload);
}

// ── Pillar 5: Hold / witness / surveillance / review gates ───────────────────

export type PointType = 'hold' | 'witness' | 'surveillance' | 'review';
export type GateAttachedKind = 'activity' | 'handover_package' | 'inspection';
export type GateStatus = 'pending' | 'released' | 'waived' | 'void';

export interface HoldGate {
  id: string;
  project_id: string;
  gate_number: string;
  point_type: PointType;
  title: string;
  description: string | null;
  required_party_role: PartyRole;
  inspection_id: string | null;
  criterion_id: string | null;
  attached_kind: GateAttachedKind | null;
  attached_id: string | null;
  blocks_progress: boolean;
  status: GateStatus;
  released_by: string | null;
  released_party_role: string | null;
  released_at: string | null;
  release_justification: string | null;
  release_signature_ip: string | null;
  release_signature_sha256: string | null;
  waived_by: string | null;
  waived_reason: string | null;
  approval_instance_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface GateCreatePayload {
  project_id: string;
  point_type?: PointType;
  title: string;
  description?: string | null;
  required_party_role?: PartyRole;
  inspection_id?: string | null;
  criterion_id?: string | null;
  attached_kind?: GateAttachedKind | null;
  attached_id?: string | null;
  blocks_progress?: boolean | null;
  metadata?: Record<string, unknown>;
}

export type GateUpdatePayload = Partial<Omit<GateCreatePayload, 'project_id'>>;

export interface GateReleasePayload {
  party_role: PartyRole;
  justification?: string | null;
  released_at?: string | null;
}

export interface GateWaivePayload {
  reason: string;
}

export interface GateProceedResponse {
  project_id: string;
  attached_kind: string;
  attached_id: string;
  can_proceed: boolean;
  blocking_gate_numbers: string[];
  blocking_gate_ids: string[];
}

export function listGates(
  projectId: string,
  opts: {
    status?: GateStatus;
    point_type?: PointType;
    attached_kind?: GateAttachedKind;
    attached_id?: string;
    offset?: number;
    limit?: number;
  } = {},
): Promise<HoldGate[]> {
  return apiGet<HoldGate[]>(
    `${BASE}/gates${qs({
      project_id: projectId,
      status: opts.status,
      point_type: opts.point_type,
      attached_kind: opts.attached_kind,
      attached_id: opts.attached_id,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createGate(payload: GateCreatePayload): Promise<HoldGate> {
  return apiPost<HoldGate>(`${BASE}/gates`, payload);
}

/** Whether an attached entity (activity / handover_package / inspection) may proceed. */
export function gateCanProceed(
  projectId: string,
  kind: GateAttachedKind,
  id: string,
): Promise<GateProceedResponse> {
  return apiGet<GateProceedResponse>(
    `${BASE}/gates/can-proceed${qs({ project_id: projectId, kind, id })}`,
  );
}

export function getGate(gateId: string): Promise<HoldGate> {
  return apiGet<HoldGate>(`${BASE}/gates/${gateId}`);
}

export function updateGate(gateId: string, payload: GateUpdatePayload): Promise<HoldGate> {
  return apiPatch<HoldGate>(`${BASE}/gates/${gateId}`, payload);
}

export function deleteGate(gateId: string): Promise<void> {
  return apiDelete(`${BASE}/gates/${gateId}`);
}

/** Release a gate. The asserted party role must satisfy the gate's required role. */
export function releaseGate(gateId: string, payload: GateReleasePayload): Promise<HoldGate> {
  return apiPost<HoldGate>(`${BASE}/gates/${gateId}/release`, payload);
}

/** Waive a gate. Only witness / surveillance / review gates may be waived. */
export function waiveGate(gateId: string, payload: GateWaivePayload): Promise<HoldGate> {
  return apiPost<HoldGate>(`${BASE}/gates/${gateId}/waive`, payload);
}

// ── Pillar 4: Handover / acceptance packages ────────────────────────────────

export type CompletionRegime = 'taking_over' | 'substantial' | 'practical';
export type CompletionType = 'whole' | 'sectional' | 'partial';
export type HandoverStatus = 'draft' | 'assembling' | 'ready' | 'issued' | 'revoked';
export type GatingState = 'blocked' | 'clear' | 'overridden';

export interface HandoverPackage {
  id: string;
  project_id: string;
  package_number: string;
  title: string;
  completion_regime: CompletionRegime;
  completion_type: CompletionType;
  section_ref: string | null;
  status: HandoverStatus;
  gating_state: GatingState;
  open_ncr_count: number;
  unreleased_hold_count: number;
  completeness_pct: number;
  gating_override_by: string | null;
  gating_override_reason: string | null;
  certificate_no: string | null;
  issued_at: string | null;
  issued_by: string | null;
  issue_signature_ip: string | null;
  issue_signature_sha256: string | null;
  closeout_package_id: string | null;
  dossier_key: string | null;
  dossier_built_at: string | null;
  assembled_at: string | null;
  approval_instance_id: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
  elements: ElementRef[];
}

export interface HandoverGateReport {
  package_id: string;
  project_id: string;
  gating_state: GatingState;
  can_issue: boolean;
  open_ncr_count: number;
  unreleased_hold_count: number;
  completeness_pct: number;
  blocking_gate_numbers: string[];
}

export interface HandoverCreatePayload {
  project_id: string;
  title: string;
  completion_regime?: CompletionRegime;
  completion_type?: CompletionType;
  section_ref?: string | null;
  element?: ElementRefIn | null;
  metadata?: Record<string, unknown>;
}

export interface HandoverUpdatePayload {
  title?: string;
  completion_regime?: CompletionRegime;
  completion_type?: CompletionType;
  section_ref?: string | null;
  certificate_no?: string | null;
  metadata?: Record<string, unknown>;
}

export interface HandoverOverridePayload {
  reason: string;
  ncr_severity?: NcrSeverity | null;
}

export interface HandoverIssuePayload {
  certificate_no?: string | null;
  notes?: string | null;
  issued_at?: string | null;
}

export function listHandoverPackages(
  projectId: string,
  opts: {
    status?: HandoverStatus;
    completion_regime?: CompletionRegime;
    completion_type?: CompletionType;
    offset?: number;
    limit?: number;
  } = {},
): Promise<HandoverPackage[]> {
  return apiGet<HandoverPackage[]>(
    `${BASE}/handover${qs({
      project_id: projectId,
      status: opts.status,
      completion_regime: opts.completion_regime,
      completion_type: opts.completion_type,
      offset: opts.offset ?? 0,
      limit: opts.limit ?? LIST_LIMIT,
    })}`,
  );
}

export function createHandoverPackage(payload: HandoverCreatePayload): Promise<HandoverPackage> {
  return apiPost<HandoverPackage>(`${BASE}/handover`, payload);
}

export function getHandoverPackage(packageId: string): Promise<HandoverPackage> {
  return apiGet<HandoverPackage>(`${BASE}/handover/${packageId}`);
}

export function updateHandoverPackage(
  packageId: string,
  payload: HandoverUpdatePayload,
): Promise<HandoverPackage> {
  return apiPatch<HandoverPackage>(`${BASE}/handover/${packageId}`, payload);
}

export function deleteHandoverPackage(packageId: string): Promise<void> {
  return apiDelete(`${BASE}/handover/${packageId}`);
}

/** The computed completion gate: open NCRs + unreleased hold gates on the project. */
export function getHandoverGates(packageId: string): Promise<HandoverGateReport> {
  return apiGet<HandoverGateReport>(`${BASE}/handover/${packageId}/gates`);
}

/** Auto-assemble the acceptance-evidence manifest and recompute the gate. */
export function assembleHandoverPackage(packageId: string): Promise<HandoverPackage> {
  return apiPost<HandoverPackage>(`${BASE}/handover/${packageId}/assemble`, {});
}

/** Override a blocked completion gate (manager only; recorded as a documentation NCR). */
export function overrideHandoverGate(
  packageId: string,
  payload: HandoverOverridePayload,
): Promise<HandoverPackage> {
  return apiPost<HandoverPackage>(`${BASE}/handover/${packageId}/override-gate`, payload);
}

/** E-sign and issue the acceptance certificate. Refused unless the gate is clear or overridden. */
export function issueHandoverCertificate(
  packageId: string,
  payload: HandoverIssuePayload,
): Promise<HandoverPackage> {
  return apiPost<HandoverPackage>(`${BASE}/handover/${packageId}/issue`, payload);
}

/** Revoke an issued acceptance certificate. */
export function revokeHandoverPackage(packageId: string): Promise<HandoverPackage> {
  return apiPost<HandoverPackage>(`${BASE}/handover/${packageId}/revoke`, {});
}
