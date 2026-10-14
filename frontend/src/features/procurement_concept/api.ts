// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the procurement concept: award packages, procedures,
// prequalification, market sounding, the award schedule and framework
// agreements with their call-offs.
//
// Backend module: backend/app/modules/procurement_concept/router.py, mounted at
// /api/v1/procurement-concept/. Project routes live under /projects/{id}/,
// framework agreements are company level (/frameworks).
//
// Money travels as a decimal string in both directions. The server refuses a
// JSON number for an amount (422), so every amount here is typed `string`.
//
// Errors arrive as `detail = {code, message_key, message, violations?, info?}`.
// The screens read `code` to explain a refusal and list `violations` in full.

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type ConceptState = 'draft' | 'in_review' | 'approved' | 'binding' | 'reopened';
export type PackageState =
  | 'planned'
  | 'procedure_set'
  | 'shortlisted'
  | 'in_tender'
  | 'awarded'
  | 'cancelled'
  | 'on_hold';
export type FrameworkState = 'draft' | 'active' | 'expired' | 'exhausted' | 'terminated';
export type FrameworkTarget = Exclude<FrameworkState, 'draft'>;
export type ThresholdStatus = 'above' | 'below' | 'unconfirmed' | 'unresolved' | 'unavailable' | 'not_applicable';
export type PackageKind = 'design' | 'works' | 'supply' | 'supply_and_install' | 'services';
export type TenderBasis = 'detailed' | 'functional' | 'mixed';
export type SplitBasis = 'trade' | 'section' | 'system' | 'whole';
export type CandidateList = 'long' | 'short' | 'excluded';
export type CandidateSource = 'market_sounding' | 'own_list' | 'framework' | 'public_notice';
export type CapacitySignal = 'ample' | 'adequate' | 'tight' | 'insufficient';
export type PriceSignal = 'below_estimate' | 'in_line' | 'above_estimate' | 'unknown';
export type SoundingMethod = 'survey' | 'meeting' | 'rfi' | 'notice';
export type CallOffMode = 'direct' | 'mini_competition';
export type PackageAction = 'hold' | 'resume' | 'cancel';
export type ConceptAction = 'submit' | 'return' | 'approve' | 'reopen';
export type AdvanceReleaseKind = 'gate_decision' | 'condition' | 'commitment';
export type EvaluationMethod = 'lowest_price' | 'best_value';
export type CostRefKind = 'boq_section';
export type ExportPart = 'concept' | 'packages' | 'shortlist' | 'schedule';
export type ExportFormat = 'pdf' | 'xlsx';

/** One rule finding. `ref` is a package code, a candidate id or `profile`. */
export interface Finding {
  code: string;
  severity: 'error' | 'warning' | string;
  ref: string;
  blocks_approval: boolean;
  message_key?: string;
  reason?: string;
}

/** A catalogue name as the API sends it: a message key, and texts per locale for company catalogues. */
export interface Named {
  code: string;
  name_key?: string;
  labels?: Record<string, string> | null;
}

export interface CatalogueProcedure extends Named {
  sector: 'public' | 'private' | 'both';
  stages: 1 | 2;
  has_prequalification: boolean;
  negotiation_allowed: boolean;
  tender_basis_allowed: Array<'detailed' | 'functional'>;
  min_bidders: number | null;
}

export interface CatalogueCriterion extends Named {
  group: string;
  kind: 'pass_fail' | 'scored';
  default_weight: string;
}

/** A procurement law of the pinned catalogue. Its codes are the catalogue's own, never a fixed list. */
export interface CatalogueJurisdiction extends Named {
  client_types: string[];
  /** The client type of a client outside the public rules; a public client picks another one. */
  private_client_type?: string;
}

/** One thing the caller may do, with the refusal code when they may not. */
export interface Capability {
  allowed: boolean;
  reason: string | null;
  /**
   * False when the action makes no sense for the object as it is, whoever asks
   * (nothing to resume, already closed): the control is left out. True with
   * `allowed` false: the control stays visible, disabled, with the reason.
   */
  applies?: boolean;
}

