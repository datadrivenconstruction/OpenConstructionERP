// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Material requisitions - typed client for `/v1/procurement/requisitions`
 * plus the pure helpers that turn buy-list rows into requisition lines.
 *
 * Quantities are the Decimal strings the backend serves and are summed as
 * strings (`addDecimalStrings`), never through a float, so 0.1 + 0.2 stays 0.3.
 */

import { apiGet, apiPatch, apiPost } from '@/shared/lib/api';
import { subtractDecimalStrings } from '@/shared/lib/exactDecimal';

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
}

export interface RequisitionLineIn {
  description: string;
  unit: string | null;
  quantity_requested: string;
  /** Decimal string. Sent back on every edit, or the server resets it to 0. */
  unit_cost?: string;
  currency_code?: string;
  catalog_item_id?: string | null;
  sources: RequisitionSourceIn[];
}

export interface RequisitionSource extends RequisitionSourceIn {
  id: string;
  cost_line_id: string | null;
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
  sources: RequisitionSource[];
  /** Purchase order lines raised from this line by a conversion. */
  po_items?: RequisitionPOItemRef[];
}

/** A purchase order line that came from a requisition line. */
export interface RequisitionPOItemRef {
  po_item_id: string;
  po_id: string;
  po_number: string | null;
  quantity: string;
  unit: string | null;
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
  notes: string | null;
  requester_id: string | null;
  approver_id?: string | null;
  po_id: string | null;
  po_number?: string | null;
  vendor_id?: string | null;
  vendor_name?: string | null;
  vendor_status?: string | null;
  submitted_by?: string | null;
  decided_at?: string | null;
  decision_comment?: string | null;
  items: RequisitionLine[];
  reconciliation: Record<string, string>;
  history: RequisitionHistoryEntry[];
  created_at: string;
  updated_at: string;
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
}

export interface RequisitionUpdateBody {
  title?: string | null;
  required_date?: string | null;
  notes?: string | null;
  vendor_id?: string | null;
  items?: RequisitionLineIn[];
}

export interface ConvertToPOBody {
  project_id: string;
  requisition_ids: string[];
  vendor_id?: string | null;
  delivery_date?: string | null;
  notes?: string | null;
}

export interface ConvertToPOResult {
  po_id: string;
  po_number: string;
  project_id: string;
  requisition_ids: string[];
  line_count: number;
  vendor_warnings: string[];
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
export type ConvertBlockReason = 'empty' | 'not_approved' | 'mixed_projects' | 'vendor_conflict';

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
  reqs: Pick<Requisition, 'status' | 'project_id' | 'vendor_id'>[],
): ConvertCheck {
  if (reqs.length === 0) return { ok: false, reason: 'empty', vendorId: null };
  if (reqs.some((r) => r.status !== 'approved')) return { ok: false, reason: 'not_approved', vendorId: null };
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
  };
}

/**
 * Turn selected buy-list rows into requisition lines.
 *
 * A buy-list row groups resources by name and unit, which is not proof they
 * are the same material. So within a row, sources that name the same catalogue
 * item become one line, and the others become one line each, unless the person
 * confirmed `combineUncoded`: then a row's uncoded sources become one line.
 * Every line keeps every source it was built from.
 */
export function buildRequisitionLinesFromBuyList(
  rows: BuyListRowLike[],
  { combineUncoded }: { combineUncoded: boolean },
): RequisitionLineIn[] {
  const lines: RequisitionLineIn[] = [];
  for (const row of rows) {
    const sources = row.sources ?? [];
    const byCatalog = new Map<string, BuyListSourceLike[]>();
    const uncoded: BuyListSourceLike[] = [];
    for (const s of sources) {
      const cat = (s.catalog_item_id ?? '').trim();
      if (cat) byCatalog.set(cat, [...(byCatalog.get(cat) ?? []), s]);
      else uncoded.push(s);
    }
    const line = (group: BuyListSourceLike[], catalog: string | null): RequisitionLineIn => ({
      description: row.name,
      unit: row.unit || null,
      quantity_requested: sumQuantities(group.map((s) => s.quantity)),
      catalog_item_id: catalog && UUID_RE.test(catalog) ? catalog : null,
      sources: group.map(toSource),
    });
    for (const [cat, group] of byCatalog) lines.push(line(group, cat));
    if (combineUncoded && uncoded.length) lines.push(line(uncoded, null));
    else for (const s of uncoded) lines.push(line([s], null));
  }
  return lines;
}

/**
 * Merge the lines at `indices` into the first of them, by an explicit choice
 * of the person editing the draft. Returns null when the lines are not in one
 * unit: summing metres and tonnes is never a merge.
 */
export function mergeRequisitionLines(lines: RequisitionLineIn[], indices: number[]): RequisitionLineIn[] | null {
  const picked = [...new Set(indices)].sort((a, b) => a - b).filter((i) => i >= 0 && i < lines.length);
  if (picked.length < 2) return lines;
  const units = new Set(picked.map((i) => (lines[i]!.unit ?? '').trim().toLowerCase()));
  if (units.size > 1) return null;
  const first = lines[picked[0]!]!;
  const merged: RequisitionLineIn = {
    ...first,
    quantity_requested: sumQuantities(picked.map((i) => lines[i]!.quantity_requested)),
    sources: picked.flatMap((i) => lines[i]!.sources),
  };
  const out: RequisitionLineIn[] = [];
  lines.forEach((l, i) => {
    if (i === picked[0]) out.push(merged);
    else if (!picked.includes(i)) out.push(l);
  });
  return out;
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
    sources: line.sources.map((s) => ({
      boq_position_id: s.boq_position_id,
      resource_key: s.resource_key,
      quantity: s.quantity,
      unit: s.unit,
    })),
  };
}
