/**
 * Pure utility functions and constants used by the BOQ Editor.
 *
 * These are extracted from BOQEditorPage.tsx to keep the editor file focused
 * on orchestration and rendering. All functions are pure (no side-effects)
 * and can be tested independently.
 */

import type { Position, Markup } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';

/* ── Constants ───────────────────────────────────────────────────────── */

/** Base metric units — always available regardless of language. */
const BASE_UNITS = ['m', 'm2', 'm3', 'kg', 't', 'pcs', 'lsum', 'h', 'set', 'lm'] as const;

/**
 * Language-specific additional units.
 * Key = i18n language code, value = extra units for that locale.
 */
const LOCALE_UNITS: Record<string, readonly string[]> = {
  de: ['Stk', 'Psch', 'lfm', 'FM', 'Std', 'Mt', 'Wo', 'Tag', 'LE', 'BE', 'ME'],
  fr: ['u', 'ens', 'fft', 'ml', 'j', 'sem', 'mois', 'lot'],
  es: ['ud', 'pa', 'ml', 'gl', 'jor', 'mes'],
  pt: ['un', 'vb', 'cj', 'gl', 'dia', 'mes'],
  ru: ['шт', 'компл', 'п.м', 'маш-ч', 'чел-ч', 'мес', 'усл'],
  zh: ['个', '套', '延米', '台班', '工日', '月'],
  ar: ['عدد', 'طقم', 'م.ط', 'يوم'],
  ja: ['本', '枚', '箇所', '式', '台', 'セット', '組'],
  ko: ['개', '세트', '식', '대'],
  tr: ['ad', 'tk', 'mt', 'gn', 'ay'],
  it: ['nr', 'cad', 'cpl', 'ml', 'gg', 'mese', 'corpo'],
  nl: ['st', 'stel', 'str.m', 'dag', 'mnd'],
  pl: ['szt', 'kpl', 'mb', 'r-g', 'm-g', 'dzień'],
  cs: ['ks', 'kpl', 'bm', 'hod', 'den'],
};

/** Custom units stored in localStorage by the user. */
const CUSTOM_UNITS_KEY = 'oe_custom_units';

