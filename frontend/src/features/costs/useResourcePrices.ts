// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Data hooks for the per-region resource price sheet.
//
// The sheet is what makes a coefficient cost base (Vietnam Dinh Muc =
// VN_NATIONAL, Indonesia AHSP = ID_NATIONAL) estimable. Those bases list every
// work item's labour/material/machine resources as quantities but carry no
// prices, so each item's rate stays 0 until a local unit price is supplied
// here. Re-pricing then recomputes every rate as
// sum(component.quantity x unit_price).
//
// Money note: `unit_price` is a DecimalMoney on the wire, i.e. a STRING. It is
// never Number()-parsed for storage - it is displayed as-is and sent back as a
// string, so an arbitrary-precision local price survives the round trip.

import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { apiGet, apiPost } from '@/shared/lib/api';

/* ── Types (mirror backend/app/modules/costs/schemas.py) ─────────────────── */

export type ResourceType =
  | 'labor'
  | 'material'
  | 'equipment'
  | 'operator'
  | 'electricity'
  | 'other';

export type ResourcePriceSource = 'cwicr_import' | 'user';

/** One resource's unit price for a region - a single row in the price sheet. */
export interface ResourcePriceRow {
  resource_key: string;
  resource_code: string;
  resource_name: string;
  /** One of ResourceType; kept widened to string for forward compatibility. */
  resource_type: ResourceType | string;
  unit: string;
  /** Local unit price as a decimal STRING. "0" means unpriced. */
  unit_price: string;
  currency: string;
  /** cwicr_import (seeded) | user (edited). */
  source: ResourcePriceSource | string;
  is_active: boolean;
}

/** Coverage of a region's price sheet. */
export interface ResourcePriceStats {
  region: string;
  resources: number;
  priced: number;
  unpriced: number;
  /** priced / resources, in the range 0..1. */
  coverage: number;
}

export interface ResourcePriceListResponse {
  region: string;
  total: number;
  limit: number;
  offset: number;
  stats: ResourcePriceStats;
  rows: ResourcePriceRow[];
}

/** Result of (re)building a region's sheet from its work items. */
export interface ResourceSeedResponse {
  region: string;
  resources: number;
  created: number;
  updated: number;
  priced: number;
  unpriced: number;
  preserved_user_edits: number;
  coverage: number;
}

/** Result of re-pricing a region's work items from its price sheet. */
export interface RepriceResponse {
  region: string;
  items_total: number;
  items_repriced: number;
  items_changed: number;
  items_fully_priced: number;
  items_partially_priced: number;
  items_unpriced: number;
  coverage: number;
  missing_resource_count: number;
  missing_resources_sample: string[];
  dry_run: boolean;
}

/** One price edit sent to the bulk endpoint. `unit_price` stays a STRING. */
export interface ResourcePriceBulkItem {
  resource_key: string;
  unit_price: string;
  currency?: string;
  unit?: string;
  resource_name?: string;
  resource_type?: string;
}

export interface ResourcePriceListParams {
  search?: string;
  resourceType?: string;
  onlyUnpriced?: boolean;
  limit?: number;
  offset?: number;
}

/* ── Raw API calls ───────────────────────────────────────────────────────── */

function regionPath(region: string): string {
  return encodeURIComponent(region);
}

/** GET /v1/costs/resource-prices/{region}/ - paginated rows plus coverage. */
export async function fetchResourcePrices(
  region: string,
  params: ResourcePriceListParams = {},
): Promise<ResourcePriceListResponse> {
  const qs = new URLSearchParams();
  if (params.search) qs.set('search', params.search);
  if (params.resourceType) qs.set('resource_type', params.resourceType);
  if (params.onlyUnpriced) qs.set('only_unpriced', 'true');
  qs.set('limit', String(params.limit ?? 100));
  qs.set('offset', String(params.offset ?? 0));
  return apiGet<ResourcePriceListResponse>(
    `/v1/costs/resource-prices/${regionPath(region)}/?${qs.toString()}`,
  );
}

