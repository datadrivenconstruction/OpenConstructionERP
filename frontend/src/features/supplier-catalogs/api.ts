// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * API helpers for the Supplier Catalogs module.
 *
 * Backed by /api/v1/supplier-catalogs/ — see backend/app/modules/supplier_catalogs/router.py
 */

import {
  apiGet,
  apiPost,
  apiPatch,
  apiDelete,
  extractErrorMessageFromBody,
  fetchWithAuth,
  type Page,
} from '@/shared/lib/api';

/* ── Types ─────────────────────────────────────────────────────────────── */

export type VendorStatus = 'active' | 'suspended' | 'blacklisted' | 'pending';
export type PRStatus =
  | 'draft'
  | 'submitted'
  | 'pending_approval'
  | 'approved'
  | 'rejected'
  | 'converted';
export type POStatus =
  | 'draft'
  | 'sent'
  | 'acknowledged'
  | 'partially_received'
  | 'received'
  | 'closed'
  | 'cancelled';
// Both unions below described columns they had never matched, and survived
// because nothing branches on either of them - they are each referenced once,
// at the field they annotate. Corrected against what the service actually
// writes rather than extended on top of the errors.
//   'matched' was listed here and is never written to VendorInvoice.status; it
//   belongs to three_way_match_status. 'disputed' was missing and IS written,
//   by the three-way match on a price or quantity exception.
export type InvoiceStatus = 'received' | 'exception' | 'disputed' | 'approved' | 'paid';
//   'auto_matched' was listed here and is never written to the column either;
//   it is the value of MatchResult.status, a different field on a different
//   response. The column takes 'matched'.
//   'not_comparable' means the match could not run - see match_invoice.
export type MatchStatus = 'pending' | 'matched' | 'exception' | 'not_comparable';

export interface Vendor {
  id: string;
  code: string;
  name: string;
  legal_name: string | null;
  tax_id: string | null;
  contact_id: string | null;
  status: VendorStatus;
  currency: string;
  payment_terms_days: number;
  rating: number | null;
  country_code: string | null;
  region: string | null;
  categories_json: unknown[];
  preferred_for_json: unknown[];
  contacts_json: unknown[];
  notes: string | null;
  created_at: string;
  updated_at: string;
}

export interface ItemCategory {
  id: string;
  code: string;
  name: string;
  parent_id: string | null;
  level: number;
  classification_ref: string | null;
}

export interface CatalogItem {
  id: string;
  sku: string;
  name: string;
  description: string | null;
  category_id: string | null;
  unit_of_measure: string;
  manufacturer: string | null;
  mpn: string | null;
  spec_json: Record<string, unknown>;
  hazard_class: string | null;
  shelf_life_days: number | null;
  reorder_point: number | string;
  active: boolean;
  gtin?: string | null;
  product_url?: string | null;
  attachment_count?: number;
}

export interface PriceList {
  id: string;
  vendor_id: string;
  name: string;
  valid_from: string | null;
  valid_to: string | null;
  currency: string;
  status: string;
  uploaded_by: string | null;
  entry_count?: number;
  expired?: boolean;
}

export interface PriceComparisonRow {
  vendor_id: string;
  vendor_code: string;
  vendor_name: string;
  unit_price: number | string;
  currency: string;
  min_order_qty: number | string;
  lead_time_days: number;
  price_list_id: string;
  rating: number | null;
  gross_price?: number | string | null;
  net_price?: number | string | null;
  discount_pct?: number | string | null;
  discount_source?: DiscountSource | null;
  entry_id?: string | null;
  valid_to?: string | null;
}

export interface PRLine {
  id: string;
  pr_id: string;
  catalog_item_id: string | null;
  description: string;
  quantity: number | string;
  unit_of_measure: string;
  estimated_unit_price: number | string;
  estimated_total: number | string;
}

