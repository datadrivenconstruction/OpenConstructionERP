// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pure decisions the FX screen makes for itself.
 *
 * They live apart from the panel deliberately. Importing the panel pulls in the
 * shared UI barrel, which transitively boots i18next with the whole English
 * resource, and a vitest worker that does that never answers. The type import
 * below is erased at compile time, so this module has no runtime dependency on
 * anything at all.
 *
 * Two rules govern everything here.
 *
 * **Nothing converts money.** When the backend has already priced something it
 * is rendered as it arrived. The only arithmetic below is on *rates* — asking
 * which direction a pair reads in, and how far apart two dates are — because
 * those are questions the screen has to answer about figures it was given, not
 * a second opinion on the figures themselves.
 *
 * **The screen must not vouch for more than the server will do.** Where a
 * helper looks stricter than it needs to be, that is why: `cross_rate` in the
 * service raises for a currency the applied set does not quote, including when
 * both sides of the pair are that same currency, so a screen that quietly
 * answered 1 would be promising a conversion the API refuses with a 422.
 */

import type { FxPolicy, FxValidation } from './api';
import { fmtFixed } from '@/shared/lib/formatters';

/**
 * Parse a plain-decimal string from the API.
 *
 * Returns null for absent, empty and unparsable values, and **zero for zero**.
 * Those are different answers: a rate of nothing is a quote somebody entered
 * wrongly, and no rate at all is a currency the set never covered. Folding them
 * together would file the first under the second and lose the only one anybody
 * can fix.
 */
export function parseDecimalString(value: string | null | undefined): number | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed)) return null;
  return parsed;
}

/**
 * Whole days between two ISO `YYYY-MM-DD` dates, `to` minus `from`.
 *
 * Both are read as UTC midnights. Parsing them as local dates would let a
 * browser west of Greenwich date a rate set a day earlier than the register
 * does, which is a discrepancy nobody could explain from the screen.
 */
export function daysBetween(from: string | null | undefined, to: string | null | undefined): number | null {
  const start = isoToUtcMillis(from);
  const end = isoToUtcMillis(to);
  if (start === null || end === null) return null;
  return Math.round((end - start) / 86_400_000);
}

function isoToUtcMillis(value: string | null | undefined): number | null {
  if (!value) return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value.trim());
  if (!match) return null;
  const millis = Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
  return Number.isFinite(millis) ? millis : null;
}

/**
 * How the rates behind a project read on a given day.
 *
 * `pinned` is a state rather than a modifier because the backend treats it as
 * one: `fx.rate_freshness` returns nothing at all for a pinned project, since
 * holding old rates is the entire point of pinning and warning about it would
 * train people to ignore the light.
 */
export type RateFreshness = 'unknown' | 'pinned' | 'future' | 'current' | 'stale';

/**
 * Judge a rate set's age against the tolerance the project set for itself.
 *
 * Mirrors `FxRateFreshness` in the module's validators: the comparison is
 * `age <= tolerance`, so a tolerance of zero means the rates must carry the day
 * they are being judged on, and a set dated today passes it. Zero is a real
 * setting the schema accepts, not an unset one.
 */
export function rateFreshness(args: {
  rateDate: string | null | undefined;
  onDate: string | null | undefined;
  maxAgeDays: number;
  pinned?: boolean;
}): RateFreshness {
  if (args.pinned) return 'pinned';
  const age = daysBetween(args.rateDate, args.onDate);
  if (age === null) return 'unknown';
  if (age < 0) return 'future';
  return age <= args.maxAgeDays ? 'current' : 'stale';
}

/**
 * How a freshness state is painted.
 *
 * `future` is neutral rather than a warning: the backend passes it, and a rate
 * set published ahead of its effective date is ordinary in a contract. `pinned`
 * is blue because it is a decision somebody made, not a condition to fix.
 */
export function freshnessTone(state: RateFreshness): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  switch (state) {
    case 'stale':
      return 'warning';
    case 'current':
      return 'success';
    case 'pinned':
      return 'blue';
    case 'future':
    case 'unknown':
      return 'neutral';
  }
}

/**
 * How a set's provenance is painted.
 *
 * The bundled fallback earns a warning tone: it is a small offline snapshot
 * that ships with the product, and a project pricing against it is pricing
 * against rates that were never fetched for it.
 */
export function sourceTone(source: string): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  switch (source) {
    case 'seed':
      return 'warning';
    case 'manual':
      return 'blue';
    case 'ecb':
      return 'success';
    default:
      return 'neutral';
  }
}

/**
 * The rate of one currency inside a set: units of it per one base unit.
 *
 * The base is implicit at 1 and is never quoted in the set itself. A quote that
 * is missing, unparsable or not strictly positive comes back null, matching
 * `rate_of` in the service, which refuses to divide by any of the three.
 */
export function quotedRate(
  rates: Record<string, string>,
  baseCurrency: string,
  currency: string,
): number | null {
  const base = normaliseCurrency(baseCurrency);
  const code = normaliseCurrency(currency);
  if (code === '') return null;
  if (code === base) return 1;
  const parsed = parseDecimalString(rates[code]);
  if (parsed === null || parsed <= 0) return null;
  return parsed;
}

/** Uppercased, trimmed ISO 4217 code, or empty when it is not one. */
export function normaliseCurrency(code: string | null | undefined): string {
  const cleaned = (code ?? '').trim().toUpperCase();
  return /^[A-Z]{3}$/.test(cleaned) ? cleaned : '';
}

/**
 * Whether a set can price this pair at all.
 *
 * Both sides have to be quoted, or be the base. A pair where one side is a
 * currency the set never carried is the case the register reports honestly, and
 * a pair where one side is quoted at zero is a set somebody has to correct
 * before anything is priced with it.
 */
