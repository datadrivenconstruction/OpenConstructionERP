// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure utility functions and constants used by the BOQ Editor.
 *
 * These are extracted from BOQEditorPage.tsx to keep the editor file focused
 * on orchestration and rendering. All functions are pure (no side-effects)
 * and can be tested independently.
 */

import type { Position, Markup } from './api';
import { getIntlLocale } from '@/shared/lib/formatters';
import { getNumberLocale } from '@/stores/usePreferencesStore';
import { formatCurrency } from '@/shared/lib/money';
import { apiGet, apiPatch } from '@/shared/lib/api';
import { formatElapsed, type Translate as DurationTranslate } from '@/shared/lib/duration';

/* ── Constants ───────────────────────────────────────────────────────── */

/**
 * Base metric units — always available regardless of language.
 *
 * Comprehensive global list covering construction estimating across all
 * 21 supported locales. Order is curated: most-used metric tokens first,
 * then imperial, then specialised industry tokens. The locale-specific
 * dictionaries below add native-language tokens on top (e.g. "Stk" for
 * de, "шт" for ru, "個" for ja).
 */
const BASE_UNITS = [
  // ── Length (metric) ──
  'mm', 'cm', 'dm', 'm', 'km', 'lm',
  // ── Area (metric) ──
  'mm2', 'cm2', 'dm2', 'm2', 'km2', 'ha', 'a',
  // ── Volume (metric) ──
  'mm3', 'cm3', 'dm3', 'm3', 'l', 'ml', 'cl', 'hl',
  // ── Mass (metric) ──
  'mg', 'g', 'kg', 't',
  // ── Imperial / US ──
  'in', 'ft', 'yd', 'mi',
  'sqft', 'sqyd', 'acre', 'sq',
  'cuft', 'cuyd', 'gal', 'oz', 'lb', 'cwt', 'ton',
  'cy', 'lf', 'msf', 'mbf', 'bdft',
  // ── Counts / packaging ──
  'pcs', 'pc', 'ea', 'set', 'pair', 'pr', 'lot', 'box',
  'roll', 'sheet', 'bundle', 'pack', 'pkg', 'bag', 'unit',
  // ── Construction-specific countables ──
  'door', 'win', 'fixture', 'point', 'item',
  // ── Labour / time ──
  's', 'min', 'h', 'hr', 'mh', 'shift', 'day', 'wk', 'mo', 'yr',
  // ── Lump-sum / scope ──
  'lsum', 'ls', 'job', 'visit',
  // ── Power / energy ──
  'W', 'kW', 'MW', 'kVA', 'kWh', 'MWh', 'BTU',
  // ── Force / pressure / per-unit-of-X ──
  'kN', 'MN', 'kg/m', 'kg/m2', 'kg/m3',
] as const;

/**
 * Language-specific additional units. Key = i18n language code, value =
 * extra tokens for that locale. Each list focuses on common tokens that
 * native estimators expect to see in the dropdown — local quantity
 * surveying conventions (e.g. "ME" for "Mengeneinheit" in DE, "пм" for
 * погонный метр in RU).
 */
