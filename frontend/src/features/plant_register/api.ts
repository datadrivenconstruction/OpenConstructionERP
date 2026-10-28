// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// REST client for the plant register: long-lead plant and equipment items,
// their lead time quotes, capacity reservations, decision papers, delivery
// limits, spares and the construction-phase IT services.
//
// Backend module: backend/app/modules/plant_register/router.py, mounted at
// /api/v1/plant-register/. Every route lives under /projects/{project_id}/.
//
// Money, quantities, scores and weights travel as decimal strings; the server
// refuses a JSON float. Errors arrive as
// `detail = {code, message_key, message, violations?, info?}`; a schema error
// is stock FastAPI (`detail` is a list) and reads through `getErrorMessage`.

import { ApiError, apiDelete, apiGet, apiPatch, apiPost, apiPut, downloadWithAuth } from '@/shared/lib/api';

export interface Page<T> {
  items: T[];
  total: number;
  offset: number;
  limit: number;
}

export type ItemStatus =
  | 'identified'
  | 'specified'
  | 'enquired'
  | 'route_set'
  | 'ordered'
  | 'manufactured'
  | 'delivered'
  | 'installed'
  | 'commissioned'
  | 'handed_over'
  | 'cancelled';
export type ItemClass = 'main_component' | 'user_equipment' | 'operating_equipment';
export type OrderStatus = 'ok' | 'due_soon' | 'overdue';
export type DateBasis = 'activity_late_start' | 'activity_start' | 'fixed' | 'none';
export type LeadBasis = 'from_order' | 'from_approved_drawings' | 'from_down_payment';
export type VendorPolicy = 'neutral' | 'bound';
export type VendorBoundReason = 'standardisation' | 'existing_estate' | 'warranty' | 'sole_source';
export type SlotStatus = 'requested' | 'held' | 'converted_to_order' | 'released' | 'expired';
export type PaperStatus = 'draft' | 'submitted' | 'approved' | 'rejected';
export type SpareStatus = 'required' | 'specified' | 'delivered' | 'handed_over' | 'waived';
export type ItStatus = 'planned' | 'provisioned' | 'retired';
export type FeeRefundable = 'none' | 'partial' | 'full';
export type ProcurementRouteCode =
  | 'contractor_furnished_installed'
  | 'owner_furnished_contractor_installed'
  | 'owner_furnished_owner_installed'
  | 'owner_procured_novated';

/* ── Catalogue ────────────────────────────────────────────────────────── */

/** A catalogue entry: a message key for shipped items, texts per locale for tenant ones. */
export interface CatalogueEntry {
  code: string;
  name_key?: string;
  labels?: Record<string, string> | null;
}

export interface ComponentClass extends CatalogueEntry {
  item_class: ItemClass;
  discipline: string;
  typical_lead_weeks: { min: number; max: number; as_of: string; review_status: string };
  quote_max_age_days: number;
  critical_by_default: boolean;
}

export interface RedundancyScheme extends CatalogueEntry {
  description_key?: string;
  min_quantity: number;
}

export interface ProcurementRoute extends CatalogueEntry {
  acronym: string;
  owner_furnished: boolean;
  needs_package: boolean;
}

export interface PlantCatalogue {
  id: string;
  version: number;
  name_key?: string;
  labels?: Record<string, string> | null;
  long_lead_threshold_weeks: number;
  warn_days: number;
  component_classes: ComponentClass[];
  redundancy_schemes: RedundancyScheme[];
  procurement_routes: ProcurementRoute[];
  lead_time_sources: Array<CatalogueEntry & { market_evidence: boolean }>;
  spare_categories: CatalogueEntry[];
  maintenance_strategies: CatalogueEntry[];
  delivery_limit_steps: Array<CatalogueEntry & { order: number }>;
  site_plant_kinds: CatalogueEntry[];
  it_service_kinds: Array<CatalogueEntry & { responsible_party: string }>;
  parties: CatalogueEntry[];
}

/** Whether the reader may do something, and the error code that says why not. */
export interface Capability {
  allowed: boolean;
  reason?: string | null;
  /** False when the action does not exist in this state at all, so it is not shown. */
  applies?: boolean;
}