export interface PR {
  id: string;
  number: string;
  project_id: string;
  requested_by: string | null;
  requested_at: string | null;
  needed_by: string | null;
  status: PRStatus;
  total_estimate: number | string;
  currency: string;
  notes: string | null;
  approval_chain_json: unknown[];
  lines: PRLine[];
}

export interface POLine {
  id: string;
  po_id: string;
  catalog_item_id: string | null;
  description: string;
  ordered_qty: number | string;
  unit_of_measure: string;
  unit_price: number | string;
  line_total: number | string;
  received_qty: number | string;
  invoiced_qty: number | string;
}

export interface PO {
  id: string;
  number: string;
  vendor_id: string;
  project_id: string;
  contract_id: string | null;
  pr_id: string | null;
  status: POStatus;
  order_date: string | null;
  expected_delivery: string | null;
  currency: string;
  subtotal: number | string;
  tax: number | string;
  total: number | string;
  terms: string | null;
  lines: POLine[];
}

export interface VendorInvoice {
  id: string;
  number: string;
  vendor_id: string;
  po_id: string | null;
  invoice_date: string | null;
  due_date: string | null;
  currency: string;
  subtotal: number | string;
  tax: number | string;
  total: number | string;
  status: InvoiceStatus;
  three_way_match_status: MatchStatus;
  exception_reason: string | null;
}

export interface Warehouse {
  id: string;
  code: string;
  name: string;
  project_id: string | null;
  address: string | null;
  manager_user_id: string | null;
  status: string;
}

export interface StockBalance {
  id: string;
  warehouse_id: string;
  catalog_item_id: string;
  batch_lot: string;
  quantity_on_hand: number | string;
  quantity_reserved: number | string;
  /** null when no single-currency average exists; see cost_state for which case. */
  unit_cost_avg: number | string | null;
  /** ISO code for unit_cost_avg, set only when cost_state is 'single'. */
  currency: string | null;
  cost_state: 'single' | 'mixed' | 'unknown';
  last_movement_at: string | null;
}

/* ── Payloads ──────────────────────────────────────────────────────────── */

export interface CreateVendorPayload {
  code: string;
  name: string;
  legal_name?: string;
  tax_id?: string;
  currency?: string;
  payment_terms_days?: number;
  country_code?: string;
  region?: string;
  categories?: string[];
  preferred_for?: string[];
  notes?: string;
}

export interface CreateCatalogItemPayload {
  sku: string;
  name: string;
  description?: string;
  category_id?: string;
  unit_of_measure?: string;
  manufacturer?: string;
  mpn?: string;
  hazard_class?: string;
  shelf_life_days?: number;
  reorder_point?: number | string;
  gtin?: string;
  product_url?: string;
}

/* The three Update payloads below deliberately drop the record's business key,
   `code` on a vendor and a warehouse and `sku` on a catalog item, because the
   PATCH routes do not accept it. Every other record in the module quotes that
   key, so rekeying is not a correction and is not offered here. A warehouse
   also cannot be moved to another project this way: the project decides who
   may read its balances. */

export interface UpdateVendorPayload {
  name?: string;
  legal_name?: string;
  tax_id?: string;
  currency?: string;
  payment_terms_days?: number;
  country_code?: string;
  region?: string;
  categories?: string[];
  preferred_for?: string[];
  notes?: string;
  tolerance_profile_name?: string;
}

export interface UpdateCatalogItemPayload {
  name?: string;
  description?: string;
  category_id?: string;
  unit_of_measure?: string;
  manufacturer?: string;
  mpn?: string;
  hazard_class?: string;
  shelf_life_days?: number;
  reorder_point?: number | string;
  gtin?: string;
  commodity_code?: string;
  commodity_scheme?: string;
  active?: boolean;
  product_url?: string;
}

export interface UpdateWarehousePayload {
  name?: string;
  address?: string;
  manager_user_id?: string;
}

