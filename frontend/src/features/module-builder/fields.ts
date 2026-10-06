// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Turning a module specification into form values, request bodies and findings.
 *
 * Everything here is pure. The renderer that uses it is a React component and
 * hard to reason about; the rules for what a `money` field puts on the wire are
 * not, and they are where a generic screen gets things quietly wrong, so they
 * live on their own and are tested on their own.
 *
 * Three decisions worth stating, because each of them looks like an oversight
 * until you know why:
 *
 * **Money and quantities never become a JS number.** The generated schema types
 * them as `Decimal`; Pydantic serialises that as a JSON string and parses a
 * string back. A double cannot hold 0.1, so a round trip through `Number()`
 * turns an exact contract sum into an approximate one. The form value is a
 * string, the payload is a string, and only the *rendering* goes through the
 * platform's shared number formatter.
 *
 * **A `datetime` goes on the wire with its time zone.** `<input
 * type="datetime-local">` yields a naive local time, and the generated
 * validator reads a naive datetime as UTC. Send the naive string and a user two
 * hours east of UTC has "now" refused as being in the future. Converting to a
 * full instant here makes the value mean the same thing on both sides.
 *
 * **Findings are evaluated twice, on purpose, and the server wins.** These
 * checks read the same `rules` the server generated its validator from, so they
 * are a second reader of one source rather than a second copy of the rules.
 * They exist so a typo is answered before the round trip; a write is still
 * refused by the module's own validator, and its findings are what the user
 * finally sees.
 */
import { fmtDate, fmtNumber, getIntlLocale } from '@/shared/lib/formatters';

import type { GeneratedRecord, ModuleFieldSpec, ModuleSpec, ModuleStateSpec } from './api';

/**
 * The form value the status feature uses. `status` is a reserved field name
 * while the feature is on, so it cannot collide with one of the user's fields.
 */
export const STATUS_KEY = 'status';

/** The stages of a module with the status feature, or none. */
export function statusStates(spec: Pick<ModuleSpec, 'features'>): ModuleStateSpec[] {
  return spec.features?.status?.states ?? [];
}

/** True when this stage code is one of the module's finished stages. */
export function isDoneStatus(spec: Pick<ModuleSpec, 'features'>, code: unknown): boolean {
  return statusStates(spec).some((s) => s.code === code && s.done);
}

/** What one input holds. Everything is text except a checkbox. */
export type FieldValue = string | boolean;

export type FormValues = Record<string, FieldValue>;

/**
 * One thing wrong with the draft.
 *
 * `message` is the module's own wording when one of its rules refused the
 * value, and it is shown as written - those are the author's words about their
 * own module, not a platform string to translate. It is null when the platform
 * itself refused (a field the schema requires was left empty), and the caller
 * translates by `code`.
 */
export interface DraftFinding {
  field: string;
  code: string;
  message: string | null;
  severity: 'error' | 'warning';
}

/** `code` of the platform's own "this field cannot be empty" finding. */
export const REQUIRED_CODE = 'FIELD_REQUIRED';

/** `code` of the platform's own "this is not a number" finding. */
export const NOT_A_NUMBER_CODE = 'FIELD_NOT_A_NUMBER';

/**
 * How many columns the list view shows.
 *
 * A spec may carry forty fields. A table of forty columns is not a table, and
 * the detail view shows all of them anyway, so the list takes the ones the spec
 * marked `in_list` and stops.
 */
export const MAX_LIST_COLUMNS = 6;

/** True when this value counts as "nothing was entered". */
export function isBlank(value: FieldValue | null | undefined): boolean {
  if (value === null || value === undefined) return true;
  if (typeof value === 'boolean') return false;
  return value.trim() === '';
}

/** The columns the list view renders, in spec order. */
export function listColumns(spec: ModuleSpec, max = MAX_LIST_COLUMNS): ModuleFieldSpec[] {
  const marked = spec.entity.fields.filter((f) => f.in_list);
  // A spec that marks nothing still needs a readable table, so fall back to the
  // first few fields rather than rendering a grid of ids.
  const columns = (marked.length > 0 ? marked : spec.entity.fields).slice(0, max);
  // The due date is what the overdue highlight is drawn on, so a module that
  // reminds about a date always shows that date, even when it fell outside
  // the first few columns or was not marked for the table.
  const dueName = spec.features?.due?.field;
  const due = dueName ? spec.entity.fields.find((f) => f.name === dueName) : undefined;
  if (due && !columns.includes(due)) {
    return [...columns.slice(0, Math.max(0, max - 1)), due];
  }
  return columns;
}

