/**
 * suggestQuantityFromBIM — pick the most relevant geometric/quantitative
 * value from a set of BIM elements for a given BOQ position unit.
 *
 * Used by the BIM → BOQ link flow (`AddToBOQModal`) to pre-fill the
 * "Quantity" input.  Mapping (priority order, first hit wins):
 *
 *   m³ / m3   → quantities.volume_m3, quantities.volume,
 *               properties.NetVolume, properties.GrossVolume,
 *               properties.Volume
 *   m² / m2   → quantities.area_m2, quantities.area,
 *               properties.NetArea, properties.GrossArea,
 *               properties.NetSideArea, properties.Area
 *   m         → quantities.length_m, quantities.length,
 *               properties.Length, properties.Height
 *   kg        → quantities.mass, quantities.mass_kg,
 *               properties.NetWeight, properties.GrossWeight.
 *               Fallback: volume × material density when both
 *               are known (low confidence).
 *   pcs / Stk / шт / pc / piece(s) → element count
 *   lsum / ls / lump → 1
 *
 * Multi-element semantics:
 *   - sum across elements for volume / area / length / mass
 *   - count for pcs/шт
 *   - 1 for lsum
 *
 * Returns `{ value, source, confidence }` so the caller can render
 * a badge ("Σ volume = 17.40 m³ from 3 elements") and warn on low
 * confidence (computed-from-density, unit mismatch).
 *
 * This module is pure (no React, no I/O) — safe to import from tests.
 */

import type { BIMElementData } from '@/shared/ui/BIMViewer/ElementManager';

/* ── Types ────────────────────────────────────────────────────────────── */

/** Where the suggested value came from. Ordered alphabetically; the UI
 *  uses this to render a human-readable badge. */
export type QuantitySuggestionSource =
  | 'sum_volume'
  | 'sum_area'
  | 'sum_length'
  | 'sum_mass'
  | 'count'
  | 'lsum'
  | 'computed_mass_from_density'
  | 'unit_unknown'
  | 'no_elements';

export type QuantitySuggestionConfidence = 'high' | 'medium' | 'low';

export interface QuantitySuggestion {
  /** Numeric value to pre-fill into the quantity input. Always finite,
   *  never NaN. Zero is a valid signal ("we found the field but the
   *  geometry was empty"). */
  value: number;
  /** What the value represents. Drives the badge label and the icon. */
  source: QuantitySuggestionSource;
  /** UI hint for trust-level. `low` = show a warning. */
  confidence: QuantitySuggestionConfidence;
  /** Property/quantity key that produced the value (or empty for count
   *  / lsum / no_elements). Useful for debug overlays. */
  matchedKey: string;
  /** Number of elements that contributed at least one numeric value
   *  to the sum.  For `count` it's `elements.length`. */
  contributingElements: number;
  /** Total number of elements considered (== `elements.length`). */
  totalElements: number;
  /** Inferred unit ("m³", "m²", "m", "kg", "pcs", "lsum") — may differ
   *  from the requested unit when `source === 'unit_unknown'` (in which
   *  case it falls back to a best-effort guess). */
  inferredUnit: string;
}

/* ── Unit normalization ──────────────────────────────────────────────── */

/** Canonicalize a free-text unit string (e.g. user-typed "M3", "m³",
 *  "Stk.") to one of our internal categories. Unknown units return
 *  the empty string so callers can fall back to volume-first heuristics. */
export type CanonicalUnit = 'm3' | 'm2' | 'm' | 'kg' | 'pcs' | 'lsum' | '';