/** The pinned catalogue body. Only the parts the screens read are typed. */
export interface PinnedCatalogue {
  id: string;
  version: number;
  name_key: string;
  labels?: Record<string, string> | null;
  review_status: 'verified' | 'unconfirmed' | string;
  procedures: CatalogueProcedure[];
  jurisdictions: CatalogueJurisdiction[];
  prequal_criteria: CatalogueCriterion[];
}

export interface CatalogueSummary {
  source: 'shipped' | 'tenant';
  id: string;
  code: string;
  name: { key: string | null; text: Record<string, string> | null };
  state: string;
  versions: number[];
  latest_version: number | null;
  review_status: string;
  /** The laws this catalogue brings. Empty for a company catalogue with no published version, which cannot be pinned. */
  jurisdictions?: CatalogueJurisdiction[];
}

export interface Concept {
  id: string;
  project_id: string;
  catalogue_source: 'shipped' | 'tenant';
  catalogue_id: string;
  catalogue_version: number;
  jurisdiction: string;
  client_type: string;
  public_client: boolean;
  vat_rate_pct: string;
  /** The state that counts: `binding` is read from the frame document, never stored here. */
  state: ConceptState;
  stored_state: ConceptState;
  governance_document_id: string | null;
  /** The gate named by hand; empty means the one the governance catalogue tags. */
  release_gate_code: string | null;
  /** The gate actually used. Null when none is named or tagged. */
  resolved_release_gate_code: string | null;
  /** The phase model opens procurement in its first phase: no gate releases it, and none is missing. */
  released_from_start?: boolean;
  /** False on a project that never adopted a phase model: it has no gates, so none releases procurement. */
  gates_in_use?: boolean;
  governance_area_code: string | null;
  default_profile_id: string | null;
  submitted_by: string | null;
  approved_by: string | null;
  approved_at: string | null;
  /** The person who submitted the concept also approved it. */
  four_eyes_violated: boolean;
  jurisdictions: CatalogueJurisdiction[];
  review_status: string;
  /** What the caller may do on this concept, decided by the server from the checks the writes enforce. */
  can: {
    steer: Capability;
    edit_plan: Capability;
    submit: Capability;
    return: Capability;
    set_gate_fields: Capability;
    /** Approval and reopening by hand exist only on a project without gates; with gates they do not apply. */
    approve: Capability;
    reopen: Capability;
  };
}

export interface ConceptInput {
  catalogue_source?: 'shipped' | 'tenant';
  catalogue_id?: string;
  jurisdiction?: string;
  client_type?: string;
  public_client?: boolean;
  vat_rate_pct?: string;
  release_gate_code?: string;
  default_profile_id?: string;
}

export interface Readiness {
  state: ConceptState | null;
  approved: boolean;
  submitted: boolean;
  blocking: number;
  ready_for_gate: boolean;
}

/** A gate of the project, for choosing the one that releases procurement. */
export interface GateOption {
  code: string;
  /** The name the governance model gives the gate: a message key for a shipped model, texts per locale for a company one. */
  label?: { key: string | null; text: Record<string, string> | null } | null;
  from_phase: string | null;
  to_phase: string | null;
  status: string;
  target_date: string | null;
  sort_order: number;
  /** The gate the governance catalogue tags as the one that releases procurement. */
  tagged_release_gate: boolean;
  selected: boolean;
}

/** An act of the release gate that can release an advance package. */
export interface AdvanceRelease {
  kind: AdvanceReleaseKind;
  id: string;
  /** Null for a commitment: it is released in the commitment matrix, not at a gate. */
  gate_code: string | null;
  label: string;
  status: string;
  date: string | null;
  /** False for an open condition: it may be named, but the package then stays unreleased. */
  releases: boolean;
}

/** A tender package of the project that an award package can be linked to. */
export interface TenderPackageOption {
  id: string;
  name: string;
  status: string;
  deadline: string | null;
  linked_package_id: string | null;
  linked_package_code: string | null;
  can: { link: Capability };
}

