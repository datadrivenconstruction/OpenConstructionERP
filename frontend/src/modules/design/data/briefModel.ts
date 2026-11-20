// Design module (ERP side of the design editor link).
/**
 * The brief form, derived from `ddc-brief/1`: which fields exist, what kind of input each needs
 * (read from the schema at the field's JSON Pointer), and how an edit changes the document and
 * its provenance. Pure: no React, no network.
 */

import rawSchema from './brief.schema.json';
import {
  escapePointerToken,
  isRequiredAt,
  jsonEqual,
  schemaAt,
  validate,
  type Json,
  type Schema,
  type SchemaError,
} from './schemaCheck';

export const BRIEF_SCHEMA = rawSchema as unknown as Schema;
export const BRIEF_SCHEMA_ID = 'ddc-brief/1';

export type ProvenanceStatus = 'proposed' | 'confirmed' | 'default';

export interface ProvenanceSource {
  kind: 'document' | 'drawing' | 'sketch' | 'text' | 'map' | 'user';
  document_id?: string;
  page?: number;
  quote?: string;
  region?: number[];
}

export interface Provenance {
  status: ProvenanceStatus;
  confirmed_by?: string;
  confirmed_at?: string;
  sources?: ProvenanceSource[];
  note?: string;
}

export interface BriefQuestion {
  id: string;
  pointer: string;
  text: string;
  options: (string | number | boolean)[];
  default?: string | number | boolean | null;
  reason?: 'missing' | 'contradiction' | 'out_of_range' | 'ambiguous';
}

/** The document as stored; sections are reached by pointer, so they stay loosely typed. */
export interface BriefDoc {
  schema: string;
  brief_id: string;
  project_id: string;
  version: number;
  provenance?: Record<string, Provenance>;
  questions?: BriefQuestion[];
  [section: string]: unknown;
}

/* ── Pointers ────────────────────────────────────────────────────────── */

export function pointerTokens(pointer: string): string[] {
  if (pointer === '') return [];
  return pointer
    .split('/')
    .slice(1)
    .map((t) => t.replace(/~1/g, '/').replace(/~0/g, '~'));
}

export function childPointer(pointer: string, token: string | number): string {
  return `${pointer}/${escapePointerToken(token)}`;
}

export function getAt(doc: unknown, pointer: string): unknown {
  let node: unknown = doc;
  for (const t of pointerTokens(pointer)) {
    if (Array.isArray(node)) node = /^\d+$/.test(t) ? node[Number(t)] : undefined;
    else if (node && typeof node === 'object') node = (node as Record<string, unknown>)[t];
    else return undefined;
    if (node === undefined) return undefined;
  }
  return node;
}

/** Objects that must exist even when empty (required by the schema at the top level). */
const KEEP_EMPTY = new Set(['/use', '/massing', '/programme']);

function clone<T>(v: T): T {
  return structuredClone(v);
}

/** Copy of `doc` with `value` at `pointer`; `undefined` removes the key and prunes empty parents. */
export function setAt<T extends object>(doc: T, pointer: string, value: unknown): T {
  const out = clone(doc);
  const tokens = pointerTokens(pointer);
  const parents: unknown[] = [out];
  let node: unknown = out;
  for (let i = 0; i < tokens.length - 1; i++) {
    const t = tokens[i]!;
    const container = node as Record<string, unknown>;
    if (container[t] === undefined || container[t] === null || typeof container[t] !== 'object') {
      if (value === undefined) return out;
      container[t] = /^\d+$/.test(tokens[i + 1]!) ? [] : {};
    }
    node = container[t];
    parents.push(node);
  }
  const last = tokens[tokens.length - 1]!;
  if (value === undefined) {
    if (Array.isArray(node)) node.splice(Number(last), 1);
    else delete (node as Record<string, unknown>)[last];
    for (let i = tokens.length - 1; i > 0; i--) {
      const holder = parents[i] as Record<string, unknown>;
      if (Array.isArray(parents[i - 1])) break; // an empty list item stays, so its errors show
      const path = '/' + tokens.slice(0, i).map(escapePointerToken).join('/');
      if (Array.isArray(holder) || Object.keys(holder).length || KEEP_EMPTY.has(path)) break;
      delete (parents[i - 1] as Record<string, unknown>)[tokens[i - 1]!];
    }
  } else if (Array.isArray(node)) {
    node[Number(last)] = value;
  } else {
    (node as Record<string, unknown>)[last] = value;
  }
  return out;
}

