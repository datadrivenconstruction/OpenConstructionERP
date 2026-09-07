// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
//
// Field-type metadata for the template builder + a light mirror of the backend
// validation engine (app/modules/forms/validation.py). The backend remains the
// source of truth - it re-validates on every write and every complete - but
// mirroring the rules here lets the builder show integrity problems live and
// the filler gate the Complete button without a round-trip.

import {
  Heading,
  Type,
  AlignLeft,
  Hash,
  CircleDot,
  ListChecks,
  CheckSquare,
  ShieldCheck,
  Star,
  Camera,
  PenLine,
  Calendar,
  Sigma,
  type LucideIcon,
} from 'lucide-react';
import type {
  AnswerMap,
  AnswerValue,
  ConditionExpr,
  ConditionOp,
  FieldType,
  FormFieldDef,
  TemplateCategory,
} from './api';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';

export interface FieldTypeMeta {
  type: FieldType;
  label: string;
  hint: string;
  icon: LucideIcon;
  /** Layout-only (no answer) - a section header. */
  layout?: boolean;
  /** Computed (no user answer) - a formula field. */
  computed?: boolean;
  /** Requires an options list. */
  hasOptions?: boolean;
  /** Has an optional measurement unit. */
  hasUnit?: boolean;
  /** Has a rating scale. */
  hasRating?: boolean;
}

/** Ordered palette - the order fields appear in the "add field" menu. */
export const FIELD_TYPES: FieldTypeMeta[] = [
  { type: 'section', label: 'Section header', hint: 'Group and title the fields below', icon: Heading, layout: true },
  { type: 'short_text', label: 'Short text', hint: 'A single line of text', icon: Type },
  { type: 'long_text', label: 'Paragraph', hint: 'Multi-line notes', icon: AlignLeft },
  { type: 'number', label: 'Number', hint: 'A measured value with an optional unit', icon: Hash, hasUnit: true },
  { type: 'single_choice', label: 'Single choice', hint: 'Pick one option', icon: CircleDot, hasOptions: true },
  { type: 'multi_choice', label: 'Multiple choice', hint: 'Pick any options', icon: ListChecks, hasOptions: true },
  { type: 'checkbox', label: 'Checkbox', hint: 'A single confirmation to tick', icon: CheckSquare },
  { type: 'pass_fail_na', label: 'Pass / Fail / NA', hint: 'The checklist workhorse', icon: ShieldCheck },
  { type: 'rating', label: 'Rating', hint: 'A star / numeric score', icon: Star, hasRating: true },
  { type: 'photo', label: 'Photo', hint: 'Attach photo evidence', icon: Camera },
  { type: 'signature', label: 'Signature', hint: 'Capture a signature', icon: PenLine },
  { type: 'date', label: 'Date', hint: 'A calendar date', icon: Calendar },
  { type: 'formula', label: 'Computed', hint: 'A value derived from other fields', icon: Sigma, computed: true },
];

const META_BY_TYPE: Record<FieldType, FieldTypeMeta> = FIELD_TYPES.reduce(
  (acc, m) => {
    acc[m.type] = m;
    return acc;
  },
  {} as Record<FieldType, FieldTypeMeta>,
);

export function fieldMeta(type: FieldType): FieldTypeMeta {
  return META_BY_TYPE[type] ?? META_BY_TYPE.short_text;
}

export const CHOICE_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['single_choice', 'multi_choice']);
export const LAYOUT_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['section']);
/** Computed fields carry a value but the user never enters it (formula). */
export const COMPUTED_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['formula']);
/** Free-text types that support a min-length / pattern constraint. */
export const TEXT_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['short_text', 'long_text']);
/** Types that support a numeric min / max bound. */
export const BOUNDED_TYPES: ReadonlySet<FieldType> = new Set<FieldType>(['number']);
/** Types that support a free-text placeholder. */
export const PLACEHOLDER_TYPES: ReadonlySet<FieldType> = new Set<FieldType>([
  'short_text',
  'long_text',
  'number',
]);

/** The comparison operators a conditional rule may use (mirrors backend). */
export const CONDITION_OPS: ConditionOp[] = [
  'eq',
  'neq',
  'in',
  'not_in',
  'gt',
  'lt',
  'gte',
  'lte',
  'empty',
  'not_empty',
];