/** A bill of quantities section a package may name as the source of its scope lines. */
export interface CostSection {
  kind: CostRefKind;
  id: string;
  code: string;
  title: string;
  boq_id: string;
  boq_name: string;
  /** How many positions sit under the section, so how many scope lines the tender would get. */
  positions: number;
}

/** A list that also says what the caller may do on it as a whole. */
export type PageWithCan<T, K extends string> = Page<T> & { can: Record<K, Capability> };

export interface ContractPackage {
  id: string;
  code: string;
  title: string;
  kind: string;
  parent_id: string | null;
  scope: string;
  boq_ref: string;
  need_date: string | null;
  status: string;
  execution_link: { kind: string; id: string } | null;
}

export interface AwardPackage {
  id: string;
  split_basis: SplitBasis;
  is_advance: boolean;
  advance_reason: string;
  estimated_value: string | null;
  currency: string;
  lot_group: string;
  small_lot_exemption: boolean;
  procedure_code: string | null;
  tender_basis: TenderBasis | null;
  framework_agreement_id: string | null;
  evaluation_method: EvaluationMethod;
  need_date: string | null;
  /** The schedule milestone the need date is taken from, or null when it is typed. */
  need_activity_id: string | null;
  lead_time_days: number | null;
  procedure_days: number | null;
  planned_start: string | null;
  prequal_profile_id: string | null;
  start_activity_id: string | null;
  award_activity_id: string | null;
  state: PackageState;
  notes: string;
  /** The act of the release gate that releases this advance package (see `listAdvanceReleases`). */
  advance_release_kind?: AdvanceReleaseKind | null;
  advance_release_id?: string | null;
  /** Award criteria and their weights in percent. Empty when none are set. */
  evaluation_weights?: Record<string, string> | null;
  /** The BOQ section whose positions become the scope lines of the tender. Set together or not at all. */
  cost_ref_kind?: CostRefKind | null;
  cost_ref_id?: string | null;
  /** Only on the board: the value the threshold is tested against when lots are added up. */
  aggregated_value?: string | null;
}

export interface ThresholdRow {
  contract_kind: string;
  client_type: string;
  amount: string;
  currency: string;
  vat_basis: 'net' | 'gross';
  effect: string;
  source_url: string | null;
  review_status: 'verified' | 'unconfirmed' | string;
  valid_from: string | null;
  valid_to: string | null;
  compared_value: string | null;
  position?: 'above' | 'below';
}

export interface PackageView {
  contract_package: ContractPackage;
  /** Null when this kind of contract package is not procured as an award package. */
  package_kind: PackageKind | null;
  award: AwardPackage | null;
  threshold: {
    status: ThresholdStatus;
    allowed: string[] | null;
    thresholds: ThresholdRow[];
    small_lot_exempt: boolean;
    aggregated_value: string | null;
  } | null;
  schedule: { award_date: string | null; start_date: string | null; procedure_days: number } | null;
  /** What the caller may do with this package now. `create_execution` also answers for linking a tender package. */
  can: {
    edit: Capability;
    /** The advance switch and its release fields. Not applicable where no gate holds procurement back. */
    set_advance: Capability;
    hold: Capability;
    resume: Capability;
    cancel: Capability;
    confirm_shortlist: Capability;
    create_execution: Capability;
  };
}

export interface PackageInput {
  split_basis?: SplitBasis;
  is_advance?: boolean;
  advance_reason?: string;
  estimated_value?: string | null;
  currency?: string;
  lot_group?: string;
  small_lot_exemption?: boolean;
  procedure_code?: string | null;
  tender_basis?: TenderBasis | null;
  framework_agreement_id?: string | null;
  need_date?: string | null;
  need_activity_id?: string | null;
  lead_time_days?: number | null;
  prequal_profile_id?: string | null;
  notes?: string;
  /** Set or cleared together, from one item of `listAdvanceReleases`. */
  advance_release_kind?: AdvanceReleaseKind | null;
  advance_release_id?: string | null;
  evaluation_method?: EvaluationMethod;
  /** `{criterion: percent}` as decimal strings, summing to 100. An empty object clears them; null is refused. */
  evaluation_weights?: Record<string, string>;
  /** Set or cleared together. */
  cost_ref_kind?: CostRefKind | null;
  cost_ref_id?: string | null;
}

