// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Material requisitions - typed client for `/v1/procurement/requisitions`
 * plus the pure helpers that turn buy-list rows into requisition lines.
 *
 * Quantities are the Decimal strings the backend serves and are summed as
 * strings (`addDecimalStrings`), never through a float, so 0.1 + 0.2 stays 0.3.
 */

import { apiGet, apiPatch, apiPost, apiPut } from '@/shared/lib/api';
import { isDecimalString, subtractDecimalStrings, weightedMeanDecimalStrings } from '@/shared/lib/exactDecimal';

/* ── Types ──────────────────────────────────────────────────────────────── */

export type RequisitionStatus =
  | 'draft'
  | 'submitted'
  | 'approved'
  | 'ordered'
  | 'received'
  | 'consumed'
  | 'rejected'
  | 'cancelled';

export const REQUISITION_STATUSES: RequisitionStatus[] = [
  'draft',
  'submitted',
  'approved',
  'ordered',
  'received',
  'consumed',
  'rejected',
  'cancelled',
];

export interface RequisitionSourceIn {
  boq_position_id: string | null;
  resource_key: string | null;
  quantity: string;
  unit: string | null;
  /**
   * The supplier the BOQ suggested for this source. Left out, the server reads
   * it from the bill; sent (null included), it is kept as sent.
   */
  suggested_vendor_id?: string | null;
  /**
   * The cost line the source's position pointed at. Sent back on every edit so
   * a draft keeps it; left out, the server resolves it from the position.
   */
  cost_line_id?: string | null;
}

export interface RequisitionLineIn {
  description: string;
  unit: string | null;
  quantity_requested: string;
  /** Decimal string. Sent back on every edit, or the server resets it to 0. */
  unit_cost?: string;
  currency_code?: string;
  catalog_item_id?: string | null;
  /**
   * The supplier suggested for the line. Left out, the server takes the one
   * the sources agree on; sent (null included), it is the requester's choice.
   */
  suggested_vendor_id?: string | null;
  /** When the line is needed; null falls back to the requisition's date. */
  required_date?: string | null;
  schedule_activity_id?: string | null;
  schedule_buffer_days?: number | null;
  /** The activity start the date was proposed from, echoed back unchanged. */
  schedule_anchor_date?: string | null;
  /** The cost line of the line itself, echoed back unchanged on every edit. */
  cost_line_id?: string | null;
  /** Why the line goes over the BOQ demand, when it does. Answers the warning, never required. */
  over_allocation_reason?: string | null;
  sources: RequisitionSourceIn[];
}

export interface RequisitionSource extends RequisitionSourceIn {
  id: string;
  cost_line_id: string | null;
  suggested_vendor_name?: string | null;
}

/** A Vendor directory entry as a requisition shows it. */
export interface RequisitionVendorRef {
  id: string;
  name: string | null;
  status: string | null;
}

export interface RequisitionLine {
  id: string;
  description: string;
  unit: string | null;
  quantity_requested: string;
  quantity_ordered: string;
  quantity_received: string;
  quantity_consumed: string;
  quantity_outstanding: string;
  unit_cost?: string;
  currency_code?: string;
  catalog_item_id: string | null;
  cost_line_id: string | null;
  sort_order: number;
  suggested_vendor_id?: string | null;
  suggested_vendor_name?: string | null;
  suggested_vendor_status?: string | null;
  /** Every distinct supplier the BOQ sources suggested; more than one is a conflict. */
  source_suggested_vendors?: RequisitionVendorRef[];
  suggestion_conflict?: boolean;
  required_date?: string | null;
  /** The line's own date, or the requisition's when the line has none. */
  effective_required_date?: string | null;
  required_date_source?: 'line' | 'schedule' | 'requisition' | null;
  latest_order_date?: string | null;
  schedule_activity_id?: string | null;
  schedule_activity_name?: string | null;
  schedule_buffer_days?: number | null;
  schedule_anchor_date?: string | null;
  schedule_activity_start?: string | null;
  /** The activity starts on another day than the one the date was proposed from. */
  schedule_moved?: boolean;
  over_allocation_reason?: string | null;
  sources: RequisitionSource[];
  /** Purchase order lines raised from this line by a conversion. */
  po_items?: RequisitionPOItemRef[];
  /** Order lines an external purchasing system reported for this line. */
  external_orders?: RequisitionExternalLine[];
  /** Requested minus what live orders hold, never below zero. */
  quantity_to_order?: string;
  /** Live orders hold more than the line requested. */
  over_ordered?: boolean;
}

