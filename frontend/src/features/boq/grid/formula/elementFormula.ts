// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Per-element quantity formulas (Issue #347) — frontend half.
 *
 * A BOQ quantity link can project a position's quantity out of its bound BIM
 * elements with a per-element arithmetic formula (`area_m2 * 0.5`,
 * `length_m * height_m`, …). This module builds the variable map a formula
 * sees for one element and evaluates the formula by REUSING the shared BOQ
 * formula engine (no second evaluator) — it just teaches the engine to resolve
 * bare identifiers from `elementVars`.
 *
 * The `normalizeVarName` / `isNumericValue` / `buildElementVars` helpers are
 * mirrored byte-for-byte in the backend `app/modules/boq/quantity_formula.py`
 * and locked by the shared vectors fixture
 * (`src/shared/lib/__fixtures__/elementFormula.vectors.json`) so a formula
 * written in the grid resolves to the same value the backend computes at apply
 * time. Keep the two in lock-step.
 */
import { evaluateFormulaStrict, type FormulaContext } from './engine';

const NON_IDENT_RE = /[^A-Za-z0-9]/g;
const MULTI_US_RE = /_+/g;
const NUMERIC_STR_RE = /^[+-]?(\d+(\.\d+)?|\.\d+)([eE][+-]?\d+)?$/;

/**
 * Turn an arbitrary quantity/property key into a formula identifier.
 * MUST stay identical to the backend `normalize_var_name`.
 */
export function normalizeVarName(raw: unknown): string {
  let s = String(raw).replace(NON_IDENT_RE, '_');
  s = s.replace(MULTI_US_RE, '_').replace(/^_+|_+$/g, '');
  s = s.toLowerCase();
  if (!s) return '';
  if (s.charCodeAt(0) >= 48 && s.charCodeAt(0) <= 57) s = '_' + s;
  return s;
}

/**
 * True when `value` is a finite number or a plain numeric string. Booleans are
 * NOT numeric. MUST stay identical to the backend `is_numeric_value`.
 */
export function isNumericValue(value: unknown): boolean {
  if (typeof value === 'boolean') return false;
  if (typeof value === 'number') return Number.isFinite(value);
  if (typeof value === 'string') return NUMERIC_STR_RE.test(value.trim());
  return false;
}

/**
 * Build the variable map a formula sees for one element: every numeric
 * `quantities` entry (primary), then every numeric `properties` entry whose
 * normalised name is not already taken (secondary). MUST stay identical to the
 * backend `build_element_vars`.
 */
export function buildElementVars(
  quantities: Record<string, unknown> | null | undefined,
  properties?: Record<string, unknown> | null | undefined,
): Map<string, number> {
  const out = new Map<string, number>();
  for (const source of [quantities, properties]) {
    if (!source || typeof source !== 'object') continue;
    for (const [key, val] of Object.entries(source)) {
      if (!isNumericValue(val)) continue;
      const name = normalizeVarName(key);
      if (!name || out.has(name)) continue;
      out.set(name, Number(val));
    }
  }
  return out;
}

/**
 * Evaluate a per-element formula against its variable map. Returns the numeric
 * result (rounded to 4 dp by the engine). Throws on an unknown variable, a
 * banned construct, division by zero, or any non-numeric result — the caller
 * surfaces the error (never a silent zero), mirroring the backend.
 */
export function evaluateElementFormula(formula: string, vars: Map<string, number>): number {
  const ctx: FormulaContext = {
    positionsByOrdinal: new Map(),
    positionsById: new Map(),
    sectionsByName: new Map(),
    variables: new Map(),
    elementVars: vars,
  };
  const result = evaluateFormulaStrict(formula, ctx);
  if (typeof result !== 'number' || !Number.isFinite(result)) {
    throw new Error('formula did not produce a numeric result');
  }
  return result;
}
