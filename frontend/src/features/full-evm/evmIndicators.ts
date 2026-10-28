// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * The pure decisions the Full EVM screen makes for itself.
 *
 * Everything else on the panel is the server's answer rendered as it came. The
 * register computes every EVM figure exactly, in Decimal, and persists it, so
 * nothing here recomputes SPI, CPI, EAC, ETC, VAC or TCPI. What is here is the
 * reading of those figures — which band an index falls in, which way a variance
 * points — plus the few derivations the API genuinely does not return: the
 * per-period amount hidden inside a cumulative curve, and how far the three EAC
 * formulas disagree with each other.
 *
 * Two rules run through all of it.
 *
 * **`null` is undefined, not zero.** The register stores NULL for an index
 * whose denominator was zero and the wire carries `null`. Zero is a different
 * and equally real answer: a CPI of 0 means money was spent and nothing was
 * earned. Collapsing the two reports a project that has not started as the
 * worst-performing one on the books.
 *
 * **Zero is an answer.** A variance of exactly 0 is a project exactly on plan,
 * and a completion of exactly 0 is a project that has earned nothing. Neither
 * is a missing value, so nothing here tests an amount for truthiness.
 *
 * They live apart from the panel deliberately: importing the panel pulls in the
 * shared UI barrel, which transitively boots i18next with the whole English
 * resource, and a vitest worker that does that never answers. The type imports
 * below are erased at compile time, so this module has no runtime dependency on
 * anything — which also means nothing here may return a user-facing string.
 * Bands and tones come back as keys the caller translates.
 */

import type { BaselinePeriod, Measure, SCurvePoint } from './api';

/**
 * Half-width of the band around 1.0 that still reads as "on track".
 *
 * The register stores indices to six decimal places, so a project running
 * dead-on plan lands on 0.999xxx as often as on 1.000000, and a badge that
 * flipped between "behind" and "on track" on that wobble would be noise. Equal
 * to the epsilon in features/schedule/evm.ts on purpose: the 4D schedule panel
 * and this register report the same kind of index for the same project, and two
 * screens that disagree about what 0.998 means is worse than either threshold.
 */
export const INDEX_EPSILON = 0.005;

/**
 * How an amount or an index arrives: a plain-decimal string, or `null`.
 *
 * Both money and indices are serialised as strings so a JavaScript client
 * cannot silently round a budget, and `null` survives the trip to mean
 * undefined.
 */
export type WireFigure = string | null | undefined;

/**
 * Parse a wire figure to a finite number, keeping "undefined" distinguishable.
 *
 * Returns `null` for `null`, `undefined`, blank, and anything that does not
 * parse to a finite number. Returns `0` for `"0"`, and the difference between
 * those two answers is the whole contract of this module. Deliberately not
 * `toNum` from shared/lib/money: that one degrades null to 0, which is right
 * for a total and wrong for every index here.
 */
