// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site Logistics & Delivery.
 *
 * All endpoints are prefixed with /v1/site-logistics/. Trailing slashes match
 * the FastAPI routes exactly, avoiding a 307 redirect that some proxies rewrite
 * without forwarding the auth header (which would surface as an empty list).
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

import type { Verdict } from './plan/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type DeliveryStatus =
  | 'requested'
  | 'approved'
  | 'rejected'
  | 'arrived'
  | 'completed';

/** What the server lets this reader do with one record of the board, each with its reason. */
export interface BoardCan {
  edit?: Verdict;
  delete?: Verdict;
  /** Deliveries only. */
  approve?: Verdict;
  reject?: Verdict;
}

export type BoardKind = 'gate' | 'zone' | 'delivery';

/** The board lists are plain arrays, so what may be created is asked for separately. */
export type BoardCreate = Partial<Record<BoardKind, { create?: Verdict }>>;

export interface Gate {
  id: string;
  can?: BoardCan;
  project_id: string;
  name: string;
  open_time: string;
  close_time: string;
  capacity_per_slot: number;
  notes: string | null;
  /** Catalogue code of the kind of access (road gate, rail siding ...). */
  access_kind?: string | null;
  /** Load and dimension limits as decimal strings; the plan checks transports against them. */
  max_axle_load_t?: string | null;
  max_gross_t?: string | null;
  max_height_m?: string | null;
  max_width_m?: string | null;
  max_length_m?: string | null;
  turning_radius_m?: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface LaydownZone {
  id: string;
  can?: BoardCan;
  project_id: string;
  name: string;
  capacity_desc: string | null;
  usage_note: string | null;
  created_by: string | null;
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * One bill position a delivery carries.
 *
 * `boq_position_id` is null either because the line was never linked to the
 * estimate, or because the position was deleted after the booking was made -
 * `position_ordinal` tells the two apart, and a line that kept its ordinal but
 * lost its id is a detached line: the material still arrived.
 */
export interface DeliveryLine {
  id: string;
  delivery_id: string;
  boq_position_id: string | null;
  position_ordinal: string | null;
  description: string;
  /** Decimal as a string, never a float. */
  quantity: string;
  unit: string;
  note: string | null;
  sort_order: number;
}

export interface DeliveryBooking {
  id: string;
  can?: BoardCan;
  /** What the server could not check for this delivery, for example gate hours on a site without a time zone. */
  warnings?: { code: string; severity: string; field?: string | null }[];
  project_id: string;
  gate_id: string | null;
  supplier_name: string;
  contact_name: string | null;
  contact_phone: string | null;
  vehicle_type: string | null;
  materials_desc: string | null;
  window_start: string;
  window_end: string;
  status: DeliveryStatus;
  po_ref: string | null;
  /** A flow of the logistics concept; the server refuses a code the concept does not have. */
  flow_code?: string | null;
  notes: string | null;
  created_by: string | null;
  lines: DeliveryLine[];
  metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/**
 * A line as it is written back: the bill supplies description and unit.
 *
 * `position_ordinal` is only read for a line with no position, so a detached
 * line keeps the ordinal it was delivered against when the delivery is edited.
 */
export interface DeliveryLineInput {
  boq_position_id?: string | null;
  position_ordinal?: string | null;
  description?: string;
  quantity: string;
  unit?: string;
  note?: string | null;
}

/** One estimate line with what has been booked and delivered against it. */
export interface BillCoverageRow {
  position_id: string;
  boq_id: string;
  ordinal: string;
  description: string;
  unit: string;
  /** Every quantity and amount below is a Decimal serialised as a string. */
  bill_quantity: string;
  unit_rate: string;
  bill_total: string;
  delivered_quantity: string;
  booked_quantity: string;
  outstanding_quantity: string;
  delivered_value: string;
  delivery_line_count: number;
  over_delivered: boolean;
}

export interface BillCoverage {
  rows: BillCoverageRow[];
  total: number;
  truncated: boolean;
  currency: string;
  linked_position_count: number;
  delivered_value_total: string;
  detached_line_count: number;
}

export interface SiteLogisticsStats {
  total_deliveries: number;
  by_status: Record<string, number>;
  gate_count: number;
  laydown_zone_count: number;
  upcoming_approved: number;
  deliveries_linked_to_bill: number;
  positions_covered: number;
}

export interface CreateGatePayload {
  project_id: string;
  name: string;
  open_time?: string;
  close_time?: string;
  capacity_per_slot?: number;
  notes?: string;
  /** Catalogue code of the kind of access (road gate, rail siding ...). */
  access_kind?: string | null;
  /** Load and dimension limits as decimal strings; the plan checks transports against them. */
  max_axle_load_t?: string | null;
  max_gross_t?: string | null;
  max_height_m?: string | null;
  max_width_m?: string | null;
  max_length_m?: string | null;
  turning_radius_m?: string | null;
}

export type UpdateGatePayload = Partial<Omit<CreateGatePayload, 'project_id'>>;

export interface CreateLaydownZonePayload {
  project_id: string;
  name: string;
  capacity_desc?: string;
  usage_note?: string;
}

export type UpdateLaydownZonePayload = Partial<
  Omit<CreateLaydownZonePayload, 'project_id'>
>;

export interface CreateDeliveryPayload {
  project_id: string;
  gate_id?: string | null;
  supplier_name: string;
  contact_name?: string;
  contact_phone?: string;
  vehicle_type?: string;
  materials_desc?: string;
  window_start: string;
  window_end: string;
  status?: DeliveryStatus;
  po_ref?: string;
  flow_code?: string | null;
  notes?: string;
  lines?: DeliveryLineInput[];
}

/**
 * `lines` replaces the booking's whole list when present and leaves it alone
 * when omitted, so a status-only PATCH never touches what the lorry carries.
 */
export type UpdateDeliveryPayload = Partial<
  Omit<CreateDeliveryPayload, 'project_id'>
>;

export interface DeliveryFilters {
  day?: string;
  gate_id?: string;
  status?: DeliveryStatus | '';
}

/* ── Gates ──────────────────────────────────────────────────────────────── */

export async function fetchBoardCan(projectId: string): Promise<BoardCreate> {
  return apiGet<BoardCreate>(`/v1/site-logistics/can/?project_id=${encodeURIComponent(projectId)}`);
}

export async function fetchGates(projectId: string): Promise<Gate[]> {
  return apiGet<Gate[]>(
    `/v1/site-logistics/gates/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createGate(data: CreateGatePayload): Promise<Gate> {
  return apiPost<Gate>('/v1/site-logistics/gates/', data);
}

export async function updateGate(id: string, data: UpdateGatePayload): Promise<Gate> {
  return apiPatch<Gate>(`/v1/site-logistics/gates/${id}`, data);
}

export async function deleteGate(id: string): Promise<void> {
  return apiDelete<void>(`/v1/site-logistics/gates/${id}`);
}

/* ── Laydown zones ──────────────────────────────────────────────────────── */

export async function fetchLaydownZones(projectId: string): Promise<LaydownZone[]> {
  return apiGet<LaydownZone[]>(
    `/v1/site-logistics/laydown-zones/?project_id=${encodeURIComponent(projectId)}`,
  );
}

export async function createLaydownZone(
  data: CreateLaydownZonePayload,
): Promise<LaydownZone> {
  return apiPost<LaydownZone>('/v1/site-logistics/laydown-zones/', data);
}

export async function updateLaydownZone(
  id: string,
  data: UpdateLaydownZonePayload,
): Promise<LaydownZone> {
  return apiPatch<LaydownZone>(`/v1/site-logistics/laydown-zones/${id}`, data);
}

export async function deleteLaydownZone(id: string): Promise<void> {
  return apiDelete<void>(`/v1/site-logistics/laydown-zones/${id}`);
}

/* ── Deliveries ─────────────────────────────────────────────────────────── */

export async function fetchDeliveries(
  projectId: string,
  filters?: DeliveryFilters,
): Promise<DeliveryBooking[]> {
  const params = new URLSearchParams();
  params.set('project_id', projectId);
  if (filters?.day) params.set('day', filters.day);
  if (filters?.gate_id) params.set('gate_id', filters.gate_id);
  if (filters?.status) params.set('status', filters.status);
  return apiGet<DeliveryBooking[]>(`/v1/site-logistics/deliveries/?${params.toString()}`);
}

export async function createDelivery(
  data: CreateDeliveryPayload,
): Promise<DeliveryBooking> {
  return apiPost<DeliveryBooking>('/v1/site-logistics/deliveries/', data);
}

export async function updateDelivery(
  id: string,
  data: UpdateDeliveryPayload,
): Promise<DeliveryBooking> {
  return apiPatch<DeliveryBooking>(`/v1/site-logistics/deliveries/${id}`, data);
}

export async function deleteDelivery(id: string): Promise<void> {
  return apiDelete<void>(`/v1/site-logistics/deliveries/${id}`);
}

export async function approveDelivery(
  id: string,
  reason?: string,
): Promise<DeliveryBooking> {
  return apiPost<DeliveryBooking>(`/v1/site-logistics/deliveries/${id}/approve/`, {
    reason,
  });
}

export async function rejectDelivery(
  id: string,
  reason?: string,
): Promise<DeliveryBooking> {
  return apiPost<DeliveryBooking>(`/v1/site-logistics/deliveries/${id}/reject/`, {
    reason,
  });
}

/* ── Bill coverage ──────────────────────────────────────────────────────── */

export interface BillCoverageFilters {
  boq_id?: string;
  search?: string;
  limit?: number;
}

/**
 * Read the project's bill as a delivery ledger.
 *
 * Backs both the coverage table and the position picker in the booking dialog,
 * so the picker shows how much of a line is still outstanding at the moment
 * someone books a lorry against it.
 */
export async function fetchBillCoverage(
  projectId: string,
  filters?: BillCoverageFilters,
): Promise<BillCoverage> {
  const params = new URLSearchParams();
  params.set('project_id', projectId);
  if (filters?.boq_id) params.set('boq_id', filters.boq_id);
  if (filters?.search) params.set('search', filters.search);
  if (filters?.limit) params.set('limit', String(filters.limit));
  return apiGet<BillCoverage>(`/v1/site-logistics/bill-coverage/?${params.toString()}`);
}

/* ── Stats ──────────────────────────────────────────────────────────────── */

export async function fetchSiteLogisticsStats(
  projectId: string,
): Promise<SiteLogisticsStats> {
  return apiGet<SiteLogisticsStats>(
    `/v1/site-logistics/stats/?project_id=${encodeURIComponent(projectId)}`,
  );
}

/* ── Neighbour issues (logistics plan) ──────────────────────────────────── */

export type NeighbourIssueState = 'received' | 'acknowledged' | 'action_taken' | 'closed';

/** A complaint from the surroundings, as `GET /projects/{id}/neighbour-issues` returns it. */
export interface NeighbourIssue {
  id: string;
  kind: string;
  reported_on: string;
  reporter: string;
  location: Record<string, unknown> | null;
  description: string;
  transport_id: string | null;
  delivery_id: string | null;
  owner_user_id: string | null;
  response: string;
  response_due: string | null;
  state: NeighbourIssueState | string;
  /** Past its response date and not yet acknowledged (server-side rule 18). */
  overdue: boolean;
  created_at: string | null;
}

export interface NeighbourIssuePage {
  items: NeighbourIssue[];
  total: number;
  offset: number;
  limit: number;
}

/** Every neighbour issue of a project; closed ones are filtered by the caller. */
export async function fetchNeighbourIssues(projectId: string): Promise<NeighbourIssuePage> {
  return apiGet<NeighbourIssuePage>(
    `/v1/site-logistics/projects/${encodeURIComponent(projectId)}/neighbour-issues`,
  );
}