export function pairIsCovered(
  rates: Record<string, string>,
  baseCurrency: string,
  from: string,
  to: string,
): boolean {
  return quotedRate(rates, baseCurrency, from) !== null && quotedRate(rates, baseCurrency, to) !== null;
}

/**
 * Target units per one source unit, or null when the set cannot price the pair.
 *
 * The direction is the one the register stores in: every quote is units of that
 * currency per one *base*, so the cross rate is the target's quote over the
 * source's quote and never the other way round. Mirrors `cross_rate` in the
 * service, including its answer for a pair whose two sides are the same
 * currency: exactly 1 when the set quotes it, and null when it does not,
 * because the service raises there rather than short-circuiting.
 */
export function crossRate(
  rates: Record<string, string>,
  baseCurrency: string,
  from: string,
  to: string,
): number | null {
  const fromRate = quotedRate(rates, baseCurrency, from);
  const toRate = quotedRate(rates, baseCurrency, to);
  if (fromRate === null || toRate === null) return null;
  return toRate / fromRate;
}

/**
 * The other direction of a quoted pair: source units per one target unit.
 *
 * Null for a rate of zero, which has no inverse. Guarding that explicitly
 * matters because dividing by it in JavaScript yields Infinity rather than an
 * error, and Infinity formats into a screen as readily as a number does.
 *
 * Derived for display only. It is never sent back, and the exact figure stays
 * the string the register published.
 */
export function inverseRate(rate: string | number | null | undefined): number | null {
  const parsed = typeof rate === 'number' ? rate : parseDecimalString(rate);
  if (parsed === null || parsed === 0) return null;
  return 1 / parsed;
}

/**
 * Render a rate this screen worked out itself.
 *
 * Six decimals above one, twelve significant digits below it. The scale change
 * is the same one the backend makes and for the same reason: six decimals turn
 * an inverse rate of 0.0000363636 into 0.000036, which is a one percent error
 * on every figure it touches, and a construction budget is converted in both
 * directions.
 */
export function formatDerivedRate(value: number | null): string | null {
  if (value === null || !Number.isFinite(value)) return null;
  if (value === 0) return '0';
  const magnitude = Math.abs(value);
  const decimals = magnitude >= 1 ? 6 : Math.min(11 - Math.floor(Math.log10(magnitude)), 100);
  const rendered = fmtFixed(value, decimals);
  return rendered.includes('.') ? rendered.replace(/0+$/, '').replace(/\.$/, '') : rendered;
}

/**
 * How far the applied rates sit from the date that was asked for, in days.
 *
 * Positive means the rates predate the request: a set from before the date is
 * what a point-in-time lookup is supposed to return, but a set from three years
 * before it is not what anybody meant. The screen works this out itself because
 * `covers_requested_date` cannot report it — the lookup already filters to sets
 * on or before the date, so the flag it would raise is never raised.
 */
export function appliedDateGapDays(
  asOf: string | null | undefined,
  requestedDate: string | null | undefined,
): number | null {
  if (!requestedDate) return null;
  return daysBetween(asOf, requestedDate);
}

/** The three currencies a policy declares, in role order, without repeats. */
export function policyCurrencies(policy: FxPolicy): string[] {
  const ordered = [policy.estimating_currency, policy.procurement_currency, policy.reporting_currency];
  const seen: string[] = [];
  for (const raw of ordered) {
    const code = normaliseCurrency(raw);
    if (code !== '' && !seen.includes(code)) seen.push(code);
  }
  return seen;
}

/**
 * The project's own currencies that the applied rates cannot price.
 *
 * Mirrors `fx.policy_currency_coverage`, which is an ERROR in the rule set: a
 * project whose reporting currency is not quoted by the set backing it produces
 * figures that look finished and cannot be converted.
 */
export function uncoveredPolicyCurrencies(
  policy: FxPolicy,
  rates: Record<string, string>,
  baseCurrency: string,
): string[] {
  return policyCurrencies(policy).filter((code) => quotedRate(rates, baseCurrency, code) === null);
}

/**
 * What a validation report amounts to.
 *
 * `unchecked` is separate from `passed` on purpose. A project with no policy
 * makes every rule stay silent, and the report that comes back has no errors,
 * no warnings and nothing examined. Painting that green would let a project
 * bank a pass from checks that never ran, which is the one outcome the rule set
 * is written to refuse.
 */
export type ValidationVerdict = 'unchecked' | 'errors' | 'warnings' | 'passed';

export function validationVerdict(report: FxValidation | undefined): ValidationVerdict {
  if (!report || report.checked === 0) return 'unchecked';
  if (report.errors.length > 0) return 'errors';
  if (report.warnings.length > 0) return 'warnings';
  return 'passed';
}

/** How a verdict is painted. Only an examined project earns the success tone. */
export function verdictTone(verdict: ValidationVerdict): 'neutral' | 'blue' | 'success' | 'warning' | 'error' {
  switch (verdict) {
    case 'errors':
      return 'error';
    case 'warnings':
      return 'warning';
    case 'passed':
      return 'success';
    case 'unchecked':
      return 'neutral';
  }
}

/**
 * Whether a pin actually holds.
 *
 * Mirrors `fx.pinned_set_resolvable`. An unlocked pin is not a pin: the next
 * refresh can rewrite the set underneath it and the reproducible estimate
 * moves without anybody touching the project.
 */
export function pinHolds(policy: FxPolicy | undefined): boolean {
  if (!policy || policy.rate_mode !== 'pinned') return false;
  return policy.pinned_rate_set !== null && policy.pinned_rate_set.is_locked;
}
