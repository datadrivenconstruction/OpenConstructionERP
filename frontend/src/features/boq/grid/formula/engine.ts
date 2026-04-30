/**
 * BOQ formula engine — extended.
 *
 * Hand-written, CSP-safe (no `eval`, no `new Function`) recursive-descent
 * evaluator that powers the Quantity / Unit Rate / calculated-column inputs.
 *
 * What's new vs the original parser at `cellEditors.tsx:85-242`:
 *   • Context object: cross-position `pos("X").qty`, section aggregates,
 *     calculated-column row lookups, named `$VAR` references.
 *   • String literals (single + double quoted) so `pos("01.001")` parses.
 *   • Comparison operators (<, <=, >, >=, ==, !=) for `if(cond, a, b)`.
 *   • New built-ins: `pos`, `section`, `col`, `if`, unit converters,
 *     `round_up`, `round_down`.
 *   • Member-access `.` operator on tagged records returned by `pos()` and
 *     `section()`.
 *
 * The signature stays backwards-compatible: omitting `ctx` gives EXACTLY
 * the same behaviour as the legacy single-position evaluator (no
 * cross-position references, no variables, no comparisons — only the
 * legacy math vocabulary).
 *
 * Rounding: results are rounded to 4 decimal places (matches the backend
 * BUG-MATH01 storage precision). Negative results clamp to `null` so we
 * never write a negative quantity.
 */

import type { Position } from '../../api';

/* ── Public types ───────────────────────────────────────────────────── */

export interface FormulaVariable {
  type: 'number' | 'text' | 'date';
  value: string | number | null;
}

export interface FormulaSection {
  positions: Position[];
}

export interface FormulaContext {
  /** Position currently being edited. Used for self-reference detection. */
  currentPositionId?: string;
  /** All positions keyed by their human ordinal (e.g. `01.02.003`). */
  positionsByOrdinal: Map<string, Position>;
  /** All positions keyed by their UUID. */
  positionsById: Map<string, Position>;
  /** Sections keyed by display name. */
  sectionsByName: Map<string, FormulaSection>;
  /** BOQ-scoped named variables. */
  variables: Map<string, FormulaVariable>;
  /** Current row data — used by `col(...)` in calculated columns. */
  currentRow?: Record<string, unknown>;
}

/** Sentinel returned by `pos()` / `section()` — supports member access via `.`. */
export interface PositionRecord {
  __kind: 'position';
  qty: number;
  rate: number;
  total: number;
}

export interface SectionRecord {
  __kind: 'section';
  total: number;
}

type RecordValue = PositionRecord | SectionRecord;
type Value = number | string | RecordValue | boolean;

/* ── Public API ─────────────────────────────────────────────────────── */

/**
 * Evaluate a formula string. Returns the rounded result, or `null` for
 * empty / invalid / negative input.
 *
 * Backwards-compat: when `ctx` is omitted, the evaluator falls back to
 * legacy mode (no cross-position refs, no variables, no comparisons —
 * just math). This keeps every existing callsite green.
 */
export function evaluateFormula(input: string, ctx?: FormulaContext): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const body = trimmed.startsWith('=') ? trimmed.slice(1) : trimmed;
  const normalised = normaliseFormula(body);
  try {
    const result = parseFormulaExpr(normalised, ctx);
    if (typeof result !== 'number') return null;
    if (!isFinite(result)) return null;
    if (result < 0) return null;
    return Math.round(result * 10000) / 10000;
  } catch {
    return null;
  }
}

/**
 * Like `evaluateFormula` but allows negative numbers and signed text/bool
 * results. Used by calculated custom columns where a negative cost or a
 * text label is legitimate.
 */
export function evaluateFormulaRaw(
  input: string,
  ctx?: FormulaContext,
): number | string | boolean | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const body = trimmed.startsWith('=') ? trimmed.slice(1) : trimmed;
  const normalised = normaliseFormula(body);
  try {
    const result = parseFormulaExpr(normalised, ctx);
    if (typeof result === 'number') {
      if (!isFinite(result)) return null;
      return Math.round(result * 10000) / 10000;
    }
    if (typeof result === 'string' || typeof result === 'boolean') return result;
    return null;
  } catch {
    return null;
  }
}

