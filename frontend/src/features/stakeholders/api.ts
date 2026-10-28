// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for Stakeholders: the register, the analysis, the communication
// plan, commitments, and the project organisation with its mandates.
//
// Backend module: backend/app/modules/stakeholders/router.py, mounted at
// /api/v1/stakeholders/. Every project route lives under
// /projects/{project_id}/ there; the organisation routes sit one level deeper
// under /organisation/.
//
// Errors arrive as `detail = {code, message_key, message, violations?}`. The
// screens read `code` to tell an empty state from a failure and show the
// server's `message` as the reason of a refused action.

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

/* ── Framework (the pinned catalogue body) ────────────────────────────── */

/** A catalogue item: shipped items carry a message key, tenant items carry texts per locale. */
export interface FrameworkItem {
  code: string;
  name_key: string;
  labels: Record<string, string> | null;
}

export interface FrameworkCategory extends FrameworkItem {
  kind: 'internal' | 'external';
  private_person: boolean;
}

export interface Dimension extends FrameworkItem {
  type: 'int' | 'bool';
  min: number;
  max: number;
}

export interface RuleCondition {
  gte: number | null;
  lte: number | null;
  eq: boolean | null;
}

export interface ClassRule {
  when: Record<string, RuleCondition>;
  classification: string;
}

export interface AnalysisMethod extends FrameworkItem {
  version: number;
  dimensions: Dimension[];
  classes: FrameworkItem[];
  rules: ClassRule[];
  default: string | null;
}

export interface OrderedLevel extends FrameworkItem {
  order: number;
  promise_key?: string;
}

export interface StatutoryRef {
  jurisdiction: string;
  ref: string;
  url: string;
  review_status: string;
}

export interface ParticipationFormat extends FrameworkItem {
  default_level: string;
  default_channels: string[];
  statutory_refs: StatutoryRef[];
}

export interface FrameworkRole extends FrameworkItem {
  holder_kind: 'person' | 'organisation';
  multi: boolean;
  required: boolean;
}

export interface BodyType extends FrameworkItem {
  default_decision_level: number;
}

export interface DecisionType extends FrameworkItem {
  commitment_type: string | null;
  approval_target_kind: string | null;
  required: boolean;
  forbid_self_approval: boolean;
}

export interface Framework {
  id: string;
  version: number;
  name_key: string;
  labels: Record<string, string> | null;
  review_status: string;
  default_method: string;
  feedback_due_days: number;
  stakeholder_categories: FrameworkCategory[];
  analysis_methods: AnalysisMethod[];
  engagement_levels: OrderedLevel[];
  participation_levels: OrderedLevel[];
  channels: FrameworkItem[];
  participation_formats: ParticipationFormat[];
  roles: FrameworkRole[];
  body_types: BodyType[];
  decision_types: DecisionType[];
}

/** A framework as the catalogue list names it, before its body is loaded. */
export interface FrameworkSummary {
  kind: string;
  source: 'shipped' | 'tenant';
  id: string;
  code: string;
  name: { key: string | null; text: Record<string, string> | null };
  state: string;
  latest_version: number | null;
  review_status: string;
  jurisdiction_countries: string[];
}

export interface StakeholderSettings {
  id: string;
  project_id: string;
  framework_source: 'shipped' | 'tenant';
  framework_id: string;
  framework_version: number;
  analysis_method: string;
  review_interval_days: number;
  owner_area_code: string;
  commitment_route_id: string | null;
  framework: Framework;
  /** What the caller may do on this project, decided by the server. */
  can: { edit: boolean; read_personal: boolean; manage_organisation: boolean };
  /** Whether each document can be filed for the gate: not at all on a project without gates, or not now, with the reason. */
  can_file: Record<ExportDocument, FilePermission>;
}

export interface FilePermission {
  /** False when the project has no frame documents; the filing action is then not shown. */
  applies: boolean;
  allowed: boolean;
  reason: string | null;
}

export interface SettingsInput {
  framework_source?: 'shipped' | 'tenant';
  framework_id?: string;
  analysis_method?: string;
  review_interval_days?: number;
}

/* ── Register and analysis ────────────────────────────────────────────── */

export type StakeholderStatus = 'active' | 'dormant' | 'archived';

