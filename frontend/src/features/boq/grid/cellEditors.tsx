// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
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
import { AlertTriangle, X as XIcon } from 'lucide-react';
import type { ICellEditorParams } from 'ag-grid-community';
import { AutocompleteInput } from '../AutocompleteInput';
import type { CostAutocompleteItem, Position } from '../api';
import { getUnitsForLocale, saveCustomUnit } from '../boqHelpers';
import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import { useToastStore } from '@/stores/useToastStore';
import type { DisplayQuantityApi } from '@/shared/hooks/useDisplayQuantity';
import {
  evaluateFormula as evalFormulaImpl,
  isFormula as isFormulaImpl,
  normaliseFormula as normaliseFormulaImpl,
  buildFormulaContext,
  extractReferences,
  type FormulaContext,
  type FormulaVariable,
} from './formula';
import { getNumberLocale } from '@/stores/usePreferencesStore';

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

/**
 * Issue #285: convert a Qty value the user typed / a formula resolved in the
 * DISPLAYED measurement system back to metric-canonical storage. The display
 * API is threaded onto AG Grid's ``context`` (the same ``gridContext`` BOQGrid
 * builds, see ``BOQColumnContext.displayQuantity``); the row's metric unit is
 * read from ``params.data.unit``. Returns the value unchanged when no display
 * API is present, or for metric / unmapped units (``toMetric`` is identity
 * there). The formula editor writes via ``setDataValue`` which bypasses the
 * column ``valueParser``, so this is the editor's own conversion seam.
 */
function toMetricQty(params: ICellEditorParams, displayValue: number): number {
  const dq = (params.context as { displayQuantity?: DisplayQuantityApi } | undefined)?.displayQuantity;
  if (!dq) return displayValue;
  const unit = (params.data?.unit as string | undefined) ?? '';
  return dq.toMetric(displayValue, unit);
}

/**
 * Issue #287: the reverse of ``toMetricQty``, converting a metric-canonical Qty
 * into the DISPLAYED measurement system so the editor opens on the value the
 * user actually sees. Without it the editor seeds from the raw metric value
 * while the commit path (``toMetricQty``) converts display→metric, so opening
 * and committing a cell unchanged double-converts and silently corrupts
 * storage. Identity for the metric system and for units with no imperial
 * mapping, so this never changes what a metric user sees.
 */
function toDisplayQty(params: ICellEditorParams, metricValue: number): number {
  const dq = (params.context as { displayQuantity?: DisplayQuantityApi } | undefined)?.displayQuantity;
  if (!dq) return metricValue;
  const unit = (params.data?.unit as string | undefined) ?? '';
  return dq.convert(metricValue, unit).value;
}

/** Check whether an input string looks like a formula (Excel-style `=` prefix,
 * any math operator, named constant, or function call). Pure numbers like
 * "12.5" are NOT formulas — they go through the normal numeric path. */
export function isFormula(input: string): boolean {
  return isFormulaImpl(input);
}

/* ── Feet-and-inches input (Issue #290) ─────────────────────────────── */

/**
 * Vulgar-fraction glyphs mapped to a plain "numerator/denominator" string.
 * US estimators paste dimensions using these single-character fractions
 * (e.g. `3/4"` written as `¾"`); expanding them to `3/4` lets the same
 * inch parser handle both notations.
 */
const VULGAR_FRACTIONS: Record<string, string> = {
  '¼': '1/4', // vulgar one quarter
  '½': '1/2', // vulgar one half
  '¾': '3/4', // vulgar three quarters
  '⅓': '1/3', // vulgar one third
  '⅔': '2/3', // vulgar two thirds
  '⅕': '1/5', // vulgar one fifth
  '⅖': '2/5', // vulgar two fifths
  '⅗': '3/5', // vulgar three fifths
  '⅘': '4/5', // vulgar four fifths
  '⅙': '1/6', // vulgar one sixth
  '⅚': '5/6', // vulgar five sixths
  '⅛': '1/8', // vulgar one eighth
  '⅜': '3/8', // vulgar three eighths
  '⅝': '5/8', // vulgar five eighths
  '⅞': '7/8', // vulgar seven eighths
};

/**
 * Parse the inches portion of a feet-and-inches string into a number of
 * inches. Accepts a whole number (`6`), a decimal (`6.5`), a fraction
 * (`3/4`, `11/16`) or a whole-plus-fraction (`6 3/4`). Returns `null` when a
 * token is not a non-negative number / fraction, or a denominator is 0.
 */
function parseInchValue(str: string): number | null {
  const s = str.trim();
  if (s === '') return null;
  let total = 0;
  for (const part of s.split(/\s+/)) {
    const frac = /^(\d+)\/(\d+)$/.exec(part);
    if (frac) {
      const den = Number(frac[2]);
      if (den === 0) return null;
      total += Number(frac[1]) / den;
      continue;
    }
    if (/^\d+(?:\.\d+)?$/.test(part)) {
      total += Number(part);
      continue;
    }
    return null;
  }
  return total;
}

