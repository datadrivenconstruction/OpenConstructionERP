// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The course locale, which is not the UI locale.
//
// Course content (title, brief, steps, options, feedback, diagnoses) is
// written in the course language and rendered under the course locale: its
// container carries `lang` and `dir` for that language. Chrome (buttons,
// headings, status words) follows the UI language through `t()`. Nothing here
// ever switches the UI language (founder Q5).
//
// Number entry is parsed under the course locale's separators, and the result
// is a decimal STRING ("3581310.00"). It never passes through `Number`, so no
// float rounding reaches the server. Input whose grouping does not fit the
// locale is refused, not guessed: under `de`, "3581310.00" is a misgrouped
// number, and reading it as 358131000 would be a silent hundredfold error.

import type { CourseInfo } from './types';

const RTL_LANGUAGES = new Set(['ar', 'he', 'iw', 'fa', 'ur', 'ps', 'yi', 'dv', 'ckb', 'sd', 'ug']);

function canonical(tag: string): string | null {
  try {
    return Intl.getCanonicalLocales(tag)[0] ?? null;
  } catch {
    return null;
  }
}

/**
 * The locale course content renders in: `course.locale` when it is a valid
 * tag, else `language-country`, else the bare language, else `en`.
 */
export function courseLocaleOf(course: Pick<CourseInfo, 'locale' | 'language' | 'country'>): string {
  const candidates = [course.locale, `${course.language}-${course.country}`, course.language];
  for (const candidate of candidates) {
    if (!candidate) continue;
    const tag = canonical(candidate);
    if (tag) return tag;
  }
  return 'en';
}

/** The primary language subtag: `en-GB` -> `en`. */
export function baseLanguage(locale: string): string {
  return (locale.split(/[-_]/, 1)[0] ?? '').toLowerCase();
}

/** Writing direction of a locale, for the `dir` attribute on course content. */
export function courseDir(locale: string): 'ltr' | 'rtl' {
  return RTL_LANGUAGES.has(baseLanguage(locale)) ? 'rtl' : 'ltr';
}

/** True when the course and the UI share a language (regions may differ). */
export function sameLanguage(courseLocale: string, uiLocale: string): boolean {
  return baseLanguage(courseLocale) === baseLanguage(uiLocale);
}

/**
 * The course language's name in the UI language, for
 * `trainer.panel.course_language_note`. Falls back to the tag itself.
 */
export function courseLanguageName(courseLocale: string, uiLocale: string): string {
  try {
    return new Intl.DisplayNames([uiLocale], { type: 'language' }).of(baseLanguage(courseLocale)) ?? courseLocale;
  } catch {
    return courseLocale;
  }
}

// ── Number entry ────────────────────────────────────────────────────────────

export interface NumberSeparators {
  /** Thousands separator as Intl writes it (may be U+00A0 or U+202F). */
  group: string;
  decimal: string;
  /** Size of the groups between the first and the last: 3, or 2 for Indian grouping. */
  middleGroupSize: number;
  /** The locale's own digits 0-9 when it writes non-Latin ones (ar-EG, fa). */
  digits: string[] | null;
}

const separatorCache = new Map<string, NumberSeparators>();

/** Separators read from `Intl.NumberFormat(locale).formatToParts(1234567.5)`. */
export function numberSeparators(locale: string): NumberSeparators {
  const cached = separatorCache.get(locale);
  if (cached) return cached;
  let parts: Intl.NumberFormatPart[];
  try {
    parts = new Intl.NumberFormat(locale).formatToParts(1234567.5);
  } catch {
    parts = new Intl.NumberFormat('en').formatToParts(1234567.5);
  }
  const integers = parts.filter((p) => p.type === 'integer').map((p) => p.value);
  const group = parts.find((p) => p.type === 'group')?.value ?? ',';
  const decimal = parts.find((p) => p.type === 'decimal')?.value ?? '.';
  const middleGroupSize = integers.length > 2 ? (integers[1]?.length ?? 3) : 3;
  let digits: string[] | null = null;
  try {
    const zeroToNine = new Intl.NumberFormat(locale, { useGrouping: false }).format(1234567890);
    if (!/^[0-9]+$/.test(zeroToNine)) {
      const chars = Array.from(zeroToNine);
      // "1234567890" -> positions of 1..9 then 0
      digits = [chars[9] ?? '0', ...chars.slice(0, 9)];
    }
  } catch {
    digits = null;
  }
  const result = { group, decimal, middleGroupSize, digits };
  separatorCache.set(locale, result);
  return result;
}