export interface Stakeholder {
  id: string;
  project_id: string;
  code: string;
  display_name: string;
  /** Null with `masked` for a private person the caller may not name. */
  name: string | null;
  masked: boolean;
  anonymised: boolean;
  category: string;
  contact_id: string | null;
  is_group: boolean;
  group_size_estimate: number | null;
  /** The group or organisation this stakeholder belongs to. */
  parent_stakeholder_id: string | null;
  interests: string;
  expectations: string;
  concerns: string;
  relationship_owner_user_id: string | null;
  /** Where the stakeholder sits, for neighbours. Null on a masked row, whatever is stored. */
  geo: Record<string, string> | null;
  is_confidential: boolean;
  status: StakeholderStatus;
  /** The risk register entry that follows this stakeholder. */
  risk_id: string | null;
  classification: string;
  method_code: string;
  engagement_current: string | null;
  engagement_desired: string | null;
  engagement_gap: number | null;
  attitude: number | null;
  last_assessed_at: string | null;
  review_due: boolean;
  external: boolean;
  open_commitments: number;
}

export interface StakeholderInput {
  display_name?: string;
  category?: string;
  contact_id?: string | null;
  is_group?: boolean;
  group_size_estimate?: number | null;
  interests?: string;
  expectations?: string;
  concerns?: string;
  relationship_owner_user_id?: string | null;
  is_confidential?: boolean;
  status?: StakeholderStatus;
  parent_stakeholder_id?: string | null;
  geo?: Record<string, string> | null;
  risk_id?: string | null;
}

export type Scores = Record<string, number | boolean>;

export interface Assessment {
  id: string;
  stakeholder_id: string;
  method_code: string;
  method_version: number;
  scores: Scores;
  classification: string;
  engagement_current: string | null;
  engagement_desired: string | null;
  attitude: number | null;
  rationale: string;
  assessed_by: string | null;
  assessed_at: string | null;
}

export interface AssessmentInput {
  method_code: string;
  scores: Scores;
  engagement_current: string | null;
  engagement_desired: string | null;
  attitude: number | null;
  rationale: string;
}

export interface GridItem {
  stakeholder_id: string;
  code: string;
  name: string | null;
  masked: boolean;
  anonymised: boolean;
  category: string;
  classification: string;
  position: { x?: number; y?: number; x_dim?: string; y_dim?: string; sets?: string[] } | null;
  scores: Scores | null;
  assessment_id: string | null;
}

export interface GridResponse {
  method_code: string;
  method_version: number;
  dimensions: Dimension[];
  classes: FrameworkItem[];
  items: GridItem[];
}

/* ── Communication plan and events ────────────────────────────────────── */

export type PlanStatus = 'planned' | 'active' | 'paused' | 'completed' | 'cancelled';

export interface PlanItem {
  id: string;
  title: string;
  purpose: string;
  key_message: string;
  audience_stakeholder_ids: string[];
  audience_categories: string[];
  audience_body_id: string | null;
  participation_level: string;
  channel: string;
  format_code: string | null;
  frequency: string;
  trigger_kind: 'gate' | 'event' | null;
  trigger_ref: string | null;
  owner_user_id: string | null;
  starts_on: string | null;
  ends_on: string | null;
  status: PlanStatus;
  next_due: string | null;
  overdue: boolean;
}

export interface PlanItemInput {
  title?: string;
  purpose?: string;
  key_message?: string;
  audience_stakeholder_ids?: string[];
  audience_categories?: string[];
  participation_level?: string;
  channel?: string;
  format_code?: string | null;
  frequency?: string;
  trigger_kind?: 'gate' | 'event' | null;
  trigger_ref?: string;
  owner_user_id?: string | null;
  starts_on?: string | null;
  ends_on?: string | null;
  status?: PlanStatus;
}

export interface DueOccurrence {
  plan_item_id: string;
  title: string;
  date: string;
  done: boolean;
  overdue: boolean;
  participation_level: string;
  channel: string;
  owner_user_id: string | null;
}

export type EventStatus = 'planned' | 'held' | 'cancelled';

export interface EngagementEvent {
  id: string;
  plan_item_id: string | null;
  occurrence_date: string | null;
  format_code: string | null;
  participation_level: string | null;
  title: string;
  held_on: string | null;
  location: string;
  stakeholder_ids: string[];
  attendance_count: number | null;
  outcome: string;
  feedback_summary: string;
  /** The project meeting this event was, when it was held as one. */
  meeting_id: string | null;
  /** Letters sent or received around the event. */
  correspondence_ids: string[];
  cde_container_ids: string[];
  status: EventStatus;
  feedback_not_reported: boolean;
  feedback_due_on: string | null;
}

