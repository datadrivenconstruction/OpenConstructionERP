// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Locale-aware number and date formatters.
 *
 * The language-to-locale mapping itself lives in `./intlLocale` and is
 * re-exported below, so this module stays the place to import a formatter from
 * while the locale question has a single answer of its own.
 *
 * NUMBERS AND DATES ASK DIFFERENT QUESTIONS, so they read different sources.
 *
 * A number is written the way the reader asked for it: `getNumberLocale()`,
 * which is the `numberLocale` preference and answers with the UI language only
 * while that preference is `'auto'`. Reading the language directly here would
 * be a formatter deciding to ignore a setting the user changed on purpose, and
 * a bill in one convention beside a dashboard in another is the bug this
 * module exists to prevent.
 *
 * A date keeps `getIntlLocale()`, the language, and that is not an oversight.
 * Dates have a preference of their own (`dateFormat`, applied below), and the
 * locale is there so the month reads "Aug" or "Aug." or "août" in the reader's
 * language. Pointing a number-format setting at a month name would answer a
 * question nobody asked.
 *
 * This module also hosts a small handful of file/number helpers that
 * are not AI-specific (`formatNumber`, `formatFileSize`,
 * `getFileExtension`) — they used to live inside AI feature files but
 * were lifted out so any feature can reuse them.
 */
import { getNumberLocale, usePreferencesStore, type DateFormat } from '@/stores/usePreferencesStore';
import { getIntlLocale } from './intlLocale';

// The language-to-locale map moved to `./intlLocale`, a leaf module the
// preferences store can import without closing a cycle back through this file.
// Re-exported here because this is where the rest of the app looks for it.
export { getIntlLocale, useIntlLocale } from './intlLocale';

/** Currency-style number formatter (e.g. 1,234.56) using current locale. */
export function fmtNumber(value: number | string | null | undefined, decimals = 2): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(safe);
}

/**
 * `toFixed` with the reader's separators, and nothing else changed.
 *
 * `(1234.5).toFixed(2)` is `1234.50` for everyone on earth: the method takes
 * no locale, always writes a point and never groups the thousands. There is no
 * argument that fixes it, so a visible number has to move onto a formatter,
 * and this is the one that moves without deciding anything else on the way.
 *
 * It exists next to `fmtNumber` rather than inside it because the two answer
 * different questions about a number that is not a number. `fmtNumber` takes
 * `string | null | undefined` off the wire and renders nonsense as zero, which
 * is right when the alternative is `NaN` in a total. Applied to a `toFixed`
 * call site it would be a quiet lie: `NaN.toFixed(2)` says `NaN` today, and a
 * sweep that turned every one of those into `0.00` would trade a formatting
 * bug for a costing bug and leave the screen looking confident about it. So a
 * non-finite value is handed back to `toFixed` and keeps the text it already
 * had; only finite numbers are localised.
 */
