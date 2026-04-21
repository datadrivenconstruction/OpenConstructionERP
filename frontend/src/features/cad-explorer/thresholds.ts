/**
 * Conditional-formatting threshold rules for Data Explorer pivot cells.
 *
 * Power-BI-style horizontal data bars already render proportional to each
 * aggregate column's visible max. Threshold rules let the user bucket the
 * numeric value into low / mid / high zones (e.g. "< 0.8 red, 0.8–1.0
 * amber, > 1.0 green") and colour the bar + cell accordingly.
 *
 * The rule set persists in the URL so a shared link or browser reload
 * restores the exact same colouring. We keep the payload short:
 *
 *   ?tr=col~low~high~lowColor~midColor~highColor;col2~…
 *
 * Hex colour codes are stored without the leading `#` to shave characters
 * so we can fit up to MAX_RULES rules under the ~250-char soft cap.
 *
 * All functions here are pure — no React, no store imports — so they can
 * be round-tripped in unit tests.
 */

/** Single conditional-formatting rule bound to one aggregate column. */
export interface ThresholdRule {
  /** Aggregate column name (must be present in pivot aggCols). */
  column: string;
  /** Lower bound — values strictly below this fall into the `low` bucket. */
  low: number;
  /** Upper bound — values at or above this fall into the `high` bucket. */
  high: number;
  /** Bar / text colour for values below `low`. Hex (e.g. `#ef4444`). */
  lowColor: string;
  /** Bar / text colour for values in `[low, high)`. Hex. */
  midColor: string;
  /** Bar / text colour for values at or above `high`. Hex. */
  highColor: string;
}

/** Semantic zone a value falls into. `null` means no rule matched. */
export type ThresholdZone = 'low' | 'mid' | 'high';

/** Default colour palette — matches Tailwind red-500 / amber-500 / emerald-500. */
export const DEFAULT_LOW_COLOR = '#ef4444';
export const DEFAULT_MID_COLOR = '#f59e0b';
export const DEFAULT_HIGH_COLOR = '#10b981';

/** Hard cap on rule count to keep the URL short and the UI skimmable. */
export const MAX_RULES = 5;

/** Soft cap on serialised URL length — rules are truncated to fit. */
export const MAX_URL_LENGTH = 250;

/** Build a default rule for a freshly-added column. */
export function createDefaultRule(column: string): ThresholdRule {
  return {
    column,
    low: 0.8,
    high: 1,
    lowColor: DEFAULT_LOW_COLOR,
    midColor: DEFAULT_MID_COLOR,
    highColor: DEFAULT_HIGH_COLOR,
  };
}

/* ── Zone resolution ───────────────────────────────────────────────────── */

/**
 * Bucket a numeric value into a rule's low / mid / high zone.
 *
 * Convention:
 *   value <  low            → 'low'
 *   low   <= value <  high  → 'mid'
 *   value >= high           → 'high'
 *
 * When `low == high` (degenerate), the mid band has zero width so values
 * below the pivot go low and values at/above it go high — no value falls
 * in mid. This keeps the three-colour UI semantically predictable.
 *
 * Returns `null` when the rule doesn't apply (column mismatch, non-finite
 * inputs) so callers can fall back to the existing single-tone bar.
 */
export function resolveThresholdColor(
  value: number | null | undefined,
  rule: ThresholdRule | null | undefined,
  column?: string,
): ThresholdZone | null {
  if (!rule) return null;
  if (value == null || !Number.isFinite(value)) return null;
  if (column !== undefined && column !== rule.column) return null;
  if (!Number.isFinite(rule.low) || !Number.isFinite(rule.high)) return null;
  if (value < rule.low) return 'low';
  if (value >= rule.high) return 'high';
  return 'mid';
}

/* ── Style application ────────────────────────────────────────────────── */

/** Resolved style for a single pivot cell under a threshold rule. */
export interface ThresholdStyle {
  /** Bar fill colour (hex). */
  bar: string;
  /** Text colour (hex) for the numeric value inside the cell. */
  text: string;
  /** Cell background tint (rgba with 10% alpha). */
  bg: string;
}

/** Convert `#rrggbb` to `rgba(r, g, b, a)`. Tolerant of malformed hex. */
function hexToRgba(hex: string, alpha: number): string {
  const h = hex.replace(/^#/, '');
  if (h.length !== 3 && h.length !== 6) return `rgba(0, 0, 0, ${alpha})`;
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) {
    return `rgba(0, 0, 0, ${alpha})`;
  }
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
}

/**
 * Darken a hex colour by `amount` (0–1) toward black. Used to pick a
 * readable text colour on a light cell-background tint — the bar colour
 * itself is too saturated to read numbers against.
 */
