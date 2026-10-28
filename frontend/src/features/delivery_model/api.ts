// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the delivery model: which contracting form the project is
// delivered under, how it was chosen, who carries which risk, the package
// plan and the items the owner supplies.
//
// Backend module: backend/app/modules/delivery_model/router.py, mounted at
// /api/v1/delivery-model/. Every project route lives under
// /projects/{project_id}/ there.
//
// Errors arrive as `detail = {code, message_key, message, violations?}`. The
// screens read `code` and `violations` to explain a refusal and fall back to
// `getErrorMessage` for everything else. Weights, shares and totals travel as
// decimal strings in both directions; the server refuses floats.

import { API_BASE, ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type ModelStatus = 'draft' | 'under_evaluation' | 'proposed' | 'approved' | 'binding' | 'reopened';
export type DecisionStatus = 'proposed' | 'approved' | 'superseded' | 'withdrawn' | 'rejected';
export type AllocationStatus = 'unconfirmed' | 'confirmed' | 'link_missing';
export type Basis = 'contract' | 'insurance' | 'shared_pain_gain' | 'statute' | 'ground_baseline';
export type PackageKind =
  | 'design'
  | 'construction'
  | 'design_and_construction'
  | 'supply'
  | 'supply_and_install'
  | 'management_services'
  | 'operation'
  | 'project_agreement';
export type PriceBasis = 'remeasure' | 'lump_sum' | 'gmp' | 'target_cost' | 'cost_reimbursable' | 'availability_payment';
export type PackageStatus = 'planned' | 'closed' | 'cancelled';
export type PackageEffectiveStatus = 'planned' | 'in_procurement' | 'awarded' | 'closed' | 'cancelled';
export type PackageLinkKind = 'bid_package' | 'tender_package' | 'rfq' | 'subcontract_agreement' | 'contract';
export type ContractingParty = 'owner' | 'manager';
export type OfiKind = 'equipment' | 'material' | 'design' | 'service' | 'utility';
export type OfiRoute = 'rfq' | 'purchase_order' | 'requisition' | 'framework' | 'existing_stock' | 'none_yet';
export type OfiLinkKind = 'rfq' | 'purchase_order' | 'requisition';
export type OfiStatus = 'identified' | 'route_set' | 'ordered' | 'delivered' | 'handed_to_installer';
export type InstallBy = 'owner' | 'package';
export type Disposition = 'keep' | 're_scope' | 'cancel';
export type FindingSeverity = 'error' | 'warning' | 'info';
export type ReviewStatus = 'unconfirmed' | 'verified' | string;
export type ExportWhat = 'decision' | 'matrix' | 'packages';
export type ExportFormat = 'pdf' | 'xlsx';

/** Texts a tenant catalogue carries per locale, where a shipped one carries a message key. */
export type LocaleTexts = Record<string, string>;

export interface FormAlias {
  country: string;
  term: string;
  self_performs?: boolean | null;
  source_url: string;
  review_status: ReviewStatus;
}

export interface DeliveryForm {
  code: string;
  name_key?: string | null;
  description_key?: string | null;
  labels?: LocaleTexts | null;
  aliases: FormAlias[];
  design_responsibility: 'owner' | 'contractor' | 'split_at_stage' | 'shared';
  design_transfer_stage?: string | null;
  owner_construction_contracts: 'many' | 'one' | 'one_per_package_managed';
  contractor_role: 'builder' | 'manager_at_risk' | 'manager_agency' | 'integrator' | 'concessionaire';
  price_basis_at_award: PriceBasis | null;
  allowed_price_bases: PriceBasis[];
  early_involvement?: boolean;
  scope_extends?: string[];
  compatible_contract_types?: string[];
  compatible_standard_forms?: string[];
  source_url?: string;
  review_status: ReviewStatus;
}

export interface CatalogueParty {
  code: string;
  name_key?: string | null;
  labels?: LocaleTexts | null;
  contract_party_role?: string | null;
  side?: 'owner' | 'contractor' | 'operator' | null;
}

export interface CatalogueRiskCategory {
  code: string;
  name_key?: string | null;
  description_key?: string | null;
  labels?: LocaleTexts | null;
  register_category?: string | null;
  concerns?: 'design' | 'operation' | null;
}

export interface CatalogueCriterion {
  code: string;
  name_key?: string | null;
  rationale_key?: string | null;
  labels?: LocaleTexts | null;
  default_weight?: string;
}

/** The body of the catalogue the project pins. */
export interface DeliveryCatalogue {
  id: string;
  version: number;
  contract_kinds?: ContractKind[];
  name_key?: string | null;
  labels?: LocaleTexts | null;
  review_status?: ReviewStatus;
  forms: DeliveryForm[];
  parties: CatalogueParty[];
  risk_categories: CatalogueRiskCategory[];
  criteria: CatalogueCriterion[];
}

export interface CatalogueSummary {
  kind: string;
  source: 'shipped' | 'tenant';
  id: string;
  code: string;
  name: { key: string | null; text: LocaleTexts | null };
  state: string;
  versions: number[];
  latest_version?: number | null;
  review_status?: ReviewStatus;
  jurisdiction_countries?: string[];
}

export interface OwnerCapability {
  owner_has_design_team?: boolean | null;
  owner_has_cm_capacity?: boolean | null;
  public_client?: boolean | null;
  funding_source?: string;
}

/** The server's answer for one action: may the caller do it now, and if not, why. */
export interface Capability {
  /** false: the action does not exist in this state, so nothing is shown for it. */
  applies?: boolean;
  allowed: boolean;
  reason: string | null;
}

export type ModelAction = 'edit' | 'propose' | 'withdraw' | 'reopen' | 'close_reopening';

/** The governance frame document that carries the delivery decision. */
export interface Carrier {
  document_id: string | null;
  document_type: string | null;
  document_status: string | null;
  missing_reason: 'governance_model_missing' | 'carrier_missing' | null;
}

export interface DeliveryModel {
  id: string;
  project_id: string;
  catalogue_source: 'shipped' | 'tenant';
  catalogue_id: string;
  catalogue_version: number;
  selected_form_code: string | null;
  selected_form: DeliveryForm | null;
  status: ModelStatus;
  underground_risk_sharing: boolean;
  owner_capability: OwnerCapability;
  carrier: Carrier;
  change_request_id: string | null;
  current_decision_id: string | null;
  /** Why a binding carrier did not approve the current decision, when it did not. */
  approval_blocked_reason: string | null;
  can: Record<ModelAction, Capability>;
  version: number;
}

export interface DeliveryOption {
  id: string;
  form_code: string;
  form: DeliveryForm | null;
  overrides: Record<string, unknown>;
  /** Attributes of the form this project changed. `form` already has them applied. */
  customised?: string[];
  notes: string;
  /** Decimal string, or null while the option still misses a score. */
  weighted_total: string | null;
}

export interface ComparisonCriterion {
  id: string;
  code: string;
  weight: string;
  name_key: string | null;
  rationale_key: string | null;
}

export interface ComparisonScore {
  option_id: string;
  criterion_code: string | null;
  score: number;
  rationale: string;
}

export interface Comparison {
  options: DeliveryOption[];
  criteria: ComparisonCriterion[];
  scores: ComparisonScore[];
  weights_total: string;
}

export interface Finding {
  code: string;
  severity: FindingSeverity;
  ref: string;
  params?: Record<string, unknown>;
  effective_status?: string;
}

export interface DecisionSnapshot {
  form?: DeliveryForm | null;
  options?: DeliveryOption[];
  criteria?: ComparisonCriterion[];
  scores?: ComparisonScore[];
  weights_total?: string;
}

export interface Decision {
  id: string;
  form_code: string;
  option_id: string | null;
  status: DecisionStatus;
  rationale: string;
  snapshot: DecisionSnapshot;
  owner_capability: OwnerCapability;
  dispositions: Record<string, Disposition>;
  proposed_by: string | null;
  proposed_at: string | null;
  approved_by: string | null;
  approved_at: string | null;
  approval_source: 'gate' | 'change_request' | '';
  /** Written at approval, null before. */
  governance_document_id: string | null;
  supersedes_id: string | null;
  snapshot_hash?: string | null;
  /** null when the record cannot be compared with the bound revision. */
  record_matches_bound_revision?: boolean | null;
  four_eyes?: boolean | null;
  four_eyes_violated: boolean;
  approval_blocked_reason?: string | null;
  is_current: boolean;
}

export interface Allocation {
  id: string;
  category_code: string;
  party: string | null;
  basis: Basis;
  shares: Record<string, string>;
  rationale: string;
  not_applicable: boolean;
  source: 'catalogue_default' | 'edited';
  status: AllocationStatus;
  confirmed_by: string | null;
  confirmed_at: string | null;
  risk_item_ids: string[];
}

export interface DefaultAllocation {
  party: string | null;
  basis: Basis;
  shares: Record<string, string> | null;
  rationale_key: string | null;
  source_url: string;
  review_status: ReviewStatus;
}

export interface AllocationItem {
  category_code: string;
  name_key: string | null;
  description_key: string | null;
  register_category: string | null;
  allocation: Allocation | null;
  default: DefaultAllocation | null;
  findings: Finding[];
}

export interface AllocationMatrix extends Page<AllocationItem> {
  form_code: string | null;
  parties: CatalogueParty[];
  orphans: Allocation[];
}

export interface AllocationInput {
  party: string | null;
  basis: Basis;
  shares: Record<string, string>;
  rationale: string;
  not_applicable: boolean;
}

export interface SeededRisk {
  category_code: string;
  register_category: string | null;
  title: string;
  party: string | null;
  risk_id: string | null;
}

export interface RecordLink<K extends string> {
  kind: K;
  id: string;
  status: string | null;
  missing: boolean;
}

export interface DeliveryPackage {
  id: string;
  code: string;
  title: string;
  kind: PackageKind;
  designs: boolean;
  builds: boolean;
  supplies: boolean;
  manages: boolean;
  party: string;
  contracting_party: ContractingParty;
  price_basis: PriceBasis | null;
  standard_form: string;
  parent_id: string | null;
  scope: string;
  wbs_ref: string;
  boq_ref: string;
  need_date: string | null;
  status: PackageStatus;
  effective_status: PackageEffectiveStatus;
  link: RecordLink<PackageLinkKind> | null;
  linked_contract_type: string | null;
}

export interface PackageInput {
  code: string;
  title: string;
  kind: PackageKind;
  designs: boolean;
  builds: boolean;
  supplies: boolean;
  manages: boolean;
  party: string;
  contracting_party: ContractingParty;
  price_basis: PriceBasis | null;
  standard_form: string;
  parent_id: string | null;
  scope: string;
  wbs_ref: string;
  boq_ref: string;
  need_date: string | null;
}

export interface Consistency extends Page<Finding> {
  form_code: string | null;
  errors: number;
  warnings: number;
}

export interface OwnerFurnishedItem {
  id: string;
  code: string;
  description: string;
  item_kind: OfiKind;
  install_by: InstallBy;
  package_id: string | null;
  procurement_route: OfiRoute | null;
  link: RecordLink<OfiLinkKind> | null;
  schedule_activity_id: string | null;
  need_by_date: string | null;
  expected_delivery_date: string | null;
  enquiry_date: string | null;
  lead_time_days: number | null;
  /** The plant register item this one is, when it is linked to one. */
  plant_item_id?: string | null;
  /** null when unlinked. `missing`: the link is set but the plant register does not answer for it. */
  plant_item?: { code: string; missing: boolean } | null;
  /**
   * Whose figures `enquiry_date`, `lead_time_days` and `latest_order_date` are.
   * With `plant_register` they are read from the linked plant item and cannot
   * be edited here.
   */
  dates_source?: 'own' | 'plant_register';
  /** Only the plant register has one; null for every unlinked item. */
  latest_order_date?: string | null;
  status: OfiStatus;
  findings: Finding[];
}

export interface OfiInput {
  code: string;
  description: string;
  item_kind: OfiKind;
  install_by: InstallBy;
  package_id: string | null;
  need_by_date: string | null;
  expected_delivery_date: string | null;
  enquiry_date: string | null;
  lead_time_days: number | null;
  /** null on an update removes the link to the plant item. */
  plant_item_id?: string | null;
}

export type ContractGroup = 'contract_form' | 'land_tenure' | 'utility_contract' | 'user_agreement' | 'partner_structure';
export type ContractItemStatus = 'draft' | 'negotiating' | 'agreed' | 'signed' | 'terminated';

/** A kind of contract-side item the pinned catalogue offers. */
export interface ContractKind {
  code: string;
  group: ContractGroup;
  name_key?: string | null;
  labels?: LocaleTexts | null;
}

/** A contract form, land tenure, utility contract, user agreement or partner of the project. */
export interface ContractItem {
  id: string;
  code: string;
  group_code: ContractGroup;
  kind_code: string;
  title: string;
  counterparty: string;
  package_id: string | null;
  status: ContractItemStatus;
  reference: string;
  start_date: string | null;
  end_date: string | null;
  price_basis: PriceBasis | null;
  share_percent: string | null;
  notes: string;
  kind_known: boolean;
  findings: Finding[];
}

export interface ContractItemInput {
  code: string;
  group_code: ContractGroup;
  kind_code: string;
  title: string;
  counterparty: string;
  package_id: string | null;
  status: ContractItemStatus;
  reference: string;
  start_date: string | null;
  end_date: string | null;
  price_basis: PriceBasis | null;
  share_percent: string | null;
  notes: string;
}

export interface Readiness {
  in_use: boolean;
  met: boolean;
  status: ModelStatus | null;
  decision_present?: boolean;
  risks_allocated?: boolean;
  errors: Finding[];
}

export interface ProposeInput {
  option_id: string;
  rationale: string;
  owner_capability?: OwnerCapability;
  dispositions?: Record<string, Disposition>;
}

function detailOf(err: unknown): Record<string, unknown> | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, unknown>) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function deliveryErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** Every blocker a refusal listed, so a dialog can show all of them and not only the first. */
export function deliveryViolations(err: unknown): Finding[] {
  const list = detailOf(err)?.violations;
  return Array.isArray(list) ? (list as Finding[]) : [];
}

