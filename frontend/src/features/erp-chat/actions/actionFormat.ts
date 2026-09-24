// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Reading, editing and comparing proposal field values.
 *
 * Display goes through the app's shared formatters so a quantity, an amount or
 * a date on a proposal card reads exactly like the same value in the BOQ or
 * the schedule: the reader's number locale, the currency's own minor units,
 * the reader's date preference. Nothing here calls `toFixed` on a value a
 * person will read.
 *
 * Editing works on CANONICAL strings (digits and a point), never on a grouped
 * display string: a grouped "1,234.50" handed back to a parser is how totals
 * got truncated at the thousands separator (#466). Input is parsed with the
 * shared tolerant parsers, so "1.234,5" and "1,234.5" both mean 1234.5.
 */
import type { TFunction } from 'i18next';
import { formatCurrency } from '@/shared/lib/money';
import { formatValue } from '@/shared/lib/numberFormat';
import { fmtDate, fmtPercent, formatDateWithPreference, getDateFormatPreference } from '@/shared/lib/formatters';
import { getIntlLocale } from '@/shared/lib/intlLocale';
import { parseDecimalInput, parseMoneyInput, normalizeDecimalSeparators } from '@/shared/lib/parseDecimal';
import { localizedUnitCode } from '@/shared/lib/unitLabels';
import type { ActionField, ActionFieldOption } from './types';

/** Placeholder shown for an empty value. */
export const EMPTY_VALUE = '—';

/** A finite number from a wire value, or null. Unlike `toNum`, never invents 0. */
export function toNumberOrNull(v: unknown): number | null {
  if (typeof v === 'number') return Number.isFinite(v) ? v : null;
  if (typeof v === 'string' && v.trim() !== '') {
    const n = Number(v);
    return Number.isFinite(n) ? n : null;
  }
  return null;
}

function isBlank(v: unknown): boolean {
  return v === null || v === undefined || (typeof v === 'string' && v.trim() === '');
}

/** Label of an enum option in the reader's language. */
export function optionLabel(option: ActionFieldOption, t: TFunction): string {
  const fallback = option.label ?? option.value;
  return option.label_key ? String(t(option.label_key, { defaultValue: fallback })) : fallback;
}

/** Label of a field in the reader's language. */
export function fieldLabel(field: ActionField, t: TFunction): string {
  return field.label_key ? String(t(field.label_key, { defaultValue: field.label })) : field.label;
}

/** Text and optional link of a `ref` value. */
export function refParts(v: unknown): { label: string; url: string | null } | null {
  if (isBlank(v)) return null;
  if (typeof v === 'object' && v !== null) {
    const r = v as Record<string, unknown>;
    const label =
      (typeof r.label === 'string' && r.label) ||
      (typeof r.name === 'string' && r.name) ||
      (typeof r.title === 'string' && r.title) ||
      (typeof r.id === 'string' && r.id) ||
      '';
    const url = typeof r.url === 'string' && r.url ? r.url : null;
    return label ? { label, url } : null;
  }
  return { label: String(v), url: null };
}

/** Up to three decimals, trailing zeros trimmed: 120, 12.5, 0.125. */
function formatPlainNumber(n: number): string {
  return formatValue(n, 'number', { minimumFractionDigits: 0, maximumFractionDigits: 3 });
}

/**
 * The value as a reader sees it. `lang` is the active UI language, used for
 * the locale's trade spelling of a unit (`m3` -> `m³`, `pcs` -> `Stk` in German).
 */
export function formatFieldValue(field: ActionField, value: unknown, t: TFunction, lang: string): string {
  if (isBlank(value)) return EMPTY_VALUE;
  switch (field.kind) {
    case 'number': {
      const n = toNumberOrNull(value);
      if (n === null) return String(value);
      const unit = field.unit ? localizedUnitCode(field.unit, lang) : '';
      return unit ? `${formatPlainNumber(n)} ${unit}` : formatPlainNumber(n);
    }
    case 'money': {
      const n = toNumberOrNull(value);
      if (n === null) return String(value);
      return formatCurrency(n, field.currency ?? undefined);
    }
    case 'percent': {
      const n = toNumberOrNull(value);
      if (n === null) return String(value);
      return fmtPercent(n, Number.isInteger(n) ? 0 : 1);
    }
    case 'date': {
      const s = String(value);
      const day = /^\d{4}-\d{2}-\d{2}/.test(s) ? s.slice(0, 10) : s;
      const parsed = new Date(day);
      return Number.isNaN(parsed.getTime()) ? s : fmtDate(day);
    }
    case 'enum': {
      const hit = (field.options ?? []).find((o) => o.value === String(value));
      return hit ? optionLabel(hit, t) : String(value);
    }
    case 'ref': {
      return refParts(value)?.label ?? EMPTY_VALUE;
    }
    default: {
      if (typeof value === 'boolean') {
        return value
          ? String(t('erp_chat.action.value.yes', { defaultValue: 'Yes' }))
          : String(t('erp_chat.action.value.no', { defaultValue: 'No' }));
      }
      if (typeof value === 'object') return refParts(value)?.label ?? EMPTY_VALUE;
      return String(value);
    }
  }
}

/**
 * True when two wire values mean the same thing for a field. Numbers compare
 * numerically so "80.00" and 80 are equal; dates compare by day.
 */
export function sameFieldValue(field: ActionField, a: unknown, b: unknown): boolean {
  if (isBlank(a) && isBlank(b)) return true;
  if (isBlank(a) !== isBlank(b)) return false;
  if (field.kind === 'number' || field.kind === 'money' || field.kind === 'percent') {
    const x = toNumberOrNull(a);
    const y = toNumberOrNull(b);
    if (x !== null && y !== null) return x === y;
  }
  if (field.kind === 'date') return String(a).slice(0, 10) === String(b).slice(0, 10);
  if (typeof a === 'object' || typeof b === 'object') return JSON.stringify(a) === JSON.stringify(b);
  return String(a) === String(b);
}

/** True when the field changes an existing value (an edit, not a create). */
export function isChangedField(field: ActionField): boolean {
  return !isBlank(field.before) && !sameFieldValue(field, field.before, field.value);
}

/** Canonical editing string for a field's current value. */
export function draftFromValue(field: ActionField): string {
  const v = field.value;
  if (isBlank(v)) return '';
  switch (field.kind) {
    case 'number':
    case 'money':
    case 'percent': {
      if (typeof v === 'number') return Number.isFinite(v) ? String(v) : '';
      const s = String(v).trim();
      return parseDecimalInput(s) === null ? s : normalizeDecimalSeparators(s);
    }
    case 'date':
      return String(v).slice(0, 10);
    case 'ref':
      return refParts(v)?.label ?? '';
    default:
      return typeof v === 'object' ? JSON.stringify(v) : String(v);
  }
}

export type DraftError = 'required' | 'number' | 'date';

export type ParsedDraft = { ok: true; value: unknown } | { ok: false; error: DraftError };

/**
 * Turn what the person typed back into a wire value of the field's type.
 *
 * Money keeps the wire type it arrived in: a Decimal string stays a canonical
 * string (`"1234.5"`), a number stays a number. Text is trimmed. An empty
 * optional field becomes `null`, which is how a person clears it.
 */
export function parseDraft(field: ActionField, draft: string): ParsedDraft {
  const raw = draft.trim();
  if (raw === '') {
    return field.required ? { ok: false, error: 'required' } : { ok: true, value: null };
  }
  switch (field.kind) {
    case 'number':
    case 'percent': {
      const n = parseDecimalInput(raw);
      return n === null ? { ok: false, error: 'number' } : { ok: true, value: n };
    }
    case 'money': {
      const n = parseMoneyInput(raw);
      if (n === null) return { ok: false, error: 'number' };
      return typeof field.value === 'string' ? { ok: true, value: String(n) } : { ok: true, value: n };
    }
    case 'date':
      return /^\d{4}-\d{2}-\d{2}$/.test(raw) ? { ok: true, value: raw } : { ok: false, error: 'date' };
    default:
      return { ok: true, value: raw };
  }
}

// ── Time ────────────────────────────────────────────────────────────────────

function toDate(iso: string | null | undefined): Date | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? null : d;
}