export interface CreatePRPayload {
  project_id: string;
  needed_by?: string;
  notes?: string;
  currency?: string;
  approval_chain?: string[];
  lines: Array<{
    catalog_item_id?: string;
    description: string;
    quantity: number;
    unit_of_measure?: string;
    estimated_unit_price?: number;
  }>;
}

export interface CreatePOPayload {
  vendor_id: string;
  project_id: string;
  pr_id?: string;
  order_date?: string;
  expected_delivery?: string;
  currency?: string;
  tax?: number;
  terms?: string;
  lines: Array<{
    catalog_item_id?: string;
    description: string;
    ordered_qty: number;
    unit_of_measure?: string;
    unit_price: number;
  }>;
}

export interface CreateWarehousePayload {
  code: string;
  name: string;
  project_id?: string;
  address?: string;
}

/* ── Helpers ───────────────────────────────────────────────────────────── */

function qs(params: Record<string, string | number | undefined>): string {
  const s = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== '' && v !== null) s.set(k, String(v));
  }
  const out = s.toString();
  return out ? `?${out}` : '';
}

/**
 * The same query string without the leading `?`, for the paged routes below.
 *
 * check_page_envelope_consumers.py binds a URL literal to the call it stands
 * next to and cuts the route at the first `?`. Interpolating `qs()` puts the
 * `?` inside the interpolation, so the route it extracts is not the route -
 * the endpoint could go half migrated with the gate reporting nothing. Writing
 * the `?` unconditionally outside the interpolation fixes that, and a trailing
 * `?` with an empty query is a valid URL that parses as no query at all.
 */
function query(params: Record<string, string | number | undefined>): string {
  return qs(params).replace(/^\?/, '');
}

/* ── Vendors ───────────────────────────────────────────────────────────── */

export function listVendors(params?: {
  status?: string;
  country_code?: string;
  offset?: number;
  limit?: number;
}): Promise<Page<Vendor>> {
  /* The query is built into a local first because the guard's URL pattern
     excludes whitespace, and `query(params || {})` carries spaces - inlined,
     the literal is cut short and the route goes unseen. */
  const q = query(params || {});
  return apiGet<Page<Vendor>>(`/v1/supplier-catalogs/vendors?${q}`);
}

export function createVendor(data: CreateVendorPayload): Promise<Vendor> {
  return apiPost<Vendor>('/v1/supplier-catalogs/vendors', data);
}

export function updateVendor(id: string, data: UpdateVendorPayload): Promise<Vendor> {
  return apiPatch<Vendor>(`/v1/supplier-catalogs/vendors/${id}`, data);
}

/**
 * Delete a vendor nothing references.
 *
 * The backend refuses with 409 and a structured reason when price lists,
 * purchase orders, invoices or KYC documents point at it, and that reason
 * names suspend and blacklist as what to do instead. `ApiError.message`
 * already carries the sentence, so callers show it rather than composing one.
 */
export function deleteVendor(id: string): Promise<void> {
  return apiDelete<void>(`/v1/supplier-catalogs/vendors/${id}`);
}

export function suspendVendor(id: string, reason?: string): Promise<Vendor> {
  return apiPatch<Vendor>(`/v1/supplier-catalogs/vendors/${id}/suspend${qs({ reason })}`, {});
}

export function blacklistVendor(id: string, reason?: string): Promise<Vendor> {
  return apiPatch<Vendor>(`/v1/supplier-catalogs/vendors/${id}/blacklist${qs({ reason })}`, {});
}

export function rateVendor(id: string, rating: number, comment?: string): Promise<Vendor> {
  return apiPost<Vendor>(`/v1/supplier-catalogs/vendors/${id}/rating`, { rating, comment });
}

/* ── Catalog ───────────────────────────────────────────────────────────── */

export function listCatalogItems(params?: {
  category_id?: string;
  search?: string;
  offset?: number;
  limit?: number;
}): Promise<Page<CatalogItem>> {
  const q = query(params || {});
  return apiGet<Page<CatalogItem>>(`/v1/supplier-catalogs/catalog-items?${q}`);
}