export function fmtFixed(value: number, decimals = 2): string {
  if (!Number.isFinite(value)) return value.toFixed(decimals);
  return new Intl.NumberFormat(getNumberLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(value);
}

/**
 * A number written for a field a person is still editing, not for reading.
 *
 * `fmtFixed` and every other formatter in this module answer "how does this
 * reader write a number", and the answer is a separator. That is right on a
 * screen and wrong inside a control: `<input type="number">` accepts exactly
 * one spelling, digits with a point, and silently empties itself when handed
 * anything else. Issue #466 was a total that vanished from a thousand upwards
 * because it had been grouped, and the same grouped string was what the form
 * read back when it built the request, so `parseFloat` truncated the invoice
 * at the separator. Under a comma-decimal reader the same call dropped the
 * cents off every amount at any size.
 *
 * So an editable number stays in the canonical form, which has no locale and
 * therefore cannot be right for one convention and wrong for the other. Where
 * the same figure also has to be read, that is a second, read-only element
 * formatted by the functions above.
 *
 * A non-finite value comes back as an empty field rather than as the text
 * `NaN`, which is the one place this parts company with `fmtFixed`: there is
 * no editing a NaN, the control empties itself on it anyway, and a blank field
 * says "nothing here yet" where `NaN` says the software is confused. Still no
 * invented zero, for the reason `fmtFixed` gives.
 */
export function fmtNumberForInput(value: number, decimals = 2): string {
  return Number.isFinite(value) ? value.toFixed(decimals) : '';
}

/**
 * `toPrecision` with the reader's separators: a count of significant digits
 * rather than of decimal places.
 *
 * Used where a quantity can be very small and a fixed number of decimals would
 * round it away, so `0.0012` has to keep its two digits while `1234` keeps
 * four. Like `fmtFixed`, a non-finite value is handed back to the method it
 * replaces rather than being invented into a zero.
 */
export function fmtPrecision(value: number, digits: number): string {
  if (!Number.isFinite(value)) return value.toPrecision(digits);
  return new Intl.NumberFormat(getNumberLocale(), {
    maximumSignificantDigits: digits,
    minimumSignificantDigits: Math.min(digits, 2),
  }).format(value);
}

/**
 * A percentage that is already on a 0-100 scale, written the way the reader's
 * language writes one.
 *
 * `${n.toFixed(1)}%` is the shape this replaces, and it is wrong twice over
 * outside English: the separator is a point where most of Europe writes a
 * comma, so 68.3 reads as a number in the tens of thousands, and the sign
 * goes before the digits in Turkish. Both belong to the locale data, not to
 * the call site.
 *
 * The value is divided by 100 because the engine's percent style multiplies
 * it back; the digit count still refers to the percentage as displayed.
 */
export function fmtPercent(value: number | string | null | undefined, decimals = 1): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(getNumberLocale(), {
    style: 'percent',
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(safe / 100);
}

/** Compact number formatter (e.g. 1.2M) using current locale. */
export function fmtCompact(value: number | string | null | undefined): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(getNumberLocale(), {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(safe);
}

/**
 * "A, B and C" written the way the reader's language writes a list.
 *
 * The separator between list items is part of the sentence, not punctuation
 * the code gets to choose: Japanese and Chinese enumerate with U+3001, Arabic
 * with U+060C, and a Latin comma in those languages is as wrong as a Latin
 * decimal point in German. `items.join(', ')` writes one language's separator
 * for every reader, and no argument to `join` fixes that - the call has to
 * move onto a formatter, exactly as `toFixed` did.
 *
 * This reads `getIntlLocale()`, the language, and deliberately not
 * `getNumberLocale()`. A reader who set the number preference to a different
 * convention was answering a question about digits; the comma between two
 * module names is a fact about the sentence they are reading.
 *
 * The two modes are named for what the caller means, not for Intl's two axes,
 * because the axis names mislead and the wrong pick is worse than the defect.
 * `'list'` is a bare enumeration after a label ("Modules: A, B, C"); `'prose'`
 * is a phrase inside a sentence ("written for A, B and C").
 *
 * Do NOT reach for Intl's `type: 'unit'` for an enumeration, whatever its name
 * suggests. In CLDR that type is a list of MEASUREMENTS - "3 ft 7 in" - so it
 * joins with a space in Japanese, Korean and Russian and with nothing at all
 * in Chinese. Measured: `['A','B','C']` comes back "ABC" in zh. That is not a
 * milder version of the Latin-comma bug, it is a worse one. `'narrow'` plus
 * `'conjunction'` is the combination that yields a real separator everywhere,
 * and it happens to be byte-identical to the old `join(', ')` in English and
 * Russian, so it changes only the languages that were being written wrongly.
 *
 * The catch path is not a fallback to English by choice: it runs only once
 * Intl has already refused the locale, and asking it the same question again
 * would not be a fix.
 */
export function fmtList(items: readonly string[], mode: 'list' | 'prose' = 'list'): string {
  const parts = items.filter((s) => s && s.trim().length > 0);
  if (parts.length === 0) return '';
  if (parts.length === 1) return parts[0] ?? '';
  try {
    return new Intl.ListFormat(getIntlLocale(), {
      style: mode === 'prose' ? 'long' : 'narrow',
      type: 'conjunction',
    }).format(parts);
  } catch {
    return parts.join(', ');
  }
}

/**
 * Currency formatter using current locale.
 *
 * When ``currency`` is empty / null / not a valid ISO 4217 code, falls
 * back to a plain number with no currency symbol — preferable to the
 * historical "default EUR" because rendering ``1,234,567 EUR`` on a
 * USD/BRL/JPY project is actively wrong (lies to the operator about
 * the unit). A bare formatted number is honest: "we don't know the
 * currency for this value, ask before relying on it".
 *
 * Callers that genuinely want a EUR fallback (legacy LanceDB rows
 * that pre-date currency stamping) can still pass ``"EUR"`` explicitly.
 */
export function fmtCurrency(value: number | string | null | undefined, currency?: string | null): string {
  // Defence-in-depth against the project-wide Decimal-as-string money
  // contract leaking past TypeScript: coerce here so `.toFixed` in the
  // catch path can never crash, and so Intl.NumberFormat never sees a
  // string it might surprise-format.
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  const trimmed = (currency || '').trim().toUpperCase();
  const isValid = /^[A-Z]{3}$/.test(trimmed);
  if (!isValid) {
    // No currency known — render the number with locale grouping but
    // without a currency symbol. Prevents the EUR-on-USD-project bug.
    return new Intl.NumberFormat(getNumberLocale(), {
      maximumFractionDigits: 0,
    }).format(safe);
  }
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: 'currency',
      currency: trimmed,
      maximumFractionDigits: 0,
    }).format(safe);
  } catch {
    return `${safe.toFixed(0)} ${trimmed}`;
  }
}

