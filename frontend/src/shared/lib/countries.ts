// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// ISO 3166-1 alpha-2 country dataset shared across the app.
//
// Why it lives here: several modules need to render a long country list
// (Property Dev house-types, Procurement vendor catalogues, CRM
// contacts, ...). Previously each module hard-coded its own 10-15 most-
// common list, which meant "I'm based in Senegal" users got no entry.
// Centralising the dataset gives every picker the same coverage and
// keeps the emoji-flag derivation logic in one place.
//
// The display name follows the "English (Local script)" pattern where a
// local script is meaningful, e.g. "Russia (Россия)". Local scripts are
// included only when they meaningfully aid recognition; for languages
// using the Latin alphabet we keep a single label.
//
// `nameLocal` is used as the secondary search index so a user typing
// "Россия" matches RU, "Deutschland" matches DE, etc.

export interface Country {
  /** ISO 3166-1 alpha-2 code, uppercase. */
  code: string;
  /** English display name. */
  name: string;
  /** Optional native-script label, used as a secondary search field. */
  nameLocal?: string;
  /** Default ISO 4217 currency for the country (best-effort, not exhaustive). */
  currency?: string;
}

/**
 * Curated 200-country list covering every UN member state plus
 * commonly-used non-state territories (HK, TW, PS, ...). Sort order is
 * alphabetic by English name at runtime — see `sortedCountries()`.
 */