export interface ProcedureOption {
  code: string;
  name_key: string;
  allowed: boolean;
  reason: string | null;
}

export interface ThresholdCheck {
  package_id: string;
  checked_on: string;
  status: ThresholdStatus;
  single_value: string | null;
  aggregated_value: string | null;
  small_lot_exempt: boolean;
  thresholds: ThresholdRow[];
  procedures: ProcedureOption[];
  findings: Finding[];
}

export interface ExecutionResult {
  package_id: string;
  kind: 'bid_package' | 'rfq';
  id: string;
  lines: number;
}

export interface ProfileCriterion {
  code: string;
  kind?: 'pass_fail' | 'scored';
  weight: string;
}

export interface PrequalProfile {
  id: string;
  package_id: string | null;
  name: string;
  criteria: ProfileCriterion[];
  pass_mark: string;
  validity_months: number;
  /** The concept or a package uses it, so it cannot be deleted. */
  in_use: boolean;
  can: { edit: Capability; delete: Capability };
}

export interface ProfileInput {
  package_id: string | null;
  name: string;
  criteria: Array<{ code: string; weight: string }>;
  pass_mark: string;
  validity_months: number;
}

export interface CandidateScore {
  criterion_code: string;
  passed: boolean | null;
  score: string | null;
  note?: string;
}

export interface CandidateReference {
  id: string;
  project_name: string;
  client: string;
  value: string | null;
  currency: string;
  year: number | null;
  role: string;
  contact: string;
  verified: boolean;
}

export interface CandidateEvidence {
  kind: 'prequal_status' | 'certificate' | string;
  ref: string;
  status?: string;
  type?: string;
  expires: string | null;
  rating?: string | null;
}

export interface Candidate {
  id: string;
  package_id: string;
  subcontractor_id: string | null;
  vendor_id: string | null;
  name: string;
  /** Linked to a subcontractor or vendor record. Only a registered company can be short-listed. */
  registered: boolean;
  source: CandidateSource;
  list: CandidateList;
  decision_rationale: string;
  conflict_of_interest_declared: boolean;
  conflict_note: string;
  scores: CandidateScore[];
  total_score: string;
  passed_all: boolean;
  missing_criteria: string[];
  evidence: CandidateEvidence[];
  references: CandidateReference[];
}

export interface CandidateMatrix {
  package_id: string;
  profile: { id: string; criteria: ProfileCriterion[]; pass_mark: string } | null;
  min_bidders: number;
  items: Candidate[];
  total: number;
  findings: Finding[];
  package_state: PackageState;
  can: {
    add: Capability;
    score: Capability;
    reference: Capability;
    /** Moving a company between the long, short and excluded lists. */
    set_list: Capability;
    delete: Capability;
    confirm_shortlist: Capability;
  };
}

export interface CandidateInput {
  subcontractor_id?: string | null;
  vendor_id?: string | null;
  free_name?: string;
  source?: CandidateSource;
  list?: CandidateList;
  decision_rationale?: string;
  conflict_of_interest_declared?: boolean;
  conflict_note?: string;
}

export interface ScoreInput {
  criterion_code: string;
  passed?: boolean | null;
  score?: string | null;
}

export interface ReferenceInput {
  project_name: string;
  client: string;
  value: string | null;
  currency: string;
  year: number | null;
  role: string;
  verified: boolean;
}

export interface MarketSounding {
  id: string;
  package_ids: string[];
  trade: string;
  held_on: string;
  method: SoundingMethod;
  participant_candidate_ids: string[];
  findings: string;
  capacity_signal: CapacitySignal;
  price_signal: PriceSignal;
  lead_time_signal_days: number | null;
  mitigation: string;
  resplit: boolean;
  /** Tight or insufficient capacity with neither a mitigation nor a new split. */
  unmitigated: boolean;
}

