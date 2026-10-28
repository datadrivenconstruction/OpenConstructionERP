// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Find and replace over the sheet, limited to the selected range when there
 * is one, else to the visible rows and columns.
 */

import type { CellChange, SheetField } from './history';

export interface FindOptions {
  caseSensitive?: boolean;
  wholeCell?: boolean;
}

export interface FindHit {
  row: number;
  col: number;
}

export interface Grid {
  rowIds: string[];
  fields: SheetField[];
  /** Raw text of a cell, as the user would edit it. */
  text: (row: number, col: number) => string;
  editable: (row: number, col: number) => boolean;
}

export interface Scope {
  r0: number;
  r1: number;
  c0: number;
  c1: number;
}

function matcher(query: string, opts: FindOptions): RegExp {
  const esc = query.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  return new RegExp(opts.wholeCell ? `^${esc}$` : esc, opts.caseSensitive ? 'g' : 'gi');
}

export function findAll(grid: Grid, query: string, scope: Scope, opts: FindOptions = {}): FindHit[] {
  if (!query) return [];
  const re = matcher(query, opts);
  const hits: FindHit[] = [];
  for (let r = scope.r0; r <= scope.r1; r += 1) {
    for (let c = scope.c0; c <= scope.c1; c += 1) {
      re.lastIndex = 0;
      if (re.test(grid.text(r, c))) hits.push({ row: r, col: c });
    }
  }
  return hits;
}

/** Changes for replace-all; read-only cells are counted in `skipped`, not changed. */
export function replaceAll(
  grid: Grid,
  query: string,
  replacement: string,
  scope: Scope,
  opts: FindOptions = {},
): { changes: CellChange[]; skipped: number } {
  const changes: CellChange[] = [];
  let skipped = 0;
  const re = matcher(query, opts);
  for (const hit of findAll(grid, query, scope, opts)) {
    if (!grid.editable(hit.row, hit.col)) {
      skipped += 1;
      continue;
    }
    const before = grid.text(hit.row, hit.col);
    const after = before.replace(re, () => replacement);
    changes.push({ rowId: grid.rowIds[hit.row]!, field: grid.fields[hit.col]!, before, after });
  }
  return { changes, skipped };
}