export interface EventInput {
  occurrence_date?: string | null;
  participation_level?: string | null;
  title?: string;
  held_on?: string | null;
  location?: string;
  stakeholder_ids?: string[];
  attendance_count?: number | null;
  outcome?: string;
  feedback_summary?: string;
  meeting_id?: string | null;
  correspondence_ids?: string[];
  status?: EventStatus;
}

/* ── Commitments ──────────────────────────────────────────────────────── */

export type CommitmentStatus =
  | 'proposed'
  | 'agreed'
  | 'in_progress'
  | 'fulfilled'
  | 'verified'
  | 'withdrawn'
  | 'breached';

export type CommitmentTarget = Exclude<CommitmentStatus, 'proposed'>;

/** Whether the reader may make one move on one commitment, and the server's reason code when not. */
export interface CommitmentPermission {
  /** False when the action does not exist in this state at all; it is then not shown. */
  applies: boolean;
  allowed: boolean;
  reason: string | null;
}

export type CommitmentCan = Record<CommitmentTarget | 'edit', CommitmentPermission>;

/** Where a commitment was made. The server freezes the title and day of the source when it is recorded. */
export type CommitmentSource = 'event' | 'meeting' | 'correspondence' | 'permit_condition' | 'manual';

export interface Commitment {
  id: string;
  code: string;
  stakeholder_ids: string[];
  source_kind: CommitmentSource;
  source_ref: string;
  source_snapshot: { title?: string; date?: string | null };
  text: string;
  category: string;
  owner_user_id: string | null;
  due_date: string | null;
  verification: string;
  cost_estimate: string | null;
  currency: string;
  risk_id: string | null;
  task_id: string | null;
  requirement_id: string | null;
  release_item_id: string | null;
  status: CommitmentStatus;
  overdue: boolean;
  approval_instance_id: string | null;
  /** Set while an approval route decides the move; the status changes when it completes. */
  pending_target: CommitmentTarget | null | '';
  withdraw_rationale: string;
  breach_rationale: string;
  communicated_back_at: string | null;
  loop_not_required_rationale: string;
  /** What the reader may do with this commitment, decided by the server with the same checks as the writes. */
  can: CommitmentCan;
  warnings?: string[];
}

export interface CommitmentInput {
  stakeholder_ids?: string[];
  source_kind?: CommitmentSource;
  source_ref?: string;
  text?: string;
  category?: string;
  owner_user_id?: string | null;
  due_date?: string | null;
  verification?: string;
  cost_estimate?: string | null;
  currency?: string;
  risk_id?: string | null;
  task_id?: string | null;
  requirement_id?: string | null;
  release_item_id?: string | null;
}

export interface TransitionInput {
  target: CommitmentTarget;
  rationale: string;
  communicated_back_at?: string | null;
  loop_not_required_rationale: string;
  create_risk: boolean;
}

/* ── Readiness ────────────────────────────────────────────────────────── */

export type ReadinessCode =
  | 'register_present'
  | 'key_stakeholders_planned'
  | 'mandates_complete'
  | 'roles_filled'
  | 'commitments_tracked';

export interface ReadinessCheck {
  status: 'met' | 'not_met';
  refs?: string[];
  /** On the commitments check: the codes of open promises past their due date. They warn, they do not fail the check. */
  overdue_refs?: string[];
}

export type Readiness = Record<ReadinessCode, ReadinessCheck>;

/* ── Organisation ─────────────────────────────────────────────────────── */

export interface RoleHolder {
  id: string;
  role_code: string;
  custom_label: string;
  roster_member_id: string | null;
  holder_contact_id: string | null;
  deputy_roster_member_id: string | null;
  holder_name: string | null;
  user_id: string | null;
  valid_from: string | null;
  valid_to: string | null;
  valid_today: boolean;
  conflict_rationale: string;
}

export interface RolesView {
  roles: Array<Pick<FrameworkRole, 'code' | 'name_key' | 'holder_kind' | 'multi' | 'required'>>;
  holders: RoleHolder[];
  vacant: string[];
  vacant_required: string[];
}

