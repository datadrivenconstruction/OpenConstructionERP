// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * One duration formatter for the whole frontend (#174).
 *
 * Money and areas already go through shared primitives; durations did not.
 * Five screens each carried their own arithmetic and only two of them picked
 * a unit at the scale of the value, which is how a phone log printed a
 * two-hour call as "120m" and how a meeting agenda printed a full day as
 * "480 min".
 *
 * Two things this helper insists on, both learned from the copies it
 * replaces:
 *
 * 1. **The input unit is explicit.** The five call sites variously passed
 *    seconds, minutes and milliseconds. A helper with an implicit unit would
 *    have been wrong by a factor of sixty at four of them, silently, and the
 *    build would not have said a word.
 * 2. **The suffixes come from i18n.** "5m" is English. Every copy replaced
 *    here hardcoded its abbreviations, so a Japanese user read "5m" too. The
 *    ``defaultValue`` on each key is the abbreviation those copies used, so
 *    English is unchanged today and every other locale improves the moment
 *    the ``duration.*`` keys are translated.
 *
 * Not ``Intl.NumberFormat(…, { style: 'unit' })``: at ``unitDisplay:
 * 'narrow'`` English renders both *minute* and *month* as "5m", and at
 * 'short' it renders "5 mths" / "5 days", which is wider than the pills and
 * chips these strings sit in. A translated key per unit is the smaller and
 * more honest instrument.
 *
 * Interpolation uses ``{{value}}`` rather than i18next's ``{{count}}``
 * deliberately: ``count`` switches on the CLDR plural category, which would
 * oblige all 29 locales to carry a plural family for what is an
 * unpluralised unit symbol in most of them.
 */

/**
 * Minimal shape of the i18next `t` used here (repo convention).
 *
 * One signature covering every key below: each takes a ``defaultValue`` plus
 * the interpolations that key needs, which are numbers for the unit keys and
 * strings for the two that compose already-formatted fragments.
 */
export type Translate = (
  key: string,
  opts: { defaultValue: string; [param: string]: string | number },
) => string;

/** The unit the caller's number is already in. Always state it. */
export type DurationUnit = 'ms' | 's' | 'min' | 'h' | 'd';

const SECONDS_PER: Record<DurationUnit, number> = {
  ms: 1 / 1000,
  s: 1,
  min: 60,
  h: 3600,
  d: 86400,
};

/**
 * A month is 30 days here. Calendar months are not a fixed length, so any
 * duration expressed in months is an approximation; this is the same 30-day
 * month the BOQ activity panel has always used, kept so its output does not
 * shift under the consolidation.
 */
const SECONDS_PER_MONTH = 30 * 86400;

interface Step {
  /** Upper bound in seconds, exclusive. Above the last step we use months. */
  limit: number;
  seconds: number;
  key: string;
  short: string;
}

/**
 * Unit ladder, smallest first. A duration renders in the largest unit that
 * still yields a whole value of at least one.
 */
const LADDER: Step[] = [
  { limit: 60, seconds: 1, key: 'duration.secs', short: '{{value}}s' },
  { limit: 3600, seconds: 60, key: 'duration.mins', short: '{{value}}m' },
  { limit: 86400, seconds: 3600, key: 'duration.hours', short: '{{value}}h' },
  { limit: SECONDS_PER_MONTH, seconds: 86400, key: 'duration.days', short: '{{value}}d' },
  { limit: Infinity, seconds: SECONDS_PER_MONTH, key: 'duration.months', short: '{{value}}mo' },
];

export interface FormatDurationOptions {
  /**
   * ``1`` renders one unit ("2h"). ``2`` appends the next-smaller unit when
   * it is non-zero ("2h 5m"), which is what a call log or a live elapsed
   * counter wants and what a coarse "how old is this" label does not.
   * Default 1.
   */
  parts?: 1 | 2;
  /**
   * Rendered for a missing, non-finite or non-positive input. Default ``''``.
   * The phone log passes ``'-'`` because a blank cell in a table reads as a
   * rendering fault rather than as "no call".
   */
  empty?: string;
}

/** Split ``seconds`` into a major unit and, optionally, the next one down. */
function pick(seconds: number): { step: Step; value: number; rest: number } {
  const step = LADDER.find((s) => seconds < s.limit) ?? LADDER[LADDER.length - 1]!;
  const value = Math.floor(seconds / step.seconds);
  return { step, value, rest: seconds - value * step.seconds };
}

function render(t: Translate, step: Step, value: number): string {
  return t(step.key, { defaultValue: step.short, value });
}

/**
 * Format a duration at the scale of its value.
 *
 * ```ts
 * formatDuration(t, 45, 's')                  // "45s"
 * formatDuration(t, 7200, 's')                // "2h"      (was "120m")
 * formatDuration(t, 3700, 's', { parts: 2 })  // "1h 1m"
 * formatDuration(t, 480, 'min')               // "8h"      (was "480 min")
 * ```
 */
export function formatDuration(
  t: Translate,
  amount: number | null | undefined,
  unit: DurationUnit,
  options: FormatDurationOptions = {},
): string {
  const empty = options.empty ?? '';
  if (amount == null || !Number.isFinite(amount)) return empty;

  const seconds = Math.floor(amount * SECONDS_PER[unit]);
  if (seconds <= 0) return empty;

  const { step, value, rest } = pick(seconds);
  const major = render(t, step, value);

  if (options.parts !== 2) return major;

  // The next unit down, and only when it contributes something. "2h 0m" is
  // noise; "2h" is the same information.
  const index = LADDER.indexOf(step);
  const smaller = index > 0 ? LADDER[index - 1] : undefined;
  if (!smaller) return major;
  const minorValue = Math.floor(rest / smaller.seconds);
  if (minorValue <= 0) return major;

  return t('duration.pair', {
    defaultValue: '{{major}} {{minor}}',
    major,
    minor: render(t, smaller, minorValue),
  });
}

export interface FormatElapsedOptions extends FormatDurationOptions {
  /** Wrap the result as "… ago". Default false. */
  suffix?: boolean;
  /** Clock reading to measure against, in ms. Defaults to now; injectable for tests. */
  now?: number;
}

/**
 * Format how long ago something happened.
 *
 * Anything under a minute - including a timestamp in the future, which is
 * ordinary when a server clock runs ahead - reads "just now" rather than a
 * second count that changes while the user looks at it.
 *
 * ```ts
 * formatElapsed(t, iso)                     // "2m"
 * formatElapsed(t, iso, { suffix: true })   // "2m ago"
 * ```
 */
export function formatElapsed(
  t: Translate,
  since: string | number | Date | null | undefined,
  options: FormatElapsedOptions = {},
): string {
  const empty = options.empty ?? '';
  if (since == null) return empty;

  const then =
    since instanceof Date
      ? since.getTime()
      : typeof since === 'number'
        ? since
        : new Date(since).getTime();
  if (!Number.isFinite(then)) return empty;

  const elapsedSec = Math.floor(((options.now ?? Date.now()) - then) / 1000);
  if (elapsedSec < 60) {
    return t('duration.just_now', { defaultValue: 'just now' });
  }

  const body = formatDuration(t, elapsedSec, 's', {
    parts: options.parts,
    empty,
  });
  if (!options.suffix || body === empty) return body;

  return t('duration.ago', { defaultValue: '{{duration}} ago', duration: body });
}