export interface PlantSettings {
  catalogue_source: string;
  catalogue_id: string;
  catalogue_version: number | null;
  pinned: boolean;
  /** Decided by the server. `edit` covers every write, `manage` the overrides and the catalogue pin. */
  can?: { edit?: Capability; manage?: Capability };
}

/* ── Item ─────────────────────────────────────────────────────────────── */

export interface PerformanceRow {
  key: string;
  value: string;
  unit: string;
}

export interface PlantItem {
  id: string;
  project_id: string;
  code: string;
  title: string;
  description: string;
  component_class_code: string;
  item_class: ItemClass;
  /** Decimal string. */
  quantity: string;
  unit: string;
  tag: string;
  space_ref: string;
  performance: PerformanceRow[];
  redundancy_scheme: string;
  vendor_policy: VendorPolicy;
  vendor_bound_reason: VendorBoundReason | '';
  vendor_id: string | null;
  /** null follows the class default. */
  critical_override: boolean | null;
  critical_reason: string;
  need_activity_id: string | null;
  need_date_fixed: string | null;
  procurement_route: ProcurementRouteCode | null;
  contract_package_id: string | null;
  purchase_order_id: string | null;
  maintenance_strategy: string;
  no_strategic_spare_reason: string;
  long_lead_override: boolean | null;
  long_lead_override_reason: string;
  owner_user_id: string | null;
  status: ItemStatus;
  service_asset_id: string | null;
  created_at: string;
  updated_at: string;
  // Derived on read, never stored.
  critical: boolean;
  long_lead: boolean;
  long_lead_threshold_weeks: number;
  effective_lead_weeks: number | null;
  /** A lead time source code, `catalogue_default` or `none`. */
  lead_source: string;
  lead_basis: LeadBasis | '';
  market_evidence: boolean;
  basis_quote_id: string | null;
  basis_enquiry_date: string | null;
  quote_age_days: number | null;
  quote_max_age_days: number;
  quote_stale: boolean;
  need_date: string | null;
  date_basis: DateBasis;
  latest_order_date: string | null;
  float_days: number | null;
  order_status: OrderStatus;
  needs_slot: boolean;
  paper_id: string | null;
  paper_status: PaperStatus | null;
  slot_id: string | null;
  slot_status: SlotStatus | null;
  slot_after_order_date: boolean;
  delivery_limit_gaps: string[];
  spare_categories: string[];
  strategic_spares_ok: boolean;
  redundancy_ok: boolean;
  vendor_findings: string[];
}

/** What a create or an edit may send. Explicit null clears a link or an override. */
export interface ItemInput {
  code?: string;
  title?: string;
  description?: string;
  component_class_code?: string;
  quantity?: string;
  unit?: string;
  tag?: string;
  space_ref?: string;
  performance?: PerformanceRow[];
  redundancy_scheme?: string;
  vendor_policy?: VendorPolicy;
  vendor_bound_reason?: string;
  critical_override?: boolean | null;
  critical_reason?: string;
  need_date_fixed?: string | null;
  maintenance_strategy?: string;
  no_strategic_spare_reason?: string;
  long_lead_override?: boolean | null;
  long_lead_override_reason?: string;
  owner_user_id?: string | null;
}

/* ── Quotes, slot, paper ──────────────────────────────────────────────── */

export interface Quote {
  id: string;
  plant_item_id: string;
  source: string;
  source_name: string;
  enquiry_date: string;
  response_date: string | null;
  lead_weeks_min: number;
  lead_weeks_max: number;
  lead_basis: LeadBasis;
  valid_until: string | null;
  document_ref: string;
  is_basis: boolean;
  superseded_by: string | null;
  note: string;
  created_at: string;
}

export interface QuoteInput {
  source: string;
  source_name: string;
  enquiry_date: string | null;
  response_date?: string | null;
  lead_weeks_min: number;
  lead_weeks_max: number;
  lead_basis: LeadBasis;
  valid_until?: string | null;
  document_ref: string;
  note: string;
  set_basis: boolean;
}

