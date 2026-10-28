// DDC-CWICR-OE: DataDrivenConstruction - OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The parts of the logistics plan screens that are plain functions: which
// status a record can move to next, how a form becomes a request body, and
// how a code or a finding is put into words.

import type { BadgeVariant } from '@/shared/ui/Badge';

import type { Can, CatalogueEntry, LinkKind, CatalogueGroup, Finding, PlanCatalogue, Verdict, Violation } from './api';
import { instantOf, wallClock } from './siteTime';
import { isTextKey, served, tx, type TextKey, type TFn } from './texts';

/* ── Status moves ─────────────────────────────────────────────────────── */

export type Lifecycle = 'stage' | 'media' | 'transport' | 'permit' | 'customs' | 'document' | 'complaint';

/** The action exists but the server refuses it right now. Unknown counts as not refused. */
export function denied(verdict: Verdict | undefined): boolean {
  return !!verdict && !verdict.allowed;
}

/** The action does not exist for this record in its state. Unknown counts as existing. */
export function absent(verdict: Verdict | undefined): boolean {
  return !!verdict && !verdict.applies;
}

/**
 * Stands in for an answer that has not arrived yet: the button is there,
 * disabled and without a reason, and wakes up when the server has spoken.
 */
export const WAITING: Verdict = { allowed: false, applies: true, reason: null };

/** The action can be pressed: it exists and the server allows it. Unknown counts as allowed. */
export function offered(verdict: Verdict | undefined): boolean {
  return !denied(verdict) && !absent(verdict);
}

/**
 * The action belongs on the screen: it exists, and a refusal is about the record
 * and not about the reader lacking the right, which no button would change.
 */
export function shown(verdict: Verdict | undefined): boolean {
  return !absent(verdict) && !(denied(verdict) && verdict?.reason === 'permission_denied');
}

/** The fields of a record the server keeps as they are: from its verdicts, or from the record itself. */
export function frozenOf(record: object | null | undefined): string[] {
  const r = record as { can?: Can; frozen_fields?: string[] } | null | undefined;
  return r?.can?.frozen_fields ?? r?.frozen_fields ?? [];
}

/** Why the server refuses, in the reader's language; the code in plain words where no sentence is shipped. */
export function reasonText(t: TFn, verdict: Verdict | undefined): string | undefined {
  if (!verdict || verdict.allowed || !verdict.reason) return undefined;
  return served(t, `site_logistics.errors.${verdict.reason}`, humanise(verdict.reason));
}

const TONES: Record<string, BadgeVariant> = {
  planned: 'neutral',
  identified: 'neutral',
  draft: 'neutral',
  missing: 'warning',
  open: 'blue',
  received: 'blue',
  requested: 'blue',
  applied: 'blue',
  offered: 'purple',
  permit_pending: 'warning',
  held: 'warning',
  acknowledged: 'purple',
  documents_complete: 'purple',
  declared: 'purple',
  scheduled: 'purple',
  in_transit: 'purple',
  action_taken: 'purple',
  active: 'success',
  contracted: 'success',
  connected: 'success',
  granted: 'success',
  arrived: 'success',
  cleared: 'success',
  verified: 'success',
  refused: 'error',
  expired: 'error',
  cancelled: 'neutral',
  closed: 'neutral',
  disconnected: 'neutral',
};

export function stateTone(state: string): BadgeVariant {
  return TONES[state] ?? 'neutral';
}

/** A code nobody translated, made readable: `dirt_on_road` becomes `Dirt on road`. */
export function humanise(code: string): string {
  const words = code.replace(/_/g, ' ').trim();
  return words ? words.charAt(0).toUpperCase() + words.slice(1) : code;
}

export function stateLabel(t: TFn, state: string): string {
  const key = `state.${state}`;
  return isTextKey(key) ? tx(t, key) : humanise(state);
}

export function moveLabel(t: TFn, lifecycle: Lifecycle, target: string): string {
  const key = `move.${lifecycle}.${target}`;
  return isTextKey(key) ? tx(t, key) : stateLabel(t, target);
}

export function enumLabel(t: TFn, group: string, value: string | null | undefined): string {
  if (!value) return tx(t, 'not_set');
  const key = `enum.${group}.${value}`;
  return isTextKey(key) ? tx(t, key) : humanise(value);
}

