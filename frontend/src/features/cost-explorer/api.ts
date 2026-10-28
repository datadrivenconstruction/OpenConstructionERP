// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Typed client for the Cost Explorer module (/api/v1/cost-explorer).
//
// Money and quantities arrive as strings (the backend stores them as
// Decimal-compatible strings and never routes a precision-critical rate
// through a float); the UI formats them for display but never does arithmetic
// on them beyond what the backend already computed.

import { apiGet, apiPost } from '@/shared/lib/api';

// ── By resources ────────────────────────────────────────────────────────────

export interface ResourceQuery {
  code: string;
  weight: number;
}

export interface MatchedResource {
  code: string;
  name: string;
  cost: string;
  quantity: string;
}

export interface ByResourcesMatch {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
  region: string | null;
  source: string;
  classification: Record<string, unknown>;
  score: number;
  coverage: number;
  cost_weight: number;
  matched: MatchedResource[];
  missing_codes: string[];
}

export interface ByResourcesResponse {
  requested_count: number;
  result_count: number;
  results: ByResourcesMatch[];
}

export interface ByResourcesRequest {
  region?: string | null;
  resources: ResourceQuery[];
  sources?: string[] | null;
  limit?: number;
}

// ── Find work ───────────────────────────────────────────────────────────────

export interface FindWorkItem {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
  region: string | null;
  source: string;
  classification: Record<string, unknown>;
  score: number;
}

export interface FindWorkResponse {
  query: string;
  result_count: number;
  mode: string;
  results: FindWorkItem[];
  /**
   * Plain-language guidance shown when a search returns nothing or only weak
   * matches, or a spelling suggestion. Null when the top results are strong.
   * For `hint_code === 'cost_explorer.hint.did_you_mean'` this carries the
   * suggested corrected query verbatim (e.g. 'concrete') so the chip can re-run
   * it; for every other code it is a ready English message.
   */
  hint?: string | null;
  /** Stable key a localized UI maps to a translated string; null with `hint`. */
  hint_code?: string | null;
}

// ── Compare across bases ─────────────────────────────────────────────────────

export interface CompareRow {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  rate: string;
  currency: string;
  region: string | null;
  source: string;
}

export interface CompareResponse {
  code: string;
  unit: string;
  description: string;
  region_count: number;
  currencies: string[];
  rows: CompareRow[];
}

// ── Substitute ───────────────────────────────────────────────────────────────

export interface SubstituteResponse {
  cost_item_id: string;
  code: string;
  description: string;
  unit: string;
  currency: string;
  region: string | null;
  resource_code: string;
  resource_name: string;
  quantity: string;
  old_unit_rate: string;
  new_unit_rate: string;
  substitute_resource_code: string | null;
  substitute_resource_name: string | null;
  original_unit: string | null;
  substitute_unit: string | null;
  unit_mismatch: boolean;
  old_rate: string;
  new_rate: string;
  delta: string;
  delta_pct: number;
  clamped: boolean;
}

export interface SubstituteRequest {
  cost_item_id: string;
  resource_code: string;
  new_unit_rate?: string | null;
  substitute_resource_code?: string | null;
}

// ── Price intelligence ───────────────────────────────────────────────────────

export interface PriceStats {
  count: number;
  min: string;
  p25: string;
  median: string;
  p75: string;
  max: string;
  mean: string;
  /** Currency of the single-region spread (never a cross-currency blend). */
  currency: string;
}

export interface PriceRegionRow {
  region: string | null;
  unit: string;
  base_price: string;
  min_price: string;
  max_price: string;
  currency: string;
}

export interface PriceUsageWork {
  cost_item_id: string;
  code: string;
  description: string;
  region: string | null;
  quantity: string;
  unit_rate: string;
}

export interface PriceIntelResponse {
  resource_code: string;
  resource_name: string;
  resource_type: string;
  unit: string;
  stats: PriceStats;
  /** Region the single-currency spread was computed over (dominant one when unscoped). */
  stats_region: string | null;
  usage_count: number;
  by_region: PriceRegionRow[];
  top_works: PriceUsageWork[];
}

// ── Index status / reindex (admin) ───────────────────────────────────────────

export interface IndexStatus {
  indexed_edges: number;
  cost_items: number;
  /** Loaded regions that carry works but are missing from the index (rebuild prompt). */
  unindexed_regions?: string[];
}

export interface ReindexResponse {
  regions: string[];
  items_scanned: number;
  edges_written: number;
  resources_seen: number;
}

// ── Catalog resource (autocomplete source, from the catalog module) ──────────

export interface CatalogResource {
  id?: string;
  resource_code: string;
  name: string;
  unit: string;
  resource_type: string;
  region: string | null;
  base_price: string | number;
  category?: string | null;
}

interface CatalogSearchResponse {
  items: CatalogResource[];
  total: number;
}

// ── Calls ────────────────────────────────────────────────────────────────────

const BASE = '/v1/cost-explorer';

export function findByResources(
  body: ByResourcesRequest,
  init?: { signal?: AbortSignal },
): Promise<ByResourcesResponse> {
  return apiPost<ByResourcesResponse, ByResourcesRequest>(`${BASE}/by-resources`, body, init);
}

export function findWork(
  body: { q: string; region?: string | null; sources?: string[] | null; limit?: number },
  init?: { signal?: AbortSignal },
): Promise<FindWorkResponse> {
  return apiPost<FindWorkResponse>(`${BASE}/find-work`, body, init);
}

export function compareBases(
  body: { code?: string | null; cost_item_id?: string | null; limit?: number },
  init?: { signal?: AbortSignal },
): Promise<CompareResponse> {
  return apiPost<CompareResponse>(`${BASE}/compare`, body, init);
}

export function substitute(
  body: SubstituteRequest,
  init?: { signal?: AbortSignal },
): Promise<SubstituteResponse> {
  return apiPost<SubstituteResponse, SubstituteRequest>(`${BASE}/substitute`, body, init);
}

export function priceIntelligence(
  resourceCode: string,
  region?: string | null,
): Promise<PriceIntelResponse> {
  const q = region ? `?region=${encodeURIComponent(region)}` : '';
  return apiGet<PriceIntelResponse>(`${BASE}/price-intelligence/${encodeURIComponent(resourceCode)}${q}`);
}

export function getIndexStatus(): Promise<IndexStatus> {
  return apiGet<IndexStatus>(`${BASE}/status`);
}

export function reindex(): Promise<ReindexResponse> {
  return apiPost<ReindexResponse>(`${BASE}/reindex`, {}, { longRunning: true });
}

/** The regions (price bases) currently loaded, e.g. ['DE_BERLIN', 'TR_ISTANBUL']. */
export function listRegions(): Promise<string[]> {
  return apiGet<string[]>('/v1/costs/regions/');
}

/** Autocomplete resources from the catalog price book. */
export async function searchCatalogResources(
  q: string,
  opts?: { region?: string | null; resourceType?: string | null; limit?: number; signal?: AbortSignal },
): Promise<CatalogResource[]> {
  const params = new URLSearchParams();
  if (q) params.set('q', q);
  if (opts?.region) params.set('region', opts.region);
  if (opts?.resourceType) params.set('resource_type', opts.resourceType);
  params.set('limit', String(opts?.limit ?? 12));
  const res = await apiGet<CatalogSearchResponse>(`/v1/catalog/?${params.toString()}`, {
    signal: opts?.signal,
  });
  return res.items ?? [];
}