export interface Slot {
  id: string;
  plant_item_id: string;
  vendor_name: string;
  slot_from: string | null;
  slot_to: string | null;
  /** Decimal string, or null when no fee was agreed. */
  reservation_fee: string | null;
  currency: string;
  fee_refundable: FeeRefundable | '';
  fee_credited_to_order: boolean;
  convert_by_date: string | null;
  terms: string;
  commitment_item_id: string | null;
  document_ref: string;
  status: SlotStatus;
  created_at: string;
}

/** On an edit, null clears a date or the fee; no other field takes null. */
export interface SlotInput {
  vendor_name?: string;
  slot_from?: string | null;
  slot_to?: string | null;
  reservation_fee?: string | null;
  currency?: string;
  fee_refundable?: FeeRefundable;
  fee_credited_to_order?: boolean;
  convert_by_date?: string | null;
  terms?: string;
  document_ref?: string;
}

export interface PaperOption {
  code: string;
  title: string;
  lead_weeks?: number | null;
  /** Decimal string. */
  cost?: string | null;
  currency?: string | null;
  vendor_id?: string | null;
  quote_id?: string | null;
  risk_ref?: string | null;
  /** Score per criterion code, decimal strings. */
  scores: Record<string, string>;
}

export interface PaperCriterion {
  code: string;
  title: string;
  /** Decimal string. */
  weight: string;
}

export interface Paper {
  id: string;
  plant_item_id: string;
  question: string;
  options: PaperOption[];
  criteria: PaperCriterion[];
  /** Weighted score per option code, computed by the server. */
  scores: Record<string, string>;
  recommendation: string;
  rationale: string;
  approval_instance_id: string | null;
  status: PaperStatus;
  decided_at: string | null;
  created_at: string;
}

export interface PaperInput {
  question: string;
  options: PaperOption[];
  criteria: PaperCriterion[];
  recommendation: string;
  rationale: string;
}

/* ── Delivery limits, spares, IT ──────────────────────────────────────── */

export interface Limit {
  step: string;
  party: string;
  contract_package_id: string | null;
  note: string;
}

export interface LimitMatrix {
  steps: string[];
  rows: Array<{
    item_id: string;
    code: string;
    title: string;
    item_class: ItemClass;
    cells: Record<string, { party: string; contract_package_id: string | null }>;
  }>;
}

export interface Spare {
  id: string;
  plant_item_id: string;
  category: string;
  description: string;
  /** Decimal string. */
  quantity: string;
  unit: string;
  supply_by: string;
  handover_target: string;
  waiver_reason: string;
  status: SpareStatus;
}

export interface SpareInput {
  category?: string;
  description?: string;
  quantity?: string;
  unit?: string;
  supply_by?: string;
  handover_target?: string;
}

export interface ItService {
  id: string;
  kind: string;
  description: string;
  responsible_party: string;
  needed_from: string | null;
  needed_until: string | null;
  access_roles: string[];
  cde_container_id: string | null;
  status: ItStatus;
}

export interface ItServiceInput {
  kind?: string;
  description?: string;
  responsible_party?: string;
  /** On an edit, null clears the date. */
  needed_from?: string | null;
  needed_until?: string | null;
}

/* ── Read views ───────────────────────────────────────────────────────── */

export interface FrameSummary {
  catalogue: string;
  item_count: number;
  critical_count: number;
  long_lead_count: number;
  overdue_count: number;
  by_item_class: Record<string, number>;
  by_route: Record<string, number>;
  site_plant: Array<{
    id: string;
    kind: string;
    name: string;
    reach_m: string | null;
    max_load_t: string | null;
    from_date: string | null;
    to_date: string | null;
  }>;
}

export interface Readiness {
  ready: boolean;
  error_findings: Array<{ rule_id: string; element_ref: string | null }>;
  critical_open: string[];
  long_lead_open: string[];
  frame_document_attached: boolean;
  /** False when the project pinned no phase model: no gate and no frame document exist. */
  gates_in_use?: boolean;
}