/** Human labels for the operators, for the rule editor dropdown. */
export const CONDITION_OP_LABELS: Record<ConditionOp, string> = {
  eq: 'equals',
  neq: 'does not equal',
  in: 'is one of',
  not_in: 'is not one of',
  gt: 'is greater than',
  lt: 'is less than',
  gte: 'is at least',
  lte: 'is at most',
  empty: 'is empty',
  not_empty: 'is filled in',
};

/** Operators that take no comparison value. */
export const VALUELESS_OPS: ReadonlySet<ConditionOp> = new Set<ConditionOp>(['empty', 'not_empty']);

export const RATING_MIN_SCALE = 2;
export const RATING_MAX_SCALE = 10;
export const DEFAULT_RATING_SCALE = 5;

export const CATEGORY_ORDER: TemplateCategory[] = [
  'safety',
  'quality',
  'handover',
  'inspection',
  'commissioning',
  'custom',
];

export const CATEGORY_LABELS: Record<TemplateCategory, string> = {
  safety: 'Safety',
  quality: 'Quality & acceptance',
  handover: 'Handover',
  inspection: 'Inspection',
  commissioning: 'Commissioning',
  custom: 'Custom',
};

/* -- Keys ------------------------------------------------------------------ */

export function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
    .slice(0, 60);
}

/**
 * Fill blank keys from labels and de-duplicate, mirroring
 * validation.normalize_fields so the client and server agree on keys before a
 * save. Never mutates the input.
 */
export function ensureFieldKeys(fields: FormFieldDef[]): FormFieldDef[] {
  const seen = new Set<string>();
  return fields.map((f, idx) => {
    let key = (f.key || '').trim() || slugify(f.label) || `field_${idx + 1}`;
    const base = key;
    let n = 2;
    while (seen.has(key)) {
      key = `${base}_${n}`;
      n += 1;
    }
    seen.add(key);
    return { ...f, key };
  });
}

/* -- Template integrity (mirror of validate_template_fields) --------------- */

export interface BuilderIssue {
  index: number;
  message: string;
}

export function validateTemplateFields(fields: FormFieldDef[]): BuilderIssue[] {
  const issues: BuilderIssue[] = [];
  if (fields.length === 0) {
    issues.push({ index: -1, message: 'Add at least one field.' });
    return issues;
  }
  const knownKeys = new Set(
    fields.map((f, idx) => (f.key || '').trim() || slugify(f.label) || `field_${idx + 1}`),
  );
  let fillable = 0;
  fields.forEach((f, idx) => {
    const key = (f.key || '').trim() || slugify(f.label) || `field_${idx + 1}`;
    if (!f.label.trim()) issues.push({ index: idx, message: 'Every field needs a label.' });
    // Only a field the user can enter counts as fillable (not a section, not a formula).
    if (!LAYOUT_TYPES.has(f.type) && !COMPUTED_TYPES.has(f.type)) fillable += 1;

    if (CHOICE_TYPES.has(f.type)) {
      const distinct = new Set((f.options ?? []).map((o) => o.trim()).filter(Boolean));
      if (distinct.size < 2) {
        issues.push({ index: idx, message: 'A choice field needs at least two options.' });
      }
    }
    if (f.type === 'rating') {
      const scale = f.max_rating ?? DEFAULT_RATING_SCALE;
      if (scale < RATING_MIN_SCALE || scale > RATING_MAX_SCALE) {
        issues.push({ index: idx, message: `Rating scale must be ${RATING_MIN_SCALE}-${RATING_MAX_SCALE}.` });
      }
    }
    if (f.type === 'number' && f.min != null && f.max != null && f.min > f.max) {
      issues.push({ index: idx, message: 'The minimum cannot be greater than the maximum.' });
    }
    if (TEXT_TYPES.has(f.type) && f.pattern && f.pattern.trim()) {
      try {
        new RegExp(f.pattern);
      } catch {
        issues.push({ index: idx, message: 'The validation pattern is not a valid expression.' });
      }
    }
    if (f.type === 'formula') {
      const expr = (f.formula ?? '').trim();
      if (!expr) {
        issues.push({ index: idx, message: 'A computed field needs a formula.' });
      } else {
        const parsed = parseFormula(expr);
        if (!parsed.ok) {
          issues.push({ index: idx, message: `Invalid formula: ${parsed.error}` });
        } else {
          for (const ref of parsed.vars) {
            if (ref === key) {
              issues.push({ index: idx, message: 'A formula cannot refer to its own field.' });
            } else if (!knownKeys.has(ref)) {
              issues.push({ index: idx, message: `A formula refers to unknown field '${ref}'.` });
            }
          }
        }
      }
    }
  });
  if (fillable === 0) {
    issues.push({ index: -1, message: 'Add at least one field to fill in, not only section headers.' });
  }
  return issues;
}

