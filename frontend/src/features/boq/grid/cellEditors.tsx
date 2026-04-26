import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  useEffect,
  useCallback,
} from 'react';
import type { ICellEditorParams } from 'ag-grid-community';
import { AutocompleteInput } from '../AutocompleteInput';
import type { CostAutocompleteItem } from '../api';

/* ── Formula Cell Editor ──────────────────────────────────────────── */

/**
 * Evaluate an Excel-like math formula string. Supports (Issue #90):
 *   • Optional leading `=` (Excel convention)
 *   • Operators: + - * / ^  (^ is right-associative exponentiation)
 *   • `x` / `×` as aliases for `*` (so "2 x 3" works)
 *   • `,` as decimal alias (so "2,5" parses as 2.5 in es/de locales)
 *   • Constants: PI, E
 *   • Functions: sqrt, abs, round, floor, ceil, pow, min, max, sin, cos, tan
 *   • Parentheses + nesting
 *
 * CSP-safe: hand-written recursive-descent parser, no eval / no Function().
 *
 * Examples:
 *   "=2*PI()^2*3"  → 59.22
 *   "=sqrt(144)"   → 12
 *   "12 x 4 + 8"   → 56
 *   "=2,5 * 4"     → 10  (es/de comma decimal)
 */
export function evaluateFormula(input: string): number | null {
  const trimmed = input.trim();
  if (!trimmed) return null;
  // Strip optional Excel-style leading "="
  const body = trimmed.startsWith('=') ? trimmed.slice(1) : trimmed;
  const normalised = normaliseFormula(body);
  try {
    const result = parseMathExpr(normalised);
    if (typeof result === 'number' && isFinite(result) && result >= 0) {
      // 4 decimal places — matches backend BUG-MATH01 storage precision.
      return Math.round(result * 10000) / 10000;
    }
  } catch {
    return null;
  }
  return null;
}

/**
 * Normalise human/locale variants of math syntax to canonical operators.
 *   • × → *
 *   • `x` between two operand-edges (digit/letter/paren) → *
 *   • `,` → `.` ONLY when used as a locale-decimal (no other commas + no
 *     parentheses, so it can't conflict with function-call argument
 *     separators like `min(1,2,3)`).
 *
 * Exported for test coverage.
 */
export function normaliseFormula(s: string): string {
  let out = s.replace(/×/g, '*');
  // `x`/`X` as multiplication: only when the LHS is a digit or `)`. If
  // the LHS were a letter we'd also match the `x` inside identifiers like
  // `max(`, breaking function-call parsing. The lookahead requires the
  // RHS be a digit / opening paren / identifier start so we don't eat
  // `x` from things like trailing literals.
  out = out.replace(/([0-9)])\s*[xX]\s*(?=[0-9(a-zA-Z])/g, (_m, lhs) => `${lhs}*`);
  // Locale-decimal: only safe when there are no parens (no function calls)
  // and the comma count matches a single decimal value or list of plain
  // decimals separated by spaces. To avoid stomping function-arg commas,
  // we only convert when the input has no `(`.
  if (!out.includes('(')) {
    out = out.replace(/,/g, '.');
  }
  return out;
}

/* ── Recursive descent math parser (CSP-safe, no eval) ────────────── */

const _IDENT_RE = /[a-zA-Z_]/;

/** Tokenize a math expression into numbers, operators, parens, and identifiers. */
function tokenize(expr: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i]!;
    if (ch === ' ' || ch === '\t') { i++; continue; }
    if ('+-*/^(),'.includes(ch)) {
      // Handle "**" as exponent (Python convention)
      if (ch === '*' && expr[i + 1] === '*') {
        tokens.push('^');
        i += 2;
        continue;
      }
      tokens.push(ch);
      i++;
    } else if ((ch >= '0' && ch <= '9') || ch === '.') {
      // Locale-comma decimals are handled in normaliseFormula() before
      // tokenization, so here `,` is unambiguously a function-arg separator
      // (handled below in the operator branch).
      let num = '';
      while (i < expr.length) {
        const c = expr[i]!;
        if (!((c >= '0' && c <= '9') || c === '.')) break;
        num += c;
        i++;
      }
      tokens.push(num);
    } else if (_IDENT_RE.test(ch)) {
      let ident = '';
      while (i < expr.length && (_IDENT_RE.test(expr[i]!) || (expr[i]! >= '0' && expr[i]! <= '9'))) {
        ident += expr[i]!;
        i++;
      }
      tokens.push(ident.toLowerCase());
    } else {
      throw new Error(`Unexpected character: ${ch}`);
    }
  }
  return tokens;
}

