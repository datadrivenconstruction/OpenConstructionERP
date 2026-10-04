// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Client types and data hook for the CWICR base catalog. The backend endpoint
// GET /api/v1/costs/base-catalog enumerates the nine cost-base families and
// every loadable market variant with real work-item counts, so the import page,
// database setup and onboarding all render one consistent picker from a single
// source of truth (see backend app/modules/costs/base_registry.py).

import { useQuery } from '@tanstack/react-query';
import { apiGet, apiPost } from '@/shared/lib/api';
import { ROLE_RANK, normalizeRole } from '@/shared/lib/roles';

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
  /** On a market card: whether the server's stored state says the base is
   *  priced into this market now. Always false on a home or global card. */
  active: boolean;
  /** Human market / country label (English). */
  market: string;
  /** Representative city, or "National" for country-wide bases. */
  city: string;
  /** Display language label. */
  language: string;
  /** ISO 639-1 language code. */
  lang_code: string;
  /** The language the loaded work-item text is really in. Differs from
   *  `lang_code` only where no published file holds the base in the card's
   *  language (Turkiye has no English text), so the card must say so. */
  text_lang_code?: string;
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

/**
 * Which market a loaded national base is in, as the server stores it.
 *
 * `home`: the base's own prices. `market`: priced into `active_market`.
 * `switching`: a market switch or a return home started and has not finished
 * (still running, or cut off). `unknown`: the base was loaded before the server
 * kept this, so nothing is known about it.
 */
export type BaseMarketState = 'home' | 'market' | 'switching' | 'unknown';

export interface BaseStateInfo {
  market_state: BaseMarketState;
  active_market: string | null;
  switching_to: string | null;
  /** Language the work items are in, or null when not known. */
  text_language: string | null;
  updated_at: string | null;
}