const WHITESPACE = /[\s\u00a0\u202f\u2009\u2007]/;
const APOSTROPHES = /['\u2019\u02bc]/;
const MINUS = /^[-\u2212\u2012\u2013]/;

function isGroupChar(ch: string, group: string): boolean {
  if (ch === group) return true;
  if (WHITESPACE.test(ch)) return true;
  return APOSTROPHES.test(group) && APOSTROPHES.test(ch);
}

/**
 * Parse what a learner typed into a decimal string, under the course locale.
 *
 * Accepted: the locale's group and decimal separators, any space as a group
 * separator, a leading minus or plus, a currency symbol or ISO code and a
 * percent sign around the number, and the locale's own digits. The grouping
 * must fit the locale: first group 1-3 digits, middle groups 3 (2 in Indian
 * grouping), last group 3. Returns null when the input does not read as a
 * number under these rules.
 *
 * @example parseCourseNumber('3.581.310,00', 'de-DE') === '3581310.00'
 * @example parseCourseNumber('3581310.00', 'de-DE') === null
 */
export function parseCourseNumber(input: string, locale: string): string | null {
  const sep = numberSeparators(locale);
  let text = input.trim();
  if (sep.digits) {
    const native = sep.digits;
    text = Array.from(text, (ch) => {
      const i = native.indexOf(ch);
      return i >= 0 ? String(i) : ch;
    }).join('');
  }
  // Currency and percent decorations, either side.
  text = text
    .replace(/^[\p{Sc}]+|[\p{Sc}]+$/gu, '')
    .replace(/^[A-Z]{3}(?=[\s\u00a0\u202f\d+\-\u2212])|(?<=[\d\s\u00a0\u202f])[A-Z]{3}$/g, '')
    .replace(/%$/, '')
    .trim();

  let negative = false;
  if (MINUS.test(text)) {
    negative = true;
    text = text.slice(1);
  } else if (text.startsWith('+')) {
    text = text.slice(1);
  }
  // A currency symbol may sit after the sign: "-£12".
  text = text.replace(/^[\p{Sc}]+/u, '').trim();
  if (text.length === 0) return null;

  const decimalAt = text.lastIndexOf(sep.decimal);
  const intPart = decimalAt >= 0 ? text.slice(0, decimalAt) : text;
  const fracPart = decimalAt >= 0 ? text.slice(decimalAt + sep.decimal.length) : '';
  if (decimalAt >= 0 && fracPart.length === 0) return null;
  if (!/^[0-9]*$/.test(fracPart)) return null;

  // Split the integer part on group characters and validate the grouping.
  const groups: string[] = [];
  let current = '';
  for (const ch of intPart) {
    if (/[0-9]/.test(ch)) {
      current += ch;
    } else if (isGroupChar(ch, sep.group)) {
      groups.push(current);
      current = '';
    } else {
      return null;
    }
  }
  groups.push(current);
  if (groups.length > 1) {
    const first = groups[0] ?? '';
    const last = groups[groups.length - 1] ?? '';
    if (first.length < 1 || first.length > 3 || last.length !== 3) return null;
    for (const middle of groups.slice(1, -1)) {
      if (middle.length !== sep.middleGroupSize && middle.length !== 3) return null;
    }
  }
  const digits = groups.join('');
  if (digits.length === 0 && fracPart.length === 0) return null;

  const whole = digits.replace(/^0+(?=\d)/, '') || '0';
  const body = fracPart.length > 0 ? `${whole}.${fracPart}` : whole;
  const isZero = /^0(\.0*)?$/.test(body);
  return negative && !isZero ? `-${body}` : body;
}