const _CONSTANTS: Record<string, number> = {
  pi: Math.PI,
  e: Math.E,
};

/** Single-arg / multi-arg math functions. Anything not listed is rejected. */
function callFunction(name: string, args: number[]): number {
  switch (name) {
    case 'sqrt': return Math.sqrt(args[0]!);
    case 'abs': return Math.abs(args[0]!);
    case 'round': return Math.round(args[0]!);
    case 'floor': return Math.floor(args[0]!);
    case 'ceil': return Math.ceil(args[0]!);
    case 'sin': return Math.sin(args[0]!);
    case 'cos': return Math.cos(args[0]!);
    case 'tan': return Math.tan(args[0]!);
    case 'log': return Math.log(args[0]!);
    case 'exp': return Math.exp(args[0]!);
    case 'pow': return Math.pow(args[0]!, args[1]!);
    case 'min': return Math.min(...args);
    case 'max': return Math.max(...args);
    default: throw new Error(`Unknown function: ${name}`);
  }
}

/**
 * Grammar (precedence low→high):
 *   expr   = term (('+' | '-') term)*
 *   term   = power (('*' | '/') power)*
 *   power  = factor ('^' power)?    -- right-associative
 *   factor = ('+' | '-') factor
 *          | '(' expr ')'
 *          | NUMBER
 *          | IDENT '(' [expr (',' expr)*] ')'   -- function call
 *          | IDENT                               -- constant (PI, E)
 */
function parseMathExpr(input: string): number {
  const tokens = tokenize(input);
  if (tokens.length === 0) throw new Error('Empty');
  let pos = 0;

  function parseExpr(): number {
    let left = parseTerm();
    while (pos < tokens.length && (tokens[pos] === '+' || tokens[pos] === '-')) {
      const op = tokens[pos++];
      const right = parseTerm();
      left = op === '+' ? left + right : left - right;
    }
    return left;
  }

  function parseTerm(): number {
    let left = parsePower();
    while (pos < tokens.length && (tokens[pos] === '*' || tokens[pos] === '/')) {
      const op = tokens[pos++];
      const right = parsePower();
      left = op === '*' ? left * right : left / right;
    }
    return left;
  }

  function parsePower(): number {
    const base = parseFactor();
    if (pos < tokens.length && tokens[pos] === '^') {
      pos++;
      const exp = parsePower(); // right-associative recursion
      return Math.pow(base, exp);
    }
    return base;
  }

  function parseFactor(): number {
    const tok = tokens[pos] ?? '';
    if (tok === '-') { pos++; return -parseFactor(); }
    if (tok === '+') { pos++; return parseFactor(); }
    if (tok === '(') {
      pos++;
      const val = parseExpr();
      if (tokens[pos] !== ')') throw new Error('Missing )');
      pos++;
      return val;
    }
    // Identifier — either a constant (PI, E) or a function call (sqrt(…), pi(), …)
    if (_IDENT_RE.test(tok[0] ?? '')) {
      pos++;
      // Function call: IDENT '(' …args… ')'
      if (tokens[pos] === '(') {
        pos++;
        const args: number[] = [];
        if (tokens[pos] !== ')') {
          args.push(parseExpr());
          while (tokens[pos] === ',') {
            pos++;
            args.push(parseExpr());
          }
        }
        if (tokens[pos] !== ')') throw new Error('Missing )');
        pos++;
        // PI() / E() as zero-arg "functions" — also valid as bare constants
        if (args.length === 0 && tok in _CONSTANTS) return _CONSTANTS[tok]!;
        return callFunction(tok, args);
      }
      // Bare constant
      if (tok in _CONSTANTS) return _CONSTANTS[tok]!;
      throw new Error(`Unknown identifier: ${tok}`);
    }
    // Number
    const num = parseFloat(tok);
    if (isNaN(num)) throw new Error(`Expected number, got: ${tok}`);
    pos++;
    return num;
  }

  const result = parseExpr();
  if (pos < tokens.length) throw new Error(`Unexpected token: ${tokens[pos]}`);
  return result;
}