export interface HolderInput {
  roster_member_id: string | null;
  holder_contact_id: string | null;
  deputy_roster_member_id: string | null;
  valid_from: string | null;
  valid_to: string | null;
  conflict_rationale: string;
}

export interface MandateConflict {
  decision_type: string;
  scope: string;
  user_id: string | null;
  letters: string[];
  roles: string[];
  severity: 'error' | 'warning';
  acknowledged: boolean;
}

/** What a write on the organisation answers besides the fresh view. */
export interface OrganisationWriteNotes {
  conflicts?: MandateConflict[];
  hints?: Array<{ code: string; area_code: string; owner_user_id: string }>;
  warnings?: string[];
}

export interface BodyMember {
  id: string;
  role_code: string | null;
  user_id: string | null;
  contact_id: string | null;
  voting: boolean;
  valid_from: string | null;
  valid_to: string | null;
  valid_today: boolean;
}

export type QuorumKind = 'min_members' | 'majority' | 'unanimous';

export interface GovernanceBody {
  id: string;
  code: string;
  body_type: string;
  name: string;
  chair_role_code: string | null;
  quorum_kind: QuorumKind;
  quorum_min: number | null;
  decision_level: number;
  members: BodyMember[];
  quorum_needed: number;
  quorum_present: number;
  inquorate: boolean;
}

export interface BodyInput {
  code?: string;
  body_type?: string;
  name?: string;
  chair_role_code?: string | null;
  quorum_kind?: QuorumKind;
  quorum_min?: number | null;
  decision_level?: number;
}

export interface MemberInput {
  role_code: string | null;
  user_id: string | null;
  contact_id: string | null;
  voting: boolean;
  valid_from: string | null;
  valid_to: string | null;
}

export type Letter = 'P' | 'D' | 'A' | 'C' | 'I';

export interface MandateRow {
  id?: string;
  decision_type: string;
  scope: string;
  holder_kind: 'role' | 'body';
  holder_code: string;
  letter: Letter;
  scope_note: string;
}

export interface MandateMatrix extends OrganisationWriteNotes {
  decision_types: DecisionType[];
  roles: string[];
  bodies: string[];
  rows: MandateRow[];
  missing: string[];
  conflicts: MandateConflict[];
}

export interface WhoDecides {
  decision_type: string;
  scope: string;
  holder_kind: 'role' | 'body' | null;
  holder_code: string | null;
  user_ids: string[];
  parties: Array<{
    user_id: string | null;
    contact_id: string | null;
    roster_member_id: string | null;
    role_code: string | null;
    voting: boolean;
    /** The roster, contact or account name of the party, when the server knows one. */
    name?: string | null;
  }>;
  quorum_needed: number | null;
  quorum_present: number | null;
  flags: string[];
  authority: {
    tier_code: string | null;
    approver_user_ids: string[];
    escalate_outside: boolean;
    amount: string;
    currency: string;
  } | null;
}

/* ── Errors ───────────────────────────────────────────────────────────── */

interface ErrorDetail {
  code?: unknown;
  message?: unknown;
  violations?: unknown;
}

function detailOf(err: unknown): ErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as ErrorDetail) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function stakeholderErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server wrote for a refusal, already in the reader's language. */
export function stakeholderErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

/** Every blocker a refused write listed (two deciders, self approval, invalid scores). */
export function stakeholderViolations(err: unknown): Array<Record<string, unknown>> {
  const list = detailOf(err)?.violations;
  return Array.isArray(list) ? (list as Array<Record<string, unknown>>) : [];
}

/**
 * The capability flags a refusal carries. The settings route sends them with
 * `settings_missing`, so the first choice of a framework can follow a flag too.
 */