export interface BaseCatalog {
  repo: string;
  families: BaseFamily[];
  total_bases: number;
  total_families: number;
  loaded_regions: string[];
  /** Stored state of every loaded national base, keyed by base_region. Absent
   *  from an older server, which kept the active market in the browser only. */
  base_states?: Record<string, BaseStateInfo>;
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

// Which market each national base is currently repriced into, as THIS browser
// last saw it. Keyed by base_region -> market_catalog token (e.g.
// { ZH_CHINA: 'GB_LONDON_en' }). The server's stored state is the answer
// (`BaseCatalog.base_states`, read through `effectiveActiveMarkets`); this is
// only a cache for the moment before the catalog has loaded and for a base the
// server knows nothing about.
const ACTIVE_MARKETS_KEY = 'oe_active_markets';

export function getActiveMarkets(): Record<string, string> {
  try {
    const raw = localStorage.getItem(ACTIVE_MARKETS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, string>) : {};
  } catch {
    return {};
  }
}

export function setActiveMarketFor(baseRegion: string, token: string): void {
  try {
    const current = getActiveMarkets();
    current[baseRegion] = token;
    localStorage.setItem(ACTIVE_MARKETS_KEY, JSON.stringify(current));
  } catch {
    // Storage unavailable -- ignore.
  }
}

/** Forget this browser's cached market for a base (it is back on its home market). */
export function clearActiveMarketFor(baseRegion: string): void {
  try {
    const rest = Object.fromEntries(Object.entries(getActiveMarkets()).filter(([region]) => region !== baseRegion));
    localStorage.setItem(ACTIVE_MARKETS_KEY, JSON.stringify(rest));
  } catch {
    // Storage unavailable -- ignore.
  }
}

/**
 * The market each base is in, for the cards to mark: the server's stored state
 * wherever it knows one, this browser's cache only where it does not.
 *
 * A base the server reports on the home market, or in the middle of a switch,
 * maps to '' so no market card reads as active, whatever the cache still holds.
 * Without this, two browsers showed two different active markets over the same
 * shared rows, and a restart of the server was invisible to both.
 */
export function effectiveActiveMarkets(
  catalog: BaseCatalog | undefined,
  cached: Record<string, string> | undefined,
): Record<string, string> {
  const out: Record<string, string> = { ...(cached ?? {}) };
  for (const [baseRegion, state] of Object.entries(catalog?.base_states ?? {})) {
    if (state.market_state === 'unknown') continue;
    out[baseRegion] = state.market_state === 'market' ? (state.active_market ?? '') : '';
  }
  return out;
}

/**
 * Whether a base can be offered "Return to home market": the server says it is
 * priced into a market or a switch did not finish, or, where the server knows
 * nothing, this browser remembers pricing it into one.
 */
export function canReturnHome(
  baseRegion: string,
  catalog: BaseCatalog | undefined,
  cached: Record<string, string> | undefined,
): boolean {
  const state = catalog?.base_states?.[baseRegion];
  if (state && state.market_state !== 'unknown') {
    return state.market_state === 'market' || state.market_state === 'switching';
  }
  return !!cached?.[baseRegion];
}

/** Server answer of POST /v1/costs/base-home/{base_region}. */
export interface RestoreHomeResult extends Record<string, unknown> {
  items_restored?: number;
  /** Items the home file does not hold, repriced from the rebuilt home sheet. */
  items_repriced_home?: number;
  /** Items whose recipe the home sheet cannot price: they keep the market's rates and currency. */
  items_left_in_market?: number;
  currency?: string;
  /** Edited resource prices the return home replaced. */
  user_prices_discarded?: number;
  previous_market?: string | null;
  text_language?: string | null;
  text_language_requested?: string;
  text_language_error?: string;
  catalog?: { error?: string } & Record<string, unknown>;
  state?: BaseStateInfo | null;
}

/**
 * Bring a national base back from a market to its own prices, currency and
 * language. The server keeps every item id, rebuilds the resource price sheet
 * and the Resource Catalog, and records the home market for every browser.
 */
export async function restoreBaseHome(baseRegion: string): Promise<RestoreHomeResult> {
  const data = await apiPost<RestoreHomeResult>(`/v1/costs/base-home/${baseRegion}`, undefined, {
    longRunning: true,
  });
  clearActiveMarketFor(baseRegion);
  return data;
}

/** Server answer of POST /v1/costs/base-market/{base_region}/{market_token}. */
export interface BaseMarketResult extends Record<string, unknown> {
  items_repriced?: number;
  items_total?: number;
  /** Language the text is in after the call; null when it is unknown. */
  text_language?: string | null;
  /** Language the card asked for. */
  text_language_requested?: string;
  /** The Resource Catalog mirror of the market; `error` when it failed. */
  catalog?: { error?: string } & Record<string, unknown>;
}

/**
 * Load a national base and price it into a market card's market and language.
 *
 * Every surface that shows a national market card goes through here. Loading
 * the card's `region` instead installs the plain home base in the home
 * language, the silent wrong-language load this helper exists to stop. The
 * server fails the call when the card's language cannot land.
 */
export async function loadBaseMarket(variant: BaseVariant): Promise<BaseMarketResult> {
  const data = await apiPost<BaseMarketResult>(
    `/v1/costs/base-market/${variant.base_region}/${variant.market_catalog}`,
    undefined,
    { longRunning: true },
  );
  setActiveMarketFor(variant.base_region, variant.market_catalog);
  return data;
}

/**
 * Whether a role may price a base into a market. The endpoint needs
 * costs.update, which is editor and up; a viewer is not offered market cards
 * rather than offered a button that answers 403.
 */
export function canPriceMarkets(role: string | null | undefined): boolean {
  const rank = (ROLE_RANK as Record<string, number>)[normalizeRole(role)];
  return rank !== undefined && rank >= ROLE_RANK.editor;
}

/** A language code's name in the reader's language, falling back to the code. */
export function languageName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames([locale], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/**
 * The language a loaded base's text is really in, or null when it is the one
 * that was asked for. A market load answers this for Turkiye's English cards,
 * which have no English file; a fresh base load answers it when the switch to
 * the base's own language did not land.
 */
export function textLanguageFallback(data: BaseMarketResult): string | null {
  const shown = data.text_language;
  const asked = data.text_language_requested;
  return shown && asked && shown !== asked ? shown : null;
}