function isUnder(pointer: string, base: string): boolean {
  return pointer === base || pointer.startsWith(base + '/');
}

/* ── Fields, read from the schema ────────────────────────────────────── */

export type FieldKind = 'text' | 'integer' | 'number' | 'choice' | 'boolean' | 'integer_list' | 'text_list';

export interface FieldSpec {
  pointer: string;
  kind: FieldKind;
  required: boolean;
  options: string[];
  min?: number;
  max?: number;
  unit?: string;
  maxLength?: number;
}

/** Units are in the property names of the schema (`_m`, `_m2`, `_deg`), so they are read from there. */
function unitOf(pointer: string): string | undefined {
  const name = pointerTokens(pointer).filter((t) => !/^\d+$/.test(t));
  const path = name.join('/');
  if (/_m2$/.test(path)) return 'm²';
  if (/_deg$/.test(path)) return '°';
  if (/(_m|setbacks_m\/\w+|footprint\/\w+_m)$/.test(path)) return 'm';
  if (path === 'budget/amount') return 'currency';
  return undefined;
}

export function fieldSpec(pointer: string): FieldSpec {
  const s = schemaAt(BRIEF_SCHEMA, pointer);
  if (!s) throw new Error(`no schema at ${pointer}`);
  const required = isRequiredAt(BRIEF_SCHEMA, pointer);
  const base = { pointer, required, options: [] as string[], unit: unitOf(pointer) };
  if (Array.isArray(s.enum)) {
    return { ...base, kind: 'choice', options: (s.enum as (string | null)[]).filter((e): e is string => e !== null) };
  }
  const items = s.items as Record<string, unknown> | undefined;
  switch (s.type) {
    case 'integer':
      return { ...base, kind: 'integer', min: lower(s), max: s.maximum as number | undefined };
    case 'number':
      return { ...base, kind: 'number', min: lower(s), max: s.maximum as number | undefined };
    case 'boolean':
      return { ...base, kind: 'boolean' };
    case 'array':
      return { ...base, kind: items?.type === 'integer' ? 'integer_list' : 'text_list' };
    default:
      return { ...base, kind: 'text', maxLength: s.maxLength as number | undefined };
  }
}

function lower(s: Record<string, unknown>): number | undefined {
  return (s.minimum ?? s.exclusiveMinimum) as number | undefined;
}

/** Room kinds the generator knows, listed in the schema's description of `space.kind`. */
export function roomKinds(): string[] {
  const d = String(schemaAt(BRIEF_SCHEMA, '/programme/spaces/0/kind')?.description ?? '');
  const m = /\(([^)]*)\)/.exec(d);
  return m ? m[1]!.split(',').map((s) => s.trim()).filter(Boolean) : [];
}

export interface Section {
  id: string;
  fields: string[];
}

/** Scalar fields of the form, grouped as the page shows them. Lists are edited by their own blocks. */
export const SECTIONS: Section[] = [
  { id: 'general', fields: ['/name', '/country', '/locale', '/norm_pack', '/depth_level'] },
  { id: 'use', fields: ['/use/category', '/use/detail'] },
  {
    id: 'site',
    fields: [
      '/site/address', '/site/setbacks_m/front', '/site/setbacks_m/side', '/site/setbacks_m/rear',
      '/site/max_height_m', '/site/max_floors', '/site/floor_area_ratio_max', '/site/site_coverage_max',
      '/site/ground_elevation_m',
    ],
  },
  {
    id: 'massing',
    fields: [
      '/massing/floors_above', '/massing/floors_below', '/massing/floor_height_m', '/massing/ground_floor_height_m',
      '/massing/footprint/width_m', '/massing/footprint/depth_m', '/massing/gross_floor_area_m2', '/massing/lift',
    ],
  },
  { id: 'programme', fields: ['/programme/parking_spaces'] },
  { id: 'structure', fields: ['/structure/system', '/structure/foundation', '/structure/grid_m'] },
  { id: 'envelope', fields: ['/envelope/roof', '/envelope/roof_slope_deg', '/envelope/facade', '/envelope/energy_standard'] },
  { id: 'quality', fields: ['/quality_level'] },
  { id: 'budget', fields: ['/budget/amount', '/budget/currency', '/budget/includes_vat', '/budget/cost_groups'] },
];

