// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Comparison operators for quantity-rule property conditions.
 *
 * Mirror of ``backend/app/modules/bim_hub/rule_operators.py``; both engines
 * read ``__tests__/fixtures/ruleMatchingParity.json``. A bare value in a
 * rule's ``property_filter`` is the original equality form with ``*`` / ``?``
 * wildcards. Any other comparison is stored as ``{"$op": op, "value": v}``,
 * the empty checks without a value.
 *
 * Numbers compare unit-aware where a value carries a unit ("3 m" > "2500 mm").
 * A bare number on one side is read in the unit of the other; a length never
 * compares with a mass.
 */

import { parseSearchNumber } from './propertySearch';

export const RULE_OPERATORS = [
  'equals',
  'not_equals',
  'contains',
  'not_contains',
  'gt',
  'gte',
  'lt',
  'lte',
  'is_empty',
  'is_not_empty',
] as const;

export type RuleOperator = (typeof RULE_OPERATORS)[number];

export interface PropertyCondition {
  $op: string;
  value?: string;
}

/** What a rule stores per property: a bare equality value or a condition. */
export type PropertyFilterValue = string | number | boolean | null | PropertyCondition | unknown[];

export const NUMERIC_OPERATORS: ReadonlySet<string> = new Set(['gt', 'gte', 'lt', 'lte']);
export const VALUELESS_OPERATORS: ReadonlySet<string> = new Set(['is_empty', 'is_not_empty']);
/** The operators whose value is one of the model's values, so the editor
 *  offers the property's value list. */
export const VALUE_LIST_OPERATORS: ReadonlySet<string> = new Set(['equals', 'not_equals']);

const EMPTY_TEXT = new Set(['', 'none', 'null', 'n/a']);
const MAX_TEXT_VALUE = 500;

type UnitKind = 'length' | 'area' | 'volume' | 'mass';

const UNITS: Record<string, [UnitKind, number]> = {
  mm: ['length', 0.001],
  cm: ['length', 0.01],
  dm: ['length', 0.1],
  m: ['length', 1],
  km: ['length', 1000],
  in: ['length', 0.0254],
  ft: ['length', 0.3048],
  yd: ['length', 0.9144],
  mm2: ['area', 1e-6],
  cm2: ['area', 1e-4],
  dm2: ['area', 0.01],
  m2: ['area', 1],
  ha: ['area', 10000],
  in2: ['area', 0.00064516],
  ft2: ['area', 0.09290304],
  sf: ['area', 0.09290304],
  yd2: ['area', 0.83612736],
  mm3: ['volume', 1e-9],
  cm3: ['volume', 1e-6],
  dm3: ['volume', 0.001],
  l: ['volume', 0.001],
  m3: ['volume', 1],
  ft3: ['volume', 0.028316846592],
  cf: ['volume', 0.028316846592],
  yd3: ['volume', 0.764554857984],
  g: ['mass', 0.001],
  kg: ['mass', 1],
  t: ['mass', 1000],
  lb: ['mass', 0.45359237],
};