export interface SoundingInput {
  package_ids: string[];
  trade: string;
  held_on: string;
  method: SoundingMethod;
  findings: string;
  capacity_signal: CapacitySignal;
  price_signal: PriceSignal;
  lead_time_signal_days: number | null;
  mitigation: string;
  resplit: boolean;
  /** The candidates that took part. Left out to keep the stored list: the server checks every id it is sent. */
  participant_candidate_ids?: string[];
}

export interface ScheduleRow {
  package_id: string;
  code: string;
  title: string;
  need_date: string | null;
  lead_time_days: number | null;
  procedure_code: string | null;
  procedure_days: number | null;
  proposed_award_date: string | null;
  proposed_start_date: string | null;
  is_advance: boolean;
  start_activity_id: string | null;
  award_activity_id: string | null;
  findings: Finding[];
}

export interface ScheduleView extends Page<ScheduleRow> {
  release_date: string | null;
  release_gate_code: string | null;
}

/** One lot of a framework agreement: a part of its scope with its own name. */
export interface FrameworkLot {
  code?: string;
  title?: string;
}

export interface Framework {
  id: string;
  code: string;
  title: string;
  subcontractor_id: string | null;
  vendor_id: string | null;
  supplier_name: string;
  scope: string;
  package_kinds: PackageKind[];
  lots: FrameworkLot[];
  max_value: string;
  currency: string;
  start_date: string;
  end_date: string;
  call_off_mode: CallOffMode;
  source_procedure_ref: string;
  state: FrameworkState;
  /** `transitions` lists the states this caller may move the agreement to; empty when none. */
  can: { edit: Capability; transitions: FrameworkTarget[] };
}

export interface FrameworkInput {
  code: string;
  title: string;
  supplier_name: string;
  scope: string;
  package_kinds: PackageKind[];
  max_value: string;
  currency: string;
  start_date: string;
  end_date: string;
  call_off_mode: CallOffMode;
  source_procedure_ref: string;
  /** Left out of a change to keep the stored lots; an empty list removes them. */
  lots?: FrameworkLot[];
  /** The supplier as a registered company: one of the two, never both. Null clears the link. */
  subcontractor_id?: string | null;
  vendor_id?: string | null;
}

export type FrameworkPatch = Partial<Omit<FrameworkInput, 'code' | 'currency' | 'start_date'>>;

export interface LedgerEntry {
  kind: 'award_package' | 'purchase_order';
  id: string;
  project_id: string;
  amount: string;
  currency: string;
  state: string;
}

export interface FrameworkLedger {
  framework_id: string;
  max_value: string;
  currency: string;
  call_off_value: string;
  /** Null when it cannot be determined (see `remaining_known`). */
  remaining_value: string | null;
  remaining_known: boolean;
  /** False when a source of call-offs could not be read, so the list may miss entries. */
  complete: boolean;
  /** Entries in another currency: they are listed but not added to the call-off value. */
  unconverted_entries: number;
  items: LedgerEntry[];
  total: number;
}

/* ── Refusals ─────────────────────────────────────────────────────────── */

function detailOf(err: unknown): Record<string, unknown> | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function procurementErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the backend sent with the code, already in the reader's language. */
export function procurementErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