export const UNIT_FIELDS = ['name', 'count', 'area_m2'] as const;
export const SPACE_FIELDS = ['kind', 'name', 'count', 'area_m2', 'floors', 'adjacent_to'] as const;
export const PLOT_POINTER = '/site/plot';

/** i18n key of a field label: pointer without list indices, e.g. `design.field.programme.units.rooms.kind`. */
export function labelKey(pointer: string): string {
  return 'design.field.' + pointerTokens(pointer).filter((t) => !/^\d+$/.test(t)).join('.');
}

/* ── Input parsing ───────────────────────────────────────────────────── */

export type Parsed = { ok: true; value: Json | undefined } | { ok: false; code: 'not_a_number' | 'not_an_integer' };

/** Plain decimal notation only: no hex, exponent, Infinity or digit separators. */
const DECIMAL = /^[+-]?(\d+([.,]\d*)?|[.,]\d+)$/;

/** Text typed into a field → JSON value; empty text clears the field. */
export function parseInput(spec: FieldSpec, text: string): Parsed {
  const t = text.trim();
  if (spec.kind === 'boolean') return { ok: true, value: t === '' ? undefined : t === 'true' };
  if (t === '') return { ok: true, value: undefined };
  switch (spec.kind) {
    case 'integer': {
      if (!DECIMAL.test(t)) return { ok: false, code: 'not_a_number' };
      const n = Number(t.replace(',', '.'));
      return Number.isInteger(n) ? { ok: true, value: n } : { ok: false, code: 'not_an_integer' };
    }
    case 'number':
      return DECIMAL.test(t) ? { ok: true, value: Number(t.replace(',', '.')) } : { ok: false, code: 'not_a_number' };
    case 'integer_list': {
      const parts = t.split(/[,;\s]+/).filter(Boolean);
      if (!parts.every((p) => /^[+-]?\d+$/.test(p))) return { ok: false, code: 'not_an_integer' };
      return { ok: true, value: parts.map(Number) };
    }
    case 'text_list':
      return { ok: true, value: t.split(/[,;]+/).map((s) => s.trim()).filter(Boolean) };
    default:
      return { ok: true, value: t };
  }
}

/** JSON value → text for an input. */
export function formatValue(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (Array.isArray(value)) return value.join(', ');
  return String(value);
}

/* ── Documents ───────────────────────────────────────────────────────── */

export interface ProjectDefaults {
  id: string;
  country_code?: string | null;
  locale?: string | null;
  currency?: string | null;
  name?: string | null;
}

/**
 * A new brief prefilled from the project settings. Prefilled values carry status `default` and
 * say where they came from; everything a person must decide (use, floors) stays empty.
 */
export function newBrief(project: ProjectDefaults, briefId: string): BriefDoc {
  let doc: BriefDoc = {
    schema: BRIEF_SCHEMA_ID,
    brief_id: briefId,
    project_id: project.id,
    version: 1,
    use: {},
    massing: {},
    programme: {},
    provenance: {},
  };
  const note = 'From the project settings';
  const country = (project.country_code ?? '').toUpperCase();
  if (/^[A-Z]{2}$/.test(country)) doc = withDefault(doc, '/country', country, note);
  const locale = normaliseLocale(project.locale);
  if (locale) doc = withDefault(doc, '/locale', locale, note);
  if (project.name) doc = withDefault(doc, '/name', project.name.slice(0, 200), note);
  return doc;
}