/** The sentence the server wrote for a refusal, already in the reader's language. */
export function deliveryServerMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

export const deliveryKeys = {
  all: ['delivery-model'] as const,
  project: (projectId: string) => ['delivery-model', projectId] as const,
  model: (projectId: string) => ['delivery-model', projectId, 'model'] as const,
  catalogue: (projectId: string) => ['delivery-model', projectId, 'catalogue'] as const,
  comparison: (projectId: string) => ['delivery-model', projectId, 'comparison'] as const,
  decisions: (projectId: string) => ['delivery-model', projectId, 'decisions'] as const,
  allocations: (projectId: string) => ['delivery-model', projectId, 'allocations'] as const,
  packages: (projectId: string) => ['delivery-model', projectId, 'packages'] as const,
  consistency: (projectId: string) => ['delivery-model', projectId, 'consistency'] as const,
  ofi: (projectId: string) => ['delivery-model', projectId, 'ofi'] as const,
  contractItems: (projectId: string) => ['delivery-model', projectId, 'contract-items'] as const,
  readiness: (projectId: string) => ['delivery-model', projectId, 'readiness'] as const,
  linkTargets: (projectId: string, kind: string) => ['delivery-model', projectId, 'link-targets', kind] as const,
  catalogues: ['delivery-model', 'catalogues'] as const,
};