/* -- Submission completeness (mirror of _is_empty_answer) ------------------ */

export function isAnswerEmpty(type: FieldType, value: AnswerValue): boolean {
  if (value === null || value === undefined) return true;
  if (type === 'checkbox') return value !== true;
  if (type === 'multi_choice') {
    return !(Array.isArray(value) && value.filter((v) => String(v).trim()).length > 0);
  }
  if (type === 'photo') {
    if (Array.isArray(value)) return value.filter((v) => String(v).trim()).length === 0;
    return String(value).trim() === '';
  }
  if (type === 'signature') {
    if (value && typeof value === 'object' && !Array.isArray(value)) {
      const sig = value as { name?: string; data?: string };
      return !(String(sig.name ?? '').trim() || String(sig.data ?? '').trim());
    }
    return String(value).trim() === '';
  }
  if (typeof value === 'string') return value.trim() === '';
  return false;
}

/**
 * Keys of required fields that are not yet answered (for progress + gating).
 *
 * Honours conditional logic: a field hidden by a visible_if rule is skipped, and
 * a field switched on by a required_if rule is enforced exactly like a statically
 * required one. Computed (formula) fields are never required. Mirrors the backend
 * validate_submission_answers gate so the client and server agree on completeness.
 */
export function missingRequiredKeys(fields: FormFieldDef[], answers: AnswerMap): string[] {
  const state = resolveVisibility(fields, answers);
  const missing: string[] = [];
  for (const f of fields) {
    if (LAYOUT_TYPES.has(f.type) || COMPUTED_TYPES.has(f.type)) continue;
    const s = state[f.key];
    if (s && !s.visible) continue;
    const required = s ? s.required : f.required;
    if (!required) continue;
    if (isAnswerEmpty(f.type, answers[f.key] ?? null)) missing.push(f.key);
  }
  return missing;
}

/** Count of currently-required, visible fields (denominator for the meter). */
export function requiredCount(fields: FormFieldDef[], answers: AnswerMap = {}): number {
  const state = resolveVisibility(fields, answers);
  let count = 0;
  for (const f of fields) {
    if (LAYOUT_TYPES.has(f.type) || COMPUTED_TYPES.has(f.type)) continue;
    const s = state[f.key];
    if (s && !s.visible) continue;
    if (s ? s.required : f.required) count += 1;
  }
  return count;
}

/* -- Safe formula evaluator (mirror of backend formula.py) ----------------- */
//
// A tiny recursive-descent parser for the same minimal grammar the backend
// accepts: number literals, bare field-key names, unary +/-, binary + - * /,
// parentheses, and the pure functions round / min / max. There is NO eval, no
// property access, no other names or calls - anything outside the grammar is a
// parse error. Arithmetic is plain JS number here (enough for a live preview);
// the backend recomputes with exact Decimal on complete and is the source of
// truth for stored values.

type Tok = { t: 'num'; v: number } | { t: 'name'; v: string } | { t: 'op'; v: string };

const FORMULA_FUNCS = new Set(['round', 'min', 'max']);
const MAX_FORMULA_LEN = 512;

function tokenizeFormula(src: string): Tok[] {
  const tokens: Tok[] = [];
  let i = 0;
  const s = src;
  while (i < s.length) {
    const c = s[i]!;
    if (c === ' ' || c === '\t' || c === '\n' || c === '\r') {
      i += 1;
      continue;
    }
    if ('+-*/(),'.includes(c)) {
      tokens.push({ t: 'op', v: c });
      i += 1;
      continue;
    }
    if ((c >= '0' && c <= '9') || c === '.') {
      let j = i + 1;
      while (j < s.length && /[0-9.]/.test(s[j]!)) j += 1;
      const num = Number(s.slice(i, j));
      if (!Number.isFinite(num)) throw new Error('bad number');
      tokens.push({ t: 'num', v: num });
      i = j;
      continue;
    }
    if (/[A-Za-z_]/.test(c)) {
      let j = i + 1;
      while (j < s.length && /[A-Za-z0-9_]/.test(s[j]!)) j += 1;
      tokens.push({ t: 'name', v: s.slice(i, j) });
      i = j;
      continue;
    }
    throw new Error(`unexpected character '${c}'`);
  }
  return tokens;
}