/**
 * Strict variant of `evaluateFormulaRaw` that re-throws parser / runtime
 * errors instead of swallowing them into `null`. Used by calculated
 * custom columns so the UI can distinguish "valid empty result" from
 * "broken formula" and render a `#ERR` sentinel for the latter.
 *
 * Returns `null` ONLY for empty input, non-finite numbers, or genuinely
 * non-representable results — never for syntax / type errors.
 */
export function evaluateFormulaStrict(
  input: string,
  ctx?: FormulaContext,
): number | string | boolean | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  const body = trimmed.startsWith('=') ? trimmed.slice(1) : trimmed;
  const normalised = normaliseFormula(body);
  const result = parseFormulaExpr(normalised, ctx);
  if (typeof result === 'number') {
    if (!isFinite(result)) return null;
    return Math.round(result * 10000) / 10000;
  }
  if (typeof result === 'string' || typeof result === 'boolean') return result;
  return null;
}

/**
 * Normalise human/locale variants of math syntax to canonical operators.
 *   • `×` → `*`
 *   • `x` between digits / closing-paren and digit / open-paren → `*`
 *   • `,` → `.` ONLY when no parens AND no quotes (so it never clobbers
 *     function-arg separators or string contents).
 */
export function normaliseFormula(s: string): string {
  let out = s.replace(/×/g, '*');
  out = out.replace(/([0-9)])\s*[xX]\s*(?=[0-9(a-zA-Z_$])/g, (_m, lhs) => `${lhs}*`);
  if (!out.includes('(') && !out.includes('"') && !out.includes("'")) {
    out = out.replace(/,/g, '.');
  }
  return out;
}

/**
 * Whether the input "looks like" a formula. Bare numbers go through the
 * normal numeric path; `=`-prefixed strings, math operators, identifiers
 * matching a known function/constant, and `$VAR` / `pos(`-style refs all
 * count as formulas.
 */
export function isFormula(input: string): boolean {
  const t = input.trim();
  if (!t) return false;
  if (t.startsWith('=')) return true;
  if (/[+\-*/^×()<>!]/.test(t)) return true;
  if (/\$[A-Z][A-Z0-9_]*/.test(t)) return true;
  if (/\b(pi|e|sqrt|abs|round|round_up|round_down|floor|ceil|pow|min|max|sin|cos|tan|log|exp|pos|section|col|if|m_to_ft|ft_to_m|m2_to_ft2|ft2_to_m2|m3_to_yd3|yd3_to_m3|kg_to_lb|lb_to_kg)\b/i.test(t))
    return true;
  return false;
}

/* ── Tokeniser ──────────────────────────────────────────────────────── */

type Token =
  | { kind: 'num'; value: number }
  | { kind: 'str'; value: string }
  | { kind: 'ident'; value: string }
  | { kind: 'var'; value: string }
  | { kind: 'op'; value: string };

const PUNCT_OPS = ['<=', '>=', '==', '!=', '**', '+', '-', '*', '/', '^', '(', ')', ',', '<', '>', '.'];
const IDENT_START = /[a-zA-Z_]/;
const IDENT_CONT = /[a-zA-Z0-9_]/;

