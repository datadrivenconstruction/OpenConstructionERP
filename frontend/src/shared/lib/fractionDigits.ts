// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One place to turn caller-supplied fraction-digit overrides into a pair
 * `Intl.NumberFormat` will accept.
 *
 * `Intl` answers `minimumFractionDigits > maximumFractionDigits` with a
 * `RangeError` (WebKit words it "Computed minimumFractionDigits is larger than
 * maximumFractionDigits"), and it rejects any count outside its accepted
 * window outright. Every formatter in this codebase runs inside a React render
 * path, so that throw does not degrade one cell — it unmounts the page. That
 * is issue #391, reported from /match-elements.
 *
 * This module exists because the same bug then turned up in a second module.
 * `money.ts` was fixed first, `numberFormat.ts` had an identical inverted-pair
 * hole reached by a different set of defaults, and two divergent copies of the
 * clamping rule is precisely how the first one survived long enough to be
 * reported. One implementation, two callers, one set of tests.
 *
 * What the callers keep for themselves is the *default* — what to use when the
 * caller expressed no opinion. `money.ts` defaults to a point (the currency's
 * own minor units, so minimum equals maximum), `numberFormat.ts` to a range
 * (`[0, 2]`, meaning "up to two digits, trailing zeros trimmed"). Those are
 * genuinely different policies and are passed in rather than assumed here.
 */

/** Fraction-digit overrides, matching the `Intl.NumberFormatOptions` names. */
export interface FractionDigitOptions {
  minimumFractionDigits?: number;
  maximumFractionDigits?: number;
}

/** A pair guaranteed to satisfy `minimum <= maximum`, both within range. */
export interface ResolvedFractionDigits {
  minimumFractionDigits: number;
  maximumFractionDigits: number;
}

/**
 * The fraction-digit window that every engine we ship to accepts.
 *
 * ES2023 widened the ceiling to 100, but the pre-2023 limit of 20 is what
 * older WebKit builds still enforce, so we clamp to the intersection rather
 * than to whichever limit the engine running this happens to have.
 */
const MIN_FRACTION_DIGITS = 0;
const MAX_FRACTION_DIGITS = 20;

/**
 * Coerce one caller-supplied digit count into the range `Intl` accepts.
 *
 * `undefined` and non-finite values both mean "the caller has no opinion":
 * `Infinity` and `NaN` are not digit counts, and silently reading them as 0
 * would be a worse answer than falling back to the caller's own default.
 * A finite but out-of-range count (negative, 101…) is a caller bug, and
 * clamping it degrades one number instead of throwing out of a render.
 */
export function sanitizeFractionDigits(value: number | undefined): number | undefined {
  if (value === undefined || !Number.isFinite(value)) return undefined;
  return Math.min(Math.max(Math.trunc(value), MIN_FRACTION_DIGITS), MAX_FRACTION_DIGITS);
}

/**
 * Build a `(minimum, maximum)` pair that satisfies `minimum <= maximum`.
 *
 * This is the ES2023 `SetNumberFormatDigitOptions` clamping done locally, so
 * the outcome no longer depends on the engine having implemented it. Engines
 * that predate the rule throw `RangeError` for a one-sided override that
 * crosses the default at the other end — a whole-money
 * `maximumFractionDigits: 0` summary card against a two-decimal currency, for
 * instance. Doing it ourselves also means a formatter that passes *both* ends
 * explicitly (as `numberFormat.ts` does) gets the same protection, which the
 * engine's own clamping never provides.
 *
 * - Neither end given: the caller's own defaults, untouched.
 * - Only a floor: the ceiling rises to meet it, so a caller asking for three
 *   digits against a two-digit default gets them instead of a `RangeError`.
 * - A ceiling given: it wins, and the floor drops to it. Rendering more digits
 *   than the call site declared as its maximum is the worse failure — those
 *   call sites are summary cards and chart axes sized for what they asked for.
 *
 * @param options Caller overrides; either end may be missing or nonsense.
 * @param defaults What to use for an end the caller left open. Must itself
 *   satisfy `minimum <= maximum` — it is the module's own policy, not input.
 */
export function resolveFractionDigits(
  options: FractionDigitOptions | undefined,
  defaults: { minimum: number; maximum: number },
): ResolvedFractionDigits {
  const min = sanitizeFractionDigits(options?.minimumFractionDigits);
  const max = sanitizeFractionDigits(options?.maximumFractionDigits);

  if (max === undefined) {
    const floor = min ?? defaults.minimum;
    return {
      minimumFractionDigits: floor,
      maximumFractionDigits: Math.max(floor, defaults.maximum),
    };
  }
  return {
    minimumFractionDigits: Math.min(min ?? defaults.minimum, max),
    maximumFractionDigits: max,
  };
}