const LOCALE_UNITS: Record<string, readonly string[]> = {
  // German (DACH / GAEB)
  de: ['Stk', 'St', 'Std', 'Std.', 'Masch.-Std.',
       'Psch', 'psch', 'lfm', 'FM', 'Mt', 'Wo', 'Tag',
       'LE', 'BE', 'ME', 'Pos.', 'Stck', 'kpl', 'kompl'],
  // French
  fr: ['u', 'ens', 'fft', 'ml', 'm.l', 'j', 'jr', 'sem', 'mois',
       'lot', 'forfait', 'pièce', 'unité'],
  // Spanish
  es: ['ud', 'uds', 'pa', 'ml', 'gl', 'jor', 'jornal', 'mes',
       'partida', 'pieza'],
  // Portuguese
  pt: ['un', 'unid', 'vb', 'cj', 'gl', 'dia', 'mes',
       'verba', 'peça'],
  // Russian / Ukrainian / Belarusian / Kazakh (CWICR catalogues)
  ru: ['шт', 'компл', 'комп', 'компл.', 'набор',
       'пм', 'п.м', 'п.м.', 'мп', 'м.п', 'лм',
       'маш-ч', 'маш.-ч', 'маш-час', 'чел-ч', 'чел.-ч', 'чел-час',
       'ч-ч', 'ч/ч', 'ч.-ч',
       'мин', 'час', 'сут', 'смен', 'смена', 'дн', 'мес', 'мес.', 'год',
       'усл', 'усл.ед', 'у.е.',
       'место', 'этаж', 'объект', 'позиц', 'позиция',
       'мешок', 'упак', 'упак.', 'кор', 'рул', 'лист', 'пара',
       'мм', 'см', 'дм', 'м', 'км',
       'мм2', 'см2', 'м2', 'км2', 'га',
       'мм3', 'см3', 'м3',
       'мг', 'г', 'кг', 'т', 'ц',
       'л', 'мл', 'кВт', 'кВт·ч', 'кВтч', 'Вт'],
  // Chinese
  zh: ['个', '只', '套', '台', '件', '块', '张', '根',
       '延米', '米', '平方米', '立方米', '公斤', '吨',
       '台班', '工日', '月', '天', '小时', '分钟', '秒',
       '处', '层', '项', '组', '盒', '袋', '卷'],
  // Arabic
  ar: ['عدد', 'طقم', 'قطعة', 'قطع',
       'م.ط', 'م.م', 'م.م²', 'م.م³',
       'يوم', 'ساعة', 'شهر', 'سنة',
       'كجم', 'طن', 'لتر'],
  // Japanese
  ja: ['本', '枚', '箇所', '式', '台', 'セット', '組',
       '個', '体', '巻', '袋', '箱',
       '人日', '人時', '時間', '日', '月', '年',
       '平米', '立米', '平方', 'キロ', 'トン'],
  // Korean
  ko: ['개', '세트', '식', '대',
       '매', '장', '롤', '봉', '박스',
       '인', '인일', '인시', '시간', '일', '월', '년',
       '평', '제곱미터', '입방미터'],
  // Turkish
  tr: ['ad', 'adet', 'tk', 'takım', 'mt', 'm.tul',
       'gn', 'gün', 'ay', 'yıl', 'saat', 'dakika',
       'çift', 'paket', 'rulo'],
  // Italian
  it: ['nr', 'n', 'cad', 'cpl', 'ml', 'm.l',
       'gg', 'giorni', 'mese', 'corpo', 'a corpo',
       'pz', 'pezzo', 'paio', 'set'],
  // Dutch
  nl: ['st', 'stk', 'stuk', 'stel', 'paar',
       'str.m', 'sm', 'lm',
       'dag', 'wk', 'mnd', 'jr', 'uur',
       'set', 'rol', 'doos'],
  // Polish
  pl: ['szt', 'szt.', 'kpl', 'kpl.', 'mb', 'm.b',
       'r-g', 'rbg', 'm-g', 'mg',
       'dzień', 'dni', 'tydz', 'mies', 'rok', 'godz',
       'para', 'opak'],
  // Czech / Slovak
  cs: ['ks', 'kpl', 'bm', 'hod', 'den',
       'týd', 'měs', 'rok', 'min',
       'pár', 'sada', 'bal'],
  // Romanian
  ro: ['buc', 'set', 'pereche', 'kit',
       'ml', 'm.l',
       'oră', 'h', 'zi', 'lună', 'an'],
  // Bulgarian
  bg: ['бр', 'бр.', 'комплект', 'двойка',
       'лм', 'мл', 'м.л',
       'час', 'ден', 'месец', 'година', 'смяна'],
  // Croatian
  hr: ['kom', 'kpl', 'par', 'set',
       'm', 'm2', 'm3',
       'h', 'sat', 'dan', 'mj', 'god'],
  // Swedish
  sv: ['st', 'styck', 'sats', 'par',
       'lm', 'löpmeter',
       'tim', 'h', 'dag', 'vecka', 'mån', 'år'],
  // Vietnamese
  vi: ['cái', 'chiếc', 'bộ', 'cặp', 'gói',
       'm.dài',
       'giờ', 'ngày', 'tuần', 'tháng', 'năm', 'ca'],
  // Thai
  th: ['ชิ้น', 'ตัว', 'ชุด', 'คู่', 'ม้วน',
       'ม.', 'ตร.ม.', 'ลบ.ม.',
       'ชั่วโมง', 'วัน', 'เดือน', 'ปี'],
  // Indonesian / Malay
  id: ['bh', 'buah', 'set', 'pasang', 'lembar',
       'm', 'm2', 'm3',
       'jam', 'hari', 'minggu', 'bulan', 'tahun'],
};