export function createCatalogItem(data: CreateCatalogItemPayload): Promise<CatalogItem> {
  return apiPost<CatalogItem>('/v1/supplier-catalogs/catalog-items', data);
}

export function updateCatalogItem(
  id: string,
  data: UpdateCatalogItemPayload,
): Promise<CatalogItem> {
  return apiPatch<CatalogItem>(`/v1/supplier-catalogs/catalog-items/${id}`, data);
}

/** Delete a catalog item. Refused with 409 when a line or a balance quotes it. */
export function deleteCatalogItem(id: string): Promise<void> {
  return apiDelete<void>(`/v1/supplier-catalogs/catalog-items/${id}`);
}

export function comparePrices(itemId: string): Promise<PriceComparisonRow[]> {
  return apiGet<PriceComparisonRow[]>(
    `/v1/supplier-catalogs/catalog-items/${itemId}/price-comparison`,
  );
}

/* ── Purchase Requisitions ─────────────────────────────────────────────── */

export function createPR(data: CreatePRPayload): Promise<PR> {
  return apiPost<PR>('/v1/supplier-catalogs/prs', data);
}

export function submitPR(id: string): Promise<PR> {
  return apiPost<PR>(`/v1/supplier-catalogs/prs/${id}/submit`, {});
}

export function approvePR(id: string): Promise<PR> {
  return apiPost<PR>(`/v1/supplier-catalogs/prs/${id}/approve`, {});
}

export function rejectPR(id: string, reason?: string): Promise<PR> {
  return apiPost<PR>(`/v1/supplier-catalogs/prs/${id}/reject${qs({ reason })}`, {});
}

export function convertPRToPO(id: string, vendorId: string): Promise<PO> {
  return apiPost<PO>(
    `/v1/supplier-catalogs/prs/${id}/convert-to-po${qs({ vendor_id: vendorId })}`,
    {},
  );
}

/* ── Purchase Orders ───────────────────────────────────────────────────── */

export function createPO(data: CreatePOPayload): Promise<PO> {
  return apiPost<PO>('/v1/supplier-catalogs/pos', data);
}

export function sendPO(id: string): Promise<PO> {
  return apiPost<PO>(`/v1/supplier-catalogs/pos/${id}/send`, {});
}

export function acknowledgePO(id: string): Promise<PO> {
  return apiPost<PO>(`/v1/supplier-catalogs/pos/${id}/acknowledge`, {});
}

export function closePO(id: string): Promise<PO> {
  return apiPost<PO>(`/v1/supplier-catalogs/pos/${id}/close`, {});
}

/* ── Warehouses ────────────────────────────────────────────────────────── */

export function listWarehouses(): Promise<Warehouse[]> {
  return apiGet<Warehouse[]>('/v1/supplier-catalogs/warehouses');
}

export function createWarehouse(data: CreateWarehousePayload): Promise<Warehouse> {
  return apiPost<Warehouse>('/v1/supplier-catalogs/warehouses', data);
}

export function updateWarehouse(id: string, data: UpdateWarehousePayload): Promise<Warehouse> {
  return apiPatch<Warehouse>(`/v1/supplier-catalogs/warehouses/${id}`, data);
}

/** Delete a warehouse. Refused with 409 while stock or receipts remain. */
export function deleteWarehouse(id: string): Promise<void> {
  return apiDelete<void>(`/v1/supplier-catalogs/warehouses/${id}`);
}

export function listWarehouseBalances(warehouseId: string): Promise<StockBalance[]> {
  return apiGet<StockBalance[]>(`/v1/supplier-catalogs/warehouses/${warehouseId}/balances`);
}

/* ── Invoices (read endpoints not exposed; we surface 3-way match exceptions through invoice list ── */
/* Backend currently exposes only match action; we can't list invoices generically. */

