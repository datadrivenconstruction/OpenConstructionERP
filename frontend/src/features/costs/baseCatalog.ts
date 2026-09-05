// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Client types and data hook for the CWICR base catalog. The backend endpoint
// GET /api/v1/costs/base-catalog enumerates the nine cost-base families and
// every loadable market variant with real work-item counts, so the import page,
// database setup and onboarding all render one consistent picker from a single
// source of truth (see backend app/modules/costs/base_registry.py).

import { useQuery } from '@tanstack/react-query';
import { apiGet } from '@/shared/lib/api';

/** One loadable cost base: a full work-item catalogue for a single market. */
export interface BaseVariant {
  /** Platform region id, e.g. "USA_USD" - the load-cwicr path segment. */
  region: string;
  /** Unique UI id. Global + national HOME variants use `region`; a national
   *  MARKET variant uses `${base_region}:${market_catalog}` so many cards can
   *  share one base_region yet stay individually addressable. */
  variant_id: string;
  /** The oe_costs_item.region a load + reprice targets. Global + home variants
   *  use `region`; a market variant uses its base's home region. All of a
   *  base's cards share it. */
  base_region: string;
  /** The markets/ catalog file token this card reprices into (e.g.
   *  "GB_LONDON_en"); empty for global + home variants. */
  market_catalog: string;
  /** Whether this market is the one the base is currently repriced into
   *  (registry default false; live value tracked client-side). */
  active: boolean;
  /** Human market / country label (English). */
  market: string;
  /** Representative city, or "National" for country-wide bases. */
  city: string;
  /** Display language label. */
  language: string;
  /** ISO 639-1 language code. */
  lang_code: string;
  /** ISO 4217 currency code the rates are expressed in. */
  currency: string;
  /** ISO 3166-1 alpha-2 country code (lowercase) for the flag icon. */
  flag: string;
  /** Work-item count shown before load. */
  positions: number;
  /** Whether the base ships locally (loads without any network). */
  bundled: boolean;
  /** Codeless coefficient base (estimable via a resource price sheet). */
  coefficient: boolean;
  /** Whether this region is currently loaded into the cost store. */
  loaded: boolean;
  /** Real loaded work-item count when loaded (0 otherwise). */
  loaded_positions: number;
}

/** A cost-base family: a norm system and the markets available under it. */
export interface BaseFamily {
  key: string;
  name: string;
  /** Official norm / classification the base derives from. */
  norm_system: string;
  origin: string;
  origin_flag: string;
  description: string;
  market_count: number;
  /** Additional markets the base can be repriced into (0 if not applicable). */
  repriceable_markets: number;
  /** Representative catalogue size (markets in a family share one count). */
  positions: number;
  loaded_count: number;
  variants: BaseVariant[];
}

export interface BaseCatalog {
  repo: string;
  families: BaseFamily[];
  total_bases: number;
  total_families: number;
  loaded_regions: string[];
}

/** Fetch the full cost-base catalog (families, variants, live loaded counts). */
export function useBaseCatalog() {
  return useQuery({
    queryKey: ['costs', 'base-catalog'],
    // Both slash forms work. The slash-less one used to be shadowed by the
    // costs router's GET /{item_id} route, which read "base-catalog" as an id
    // and answered 400; that route is now constrained to `{item_id:uuid}`.
    // Kept on the slash form because the app runs with redirect_slashes=False
    // and this is the form that has always been served.
    queryFn: () => apiGet<BaseCatalog>('/v1/costs/base-catalog/'),
    staleTime: 5 * 60 * 1000,
    retry: false,
  });
}

/** Flatten every variant across all families (for search / lookups). */
export function flattenVariants(catalog: BaseCatalog | undefined): BaseVariant[] {
  return catalog ? catalog.families.flatMap((f) => f.variants) : [];
}

/** True when a variant matches a free-text query (market, city, currency, etc.). */
export function variantMatches(variant: BaseVariant, family: BaseFamily, query: string): boolean {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  return (
    variant.market.toLowerCase().includes(q) ||
    variant.city.toLowerCase().includes(q) ||
    variant.currency.toLowerCase().includes(q) ||
    variant.language.toLowerCase().includes(q) ||
    variant.region.toLowerCase().includes(q) ||
    family.name.toLowerCase().includes(q) ||
    family.norm_system.toLowerCase().includes(q)
  );
}