export const COUNTRIES: ReadonlyArray<Country> = [
  { code: 'AD', name: 'Andorra', currency: 'EUR' },
  { code: 'AE', name: 'United Arab Emirates', nameLocal: 'الإمارات', currency: 'AED' },
  { code: 'AF', name: 'Afghanistan', currency: 'AFN' },
  { code: 'AG', name: 'Antigua and Barbuda', currency: 'XCD' },
  { code: 'AL', name: 'Albania', nameLocal: 'Shqipëria', currency: 'ALL' },
  { code: 'AM', name: 'Armenia', nameLocal: 'Հայաստան', currency: 'AMD' },
  { code: 'AO', name: 'Angola', currency: 'AOA' },
  { code: 'AR', name: 'Argentina', currency: 'ARS' },
  { code: 'AT', name: 'Austria', nameLocal: 'Österreich', currency: 'EUR' },
  { code: 'AU', name: 'Australia', currency: 'AUD' },
  { code: 'AZ', name: 'Azerbaijan', nameLocal: 'Azərbaycan', currency: 'AZN' },
  { code: 'BA', name: 'Bosnia and Herzegovina', nameLocal: 'Bosna i Hercegovina', currency: 'BAM' },
  { code: 'BB', name: 'Barbados', currency: 'BBD' },
  { code: 'BD', name: 'Bangladesh', nameLocal: 'বাংলাদেশ', currency: 'BDT' },
  { code: 'BE', name: 'Belgium', nameLocal: 'België', currency: 'EUR' },
  { code: 'BF', name: 'Burkina Faso', currency: 'XOF' },
  { code: 'BG', name: 'Bulgaria', nameLocal: 'България', currency: 'EUR' },
  { code: 'BH', name: 'Bahrain', nameLocal: 'البحرين', currency: 'BHD' },
  { code: 'BI', name: 'Burundi', currency: 'BIF' },
  { code: 'BJ', name: 'Benin', nameLocal: 'Bénin', currency: 'XOF' },
  { code: 'BN', name: 'Brunei', currency: 'BND' },
  { code: 'BO', name: 'Bolivia', currency: 'BOB' },
  { code: 'BR', name: 'Brazil', nameLocal: 'Brasil', currency: 'BRL' },
  { code: 'BS', name: 'Bahamas', currency: 'BSD' },
  { code: 'BT', name: 'Bhutan', currency: 'BTN' },
  { code: 'BW', name: 'Botswana', currency: 'BWP' },
  { code: 'BY', name: 'Belarus', nameLocal: 'Беларусь', currency: 'BYN' },
  { code: 'BZ', name: 'Belize', currency: 'BZD' },
  { code: 'CA', name: 'Canada', currency: 'CAD' },
  { code: 'CD', name: 'DR Congo', currency: 'CDF' },
  { code: 'CF', name: 'Central African Republic', currency: 'XAF' },
  { code: 'CG', name: 'Republic of the Congo', currency: 'XAF' },
  { code: 'CH', name: 'Switzerland', nameLocal: 'Schweiz', currency: 'CHF' },
  { code: 'CI', name: 'Ivory Coast', nameLocal: "Côte d'Ivoire", currency: 'XOF' },
  { code: 'CL', name: 'Chile', currency: 'CLP' },
  { code: 'CM', name: 'Cameroon', nameLocal: 'Cameroun', currency: 'XAF' },
  { code: 'CN', name: 'China', nameLocal: '中国', currency: 'CNY' },
  { code: 'CO', name: 'Colombia', currency: 'COP' },
  { code: 'CR', name: 'Costa Rica', currency: 'CRC' },
  { code: 'CU', name: 'Cuba', currency: 'CUP' },
  { code: 'CV', name: 'Cape Verde', nameLocal: 'Cabo Verde', currency: 'CVE' },
  { code: 'CY', name: 'Cyprus', nameLocal: 'Κύπρος', currency: 'EUR' },
  { code: 'CZ', name: 'Czechia', nameLocal: 'Česko', currency: 'CZK' },
  { code: 'DE', name: 'Germany', nameLocal: 'Deutschland', currency: 'EUR' },
  { code: 'DJ', name: 'Djibouti', currency: 'DJF' },
  { code: 'DK', name: 'Denmark', nameLocal: 'Danmark', currency: 'DKK' },
  { code: 'DM', name: 'Dominica', currency: 'XCD' },
  { code: 'DO', name: 'Dominican Republic', nameLocal: 'República Dominicana', currency: 'DOP' },
  { code: 'DZ', name: 'Algeria', nameLocal: 'الجزائر', currency: 'DZD' },
  { code: 'EC', name: 'Ecuador', currency: 'USD' },
  { code: 'EE', name: 'Estonia', nameLocal: 'Eesti', currency: 'EUR' },
  { code: 'EG', name: 'Egypt', nameLocal: 'مصر', currency: 'EGP' },
  { code: 'ER', name: 'Eritrea', currency: 'ERN' },
  { code: 'ES', name: 'Spain', nameLocal: 'España', currency: 'EUR' },
  { code: 'ET', name: 'Ethiopia', nameLocal: 'ኢትዮጵያ', currency: 'ETB' },
  { code: 'FI', name: 'Finland', nameLocal: 'Suomi', currency: 'EUR' },
  { code: 'FJ', name: 'Fiji', currency: 'FJD' },
  { code: 'FR', name: 'France', currency: 'EUR' },
  { code: 'GA', name: 'Gabon', currency: 'XAF' },
  { code: 'GB', name: 'United Kingdom', currency: 'GBP' },
  { code: 'GD', name: 'Grenada', currency: 'XCD' },
  { code: 'GE', name: 'Georgia', nameLocal: 'საქართველო', currency: 'GEL' },
  { code: 'GH', name: 'Ghana', currency: 'GHS' },
  { code: 'GM', name: 'Gambia', currency: 'GMD' },
  { code: 'GN', name: 'Guinea', nameLocal: 'Guinée', currency: 'GNF' },
  { code: 'GQ', name: 'Equatorial Guinea', currency: 'XAF' },
  { code: 'GR', name: 'Greece', nameLocal: 'Ελλάδα', currency: 'EUR' },
  { code: 'GT', name: 'Guatemala', currency: 'GTQ' },
  { code: 'GW', name: 'Guinea-Bissau', currency: 'XOF' },
  { code: 'GY', name: 'Guyana', currency: 'GYD' },
  { code: 'HK', name: 'Hong Kong', nameLocal: '香港', currency: 'HKD' },
  { code: 'HN', name: 'Honduras', currency: 'HNL' },
  { code: 'HR', name: 'Croatia', nameLocal: 'Hrvatska', currency: 'EUR' },
  { code: 'HT', name: 'Haiti', currency: 'HTG' },
  { code: 'HU', name: 'Hungary', nameLocal: 'Magyarország', currency: 'HUF' },
  { code: 'ID', name: 'Indonesia', currency: 'IDR' },
  { code: 'IE', name: 'Ireland', nameLocal: 'Éire', currency: 'EUR' },
  { code: 'IL', name: 'Israel', nameLocal: 'ישראל', currency: 'ILS' },
  { code: 'IN', name: 'India', nameLocal: 'भारत', currency: 'INR' },
  { code: 'IQ', name: 'Iraq', nameLocal: 'العراق', currency: 'IQD' },
  { code: 'IR', name: 'Iran', nameLocal: 'ایران', currency: 'IRR' },
  { code: 'IS', name: 'Iceland', nameLocal: 'Ísland', currency: 'ISK' },
  { code: 'IT', name: 'Italy', nameLocal: 'Italia', currency: 'EUR' },
  { code: 'JM', name: 'Jamaica', currency: 'JMD' },
  { code: 'JO', name: 'Jordan', nameLocal: 'الأردن', currency: 'JOD' },
  { code: 'JP', name: 'Japan', nameLocal: '日本', currency: 'JPY' },
  { code: 'KE', name: 'Kenya', currency: 'KES' },
  { code: 'KG', name: 'Kyrgyzstan', nameLocal: 'Кыргызстан', currency: 'KGS' },
  { code: 'KH', name: 'Cambodia', nameLocal: 'កម្ពុជា', currency: 'KHR' },
  { code: 'KP', name: 'North Korea', currency: 'KPW' },
  { code: 'KR', name: 'South Korea', nameLocal: '대한민국', currency: 'KRW' },
  { code: 'KW', name: 'Kuwait', nameLocal: 'الكويت', currency: 'KWD' },
  { code: 'KZ', name: 'Kazakhstan', nameLocal: 'Қазақстан', currency: 'KZT' },
  { code: 'LA', name: 'Laos', currency: 'LAK' },
  { code: 'LB', name: 'Lebanon', nameLocal: 'لبنان', currency: 'LBP' },
  { code: 'LI', name: 'Liechtenstein', currency: 'CHF' },
  { code: 'LK', name: 'Sri Lanka', currency: 'LKR' },
  { code: 'LR', name: 'Liberia', currency: 'LRD' },
  { code: 'LS', name: 'Lesotho', currency: 'LSL' },
  { code: 'LT', name: 'Lithuania', nameLocal: 'Lietuva', currency: 'EUR' },
  { code: 'LU', name: 'Luxembourg', currency: 'EUR' },
  { code: 'LV', name: 'Latvia', nameLocal: 'Latvija', currency: 'EUR' },
  { code: 'LY', name: 'Libya', nameLocal: 'ليبيا', currency: 'LYD' },
  { code: 'MA', name: 'Morocco', nameLocal: 'المغرب', currency: 'MAD' },
  { code: 'MC', name: 'Monaco', currency: 'EUR' },
  { code: 'MD', name: 'Moldova', currency: 'MDL' },
  { code: 'ME', name: 'Montenegro', nameLocal: 'Crna Gora', currency: 'EUR' },
  { code: 'MG', name: 'Madagascar', currency: 'MGA' },
  { code: 'MK', name: 'North Macedonia', nameLocal: 'Северна Македонија', currency: 'MKD' },
  { code: 'ML', name: 'Mali', currency: 'XOF' },
  { code: 'MM', name: 'Myanmar', currency: 'MMK' },
  { code: 'MN', name: 'Mongolia', nameLocal: 'Монгол улс', currency: 'MNT' },
  { code: 'MO', name: 'Macao', nameLocal: '澳門', currency: 'MOP' },
  { code: 'MR', name: 'Mauritania', nameLocal: 'موريتانيا', currency: 'MRU' },
  { code: 'MT', name: 'Malta', currency: 'EUR' },
  { code: 'MU', name: 'Mauritius', currency: 'MUR' },
  { code: 'MV', name: 'Maldives', currency: 'MVR' },
  { code: 'MW', name: 'Malawi', currency: 'MWK' },
  { code: 'MX', name: 'Mexico', nameLocal: 'México', currency: 'MXN' },
  { code: 'MY', name: 'Malaysia', currency: 'MYR' },
  { code: 'MZ', name: 'Mozambique', nameLocal: 'Moçambique', currency: 'MZN' },
  { code: 'NA', name: 'Namibia', currency: 'NAD' },
  { code: 'NE', name: 'Niger', currency: 'XOF' },
  { code: 'NG', name: 'Nigeria', currency: 'NGN' },
  { code: 'NI', name: 'Nicaragua', currency: 'NIO' },
  { code: 'NL', name: 'Netherlands', nameLocal: 'Nederland', currency: 'EUR' },
  { code: 'NO', name: 'Norway', nameLocal: 'Norge', currency: 'NOK' },
  { code: 'NP', name: 'Nepal', nameLocal: 'नेपाल', currency: 'NPR' },
  { code: 'NZ', name: 'New Zealand', currency: 'NZD' },
  { code: 'OM', name: 'Oman', nameLocal: 'عمان', currency: 'OMR' },
  { code: 'PA', name: 'Panama', currency: 'PAB' },
  { code: 'PE', name: 'Peru', currency: 'PEN' },
  { code: 'PG', name: 'Papua New Guinea', currency: 'PGK' },
  { code: 'PH', name: 'Philippines', currency: 'PHP' },
  { code: 'PK', name: 'Pakistan', currency: 'PKR' },
  { code: 'PL', name: 'Poland', nameLocal: 'Polska', currency: 'PLN' },
  { code: 'PS', name: 'Palestine', nameLocal: 'فلسطين', currency: 'ILS' },
  { code: 'PT', name: 'Portugal', currency: 'EUR' },
  { code: 'PY', name: 'Paraguay', currency: 'PYG' },
  { code: 'QA', name: 'Qatar', nameLocal: 'قطر', currency: 'QAR' },
  { code: 'RO', name: 'Romania', nameLocal: 'România', currency: 'RON' },
  { code: 'RS', name: 'Serbia', nameLocal: 'Србија', currency: 'RSD' },
  { code: 'RU', name: 'Russia', nameLocal: 'Россия', currency: 'RUB' },
  { code: 'RW', name: 'Rwanda', currency: 'RWF' },
  { code: 'SA', name: 'Saudi Arabia', nameLocal: 'السعودية', currency: 'SAR' },
  { code: 'SB', name: 'Solomon Islands', currency: 'SBD' },
  { code: 'SC', name: 'Seychelles', currency: 'SCR' },
  { code: 'SD', name: 'Sudan', nameLocal: 'السودان', currency: 'SDG' },
  { code: 'SE', name: 'Sweden', nameLocal: 'Sverige', currency: 'SEK' },
  { code: 'SG', name: 'Singapore', currency: 'SGD' },
  { code: 'SI', name: 'Slovenia', nameLocal: 'Slovenija', currency: 'EUR' },
  { code: 'SK', name: 'Slovakia', nameLocal: 'Slovensko', currency: 'EUR' },
  { code: 'SL', name: 'Sierra Leone', currency: 'SLL' },
  { code: 'SM', name: 'San Marino', currency: 'EUR' },
  { code: 'SN', name: 'Senegal', nameLocal: 'Sénégal', currency: 'XOF' },
  { code: 'SO', name: 'Somalia', currency: 'SOS' },
  { code: 'SR', name: 'Suriname', currency: 'SRD' },
  { code: 'SS', name: 'South Sudan', currency: 'SSP' },
  { code: 'SV', name: 'El Salvador', currency: 'USD' },
  { code: 'SY', name: 'Syria', nameLocal: 'سوريا', currency: 'SYP' },
  { code: 'SZ', name: 'Eswatini', currency: 'SZL' },
  { code: 'TD', name: 'Chad', nameLocal: 'Tchad', currency: 'XAF' },
  { code: 'TG', name: 'Togo', currency: 'XOF' },
  { code: 'TH', name: 'Thailand', nameLocal: 'ประเทศไทย', currency: 'THB' },
  { code: 'TJ', name: 'Tajikistan', nameLocal: 'Тоҷикистон', currency: 'TJS' },
  { code: 'TL', name: 'Timor-Leste', currency: 'USD' },
  { code: 'TM', name: 'Turkmenistan', currency: 'TMT' },
  { code: 'TN', name: 'Tunisia', nameLocal: 'تونس', currency: 'TND' },
  { code: 'TR', name: 'Türkiye', currency: 'TRY' },
  { code: 'TT', name: 'Trinidad and Tobago', currency: 'TTD' },
  { code: 'TW', name: 'Taiwan', nameLocal: '台灣', currency: 'TWD' },
  { code: 'TZ', name: 'Tanzania', currency: 'TZS' },
  { code: 'UA', name: 'Ukraine', nameLocal: 'Україна', currency: 'UAH' },
  { code: 'UG', name: 'Uganda', currency: 'UGX' },
  { code: 'US', name: 'United States', currency: 'USD' },
  { code: 'UY', name: 'Uruguay', currency: 'UYU' },
  { code: 'UZ', name: 'Uzbekistan', nameLocal: "O'zbekiston", currency: 'UZS' },
  { code: 'VE', name: 'Venezuela', currency: 'VES' },
  { code: 'VN', name: 'Vietnam', nameLocal: 'Việt Nam', currency: 'VND' },
  { code: 'YE', name: 'Yemen', nameLocal: 'اليمن', currency: 'YER' },
  { code: 'ZA', name: 'South Africa', currency: 'ZAR' },
  { code: 'ZM', name: 'Zambia', currency: 'ZMW' },
  { code: 'ZW', name: 'Zimbabwe', currency: 'ZWL' },
];