export interface MatchResult {
  invoice_id: string;
  status: string;
  /* null when no comparison was performed: no PO linked, or the invoice and
     the order are priced in different currencies. Never 0 for that case. */
  price_variance: number | string | null;
  qty_variance: number | string | null;
  /* The profile's percentage, and only that. The band actually applied is the
     wider of this and the absolute floor below, so this alone does not explain
     why an invoice passed. */
  tolerance_used_pct: number | string;
  /* The absolute floor that actually widened the band, in the order's
     currency; null when none applied. */
  tolerance_used_abs?: number | string | null;
  /* not_set | applied | dropped_unlabelled | dropped_order_unlabelled |
     dropped_currency_mismatch, or null when nothing was compared. A profile's
     floor is dropped unless it can be shown to be in the order's currency. */
  absolute_tolerance_state?: string | null;
  exception_reason: string | null;
  tolerance_profile_name?: string;
  line_results?: Array<Record<string, unknown>>;
}

export function matchInvoice(
  invoiceId: string,
  tolerancePct?: number,
  toleranceProfile?: string,
): Promise<MatchResult> {
  const params: Record<string, string | number | undefined> = {};
  if (tolerancePct !== undefined) params.tolerance_pct = tolerancePct;
  if (toleranceProfile) params.tolerance_profile = toleranceProfile;
  return apiPost<MatchResult>(
    `/v1/supplier-catalogs/invoices/${invoiceId}/match${qs(params)}`,
    {},
  );
}

/* ── Commodity codes ───────────────────────────────────────────────────── */

export interface CommodityCode {
  id: string;
  scheme: 'unspsc' | 'eclass' | 'cpv';
  code: string;
  name: string;
  description: string | null;
  parent_code: string | null;
  level: number;
  active: boolean;
}

export function listCommodityCodes(params?: {
  scheme?: string;
  search?: string;
  parent_code?: string;
  level?: number;
  limit?: number;
  offset?: number;
}): Promise<CommodityCode[]> {
  return apiGet<CommodityCode[]>(
    `/v1/supplier-catalogs/commodity-codes${qs(params || {})}`,
  );
}

export function seedCommodityCodes(): Promise<Record<string, number>> {
  return apiPost<Record<string, number>>(
    '/v1/supplier-catalogs/commodity-codes/seed',
    {},
  );
}

/* ── Tolerance profiles ────────────────────────────────────────────────── */

export interface TolerianceProfile {
  id: string;
  name: string;
  description: string | null;
  price_tolerance_pct: number | string;
  price_tolerance_abs: number | string;
  /* ISO code price_tolerance_abs is written in. null when the floor is 0, and
     on rows written before the label existed - not "any currency" either way. */
  currency?: string | null;
  qty_tolerance_pct: number | string;
  period_tolerance_days: number;
  require_gr: boolean;
  is_default: boolean;
}

export interface CreateToleranceProfilePayload {
  name: string;
  description?: string;
  price_tolerance_pct?: number;
  price_tolerance_abs?: number;
  /* Required by the API as soon as price_tolerance_abs is above 0: an amount
     of money with no currency cannot be compared against an order. */
  currency?: string;
  qty_tolerance_pct?: number;
  period_tolerance_days?: number;
  require_gr?: boolean;
  is_default?: boolean;
}

export function listToleranceProfiles(): Promise<TolerianceProfile[]> {
  return apiGet<TolerianceProfile[]>(
    '/v1/supplier-catalogs/tolerance-profiles',
  );
}

export function createToleranceProfile(
  data: CreateToleranceProfilePayload,
): Promise<TolerianceProfile> {
  return apiPost<TolerianceProfile>(
    '/v1/supplier-catalogs/tolerance-profiles',
    data,
  );
}

