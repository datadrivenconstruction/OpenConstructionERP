// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for Site Inventory (on-site material stock ledger / metering).
 *
 * Every endpoint is project-scoped in the path and mounted under
 * /v1/site-inventory/projects/{projectId}/... (the backend module
 * oe_site_inventory is served at /api/v1/site-inventory). Money and
 * quantities cross the wire as canonical decimal STRINGS, never floats.
 */

import { apiDelete, apiGet, apiPatch, apiPost } from '@/shared/lib/api';

/* -- Types ----------------------------------------------------------------- */

export type MovementType = 'INBOUND' | 'CONSUMPTION' | 'WASTE' | 'TRANSFER';

export const MOVEMENT_TYPES: MovementType[] = ['INBOUND', 'CONSUMPTION', 'WASTE', 'TRANSFER'];

export interface StockLocation {
  id: string;
  project_id: string;
  name: string;
  code: string | null;
  latitude: string | null;
  longitude: string | null;
  address: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface LocationCreate {
  name: string;
  code?: string;
  latitude?: string;
  longitude?: string;
  address?: string;
  is_active?: boolean;
}

export interface StockItem {
  id: string;
  project_id: string;
  name: string;
  sku: string | null;
  unit: string;
  boq_position_id: string | null;
  procurement_req_item_id: string | null;
  default_location_id: string | null;
  standard_unit_cost: string | null;
  currency: string;
  reorder_point: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface StockItemCreate {
  name: string;
  sku?: string;
  unit?: string;
  /** The BoQ position that priced this material. What makes the stock record
   *  answerable against the estimate instead of a free-standing description. */
  boq_position_id?: string;
  /** The requisition line this material was ordered on - the "ordered" leg of
   *  the ordered / delivered / in-the-bill comparison. */
  procurement_req_item_id?: string;
  default_location_id?: string;
  standard_unit_cost?: string;
  currency?: string;
  reorder_point?: string;
  is_active?: boolean;
}

/** Patch body for a stock item. Only the keys present are written; sending an
 *  explicit `null` clears a link, which is how a wrong one gets corrected. */
export interface StockItemUpdate {
  name?: string;
  sku?: string;
  unit?: string;
  boq_position_id?: string | null;
  procurement_req_item_id?: string | null;
  default_location_id?: string | null;
  standard_unit_cost?: string;
  currency?: string;
  reorder_point?: string;
  is_active?: boolean;
}

export interface StockMovement {
  id: string;
  project_id: string;
  item_id: string;
  movement_type: MovementType;
  quantity: string;
  unit_cost: string;
  currency: string;
  location_id: string | null;
  to_location_id: string | null;
  boq_position_id: string | null;
  goods_receipt_id: string | null;
  occurred_at: string;
  actor_id: string | null;
  note: string | null;
  created_at: string;
  updated_at: string;
}

export interface MovementCreate {
  item_id: string;
  movement_type: MovementType;
  quantity: string;
  unit_cost?: string;
  currency?: string;
  location_id?: string;
  to_location_id?: string;
  /** The BoQ position this movement is booked against. Left unset, the report
   *  attributes the movement to the position of the item it moved. */
  boq_position_id?: string;
  occurred_at?: string;
  note?: string;
}

export interface StockOnHandRow {
  item_id: string;
  name: string;
  unit: string;
  on_hand: string;
}

export interface StockOnHandResponse {
  project_id: string;
  location_id: string | null;
  item_count: number;
  rows: StockOnHandRow[];
}

/** Whether two units may be compared as quantities of the same thing.
 *  `unknown` means at least one side did not state a unit - not the same as a
 *  mismatch, and rendered differently, because one is a warning and the other
 *  is a gap to fill in. */
export type UnitAgreement = 'match' | 'mismatch' | 'unknown';

/** One BoQ position's coverage: ordered, delivered, installed and left over.
 *  Every derived figure is `null` where the units behind it did not agree; the
 *  raw quantities are always present because they are true on their own. */
export interface PositionCoverageRow {
  position_id: string;
  ordinal: string;
  description: string;
  bill_unit: string;
  bill_quantity: string;
  inventory_unit: string;
  bill_unit_agreement: UnitAgreement;
  order_unit_agreement: UnitAgreement;
  ordered_quantity: string | null;
  delivered_quantity: string;
  consumed_quantity: string;
  wasted_quantity: string;
  on_hand_quantity: string;
  outstanding_quantity: string | null;
  delivered_pct: string | null;
  installed_pct: string | null;
  item_ids: string[];
}

export interface PositionCoverageResponse {
  project_id: string;
  position_count: number;
  /** How many rows had to withhold a comparison because the units disagreed. */
  unmatched_unit_count: number;
  lines: PositionCoverageRow[];
}

export interface UnfixedValueRow {
  item_id: string;
  name: string;
  unit: string;
  on_hand: string;
  unit_cost: string | null;
  value: string | null;
  currency: string;
  valuation_basis: 'inbound_average' | 'standard_cost' | 'none';
  boq_position_id: string | null;
}

export interface CurrencyTotal {
  currency: string;
  value: string;
}

export interface UnfixedValueResponse {
  project_id: string;
  lines: UnfixedValueRow[];
  /** Split per currency and never blended - two currencies have no common sum. */
  totals_by_currency: CurrencyTotal[];
  unvalued_item_count: number;
  is_single_currency: boolean;
}

export interface VarianceLine {
  position_id: string;
  budgeted_cost: string;
  actual_cost: string;
  variance: string;
  variance_pct: string | null;
  consumed_quantity: string;
  is_over_budget: boolean;
}

export interface MaterialVarianceResponse {
  project_id: string;
  total_budgeted_cost: string;
  total_actual_cost: string;
  total_variance: string;
  variance_pct: string | null;
  position_count: number;
  over_budget_count: number;
  lines: VarianceLine[];
}

/* -- Endpoint base --------------------------------------------------------- */

function base(projectId: string): string {
  return `/v1/site-inventory/projects/${projectId}`;
}

/* -- Locations ------------------------------------------------------------- */

export async function fetchLocations(projectId: string): Promise<StockLocation[]> {
  return apiGet<StockLocation[]>(`${base(projectId)}/locations`);
}

export async function createLocation(
  projectId: string,
  data: LocationCreate,
): Promise<StockLocation> {
  return apiPost<StockLocation, LocationCreate>(`${base(projectId)}/locations`, data);
}

/** Delete a storage location that nothing points at.
 *
 *  Refuses with 409 while any movement names it on either leg, any item
 *  defaults to it, or stock is still standing there. See `deleteGuard.ts` for
 *  why the database would not refuse on its own. */
export async function deleteLocation(projectId: string, locationId: string): Promise<void> {
  await apiDelete<void>(`${base(projectId)}/locations/${locationId}`);
}

/* -- Items ----------------------------------------------------------------- */

export async function fetchItems(projectId: string): Promise<StockItem[]> {
  return apiGet<StockItem[]>(`${base(projectId)}/items`);
}

export async function createItem(projectId: string, data: StockItemCreate): Promise<StockItem> {
  return apiPost<StockItem, StockItemCreate>(`${base(projectId)}/items`, data);
}

export async function updateItem(
  projectId: string,
  itemId: string,
  data: StockItemUpdate,
): Promise<StockItem> {
  return apiPatch<StockItem, StockItemUpdate>(`${base(projectId)}/items/${itemId}`, data);
}

/** Delete a stock item that has never moved.
 *
 *  Refuses with 409 once anything has been booked against it: the movement
 *  rows cascade, so the delete would take the ledger with it. */
export async function deleteItem(projectId: string, itemId: string): Promise<void> {
  await apiDelete<void>(`${base(projectId)}/items/${itemId}`);
}

/* -- Movements ------------------------------------------------------------- */

export async function fetchMovements(projectId: string, limit = 200): Promise<StockMovement[]> {
  const params = new URLSearchParams({ limit: String(limit) });
  return apiGet<StockMovement[]>(`${base(projectId)}/movements?${params.toString()}`);
}

/** The movements that name one item, or one location on either leg.
 *
 *  A separate call rather than more parameters on {@link fetchMovements},
 *  which feeds the ledger table and wants the project's recent movements. This
 *  one asks a yes/no question about a single row and wants the server's own
 *  filter to answer it: `item_id` and `location_id` here are the same filters
 *  the delete guard counts with, and the location filter matches the source
 *  and the destination leg exactly as that count does.
 *
 *  `limit` is the endpoint's maximum. A project past it has long since
 *  answered the only question being asked - whether anything holds the row. */
export async function fetchMovementsFor(
  projectId: string,
  filter: { itemId?: string; locationId?: string },
): Promise<StockMovement[]> {
  const params = new URLSearchParams({ limit: '5000' });
  if (filter.itemId) params.set('item_id', filter.itemId);
  if (filter.locationId) params.set('location_id', filter.locationId);
  return apiGet<StockMovement[]>(`${base(projectId)}/movements?${params.toString()}`);
}

export async function recordMovement(
  projectId: string,
  data: MovementCreate,
): Promise<StockMovement> {
  return apiPost<StockMovement, MovementCreate>(`${base(projectId)}/movements`, data);
}

/* -- Derived reports ------------------------------------------------------- */

export async function fetchStockOnHand(projectId: string): Promise<StockOnHandResponse> {
  return apiGet<StockOnHandResponse>(`${base(projectId)}/stock-on-hand`);
}

/** Stock on hand inside one storage location - the balances that would be left
 *  standing nowhere if that location were removed. Rows with a zero balance are
 *  returned too, so a caller counting what is stored there has to skip them. */
export async function fetchStockOnHandAt(
  projectId: string,
  locationId: string,
): Promise<StockOnHandResponse> {
  const params = new URLSearchParams({ location_id: locationId });
  return apiGet<StockOnHandResponse>(`${base(projectId)}/stock-on-hand?${params.toString()}`);
}

export async function fetchPositionCoverage(
  projectId: string,
): Promise<PositionCoverageResponse> {
  return apiGet<PositionCoverageResponse>(`${base(projectId)}/reports/position-coverage`);
}

export async function fetchUnfixedValue(projectId: string): Promise<UnfixedValueResponse> {
  return apiGet<UnfixedValueResponse>(`${base(projectId)}/reports/unfixed-value`);
}

export async function fetchMaterialVariance(
  projectId: string,
): Promise<MaterialVarianceResponse> {
  return apiGet<MaterialVarianceResponse>(`${base(projectId)}/reports/material-variance`);
}
