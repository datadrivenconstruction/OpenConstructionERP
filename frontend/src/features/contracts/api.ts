// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Contracts module (type-rich construction contracts).
 *
 * Backed by /api/v1/contracts/ — see backend/app/modules/contracts/router.py
 * and schemas.py. The shapes here mirror the Pydantic response models
 * exactly so the page can drop into the API once it's mounted.
 *
 * Backwards-compat: the older `Contract` / `ProgressClaim` / `FinalAccount`
 * names from the previous skeleton are re-exported under their original
 * aliases at the bottom so any in-flight call sites still type-check.
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiPut,
  apiDelete,
  getAuthToken,
  triggerDownload,
} from '@/shared/lib/api';
import type { Page } from '@/shared/lib/api';

/* ── Enums / unions ───────────────────────────────────────────────────── */

export type ContractType =
  | 'lump_sum'
  | 'gmp'
  | 'cost_plus'
  | 'tm'
  | 'unit_price'
  | 'design_build'
  | 'combination'
  | 'remeasurement';

export type CounterpartyType = 'client' | 'subcontractor';

export type ContractStatus =
  | 'draft'
  | 'active'
  | 'suspended'
  | 'completed'
  | 'terminated';

export type RetentionReleaseEvent =
  | 'practical_completion'
  | 'final_account'
  | 'handover';

export type ContractLineType =
  | 'work'
  | 'material'
  | 'labor'
  | 'fee'
  | 'contingency'
  | 'allowance';

export type ClaimStatus =
  | 'draft'
  | 'submitted'
  | 'approved'
  | 'certified'
  | 'paid'
  | 'rejected';

export type FinalAccountStatus = 'draft' | 'agreed' | 'disputed' | 'closed';

export type FeeType = 'percent_of_cost' | 'fixed' | 'sliding_scale';

export type OverrunResponsibility = 'contractor' | 'shared' | 'owner';

/* ── Domain models ────────────────────────────────────────────────────── */