function sameLocalDay(a: Date, b: Date): boolean {
  return a.getFullYear() === b.getFullYear() && a.getMonth() === b.getMonth() && a.getDate() === b.getDate();
}

/** Stable key of the local calendar day of a timestamp (`2026-09-23`). */
export function dayKey(iso: string | null | undefined): string {
  const d = toDate(iso);
  if (!d) return 'unknown';
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}-${m}-${day}`;
}

/**
 * When something happened, as short as it can be while staying unambiguous:
 * the time alone today, the date and time on any other day.
 */
export function formatActionTime(iso: string | null | undefined, now: Date = new Date()): string {
  const d = toDate(iso);
  if (!d) return '';
  const locale = getIntlLocale();
  if (sameLocalDay(d, now)) {
    return new Intl.DateTimeFormat(locale, { hour: '2-digit', minute: '2-digit' }).format(d);
  }
  const sameYear = d.getFullYear() === now.getFullYear();
  const options: Intl.DateTimeFormatOptions = sameYear
    ? { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }
    : { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' };
  try {
    return formatDateWithPreference(d, locale, options, getDateFormatPreference());
  } catch {
    return d.toLocaleString(locale);
  }
}

/** Heading of a day group: Today, Yesterday, or the weekday and date. */
export function formatDayHeading(iso: string | null | undefined, t: TFunction, now: Date = new Date()): string {
  const d = toDate(iso);
  if (!d) return String(t('erp_chat.changes.day_unknown', { defaultValue: 'Earlier' }));
  if (sameLocalDay(d, now)) return String(t('erp_chat.changes.today', { defaultValue: 'Today' }));
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameLocalDay(d, yesterday)) return String(t('erp_chat.changes.yesterday', { defaultValue: 'Yesterday' }));
  const options: Intl.DateTimeFormatOptions =
    d.getFullYear() === now.getFullYear()
      ? { weekday: 'long', day: 'numeric', month: 'long' }
      : { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' };
  return new Intl.DateTimeFormat(getIntlLocale(), options).format(d);
}
