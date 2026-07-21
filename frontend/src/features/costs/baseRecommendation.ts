// DDC-CWICR-OE: DataDrivenConstruction / OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// baseRecommendation - pure, dependency-light logic for "which cost base should
// we point the user at?" It is shared by onboarding, the database setup page and
// the cost surfaces so the same honest recommendation is made everywhere.
//
// Two facts about the data drive the rules:
//
//   * The CWICR "global" family (USA_USD, DE_BERLIN, ...) is ONE master
//     catalogue of ~55,000 works, re-priced and translated per region. Every
//     regional copy carries the SAME works and resource structure; only the
//     currency, language and unit prices differ. So one global copy is never
//     honestly "more complete" than another - they share the master.
//   * The "national" bases (BR_NATIONAL/SINAPI, ES_ANDALUCIA/BCCA, IT_TOSCANA,
//     GR_NATIONAL, VN_NATIONAL, ID_NATIONAL) are independent official books with
//     their own parquet. Some of them (BR, VN, ID) are coefficient books: they
//     ship labour / material / equipment norms but no ready unit prices, so a
//     resource price sheet is needed before they can be estimated against.
//
// From those facts, recommendedRegionFor() and isRecommended() encode:
//   1. prefer a priced base (usable out of the box) over a coefficient book;
//   2. among priced bases, rank by real coverage from the live base-stats
//      manifest when present, and honour a language / currency preference on
//      ties rather than inventing a coverage difference between master copies;
//   3. only fall back to a coefficient book when nothing priced is available.

import type { BaseStat, BaseStatsManifest } from './baseStats';

/** National / regional official bases that ship their own parquet (not the
 *  global CWICR master). Static fallback for when the live base-stats manifest
 *  has not loaded yet. */
export const NATIONAL_BASES: ReadonlySet<string> = new Set([
  'BR_NATIONAL',
  'ES_ANDALUCIA',
  'IT_TOSCANA',
  'VN_NATIONAL',
  'ID_NATIONAL',
  'GR_NATIONAL',
]);

/** Coefficient books: authentic norms but no ready unit prices (a resource
 *  price sheet is required before they can be priced). Static fallback for when
 *  the manifest's per-base ``coefficient`` flag is unavailable. */
export const COEFFICIENT_BASES: ReadonlySet<string> = new Set([
  'BR_NATIONAL',
  'VN_NATIONAL',
  'ID_NATIONAL',
]);

/** Options for {@link recommendedRegionFor}. */
export interface RecommendOptions {
  /** Live base-stats manifest (authoritative coverage + coefficient flags). */
  manifest?: BaseStatsManifest | null;
  /** A preferred region (e.g. matched to the UI language / currency). Wins when
   *  it is a sane, priced candidate. */
  prefer?: string | null;
}

/** Look up one base's stats in the manifest (pure, no React). */
function statOf(region: string, manifest?: BaseStatsManifest | null): BaseStat | undefined {
  if (!manifest || !Array.isArray(manifest.bases)) return undefined;
  return manifest.bases.find((b) => b.region === region);
}

/** Normalise a priced-percentage that may arrive as a 0..1 fraction or a
 *  0..100 percentage into a clamped 0..1 fraction. Never NaN. */
function clampFraction(n: number): number {
  if (!Number.isFinite(n)) return 0;
  const v = n > 1 ? n / 100 : n;
  if (v < 0) return 0;
  if (v > 1) return 1;
  return v;
}

/** Is this region part of the global CWICR master family (vs a national book)?
 *  Prefers the manifest families, falls back to the static national set. */
export function isGlobalCwicrBase(
  region: string,
  manifest?: BaseStatsManifest | null,
): boolean {
  const fam = manifest?.families;
  if (fam) {
    if (Array.isArray(fam.national) && fam.national.includes(region)) return false;
    if (Array.isArray(fam.global_cwicr) && fam.global_cwicr.includes(region)) return true;
  }
  return !NATIONAL_BASES.has(region);
}

