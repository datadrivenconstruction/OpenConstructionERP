// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * New​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠ rows from a pasted block: map the block onto the sheet columns it was
 * pasted under, read numbers in the user's locale and check every row before
 * anything is written, so the preview shows exactly what will be created.
 */

import type { PastedRow } from '../ExcelPasteModal';
import type { SheetField } from './history';
import { parseLocaleNumber } from './numberFormat';

export type RowIssueCode = 'description_missing' | 'unit_missing' | 'not_a_number' | 'negative';

export interface RowIssue {
  field: SheetField;
  code: RowIssueCode;
}

export interface PreviewRow {
  row: PastedRow;
  issues: RowIssue[];
}

const NUMERIC: ReadonlySet<SheetField> = new Set(['quantity', 'unit_rate']);

/** A first line whose numeric columns hold words is a header the user copied along. */
export function isHeaderLine(cells: string[], fields: SheetField[], locale: string): boolean {
  let numericCols = 0;
  let wordy = 0;
  fields.forEach((f, i) => {
    if (!NUMERIC.has(f)) return;
    numericCols += 1;
    const v = (cells[i] ?? '').trim();
    if (v && parseLocaleNumber(v, locale) === null) wordy += 1;
  });
  return numericCols > 0 && wordy === numericCols;
}

export function buildPreview(matrix: string[][], fields: SheetField[], locale: string): PreviewRow[] {
  const lines = matrix.filter((cells) => cells.some((c) => c.trim() !== ''));
  if (lines.length > 0 && isHeaderLine(lines[0]!, fields, locale)) lines.shift();
  return lines.map((cells) => {
    const row: PastedRow = { ordinal: '', description: '', unit: '', quantity: 0, unit_rate: 0 };
    const issues: RowIssue[] = [];
    fields.forEach((field, i) => {
      const raw = (cells[i] ?? '').trim();
      if (field === 'quantity' || field === 'unit_rate') {
        if (!raw) return;
        const n = parseLocaleNumber(raw, locale);
        if (n === null) issues.push({ field, code: 'not_a_number' });
        else if (n < 0) issues.push({ field, code: 'negative' });
        else row[field] = n;
      } else if (field === 'ordinal' || field === 'description' || field === 'unit') {
        row[field] = raw;
      }
    });
    if (!row.description) issues.push({ field: 'description', code: 'description_missing' });
    if (!row.unit && (row.quantity > 0 || row.unit_rate > 0)) issues.push({ field: 'unit', code: 'unit_missing' });
    return { row, issues };
  });
}
