// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for Project governance: phases, gates, frame documents and
// area owners.
//
// Backend module: backend/app/modules/project_governance/router.py, mounted at
// /api/v1/project-governance/. Every project route lives under
// /projects/{project_id}/ there, so the module never adds a top-level segment.
//
// Errors arrive as `detail = {code, message_key, message, violations?}`. The
// screens read `code` to explain a refusal (four-eyes, missing owner, not
// entitled) and fall back to `getErrorMessage` for everything else.

import { ApiError, apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';

/** A label as the API sends it: a message key for shipped items, texts per locale for tenant ones. */
export interface GovernanceLabel {
  key: string | null;
  text: Record<string, string> | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type GateStatus = 'not_started' | 'in_preparation' | 'in_review' | 'on_hold' | 'decided';
export type Outcome = 'go' | 'go_with_conditions' | 'hold' | 'recycle' | 'stop';
export type CheckStatus = 'not_assessed' | 'ready' | 'ready_with_risks' | 'not_ready' | 'not_applicable';
export type Rag = '' | 'red' | 'amber' | 'green';
export type DocumentStatus = 'draft' | 'in_review' | 'approved_at_gate' | 'binding' | 'superseded';
export type ConditionStatus = 'open' | 'cleared' | 'waived' | 'overdue';
export type Severity = 'critical' | 'essential' | 'recommended';
export type ChangeRequestStatus = 'submitted' | 'approved' | 'rejected' | 'cancelled';
/** A `warning` never blocks a gate, and a passing decision has to name it as it names an unknown item. */
export type EvidenceState = 'met' | 'not_met' | 'unknown' | 'warning';

/** Where a catalogue comes from: the platform, the organisation, or the active pack. */
export type CatalogueSource = 'shipped' | 'tenant' | 'pack';

export interface CatalogueSummary {
  kind: string;
  source: CatalogueSource;
  /** The pack a `pack` item comes from. */
  pack?: string;
  /** True on the one catalogue a new project of the asked country should start with. */
  default?: boolean;
  id: string;
  code: string;
  name: GovernanceLabel;
  state: string;
  versions: number[];
  latest_version: number | null;
  based_on?: string;
  review_status: string;
  jurisdiction_countries: string[];
  /** Only on a catalogue read in full; the phase mapping step offers a choice when it is there. */
  phases?: GovernancePhase[];
}

export interface GovernancePhase {
  code: string;
  order: number;
  spine_key?: string;
  name: GovernanceLabel;
}

export interface GovernanceModel {
  id: string;
  project_id: string;
  catalogue_source: CatalogueSource;
  catalogue_id: string;
  catalogue_version: number;
  current_phase: string | null;
  four_eyes: boolean;
  decision_route_id: string | null;
  change_route_id: string | null;
  stopped: boolean;
  stopped_at: string | null;
  phases: GovernancePhase[];
  /** What the caller may do on the model, decided by the server. Writes on areas and documents carry flags of their own. */
  can: { manage: boolean };
}

export interface GovernanceArea {
  id: string;
  code: string;
  name_override: string;
  sort_order: number;
  owner_user_id: string | null;
  deputy_user_id: string | null;
  applicable: boolean;
  na_rationale: string;
  retired: boolean;
  /** The area's label when the server sends one; the catalogue key names it otherwise. */
  name?: GovernanceLabel;
  /** The catalogue's frame document types for this area; `tracked` says which ones the project already holds. */
  document_types?: AreaDocumentType[];
  /** Whether the reader may track a further frame document in this area. */
  can?: { add_document: boolean; add_document_reason?: string | null };
}

export interface AreaDocumentType {
  code: string;
  name?: GovernanceLabel | null;
  required_at_gates: string[];
  /** True when the project already holds a document of this type in the area. */
  tracked: boolean;
}

export interface GovernanceGate {
  id: string;
  code: string;
  catalogue_id: string;
  from_phase: string;
  to_phase: string;
  sort_order: number;
  status: GateStatus;
  attempt_no: number;
  target_date: string;
  schedule_activity_id: string | null;
  approval_instance_id: string | null;
  hold_resume_date: string;
  last_outcome: Outcome | '';
  historic: boolean;
  version: number;
  name?: GovernanceLabel;
}

export interface Violation {
  code: string;
  message_key: string;
  message?: string;
  area_code: string | null;
  document_type: string | null;
  ref: string | null;
}

export interface EvidenceItem {
  code: string;
  state: EvidenceState;
  label: GovernanceLabel;
  /** `href` is a path of the web app the owning module registered for the kind, or null when none did. */
  link: { kind: string; id: string; href?: string | null } | null;
  detail: string;
  provider: string;
  blocking: boolean;
  error: boolean;
  /** Unknown evidence of a blocking provider: a go has to name it. */
  needs_acknowledgement?: boolean;
}

/** One evidence item by the pair the server matches on. */
export interface EvidenceRef {
  area_code: string;
  code: string;
}

export interface GateCheck {
  status: CheckStatus;
  rag: Rag;
  note: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  stale: boolean;
  na_rationale: string;
  criteria?: Record<string, { met: boolean; note?: string; by?: string | null; at?: string | null }>;
}

/** One readiness criterion of an area on a gate, with the owner's tick. Who and when come from the server. */
export interface GateCriterion {
  code: string;
  name: GovernanceLabel;
  met: boolean;
  note: string;
  ticked_by: string | null;
  ticked_at: string | null;
}

export interface GateAreaDocument {
  document_id: string;
  doc_type: string;
  status: DocumentStatus;
  required: boolean;
  container_id: string | null;
  revision_in_force: string | null;
  pending_revision: string | null;
  read_only: boolean;
  name?: GovernanceLabel;
}

export interface GateArea {
  area_id: string;
  code: string;
  owner_user_id: string | null;
  deputy_user_id: string | null;
  applicable: boolean;
  check: GateCheck | null;
  evidence: EvidenceItem[];
  documents: GateAreaDocument[];
  /** The model's criteria for this gate and area in catalogue order; empty when it defines none. */
  criteria?: GateCriterion[];
  /** Whether the caller may tick the criteria: owner or deputy, on a gate that is neither decided nor historic. */
  can_tick?: boolean;
  name?: GovernanceLabel;
}

export interface DecisionSnapshot {
  gate_code?: string;
  decider_id?: string;
  four_eyes?: boolean;
  today?: string;
  areas?: Array<{ code: string; owner_user_id: string | null; applicable: boolean; na_rationale?: string }>;
  documents?: Array<{
    document_id: string;
    area_code: string;
    doc_type: string;
    status: string;
    revision_id: string | null;
    content_hash: string | null;
    required: boolean;
  }>;
  checks?: Array<{ area_code: string; status: string; rag?: string; stale?: boolean }>;
  /** The unknown evidence the decider named when the decision was taken. */
  acknowledged_evidence?: Array<EvidenceRef & { provider?: string; state?: 'unknown' | 'warning' }>;
  [key: string]: unknown;
}

export interface GateDecision {
  id: string;
  gate_id: string;
  gate_code: string;
  attempt_no: number;
  outcome: Outcome;
  rationale: string;
  decided_by: string;
  decided_at: string;
  snapshot: DecisionSnapshot;
  proceed_at_risk_areas: string[];
  accepted_not_applicable: string[];
  hold_resume_date: string;
  approval_instance_id: string | null;
}

export interface GateDetail {
  gate: GovernanceGate;
  blockers: Violation[];
  areas: GateArea[];
  decisions: GateDecision[];
  /**
   * What the caller may do on this gate, decided by the server through the same
   * check that enforces a decision (route entitlement, four-eyes, gate state).
   * `decide` says whether any outcome is open to the caller; `outcomes` answers
   * for each one. `go` probes a plain go, so `go_reason` also names the first
   * readiness blocker. A `*_reason` is a refusal code when its flag is false.
   */
  can: GateCan;
}

/** Whether one decision outcome is open to the caller, and the refusal code when it is not. */
export interface OutcomeFlag {
  allowed: boolean;
  reason?: string | null;
}

export interface GateCan {
  edit: boolean;
  decide: boolean;
  decide_reason?: string | null;
  go?: boolean;
  go_reason?: string | null;
  outcomes?: Partial<Record<Outcome, OutcomeFlag>>;
  resume?: boolean;
  resume_reason?: string | null;
  reopen?: boolean;
  reopen_reason?: string | null;
  add_condition?: boolean;
  add_condition_reason?: string | null;
  /**
   * The unknown evidence a go or a go with conditions has to name, exactly as the
   * request sends it back. Empty when nothing is pending. It is content of the
   * request, so `go` stays open while this list is not empty.
   */
  acknowledge?: Array<EvidenceRef & { provider: string; state?: 'unknown' | 'warning' }>;
}

export interface MatrixCellOut {
  check_status: CheckStatus | null;
  rag: Rag;
  stale: boolean;
  documents: Array<{
    document_id: string;
    doc_type: string;
    status: DocumentStatus;
    required: boolean;
    name?: GovernanceLabel;
  }>;
}

export interface MatrixArea {
  area_id: string;
  code: string;
  name: GovernanceLabel | null;
  name_override: string;
  owner_user_id: string | null;
  deputy_user_id: string | null;
  applicable: boolean;
  /** Keyed by gate code. */
  cells: Record<string, MatrixCellOut>;
}

export interface MatrixResponse {
  gates: GovernanceGate[];
  next_gate: { id: string; code: string; status: GateStatus; blocker_count: number } | null;
  areas: MatrixArea[];
}

export interface ConditionInput {
  area_code?: string | null;
  document_type?: string | null;
  text: string;
  owner_user_id?: string | null;
  due_date?: string | null;
  severity: Severity;
}

export interface DecisionInput {
  outcome: Outcome;
  rationale: string;
  conditions: ConditionInput[];
  proceed_at_risk_areas: string[];
  accepted_not_applicable: string[];
  hold_resume_date?: string | null;
  acknowledged_evidence?: EvidenceRef[];
}

export interface FrameDocument {
  id: string;
  area_id: string;
  doc_type: string;
  required_at_gates: string[];
  status: DocumentStatus;
  container_id: string | null;
  bound_revision_id: string | null;
  bound_content_hash: string | null;
  approved_gate_id: string | null;
  read_only: boolean;
  name?: GovernanceLabel;
  /** What the caller may do with this document, decided by the server. Absent when the server does not report it. */
  can?: DocumentCan;
}

export interface DocumentCan {
  attach: boolean;
  attach_reason?: string | null;
  submit: boolean;
  submit_reason?: string | null;
  return: boolean;
  return_reason?: string | null;
  /** Whether the reader may raise a change request on this document. */
  change_request?: boolean;
  change_request_reason?: string | null;
}

export interface DocumentRevision {
  id: string;
  revision_code: string;
  revision_number: number;
  content_hash: string;
  file_name: string;
  created_at: string | null;
  in_force: boolean;
}

export interface ChangeRequest {
  id: string;
  document_id: string;
  previous_revision_id: string | null;
  proposed_revision_id: string;
  proposed_content_hash: string | null;
  reason: string;
  impact: string;
  status: ChangeRequestStatus;
  approval_instance_id: string | null;
  requested_by: string | null;
  decided_by: string | null;
  decided_at: string | null;
  created_at: string | null;
}

export interface DocumentHistory {
  document_id: string;
  revisions: DocumentRevision[];
  change_requests: ChangeRequest[];
}

export interface GovernanceCondition {
  id: string;
  decision_id: string;
  gate_id: string;
  gate_code: string;
  area_code: string | null;
  document_type: string | null;
  text: string;
  owner_user_id: string | null;
  due_date: string;
  severity: Severity;
  status: ConditionStatus;
  evidence: string;
  cleared_by: string | null;
  cleared_at: string | null;
  waiver_rationale: string;
  waived_by: string | null;
  waived_at: string | null;
  escalated_at: string | null;
  /** What the caller may do with this condition, decided by the server. */
  can: ConditionCan;
}

export interface ConditionCan {
  clear: boolean;
  clear_reason?: string | null;
  waive: boolean;
  waive_reason?: string | null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function governanceErrorCode(err: unknown): string | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
    const code = (detail as { code?: unknown }).code;
    return typeof code === 'string' ? code : null;
  }
  return null;
}

/**
 * Whether the reader may set the first model, as the `model_missing` answer
 * says it. Null when the answer is something else or carries no flag.
 */
export function missingModelCanManage(err: unknown): boolean | null {
  if (governanceErrorCode(err) !== 'model_missing') return null;
  const detail = ((err as ApiError).body as { detail?: { can?: { manage?: unknown } } }).detail;
  const manage = detail?.can?.manage;
  return typeof manage === 'boolean' ? manage : null;
}

/** The blockers a 422 refusal listed, so the dialog can show all of them, not only the first. */
export function governanceViolations(err: unknown): Violation[] {
  if (!(err instanceof ApiError)) return [];
  const body = err.body as { detail?: { violations?: unknown } } | null;
  const list = body?.detail && typeof body.detail === 'object' ? body.detail.violations : null;
  return Array.isArray(list) ? (list as Violation[]) : [];
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const governanceKeys = {
  all: ['project-governance'] as const,
  project: (projectId: string) => ['project-governance', projectId] as const,
  model: (projectId: string) => ['project-governance', projectId, 'model'] as const,
  areas: (projectId: string) => ['project-governance', projectId, 'areas'] as const,
  gates: (projectId: string) => ['project-governance', projectId, 'gates'] as const,
  matrix: (projectId: string) => ['project-governance', projectId, 'matrix'] as const,
  gate: (projectId: string, gateId: string) => ['project-governance', projectId, 'gate', gateId] as const,
  documents: (projectId: string) => ['project-governance', projectId, 'documents'] as const,
  history: (projectId: string, documentId: string) =>
    ['project-governance', projectId, 'history', documentId] as const,
  changeRequests: (projectId: string) => ['project-governance', projectId, 'change-requests'] as const,
  conditions: (projectId: string) => ['project-governance', projectId, 'conditions'] as const,
  containers: (projectId: string) => ['project-governance', projectId, 'containers'] as const,
  routes: (projectId: string, targetKind: string) => ['project-governance', projectId, 'routes', targetKind] as const,
  catalogues: ['project-governance', 'catalogues'] as const,
};

/* ── Catalogues and model ─────────────────────────────────────────────── */

/** The phase models on offer. With the project's country the server marks the one to start with as `default`. */
export function listCatalogues(country?: string | null): Promise<Page<CatalogueSummary>> {
  const countryQs = country ? `&country=${encodeURIComponent(country)}` : '';
  return apiGet<Page<CatalogueSummary>>(`/v1/project-governance/catalogues?kind=phase_model${countryQs}`);
}

/** The two-letter country of a project, or null when it has none. */
export function getProjectCountry(projectId: string): Promise<string | null> {
  return apiGet<{ country_code?: string | null }>(`/v1/projects/${projectId}`).then((project) => project.country_code ?? null);
}

export function getModel(projectId: string): Promise<GovernanceModel> {
  return apiGet<GovernanceModel>(`/v1/project-governance/projects/${projectId}/model`);
}

export function setModel(
  projectId: string,
  body: { catalogue_source: CatalogueSource; catalogue_id: string; catalogue_version?: number; four_eyes: boolean },
): Promise<GovernanceModel> {
  return apiPut<GovernanceModel>(`/v1/project-governance/projects/${projectId}/model`, body);
}

export function changeModel(
  projectId: string,
  body: {
    catalogue_source: CatalogueSource;
    catalogue_id: string;
    catalogue_version?: number;
    mapping: Record<string, string>;
  },
): Promise<GovernanceModel> {
  return apiPost<GovernanceModel>(`/v1/project-governance/projects/${projectId}/model/change`, body);
}

/** `decision_route_id` and `change_route_id` pin the approval routes governance runs on; null removes the pin. */
export function updateModelSettings(
  projectId: string,
  body: { four_eyes?: boolean; decision_route_id?: string | null; change_route_id?: string | null },
): Promise<GovernanceModel> {
  return apiPatch<GovernanceModel>(`/v1/project-governance/projects/${projectId}/model`, body);
}

/* ── Areas and gates ──────────────────────────────────────────────────── */

export function listAreas(projectId: string): Promise<Page<GovernanceArea>> {
  return apiGet<Page<GovernanceArea>>(`/v1/project-governance/projects/${projectId}/areas`);
}

export function updateArea(
  projectId: string,
  areaId: string,
  body: {
    owner_user_id?: string | null;
    deputy_user_id?: string | null;
    applicable?: boolean;
    na_rationale?: string;
  },
): Promise<GovernanceArea> {
  return apiPatch<GovernanceArea>(`/v1/project-governance/projects/${projectId}/areas/${areaId}`, body);
}

export function getMatrix(projectId: string): Promise<MatrixResponse> {
  return apiGet<MatrixResponse>(`/v1/project-governance/projects/${projectId}/matrix?today=${localToday()}`);
}

export function getGate(projectId: string, gateId: string): Promise<GateDetail> {
  return apiGet<GateDetail>(`/v1/project-governance/projects/${projectId}/gates/${gateId}?today=${localToday()}`);
}

export function prepareGate(projectId: string, gateId: string): Promise<GovernanceGate> {
  return apiPost<GovernanceGate>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/prepare`, {});
}

export function submitGate(projectId: string, gateId: string): Promise<GovernanceGate> {
  return apiPost<GovernanceGate>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/submit`, {});
}

/** A decision is dated by the server. The reader's calendar day goes only on reads, never on a write. */
export function decideGate(projectId: string, gateId: string, body: DecisionInput): Promise<GateDecision> {
  return apiPost<GateDecision>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/decide`, body);
}

/** The server decides whether the phase goes back: it does exactly when the reopened decision had advanced it. */
export function reopenGate(projectId: string, gateId: string, body: { rationale: string }): Promise<GovernanceGate> {
  return apiPost<GovernanceGate>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/reopen`, body);
}

