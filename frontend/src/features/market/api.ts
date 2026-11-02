// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Market scope: the client side of `/api/v1/market/`.
 *
 * The server resolves the tenant's market profile against the `markets` tags
 * of modules, packs and rule sets. This file types the answer and offers the
 * hook every menu, picker and rule-set list reads.
 */
import { useQuery, type QueryClient } from '@tanstack/react-query';
import { apiGet, apiPost, apiPut } from '@/shared/lib/api';
import { setActiveUnitsSystem, type UnitsSystem } from '@/features/boq/boqHelpers';

export interface MarketEntry {
  country: string;
  subdivision: string;
}

export interface MarketStandards {
  classification: string;
  measurement: string;
  contract_family: string;
  tax_profile: string;
  units: string;
}

export interface MarketProfile {
  primary: MarketEntry | null;
  extra_markets: MarketEntry[];
  company_type: string | null;
  standards: MarketStandards;
  keep_modules: string[];
}

export interface MarketScope {
  profile: MarketProfile;
  /** True when the tenant never saved a profile and it was derived from its data. */
  derived: boolean;
  markets: string[];
  expanded_markets: string[];
  all_markets: boolean;
  /** Module keys (no `oe_` prefix) that belong to other markets. */
  hidden_modules: string[];
  module_markets: Record<string, string[]>;
  packs: string[];
  units_system: UnitsSystem;
  standards: Partial<MarketStandards>;
  options: { standards: string[]; contract_forms: string[] };
  rule_sets: string[];
  can_edit: boolean;
}

export const MARKET_QUERY_KEY = ['market-scope'] as const;

export function fetchMarketScope(projectId?: string | null): Promise<MarketScope> {
  const qs = projectId ? `?project_id=${encodeURIComponent(projectId)}` : '';
  return apiGet<MarketScope>(`/v1/market/${qs}`);
}

export function saveMarketProfile(profile: MarketProfile): Promise<MarketScope> {
  return apiPut<MarketScope>('/v1/market/', profile);
}

/** The tenant's market scope (or one project's, when `projectId` is given). */
export function useMarketScope(enabled = true, projectId?: string | null) {
  return useQuery({
    queryKey: [...MARKET_QUERY_KEY, projectId ?? null],
    queryFn: () => fetchMarketScope(projectId),
    enabled,
    staleTime: 60 * 1000,
  });
}

/**
 * Units system for pickers: the project's country narrows the tenant's when a
 * project is given; until the scope loads every unit shows.
 */
export function useUnitsSystem(projectId?: string | null): UnitsSystem {
  const { data } = useMarketScope(true, projectId);
  return data?.units_system ?? 'both';
}

/**
 * Keep the tenant-wide default units system (used by pickers outside a project)
 * in step with the tenant scope query. Called once at app start.
 */
export function hydrateUnitsSystem(client: QueryClient): () => void {
  const key = JSON.stringify([...MARKET_QUERY_KEY, null]);
  const sync = () => {
    const scope = client.getQueryData<MarketScope>([...MARKET_QUERY_KEY, null]);
    if (scope?.units_system) setActiveUnitsSystem(scope.units_system);
  };
  sync();
  return client.getQueryCache().subscribe((event) => {
    if (JSON.stringify(event.query.queryKey) === key) sync();
  });
}

export interface MarketPreview extends Omit<MarketScope, 'derived' | 'can_edit'> {
  suggested_packages: string[];
}

/** What a draft profile would show, without saving it. */
export function previewMarketProfile(profile: MarketProfile): Promise<MarketPreview> {
  return apiPost<MarketPreview>('/v1/market/preview/', profile);
}
