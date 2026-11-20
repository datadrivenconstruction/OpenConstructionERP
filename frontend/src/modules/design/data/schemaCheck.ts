// Design module (ERP side of the design editor link).
/**
 * JSON Schema (draft 2020-12) checking for the keyword subset the `ddc-brief/1` schema uses.
 * Same rules as the backend's `schema_check.py`; the backend stays the authority on save.
 */

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type Schema = boolean | { [key: string]: unknown };

export interface SchemaError {
  /** JSON Pointer of the offending value ('' = the document). */
  pointer: string;
  /** Machine code; the UI turns it into a sentence. */
  code: string;
  /** Parameter of the code (a limit, a pattern, the allowed values). */
  param?: string | number;
}

const DATE_TIME = /^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?([Zz]|[+-](\d{2}):(\d{2}))$/;

export function escapePointerToken(token: string | number): string {
  return String(token).replace(/~/g, '~0').replace(/\//g, '~1');
}

export function toPointer(parts: (string | number)[]): string {
  return parts.map((p) => '/' + escapePointerToken(p)).join('');
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v);
}

function isType(value: unknown, name: string): boolean {
  switch (name) {
    case 'null':
      return value === null;
    case 'boolean':
      return typeof value === 'boolean';
    case 'object':
      return isObject(value);
    case 'array':
      return Array.isArray(value);
    case 'string':
      return typeof value === 'string';
    case 'number':
      return typeof value === 'number' && Number.isFinite(value);
    case 'integer':
      return typeof value === 'number' && Number.isInteger(value);
    default:
      throw new Error(`unknown type ${name}`);
  }
}

export function jsonEqual(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) {
    return a.length === b.length && a.every((x, i) => jsonEqual(x, b[i]));
  }
  if (isObject(a) && isObject(b)) {
    const ka = Object.keys(a);
    return ka.length === Object.keys(b).length && ka.every((k) => k in b && jsonEqual(a[k], b[k]));
  }
  return a === b;
}

function dateTimeOk(value: string): boolean {
  const m = DATE_TIME.exec(value);
  if (!m) return false;
  const [year, month, day, hour, minute, second] = [1, 2, 3, 4, 5, 6].map((i) => Number(m[i]));
  const leap = year! % 4 === 0 && (year! % 100 !== 0 || year! % 400 === 0);
  const days = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  if (!(month! >= 1 && month! <= 12 && day! >= 1 && day! <= days[month! - 1]! && hour! <= 23 && minute! <= 59 && second! <= 60)) {
    return false;
  }
  return m[9] === undefined || (Number(m[9]) <= 23 && Number(m[10]) <= 59);
}

export function resolveRef(root: Schema, ref: string): Schema {
  if (!ref.startsWith('#')) throw new Error(`only local $ref is supported: ${ref}`);
  let node: unknown = root;
  for (const part of ref.slice(1).split('/').filter(Boolean)) {
    node = (node as Record<string, unknown>)[part.replace(/~1/g, '/').replace(/~0/g, '~')];
  }
  return node as Schema;
}

