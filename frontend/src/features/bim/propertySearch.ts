// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure helpers behind the BIM property search panel.
 *
 * The panel queries the model's Parquet sidecar, whose rows are keyed by the
 * CAD element id (the Revit ElementId for a DDC export, the same value the
 * backend stores as ``mesh_ref``). The 3D viewer keys its meshes by the
 * element's database id, so a Parquet hit has to be translated before it can
 * isolate anything. These helpers do that translation and pick the columns a
 * query needs, with no React in the way so they can be tested directly.
 */

import { parseDecimalInput } from '@/shared/lib/parseDecimal';
import type { BIMDataframeColumn, BIMDataframeFilter } from './api';

/** Element fields the id translation reads. */
export interface PropertySearchElement {
  id: string;
  mesh_ref?: string | null;
  stable_id?: string | null;
}

/** Column names a sidecar may use for the CAD element id, most common first.
 *  Mirrors the probe in ``BIMHubService.ensure_element``. ``stable_id`` comes
 *  last: a sidecar rebuilt by the Parquet retry carries no other id. The
 *  server's ``dataframe_store._ID_COLUMNS`` keeps the same list. */
export const PARQUET_ID_COLUMNS = [
  'id',
  'Id',
  'ID',
  'ElementId',
  'Element ID',
  'element_id',
  'stable_id',
] as const;

/** The id column this sidecar carries, or null when it has none. */
export function pickIdColumn(schema: readonly BIMDataframeColumn[]): string | null {
  const names = new Set(schema.map((c) => c.name));
  return PARQUET_ID_COLUMNS.find((c) => names.has(c)) ?? null;
}

/** What the user sees for a column: the original header when the sidecar
 *  stored one, otherwise the key itself. */
export function columnLabel(column: BIMDataframeColumn): string {
  const label = column.label?.trim();
  return label ? label : column.name;
}

/** The comparators that need a number rather than text. */
export function isNumericSearchOp(op: BIMDataframeFilter['op']): boolean {
  return op === '>' || op === '>=' || op === '<' || op === '<=';
}

/** A typed number as the search will use it. */
export interface SearchNumber {
  value: number;
  /** The text also reads as a different number in another convention
   *  ("1.500" is 1500 in Italian and 1.5 in English), so the panel says
   *  which one it used. */
  ambiguous: boolean;
}

/** One separator, once, followed by exactly three digits: "1.500", "1,500". */
const AMBIGUOUS_RE = /^([+\-−]?)([1-9]\d{0,2})([.,])(\d{3})$/;

function numberSeparators(locale: string): { group: string; decimal: string } {
  try {
    const parts = new Intl.NumberFormat(locale).formatToParts(1234567.8);
    return {
      group: parts.find((p) => p.type === 'group')?.value ?? ',',
      decimal: parts.find((p) => p.type === 'decimal')?.value ?? '.',
    };
  } catch {
    return { group: ',', decimal: '.' };
  }
}

/**
 * Read a typed number in the reader's number convention.
 *
 * Forms that read one way only go through the product's shared grammar
 * (`parseDecimalInput`): "1.234,56" and "1,234.56" are both 1234.56, "12,5" is
 * 12.5, "1.234.567" is grouped. Only "1.500" / "1,500" can mean two numbers,
 * and there the locale decides: its decimal separator reads as a decimal, its
 * group separator as thousands. Returns ``null`` for anything that is not a
 * number, so the panel refuses it instead of sending text to a ">".
 */
export function parseSearchNumber(raw: string, locale: string): SearchNumber | null {
  const text = raw.trim();
  const m = AMBIGUOUS_RE.exec(text);
  if (m) {
    const sign = m[1] ?? '';
    const whole = m[2] ?? '';
    const sep = m[3] ?? '';
    const tail = m[4] ?? '';
    const { group, decimal } = numberSeparators(locale);
    // A separator the locale uses for neither falls back to the shared
    // grammar: comma groups, dot is a decimal.
    const grouped = sep === group ? true : sep === decimal ? false : sep === ',';
    const magnitude = grouped ? Number(whole + tail) : Number(`${whole}.${tail}`);
    return { value: sign === '' || sign === '+' ? magnitude : -magnitude, ambiguous: true };
  }
  const value = parseDecimalInput(text);
  return value === null ? null : { value, ambiguous: false };
}

/** A number written so it cannot be misread: no grouping, the locale's own
 *  decimal mark, every significant digit. */
export function formatReadAs(value: number, locale: string): string {
  try {
    return new Intl.NumberFormat(locale, { useGrouping: false, maximumFractionDigits: 20 }).format(value);
  } catch {
    return String(value);
  }
}

/** Numeric comparators send a number read in the reader's convention;
 *  everything else sends the typed text. Text that is not a number goes as
 *  text, and the panel refuses it before it gets this far. */
export function coerceSearchValue(
  op: BIMDataframeFilter['op'],
  raw: string,
  locale = 'en',
): string | number {
  if (isNumericSearchOp(op)) {
    const parsed = parseSearchNumber(raw, locale);
    if (parsed) return parsed.value;
  }
  return raw;
}

export interface MappedSearchHits {
  /** Database element ids, ready for the viewer's isolation set. */
  elementIds: string[];
  /** Parquet rows that matched the filter. */
  rowCount: number;
  /** Matched rows with no loaded element behind them (no geometry, or the
   *  element list is still loading). */
  unmatchedCount: number;
}

/**
 * Translate Parquet hits into the database ids the viewer isolates by.
 *
 * A row's id is looked up as ``mesh_ref`` first (DDC exports), then as
 * ``stable_id`` (rebuilt sidecars and IFC GlobalIds), then as the database id
 * itself. When the row also carries a ``stable_id`` column, that is tried as a
 * last resort. Each element is reported once, in row order.
 */
export function mapSearchHitsToElementIds(
  rows: readonly Record<string, unknown>[],
  idColumn: string,
  elements: readonly PropertySearchElement[],
): MappedSearchHits {
  const byMeshRef = new Map<string, string>();
  const byStableId = new Map<string, string>();
  const byId = new Map<string, string>();
  for (const el of elements) {
    if (el.mesh_ref) byMeshRef.set(String(el.mesh_ref), el.id);
    if (el.stable_id) byStableId.set(String(el.stable_id), el.id);
    byId.set(String(el.id), el.id);
  }

  const seen = new Set<string>();
  const elementIds: string[] = [];
  let unmatchedCount = 0;
  for (const row of rows) {
    const raw = row[idColumn];
    const key = raw === null || raw === undefined ? '' : String(raw).trim();
    const stable = row.stable_id === null || row.stable_id === undefined ? '' : String(row.stable_id).trim();
    const hit =
      (key && (byMeshRef.get(key) ?? byStableId.get(key) ?? byId.get(key))) ||
      (stable && byStableId.get(stable)) ||
      undefined;
    if (!hit) {
      unmatchedCount += 1;
      continue;
    }
    if (!seen.has(hit)) {
      seen.add(hit);
      elementIds.push(hit);
    }
  }
  return { elementIds, rowCount: rows.length, unmatchedCount };
}