/* ── Catalogue codes ──────────────────────────────────────────────────── */

export interface Words {
  t: TFn;
  language: string;
}

/**
 * The name of a catalogue code: the entry's own label in the reader's
 * language first (a tenant or national catalogue brings its own), then the
 * shipped translation, then the code made readable.
 */
export function codeLabel(
  words: Words,
  group: CatalogueGroup,
  code: string | null | undefined,
  catalogue?: PlanCatalogue | null,
): string {
  if (!code) return tx(words.t, 'not_set');
  const entry = (catalogue?.[group] as CatalogueEntry[] | undefined)?.find((e) => e.code === code);
  const own = entry?.labels;
  const short = words.language.split('-')[0] ?? 'en';
  const text = own?.[words.language] ?? own?.[short];
  if (text) return text;
  const key = `code.${group}.${code}`;
  if (isTextKey(key)) return tx(words.t, key);
  return own?.en ?? humanise(code);
}

export function codeOptions(
  words: Words,
  group: CatalogueGroup,
  catalogue: PlanCatalogue | null | undefined,
): { value: string; label: string }[] {
  const entries = (catalogue?.[group] as CatalogueEntry[] | undefined) ?? [];
  return entries.map((e) => ({ value: e.code, label: codeLabel(words, group, e.code, catalogue) }));
}

/* ── Findings ─────────────────────────────────────────────────────────── */

/** Params that carry a catalogue code and read better as its name. */
const PARAM_GROUP: Record<string, CatalogueGroup> = { media: 'media_kinds', kind: 'customs_document_kinds' };

export function findingText(words: Words, finding: Finding | Violation, catalogue?: PlanCatalogue | null): string {
  const key = `finding.${finding.code}`;
  if (!isTextKey(key)) return humanise(finding.code);
  const vars: Record<string, unknown> = {};
  for (const [name, value] of Object.entries(finding.params ?? {})) {
    const group = PARAM_GROUP[name];
    vars[name] = group && typeof value === 'string' ? codeLabel(words, group, value, catalogue) : value ?? '';
  }
  // A blocker of a refused move carries no params; an empty title would leave a dangling colon.
  const text = tx(words.t, key as TextKey, { title: '', ...vars });
  return text.replace(/^\s*:\s*/, '').replace(/^./, (c) => c.toUpperCase());
}

/* ── Forms ────────────────────────────────────────────────────────────── */

export type Option = { value: string; label: string };

interface FieldBase {
  name: string;
  label: TextKey;
  hint?: TextKey;
  required?: boolean;
  /** Take the full width of the form grid. */
  wide?: boolean;
}

export type Field =
  | (FieldBase & { kind: 'text' | 'textarea' | 'date' | 'datetime' | 'time' | 'decimal' | 'int' | 'checkbox' | 'person' })
  | (FieldBase & { kind: 'select' | 'multi'; options: Option[] })
  /** A record of the project, chosen from the list the server offers; never a typed id. */
  | (FieldBase & { kind: 'link'; link: LinkKind })
  | (FieldBase & { kind: 'rows'; columns: Field[] });

export type FormValue = string | boolean | string[] | FormValues[];
export interface FormValues {
  [name: string]: FormValue;
}

const DECIMAL = /^\d+(\.\d+)?$/;

function pad(n: number): string {
  return String(n).padStart(2, '0');
}

/** An ISO instant as the value of a `datetime-local` input, in the reader's own time. */
export function toLocalInput(iso: string | null | undefined): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function emptyOf(field: Field): FormValue {
  if (field.kind === 'checkbox') return false;
  if (field.kind === 'multi' || field.kind === 'rows') return [];
  return '';
}

/** The form's starting values from a record (or from nothing, for a new one). */
export function toFormValues(fields: Field[], record?: Record<string, unknown> | null, zone?: string | null): FormValues {
  const out: FormValues = {};
  for (const f of fields) {
    const raw = record?.[f.name];
    if (raw === null || raw === undefined) {
      out[f.name] = emptyOf(f);
    } else if (f.kind === 'checkbox') {
      out[f.name] = raw === true;
    } else if (f.kind === 'multi') {
      out[f.name] = Array.isArray(raw) ? raw.map(String) : [];
    } else if (f.kind === 'rows') {
      out[f.name] = Array.isArray(raw)
        ? raw.map((row) => toFormValues(f.columns, row as Record<string, unknown>))
        : [];
    } else if (f.kind === 'datetime') {
      out[f.name] = wallClock(String(raw), zone) ?? toLocalInput(String(raw));
    } else {
      out[f.name] = String(raw);
    }
  }
  return out;
}