function check(root: Schema, schema: Schema, value: unknown, at: (string | number)[], out: SchemaError[]): void {
  if (schema === true) return;
  const here = toPointer(at);
  if (schema === false) {
    out.push({ pointer: here, code: 'not_allowed' });
    return;
  }
  const s = schema as Record<string, unknown>;
  const fail = (code: string, param?: string | number) => out.push({ pointer: here, code, param });

  if (typeof s.$ref === 'string') check(root, resolveRef(root, s.$ref), value, at, out);
  if (s.type !== undefined) {
    const names = Array.isArray(s.type) ? (s.type as string[]) : [s.type as string];
    if (!names.some((n) => isType(value, n))) {
      fail('type', names.join('|'));
      return;
    }
  }
  if ('const' in s && !jsonEqual(value, s.const)) fail('const', JSON.stringify(s.const));
  if (Array.isArray(s.enum) && !s.enum.some((e) => jsonEqual(value, e))) {
    fail('enum', s.enum.filter((e) => e !== null).join(', '));
  }
  if (typeof value === 'string') {
    const length = [...value].length;
    if (typeof s.minLength === 'number' && length < s.minLength) fail(s.minLength === 1 ? 'required' : 'min_length', s.minLength);
    if (typeof s.maxLength === 'number' && length > s.maxLength) fail('max_length', s.maxLength);
    if (typeof s.pattern === 'string' && !new RegExp(s.pattern, 'u').test(value)) fail('pattern', s.pattern);
    if (s.format === 'date-time' && !dateTimeOk(value)) fail('date_time');
  }
  if (isType(value, 'number')) {
    const n = value as number;
    if (typeof s.minimum === 'number' && n < s.minimum) fail('minimum', s.minimum);
    if (typeof s.maximum === 'number' && n > s.maximum) fail('maximum', s.maximum);
    if (typeof s.exclusiveMinimum === 'number' && n <= s.exclusiveMinimum) fail('exclusive_minimum', s.exclusiveMinimum);
    if (typeof s.exclusiveMaximum === 'number' && n >= s.exclusiveMaximum) fail('exclusive_maximum', s.exclusiveMaximum);
  }
  if (Array.isArray(value)) {
    if (typeof s.minItems === 'number' && value.length < s.minItems) fail('min_items', s.minItems);
    if (typeof s.maxItems === 'number' && value.length > s.maxItems) fail('max_items', s.maxItems);
    if (s.items !== undefined) value.forEach((item, i) => check(root, s.items as Schema, item, [...at, i], out));
  }
  if (isObject(value)) {
    for (const name of (s.required as string[] | undefined) ?? []) {
      if (!(name in value)) out.push({ pointer: toPointer([...at, name]), code: 'required' });
    }
    const props = (s.properties as Record<string, Schema> | undefined) ?? {};
    for (const [name, item] of Object.entries(value)) {
      if (s.propertyNames !== undefined) {
        const before = out.length;
        check(root, s.propertyNames as Schema, name, [...at, name], out);
        for (const e of out.slice(before)) e.code = `property_name_${e.code}`;
      }
      if (name in props) check(root, props[name]!, item, [...at, name], out);
      else if (s.additionalProperties === false) out.push({ pointer: toPointer([...at, name]), code: 'not_allowed' });
      else if (s.additionalProperties !== undefined) check(root, s.additionalProperties as Schema, item, [...at, name], out);
    }
  }
}

/** All violations; empty when `doc` satisfies `schema`. */
export function validate(doc: unknown, schema: Schema): SchemaError[] {
  const out: SchemaError[] = [];
  check(schema, schema, doc, [], out);
  return out;
}

/** The sub-schema that governs the value at `pointer`, following `$ref`, `properties` and `items`. */
export function schemaAt(root: Schema, pointer: string): Record<string, unknown> | null {
  let node: Schema = root;
  const deref = (n: Schema): Schema => {
    let cur = n;
    while (isObject(cur) && typeof cur.$ref === 'string') cur = resolveRef(root, cur.$ref);
    return cur;
  };
  node = deref(node);
  for (const raw of pointer.split('/').slice(1)) {
    const part = raw.replace(/~1/g, '/').replace(/~0/g, '~');
    if (!isObject(node)) return null;
    const props = node.properties as Record<string, Schema> | undefined;
    if (props && part in props) node = deref(props[part]!);
    else if (/^\d+$/.test(part) && node.items !== undefined) node = deref(node.items as Schema);
    else if (isObject(node.additionalProperties)) node = deref(node.additionalProperties as Schema);
    else return null;
  }
  return isObject(node) ? node : null;
}

/** Whether the parent object of `pointer` lists its last token as required. */
export function isRequiredAt(root: Schema, pointer: string): boolean {
  const cut = pointer.lastIndexOf('/');
  const parent = schemaAt(root, pointer.slice(0, cut));
  const name = pointer.slice(cut + 1).replace(/~1/g, '/').replace(/~0/g, '~');
  return Array.isArray(parent?.required) && (parent!.required as string[]).includes(name);
}