export function stakeholderErrorCan(err: unknown): StakeholderSettings['can'] | null {
  const can = (detailOf(err) as unknown as { can?: unknown } | null)?.can;
  if (!can || typeof can !== 'object') return null;
  const flags = can as Record<string, unknown>;
  return { edit: flags.edit === true, read_personal: flags.read_personal === true, manage_organisation: flags.manage_organisation === true };
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const stakeholderKeys = {
  frameworks: ['stakeholders', 'frameworks'] as const,
  project: (projectId: string) => ['stakeholders', projectId] as const,
  settings: (projectId: string) => ['stakeholders', projectId, 'settings'] as const,
  register: (projectId: string) => ['stakeholders', projectId, 'register'] as const,
  assessments: (projectId: string, id: string) => ['stakeholders', projectId, 'assessments', id] as const,
  grid: (projectId: string, method: string) => ['stakeholders', projectId, 'grid', method] as const,
  plan: (projectId: string) => ['stakeholders', projectId, 'plan'] as const,
  due: (projectId: string) => ['stakeholders', projectId, 'due'] as const,
  events: (projectId: string) => ['stakeholders', projectId, 'events'] as const,
  commitments: (projectId: string) => ['stakeholders', projectId, 'commitments'] as const,
  readiness: (projectId: string) => ['stakeholders', projectId, 'readiness'] as const,
  validation: (projectId: string) => ['stakeholders', projectId, 'validation'] as const,
  roles: (projectId: string) => ['stakeholders', projectId, 'roles'] as const,
  bodies: (projectId: string) => ['stakeholders', projectId, 'bodies'] as const,
  mandates: (projectId: string) => ['stakeholders', projectId, 'mandates'] as const,
};

/* ── Settings ─────────────────────────────────────────────────────────── */

export function listFrameworks(): Promise<Page<FrameworkSummary>> {
  return apiGet<Page<FrameworkSummary>>('/v1/stakeholders/frameworks');
}

export function getSettings(projectId: string): Promise<StakeholderSettings> {
  return apiGet<StakeholderSettings>(`/v1/stakeholders/projects/${projectId}/settings`);
}

export function putSettings(projectId: string, body: SettingsInput): Promise<StakeholderSettings> {
  return apiPut<StakeholderSettings>(`/v1/stakeholders/projects/${projectId}/settings`, body);
}

/* ── Register ─────────────────────────────────────────────────────────── */

export function listStakeholders(projectId: string): Promise<Page<Stakeholder>> {
  return apiGet<Page<Stakeholder>>(`/v1/stakeholders/projects/${projectId}/stakeholders?include_archived=true&limit=1000&today=${localToday()}`);
}

/** A gate of the project's phase model. `code` is what a plan item stores as its trigger. */
export interface ProjectGate {
  code: string;
  /** Resolved for the reader's language by the server; the code when the gate has no name. */
  name: string;
  status: string;
}

export interface ProjectGateList {
  items: ProjectGate[];
  /** False for a project run without gates: nothing would ever set off a line that waits for one. */
  gates_in_use: boolean;
  /** The listened project events only a gate can cause; refused like the gate trigger on a project without gates. */
  gate_bound_event_triggers?: string[];
}

/** Empty when the project has no phase model. */
export function listGates(projectId: string): Promise<ProjectGateList> {
  return apiGet<ProjectGateList>(`/v1/stakeholders/projects/${projectId}/gates`);
}

/** A requirement of one of the project's requirement sets. */
export interface RequirementOption {
  id: string;
  set_id: string;
  set_name: string;
  entity: string;
  attribute: string;
  constraint_type: string;
  constraint_value: string;
  unit: string;
  status: string;
}

export interface RequirementOptionList {
  items: RequirementOption[];
}

export function listRequirementOptions(projectId: string): Promise<RequirementOptionList> {
  return apiGet<RequirementOptionList>(`/v1/stakeholders/projects/${projectId}/requirements`);
}

export interface ReleaseItemOption {
  id: string;
  code: string;
  title: string;
}

/** `available` is false, with a reason, while no installed module provides release items. */
export interface ReleaseItemOptionList {
  items: ReleaseItemOption[];
  available: boolean;
  reason: string | null;
}

export function listReleaseItems(projectId: string): Promise<ReleaseItemOptionList> {
  return apiGet<ReleaseItemOptionList>(`/v1/stakeholders/projects/${projectId}/release-items`);
}

/** A risk register entry, as far as a picker needs it. The risk module owns the rest. */
export interface ProjectRisk {
  id: string;
  code: string;
  title: string;
}

/** The risk module serves at most this many entries per request. */
const RISK_PAGE = 100;

export function listProjectRisks(projectId: string): Promise<Page<ProjectRisk>> {
  return apiGet<Page<ProjectRisk>>(`/v1/risk/?project_id=${projectId}&limit=${RISK_PAGE}`);
}

export function createStakeholder(projectId: string, body: StakeholderInput): Promise<Stakeholder> {
  return apiPost<Stakeholder>(`/v1/stakeholders/projects/${projectId}/stakeholders`, body);
}

export function updateStakeholder(projectId: string, id: string, body: StakeholderInput): Promise<Stakeholder> {
  return apiPatch<Stakeholder>(`/v1/stakeholders/projects/${projectId}/stakeholders/${id}`, body);
}

export function archiveStakeholder(projectId: string, id: string): Promise<{ id: string; status: string }> {
  return apiDelete<{ id: string; status: string }>(`/v1/stakeholders/projects/${projectId}/stakeholders/${id}`);
}

export function listAssessments(projectId: string, id: string): Promise<Page<Assessment>> {
  return apiGet<Page<Assessment>>(`/v1/stakeholders/projects/${projectId}/stakeholders/${id}/assessments`);
}

export function createAssessment(projectId: string, id: string, body: AssessmentInput): Promise<Assessment> {
  return apiPost<Assessment>(`/v1/stakeholders/projects/${projectId}/stakeholders/${id}/assessments`, body);
}

export function getGrid(projectId: string, method: string): Promise<GridResponse> {
  return apiGet<GridResponse>(`/v1/stakeholders/projects/${projectId}/grid?method=${encodeURIComponent(method)}&today=${localToday()}`);
}

export function getReadiness(projectId: string): Promise<Readiness> {
  return apiGet<Readiness>(`/v1/stakeholders/projects/${projectId}/readiness?today=${localToday()}`);
}

/** One result of a validation rule. The message and the suggestion arrive in the reader's language. */
export interface ValidationFinding {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export function listValidation(projectId: string): Promise<Page<ValidationFinding>> {
  return apiGet<Page<ValidationFinding>>(`/v1/stakeholders/projects/${projectId}/validation?today=${localToday()}`);
}

/* ── Plan and events ──────────────────────────────────────────────────── */

export function listPlanItems(projectId: string): Promise<Page<PlanItem>> {
  return apiGet<Page<PlanItem>>(`/v1/stakeholders/projects/${projectId}/plan-items?today=${localToday()}`);
}

export function listDue(projectId: string): Promise<Page<DueOccurrence>> {
  return apiGet<Page<DueOccurrence>>(`/v1/stakeholders/projects/${projectId}/plan-items/due?today=${localToday()}`);
}

export function createPlanItem(projectId: string, body: PlanItemInput): Promise<PlanItem> {
  return apiPost<PlanItem>(`/v1/stakeholders/projects/${projectId}/plan-items`, body);
}

export function updatePlanItem(projectId: string, id: string, body: PlanItemInput): Promise<PlanItem> {
  return apiPatch<PlanItem>(`/v1/stakeholders/projects/${projectId}/plan-items/${id}`, body);
}

export function deletePlanItem(projectId: string, id: string): Promise<void> {
  return apiDelete<void>(`/v1/stakeholders/projects/${projectId}/plan-items/${id}`);
}

export function recordOccurrence(projectId: string, planItemId: string, body: EventInput): Promise<EngagementEvent> {
  return apiPost<EngagementEvent>(`/v1/stakeholders/projects/${projectId}/plan-items/${planItemId}/record`, body);
}

export function listEvents(projectId: string): Promise<Page<EngagementEvent>> {
  return apiGet<Page<EngagementEvent>>(`/v1/stakeholders/projects/${projectId}/events?today=${localToday()}`);
}

export function createEvent(projectId: string, body: EventInput): Promise<EngagementEvent> {
  return apiPost<EngagementEvent>(`/v1/stakeholders/projects/${projectId}/events`, body);
}

export function updateEvent(projectId: string, id: string, body: EventInput): Promise<EngagementEvent> {
  return apiPatch<EngagementEvent>(`/v1/stakeholders/projects/${projectId}/events/${id}`, body);
}

export function deleteEvent(projectId: string, id: string): Promise<void> {
  return apiDelete<void>(`/v1/stakeholders/projects/${projectId}/events/${id}`);
}

/* ── Commitments ──────────────────────────────────────────────────────── */

export function listCommitments(projectId: string): Promise<Page<Commitment>> {
  return apiGet<Page<Commitment>>(`/v1/stakeholders/projects/${projectId}/commitments?today=${localToday()}`);
}

export function createCommitment(projectId: string, body: CommitmentInput): Promise<Commitment> {
  return apiPost<Commitment>(`/v1/stakeholders/projects/${projectId}/commitments`, body);
}

export function updateCommitment(projectId: string, id: string, body: CommitmentInput): Promise<Commitment> {
  return apiPatch<Commitment>(`/v1/stakeholders/projects/${projectId}/commitments/${id}`, body);
}

export function transitionCommitment(projectId: string, id: string, body: TransitionInput): Promise<Commitment> {
  return apiPost<Commitment>(`/v1/stakeholders/projects/${projectId}/commitments/${id}/transition`, body);
}

/* ── Exports ──────────────────────────────────────────────────────────── */

export type ExportDocument = 'register' | 'organisation';
export type ExportFormat = 'pdf' | 'xlsx';

export function downloadExport(projectId: string, document: ExportDocument, format: ExportFormat): Promise<void> {
  if (document === 'organisation') {
    return downloadWithAuth(
      `/api/v1/stakeholders/projects/${projectId}/organisation/export?format=${format}`,
      `project_organisation_and_mandates.${format}`,
    );
  }
  return downloadWithAuth(
    `/api/v1/stakeholders/projects/${projectId}/export?format=${format}`,
    `stakeholder_and_communication_plan.${format}`,
  );
}

/** File the export as a new CDE revision of the owner area's frame document. */
export function fileFrameDocument(
  projectId: string,
  body: { document: ExportDocument; format: ExportFormat; change_reason?: string; change_impact?: string },
): Promise<Record<string, unknown>> {
  return apiPost<Record<string, unknown>>(`/v1/stakeholders/projects/${projectId}/frame-documents/file`, body);
}

/* ── Organisation ─────────────────────────────────────────────────────── */

export function getRoles(projectId: string): Promise<RolesView> {
  return apiGet<RolesView>(`/v1/stakeholders/projects/${projectId}/organisation/roles?today=${localToday()}`);
}

export function putRoleHolders(
  projectId: string,
  roleCode: string,
  holders: HolderInput[],
  customLabel = '',
): Promise<RolesView & OrganisationWriteNotes> {
  return apiPut<RolesView & OrganisationWriteNotes>(`/v1/stakeholders/projects/${projectId}/organisation/roles/${roleCode}`, {
    holders,
    custom_label: customLabel,
  });
}

export function listBodies(projectId: string): Promise<Page<GovernanceBody>> {
  return apiGet<Page<GovernanceBody>>(`/v1/stakeholders/projects/${projectId}/organisation/bodies?today=${localToday()}`);
}

export function createBody(projectId: string, body: BodyInput): Promise<GovernanceBody> {
  return apiPost<GovernanceBody>(`/v1/stakeholders/projects/${projectId}/organisation/bodies`, body);
}

export function updateBody(projectId: string, id: string, body: BodyInput): Promise<GovernanceBody> {
  return apiPatch<GovernanceBody>(`/v1/stakeholders/projects/${projectId}/organisation/bodies/${id}`, body);
}

export function deleteBody(projectId: string, id: string): Promise<void> {
  return apiDelete<void>(`/v1/stakeholders/projects/${projectId}/organisation/bodies/${id}`);
}

export function putBodyMembers(projectId: string, id: string, members: MemberInput[]): Promise<GovernanceBody> {
  return apiPut<GovernanceBody>(`/v1/stakeholders/projects/${projectId}/organisation/bodies/${id}/members`, { members });
}

export function getMandates(projectId: string): Promise<MandateMatrix> {
  return apiGet<MandateMatrix>(`/v1/stakeholders/projects/${projectId}/organisation/mandates?today=${localToday()}`);
}

export function putMandates(projectId: string, rows: MandateRow[]): Promise<MandateMatrix> {
  return apiPut<MandateMatrix>(`/v1/stakeholders/projects/${projectId}/organisation/mandates`, {
    rows: rows.map(({ decision_type, scope, holder_kind, holder_code, letter, scope_note }) => ({
      decision_type,
      scope,
      holder_kind,
      holder_code,
      letter,
      scope_note,
    })),
  });
}

export function whoDecides(
  projectId: string,
  args: { decisionType: string; amount?: string; currency?: string },
): Promise<WhoDecides> {
  const qs = new URLSearchParams({ decision_type: args.decisionType, today: localToday() });
  if (args.amount) qs.set('amount', args.amount);
  if (args.currency) qs.set('currency', args.currency);
  return apiGet<WhoDecides>(`/v1/stakeholders/projects/${projectId}/organisation/who-decides?${qs.toString()}`);
}