export interface ContractItem {
  id: string;
  code: string;
  title: string;
  contract_type: ContractType;
  counterparty_type: CounterpartyType;
  counterparty_id: string | null;
  project_id: string;
  parent_contract_id: string | null;
  start_date: string | null;
  end_date: string | null;
  total_value: number | string;
  original_contract_value: number | string | null;
  currency: string;
  retention_percent: number | string;
  retention_release_event: RetentionReleaseEvent;
  status: ContractStatus;
  signed_at: string | null;
  /**
   * The clause template the contract was drawn from, pinned as a pair. Version
   * 0 means a built-in standard form, which carries no versions of its own, so
   * zero is a complete answer here and not a missing one. Both are null on a
   * contract written from scratch.
   */
  template_code: string | null;
  template_version: number | null;
  terms: Record<string, unknown>;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContractLine {
  id: string;
  contract_id: string;
  parent_line_id: string | null;
  code: string;
  description: string;
  scope_section: string | null;
  line_type: ContractLineType;
  unit: string | null;
  quantity: number | string;
  unit_rate: number | string;
  total_value: number | string;
  order_index: number;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProgressClaimItem {
  id: string;
  contract_id: string;
  claim_number: string;
  period_start: string | null;
  period_end: string | null;
  claim_date: string | null;
  gross_amount: number | string;
  retention_amount: number | string;
  prior_claims_total: number | string;
  net_due: number | string;
  status: ClaimStatus;
  submitted_at: string | null;
  approved_at: string | null;
  paid_at: string | null;
  currency: string;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ProgressClaimLine {
  id: string;
  progress_claim_id: string;
  contract_line_id: string;
  period_completed_qty: number | string;
  period_completed_value: number | string;
  period_completed_pct: number | string;
  cumulative_completed_value: number | string;
  created_at: string;
  updated_at: string;
}

export interface FinalAccountItem {
  id: string;
  contract_id: string;
  final_contract_value: number | string;
  total_paid: number | string;
  retention_held: number | string;
  retention_released: number | string;
  final_balance: number | string;
  sign_off_date: string | null;
  sign_off_by: string | null;
  status: FinalAccountStatus;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface RetentionScheduleItem {
  id: string;
  contract_id: string;
  accrual_rule: Record<string, unknown>;
  release_rule: Record<string, unknown>;
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface FeeStructureItem {
  id: string;
  contract_id: string;
  fee_type: FeeType;
  fee_percent: number | string;
  fee_fixed_amount: number | string | null;
  sliding_scale: Record<string, unknown>[];
  max_fee: number | string | null;
  created_at: string;
  updated_at: string;
}

export interface GainshareConfigurationItem {
  id: string;
  contract_id: string;
  target_cost: number | string;
  gmp_cap: number | string;
  savings_split_owner_pct: number | string;
  savings_split_contractor_pct: number | string;
  overrun_responsibility: OverrunResponsibility;
  created_at: string;
  updated_at: string;
}

export interface LDClauseItem {
  id: string;
  contract_id: string;
  per_day_amount: number | string;
  currency: string;
  max_amount: number | string | null;
  milestone_id: string | null;
  enforcement_status: 'active' | 'waived';
  created_at: string;
  updated_at: string;
}

export interface ContractDashboard {
  contract_id: string;
  total_value: number | string;
  original_contract_value: number | string | null;
  agreed_variations: number | string;
  current_contract_value: number | string;
  pending_variations: number | string;
  forecast_contract_value: number | string;
  paid_to_date: number | string;
  retention_held: number | string;
  outstanding: number | string;
  claims_count: number;
  change_orders_count: number;
  gainshare_estimate: number | string | null;
  status: ContractStatus;
}

export interface ContractTypeConfiguration {
  id: string;
  contract_type: ContractType;
  display_name: string;
  allowed_fields: string[];
  default_fee_structure: Record<string, unknown>;
  schema_version: string;
}

/* ── Payloads ─────────────────────────────────────────────────────────── */

export interface ContractCreatePayload {
  code: string;
  title?: string;
  contract_type: ContractType;
  counterparty_type?: CounterpartyType;
  counterparty_id?: string | null;
  project_id: string;
  parent_contract_id?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  total_value?: number;
  currency?: string;
  retention_percent?: number;
  retention_release_event?: RetentionReleaseEvent;
  status?: ContractStatus;
  signed_at?: string | null;
  /**
   * The clause template this contract is drawn from, if any. Only the code is
   * sent: the server resolves the version and stores the pair, so the contract
   * keeps naming the version it actually used after a later one is published.
   */
  template_code?: string | null;
  terms?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
}

export type ContractUpdatePayload = Partial<Omit<ContractCreatePayload, 'project_id'>>;

export interface ContractLineCreatePayload {
  contract_id: string;
  parent_line_id?: string | null;
  code?: string;
  description?: string;
  scope_section?: string | null;
  line_type?: ContractLineType;
  unit?: string | null;
  quantity?: number;
  unit_rate?: number;
  order_index?: number;
  metadata?: Record<string, unknown>;
}

export interface ProgressClaimCreatePayload {
  contract_id: string;
  claim_number?: string | null;
  period_start?: string | null;
  period_end?: string | null;
  claim_date?: string | null;
  currency?: string;
  metadata?: Record<string, unknown>;
}

export interface FinalAccountCreatePayload {
  contract_id: string;
  final_contract_value?: number;
  total_paid?: number;
  retention_held?: number;
  retention_released?: number;
  final_balance?: number;
  sign_off_date?: string | null;
  sign_off_by?: string | null;
  status?: FinalAccountStatus;
  notes?: string | null;
}

/* ── List filters ─────────────────────────────────────────────────────── */

export interface ContractFilters {
  project_id: string;
  status?: ContractStatus | '';
  contract_type?: ContractType | '';
  counterparty_type?: CounterpartyType | '';
  offset?: number;
  limit?: number;
}

/* ── Internal helpers ─────────────────────────────────────────────────── */

function normaliseList<T>(res: T[] | { items: T[] } | null | undefined): T[] {
  if (!res) return [];
  if (Array.isArray(res)) return res;
  return res.items ?? [];
}

async function safeGetList<T>(path: string): Promise<T[]> {
  try {
    const res = await apiGet<T[] | { items: T[] }>(path);
    return normaliseList(res);
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'status' in err) {
      const status = (err as { status: number }).status;
      if (status === 404 || status === 501) return [];
    }
    throw err;
  }
}

/**
 * The paged counterpart of `safeGetList`, for the routes that answer with an
 * envelope. It is a separate helper rather than a widening of that one because
 * the two cannot share a return type: `safeGetList` exists to flatten the
 * envelope away, which is the thing this programme is undoing.
 *
 * It takes the request rather than the path, so the caller writes its own
 * `apiGet<Page<Row>>` and names the row type at the point of the request. That
 * reads better, and it is also what lets a caller be checked: a helper that
 * takes a path hides both the type argument and the URL inside itself, and
 * `scripts/check_page_envelope_consumers.py` binds a URL literal to the call
 * it stands next to. Through a path-taking helper the two are never adjacent
 * and every caller is invisible to the gate.
 *
 * The absent-module fallback reports zero of zero. That is a statement about
 * the module not being mounted rather than a count of the register, so nothing
 * should read a zero from here as evidence that a project has no contracts.
 */
async function safePage<T>(request: Promise<Page<T>>): Promise<Page<T>> {
  try {
    return await request;
  } catch (err: unknown) {
    if (err && typeof err === 'object' && 'status' in err) {
      const status = (err as { status: number }).status;
      if (status === 404 || status === 501) {
        return { items: [], total: 0, offset: 0, limit: 0 };
      }
    }
    throw err;
  }
}

/* ── Contracts ────────────────────────────────────────────────────────── */

export function listContracts(filters: ContractFilters): Promise<Page<ContractItem>> {
  const qs = new URLSearchParams();
  qs.set('project_id', filters.project_id);
  if (filters.status) qs.set('status', filters.status);
  if (filters.contract_type) qs.set('contract_type', filters.contract_type);
  if (filters.counterparty_type) qs.set('counterparty_type', filters.counterparty_type);
  if (filters.offset !== undefined) qs.set('offset', String(filters.offset));
  if (filters.limit !== undefined) qs.set('limit', String(filters.limit));
  return safePage(apiGet<Page<ContractItem>>(`/v1/contracts/contracts/?${qs.toString()}`));
}

export function getContract(id: string): Promise<ContractItem> {
  return apiGet<ContractItem>(`/v1/contracts/contracts/${id}`);
}

export function createContract(data: ContractCreatePayload): Promise<ContractItem> {
  return apiPost<ContractItem>('/v1/contracts/contracts/', data);
}

export function updateContract(
  id: string,
  data: ContractUpdatePayload,
): Promise<ContractItem> {
  return apiPatch<ContractItem>(`/v1/contracts/contracts/${id}`, data);
}

export function deleteContract(id: string): Promise<void> {
  return apiDelete(`/v1/contracts/contracts/${id}`);
}

export function signContract(id: string): Promise<ContractItem> {
  return apiPost<ContractItem>(`/v1/contracts/contracts/${id}/sign`, {});
}

export function suspendContract(id: string): Promise<ContractItem> {
  return apiPost<ContractItem>(`/v1/contracts/contracts/${id}/suspend`, {});
}

export function resumeContract(id: string): Promise<ContractItem> {
  return apiPost<ContractItem>(`/v1/contracts/contracts/${id}/resume`, {});
}

export function terminateContract(id: string): Promise<ContractItem> {
  return apiPost<ContractItem>(`/v1/contracts/contracts/${id}/terminate`, {});
}

export function getContractDashboard(id: string): Promise<ContractDashboard> {
  return apiGet<ContractDashboard>(`/v1/contracts/contracts/${id}/dashboard`);
}

/* ── Contract lines (SoV) ─────────────────────────────────────────────── */

export function listContractLines(contractId: string): Promise<ContractLine[]> {
  return safeGetList<ContractLine>(`/v1/contracts/contracts/${contractId}/lines`);
}

export function createContractLine(
  contractId: string,
  data: ContractLineCreatePayload,
): Promise<ContractLine> {
  return apiPost<ContractLine>(`/v1/contracts/contracts/${contractId}/lines`, data);
}

/* ── Progress claims ──────────────────────────────────────────────────── */

export function listProgressClaims(params: {
  contract_id: string;
  status?: ClaimStatus | '';
  offset?: number;
  limit?: number;
}): Promise<Page<ProgressClaimItem>> {
  const qs = new URLSearchParams();
  qs.set('contract_id', params.contract_id);
  if (params.status) qs.set('status', params.status);
  if (params.offset !== undefined) qs.set('offset', String(params.offset));
  if (params.limit !== undefined) qs.set('limit', String(params.limit));
  return safePage(
    apiGet<Page<ProgressClaimItem>>(`/v1/contracts/progress-claims/?${qs.toString()}`),
  );
}

export function getProgressClaim(id: string): Promise<ProgressClaimItem> {
  return apiGet<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}`);
}

export function createProgressClaim(
  data: ProgressClaimCreatePayload,
): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>('/v1/contracts/progress-claims/', data);
}

export function submitClaim(id: string): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}/submit`, {});
}

export function approveClaim(id: string): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}/approve`, {});
}

export function certifyClaim(id: string): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}/certify`, {});
}