/** An empty form: every field present, so a controlled input never goes uncontrolled. */
export function blankValues(spec: ModuleSpec): FormValues {
  const values: FormValues = {};
  for (const field of spec.entity.fields) {
    values[field.name] = field.type === 'boolean' ? false : '';
  }
  // A new record starts in the first stage, which is also the server's default.
  const first = statusStates(spec)[0];
  if (first) values[STATUS_KEY] = first.code;
  return values;
}

/**
 * A stored datetime as `<input type="datetime-local">` wants it: local, naive,
 * to the minute. Returns '' for anything unparseable rather than throwing, so a
 * row written by an import with an odd value still opens in the form.
 */
export function toLocalInputValue(iso: string): string {
  const parsed = new Date(iso);
  if (Number.isNaN(parsed.getTime())) return '';
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${parsed.getFullYear()}-${pad(parsed.getMonth() + 1)}-${pad(parsed.getDate())}` +
    `T${pad(parsed.getHours())}:${pad(parsed.getMinutes())}`
  );
}

/** Fill a form from a record the API returned. */
export function valuesFromRecord(spec: ModuleSpec, record: GeneratedRecord): FormValues {
  const values = blankValues(spec);
  for (const field of spec.entity.fields) {
    const raw = record[field.name];
    if (raw === null || raw === undefined) continue;
    if (field.type === 'boolean') {
      values[field.name] = raw === true;
      continue;
    }
    if (field.type === 'datetime') {
      values[field.name] = toLocalInputValue(String(raw));
      continue;
    }
    if (field.type === 'date') {
      // Stored as a plain calendar day; the input wants exactly that. Trim any
      // time part an import may have left on it.
      values[field.name] = String(raw).slice(0, 10);
      continue;
    }
    values[field.name] = String(raw);
  }
  if (statusStates(spec).length > 0 && typeof record[STATUS_KEY] === 'string') {
    values[STATUS_KEY] = record[STATUS_KEY] as string;
  }
  return values;
}

/**
 * One form value as the API types it.
 *
 * Returns `undefined` when the field was left empty and should simply not be
 * sent, and `null` when it was cleared and should be sent as a clearing.
 */
function toApiValue(field: ModuleFieldSpec, value: FieldValue | undefined): unknown {
  if (field.type === 'boolean') return value === true;
  const text = typeof value === 'string' ? value.trim() : '';
  if (text === '') return null;

  switch (field.type) {
    case 'integer': {
      const parsed = Number(text);
      // A number when it is one, the raw text when it is not: the server names
      // the field in its 422, which is more useful than silently sending 0.
      return Number.isFinite(parsed) ? Math.trunc(parsed) : text;
    }
    case 'number':
    case 'money':
      // Deliberately still a string. See the note at the top of this file.
      return text;
    case 'datetime': {
      const parsed = new Date(text);
      // `text` is naive local. `toISOString` stamps the instant it names, so
      // the server stores the moment the user meant rather than the same wall
      // clock reading in another zone.
      return Number.isNaN(parsed.getTime()) ? text : parsed.toISOString();
    }
    default:
      return text;
  }
}

/**
 * The body for a create.
 *
 * `project_id` is sent when the entity is project-scoped, because the generated
 * `Create` schema requires it there and forbids it everywhere else - the schema
 * is `extra="forbid"`, so sending it to a module that does not want it is a 422
 * rather than a harmless extra key.
 *
 * A field the spec marks required is always included, even when empty, so the
 * server refuses it by name instead of reporting a missing key.
 */
export function toCreatePayload(
  spec: ModuleSpec,
  values: FormValues,
  projectId?: string | null,
): Record<string, unknown> {
  const payload: Record<string, unknown> = {};
  if (spec.entity.project_scoped && projectId) payload.project_id = projectId;
  for (const field of spec.entity.fields) {
    const converted = toApiValue(field, values[field.name]);
    if (converted === null && !field.required) continue;
    payload[field.name] = converted;
  }
  const status = values[STATUS_KEY];
  if (statusStates(spec).length > 0 && typeof status === 'string' && status !== '') {
    payload[STATUS_KEY] = status;
  }
  return payload;
}

/**
 * The body for an update: only what actually changed.
 *
 * The generated `Update` schema leaves an absent field alone and takes an
 * explicit null as a clearing, so sending the whole form would rewrite fields
 * nobody touched and quietly lose a concurrent edit to one of them.
 */
export function toUpdatePayload(
  spec: ModuleSpec,
  values: FormValues,
  record: GeneratedRecord,
): Record<string, unknown> {
  const original = valuesFromRecord(spec, record);
  const payload: Record<string, unknown> = {};
  for (const field of spec.entity.fields) {
    const next = values[field.name];
    if (next === original[field.name]) continue;
    payload[field.name] = toApiValue(field, next);
  }
  const status = values[STATUS_KEY];
  if (
    statusStates(spec).length > 0 &&
    typeof status === 'string' &&
    status !== '' &&
    status !== original[STATUS_KEY]
  ) {
    payload[STATUS_KEY] = status;
  }
  return payload;
}

/** Where a deadline stands. `null` when there is nothing to say about it. */
export type DueState = 'overdue' | 'soon' | null;

/**
 * Whether a due date has passed or is close.
 *
 * "Soon" is the same window the reminder uses, so the highlight and the
 * notification agree about which records need attention. A finished record
 * is never overdue: once the work is done, the date is history. Dates are
 * compared as calendar days in UTC, the way the server reads a `date`.
 */
export function dueState(
  field: ModuleFieldSpec,
  value: unknown,
  remindDaysBefore: number,
  done: boolean,
  now: Date = new Date(),
): DueState {
  if (done || value === null || value === undefined || value === '') return null;
  const text = String(value);
  const at = field.type === 'date' ? Date.parse(`${text.slice(0, 10)}T00:00:00Z`) : Date.parse(text);
  if (Number.isNaN(at)) return null;
  const DAY = 86_400_000;
  if (field.type === 'date') {
    const today = Date.parse(`${now.toISOString().slice(0, 10)}T00:00:00Z`);
    if (at < today) return 'overdue';
    return at - today <= remindDaysBefore * DAY ? 'soon' : null;
  }
  if (at < now.getTime()) return 'overdue';
  return at - now.getTime() <= remindDaysBefore * DAY ? 'soon' : null;
}

/** The number a numeric rule reads, or null when the text is not one. */
function asNumber(value: FieldValue | undefined): number | null {
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (text === '') return null;
  const parsed = Number(text);
  return Number.isFinite(parsed) ? parsed : null;
}

/**
 * The instant a temporal value names, for comparison only.
 *
 * A `date` is a calendar day and is pinned to UTC, which is how the generated
 * validator reads it: `datetime.now(UTC).date()`. A `datetime` from the form is
 * local, and `Date` parses it as local, which is what we want - it is the same
 * instant `toApiValue` will send.
 */
function asInstant(field: ModuleFieldSpec, value: FieldValue | undefined): number | null {
  if (typeof value !== 'string' || value.trim() === '') return null;
  const text = value.trim();
  const parsed = field.type === 'date' ? new Date(`${text}T00:00:00Z`) : new Date(text);
  const time = parsed.getTime();
  return Number.isNaN(time) ? null : time;
}

/**
 * Everything wrong with the draft, in the order a person would read it.
 *
 * `now` is a parameter so the caller can pass a fixed instant; a test that asks
 * whether "cannot be in the future" fires must not depend on the wall clock.
 */
export function evaluateDraft(spec: ModuleSpec, values: FormValues, now: Date = new Date()): DraftFinding[] {
  const findings: DraftFinding[] = [];
  const byName = new Map(spec.entity.fields.map((f) => [f.name, f]));

  for (const field of spec.entity.fields) {
    const value = values[field.name];
    if (field.required && isBlank(value)) {
      findings.push({ field: field.name, code: REQUIRED_CODE, message: null, severity: 'error' });
      continue;
    }
    if (
      (field.type === 'integer' || field.type === 'number' || field.type === 'money') &&
      !isBlank(value) &&
      asNumber(value) === null
    ) {
      findings.push({ field: field.name, code: NOT_A_NUMBER_CODE, message: null, severity: 'error' });
    }
  }

  for (const rule of spec.rules) {
    const field = byName.get(rule.field);
    if (!field) continue; // A rule naming a field that is not there cannot fire.
    const value = values[rule.field];
    const finding: DraftFinding = {
      field: rule.field,
      code: rule.code,
      message: rule.message,
      severity: rule.severity,
    };

    switch (rule.kind) {
      case 'required':
        if (isBlank(value)) findings.push(finding);
        break;
      case 'positive': {
        const n = asNumber(value);
        if (n !== null && n <= 0) findings.push(finding);
        break;
      }
      case 'range': {
        const n = asNumber(value);
        if (n === null) break;
        const belowMin = rule.min_value !== null && n < rule.min_value;
        const aboveMax = rule.max_value !== null && n > rule.max_value;
        if (belowMin || aboveMax) findings.push(finding);
        break;
      }
      case 'one_of':
        if (typeof value === 'string' && value !== '' && !field.options.includes(value)) {
          findings.push(finding);
        }
        break;
      case 'not_future': {
        const instant = asInstant(field, value);
        if (instant === null) break;
        // A date is compared as a calendar day against today's UTC day, which
        // is the comparison the generated validator makes.
        const limit =
          field.type === 'date'
            ? Date.parse(`${now.toISOString().slice(0, 10)}T00:00:00Z`)
            : now.getTime();
        if (instant > limit) findings.push(finding);
        break;
      }
      case 'order': {
        const other = byName.get(rule.other_field);
        if (!other) break;
        const left = asInstant(field, value);
        const right = asInstant(other, values[rule.other_field]);
        if (left !== null && right !== null && left > right) findings.push(finding);
        break;
      }
    }
  }

  return findings;
}

/** True when nothing in the draft is an error. Warnings do not stop a write. */
export function canSubmit(findings: DraftFinding[]): boolean {
  return !findings.some((f) => f.severity === 'error');
}

/** Wording the caller supplies so this file stays free of translation lookups. */
export interface ValueLabels {
  yes: string;
  no: string;
  empty: string;
}

/**
 * One stored value, as a person reads it.
 *
 * Numbers go through the platform's own formatter so a generated module renders
 * a quantity the same way every other screen does. Note that this is display
 * only: the value that goes back on the wire is the untouched string.
 */
export function formatValue(
  field: ModuleFieldSpec,
  value: unknown,
  labels: ValueLabels,
): string {
  if (field.type === 'boolean') return value === true ? labels.yes : labels.no;
  if (value === null || value === undefined || value === '') return labels.empty;

  switch (field.type) {
    case 'integer':
      return fmtNumber(value as string, 0);
    case 'number':
      return withUnit(fmtNumber(value as string, 2), field.unit);
    case 'money':
      return withUnit(fmtNumber(value as string, 2), field.unit);
    case 'date':
      return fmtDate(String(value).slice(0, 10));
    case 'datetime': {
      const parsed = new Date(String(value));
      if (Number.isNaN(parsed.getTime())) return String(value);
      // `toLocaleString` rather than the shared `fmtDate`: that one goes
      // through `toLocaleDateString`, whose handling of time options is a
      // corner of the spec worth not relying on for a value that is a moment.
      return parsed.toLocaleString(getIntlLocale(), {
        day: '2-digit',
        month: 'short',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit',
      });
    }
    default:
      return withUnit(String(value), field.unit);
  }
}

function withUnit(text: string, unit: string): string {
  return unit ? `${text} ${unit}` : text;
}

/**
 * Order two stored values of one field, for sorting a generated register.
 *
 * Sorting on the rendered text would be wrong for exactly the columns people
 * sort on: "1 000,00" against "900,00" compares as strings to the wrong answer,
 * and a localised month name orders alphabetically rather than by date. So this
 * reads the stored value and compares it as what it is.
 *
 * Money and quantities are compared as numbers even though they are carried as
 * strings, and that is safe in a way `Number()` is not safe for arithmetic: a
 * double is precise enough to say which of two amounts is larger, and it is
 * never written back. The exact string stays the value.
 *
 * Blanks always sort last, in both directions. A column sorted descending that
 * opens on a screen of empty cells hides the rows the user asked to see, and
 * "no value" is not a value that belongs at either extreme.
 */
export function compareByField(field: ModuleFieldSpec, a: unknown, b: unknown): number {
  if (field.type === 'boolean') return (a === true ? 1 : 0) - (b === true ? 1 : 0);

  const aBlank = a === null || a === undefined || a === '';
  const bBlank = b === null || b === undefined || b === '';
  if (aBlank && bBlank) return 0;
  if (aBlank) return 1;
  if (bBlank) return -1;

  switch (field.type) {
    case 'integer':
    case 'number':
    case 'money': {
      const na = Number(a);
      const nb = Number(b);
      // A value that is not a number at all is treated as blank rather than as
      // NaN: NaN comparisons are all false and would make the sort unstable.
      if (!Number.isFinite(na) && !Number.isFinite(nb)) return 0;
      if (!Number.isFinite(na)) return 1;
      if (!Number.isFinite(nb)) return -1;
      return na < nb ? -1 : na > nb ? 1 : 0;
    }
    case 'date':
    case 'datetime': {
      const ta = Date.parse(String(a));
      const tb = Date.parse(String(b));
      if (Number.isNaN(ta) && Number.isNaN(tb)) return 0;
      if (Number.isNaN(ta)) return 1;
      if (Number.isNaN(tb)) return -1;
      return ta - tb;
    }
    default:
      return String(a).localeCompare(String(b), getIntlLocale());
  }
}
