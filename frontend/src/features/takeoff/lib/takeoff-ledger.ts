// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Pure ledger helpers: sort, filter, subtotals, grand totals, and CSV
 * serialization for the measurement ledger view.
 *
 * Separated from the React component so we can unit-test the math
 * without mounting anything.  Mirrors the shape of
 * `features/takeoff/lib/takeoff-types.ts::Measurement`.
 */

import type { Measurement, MeasurementType } from './takeoff-types';
import { ANNOTATION_TYPES } from './takeoff-groups';
import type { MeasurementSystem } from '@/stores/usePreferencesStore';
import { convertQuantity } from './takeoff-display-units';
import { effectiveQuantity, effectiveUnit, isWallMeasurement, reportingType } from './takeoff-quantity';
import { fmtFixed } from '@/shared/lib/formatters';

/** Sortable column keys exposed by the ledger table. */
export type LedgerSortColumn =
  | 'ordinal'
  | 'type'
  | 'annotation'
  | 'group'
  | 'value'
  | 'unit'
  | 'page';

export type SortDirection = 'asc' | 'desc';

export interface LedgerFilter {
  /** Allowed group names — empty set means "allow all". */
  groups: Set<string>;
  /** Allowed measurement types — empty set means "allow all". */
  types: Set<MeasurementType>;
  /** Allowed page numbers — empty set means "allow all". */
  pages: Set<number>;
}

/** A decorated measurement row with the sequence number used for display. */
export interface LedgerRow {
  ordinal: number;
  measurement: Measurement;
}

/** Subtotal row rendered after each group's rows. */
export interface GroupSubtotal {
  group: string;
  /** Totals keyed by canonical unit label (the unit as stored). */
  totals: Record<string, number>;
  /** Count of measurements in the group (annotation types counted). */
  count: number;
  /** Per unit key: true while every contribution came from count-type
   *  measurements — that subtotal is whole pieces (K-14), not a figure. */
  countOnly: Record<string, boolean>;
}

/** Grand total row rendered at the footer, keyed by measurement type. */
export interface TypeGrandTotal {
  type: MeasurementType;
  unit: string;
  total: number;
  count: number;
}

/**
 * Apply the current filter to a list of measurements.  Empty sets are
 * treated as "no restriction on that dimension".
 */
export function filterMeasurements(
  measurements: Measurement[],
  filter: LedgerFilter,
): Measurement[] {
  return measurements.filter((m) => {
    if (filter.groups.size > 0 && !filter.groups.has(m.group || 'General')) {
      return false;
    }
    if (filter.types.size > 0 && !filter.types.has(m.type)) return false;
    if (filter.pages.size > 0 && !filter.pages.has(m.page)) return false;
    return true;
  });
}

/**
 * Sort measurements by the requested column + direction.  Returns a new
 * array; does not mutate input.  Stable-ish secondary sort by page,
 * then by annotation, to keep rows deterministic when the primary key
 * ties.
 */
export function sortMeasurements(
  measurements: Measurement[],
  column: LedgerSortColumn,
  direction: SortDirection,
): Measurement[] {
  const mult = direction === 'asc' ? 1 : -1;
  const out = [...measurements];
  out.sort((a, b) => {
    const primary = compareByColumn(a, b, column);
    if (primary !== 0) return primary * mult;
    // Tie-breaker: page asc, annotation asc, id asc — gives stable order.
    if (a.page !== b.page) return a.page - b.page;
    const aa = a.annotation || '';
    const bb = b.annotation || '';
    if (aa !== bb) return aa.localeCompare(bb);
    return a.id.localeCompare(b.id);
  });
  return out;
}

function compareByColumn(
  a: Measurement,
  b: Measurement,
  column: LedgerSortColumn,
): number {
  switch (column) {
    case 'ordinal':
      // Natural id order — treated as a proxy for insertion order.
      return a.id.localeCompare(b.id);
    case 'type':
      return a.type.localeCompare(b.type);
    case 'annotation':
      return (a.annotation || '').localeCompare(b.annotation || '');
    case 'group':
      return (a.group || 'General').localeCompare(b.group || 'General');
    case 'value':
      // Sort by the figure the column shows (wall area, wastage, deduction sign).
      return effectiveQuantity(a) - effectiveQuantity(b);
    case 'unit':
      return (effectiveUnit(a) || '').localeCompare(effectiveUnit(b) || '');
    case 'page':
      return a.page - b.page;
  }
}

/**
 * Assign display ordinals (1-based) to the measurements in their
 * currently-sorted order.  This is purely cosmetic — the ordinal
 * reflects row position in the ledger, not a stable measurement id.
 */
export function withOrdinals(measurements: Measurement[]): LedgerRow[] {
  return measurements.map((measurement, index) => ({
    ordinal: index + 1,
    measurement,
  }));
}

/**
 * Compute per-group subtotals, keyed by unit so we can keep m + m² + m³
 * totals distinct.  Annotation types are skipped from numeric totals
 * (they have no meaningful "quantity") but still counted.
 */
export function groupSubtotals(measurements: Measurement[]): GroupSubtotal[] {
  const byGroup = new Map<string, GroupSubtotal>();
  for (const m of measurements) {
    const group = m.group || 'General';
    let entry = byGroup.get(group);
    if (!entry) {
      entry = { group, totals: {}, count: 0, countOnly: {} };
      byGroup.set(group, entry);
    }
    entry.count += 1;
    if (!ANNOTATION_TYPES.has(m.type)) {
      // Keyed by the REPORTED unit (a wall reports m², not m) so m + m2 + m3
      // stay distinct and a wall area never sums into a length.
      const unit = effectiveUnit(m) || '';
      // Effective quantity folds slope / wastage / typical-multiplier and the
      // opening-deduction sign (net area = gross - openings).
      entry.totals[unit] = (entry.totals[unit] ?? 0) + effectiveQuantity(m);
      entry.countOnly[unit] = (entry.countOnly[unit] ?? true) && m.type === 'count';
    }
  }
  return Array.from(byGroup.values()).sort((a, b) =>
    a.group.localeCompare(b.group),
  );
}