/** The findings a refusal listed, so the screen can show all of them, not only the first. */
export function procurementViolations(err: unknown): Finding[] {
  const list = detailOf(err)?.violations;
  return Array.isArray(list) ? (list as Finding[]) : [];
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const procurementKeys = {
  project: (projectId: string) => ['procurement-concept', projectId] as const,
  concept: (projectId: string) => ['procurement-concept', projectId, 'concept'] as const,
  catalogue: (projectId: string) => ['procurement-concept', projectId, 'catalogue'] as const,
  findings: (projectId: string) => ['procurement-concept', projectId, 'findings'] as const,
  packages: (projectId: string) => ['procurement-concept', projectId, 'packages'] as const,
  threshold: (projectId: string, packageId: string) =>
    ['procurement-concept', projectId, 'threshold', packageId] as const,
  profiles: (projectId: string) => ['procurement-concept', projectId, 'profiles'] as const,
  candidates: (projectId: string, packageId: string) =>
    ['procurement-concept', projectId, 'candidates', packageId] as const,
  soundings: (projectId: string) => ['procurement-concept', projectId, 'soundings'] as const,
  schedule: (projectId: string) => ['procurement-concept', projectId, 'schedule'] as const,
  projectFrameworks: (projectId: string) => ['procurement-concept', projectId, 'frameworks'] as const,
  permitConditions: (projectId: string) => ['procurement-concept', projectId, 'permit-conditions'] as const,
  gates: (projectId: string) => ['procurement-concept', projectId, 'gates'] as const,
  advanceReleases: (projectId: string) => ['procurement-concept', projectId, 'advance-releases'] as const,
  tenderPackages: (projectId: string) => ['procurement-concept', projectId, 'tender-packages'] as const,
  costSections: (projectId: string) => ['procurement-concept', projectId, 'cost-refs'] as const,
  catalogues: ['procurement-concept-company', 'catalogues'] as const,
  frameworks: ['procurement-concept-company', 'frameworks'] as const,
  ledger: (frameworkId: string) => ['procurement-concept-company', 'ledger', frameworkId] as const,
};

/* ── Catalogue and concept ────────────────────────────────────────────── */

export function listCatalogues(): Promise<Page<CatalogueSummary>> {
  return apiGet<Page<CatalogueSummary>>(`/v1/procurement-concept/catalogues`);
}

export function getPinnedCatalogue(projectId: string): Promise<PinnedCatalogue> {
  return apiGet<PinnedCatalogue>(`/v1/procurement-concept/projects/${projectId}/catalogue`);
}

export function getConcept(projectId: string): Promise<Concept> {
  return apiGet<Concept>(`/v1/procurement-concept/projects/${projectId}/concept`);
}

export function setConcept(projectId: string, body: ConceptInput): Promise<Concept> {
  return apiPut<Concept>(`/v1/procurement-concept/projects/${projectId}/concept`, body);
}

/**
 * A hand move on the concept. Submit and return exist everywhere. Approve and
 * reopen exist only on a project without gates; with gates the gate decision
 * approves and a change request reopens, and the server refuses both here.
 * Reopening carries its reason, which the server records; no other move has a body.
 */
export function conceptAction(projectId: string, action: ConceptAction, reason?: string): Promise<Concept> {
  return apiPost<Concept>(`/v1/procurement-concept/projects/${projectId}/concept/${action}`, action === 'reopen' ? { reason: reason ?? '' } : {});
}

/** The longest reason the server keeps with a reopening. */
export const REOPEN_REASON_MAX = 2000;

export function getReadiness(projectId: string): Promise<Readiness> {
  return apiGet<Readiness>(`/v1/procurement-concept/projects/${projectId}/readiness`);
}

export function listFindings(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/procurement-concept/projects/${projectId}/findings?today=${localToday()}`);
}

/* ── Packages ─────────────────────────────────────────────────────────── */

export function listPackages(projectId: string): Promise<Page<PackageView>> {
  return apiGet<Page<PackageView>>(`/v1/procurement-concept/projects/${projectId}/packages?today=${localToday()}`);
}

export function putPackage(projectId: string, packageId: string, body: PackageInput): Promise<AwardPackage> {
  return apiPut<AwardPackage>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}`, body);
}

export function setPackageState(projectId: string, packageId: string, action: PackageAction): Promise<AwardPackage> {
  return apiPost<AwardPackage>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/state`, { action });
}

export function getThreshold(projectId: string, packageId: string): Promise<ThresholdCheck> {
  return apiGet<ThresholdCheck>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/threshold?today=${localToday()}`);
}

export function createExecution(
  projectId: string,
  packageId: string,
  body: { submission_deadline?: string | null } = {},
): Promise<ExecutionResult> {
  return apiPost<ExecutionResult>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/execution`, body);
}

/** Link an existing tender package of the project as the vehicle of this award. Nothing is created. */
export function linkExecution(projectId: string, packageId: string, tenderPackageId: string): Promise<ExecutionResult> {
  return apiPost<ExecutionResult>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/execution/link`, { tender_package_id: tenderPackageId });
}