export function resumeGate(projectId: string, gateId: string): Promise<GovernanceGate> {
  return apiPost<GovernanceGate>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/resume`, {});
}

export function confirmCheck(
  projectId: string,
  gateId: string,
  areaId: string,
  body: { status: Exclude<CheckStatus, 'not_applicable'>; rag: Rag; note: string },
): Promise<GateCheck> {
  return apiPut<GateCheck>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/checks/${areaId}`, body);
}

/** Ticks or unticks one readiness criterion. Area owner or deputy only. */
export function setCriterion(
  projectId: string,
  gateId: string,
  areaId: string,
  code: string,
  body: { met: boolean; note?: string },
): Promise<GateCheck> {
  return apiPut<GateCheck>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/checks/${areaId}/criteria/${code}`, body);
}

export function markCheckNotApplicable(
  projectId: string,
  gateId: string,
  areaId: string,
  rationale: string,
): Promise<GateCheck> {
  return apiPost<GateCheck>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/checks/${areaId}/not-applicable`, { rationale });
}

/* ── Documents and change requests ────────────────────────────────────── */

export function listDocuments(projectId: string): Promise<Page<FrameDocument>> {
  return apiGet<Page<FrameDocument>>(`/v1/project-governance/projects/${projectId}/documents`);
}

export function getDocumentHistory(projectId: string, documentId: string): Promise<DocumentHistory> {
  return apiGet<DocumentHistory>(`/v1/project-governance/projects/${projectId}/documents/${documentId}/history`);
}