function darken(hex: string, amount: number): string {
  const h = hex.replace(/^#/, '');
  if (h.length !== 3 && h.length !== 6) return hex;
  const full = h.length === 3 ? h.split('').map((c) => c + c).join('') : h;
  const r = parseInt(full.slice(0, 2), 16);
  const g = parseInt(full.slice(2, 4), 16);
  const b = parseInt(full.slice(4, 6), 16);
  if (!Number.isFinite(r) || !Number.isFinite(g) || !Number.isFinite(b)) return hex;
  const f = Math.max(0, Math.min(1, 1 - amount));
  const rr = Math.round(r * f).toString(16).padStart(2, '0');
  const gg = Math.round(g * f).toString(16).padStart(2, '0');
  const bb = Math.round(b * f).toString(16).padStart(2, '0');
  return `#${rr}${gg}${bb}`;
}

/**
 * Resolve a value + rule into a { bar, text, bg } triple for rendering.
 *
 * The caller keeps the bar width from `computeDataBar` — this function
 * only changes colours. When the rule doesn't apply, the returned struct
 * carries neutral fallback values that visually match the default
 * oe-blue theme; callers should typically skip calling this when
 * `resolveThresholdColor` returns null.
 */
export function applyRuleToBar(
  value: number | null | undefined,
  rule: ThresholdRule | null | undefined,
  _colMax?: number,
): ThresholdStyle {
  void _colMax; // Reserved for future gradient-within-zone support.
  const zone = resolveThresholdColor(value, rule);
  if (!zone || !rule) {
    return {
      bar: '#3b82f6',
      text: 'inherit',
      bg: 'transparent',
    };
  }
  const base =
    zone === 'low' ? rule.lowColor : zone === 'high' ? rule.highColor : rule.midColor;
  return {
    bar: base,
    // 30% darken keeps the text readable on the 10% bg tint without
    // washing out the colour signal.
    text: darken(base, 0.3),
    bg: hexToRgba(base, 0.1),
  };
}

/* ── URL (de)serialisation ────────────────────────────────────────────── */

/** Compress `#rrggbb` → `rrggbb` for shorter URLs; no-op otherwise. */
function stripHash(c: string): string {
  return c.startsWith('#') ? c.slice(1) : c;
}

/** Re-prefix `rrggbb` → `#rrggbb`; no-op if already prefixed. */
function prefixHash(c: string): string {
  return c.startsWith('#') ? c : `#${c}`;
}

/** Encode a column name so it survives our separator chars (`~` and `;`). */
function encodeColumn(col: string): string {
  return encodeURIComponent(col).replace(/~/g, '%7E').replace(/;/g, '%3B');
}

function decodeColumn(col: string): string {
  try {
    return decodeURIComponent(col);
  } catch {
    return col;
  }
}

/**
 * Serialise up to MAX_RULES threshold rules into a compact URL param.
 *
 * Format: `col~low~high~lowCol~midCol~highCol;col2~…`
 *   — tilde separates fields inside a rule
 *   — semicolon separates rules
 *
 * Rules beyond MAX_RULES are silently dropped. The output is also
 * truncated at MAX_URL_LENGTH by dropping trailing rules rather than
 * producing an un-parseable string.
 */
export function serialiseThresholds(rules: readonly ThresholdRule[]): string {
  if (!rules.length) return '';
  const capped = rules.slice(0, MAX_RULES);
  const chunks: string[] = [];
  for (const r of capped) {
    if (!r.column) continue;
    if (!Number.isFinite(r.low) || !Number.isFinite(r.high)) continue;
    const parts = [
      encodeColumn(r.column),
      String(r.low),
      String(r.high),
      stripHash(r.lowColor),
      stripHash(r.midColor),
      stripHash(r.highColor),
    ];
    chunks.push(parts.join('~'));
  }
  // Soft-cap the total length by dropping trailing rules.
  let out = chunks.join(';');
  while (out.length > MAX_URL_LENGTH && chunks.length > 1) {
    chunks.pop();
    out = chunks.join(';');
  }
  return out;
}

/**
 * Inverse of `serialiseThresholds`. Tolerant of malformed input — skips
 * bad rules so the UI degrades gracefully on hand-edited URLs.
 */
export function parseThresholds(raw: string | null | undefined): ThresholdRule[] {
  if (!raw) return [];
  const out: ThresholdRule[] = [];
  for (const chunk of raw.split(';')) {
    if (!chunk) continue;
    const parts = chunk.split('~');
    if (parts.length < 6) continue;
    const [col, lowS, highS, lowC, midC, highC] = parts;
    const column = decodeColumn(col || '');
    const low = parseFloat(lowS || '');
    const high = parseFloat(highS || '');
    if (!column) continue;
    if (!Number.isFinite(low) || !Number.isFinite(high)) continue;
    out.push({
      column,
      low,
      high,
      lowColor: prefixHash(lowC || DEFAULT_LOW_COLOR),
      midColor: prefixHash(midC || DEFAULT_MID_COLOR),
      highColor: prefixHash(highC || DEFAULT_HIGH_COLOR),
    });
    if (out.length >= MAX_RULES) break;
  }
  return out;
}

/** Find the first rule that binds to `column`, or null when none does. */
export function findRuleForColumn(
  rules: readonly ThresholdRule[],
  column: string,
): ThresholdRule | null {
  for (const r of rules) {
    if (r.column === column) return r;
  }
  return null;
}

/** Shallow validity check used by the modal to gate Save. */
export function isRuleValid(
  rule: ThresholdRule,
  availableColumns: readonly string[],
): boolean {
  if (!rule.column) return false;
  if (availableColumns.length > 0 && !availableColumns.includes(rule.column)) return false;
  if (!Number.isFinite(rule.low) || !Number.isFinite(rule.high)) return false;
  if (rule.low >= rule.high) return false;
  return true;
}