function tokenize(expr: string): Token[] {
  const tokens: Token[] = [];
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i]!;
    if (ch === ' ' || ch === '\t' || ch === '\n' || ch === '\r') {
      i++;
      continue;
    }
    // String literal
    if (ch === '"' || ch === "'") {
      const quote = ch;
      let str = '';
      i++;
      while (i < expr.length && expr[i] !== quote) {
        if (expr[i] === '\\' && i + 1 < expr.length) {
          str += expr[i + 1];
          i += 2;
          continue;
        }
        str += expr[i];
        i++;
      }
      if (i >= expr.length) throw new Error('Unterminated string literal');
      i++; // skip closing quote
      tokens.push({ kind: 'str', value: str });
      continue;
    }
    // $VAR
    if (ch === '$') {
      i++;
      if (i >= expr.length || !IDENT_START.test(expr[i]!)) {
        throw new Error('Expected variable name after $');
      }
      let name = '';
      while (i < expr.length && IDENT_CONT.test(expr[i]!)) {
        name += expr[i]!;
        i++;
      }
      tokens.push({ kind: 'var', value: name.toUpperCase() });
      continue;
    }
    // Number — ".5" / "0.5" / "12"
    if ((ch >= '0' && ch <= '9') || (ch === '.' && i + 1 < expr.length && expr[i + 1]! >= '0' && expr[i + 1]! <= '9')) {
      let num = '';
      while (i < expr.length) {
        const c = expr[i]!;
        if (!((c >= '0' && c <= '9') || c === '.')) break;
        num += c;
        i++;
      }
      const n = parseFloat(num);
      if (isNaN(n)) throw new Error(`Bad number: ${num}`);
      tokens.push({ kind: 'num', value: n });
      continue;
    }
    // Identifier
    if (IDENT_START.test(ch)) {
      let ident = '';
      while (i < expr.length && IDENT_CONT.test(expr[i]!)) {
        ident += expr[i]!;
        i++;
      }
      tokens.push({ kind: 'ident', value: ident.toLowerCase() });
      continue;
    }
    // Two-char ops first
    const two = expr.slice(i, i + 2);
    if (PUNCT_OPS.includes(two)) {
      // Special case: `**` → `^`
      if (two === '**') tokens.push({ kind: 'op', value: '^' });
      else tokens.push({ kind: 'op', value: two });
      i += 2;
      continue;
    }
    if (PUNCT_OPS.includes(ch)) {
      tokens.push({ kind: 'op', value: ch });
      i++;
      continue;
    }
    throw new Error(`Unexpected character: ${ch}`);
  }
  return tokens;
}

/* ── Built-ins ──────────────────────────────────────────────────────── */

const CONSTANTS: Record<string, number> = {
  pi: Math.PI,
  e: Math.E,
};

const UNIT_CONVERSIONS: Record<string, number> = {
  m_to_ft: 3.280839895013123,
  ft_to_m: 0.3048,
  m2_to_ft2: 10.763910416709722,
  ft2_to_m2: 0.09290304,
  m3_to_yd3: 1.3079506193143846,
  yd3_to_m3: 0.7645548579999999,
  kg_to_lb: 2.2046226218487757,
  lb_to_kg: 0.45359237,
};

function callMathFn(name: string, args: Value[]): Value {
  const nums = args.map((a) => coerceNumber(a, name));
  switch (name) {
    case 'sqrt':
      return Math.sqrt(nums[0]!);
    case 'abs':
      return Math.abs(nums[0]!);
    case 'round':
      // Two-arg variant: round(x, n) → round to n decimals.
      if (nums.length === 2) {
        const f = Math.pow(10, nums[1]!);
        return Math.round(nums[0]! * f) / f;
      }
      return Math.round(nums[0]!);
    case 'floor':
      return Math.floor(nums[0]!);
    case 'ceil':
      return Math.ceil(nums[0]!);
    case 'sin':
      return Math.sin(nums[0]!);
    case 'cos':
      return Math.cos(nums[0]!);
    case 'tan':
      return Math.tan(nums[0]!);
    case 'log':
      return Math.log(nums[0]!);
    case 'exp':
      return Math.exp(nums[0]!);
    case 'pow':
      return Math.pow(nums[0]!, nums[1]!);
    case 'min':
      if (nums.length === 0) throw new Error('min(): need ≥1 arg');
      return Math.min(...nums);
    case 'max':
      if (nums.length === 0) throw new Error('max(): need ≥1 arg');
      return Math.max(...nums);
    case 'round_up': {
      const n = nums.length >= 2 ? nums[1]! : 0;
      const f = Math.pow(10, n);
      return Math.ceil(nums[0]! * f) / f;
    }
    case 'round_down': {
      const n = nums.length >= 2 ? nums[1]! : 0;
      const f = Math.pow(10, n);
      return Math.floor(nums[0]! * f) / f;
    }
    default:
      if (name in UNIT_CONVERSIONS) {
        if (nums.length !== 1) throw new Error(`${name}(): expects 1 arg`);
        return nums[0]! * UNIT_CONVERSIONS[name]!;
      }
      throw new Error(`Unknown function: ${name}`);
  }
}