export function parseFigure(value: WireFigure): number | null {
  if (value === null || value === undefined) return null;
  const trimmed = value.trim();
  if (trimmed === '') return null;
  const parsed = Number(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

/* ── Performance indices ───────────────────────────────────────────────── */

/**
 * How a performance index reads.
 *
 * `undefined` is its own answer rather than a flavour of bad: it is what an
 * index says before there is anything to divide by, and the next action for it
 * is to record a measurement, not to recover a project.
 */
export type IndexBand = 'ahead' | 'on_track' | 'behind' | 'undefined';

/**
 * Band an SPI or CPI against the 1.0 baseline.
 *
 * Above 1.0 is ahead of schedule (SPI) or under budget (CPI); below is behind
 * or over. Exactly 1.0 is on track, and so is anything inside
 * {@link INDEX_EPSILON} of it.
 */
export function indexBand(value: WireFigure, epsilon: number = INDEX_EPSILON): IndexBand {
  const index = parseFigure(value);
  if (index === null) return 'undefined';
  if (index >= 1 + epsilon) return 'ahead';
  if (index <= 1 - epsilon) return 'behind';
  return 'on_track';
}

/** The palette the shared Badge speaks. */
export type Tone = 'neutral' | 'blue' | 'success' | 'warning' | 'error';

/**
 * How an index band is painted.
 *
 * An undefined index is neutral, not a warning. Nothing is wrong with a
 * project that has not spent anything yet, and colouring it amber trains
 * readers to ignore the colour.
 */
export function indexTone(band: IndexBand): Tone {
  switch (band) {
    case 'ahead':
      return 'success';
    case 'on_track':
      return 'blue';
    case 'behind':
      return 'warning';
    case 'undefined':
      return 'neutral';
  }
}

/**
 * Which way a money variance points.
 *
 * SV = EV - PV and CV = EV - AC, so for both a positive value is favourable and
 * a negative one is not. Zero is neither: it is a project exactly on plan, and
 * it is reported as such rather than folded into either side.
 *
 * A negative variance is `warning` and not `error`. It is an unfavourable
 * number, not a fault, and the module has no threshold that would tell a
 * one-unit overrun from a ruinous one without inventing it.
 */
export function varianceTone(value: WireFigure): Tone {
  const variance = parseFigure(value);
  if (variance === null) return 'neutral';
  if (variance > 0) return 'success';
  if (variance < 0) return 'warning';
  return 'neutral';
}

/* ── To Complete Performance Index ─────────────────────────────────────── */

/**
 * What a TCPI says once you know what the project has actually achieved.
 *
 * TCPI reads the opposite way to CPI: it is the cost efficiency the *remaining*
 * work has to reach to still hit a target, so a higher number is a harder ask.
 * Banding it against 1.0 alone would be meaningless — the question is whether
 * the remaining work must beat the efficiency the project has managed so far.
 *
 * `no_benchmark` is the honest answer while CPI is undefined: with nothing
 * spent there is no achieved efficiency to compare against, and calling that
 * `at_or_below_achieved` would vouch for a project on no evidence.
 */
export type TcpiOutlook = 'at_or_below_achieved' | 'above_achieved' | 'no_benchmark' | 'undefined';

/**
 * Compare a TCPI with the CPI the project has actually achieved.
 *
 * Both figures come from the register; this only reads them against each other,
 * which is a comparison the API does not make.
 */
export function tcpiOutlook(
  tcpi: WireFigure,
  cpi: WireFigure,
  epsilon: number = INDEX_EPSILON,
): TcpiOutlook {
  const required = parseFigure(tcpi);
  if (required === null) return 'undefined';
  const achieved = parseFigure(cpi);
  if (achieved === null) return 'no_benchmark';
  return required <= achieved + epsilon ? 'at_or_below_achieved' : 'above_achieved';
}

/** How a TCPI outlook is painted. */
export function tcpiTone(outlook: TcpiOutlook): Tone {
  switch (outlook) {
    case 'at_or_below_achieved':
      return 'success';
    case 'above_achieved':
      return 'warning';
    case 'no_benchmark':
    case 'undefined':
      return 'neutral';
  }
}

/* ── Shares of the budget ──────────────────────────────────────────────── */

/**
 * Turn a fraction the register returns into a percentage.
 *
 * `percent_complete` and `percent_spent` are stored as fractions (EV/BAC and
 * AC/BAC), despite the names. Null stays null, and 0 stays 0.
 */
export function fractionToPercent(value: WireFigure): number | null {
  const fraction = parseFigure(value);
  return fraction === null ? null : fraction * 100;
}

/**
 * What share of the budget an amount represents, as a percentage.
 *
 * Returns `null` when the budget is zero or unparseable — a baseline with a
 * zero BAC is an ordinary state while a plan is being drafted, and dividing by
 * it yields Infinity, which renders as a confident and meaningless number. It
 * returns 0 for a zero amount against a real budget, because that is a fact.
 */
export function shareOfBudget(amount: WireFigure, bac: WireFigure): number | null {
  const total = parseFigure(bac);
  if (total === null || total === 0) return null;
  const part = parseFigure(amount);
  return part === null ? null : (part / total) * 100;
}

/* ── The planned-value curve ───────────────────────────────────────────── */

/** The shape this module needs from a curve point. */
export type CurvePointLike = Pick<BaselinePeriod, 'period_end' | 'planned_value'>;

/**
 * The amount planned *inside* each period, from a curve stored cumulatively.
 *
 * The register stores cumulative planned value because that is what an S-curve
 * plots and what a Planned Value at a data date is read off, but a reader
 * checking a spread wants the period's own amount. It is the only figure on
 * this screen the API does not carry, so it is derived here.
 *
 * The first period's increment is its whole value: a cumulative curve starts
 * from zero. A negative increment is returned as it is rather than clamped — a
 * cumulative total that goes down is a real data fault, which the rule
 * `full_evm.baseline_pv_monotonic` reports, and hiding it here would make the
 * screen disagree with the finding beside it. An unparseable value yields
 * `null` for its own increment and for the next one, because neither can be
 * known without it.
 */
export function periodIncrements(periods: CurvePointLike[]): (number | null)[] {
  let previous: number | null = 0;
  return periods.map((period) => {
    const cumulative = parseFigure(period.planned_value);
    const increment = cumulative === null || previous === null ? null : cumulative - previous;
    previous = cumulative;
    return increment;
  });
}

/**
 * How many plotted points carry no measurement.
 *
 * The server sends `null` for a period nobody reported, so this counts what it
 * said rather than deciding it. A high count against a curve that is well into
 * its life is the difference between a project with no progress and a project
 * nobody has measured, and those look identical on the chart alone.
 */
export function unmeasuredPoints(points: Pick<SCurvePoint, 'earned_value'>[]): number {
  return points.filter((point) => point.earned_value === null).length;
}

/* ── Measurements ──────────────────────────────────────────────────────── */

/**
 * The newest measurement in a list, or `null` for an empty one.
 *
 * The API returns measurements oldest first, but the newest is picked by
 * comparing `data_date` rather than by taking the last element, so a caller
 * that filtered or concatenated the list still gets the right row. ISO dates
 * sort lexicographically, so no Date is constructed and no timezone is dragged
 * into a reporting cutoff.
 */
export function latestMeasure<T extends Pick<Measure, 'data_date'>>(measures: T[]): T | null {
  let newest: T | null = null;
  for (const measure of measures) {
    if (newest === null || measure.data_date > newest.data_date) newest = measure;
  }
  return newest;
}

/**
 * How far apart the EAC formulas are for one measurement.
 *
 * The register computes every variant side by side because they disagree by
 * design: `remaining` assumes the overspend was a one-off, `cpi` assumes it
 * continues, `combined` assumes being late keeps pushing cost up. The spread
 * between them is how much the forecast depends on that choice, and it is not a
 * figure the API returns.
 *
 * Returns `null` when fewer than two variants are computable. One variant is
 * not the formulas agreeing — it is the others having no inputs — and reporting
 * a spread of zero there would claim a consensus that was never taken.
 */
export function eacVariantSpread(
  variants: Record<string, string | null> | undefined,
): { low: number; high: number; spread: number } | null {
  const values: number[] = [];
  for (const value of Object.values(variants ?? {})) {
    const parsed = parseFigure(value);
    if (parsed !== null) values.push(parsed);
  }
  if (values.length < 2) return null;
  const low = Math.min(...values);
  const high = Math.max(...values);
  return { low, high, spread: high - low };
}

/**
 * Did the EAC formula the caller asked for actually run?
 *
 * `false` means a divisor was zero and the register fell back to a simpler
 * formula, which is the normal state of a project that has earned nothing yet.
 * The two names are kept apart on the row precisely so this can be said out
 * loud instead of the screen implying the requested formula produced the
 * number. `auto` asks for whatever is richest, so it is never a substitution.
 */
export function eacMethodWasHonoured(measure: Pick<Measure, 'eac_method' | 'eac_method_effective'>): boolean {
  return measure.eac_method === 'auto' || measure.eac_method === measure.eac_method_effective;
}

/* ── Baseline status ───────────────────────────────────────────────────── */

/** How a baseline's lifecycle state is painted. */
export function baselineStatusTone(status: string): Tone {
  switch (status) {
    case 'approved':
      return 'success';
    case 'draft':
      return 'blue';
    case 'superseded':
      return 'neutral';
    case 'archived':
      return 'neutral';
    default:
      // A status a later version writes. Neutral rather than a guess.
      return 'neutral';
  }
}

/**
 * How the outcome of the last rule-set run is painted.
 *
 * `pending` means the row has never been validated and `unsupported` means the
 * rule set resolved to no rules at all. Neither is a pass, and neither is a
 * failure, so both stay neutral rather than borrowing the colour of one.
 */
export function validationTone(status: string): Tone {
  switch (status) {
    case 'passed':
      return 'success';
    case 'warnings':
      return 'warning';
    case 'errors':
      return 'error';
    case 'info':
      return 'blue';
    default:
      return 'neutral';
  }
}

/**
 * Can this baseline be approved as things stand?
 *
 * Mirrors the gate in `service.approve_baseline`: an already-approved baseline
 * is refused, and so is one whose last run found blocking errors. The server
 * re-runs the rules before it decides, so this is the button's reading and not
 * the authority — a stale `errors` on a row that has since been fixed still
 * disables the button until the row is re-validated, which is why the screen
 * offers "check again" beside it.
 */
export function canApprove(baseline: { status: string; validation_status: string }): boolean {
  return baseline.status !== 'approved' && baseline.validation_status !== 'errors';
}
