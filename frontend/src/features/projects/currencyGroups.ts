// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Shared currency catalogue — single source of truth for the project
 * currency picker, used by both ``CreateProjectPage`` (modal/page) and
 * ``ProjectDetailPage`` (inline edit form).
 *
 * Extracting this here means a) we don't duplicate the 80-entry list,
 * and b) the edit form on the detail page can pick from the same set
 * instead of accepting free text — which previously let a user save
 * a stub like ``"Eu"`` and break ``Intl.NumberFormat``.
 *
 * Also exports ``COUNTRY_DEFAULTS`` — a tiny country-code → region +
 * currency lookup the create dialog uses to auto-fill sensible defaults
 * after a successful geocode (only fires if the user hasn't picked yet).
 */

export interface OptionGroup {
  group: string;
  options: { value: string; label: string }[];
}

// ── Currencies (all major construction-market currencies) ─────────────────
//
// Kept verbatim to match the previous in-file constant; visual layout in
// both forms relies on the exact label format ``CODE (symbol) — Name``.
export const CURRENCY_GROUPS: OptionGroup[] = [
  {
    group: 'Europe',
    options: [
      { value: 'EUR', label: 'EUR (€) - Euro' },
      { value: 'GBP', label: 'GBP (£) - British Pound' },
      { value: 'CHF', label: 'CHF (Fr.) - Swiss Franc' },
      { value: 'SEK', label: 'SEK (kr) - Swedish Krona' },
      { value: 'NOK', label: 'NOK (kr) - Norwegian Krone' },
      { value: 'DKK', label: 'DKK (kr) - Danish Krone' },
      { value: 'PLN', label: 'PLN (zł) - Polish Zloty' },
      { value: 'CZK', label: 'CZK (Kč) - Czech Koruna' },
      { value: 'TRY', label: 'TRY (₺) - Turkish Lira' },
      { value: 'RUB', label: 'RUB (₽) - Russian Ruble' },
      { value: 'HUF', label: 'HUF (Ft) - Hungarian Forint' },
      { value: 'RON', label: 'RON (lei) - Romanian Leu' },
      { value: 'BGN', label: 'BGN (лв) - Bulgarian Lev' },
      { value: 'ISK', label: 'ISK (kr) - Icelandic Krona' },
    ],
  },
  {
    group: 'Americas',
    options: [
      { value: 'USD', label: 'USD ($) - US Dollar' },
      { value: 'CAD', label: 'CAD (C$) - Canadian Dollar' },
      { value: 'BRL', label: 'BRL (R$) - Brazilian Real' },
      { value: 'MXN', label: 'MXN (Mex$) - Mexican Peso' },
      { value: 'ARS', label: 'ARS (AR$) - Argentine Peso' },
      { value: 'CLP', label: 'CLP (CL$) - Chilean Peso' },
      { value: 'PEN', label: 'PEN (S/) - Peruvian Sol' },
      { value: 'COP', label: 'COP (COL$) - Colombian Peso' },
    ],
  },
  {
    group: 'Asia & Middle East',
    options: [
      { value: 'CNY', label: 'CNY (¥) - Chinese Yuan' },
      { value: 'JPY', label: 'JPY (¥) - Japanese Yen' },
      { value: 'KRW', label: 'KRW (₩) - South Korean Won' },
      { value: 'INR', label: 'INR (₹) - Indian Rupee' },
      { value: 'AED', label: 'AED (د.إ) - UAE Dirham' },
      { value: 'SAR', label: 'SAR (﷼) - Saudi Riyal' },
      { value: 'QAR', label: 'QAR (﷼) - Qatari Riyal' },
      { value: 'BHD', label: 'BHD (BD) - Bahraini Dinar' },
      { value: 'KWD', label: 'KWD (د.ك) - Kuwaiti Dinar' },
      { value: 'OMR', label: 'OMR (ر.ع.) - Omani Rial' },
      { value: 'SGD', label: 'SGD (S$) - Singapore Dollar' },
      { value: 'MYR', label: 'MYR (RM) - Malaysian Ringgit' },
      { value: 'THB', label: 'THB (฿) - Thai Baht' },
      { value: 'IDR', label: 'IDR (Rp) - Indonesian Rupiah' },
      { value: 'PHP', label: 'PHP (₱) - Philippine Peso' },
      { value: 'VND', label: 'VND (₫) - Vietnamese Dong' },
      { value: 'HKD', label: 'HKD (HK$) - Hong Kong Dollar' },
      { value: 'TWD', label: 'TWD (NT$) - Taiwan Dollar' },
      { value: 'ILS', label: 'ILS (₪) - Israeli Shekel' },
      { value: 'JOD', label: 'JOD (JD) - Jordanian Dinar' },
      { value: 'LBP', label: 'LBP (ل.ل) - Lebanese Pound' },
      { value: 'PKR', label: 'PKR (₨) - Pakistani Rupee' },
      { value: 'BDT', label: 'BDT (৳) - Bangladeshi Taka' },
      { value: 'LKR', label: 'LKR (Rs) - Sri Lankan Rupee' },
    ],
  },
  {
    group: 'Africa',
    options: [
      { value: 'ZAR', label: 'ZAR (R) - South African Rand' },
      { value: 'EGP', label: 'EGP (E£) - Egyptian Pound' },
      { value: 'NGN', label: 'NGN (₦) - Nigerian Naira' },
      { value: 'KES', label: 'KES (KSh) - Kenyan Shilling' },
      { value: 'MAD', label: 'MAD (د.م.) - Moroccan Dirham' },
      { value: 'TND', label: 'TND (DT) - Tunisian Dinar' },
      { value: 'GHS', label: 'GHS (GH₵) - Ghanaian Cedi' },
      { value: 'TZS', label: 'TZS (TSh) - Tanzanian Shilling' },
      { value: 'UGX', label: 'UGX (USh) - Ugandan Shilling' },
      { value: 'ETB', label: 'ETB (Br) - Ethiopian Birr' },
    ],
  },
  {
    group: 'Oceania',
    options: [
      { value: 'AUD', label: 'AUD (A$) - Australian Dollar' },
      { value: 'NZD', label: 'NZD (NZ$) - New Zealand Dollar' },
      { value: 'FJD', label: 'FJD (FJ$) - Fijian Dollar' },
    ],
  },
  {
    group: 'Other',
    options: [{ value: '__custom__', label: 'Custom...' }],
  },
];

/** Sentinel select value that reveals the free-text "type your own code"
 *  input. Kept identical to the literal used across the project forms and
 *  ``CountryCombobox`` so the grouped picker can reuse the same option. */
export const CUSTOM_CURRENCY_SENTINEL = '__custom__';

/** Set of every selectable currency code (excluding `__custom__`) — used
 *  by the detail-page edit form to validate a project's stored currency
 *  against the catalogue before rendering it as the select's value. */
export const CURRENCY_CODES: ReadonlySet<string> = new Set(
  CURRENCY_GROUPS.flatMap((g) => g.options.map((o) => o.value)).filter(
    (v) => v !== CUSTOM_CURRENCY_SENTINEL,
  ),
);

/**
 * Normalize a free-text currency code the same way the money formatter does
 * before it renders a symbol: trim, drop inner whitespace, upper-case. This
 * does NOT hard-reject input - it returns the cleaned string so the caller
 * can store a non-ISO code (the backend ``currency`` column is a free-form
 * ``str`` and ``formatCurrency`` already degrades unknown codes gracefully).
 *
 * Use {@link isValidCurrencyCode} to decide whether to show a soft hint.
 */
export function normalizeCurrencyCode(raw: string): string {
  return raw.replace(/\s+/g, '').toUpperCase();
}

/** Whether a (normalized or raw) code matches the ISO-4217 shape the
 *  ``Intl.NumberFormat`` currency style understands (3 ascii letters).
 *  Mirrors ``CURRENCY_CODE_RE`` in ``shared/lib/money.ts``. */
export function isValidCurrencyCode(code: string): boolean {
  return /^[A-Z]{3}$/.test(normalizeCurrencyCode(code));
}

// ── Country → (region, currency) defaults ────────────────────────────────
//
// Tiny lookup table — covers the existing project mix plus the most common
// markets the user is likely to type into the address field. The values
// must match an option ``value`` in REGION_GROUPS / CURRENCY_GROUPS or the
// auto-fill silently no-ops on submit. Country codes are ISO 3166-1 alpha-2
// as returned by Nominatim's ``address.country_code`` (lowercase).
export interface CountryDefault {
  region: string;
  currency: string;
}

export const COUNTRY_DEFAULTS: Readonly<Record<string, CountryDefault>> = {
  de: { region: 'DACH', currency: 'EUR' },
  at: { region: 'DACH', currency: 'EUR' },
  ch: { region: 'DACH', currency: 'CHF' },
  gb: { region: 'UK', currency: 'GBP' },
  fr: { region: 'France', currency: 'EUR' },
  es: { region: 'Spain', currency: 'EUR' },
  it: { region: 'Italy', currency: 'EUR' },
  nl: { region: 'Netherlands', currency: 'EUR' },
  pl: { region: 'Poland', currency: 'PLN' },
  cz: { region: 'Czech', currency: 'CZK' },
  // Croatia replaced the kuna with the euro on 2023-01-01, so HRK is not
  // offered for a new project at all. A project saved in HRK before then
  // still shows its code; the picker renders an unlisted code as custom.
  hr: { region: 'Croatia', currency: 'EUR' },
  tr: { region: 'Turkey', currency: 'TRY' },
  ru: { region: 'Russia', currency: 'RUB' },
  us: { region: 'US', currency: 'USD' },
  ca: { region: 'Canada', currency: 'CAD' },
  br: { region: 'Brazil', currency: 'BRL' },
  mx: { region: 'Mexico', currency: 'MXN' },
  cn: { region: 'China', currency: 'CNY' },
  jp: { region: 'Japan', currency: 'JPY' },
  kr: { region: 'Korea', currency: 'KRW' },
  in: { region: 'India', currency: 'INR' },
  ae: { region: 'GulfStates', currency: 'AED' },
  sa: { region: 'GulfStates', currency: 'SAR' },
  au: { region: 'Australia', currency: 'AUD' },
  nz: { region: 'NewZealand', currency: 'NZD' },
  za: { region: 'SouthAfrica', currency: 'ZAR' },
};

export function lookupCountryDefault(
  countryCode?: string | null,
): CountryDefault | null {
  if (!countryCode) return null;
  return COUNTRY_DEFAULTS[countryCode.toLowerCase()] ?? null;
}
