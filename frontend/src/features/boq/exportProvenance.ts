/**
 * Shared cost-base provenance helpers for BOQ exports (Excel + PDF).
 *
 * A multi-base estimate mixes cost lines drawn from more than one cost
 * database ("base"), e.g. Germany (EUR) and Türkiye (TRY). Every BOQ
 * position added from the Cost Database browser carries its origin under
 * ``metadata.cost_item_region`` (+ ``metadata.cost_item_currency`` or the
 * generic ``metadata.currency``); how the line entered the estimate is on
 * ``position.source`` (manual / cad_import / ai_takeoff / gaeb_import).
 *
 * These helpers read that stamped provenance and turn it into:
 *   - per-line Base / Source / Currency values for the export tables, and
 *   - an estimate-level "Cost Bases Used" summary (distinct bases + counts).
 *
 * Back-compat / self-hide: a single-base estimate (0 or 1 distinct base)
 * returns an empty ``basesUsed`` list and ``distinctBaseCount() < 2`` so
 * callers keep today's layout with no extra columns or blocks.
 *
 * Money is never blended: no value here is a currency-converted amount; the
 * summary lists each base's own currency explicitly.
 */

import { REGION_MAP } from '@/stores/useCostDatabaseStore';
import { isSection, type Position } from './api';

/**
 * Country-head fallback for region ids the UI table (REGION_MAP) does not
 * carry verbatim, e.g. a canonical backend id ``GB_LONDON`` vs the UI key
 * ``UK_GBP``, or ``ES_MADRID`` vs ``SP_BARCELONA``. Keeps the base name
 * readable instead of leaking a raw code into the export.
 */
const COUNTRY_HEAD_NAMES: Record<string, string> = {
  DE: 'Germany',
  AT: 'Austria',
  CH: 'Switzerland',
  FR: 'France',
  ES: 'Spain',
  SP: 'Spain',
  IT: 'Italy',
  PT: 'Portugal',
  BR: 'Brazil',
  GB: 'United Kingdom',
  UK: 'United Kingdom',
  IE: 'Ireland',
  USA: 'United States',
  US: 'United States',
  CA: 'Canada',
  ENG: 'Canada',
  AU: 'Australia',
  NZ: 'New Zealand',
  ZA: 'South Africa',
  NG: 'Nigeria',
  IN: 'India',
  HI: 'India',
  PL: 'Poland',
  CZ: 'Czech Republic',
  CS: 'Czech Republic',
  RO: 'Romania',
  RU: 'Russia',
  BG: 'Bulgaria',
  HR: 'Croatia',
  NL: 'Netherlands',
  BE: 'Belgium',
  SV: 'Sweden',
  SE: 'Sweden',
  ZH: 'China',
  CN: 'China',
  JP: 'Japan',
  JA: 'Japan',
  KR: 'South Korea',
  KO: 'South Korea',
  ID: 'Indonesia',
  TH: 'Thailand',
  VN: 'Vietnam',
  VI: 'Vietnam',
  AE: 'Middle East / Gulf',
  AR: 'Middle East / Gulf',
  TR: 'Türkiye',
  GR: 'Greece',
  MX: 'Mexico',
};

/**
 * Human-readable base name for a stamped region / catalog code. Uses the
 * same REGION_MAP table the UI renders, then a country-head fallback, then
 * the raw code so nothing renders blank.
 */
export function baseNameForRegion(region: string | null | undefined): string {
  if (!region) return '';
  const info = REGION_MAP[region];
  if (info) return info.name;
  const head = (region.split('_', 1)[0] ?? '').toUpperCase();
  return COUNTRY_HEAD_NAMES[head] ?? region;
}

export interface PositionProvenance {
  /** Raw region / catalog code stamped on the position ('' when absent). */
  region: string;
  /** Human-readable base name (falls back to the raw code). */
  base: string;
  /** How the line entered the estimate (position.source). */
  source: string;
  /** ISO 4217 currency stamped on the position ('' when absent). */
  currency: string;
}

function readMeta(pos: Position): Record<string, unknown> {
  return (pos.metadata ??
    (pos as unknown as Record<string, unknown>).metadata_ ??
    {}) as Record<string, unknown>;
}

/** Extract Base / Source / Currency provenance from one BOQ position. */
export function provenanceOf(pos: Position): PositionProvenance {
  const meta = readMeta(pos);
  const region = typeof meta.cost_item_region === 'string' ? meta.cost_item_region : '';
  const currency =
    (typeof meta.cost_item_currency === 'string' && meta.cost_item_currency) ||
    (typeof meta.currency === 'string' && meta.currency) ||
    '';
  const source = typeof pos.source === 'string' ? pos.source : '';
  return { region, base: baseNameForRegion(region), source, currency };
}

export interface BaseUsage {
  region: string;
  base: string;
  currency: string;
  /** Number of costed (non-section) positions attributed to this base. */
  positions: number;
}

/**
 * Aggregate the distinct cost bases used across a positions list. Only
 * positions that carry a stamped ``cost_item_region`` count; manual lines
 * without provenance are ignored. Sorted by descending line count.
 */
export function basesUsed(positions: Position[]): BaseUsage[] {
  const byRegion = new Map<string, BaseUsage>();
  for (const pos of positions) {
    if (isSection(pos)) continue;
    const { region, base, currency } = provenanceOf(pos);
    if (!region) continue;
    const existing = byRegion.get(region);
    if (existing) {
      existing.positions += 1;
      if (!existing.currency && currency) existing.currency = currency;
    } else {
      byRegion.set(region, { region, base: base || region, currency, positions: 1 });
    }
  }
  return [...byRegion.values()].sort((a, b) => b.positions - a.positions);
}

/**
 * Number of distinct cost bases. Drives the self-hide rule: provenance
 * columns and the "Cost Bases Used" block appear only when this is >= 2, so
 * a single-base estimate exports exactly as it does today.
 */
export function distinctBaseCount(positions: Position[]): number {
  return basesUsed(positions).length;
}