export function listTenderPackages(projectId: string): Promise<Page<TenderPackageOption>> {
  return apiGet<Page<TenderPackageOption>>(`/v1/procurement-concept/projects/${projectId}/tender-packages`);
}

export function listCostSections(projectId: string): Promise<Page<CostSection>> {
  return apiGet<Page<CostSection>>(`/v1/procurement-concept/projects/${projectId}/cost-refs`);
}

export function listGates(projectId: string): Promise<Page<GateOption>> {
  return apiGet<Page<GateOption>>(`/v1/procurement-concept/projects/${projectId}/gates`);
}

/** The acts that can release an advance package, and whether released commitments could be read at all. */
export type AdvanceReleasePage = Page<AdvanceRelease> & {
  commitments?: { available: boolean; reason: string | null };
};

export function listAdvanceReleases(projectId: string): Promise<AdvanceReleasePage> {
  return apiGet<AdvanceReleasePage>(`/v1/procurement-concept/projects/${projectId}/advance-releases`);
}

/* ── Prequalification ─────────────────────────────────────────────────── */

export function listProfiles(projectId: string): Promise<PageWithCan<PrequalProfile, 'create'>> {
  return apiGet<PageWithCan<PrequalProfile, 'create'>>(`/v1/procurement-concept/projects/${projectId}/prequal-profiles`);
}

export function createProfile(projectId: string, body: ProfileInput): Promise<PrequalProfile> {
  return apiPost<PrequalProfile>(`/v1/procurement-concept/projects/${projectId}/prequal-profiles`, body);
}

export function updateProfile(projectId: string, profileId: string, body: ProfileInput): Promise<PrequalProfile> {
  return apiPut<PrequalProfile>(`/v1/procurement-concept/projects/${projectId}/prequal-profiles/${profileId}`, body);
}

export function deleteProfile(projectId: string, profileId: string): Promise<void> {
  return apiDelete(`/v1/procurement-concept/projects/${projectId}/prequal-profiles/${profileId}`);
}

export function listCandidates(projectId: string, packageId: string): Promise<CandidateMatrix> {
  return apiGet<CandidateMatrix>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/candidates`);
}

export function addCandidate(
  projectId: string,
  packageId: string,
  body: CandidateInput,
): Promise<{ id: string; list: CandidateList }> {
  return apiPost<{ id: string; list: CandidateList }>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/candidates`, body);
}

export function patchCandidate(
  projectId: string,
  candidateId: string,
  body: CandidateInput,
): Promise<{ id: string; list: CandidateList }> {
  return apiPatch<{ id: string; list: CandidateList }>(`/v1/procurement-concept/projects/${projectId}/candidates/${candidateId}`, body);
}

export function deleteCandidate(projectId: string, candidateId: string): Promise<void> {
  return apiDelete(`/v1/procurement-concept/projects/${projectId}/candidates/${candidateId}`);
}

export function putScores(projectId: string, candidateId: string, scores: ScoreInput[]): Promise<Page<CandidateScore>> {
  return apiPut<Page<CandidateScore>>(`/v1/procurement-concept/projects/${projectId}/candidates/${candidateId}/scores`, { scores });
}

export function addReference(
  projectId: string,
  candidateId: string,
  body: ReferenceInput,
): Promise<{ id: string; verified: boolean }> {
  return apiPost<{ id: string; verified: boolean }>(`/v1/procurement-concept/projects/${projectId}/candidates/${candidateId}/references`, body);
}

export function deleteReference(projectId: string, candidateId: string, referenceId: string): Promise<void> {
  return apiDelete(`/v1/procurement-concept/projects/${projectId}/candidates/${candidateId}/references/${referenceId}`);
}

export function confirmShortlist(projectId: string, packageId: string): Promise<AwardPackage> {
  return apiPost<AwardPackage>(`/v1/procurement-concept/projects/${projectId}/packages/${packageId}/shortlist`, {});
}

/* ── Market sounding ──────────────────────────────────────────────────── */

