// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Live preview and API payload for formula-mode quantity links (Issue #535,
 * backend half: Issue #347). Evaluation reuses the shared element-formula
 * engine, so a preview matches what the backend computes at apply time.
 */
import { buildElementVars, evaluateElementFormula, normalizeVarName } from './elementFormula';
import type { CreateQuantityLinkData, QuantityAggregation } from '../../api';

export interface FormulaElementInput {
  id: string;
  label: string;
  quantities?: Record<string, unknown> | null;
  /** Properties incl. `[Type] <key>` params and any extra numeric columns. */
  properties?: Record<string, unknown> | null;
}

export interface FormulaVarChip {
  /** Identifier to insert into the formula. */
  name: string;
  /** Source key as shown to the user. */
  label: string;
  /** Number of elements that carry a numeric value for it. */
  count: number;
}

export interface FormulaElementResult {
  id: string;
  label: string;
  value: number;
}

export interface FormulaMissingResult {
  id: string;
  label: string;
  /** Variable names the element lacks, or the evaluation error text. */
  missing: string[];
  error?: string;
}

export interface FormulaPreview {
  /** Aggregated value, or null when no element produced a value. */
  total: number | null;
  rows: FormulaElementResult[];
  /** Elements left out of the total (never counted as 0). */
  skipped: FormulaMissingResult[];
  /** Whole-formula problem (empty / syntax), shown instead of rows. */
  error: string | null;
}

const UNKNOWN_RE = /^Unknown identifier: (.+)$/;

export function aggregateValues(values: number[], agg: QuantityAggregation): number | null {
  if (agg === 'count') return values.length;
  if (values.length === 0) return null;
  switch (agg) {
    case 'max':
      return Math.max(...values);
    case 'min':
      return Math.min(...values);
    case 'first':
      return values[0]!;
    default:
      return values.reduce((a, b) => a + b, 0);
  }
}

/** Variable chips for the linked elements, most widely available first. */
export function collectFormulaVars(elements: FormulaElementInput[]): FormulaVarChip[] {
  const byName = new Map<string, FormulaVarChip>();
  for (const el of elements) {
    for (const source of [el.quantities, el.properties]) {
      if (!source) continue;
      for (const key of Object.keys(source)) {
        const name = normalizeVarName(key);
        if (!name) continue;
        if (!byName.has(name)) byName.set(name, { name, label: key, count: 0 });
      }
    }
    const vars = buildElementVars(el.quantities, el.properties);
    for (const name of vars.keys()) {
      const chip = byName.get(name);
      if (chip) chip.count += 1;
    }
  }
  return [...byName.values()]
    .filter((c) => c.count > 0)
    .sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
}

export function previewFormula(
  formula: string,
  aggregation: QuantityAggregation,
  elements: FormulaElementInput[],
): FormulaPreview {
  const text = formula.trim();
  if (!text) return { total: null, rows: [], skipped: [], error: null };
  const rows: FormulaElementResult[] = [];
  const skipped: FormulaMissingResult[] = [];
  let fatal: string | null = null;
  for (const el of elements) {
    const vars = buildElementVars(el.quantities, el.properties);
    try {
      rows.push({ id: el.id, label: el.label, value: evaluateElementFormula(text, vars) });
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      const m = UNKNOWN_RE.exec(msg);
      if (m) {
        skipped.push({ id: el.id, label: el.label, missing: [normalizeVarName(m[1]) || m[1]!] });
      } else {
        fatal = fatal ?? msg;
        skipped.push({ id: el.id, label: el.label, missing: [], error: msg });
      }
    }
  }
  if (rows.length === 0 && fatal) return { total: null, rows: [], skipped: [], error: fatal };
  return {
    total: aggregateValues(
      rows.map((r) => r.value),
      aggregation,
    ),
    rows,
    skipped,
    error: null,
  };
}

/** Body for `POST /v1/boq/positions/{id}/quantity-links/` in formula mode. */
export function buildFormulaLinkPayload(
  modelId: string,
  elementStableIds: string[],
  formula: string,
  aggregation: QuantityAggregation,
): CreateQuantityLinkData {
  return {
    model_id: modelId,
    element_stable_ids: elementStableIds,
    projection_mode: 'formula',
    formula: formula.trim(),
    aggregation,
    target_field: 'quantity',
  };
}
