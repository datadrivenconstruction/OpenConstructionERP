// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for Design management: design setup, the work breakdown, the
// design team, the design schedule, the drawing register and its numbering,
// releases, reviews, reports and the permit package.
//
// Backend module: backend/app/modules/design_management/router.py, mounted at
// /api/v1/design-management/. Every route lives under /projects/{project_id}/.
//
// A row is its columns plus a computed `state` (the same value as `status`).
// Lists arrive as `{items, total, offset, limit}`. Errors arrive as
// `detail = {code, message_key, message, violations?, info?}`; the screens
// show the sentence for `code` and list the violations under it.

import { API_BASE, ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

/** A label as the API sends it: a message key for shipped items, texts per locale for tenant ones. */
export interface DesignLabel {
  key: string | null;
  text: Record<string, string> | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type Purpose =
  | 'for_approval'
  | 'for_review'
  | 'for_information'
  | 'for_construction'
  | 'for_tender'
  | 'for_record';
export type CdeState = 'wip' | 'shared' | 'published' | 'archived';
export type RoleState = 'planned' | 'appointed' | 'active' | 'released';
export type PartyKind =
  | 'owner'
  | 'lead_designer'
  | 'discipline_designer'
  | 'specialist'
  | 'checker'
  | 'authority'
  | 'contractor_designer';
export type ApprovalPointState = 'open' | 'in_review' | 'approved' | 'rejected';
export type ApprovalPointKind = 'owner_approval' | 'user_signoff' | 'cost_check' | 'authority' | 'internal_review';
export type DeliverableState = 'not_started' | 'in_progress' | 'issued_for_review' | 'accepted' | 'waived';
export type ReleaseState = 'draft' | 'ready' | 'issued' | 'cancelled';
export type ReviewState = 'planned' | 'open' | 'comments_closed' | 'concluded';
export type ReviewOutcome = 'accepted' | 'accepted_with_comments' | 'rework';
export type CommentState = 'open' | 'answered' | 'closed' | 'rejected';
export type CommentSeverity = 'minor' | 'major' | 'critical';
export type ReportState =
  | 'required'
  | 'commissioned'
  | 'in_progress'
  | 'submitted'
  | 'under_check'
  | 'remarks'
  | 'accepted'
  | 'rejected'
  | 'not_required';
export type IndependentCheck = 'none' | 'optional' | 'required_by_rule';
export type PermitState =
  | 'assembling'
  | 'ready'
  | 'submitted'
  | 'under_review'
  | 'remarks'
  | 'approved'
  | 'partially_approved'
  | 'refused'
  | 'withdrawn';
export type PermitItemKind = 'drawing' | 'report' | 'form';
export type WbsKind = 'location' | 'system' | 'package' | 'phase' | 'cost';
export type DistFormat = 'pdf' | 'native' | 'both';
export type ExportRegister = 'register' | 'matrix' | 'reports' | 'permit';
export type CatalogueSource = 'shipped' | 'tenant';

/* ── Catalogues ───────────────────────────────────────────────────────── */

export interface CodeListEntry {
  code: string;
  label_key: string;
  labels: Record<string, string> | null;
}

export interface NumberingField {
  code: string;
  label_key: string;
  labels: Record<string, string> | null;
  required: boolean;
  pattern: string | null;
  length_min: number | null;
  length_max: number | null;
  code_list: CodeListEntry[] | 'free';
  pad: number | null;
  source_field: string;
  joiner: string | null;
}

export interface NumberingScheme {
  id: string;
  version: number;
  name_key: string;
  labels: Record<string, string> | null;
  description_key: string;
  source_url: string | null;
  source_title: string | null;
  review_status: string;
  fields: NumberingField[];
  separator: string;
  max_length: number;
}

export interface ReportKind {
  code: string;
  name_key: string;
  labels: Record<string, string> | null;
  discipline: string;
  typical_phase: string;
  independent_check: IndependentCheck;
}

export interface PermitProfile {
  code: string;
  name_key: string;
  labels: Record<string, string> | null;
  jurisdiction_countries: string[];
}

export interface ReportsCatalogue {
  id: string;
  version: number;
  name_key: string;
  labels: Record<string, string> | null;
  report_kinds: ReportKind[];
  permit_steps: PermitProfile[];
}

export interface CatalogueSummary {
  kind: string;
  source: CatalogueSource;
  id: string;
  code: string;
  name: DesignLabel;
  state: string;
  versions: number[];
  latest_version: number | null;
  review_status: string;
  jurisdiction_countries: string[];
}

export interface DesignPhase {
  code: string;
  order: number;
  spine_key?: string;
  name: DesignLabel;
}

/* ── Rows ─────────────────────────────────────────────────────────────── */

export interface DesignSetup {
  id: string;
  /** False on a project without a phase model: no phases, no gates, no frame document. */
  gates_in_use?: boolean;
  project_id: string;
  scheme_source: CatalogueSource;
  scheme_id: string;
  scheme_version: number;
  reports_source: CatalogueSource;
  reports_id: string;
  reports_version: number;
  previous_schemes: Array<{ source: string; id: string; version: number; until?: string }>;
  four_eyes_release: boolean;
  default_distribution_purpose: Purpose;
  lead_designer_role_id: string | null;
  hierarchical_codes: boolean;
  wbs_separator: string;
  target_suitability: Record<string, string>;
  approval_route_id: string | null;
  release_route_id: string | null;
  scheme: NumberingScheme;
  reports_catalogue: ReportsCatalogue;
  phases: DesignPhase[];
  /** Only on the answer to a scheme change: how many drawings keep an older number. */
  legacy_drawings?: number;
}

export interface WbsNode {
  id: string;
  parent_id: string | null;
  code: string;
  name: string;
  level: number;
  sort_order: number;
  kind: WbsKind | null;
  discipline: string | null;
  closed: boolean;
  duplicate_code: boolean;
  /** How many records of each module point at the node. */
  references: Record<string, number>;
}

export interface WbsReference {
  module: string;
  table: string;
  row_id: string;
  value: string;
}

export interface DesignRole {
  id: string;
  code: string;
  title: string;
  party_kind: PartyKind;
  discipline_code: string | null;
  contact_id: string | null;
  user_id: string | null;
  originator_code: string | null;
  contract_package_id: string | null;
  responsible_wbs_ids: string[];
  state: RoleState;
  can?: { transitions?: Transitions<RoleState> };
}

export interface ApprovalPoint {
  id: string;
  code: string;
  title: string;
  phase_code: string | null;
  kind: ApprovalPointKind;
  governance_gate_id: string | null;
  approver_role_id: string | null;
  state: ApprovalPointState;
  approval_instance_id: string | null;
  decided_by: string | null;
  decided_at: string | null;
  note: string;
  can?: { submit?: Flag; reopen?: Flag };
}

export interface Deliverable {
  id: string;
  code: string;
  title: string;
  /** Null on a project without a phase model. */
  phase_code: string | null;
  role_id: string | null;
  discipline_code: string | null;
  form_code: string | null;
  wbs_node_id: string | null;
  planned_count: number;
  planned_count_rationale: string;
  required: boolean;
  required_for: string[];
  target_suitability: string | null;
  waived: boolean;
  waived_rationale: string;
  state: DeliverableState;
  can?: { waive?: Flag; unwaive?: Flag };
}

export interface Drawing {
  id: string;
  container_id: string;
  number: string;
  title: string;
  scale: string;
  sheet_size: string;
  phase_code: string | null;
  deliverable_id: string | null;
  wbs_node_id: string | null;
  role_id: string | null;
  planned_first_issue: string | null;
  forecast_issue: string | null;
  superseded_by_container_id: string | null;
  legacy_scheme: boolean;
  aliases: string[];
  title_block_number: string | null;
  cde_state: CdeState;
  suitability_code?: string | null;
  discipline_code?: string | null;
  form_code?: string | null;
  revision_code?: string | null;
  current_revision_id?: string | null;
  title_block_mismatch?: boolean;
  last_issue?: { at: string | null; recipients: string[] } | null;
}

export interface NumberIssue {
  code: string;
  field: string | null;
  value: string | null;
}

/**
 * Whether the caller may take an action. The server decides; the screen shows it.
 * `applies: false` means the action does not exist for the row now, so it is
 * left out; `allowed: false` shows it disabled with the sentence for `reason`.
 */
export interface Flag {
  allowed: boolean;
  applies?: boolean;
  reason: string | null;
}

/** The moves a row has from its current state, each with its flag. */
export type Transitions<S extends string> = Partial<Record<S, Flag>>;

/** One entry of `detail.violations`. A number problem carries `code`; other refusals name what stands in the way. */
export interface Violation {
  code?: string;
  field?: string | null;
  value?: string | null;
  ref?: string | null;
  recipient?: string | null;
  kind?: string;
  id?: string;
  /** What stands in the way, named for a reader, such as "DL-001 Permit drawings". */
  label?: string | null;
}

export interface NumberCheck {
  valid: boolean;
  issues: NumberIssue[];
  parts: Record<string, string> | null;
}

export interface NumberPreview {
  number: string;
  fields: Record<string, string>;
  missing: string[];
  validation: NumberCheck;
}

export interface BulkCheckRow {
  drawing_id: string;
  container_id: string;
  number: string;
  valid: boolean;
  legacy_scheme: boolean;
  issues: NumberIssue[];
}

export interface RenumberRow {
  drawing_id: string;
  old: string;
  new: string;
  missing: string[];
}

export interface WbsRenumberRow {
  id: string;
  old: string;
  new: string;
}

export interface DistributionRule {
  id: string;
  recipient_list_id: string | null;
  recipient_role_id: string | null;
  discipline_codes: string[];
  form_codes: string[];
  phase_codes: string[];
  wbs_node_ids: string[];
  min_suitability: string | null;
  /** Empty or null: the rule applies to releases of any purpose. */
  purpose: Purpose | '' | null;
  format: DistFormat;
  copies_paper: number;
  ack_required: boolean;
  active: boolean;
}

export interface Release {
  id: string;
  code: string;
  title: string;
  purpose: Purpose;
  revision_ids: string[];
  state: ReleaseState;
  transmittal_ids: string[];
  duplicate_reason: string;
  prepared_by: string | null;
  issued_by: string | null;
  issued_at: string | null;
  content_changed_by?: string | null;
  approval_status?: 'none' | 'pending' | 'approved' | 'rejected';
  approved_by?: string | null;
  approved_at?: string | null;
  can?: { transitions?: Transitions<ReleaseState>; issue?: Flag; approve?: Flag };
}

export interface ReleasePlan {
  recipient_key: string;
  purpose: Purpose;
  revision_ids: string[];
  excluded: Array<{ revision_id: string; reason: string }>;
  duplicates: string[];
}

export interface Review {
  id: string;
  code: string;
  title: string;
  phase_code: string | null;
  deliverable_ids: string[];
  reviewer_role_ids: string[];
  state: ReviewState;
  outcome: ReviewOutcome | null;
  concluded_by: string | null;
  concluded_at: string | null;
  comments_open: number;
  comments_major_open: number;
  can?: { transitions?: Transitions<ReviewState>; conclude?: Flag };
}

export interface ReviewComment {
  id: string;
  review_id: string;
  revision_id: string | null;
  text: string;
  severity: CommentSeverity;
  state: CommentState;
  answer: string;
  answered_by_role_id: string | null;
  created_by: string | null;
  can?: { transitions?: Transitions<CommentState> };
}

export interface Report {
  id: string;
  code: string;
  kind_code: string;
  title: string;
  phase_code: string | null;
  author_role_id: string | null;
  container_id: string | null;
  checker_role_id: string | null;
  external_check: boolean;
  review_cycle_id: string | null;
  required: boolean;
  required_reason: string;
  independent_check: IndependentCheck;
  hint_overridden: boolean;
  rationale: string;
  state: ReportState;
  conditions_text: string;
  can?: { transitions?: Transitions<ReportState>; edit_gate_fields?: Flag };
}

export interface ReportHint {
  kind_code: string;
  region: string | null;
  text_key: string;
  condition_key: string;
  source_url: string | null;
  review_status: string;
}

export interface PermitItem {
  id: string;
  permit_id: string;
  kind: PermitItemKind;
  title: string;
  container_id: string | null;
  report_id: string | null;
  required: boolean;
  included_revision_id: string | null;
  present: boolean;
  state_ok: boolean;
  current_revision_id: string | null;
}

export interface PermitCondition {
  id: string;
  text: string;
  owner_user_id: string | null;
  due_date: string | null;
  state: 'proposed' | 'confirmed' | 'dismissed';
  task_id: string | null;
}

export interface Permit {
  id: string;
  code: string;
  title: string;
  profile_code: string;
  authority_submission_id: string | null;
  review_cycle_id: string | null;
  target_submission_date: string | null;
  state: PermitState;
  submitted_by: string | null;
  submitted_at: string | null;
  superseded_content: boolean;
  conditions: PermitCondition[];
  items: PermitItem[];
  /** Ids of the required items that are missing or not shared yet. */
  missing: string[];
  can?: { transitions?: Transitions<PermitState> };
}

export interface PhaseReadiness {
  /** Null on the one row a project without a phase model answers: the whole project. */
  code: string | null;
  order: number;
  name: DesignLabel | null;
  met: boolean;
  open_deliverables: string[];
  open_reports: string[];
  open_major_comments: number;
}

export interface ValidationFinding {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/* ── Pickers ──────────────────────────────────────────────────────────── */

export type OptionKind =
  | 'contacts'
  | 'contract_packages'
  | 'governance_gates'
  | 'recipient_lists'
  | 'review_cycles'
  | 'authority_submissions'
  | 'forms'
  | 'wbs_nodes';

export interface DesignOption {
  id: string;
  label: string;
  code: string | null;
  label_key?: string | null;
  label_text?: Record<string, string> | null;
}

/** The choices of a picker fed by another module. `available: false` means that source is not there. */
export interface OptionList {
  kind: string;
  available: boolean;
  reason: string | null;
  items: DesignOption[];
}

/* ── Errors ───────────────────────────────────────────────────────────── */

function errorDetail(err: unknown): Record<string, unknown> | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function designErrorCode(err: unknown): string | null {
  const code = errorDetail(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server wrote for the refusal, already in the reader's language. */
export function designErrorMessage(err: unknown): string | null {
  const message = errorDetail(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

/** The per-field problems a refusal listed, so a dialog can show all of them. */
export function designViolations(err: unknown): Violation[] {
  const list = errorDetail(err)?.violations;
  return Array.isArray(list) ? (list as Violation[]).filter((v) => !!v && typeof v === 'object') : [];
}

export const designKeys = {
  project: (projectId: string) => ['design-management', projectId] as const,
  setup: (projectId: string) => ['design-management', projectId, 'setup'] as const,
  list: (projectId: string, name: string) => ['design-management', projectId, name] as const,
  comments: (projectId: string, reviewId: string) => ['design-management', projectId, 'comments', reviewId] as const,
  plan: (projectId: string, releaseId: string) => ['design-management', projectId, 'plan', releaseId] as const,
  catalogues: (kind: string) => ['design-management', 'catalogues', kind] as const,
};

const items = <T,>(page: Promise<Page<T>>): Promise<T[]> => page.then((r) => r.items);

/* ── Setup ────────────────────────────────────────────────────────────── */

export function listSchemes(): Promise<CatalogueSummary[]> {
  return items(apiGet<Page<CatalogueSummary>>(`/v1/project-governance/catalogues?kind=drawing_numbering`));
}

export function getSetup(projectId: string): Promise<DesignSetup> {
  return apiGet<DesignSetup>(`/v1/design-management/projects/${projectId}/setup`);
}

export interface SetupCreateInput {
  scheme_source?: CatalogueSource;
  scheme_id?: string;
  four_eyes_release: boolean;
}

export function createSetup(projectId: string, body: SetupCreateInput): Promise<DesignSetup> {
  return apiPut<DesignSetup>(`/v1/design-management/projects/${projectId}/setup`, body);
}

export interface SetupPatchInput {
  four_eyes_release?: boolean;
  default_distribution_purpose?: Purpose;
  hierarchical_codes?: boolean;
  wbs_separator?: string;
  target_suitability?: Record<string, string>;
  lead_designer_role_id?: string | null;
}

export function updateSetup(projectId: string, body: SetupPatchInput): Promise<DesignSetup> {
  return apiPatch<DesignSetup>(`/v1/design-management/projects/${projectId}/setup`, body);
}

export function changeScheme(projectId: string, body: { source: CatalogueSource; id: string }): Promise<DesignSetup> {
  return apiPost<DesignSetup>(`/v1/design-management/projects/${projectId}/setup/change`, { ...body, catalogue: 'numbering' });
}

export function listReportHints(projectId: string): Promise<ReportHint[]> {
  return items(apiGet<Page<ReportHint>>(`/v1/design-management/projects/${projectId}/catalogue/hints`));
}

/* ── Work breakdown ───────────────────────────────────────────────────── */

export function listWbs(projectId: string): Promise<WbsNode[]> {
  return items(apiGet<Page<WbsNode>>(`/v1/design-management/projects/${projectId}/wbs`));
}

export interface WbsInput {
  code?: string;
  name?: string;
  parent_id?: string | null;
  kind?: WbsKind;
  discipline?: string | null;
}

export function createWbsNode(projectId: string, body: WbsInput): Promise<WbsNode> {
  return apiPost<WbsNode>(`/v1/design-management/projects/${projectId}/wbs`, body);
}

export function updateWbsNode(projectId: string, nodeId: string, body: WbsInput): Promise<WbsNode> {
  return apiPatch<WbsNode>(`/v1/design-management/projects/${projectId}/wbs/${nodeId}`, body);
}

export function previewWbsRenumber(projectId: string, nodeId: string, code: string): Promise<WbsRenumberRow[]> {
  return items(apiPost<Page<WbsRenumberRow>>(`/v1/design-management/projects/${projectId}/wbs/${nodeId}/renumber-preview`, { code }));
}

export function closeWbsNode(projectId: string, nodeId: string, closed: boolean): Promise<WbsNode> {
  return apiPost<WbsNode>(`/v1/design-management/projects/${projectId}/wbs/${nodeId}/close`, { closed });
}

export function deleteWbsNode(projectId: string, nodeId: string): Promise<void> {
  return apiDelete(`/v1/design-management/projects/${projectId}/wbs/${nodeId}`);
}

export function listUnresolvedWbs(projectId: string): Promise<WbsReference[]> {
  return items(apiGet<Page<WbsReference>>(`/v1/design-management/projects/${projectId}/wbs/unresolved`));
}

/* ── Design team ──────────────────────────────────────────────────────── */

export function listRoles(projectId: string): Promise<DesignRole[]> {
  return items(apiGet<Page<DesignRole>>(`/v1/design-management/projects/${projectId}/roles`));
}

export interface RoleInput {
  code?: string;
  title?: string;
  party_kind?: PartyKind;
  discipline_code?: string | null;
  user_id?: string | null;
  contact_id?: string | null;
  originator_code?: string | null;
  state?: RoleState;
}

export function createRole(projectId: string, body: RoleInput): Promise<DesignRole> {
  return apiPost<DesignRole>(`/v1/design-management/projects/${projectId}/roles`, body);
}

export function updateRole(projectId: string, roleId: string, body: RoleInput): Promise<DesignRole> {
  return apiPatch<DesignRole>(`/v1/design-management/projects/${projectId}/roles/${roleId}`, body);
}

export function deleteRole(projectId: string, roleId: string): Promise<void> {
  return apiDelete(`/v1/design-management/projects/${projectId}/roles/${roleId}`);
}

/* ── Approval points and the design schedule ──────────────────────────── */

export function listApprovalPoints(projectId: string): Promise<ApprovalPoint[]> {
  return items(apiGet<Page<ApprovalPoint>>(`/v1/design-management/projects/${projectId}/approval-points`));
}

export interface ApprovalPointInput {
  code?: string;
  title?: string;
  phase_code?: string | null;
  kind?: ApprovalPointKind;
  approver_role_id?: string | null;
  governance_gate_id?: string | null;
  note?: string;
}

export function createApprovalPoint(projectId: string, body: ApprovalPointInput): Promise<ApprovalPoint> {
  return apiPost<ApprovalPoint>(`/v1/design-management/projects/${projectId}/approval-points`, body);
}

export function updateApprovalPoint(projectId: string, id: string, body: ApprovalPointInput): Promise<ApprovalPoint> {
  return apiPatch<ApprovalPoint>(`/v1/design-management/projects/${projectId}/approval-points/${id}`, body);
}

export function submitApprovalPoint(projectId: string, id: string): Promise<ApprovalPoint> {
  return apiPost<ApprovalPoint>(`/v1/design-management/projects/${projectId}/approval-points/${id}/submit`, {});
}

/** Puts a rejected approval point back to open, so it can be changed and sent again. */
export function reopenApprovalPoint(projectId: string, id: string): Promise<ApprovalPoint> {
  return apiPost<ApprovalPoint>(`/v1/design-management/projects/${projectId}/approval-points/${id}/reopen`, {});
}

export function listDeliverables(projectId: string): Promise<Deliverable[]> {
  return items(apiGet<Page<Deliverable>>(`/v1/design-management/projects/${projectId}/deliverables`));
}

export interface DeliverableInput {
  code?: string;
  title?: string;
  phase_code?: string | null;
  role_id?: string | null;
  discipline_code?: string | null;
  form_code?: string | null;
  wbs_node_id?: string | null;
  planned_count?: number;
  planned_count_rationale?: string;
  required?: boolean;
  target_suitability?: string | null;
  waived?: boolean;
  waived_rationale?: string;
}

export function createDeliverable(projectId: string, body: DeliverableInput): Promise<Deliverable> {
  return apiPost<Deliverable>(`/v1/design-management/projects/${projectId}/deliverables`, body);
}

export function updateDeliverable(projectId: string, id: string, body: DeliverableInput): Promise<Deliverable> {
  return apiPatch<Deliverable>(`/v1/design-management/projects/${projectId}/deliverables/${id}`, body);
}

export function deleteDeliverable(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/design-management/projects/${projectId}/deliverables/${id}`);
}

/* ── Numbering and the drawing register ───────────────────────────────── */

export interface NumberRequest {
  role_id?: string | null;
  phase_code?: string | null;
  sheet_size?: string | null;
  wbs_node_id?: string | null;
  fields: Record<string, string>;
}

export function previewNumber(projectId: string, body: NumberRequest): Promise<NumberPreview> {
  return apiPost<NumberPreview>(`/v1/design-management/projects/${projectId}/numbering/preview`, body);
}

/** Takes the next number for good: a number handed out is never handed out again. */
export function allocateNumber(projectId: string, body: NumberRequest): Promise<{ number: string }> {
  return apiPost<{ number: string }>(`/v1/design-management/projects/${projectId}/numbering/allocate`, body);
}

export function validateNumber(projectId: string, number: string): Promise<NumberCheck> {
  return apiPost<NumberCheck>(`/v1/design-management/projects/${projectId}/numbering/validate`, { number });
}

export function bulkValidateNumbers(projectId: string): Promise<BulkCheckRow[]> {
  return items(apiPost<Page<BulkCheckRow>>(`/v1/design-management/projects/${projectId}/numbering/bulk-validate`, {}));
}

export function previewRenumber(projectId: string): Promise<RenumberRow[]> {
  return items(apiPost<Page<RenumberRow>>(`/v1/design-management/projects/${projectId}/numbering/renumber-preview`, {}));
}

export function applyRenumber(projectId: string, mapping: Record<string, string>): Promise<unknown> {
  return apiPost(`/v1/design-management/projects/${projectId}/numbering/renumber-apply`, { mapping });
}

export function listDrawings(projectId: string): Promise<Drawing[]> {
  return items(apiGet<Page<Drawing>>(`/v1/design-management/projects/${projectId}/drawings?limit=1000`));
}

export interface DrawingCreateInput extends NumberRequest {
  number?: string;
  title: string;
  scale?: string;
  deliverable_id?: string | null;
  planned_first_issue?: string | null;
  forecast_issue?: string | null;
}

export function createDrawing(projectId: string, body: DrawingCreateInput): Promise<Drawing> {
  return apiPost<Drawing>(`/v1/design-management/projects/${projectId}/drawings`, body);
}

export interface DrawingPatchInput {
  title?: string;
  scale?: string;
  sheet_size?: string;
  phase_code?: string | null;
  deliverable_id?: string | null;
  wbs_node_id?: string | null;
  role_id?: string | null;
  planned_first_issue?: string | null;
  forecast_issue?: string | null;
}

export function updateDrawing(projectId: string, id: string, body: DrawingPatchInput): Promise<Drawing> {
  return apiPatch<Drawing>(`/v1/design-management/projects/${projectId}/drawings/${id}`, body);
}

export function supersedeDrawing(projectId: string, id: string, byContainerId: string): Promise<Drawing> {
  return apiPost<Drawing>(`/v1/design-management/projects/${projectId}/drawings/${id}/supersede`, { by_container_id: byContainerId });
}

export function readTitleBlock(projectId: string, id: string, text: string): Promise<Drawing> {
  return apiPost<Drawing>(`/v1/design-management/projects/${projectId}/drawings/${id}/title-block`, { text });
}

/* ── Distribution and releases ────────────────────────────────────────── */

export function listDistributionRules(projectId: string): Promise<DistributionRule[]> {
  return items(apiGet<Page<DistributionRule>>(`/v1/design-management/projects/${projectId}/distribution-rules`));
}

export interface DistributionRuleInput {
  recipient_role_id?: string | null;
  recipient_list_id?: string | null;
  discipline_codes?: string[];
  form_codes?: string[];
  phase_codes?: string[];
  wbs_node_ids?: string[];
  min_suitability?: string | null;
  purpose?: Purpose | null;
  format?: DistFormat;
  copies_paper?: number;
  ack_required?: boolean;
  active?: boolean;
}

export function createDistributionRule(projectId: string, body: DistributionRuleInput): Promise<DistributionRule> {
  return apiPost<DistributionRule>(`/v1/design-management/projects/${projectId}/distribution-rules`, body);
}

export function updateDistributionRule(
  projectId: string,
  id: string,
  body: DistributionRuleInput,
): Promise<DistributionRule> {
  return apiPatch<DistributionRule>(`/v1/design-management/projects/${projectId}/distribution-rules/${id}`, body);
}

export function deleteDistributionRule(projectId: string, id: string): Promise<void> {
  return apiDelete(`/v1/design-management/projects/${projectId}/distribution-rules/${id}`);
}

export function listReleases(projectId: string): Promise<Release[]> {
  return items(apiGet<Page<Release>>(`/v1/design-management/projects/${projectId}/releases`));
}

export interface ReleaseInput {
  code?: string;
  title?: string;
  purpose?: Purpose;
  revision_ids?: string[];
}

export function createRelease(projectId: string, body: ReleaseInput): Promise<Release> {
  return apiPost<Release>(`/v1/design-management/projects/${projectId}/releases`, body);
}

export function updateRelease(projectId: string, id: string, body: ReleaseInput): Promise<Release> {
  return apiPatch<Release>(`/v1/design-management/projects/${projectId}/releases/${id}`, body);
}

export function previewRelease(projectId: string, id: string): Promise<ReleasePlan[]> {
  return items(apiGet<Page<ReleasePlan>>(`/v1/design-management/projects/${projectId}/releases/${id}/preview`));
}

export function moveRelease(projectId: string, id: string, target: ReleaseState): Promise<Release> {
  return apiPost<Release>(`/v1/design-management/projects/${projectId}/releases/${id}/transition`, { target });
}

export function issueRelease(projectId: string, id: string, duplicateReason: string): Promise<Release> {
  return apiPost<Release>(`/v1/design-management/projects/${projectId}/releases/${id}/issue`, { duplicate_reason: duplicateReason });
}

/* ── Reviews ──────────────────────────────────────────────────────────── */

export function listReviews(projectId: string): Promise<Review[]> {
  return items(apiGet<Page<Review>>(`/v1/design-management/projects/${projectId}/reviews`));
}

export interface ReviewInput {
  code?: string;
  title?: string;
  phase_code?: string | null;
  deliverable_ids: string[];
  reviewer_role_ids: string[];
}

export function createReview(projectId: string, body: ReviewInput): Promise<Review> {
  return apiPost<Review>(`/v1/design-management/projects/${projectId}/reviews`, body);
}

export function moveReview(projectId: string, id: string, target: ReviewState): Promise<Review> {
  return apiPost<Review>(`/v1/design-management/projects/${projectId}/reviews/${id}/transition`, { target });
}

export function concludeReview(projectId: string, id: string, outcome: ReviewOutcome): Promise<Review> {
  return apiPost<Review>(`/v1/design-management/projects/${projectId}/reviews/${id}/conclude`, { outcome });
}

export function listReviewComments(projectId: string, reviewId: string): Promise<ReviewComment[]> {
  return items(apiGet<Page<ReviewComment>>(`/v1/design-management/projects/${projectId}/reviews/${reviewId}/comments`));
}

export function addReviewComment(
  projectId: string,
  reviewId: string,
  body: { text: string; severity: CommentSeverity; revision_id?: string | null },
): Promise<ReviewComment> {
  return apiPost<ReviewComment>(`/v1/design-management/projects/${projectId}/reviews/${reviewId}/comments`, body);
}

export function moveComment(
  projectId: string,
  commentId: string,
  body: { target: CommentState; answer?: string; role_id?: string | null },
): Promise<ReviewComment> {
  return apiPost<ReviewComment>(`/v1/design-management/projects/${projectId}/comments/${commentId}/transition`, body);
}

/* ── Reports ──────────────────────────────────────────────────────────── */

export function listReports(projectId: string): Promise<Report[]> {
  return items(apiGet<Page<Report>>(`/v1/design-management/projects/${projectId}/reports`));
}

export interface ReportInput {
  code?: string;
  kind_code?: string;
  title?: string;
  phase_code?: string | null;
  author_role_id?: string | null;
  checker_role_id?: string | null;
  external_check?: boolean;
  review_cycle_id?: string | null;
  required?: boolean;
  independent_check?: IndependentCheck;
  rationale?: string;
  conditions_text?: string;
  from_catalogue?: boolean;
}

export function createReport(projectId: string, body: ReportInput): Promise<Report> {
  return apiPost<Report>(`/v1/design-management/projects/${projectId}/reports`, body);
}

export function updateReport(projectId: string, id: string, body: ReportInput): Promise<Report> {
  return apiPatch<Report>(`/v1/design-management/projects/${projectId}/reports/${id}`, body);
}

export function moveReport(projectId: string, id: string, target: ReportState, rationale = ''): Promise<Report> {
  return apiPost<Report>(`/v1/design-management/projects/${projectId}/reports/${id}/transition`, { target, rationale });
}

export function syncReport(projectId: string, id: string): Promise<Report> {
  return apiPost<Report>(`/v1/design-management/projects/${projectId}/reports/${id}/sync`, {});
}

/* ── Permit package ───────────────────────────────────────────────────── */

export function listPermits(projectId: string): Promise<Permit[]> {
  return items(apiGet<Page<Permit>>(`/v1/design-management/projects/${projectId}/permits`));
}

export function getPermit(projectId: string, id: string): Promise<Permit> {
  return apiGet<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}`);
}

export interface PermitInput {
  code?: string;
  title?: string;
  profile_code?: string;
  target_submission_date?: string | null;
  authority_submission_id?: string | null;
  review_cycle_id?: string | null;
}

export function createPermit(projectId: string, body: PermitInput): Promise<Permit> {
  return apiPost<Permit>(`/v1/design-management/projects/${projectId}/permits`, body);
}

export function updatePermit(projectId: string, id: string, body: PermitInput): Promise<Permit> {
  return apiPatch<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}`, body);
}

export interface PermitItemInput {
  kind: PermitItemKind;
  title: string;
  container_id?: string | null;
  report_id?: string | null;
  required: boolean;
}

export function addPermitItem(projectId: string, id: string, body: PermitItemInput): Promise<unknown> {
  return apiPost(`/v1/design-management/projects/${projectId}/permits/${id}/items`, body);
}

export function removePermitItem(projectId: string, id: string, itemId: string): Promise<void> {
  return apiDelete(`/v1/design-management/projects/${projectId}/permits/${id}/items/${itemId}`);
}

export function movePermit(projectId: string, id: string, target: PermitState): Promise<Permit> {
  return apiPost<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}/transition`, { target });
}

export function syncPermit(projectId: string, id: string): Promise<Permit> {
  return apiPost<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}/sync`, {});
}

export function proposePermitConditions(
  projectId: string,
  id: string,
  conditions: Array<{ text: string; owner_user_id?: string | null; due_date?: string | null }>,
): Promise<Permit> {
  return apiPost<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}/conditions`, { conditions });
}

export function decidePermitCondition(
  projectId: string,
  id: string,
  conditionId: string,
  confirm: boolean,
): Promise<Permit> {
  return apiPost<Permit>(`/v1/design-management/projects/${projectId}/permits/${id}/conditions/${conditionId}`, { confirm });
}

export function listOptions(projectId: string, kind: OptionKind): Promise<OptionList> {
  return apiGet<OptionList>(`/v1/design-management/projects/${projectId}/options/${kind}`);
}

/* ── Readiness, checks and exports ────────────────────────────────────── */

export function listReadiness(projectId: string): Promise<PhaseReadiness[]> {
  return items(apiGet<Page<PhaseReadiness>>(`/v1/design-management/projects/${projectId}/readiness`));
}

export function listValidation(projectId: string): Promise<ValidationFinding[]> {
  return items(apiGet<Page<ValidationFinding>>(`/v1/design-management/projects/${projectId}/validation`));
}

export function downloadRegister(projectId: string, register: ExportRegister, format: 'pdf' | 'xlsx'): Promise<void> {
  return downloadWithAuth(
    `${API_BASE}/v1/design-management/projects/${projectId}/export?register=${register}&format=${format}`,
    `design_${register}.${format}`,
  );
}

/** Files the register as a new revision of the design frame document in the CDE. */
export function fileFrameDocument(projectId: string, register: ExportRegister): Promise<unknown> {
  return apiPost(`/v1/design-management/projects/${projectId}/frame-documents/${register}`, {});
}