/** An order line placed in an external purchasing system. No local order exists for it. */
export interface RequisitionExternalLine {
  id: string;
  external_system: string;
  external_order_number: string;
  external_line_ref: string;
  status: ExternalOrderStatus;
  quantity_ordered: string;
  quantity_received: string;
  unit: string | null;
  expected_delivery_date: string | null;
  confirmed_delivery_date: string | null;
  /** The unit cannot be restated in the line's unit, so it is not counted. */
  unit_mismatch: boolean;
  updated_at: string | null;
}

export type ExternalOrderStatus = 'open' | 'confirmed' | 'partially_received' | 'received' | 'cancelled';

export const EXTERNAL_ORDER_STATUSES: ExternalOrderStatus[] = [
  'open',
  'confirmed',
  'partially_received',
  'received',
  'cancelled',
];

/** Where a requisition's orders are placed. */
export type OrderOwner = 'ocerp' | 'external';

/** One designated approver of a requisition, in order. */
export interface RequisitionApprovalStep {
  user_id: string;
  name: string | null;
  /** approved: done this round; next: the only one who may decide now; waiting: after them. */
  state: 'approved' | 'next' | 'waiting';
  decided_at: string | null;
  comment: string | null;
}

export interface RequisitionOrderRef {
  po_id: string;
  po_number: string | null;
  status: string | null;
}

/** A purchase order line that came from a requisition line. */
export interface RequisitionPOItemRef {
  po_item_id: string;
  po_id: string;
  po_number: string | null;
  quantity: string;
  unit: string | null;
  /** The order's delivery date and the supplier's confirmed one, apart from the need date. */
  po_delivery_date?: string | null;
  supplier_confirmed_delivery_date?: string | null;
  po_status?: string | null;
  quantity_received?: string;
  /** The order line's unit cannot be restated in the line's unit, so it is not counted. */
  unit_mismatch?: boolean;
}

/** A schedule activity a line can take its needed-by date from. */
export interface ScheduleActivityOption {
  id: string;
  name: string;
  schedule_name: string | null;
  start_date: string;
  end_date: string | null;
  activity_type: string | null;
}

export interface RequisitionHistoryEntry {
  at: string;
  action: string;
  actor: string | null;
  reason?: string;
  comment?: string;
}

export interface Requisition {
  id: string;
  project_id: string;
  req_number: string | null;
  status: RequisitionStatus;
  title: string | null;
  required_date: string | null;
  lead_time_days?: number;
  /** The last day to order and still arrive by the needed-by date. */
  latest_order_date?: string | null;
  /** The delivery date of the order this requisition became; null before. */
  estimated_delivery_date?: string | null;
  notes: string | null;
  requester_id: string | null;
  approver_id?: string | null;
  /** Display name of the approver, resolved by the server. */
  approver_name?: string | null;
  po_id: string | null;
  po_number?: string | null;
  vendor_id?: string | null;
  vendor_name?: string | null;
  vendor_status?: string | null;
  /** Distinct suppliers the lines suggest. Never applied to vendor_id by itself. */
  suggested_vendors?: RequisitionVendorRef[];
  submitted_by?: string | null;
  decided_at?: string | null;
  decision_comment?: string | null;
  items: RequisitionLine[];
  reconciliation: Record<string, string>;
  history: RequisitionHistoryEntry[];
  created_at: string;
  updated_at: string;
  order_owner?: OrderOwner;
  /** none, partial or full: how much of what was requested live orders hold. */
  order_progress?: 'none' | 'partial' | 'full';
  /** Every order raised from this requisition, cancelled ones included. */
  purchase_orders?: RequisitionOrderRef[];
  approval_chain?: RequisitionApprovalStep[];
  approval_step?: number;
  /** With designated approvers, the only person who may approve or reject now. */
  next_approver_id?: string | null;
  row_version?: number;
}