export function listSoundings(projectId: string): Promise<PageWithCan<MarketSounding, 'create' | 'edit' | 'delete'>> {
  return apiGet<PageWithCan<MarketSounding, 'create' | 'edit' | 'delete'>>(`/v1/procurement-concept/projects/${projectId}/market-soundings`);
}

export function createSounding(projectId: string, body: SoundingInput): Promise<MarketSounding> {
  return apiPost<MarketSounding>(`/v1/procurement-concept/projects/${projectId}/market-soundings`, body);
}

export function patchSounding(
  projectId: string,
  soundingId: string,
  body: Partial<SoundingInput>,
): Promise<MarketSounding> {
  return apiPatch<MarketSounding>(`/v1/procurement-concept/projects/${projectId}/market-soundings/${soundingId}`, body);
}

export function deleteSounding(projectId: string, soundingId: string): Promise<void> {
  return apiDelete(`/v1/procurement-concept/projects/${projectId}/market-soundings/${soundingId}`);
}

/* ── Award schedule ───────────────────────────────────────────────────── */

export function getSchedule(projectId: string): Promise<ScheduleView> {
  return apiGet<ScheduleView>(`/v1/procurement-concept/projects/${projectId}/schedule?today=${localToday()}`);
}

export function confirmSchedule(
  projectId: string,
  packageIds: string[],
): Promise<Page<{ package_id: string; start_date: string; award_date: string }>> {
  return apiPost<Page<{ package_id: string; start_date: string; award_date: string }>>(
    `/v1/procurement-concept/projects/${projectId}/schedule/confirm`,
    { package_ids: packageIds },
  );
}

/* ── Export ───────────────────────────────────────────────────────────── */

export function downloadExport(
  projectId: string,
  part: ExportPart,
  format: ExportFormat,
  packageId?: string,
): Promise<void> {
  const qs = new URLSearchParams({ format, part });
  if (packageId) qs.set('package_id', packageId);
  return downloadWithAuth(`/api/v1/procurement-concept/projects/${projectId}/export?${qs.toString()}`, `procurement_${part}.${format}`);
}

/* ── Framework agreements (company level) ─────────────────────────────── */

/** The agreements a package of this project may call off. */
export function listProjectFrameworks(projectId: string): Promise<Page<Framework>> {
  return apiGet<Page<Framework>>(`/v1/procurement-concept/projects/${projectId}/frameworks`);
}

export function listFrameworks(): Promise<PageWithCan<Framework, 'create'>> {
  return apiGet<PageWithCan<Framework, 'create'>>(`/v1/procurement-concept/frameworks`);
}

export function createFramework(body: FrameworkInput): Promise<Framework> {
  return apiPost<Framework>(`/v1/procurement-concept/frameworks`, body);
}

export function patchFramework(frameworkId: string, body: FrameworkPatch): Promise<Framework> {
  return apiPatch<Framework>(`/v1/procurement-concept/frameworks/${frameworkId}`, body);
}

export function setFrameworkState(frameworkId: string, target: FrameworkTarget): Promise<Framework> {
  return apiPost<Framework>(`/v1/procurement-concept/frameworks/${frameworkId}/state`, { target });
}

export function getLedger(frameworkId: string): Promise<FrameworkLedger> {
  return apiGet<FrameworkLedger>(`/v1/procurement-concept/frameworks/${frameworkId}/ledger`);
}

export interface PermitLotRequirement {
  condition_id: string;
  permit_id: string;
  permit_reference: string;
  number: string;
  requirement: string;
  trigger: string;
  due_date: string | null;
  topic: string;
  responsible_party: string;
  evidence_required: string;
  for_tender_documents: boolean;
}

export interface PermitLotRequirements {
  available: boolean;
  reason: string;
  items: PermitLotRequirement[];
  tender_count: number;
}

/** Permit conditions of module 2 that every open lot inherits as a requirement. */
export const getPermitLotRequirements = (projectId: string) =>
  apiGet<PermitLotRequirements>(`/v1/procurement-concept/projects/${projectId}/permit-conditions`);