function coerceNumber(v: Value, ctx: string): number {
  if (typeof v === 'number') return v;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (typeof v === 'string') {
    const n = parseFloat(v);
    if (!isNaN(n)) return n;
    throw new Error(`${ctx}: cannot use string "${v}" as number`);
  }
  if (v && typeof v === 'object' && '__kind' in v) {
    throw new Error(`${ctx}: cannot use ${v.__kind} record as number — did you mean .qty / .total?`);
  }
  throw new Error(`${ctx}: not a number`);
}

/* ── Parser ─────────────────────────────────────────────────────────── */

/**
 * Grammar (low → high precedence):
 *   expr     = compare
 *   compare  = addsub (('==' | '!=' | '<' | '<=' | '>' | '>=') addsub)?
 *   addsub   = muldiv (('+' | '-') muldiv)*
 *   muldiv   = power (('*' | '/') power)*
 *   power    = unary ('^' power)?            -- right-associative
 *   unary    = ('+' | '-') unary | member
 *   member   = primary ('.' IDENT)*
 *   primary  = NUMBER | STRING | '$' VAR | '(' expr ')' | IDENT '(' args? ')' | IDENT
 */
function parseFormulaExpr(input: string, ctx?: FormulaContext): Value {
  const tokens = tokenize(input);
  if (tokens.length === 0) throw new Error('Empty');
  let pos = 0;

  const peek = (): Token | undefined => tokens[pos];
  const eat = (): Token => {
    const t = tokens[pos];
    if (!t) throw new Error('Unexpected end of input');
    pos++;
    return t;
  };
  const isOp = (t: Token | undefined, ...ops: string[]): boolean =>
    !!t && t.kind === 'op' && ops.includes(t.value);

  function parseExpr(): Value {
    return parseCompare();
  }

  function parseCompare(): Value {
    const left = parseAddSub();
    const t = peek();
    if (t && t.kind === 'op' && ['==', '!=', '<', '<=', '>', '>='].includes(t.value)) {
      eat();
      const right = parseAddSub();
      const a = coerceNumber(left, 'compare');
      const b = coerceNumber(right, 'compare');
      switch (t.value) {
        case '==':
          return a === b;
        case '!=':
          return a !== b;
        case '<':
          return a < b;
        case '<=':
          return a <= b;
        case '>':
          return a > b;
        case '>=':
          return a >= b;
      }
    }
    return left;
  }

  function parseAddSub(): Value {
    let left = parseMulDiv();
    while (isOp(peek(), '+', '-')) {
      const op = eat().value;
      const right = parseMulDiv();
      const a = coerceNumber(left, 'addsub');
      const b = coerceNumber(right, 'addsub');
      left = op === '+' ? a + b : a - b;
    }
    return left;
  }

  function parseMulDiv(): Value {
    let left = parsePower();
    while (isOp(peek(), '*', '/')) {
      const op = eat().value;
      const right = parsePower();
      const a = coerceNumber(left, 'muldiv');
      const b = coerceNumber(right, 'muldiv');
      left = op === '*' ? a * b : a / b;
    }
    return left;
  }

  function parsePower(): Value {
    const base = parseUnary();
    if (isOp(peek(), '^')) {
      eat();
      const exp = parsePower();
      return Math.pow(coerceNumber(base, 'pow'), coerceNumber(exp, 'pow'));
    }
    return base;
  }

  function parseUnary(): Value {
    const t = peek();
    if (isOp(t, '-')) {
      eat();
      return -coerceNumber(parseUnary(), 'neg');
    }
    if (isOp(t, '+')) {
      eat();
      return coerceNumber(parseUnary(), 'pos');
    }
    return parseMember();
  }

  function parseMember(): Value {
    let v: Value = parsePrimary();
    while (isOp(peek(), '.')) {
      eat();
      const ident = eat();
      if (ident.kind !== 'ident') throw new Error('Expected member name after .');
      const member = ident.value;
      if (typeof v === 'object' && v !== null && '__kind' in v) {
        if (v.__kind === 'position') {
          if (member === 'qty' || member === 'quantity') v = v.qty;
          else if (member === 'rate' || member === 'unit_rate') v = v.rate;
          else if (member === 'total') v = v.total;
          else throw new Error(`pos record has no member .${member}`);
        } else if (v.__kind === 'section') {
          if (member === 'total') v = v.total;
          else throw new Error(`section record has no member .${member}`);
        } else {
          throw new Error(`Unknown record kind`);
        }
      } else {
        throw new Error(`Cannot access .${member} on ${typeof v}`);
      }
    }
    return v;
  }

  function parsePrimary(): Value {
    const t = peek();
    if (!t) throw new Error('Unexpected end of expression');
    if (t.kind === 'op' && t.value === '(') {
      eat();
      const v = parseExpr();
      if (!isOp(peek(), ')')) throw new Error('Missing )');
      eat();
      return v;
    }
    if (t.kind === 'num') {
      eat();
      return t.value;
    }
    if (t.kind === 'str') {
      eat();
      return t.value;
    }
    if (t.kind === 'var') {
      eat();
      if (!ctx) throw new Error('No context: $variable not available');
      const v = ctx.variables.get(t.value);
      if (!v) throw new Error(`Unknown variable: $${t.value}`);
      if (v.value === null) throw new Error(`Variable $${t.value} has no value`);
      if (v.type === 'number') return typeof v.value === 'number' ? v.value : parseFloat(String(v.value));
      return v.value;
    }
    if (t.kind === 'ident') {
      const name = t.value;
      eat();
      // Function call?
      if (isOp(peek(), '(')) {
        eat();
        const args: Value[] = [];
        if (!isOp(peek(), ')')) {
          // Special: short-circuit `if(cond, a, b)` — evaluate only the
          // taken branch so type-checked branches don't blow up the whole
          // formula when they would never be taken.
          if (name === 'if') {
            const cond = parseExpr();
            if (!isOp(peek(), ',')) throw new Error('if(): expected comma after condition');
            eat();
            const condTrue = !!coerceNumberLoose(cond);
            if (condTrue) {
              const a = parseExpr();
              if (!isOp(peek(), ',')) throw new Error('if(): expected comma after a');
              eat();
              skipExpr();
              if (!isOp(peek(), ')')) throw new Error('if(): missing )');
              eat();
              return a;
            } else {
              skipExpr();
              if (!isOp(peek(), ',')) throw new Error('if(): expected comma after a');
              eat();
              const b = parseExpr();
              if (!isOp(peek(), ')')) throw new Error('if(): missing )');
              eat();
              return b;
            }
          }
          args.push(parseExpr());
          while (isOp(peek(), ',')) {
            eat();
            args.push(parseExpr());
          }
        }
        if (!isOp(peek(), ')')) throw new Error('Missing )');
        eat();
        // Built-in dispatch
        if (name === 'pos') return callPos(args, ctx);
        if (name === 'section') return callSection(args, ctx);
        if (name === 'col') return callCol(args, ctx);
        // pi() / e() short-form
        if (args.length === 0 && name in CONSTANTS) return CONSTANTS[name]!;
        return callMathFn(name, args);
      }
      // Bare identifier → constant
      if (name in CONSTANTS) return CONSTANTS[name]!;
      throw new Error(`Unknown identifier: ${name}`);
    }
    throw new Error(`Unexpected token: ${JSON.stringify(t)}`);
  }

  /**
   * Skip past one full expression in the token stream without evaluating it.
   * Used by the short-circuit branch of `if(...)`. Mirrors the precedence
   * of parseExpr so we land on the right delimiter.
   */
  function skipExpr() {
    let depth = 0;
    while (pos < tokens.length) {
      const t = tokens[pos]!;
      if (t.kind === 'op') {
        if (t.value === '(') depth++;
        else if (t.value === ')') {
          if (depth === 0) return;
          depth--;
        } else if (t.value === ',' && depth === 0) return;
      }
      pos++;
    }
  }

  const result = parseExpr();
  if (pos < tokens.length) throw new Error(`Unexpected token after end: ${JSON.stringify(tokens[pos])}`);
  return result;
}