/** Is this a coefficient book (norms, no ready unit prices)? Prefers the live
 *  manifest flag, falls back to the static set. */
export function isCoefficientBase(
  region: string,
  manifest?: BaseStatsManifest | null,
): boolean {
  const stat = statOf(region, manifest);
  if (stat && typeof stat.coefficient === 'boolean') return stat.coefficient;
  return COEFFICIENT_BASES.has(region);
}

/** A base is "priced" (usable out of the box) when it is not a coefficient
 *  book. */
export function isPricedBase(region: string, manifest?: BaseStatsManifest | null): boolean {
  return !isCoefficientBase(region, manifest);
}

/** Coverage score used to rank equally-priced candidates. Uses live coverage
 *  when the manifest is present (works weighted by resource depth and priced
 *  coverage); otherwise a coarse, honest category baseline: a global CWICR
 *  master outranks a single national book, which outranks a coefficient book.
 *  Never NaN. */
function coverageScore(region: string, manifest?: BaseStatsManifest | null): number {
  const stat = statOf(region, manifest);
  if (stat) {
    const works = Number(stat.works) || 0;
    const depth = Number(stat.avg_resources_per_work) || 0;
    const priced = typeof stat.priced_pct === 'number' ? clampFraction(stat.priced_pct) : 1;
    // Works are the backbone; resource depth and priced coverage refine it so a
    // more fully priced copy of the same master ranks a touch higher.
    return works * (1 + Math.min(depth, 20) / 20) * (0.5 + 0.5 * priced);
  }
  // No manifest: coarse ordering only, never a fake per-copy coverage claim.
  if (isCoefficientBase(region, manifest)) return 1;
  if (isGlobalCwicrBase(region, manifest)) return 3;
  return 2;
}

/**
 * Pick the single best base to recommend out of ``bases``.
 *
 * Returns the region code, or ``null`` when the list is empty. Pure: no React,
 * no network, safe to call from anywhere (render, effects, handlers).
 */
export function recommendedRegionFor(
  bases: readonly string[],
  opts: RecommendOptions = {},
): string | null {
  const list = Array.from(new Set((bases ?? []).filter((r): r is string => !!r)));
  if (list.length === 0) return null;
  const { manifest = null, prefer = null } = opts;

  // 1. Honour an explicit preference when it is a real candidate that is either
  //    priced, or the only kind available (every candidate is a coefficient
  //    book, so the preference is as good as any).
  if (prefer && list.includes(prefer)) {
    if (isPricedBase(prefer, manifest) || list.every((r) => isCoefficientBase(r, manifest))) {
      return prefer;
    }
  }

  // 2. Prefer priced bases; only fall back to coefficient books when nothing
  //    priced is loaded.
  const priced = list.filter((r) => isPricedBase(r, manifest));
  const pool = priced.length > 0 ? priced : list;

  // 3. Rank by coverage, then prefer the global CWICR master on ties (the fuller
  //    multi-trade book), then a stable alphabetical order for determinism.
  const ranked = pool.slice().sort((a, b) => {
    const ca = coverageScore(a, manifest);
    const cb = coverageScore(b, manifest);
    if (cb !== ca) return cb - ca;
    const ga = isGlobalCwicrBase(a, manifest) ? 1 : 0;
    const gb = isGlobalCwicrBase(b, manifest) ? 1 : 0;
    if (gb !== ga) return gb - ga;
    return a.localeCompare(b);
  });
  return ranked[0] ?? null;
}

/**
 * Whether a single region is worth surfacing as a recommended base on its own:
 * a priced base (the global CWICR master, or an official priced national book)
 * that is usable straight after loading. Coefficient books are never
 * self-recommended because they cannot be priced without extra setup. When a
 * manifest is supplied its ``coefficient`` flag is authoritative.
 */
export function isRecommended(region: string, manifest?: BaseStatsManifest | null): boolean {
  if (!region) return false;
  return isPricedBase(region, manifest);
}