export interface FormulaCellEditorParams extends ICellEditorParams {
  onFormulaApplied?: (positionId: string, formula: string, result: number) => void;
}

/** Check whether an input string looks like a formula (Excel-style `=` prefix,
 * any math operator, named constant, or function call). Pure numbers like
 * "12.5" are NOT formulas — they go through the normal numeric path. */
function isFormula(input: string): boolean {
  const t = input.trim();
  if (!t) return false;
  if (t.startsWith('=')) return true;
  if (/[+\-*/^×()]/.test(t)) return true;
  if (/\b(pi|e|sqrt|abs|round|floor|ceil|pow|min|max|sin|cos|tan|log|exp)\b/i.test(t)) return true;
  return false;
}

/**
 * Compute a live preview state for the formula editor. Returns one of:
 *   { kind: 'idle' }     — empty input, nothing to show
 *   { kind: 'number' }   — a plain numeric input (not a formula)
 *   { kind: 'ok',  v }   — a valid formula evaluated to v
 *   { kind: 'err', m }   — looks like a formula but failed to parse
 */
type FormulaPreview =
  | { kind: 'idle' }
  | { kind: 'number'; v: number }
  | { kind: 'ok'; v: number }
  | { kind: 'err'; m: string };

function previewFor(input: string): FormulaPreview {
  const t = input.trim();
  if (!t) return { kind: 'idle' };
  if (!isFormula(t)) {
    const n = parseFloat(t.replace(',', '.'));
    return isFinite(n) ? { kind: 'number', v: n } : { kind: 'err', m: 'Not a number' };
  }
  // Body for error reporting: try to surface the parser's exception detail
  const body = t.startsWith('=') ? t.slice(1) : t;
  const normalised = body.replace(/×/g, '*').replace(/\bx\b/gi, '*');
  try {
    const r = parseMathExpr(normalised);
    if (!isFinite(r)) return { kind: 'err', m: 'Result is not finite' };
    if (r < 0) return { kind: 'err', m: 'Result is negative' };
    return { kind: 'ok', v: Math.round(r * 10000) / 10000 };
  } catch (e) {
    return { kind: 'err', m: e instanceof Error ? e.message : 'Syntax error' };
  }
}

