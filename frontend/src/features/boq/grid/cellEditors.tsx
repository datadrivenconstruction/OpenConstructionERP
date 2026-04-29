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
import {
  evaluateFormula as evalFormulaImpl,
  isFormula as isFormulaImpl,
  normaliseFormula as normaliseFormulaImpl,
  type FormulaContext,
} from './formula';

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
 * Phase C extension (v2.7.0/C): when a `FormulaContext` is supplied the
 * evaluator additionally accepts cross-position references (`pos("X")`),
 * BOQ-scoped variables (`$GFA`), section aggregates, calculated-column
 * row lookups, comparisons, `if(cond, a, b)`, unit conversions, and
 * `round_up`/`round_down`. The single-arg signature is preserved
 * verbatim — every existing callsite stays green.
 *
 * CSP-safe: hand-written recursive-descent parser, no eval / no Function().
 *
 * Examples:
 *   "=2*PI()^2*3"           → 59.22
 *   "=sqrt(144)"            → 12
 *   "12 x 4 + 8"            → 56
 *   "=2,5 * 4"              → 10  (es/de comma decimal)
 *   "=pos(\"1.1\").qty * 2" → ctx-dependent
 *   "=$GFA * 0.15"          → ctx-dependent
 */
export function evaluateFormula(input: string, ctx?: FormulaContext): number | null {
  return evalFormulaImpl(input, ctx);
}

/**
 * Normalise human/locale variants of math syntax to canonical operators.
 * See `./formula/engine.ts` for the canonical implementation; this
 * thin wrapper preserves the legacy export name + signature.
 *
 * Exported for test coverage.
 */
export function normaliseFormula(s: string): string {
  return normaliseFormulaImpl(s);
}

/* ── Recursive descent math parser ──────────────────────────────────
 *
 * The actual parser lives in `./formula/engine.ts` (Phase C v2.7.0/C).
 * The `evaluateFormula` and `normaliseFormula` exports above delegate
 * to that module so legacy callsites (tests, BOQGrid, etc.) keep
 * working unchanged.
 */

export interface FormulaCellEditorParams extends ICellEditorParams {
  onFormulaApplied?: (positionId: string, formula: string, result: number) => void;
}

/** Check whether an input string looks like a formula (Excel-style `=` prefix,
 * any math operator, named constant, or function call). Pure numbers like
 * "12.5" are NOT formulas — they go through the normal numeric path. */
export function isFormula(input: string): boolean {
  return isFormulaImpl(input);
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
  // The grid editor preview operates without a FormulaContext (the
  // editor is mounted inside a single cell and doesn't have access to
  // the full positions list), so $VAR / pos(...) preview as a parser
  // error here. Live evaluation with a context happens elsewhere.
  const r = evalFormulaImpl(t);
  if (r === null) return { kind: 'err', m: 'Syntax error or unresolved reference' };
  return { kind: 'ok', v: r };
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
      // Fixed editor dimensions: 180px wide × 32px tall. The Quantity column
      // is 110px so a 180px popup spills ~70px to the right — but earlier
      // sizing let the inner content grow to ~280px+ once a formula was
      // typed, which pushed deep into the Unit Rate column. Capping the
      // outer width here keeps the popup contained while still being wide
      // enough for a typical "=2*PI()^2*3" expression. Taller height makes
      // the live preview underneath legible without overlapping the row.
      <div className="relative" style={{ width: '180px', height: '32px' }}>
        <div className={`flex items-center w-full h-full bg-surface-elevated border rounded ring-2 ${borderClass}`}>
          {/* fx badge — purple when in formula mode, faint otherwise */}
          <span
            aria-hidden="true"
            className={`shrink-0 pl-1.5 pr-1 text-[11px] font-bold tracking-wide ${
              isFormulaMode ? 'text-violet-600 dark:text-violet-300' : 'text-content-quaternary'
            }`}
            title="Type = to enter a formula. Click ? for help."
          >
            ƒx
          </span>
          <input
            ref={inputRef}
            className="flex-1 min-w-0 h-full bg-transparent outline-none text-sm text-content-primary tabular-nums text-right pr-1"
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