/* ── Catalogues and model ─────────────────────────────────────────────── */

export function listCatalogues(): Promise<Page<CatalogueSummary>> {
  return apiGet<Page<CatalogueSummary>>('/v1/delivery-model/catalogues');
}

export function getPinnedCatalogue(projectId: string): Promise<DeliveryCatalogue> {
  return apiGet<DeliveryCatalogue>(`/v1/delivery-model/projects/${projectId}/catalogue`);
}

export function getModel(projectId: string): Promise<DeliveryModel> {
  return apiGet<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model`);
}

export function setModel(
  projectId: string,
  body: { catalogue_source?: 'shipped' | 'tenant'; catalogue_id?: string; catalogue_version?: number },
): Promise<DeliveryModel> {
  return apiPut<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model`, body);
}

export function patchModel(
  projectId: string,
  body: { underground_risk_sharing?: boolean; owner_capability?: OwnerCapability },
): Promise<DeliveryModel> {
  return apiPatch<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model`, body);
}

export function changeCatalogue(
  projectId: string,
  body: {
    catalogue_source: 'shipped' | 'tenant';
    catalogue_id: string;
    catalogue_version?: number;
    form_mapping: Record<string, string>;
    category_mapping: Record<string, string>;
  },
): Promise<DeliveryModel> {
  return apiPost<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model/catalogue`, body);
}