/** GET /v1/costs/resource-prices/{region}/stats/ - coverage only. */
export async function fetchResourcePriceStats(
  region: string,
): Promise<ResourcePriceStats> {
  return apiGet<ResourcePriceStats>(
    `/v1/costs/resource-prices/${regionPath(region)}/stats/`,
  );
}

/** POST .../seed/ - (re)build the sheet from the base. Preserves user edits. */
export async function seedResourcePrices(
  region: string,
): Promise<ResourceSeedResponse> {
  return apiPost<ResourceSeedResponse>(
    `/v1/costs/resource-prices/${regionPath(region)}/seed/`,
    undefined,
    { longRunning: true },
  );
}

/** POST .../bulk/ - apply many price edits in one transaction. */
export async function bulkSetResourcePrices(
  region: string,
  items: ResourcePriceBulkItem[],
): Promise<{ region: string; written: number }> {
  return apiPost<{ region: string; written: number }, { items: ResourcePriceBulkItem[] }>(
    `/v1/costs/resource-prices/${regionPath(region)}/bulk/`,
    { items },
  );
}

/** POST .../reprice/ - recompute every work-item rate from the sheet. */
export async function repriceRegion(
  region: string,
  dryRun: boolean,
): Promise<RepriceResponse> {
  return apiPost<RepriceResponse>(
    `/v1/costs/resource-prices/${regionPath(region)}/reprice/?dry_run=${dryRun ? 'true' : 'false'}`,
    undefined,
    { longRunning: true },
  );
}

/* ── Query keys ──────────────────────────────────────────────────────────── */

/** Prefix that covers every resource-price query for a region, so a single
 *  invalidation refreshes both the paginated list and the coverage stats. */
function regionKey(region: string): [string, string, string] {
  return ['costs', 'resource-prices', region];
}

/* ── Hooks ───────────────────────────────────────────────────────────────── */

/** List the price sheet for a region (paginated, filterable). */
export function useResourcePricesQuery(
  region: string,
  params: ResourcePriceListParams,
  enabled = true,
): UseQueryResult<ResourcePriceListResponse> {
  return useQuery({
    queryKey: [...regionKey(region), 'list', params],
    queryFn: () => fetchResourcePrices(region, params),
    enabled: enabled && Boolean(region),
    staleTime: 15_000,
    // Keep the current page visible while the next page / filtered result
    // loads, so the table does not flash empty on every keystroke.
    placeholderData: (prev) => prev,
  });
}

/** Region-wide coverage stats (independent of the current page / filters). */
export function useResourcePriceStatsQuery(
  region: string,
  enabled = true,
): UseQueryResult<ResourcePriceStats> {
  return useQuery({
    queryKey: [...regionKey(region), 'stats'],
    queryFn: () => fetchResourcePriceStats(region),
    enabled: enabled && Boolean(region),
    staleTime: 15_000,
  });
}

/** Build (or rebuild) the price sheet for a region from its work items. */
export function useSeedResourcePrices(
  region: string,
): UseMutationResult<ResourceSeedResponse, Error, void> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => seedResourcePrices(region),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: regionKey(region) });
    },
  });
}

/** Save many resource-price edits at once. */
export function useBulkSetResourcePrices(
  region: string,
): UseMutationResult<{ region: string; written: number }, Error, ResourcePriceBulkItem[]> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (items: ResourcePriceBulkItem[]) => bulkSetResourcePrices(region, items),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: regionKey(region) });
    },
  });
}

/**
 * Re-price a region. Pass `true` for a dry-run preview (nothing is written) or
 * `false` to commit. A committed reprice rewrites work-item rates across the
 * whole base, so it invalidates the broader cost cache; a dry run only refreshes
 * this region's coverage.
 */
export function useRepriceRegion(
  region: string,
): UseMutationResult<RepriceResponse, Error, boolean> {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (dryRun: boolean) => repriceRegion(region, dryRun),
    onSuccess: (result) => {
      if (result.dry_run) {
        queryClient.invalidateQueries({ queryKey: [...regionKey(region), 'stats'] });
      } else {
        queryClient.invalidateQueries({ queryKey: ['costs'] });
      }
    },
  });
}