export interface RequisitionPage {
  items: Requisition[];
  total: number;
  offset: number;
  limit: number;
}

export interface RequisitionCreateBody {
  project_id: string;
  title?: string | null;
  required_date?: string | null;
  notes?: string | null;
  vendor_id?: string | null;
  items: RequisitionLineIn[];
  order_owner?: OrderOwner | null;
  approval_chain?: string[] | null;
  client_request_id?: string | null;
}

export interface RequisitionUpdateBody {
  title?: string | null;
  required_date?: string | null;
  notes?: string | null;
  vendor_id?: string | null;
  items?: RequisitionLineIn[];
  order_owner?: OrderOwner | null;
  approval_chain?: string[] | null;
}

export interface ConvertToPOBody {
  project_id: string;
  requisition_ids: string[];
  vendor_id?: string | null;
  delivery_date?: string | null;
  notes?: string | null;
  /** Order only these lines with these quantities; left out, everything still to order. */
  lines?: { requisition_item_id: string; quantity: string }[];
  /** A retry with the same key answers with the order the first call made. */
  idempotency_key?: string | null;
}

export interface ConvertToPOResult {
  po_id: string;
  po_number: string;
  project_id: string;
  requisition_ids: string[];
  line_count: number;
  vendor_warnings: string[];
  replayed?: boolean;
  fully_ordered_requisition_ids?: string[];
}

export interface ProcurementSettings {
  project_id: string;
  order_owner: OrderOwner;
  default_approvers: RequisitionApprovalStep[];
}

export interface ProcurementSettingsBody {
  order_owner?: OrderOwner;
  default_approval_chain?: string[];
}

export interface ExternalOrderLineIn {
  requisition_item_id: string;
  external_line_ref?: string;
  status?: ExternalOrderStatus;
  quantity_ordered: string;
  quantity_received?: string;
  unit?: string | null;
  expected_delivery_date?: string | null;
  confirmed_delivery_date?: string | null;
}

export interface ExternalOrderReport {
  external_system: string;
  external_order_number: string;
  lines: ExternalOrderLineIn[];
}

/** A member of the project, as the approver picker lists them. */
export interface ProjectMemberOption {
  user_id: string;
  email: string;
  full_name: string;
  role?: string | null;
}

export interface TracePOLineRef {
  po_id: string;
  po_number: string | null;
  po_status: string | null;
  po_item_id: string;
  quantity: string;
  unit: string | null;
}

/** One BOQ source of a requisition line, seen from the BOQ position. */
export interface PositionTraceRow {
  requisition_id: string;
  req_number: string | null;
  requisition_status: RequisitionStatus;
  requisition_item_id: string;
  description: string;
  line_unit: string | null;
  quantity_requested: string;
  quantity_ordered: string;
  resource_key: string | null;
  source_quantity: string;
  source_unit: string | null;
  purchase_orders: TracePOLineRef[];
}

export interface PositionTrace {
  boq_position_id: string;
  items: PositionTraceRow[];
}

export interface POTraceLine {
  po_item_id: string;
  description: string;
  quantity: string;
  unit: string | null;
  requisition_item_id: string | null;
  requisition_id: string | null;
  req_number: string | null;
  sources: {
    boq_position_id: string | null;
    resource_key: string | null;
    quantity: string;
    unit: string | null;
    position_ordinal?: string | null;
    position_description?: string | null;
  }[];
}

export interface POTrace {
  po_id: string;
  po_number: string | null;
  po_status: string | null;
  requisitions: { id: string; req_number: string | null; status: RequisitionStatus; title: string | null }[];
  lines: POTraceLine[];
}