export function rejectClaim(id: string): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}/reject`, {});
}

export function markClaimPaid(id: string): Promise<ProgressClaimItem> {
  return apiPost<ProgressClaimItem>(`/v1/contracts/progress-claims/${id}/mark-paid`, {});
}

export function listClaimLines(claimId: string): Promise<ProgressClaimLine[]> {
  return safeGetList<ProgressClaimLine>(`/v1/contracts/progress-claims/${claimId}/lines`);
}

export function updateClaimLine(
  lineId: string,
  data: {
    period_completed_qty?: number;
    period_completed_value?: number;
    period_completed_pct?: number;
    cumulative_completed_value?: number;
  },
): Promise<ProgressClaimLine> {
  return apiPatch<ProgressClaimLine>(
    `/v1/contracts/progress-claim-lines/${lineId}`,
    data,
  );
}

/* ── Progress bridge (Gap I) ──────────────────────────────────────────── */

export interface ProgressClaimPopulatePreviewItem {
  contract_line_id: string;
  contract_line_code: string;
  contract_line_description: string;
  boq_position_id: string;
  unit: string | null;
  contract_quantity: number | string;
  contract_line_value: number | string;
  observed_pct: number | string;
  period_label: string | null;
  recorded_at: string | null;
  period_completed_qty: number | string;
  period_completed_value: number | string;
  cumulative_completed_value: number | string;
}

export interface ProgressClaimPopulatePreview {
  claim_id: string;
  contract_id: string;
  currency: string;
  items: ProgressClaimPopulatePreviewItem[];
  skipped_unlinked: number;
  skipped_no_progress: number;
  skipped_foreign_currency: number;
  gross: number | string;
  retention: number | string;
  prior_claims_total: number | string;
  net_due: number | string;
}

export interface ProgressClaimCommitLine {
  contract_line_id: string;
  period_completed_pct: number;
  period_completed_value?: number;
}

/** Read-only preview of the claim lines derived from progress observations. */
export function populateClaimPreview(
  claimId: string,
  boqPositionIds?: string[],
): Promise<ProgressClaimPopulatePreview> {
  const qs = new URLSearchParams();
  (boqPositionIds ?? []).forEach((id) => qs.append('boq_position_ids', id));
  const suffix = qs.toString() ? `?${qs.toString()}` : '';
  return apiGet<ProgressClaimPopulatePreview>(
    `/v1/contracts/progress-claims/${claimId}/populate-from-progress${suffix}`,
  );
}

/** Commit a populated / edited set of claim lines; server re-rolls totals. */
export function commitClaimLines(
  claimId: string,
  lines: ProgressClaimCommitLine[],
): Promise<ProgressClaimItem> {
  return apiPut<ProgressClaimItem>(
    `/v1/contracts/progress-claims/${claimId}/commit-populated-lines`,
    { lines },
  );
}

/* ── Retention schedule ───────────────────────────────────────────────── */

export function getRetentionSchedule(scheduleId: string): Promise<RetentionScheduleItem> {
  return apiGet<RetentionScheduleItem>(
    `/v1/contracts/retention-schedules/${scheduleId}`,
  );
}

/* ── Fee structure ────────────────────────────────────────────────────── */

export function getFeeStructure(feeId: string): Promise<FeeStructureItem> {
  return apiGet<FeeStructureItem>(`/v1/contracts/fee-structures/${feeId}`);
}

/* ── Gainshare ────────────────────────────────────────────────────────── */

export function getGainshareConfig(configId: string): Promise<GainshareConfigurationItem> {
  return apiGet<GainshareConfigurationItem>(
    `/v1/contracts/gainshare-configurations/${configId}`,
  );
}

/* ── LD clauses ───────────────────────────────────────────────────────── */

export function getLDClause(ldId: string): Promise<LDClauseItem> {
  return apiGet<LDClauseItem>(`/v1/contracts/ld-clauses/${ldId}`);
}

/* ── Final accounts ───────────────────────────────────────────────────── */

export function getFinalAccount(accountId: string): Promise<FinalAccountItem> {
  return apiGet<FinalAccountItem>(`/v1/contracts/final-accounts/${accountId}`);
}

export function createFinalAccount(
  data: FinalAccountCreatePayload,
): Promise<FinalAccountItem> {
  return apiPost<FinalAccountItem>('/v1/contracts/final-accounts/', data);
}

export function closeContract(
  contractId: string,
  data: FinalAccountCreatePayload,
): Promise<FinalAccountItem> {
  return apiPost<FinalAccountItem>(
    `/v1/contracts/contracts/${contractId}/close`,
    { ...data, contract_id: contractId },
  );
}

/* ── Type configurations ──────────────────────────────────────────────── */

export function listTypeConfigurations(): Promise<ContractTypeConfiguration[]> {
  return safeGetList<ContractTypeConfiguration>('/v1/contracts/type-configurations/');
}

/* ── Clone (deep-copy a contract into draft) ──────────────────────────── */

export interface ContractClonePayload {
  new_code: string;
  new_title?: string | null;
  target_project_id?: string | null;
  include_lines?: boolean;
  copy_subconfigs?: boolean;
}

export function cloneContract(
  contractId: string,
  data: ContractClonePayload,
): Promise<ContractItem> {
  return apiPost<ContractItem>(
    `/v1/contracts/contracts/${contractId}/clone`,
    data,
  );
}

/* ── Clause templates (FIDIC / JCT / NEC / AIA / ConsensusDocs) ───────── */

/**
 * One row of the catalogue, from either half of the namespace.
 *
 * `source` says which half: `builtin` are the standard forms the platform
 * ships as constants, `authored` are the tenant's own versioned paper.
 * `editable` is the answer to "may the pencil be drawn", which is false for
 * both a built-in and a published version. `version` is 0 for a built-in
 * rather than null, so sorting on it never has to branch on the type.
 */
export interface ClauseTemplate {
  code: string;
  name: string;
  family: string;
  description?: string;
  retention_release_event: string;
  clause_count: number;
  source: 'builtin' | 'authored';
  editable: boolean;
  version: number;
  status: TemplateStatus;
  derived_from_builtin?: string | null;
  template_id?: string | null;
}

export type TemplateStatus = 'draft' | 'published' | 'archived';
export type ClauseRiskLevel = 'none' | 'low' | 'medium' | 'high';

export interface TemplateClause {
  id?: string | null;
  number: string;
  title: string;
  body: string;
  sort_order: number;
  risk_level: ClauseRiskLevel;
  risk_note: string;
  is_optional: boolean;
}

/** One template version. Built-ins answer in this shape too, at version 0. */
export interface ClauseTemplateDetail extends ClauseTemplate {
  id?: string | null;
  lineage_id?: string | null;
  published_at?: string | null;
  published_by?: string | null;
  clauses: TemplateClause[];
}

export interface ClauseTemplateCreatePayload {
  code: string;
  name: string;
  family?: string;
  description?: string;
  retention_release_event?: RetentionReleaseEvent;
  clauses?: TemplateClause[];
}

export interface ClauseTemplateUpdatePayload {
  name?: string;
  family?: string;
  description?: string;
  retention_release_event?: RetentionReleaseEvent;
}

export function listClauseTemplates(): Promise<ClauseTemplate[]> {
  return safeGetList<ClauseTemplate>('/v1/contracts/contract-templates/');
}

export function getClauseTemplate(
  code: string,
  version?: number,
): Promise<ClauseTemplateDetail> {
  const q = version === undefined ? '' : `?version=${version}`;
  return apiGet<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}${q}`,
  );
}