export const FormulaCellEditor = forwardRef(
  (props: FormulaCellEditorParams, ref) => {
    const inputRef = useRef<HTMLInputElement>(null);
    const formula = props.data?.metadata?.formula;
    // Pre-fill with the previously-saved formula if there is one — this
    // means re-editing a "formula" cell takes the user back to the source
    // expression, not just the resolved number (Issue #90 round-trip UX).
    const [value, setValue] = useState<string>(
      formula ? String(formula) : String(props.value ?? ''),
    );
    const [showHelp, setShowHelp] = useState(false);
    // Single source of truth — what numeric value we will hand back to AG
    // Grid. Updated only by commitFromInput / getValue so the formula
    // metadata write and the quantity write stay consistent (no race that
    // PATCHes the original value back over the formula result).
    const lastParsedRef = useRef<number | null>(null);
    const lastFormulaRef = useRef<string>('');

    const preview = useMemo(() => previewFor(value), [value]);

    useEffect(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, []);

    // Resolve onFormulaApplied: prefer the editor-param prop, fall back to
    // the grid context. AG Grid's column-defs don't pass cellEditorParams
    // for the Quantity column, so the actual delivery channel is
    // ``context.onFormulaApplied`` set in BOQGrid's gridContext.
    const fireFormulaApplied = (
      positionId: string | undefined,
      f: string,
      r: number,
    ) => {
      if (!positionId) return;
      const ctxFn = (props.context as { onFormulaApplied?: (id: string, f: string, r: number) => void } | undefined)
        ?.onFormulaApplied;
      if (props.onFormulaApplied) {
        props.onFormulaApplied(positionId, f, r);
      } else if (ctxFn) {
        ctxFn(positionId, f, r);
      }
    };

    // Issue #90 follow-up (v2.5.6 hotfix): React 18 + ag-grid-react v32
    // popup editors render in a DOM root that doesn't share the synthetic
    // event delegation root, so JSX ``onKeyDown`` / ``onChange`` never
    // fire. We attach NATIVE listeners through the ref. The flow is:
    //
    //   keydown(Enter) → parse → fire onFormulaApplied (metadata) →
    //   stopEditing(false) → AG Grid calls getValue() → returns parsed →
    //   AG Grid writes quantity → fires cellValueChanged → PATCH.
    //
    // We DO NOT call ``node.setDataValue`` here: doing so plus AG Grid's
    // own getValue path resulted in two PATCHes (one with the parsed
    // result, one with the editor's raw text after the parser fell back
    // to oldValue). Single source of truth via ``lastParsedRef`` keeps it
    // to one PATCH per commit.
    const parseInput = (live: string): { parsed: number; formulaSrc: string } => {
      const trimmed = live.trim();
      let parsed: number;
      let formulaSrc = '';
      if (isFormula(trimmed)) {
        const result = evaluateFormula(trimmed);
        if (result !== null) {
          parsed = result;
          formulaSrc = trimmed;
        } else {
          parsed = parseFloat(trimmed.replace(',', '.')) || 0;
        }
      } else {
        parsed = parseFloat(trimmed.replace(',', '.')) || 0;
      }
      return { parsed, formulaSrc };
    };

    // Idempotency guard: Enter→commitFromInput→stopEditing destroys the
    // input, which fires a tail blur event that would otherwise re-enter
    // commitFromInput and double-PATCH the formula. Track whether we've
    // already committed and short-circuit subsequent calls.
    const committedRef = useRef(false);

    const commitFromInput = (cancelNavigation: boolean) => {
      if (committedRef.current) return;
      committedRef.current = true;

      const live = inputRef.current?.value ?? value;
      const { parsed, formulaSrc } = parseInput(live);
      const hadStoredFormula = !!formula;
      lastParsedRef.current = parsed;
      lastFormulaRef.current = formulaSrc;

      if (formulaSrc) {
        fireFormulaApplied(props.data?.id, formulaSrc, parsed);
      } else if (hadStoredFormula) {
        // User replaced a stored formula with a plain number — clear it.
        fireFormulaApplied(props.data?.id, '', parsed);
      }

      // ag-grid-react v32 + React 18 sometimes skips ``getValue()`` after
      // ``stopEditing(false)`` on functional editors, so write the value
      // directly *and* implement getValue. The check ``parsed !== old``
      // ensures we don't fire a no-op cellValueChanged.
      const colId = props.column?.getColId?.() ?? 'quantity';
      const oldValue = props.node?.data?.[colId];
      if (parsed !== oldValue) {
        props.node?.setDataValue(colId, parsed);
      }

      props.api.stopEditing(cancelNavigation);
    };

    useEffect(() => {
      const el = inputRef.current;
      if (!el) return;

      const handleInput = (ev: Event) => {
        setValue((ev.target as HTMLInputElement).value);
      };
      const handleKeyDown = (ev: KeyboardEvent) => {
        if (ev.key === 'Escape') {
          if (showHelp) {
            setShowHelp(false);
            ev.stopPropagation();
            return;
          }
          props.api.stopEditing(true);
          return;
        }
        if (ev.key === 'Enter') {
          ev.preventDefault();
          ev.stopPropagation();
          commitFromInput(false);
          return;
        }
        if (ev.key === 'Tab') {
          ev.preventDefault();
          ev.stopPropagation();
          commitFromInput(false);
          props.api.tabToNextCell();
        }
      };
      const handleBlur = () => {
        // Blur (clicking outside the popup) should also commit, matching
        // how AG Grid's native editors behave.
        commitFromInput(false);
      };

      el.addEventListener('input', handleInput);
      el.addEventListener('keydown', handleKeyDown);
      el.addEventListener('blur', handleBlur);
      return () => {
        el.removeEventListener('input', handleInput);
        el.removeEventListener('keydown', handleKeyDown);
        el.removeEventListener('blur', handleBlur);
      };
      // commitFromInput closes over the latest props/value via the ref
      // read inside it, so it doesn't need to be in the dep list.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [showHelp]);

    useImperativeHandle(ref, () => ({
      getValue() {
        // If the user already pressed Enter / blurred / Tab, commitFromInput
        // already parsed and stored the canonical numeric value — return
        // that so AG Grid's cellValueChanged fires with the SAME number we
        // wrote via setDataValue (no double PATCH, no rollback to the
        // pre-edit value).
        if (lastParsedRef.current !== null) {
          return lastParsedRef.current;
        }
        // Cold path: AG Grid called getValue without any prior commit
        // (programmatic stopEditing, focus loss not via blur listener).
        // Parse and return — but DO NOT fire onFormulaApplied here, since
        // we can't tell if this is a real commit or a cancel-by-API call.
        // commitFromInput is the only path that persists the formula.
        const live = inputRef.current?.value ?? value;
        return parseInput(live).parsed;
      },
      isCancelAfterEnd() {
        return false;
      },
    }));

    const isFormulaMode = isFormula(value);
    const borderClass = preview.kind === 'err'
      ? 'border-rose-400/70 ring-rose-400/20'
      : isFormulaMode
        ? 'border-violet-500/70 ring-violet-500/25'
        : 'border-oe-blue/40 ring-oe-blue/20';

    return (
      <div className="relative w-full h-full">
        <div className={`flex items-center w-full h-full bg-surface-elevated border rounded ring-2 ${borderClass}`}>
          {/* fx badge — purple when in formula mode, faint otherwise */}
          <span
            aria-hidden="true"
            className={`shrink-0 pl-1.5 pr-1 text-[10px] font-bold tracking-wide ${
              isFormulaMode ? 'text-violet-600 dark:text-violet-300' : 'text-content-quaternary'
            }`}
            title="Type = to enter a formula. Click ? for help."
          >
            ƒx
          </span>
          <input
            ref={inputRef}
            className="flex-1 min-w-0 h-full bg-transparent outline-none text-xs text-content-primary tabular-nums text-right pr-1"
            // ``defaultValue`` (NOT ``value``) — the input is driven by the
            // native ``input`` listener attached in useEffect above. React
            // synthetic ``onChange`` doesn't fire inside AG Grid's popup
            // editor, so the controlled-input pattern would deadlock.
            defaultValue={value}
            placeholder="123  or  =2*PI()^2*3"
          />
          {/* Help toggle — opens the cheat-sheet popover */}
          <button
            type="button"
            tabIndex={-1}
            onMouseDown={(e) => { e.preventDefault(); setShowHelp((v) => !v); }}
            className="shrink-0 px-1.5 h-full text-[10px] font-bold text-content-quaternary hover:text-violet-600 transition-colors"
            aria-label="Formula help"
            title="Formula help"
          >
            ?
          </button>
        </div>

        {/* Live preview row — anchors below the cell, doesn't shift layout */}
        {preview.kind !== 'idle' && (
          <div className="absolute right-0 top-full mt-0.5 text-[10px] leading-tight tabular-nums pointer-events-none whitespace-nowrap z-10 px-1.5 py-0.5 rounded shadow-sm bg-surface-elevated border border-border-light">
            {preview.kind === 'ok' && (
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                = {preview.v.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
              </span>
            )}
            {preview.kind === 'number' && isFormulaMode === false && value.trim() !== '' && (
              <span className="text-content-tertiary">numeric input</span>
            )}
            {preview.kind === 'err' && (
              <span className="text-rose-600 dark:text-rose-400">⚠ {preview.m}</span>
            )}
          </div>
        )}

        {/* Help popover — Excel-style cheat sheet */}
        {showHelp && (
          <div
            className="absolute right-0 top-full mt-7 z-20 w-[320px] rounded-lg border border-border-light bg-surface-elevated shadow-lg p-3 text-[11px] text-content-secondary pointer-events-auto"
            onMouseDown={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-2">
              <span className="font-semibold text-content-primary">Formula syntax</span>
              <button
                type="button"
                onClick={() => setShowHelp(false)}
                className="text-content-quaternary hover:text-content-primary"
                aria-label="Close help"
              >
                ✕
              </button>
            </div>
            <div className="grid grid-cols-2 gap-x-3 gap-y-1 font-mono text-[10px]">
              <span className="text-violet-600 dark:text-violet-300">+ − * /</span><span>basic math</span>
              <span className="text-violet-600 dark:text-violet-300">^ or **</span><span>exponent</span>
              <span className="text-violet-600 dark:text-violet-300">( )</span><span>grouping</span>
              <span className="text-violet-600 dark:text-violet-300">PI, E</span><span>constants</span>
              <span className="text-violet-600 dark:text-violet-300">sqrt(x)</span><span>square root</span>
              <span className="text-violet-600 dark:text-violet-300">pow(x,y)</span><span>x to the y</span>
              <span className="text-violet-600 dark:text-violet-300">abs round</span><span>abs / round</span>
              <span className="text-violet-600 dark:text-violet-300">floor ceil</span><span>floor / ceil</span>
              <span className="text-violet-600 dark:text-violet-300">min max</span><span>multi-arg</span>
              <span className="text-violet-600 dark:text-violet-300">sin cos tan</span><span>trig (radians)</span>
            </div>
            <div className="mt-2.5 pt-2 border-t border-border-light/70">
              <div className="font-semibold text-content-primary mb-1">Examples</div>
              <ul className="font-mono text-[10px] space-y-0.5">
                <li><span className="text-violet-600 dark:text-violet-300">=2*PI()^2*3</span><span className="text-content-tertiary"> → 59.22</span></li>
                <li><span className="text-violet-600 dark:text-violet-300">=sqrt(144) + 5</span><span className="text-content-tertiary"> → 17</span></li>
                <li><span className="text-violet-600 dark:text-violet-300">12.5 x 4</span><span className="text-content-tertiary"> → 50</span></li>
              </ul>
            </div>
            <div className="mt-2 text-[10px] text-content-tertiary">
              Prefix with <kbd className="px-1 rounded bg-surface-secondary">=</kbd> or just type the expression. Press <kbd className="px-1 rounded bg-surface-secondary">Esc</kbd> to close.
            </div>
          </div>
        )}
      </div>
    );
  },
);
FormulaCellEditor.displayName = 'FormulaCellEditor';

/* ── Autocomplete Cell Editor ─────────────────────────────────────── */

export interface AutocompleteCellEditorParams extends ICellEditorParams {
  onSelectSuggestion?: (positionId: string, item: CostAutocompleteItem) => void;
}

export const AutocompleteCellEditor = forwardRef(
  (props: AutocompleteCellEditorParams, ref) => {
    const [value, setValue] = useState<string>(String(props.value ?? ''));
    const committedRef = useRef(false);

    useImperativeHandle(ref, () => ({
      getValue() {
        return value;
      },
      isCancelAfterEnd() {
        return false;
      },
    }));

    const handleCommit = useCallback(
      (val: string) => {
        setValue(val);
        committedRef.current = true;
        props.api.stopEditing(false);
      },
      [props.api],
    );

    const handleCancel = useCallback(() => {
      props.api.stopEditing(true);
    }, [props.api]);

    const handleSelectSuggestion = useCallback(
      (item: CostAutocompleteItem) => {
        props.onSelectSuggestion?.(props.data?.id, item);
        committedRef.current = true;
        props.api.stopEditing(true);
      },
      [props.api, props.onSelectSuggestion, props.data?.id],
    );

    return (
      <div className="w-full h-full">
        <AutocompleteInput
          value={props.value ?? ''}
          onCommit={handleCommit}
          onSelectSuggestion={handleSelectSuggestion}
          onCancel={handleCancel}
          placeholder="Enter description..."
        />
      </div>
    );
  },
);
AutocompleteCellEditor.displayName = 'AutocompleteCellEditor';
