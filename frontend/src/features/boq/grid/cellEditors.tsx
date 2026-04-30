import {
  forwardRef,
  useImperativeHandle,
  useMemo,
  useRef,
  useState,
  useEffect,
  useCallback,
  useLayoutEffect,
} from 'react';
import { createPortal } from 'react-dom';
import { useTranslation } from 'react-i18next';
import type { ICellEditorParams } from 'ag-grid-community';
import { AutocompleteInput } from '../AutocompleteInput';
import type { CostAutocompleteItem } from '../api';
import { getUnitsForLocale, saveCustomUnit } from '../boqHelpers';
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

/* ── Unit Cell Editor (combobox: dropdown + free typing) ──────────────
 *
 * Replaces the strict ``agSelectCellEditor`` for the ``unit`` column.
 * The strict dropdown silently swallowed edits when the existing value
 * wasn't in its hard-coded list (every CWICR row whose unit was a
 * Cyrillic / locale-specific token like "т" / "маш.-ч" was uneditable).
 *
 * Reuses ``getUnitsForLocale()`` + ``saveCustomUnit()`` from boqHelpers
 * so the dropdown:
 *   • shows the canonical multilingual unit set + the active i18n
 *     language's locale-specific tokens (DE: Stk/Std, RU: шт/маш.-ч,
 *     ZH: 个/套, JA: 本/箇所, ...),
 *   • includes any custom unit the user has typed before (synced to
 *     ``/v1/users/me/custom-units/`` so the same list shows on every
 *     device + the same custom set is shared with the cost database,
 *     assemblies and catalog screens),
 *   • accepts free-text input so any one-off unit still commits.
 */