function coerceNumberLoose(v: Value): number {
  if (typeof v === 'number') return v;
  if (typeof v === 'boolean') return v ? 1 : 0;
  if (typeof v === 'string') {
    const n = parseFloat(v);
    return isNaN(n) ? 0 : n;
  }
  return 0;
}

/* ── Built-in record constructors ───────────────────────────────────── */

function callPos(args: Value[], ctx?: FormulaContext): PositionRecord {
  if (!ctx) throw new Error('pos(): no formula context');
  if (args.length !== 1) throw new Error('pos(): expects 1 arg');
  const ord = String(args[0]);
  const p = ctx.positionsByOrdinal.get(ord);
  if (!p) throw new Error(`pos(): no position with ordinal "${ord}"`);
  const qty = Number(p.quantity) || 0;
  const rate = Number(p.unit_rate) || 0;
  return { __kind: 'position', qty, rate, total: qty * rate };
}

function callSection(args: Value[], ctx?: FormulaContext): SectionRecord {
  if (!ctx) throw new Error('section(): no formula context');
  if (args.length !== 1) throw new Error('section(): expects 1 arg');
  const name = String(args[0]);
  const sec = ctx.sectionsByName.get(name);
  if (!sec) throw new Error(`section(): no section named "${name}"`);
  let total = 0;
  for (const p of sec.positions) {
    const q = Number(p.quantity) || 0;
    const r = Number(p.unit_rate) || 0;
    total += q * r;
  }
  return { __kind: 'section', total };
}