export function normalizeUnit(unit: string | null | undefined): CanonicalUnit {
  if (!unit) return '';
  const u = String(unit).trim().toLowerCase();
  if (!u) return '';
  // Strip trailing dots ("Stk." → "stk") and surrounding punctuation.
  const stripped = u.replace(/[.\s]+$/, '').replace(/^[.\s]+/, '');

  // Volume
  if (
    stripped === 'm³' ||
    stripped === 'm3' ||
    stripped === 'cbm' ||
    stripped === 'cu.m' ||
    stripped === 'cum' ||
    stripped === 'm^3'
  ) {
    return 'm3';
  }
  // Area
  if (
    stripped === 'm²' ||
    stripped === 'm2' ||
    stripped === 'sqm' ||
    stripped === 'sq.m' ||
    stripped === 'm^2'
  ) {
    return 'm2';
  }
  // Length
  if (stripped === 'm' || stripped === 'lm' || stripped === 'mtr' || stripped === 'meter' || stripped === 'metre') {
    return 'm';
  }
  // Mass
  if (stripped === 'kg' || stripped === 'kgs' || stripped === 'kilogram' || stripped === 'kilograms') {
    return 'kg';
  }
  // Count — German "Stk", Russian "шт", English "pcs/pc/piece(s)/each/ea"
  if (
    stripped === 'pcs' ||
    stripped === 'pc' ||
    stripped === 'piece' ||
    stripped === 'pieces' ||
    stripped === 'stk' ||
    stripped === 'stck' ||
    stripped === 'stuck' ||
    stripped === 'stück' ||
    stripped === 'шт' ||
    stripped === 'each' ||
    stripped === 'ea' ||
    stripped === 'nr' ||
    stripped === 'no'
  ) {
    return 'pcs';
  }
  // Lump-sum
  if (
    stripped === 'lsum' ||
    stripped === 'ls' ||
    stripped === 'lump' ||
    stripped === 'lumpsum' ||
    stripped === 'psch' || // German "Pauschal"
    stripped === 'pausch'
  ) {
    return 'lsum';
  }
  return '';
}

/* ── Internal helpers ────────────────────────────────────────────────── */

/** Coerce a value to a finite number, or null if it can't be coerced.
 *  Empty strings and zero-length collections become null (we don't want
 *  "0" to mask the "field absent" case for fallbacks). */
function toFiniteNumber(value: unknown): number | null {
  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : null;
  }
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const n = Number.parseFloat(trimmed);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

/** Sum a numeric field across elements, looking it up in `quantities`
 *  first then `properties`. Returns `{ sum, contributors, matchedKey }`
 *  where `contributors` is the count of elements that provided a value. */
interface SumResult {
  sum: number;
  contributors: number;
  matchedKey: string;
}

function sumField(
  elements: readonly BIMElementData[],
  candidates: readonly { source: 'quantities' | 'properties'; key: string }[],
): SumResult {
  let total = 0;
  let contributors = 0;
  let matchedKey = '';
  for (const el of elements) {
    let elementContribution: number | null = null;
    let elementMatchedKey = '';
    for (const { source, key } of candidates) {
      const bag =
        source === 'quantities' ? el.quantities : (el.properties as Record<string, unknown> | undefined);
      if (!bag) continue;
      // Case-sensitive first, then case-insensitive fallback for property
      // keys (Revit/IFC mix `NetVolume` vs `netVolume` vs `Net Volume`).
      let raw: unknown = (bag as Record<string, unknown>)[key];
      if (raw === undefined) {
        const lc = key.toLowerCase();
        for (const [k, v] of Object.entries(bag)) {
          if (k.toLowerCase() === lc) {
            raw = v;
            break;
          }
        }
      }
      const n = toFiniteNumber(raw);
      if (n !== null) {
        elementContribution = n;
        elementMatchedKey = `${source}.${key}`;
        break; // first hit per element wins
      }
    }
    if (elementContribution !== null) {
      total += elementContribution;
      contributors += 1;
      if (!matchedKey) matchedKey = elementMatchedKey;
    }
  }
  return { sum: total, contributors, matchedKey };
}

/** Try to read a material-density value (kg/m³) from element properties.
 *  Common keys across IFC/Revit exports: `Density`, `MaterialDensity`,
 *  `density`. Returns null if absent or non-numeric. */
function readDensity(el: BIMElementData): number | null {
  const props = el.properties as Record<string, unknown> | undefined;
  if (!props) return null;
  for (const key of ['Density', 'MaterialDensity', 'density', 'material_density']) {
    const v = toFiniteNumber(props[key]);
    if (v !== null && v > 0) return v;
  }
  // Last-ditch: case-insensitive scan
  for (const [k, v] of Object.entries(props)) {
    if (k.toLowerCase().includes('density')) {
      const n = toFiniteNumber(v);
      if (n !== null && n > 0) return n;
    }
  }
  return null;
}

/* ── Field-priority tables ───────────────────────────────────────────── */

const VOLUME_KEYS = [
  { source: 'quantities' as const, key: 'volume_m3' },
  { source: 'quantities' as const, key: 'volume' },
  { source: 'properties' as const, key: 'NetVolume' },
  { source: 'properties' as const, key: 'GrossVolume' },
  { source: 'properties' as const, key: 'Volume' },
];