export interface Finding {
  rule_id: string;
  passed: boolean;
  severity: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

export interface EscalateResult {
  overdue: string[];
  due_soon: string[];
  expired_slots: string[];
}

export type ExportKind = 'register' | 'limits' | 'spares' | 'paper' | 'frame';
export type ExportFormat = 'pdf' | 'xlsx';

/* ── Errors ───────────────────────────────────────────────────────────── */

export interface PlantViolation {
  code: string;
  reason?: string;
  message_key?: string;
  message?: string;
}

interface PlantErrorDetail {
  code?: unknown;
  message?: unknown;
  violations?: unknown;
}

function detailOf(err: unknown): PlantErrorDetail | null {
  if (!(err instanceof ApiError)) return null;
  const body = err.body as { detail?: unknown } | null;
  const detail = body && typeof body === 'object' ? body.detail : null;
  return detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as PlantErrorDetail) : null;
}

/** The error code the backend put in `detail.code`, or null for any other failure. */
export function plantErrorCode(err: unknown): string | null {
  const code = detailOf(err)?.code;
  return typeof code === 'string' ? code : null;
}

/** The sentence the server sent with its code, already in the request's language. */
export function plantErrorMessage(err: unknown): string | null {
  const message = detailOf(err)?.message;
  return typeof message === 'string' && message ? message : null;
}

/** Every rule a 422 refusal listed, so the screen can show all of them, not only the first. */
export function plantViolations(err: unknown): PlantViolation[] {
  const list = detailOf(err)?.violations;
  if (!Array.isArray(list)) return [];
  return list.filter((v): v is PlantViolation => !!v && typeof v === 'object' && typeof (v as PlantViolation).code === 'string');
}

/** Today as the calendar day the reader is living in, not UTC. */
export function localToday(): string {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
}

export const plantKeys = {
  project: (projectId: string) => ['plant-register', projectId] as const,
  catalogue: (projectId: string) => ['plant-register', projectId, 'catalogue'] as const,
  settings: (projectId: string) => ['plant-register', projectId, 'settings'] as const,
  items: (projectId: string) => ['plant-register', projectId, 'items'] as const,
  quotes: (projectId: string, itemId: string) => ['plant-register', projectId, 'item', itemId, 'quotes'] as const,
  slots: (projectId: string, itemId: string) => ['plant-register', projectId, 'item', itemId, 'slots'] as const,
  papers: (projectId: string, itemId: string) => ['plant-register', projectId, 'item', itemId, 'papers'] as const,
  limits: (projectId: string, itemId: string) => ['plant-register', projectId, 'item', itemId, 'limits'] as const,
  spares: (projectId: string, itemId: string) => ['plant-register', projectId, 'item', itemId, 'spares'] as const,
  matrix: (projectId: string) => ['plant-register', projectId, 'limit-matrix'] as const,
  itServices: (projectId: string) => ['plant-register', projectId, 'it-services'] as const,
  frame: (projectId: string) => ['plant-register', projectId, 'frame-summary'] as const,
  readiness: (projectId: string) => ['plant-register', projectId, 'readiness'] as const,
  validation: (projectId: string) => ['plant-register', projectId, 'validation'] as const,
};

/* ── Catalogue and items ──────────────────────────────────────────────── */

export function getCatalogue(projectId: string): Promise<PlantCatalogue> {
  return apiGet<PlantCatalogue>(`/v1/plant-register/projects/${projectId}/catalogue`);
}

export function getSettings(projectId: string): Promise<PlantSettings> {
  return apiGet<PlantSettings>(`/v1/plant-register/projects/${projectId}/settings`);
}

export function listItems(projectId: string): Promise<Page<PlantItem>> {
  return apiGet<Page<PlantItem>>(`/v1/plant-register/projects/${projectId}/items?limit=500&today=${localToday()}`);
}

export function createItem(projectId: string, body: ItemInput): Promise<PlantItem> {
  return apiPost<PlantItem>(`/v1/plant-register/projects/${projectId}/items`, body);
}

export function updateItem(projectId: string, itemId: string, body: ItemInput): Promise<PlantItem> {
  return apiPatch<PlantItem>(`/v1/plant-register/projects/${projectId}/items/${itemId}`, body);
}