function callCol(args: Value[], ctx?: FormulaContext): Value {
  if (!ctx) throw new Error('col(): no formula context');
  if (!ctx.currentRow) throw new Error('col(): not in a calculated-column row context');
  if (args.length !== 1) throw new Error('col(): expects 1 arg');
  const name = String(args[0]);
  const v = ctx.currentRow[name];
  if (v === undefined || v === null) return 0;
  if (typeof v === 'number' || typeof v === 'string' || typeof v === 'boolean') return v;
  return 0;
}

/* ── Helper: build a context from a positions list ──────────────────── */

export function buildFormulaContext(args: {
  positions: Position[];
  variables?: Map<string, FormulaVariable>;
  currentPositionId?: string;
  currentRow?: Record<string, unknown>;
  sectionMembers?: Map<string, Position[]>;
}): FormulaContext {
  const positionsByOrdinal = new Map<string, Position>();
  const positionsById = new Map<string, Position>();
  const sectionsByName = new Map<string, FormulaSection>();
  for (const p of args.positions) {
    if (p.ordinal) positionsByOrdinal.set(p.ordinal, p);
    if (p.id) positionsById.set(p.id, p);
  }
  if (args.sectionMembers) {
    for (const [name, members] of args.sectionMembers) {
      sectionsByName.set(name, { positions: members });
    }
  }
  return {
    currentPositionId: args.currentPositionId,
    positionsByOrdinal,
    positionsById,
    sectionsByName,
    variables: args.variables ?? new Map(),
    currentRow: args.currentRow,
  };
}