// ---------------------------------------------------------------------------
// Date-format preference (Settings → Regional → Date Format)
//
// The preference selects the ORDER and SEPARATOR of the day/month/year fields
// and forces them numeric. It deliberately does not touch the calendar, the
// numbering system, the time zone or the time fields: those follow the UI
// language, exactly as they did before the preference was wired up. An Arabic
// user who asks for MM/DD/YYYY keeps Arabic-Indic digits and the Islamic
// calendar, only reordered.
//
// `'auto'` is the default and means "follow the UI language". It runs the
// original, language-derived code path untouched, so an account that never
// chose a format renders byte for byte as it did before.
// ---------------------------------------------------------------------------

const DATE_FIELD_TYPES: ReadonlySet<string> = new Set(['day', 'month', 'year']);

/** The all-numeric day/month/year every explicit preference implies. */
const NUMERIC_DATE_FIELDS: Intl.DateTimeFormatOptions = {
  day: '2-digit',
  month: '2-digit',
  year: 'numeric',
};

function joinByPreference(
  day: string,
  month: string,
  year: string,
  pref: Exclude<DateFormat, 'auto'>,
): string {
  switch (pref) {
    case 'MM/DD/YYYY':
      return `${month}/${day}/${year}`;
    case 'YYYY-MM-DD':
      return `${year}-${month}-${day}`;
    case 'DD.MM.YYYY':
    default:
      return `${day}.${month}.${year}`;
  }
}

/**
 * Format `date` in `locale` with `options`, applying the date-format
 * preference `pref`.
 *
 * Under `'auto'` this is `Intl.DateTimeFormat(locale, options).format(date)`
 * and nothing else — the equivalence the unset default depends on.
 *
 * Under an explicit preference the day/month/year fields are re-emitted in the
 * requested order, and everything the locale produced around them (the time,
 * the date/time connector, era markers, RTL marks) is kept verbatim. Options
 * that do not ask for a full date — a time-only cell, a month/year header —
 * have no field order to rewrite and stay with the language.
 *
 * One nuance of re-emitting through `formatToParts`: on some ICU builds it
 * disagrees with `format()` about invisible separators (Node 24 / ICU 78 puts
 * a narrow no-break space before the en-US day period where `format()` puts an
 * ordinary space). Only a surface with an explicit preference takes this path,
 * so the difference cannot reach the default rendering, but a caller matching
 * on the exact whitespace of a time should know it exists.
 */