export function transitionItem(projectId: string, itemId: string, target: ItemStatus): Promise<PlantItem> {
  return apiPost<PlantItem>(`/v1/plant-register/projects/${projectId}/items/${itemId}/transition`, { target });
}

export function syncItem(projectId: string, itemId: string): Promise<PlantItem> {
  return apiPost<PlantItem>(`/v1/plant-register/projects/${projectId}/items/${itemId}/sync`, {});
}

export function setRoute(projectId: string, itemId: string, route: ProcurementRouteCode): Promise<PlantItem> {
  return apiPut<PlantItem>(`/v1/plant-register/projects/${projectId}/items/${itemId}/route`, { procurement_route: route });
}

/** Handover with no service contract named, so the server asks why the item has no service asset. */
export function handoverItem(
  projectId: string,
  itemId: string,
  confirm: boolean,
  noAssetReason: string,
): Promise<PlantItem> {
  return apiPost<PlantItem>(`/v1/plant-register/projects/${projectId}/items/${itemId}/handover`, { confirm, no_asset_reason: noAssetReason });
}

/* ── Quotes ───────────────────────────────────────────────────────────── */

export function listQuotes(projectId: string, itemId: string): Promise<Page<Quote>> {
  return apiGet<Page<Quote>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/quotes`);
}

export function addQuote(projectId: string, itemId: string, body: QuoteInput): Promise<Quote> {
  return apiPost<Quote>(`/v1/plant-register/projects/${projectId}/items/${itemId}/quotes`, body);
}

export function setBasisQuote(projectId: string, itemId: string, quoteId: string): Promise<Quote> {
  return apiPost<Quote>(`/v1/plant-register/projects/${projectId}/items/${itemId}/quotes/${quoteId}/basis`, {});
}

/* ── Capacity reservation ─────────────────────────────────────────────── */

export function listSlots(projectId: string, itemId: string): Promise<Page<Slot>> {
  return apiGet<Page<Slot>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/slot`);
}

export function createSlot(projectId: string, itemId: string, body: SlotInput): Promise<Slot> {
  return apiPost<Slot>(`/v1/plant-register/projects/${projectId}/items/${itemId}/slot`, body);
}

export function updateSlot(projectId: string, itemId: string, slotId: string, body: SlotInput): Promise<Slot> {
  return apiPatch<Slot>(`/v1/plant-register/projects/${projectId}/items/${itemId}/slot/${slotId}`, body);
}

export function transitionSlot(
  projectId: string,
  itemId: string,
  slotId: string,
  target: Extract<SlotStatus, 'held' | 'converted_to_order' | 'released'>,
): Promise<Slot> {
  return apiPost<Slot>(`/v1/plant-register/projects/${projectId}/items/${itemId}/slot/${slotId}/transition`, { target });
}

/* ── Decision paper ───────────────────────────────────────────────────── */

export function listPapers(projectId: string, itemId: string): Promise<Page<Paper>> {
  return apiGet<Page<Paper>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/decision-paper`);
}

export function createPaper(projectId: string, itemId: string, body: PaperInput): Promise<Paper> {
  return apiPost<Paper>(`/v1/plant-register/projects/${projectId}/items/${itemId}/decision-paper`, body);
}

export function updatePaper(projectId: string, itemId: string, paperId: string, body: PaperInput): Promise<Paper> {
  return apiPatch<Paper>(`/v1/plant-register/projects/${projectId}/items/${itemId}/decision-paper/${paperId}`, body);
}

export function submitPaper(projectId: string, itemId: string, paperId: string): Promise<Paper> {
  return apiPost<Paper>(`/v1/plant-register/projects/${projectId}/items/${itemId}/decision-paper/${paperId}/submit`, {});
}

/** Takes a submitted paper back to draft so it can be changed. */
export function withdrawPaper(projectId: string, itemId: string, paperId: string): Promise<Paper> {
  return apiPost<Paper>(`/v1/plant-register/projects/${projectId}/items/${itemId}/decision-paper/${paperId}/withdraw`, {});
}

/* ── Delivery limits ──────────────────────────────────────────────────── */

export function listLimits(projectId: string, itemId: string): Promise<Page<Limit>> {
  return apiGet<Page<Limit>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/delivery-limits`);
}