/**
 * Compute grand totals per measurement type.  These appear in the
 * ledger footer — one row per distinct type present.
 */
export function typeGrandTotals(measurements: Measurement[]): TypeGrandTotal[] {
  const byType = new Map<MeasurementType, TypeGrandTotal>();
  for (const m of measurements) {
    if (ANNOTATION_TYPES.has(m.type)) continue;
    // A wall (linear run with a height) reports area, so it totals with areas.
    const type = reportingType(m);
    const unit = effectiveUnit(m);
    let entry = byType.get(type);
    if (!entry) {
      entry = { type, unit: unit || '', total: 0, count: 0 };
      byType.set(type, entry);
    }
    // Effective quantity folds slope / wastage / typical-multiplier and the
    // opening-deduction sign (net = gross - openings) into the grand total.
    entry.total += effectiveQuantity(m);
    entry.count += 1;
    // Prefer a non-empty unit string if we have one.
    if (!entry.unit && unit) entry.unit = unit;
  }
  return Array.from(byType.values()).sort((a, b) =>
    a.type.localeCompare(b.type),
  );
}

/**
 * Build a CSV string from a filtered + sorted ledger, including
 * subtotal rows per group and grand-total rows per type.  Output is
 * RFC-4180-ish: comma separator, quoted strings, doubled quotes inside.
 *
 * `system` converts the canonical-metric values + unit labels to the
 * user's preferred measurement system at the export boundary (D-TKC-016
 * keeps storage metric). Defaults to `'metric'`, which is a pass-through
 * so the emitted numbers + units are identical to before this seam.
 */
export function ledgerToCsv(
  measurements: Measurement[],
  system: MeasurementSystem = 'metric',
): string {
  const header = '#,Type,Annotation,Group,Value,Unit,Page';
  const rows: string[] = [header];

  const ordered = withOrdinals(measurements);
  // Group rows together so subtotals land after each block.
  const byGroup = new Map<string, LedgerRow[]>();
  for (const row of ordered) {
    const g = row.measurement.group || 'General';
    if (!byGroup.has(g)) byGroup.set(g, []);
    byGroup.get(g)!.push(row);
  }

  for (const [group, groupRows] of byGroup.entries()) {
    for (const { ordinal, measurement } of groupRows) {
      // Reported (effective) quantity: folds slope / wastage / typical-
      // multiplier and the opening-deduction sign, so a void still prints
      // NEGATIVE and reconciles with the net subtotal below, and a factored
      // row exports the same number the ledger shows.
      const signedValue = effectiveQuantity(measurement);
      const typeLabel = measurement.isDeduction
        ? `${measurement.type} (deduction)`
        : isWallMeasurement(measurement)
          ? `${measurement.type} (wall)`
          : measurement.type;
      const disp = convertQuantity(signedValue, effectiveUnit(measurement) || '', system);
      rows.push(
        [
          String(ordinal),
          escapeCsv(typeLabel),
          escapeCsv(measurement.annotation || ''),
          escapeCsv(group),
          formatNumber(disp.value),
          escapeCsv(disp.unit),
          String(measurement.page),
        ].join(','),
      );
    }
    // Subtotal(s) per group — one line per unique unit present.
    const subs = groupSubtotals(groupRows.map((r) => r.measurement))[0];
    if (subs) {
      for (const [unit, total] of Object.entries(subs.totals)) {
        const disp = convertQuantity(total, unit, system);
        rows.push(
          [
            '',
            'subtotal',
            escapeCsv(`${group} subtotal`),
            escapeCsv(group),
            formatNumber(disp.value),
            escapeCsv(disp.unit),
            '',
          ].join(','),
        );
      }
    }
  }

  for (const gt of typeGrandTotals(measurements)) {
    const disp = convertQuantity(gt.total, gt.unit, system);
    rows.push(
      [
        '',
        'grand_total',
        escapeCsv(`Total ${gt.type}`),
        '',
        formatNumber(disp.value),
        escapeCsv(disp.unit),
        '',
      ].join(','),
    );
  }

  return rows.join('\n');
}

function escapeCsv(value: string): string {
  return `"${value.replace(/"/g, '""')}"`;
}

function formatNumber(value: number): string {
  // Match the same precision rules used by formatMeasurement — 3 dp for
  // tiny values, 2 dp for normal, 1 dp for large.  Keeps CSV readable
  // in Excel without scientific notation.
  if (value === 0) return '0';
  const abs = Math.abs(value);
  if (abs < 1) return fmtFixed(value, 3);
  if (abs < 100) return fmtFixed(value, 2);
  return fmtFixed(value, 1);
}

/** Convert a filter payload to the union of unique tokens found in the
 *  provided measurement list — used to populate multi-select UI. */
export function uniqueFilterOptions(measurements: Measurement[]): {
  groups: string[];
  types: MeasurementType[];
  pages: number[];
} {
  const groups = new Set<string>();
  const types = new Set<MeasurementType>();
  const pages = new Set<number>();
  for (const m of measurements) {
    groups.add(m.group || 'General');
    types.add(m.type);
    pages.add(m.page);
  }
  return {
    groups: Array.from(groups).sort(),
    types: Array.from(types).sort() as MeasurementType[],
    pages: Array.from(pages).sort((a, b) => a - b),
  };
}

/** Create an empty (no-restriction) filter. */
export function emptyFilter(): LedgerFilter {
  return { groups: new Set(), types: new Set(), pages: new Set() };
}