/**
 * Custom unit catalogue — hybrid local + server persistence.
 *
 * The dropdown reads from localStorage for instant render. On app boot we
 * call `syncCustomUnitsFromServer()` to merge the server-side list (per-user,
 * stored on `User.metadata_["custom_units"]`) into the local cache. New unit
 * commits go through `saveCustomUnit()` which writes locally first then
 * fire-and-forgets a PATCH to the server. Anonymous / offline sessions keep
 * working as before — the server sync is best-effort and silently degrades.
 */
const CUSTOM_UNITS_KEY = 'oe_custom_units';

function loadCustomUnits(): string[] {
  try {
    const raw = localStorage.getItem(CUSTOM_UNITS_KEY);
    return raw ? (JSON.parse(raw) as string[]) : [];
  } catch {
    return [];
  }
}

function writeCustomUnits(units: string[]): void {
  try {
    localStorage.setItem(CUSTOM_UNITS_KEY, JSON.stringify(units));
  } catch { /* localStorage full / disabled — accept the loss */ }
}

interface CustomUnitsResponse { units: string[] }

// Module-level promise cache. ``syncCustomUnitsFromServer()`` is called from
// a ``useEffect`` in App.tsx — under React StrictMode in dev that effect
// double-fires, and even in prod a fast re-render would otherwise issue two
// concurrent GETs. Caching the in-flight promise dedupes both paths and
// returns the same merged result to every caller within the session.
let inFlightSync: Promise<string[]> | null = null;

/** Pull the server-side catalogue into local cache. Called once on app boot
 *  after auth resolves. Returns the merged list for callers that want it. */
export async function syncCustomUnitsFromServer(): Promise<string[]> {
  if (inFlightSync) return inFlightSync;
  inFlightSync = (async () => {
    try {
      const resp = await apiGet<CustomUnitsResponse>('/v1/users/me/custom-units/');
      const server = Array.isArray(resp?.units) ? resp.units : [];
      const merged = [...new Set([...loadCustomUnits(), ...server])];
      writeCustomUnits(merged);
      // If the merge produced new entries that weren't on the server, push them.
      if (merged.length !== server.length) {
        apiPatch('/v1/users/me/custom-units/', { units: merged }).catch(() => undefined);
      }
      return merged;
    } catch {
      // 401 (anonymous) or network failure — local-only path stays valid.
      return loadCustomUnits();
    }
  })();
  return inFlightSync;
}