export function updateToleranceProfile(
  id: string,
  data: Partial<CreateToleranceProfilePayload>,
): Promise<TolerianceProfile> {
  return apiPatch<TolerianceProfile>(
    `/v1/supplier-catalogs/tolerance-profiles/${id}`,
    data,
  );
}

/**
 * Delete a tolerance profile.
 *
 * Refused with 409 when vendors are matched against it (the link is by name,
 * so nothing in the database would have stopped it) or when it is the tenant
 * default.
 */
export function deleteToleranceProfile(id: string): Promise<void> {
  return apiDelete<void>(`/v1/supplier-catalogs/tolerance-profiles/${id}`);
}

/* ── KYC documents ─────────────────────────────────────────────────────── */

export type KYCDocType =
  | 'w9'
  | 'vat_cert'
  | 'gst'
  | 'trn'
  | 'coi'
  | 'iso'
  | 'other';

export interface KYCDocument {
  id: string;
  vendor_id: string;
  doc_type: KYCDocType;
  document_number: string | null;
  issued_on: string | null;
  expires_on: string | null;
  issuing_country: string | null;
  issuing_authority: string | null;
  file_url: string | null;
  status: string;
  verified_at: string | null;
  verified_by: string | null;
  notes: string | null;
}

export interface CreateKYCDocPayload {
  doc_type: KYCDocType;
  document_number?: string;
  issued_on?: string;
  expires_on?: string;
  issuing_country?: string;
  issuing_authority?: string;
  file_url?: string;
  notes?: string;
}

export function listVendorKYC(vendorId: string): Promise<KYCDocument[]> {
  return apiGet<KYCDocument[]>(
    `/v1/supplier-catalogs/vendors/${vendorId}/kyc`,
  );
}

export function addVendorKYC(
  vendorId: string,
  data: CreateKYCDocPayload,
): Promise<KYCDocument> {
  return apiPost<KYCDocument>(
    `/v1/supplier-catalogs/vendors/${vendorId}/kyc`,
    data,
  );
}

export function checkKYCExpiry(daysAhead = 30): Promise<{ expiring: number; expired: number }> {
  return apiPost<{ expiring: number; expired: number }>(
    `/v1/supplier-catalogs/kyc/check-expiry${qs({ days_ahead: daysAhead })}`,
    {},
  );
}

/* ── Scorecards ────────────────────────────────────────────────────────── */

export interface Scorecard {
  id: string;
  vendor_id: string;
  period_start: string;
  period_end: string;
  delivery_score: number | string;
  quality_score: number | string;
  price_score: number | string;
  esg_score: number | string;
  composite_score: number | string;
  inputs_json: Record<string, unknown>;
  weights_json: Record<string, unknown>;
  computed_at: string;
}

export interface ScorecardRecomputePayload {
  period_start: string;
  period_end: string;
  weights?: {
    delivery?: number;
    quality?: number;
    price?: number;
    esg?: number;
  };
}

export function recomputeScorecard(
  vendorId: string,
  data: ScorecardRecomputePayload,
): Promise<Scorecard> {
  return apiPost<Scorecard>(
    `/v1/supplier-catalogs/vendors/${vendorId}/scorecard/recompute`,
    data,
  );
}

export function listVendorScorecards(
  vendorId: string,
  limit = 24,
): Promise<Scorecard[]> {
  return apiGet<Scorecard[]>(
    `/v1/supplier-catalogs/vendors/${vendorId}/scorecards${qs({ limit })}`,
  );
}

/* ── PEPPOL invoice ingest ─────────────────────────────────────────────── */

export interface PeppolIngestResult {
  invoice_id: string;
  invoice_number: string;
  vendor_id: string;
  matched_status: string;
  line_count: number;
  total: number | string;
  currency: string;
  exception_reason: string | null;
  peppol_message_id: string | null;
}

/* ── Price lists, import, discounts, item documents ───────────────────── */