const BY_CODE: Record<string, Country> = (() => {
  const map: Record<string, Country> = {};
  for (const c of COUNTRIES) map[c.code] = c;
  return map;
})();

/** Return the country entry for an ISO alpha-2 code, or null if unknown. */
export function getCountry(code: string | null | undefined): Country | null {
  if (!code) return null;
  return BY_CODE[code.toUpperCase()] ?? null;
}

/** Alphabetically sorted (by English name) snapshot of COUNTRIES. */
export function sortedCountries(): Country[] {
  return [...COUNTRIES].sort((a, b) => a.name.localeCompare(b.name));
}

/**
 * Build a flag emoji from an ISO alpha-2 code by mapping each letter to
 * its regional-indicator codepoint.
 *
 * NOTE: Windows ships no flag-emoji glyphs in any system font, so the
 * returned string may render as literal "DE"/"US" text. Use the
 * <CountryFlag /> component for guaranteed-visible SVG flags. This
 * helper exists for plain-text contexts (search input value, ARIA
 * label, search index).
 */
export function countryFlagEmoji(code: string | null | undefined): string {
  if (!code) return '';
  const upper = code.toUpperCase();
  if (upper.length !== 2 || !/^[A-Z]{2}$/.test(upper)) return '';
  const A = 0x1f1e6;
  return String.fromCodePoint(A + upper.charCodeAt(0) - 65, A + upper.charCodeAt(1) - 65);
}