export function reopenModel(projectId: string): Promise<DeliveryModel> {
  return apiPost<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model/reopen`, {});
}

/** Gives a reopening up: the model returns to the approved decision. */
export function closeReopening(projectId: string): Promise<DeliveryModel> {
  return apiPost<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/model/reopen/close`, {});
}

/* ── Comparison ───────────────────────────────────────────────────────── */

export function getComparison(projectId: string): Promise<Comparison> {
  return apiGet<Comparison>(`/v1/delivery-model/projects/${projectId}/comparison`);
}

export function addOption(projectId: string, body: { form_code: string; notes?: string }): Promise<unknown> {
  return apiPost(`/v1/delivery-model/projects/${projectId}/options`, { overrides: {}, notes: '', ...body });
}

export function updateOption(projectId: string, optionId: string, body: { notes?: string }): Promise<unknown> {
  return apiPatch(`/v1/delivery-model/projects/${projectId}/options/${optionId}`, body);
}

export function deleteOption(projectId: string, optionId: string): Promise<void> {
  return apiDelete(`/v1/delivery-model/projects/${projectId}/options/${optionId}`);
}

export function patchWeights(projectId: string, weights: Record<string, string>): Promise<unknown> {
  return apiPatch(`/v1/delivery-model/projects/${projectId}/criteria`, { weights });
}