/**
 * Parse a feet-and-inches string into DECIMAL FEET, or `null` when the input
 * is not feet-and-inches notation (Issue #290).
 *
 * An explicit foot (`'`) or inch (`"`) mark is required - smart quotes and
 * primes are accepted too - so a bare number or a real formula is never
 * misread as ft-in. Accepts: `10'6"`, `10' 6"`, `10'-6"`, `10'`, `6"`,
 * `10' 3/4"`, `11/16"` and vulgar-fraction glyphs (`¾"`). Feet contribute
 * directly, inches divide by 12, a bare fraction is inches. Negatives and
 * zero denominators are rejected.
 */
export function parseFeetInches(raw: string): number | null {
  if (!raw) return null;
  let s = raw.trim();
  if (s === '') return null;
  // Normalise smart single/double quotes and primes to ASCII ' and ".
  s = s.replace(/[‘’′]/g, "'").replace(/[“”″]/g, '"');
  // Expand vulgar-fraction glyphs to " 3/4" (leading space detaches them
  // from any preceding whole number or foot mark).
  s = s.replace(/[¼-¾⅓-⅞]/g, (m) =>
    m in VULGAR_FRACTIONS ? ` ${VULGAR_FRACTIONS[m]}` : m,
  );
  // Require an explicit foot or inch mark.
  if (!s.includes("'") && !s.includes('"')) return null;

  let feet = 0;
  let inchPart: string;
  const footIdx = s.indexOf("'");
  if (footIdx >= 0) {
    const feetStr = s.slice(0, footIdx).trim();
    if (feetStr === '' || !/^\d+(?:\.\d+)?$/.test(feetStr)) return null;
    feet = Number(feetStr);
    // The remainder holds the inches; drop a single "-" separator (10'-6").
    inchPart = s.slice(footIdx + 1).trim().replace(/^-\s*/, '').trim();
  } else {
    inchPart = s.trim();
  }

  let inches = 0;
  if (inchPart !== '') {
    // When inches are present they must be closed by an inch mark.
    if (!inchPart.endsWith('"')) return null;
    const parsed = parseInchValue(inchPart.slice(0, -1).trim());
    if (parsed === null) return null;
    inches = parsed;
  }

  const totalFeet = feet + inches / 12;
  if (!Number.isFinite(totalFeet) || totalFeet < 0) return null;
  return totalFeet;
}

/**
 * Strict plain-number parse: the ENTIRE trimmed string must be a finite
 * number (comma accepted as a decimal point for es/de locales). Unlike
 * `parseFloat` this returns `null` - not a truncated value - for `"abc"` /
 * `"10.5x"` / a malformed ft-in string, so those never commit silently as
 * garbage (Issue #290).
 */
function parsePlainNumber(raw: string): number | null {
  // Locale-aware and strict: `48,60` -> 48.6, `1.234,56` -> 1234.56,
  // `48.60` stays 48.6; anything not wholly a number is null (never a
  // truncated parseFloat prefix). See parseDecimal.ts for the rules.
  return parseDecimalInput(raw);
}

type TranslateFn = (key: string, opts?: Record<string, unknown>) => string;

/**
 * Invalid-number revert toast - the numeric editors' sibling of the
 * Ordnungszahl guard's toast in BOQGrid.onCellValueChanged. Fired when a
 * commit path refuses unparseable input and keeps the stored value.
 */
