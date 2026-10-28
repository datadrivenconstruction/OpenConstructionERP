// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the commitment and release matrix: what the project plans
// to commit, what was released in which tranche, who approves at which amount
// and what an abort would cost.
//
// Backend module: backend/app/modules/commitment_release/router.py, mounted at
// /api/v1/commitment-release/. Every project route lives under
// /projects/{project_id}/ there.
//
// Money travels as decimal strings in both directions and is never turned
// into a number here. Errors arrive as
// `detail = {code, message_key, message, violations?, info?}`; the screens
// read `code` to explain a refusal and fall back to `getErrorMessage`.

import { API_BASE, ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

/** A label as the API sends it: a message key for shipped items, texts per locale for tenant ones. */
export interface CommitmentLabel {
  key: string | null;
  text: Record<string, string> | null;
}

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type Enforcement = 'off' | 'warn' | 'block';
export type FxPolicy = 'fx_service_rate_set' | 'project_rates';
export type PlannedSource = 'budget_line' | 'cost_line' | 'boq_position' | 'manual';
/** Where a catalogue row comes from. Sent back as the row carries it, never mapped. */
export type CatalogueSource = 'shipped' | 'tenant' | 'pack';
export type ItemStatus =
  | 'planned'
  | 'release_requested'
  | 'released'
  | 'partially_released'
  | 'committed'
  | 'closed'
  | 're_release_required'
  | 'on_hold'
  | 'aborted'
  | 'transferred';
export type LinkKind =
  | 'contract'
  | 'contract_line'
  | 'purchase_order'
  | 'change_order'
  | 'variation_order'
  | 'tender_package'
  | 'bid_package'
  | 'rfq';
export type PreconditionKind =
  | 'manual'
  | 'gate_decided'
  | 'frame_document_binding'
  | 'funding_approved'
  | 'permit'
  | 'budget_available'
  | 'public_commitment_appropriation';
export type ReleaseOutcome = 'pending' | 'released' | 'rejected' | 'withdrawn' | 'aborted';
/** What a request asks for: money to commit, or stopping the item. */
export type ReleasePurpose = 'release' | 'abort';
export type DateBasis = 'fixed' | 'late_start' | 'start_date' | 'plant_item' | 'none';

/** Whose lead time is in force on an item. */
export type LeadTimeSource = 'plant_item' | 'item' | 'requisition';
export type Transferable = 'no' | 'to_project' | 'resale';

export type RouteState = 'generated' | 'pinned' | 'changed' | 'none';

export interface Approver {
  kind: 'role' | 'project_role' | 'user';
  ref: string;
}

export interface MatrixTier {
  code: string;
  name: CommitmentLabel;
  approver: Approver;
  steps_mode: 'all' | 'any';
  four_eyes: boolean;
  route_id: string | null;
  /** `changed`: the route's steps were edited since a manager accepted them; requests of the tier are refused. */
  route_state?: RouteState;
}

export interface MatrixCode {
  code: string;
  name: CommitmentLabel;
  min_tier?: string | null;
}

export interface CommitmentMatrix {
  id: string;
  project_id: string;
  schedule_source: CatalogueSource;
  schedule_id: string;
  schedule_version: number;
  enforcement: Enforcement;
  fx_policy: FxPolicy;
  require_link: boolean;
  tier_routes: Record<string, string>;
  legal_entity_id: string | null;
  base_currency: string;
  schedule_currency: string;
  tiers: MatrixTier[];
  commitment_types: MatrixCode[];
  novelty_flags: MatrixCode[];
}

export interface MatrixInput {
  schedule_source?: CatalogueSource;
  schedule_id?: string;
  schedule_version?: number;
  enforcement?: Enforcement;
  fx_policy?: FxPolicy;
  require_link?: boolean;
}

export interface CatalogueSummary {
  kind: string;
  source: CatalogueSource;
  id: string;
  code: string;
  name: CommitmentLabel;
  state: string;
  versions: number[];
  latest_version: number | null;
  review_status: string;
  jurisdiction_countries: string[];
}

/** A contract figure a basis asks for. Values are fractions of one as decimal strings: "0.05" is five per cent. */
export interface AbortParameterField {
  name: string;
  type: string;
  unit: string;
  min: string;
  max: string;
  /** What the basis ships; null means the figure must be entered. */
  default: string | null;
  required: boolean;
  statutory: boolean;
  label_key: string;
  note_key: string | null;
}

export interface AbortBasis extends CatalogueSummary {
  method?: string | null;
  source_url?: string;
  parameter_fields?: AbortParameterField[];
}

export interface Assignment {
  id: string;
  project_role: string;
  user_id: string;
  deputy_user_id: string | null;
  valid_from: string | null;
  valid_to: string | null;
}

export interface AssignmentInput {
  project_role: string;
  /** Null when a deputy or an end date was filled without an approver; the server refuses that row by name. */
  user_id: string | null;
  deputy_user_id?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
}

/** What route generation did per tier. */
export type RouteReport = 'created' | 'replaced' | 'unchanged' | 'edited' | 'unfilled' | 'pinned';

export interface Precondition {
  id: string;
  kind: PreconditionKind;
  ref_id: string | null;
  text: string;
  state: string;
  evidence_ref: string | null;
  confirmed_by: string | null;
  confirmed_at: string | null;
  /** A refusal code when the precondition names something the project does not have, so it can never be met. */
  unreachable_reason?: string | null;
}

export interface ItemLink {
  link_id: string;
  kind: LinkKind;
  document_id: string;
  /** The contract a line, a change order or a variation order belongs to; null when it has none. */
  contract_id?: string | null;
  currency: string;
  document_amount: string;
  counted_amount: string;
  counts: boolean;
  closed: boolean;
  status: string | null;
  found: boolean;
  notes: string[];
}

export interface ExposureLine {
  code: string;
  amount?: string;
  pct?: string;
  milestone?: string;
}

/** `residual_loss` null means unknown. It is never shown as zero. */
export interface Exposure {
  sunk?: string | null;
  committed?: string | null;
  committed_not_spent?: string | null;
  cancellation_charge?: string | null;
  recoverable?: string | null;
  residual_loss: string | null;
  reason?: string | null;
  method?: string | null;
  basis_review_status?: string | null;
  lines?: ExposureLine[];
  currency: string;
  as_of?: string;
  basis_code?: string | null;
  transferable?: Transferable | null;
  note?: string;
}

/**
 * Whether the caller may do one thing to an item now. `reason` is the refusal
 * code the write itself would answer with, so a disabled button and a refused
 * click say the same sentence.
 */
export interface CanFlag {
  allowed: boolean;
  reason: string | null;
}

export type ProjectAction = 'manage' | 'add_item' | 'save_scenario';
export type ProjectCan = Partial<Record<ProjectAction, CanFlag>>;

/** What the caller may do on the project's matrix. Answered before the matrix exists too. */
export interface ProjectCapabilities {
  matrix_exists: boolean;
  can: ProjectCan;
}

export type ItemAction =
  | 'edit'
  | 'link'
  | 'request_release'
  | 'request_abort'
  | 'withdraw'
  | 'decide'
  | 'hold'
  | 'resume'
  | 'transfer'
  | 'defer'
  | 'edit_gate_fields'
  | 'remove_precondition';

/** What is left to do by hand after an abort was decided: the module ends no contract or order itself. */
export interface AbortFollowUp {
  kind: LinkKind;
  document_id: string;
  action: 'terminate' | 'cancel';
  status: string | null;
}

export interface AbortRecord {
  release_id: string;
  decided_at: string | null;
  decided_by: string | null;
  reason: string;
  residual_loss: string;
  currency: string;
  follow_up: AbortFollowUp[];
}

export interface CommitmentItem {
  id: string;
  code: string;
  title: string;
  commitment_type: string;
  status: ItemStatus;
  attempt_no: number;
  flags: string[];
  governance_area_code: string | null;
  gate_code: string | null;
  deferred: boolean;
  deferred_reason: string | null;
  split_group: string | null;
  owner_user_id: string | null;
  planned_source: PlannedSource;
  /** The figure typed on the item. It is the one in force only when `lead_time_source` is `item`. */
  lead_time_days: number | null;
  /** The lead time the dates are computed with, and whose it is. */
  lead_time_in_force_days?: number | null;
  lead_time_source?: LeadTimeSource | null;
  /** An item of the plant register this commitment pays for; its code is null once the register no longer knows it. */
  plant_item_id?: string | null;
  plant_item_code?: string | null;
  /** The register no longer answers for the linked plant item, so the item's own lead time is in force. */
  plant_item_missing?: boolean;
  /** The register's own status of the linked plant item, when it serves one. */
  plant_item_status?: string | null;
  /** The linked plant item is cancelled in the register. Its dates are still the ones used. */
  plant_item_cancelled?: boolean;
  decision_buffer_days: number | null;
  latest_decision_date_fixed: string | null;
  planned: { amount: string | null; currency: string; note: string | null };
  schedule_currency: string;
  planned_in_schedule_currency: string | null;
  released: string | null;
  /** null when a linked amount has no exchange rate, see `committed_reason`. */
  committed: string | null;
  committed_reason: string | null;
  release_ceiling_with_tolerance: string | null;
  over_release: boolean;
  /** Released less the expired part nothing is bound under; null when the bound sum has no exchange rate. */
  released_in_force?: string | null;
  /** Released less what is in force. It stays after a renewal: history, not a warning. */
  released_lapsed?: string | null;
  /** A passed validity date is what stops further money right now. A renewed release with headroom clears it. */
  release_expired?: boolean;
  /** The passed validity dates, earliest first. */
  expired_release_dates?: string[];
  /** A tier code, or `escalate_outside` when the amount is above every tier. */
  required_tier_for_planned: string | null;
  latest_decision_date: string | null;
  date_basis: DateBasis;
  decision_overdue: boolean;
  preconditions: Precondition[];
  open_preconditions: number;
  links: ItemLink[];
  pending_release_id: string | null;
  pending_purpose: ReleasePurpose | null;
  transferred_to_item_id: string | null;
  /** The item that took this one over; null unless it was handed over. */
  transferred_to?: TransferredTo | null;
  /** Set once an abort was decided. */
  abort: AbortRecord | null;
  can: Partial<Record<ItemAction, CanFlag>>;
  exposure?: Exposure;
}

export interface ItemTotals {
  currency: string;
  planned: string | null;
  /** Everything ever released, lapsed or not. */
  released: string | null;
  released_in_force?: string | null;
  released_lapsed?: string | null;
  committed: string | null;
  mixed_currency: boolean;
  /** Which of the three totals leave out an item that could not be converted. */
  incomplete: string[];
}

export interface ItemsResponse extends Page<CommitmentItem> {
  totals: ItemTotals;
}

export interface ItemInput {
  code?: string;
  title?: string;
  commitment_type?: string;
  planned_source?: PlannedSource;
  planned_manual_amount?: string | null;
  currency?: string | null;
  owner_user_id?: string | null;
  lead_time_days?: number | null;
  decision_buffer_days?: number | null;
  latest_decision_date_fixed?: string | null;
  flags?: string[];
  split_group?: string | null;
  governance_area_code?: string | null;
  gate_code?: string | null;
  /** An item of the plant register; null removes the link. */
  plant_item_id?: string | null;
  deferred?: boolean;
  deferred_reason?: string | null;
}

export interface DecisionInput {
  decision: 'approved' | 'rejected';
  /** The rationale. A rejection is refused without it. */
  comment: string;
  conditions: string;
  valid_until: string | null;
}

export interface TransferInput {
  target_item_id: string;
  /** Only for an item of another project; left out inside the project. */
  target_project_id?: string;
  reason: string;
}

/* ── Pick lists read through the modules that own the records ──────────── */

export interface ReferenceGate {
  code: string;
  name: CommitmentLabel;
  status: string;
  last_outcome: string | null;
}

export interface ReferenceArea {
  code: string;
  name: CommitmentLabel;
}

export interface ReferenceFrameDocument {
  id: string;
  doc_type: string;
  name: CommitmentLabel;
  area_code: string | null;
  status: string;
}

export interface ReferenceFunding {
  id: string;
  code: string;
  title: string;
  status: string;
}

/** What the item and precondition forms let a person pick. Every list is empty without a governance model. */
/** An item of the plant register. The name is the register's own title, the status its own code. */
export interface ReferencePlantItem {
  id: string;
  code: string;
  name: string;
  status: string;
}

export interface References {
  has_model: boolean;
  /** False on a project that does not use gates; `gates` is empty then. */
  gates_in_use?: boolean;
  gates: ReferenceGate[];
  areas: ReferenceArea[];
  frame_documents: ReferenceFrameDocument[];
  funding_applications: ReferenceFunding[];
  /** `available` is false when the project has no plant register to choose from. */
  plant_items?: { available: boolean; items: ReferencePlantItem[] };
}

/**
 * The item that took a handed-over item over. The ids are always there; the
 * names are null when the reader may not open the receiving project.
 */
export interface TransferredTo {
  project_id: string;
  item_id: string;
  same_project: boolean;
  can_open: boolean;
  project_name: string | null;
  code: string | null;
  title: string | null;
}

/** A project an item may be handed over to, with the open items that can take it. */
export interface TransferTarget {
  project_id: string;
  project_name: string;
  same_project: boolean;
  can: CanFlag;
  items: Array<{ id: string; code: string; title: string }>;
}

export interface CheckInput {
  kind: LinkKind;
  document_id: string;
  new_amount: string;
  currency: string;
}

export interface CheckReason {
  code: string;
  released?: string;
  ceiling?: string;
  would_commit?: string;
  currency?: string;
}

/** What the guard would say to a new amount on a document. `item_id` is null when no item counts the document. */
export interface CheckResult {
  result: 'ok' | 'warn' | 'block';
  reasons: CheckReason[];
  item_id: string | null;
}

export interface ReleaseInput {
  amount: string;
  currency?: string;
  tranche_note: string;
  external_approval_ref: string;
}

export interface FxQuote {
  from: string;
  to: string;
  rate: string;
  as_of: string | null;
  source: string;
  rate_set_id: string | null;
}

/** What a release request would need. The preview writes nothing. */
export interface ReleasePreview {
  amount: string;
  currency: string;
  schedule_currency: string;
  amount_in_schedule_currency: string;
  fx: FxQuote;
  released_before: string;
  group_released: string;
  evaluated_amount: string;
  required_tier: string | null;
  escalate_outside: boolean;
  band_code: string | null;
  raised_by: string[];
  route_tier: string | null;
  route_id: string | null;
  /** User ids, or `role:<name>` for a step a role decides. */
  approvers: string[];
  schedule: string;
  open_preconditions: Precondition[];
}

/** What an abort request would be judged on today. The tier follows the residual loss, not an amount typed here. */
export interface AbortPreview extends Omit<ReleasePreview, 'released_before' | 'group_released'> {
  residual_loss: string;
  external_approval_required: boolean;
  exposure: Exposure;
}

/** What the decider is shown, frozen when the request was made. */
export interface ReleaseSnapshot {
  preconditions?: Precondition[];
  links?: ItemLink[];
  committed?: string | null;
  four_eyes?: boolean;
}

export interface Release {
  id: string;
  item_id: string;
  attempt: number;
  purpose: ReleasePurpose;
  requested_amount: string;
  currency: string;
  schedule_currency: string;
  amount_in_schedule_currency: string;
  fx_rate_used: string;
  fx_rate_date: string | null;
  fx_source: string;
  evaluated_amount: string;
  cumulative_after: string;
  required_tier: string | null;
  escalate_outside: boolean;
  external_approval_ref: string;
  approval_instance_id: string | null;
  outcome: ReleaseOutcome;
  requested_by: string | null;
  decided_by: string | null;
  on_behalf_of: string | null;
  decided_at: string | null;
  tranche_note: string;
  conditions: string;
  rationale: string;
  valid_until: string | null;
  snapshot?: ReleaseSnapshot;
  created_at: string;
}

export interface ScheduleStep {
  milestone: string;
  from_date?: string | null;
  progress_pct?: string | null;
  charge_amount?: string | null;
  charge_pct?: string | null;
}

export interface AbortTerms {
  id: string;
  item_id: string;
  scope: string;
  basis_code: string | null;
  basis_source: CatalogueSource;
  cancellation_schedule: ScheduleStep[];
  parameters: Record<string, string>;
  transferable: Transferable;
  transfer_value_estimate: string | null;
  salvage_value_estimate: string | null;
  saved_cost_estimate: string | null;
  other_charge_estimate: string | null;
  progress_pct: string | null;
  notice_days: number | null;
  source_note: string;
  entered_by: string | null;
  entered_at: string | null;
}

export interface AbortTermsInput {
  link_id: string | null;
  basis_code: string | null;
  basis_source: CatalogueSource;
  cancellation_schedule: ScheduleStep[];
  transferable: Transferable;
  transfer_value_estimate: string | null;
  salvage_value_estimate: string | null;
  saved_cost_estimate: string | null;
  other_charge_estimate: string | null;
  /** How far the work has come, as a fraction; cancellation steps by progress read it. */
  progress_pct: string | null;
  /** The contract figures of the chosen basis, by name, as fractions of one. */
  parameters: Record<string, string>;
  notice_days: number | null;
  source_note: string;
}

export interface ExposureRow extends Exposure {
  item_id: string;
  code: string;
  status: ItemStatus;
}

export interface ExposureResponse {
  as_of: string;
  currency: string;
  items: ExposureRow[];
  total_residual_loss: string;
  unknown_count: number;
}

export interface Scenario {
  id: string;
  as_of: string;
  label: string;
  payload: ExposureResponse;
}

export interface EvaluateInput {
  schedule_source: CatalogueSource;
  schedule_id: string;
  schedule_version?: number;
  commitment_type: string;
  amount: string;
  flags: string[];
}

export interface EvaluateResult {
  required_tier: string | null;
  escalate_outside: boolean;
  band_code: string | null;
  raised_by: string[];
  currency: string;
  approver: Approver | null;
}

export interface Finding {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/** One entry of `detail.violations`: the backend sends at least a code. */
export interface CommitmentViolation {
  code: string;
  message?: string;
  /** The precondition id for `precondition_open`. */
  ref?: string;
  kind?: string;
}

function detailOf(err: unknown): Record<string, unknown> | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function commitmentErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server wrote for the refusal, already in the reader's language. */
export function commitmentErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message.trim() ? message : null;
}

/** What a refusal listed (open preconditions, catalogue rule breaks), so the dialog shows all of them. */
export function commitmentViolations(err: unknown): CommitmentViolation[] {
  const list = detailOf(err)?.violations;
  if (!Array.isArray(list)) return [];
  return list.filter((v): v is CommitmentViolation => !!v && typeof v === 'object');
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const commitmentKeys = {
  all: ['commitment-release'] as const,
  project: (projectId: string) => ['commitment-release', projectId] as const,
  matrix: (projectId: string) => ['commitment-release', projectId, 'matrix'] as const,
  capabilities: (projectId: string) => ['commitment-release', projectId, 'capabilities'] as const,
  items: (projectId: string) => ['commitment-release', projectId, 'items'] as const,
  item: (projectId: string, itemId: string) => ['commitment-release', projectId, 'item', itemId] as const,
  releases: (projectId: string, itemId: string) => ['commitment-release', projectId, 'releases', itemId] as const,
  abortTerms: (projectId: string, itemId: string) => ['commitment-release', projectId, 'abort-terms', itemId] as const,
  assignments: (projectId: string) => ['commitment-release', projectId, 'assignments'] as const,
  exposure: (projectId: string, asOf: string) => ['commitment-release', projectId, 'exposure', asOf] as const,
  scenarios: (projectId: string) => ['commitment-release', projectId, 'scenarios'] as const,
  findings: (projectId: string) => ['commitment-release', projectId, 'findings'] as const,
  documents: (projectId: string, kind: string) => ['commitment-release', projectId, 'documents', kind] as const,
  contractLines: (projectId: string, contractId: string) =>
    ['commitment-release', projectId, 'contract-lines', contractId] as const,
  references: (projectId: string) => ['commitment-release', projectId, 'references'] as const,
  abortPreview: (projectId: string, itemId: string) =>
    ['commitment-release', projectId, 'abort-preview', itemId] as const,
  transferTargets: (projectId: string, itemId: string) =>
    ['commitment-release', projectId, 'transfer-targets', itemId] as const,
  schedules: ['commitment-release', 'schedules'] as const,
  abortBases: ['commitment-release', 'abort-bases'] as const,
};

/* ── Catalogues ───────────────────────────────────────────────────────── */

export function listSchedules(): Promise<Page<CatalogueSummary>> {
  return apiGet<Page<CatalogueSummary>>(`/v1/commitment-release/authority-schedules`);
}

export function listAbortBases(): Promise<Page<AbortBasis>> {
  return apiGet<Page<AbortBasis>>(`/v1/commitment-release/abort-bases`);
}

export function evaluateSchedule(body: EvaluateInput): Promise<EvaluateResult> {
  return apiPost<EvaluateResult>(`/v1/commitment-release/authority-schedules/evaluate`, body);
}

/* ── Matrix, assignments and routes ───────────────────────────────────── */

export function getCapabilities(projectId: string): Promise<ProjectCapabilities> {
  return apiGet<ProjectCapabilities>(`/v1/commitment-release/projects/${projectId}/capabilities`);
}

export function getMatrix(projectId: string): Promise<CommitmentMatrix> {
  return apiGet<CommitmentMatrix>(`/v1/commitment-release/projects/${projectId}/matrix`);
}

export function setMatrix(projectId: string, body: MatrixInput): Promise<CommitmentMatrix> {
  return apiPut<CommitmentMatrix>(`/v1/commitment-release/projects/${projectId}/matrix`, body);
}

export function listAssignments(projectId: string): Promise<Page<Assignment>> {
  return apiGet<Page<Assignment>>(`/v1/commitment-release/projects/${projectId}/assignments`);
}

export function putAssignments(projectId: string, assignments: AssignmentInput[]): Promise<Page<Assignment>> {
  return apiPut<Page<Assignment>>(`/v1/commitment-release/projects/${projectId}/assignments`, { assignments });
}

export function generateRoutes(projectId: string, force: boolean): Promise<{ tiers: Record<string, RouteReport> }> {
  return apiPost<{ tiers: Record<string, RouteReport> }>(`/v1/commitment-release/projects/${projectId}/routes/generate`, {
    force,
  });
}

export function pinTierRoute(projectId: string, tierCode: string, routeId: string): Promise<CommitmentMatrix> {
  return apiPut<CommitmentMatrix>(`/v1/commitment-release/projects/${projectId}/routes/${encodeURIComponent(tierCode)}`, { route_id: routeId });
}

/** Give a tier back to its generated route. */
export function unpinTierRoute(projectId: string, tierCode: string): Promise<CommitmentMatrix> {
  return apiDelete<CommitmentMatrix>(`/v1/commitment-release/projects/${projectId}/routes/${encodeURIComponent(tierCode)}`);
}

/* ── Items ────────────────────────────────────────────────────────────── */

export function listItems(projectId: string): Promise<ItemsResponse> {
  return apiGet<ItemsResponse>(`/v1/commitment-release/projects/${projectId}/items?today=${localToday()}&with_exposure=true`);
}

export function getItem(projectId: string, itemId: string): Promise<CommitmentItem> {
  return apiGet<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}?today=${localToday()}`);
}

export function createItem(projectId: string, body: ItemInput): Promise<CommitmentItem> {
  return apiPost<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items`, body);
}

