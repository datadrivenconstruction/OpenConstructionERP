// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Turns the three things the backend already publishes about cost bases into
// one row per base that a person can actually choose from.
//
// The three sources, and why each is the one used:
//   * GET /v1/costs/regions/      - the authoritative list of base ids. This is
//     the ONLY list whose values the search endpoints accept as `region`, and
//     it is the only one that filters out the `__xlate_` staging regions an
//     interrupted language swap leaves behind. Never substitute the stats list
//     for it: stats does not filter those, so a staging region would appear in
//     the picker as if it were a base.
//   * GET /v1/costs/base-catalog/ - the registry (backend base_registry.py) that
//     knows a base's market, city, currency, flag and norm system. Decoration
//     only; it enumerates what is LOADABLE, not what is loaded.
//   * GET /v1/costs/regions/stats/ - the live per-region row count, which is the
//     one honest measure of a base's size on THIS install.
//
// A region the registry has never heard of (a customer's own import, or a
// legacy tag such as DE_HAMBURG that predates the registry) still gets a row
// with its real size and a readable name derived from its id. It is marked
// `known: false` so the UI can say "imported base" instead of inventing a
// currency for it.

import type { BaseCatalog, BaseFamily, BaseVariant } from '@/features/costs/baseCatalog';

/** One loaded cost base, as the picker needs to show it. */
export interface LoadedBase {
  /** The base id, and the value the search endpoints accept as `region`. */
  region: string;
  /** Market label, e.g. "Germany / DACH". Falls back to a readable form of the id. */
  market: string;
  /** Representative city, or '' when the registry does not name one. */
  city: string;
  /** ISO 4217 of the rates; '' when unknown, never guessed. */
  currency: string;
  /** ISO 3166-1 alpha-2 for the flag; '' when unknown. */
  flag: string;
  /** Rows loaded on this install; null when the count is not known yet. */
  positions: number | null;
  /** Norm system the base derives from, e.g. "GESN / FER / TER"; '' when unknown. */
  normSystem: string;
  /** False for a base the registry does not carry (custom or legacy import). */
  known: boolean;
}

/**
 * Render a raw base id as something readable, without a country/city table.
 *
 * Ids are conventionally ``CC_CITY`` (``DE_BERLIN`` -> ``DE / Berlin``), so a
 * base the registry has never seen still reads as a place rather than as a
 * shouted constant. An id that does not split is echoed back untouched.
 */
export function readableRegion(code: string): string {
  if (!code) return code;
  const parts = code.split('_').filter(Boolean);
  if (parts.length < 2) return code;
  const country = (parts[0] ?? '').toUpperCase();
  const place = parts
    .slice(1)
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1).toLowerCase())
    .join(' ');
  return `${country} / ${place}`;
}

/**
 * Index the registry by the base id a load actually lands under.
 *
 * A national base can carry several market cards that share one `base_region`
 * (China repriced into London, say). Only the card whose own `region` IS its
 * `base_region` names a base id that can appear in `oe_costs_item.region`, so
 * that card wins. The looser match is kept as a fallback so a registry shape
 * change degrades into a slightly less precise label rather than into nothing.
 */
function indexByRegion(catalog: BaseCatalog | undefined): Map<string, { v: BaseVariant; f: BaseFamily }> {
  const exact = new Map<string, { v: BaseVariant; f: BaseFamily }>();
  const loose = new Map<string, { v: BaseVariant; f: BaseFamily }>();
  for (const f of catalog?.families ?? []) {
    for (const v of f.variants) {
      if (v.region === v.base_region) {
        if (!exact.has(v.region)) exact.set(v.region, { v, f });
      } else if (!loose.has(v.region)) {
        loose.set(v.region, { v, f });
      }
    }
  }
  for (const [region, hit] of loose) {
    if (!exact.has(region)) exact.set(region, hit);
  }
  return exact;
}

/**
 * Describe every loaded base, in the order the base id list gives them.
 *
 * Args:
 *   regions: The loaded base ids, from `GET /v1/costs/regions/`.
 *   catalog: The base registry, for decoration. Undefined while it loads, and
 *     that is fine - every row still renders, just without market metadata.
 *   counts: Region id to loaded row count, from `GET /v1/costs/regions/stats/`.
 *     A region absent from it gets `positions: null`, which the UI shows as
 *     nothing rather than as zero.
 */
export function describeBases(
  regions: string[] | undefined,
  catalog: BaseCatalog | undefined,
  counts: Record<string, number> | undefined,
): LoadedBase[] {
  const byRegion = indexByRegion(catalog);
  return (regions ?? []).map((region) => {
    const hit = byRegion.get(region);
    const count = counts?.[region];
    return {
      region,
      market: hit?.v.market || readableRegion(region),
      city: hit?.v.city ?? '',
      currency: hit?.v.currency ?? '',
      flag: hit?.v.flag || region,
      positions: typeof count === 'number' ? count : (hit?.v.loaded_positions ?? null),
      normSystem: hit?.f.norm_system ?? '',
      known: !!hit,
    };
  });
}

/** The distinct currencies across a set of bases, in first-seen order. */
export function baseCurrencies(bases: LoadedBase[]): string[] {
  const out: string[] = [];
  for (const b of bases) {
    if (b.currency && !out.includes(b.currency)) out.push(b.currency);
  }
  return out;
}