/** A parsed formula AST node. */
type FNode =
  | { k: 'num'; v: number }
  | { k: 'var'; v: string }
  | { k: 'neg'; a: FNode }
  | { k: 'bin'; op: string; a: FNode; b: FNode }
  | { k: 'call'; fn: string; args: FNode[] };

class FormulaParser {
  private pos = 0;
  constructor(private readonly toks: Tok[]) {}

  parse(): FNode {
    const node = this.expr();
    if (this.pos < this.toks.length) throw new Error('unexpected trailing input');
    return node;
  }
  private peek(): Tok | undefined {
    return this.toks[this.pos];
  }
  private eat(): Tok {
    const t = this.toks[this.pos];
    if (!t) throw new Error('unexpected end of formula');
    this.pos += 1;
    return t;
  }
  private expr(): FNode {
    let left = this.term();
    for (let t = this.peek(); t && t.t === 'op' && (t.v === '+' || t.v === '-'); t = this.peek()) {
      this.eat();
      left = { k: 'bin', op: t.v, a: left, b: this.term() };
    }
    return left;
  }
  private term(): FNode {
    let left = this.unary();
    for (let t = this.peek(); t && t.t === 'op' && (t.v === '*' || t.v === '/'); t = this.peek()) {
      this.eat();
      left = { k: 'bin', op: t.v, a: left, b: this.unary() };
    }
    return left;
  }
  private unary(): FNode {
    const t = this.peek();
    if (t && t.t === 'op' && (t.v === '+' || t.v === '-')) {
      this.eat();
      const a = this.unary();
      return t.v === '-' ? { k: 'neg', a } : a;
    }
    return this.atom();
  }
  private atom(): FNode {
    const t = this.eat();
    if (t.t === 'num') return { k: 'num', v: t.v };
    if (t.t === 'op' && t.v === '(') {
      const inner = this.expr();
      const close = this.eat();
      if (close.t !== 'op' || close.v !== ')') throw new Error('expected )');
      return inner;
    }
    if (t.t === 'name') {
      const next = this.peek();
      if (next && next.t === 'op' && next.v === '(') {
        if (!FORMULA_FUNCS.has(t.v)) throw new Error(`unknown function '${t.v}'`);
        this.eat(); // (
        const args: FNode[] = [];
        if (!(this.peek()?.t === 'op' && this.peek()?.v === ')')) {
          args.push(this.expr());
          while (this.peek()?.t === 'op' && this.peek()?.v === ',') {
            this.eat();
            args.push(this.expr());
          }
        }
        const close = this.eat();
        if (close.t !== 'op' || close.v !== ')') throw new Error('expected )');
        return { k: 'call', fn: t.v, args };
      }
      return { k: 'var', v: t.v };
    }
    throw new Error('unexpected token');
  }
}

export interface ParsedFormula {
  ok: boolean;
  error?: string;
  vars: string[];
  node?: FNode;
}

function collectVars(node: FNode, out: Set<string>): void {
  if (node.k === 'var') out.add(node.v);
  else if (node.k === 'neg') collectVars(node.a, out);
  else if (node.k === 'bin') {
    collectVars(node.a, out);
    collectVars(node.b, out);
  } else if (node.k === 'call') node.args.forEach((a) => collectVars(a, out));
}

/** Parse + safety-check a formula, returning its referenced variable names. */
export function parseFormula(expr: string): ParsedFormula {
  let text = (expr ?? '').trim();
  if (text.startsWith('=')) text = text.slice(1).trim();
  if (!text) return { ok: false, error: 'empty formula', vars: [] };
  if (text.length > MAX_FORMULA_LEN) return { ok: false, error: 'formula too long', vars: [] };
  try {
    const node = new FormulaParser(tokenizeFormula(text)).parse();
    const vars = new Set<string>();
    collectVars(node, vars);
    return { ok: true, vars: [...vars], node };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'invalid formula', vars: [] };
  }
}

function evalNode(node: FNode, vars: Record<string, number>): number {
  switch (node.k) {
    case 'num':
      return node.v;
    case 'var': {
      const v = vars[node.v];
      if (v === undefined) throw new Error(`unknown variable '${node.v}'`);
      return v;
    }
    case 'neg':
      return -evalNode(node.a, vars);
    case 'bin': {
      const a = evalNode(node.a, vars);
      const b = evalNode(node.b, vars);
      if (node.op === '+') return a + b;
      if (node.op === '-') return a - b;
      if (node.op === '*') return a * b;
      if (b === 0) throw new Error('division by zero');
      return a / b;
    }
    case 'call': {
      const args = node.args.map((a) => evalNode(a, vars));
      if (node.fn === 'min') return Math.min(...args);
      if (node.fn === 'max') return Math.max(...args);
      // round(x) / round(x, n) - half-up on the non-negative domain.
      const ndigits = args.length === 2 ? Math.trunc(args[1]!) : 0;
      const factor = 10 ** Math.max(0, ndigits);
      return Math.round((args[0]! + Number.EPSILON) * factor) / factor;
    }
  }
}