export function putScores(
  projectId: string,
  scores: Array<{ option_id: string; criterion_code: string; score: number; rationale: string }>,
): Promise<Comparison> {
  return apiPut<Comparison>(`/v1/delivery-model/projects/${projectId}/scores`, { scores });
}

export function prefillScores(projectId: string): Promise<Comparison> {
  return apiPost<Comparison>(`/v1/delivery-model/projects/${projectId}/scores/prefill`, {});
}

/* ── Decision ─────────────────────────────────────────────────────────── */

export function proposeDecision(projectId: string, body: ProposeInput): Promise<Decision> {
  return apiPost<Decision>(`/v1/delivery-model/projects/${projectId}/decision`, body);
}

export function withdrawDecision(projectId: string): Promise<DeliveryModel> {
  return apiPost<DeliveryModel>(`/v1/delivery-model/projects/${projectId}/decision/withdraw`, {});
}

export function listDecisions(projectId: string): Promise<Page<Decision>> {
  return apiGet<Page<Decision>>(`/v1/delivery-model/projects/${projectId}/decisions`);
}

/* ── Risk allocation ──────────────────────────────────────────────────── */

export function getAllocations(projectId: string): Promise<AllocationMatrix> {
  return apiGet<AllocationMatrix>(`/v1/delivery-model/projects/${projectId}/allocations`);
}

export function putAllocation(projectId: string, category: string, body: AllocationInput): Promise<AllocationMatrix> {
  return apiPut<AllocationMatrix>(`/v1/delivery-model/projects/${projectId}/allocations/${encodeURIComponent(category)}`, body);
}

export function confirmAllocations(projectId: string, categories?: string[]): Promise<AllocationMatrix> {
  return apiPost<AllocationMatrix>(`/v1/delivery-model/projects/${projectId}/allocations/confirm`, categories ? { categories } : {});
}

export function seedRisks(
  projectId: string,
  body: { categories?: string[]; preview: boolean },
): Promise<Page<SeededRisk> & { preview: boolean }> {
  return apiPost<Page<SeededRisk> & { preview: boolean }>(`/v1/delivery-model/projects/${projectId}/allocations/seed-risks`, body);
}

/* ── Packages ─────────────────────────────────────────────────────────── */

export function listPackages(projectId: string): Promise<Page<DeliveryPackage>> {
  return apiGet<Page<DeliveryPackage>>(`/v1/delivery-model/projects/${projectId}/packages`);
}

export function createPackage(projectId: string, body: PackageInput): Promise<DeliveryPackage> {
  return apiPost<DeliveryPackage>(`/v1/delivery-model/projects/${projectId}/packages`, body);
}

export function updatePackage(
  projectId: string,
  packageId: string,
  body: Partial<Omit<PackageInput, 'code'>>,
): Promise<DeliveryPackage> {
  return apiPatch<DeliveryPackage>(`/v1/delivery-model/projects/${projectId}/packages/${packageId}`, body);
}

export function deletePackage(projectId: string, packageId: string): Promise<void> {
  return apiDelete(`/v1/delivery-model/projects/${projectId}/packages/${packageId}`);
}

