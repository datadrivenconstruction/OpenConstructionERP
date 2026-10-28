// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pure decisions the tax withholding screen makes for itself.
 *
 * They live apart from the panel deliberately. Importing the panel pulls in
 * the shared UI barrel, which transitively boots i18next with the whole
 * English resource, and a vitest worker that does that never answers. The type
 * imports below are erased at compile time, so this module has no runtime
 * dependency on anything.
 */

import type { PartyStatus, RateBand, Regime } from './api';

/**
 * What a recorded standing amounts to today.
 *
 * The distinction the module exists for is between a standing that still holds
 * and one that stopped holding without anybody noticing, so the states below
 * are the ways it stops rather than a single "bad". Each carries a different
 * next action: a lapsed verification is renewed, a revoked one is obtained
 * again from scratch, and one with no reference on it was never a verification
 * in the first place.
 */
export type StandingState =
  | 'revoked'
  | 'lapsed'
  | 'unverified'
  | 'pending'
  | 'not_yet'
  | 'expiring'
  | 'current';

/**
 * Judge one standing as of `today`, treating anything ending inside
 * `withinDays` as expiring.
 *
 * Mirrors `service.verification_is_current` in the backend on purpose. The two
 * have to agree: a standing this file calls current, and the preview then
 * silently downgrades, is the surprise the module was written to prevent, only
 * now with the product's own screen vouching for it.
 *
 * `days_to_expiry` is the field to be careful with. The server computes it as
 * `(valid_to - as_of).days`, so it is **negative** once the window has closed
 * and **null** only for a standing with no end date at all. Zero means the
 * window closes today, which is a real answer and not a missing one — treating
 * it as falsy files "expires today" under "never expires".
 *
 * Dates are compared as ISO strings: they arrive as `YYYY-MM-DD`, which sorts
 * lexicographically, and parsing them into Date would drag the browser's
 * timezone into a statutory window.
 */
export function standingState(
  standing: PartyStatus,
  today: string,
  withinDays = 60,
): StandingState {
  // Revoked outranks lapsed. Both may be true of one row, but a withdrawal is
  // somebody's decision and time passing is not, so the decision is the news.
  if (standing.status === 'revoked') return 'revoked';
  if (standing.is_expired || standing.status === 'expired') return 'lapsed';
  // A standing marked active with no reference to the authority's own answer
  // is somebody's intention, not a verification, and the backend refuses it.
  if (!standing.verification_reference.trim()) return 'unverified';
  // Reported rather than folded into `current`. The backend does honour a
  // pending standing — `verification_is_current` refuses only revoked and
  // expired — so this changes no figure. It changes what the badge vouches
  // for: a green "Current" on a row somebody deliberately left pending is
  // this screen making a claim the record does not.
  if (standing.status === 'pending') return 'pending';
  if (standing.valid_from > today) return 'not_yet';
  if (standing.days_to_expiry !== null && standing.days_to_expiry <= withinDays) return 'expiring';
  return 'current';
}

/**
 * How a standing's state is painted.
 *
 * `not_yet` and `pending` are neutral rather than warnings: a verification
 * that starts next month, or one recorded but not yet confirmed, is not wrong.
 * Only `current` earns the success colour, because that is the one state this
 * screen is willing to vouch for.
 */
export function standingVariant(
  state: StandingState,
): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  switch (state) {
    case 'revoked':
    case 'lapsed':
      return 'error';
    case 'unverified':
    case 'expiring':
      return 'warning';
    case 'pending':
      return 'blue';
    case 'not_yet':
      return 'neutral';
    case 'current':
      return 'success';
  }
}

/** One band of a scheme by code, or null when the scheme defines no such band. */
export function findBand(regime: Regime | undefined, bandCode: string): RateBand | null {
  if (!regime || !bandCode) return null;
  return regime.bands.find((band) => band.code === bandCode) ?? null;
}

/**
 * The rate a picked band deducts at, as the plain-decimal string it arrived as.
 *
 * Null for a band the scheme does not define, and never zero for it. The
 * shipped schemes carry genuine zero-rate bands — Ireland's `ZERO`, Germany's
 * `EXEMPT`, the US `NONE` — so a `0` returned for "no such band" is
 * indistinguishable from a correct answer of no deduction at all.
 */
export function bandRate(regime: Regime | undefined, bandCode: string): string | null {
  return findBand(regime, bandCode)?.rate_pct ?? null;
}