export function formatDateWithPreference(
  date: Date,
  locale: string | undefined,
  options: Intl.DateTimeFormatOptions,
  pref: DateFormat,
): string {
  if (pref === 'auto' || !options.day || !options.month || !options.year) {
    return new Intl.DateTimeFormat(locale, options).format(date);
  }
  const parts = new Intl.DateTimeFormat(locale, { ...options, ...NUMERIC_DATE_FIELDS }).formatToParts(date);
  const first = parts.findIndex((p) => DATE_FIELD_TYPES.has(p.type));
  if (first < 0) return new Intl.DateTimeFormat(locale, options).format(date);
  let last = first;
  for (let i = parts.length - 1; i > first; i--) {
    if (DATE_FIELD_TYPES.has(parts[i]!.type)) {
      last = i;
      break;
    }
  }
  const pick = (type: string) => parts.find((p) => p.type === type)?.value ?? '';
  return [
    ...parts.slice(0, first).map((p) => p.value),
    joinByPreference(pick('day'), pick('month'), pick('year'), pref),
    ...parts.slice(last + 1).map((p) => p.value),
  ].join('');
}

/**
 * The date format the user chose, or `'auto'` when they never chose one.
 *
 * Read through `getState()` rather than the hook so plain formatters can use
 * it; React surfaces should subscribe with `usePreferencesStore` so a change
 * in Settings repaints the page that is already open.
 */
export function getDateFormatPreference(): DateFormat {
  return usePreferencesStore.getState().dateFormat;
}

/** Date formatter using current locale and the user's date-format preference. */
export function fmtDate(dateStr: string, options?: Intl.DateTimeFormatOptions): string {
  const defaults: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  };
  const opts = options || defaults;
  // A date-only string (YYYY-MM-DD) is parsed by `new Date()` as UTC
  // midnight, so rendering it in the browser's local zone shifts it a day
  // back at negative UTC offsets (a diary date of 2026-07-01 shows as
  // 2026-06-30 in UTC-6). Pin date-only values to UTC so the calendar day
  // is preserved; full timestamps keep their local-zone rendering.
  const isDateOnly = /^\d{4}-\d{2}-\d{2}$/.test(dateStr);
  const finalOpts = isDateOnly && !opts.timeZone ? { ...opts, timeZone: 'UTC' } : opts;
  const pref = getDateFormatPreference();
  if (pref === 'auto') {
    return new Date(dateStr).toLocaleDateString(getIntlLocale(), finalOpts);
  }
  return formatDateWithPreference(new Date(dateStr), getIntlLocale(), finalOpts, pref);
}

// ---------------------------------------------------------------------------
// Wave 24 — unit-system formatters (metric / imperial)
//
// Each formatter accepts a base SI value (m, m², m³, kg, °C), a unit system,
// and an explicit locale (test-friendly — no i18next runtime dependency).
// Returns '—' for null / undefined / NaN.
// ---------------------------------------------------------------------------

export type UnitSystem = 'metric' | 'imperial';

const EM_DASH = '—';

function _fmtUnit(
  value: number | null | undefined,
  locale: string,
  unit: string,
  decimals = 2,
): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return EM_DASH;
  const num = new Intl.NumberFormat(locale, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: Math.max(decimals, 4),
  }).format(value);
  return `${num} ${unit}`;
}

/** Area (base unit: m²). Imperial → sqft (× 10.7639). */
export function formatArea(
  value: number | null | undefined,
  system: UnitSystem,
  locale: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value as number)) return EM_DASH;
  return system === 'imperial'
    ? _fmtUnit((value as number) * 10.7639, locale, 'sqft')
    : _fmtUnit(value as number, locale, 'm²');
}