export const UnitCellEditor = forwardRef((props: ICellEditorParams, ref) => {
  const { i18n } = useTranslation();
  const lang = i18n.language || 'en';
  const initial = String(props.value ?? '');
  const [value, setValue] = useState<string>(initial);
  // Open by default so the dropdown is visible the moment the editor
  // mounts (matches the original ``agSelectCellEditor`` UX). The
  // dropdown lives in a portal at <body> level (see render below) so
  // AG Grid's per-cell ``overflow:hidden`` no longer clips it — the
  // earlier ``open=false`` workaround is replaced by the portal fix.
  const [open, setOpen] = useState(true);
  const [activeIdx, setActiveIdx] = useState(0);
  // Anchor rect for portal positioning. Recomputed when the dropdown
  // opens so resizing the column / scrolling doesn't leave a stale popover.
  const [anchorRect, setAnchorRect] = useState<DOMRect | null>(null);
  // ``committedRef`` short-circuits redundant stopEditing calls — when
  // pick() / Enter / Tab commits, we set this flag so the trailing
  // onBlur doesn't double-commit.
  const committedRef = useRef(false);
  // ``valueRef`` is the source of truth for AG Grid's getValue() —
  // setValue() is async, so reading from React state inside getValue()
  // (which AG Grid invokes synchronously during stopEditing) returned
  // the stale pre-commit value. The ref is mutated synchronously
  // alongside setValue, so getValue() always sees the latest pick.
  const valueRef = useRef<string>(initial);
  const inputRef = useRef<HTMLInputElement>(null);
  const listRef = useRef<HTMLUListElement>(null);

  // Locale-aware multilingual list + user's custom units. Current value
  // is appended when not already in the list so the existing token still
  // shows up.
  const allOptions = useMemo(() => {
    const list = getUnitsForLocale(lang);
    if (initial && !list.includes(initial)) return [...list, initial];
    return list;
  }, [lang, initial]);

  // Filter as the user types. Empty / unchanged value shows the FULL list
  // (the previous datalist-based implementation hid all-but-one options
  // when the existing value matched a single token — Chromium's datalist
  // filters strictly by the input's current value). Built-in tokens
  // bubble to the top; the rest preserves the locale-curated order.
  const filtered = useMemo(() => {
    const q = value.trim().toLowerCase();
    if (!q || q === initial.trim().toLowerCase()) return allOptions;
    const starts: string[] = [];
    const contains: string[] = [];
    for (const u of allOptions) {
      const lc = u.toLowerCase();
      if (lc.startsWith(q)) starts.push(u);
      else if (lc.includes(q)) contains.push(u);
    }
    return [...starts, ...contains];
  }, [value, initial, allOptions]);

  // Keep activeIdx within bounds when filter changes.
  useEffect(() => {
    if (activeIdx >= filtered.length) setActiveIdx(0);
  }, [filtered.length, activeIdx]);

  // Mirror React state into the ref so getValue() (which AG Grid invokes
  // synchronously) always reads the current value, not a stale closure.
  useEffect(() => {
    valueRef.current = value;
  }, [value]);

  useImperativeHandle(ref, () => ({
    getValue() {
      return (valueRef.current ?? '').trim();
    },
    isCancelAfterEnd() {
      return false;
    },
  }));

  useEffect(() => {
    // Defer focus by one tick so AG Grid finishes attaching the editor
    // to the DOM before we steal focus into the input. Calling focus
    // synchronously inside useEffect on mount caused intermittent
    // races on AG Grid 32 where the cell hadn't received focus yet.
    const t = setTimeout(() => {
      inputRef.current?.focus();
      inputRef.current?.select();
    }, 0);
    return () => clearTimeout(t);
  }, []);

  const commit = useCallback((finalValue?: string) => {
    if (committedRef.current) return;
    committedRef.current = true;
    const v = (finalValue ?? value).trim();
    valueRef.current = v;          // sync the ref BEFORE stopEditing
    if (v) saveCustomUnit(v);
    setValue(v);
    setTimeout(() => {
      try { props.api.stopEditing(false); } catch { /* editor already gone */ }
    }, 0);
  }, [value, props.api]);

  const pick = useCallback((u: string) => {
    if (committedRef.current) return;
    committedRef.current = true;
    valueRef.current = u;          // sync the ref BEFORE stopEditing
    setValue(u);
    setOpen(false);
    if (u.trim()) saveCustomUnit(u);
    setTimeout(() => {
      try { props.api.stopEditing(false); } catch { /* editor already gone */ }
    }, 0);
  }, [props.api]);

  // Scroll the active option into view as the user navigates.
  useEffect(() => {
    if (!open || !listRef.current) return;
    const el = listRef.current.querySelector<HTMLLIElement>(`[data-idx="${activeIdx}"]`);
    el?.scrollIntoView({ block: 'nearest' });
  }, [activeIdx, open]);

  // Recompute the anchor rect every time the dropdown opens (or the
  // window scrolls / resizes) so the portal stays glued to the input.
  useLayoutEffect(() => {
    if (!open) return;
    const updateAnchor = () => {
      if (inputRef.current) setAnchorRect(inputRef.current.getBoundingClientRect());
    };
    updateAnchor();
    window.addEventListener('scroll', updateAnchor, true);
    window.addEventListener('resize', updateAnchor);
    return () => {
      window.removeEventListener('scroll', updateAnchor, true);
      window.removeEventListener('resize', updateAnchor);
    };
  }, [open]);

  return (
    <div className="relative w-full h-full">
      <input
        ref={inputRef}
        type="text"
        value={value}
        maxLength={20}
        onChange={(e) => {
          setValue(e.target.value);
          setOpen(true);
          setActiveIdx(0);
        }}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') {
            e.preventDefault();
            const sel = filtered[activeIdx];
            if (open && sel != null) pick(sel);
            else commit();
          } else if (e.key === 'Escape') {
            e.preventDefault();
            if (open) setOpen(false);
            else props.api.stopEditing(true);
          } else if (e.key === 'ArrowDown') {
            e.preventDefault();
            setOpen(true);
            setActiveIdx((i) => Math.min(filtered.length - 1, i + 1));
          } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            setActiveIdx((i) => Math.max(0, i - 1));
          } else if (e.key === 'Tab') {
            // Plain Tab commits the current text — same behaviour as Enter on
            // a free-typed value, lets the user blow past the dropdown.
            commit();
          }
        }}
        onBlur={(e) => {
          // Defer so a click on a list item commits the picked value first.
          const next = e.relatedTarget as HTMLElement | null;
          if (next && listRef.current?.contains(next)) return;
          setTimeout(() => {
            setOpen(false);
            commit();
          }, 100);
        }}
        className="w-full h-full text-center text-xs font-mono bg-white dark:bg-surface-primary border border-oe-blue rounded px-1 py-0 outline-none"
        aria-label="Edit unit"
        autoComplete="off"
        role="combobox"
        aria-expanded={open}
        aria-autocomplete="list"
      />
      {open && filtered.length > 0 && anchorRect && createPortal(
        (() => {
          // Position dropdown directly below the input, anchored at the
          // input's left edge. Auto-flips above when there's no room
          // below (within 8 px of the viewport bottom). Min-width keeps
          // it readable even when the unit column is narrow (~80 px).
          const MAX_HEIGHT = 256;            // matches max-h-64
          const GUTTER = 4;
          const spaceBelow = window.innerHeight - anchorRect.bottom;
          const flipAbove = spaceBelow < 160 && anchorRect.top > spaceBelow;
          const top = flipAbove
            ? Math.max(8, anchorRect.top - GUTTER - MAX_HEIGHT)
            : anchorRect.bottom + GUTTER;
          const left = Math.min(
            anchorRect.left,
            window.innerWidth - 200, // keep within viewport (200 = min-width + slack)
          );
          return (
            <ul
              ref={listRef}
              role="listbox"
              tabIndex={-1}
              className="fixed z-[10001] max-h-64
                         overflow-y-auto rounded border border-border-light bg-surface-elevated
                         shadow-xl text-xs"
              style={{
                top: `${top}px`,
                left: `${Math.max(0, left)}px`,
                minWidth: `${Math.max(160, anchorRect.width)}px`,
              }}
              onMouseDown={(e) => {
                // Prevent blur on the input AND stop AG Grid's outside-click
                // detector from cancelling the edit before pick() runs. The
                // dropdown is portaled to <body> so AG Grid sees it as
                // outside the editor cell. AG Grid 32's outside-click
                // detector listens at the *native* document level, so
                // React's synthetic ``stopPropagation()`` is not enough —
                // we need ``nativeEvent.stopImmediatePropagation()`` to
                // prevent ``stopEditing(true)`` (cancel=true), which would
                // silently drop the pick before getValue() runs.
                e.preventDefault();
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
              onClick={(e) => {
                e.stopPropagation();
                e.nativeEvent.stopImmediatePropagation();
              }}
            >
              {filtered.map((u, idx) => (
                <li
                  key={u + idx}
                  data-idx={idx}
                  role="option"
                  aria-selected={idx === activeIdx}
                  onMouseEnter={() => setActiveIdx(idx)}
                  onMouseDown={(e) => {
                    // Commit on mouseDown so AG Grid can't intercept and
                    // stop editing before our onClick handler fires.
                    // ``stopImmediatePropagation`` on the native event is
                    // required so AG Grid 32's document-level outside-
                    // click listener does not cancel the edit first.
                    e.preventDefault();
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    pick(u);
                  }}
                  onClick={(e) => {
                    e.stopPropagation();
                    e.nativeEvent.stopImmediatePropagation();
                    if (!committedRef.current) pick(u);
                  }}
                  className={`cursor-pointer px-2 py-1 font-mono whitespace-nowrap ${
                    idx === activeIdx
                      ? 'bg-oe-blue text-white'
                      : 'text-content-primary hover:bg-surface-secondary'
                  }`}
                >
                  {u}
                </li>
              ))}
            </ul>
          );
        })(),
        document.body,
      )}
    </div>
  );
});
UnitCellEditor.displayName = 'UnitCellEditor';
