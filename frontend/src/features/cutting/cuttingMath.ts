// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP​‌‍⁠​‌‍⁠​‌‍⁠​‌‍⁠
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers for the cutting page: pasting a cut list from a spreadsheet,
 * stable colours per piece mark, and the numbers the diagrams scale by.
 * Values stay decimal strings until a drawing needs a coordinate.
 */

import type { CuttingPiece, CuttingStock, JobKind, LinearBar, SheetLayout } from './api';

/** A decimal string or number as a finite number, or 0. Accepts a comma as decimal separator. */
export function toNum(value: string | number | null | undefined): number {
  if (value === null || value === undefined) return 0;
  const n = typeof value === 'number' ? value : Number(String(value).trim().replace(',', '.'));
  return Number.isFinite(n) ? n : 0;
}

/** A positive decimal string, normalised to a dot, or null when it is not one. */
export function positiveDecimal(value: string): string | null {
  const text = value.trim().replace(',', '.');
  if (!/^\d+(\.\d+)?$/.test(text)) return null;
  return Number(text) > 0 ? text : null;
}

const SPLIT = /\t|;|\s{2,}|,(?=\s*\S)/;

/**
 * Rows pasted from a spreadsheet: `mark length [width] quantity [label]`.
 * Columns may be tab, semicolon or comma separated. A first row without a
 * number in the length column is taken as a header and skipped.
 */
export function parsePastedPieces(text: string, kind: JobKind): CuttingPiece[] {
  const out: CuttingPiece[] = [];
  const lines = text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  for (const line of lines) {
    const cells = (line.includes('\t') || line.includes(';') ? line.split(/\t|;/) : line.split(SPLIT)).map((c) =>
      c.trim(),
    );
    const want = kind === 'sheet' ? 4 : 3;
    if (cells.length < want - 1) continue;
    const length = positiveDecimal(cells[1] ?? '');
    if (!length) continue;
    let width: string | null = null;
    let qtyCell = cells[2];
    let labelIdx = 3;
    if (kind === 'sheet') {
      width = positiveDecimal(cells[2] ?? '');
      if (!width) continue;
      qtyCell = cells[3];
      labelIdx = 4;
    }
    const qty = qtyCell === undefined || qtyCell === '' ? 1 : Math.ceil(toNum(qtyCell));
    if (!Number.isFinite(qty) || qty < 1) continue;
    out.push({
      ref: (cells[0] || `P${out.length + 1}`).slice(0, 64),
      label: (cells.slice(labelIdx).join(' ') || '').slice(0, 255),
      length_mm: length,
      width_mm: width,
      quantity: Math.min(qty, 100000),
      rotatable: true,
    });
  }
  return uniqueRefs(out);
}

/** Refs must be unique within a job; later duplicates get a numeric suffix. */
export function uniqueRefs<T extends { ref: string }>(rows: T[]): T[] {
  const seen = new Map<string, number>();
  return rows.map((row) => {
    const base = row.ref.trim() || 'P';
    const n = seen.get(base) ?? 0;
    seen.set(base, n + 1);
    return n === 0 ? { ...row, ref: base } : { ...row, ref: `${base}.${n + 1}`.slice(0, 64) };
  });
}

/** The next free ref with a prefix: P1, P2, ... */
export function nextRef(rows: { ref: string }[], prefix: string): string {
  const taken = new Set(rows.map((r) => r.ref));
  let i = rows.length + 1;
  while (taken.has(`${prefix}${i}`)) i += 1;
  return `${prefix}${i}`;
}

/** A stable, readable fill colour per piece mark (same mark, same colour, every render). */
export function colourForRef(ref: string): string {
  let hash = 0;
  for (let i = 0; i < ref.length; i += 1) hash = (hash * 31 + ref.charCodeAt(i)) | 0;
  const hue = Math.abs(hash) % 360;
  return `hsl(${hue} 62% 62%)`;
}

/** Total demanded pieces of a cut list. */
export function pieceCount(pieces: CuttingPiece[]): number {
  return pieces.reduce((sum, p) => sum + (Number.isFinite(p.quantity) ? p.quantity : 0), 0);
}

/** Pieces that fit no stock entry after trim (mirrors the backend rule, for instant feedback). */
export function oversizePieces(kind: JobKind, pieces: CuttingPiece[], stocks: CuttingStock[], trimMm: string): string[] {
  if (stocks.length === 0) return [];
  const trim = toNum(trimMm);
  return pieces
    .filter((p) => {
      const pl = toNum(p.length_mm);
      const pw = toNum(p.width_mm);
      return !stocks.some((s) => {
        if (kind === 'sheet') {
          const sl = toNum(s.length_mm) - 2 * trim;
          const sw = toNum(s.width_mm) - 2 * trim;
          return (pl <= sl && pw <= sw) || (pw <= sl && pl <= sw);
        }
        return pl <= toNum(s.length_mm) - trim;
      });
    })
    .map((p) => p.ref);
}

/** Longest bar in a linear layout, so every bar is drawn to one scale. */
export function longestBar(bars: LinearBar[]): number {
  return bars.reduce((max, b) => Math.max(max, toNum(b.length_mm)), 0);
}

/** Largest sheet side in a layout, so every sheet is drawn to one scale. */
export function largestSheetSide(sheets: SheetLayout[]): number {
  return sheets.reduce((max, s) => Math.max(max, toNum(s.length_mm), toNum(s.width_mm)), 0);
}

/** Group identical bar layouts (same stock, same cuts) so a plan of 40 bars reads as a few patterns. */
export function groupBars(bars: LinearBar[]): { bar: LinearBar; count: number }[] {
  const groups = new Map<string, { bar: LinearBar; count: number }>();
  for (const bar of bars) {
    const key = `${bar.stock_ref}|${bar.cuts.map((c) => `${c.ref}:${c.length_mm}`).join(',')}`;
    const found = groups.get(key);
    if (found) found.count += 1;
    else groups.set(key, { bar, count: 1 });
  }
  return [...groups.values()];
}
