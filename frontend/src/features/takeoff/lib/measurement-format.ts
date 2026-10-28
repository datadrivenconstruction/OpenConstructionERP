import { getNumberLocale } from '@/stores/usePreferencesStore';

/**​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
 * Shared locale-aware digit rendering for takeoff quantity readouts
 * (audit case-2 K-12 follow-up).
 *
 * The same precision ladder used to live as four independent `toFixed`
 * copies (measurement ledger, legend group totals, RFI prefill, scale
 * badge). Localising only two of them put both decimal separators into a
 * single frame: legend totals read "485.3" directly above the "248,5"
 * rows they sum. Every on-screen quantity must render through this module
 * so the next copy cannot drift; CSV/GAEB exports intentionally stay on
 * `toFixed` (fixed machine format is documented there).
 *
 * Formatters are cached per locale+shape because the viewer formats every
 * label on every canvas redraw.
 *
 * The locale is the reader's number preference, not the interface language.
 * These used to fall back to `i18n.language`, which meant a person reading the
 * app in English and formatting numbers the German way got "485.3" on the
 * canvas and "485,3" everywhere else, which is the exact frame this module was
 * written to stop. The preference resolver answers the language when the
 * preference is `auto`, so the old behaviour is still reachable by choosing it
 * rather than by being the only thing on offer. The snapshot reader is the
 * right one here: these are plain functions called from a canvas redraw, not
 * components, and the viewer repaints them from above.
 */
const _formats = new Map<string, Intl.NumberFormat>();

function cachedFormat(locale: string, key: string, opts: Intl.NumberFormatOptions): Intl.NumberFormat {
  const cacheKey = `${locale}|${key}`;
  let fmt = _formats.get(cacheKey);
  if (!fmt) {
    fmt = new Intl.NumberFormat(locale, opts);
    _formats.set(cacheKey, fmt);
  }
  return fmt;
}

/** Render with a fixed number of fraction digits (locale-aware `toFixed`). */
export function formatFixedDigits(value: number, digits: number, locale?: string): string {
  const loc = locale || getNumberLocale();
  return cachedFormat(loc, `f${digits}`, {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(value);
}

/** Render with a fixed number of significant digits (for sub-millimetre
 *  readouts where fraction digits would collapse to zero). */
export function formatSignificantDigits(value: number, digits: number, locale?: string): string {
  const loc = locale || getNumberLocale();
  return cachedFormat(loc, `s${digits}`, {
    minimumSignificantDigits: digits,
    maximumSignificantDigits: digits,
  }).format(value);
}

/** The ledger precision ladder: 3 decimals under 1, 2 under 100, 1 above.
 *  Shared by the ledger, legend totals and RFI prefill so a group total
 *  and the rows it sums follow one rule. */
export function quantityDigits(value: number): number {
  const abs = Math.abs(value);
  if (abs < 1) return 3;
  if (abs < 100) return 2;
  return 1;
}

/** Ledger-ladder quantity in the reader's number format (or an explicit
 *  locale, which is what a caller formatting for somebody else passes).
 *  Zero renders as a bare "0" (not "0.000"): the ledger and the RFI
 *  prefill both showed it that way before the ladder was shared. */
export function formatQuantity(value: number, locale?: string): string {
  if (!Number.isFinite(value) || value === 0) return '0';
  return formatFixedDigits(value, quantityDigits(value), locale);
}

/** Count quantities are whole pieces: no decimal ladder, locale grouping
 *  only ("17", never "17,00"). Shared by every surface that prints a
 *  count-type measurement (K-14) so pieces cannot regain a fraction on
 *  one surface while another renders them whole. */
export function formatCountQuantity(value: number, locale?: string): string {
  if (!Number.isFinite(value)) return '0';
  return formatFixedDigits(value, 0, locale);
}

/** Render with UP TO `maxDigits` fraction digits: whole numbers stay
 *  whole ("2740"), fractions keep their precision ("2,74" in de). For
 *  echoing back a user-entered number in the user's locale (K-15: the
 *  calibration toast printed the raw JS number). */
export function formatMaxDigits(value: number, maxDigits: number, locale?: string): string {
  const loc = locale || getNumberLocale();
  return cachedFormat(loc, `m${maxDigits}`, {
    maximumFractionDigits: maxDigits,
  }).format(value);
}
