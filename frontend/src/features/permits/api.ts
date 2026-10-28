// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for permits: the permit roadmap, applications with their
// decision clock, decisions, permits in force and the conditions they carry.
//
// Backend module: backend/app/modules/permits/router.py, mounted at
// /api/v1/permits/. Every project route lives under /projects/{project_id}/.
//
// Errors arrive as `detail = {code, message_key, message, violations?, info?}`.
// The screens read `code` to explain a refusal in the reader's language and
// fall back to `getErrorMessage` for everything else.

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

/** What the caller may do with a record: the guard of the write, run dry by the server. */
export interface CanFlag {
  allowed: boolean;
  /** False when the action makes no sense for the record as it stands; the button is then left out. */
  applies?: boolean;
  /** The refusal code the write would answer with. */
  reason: string | null;
  change_request_required?: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/** A label as the catalogue store sends it: a message key for shipped items, texts per locale for tenant ones. */
export interface PermitLabel {
  key: string | null;
  text: Record<string, string> | null;
}

export type ApplicantRole = 'owner' | 'designer' | 'contractor' | 'operator';
export type RequirementState =
  | 'not_started'
  | 'in_progress'
  | 'granted'
  | 'partially_granted'
  | 'refused'
  | 'blocked'
  | 'not_applicable'
  | 'not_in_force';
export type ApplicationState =
  | 'planned'
  | 'preparing'
  | 'internal_review'
  | 'submitted'
  | 'validated'
  | 'under_review'
  | 'info_requested'
  | 'decided'
  | 'withdrawn';
export type ApplicationTarget = Exclude<ApplicationState, 'planned' | 'decided'>;
export type ApplicationKind =
  | 'new'
  | 'variation'
  | 'amendment_non_material'
  | 'extension_of_validity'
  | 'discharge_of_conditions'
  | 'early_start';
export type Outcome =
  | 'granted'
  | 'granted_with_conditions'
  | 'partially_granted'
  | 'refused'
  | 'deemed_granted'
  | 'withdrawn';
export type PermitState = 'in_force' | 'suspended' | 'lapsed' | 'revoked' | 'superseded' | 'expired';
export type PermitTarget = 'suspended' | 'in_force' | 'revoked' | 'expired' | 'lapsed';
export type PermitScope = 'full' | 'partial' | 'preliminary' | 'early_start';
export type ConditionState =
  | 'open'
  | 'evidence_submitted'
  | 'discharge_applied'
  | 'discharged'
  | 'in_compliance'
  | 'breach'
  | 'not_triggered'
  | 'waived'
  | 'superseded';
export type ConditionKind =
  | 'suspensive'
  | 'obligation'
  | 'time_limit'
  | 'revocation_reserve'
  | 'reserved_obligation'
  | 'information';
export type Trigger =
  | 'before_application_x'
  | 'before_start'
  | 'before_stage'
  | 'before_occupation'
  | 'ongoing'
  | 'by_date'
  | 'on_event'
  | 'after_completion';
export type Topic =
  | 'hse'
  | 'environment'
  | 'noise'
  | 'traffic'
  | 'heritage'
  | 'structural'
  | 'fire'
  | 'drainage'
  | 'ecology'
  | 'design'
  | 'admin'
  | 'other';
/** What an obligation of an early start secures; empty for every other condition. */
export type ConditionPurpose = '' | 'restoration' | 'security';
export type ConditionView = 'before_start' | 'before_occupation' | 'ongoing_hse' | 'overdue' | 'mine';
export type ClockEventKind = 'stop' | 'resume' | 'extension_agreed' | 'extension_by_authority';
export type ClockUnit = 'calendar_days' | 'working_days' | 'weeks' | 'months' | 'years';
export type EvidenceKind =
  | 'cde_revision'
  | 'inspection'
  | 'commissioning_item'
  | 'report'
  | 'photo'
  | 'external_url'
  | 'discharge_decision';
/** The modes a user records by hand; authority and deemed discharge come only from a decided application. */
export type DischargeMode = 'self_certified' | 'not_triggered' | 'waived_by_authority';
export type AnyDischargeMode = DischargeMode | 'authority_discharged' | 'deemed_discharged';
export type DependencyOn = 'granted' | 'submitted';
export type ReadinessGate = 'start' | 'handover' | 'roadmap' | 'register';
export type ReadinessStatus = 'ready' | 'at_risk' | 'not_ready' | 'no_roadmap';
export type ExportRegister = 'roadmap' | 'conditions' | 'permits';

export interface CatalogueSummary {
  kind: string;
  source: 'shipped' | 'tenant';
  id: string;
  code: string;
  name: PermitLabel;
  state: string;
  versions: number[];
  latest_version: number | null;
  review_status?: string;
  jurisdiction?: string | null;
  extends?: string | null;
}

/** One permit type of a catalogue, as far as the roadmap screens read it. */
export interface CatalogueType {
  code: string;
  name_key: string;
  labels: Record<string, string> | null;
  category: string;
  scope: PermitScope;
  default_applicant_role: ApplicantRole;
}

export interface CatalogueBody {
  id: string;
  version: number;
  permit_types: CatalogueType[];
}

export interface Roadmap {
  can?: RoadmapCan;
  /** False when the project has no phase model: no gate agrees the roadmap and no frame document hosts it. */
  gates_in_use?: boolean;
  /** Approved change requests a structural change already used up; each covers one change. */
  consumed_change_request_ids?: string[];
  id: string;
  project_id: string;
  catalogue_source: 'shipped' | 'tenant';
  catalogue_id: string;
  catalogue_version: number;
  jurisdiction: string | null;
  route_assessment_id: string | null;
  delivery_model_id: string | null;
  governance_document_id: string | null;
  /** `draft`, or `agreed` once the roadmap frame document is binding: structure then changes through a change request. */
  state: string;
  roadmap_area_code: string | null;
  conditions_area_code: string | null;
  internal_review: boolean;
  approval_route_id: string | null;
  escalation_days: number;
  buffer_days: number;
}

export interface RoadmapInput {
  catalogue_source?: 'shipped' | 'tenant';
  catalogue_id?: string;
  catalogue_version?: number;
  jurisdiction?: string;
  internal_review?: boolean;
  escalation_days?: number;
  buffer_days?: number;
}

export interface Dependency {
  id: string;
  on: DependencyOn;
}

export interface Requirement {
  id: string;
  project_id: string;
  permit_type_code: string;
  title: string;
  applicable: boolean;
  applicability_rationale: string;
  applicant_role: ApplicantRole | null;
  applicant_source: string;
  applicant_rationale: string;
  applicant_party: string;
  applicant_contact_id: string | null;
  responsible_user_id: string | null;
  planned_submit_date: string | null;
  needed_by_activity_id: string | null;
  needed_by_date: string | null;
  clock_variant: string;
  expected_decision_date: string | null;
  schedule_activity_id: string | null;
  governance_area_code: string | null;
  conflict_accepted: boolean;
  follow_up_of_id: string | null;
  proposed_from_route: boolean;
  sort_order: number;
}

/** A roadmap row as the list sends it: the requirement plus what the server derived for it. */
export interface RequirementRow extends Requirement {
  can?: RequirementCan;
  state: RequirementState | null;
  category: string | null;
  name_key: string | null;
  depends_on: Dependency[];
}

export interface RequirementInput {
  permit_type_code?: string;
  title?: string;
  applicable?: boolean;
  applicability_rationale?: string;
  applicant_role?: ApplicantRole | null;
  applicant_rationale?: string;
  applicant_party?: string;
  responsible_user_id?: string | null;
  planned_submit_date?: string | null;
  needed_by_date?: string | null;
  expected_decision_date?: string | null;
  conflict_accepted?: boolean;
  /** On a binding roadmap: the approved change request a structural change uses up. */
  change_request_id?: string;
}

export interface ClockExtension {
  period: number;
  unit: ClockUnit;
  kind: ClockEventKind;
}

export interface Clock {
  start: string | null;
  base_due: string | null;
  forecast: string | null;
  /** Why there is no forecast: `no_statutory_period`, `clock_not_started`. */
  reason: string | null;
  stopped_days: number;
  stopped_now: boolean;
  extensions: ClockExtension[];
  estimate: boolean;
  deemed_proposal: 'deemed_granted' | 'deemed_discharged' | null;
  deemed_requires_notice: boolean;
  period: number | null;
  unit: ClockUnit | null;
  start_event: string | null;
}

export interface TimelineRow {
  requirement_id: string;
  needed_by: string | null;
  date_basis: string | null;
  latest_decision: string | null;
  latest_submit: string | null;
  forecast_decision: string | null;
  forecast_reason: string | null;
  schedule_conflict: boolean;
  conflict_days: number | null;
  conflict_accepted: boolean;
  derived_from: string | null;
  state: RequirementState | null;
  estimate: boolean;
  clock: Clock | null;
}

export interface Application {
  can?: ApplicationCan;
  id: string;
  requirement_id: string;
  attempt: number;
  kind: ApplicationKind;
  parent_permit_id: string | null;
  discharges_condition_ids: string[];
  authority_name: string;
  authority_reference: string;
  submitted_at: string | null;
  received_at: string | null;
  validated_at: string | null;
  review_cycle_ids: string[];
  submission_id: string | null;
  cde_container_id: string | null;
  approval_instance_id: string | null;
  state: ApplicationState;
  appeal_note: string;
  applicant_role?: ApplicantRole | null;
  applicant_source?: string;
}

export interface ClockEvent {
  id: string;
  application_id: string;
  kind: ClockEventKind;
  at: string | null;
  period: number | null;
  unit: ClockUnit | null;
  reason: string;
}

export interface Decision {
  can?: DecisionCan;
  id: string;
  application_id: string;
  revision: number;
  supersedes_id: string | null;
  outcome: Outcome;
  decision_date: string | null;
  served_date: string | null;
  reference: string;
  scope_note: string;
  scope_activity_ids: string[];
  conditions_pending: boolean;
  appeal_deadline: string | null;
  document_revision_id: string | null;
  content_hash: string;
  deemed: boolean;
  decided_by: string | null;
}

export interface ApplicationDetail extends Application {
  clock: Clock;
  clock_events: ClockEvent[];
  decisions: Decision[];
  /** The states the server lets this application move to now. Recording a decision is not among them. */
  allowed_targets: ApplicationTarget[];
}

export interface ApplicationInput {
  requirement_id: string;
  kind: ApplicationKind;
  parent_permit_id?: string | null;
  discharges_condition_ids?: string[];
  authority_name: string;
  authority_reference: string;
}

export interface ApplicationPatch {
  authority_name?: string;
  authority_reference?: string;
  received_at?: string | null;
  validated_at?: string | null;
  appeal_note?: string;
}

export interface ClockEventInput {
  kind: ClockEventKind;
  at: string;
  period?: number;
  unit?: ClockUnit;
  reason: string;
}

export interface ConditionInput {
  number: string;
  text: string;
  kind: ConditionKind;
  trigger: Trigger | '';
  stage_ref: string;
  event_text: string;
  due_date: string | null;
  topic: Topic;
  purpose: ConditionPurpose;
  owner_user_id: string | null;
  responsible_party: string;
  requires_authority_approval: boolean;
  evidence_required: string;
}

export interface DecisionInput {
  outcome: Outcome;
  decision_date: string;
  served_date?: string | null;
  reference: string;
  scope_note: string;
  conditions: ConditionInput[];
  conditions_pending: boolean;
  appeal_deadline?: string | null;
  document_revision_id?: string | null;
  security_amount?: string | null;
  security_currency?: string;
  /** On a discharge application: the conditions the authority discharged, when not all of them. */
  discharged_condition_ids?: string[] | null;
  /** On a variation: the numbers of the conditions the new decision drops. */
  removed_condition_numbers?: string[];
}

export interface DecisionCorrection {
  reason: string;
  decision_date?: string;
  served_date?: string | null;
  reference?: string;
  scope_note?: string;
  appeal_deadline?: string | null;
  document_revision_id?: string | null;
}

export interface FrameDocumentResult {
  /** Named by the project's governance model, not by this module. */
  doc_type: string;
  register: ExportRegister;
  governance_document_id: string;
  container_id: string;
  revision_id: string;
  content_hash: string;
}

/** A change request of a governance frame document, as far as the roadmap dialogs read it. */
export interface FrameChangeRequest {
  id: string;
  document_id: string;
  reason: string;
  status: string;
  decided_at: string | null;
}

export interface LapseWarning {
  /** `d90`, `d30`, `d7` before the lapse date, `lapsed` after it. */
  level: string;
  days: number;
}

export interface Permit {
  id: string;
  requirement_id: string;
  application_id: string;
  decision_id: string;
  permit_type_code: string;
  scope: PermitScope;
  state: PermitState;
  reference: string;
  revocable: boolean;
  security_amount: string | null;
  security_currency: string;
  start_notified_at: string | null;
  /** The day work stopped, while it is interrupted; a long interruption can make the permit lapse. */
  paused_since?: string | null;
  valid_until: string | null;
  superseded_by_id: string | null;
  lapse_warning?: LapseWarning | null;
  can?: PermitCan;
}

export interface RoadmapCan {
  edit?: CanFlag;
  add_requirement?: CanFlag;
  accept_proposals?: CanFlag;
  escalate?: CanFlag;
  publish_frame_document?: CanFlag;
}

export interface RequirementCan {
  edit?: CanFlag;
  manage_fields?: CanFlag;
  delete?: CanFlag;
  set_dependencies?: CanFlag;
  create_application?: CanFlag;
  push_milestone?: CanFlag;
}

export interface ApplicationCan {
  edit?: CanFlag;
  clock?: CanFlag;
  decide?: CanFlag;
  transition?: Partial<Record<ApplicationTarget, CanFlag>>;
}

export interface DecisionCan {
  correct?: CanFlag;
  complete_register?: CanFlag;
}

export interface ConditionCan {
  edit?: CanFlag;
  manage_fields?: CanFlag;
  assign?: CanFlag;
  add_evidence?: CanFlag;
  remove_evidence?: CanFlag;
  submit_evidence?: CanFlag;
  breach?: CanFlag;
  in_compliance?: CanFlag;
  confirm?: CanFlag;
  link_requirement?: CanFlag;
  discharge?: DischargeCan;
}

export interface PermitCan {
  start?: CanFlag;
  interrupt?: CanFlag;
  resume?: CanFlag;
  transition?: Partial<Record<PermitTarget, CanFlag>>;
  add_condition?: CanFlag;
  propose_conditions?: CanFlag;
}

export interface DecisionResult {
  decision: Decision;
  permit: Permit | null;
  follow_up_requirement: Requirement | null;
  next: string[];
}

export interface Condition {
  id: string;
  permit_id: string;
  number: string;
  text: string;
  kind: ConditionKind;
  national_kind: string;
  trigger: Trigger | '';
  stage_ref: string;
  event_text: string;
  due_date: string | null;
  topic: Topic;
  purpose: ConditionPurpose;
  owner_user_id: string | null;
  responsible_party: string;
  requires_authority_approval: boolean;
  evidence_required: string;
  requirement_id: string | null;
  hse_relevant: boolean;
  state: ConditionState;
  /** `manual` for a typed condition, anything else for a proposal read out of the notice. */
  source: string;
  confidence: string | null;
  /** Where the condition stands in the notice: a page or a clause. */
  text_span: string;
  /** The sentence quoted from the notice; empty unless it really occurs in the document. */
  passage?: string;
  confirmed: boolean;
  gate_condition_id: string | null;
  original_id: string | null;
  breach_ref_kind: string;
  breach_ref_id: string | null;
  breach_note: string;
  evidence_submitted_by?: string | null;
  can?: ConditionCan;
}

export interface ConditionRow extends Condition {
  permit_reference: string;
  permit_type_code: string;
  overdue: boolean;
  breach_risk: boolean;
  evidence_count: number;
}

export interface Evidence {
  id: string;
  condition_id: string;
  kind: EvidenceKind;
  ref_id: string;
  /** The linked document and its revision, named by the server when it can resolve them. */
  ref_title?: string | null;
  ref_revision?: string | null;
  content_hash: string;
  note: string;
  added_by: string | null;
  added_at: string | null;
}

export interface Discharge {
  id: string;
  condition_id: string;
  mode: AnyDischargeMode;
  decided_by: string | null;
  discharge_application_id: string | null;
  verifier_user_id: string | null;
  date: string | null;
  document_revision_id: string | null;
  note: string;
  carried_from_id?: string | null;
}

/** Whether the reader may close the condition in one way, and the refusal code when not. */
export interface DischargeGate {
  allowed: boolean;
  /** False when this way of closing is not for the condition as it stands; it is then not offered. */
  applies?: boolean;
  reason: string | null;
}

export type DischargeCan = Partial<Record<DischargeMode, DischargeGate>>;

export interface ConditionDetail extends Condition {
  evidence: Evidence[];
  discharges: Discharge[];
}

export interface ReadinessItem {
  code: string;
  /** `warning` is a note that never changes the status: a permit needed only after the date checked. */
  state: 'met' | 'not_met' | 'at_risk' | 'warning';
  /** The condition number or the roadmap row title the item is about. */
  detail: string;
  ref: string | null;
  /** Only on `permit_due_later`: the permit and the day it is needed, apart, so the date reads in the reader's format. */
  title?: string;
  needed_by?: string;
}

export interface Readiness {
  gate: string;
  status: ReadinessStatus;
  items: ReadinessItem[];
  /** The day the start check was made for: the target date of the gate into construction, when it has one. */
  needed_from?: string | null;
}

export interface Finding {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface Proposal {
  permit_type_code: string;
  name_key: string | null;
  category: string;
  applicant_role: ApplicantRole;
  applicant_source: string;
  already_present: boolean;
  requires: Array<{ code: string; on: string }>;
}

export interface ProposeResult {
  route: string;
  route_assessment_id: string;
  proposals: Proposal[];
  /** Why nothing is proposed: `route_exempt`, `route_undetermined`, `no_types_for_route`. */
  reason?: string;
}

export interface EscalateResult {
  notified: string[];
  escalated: string[];
  /** Due for escalation, but the area has no owner yet; the server retries. */
  unescalated?: string[];
  lapsed: string[];
}

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
}

function errorDetail(err: unknown): ErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as ErrorDetail) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function permitErrorCode(err: unknown): string | null {
  const code = errorDetail(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the backend sent with the code, already in the request language. */
export function permitErrorMessage(err: unknown): string | null {
  const message = errorDetail(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const permitKeys = {
  all: ['permits'] as const,
  catalogues: ['permits', 'catalogues'] as const,
  catalogue: (id: string) => ['permits', 'catalogues', id] as const,
  project: (projectId: string) => ['permits', projectId] as const,
  roadmap: (projectId: string) => ['permits', projectId, 'roadmap'] as const,
  requirements: (projectId: string) => ['permits', projectId, 'requirements'] as const,
  timeline: (projectId: string) => ['permits', projectId, 'timeline'] as const,
  applications: (projectId: string) => ['permits', projectId, 'applications'] as const,
  application: (projectId: string, id: string) => ['permits', projectId, 'application', id] as const,
  permits: (projectId: string) => ['permits', projectId, 'permits'] as const,
  conditions: (projectId: string) => ['permits', projectId, 'conditions'] as const,
  condition: (projectId: string, id: string) => ['permits', projectId, 'condition', id] as const,
  readiness: (projectId: string, gate: string) => ['permits', projectId, 'readiness', gate] as const,
  validation: (projectId: string) => ['permits', projectId, 'validation'] as const,
};

/* ── Catalogues and roadmap ───────────────────────────────────────────── */

export function listCatalogues(): Promise<Page<CatalogueSummary>> {
  return apiGet<Page<CatalogueSummary>>(`/v1/permits/catalogues`);
}

/** A shipped catalogue with its parent chain resolved, so it lists every permit type it offers. */
export function getShippedCatalogue(catalogueId: string): Promise<CatalogueBody> {
  return apiGet<CatalogueBody>(`/v1/permits/catalogues/shipped/${catalogueId}`);
}

export function getRoadmap(projectId: string): Promise<Roadmap> {
  return apiGet<Roadmap>(`/v1/permits/projects/${projectId}/roadmap`);
}

export function setRoadmap(projectId: string, body: RoadmapInput): Promise<Roadmap> {
  return apiPut<Roadmap>(`/v1/permits/projects/${projectId}/roadmap`, body);
}

export function proposeRequirements(projectId: string): Promise<ProposeResult> {
  return apiPost<ProposeResult>(`/v1/permits/projects/${projectId}/roadmap/propose`, {});
}

export function acceptProposals(
  projectId: string,
  body: { permit_type_codes: string[]; route_assessment_id?: string; change_request_id?: string },
): Promise<Page<Requirement>> {
  return apiPost<Page<Requirement>>(`/v1/permits/projects/${projectId}/roadmap/accept`, body);
}

/** The change requests of the project's governance documents; the roadmap dialogs offer the approved ones. */
export function listFrameChangeRequests(projectId: string): Promise<Page<FrameChangeRequest>> {
  return apiGet<Page<FrameChangeRequest>>(`/v1/project-governance/projects/${projectId}/change-requests`);
}

/* ── Requirements and timeline ────────────────────────────────────────── */

export function listRequirements(projectId: string): Promise<Page<RequirementRow>> {
  return apiGet<Page<RequirementRow>>(`/v1/permits/projects/${projectId}/requirements`);
}

export function createRequirement(projectId: string, body: RequirementInput): Promise<Requirement> {
  return apiPost<Requirement>(`/v1/permits/projects/${projectId}/requirements`, body);
}

export function updateRequirement(projectId: string, id: string, body: RequirementInput): Promise<Requirement> {
  return apiPatch<Requirement>(`/v1/permits/projects/${projectId}/requirements/${id}`, body);
}

export function deleteRequirement(projectId: string, id: string, changeRequestId?: string): Promise<void> {
  const qs = changeRequestId ? `?change_request_id=${changeRequestId}` : '';
  return apiDelete<void>(`/v1/permits/projects/${projectId}/requirements/${id}${qs}`);
}

export function setDependencies(
  projectId: string,
  id: string,
  dependencies: Array<{ depends_on_id: string; on: DependencyOn }>,
  changeRequestId?: string,
): Promise<Page<Dependency>> {
  return apiPut<Page<Dependency>>(`/v1/permits/projects/${projectId}/requirements/${id}/dependencies`, {
    dependencies,
    ...(changeRequestId ? { change_request_id: changeRequestId } : {}),
  });
}

export function pushMilestone(projectId: string, id: string): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/v1/permits/projects/${projectId}/requirements/${id}/push-milestone`, {});
}

export function getTimeline(projectId: string): Promise<Page<TimelineRow>> {
  return apiGet<Page<TimelineRow>>(`/v1/permits/projects/${projectId}/timeline?today=${localToday()}`);
}

/* ── Applications, clock and decisions ────────────────────────────────── */

export function listApplications(projectId: string): Promise<Page<Application>> {
  return apiGet<Page<Application>>(`/v1/permits/projects/${projectId}/applications`);
}

export function createApplication(projectId: string, body: ApplicationInput): Promise<Application> {
  return apiPost<Application>(`/v1/permits/projects/${projectId}/applications`, body);
}

export function getApplication(projectId: string, id: string): Promise<ApplicationDetail> {
  return apiGet<ApplicationDetail>(`/v1/permits/projects/${projectId}/applications/${id}?today=${localToday()}`);
}

export function updateApplication(projectId: string, id: string, body: ApplicationPatch): Promise<Application> {
  return apiPatch<Application>(`/v1/permits/projects/${projectId}/applications/${id}`, body);
}

export function transitionApplication(
  projectId: string,
  id: string,
  body: { target: ApplicationTarget; on_date?: string | null; reason: string },
): Promise<Application> {
  return apiPost<Application>(`/v1/permits/projects/${projectId}/applications/${id}/transition`, body);
}

export function addClockEvent(projectId: string, id: string, body: ClockEventInput): Promise<ClockEvent> {
  return apiPost<ClockEvent>(`/v1/permits/projects/${projectId}/applications/${id}/clock-events`, body);
}

export function recordDecision(projectId: string, id: string, body: DecisionInput): Promise<DecisionResult> {
  return apiPost<DecisionResult>(`/v1/permits/projects/${projectId}/applications/${id}/decision`, body);
}

export function completeRegister(projectId: string, decisionId: string): Promise<Decision> {
  return apiPost<Decision>(`/v1/permits/projects/${projectId}/decisions/${decisionId}/complete-register`, {});
}

/** A new revision of a decision with corrected facts. The outcome itself cannot be corrected. */
export function correctDecision(projectId: string, decisionId: string, body: DecisionCorrection): Promise<Decision> {
  return apiPost<Decision>(`/v1/permits/projects/${projectId}/decisions/${decisionId}/correct`, body);
}

/* ── Permits ──────────────────────────────────────────────────────────── */

export function listPermits(projectId: string): Promise<Page<Permit>> {
  return apiGet<Page<Permit>>(`/v1/permits/projects/${projectId}/permits?today=${localToday()}`);
}

export function notifyStart(projectId: string, permitId: string, onDate: string): Promise<Permit> {
  return apiPost<Permit>(`/v1/permits/projects/${projectId}/permits/${permitId}/start-notice`, { on_date: onDate });
}

export function recordInterruption(projectId: string, permitId: string, onDate: string): Promise<Permit> {
  return apiPost<Permit>(`/v1/permits/projects/${projectId}/permits/${permitId}/interruption`, { on_date: onDate });
}

export function recordResumption(projectId: string, permitId: string, onDate: string): Promise<Permit> {
  return apiPost<Permit>(`/v1/permits/projects/${projectId}/permits/${permitId}/resumption`, { on_date: onDate });
}

export function transitionPermit(
  projectId: string,
  permitId: string,
  body: { target: PermitTarget; reason: string },
): Promise<Permit> {
  return apiPost<Permit>(`/v1/permits/projects/${projectId}/permits/${permitId}/transition`, body);
}

export function createCondition(projectId: string, permitId: string, body: ConditionInput): Promise<Condition> {
  return apiPost<Condition>(`/v1/permits/projects/${projectId}/permits/${permitId}/conditions`, body);
}

/* ── Conditions ───────────────────────────────────────────────────────── */

export function listConditions(projectId: string): Promise<Page<ConditionRow>> {
  return apiGet<Page<ConditionRow>>(`/v1/permits/projects/${projectId}/conditions?include_proposals=true&today=${localToday()}`);
}

export function getCondition(projectId: string, id: string): Promise<ConditionDetail> {
  return apiGet<ConditionDetail>(`/v1/permits/projects/${projectId}/conditions/${id}`);
}

export function updateCondition(projectId: string, id: string, body: Partial<ConditionInput>): Promise<Condition> {
  return apiPatch<Condition>(`/v1/permits/projects/${projectId}/conditions/${id}`, body);
}

export function assignOwner(projectId: string, conditionIds: string[], ownerUserId: string): Promise<Page<Condition>> {
  return apiPost<Page<Condition>>(`/v1/permits/projects/${projectId}/conditions/assign`, {
    condition_ids: conditionIds,
    owner_user_id: ownerUserId,
  });
}

export function addEvidence(
  projectId: string,
  id: string,
  body: { kind: EvidenceKind; ref_id: string; note: string },
): Promise<Evidence> {
  return apiPost<Evidence>(`/v1/permits/projects/${projectId}/conditions/${id}/evidence`, body);
}

export function removeEvidence(projectId: string, id: string, evidenceId: string): Promise<void> {
  return apiDelete<void>(`/v1/permits/projects/${projectId}/conditions/${id}/evidence/${evidenceId}`);
}

export function submitEvidence(projectId: string, id: string): Promise<Condition> {
  return apiPost<Condition>(`/v1/permits/projects/${projectId}/conditions/${id}/submit-evidence`, {});
}

export function dischargeCondition(
  projectId: string,
  id: string,
  body: { mode: DischargeMode; on_date?: string | null; document_revision_id?: string | null; note: string },
): Promise<Discharge> {
  return apiPost<Discharge>(`/v1/permits/projects/${projectId}/conditions/${id}/discharge`, body);
}

export function raiseBreach(projectId: string, id: string, note: string): Promise<Condition> {
  return apiPost<Condition>(`/v1/permits/projects/${projectId}/conditions/${id}/breach`, { ref_kind: 'manual', note });
}

export function markInCompliance(projectId: string, id: string, note: string): Promise<Condition> {
  return apiPost<Condition>(`/v1/permits/projects/${projectId}/conditions/${id}/in-compliance`, { note });
}

export function confirmProposal(
  projectId: string,
  id: string,
  accept: boolean,
): Promise<{ condition: Condition | null; accepted: boolean }> {
  return apiPost<{ condition: Condition | null; accepted: boolean }>(`/v1/permits/projects/${projectId}/conditions/${id}/confirm`, {
    accept,
  });
}

/** What reading a notice answered: the proposals stored, and what was left out and why. */
export interface ExtractResult extends Page<Condition> {
  already_known: number;
  rejected: number;
  document_cut: boolean;
}

/** Read the conditions out of the permit's decision notice; they are stored as unconfirmed proposals. */
export function extractConditions(projectId: string, permitId: string): Promise<ExtractResult> {
  return apiPost<ExtractResult>(`/v1/permits/projects/${projectId}/permits/${permitId}/condition-proposals/extract`, {});
}

export function conditionToRequirement(
  projectId: string,
  id: string,
  body: { entity: string; attribute: string; constraint_type: string; constraint_value: string; unit: string },
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/v1/permits/projects/${projectId}/conditions/${id}/requirement`, body);
}

export function escalateConditions(projectId: string): Promise<EscalateResult> {
  return apiPost<EscalateResult>(`/v1/permits/projects/${projectId}/conditions/escalate`, {});
}

/* ── Read side ────────────────────────────────────────────────────────── */

export function getReadiness(projectId: string, gate: ReadinessGate): Promise<Readiness> {
  return apiGet<Readiness>(`/v1/permits/projects/${projectId}/readiness?gate=${gate}&today=${localToday()}`);
}

export function getValidation(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/permits/projects/${projectId}/validation?today=${localToday()}`);
}

/** File the register as a new revision of its governance frame document. */
export function publishFrameDocument(projectId: string, register: ExportRegister): Promise<FrameDocumentResult> {
  return apiPost<FrameDocumentResult>(`/v1/permits/projects/${projectId}/frame-document/publish?register=${register}`, {});
}

export function downloadRegister(projectId: string, register: ExportRegister, format: 'pdf' | 'xlsx'): Promise<void> {
  return downloadWithAuth(
    `/api/v1/permits/projects/${projectId}/export?register=${register}&format=${format}&today=${localToday()}`,
    `permits_${register}.${format}`,
  );
}