function withDefault(doc: BriefDoc, pointer: string, value: Json, note: string): BriefDoc {
  const out = setAt(doc, pointer, value);
  out.provenance = { ...(out.provenance ?? {}), [pointer]: { status: 'default', note } };
  return out;
}

/** `de_DE`, `de-de`, `DE` → `de-DE`, `de`; anything else → null. */
export function normaliseLocale(raw: string | null | undefined): string | null {
  const m = /^([a-zA-Z]{2,3})(?:[-_]([a-zA-Z]{2}))?$/.exec((raw ?? '').trim());
  if (!m) return null;
  return m[2] ? `${m[1]!.toLowerCase()}-${m[2].toUpperCase()}` : m[1]!.toLowerCase();
}

/**
 * A person typed or drew a value. The value becomes theirs (`proposed`, source `user` or `map`)
 * until they confirm it; clearing a value removes its provenance too.
 */
export function editField(doc: BriefDoc, pointer: string, value: unknown, source: ProvenanceSource['kind'] = 'user'): BriefDoc {
  if (jsonEqual(getAt(doc, pointer), value)) return doc;
  const out = setAt(doc, pointer, value);
  const prov: Record<string, Provenance> = {};
  for (const [p, entry] of Object.entries(out.provenance ?? {})) {
    if (!isUnder(p, pointer) && !isUnder(pointer, p)) prov[p] = entry;
    else if (isUnder(pointer, p) && p !== pointer && getAt(out, p) !== undefined) {
      // An ancestor's confirmation covered the old value of this child: it no longer holds.
      prov[p] = entry.status === 'confirmed' ? { status: 'proposed', sources: entry.sources, note: entry.note } : entry;
    }
  }
  if (value !== undefined) prov[pointer] = { status: 'proposed', sources: [{ kind: source }] };
  out.provenance = prov;
  return out;
}

/**
 * Cite a project document as a source of the value at `pointer`. The generic `user` source it got
 * when typed is replaced by the document; status and value stay as they are, so citing never
 * confirms anything.
 */
export function citeDocument(doc: BriefDoc, pointer: string, source: { document_id: string; page?: number; quote?: string }): BriefDoc {
  const entry = doc.provenance?.[pointer];
  if (!entry || getAt(doc, pointer) === undefined) return doc;
  const cleaned: ProvenanceSource = { kind: 'document', document_id: source.document_id };
  if (source.page && source.page >= 1) cleaned.page = Math.floor(source.page);
  const quote = source.quote?.trim();
  if (quote) cleaned.quote = quote.slice(0, 1000);
  const kept = (entry.sources ?? []).filter((x) => x.kind !== 'user' && !(x.kind === 'document' && x.document_id === cleaned.document_id && x.page === cleaned.page && x.quote === cleaned.quote));
  return { ...doc, provenance: { ...doc.provenance, [pointer]: { ...entry, sources: [...kept, cleaned] } } };
}

/** How many values cite each document (by document id). */
export function documentCitations(doc: BriefDoc): Record<string, number> {
  const out: Record<string, number> = {};
  for (const [pointer, entry] of Object.entries(doc.provenance ?? {})) {
    if (getAt(doc, pointer) === undefined) continue;
    const ids = new Set((entry.sources ?? []).filter((x) => x.kind === 'document' && x.document_id).map((x) => x.document_id as string));
    for (const id of ids) out[id] = (out[id] ?? 0) + 1;
  }
  return out;
}

/** Append an item to the list at `pointer`. */
export function addItem(doc: BriefDoc, pointer: string, item: Json): BriefDoc {
  const list = (getAt(doc, pointer) as Json[] | undefined) ?? [];
  return setAt(doc, pointer, [...list, item]);
}

/** Remove item `index` of the list at `pointer`; provenance of later items moves down by one. */
export function removeItem(doc: BriefDoc, pointer: string, index: number): BriefDoc {
  const list = (getAt(doc, pointer) as Json[] | undefined) ?? [];
  const next = list.filter((_, i) => i !== index);
  const out = setAt(doc, pointer, next.length ? next : undefined);
  return shiftProvenance(out, pointer, index);
}

