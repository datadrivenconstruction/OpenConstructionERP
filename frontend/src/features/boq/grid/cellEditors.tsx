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
 * Evaluate a simple math formula string (e.g. "2 * 3.5 * 12" => 84).
 * Only allows safe math: numbers, +, -, *, /, (, ), spaces, and decimals.
 * Uses a recursive descent parser instead of eval/new Function for CSP safety.
 */
export function evaluateFormula(input: string): number | null {
  const sanitized = input.replace(/[^0-9+\-*/().\s]/g, '');
  if (!sanitized || sanitized !== input.trim()) return null;
  try {
    const result = parseMathExpr(sanitized);
    if (typeof result === 'number' && isFinite(result) && result >= 0) {
      return Math.round(result * 100) / 100;
    }
  } catch {
    return null;
  }
  return null;
}

/* ── Recursive descent math parser (CSP-safe, no eval) ────────────── */

/** Tokenize a math expression into numbers, operators, and parens. */
function tokenize(expr: string): string[] {
  const tokens: string[] = [];
  let i = 0;
  while (i < expr.length) {
    const ch = expr[i]!;
    if (ch === ' ') { i++; continue; }
    if ('+-*/()'.includes(ch)) {
      tokens.push(ch);
      i++;
    } else if (ch >= '0' && ch <= '9' || ch === '.') {
      let num = '';
      while (i < expr.length) {
        const c = expr[i]!;
        if (!(c >= '0' && c <= '9' || c === '.')) break;
        num += c;
        i++;
      }
      tokens.push(num);
    } else {
      throw new Error('Unexpected character');
    }
  }
  return tokens;
}

/** Parse and evaluate: expr = term (('+' | '-') term)* */
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
    let left = parseFactor();
    while (pos < tokens.length && (tokens[pos] === '*' || tokens[pos] === '/')) {
      const op = tokens[pos++];
      const right = parseFactor();
      left = op === '*' ? left * right : left / right;
    }
    return left;
  }

  function parseFactor(): number {
    const tok = tokens[pos] ?? '';
    // Unary minus
    if (tok === '-') {
      pos++;
      return -parseFactor();
    }
    // Unary plus
    if (tok === '+') {
      pos++;
      return parseFactor();
    }
    // Parenthesized expression
    if (tok === '(') {
      pos++; // skip '('
      const val = parseExpr();
      if (tokens[pos] !== ')') throw new Error('Missing )');
      pos++; // skip ')'
      return val;
    }
    // Number
    const num = parseFloat(tok);
    if (isNaN(num)) throw new Error('Expected number');
    pos++;
    return num;
  }

  const result = parseExpr();
  if (pos < tokens.length) throw new Error('Unexpected token');
  return result;
}

export interface FormulaCellEditorParams extends ICellEditorParams {
  onFormulaApplied?: (positionId: string, formula: string, result: number) => void;
}

/** Check whether an input string looks like a formula (contains an operator). */
function isFormula(input: string): boolean {
  return /[+\-*/]/.test(input);
}

export const FormulaCellEditor = forwardRef(
  (props: FormulaCellEditorParams, ref) => {
    const inputRef = useRef<HTMLInputElement>(null);
    const formula = props.data?.metadata?.formula;
    const [value, setValue] = useState<string>(
      formula ? String(formula) : String(props.value ?? ''),
    );

    // Compute live preview when the input looks like a formula
    const formulaPreview = useMemo(() => {
      const trimmed = value.trim();
      if (!isFormula(trimmed)) return null;
      const result = evaluateFormula(trimmed);
      if (result === null) return null;
      return `= ${result.toFixed(2)}`;
    }, [value]);

    useEffect(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, []);

    useImperativeHandle(ref, () => ({
      getValue() {
        const trimmed = value.trim();
        if (isFormula(trimmed)) {
          const result = evaluateFormula(trimmed);
          if (result !== null) {
            props.onFormulaApplied?.(props.data?.id, trimmed, result);
            return result;
          }
        }
        return parseFloat(trimmed) || 0;
      },
      isCancelAfterEnd() {
        return false;
      },
    }));

    return (
      <div className="relative w-full h-full">
        <input
          ref={inputRef}
          className="w-full h-full bg-surface-elevated border border-oe-blue/40 rounded px-1 outline-none text-xs text-content-primary ring-2 ring-oe-blue/20 tabular-nums text-right"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Escape') {
              props.api.stopEditing(true);
            }
          }}
        />
        {formulaPreview && (
          <span className="absolute right-1 top-full mt-0.5 text-[10px] leading-tight text-content-secondary/70 tabular-nums pointer-events-none whitespace-nowrap z-10">
            {formulaPreview}
          </span>
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
