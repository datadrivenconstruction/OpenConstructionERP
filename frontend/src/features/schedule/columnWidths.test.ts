// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
/**
 * The arithmetic behind the activity grid's resizable columns.
 *
 * These are the rules a drag, a window resize and an auto-fit all go through,
 * tested without a DOM: clamping to a column's own minimum, fitting a set of
 * columns to a wrap that is too narrow (and one that is not), auto-fitting to
 * the widest cell, and the localStorage round-trip that makes a width survive
 * a reload.
 */
import { describe, expect, it, beforeEach } from 'vitest';
import {
  autoFitWidth,
  clampWidth,
  clearWidths,
  fitColumnWidths,
  loadWidths,
  resolveWidths,
  saveWidths,
  totalWidth,
  widthsStorageKey,
  MAX_COLUMN_WIDTH,
  type ColumnSpec,
} from './columnWidths';

const SPECS: ColumnSpec[] = [
  { key: 'wbs', min: 50, def: 80 },
  { key: 'name', min: 100, def: 200 },
  { key: 'end', min: 60, def: 120 },
];

describe('clampWidth', () => {
  it('never returns less than the column minimum', () => {
    expect(clampWidth(SPECS[0]!, 10)).toBe(50);
  });

  it('never returns more than the hard maximum', () => {
    expect(clampWidth(SPECS[1]!, 5000)).toBe(MAX_COLUMN_WIDTH);
  });

  it('falls back to the default rather than storing a NaN', () => {
    expect(clampWidth(SPECS[1]!, Number.NaN)).toBe(200);
  });
});

describe('resolveWidths', () => {
  it('uses the default for a column nothing is stored for', () => {
    expect(resolveWidths(SPECS, { name: 260 })).toEqual({ wbs: 80, name: 260, end: 120 });
  });

  it('clamps a stored width that is under the minimum', () => {
    expect(resolveWidths(SPECS, { wbs: 4 }).wbs).toBe(50);
  });
});

describe('fitColumnWidths', () => {
  it('gives spare width to the grow column', () => {
    const out = fitColumnWidths(SPECS, resolveWidths(SPECS, null), 501, 'name');
    // 500 target - (80 + 120) fixed = 300 for the name column.
    expect(out).toEqual({ wbs: 80, name: 300, end: 120 });
    expect(totalWidth(SPECS, out)).toBe(500);
  });

  it('leaves the columns alone when the user has set them (no expand)', () => {
    const out = fitColumnWidths(SPECS, resolveWidths(SPECS, null), 900, 'name', { expand: false });
    expect(out).toEqual({ wbs: 80, name: 200, end: 120 });
  });

  it('leaves the user’s own widths alone and lets the wrap scroll (no shrink)', () => {
    const out = fitColumnWidths(SPECS, { wbs: 80, name: 400, end: 120 }, 300, 'name', {
      expand: false,
      shrink: false,
    });
    expect(out).toEqual({ wbs: 80, name: 400, end: 120 });
  });

  it('applies the minimum as a floor even when it is not fitting anything', () => {
    const out = fitColumnWidths(SPECS, { wbs: 10, name: 400, end: 120 }, 300, 'name', {
      expand: false,
      shrink: false,
    });
    expect(out.wbs).toBe(50);
  });

  it('shrinks the other columns pro-rata before the grow column', () => {
    const out = fitColumnWidths(SPECS, { wbs: 80, name: 200, end: 120 }, 351, 'name');
    // Needs 50px back; wbs has 30 of slack and end has 60, so they give
    // 50 * 30/90 and 50 * 60/90 and the name column is untouched.
    expect(out.name).toBe(200);
    expect(out.wbs).toBe(63);
    expect(out.end).toBe(87);
  });

  it('takes the rest off the grow column once the others are at their floor', () => {
    const out = fitColumnWidths(SPECS, { wbs: 80, name: 200, end: 120 }, 251, 'name');
    expect(out.wbs).toBe(50);
    expect(out.end).toBe(60);
    expect(out.name).toBe(140);
    expect(totalWidth(SPECS, out)).toBe(250);
  });

  it('stops at every minimum and lets the wrap scroll rather than clipping', () => {
    const out = fitColumnWidths(SPECS, { wbs: 80, name: 200, end: 120 }, 100, 'name');
    expect(out).toEqual({ wbs: 50, name: 100, end: 60 });
    expect(totalWidth(SPECS, out)).toBe(210);
  });

  it('is a no-op while the wrap is hidden and measures zero', () => {
    const widths = { wbs: 80, name: 200, end: 120 };
    expect(fitColumnWidths(SPECS, widths, 0, 'name')).toEqual(widths);
  });

  it('does not mutate the widths it was handed', () => {
    const widths = { wbs: 80, name: 200, end: 120 };
    fitColumnWidths(SPECS, widths, 300, 'name');
    expect(widths).toEqual({ wbs: 80, name: 200, end: 120 });
  });
});

describe('autoFitWidth', () => {
  // A stand-in for the canvas measurer: eight pixels per character.
  const measure = (s: string) => s.length * 8;

  it('fits the widest string, plus the cell chrome', () => {
    const w = autoFitWidth(['ab', 'abcdefghij'], measure, { min: 40 });
    expect(w).toBe(10 * 8 + 26);
  });

  it('never drops below the column minimum', () => {
    expect(autoFitWidth(['a'], measure, { min: 120 })).toBe(120);
  });

  it('adds the per-column furniture (a badge, a select arrow)', () => {
    expect(autoFitWidth(['abcd'], measure, { min: 0, extra: 30 })).toBe(4 * 8 + 26 + 30);
  });

  it('caps a pathologically long cell instead of making a 2000px column', () => {
    expect(autoFitWidth(['x'.repeat(500)], measure, { min: 40 })).toBe(MAX_COLUMN_WIDTH);
  });

  it('reads an empty column as its minimum, not as zero', () => {
    expect(autoFitWidth([], measure, { min: 90 })).toBe(90);
  });
});

describe('persistence', () => {
  beforeEach(() => {
    clearWidths('sched-1');
  });

  it('round-trips widths through localStorage under a schedule-scoped key', () => {
    saveWidths('sched-1', { name: 320, wbs: 64 });
    expect(window.localStorage.getItem(widthsStorageKey('sched-1'))).toBeTruthy();
    expect(loadWidths('sched-1')).toEqual({ name: 320, wbs: 64 });
  });

  it('keeps one schedule’s widths out of another’s', () => {
    saveWidths('sched-1', { name: 320 });
    expect(loadWidths('sched-2')).toBeNull();
    clearWidths('sched-2');
  });

  it('reads nothing stored as null so the defaults apply', () => {
    expect(loadWidths('sched-1')).toBeNull();
  });

  it('treats a corrupt stored value as nothing stored rather than throwing', () => {
    window.localStorage.setItem(widthsStorageKey('sched-1'), '{not json');
    expect(loadWidths('sched-1')).toBeNull();
  });

  it('drops non-numeric entries instead of poisoning a column width', () => {
    window.localStorage.setItem(
      widthsStorageKey('sched-1'),
      JSON.stringify({ name: 300, wbs: 'wide' }),
    );
    expect(loadWidths('sched-1')).toEqual({ name: 300 });
  });

  it('clears the stored widths outright', () => {
    saveWidths('sched-1', { name: 320 });
    clearWidths('sched-1');
    expect(loadWidths('sched-1')).toBeNull();
  });
});