/** Length (base unit: m). Imperial → ft (× 3.28084). */
export function formatLength(
  value: number | null | undefined,
  system: UnitSystem,
  locale: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value as number)) return EM_DASH;
  return system === 'imperial'
    ? _fmtUnit((value as number) * 3.28084, locale, 'ft')
    : _fmtUnit(value as number, locale, 'm');
}

/** Volume (base unit: m³). Imperial → ft³ (× 35.3147). */
export function formatVolume(
  value: number | null | undefined,
  system: UnitSystem,
  locale: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value as number)) return EM_DASH;
  return system === 'imperial'
    ? _fmtUnit((value as number) * 35.3147, locale, 'ft³')
    : _fmtUnit(value as number, locale, 'm³');
}

/** Weight (base unit: kg). Imperial → lb (× 2.20462). */
export function formatWeight(
  value: number | null | undefined,
  system: UnitSystem,
  locale: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value as number)) return EM_DASH;
  return system === 'imperial'
    ? _fmtUnit((value as number) * 2.20462, locale, 'lb')
    : _fmtUnit(value as number, locale, 'kg');
}

/** Temperature (base unit: °C). Imperial → °F (× 9/5 + 32). */
export function formatTemperature(
  value: number | null | undefined,
  system: UnitSystem,
  locale: string,
): string {
  if (value === null || value === undefined || !Number.isFinite(value as number)) return EM_DASH;
  return system === 'imperial'
    ? _fmtUnit((value as number) * 9 / 5 + 32, locale, '°F')
    : _fmtUnit(value as number, locale, '°C');
}

// ---------------------------------------------------------------------------
// File / generic-number helpers — lifted from per-feature files so any
// surface (AI, takeoff, tendering, …) can share them. None of these are
// AI-specific; the function names follow the existing
// `format*` / `get*` conventions used elsewhere in this module.
// ---------------------------------------------------------------------------

/**
 * Locale-aware number formatter with optional currency style.
 *
 * - When ``currency`` is omitted (or empty), renders as a plain
 *   decimal with grouping (e.g. ``1,234.5``).
 * - When ``currency`` is a valid ISO 4217 code, renders with the
 *   matching symbol (``$1,234.50``, ``€1.234,50``).
 * - On any Intl error, falls back to ``n.toLocaleString()`` so calls
 *   never throw.
 *
 * @param n The numeric value.
 * @param currency Optional ISO 4217 currency code.
 */
export function formatNumber(n: number, currency?: string): string {
  try {
    return new Intl.NumberFormat(getNumberLocale(), {
      style: currency ? 'currency' : 'decimal',
      currency: currency || undefined,
      minimumFractionDigits: 0,
      maximumFractionDigits: 2,
    }).format(n);
  } catch {
    return n.toLocaleString();
  }
}

/**
 * Human-readable byte size — short form (``523 B`` / ``12.4 KB`` /
 * ``3.1 MB``). Always returns 1 decimal place above 1 KiB so file
 * lists line up visually.
 *
 * Uses binary 1024 units (KB/MB) to match what users see in OS file
 * managers; callers showing wire-bytes should use the SI variant
 * elsewhere.
 */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${fmtFixed(bytes / 1024, 1)} KB`;
  return `${fmtFixed(bytes / (1024 * 1024), 1)} MB`;
}

/**
 * Extract the (lowercased) file extension from a name.
 *
 * - ``"foo.pdf"`` → ``"pdf"``
 * - ``"FILE.PDF"`` → ``"pdf"``
 * - ``"archive.tar.gz"`` → ``"gz"``  (returns only the final segment)
 * - ``"noext"`` → ``""``
 */
export function getFileExtension(name: string): string {
  const dot = name.lastIndexOf('.');
  return dot >= 0 ? name.slice(dot + 1).toLowerCase() : '';
}