export function createDocument(
  projectId: string,
  body: { area_id: string; doc_type: string },
): Promise<FrameDocument> {
  return apiPost<FrameDocument>(`/v1/project-governance/projects/${projectId}/documents`, body);
}

export function attachDocument(projectId: string, documentId: string, containerId: string): Promise<FrameDocument> {
  return apiPost<FrameDocument>(`/v1/project-governance/projects/${projectId}/documents/${documentId}/attach`, { container_id: containerId });
}

export function returnDocument(projectId: string, documentId: string): Promise<FrameDocument> {
  return apiPost<FrameDocument>(`/v1/project-governance/projects/${projectId}/documents/${documentId}/return`, {});
}

export function submitDocument(projectId: string, documentId: string): Promise<FrameDocument> {
  return apiPost<FrameDocument>(`/v1/project-governance/projects/${projectId}/documents/${documentId}/submit`, {});
}

export function createChangeRequest(
  projectId: string,
  documentId: string,
  body: { reason: string; impact: string },
): Promise<ChangeRequest> {
  return apiPost<ChangeRequest>(`/v1/project-governance/projects/${projectId}/documents/${documentId}/change-requests`, body);
}

export function listChangeRequests(projectId: string): Promise<Page<ChangeRequest>> {
  return apiGet<Page<ChangeRequest>>(`/v1/project-governance/projects/${projectId}/change-requests`);
}

/* ── Conditions ───────────────────────────────────────────────────────── */

export function listConditions(projectId: string): Promise<Page<GovernanceCondition>> {
  return apiGet<Page<GovernanceCondition>>(`/v1/project-governance/projects/${projectId}/conditions?limit=500`);
}

/** A further condition on a gate already decided as go with conditions. */
export function addGateCondition(projectId: string, gateId: string, body: ConditionInput): Promise<GovernanceCondition> {
  return apiPost<GovernanceCondition>(`/v1/project-governance/projects/${projectId}/gates/${gateId}/conditions`, body);
}

export function clearCondition(projectId: string, conditionId: string, evidence: string): Promise<GovernanceCondition> {
  return apiPost<GovernanceCondition>(`/v1/project-governance/projects/${projectId}/conditions/${conditionId}/clear`, { evidence });
}

export function waiveCondition(projectId: string, conditionId: string, rationale: string): Promise<GovernanceCondition> {
  return apiPost<GovernanceCondition>(`/v1/project-governance/projects/${projectId}/conditions/${conditionId}/waive`, { rationale });
}