const NUMBER_RE = /^\s*([+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?)\s*([\s\S]*?)\s*$/;

export interface Measure {
  value: number;
  unit: string;
}

export function foldUnit(raw: string): string {
  return raw.replace(/²/g, '2').replace(/³/g, '3').replace(/ /g, '').toLowerCase();
}

/** A number with an optional known unit, or null. No decimal comma: the
 *  editor writes every number it saves with a dot. */
export function parseMeasure(raw: unknown): Measure | null {
  if (typeof raw === 'number') return Number.isFinite(raw) ? { value: raw, unit: '' } : null;
  if (typeof raw !== 'string') return null;
  const m = NUMBER_RE.exec(raw);
  if (!m) return null;
  const value = Number(m[1]);
  if (!Number.isFinite(value)) return null;
  const unit = foldUnit(m[2] ?? '');
  if (unit && !(unit in UNITS)) return null;
  return { value, unit };
}

/** -1 / 0 / 1 for actual against expected, or null when they do not compare. */
export function compareMeasures(actual: Measure, expected: Measure): number | null {
  let a = actual.value;
  let e = expected.value;
  if (actual.unit && expected.unit && actual.unit !== expected.unit) {
    const [kindA, factorA] = UNITS[actual.unit]!;
    const [kindE, factorE] = UNITS[expected.unit]!;
    if (kindA !== kindE) return null;
    a *= factorA;
    e *= factorE;
  }
  // Same tolerance as Python's math.isclose(rel_tol=1e-9, abs_tol=1e-12).
  if (Math.abs(a - e) <= Math.max(1e-9 * Math.max(Math.abs(a), Math.abs(e)), 1e-12)) return 0;
  return a < e ? -1 : 1;
}

/** ``[op, value]`` when the stored pattern is a condition object. */
export function conditionOf(pattern: unknown): [string, unknown] | null {
  if (pattern && typeof pattern === 'object' && !Array.isArray(pattern) && '$op' in pattern) {
    const c = pattern as { $op: unknown; value?: unknown };
    return [String(c.$op), c.value];
  }
  return null;
}

export function isEmptyValue(actual: unknown): boolean {
  if (actual === null || actual === undefined) return true;
  if (typeof actual === 'string') return EMPTY_TEXT.has(actual.trim().toLowerCase());
  if (Array.isArray(actual)) return actual.every(isEmptyValue);
  if (typeof actual === 'object') return Object.values(actual as Record<string, unknown>).every(isEmptyValue);
  return false;
}

function contains(actual: unknown, needle: string): boolean {
  if (isEmptyValue(actual)) return false;
  if (Array.isArray(actual)) return actual.some((item) => contains(item, needle));
  if (typeof actual === 'object') {
    return Object.values(actual as Record<string, unknown>).some((item) => contains(item, needle));
  }
  return String(actual).toLowerCase().includes(needle.trim().toLowerCase());
}

function numeric(actual: unknown, op: string, expected: unknown): boolean {
  const want = parseMeasure(expected);
  if (!want) return false;
  const values = Array.isArray(actual) ? actual : [actual];
  return values.some((item) => {
    const have = parseMeasure(item);
    if (!have) return false;
    const order = compareMeasures(have, want);
    if (order === null) return false;
    return (
      (op === 'gt' && order > 0) ||
      (op === 'gte' && order >= 0) ||
      (op === 'lt' && order < 0) ||
      (op === 'lte' && order <= 0)
    );
  });
}

/** Does ``actual`` satisfy ``op value``? ``equals`` is the bare form's
 *  predicate (wildcards, trimming, list membership). An absent property
 *  satisfies the negations and nothing else. */
export function conditionMatches(
  actual: unknown,
  op: string,
  value: unknown,
  equals: (actual: unknown, expected: unknown) => boolean,
): boolean {
  if (op === 'is_empty') return isEmptyValue(actual);
  if (op === 'is_not_empty') return !isEmptyValue(actual);
  const absent = actual === null || actual === undefined;
  if (op === 'equals') return !absent && equals(actual, value);
  if (op === 'not_equals') return absent || !equals(actual, value);
  if (op === 'contains') return contains(actual, String(value));
  if (op === 'not_contains') return !contains(actual, String(value));
  if (NUMERIC_OPERATORS.has(op)) return numeric(actual, op, value);
  return false;
}

/* ── Editor helpers ─────────────────────────────────────────────────────── */

/** The operator and value text the editor shows for a stored pattern. */
export function decodeCondition(pattern: unknown): { op: RuleOperator; value: string } {
  const cond = conditionOf(pattern);
  if (cond) {
    const op = (RULE_OPERATORS as readonly string[]).includes(cond[0]) ? (cond[0] as RuleOperator) : 'equals';
    return { op, value: cond[1] === undefined || cond[1] === null ? '' : String(cond[1]) };
  }
  return { op: 'equals', value: pattern === null || pattern === undefined ? '' : String(pattern) };
}

/** What the rule stores for an editor row. Equality stays the bare value so
 *  a rule without operators reads exactly as it did before they existed. */
export function encodeCondition(op: RuleOperator, value: string): PropertyFilterValue {
  if (op === 'equals') return value;
  if (VALUELESS_OPERATORS.has(op)) return { $op: op };
  return { $op: op, value };
}

export type ConditionProblem = 'value_required' | 'value_not_number' | 'value_too_long';

export interface CheckedCondition {
  /** The value as it will be stored: trimmed, numbers with a dot. */
  value: string;
  problem: ConditionProblem | null;
  /** A typed number that reads two ways ("1.500"), shown as it was read. */
  ambiguous: boolean;
}

/**
 * Check and normalise an editor row's value for its operator, the same
 * refusals the server makes (``check_property_filter``). A number is read in
 * the reader's convention ("3,5 m" in Italian is 3.5 m) and stored with a dot.
 */
export function checkConditionValue(op: RuleOperator, raw: string, locale: string): CheckedCondition {
  if (VALUELESS_OPERATORS.has(op)) return { value: '', problem: null, ambiguous: false };
  const text = raw.trim();
  if (op === 'equals') {
    // Bare equality keeps its old meaning; an empty value is a rule being typed.
    return { value: raw, problem: text.length > MAX_TEXT_VALUE ? 'value_too_long' : null, ambiguous: false };
  }
  if (!text) return { value: text, problem: 'value_required', ambiguous: false };
  if (text.length > MAX_TEXT_VALUE) return { value: text, problem: 'value_too_long', ambiguous: false };
  if (!NUMERIC_OPERATORS.has(op)) return { value: text, problem: null, ambiguous: false };
  const m = /^([+\-−]?[0-9][0-9.,\s]*?|[+\-−]?[.,][0-9]+)\s*([^0-9\s.,].*)?$/.exec(text);
  if (!m) return { value: text, problem: 'value_not_number', ambiguous: false };
  const number = parseSearchNumber((m[1] ?? '').trim(), locale);
  const unit = foldUnit(m[2] ?? '');
  if (!number || (unit && !(unit in UNITS))) return { value: text, problem: 'value_not_number', ambiguous: false };
  const stored = unit ? `${number.value} ${unit}` : String(number.value);
  if (!parseMeasure(stored)) return { value: text, problem: 'value_not_number', ambiguous: false };
  return { value: stored, problem: null, ambiguous: number.ambiguous };
}
