// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cell formulas in the sheet's quantity and rate cells, on top of the BOQ
 * formula engine: the same $VARIABLES, pos("01.010").qty links and
 * section("Name").total. A quantity formula lives on metadata.formula, the
 * same key the grid uses; a rate formula on metadata.rate_formula.
 */

import type { BOQVariable, Position } from '../api';
import {
  buildDependencyGraph,
  buildFormulaContext,
  evaluateFormula,
  isFormula,
  variableUsers,
  type FormulaVariable,
} from '../grid/formula';

export type FormulaOutcome =
  | { ok: true; value: number }
  | { ok: false; error: 'cycle'; cycle: string[] }
  | { ok: false; error: 'invalid' };

export function variablesMap(vars: BOQVariable[] | undefined): Map<string, FormulaVariable> {
  const m = new Map<string, FormulaVariable>();
  for (const v of vars ?? []) m.set(v.name.toUpperCase(), { type: v.type, value: v.value });
  return m;
}

/** True when the typed text is a formula and not a plain number. */
export function looksLikeFormula(text: string): boolean {
  const t = text.trim();
  return t.startsWith('=') || (isFormula(t) && /[a-z$(]/i.test(t));
}

export type FormulaField = 'quantity' | 'unit_rate';

function readText(p: Position, key: string): string {
  const v = (p.metadata ?? {})[key];
  return typeof v === 'string' ? v.trim() : '';
}

/**
 * Positions as the static graph sees them: the quantity and rate formulas of a
 * row are both its dependencies, so a loop through either is caught. Only the
 * references are read from the joined text, it is never evaluated.
 */
function forGraph(positions: Position[], rowId?: string, field?: FormulaField, formula?: string): Position[] {
  return positions.map((p) => {
    let q = readText(p, 'formula');
    let r = readText(p, 'rate_formula');
    if (p.id === rowId) {
      if (field === 'quantity') q = formula ?? '';
      else r = formula ?? '';
    }
    if (!r) return p.id === rowId ? { ...p, metadata: { ...(p.metadata ?? {}), formula: q } } : p;
    return { ...p, metadata: { ...(p.metadata ?? {}), formula: [q, r].filter(Boolean).join(' + ') } };
  });
}

function ordinalResolver(positions: Position[]): (o: string) => string | undefined {
  const byOrdinal = new Map(positions.map((p) => [p.ordinal, p.id]));
  return (o) => byOrdinal.get(o);
}

/**
 * Evaluate a formula typed into a row's quantity or rate cell. A formula that
 * would close a loop through pos() links is refused with the loop's ordinals.
 */
export function evaluateCellFormula(
  input: string,
  rowId: string,
  field: FormulaField,
  positions: Position[],
  variables: Map<string, FormulaVariable>,
): FormulaOutcome {
  const candidate = forGraph(positions, rowId, field, input.trim());
  const graph = buildDependencyGraph(candidate, { resolveOrdinal: ordinalResolver(candidate) });
  if (graph.cycleIds.has(rowId)) {
    const byId = new Map(positions.map((p) => [p.id, p.ordinal]));
    const path = graph.cyclePathById.get(rowId) ?? [rowId];
    return { ok: false, error: 'cycle', cycle: path.map((id) => byId.get(id) ?? id) };
  }
  const ctx = buildFormulaContext({ positions, variables, currentPositionId: rowId });
  const value = evaluateFormula(input, ctx);
  return value === null ? { ok: false, error: 'invalid' } : { ok: true, value };
}

export interface DependencyInfo {
  /** Ordinals this row's quantity formula reads. */
  uses: string[];
  /** Ordinals of rows whose formulas read this row. */
  usedBy: string[];
}

export function dependencyInfo(rowId: string, positions: Position[]): DependencyInfo {
  const graph = buildDependencyGraph(forGraph(positions), { resolveOrdinal: ordinalResolver(positions) });
  const byId = new Map(positions.map((p) => [p.id, p.ordinal]));
  const names = (ids: Set<string> | undefined) =>
    [...(ids ?? [])].map((id) => byId.get(id) ?? id).sort();
  return { uses: names(graph.dependsOn.get(rowId)), usedBy: names(graph.dependents.get(rowId)) };
}

/** Audit: ordinals of every position whose formula references `$name`. */
export function positionsUsingVariable(name: string, positions: Position[]): string[] {
  const graph = buildDependencyGraph(forGraph(positions), { resolveOrdinal: ordinalResolver(positions) });
  const byId = new Map(positions.map((p) => [p.id, p.ordinal]));
  return [...variableUsers(graph, name.replace(/^\$/, '').toUpperCase())].map((id) => byId.get(id) ?? id).sort();
}