/**
 * One entry of a version history. Deliberately narrower than ClauseTemplate:
 * a built-in answers here with a single frozen row that carries no family and
 * no clause count, so one history screen serves both halves of the catalogue.
 */
export interface TemplateVersionRow {
  code: string;
  version: number;
  status: TemplateStatus;
  name: string;
  source: 'builtin' | 'authored';
  editable: boolean;
  published_at?: string | null;
  published_by?: string | null;
}

export function listClauseTemplateVersions(
  code: string,
): Promise<TemplateVersionRow[]> {
  return safeGetList<TemplateVersionRow>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions`,
  );
}

export function createClauseTemplate(
  data: ClauseTemplateCreatePayload,
): Promise<ClauseTemplateDetail> {
  return apiPost<ClauseTemplateDetail>('/v1/contracts/contract-templates/', data);
}

export function forkClauseTemplate(
  code: string,
  data: { new_code: string; new_name?: string | null },
): Promise<ClauseTemplateDetail> {
  return apiPost<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/fork`,
    data,
  );
}

export function updateClauseTemplate(
  code: string,
  version: number,
  data: ClauseTemplateUpdatePayload,
): Promise<ClauseTemplateDetail> {
  return apiPatch<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions/${version}`,
    data,
  );
}

/**
 * Replace the whole clause set of a draft.
 *
 * Whole-set rather than per-clause because numbering and order are one
 * document: renumbering 14.3 to 14.4 while 14.4 still exists is a legal edit
 * of the document and an illegal sequence of row updates.
 */
export function setClauseTemplateClauses(
  code: string,
  version: number,
  clauses: TemplateClause[],
): Promise<ClauseTemplateDetail> {
  return apiPut<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions/${version}/clauses`,
    { clauses },
  );
}

export function publishClauseTemplate(
  code: string,
  version: number,
): Promise<ClauseTemplateDetail> {
  return apiPost<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions/${version}/publish`,
    {},
  );
}

/** Open version N+1 as a draft. This is what editing published paper means. */
export function openNextClauseTemplateVersion(
  code: string,
): Promise<ClauseTemplateDetail> {
  return apiPost<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions`,
    {},
  );
}