/** Where a net price came from, most specific first. */
export type DiscountSource =
  | 'item_fixed'
  | 'item'
  | 'category'
  | 'overall'
  | 'none'
  | 'manual';

export interface PriceListEntryRow {
  entry_id: string;
  catalog_item_id: string;
  sku: string;
  name: string;
  unit_of_measure: string;
  vendor_sku: string | null;
  mpn: string | null;
  gtin: string | null;
  gross_price: number | string;
  net_price: number | string;
  discount_pct: number | string | null;
  discount_source: DiscountSource;
  discount_agreement_id: string | null;
  min_order_qty: number | string;
  lead_time_days: number;
  product_url: string | null;
  attachment_count: number;
}

export interface PriceListEntriesPage {
  price_list: PriceList;
  items: PriceListEntryRow[];
  total: number;
  offset: number;
  limit: number;
}

export type ImportField =
  | 'vendor_sku'
  | 'mpn'
  | 'gtin'
  | 'sku'
  | 'unit_price'
  | 'price_unit'
  | 'currency'
  | 'valid_from'
  | 'valid_to'
  | 'min_order_qty'
  | 'lead_time_days'
  | 'unit'
  | 'discount_pct'
  | 'name'
  | 'notes';

export type ImportAction = 'create' | 'update' | 'unchanged' | 'unmatched' | 'error';

export interface ImportRowResult {
  row: number;
  action: ImportAction;
  matched_by: string | null;
  catalog_item_id: string | null;
  sku: string | null;
  item_name: string | null;
  vendor_sku: string | null;
  old_price: number | string | null;
  new_price: number | string | null;
  currency: string | null;
  errors: string[];
}

export interface ImportPreview {
  preset: string;
  sheet: string;
  headers: string[];
  mapping: Partial<Record<ImportField, string>>;
  sample: string[][];
  total_rows: number;
  counts: Record<ImportAction, number>;
  duplicate_vendor_skus: string[];
  valid_from: string | null;
  valid_to: string | null;
  currencies: string[];
  rows: ImportRowResult[];
  rows_truncated: boolean;
}

export interface ImportCommitResult {
  price_list_id: string;
  counts: Record<ImportAction, number>;
  unmatched: ImportRowResult[];
  changed: ImportRowResult[];
}

export interface ImportOptions {
  mapping?: Partial<Record<ImportField, string>>;
  preset?: string;
  priceListId?: string;
  currency?: string;
  name?: string;
  validFrom?: string;
  validTo?: string;
}

export interface DiscountAgreement {
  id: string;
  vendor_id: string;
  name: string;
  reference: string | null;
  price_list_id: string | null;
  category_id: string | null;
  catalog_item_id: string | null;
  discount_pct: number | string | null;
  fixed_net_price: number | string | null;
  valid_from: string | null;
  valid_to: string | null;
  active: boolean;
  notes: string | null;
}

export interface CreateDiscountPayload {
  name: string;
  reference?: string;
  price_list_id?: string;
  category_id?: string;
  catalog_item_id?: string;
  discount_pct?: number | string;
  fixed_net_price?: number | string;
  valid_from?: string;
  valid_to?: string;
  active?: boolean;
}

export interface ItemAttachment {
  id: string;
  catalog_item_id: string;
  document_id: string;
  project_id: string;
  kind: 'datasheet' | 'drawing' | 'certificate' | 'other';
  title: string;
}

export function listVendorPriceLists(vendorId: string): Promise<PriceList[]> {
  return apiGet<PriceList[]>(`/v1/supplier-catalogs/vendors/${vendorId}/price-lists`);
}

export function listPriceListEntries(
  priceListId: string,
  params?: { search?: string; offset?: number; limit?: number },
): Promise<PriceListEntriesPage> {
  return apiGet<PriceListEntriesPage>(
    `/v1/supplier-catalogs/price-lists/${priceListId}/entries?${query({ ...params })}`,
  );
}