export function updateItem(projectId: string, itemId: string, body: ItemInput): Promise<CommitmentItem> {
  return apiPatch<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}`, body);
}

export function holdItem(projectId: string, itemId: string, hold: boolean, reason: string): Promise<CommitmentItem> {
  return apiPost<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/hold`, { hold, reason });
}

export function addLink(projectId: string, itemId: string, kind: LinkKind, documentId: string): Promise<unknown> {
  return apiPost<unknown>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/links`, { kind, document_id: documentId });
}

export function removeLink(projectId: string, itemId: string, linkId: string): Promise<void> {
  return apiDelete(`/v1/commitment-release/projects/${projectId}/items/${itemId}/links/${linkId}`);
}

export function addPrecondition(
  projectId: string,
  itemId: string,
  body: { kind: PreconditionKind; ref_id?: string | null; text: string },
): Promise<CommitmentItem> {
  return apiPost<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/preconditions`, body);
}

/** Take a precondition off the item. The reason is kept on the record. */
export function removePrecondition(projectId: string, itemId: string, preconditionId: string, reason: string): Promise<void> {
  return apiDelete(`/v1/commitment-release/projects/${projectId}/items/${itemId}/preconditions/${preconditionId}?reason=${encodeURIComponent(reason)}`);
}

export function confirmPrecondition(
  projectId: string,
  itemId: string,
  preconditionId: string,
  body: { met: boolean; evidence_ref: string },
): Promise<CommitmentItem> {
  return apiPost<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/preconditions/${preconditionId}/confirm`, body);
}

/* ── Releases ─────────────────────────────────────────────────────────── */

export function previewRelease(projectId: string, itemId: string, body: ReleaseInput): Promise<ReleasePreview> {
  return apiPost<ReleasePreview>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/releases/preview`, body);
}