/** One rule failure from a refused submit (422 `detail.errors`). */
export interface RequisitionRuleError {
  rule_id: string;
  message: string;
  element_ref: string | null;
  suggestion: string | null;
}

/* ── Calls ──────────────────────────────────────────────────────────────── */

export function listRequisitions(projectId: string, status?: RequisitionStatus | ''): Promise<RequisitionPage> {
  const qs = new URLSearchParams({ project_id: projectId, limit: '100' });
  if (status) qs.set('status', status);
  return apiGet<RequisitionPage>(`/v1/procurement/requisitions/?${qs.toString()}`);
}

export function getRequisition(id: string): Promise<Requisition> {
  return apiGet<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}`);
}

export function createRequisition(body: RequisitionCreateBody): Promise<Requisition> {
  return apiPost<Requisition, RequisitionCreateBody>(`/v1/procurement/requisitions/`, body);
}

export function updateRequisition(id: string, body: RequisitionUpdateBody): Promise<Requisition> {
  return apiPatch<Requisition, RequisitionUpdateBody>(`/v1/procurement/requisitions/${encodeURIComponent(id)}`, body);
}

export function submitRequisition(id: string): Promise<Requisition> {
  return apiPost<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}/submit`, {});
}

export function withdrawRequisition(id: string): Promise<Requisition> {
  return apiPost<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}/withdraw`, {});
}

export function cancelRequisition(id: string, reason?: string): Promise<Requisition> {
  return apiPost<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}/cancel`, { reason: reason || null });
}