/** True when a value is a finite number or a plain numeric string (not a bool). */
export function isNumericAnswer(value: AnswerValue): boolean {
  if (typeof value === 'boolean' || value == null) return false;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return parseDecimalInput(value) !== null;
  return false;
}

function toNumber(value: AnswerValue): number | null {
  if (typeof value === 'number') return Number.isFinite(value) ? value : null;
  if (typeof value === 'string') {
    return parseDecimalInput(value);
  }
  return null;
}

/**
 * Compute every formula field's value from the current answers and return them
 * as a { key: number | null } map. A blank / non-numeric operand is treated as 0
 * (a running total works before the form is finished); a formula that cannot be
 * evaluated (division by zero, a bad reference) yields null. This is a live
 * preview; the backend recomputes exactly on complete.
 */
export function computeFormulas(fields: FormFieldDef[], answers: AnswerMap): Record<string, number | null> {
  const out: Record<string, number | null> = {};
  const vars: Record<string, number> = {};
  for (const f of fields) {
    if (!f.key) continue;
    const n = toNumber(answers[f.key] ?? null);
    if (n != null) vars[f.key] = n;
    else vars[f.key] = 0;
  }
  // Iterate so a formula that reads another formula converges (capped by count).
  const formulaFields = fields.filter((f) => f.type === 'formula' && (f.formula ?? '').trim());
  for (let pass = 0; pass < formulaFields.length + 1; pass += 1) {
    let changed = false;
    for (const f of formulaFields) {
      const parsed = parseFormula(f.formula ?? '');
      let value: number | null = null;
      if (parsed.ok && parsed.node) {
        try {
          value = evalNode(parsed.node, vars);
          if (!Number.isFinite(value)) value = null;
        } catch {
          value = null;
        }
      }
      if (out[f.key] !== value) changed = true;
      out[f.key] = value;
      if (value != null) vars[f.key] = value;
    }
    if (!changed) break;
  }
  return out;
}

/**
 * Seed field defaults into an answers map for any field left blank, returning a
 * new map (never mutates). Used when opening a draft so a configured default
 * value is prefilled but a real saved answer is never overwritten. Layout and
 * computed fields are skipped.
 */
export function applyDefaults(fields: FormFieldDef[], answers: AnswerMap): AnswerMap {
  const next: AnswerMap = { ...answers };
  for (const f of fields) {
    if (!f.key || LAYOUT_TYPES.has(f.type) || COMPUTED_TYPES.has(f.type)) continue;
    if (f.default == null) continue;
    if (!isAnswerEmpty(f.type, next[f.key] ?? null)) continue;
    next[f.key] = f.default as AnswerValue;
  }
  return next;
}

/* -- Conditional visibility resolver (mirror of backend conditional.py) ----- */

export interface FieldState {
  visible: boolean;
  required: boolean;
}

/**
 * Resolve every keyed field's live visible / required state from the answers,
 * mirroring backend conditional.evaluate_visibility. A field with no visible_if
 * is visible; a hidden field is never required and contributes no answer to
 * fields that depend on it; a visible field is required when its static required
 * flag is set or its required_if rule holds. Never throws - a bad rule, a missing
 * reference or a cycle all resolve to safe defaults (show, do not require).
 */