export function putLimits(
  projectId: string,
  itemId: string,
  limits: Array<{ step: string; party: string; note: string; contract_package_id?: string | null }>,
): Promise<Page<Limit>> {
  return apiPut<Page<Limit>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/delivery-limits`, { limits });
}

export function getLimitMatrix(projectId: string): Promise<LimitMatrix> {
  return apiGet<LimitMatrix>(`/v1/plant-register/projects/${projectId}/delivery-limits`);
}

/* ── Spares ───────────────────────────────────────────────────────────── */

export function listSpares(projectId: string, itemId: string): Promise<Page<Spare>> {
  return apiGet<Page<Spare>>(`/v1/plant-register/projects/${projectId}/items/${itemId}/spares`);
}

export function createSpare(projectId: string, itemId: string, body: SpareInput): Promise<Spare> {
  return apiPost<Spare>(`/v1/plant-register/projects/${projectId}/items/${itemId}/spares`, body);
}

export function updateSpare(projectId: string, itemId: string, spareId: string, body: SpareInput): Promise<Spare> {
  return apiPatch<Spare>(`/v1/plant-register/projects/${projectId}/items/${itemId}/spares/${spareId}`, body);
}

export function transitionSpare(
  projectId: string,
  itemId: string,
  spareId: string,
  target: Exclude<SpareStatus, 'required'>,
  reason: string,
): Promise<Spare> {
  return apiPost<Spare>(`/v1/plant-register/projects/${projectId}/items/${itemId}/spares/${spareId}/transition`, { target, reason });
}

export function deleteSpare(projectId: string, itemId: string, spareId: string): Promise<void> {
  return apiDelete(`/v1/plant-register/projects/${projectId}/items/${itemId}/spares/${spareId}`);
}

/* ── IT services ──────────────────────────────────────────────────────── */

export function listItServices(projectId: string): Promise<Page<ItService>> {
  return apiGet<Page<ItService>>(`/v1/plant-register/projects/${projectId}/it-services`);
}

export function createItService(projectId: string, body: ItServiceInput): Promise<ItService> {
  return apiPost<ItService>(`/v1/plant-register/projects/${projectId}/it-services`, body);
}

export function updateItService(projectId: string, serviceId: string, body: ItServiceInput): Promise<ItService> {
  return apiPatch<ItService>(`/v1/plant-register/projects/${projectId}/it-services/${serviceId}`, body);
}

export function transitionItService(
  projectId: string,
  serviceId: string,
  target: Extract<ItStatus, 'provisioned' | 'retired'>,
): Promise<ItService> {
  return apiPost<ItService>(`/v1/plant-register/projects/${projectId}/it-services/${serviceId}/transition`, { target });
}

export function deleteItService(projectId: string, serviceId: string): Promise<void> {
  return apiDelete(`/v1/plant-register/projects/${projectId}/it-services/${serviceId}`);
}

/* ── Read views, escalation, export ───────────────────────────────────── */

export function getFrameSummary(projectId: string): Promise<FrameSummary> {
  return apiGet<FrameSummary>(`/v1/plant-register/projects/${projectId}/frame-summary?today=${localToday()}`);
}

export function getReadiness(projectId: string): Promise<Readiness> {
  return apiGet<Readiness>(`/v1/plant-register/projects/${projectId}/readiness?today=${localToday()}`);
}

export function listFindings(projectId: string): Promise<Page<Finding>> {
  return apiGet<Page<Finding>>(`/v1/plant-register/projects/${projectId}/validation?today=${localToday()}`);
}

export function escalate(projectId: string): Promise<EscalateResult> {
  return apiPost<EscalateResult>(`/v1/plant-register/projects/${projectId}/escalate`, {});
}

export function downloadExport(
  projectId: string,
  kind: ExportKind,
  format: ExportFormat,
  itemId?: string,
): Promise<void> {
  const query = itemId ? `format=${format}&item_id=${itemId}` : `format=${format}`;
  return downloadWithAuth(`/api/v1/plant-register/projects/${projectId}/export/${kind}?${query}`, `plant_${kind}.${format}`);
}