export function approveRequisition(id: string, comment?: string): Promise<Requisition> {
  return apiPost<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}/approve`, {
    comment: comment?.trim() || null,
  });
}

export function rejectRequisition(id: string, comment: string): Promise<Requisition> {
  return apiPost<Requisition>(`/v1/procurement/requisitions/${encodeURIComponent(id)}/reject`, { comment: comment.trim() });
}

export function convertRequisitionsToPurchaseOrder(body: ConvertToPOBody): Promise<ConvertToPOResult> {
  return apiPost<ConvertToPOResult, ConvertToPOBody>(`/v1/procurement/requisitions/convert-to-po`, body);
}

export function getProcurementSettings(projectId: string): Promise<ProcurementSettings> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiGet<ProcurementSettings>(`/v1/procurement/requisitions/settings?${qs.toString()}`);
}

export function updateProcurementSettings(projectId: string, body: ProcurementSettingsBody): Promise<ProcurementSettings> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiPut<ProcurementSettings, ProcurementSettingsBody>(
    `/v1/procurement/requisitions/settings?${qs.toString()}`,
    body,
  );
}

export function reportExternalOrder(requisitionId: string, body: ExternalOrderReport): Promise<Requisition> {
  return apiPost<Requisition, ExternalOrderReport>(
    `/v1/procurement/requisitions/${encodeURIComponent(requisitionId)}/external-orders`,
    body,
  );
}

export function listProjectMemberOptions(projectId: string): Promise<ProjectMemberOption[]> {
  return apiGet<ProjectMemberOption[]>(`/v1/projects/${encodeURIComponent(projectId)}/members/`);
}

/** A fresh key for one conversion attempt, so a retried click is one order. */
export function newIdempotencyKey(): string {
  const c = (globalThis as { crypto?: Crypto }).crypto;
  if (c && typeof c.randomUUID === 'function') return c.randomUUID();
  return `conv-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 10)}`;
}

/** One page of schedule activities; total counts all of the project's. */
export interface ScheduleActivityOptionPage {
  items: ScheduleActivityOption[];
  total: number;
  offset: number;
  limit: number;
}

export function listScheduleActivities(projectId: string): Promise<ScheduleActivityOptionPage> {
  const qs = new URLSearchParams({ project_id: projectId, limit: '1000' });
  return apiGet<ScheduleActivityOptionPage>(`/v1/procurement/requisitions/schedule-activities?${qs.toString()}`);
}

export function traceBoqPosition(positionId: string, projectId: string): Promise<PositionTrace> {
  const qs = new URLSearchParams({ project_id: projectId });
  return apiGet<PositionTrace>(
    `/v1/procurement/requisitions/trace/position/${encodeURIComponent(positionId)}?${qs.toString()}`,
  );
}

export function tracePurchaseOrder(poId: string): Promise<POTrace> {
  return apiGet<POTrace>(`/v1/procurement/requisitions/trace/purchase-order/${encodeURIComponent(poId)}`);
}

/** Why a selection of requisitions cannot go into one purchase order. */
export type ConvertBlockReason = 'empty' | 'not_approved' | 'mixed_projects' | 'vendor_conflict' | 'external_owner';

export interface ConvertCheck {
  ok: boolean;
  reason: ConvertBlockReason | null;
  /** The vendor every requisition that names one agrees on, or null. */
  vendorId: string | null;
}

/**
 * Whether these requisitions can be converted into one purchase order: all
 * approved, in one project, and naming at most one vendor between them. The
 * server checks the same and is the authority; this only says it early.
 */
export function canConvertTogether(
  reqs: (Pick<Requisition, 'status' | 'project_id' | 'vendor_id'> & Pick<Partial<Requisition>, 'order_owner'>)[],
): ConvertCheck {
  if (reqs.length === 0) return { ok: false, reason: 'empty', vendorId: null };
  if (reqs.some((r) => r.status !== 'approved')) return { ok: false, reason: 'not_approved', vendorId: null };
  if (reqs.some((r) => r.order_owner === 'external')) return { ok: false, reason: 'external_owner', vendorId: null };
  if (new Set(reqs.map((r) => r.project_id)).size > 1) return { ok: false, reason: 'mixed_projects', vendorId: null };
  const vendors = new Set(reqs.map((r) => r.vendor_id).filter((v): v is string => !!v));
  if (vendors.size > 1) return { ok: false, reason: 'vendor_conflict', vendorId: null };
  return { ok: true, reason: null, vendorId: vendors.size === 1 ? [...vendors][0]! : null };
}

/** Pull the rule failures out of a refused submit, or an empty list. */
export function parseRequisitionRuleErrors(err: unknown): RequisitionRuleError[] {
  const body = (err as { body?: { detail?: unknown } } | null)?.body;
  const detail = body?.detail as { errors?: unknown } | undefined;
  if (!detail || !Array.isArray(detail.errors)) return [];
  return detail.errors.flatMap((e): RequisitionRuleError[] => {
    if (!e || typeof e !== 'object') return [];
    const r = e as Record<string, unknown>;
    if (typeof r.rule_id !== 'string' || typeof r.message !== 'string') return [];
    return [
      {
        rule_id: r.rule_id,
        message: r.message,
        element_ref: typeof r.element_ref === 'string' ? r.element_ref : null,
        suggestion: typeof r.suggestion === 'string' ? r.suggestion : null,
      },
    ];
  });
}

/* ── Pure helpers ───────────────────────────────────────────────────────── */

/** Add two wire decimals exactly; an invalid input makes the sum unavailable. */
export function addDecimalStrings(left: string, right: string): string | null {
  const negated = right.startsWith('-') ? right.slice(1) : `-${right}`;
  return subtractDecimalStrings(left, negated);
}

function sumQuantities(values: string[]): string {
  let total = '0';
  for (const value of values) {
    total = addDecimalStrings(total, value) ?? total;
  }
  return total;
}

const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** A buy-list source as `/resource-summary/.../buy-list` serves it. */
export interface BuyListSourceLike {
  position_id: string;
  resource_key: string;
  quantity: string;
  unit: string;
  catalog_item_id?: string | null;
  /** The supplier the BOQ suggests for this resource or its position. */
  suggested_vendor_id?: string | null;
  /** The resource's own rate per `unit`, and its currency. */
  unit_rate?: string | null;
  currency?: string | null;
  /** Held by submitted and later requisitions, in `unit`; null when unknown. */
  covered_quantity?: string | null;
  /** `quantity` minus what is held; negative when more is held than the BOQ needs. */
  remaining_quantity?: string | null;
}

/** A buy-list row: the name/unit grouping plus every source folded into it. */
export interface BuyListRowLike {
  name: string;
  unit: string;
  sources?: BuyListSourceLike[];
}

function toSource(s: BuyListSourceLike): RequisitionSourceIn {
  return {
    // Positions without an id are numbered client-side by the aggregator
    // (`__anon_0`); they cannot be linked, so they travel without one.
    boq_position_id: UUID_RE.test(s.position_id) ? s.position_id : null,
    resource_key: s.resource_key || null,
    quantity: s.quantity,
    unit: s.unit || null,
    // The bill's suggestion as the buy list read it; the line inherits it on
    // the server when its sources agree.
    suggested_vendor_id: s.suggested_vendor_id ?? null,
  };
}

/** The quantity a buy-list source still needs requisitioned: its remainder when known, else all of it. */
function sourceQuantity(s: BuyListSourceLike, useRemaining: boolean): string {
  if (useRemaining && s.remaining_quantity != null && isDecimalString(s.remaining_quantity)) {
    return s.remaining_quantity;
  }
  return s.quantity;
}

/**
 * The indicative unit cost of a group of sources: the mean of their rates
 * weighted by the quantity taken from each, when every source carries a rate in
 * one shared currency. Otherwise null, and the line stays without a cost.
 */
export function indicativeUnitCost(
  group: { rate: string | null | undefined; currency: string | null | undefined; quantity: string }[],
): { unit_cost: string; currency_code: string } | null {
  if (group.length === 0) return null;
  const currencies = new Set(group.map((g) => (g.currency ?? '').trim().toUpperCase()));
  if (currencies.size !== 1) return null;
  if (group.some((g) => g.rate == null || g.rate === '' || !isDecimalString(g.rate))) return null;
  const unit_cost = weightedMeanDecimalStrings(group.map((g) => ({ weight: g.quantity, value: g.rate as string })));
  return unit_cost == null ? null : { unit_cost, currency_code: [...currencies][0]! };
}

/**
 * Turn selected buy-list rows into requisition lines.
 *
 * A buy-list row groups resources by name and unit, which is not proof they
 * are the same material. So within a row, sources that name the same catalogue
 * item become one line, and the others become one line each, unless the person
 * confirmed `combineUncoded`: then a row's uncoded sources become one line.
 * Every line keeps every source it was built from.
 *
 * By default each source asks for what is still uncovered (`remaining_quantity`),
 * and a source with nothing left is skipped; `useRemaining: false` asks for the
 * whole BOQ quantity. Each line carries an estimated unit cost from the BOQ
 * rates when they share one currency (see `indicativeUnitCost`).
 */
export function buildRequisitionLinesFromBuyList(
  rows: BuyListRowLike[],
  { combineUncoded, useRemaining = true }: { combineUncoded: boolean; useRemaining?: boolean },
): RequisitionLineIn[] {
  const lines: RequisitionLineIn[] = [];
  for (const row of rows) {
    const sources = (row.sources ?? []).filter((s) => !useRemaining || isPositiveDecimal(sourceQuantity(s, true)));
    const byCatalog = new Map<string, BuyListSourceLike[]>();
    const uncoded: BuyListSourceLike[] = [];
    for (const s of sources) {
      const cat = (s.catalog_item_id ?? '').trim();
      if (cat) byCatalog.set(cat, [...(byCatalog.get(cat) ?? []), s]);
      else uncoded.push(s);
    }
    const line = (group: BuyListSourceLike[], catalog: string | null): RequisitionLineIn => {
      const cost = indicativeUnitCost(
        group.map((s) => ({ rate: s.unit_rate, currency: s.currency, quantity: sourceQuantity(s, useRemaining) })),
      );
      return {
        description: row.name,
        unit: row.unit || null,
        quantity_requested: sumQuantities(group.map((s) => sourceQuantity(s, useRemaining))),
        ...(cost ?? {}),
        catalog_item_id: catalog && UUID_RE.test(catalog) ? catalog : null,
        sources: group.map((s) => ({ ...toSource(s), quantity: sourceQuantity(s, useRemaining) })),
      };
    };
    for (const [cat, group] of byCatalog) lines.push(line(group, cat));
    if (combineUncoded && uncoded.length) lines.push(line(uncoded, null));
    else for (const s of uncoded) lines.push(line([s], null));
  }
  return lines;
}

/** What differs between lines picked for a merge, so the person can confirm it. */
export type MergeConflict = 'unit_cost' | 'currency' | 'cost_line';

export type MergeResult =
  | { ok: true; lines: RequisitionLineIn[] }
  | { ok: false; reason: 'unit_mismatch' }
  | { ok: false; reason: 'needs_confirmation'; conflicts: MergeConflict[] };

function costKey(raw: string | null | undefined): string {
  const v = (raw ?? '').trim();
  if (!v || !isDecimalString(v)) return '0';
  return v.includes('.') ? v.replace(/\.?0+$/, '') || '0' : v;
}

/** The ways the lines at `indices` disagree on cost, currency or cost line. */
export function mergeConflicts(lines: RequisitionLineIn[], indices: number[]): MergeConflict[] {
  const picked = [...new Set(indices)].filter((i) => i >= 0 && i < lines.length).map((i) => lines[i]!);
  const found: MergeConflict[] = [];
  if (new Set(picked.map((l) => costKey(l.unit_cost))).size > 1) found.push('unit_cost');
  if (new Set(picked.map((l) => (l.currency_code ?? '').trim().toUpperCase())).size > 1) found.push('currency');
  const costLines = new Set(
    picked.flatMap((l) => [l.cost_line_id ?? '', ...l.sources.map((s) => s.cost_line_id ?? '')]).filter((v) => v),
  );
  const unlinked = picked.some((l) => !l.cost_line_id && l.sources.every((s) => !s.cost_line_id));
  if (costLines.size > 1 || (costLines.size === 1 && unlinked)) found.push('cost_line');
  return found;
}

/**
 * Merge the lines at `indices` into the first of them, by an explicit choice
 * of the person editing the draft. Refused when the lines are not in one unit
 * (summing metres and tonnes is never a merge), and refused until the person
 * confirms when their unit costs, currencies or cost lines differ. A confirmed
 * merge keeps every source with its own cost line, and prices the line at the
 * quantity-weighted mean cost when the currency is one, otherwise leaves it
 * unpriced.
 */
export function mergeRequisitionLines(
  lines: RequisitionLineIn[],
  indices: number[],
  { confirmed = false }: { confirmed?: boolean } = {},
): MergeResult {
  const picked = [...new Set(indices)].sort((a, b) => a - b).filter((i) => i >= 0 && i < lines.length);
  if (picked.length < 2) return { ok: true, lines };
  const units = new Set(picked.map((i) => (lines[i]!.unit ?? '').trim().toLowerCase()));
  if (units.size > 1) return { ok: false, reason: 'unit_mismatch' };
  const conflicts = mergeConflicts(lines, picked);
  if (conflicts.length > 0 && !confirmed) return { ok: false, reason: 'needs_confirmation', conflicts };
  const first = lines[picked[0]!]!;
  const merged: RequisitionLineIn = {
    ...first,
    quantity_requested: sumQuantities(picked.map((i) => lines[i]!.quantity_requested)),
    sources: picked.flatMap((i) => lines[i]!.sources),
  };
  if (conflicts.length > 0) {
    const cost = conflicts.includes('currency')
      ? null
      : indicativeUnitCost(
          picked.map((i) => ({
            rate: lines[i]!.unit_cost,
            currency: lines[i]!.currency_code,
            quantity: lines[i]!.quantity_requested,
          })),
        );
    merged.unit_cost = cost?.unit_cost ?? '0';
    merged.currency_code = cost?.currency_code ?? '';
    // Each source keeps its own cost line; the merged line has no single one.
    if (conflicts.includes('cost_line')) merged.cost_line_id = null;
  }
  merged.over_allocation_reason =
    picked.map((i) => lines[i]!.over_allocation_reason).find((r) => r && r.trim()) ?? null;
  // Lines that suggest different suppliers lose the suggestion on merge rather
  // than keeping the first one's: nobody chose it for the merged line.
  if (picked.some((i) => 'suggested_vendor_id' in lines[i]!)) {
    const offered = new Set(picked.map((i) => lines[i]!.suggested_vendor_id ?? null));
    merged.suggested_vendor_id = offered.size === 1 ? [...offered][0]! : null;
  }
  const out: RequisitionLineIn[] = [];
  lines.forEach((l, i) => {
    if (i === picked[0]) out.push(merged);
    else if (!picked.includes(i)) out.push(l);
  });
  return { ok: true, lines: out };
}

/** The editable form of a stored line, sources included. */
export function lineToInput(line: RequisitionLine): RequisitionLineIn {
  return {
    description: line.description,
    unit: line.unit,
    quantity_requested: line.quantity_requested,
    unit_cost: line.unit_cost != null ? String(line.unit_cost) : '0',
    currency_code: line.currency_code ?? '',
    catalog_item_id: line.catalog_item_id,
    cost_line_id: line.cost_line_id ?? null,
    over_allocation_reason: line.over_allocation_reason ?? null,
    suggested_vendor_id: line.suggested_vendor_id ?? null,
    required_date: line.required_date ?? null,
    schedule_activity_id: line.schedule_activity_id ?? null,
    schedule_buffer_days: line.schedule_buffer_days ?? null,
    schedule_anchor_date: line.schedule_anchor_date ?? null,
    sources: line.sources.map((s) => ({
      boq_position_id: s.boq_position_id,
      resource_key: s.resource_key,
      quantity: s.quantity,
      unit: s.unit,
      cost_line_id: s.cost_line_id ?? null,
      suggested_vendor_id: s.suggested_vendor_id ?? null,
    })),
  };
}

/**
 * The conversion lines for a set of chosen quantities, or undefined when every
 * line with something left to order takes exactly that: the server then
 * orders everything still open, which is the same order, sent the old way.
 * Lines with an empty or zero quantity are left out of the order.
 */
export function plannedConvertLines(
  reqs: Pick<Requisition, 'items'>[],
  chosen: Record<string, string>,
): { requisition_item_id: string; quantity: string }[] | undefined {
  const open = reqs.flatMap((r) => r.items).filter((i) => isPositiveDecimal(i.quantity_to_order ?? i.quantity_outstanding));
  const lines = open.flatMap((i) => {
    const raw = (chosen[i.id] ?? i.quantity_to_order ?? '').trim();
    return isPositiveDecimal(raw) ? [{ requisition_item_id: i.id, quantity: raw }] : [];
  });
  const unchanged =
    lines.length === open.length &&
    lines.every((l) => {
      const item = open.find((i) => i.id === l.requisition_item_id)!;
      const diff = subtractDecimalStrings(l.quantity, item.quantity_to_order ?? l.quantity);
      return diff !== null && /^-?0(\.0+)?$/.test(diff);
    });
  return unchanged ? undefined : lines;
}

/** A decimal string greater than zero. */
export function isPositiveDecimal(raw: string | null | undefined): boolean {
  const value = (raw ?? '').trim();
  if (!/^\d+(\.\d+)?$/.test(value)) return false;
  return /[1-9]/.test(value);
}

/** Days between two ISO dates (b minus a), or null when either is missing or invalid. */
export function daysBetween(a: string | null | undefined, b: string | null | undefined): number | null {
  if (!a || !b) return null;
  const left = Date.parse(`${a.slice(0, 10)}T00:00:00Z`);
  const right = Date.parse(`${b.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(left) || Number.isNaN(right)) return null;
  return Math.round((right - left) / 86_400_000);
}
