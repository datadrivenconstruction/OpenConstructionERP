// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Cell text to stored values: what a sheet cell shows, what it edits as, and
 * how a batch of text changes becomes one sheet-edit request. Changes are
 * applied in order to a working copy, so a formula reading a row changed in
 * the same paste sees the new value.
 */

import { isSection, type Position } from '../api';
import { evaluateCellFormula, looksLikeFormula, type FormulaOutcome } from './cellFormula';
import type { CellChange, SheetField } from './history';
import { formatLocaleNumber, parseLocaleNumber } from './numberFormat';
import type { FormulaVariable } from '../grid/formula';

export type ColumnId = SheetField | 'total';

export const FORMULA_KEY: Record<'quantity' | 'unit_rate', string> = {
  quantity: 'formula',
  unit_rate: 'rate_formula',
};

function storedFormula(p: Position, field: 'quantity' | 'unit_rate'): string {
  const v = (p.metadata ?? {})[FORMULA_KEY[field]];
  return typeof v === 'string' ? v.trim() : '';
}

export function isEditableCell(p: Position, col: ColumnId, readOnly = false): boolean {
  if (readOnly || col === 'total') return false;
  if (isSection(p)) return col === 'ordinal' || col === 'description';
  return true;
}

/** The text a cell opens with in edit mode, and the unit of undo. */
export function editText(p: Position, col: ColumnId, locale: string): string {
  switch (col) {
    case 'ordinal':
      return p.ordinal ?? '';
    case 'description':
      return p.description ?? '';
    case 'unit':
      return p.unit ?? '';
    case 'quantity':
    case 'unit_rate': {
      const f = storedFormula(p, col);
      if (f) return f.startsWith('=') ? f : `=${f}`;
      const n = Number(p[col] ?? 0);
      return Number.isFinite(n) ? formatLocaleNumber(n, locale, 6).replace(/[\s  ]/g, '') : '';
    }
    default:
      return displayText(p, col, locale);
  }
}

export function displayText(p: Position, col: ColumnId, locale: string): string {
  if (col === 'quantity' || col === 'unit_rate' || col === 'total') {
    if (isSection(p) && col !== 'total') return '';
    const n = Number(p[col] ?? 0);
    if (!Number.isFinite(n)) return '';
    return col === 'quantity' ? formatLocaleNumber(n, locale, 3) : formatLocaleNumber(n, locale, 2, 2);
  }
  return editText(p, col, locale);
}

export function hasFormula(p: Position, col: ColumnId): boolean {
  return (col === 'quantity' || col === 'unit_rate') && storedFormula(p, col) !== '';
}

export interface SheetCellEdit {
  id: string;
  version: number;
  fields: Record<string, unknown>;
}

export interface CellError {
  rowId: string;
  field: SheetField;
  outcome: Exclude<FormulaOutcome, { ok: true }> | { ok: false; error: 'not_a_number' | 'negative' };
}

/**
 * Turn text changes into per-row field updates. Numbers are sent as decimal
 * strings so the server keeps them exact; a typed formula is evaluated with
 * the engine and stored next to its value.
 */
export function toSheetEdits(
  changes: CellChange[],
  positions: Position[],
  variables: Map<string, FormulaVariable>,
  locale: string,
): { edits: SheetCellEdit[]; errors: CellError[]; working: Position[] } {
  const working = positions.map((p) => ({ ...p, metadata: { ...(p.metadata ?? {}) } }));
  const index = new Map(working.map((p, i) => [p.id, i]));
  const byRow = new Map<string, SheetCellEdit>();
  const errors: CellError[] = [];
  for (const ch of changes) {
    const i = index.get(ch.rowId);
    if (i === undefined) continue;
    const p = working[i]!;
    const edit = byRow.get(p.id) ?? { id: p.id, version: Number(p.version ?? 0), fields: {} };
    const text = ch.after.trim();
    if (ch.field === 'quantity' || ch.field === 'unit_rate') {
      const key = FORMULA_KEY[ch.field];
      let value: number;
      if (looksLikeFormula(text)) {
        const out = evaluateCellFormula(text, p.id, ch.field, working, variables);
        if (!out.ok) {
          errors.push({ rowId: p.id, field: ch.field, outcome: out });
          continue;
        }
        value = out.value;
        p.metadata = { ...p.metadata, [key]: text };
      } else {
        const n = text === '' ? 0 : parseLocaleNumber(text, locale);
        if (n === null || n < 0) {
          errors.push({ rowId: p.id, field: ch.field, outcome: { ok: false, error: n === null ? 'not_a_number' : 'negative' } });
          continue;
        }
        value = n;
        if (storedFormula(p, ch.field)) p.metadata = { ...p.metadata, [key]: '' };
      }
      p[ch.field] = value;
      p.total = Math.round(Number(p.quantity) * Number(p.unit_rate) * 100) / 100;
      edit.fields[ch.field] = String(value);
      if (p.metadata[key] !== undefined) {
        edit.fields.metadata = { ...((edit.fields.metadata as Record<string, unknown>) ?? {}), [key]: p.metadata[key] };
      }
    } else {
      p[ch.field] = text;
      edit.fields[ch.field] = text;
    }
    byRow.set(p.id, edit);
  }
  return { edits: [...byRow.values()].filter((e) => Object.keys(e.fields).length > 0), errors, working };
}
