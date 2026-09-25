// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Human-readable, localized labels for unit tokens.
 *
 * The unit dropdowns across the app store a canonical token (`m2`, `sqft`,
 * `cy` …) produced by {@link getUnitsForLocale}. Showing that raw token in a
 * picker ("m2", "sqft") is terse and unclear for a first-time global user, so
 * this helper turns a token into a friendly label ("m² · Square meter") while
 * the caller keeps the raw token as the option `value` — storage stays
 * canonical and no save flow changes.
 *
 * The friendly-name set is deliberately small: the common construction
 * estimating units plus the core imperial tokens. Every other token
 * (locale-native "Stk"/"шт"/"個", or a specialised token) falls back to its
 * display glyph and ultimately the raw token, so nothing ever renders blank.
 */
import { getDisplayUnit } from './unitConversion';

/** Minimal shape of the i18next `t` used here (repo convention). */
type Translate = (key: string, opts?: { defaultValue?: string }) => string;

/**
 * Canonical token -> { i18n key, English name }. Keys live under the shared
 * `units.*` namespace (not `assemblies.*`) so any picker — assemblies, catalog,
 * costs, BOQ — can adopt this helper without pulling a feature-scoped key.
 */
const UNIT_NAMES: Record<string, { key: string; en: string }> = {
  // Common metric
  m: { key: 'units.m', en: 'Meter' },
  lm: { key: 'units.lm', en: 'Linear meter' },
  m2: { key: 'units.m2', en: 'Square meter' },
  m3: { key: 'units.m3', en: 'Cubic meter' },
  kg: { key: 'units.kg', en: 'Kilogram' },
  t: { key: 'units.t', en: 'Tonne' },
  // Counts / scope
  pcs: { key: 'units.pcs', en: 'Piece' },
  ea: { key: 'units.ea', en: 'Each' },
  set: { key: 'units.set', en: 'Set' },
  lsum: { key: 'units.lsum', en: 'Lump sum' },
  h: { key: 'units.h', en: 'Hour' },
  // Core imperial (the whole point of the locale/imperial-aware picker)
  ft: { key: 'units.ft', en: 'Foot' },
  sqft: { key: 'units.sqft', en: 'Square foot' },
  cy: { key: 'units.cy', en: 'Cubic yard' },
  lf: { key: 'units.lf', en: 'Linear foot' },
};

/**
 * Compact display glyph for a unit token, e.g. `m2` -> `m²`. Never adds a
 * name — use this for dense grid cells and inline suffixes where space is
 * tight. Unknown tokens pass through unchanged.
 */
export function unitGlyph(token: string): string {
  if (!token) return '';
  return getDisplayUnit(token);
}

/**
 * Locale-specific trade codes that replace the canonical token in dense
 * cells. German LVs write a lump-sum position as "psch" (pauschal) — the
 * GAEB-DA short code — so showing the internal "lsum" token reads as a bug
 * to a Kalkulator. Only display changes: storage stays canonical.
 */
const LOCALE_UNIT_CODES: Record<string, Record<string, string>> = {
  // "Stk" is the trade short form the app's own German strings promise
  // ("Standard-m, m², m³, kg, Stk"); a raw "pcs" next to German labels
  // reads as untranslated UI (audit case-2 K-14).
  de: { lsum: 'psch', ls: 'psch', lump_sum: 'psch', pcs: 'Stk', ea: 'Stk' },
  // A Croatian troskovnik writes a running metre as "m'", a lump sum as
  // "paus." with the caron and a piece as "kom". The server folds the
  // apostrophe forms of the running metre into the canonical "lm", so without
  // this entry a Croatian user who typed m' would read back "l.m".
  hr: { lm: "m'", lsum: 'pauš.', ls: 'pauš.', lump_sum: 'pauš.', pcs: 'kom', ea: 'kom' },
};

/**
 * Locale-aware short unit code for dense grid cells and badges.
 *
 * Applies the display glyph (`m2` -> `m²`, `m3` -> `m³`) and, on top of it,
 * the locale's trade spelling for tokens that have one (de: `lsum` ->
 * `psch`). Unknown tokens pass through unchanged; the stored value is never
 * modified.
 *
 * @param token Canonical unit token as stored (`m2`, `lsum`, …).
 * @param lang  Active i18next language (e.g. `de`, `de-AT`, `en`).
 */
export function localizedUnitCode(token: string, lang: string): string {
  if (!token) return '';
  const trimmed = token.trim();
  // Compound trade units ("100 m2", "10 m3" — common in DACH cost bases):
  // keep the multiplier, localize the unit part ("100 m2" -> "100 m²").
  const compound = trimmed.match(/^(\d+(?:[.,]\d+)?)\s*([^\d\s].*)$/);
  if (compound?.[1] && compound[2]) {
    return `${compound[1]} ${localizedUnitCode(compound[2], lang)}`;
  }
  const localeMap = LOCALE_UNIT_CODES[(lang || '').split('-')[0] ?? ''];
  const localized = localeMap?.[trimmed.toLowerCase()];
  return localized ?? getDisplayUnit(trimmed);
}

/**
 * Friendly, localized label for a unit token, e.g. "m² · Square meter".
 *
 * The glyph is always placed first so that even when a locale has no
 * translation for the name (or the token is unknown) the estimator still sees
 * the symbol they recognise. The name is appended only for the common tokens
 * in {@link UNIT_NAMES}; every other token renders as just its glyph.
 */
export function unitLabel(token: string, t: Translate): string {
  const glyph = unitGlyph(token);
  const entry = UNIT_NAMES[token] ?? UNIT_NAMES[token.toLowerCase()];
  if (!entry) return glyph || token;
  const name = t(entry.key, { defaultValue: entry.en });
  // Guard against a locale returning the bare key (missing + no fallback).
  if (!name || name === entry.key) return glyph || token;
  return `${glyph} · ${name}`;
}