export function derivePackages(projectId: string): Promise<Page<DeliveryPackage> & { created: number }> {
  return apiPost<Page<DeliveryPackage> & { created: number }>(`/v1/delivery-model/projects/${projectId}/packages/derive`, {});
}

export function getConsistency(projectId: string): Promise<Consistency> {
  return apiGet<Consistency>(`/v1/delivery-model/projects/${projectId}/packages/consistency`);
}

export function setPackageStatus(projectId: string, packageId: string, status: PackageStatus): Promise<DeliveryPackage> {
  return apiPost<DeliveryPackage>(`/v1/delivery-model/projects/${projectId}/packages/${packageId}/status`, { status });
}

export function linkPackage(
  projectId: string,
  packageId: string,
  body: { link_kind: PackageLinkKind; link_id: string },
): Promise<DeliveryPackage> {
  return apiPut<DeliveryPackage>(`/v1/delivery-model/projects/${projectId}/packages/${packageId}/link`, body);
}

export function unlinkPackage(projectId: string, packageId: string): Promise<DeliveryPackage> {
  return apiDelete<DeliveryPackage>(`/v1/delivery-model/projects/${projectId}/packages/${packageId}/link`);
}

/* ── Owner-furnished items ────────────────────────────────────────────── */

export function listOfi(projectId: string): Promise<Page<OwnerFurnishedItem>> {
  return apiGet<Page<OwnerFurnishedItem>>(`/v1/delivery-model/projects/${projectId}/ofi`);
}

export function createOfi(projectId: string, body: OfiInput): Promise<OwnerFurnishedItem> {
  return apiPost<OwnerFurnishedItem>(`/v1/delivery-model/projects/${projectId}/ofi`, body);
}

export function updateOfi(
  projectId: string,
  ofiId: string,
  body: Partial<Omit<OfiInput, 'code'>>,
): Promise<OwnerFurnishedItem> {
  return apiPatch<OwnerFurnishedItem>(`/v1/delivery-model/projects/${projectId}/ofi/${ofiId}`, body);
}

export function deleteOfi(projectId: string, ofiId: string): Promise<void> {
  return apiDelete(`/v1/delivery-model/projects/${projectId}/ofi/${ofiId}`);
}

export function setOfiRoute(
  projectId: string,
  ofiId: string,
  body: { procurement_route: OfiRoute; link_kind?: OfiLinkKind; link_id?: string },
): Promise<OwnerFurnishedItem> {
  return apiPut<OwnerFurnishedItem>(`/v1/delivery-model/projects/${projectId}/ofi/${ofiId}/route`, body);
}

export function setOfiStatus(projectId: string, ofiId: string, status: OfiStatus): Promise<OwnerFurnishedItem> {
  return apiPost<OwnerFurnishedItem>(`/v1/delivery-model/projects/${projectId}/ofi/${ofiId}/status`, { status });
}

/* ── Readiness and export ─────────────────────────────────────────────── */

export function getReadiness(projectId: string): Promise<Readiness> {
  return apiGet<Readiness>(`/v1/delivery-model/projects/${projectId}/readiness`);
}

/** Download the decision record, the risk matrix or the package plan as PDF or XLSX. */
export function downloadExport(projectId: string, what: ExportWhat, format: ExportFormat): Promise<void> {
  return downloadWithAuth(`${API_BASE}/v1/delivery-model/projects/${projectId}/export?what=${what}&format=${format}`, `delivery_${what}.${format}`);
}

export function listContractItems(projectId: string): Promise<Page<ContractItem>> {
  return apiGet<Page<ContractItem>>(`/v1/delivery-model/projects/${projectId}/contract-items`);
}

export function createContractItem(projectId: string, body: ContractItemInput): Promise<ContractItem> {
  return apiPost<ContractItem>(`/v1/delivery-model/projects/${projectId}/contract-items`, body);
}

export function updateContractItem(
  projectId: string,
  itemId: string,
  body: Partial<Omit<ContractItemInput, 'code' | 'group_code'>>,
): Promise<ContractItem> {
  return apiPatch<ContractItem>(`/v1/delivery-model/projects/${projectId}/contract-items/${itemId}`, body);
}

export function deleteContractItem(projectId: string, itemId: string): Promise<void> {
  return apiDelete(`/v1/delivery-model/projects/${projectId}/contract-items/${itemId}`);
}