export function archiveClauseTemplateVersion(
  code: string,
  version: number,
): Promise<ClauseTemplateDetail> {
  return apiPost<ClauseTemplateDetail>(
    `/v1/contracts/contract-templates/${encodeURIComponent(code)}/versions/${version}/archive`,
    {},
  );
}

/* ── Compliance gate (Item #27) ───────────────────────────────────────── */

export interface ComplianceViolation {
  rule_id: string;
  rule_name: string;
  severity: 'error' | 'warning' | 'info';
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface ComplianceGateReport {
  contract_id: string;
  contract_status: ContractStatus;
  rule_packs: string[];
  rule_sets: string[];
  status: 'passed' | 'warnings' | 'errors' | 'skipped';
  score: number | null;
  blocked: boolean;
  counts: { errors: number; warnings: number; passed: number };
  errors: ComplianceViolation[];
  warnings: ComplianceViolation[];
}

/** Shape of the structured 422 body returned when the sign gate blocks. */
export interface ComplianceGateError {
  error: 'compliance_gate_failed';
  message: string;
  rule_packs: string[];
  rule_sets: string[];
  status: 'passed' | 'warnings' | 'errors' | 'skipped';
  score: number | null;
  counts: { errors: number; warnings: number; passed: number };
  errors: ComplianceViolation[];
  warnings: ComplianceViolation[];
}

export interface ComplianceRulePack {
  id: string;
  name: string;
  description?: string;
  jurisdiction: string | null;
  enforced_workflows: string[];
  rule_sets: string[];
}

/** Read-only preview of the compliance gate (does not transition the contract). */
export function previewComplianceGate(
  contractId: string,
): Promise<ComplianceGateReport> {
  return apiGet<ComplianceGateReport>(
    `/v1/contracts/contracts/${contractId}/compliance-gate`,
  );
}

/** List the jurisdiction compliance rule-pack catalogue. */
export function listComplianceRulePacks(): Promise<ComplianceRulePack[]> {
  return safeGetList<ComplianceRulePack>('/v1/contracts/compliance-rule-packs/');
}

/**
 * Narrow a thrown {@link ApiError} body to a {@link ComplianceGateError}.
 *
 * The sign endpoint returns HTTP 422 with this structured detail when the
 * compliance gate blocks. Returns the parsed detail or `null` when the error
 * is something else (so the caller can fall back to a plain toast).
 */
export function asComplianceGateError(err: unknown): ComplianceGateError | null {
  if (!err || typeof err !== 'object') return null;
  const body = (err as { body?: unknown }).body;
  const detail =
    body && typeof body === 'object'
      ? (body as { detail?: unknown }).detail
      : undefined;
  if (
    detail &&
    typeof detail === 'object' &&
    (detail as { error?: unknown }).error === 'compliance_gate_failed'
  ) {
    return detail as ComplianceGateError;
  }
  return null;
}

/* ── AIA G702/G703 payment applications (US/CA/AU only) ───────────────── */
//
// These mirror the backend AIAApplicationResponse / AIAG702Summary /
// AIAG703Line / AIACertification schemas. The endpoints are country-gated on
// the server (404 for non-US/CA/AU projects), and the UI is additionally gated
// off project.is_aia_eligible so it never renders elsewhere.

export interface AIAG703Line {
  line_number: number;
  item_number: string;
  description: string;
  scheduled_value: string;
  previous_value: string;
  this_period_value: string;
  materials_stored: string;
  total_completed_stored: string;
  percent_complete: string;
  balance_to_finish: string;
  retainage: string;
}

export interface AIAG702Summary {
  original_contract_sum: string;
  change_orders_net: string;
  contract_sum_to_date: string;
  total_completed_stored: string;
  retainage: string;
  total_earned_less_retainage: string;
  previous_certificates_total: string;
  current_payment_due: string;
  balance_to_finish: string;
}

export interface AIACertification {
  architect_certified_at?: string | null;
  architect_certified_by?: string | null;
  owner_certified_at?: string | null;
  owner_certified_by?: string | null;
  certified_amount?: string | null;
}

export interface AIAApplication {
  claim_id: string;
  contract_id: string;
  project_id: string;
  application_number: string;
  period_start?: string | null;
  period_end?: string | null;
  claim_date?: string | null;
  currency: string;
  claim_status: ClaimStatus;
  retainage_percent: string;
  summary: AIAG702Summary;
  lines: AIAG703Line[];
  certification: AIACertification;
}

/**
 * Fetch the AIA G702 summary + G703 continuation for a progress claim.
 *
 * The backend raises 404 for non-US/CA/AU projects, so callers must only hit
 * this when {@link Project.is_aia_eligible} is true.
 */
export function getAiaApplication(claimId: string): Promise<AIAApplication> {
  return apiGet<AIAApplication>(
    `/v1/contracts/progress-claims/${encodeURIComponent(claimId)}/aia-application`,
  );
}

/**
 * Download the AIA G702/G703 application as a PDF.
 *
 * Mirrors the blob-download pattern used by the BOQ / Daily-Diary exports:
 * fetch with the stored bearer token, then stream the response to a file.
 */
export async function downloadAiaApplicationPdf(
  claimId: string,
  applicationNumber?: string,
): Promise<void> {
  const token = getAuthToken();
  const res = await fetch(
    `/api/v1/contracts/progress-claims/${encodeURIComponent(claimId)}/aia-application/pdf`,
    { headers: token ? { Authorization: `Bearer ${token}` } : {} },
  );
  if (!res.ok) {
    let message = `Export failed (${res.status})`;
    try {
      const body = await res.json();
      if (body?.detail) message = String(body.detail);
    } catch {
      // Non-JSON error body — keep the status-code message.
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  triggerDownload(blob, `AIA_G702_${applicationNumber || claimId}.pdf`);
}

/* ── Contract analytics (detail-view panels) ──────────────────────────── */
//
// Four read-only analytics endpoints that hang off a single contract. All are
// GET, permission `contracts.read`, path param `contract_id`. They mirror the
// backend shapes in contracts/router.py and contracts/service.py exactly. Money
// is a decimal STRING on the wire (the SoV router coerces Decimals to strings);
// we type money as `number | string` for parity with ContractItem and coerce at
// the call site.

/** One Schedule-of-Values line's billed-vs-earned-vs-paid position. */
export interface SovStatusLine {
  scheduled: number | string;
  billed: number | string;
  earned: number | string;
  paid: number | string;
  retained: number | string;
  net_paid: number | string;
  /** Earned / scheduled × 100, already rounded server-side (a plain number). */
  percent_complete: number;
}

/** Totals row for the SoV status table. Note: no `net_paid` at the total level. */
export interface SovStatusTotals {
  scheduled: number | string;
  billed: number | string;
  earned: number | string;
  paid: number | string;
  retained: number | string;
  percent_complete: number;
}

export interface SovStatusResponse {
  /** Keyed by contract-line id (UUID string), in contract-line order. */
  by_line: Record<string, SovStatusLine>;
  totals: SovStatusTotals;
}

/** Per-line scheduled/billed/earned/paid + totals for a contract's SoV. */
export function getSovStatus(contractId: string): Promise<SovStatusResponse> {
  return apiGet<SovStatusResponse>(
    `/v1/contracts/contracts/${contractId}/sov-status`,
  );
}

/** One finding from the contracts completeness rule set (parties/security/EOT). */
export interface CompletenessFinding {
  rule_id: string;
  rule_name: string;
  severity: 'error' | 'warning' | 'info';
  passed: boolean;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/** Overall validation status (mirrors backend ValidationStatus enum). */
export type CompletenessStatus =
  | 'passed'
  | 'warnings'
  | 'errors'
  | 'info'
  | 'skipped'
  | 'unsupported';

export interface CompletenessReport {
  contract_id: string;
  status: CompletenessStatus;
  score: number | null;
  summary: {
    id?: string | null;
    status: string;
    score: number | null;
    counts: {
      total: number;
      passed: number;
      errors: number;
      warnings: number;
      infos: number;
      engine_errors: number;
    };
    rule_sets?: string[];
    supported_rule_sets?: string[];
    unsupported_rule_sets?: string[];
    duration_ms?: number;
  };
  errors: CompletenessFinding[];
  warnings: CompletenessFinding[];
}

/** Run the contracts rule set over a contract for a traffic-light panel. */
export function getContractCompleteness(
  contractId: string,
): Promise<CompletenessReport> {
  return apiGet<CompletenessReport>(
    `/v1/contracts/contracts/${contractId}/completeness`,
  );
}

/** Aggregate extension-of-time exposure for a contract. */
export interface EotSummary {
  contract_id: string;
  claims_count: number;
  pending_count: number;
  decided_count: number;
  total_days_claimed: number;
  total_days_granted: number;
  /** ISO date of the latest revised completion date, or null when none set. */
  latest_revised_completion_date: string | null;
}

export function getEotSummary(contractId: string): Promise<EotSummary> {
  return apiGet<EotSummary>(
    `/v1/contracts/contracts/${contractId}/eot-summary`,
  );
}

export type FinalAccountCheckStatus = 'pass' | 'fail' | 'not_applicable';

/** One close-out condition in the final-account readiness checklist. */
export interface FinalAccountCheckItem {
  /** Stable identifier, e.g. `progress_claims_settled` (safe for i18n wiring). */
  key: string;
  status: FinalAccountCheckStatus;
  reason: string;
  based_on: Record<string, string>;
}

export interface FinalAccountChecklist {
  contract_id: string;
  ready: boolean;
  /** Passed / applicable × 100 (a Decimal on the wire; coerce with toNum). */
  completion_percent: number | string;
  passed_count: number;
  applicable_count: number;
  total_count: number;
  items: FinalAccountCheckItem[];
}

/** Close-out readiness checklist for a contract. */
export function getFinalAccountChecklist(
  contractId: string,
): Promise<FinalAccountChecklist> {
  return apiGet<FinalAccountChecklist>(
    `/v1/contracts/contracts/${contractId}/final-account-checklist`,
  );
}

/* ── Gain-share preview (GMP target-cost) ─────────────────────────────── */
//
// GET /contracts/{id}/gainshare-preview?actual_cost=… returns the gain / pain
// split for a hypothetical out-turn cost. It is only valid for GMP contracts
// (400 otherwise) and needs a gain-share configuration (404 otherwise). Money
// fields are Decimal on the wire (typed number | string; coerce with toNum).
// Note: the response carries no currency, so callers pass the contract's.

/** GMP gain / pain split computed for a given out-turn cost. */
export interface GainshareCalculation {
  actual_cost: number | string;
  target_cost: number | string;
  gmp_cap: number | string;
  /** Under-run below target, shared between owner and contractor. */
  savings: number | string;
  owner_share: number | string;
  contractor_share: number | string;
  /** Over-run above target. */
  overrun: number | string;
  /** Who carries the over-run, e.g. `contractor` / `owner` / `shared`. */
  overrun_responsibility: string;
}

/** Preview the gain / pain split for a GMP contract at a given out-turn cost. */
export function getGainsharePreview(
  contractId: string,
  actualCost: number | string,
): Promise<GainshareCalculation> {
  const qs = new URLSearchParams({ actual_cost: String(actualCost) });
  return apiGet<GainshareCalculation>(
    `/v1/contracts/contracts/${contractId}/gainshare-preview?${qs.toString()}`,
  );
}

/* ── Security / bonds coverage ────────────────────────────────────────── */

/** Bonds / guarantees / insurance held against a contract, summarised. */
export interface SecurityCoverage {
  contract_id: string;
  currency: string;
  /** Total securities recorded, in any status. */
  count: number;
  /** How many are currently `active`. */
  active_count: number;
  /** Sum of active security amounts (Decimal on the wire; coerce with toNum). */
  total_active_amount: number | string;
  /** Count of securities per status, e.g. `{ required: 1, active: 2 }`. */
  by_status: Record<string, number>;
  /** Distinct security types among the active ones, sorted. */
  active_types: string[];
}

/** Summary of bonds / guarantees / insurance held on a contract. */
export function getSecurityCoverage(
  contractId: string,
): Promise<SecurityCoverage> {
  return apiGet<SecurityCoverage>(
    `/v1/contracts/contracts/${contractId}/security-coverage`,
  );
}

/* ── Security register (the rows behind the coverage summary) ─────────── */

/**
 * The instruments a contract can be secured with, ordered the way a commercial
 * manager reads them: the bonds, then the guarantees, then the insurance lines.
 * Mirrors SECURITY_TYPES in the module's schemas; a value outside this list is
 * refused by the API rather than stored.
 */
export const CONTRACT_SECURITY_TYPES = [
  'performance_bond',
  'payment_bond',
  'advance_payment_bond',
  'retention_bond',
  'parent_company_guarantee',
  'bank_guarantee',
  'insurance_pl',
  'insurance_car',
  'insurance_pi',
  'other',
] as const;

export type ContractSecurityType = (typeof CONTRACT_SECURITY_TYPES)[number];

/**
 * The life of one instrument, from the clause that demands it to the day it is
 * given back or called. Mirrors SECURITY_STATUSES in the module's schemas.
 */
export const CONTRACT_SECURITY_STATUSES = [
  'required',
  'received',
  'active',
  'expired',
  'released',
  'claimed',
] as const;

export type ContractSecurityStatus =
  (typeof CONTRACT_SECURITY_STATUSES)[number];

export interface ContractSecurity {
  id: string;
  contract_id: string;
  security_type: string;
  /** The instrument's own number, as the issuer wrote it. */
  reference: string | null;
  /** The issuer: the bank, surety or insurer standing behind the instrument. */
  provider_name: string;
  /** Face value. Decimal on the wire, so keep the string when round-tripping. */
  amount: number | string;
  /** Per row, not per contract: a bond can be issued in another currency. */
  currency: string;
  /** Decimal on the wire; null when the row was entered as a flat sum. */
  percent_of_contract: number | string | null;
  /** ISO YYYY-MM-DD, or null when the instrument has no stated start. */
  valid_from: string | null;
  /** ISO YYYY-MM-DD expiry, or null when it is open-ended. */
  valid_to: string | null;
  status: string;
  document_id: string | null;
  notes: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * Money and percent are typed `string` on the way in, never `number`. They are
 * Decimal columns and the wire form is the exact text that was typed; parsing
 * to a float here would send back a figure nobody entered. The date fields take
 * `YYYY-MM-DD` only — the schema rejects an empty string, so an unknown date is
 * omitted rather than blanked.
 */
export interface ContractSecurityCreate {
  contract_id: string;
  security_type: string;
  reference?: string | null;
  provider_name?: string;
  amount?: string;
  currency?: string;
  percent_of_contract?: string;
  valid_from?: string;
  valid_to?: string;
  status?: string;
  document_id?: string | null;
  notes?: string | null;
}

/**
 * PATCH body. Only the keys present are touched, and note the asymmetry the
 * service imposes: it drops nulls before writing, so a field cannot be cleared
 * by sending null. An empty string does clear the free-text fields; the dated
 * and numeric ones have no clear operation at all.
 */
export interface ContractSecurityUpdate {
  security_type?: string;
  reference?: string;
  provider_name?: string;
  amount?: string;
  currency?: string;
  percent_of_contract?: string;
  valid_from?: string;
  valid_to?: string;
  status?: string;
  document_id?: string | null;
  notes?: string;
}

/** Every bond, guarantee and insurance line recorded against a contract. */
export function listContractSecurities(
  contractId: string,
): Promise<ContractSecurity[]> {
  return apiGet<ContractSecurity[]>(
    `/v1/contracts/contracts/${contractId}/securities`,
  );
}

export function createContractSecurity(
  contractId: string,
  body: ContractSecurityCreate,
): Promise<ContractSecurity> {
  return apiPost<ContractSecurity>(
    `/v1/contracts/contracts/${contractId}/securities`,
    body,
  );
}

/**
 * Securities are addressed by their own id, not through the contract. Note the
 * doubled segment, as with the party register: the module router is mounted at
 * /v1/contracts and the route itself is /contracts/securities/{id}, so both
 * belong in the path.
 */
export function updateContractSecurity(
  securityId: string,
  body: ContractSecurityUpdate,
): Promise<ContractSecurity> {
  return apiPatch<ContractSecurity>(
    `/v1/contracts/contracts/securities/${securityId}`,
    body,
  );
}

export function deleteContractSecurity(securityId: string): Promise<void> {
  return apiDelete(`/v1/contracts/contracts/securities/${securityId}`);
}

/* ── Milestone payment schedule ───────────────────────────────────────── */

/** One resolved milestone in the payment schedule. */
export interface MilestoneScheduleItem {
  id: string;
  code: string;
  name: string;
  /** ISO date the milestone is planned for, or null when unscheduled. */
  planned_date: string | null;
  /** What releases the milestone, e.g. `date` / `completion` / `approval`. */
  trigger: string;
  /** One of `pending` / `reached` / `invoiced` / `paid`. */
  status: string;
  /** Resolved milestone value (Decimal on the wire; coerce with toNum). */
  value: number | string;
}

export interface MilestoneSchedule {
  contract_id: string;
  currency: string;
  count: number;
  /** Total scheduled milestone value (Decimal on the wire; coerce with toNum). */
  scheduled_value: number | string;
  milestones: MilestoneScheduleItem[];
}

/** Resolve each milestone's value and the total scheduled milestone value. */
export function getMilestoneSchedule(
  contractId: string,
): Promise<MilestoneSchedule> {
  return apiGet<MilestoneSchedule>(
    `/v1/contracts/contracts/${contractId}/milestone-schedule`,
  );
}

/* ── E-signature bridge ───────────────────────────────────────────────── */

/** One expected signatory on a session, derived from the party register. */
export interface ContractSignatory {
  name: string;
  role: string;
  required?: boolean;
}

/**
 * A signing session opened against a contract.
 *
 * `content_hash_current` and `stale_signatories` are the two fields the screen
 * exists for. A contract can be edited while it is out for signature, and when
 * that happens everyone who already signed signed different paper. The flag
 * drives the banner, the names drive the list of who has to sign again.
 */
export interface ContractSigningSession {
  id: string;
  document_ref: string;
  document_content_hash: string;
  provider_capability: string;
  delivered_capability: string | null;
  status: string;
  signatory_map: ContractSignatory[];
  expires_at: string | null;
  created_at: string | null;
  content_hash_current: boolean;
  stale_signatories: string[];
  signed_roles: string[];
}

export interface ContractSigningSessionOpen {
  provider_capability?: string;
  expires_at?: string | null;
  /** Override the map derived from the contract's parties. Rarely needed. */
  signatories?: ContractSignatory[];
}

/**
 * Put the contract up for signature.
 *
 * Runs the compliance gate first, so this rejects with 422 on a contract that
 * would be blocked at activation. That is the point: finding out after every
 * party has signed is finding out too late.
 */
export function openContractSigningSession(
  contractId: string,
  body: ContractSigningSessionOpen = {},
): Promise<ContractSigningSession> {
  return apiPost<ContractSigningSession>(
    `/v1/contracts/contracts/${contractId}/signing-session`,
    body,
  );
}

/** Every session ever opened against this contract, newest first. */
export function listContractSigningSessions(
  contractId: string,
): Promise<ContractSigningSession[]> {
  return apiGet<ContractSigningSession[]>(
    `/v1/contracts/contracts/${contractId}/signing-sessions`,
  );
}

/**
 * Bring the contract's own status in line with its signing session.
 *
 * A partly signed contract stays in draft; a fully signed one is transitioned
 * to active through the normal path, gate and audit included.
 */
export function syncContractFromSigning(
  contractId: string,
): Promise<ContractItem> {
  return apiPost<ContractItem>(
    `/v1/contracts/contracts/${contractId}/signing-session/sync`,
    {},
  );
}

/* ── Party register ───────────────────────────────────────────────────── */

/**
 * The roles a party can hold on a contract, in the order a signature block
 * puts them. Mirrors PARTY_ROLES in the module's schemas; a value outside this
 * list is refused by the API rather than stored.
 */
export const CONTRACT_PARTY_ROLES = [
  'employer',
  'contractor',
  'subcontractor',
  'consultant',
  'architect',
  'engineer',
  'guarantor',
  'other',
] as const;

export type ContractPartyRole = (typeof CONTRACT_PARTY_ROLES)[number];

/**
 * The roles that are asked to sign. Kept in step with SIGNING_PARTY_ROLES on
 * the backend, which is what actually decides: this copy only lets the screen
 * say which rows matter before the server is asked.
 */
export const SIGNING_PARTY_ROLES: readonly ContractPartyRole[] = [
  'employer',
  'contractor',
  'subcontractor',
];

export interface ContractParty {
  id: string;
  contract_id: string;
  party_role: string;
  party_type: string;
  party_id: string | null;
  display_name: string;
  /**
   * The name resolved from the linked contact, subcontractor or user, which is
   * current where display_name is a copy taken when the row was written. Null
   * when there is no link or it no longer resolves, and the caller falls back
   * to display_name.
   */
  resolved_name: string | null;
  is_primary: boolean;
  contact_details: Record<string, unknown>;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface ContractPartyCreate {
  contract_id: string;
  party_role: string;
  party_type?: string;
  party_id?: string | null;
  display_name: string;
  is_primary?: boolean;
}

/** The contract's parties, each with the live name resolved for it. */
export function listContractParties(
  contractId: string,
): Promise<ContractParty[]> {
  return apiGet<ContractParty[]>(
    `/v1/contracts/contracts/${contractId}/parties`,
  );
}

export function createContractParty(
  contractId: string,
  body: ContractPartyCreate,
): Promise<ContractParty> {
  return apiPost<ContractParty>(
    `/v1/contracts/contracts/${contractId}/parties`,
    body,
  );
}

/**
 * Parties are addressed by their own id, not through the contract. Note the
 * doubled segment: the module router is mounted at /v1/contracts and the route
 * itself is /contracts/parties/{id}, so both belong in the path. Dropping one
 * gives a 404 that looks like a missing row rather than a missing route.
 */
export function deleteContractParty(partyId: string): Promise<void> {
  return apiDelete(`/v1/contracts/contracts/parties/${partyId}`);
}

/* ── Back-compat aliases (old skeleton names) ─────────────────────────── */

export type Contract = ContractItem;
export type ProgressClaim = ProgressClaimItem;
export type FinalAccount = FinalAccountItem;
export type SoVLine = ContractLine;