function loadCustomUnits(): string[] {
  try {
    const raw = localStorage.getItem(CUSTOM_UNITS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

export function saveCustomUnit(unit: string): void {
  const custom = loadCustomUnits();
  if (!custom.includes(unit)) {
    custom.push(unit);
    try {
      localStorage.setItem(CUSTOM_UNITS_KEY, JSON.stringify(custom));
    } catch { /* ignore */ }
  }
}

/**
 * Get units for the current locale. Includes base metric + locale-specific + user custom.
 * Always deduplicates and keeps base units first.
 */
export function getUnitsForLocale(lang?: string): string[] {
  const code = (lang || 'en').split('-')[0] ?? 'en';
  const locale = LOCALE_UNITS[code] ?? [];
  const custom = loadCustomUnits();
  const all = [...BASE_UNITS, ...locale, ...custom];
  // Deduplicate preserving order
  return [...new Set(all)];
}

/** Default export for backward compatibility. */
export const UNITS = BASE_UNITS;

/** Maximum number of undo entries stored. */
export const UNDO_STACK_LIMIT = 20;

/** Editable field names in left-to-right column order for keyboard navigation. */
export const EDITABLE_FIELDS = ['ordinal', 'description', 'unit', 'quantity', 'unit_rate'] as const;
export type EditableField = (typeof EDITABLE_FIELDS)[number];

/* ── VAT Rates ───────────────────────────────────────────────────────── */

/** VAT rates by region — used when markups API is unavailable. */
const VAT_RATES: Record<string, number> = {
  'DACH (Germany, Austria, Switzerland)': 0.19,
  'United Kingdom': 0.20,
  'France': 0.20,
  'Spain': 0.21,
  'Italy': 0.22,
  'Netherlands': 0.21,
  'Poland': 0.23,
  'Czech Republic': 0.21,
  'Turkey': 0.20,
  'Russia': 0.20,
  'United States': 0.0,
  'Canada': 0.05,
  'Brazil': 0.0, // PIS/COFINS varies
  'China': 0.09,
  'Japan': 0.10,
  'India': 0.18,
  'Gulf States (UAE, Saudi Arabia, Qatar)': 0.05,
  'Middle East (General)': 0.05,
  'Australia': 0.10,
  'New Zealand': 0.15,
};

export function getVatRate(region?: string): number {
  if (!region) return 0.19;
  return VAT_RATES[region] ?? 0.19;
}

/* ── Region Locales ──────────────────────────────────────────────────── */

/** Map region to locale for number/date formatting. */
const REGION_LOCALES: Record<string, string> = {
  'DACH (Germany, Austria, Switzerland)': 'de-DE',
  'United Kingdom': 'en-GB',
  'France': 'fr-FR',
  'Spain': 'es-ES',
  'Italy': 'it-IT',
  'Netherlands': 'nl-NL',
  'Poland': 'pl-PL',
  'Czech Republic': 'cs-CZ',
  'Turkey': 'tr-TR',
  'Russia': 'ru-RU',
  'United States': 'en-US',
  'Canada': 'en-CA',
  'Brazil': 'pt-BR',
  'China': 'zh-CN',
  'Japan': 'ja-JP',
  'India': 'en-IN',
  'Gulf States (UAE, Saudi Arabia, Qatar)': 'ar-AE',
  'Middle East (General)': 'ar-SA',
  'Australia': 'en-AU',
  'New Zealand': 'en-NZ',
};

export function getLocaleForRegion(region?: string): string {
  if (!region) return 'de-DE';
  return REGION_LOCALES[region] ?? 'en-US';
}

/* ── Currency Symbols ────────────────────────────────────────────────── */

/** Map currency code to symbol. */
const CURRENCY_SYMBOLS: Record<string, string> = {
  EUR: '\u20ac', GBP: '\u00a3', USD: '$', CHF: 'Fr.', CAD: 'C$', AUD: 'A$', NZD: 'NZ$',
  JPY: '\u00a5', CNY: '\u00a5', KRW: '\u20a9', INR: '\u20b9', BRL: 'R$', MXN: 'Mex$', TRY: '\u20ba',
  RUB: '\u20bd', PLN: 'z\u0142', CZK: 'K\u010d', SEK: 'kr', NOK: 'kr', DKK: 'kr',
  AED: '\u062f.\u0625', SAR: '\ufdfc', QAR: '\ufdfc', ZAR: 'R', EGP: 'E\u00a3', NGN: '\u20a6',
  SGD: 'S$', MYR: 'RM', THB: '\u0e3f', IDR: 'Rp', PHP: '\u20b1', HKD: 'HK$',
};

/**
 * Extract display symbol from currency string. Handles formats:
 *  - "EUR (€) — Euro" → "€"
 *  - "CAD (C$) — Canadian Dollar" → "C$"
 *  - "EUR" → "€" (plain code lookup)
 *  - "GBP" → "£"
 */
export function getCurrencySymbol(currencyStr?: string): string {
  if (!currencyStr) return '\u20ac';
  // Try "(symbol)" pattern first: "CAD (C$) — Canadian Dollar"
  const match = currencyStr.match(/\((.+?)\)/);
  if (match?.[1]) return match[1];
  // Try plain 3-letter code: "CAD", "EUR", "GBP"
  const code = currencyStr.trim().substring(0, 3).toUpperCase();
  return CURRENCY_SYMBOLS[code] || code;
}

/* ── Currency Code Extraction ───────────────────────────────────────── */

/**
 * Extract ISO 4217 currency code from currency string. Handles formats:
 *  - "EUR (€) — Euro" → "EUR"
 *  - "CAD (C$) — Canadian Dollar" → "CAD"
 *  - "EUR" → "EUR"
 *  - "GBP" → "GBP"
 */
export function getCurrencyCode(currencyStr?: string): string {
  if (!currencyStr) return 'EUR';
  const code = currencyStr.trim().substring(0, 3).toUpperCase();
  // Validate it looks like a currency code (3 uppercase letters)
  if (/^[A-Z]{3}$/.test(code)) return code;
  return 'EUR';
}

/* ── Number Formatting ───────────────────────────────────────────────── */

/** Locale-aware number formatter for currency-like values. */
export function createFormatter(locale = 'de-DE'): Intl.NumberFormat {
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Format a number for display. Always shows full precision in BOQ context —
 * rounding (K/M) is never acceptable for professional cost estimation.
 */
export function fmtCompact(n: number, fmt: Intl.NumberFormat): string {
  return fmt.format(n);
}

/**
 * Format a number with locale-aware currency symbol placement.
 * Uses Intl.NumberFormat with style: 'currency' so the symbol position,
 * decimal separator, and grouping are all determined by the locale:
 *  - de-DE + EUR → "1.400,00 €"
 *  - en-US + USD → "$1,400.00"
 *  - en-GB + GBP → "£1,400.00"
 *  - ar-AE + AED → "١٬٤٠٠٫٠٠ د.إ." (with Latin digits fallback)
 *  - ru-RU + RUB → "1 400,00 ₽"
 */
export function fmtWithCurrency(
  value: number,
  locale: string,
  currencyCode: string,
): string {
  try {
    return new Intl.NumberFormat(locale, {
      style: 'currency',
      currency: currencyCode,
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    }).format(value);
  } catch {
    // Fallback: use the plain number formatter + symbol
    const fmt = new Intl.NumberFormat(locale, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
    return `${fmt.format(value)} ${currencyCode}`;
  }
}

/* ── Quality Score ───────────────────────────────────────────────────── */

export interface QualityBreakdown {
  /** Percentage of positions that have a non-empty description. */
  withDescription: number;
  /** Percentage of positions that have quantity > 0. */
  withQuantity: number;
  /** Percentage of positions that have unit_rate > 0. */
  withRate: number;
  /** Whether markups exist (overhead, profit, etc.). */
  hasMarkups: boolean;
  /** Overall score 0-100. */
  score: number;
}

export function computeQualityScore(
  positions: Position[],
  markups: Markup[],
): QualityBreakdown {
  // Only count non-section positions (positions that have a unit)
  const items = positions.filter((p) => p.unit && p.unit.trim() !== '' && p.unit.trim().toLowerCase() !== 'section');
  if (items.length === 0) {
    return { withDescription: 0, withQuantity: 0, withRate: 0, hasMarkups: markups.length > 0, score: 0 };
  }

  const withDescription = (items.filter((p) => p.description.trim().length > 0).length / items.length) * 100;
  const withQuantity = (items.filter((p) => p.quantity > 0).length / items.length) * 100;
  const withRate = (items.filter((p) => p.unit_rate > 0).length / items.length) * 100;
  const hasMarkups = markups.length > 0;

  // Weighted: description 30%, quantity 30%, rate 30%, markups 10%
  const score = withDescription * 0.3 + withQuantity * 0.3 + withRate * 0.3 + (hasMarkups ? 10 : 0);

  return { withDescription, withQuantity, withRate, hasMarkups, score: Math.round(score) };
}

/* ── Time Formatting ─────────────────────────────────────────────────── */

export function formatTimeAgo(dateStr: string): string {
  const now = Date.now();
  const date = new Date(dateStr).getTime();
  const diff = now - date;
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'just now';
  if (mins < 60) return `${mins}m ago`;
  const hours = Math.floor(mins / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 7) return `${days}d ago`;
  return new Date(dateStr).toLocaleDateString(getIntlLocale());
}

/** Format a timestamp as a relative time string (e.g. "2m ago", "3h ago"). */
export function formatRelativeTime(isoString: string): string {
  const now = Date.now();
  const then = new Date(isoString).getTime();
  const diffMs = now - then;

  if (diffMs < 0) return 'just now';

  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return 'just now';

  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m`;

  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h`;

  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d`;

  const months = Math.floor(days / 30);
  return `${months}mo`;
}

/* ── Undo Entry Type ─────────────────────────────────────────────────── */

/** An entry in the undo/redo stack describing a single mutation. */
export interface UndoEntry {
  type: 'update' | 'add' | 'delete';
  positionId: string;
  oldData: import('./api').UpdatePositionData | null;
  newData: import('./api').UpdatePositionData | null;
  /** Full position snapshot for re-creating on redo after delete, or undoing an add. */
  positionSnapshot?: Position;
}

/* ── Validation Status Styles ────────────────────────────────────────── */

export const VALIDATION_DOT_STYLES: Record<string, string> = {
  passed: 'bg-green-500',
  warnings: 'bg-yellow-400',
  errors: 'bg-red-500',
  pending: 'bg-gray-300 dark:bg-gray-600',
};

export const VALIDATION_DOT_LABELS: Record<string, string> = {
  passed: 'validation.passed',
  warnings: 'validation.warnings',
  errors: 'validation.errors',
  pending: 'validation.pending',
};

/* ── Resource Type Badges ────────────────────────────────────────────── */

export const RESOURCE_TYPE_BADGE: Record<string, { bg: string; label: string }> = {
  material:      { bg: 'bg-blue-100 text-blue-700 dark:bg-blue-900/40 dark:text-blue-300',    label: 'M' },
  labor:         { bg: 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300', label: 'L' },
  equipment:     { bg: 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300', label: 'E' },
  operator:      { bg: 'bg-green-100 text-green-700 dark:bg-green-900/40 dark:text-green-300', label: 'O' },
  subcontractor: { bg: 'bg-pink-100 text-pink-700 dark:bg-pink-900/40 dark:text-pink-300',    label: 'S' },
  electricity:   { bg: 'bg-yellow-100 text-yellow-700 dark:bg-yellow-900/40 dark:text-yellow-300', label: 'W' },
  other:         { bg: 'bg-gray-100 text-gray-600 dark:bg-gray-800 dark:text-gray-400',       label: '?' },
};

/* ── Shared Interfaces ───────────────────────────────────────────────── */

export interface PositionResource {
  name: string;
  code?: string;
  type: string; // material, labor, equipment, subcontractor, operator, other
  unit: string;
  quantity: number;
  unit_rate: number;
  total: number;
  waste_pct?: number; // material waste/loss factor (%), e.g. 3 means +3%
}

export interface PositionComment {
  id: string;
  text: string;
  date: string; // ISO string
  author: string;
}

export interface Tip {
  id: string;
  text: string;
  condition?: 'no_sections' | 'no_markups' | 'has_empty_descriptions' | 'always';
}