const AREA_KEYS = [
  { source: 'quantities' as const, key: 'area_m2' },
  { source: 'quantities' as const, key: 'area' },
  { source: 'properties' as const, key: 'NetArea' },
  { source: 'properties' as const, key: 'GrossArea' },
  { source: 'properties' as const, key: 'NetSideArea' },
  { source: 'properties' as const, key: 'GrossSideArea' },
  { source: 'properties' as const, key: 'Area' },
];

const LENGTH_KEYS = [
  { source: 'quantities' as const, key: 'length_m' },
  { source: 'quantities' as const, key: 'length' },
  { source: 'properties' as const, key: 'Length' },
  { source: 'properties' as const, key: 'Height' },
  { source: 'properties' as const, key: 'Perimeter' },
];

const MASS_KEYS = [
  { source: 'quantities' as const, key: 'mass' },
  { source: 'quantities' as const, key: 'mass_kg' },
  { source: 'quantities' as const, key: 'weight' },
  { source: 'properties' as const, key: 'NetWeight' },
  { source: 'properties' as const, key: 'GrossWeight' },
  { source: 'properties' as const, key: 'Mass' },
  { source: 'properties' as const, key: 'Weight' },
];

/* ── Public API ──────────────────────────────────────────────────────── */

/**
 * Suggest a quantity value for a BOQ position based on its `unit` and
 * the linked BIM elements' geometric/quantitative properties.
 *
 * @param elements - one or more BIM elements (single or bulk-link case)
 * @param unit     - target BOQ position unit (free text, will be normalized)
 * @returns        - suggestion with confidence + source for UI display
 */
export function suggestQuantityFromBIM(
  elements: readonly BIMElementData[],
  unit: string | null | undefined,
): QuantitySuggestion {
  const totalElements = elements.length;

  if (totalElements === 0) {
    return {
      value: 0,
      source: 'no_elements',
      confidence: 'low',
      matchedKey: '',
      contributingElements: 0,
      totalElements: 0,
      inferredUnit: '',
    };
  }

  const canonical = normalizeUnit(unit);

  switch (canonical) {
    case 'm3': {
      const r = sumField(elements, VOLUME_KEYS);
      if (r.contributors > 0) {
        return {
          value: r.sum,
          source: 'sum_volume',
          confidence: r.contributors === totalElements ? 'high' : 'medium',
          matchedKey: r.matchedKey,
          contributingElements: r.contributors,
          totalElements,
          inferredUnit: 'm³',
        };
      }
      // Volume requested but no volume field → low confidence zero.
      return zeroSuggestion('sum_volume', 'm³', totalElements);
    }

    case 'm2': {
      const r = sumField(elements, AREA_KEYS);
      if (r.contributors > 0) {
        return {
          value: r.sum,
          source: 'sum_area',
          confidence: r.contributors === totalElements ? 'high' : 'medium',
          matchedKey: r.matchedKey,
          contributingElements: r.contributors,
          totalElements,
          inferredUnit: 'm²',
        };
      }
      return zeroSuggestion('sum_area', 'm²', totalElements);
    }

    case 'm': {
      const r = sumField(elements, LENGTH_KEYS);
      if (r.contributors > 0) {
        return {
          value: r.sum,
          source: 'sum_length',
          confidence: r.contributors === totalElements ? 'high' : 'medium',
          matchedKey: r.matchedKey,
          contributingElements: r.contributors,
          totalElements,
          inferredUnit: 'm',
        };
      }
      return zeroSuggestion('sum_length', 'm', totalElements);
    }

    case 'kg': {
      // 1) Direct mass field
      const direct = sumField(elements, MASS_KEYS);
      if (direct.contributors > 0) {
        return {
          value: direct.sum,
          source: 'sum_mass',
          confidence: direct.contributors === totalElements ? 'high' : 'medium',
          matchedKey: direct.matchedKey,
          contributingElements: direct.contributors,
          totalElements,
          inferredUnit: 'kg',
        };
      }
      // 2) Compute from volume × density per element (low confidence)
      let total = 0;
      let contributors = 0;
      let firstKey = '';
      for (const el of elements) {
        const volR = sumField([el], VOLUME_KEYS);
        if (volR.contributors === 0 || volR.sum <= 0) continue;
        const density = readDensity(el);
        if (density === null) continue;
        total += volR.sum * density;
        contributors += 1;
        if (!firstKey) firstKey = `${volR.matchedKey}×density`;
      }
      if (contributors > 0) {
        return {
          value: total,
          source: 'computed_mass_from_density',
          confidence: 'low',
          matchedKey: firstKey,
          contributingElements: contributors,
          totalElements,
          inferredUnit: 'kg',
        };
      }
      return zeroSuggestion('sum_mass', 'kg', totalElements);
    }

    case 'pcs': {
      return {
        value: totalElements,
        source: 'count',
        confidence: 'high',
        matchedKey: '',
        contributingElements: totalElements,
        totalElements,
        inferredUnit: 'pcs',
      };
    }

    case 'lsum': {
      return {
        value: 1,
        source: 'lsum',
        confidence: 'high',
        matchedKey: '',
        contributingElements: totalElements,
        totalElements,
        inferredUnit: 'lsum',
      };
    }

    case '':
    default: {
      // Unknown / missing unit — fall back to volume → area → length → count,
      // matching the behaviour the modal had before this helper existed.
      // Confidence is `low` because we're guessing what the user meant.
      const vol = sumField(elements, VOLUME_KEYS);
      if (vol.contributors > 0 && vol.sum > 0) {
        return {
          value: vol.sum,
          source: 'sum_volume',
          confidence: 'low',
          matchedKey: vol.matchedKey,
          contributingElements: vol.contributors,
          totalElements,
          inferredUnit: 'm³',
        };
      }
      const area = sumField(elements, AREA_KEYS);
      if (area.contributors > 0 && area.sum > 0) {
        return {
          value: area.sum,
          source: 'sum_area',
          confidence: 'low',
          matchedKey: area.matchedKey,
          contributingElements: area.contributors,
          totalElements,
          inferredUnit: 'm²',
        };
      }
      const len = sumField(elements, LENGTH_KEYS);
      if (len.contributors > 0 && len.sum > 0) {
        return {
          value: len.sum,
          source: 'sum_length',
          confidence: 'low',
          matchedKey: len.matchedKey,
          contributingElements: len.contributors,
          totalElements,
          inferredUnit: 'm',
        };
      }
      return {
        value: totalElements,
        source: 'unit_unknown',
        confidence: 'low',
        matchedKey: '',
        contributingElements: totalElements,
        totalElements,
        inferredUnit: 'pcs',
      };
    }
  }
}