export function saveCustomUnit(unit: string): void {
  const custom = loadCustomUnits();
  if (custom.includes(unit)) return;
  custom.push(unit);
  writeCustomUnits(custom);
  // Best-effort server sync. Don't block the UI on the network round-trip;
  // don't surface the error if it fails — the next syncCustomUnitsFromServer()
  // call will reconcile the merged list.
  apiPatch('/v1/users/me/custom-units/', { units: custom }).catch(() => undefined);
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
export const UNDO_STACK_LIMIT = 30;

/** Editable field names in left-to-right column order for keyboard navigation. */
export const EDITABLE_FIELDS = ['ordinal', 'description', 'unit', 'quantity', 'unit_rate'] as const;
export type EditableField = (typeof EDITABLE_FIELDS)[number];

/* ── VAT Rates ───────────────────────────────────────────────────────── */

/**
 * Suggested VAT rates per region — used ONLY as seed values when the user
 * clicks "Apply Default Markups" in the Markups & Overheads panel. Never
 * applied automatically; never used as a render-time fallback.
 */
export const SUGGESTED_VAT_RATES: Record<string, number> = {
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
  'Brazil': 0.0,
  'China': 0.09,
  'Japan': 0.10,
  'India': 0.18,
  'Gulf States (UAE, Saudi Arabia, Qatar)': 0.05,
  'Middle East (General)': 0.05,
  'Australia': 0.10,
  'New Zealand': 0.15,
};

/**
 * Resolve a VAT rate from the BOQ's first percentage `tax`-category markup row.
 * Returns 0 when no such row exists; the editor footer renders "No VAT" then.
 *
 * Display convenience, NOT the authority on what a bill is taxed. It reads one
 * row, so a second tax line is invisible to it and a tax charged as a fixed sum
 * carries no percentage to read at all. Both are ordinary: Brazil stacks two,
 * and a stamp duty is a sum. The authority is `cost-breakdown.grand_total`.
 *
 * This comment used to claim it matched the backend PDF and Excel writers.
 * It no longer does, and the correction runs the other way: the PDF stopped
 * reading a rate off one row and now sums the amounts of every tax row.
 */
export function getVatRateFromMarkups(markups: Markup[]): number {
  const tax = markups.find(
    (m) => m.category === 'tax' && m.is_active !== false && m.markup_type === 'percentage',
  );
  if (!tax) return 0;
  return tax.percentage / 100;
}

/**
 * Suggestion-only lookup for the Project Settings placeholder. Returns 0
 * when the region is missing or unknown — never falls back to a country
 * default. Do NOT use as a render-time VAT rate; use {@link getVatRateFromMarkups}.
 */
export function getVatRate(region?: string): number {
  if (!region) return 0;
  return SUGGESTED_VAT_RATES[region] ?? 0;
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
  if (!currencyStr) return '';
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
  if (!currencyStr) return '';
  const code = currencyStr.trim().substring(0, 3).toUpperCase();
  if (/^[A-Z]{3}$/.test(code)) return code;
  return '';
}

/* ── Number Formatting ───────────────────────────────────────────────── */

/** Locale-aware number formatter for currency-like values. */
export function createFormatter(locale?: string): Intl.NumberFormat {
  return new Intl.NumberFormat(locale ?? getNumberLocale(), {
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
 *
 * A thin adapter over the canonical `formatCurrency`, kept for its argument
 * order, which the eleven bill surfaces already spell this way. The formatting
 * itself deliberately lives in one place: this used to build its own
 * `Intl.NumberFormat`, and two implementations of the same idea is how the bill
 * and the finance register came to write the same amount two different ways.
 *
 * The visible consequence of delegating is the decimal count. This helper asked
 * for two of them on every currency, so a bill in yen showed cents that do not
 * exist and one in dinars hid a digit that does. `formatCurrency` reads the
 * count the engine holds for the code.
 *
 *  - de-DE + EUR -> "1.400,00 EUR-symbol"
 *  - en-US + USD -> "$1,400.00"
 *  - en-GB + GBP -> "£1,400.00"
 *  - ja-JP + JPY -> "¥1,400"      (no minor unit)
 *  - ar-AE + AED -> Arabic-indic digits, symbol per locale
 *  - ru-RU + RUB -> "1 400,00 ₽"
 */
export function fmtWithCurrency(
  value: number,
  locale: string,
  currencyCode: string,
): string {
  // An empty tag means "no opinion", not "the C locale": `formatCurrency`
  // answers that with the UI language, which is what a caller who passed
  // nothing wants to see.
  return formatCurrency(value, currencyCode, (locale || '').trim() || undefined);
}

/* ── Multi-currency rebase (Issue #88 / #111) ───────────────────────────
 * Convert a value from a position's source currency into the project's
 * base currency. Project FX rates are stored as ``rate`` per currency,
 * with semantics: ``1 unit of the foreign currency = rate base units``.
 * So foreign → base is multiplication.
 *
 * Returns the value unchanged when:
 *   - source currency is empty / undefined / equals base
 *   - no FX rate exists for the source currency (best-effort, with a
 *     console warning so the dev tools surface the gap)
 *   - the rate is non-finite or non-positive
 *
 * This was missing in v2.9.1's #88 fix — positions priced in a foreign
 * currency had their ``total`` summed into directCost as if it were
 * already in base. Issue #111 surfaced the bug for ARS-priced positions
 * inside a USD project.
 */
export function convertToBase(
  value: number,
  sourceCurrency: string | undefined | null,
  baseCurrency: string | undefined | null,
  fxRates: Array<{ currency: string; rate: number }> | undefined | null,
): number {
  // Defensive: backend Numeric columns serialise as decimal *strings*.
  // The TS type says ``number`` but a string can still arrive at runtime
  // from a path that skipped ``normalizePosition`` — coerce instead of
  // letting ``Number.isFinite("123")`` (false) zero a real value (#131).
  const v = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(v)) return 0;
  if (!sourceCurrency) return v;
  if (!baseCurrency || sourceCurrency === baseCurrency) return v;
  const list = fxRates ?? [];
  const fx = list.find((r) => r.currency === sourceCurrency);
  const fxRate = fx ? Number(fx.rate) : NaN;
  if (!fx || !Number.isFinite(fxRate) || fxRate <= 0) {
    // No rate configured — surface the gap in dev tools but don't crash.
    if (typeof console !== 'undefined' && console.warn) {
      console.warn(
        `[boq] no FX rate for ${sourceCurrency} → ${baseCurrency}; ` +
        `position total left unconverted.`,
      );
    }
    return v;
  }
  return v * fxRate;
}

/* ── Resource-currency-aware leaf total (Issue #111 — skolodi follow-up) ──
 * ``convertToBase`` only ever converts when the *position* carries a
 * ``metadata.currency``. The contributor's real data (``Prueba_2.csv``)
 * is the shape that path can never catch: a position with NO
 * ``metadata.currency`` but whose ``metadata.resources`` are priced in a
 * foreign currency. The stored position ``total`` is built from
 * ``Σ(r.quantity × r.unit_rate)`` with no FX applied, so a USD 25 000
 * resource in an ARS project was rolled up as 25 000 ARS in BOTH the
 * per-position resource subtotal AND the section subtotal.
 *
 * This mirrors the backend ``_leaf_total_base_with_resources``:
 *   - position has priced resources with ≥1 foreign currency →
 *     per-unit rate = Σ(r.qty × r.rate × fx[r.currency]), then × pos.qty
 *   - otherwise → fall back to position-level ``convertToBase`` so the
 *     verified #131 ``metadata.currency`` path is unchanged.
 */
export function resourceAwareTotalInBase(
  position: {
    total?: number | string | null;
    quantity?: number | string | null;
    metadata?: Record<string, unknown> | null;
    metadata_?: Record<string, unknown> | null;
  },
  baseCurrency: string | undefined | null,
  fxRates: Array<{ currency: string; rate: number }> | undefined | null,
): number {
  const meta = (position.metadata ?? position.metadata_ ?? {}) as Record<string, unknown>;
  const resources = meta.resources;
  const num = (x: unknown): number => {
    const n = typeof x === 'number' ? x : Number(x);
    return Number.isFinite(n) ? n : 0;
  };
  const base = (baseCurrency || '').trim().toUpperCase();

  if (Array.isArray(resources) && resources.length > 0) {
    const anyForeign = resources.some((r) => {
      if (!r || typeof r !== 'object') return false;
      const code = String((r as { currency?: unknown }).currency ?? '')
        .trim()
        .toUpperCase();
      return code !== '' && code !== base;
    });
    if (anyForeign) {
      // Per-unit rate, currency-converted across mixed resource
      // currencies (resources are per-unit norms), then × position qty.
      let perUnitBase = 0;
      for (const r of resources) {
        if (!r || typeof r !== 'object') continue;
        const rr = r as {
          quantity?: unknown;
          unit_rate?: unknown;
          total?: unknown;
          currency?: unknown;
        };
        const rSub =
          rr.total != null && Number.isFinite(num(rr.total))
            ? num(rr.total)
            : num(rr.quantity) * num(rr.unit_rate);
        const rCode = String(rr.currency ?? '').trim() || base;
        perUnitBase += convertToBase(rSub, rCode, base, fxRates);
      }
      return perUnitBase * num(position.quantity);
    }
  }

  // No priced foreign resources — established position-level path.
  const src = (meta.currency as string | undefined) || base;
  return convertToBase(num(position.total), src, base, fxRates);
}

/* ── Resource-driven pricing predicate ───────────────────────────────────
 * A position's Unit Rate is derived (Σ per-unit resource subtotals) and its
 * cell is locked ONLY when the position carries a resource that actually
 * contributes to the rate: a non-empty resources list with at least one entry
 * whose quantity is a finite, non-zero number. An empty list, an absent list,
 * or a list whose every entry has a zero / blank / non-numeric quantity counts
 * as HAVING NO RESOURCES — the rate is a directly-editable manual value.
 *
 * This is the single source of truth the editable predicate (columnDefs) and
 * the rate renderer (cellRenderers) share, and it mirrors the backend
 * ``_has_contributing_resources`` so the UI never shows an editable cell whose
 * edit the backend would discard, nor a locked cell the user cannot price
 * (a position with only blank / zero-quantity resource rows).
 *
 * NB: this is the PRICING notion. Whether to render the resource sub-rows /
 * expand chevron is a separate concern keyed on ``resources.length`` — blank
 * resource rows must still be visible so the user can fill in a quantity.
 */
export function hasContributingResources(resources: unknown): boolean {
  if (!Array.isArray(resources) || resources.length === 0) return false;
  return resources.some((r) => {
    if (!r || typeof r !== 'object') return false;
    const q = (r as { quantity?: unknown }).quantity;
    const n = typeof q === 'number' ? q : parseFloat(String(q ?? ''));
    return Number.isFinite(n) && n !== 0;
  });
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
  const markupScore = hasMarkups ? 100 : 0;
  const score = withDescription * 0.3 + withQuantity * 0.3 + withRate * 0.3 + markupScore * 0.1;

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

/**
 * Format a timestamp as a compact age ("2m", "3h", "4d", "5mo").
 *
 * Now a thin wrapper over the shared formatter (#174). The unit ladder is
 * unchanged - this was one of the two copies that already climbed it - but
 * the suffixes now come from i18n rather than being English literals, so the
 * activity panel stops printing "2m" to a reader of any of the 29 locales.
 * The caller supplies ``t``.
 */
export function formatRelativeTime(t: DurationTranslate, isoString: string): string {
  return formatElapsed(t, isoString);
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

/* ── International currency catalogue ────────────────────────────────────
 * Used by the resource-row currency picker. The list is intentionally
 * broad: an international estimator may price one resource in USD and
 * another in EUR even when the project base is GBP, regardless of
 * whether the BOQ owner has populated `fx_rates` yet. Items chosen with
 * no FX configured render with a "no FX" warning badge — the value
 * itself is preserved in the resource's own currency.
 */
export const COMMON_CURRENCIES: readonly string[] = [
  // Most-used global trade currencies first
  'USD', 'EUR', 'GBP', 'CHF', 'JPY', 'CNY',
  // Major regional currencies
  'CAD', 'AUD', 'NZD', 'SGD', 'HKD', 'KRW',
  // Emerging-market & commodity currencies
  'INR', 'BRL', 'MXN', 'ZAR', 'TRY', 'RUB',
  // EU non-euro
  'PLN', 'CZK', 'HUF', 'SEK', 'NOK', 'DKK', 'RON',
  // Middle East
  'AED', 'SAR', 'QAR', 'ILS',
  // SE Asia
  'THB', 'IDR', 'MYR', 'PHP', 'VND',
];

/** ISO 4217 → symbol map for the resource currency badge. */
export const CURRENCY_SYMBOL: Record<string, string> = {
  USD: '$', EUR: '€', GBP: '£', CHF: 'Fr', JPY: '¥', CNY: '¥',
  CAD: '$', AUD: '$', NZD: '$', SGD: '$', HKD: '$', KRW: '₩',
  INR: '₹', BRL: 'R$', MXN: '$', ZAR: 'R', TRY: '₺', RUB: '₽',
  PLN: 'zł', CZK: 'Kč', HUF: 'Ft', SEK: 'kr', NOK: 'kr', DKK: 'kr', RON: 'lei',
  AED: 'د.إ', SAR: '﷼', QAR: '﷼', ILS: '₪',
  THB: '฿', IDR: 'Rp', MYR: 'RM', PHP: '₱', VND: '₫',
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
  /** ISO 4217 currency code (RFC 37 / Issue #93). Absent ⇒ project base currency. */
  currency?: string;
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

/**
 * The item code a position carries, whichever standard classified it.
 *
 * A position's `classification` is a map from a classification standard to
 * the code that standard gives the line: `{ din276: '331' }` on a German
 * bill, `{ tetelrend: 'MA-04-12-01' }` on a Hungarian one, `{ gesn: ... }`,
 * `{ cpwd: ... }`, `{ sinapi: ..., nbr: ... }` and so on. Two counts, because
 * they differ and quoting the wrong one is misleading: the backend can name
 * eighteen standards and a project can be stored under thirteen of them, while
 * the classification keys actually present on shipped demo data are fourteen.
 *
 * The two places that rendered this code read three keys, `din276`, `nrm` and
 * `masterformat`, which the backend registry itself calls the legacy three.
 * Every other standard fell through to an empty cell. Measured against the
 * shipped demos that is nine of thirty three whose Code column was blank on
 * every priced line, and eleven classification keys that could never appear:
 * sbc, gb50500, mexico, cpwd, tetelrend, gesn, asaqs, nbr, dpgf, sinapi and
 * sans1200. The validation rules meanwhile require exactly those codes, so a
 * user could be told a line has no item code by a rule while the column that
 * would show it stayed empty.
 *
 * @param classification - the position's `classification` map.
 * @param preferred - the project's own classification standard, when known.
 *   A line can carry more than one code (a Brazilian bill carries both
 *   `sinapi` and `nbr`), and the project's standard is the one its reader
 *   expects to see. Without it the first code on the row wins, which is
 *   deterministic because object key order is insertion order.
 * @returns the code, or an empty string when the row carries none.
 */
export function classificationCode(classification: unknown, preferred?: string | null): string {
  if (!classification || typeof classification !== 'object' || Array.isArray(classification)) return '';
  const cls = classification as Record<string, unknown>;
  const codeAt = (key: string): string => {
    const value = cls[key];
    if (typeof value === 'string') return value.trim();
    // A standard whose code is numeric still has a code. Booleans and
    // objects are not codes and must not be stringified into the cell.
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
    return '';
  };
  if (preferred) {
    const own = codeAt(preferred);
    if (own) return own;
  }
  for (const key of Object.keys(cls)) {
    const code = codeAt(key);
    if (code) return code;
  }
  return '';
}