function normalised(field: Field, value: FormValue): FormValue {
  if (typeof value !== 'string') return value;
  const text = value.trim();
  return field.kind === 'decimal' ? text.replace(',', '.') : text;
}

/** The name of every field the form cannot be sent with, and why. */
export function formProblems(fields: Field[], values: FormValues): Record<string, 'required' | 'number_invalid'> {
  const out: Record<string, 'required' | 'number_invalid'> = {};
  for (const f of fields) {
    const v = normalised(f, values[f.name] ?? emptyOf(f));
    if (f.kind === 'rows') {
      (v as FormValues[]).forEach((row, i) => {
        for (const [name, why] of Object.entries(formProblems(f.columns, row))) out[`${f.name}.${i}.${name}`] = why;
      });
      continue;
    }
    const blank = v === '' || (Array.isArray(v) && v.length === 0);
    if (f.required && blank && f.kind !== 'checkbox') out[f.name] = 'required';
    else if ((f.kind === 'decimal' || f.kind === 'int') && typeof v === 'string' && v !== '' && !DECIMAL.test(v)) {
      out[f.name] = 'number_invalid';
    }
  }
  return out;
}

function wire(field: Field, value: FormValue, zone?: string | null): unknown {
  if (field.kind === 'rows') return (value as FormValues[]).map((row) => toBody(field.columns, row));
  if (field.kind === 'multi') {
    // Weekdays travel as numbers; every other multi choice is a list of ids.
    const list = value as string[];
    return list.every((x) => /^\d$/.test(x)) && list.length > 0 ? list.map(Number) : list;
  }
  if (field.kind === 'checkbox') return value === true;
  const text = value as string;
  if (field.kind === 'text' || field.kind === 'textarea') return text;
  if (text === '') return null;
  if (field.kind === 'int') return Number(text);
  // On the site clock when the concept names a zone, else in the reader's own.
  if (field.kind === 'datetime') return instantOf(text, zone) ?? new Date(text).toISOString();
  return text;
}

/**
 * The request body of a form. For a new record an empty field is left out, so
 * the server applies its default. For an existing one only the fields that
 * changed are sent, and a cleared field is sent as empty: `null` for a
 * number, date or choice, an empty string for text.
 */
export function toBody(
  fields: Field[],
  values: FormValues,
  initial?: FormValues | null,
  zone?: string | null,
): Record<string, unknown> {
  const body: Record<string, unknown> = {};
  for (const f of fields) {
    const v = normalised(f, values[f.name] ?? emptyOf(f));
    const before = initial ? normalised(f, initial[f.name] ?? emptyOf(f)) : undefined;
    if (initial) {
      if (JSON.stringify(v) === JSON.stringify(before)) continue;
    } else if (v === '' || (Array.isArray(v) && v.length === 0)) {
      continue;
    } else if (f.kind === 'checkbox' && v === false) {
      continue;
    }
    body[f.name] = wire(f, v, zone);
  }
  return body;
}

/** How many decimals a decimal string really carries: `1250.00` has none, `12.50` has one, never more than three. */
export function decimalsOf(value: string | number | null | undefined): number {
  const text = String(value ?? '');
  const dot = text.indexOf('.');
  if (dot < 0) return 0;
  return Math.min(3, text.slice(dot + 1).replace(/0+$/, '').length);
}

/** Short weekday names for the reader's language, Monday first (the server counts Monday as 0). */
export function weekdayOptions(locale: string): Option[] {
  const fmt = new Intl.DateTimeFormat(locale, { weekday: 'short', timeZone: 'UTC' });
  // 2024-01-01 was a Monday.
  return Array.from({ length: 7 }, (_, i) => ({
    value: String(i),
    label: fmt.format(new Date(Date.UTC(2024, 0, 1 + i))),
  }));
}