function zeroSuggestion(
  source: QuantitySuggestionSource,
  inferredUnit: string,
  totalElements: number,
): QuantitySuggestion {
  return {
    value: 0,
    source,
    confidence: 'low',
    matchedKey: '',
    contributingElements: 0,
    totalElements,
    inferredUnit,
  };
}

/* ── Badge formatting (UI helper) ────────────────────────────────────── */

/** Human-readable label for the suggestion badge.  Examples:
 *    "Σ volume = 17.40 m³ from 3 elements"
 *    "count = 5 pcs"
 *    "computed mass = 285.00 kg (volume × density)"
 *
 *  Pure formatter — no React, callable from tests. */
export function formatSuggestionBadge(s: QuantitySuggestion): string {
  const fmt = (n: number) =>
    Number.isInteger(n)
      ? n.toLocaleString('en', { maximumFractionDigits: 0 })
      : n.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 4 });

  const elementsSuffix =
    s.totalElements > 1
      ? ` from ${s.contributingElements}/${s.totalElements} elements`
      : '';

  switch (s.source) {
    case 'sum_volume':
      return `Σ volume = ${fmt(s.value)} ${s.inferredUnit}${elementsSuffix}`;
    case 'sum_area':
      return `Σ area = ${fmt(s.value)} ${s.inferredUnit}${elementsSuffix}`;
    case 'sum_length':
      return `Σ length = ${fmt(s.value)} ${s.inferredUnit}${elementsSuffix}`;
    case 'sum_mass':
      return `Σ mass = ${fmt(s.value)} ${s.inferredUnit}${elementsSuffix}`;
    case 'count':
      return `count = ${fmt(s.value)} ${s.inferredUnit}`;
    case 'lsum':
      return 'lump sum = 1';
    case 'computed_mass_from_density':
      return `≈ ${fmt(s.value)} kg (volume × density)${elementsSuffix}`;
    case 'unit_unknown':
      return `unit unknown — using count = ${fmt(s.value)}`;
    case 'no_elements':
      return 'no elements selected';
  }
}