async function postImport<T>(vendorId: string, step: 'preview' | 'commit', file: File, o: ImportOptions): Promise<T> {
  const fd = new FormData();
  fd.append('file', file);
  if (o.mapping && Object.keys(o.mapping).length) fd.append('mapping', JSON.stringify(o.mapping));
  if (o.preset) fd.append('preset', o.preset);
  if (o.priceListId) fd.append('price_list_id', o.priceListId);
  if (o.currency) fd.append('currency', o.currency);
  if (step === 'commit') {
    if (o.name) fd.append('name', o.name);
    if (o.validFrom) fd.append('valid_from', o.validFrom);
    if (o.validTo) fd.append('valid_to', o.validTo);
  }
  const res = await fetchWithAuth(`/api/v1/supplier-catalogs/price-lists/${vendorId}/import/${step}`, {
    method: 'POST',
    body: fd,
  });
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) throw new Error(extractErrorMessageFromBody(body) ?? `HTTP ${res.status}`);
  return body as T;
}

export function previewPriceListImport(vendorId: string, file: File, o: ImportOptions = {}): Promise<ImportPreview> {
  return postImport<ImportPreview>(vendorId, 'preview', file, o);
}

export function commitPriceListImport(
  vendorId: string,
  file: File,
  o: ImportOptions = {},
): Promise<ImportCommitResult> {
  return postImport<ImportCommitResult>(vendorId, 'commit', file, o);
}

export function listVendorDiscounts(vendorId: string): Promise<DiscountAgreement[]> {
  return apiGet<DiscountAgreement[]>(`/v1/supplier-catalogs/vendors/${vendorId}/discounts`);
}

export function createVendorDiscount(vendorId: string, data: CreateDiscountPayload): Promise<DiscountAgreement> {
  return apiPost<DiscountAgreement>(`/v1/supplier-catalogs/vendors/${vendorId}/discounts`, data);
}

export function updateVendorDiscount(
  id: string,
  data: Partial<CreateDiscountPayload>,
): Promise<DiscountAgreement> {
  return apiPatch<DiscountAgreement>(`/v1/supplier-catalogs/discounts/${id}`, data);
}

export function deleteVendorDiscount(id: string): Promise<void> {
  return apiDelete(`/v1/supplier-catalogs/discounts/${id}`);
}

export function listItemAttachments(itemId: string): Promise<ItemAttachment[]> {
  return apiGet<ItemAttachment[]>(`/v1/supplier-catalogs/catalog-items/${itemId}/attachments`);
}

export function addItemAttachment(
  itemId: string,
  data: { document_id: string; kind: ItemAttachment['kind']; title?: string },
): Promise<ItemAttachment> {
  return apiPost<ItemAttachment>(`/v1/supplier-catalogs/catalog-items/${itemId}/attachments`, data);
}

export function deleteItemAttachment(itemId: string, attachmentId: string): Promise<void> {
  return apiDelete(`/v1/supplier-catalogs/catalog-items/${itemId}/attachments/${attachmentId}`);
}

/** Only http(s) links are ever rendered as clickable; mirrors the backend rule. */
export function isSafeProductUrl(url: string | null | undefined): url is string {
  if (!url) return false;
  try {
    const u = new URL(url);
    return (u.protocol === 'https:' || u.protocol === 'http:') && !!u.hostname;
  } catch {
    return false;
  }
}

export async function ingestPeppolInvoice(
  file: File,
  autoMatch = true,
): Promise<PeppolIngestResult> {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch(
    `/api/v1/supplier-catalogs/invoices/peppol${qs({ auto_match: autoMatch ? 'true' : 'false' })}`,
    {
      method: 'POST',
      body: fd,
      credentials: 'include',
    },
  );
  if (!res.ok) {
    throw new Error(`PEPPOL ingest failed: ${res.status} ${await res.text()}`);
  }
  return (await res.json()) as PeppolIngestResult;
}
