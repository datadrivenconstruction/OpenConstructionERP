/**
 * color5d — rate-based colour gradient for the BIM viewer's "5D cost" mode.
 *
 * Given a BOQ unit_rate and the min/max rate across the currently loaded
 * model, produce a hex colour on a blue → yellow → red gradient.  Elements
 * without a rate render gray with reduced opacity so the user can see them
 * but they don't compete with the cost signal.
 *
 *   low  rate → #0071e3 (Apple system blue)
 *   mid  rate → #f59e0b (amber-500)
 *   high rate → #ef4444 (red-500)
 *
 * The mapping is perceptually uniform-ish and plays well with the rest of
 * the design system (the existing validation/coverage modes use the same
 * red/amber palette).
 */

export interface RateGradientStop {
  /** Position on [0, 1]. */
  t: number;
  /** CSS hex colour. */
  hex: string;
}

/** Default 3-stop gradient.  Exposed for the legend strip. */
export const DEFAULT_5D_GRADIENT: readonly RateGradientStop[] = [
  { t: 0.0, hex: '#0071e3' },
  { t: 0.5, hex: '#f59e0b' },
  { t: 1.0, hex: '#ef4444' },
];

/** Colour for elements without a linked BOQ position. */
export const NO_LINK_COLOR = '#9ca3af';
/** Opacity for no-link elements — keeps them visible but non-competing. */
export const NO_LINK_OPACITY = 0.3;

function clamp01(x: number): number {
  if (x < 0) return 0;
  if (x > 1) return 1;
  return x;
}

function parseHex(hex: string): { r: number; g: number; b: number } {
  const h = hex.replace(/^#/, '');
  const r = parseInt(h.slice(0, 2), 16);
  const g = parseInt(h.slice(2, 4), 16);
  const b = parseInt(h.slice(4, 6), 16);
  return { r, g, b };
}

function toHex(r: number, g: number, b: number): string {
  const clamp = (v: number) => Math.max(0, Math.min(255, Math.round(v)));
  const hx = (v: number) => clamp(v).toString(16).padStart(2, '0');
  return `#${hx(r)}${hx(g)}${hx(b)}`;
}

/** Linearly interpolate between two hex colours. */
function lerpHex(a: string, b: string, t: number): string {
  const pa = parseHex(a);
  const pb = parseHex(b);
  const tt = clamp01(t);
  return toHex(
    pa.r + (pb.r - pa.r) * tt,
    pa.g + (pb.g - pa.g) * tt,
    pa.b + (pb.b - pa.b) * tt,
  );
}

/**
 * Pick the colour for a position `t` on [0, 1] against a gradient.
 *
 * Stops must be sorted ascending by `t`.  Values outside [0, 1] clamp.
 */
export function colorAtStop(
  t: number,
  stops: readonly RateGradientStop[] = DEFAULT_5D_GRADIENT,
): string {
  if (stops.length === 0) return NO_LINK_COLOR;
  if (stops.length === 1) return stops[0]!.hex;
  const tt = clamp01(t);
  // Find bracketing stops.
  for (let i = 0; i < stops.length - 1; i++) {
    const a = stops[i]!;
    const b = stops[i + 1]!;
    if (tt >= a.t && tt <= b.t) {
      const span = b.t - a.t;
      if (span <= 0) return a.hex;
      const localT = (tt - a.t) / span;
      return lerpHex(a.hex, b.hex, localT);
    }
  }
  // Out-of-bounds fallback — shouldn't happen with a valid [0,1] gradient.
  return tt <= stops[0]!.t ? stops[0]!.hex : stops[stops.length - 1]!.hex;
}

/**
 * Normalise a rate into [0, 1] given a min/max range.
 *
 *   rate = min → 0
 *   rate = max → 1
 *   degenerate (min === max) → 0.5 (middle of gradient — safe default)
 *   non-finite rate → null (caller should render no-link colour)
 */
export function normalizeRate(
  rate: number | null | undefined,
  min: number,
  max: number,
): number | null {
  if (rate == null || !Number.isFinite(rate)) return null;
  if (!Number.isFinite(min) || !Number.isFinite(max)) return null;
  if (min === max) return 0.5;
  if (max < min) return null;
  return clamp01((rate - min) / (max - min));
}

/**
 * Map a rate to a hex colour on the default 5D gradient.
 *
 * @param rate  element's linked unit_rate (or null if no link)
 * @param min   smallest rate observed across the model
 * @param max   largest rate observed across the model
 * @returns { color, hasLink } where `hasLink` is false when rate is null —
 *          callers use it to apply the NO_LINK_OPACITY fade.
 */
export function colorForRate(
  rate: number | null | undefined,
  min: number,
  max: number,
): { color: string; hasLink: boolean } {
  const t = normalizeRate(rate, min, max);
  if (t === null) {
    return { color: NO_LINK_COLOR, hasLink: false };
  }
  return { color: colorAtStop(t), hasLink: true };
}