export function resolveVisibility(fields: FormFieldDef[], answers: AnswerMap): Record<string, FieldState> {
  const byKey = new Map<string, FormFieldDef>();
  const order: string[] = [];
  for (const f of fields) {
    const key = (f.key || '').trim();
    if (!key || byKey.has(key)) continue;
    byKey.set(key, f);
    order.push(key);
  }
  const visibleCache = new Map<string, boolean>();
  const resolving = new Set<string>();

  const resolveVisible = (key: string): boolean => {
    const cached = visibleCache.get(key);
    if (cached !== undefined) return cached;
    const field = byKey.get(key);
    if (!field) return true;
    const expr = field.visible_if;
    if (!expr) {
      visibleCache.set(key, true);
      return true;
    }
    if (resolving.has(key)) return true; // break a reference cycle
    resolving.add(key);
    const visible = safeEval(expr, true);
    resolving.delete(key);
    visibleCache.set(key, visible);
    return visible;
  };

  const answerOf = (key: string): AnswerValue => {
    if (!resolveVisible(key)) return null;
    return answers[key] ?? null;
  };

  function safeEval(expr: ConditionExpr, def: boolean): boolean {
    try {
      return evalExpr(expr);
    } catch {
      return def;
    }
  }
  function evalExpr(expr: ConditionExpr): boolean {
    if (!expr || typeof expr !== 'object') return false;
    if (Array.isArray(expr.all)) return expr.all.every((sub) => evalExpr(sub));
    if (Array.isArray(expr.any)) return expr.any.some((sub) => evalExpr(sub));
    return evalRule(expr);
  }
  function evalRule(rule: ConditionExpr): boolean {
    const op = rule.op;
    if (!op || !CONDITION_OPS.includes(op)) return false;
    const ref = (rule.field || '').trim();
    const field = ref ? byKey.get(ref) : undefined;
    if (!ref || !field) return false;
    return applyOp(op, field, answerOf(ref), rule.value ?? null);
  }

  const result: Record<string, FieldState> = {};
  for (const key of order) {
    const field = byKey.get(key)!;
    if (!resolveVisible(key)) {
      result[key] = { visible: false, required: false };
      continue;
    }
    let required = !!field.required;
    if (field.required_if && !required) required = safeEval(field.required_if, false);
    result[key] = { visible: true, required };
  }
  return result;
}

function isBlankValue(field: FormFieldDef, value: AnswerValue): boolean {
  if (value == null) return true;
  if (field.type === 'checkbox') return value !== true;
  if (typeof value === 'boolean') return false;
  if (Array.isArray(value)) return !value.some((v) => String(v).trim());
  if (typeof value === 'object') {
    const sig = value as { name?: string; data?: string };
    return !(String(sig.name ?? '').trim() || String(sig.data ?? '').trim());
  }
  return String(value).trim() === '';
}

function applyOp(op: ConditionOp, field: FormFieldDef, left: AnswerValue, value: AnswerValue): boolean {
  if (op === 'empty') return isBlankValue(field, left);
  if (op === 'not_empty') return !isBlankValue(field, left);
  if (op === 'eq') return scalarEqual(left, value);
  if (op === 'neq') return !scalarEqual(left, value);
  if (op === 'in') return inCandidates(left, value);
  if (op === 'not_in') return !inCandidates(left, value);
  const l = toNumber(left);
  const r = toNumber(value);
  if (l == null || r == null) return false;
  if (op === 'gt') return l > r;
  if (op === 'lt') return l < r;
  if (op === 'gte') return l >= r;
  if (op === 'lte') return l <= r;
  return false;
}

function normToken(value: unknown): string {
  const n = typeof value === 'number' ? value : (parseDecimalInput(String(value)) ?? NaN);
  if (typeof value !== 'boolean' && String(value).trim() !== '' && Number.isFinite(n)) return `n:${n}`;
  return `s:${String(value).trim()}`;
}

function scalarEqual(left: AnswerValue, value: AnswerValue): boolean {
  if (left == null || value == null) return left == null && value == null;
  if (typeof left === 'boolean' || typeof value === 'boolean') {
    return asTruth(left) === asTruth(value);
  }
  if (Array.isArray(left) || Array.isArray(value)) {
    const a = (Array.isArray(left) ? left : [left]).map(normToken).sort();
    const b = (Array.isArray(value) ? value : [value]).map(normToken).sort();
    return a.length === b.length && a.every((x, i) => x === b[i]);
  }
  return normToken(left) === normToken(value);
}

function asTruth(value: AnswerValue): boolean {
  if (typeof value === 'boolean') return value;
  if (value == null) return false;
  const s = String(value).trim().toLowerCase();
  if (['true', 'yes', 'y', '1', 'on', 'checked'].includes(s)) return true;
  if (['false', 'no', 'n', '0', 'off', 'unchecked', ''].includes(s)) return false;
  return true;
}

function inCandidates(left: AnswerValue, value: AnswerValue): boolean {
  const candidates = new Set((Array.isArray(value) ? value : [value]).filter((v) => String(v).trim()).map(normToken));
  if (candidates.size === 0) return false;
  if (Array.isArray(left)) return left.some((item) => candidates.has(normToken(item)));
  if (left == null) return false;
  return candidates.has(normToken(left));
}
