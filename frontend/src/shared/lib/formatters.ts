/**
 * Locale-aware number and date formatters.
 *
 * Maps i18next language codes to Intl locale tags.
 * Falls back to browser locale when no mapping exists.
 *
 * This module also hosts a small handful of file/number helpers that
 * are not AI-specific (`formatNumber`, `formatFileSize`,
 * `getFileExtension`) — they used to live inside AI feature files but
 * were lifted out so any feature can reuse them.
 */
import i18next from 'i18next';

/** i18next language code → Intl BCP-47 locale tag */
const LOCALE_MAP: Record<string, string> = {
  de: 'de-DE',
  da: 'da-DK',
  cs: 'cs-CZ',
  en: 'en-US',
  es: 'es-ES',
  fr: 'fr-FR',
  fi: 'fi-FI',
  hi: 'hi-IN',
  it: 'it-IT',
  ja: 'ja-JP',
  ko: 'ko-KR',
  nl: 'nl-NL',
  no: 'nb-NO',
  pl: 'pl-PL',
  pt: 'pt-BR',
  ru: 'ru-RU',
  sv: 'sv-SE',
  tr: 'tr-TR',
  uk: 'uk-UA',
  bg: 'bg-BG',
  ar: 'ar-SA',
  zh: 'zh-CN',
};

/** Returns the Intl-compatible locale string for the current i18next language. */
export function getIntlLocale(): string {
  const lang = i18next.language || 'en';
  return LOCALE_MAP[lang] || lang;
}

/** Currency-style number formatter (e.g. 1,234.56) using current locale. */
export function fmtNumber(value: number | string | null | undefined, decimals = 2): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(getIntlLocale(), {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  }).format(safe);
}

/** Compact number formatter (e.g. 1.2M) using current locale. */
export function fmtCompact(value: number | string | null | undefined): string {
  const n = typeof value === 'number' ? value : Number(value ?? 0);
  const safe = Number.isFinite(n) ? n : 0;
  return new Intl.NumberFormat(getIntlLocale(), {
    notation: 'compact',
    maximumFractionDigits: 1,
  }).format(safe);
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
    return new Intl.NumberFormat(getIntlLocale(), {
      maximumFractionDigits: 0,
    }).format(safe);
  }
  try {
    return new Intl.NumberFormat(getIntlLocale(), {
      style: 'currency',
      currency: trimmed,
      maximumFractionDigits: 0,
    }).format(safe);
  } catch {
    return `${safe.toFixed(0)} ${trimmed}`;
  }
}

/** Date formatter using current locale. */
export function fmtDate(dateStr: string, options?: Intl.DateTimeFormatOptions): string {
  const defaults: Intl.DateTimeFormatOptions = {
    day: '2-digit',
    month: 'short',
    year: 'numeric',
  };
  return new Date(dateStr).toLocaleDateString(getIntlLocale(), options || defaults);
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
    return new Intl.NumberFormat(getIntlLocale(), {
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
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
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