export function requestRelease(projectId: string, itemId: string, body: ReleaseInput): Promise<Release> {
  return apiPost<Release>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/releases`, body);
}

export function withdrawRelease(projectId: string, itemId: string, reason: string): Promise<Release> {
  return apiPost<Release>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/releases/withdraw`, { reason });
}

/** Approve or reject the pending request as a holder of its tier. */
export function decideRelease(projectId: string, itemId: string, body: DecisionInput): Promise<Release> {
  return apiPost<Release>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/releases/decide`, body);
}

/** Ask to stop the item. It is decided like a release, on the tier its residual loss calls for. */
export function previewAbort(projectId: string, itemId: string): Promise<AbortPreview> {
  return apiGet<AbortPreview>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/abort/preview`);
}

/**
 * Ask to stop the item. The external reference travels only when the loss is
 * above every tier, as the preview says; on any other loss the server refuses one.
 */
export function requestAbort(projectId: string, itemId: string, reason: string, externalRef = ''): Promise<Release> {
  return apiPost<Release>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/abort`, {
    reason,
    external_approval_ref: externalRef,
  });
}

/**
 * End the item as transferred. Its linked documents move to the target item;
 * they belong to this project, so an item with links stays inside it.
 */
export function transferItem(projectId: string, itemId: string, body: TransferInput): Promise<CommitmentItem> {
  return apiPost<CommitmentItem>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/transfer`, body);
}

