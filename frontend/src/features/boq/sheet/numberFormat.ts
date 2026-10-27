// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Locale​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ number separators for the BOQ sheet: read and write numbers the
 * way the user's spreadsheet does (1.234,56 in de, 1,234.56 in en, 1 234,56 in fr).
 */

export interface Separators {
  decimal: string;
  group: string;
}

const cache = new Map<string, Separators>();

/** Decimal and group separators of a BCP 47 locale, read from Intl. */
export function separatorsFor(locale: string): Separators {
  const hit = cache.get(locale);
  if (hit) return hit;
  let decimal = '.';
  let group = ',';
  try {
    for (const part of new Intl.NumberFormat(locale).formatToParts(1234567.5)) {
      if (part.type === 'decimal') decimal = part.value;
      if (part.type === 'group') group = part.value;
    }
  } catch {
    /* unknown locale: keep the defaults */
  }
  const out = { decimal, group };
  cache.set(locale, out);
  return out;
}

const BLANKS = /[\s\u00a0\u202f'\u2019]/g;

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/**
 * Parse a number typed or pasted in `locale`. Group separators are dropped,
 * the locale decimal becomes '.', currency signs and spaces are ignored.
 * A lone foreign separator that cannot be a group ("12.5" in de) is read as
 * the decimal, so a block copied from another locale still lands right.
 * Returns null when the text is not a number.
 */
export function parseLocaleNumber(raw: string, locale: string): number | null {
  const { decimal } = separatorsFor(locale);
  const group = separatorsFor(locale).group.replace(BLANKS, '');
  let s = raw.trim().replace(BLANKS, '').replace(/[^\d.,\-+eE]/g, '');
  if (!s || !/\d/.test(s)) return null;
  if (group && group !== decimal && s.includes(group)) {
    const intPart = s.split(decimal)[0] ?? '';
    const grouped = new RegExp(`^[-+]?\\d{1,3}(${escapeRe(group)}\\d{2,3})*${escapeRe(group)}\\d{3}$`);
    if (grouped.test(intPart)) s = s.split(group).join('');
    else if (!s.includes(decimal) && s.split(group).length === 2) s = s.replace(group, decimal);
    else return null;
  }
  if (decimal !== '.') s = s.split(decimal).join('.');
  if (!/^[-+]?(\d+\.?\d*|\.\d+)([eE][-+]?\d+)?$/.test(s)) return null;
  const n = Number(s);
  return Number.isFinite(n) ? n : null;
}

/** Format for display, with grouping, at most `maxFraction` decimals. */
export function formatLocaleNumber(n: number, locale: string, maxFraction = 4, minFraction = 0): string {
  return new Intl.NumberFormat(locale, {
    maximumFractionDigits: maxFraction,
    minimumFractionDigits: minFraction,
  }).format(n);
}

/** Format for the clipboard: locale decimal, no grouping, so any spreadsheet reads it back. */
export function formatClipboardNumber(n: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 10, useGrouping: false }).format(n);
}