function shiftProvenance(doc: BriefDoc, list: string, index: number): BriefDoc {
  const prov: Record<string, Provenance> = {};
  const prefix = list + '/';
  for (const [p, entry] of Object.entries(doc.provenance ?? {})) {
    if (!p.startsWith(prefix)) {
      prov[p] = entry;
      continue;
    }
    const rest = p.slice(prefix.length);
    const slash = rest.indexOf('/');
    const i = Number(slash < 0 ? rest : rest.slice(0, slash));
    const tail = slash < 0 ? '' : rest.slice(slash);
    if (i < index) prov[p] = entry;
    else if (i > index) prov[`${prefix}${i - 1}${tail}`] = entry;
  }
  doc.provenance = prov;
  return doc;
}

/** Drop provenance of values the document no longer has (the server refuses it). */
export function tidy(doc: BriefDoc): BriefDoc {
  const out = clone(doc);
  out.provenance = Object.fromEntries(
    Object.entries(out.provenance ?? {}).filter(([p]) => getAt(out, p) !== undefined),
  );
  return out;
}

export type DisplayStatus = ProvenanceStatus | 'none';

export function statusOf(doc: BriefDoc, pointer: string): DisplayStatus {
  return doc.provenance?.[pointer]?.status ?? 'none';
}

/** Every pointer the form shows a value for, in page order. */
export function valuePointers(doc: BriefDoc): string[] {
  const out: string[] = [];
  for (const s of SECTIONS) for (const f of s.fields) if (getAt(doc, f) !== undefined) out.push(f);
  if (getAt(doc, PLOT_POINTER) !== undefined) out.push(PLOT_POINTER);
  const units = (getAt(doc, '/programme/units') as Json[] | undefined) ?? [];
  units.forEach((_, i) => {
    const u = `/programme/units/${i}`;
    for (const f of UNIT_FIELDS) if (getAt(doc, `${u}/${f}`) !== undefined) out.push(`${u}/${f}`);
    const rooms = (getAt(doc, `${u}/rooms`) as Json[] | undefined) ?? [];
    rooms.forEach((__, j) => {
      for (const f of SPACE_FIELDS) if (getAt(doc, `${u}/rooms/${j}/${f}`) !== undefined) out.push(`${u}/rooms/${j}/${f}`);
    });
  });
  const spaces = (getAt(doc, '/programme/spaces') as Json[] | undefined) ?? [];
  spaces.forEach((_, i) => {
    for (const f of SPACE_FIELDS) if (getAt(doc, `/programme/spaces/${i}/${f}`) !== undefined) out.push(`/programme/spaces/${i}/${f}`);
  });
  return out;
}

/** Values shown in the form that no person has confirmed yet. */
export function unconfirmed(doc: BriefDoc): string[] {
  return valuePointers(doc).filter((p) => statusOf(doc, p) !== 'confirmed');
}

/* ── Validation ──────────────────────────────────────────────────────── */

export type ErrorMap = Record<string, SchemaError[]>;

/** Schema violations keyed by the pointer they belong to. */
export function briefErrors(doc: BriefDoc): ErrorMap {
  const map: ErrorMap = {};
  for (const e of validate(doc, BRIEF_SCHEMA)) (map[e.pointer] ??= []).push(e);
  return map;
}

/** Errors at `pointer` or below it (a list field reports its items' errors too). */
export function errorsAt(errors: ErrorMap, pointer: string): SchemaError[] {
  return Object.entries(errors)
    .filter(([p]) => isUnder(p, pointer))
    .flatMap(([, list]) => list);
}

/** Server answer `{detail: {errors: [{pointer, message}]}}` → the same map, message as code. */
export function serverErrors(body: unknown): ErrorMap {
  const list = (body as { detail?: { errors?: { pointer: string; message: string }[] } } | null)?.detail?.errors;
  const map: ErrorMap = {};
  for (const e of list ?? []) (map[e.pointer] ??= []).push({ pointer: e.pointer, code: 'server', param: e.message });
  return map;
}