/** Where the item may go: this project first, then the caller's other projects, each with the server's verdict. */
export function listTransferTargets(projectId: string, itemId: string): Promise<TransferTarget[]> {
  // The route answers the list envelope; the form needs the rows only.
  const answer = apiGet<Page<TransferTarget>>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/transfer-targets`);
  return answer.then((page) => page.items);
}

export function getReferences(projectId: string): Promise<References> {
  return apiGet<References>(`/v1/commitment-release/projects/${projectId}/references`);
}

export function listReleases(projectId: string, itemId: string): Promise<Page<Release>> {
  return apiGet<Page<Release>>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/releases`);
}

/* ── Abort terms and exposure ─────────────────────────────────────────── */

export function listAbortTerms(projectId: string, itemId: string): Promise<Page<AbortTerms>> {
  return apiGet<Page<AbortTerms>>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/abort-terms`);
}

export function putAbortTerms(projectId: string, itemId: string, body: AbortTermsInput): Promise<AbortTerms> {
  return apiPut<AbortTerms>(`/v1/commitment-release/projects/${projectId}/items/${itemId}/abort-terms`, body);
}

export function getExposure(projectId: string, asOf: string): Promise<ExposureResponse> {
  return apiGet<ExposureResponse>(`/v1/commitment-release/projects/${projectId}/exposure?as_of=${asOf}`);
}

export function listScenarios(projectId: string): Promise<Page<Scenario>> {
  return apiGet<Page<Scenario>>(`/v1/commitment-release/projects/${projectId}/scenarios`);
}

export function saveScenario(projectId: string, body: { as_of: string; label: string }): Promise<Scenario> {
  return apiPost<Scenario>(`/v1/commitment-release/projects/${projectId}/scenarios`, body);
}

/* ── Checks and export ────────────────────────────────────────────────── */

/** Ask what the guard would say to a new amount on a document. Nothing is written or recorded. */
export function checkDocument(projectId: string, body: CheckInput): Promise<CheckResult> {
  return apiPost<CheckResult>(`/v1/commitment-release/projects/${projectId}/check`, body);
}

export function listFindings(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/commitment-release/projects/${projectId}/validation?today=${localToday()}`);
}

export function downloadMatrix(projectId: string, format: 'pdf' | 'xlsx'): Promise<void> {
  return downloadWithAuth(
    `${API_BASE}/v1/commitment-release/projects/${projectId}/export?format=${format}&as_of=${localToday()}`,
    `commitment_matrix.${format}`,
  );
}