function toastInvalidNumber(t: TranslateFn): void {
  useToastStore.getState().addToast({
    type: 'warning',
    title: t('boq.number_invalid_title', { defaultValue: 'Value not changed' }),
    message: t('boq.number_invalid', {
      defaultValue:
        'This is not a number the field can read - use formats like 48,60 or 48.60 or 1.234,56. The previous value was kept.',
    }),
  });
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

/**
 * Discriminated result of parsing the editor's raw text (Issue #290).
 * `ok:false` means the input is neither a plain finite number, nor a valid
 * feet-and-inches value (in imperial foot cells), nor a formula that
 * evaluates - so the commit path must refuse to write instead of coercing to
 * `parseFloat || 0` and silently storing garbage.
 *
 * `canonical` (H2 fix) marks whether `parsed` is already a metric-canonical
 * value: true for a formula that referenced a canonical symbol ($VAR / pos() /
 * section(), whose stored values are all metric), false for a displayed value
 * (a plain number, a feet-and-inches entry, or a pure-literal formula) that the
 * commit path still converts display->metric exactly once.
 */
type ParseResult =
  | { ok: true; parsed: number; formulaSrc: string; canonical: boolean }
  | { ok: false };

function previewFor(input: string, ctx?: FormulaContext, ftInActive = false): FormulaPreview {
  const t = input.trim();
  if (!t) return { kind: 'idle' };
  // Issue #290: in imperial foot cells a feet-and-inches entry (10'6") is a
  // valid numeric input; show it as a number, not a formula error.
  if (ftInActive) {
    const ft = parseFeetInches(t);
    if (ft !== null) return { kind: 'number', v: ft };
  }
  if (!isFormula(t)) {
    // Strict numeric check (matches parseInput) so "abc" / a malformed ft-in
    // surfaces as an error instead of a silently truncated number.
    const n = parsePlainNumber(t);
    return n !== null ? { kind: 'number', v: n } : { kind: 'err', m: 'Not a number' };
  }
  // Issue #292: evaluate with the FormulaContext threaded from the grid so
  // $VAR / pos(...) / section(...) resolve in the live preview instead of
  // always erroring for a lack of context.
  const r = evalFormulaImpl(t, ctx);
  if (r === null) return { kind: 'err', m: 'Syntax error or unresolved reference' };
  return { kind: 'ok', v: r };
}

export const FormulaCellEditor = forwardRef(
  (props: FormulaCellEditorParams, ref) => {
    const { t } = useTranslation();
    const inputRef = useRef<HTMLInputElement>(null);
    const formula = props.data?.metadata?.formula;
    // Pre-fill with the previously-saved formula if there is one — this
    // means re-editing a "formula" cell takes the user back to the source
    // expression, not just the resolved number (Issue #90 round-trip UX).
    const [value, setValue] = useState<string>(() => {
      if (formula) return String(formula);
      // Issue #287: seed the numeric branch with the value in the DISPLAYED
      // measurement system. The commit path (toMetricQty) converts
      // display→metric, so without this an open+commit with no change would
      // double-convert and corrupt the stored quantity. Identity for metric /
      // unmapped units, so metric users see exactly the value as before.
      const raw = props.value;
      return typeof raw === 'number' && isFinite(raw)
        ? String(toDisplayQty(props, raw))
        : String(raw ?? '');
    });
    const [showHelp, setShowHelp] = useState(false);
    // Single source of truth — what numeric value we will hand back to AG
    // Grid. Updated only by commitFromInput / getValue so the formula
    // metadata write and the quantity write stay consistent (no race that
    // PATCHes the original value back over the formula result).
    const lastParsedRef = useRef<number | null>(null);
    const lastFormulaRef = useRef<string>('');

    // Issue #292: build a FormulaContext from the grid context so $VAR /
    // pos(...) / section(...) resolve in this cell's parse + live preview.
    // props.context is BOQGrid's gridContext; every field is optional so plain
    // numeric editing still works when the grid doesn't supply them (e.g. an
    // isolated unit test that only passes displayQuantity).
    const gridCtx = props.context as
      | {
          positions?: Position[];
          boqVariablesMap?: Map<string, FormulaVariable>;
          displayQuantity?: DisplayQuantityApi;
        }
      | undefined;
    const ctxPositions = gridCtx?.positions;
    const ctxVariables = gridCtx?.boqVariablesMap;
    // Read the display seam once: it both gates the feet-and-inches parser
    // (#290) and projects the formula context into display space (#292).
    const dq = gridCtx?.displayQuantity;
    const formulaCtx = useMemo(() => {
      // Issue #292 / H2 fix: evaluate the quantity formula in METRIC-canonical
      // space. Every symbol a formula can reference - pos()/section() positions,
      // $VAR variables, and pos().rate/.total - is stored metric-canonical, and
      // BOQ variables carry no unit, so there is no single display factor that
      // could project them all consistently. We therefore keep positions raw
      // (metric) here; when a formula actually references one of these canonical
      // symbols the commit path treats the whole result as already-canonical and
      // skips toMetricQty (see parseInput), while a pure-literal formula (=10+6)
      // or a plain typed number is still read in the displayed unit and
      // converted once. This removes the earlier split - positions projected but
      // variables passed raw - which double-converted a dimensional $VAR in
      // imperial mode and stored ~10.76x the metric quantity.
      return buildFormulaContext({
        positions: ctxPositions ?? [],
        variables: ctxVariables ?? new Map<string, FormulaVariable>(),
        currentPositionId: props.data?.id,
      });
    }, [ctxPositions, ctxVariables, props.data?.id]);

    // Issue #290: engage feet-and-inches parsing ONLY in imperial cells whose
    // unit displays as feet (metric users and every other unit are untouched).
    const ftInActive = dq?.system === 'imperial' && dq.unitFor(props.data?.unit ?? '') === 'ft';

    const preview = useMemo(
      () => previewFor(value, formulaCtx, ftInActive),
      [value, formulaCtx, ftInActive],
    );

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
    const parseInput = (live: string): ParseResult => {
      const trimmed = live.trim();
      // Issue #290: feet-and-inches, imperial foot cells only. The result is a
      // DISPLAY quantity in feet; the commit path (toMetricQty) converts it to
      // metres, so it is NOT canonical yet.
      if (ftInActive) {
        const ft = parseFeetInches(trimmed);
        if (ft !== null) return { ok: true, parsed: ft, formulaSrc: '', canonical: false };
      }
      // Plain finite number (strict - never truncate "abc" / "10.5x" to a
      // partial value the way parseFloat did). A plain number is read in the
      // displayed unit, so it still needs display->metric conversion.
      const plain = parsePlainNumber(trimmed);
      if (plain !== null) return { ok: true, parsed: plain, formulaSrc: '', canonical: false };
      // Formula - context-aware so $VAR / pos(...) resolve (Issue #292). H2 fix:
      // when the formula references a canonical symbol ($VAR / pos() / section(),
      // which also covers pos().rate / .total), the resolved value is already in
      // metric-canonical space and must NOT run through toMetricQty again; a
      // pure-literal formula (=10+6) carries no reference, so it is read in the
      // displayed unit like a plain number and converted once.
      if (isFormula(trimmed)) {
        const result = evaluateFormula(trimmed, formulaCtx);
        if (result !== null) {
          const refs = extractReferences(trimmed);
          const canonical =
            refs.variables.size > 0 ||
            refs.positionOrdinals.size > 0 ||
            refs.sectionNames.size > 0;
          return { ok: true, parsed: result, formulaSrc: trimmed, canonical };
        }
      }
      return { ok: false };
    };

    // Idempotency guard: Enter→commitFromInput→stopEditing destroys the
    // input, which fires a tail blur event that would otherwise re-enter
    // commitFromInput and double-PATCH the formula. Track whether we've
    // already committed and short-circuit subsequent calls.
    const committedRef = useRef(false);

    const commitFromInput = (cancelNavigation: boolean, fromBlur = false): boolean => {
      if (committedRef.current) return true;
      committedRef.current = true;

      const live = inputRef.current?.value ?? value;
      const res = parseInput(live);
      // Issue #290: refuse to commit garbage. Never fall back to
      // ``parseFloat || 0`` - that silently stored 0 (or a truncated number)
      // for "abc" / a malformed ft-in / an unresolved formula. When the input
      // can't be classified as a plain number, a valid ft-in value or a
      // formula that evaluates, keep the user's text so they can fix it
      // (Enter/Tab) or revert to the stored value (blur = Escape-cancel).
      if (!res.ok) {
        if (fromBlur) {
          // Cancel: preserve the previously stored value. Mark committed
          // FIRST - stopEditing tears the input down, which can fire a tail
          // blur that would re-enter here and double-toast.
          committedRef.current = true;
          if (live.trim() !== '') toastInvalidNumber(t);
          props.api.stopEditing(true);
          return true;
        }
        // Keep the editor open so the user can correct the entry, and clear
        // the idempotency guard so a corrected retry still commits.
        committedRef.current = false;
        return false;
      }
      const { parsed, formulaSrc, canonical } = res;
      // Issue #285 / H2 fix: the Qty cell DISPLAYS the value converted into the
      // user's measurement system, so a displayed value (a plain number, a
      // feet-and-inches entry, or a pure-literal formula) resolves in the
      // displayed unit and is converted back to metric-canonical storage here,
      // before writing via setDataValue (which bypasses the column valueParser).
      // A formula that referenced a canonical symbol ($VAR / pos() / section())
      // already resolved to a metric-canonical value, so it is stored as-is and
      // must NOT be converted again. Identity for metric / unmapped units. The
      // metric value goes into lastParsedRef so getValue() returns the same one.
      const metricParsed = canonical ? parsed : toMetricQty(props, parsed);
      const hadStoredFormula = !!formula;
      lastParsedRef.current = metricParsed;
      lastFormulaRef.current = formulaSrc;

      if (formulaSrc) {
        fireFormulaApplied(props.data?.id, formulaSrc, metricParsed);
      } else if (hadStoredFormula) {
        // User replaced a stored formula with a plain number — clear it.
        fireFormulaApplied(props.data?.id, '', metricParsed);
      }

      // ag-grid-react v32 + React 18 sometimes skips ``getValue()`` after
      // ``stopEditing(false)`` on functional editors, so write the value
      // directly *and* implement getValue. The check ``parsed !== old``
      // ensures we don't fire a no-op cellValueChanged.
      //
      // CRITICAL — flash-then-revert fix (v2.6.34):
      // ``stopEditing(false)`` triggers AG Grid's own commit path, which
      // calls ``getValue()`` on the editor instance React happens to be
      // showing. Under StrictMode (and any double-mount of the popup
      // editor) AG Grid can query a *different* React instance whose
      // ``lastParsedRef`` is still ``null`` and whose ``value`` state is
      // the pre-edit text — so getValue returns the OLD numeric value.
      // That fires a *second* cellValueChanged with newValue=<old> and
      // overwrites the value we just wrote via setDataValue.
      //
      // Behaviour observed by the live probe:
      //   PROBE cellValueChanged {oldValue:1, newValue:6}        ← from setDataValue
      //   PROBE cellValueChanged {oldValue:6, newValue:1, src:"edit"}   ← AG Grid stale-instance commit
      //   → two PATCH requests fire ~3 ms apart, the second carrying the
      //     OLD value, and a few hundred ms later the cell snaps back.
      //
      // Fix: when we successfully wrote via setDataValue, pass
      // ``cancel=true`` to stopEditing so AG Grid skips its own commit
      // step. Tab navigation is handled explicitly by the caller via
      // ``tabToNextCell()``, and the new value is already in the row.
      const colId = props.column?.getColId?.() ?? 'quantity';
      const oldValue = props.node?.data?.[colId];
      // ``oldValue`` is the stored (metric-canonical) quantity, so compare it
      // against the metric value we are about to write, not the display one.
      const wroteViaSetDataValue = metricParsed !== oldValue;
      if (wroteViaSetDataValue) {
        props.node?.setDataValue(colId, metricParsed);
      }

      // If we already wrote the value, cancel AG Grid's secondary commit
      // path; otherwise honour the caller's intent (commit-then-navigate).
      props.api.stopEditing(wroteViaSetDataValue ? true : cancelNavigation);
      return true;
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
          // Only advance the focus when the value actually committed; on an
          // invalid entry commitFromInput keeps the editor open (Issue #290).
          if (commitFromInput(false)) {
            // Direction follows the modifier: preventDefault above removed the
            // grid's own move, so always calling tabToNextCell would send
            // Shift+Tab forward.
            if (ev.shiftKey) props.api.tabToPreviousCell();
            else props.api.tabToNextCell();
          }
        }
      };
      const handleBlur = () => {
        // Blur (clicking outside the popup) should also commit, matching how
        // AG Grid's native editors behave. On an invalid entry this cancels
        // the edit so the previously stored value is preserved (Issue #290).
        commitFromInput(false, true);
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
        // Issue #285: the resolved value is in the displayed unit; convert it
        // back to metric-canonical storage so getValue() can never leak an
        // imperial number into the quantity field.
        const live = inputRef.current?.value ?? value;
        const res = parseInput(live);
        // Issue #290: on invalid input never coerce to 0 - hand AG Grid back
        // the original stored (metric) value so a stray cold-path getValue
        // can't corrupt it.
        if (!res.ok) return props.value;
        // H2 fix: mirror commitFromInput - a formula that referenced a canonical
        // symbol is already metric-canonical and must not be converted again.
        return res.canonical ? res.parsed : toMetricQty(props, res.parsed);
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
            title={t('boq.formula_hint', { defaultValue: 'Type = to enter a formula. Click ? for help.' })}
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
            aria-label={t('boq.formula_help', { defaultValue: 'Formula help' })}
            title={t('boq.formula_help', { defaultValue: 'Formula help' })}
          >
            ?
          </button>
        </div>

        {/* Live preview row — anchors below the cell, doesn't shift layout */}
        {preview.kind !== 'idle' && (
          <div className="absolute right-0 top-full mt-0.5 text-[10px] leading-tight tabular-nums pointer-events-none whitespace-nowrap z-10 px-1.5 py-0.5 rounded shadow-sm bg-surface-elevated border border-border-light">
            {preview.kind === 'ok' && (
              <span className="text-emerald-600 dark:text-emerald-400 font-semibold">
                = {preview.v.toLocaleString(getNumberLocale(), { minimumFractionDigits: 2, maximumFractionDigits: 4 })}
              </span>
            )}
            {preview.kind === 'number' && isFormulaMode === false && value.trim() !== '' && (
              <span className="text-content-tertiary">numeric input</span>
            )}
            {preview.kind === 'err' && (
              <span className="inline-flex items-center gap-1 text-rose-600 dark:text-rose-400">
                <AlertTriangle size={11} strokeWidth={2} /> {preview.m}
              </span>
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
                aria-label={t('boq.formula_help_close', { defaultValue: 'Close help' })}
              >
                <XIcon size={12} strokeWidth={2.25} />
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

/* ── Rate Cell Editor (Issue #287) ────────────────────────────────── */

/**
 * Display-aware editor for the Unit Rate column.
 *
 * The rate cell DISPLAYS a reciprocal per-unit rate when the quantity is shown
 * converted (a 50/m rate reads 15.24/ft) so the line total reconciles. The
 * stock ``agNumberCellEditor`` opens on the RAW METRIC rate while the column
 * ``valueParser`` (``toMetricRate``) converts display→metric on commit, so
 * opening and committing a cell unchanged multiplied the stored rate by the
 * unit factor and silently corrupted storage (Issue #287).
 *
 * This editor OPENS on the displayed rate (``convertRate``) and returns the
 * typed display value; the column ``valueParser`` reverses it back to
 * metric-canonical storage. Both conversions are identity for the metric
 * system and for units with no imperial mapping, so metric users are
 * unaffected and imperial edits round-trip exactly. Inline (non-popup)
 * editor, so a plain controlled input is safe here.
 */
export const RateCellEditor = forwardRef((props: ICellEditorParams, ref) => {
  const { t } = useTranslation();
  const dq = (props.context as { displayQuantity?: DisplayQuantityApi } | undefined)?.displayQuantity;
  const unit = (props.data?.unit as string | undefined) ?? '';
  const inputRef = useRef<HTMLInputElement>(null);
  // The rate the editor OPENS on, in the displayed system. Kept as the
  // unchanged-commit fallback for the cold getValue path.
  const displaySeed = useMemo(() => {
    const raw = props.value;
    if (typeof raw !== 'number' || !isFinite(raw)) return null;
    return dq ? dq.convertRate(raw, unit) : raw;
  }, [props.value, dq, unit]);

  const seedStr = displaySeed != null ? String(displaySeed) : '';
  // ``valueRef`` mirrors the input synchronously. A plain JSX ``onChange`` +
  // ``getValue()`` was NOT enough: ag-grid-react v32 + React 18 (a) can skip
  // ``getValue()`` entirely after ``stopEditing`` on a functional editor, and
  // (b) the editor renders in an edit root where the synthetic ``onChange``
  // does not always fire. Either way a rate typed on a resource-less position
  // committed the OLD value and the edit was silently dropped (cell reverted to
  // 0, no PATCH). We therefore mirror FormulaCellEditor / UnitCellEditor:
  // NATIVE input/keydown/blur listeners capture the keystrokes, and Enter/Tab/
  // blur writes the metric-canonical rate straight to the row via
  // ``setDataValue`` (which bypasses the column valueParser), then cancels
  // ag-grid's own secondary commit so exactly one cellValueChanged fires.
  const valueRef = useRef<string>(seedStr);
  const committedRef = useRef(false);

  useEffect(() => {
    inputRef.current?.focus();
    inputRef.current?.select();
  }, []);

  const commit = (cancelNavigation: boolean): boolean => {
    if (committedRef.current) return true;
    const live = inputRef.current?.value ?? valueRef.current;
    // Locale-aware and strict: `48,60` -> 48.6, `1.234,56` -> 1234.56, and
    // garbage is refused instead of parseFloat-truncated. The input is
    // type=text precisely so the comma REACHES this parser - a number input
    // silently drops it and a German keystroke became a 100x rate.
    const n = parseDecimalInput(live);
    if (n === null) {
      // Keep the previously stored rate (Escape-style cancel). Guard set so
      // a tail blur after Enter doesn't re-enter. An empty field is a plain
      // "changed my mind"; anything else earns the why-was-it-kept toast.
      committedRef.current = true;
      if (live.trim() !== '') toastInvalidNumber(t);
      props.api.stopEditing(true);
      return true;
    }
    committedRef.current = true;
    // Typed value is in the DISPLAYED system; convert back to metric-canonical
    // before writing. ``toMetricRate`` is identity for metric / unmapped units.
    const metric = dq ? dq.toMetricRate(n, unit) : n;
    const colId = props.column?.getColId?.() ?? 'unit_rate';
    const oldValue = props.node?.data?.[colId as keyof typeof props.node.data];
    const wrote = Number(metric) !== Number(oldValue);
    if (wrote) props.node?.setDataValue(colId, metric);
    // When we wrote via setDataValue, cancel ag-grid's secondary getValue
    // commit (cancel=true) so it can't fire a second, stale cellValueChanged.
    props.api.stopEditing(wrote ? true : cancelNavigation);
    return true;
  };

  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    const onInput = (ev: Event) => {
      valueRef.current = (ev.target as HTMLInputElement).value;
    };
    const onKeyDown = (ev: KeyboardEvent) => {
      if (ev.key === 'Escape') {
        props.api.stopEditing(true);
        return;
      }
      if (ev.key === 'Enter') {
        ev.preventDefault();
        ev.stopPropagation();
        commit(false);
        return;
      }
      if (ev.key === 'Tab') {
        ev.preventDefault();
        ev.stopPropagation();
        // Direction follows the modifier, for the same reason as in the other
        // two editors: the default move is already cancelled above.
        if (commit(false)) {
          if (ev.shiftKey) props.api.tabToPreviousCell();
          else props.api.tabToNextCell();
        }
      }
    };
    const onBlur = () => commit(false);
    el.addEventListener('input', onInput);
    el.addEventListener('keydown', onKeyDown);
    el.addEventListener('blur', onBlur);
    return () => {
      el.removeEventListener('input', onInput);
      el.removeEventListener('keydown', onKeyDown);
      el.removeEventListener('blur', onBlur);
    };
  }, []);

  useImperativeHandle(ref, () => ({
    getValue() {
      // Cold path only (programmatic stopEditing without our commit): return the
      // typed DISPLAY value so the column valueParser converts it once to metric.
      const n = parseDecimalInput(valueRef.current);
      if (n !== null) return n;
      if (displaySeed != null) return displaySeed;
      return props.value;
    },
    isCancelAfterEnd() {
      return false;
    },
  }));

  return (
    <input
      ref={inputRef}
      // type=text, NOT number: a number input drops the decimal comma at the
      // keystroke level, so a German typing 48,60 silently got 4860 - the
      // comma must survive the DOM to reach parseDecimalInput above.
      // inputMode keeps the numeric keyboard on touch devices.
      type="text"
      inputMode="decimal"
      autoComplete="off"
      spellCheck={false}
      className="w-full h-full bg-surface-elevated border border-oe-blue/40 rounded ring-2 ring-oe-blue/20 outline-none text-sm text-content-primary tabular-nums text-right px-1"
      defaultValue={seedStr}
    />
  );
});
RateCellEditor.displayName = 'RateCellEditor';

/* ── Autocomplete Cell Editor ─────────────────────────────────────── */

export interface AutocompleteCellEditorParams extends ICellEditorParams {
  onSelectSuggestion?: (positionId: string, item: CostAutocompleteItem) => void;
}

export const AutocompleteCellEditor = forwardRef(
  (props: AutocompleteCellEditorParams, ref) => {
    const { t } = useTranslation();
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
          placeholder={t('boq.description_placeholder', { defaultValue: 'Enter description...' })}
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

/**
 * StrictMode-proof commit channel for unit picks.
 *
 * In React 18 + <StrictMode>, AG Grid's editor wrapper remounts the
 * `UnitCellEditor` up to 8 times when a user dblclicks. Each remount
 * gets a fresh React instance with its own `valueRef` / `committedRef`,
 * and AG Grid's `getValue()` (called synchronously inside `stopEditing`)
 * routes through whichever instance is current at THAT moment — which
 * may be a different one than the instance whose `pick()` ran. The
 * picked value gets dropped on the floor.
 *
 * The fix: when `pick()` fires, record the picked value in this
 * module-scoped map keyed by `${rowId}:${colId}` BEFORE calling
 * `stopEditing(false)`. The unit column also wires a `valueSetter`
 * (see `getUnitColumnValueSetter`) that consults this map first,
 * falling back to AG Grid's `params.newValue`. The map entry is
 * cleared as soon as it's read so a stale pick from a previous edit
 * can't leak into the next one. Because the channel lives outside
 * the React tree, it doesn't matter which mount instance handled the
 * keystroke — the pick is durable.
 */
const __unitPickCommitChannel = new Map<string, string>();

function unitPickKey(rowId: string | number | undefined, colId: string | undefined): string {
  return `${rowId ?? ''}:${colId ?? 'unit'}`;
}

/**
 * `valueSetter` factory for the `unit` column. Drains
 * `__unitPickCommitChannel` first if there's a pending pick for this
 * row+col; otherwise falls back to the value AG Grid pulled via
 * `getValue()` on the (possibly stale) editor instance. Always returns
 * `true` when the value actually changed so AG Grid fires its
 * `cellValueChanged` event and the position update flows through.
 */
export function unitColumnValueSetter(params: {
  data: Record<string, unknown> | null | undefined;
  newValue: unknown;
  oldValue: unknown;
  node?: { id?: string | number } | null;
  column?: { getColId?: () => string } | null;
}): boolean {
  const data = params.data;
  if (!data) return false;
  const rowId = params.node?.id ?? (data as { id?: string }).id;
  const colId = params.column?.getColId?.() ?? 'unit';
  const key = unitPickKey(rowId, colId);
  const pending = __unitPickCommitChannel.get(key);
  // Drain the channel regardless of which path wins so a stale pick
  // can't leak into the next edit.
  if (pending !== undefined) __unitPickCommitChannel.delete(key);
  const incoming = pending !== undefined
    ? pending
    : (params.newValue == null ? '' : String(params.newValue));
  const next = incoming.trim();
  const prev = params.oldValue == null ? '' : String(params.oldValue);
  if (next === prev) return false;
  (data as Record<string, unknown>).unit = next;
  return true;
}

export const UnitCellEditor = forwardRef((props: ICellEditorParams, ref) => {
  const { t } = useTranslation();
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

  // Stable key for the StrictMode-proof commit channel. AG Grid's
  // ``props.node.id`` is the same row identifier `getRowId` returns, so
  // remounted editor instances share the same key.
  const channelKey = unitPickKey(
    props.node?.id ?? (props.data as { id?: string } | undefined)?.id,
    props.column?.getColId?.(),
  );

  /**
   * Apply a unit commit synchronously, regardless of which React mount
   * instance handled the keystroke. We push the value into the row via
   * ``props.node.setDataValue(colId, v)`` — this triggers the column's
   * ``valueSetter`` (which drains ``__unitPickCommitChannel`` for parity
   * with the keyboard / AG-Grid-internal paths) and fires
   * ``cellValueChanged``. Calling ``setDataValue`` bypasses the editor
   * lifecycle entirely, so it doesn't matter whether AG Grid is about
   * to query a stale React instance for ``getValue()`` — the data is
   * already updated.
   */
  const applyCommit = useCallback((v: string) => {
    if (committedRef.current) return;
    committedRef.current = true;
    const trimmed = v.trim();
    valueRef.current = trimmed;
    __unitPickCommitChannel.set(channelKey, trimmed);
    setValue(trimmed);
    setOpen(false);
    if (trimmed) saveCustomUnit(trimmed);
    // Push the value into the row data. This is the StrictMode-proof
    // path: ``setDataValue`` calls our ``valueSetter`` synchronously,
    // which drains the channel and mutates ``data.unit`` regardless of
    // which React instance is current. ``cellValueChanged`` fires next.
    try {
      const colId = props.column?.getColId?.() ?? 'unit';
      const oldVal = props.node?.data?.[colId];
      if (oldVal !== trimmed) {
        props.node?.setDataValue(colId, trimmed);
      }
    } catch { /* node detached — channel still holds the value */ }
    // Stop editing AFTER setDataValue so AG Grid doesn't try to
    // re-commit via the editor lifecycle (which is the path that loses
    // the pick in StrictMode).
    try { props.api.stopEditing(true); } catch { /* editor already gone */ }
  }, [props.api, props.node, props.column, channelKey]);

  const commit = useCallback((finalValue?: string) => {
    applyCommit(finalValue ?? value);
  }, [applyCommit, value]);

  const pick = useCallback((u: string) => {
    applyCommit(u);
  }, [applyCommit]);

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

  // Native mousedown listener on the portaled <ul> itself.
  //
  // Why not React's onMouseDown? In rare cases AG Grid's editor lifecycle
  // unmounts the React tree (and the portal) BEFORE React flushes the
  // synthetic-event handlers, so the React handler never runs. A native
  // listener attached directly to the <ul> DOM node fires synchronously
  // as the event reaches the target — and our handler reads the picked
  // unit out of ``data-unit-value`` on the clicked <li>, which is set
  // statically at render time and survives any subsequent unmount.
  //
  // We previously had a document-level CAPTURE-phase shield that called
  // ``stopImmediatePropagation`` on mousedowns inside the listbox. That
  // shield was the actual cause of the "unit pick silently dropped" bug:
  // a capture-phase ``stopImmediatePropagation()`` on document halts the
  // event before it reaches the target <li>, so React's onMouseDown
  // handler never fired. Removed.
  useEffect(() => {
    if (!open) return;
    const ul = listRef.current;
    if (!ul) return;
    const handler = (e: MouseEvent) => {
      const target = e.target as HTMLElement | null;
      const li = target?.closest?.('li[role="option"]') as HTMLElement | null;
      if (!li || !ul.contains(li)) return;
      const picked = li.getAttribute('data-unit-value');
      if (picked == null) return;
      // Prevent the input from blurring (which would close the editor
      // before our applyCommit runs) and stop AG Grid's outside-click
      // detector via preventDefault on mousedown.
      e.preventDefault();
      applyCommit(picked);
    };
    ul.addEventListener('mousedown', handler);
    return () => ul.removeEventListener('mousedown', handler);
  }, [open, applyCommit]);

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
            // Plain Tab commits the current text - same behaviour as Enter on
            // a free-typed value, lets the user blow past the dropdown.
            //
            // Cancelling the keystroke matters as much as committing it. Left
            // uncancelled, this same Tab also runs ag-grid's own
            // Tab-during-edit path, so the grid advances a second time and,
            // with stopEditingWhenCellsLoseFocus on, tears down the popup
            // editor the first advance had just opened. That is the blink a
            // user sees on the quantity cell after leaving unit: the editor
            // opens and is closed by the duplicate of the keystroke that
            // opened it, and only a mouse click gets it back. Every other
            // branch in this handler already cancels; this one did not, which
            // is why this was the only hop that broke.
            e.preventDefault();
            e.stopPropagation();
            commit();
            // preventDefault also removes the grid's own move, so the move has
            // to be made here, and in the direction the user actually asked
            // for. Without the shiftKey arm Shift+Tab would walk forward.
            if (e.shiftKey) props.api.tabToPreviousCell();
            else props.api.tabToNextCell();
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
        aria-label={t('boq.inline_edit_unit', { defaultValue: 'Edit unit' })}
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
                  data-unit-value={u}
                  role="option"
                  aria-selected={idx === activeIdx}
                  onMouseEnter={() => setActiveIdx(idx)}
                  // NOTE: the actual commit handler is a native mousedown
                  // listener attached to the <ul> in a useEffect above.
                  // It reads ``data-unit-value`` off the closest <li>.
                  // We don't use React's onMouseDown here because React's
                  // synthetic events don't fire if AG Grid happens to
                  // unmount the editor before flush.
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