/**
 * Build the unicode flag emoji as a span. Use when the consumer needs
 * the result rendered (vs. raw text).
 */
export function formatCountryLabel(c: Country): string {
  if (c.nameLocal && c.nameLocal !== c.name) {
    return `${c.name} (${c.nameLocal})`;
  }
  return c.name;
}

/** Lowercase string with diacritics stripped — used for fuzzy search. */
function normalize(s: string): string {
  return s
    .toLowerCase()
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '');
}

/** Filter countries by free-text query against code, English name, and local-script name. */
export function filterCountries(query: string, limit = 50): Country[] {
  const q = normalize(query.trim());
  if (!q) return sortedCountries().slice(0, limit);
  const out: Array<{ c: Country; rank: number }> = [];
  for (const c of COUNTRIES) {
    const codeLc = c.code.toLowerCase();
    if (codeLc === q) {
      out.push({ c, rank: 0 });
      continue;
    }
    const en = normalize(c.name);
    const local = c.nameLocal ? normalize(c.nameLocal) : '';
    if (en.startsWith(q) || local.startsWith(q)) {
      out.push({ c, rank: 1 });
      continue;
    }
    if (en.includes(q) || local.includes(q) || codeLc.includes(q)) {
      out.push({ c, rank: 2 });
    }
  }
  out.sort((a, b) => {
    if (a.rank !== b.rank) return a.rank - b.rank;
    return a.c.name.localeCompare(b.c.name);
  });
  return out.slice(0, limit).map((x) => x.c);
}
