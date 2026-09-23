// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * A row nobody has typed into is not a line of the bill.
 *
 * "Add Position" creates the row on the server immediately and opens its
 * description cell, so a bill legitimately holds rows carrying nothing yet.
 * The server leaves them out of its position counts and out of every export
 * it renders; the browser still builds its own PDF from the same data and has
 * to reach the same answer, or the same bill downloads with a different number
 * of lines depending on which button the estimator pressed. Excel is the
 * server's own export now, so only the shared filter is tested here.
 *
 * The assertions carry a denominator on purpose: "the blank row is absent" is
 * satisfied by an export containing nothing at all, so every case below names
 * the priced row that must still be there.
 */

import { describe, it, expect } from 'vitest';
import { isEmptyPosition, exportablePositions, type Position } from './api';

/* ── Fixtures ─────────────────────────────────────────────────────────── */

function pos(over: Partial<Position> = {}): Position {
  return {
    id: `p-${Math.random().toString(36).slice(2, 8)}`,
    boq_id: 'boq-1',
    parent_id: null,
    ordinal: '0010',
    description: 'RC wall C30/37',
    unit: 'm3',
    quantity: 10,
    unit_rate: 185,
    total: 1850,
    classification: {},
    source: 'manual',
    confidence: null,
    sort_order: 10,
    validation_status: 'valid',
    metadata: {},
    ...over,
  };
}

/** The row exactly as `handleAddPosition` posts it, field for field. */
function untouchedRow(over: Partial<Position> = {}): Position {
  return pos({
    ordinal: '0020',
    description: '',
    unit: 'm2',
    quantity: 0,
    unit_rate: 0,
    total: 0,
    sort_order: 20,
    ...over,
  });
}

/* ── The predicate ────────────────────────────────────────────────────── */

describe('isEmptyPosition', () => {
  it('reads the row the editor creates as empty', () => {
    expect(isEmptyPosition(untouchedRow())).toBe(true);
  });

  it('stops calling it empty once a description is typed', () => {
    expect(isEmptyPosition(untouchedRow({ description: 'Excavate to reduced level' }))).toBe(false);
  });

  it('stops calling it empty once a quantity is entered', () => {
    // The estimator who measures before wording the item must not have that
    // measurement dropped from the file they then send out.
    expect(isEmptyPosition(untouchedRow({ quantity: 120 }))).toBe(false);
  });

  // Both spellings a section header is stored with. A header carries no
  // quantity by definition and often no description either, so without the
  // section guard the filter would strip the bill's structure.
  it.each(['', 'section', 'SECTION', ' '])('never treats a header (unit %p) as empty', (unit) => {
    expect(isEmptyPosition(pos({ unit, description: '', quantity: 0, unit_rate: 0, total: 0 }))).toBe(
      false,
    );
  });

  it('is not satisfied by a reader that calls everything empty', () => {
    expect(isEmptyPosition(pos())).toBe(false);
  });
});

describe('exportablePositions', () => {
  it('keeps the priced line and the header, drops only the blank row', () => {
    const header = pos({ ordinal: '01', description: 'Earthworks', unit: '', quantity: 0, unit_rate: 0, total: 0 });
    const priced = pos({ ordinal: '01.10' });
    const kept = exportablePositions([header, priced, untouchedRow({ ordinal: '01.20' })]);

    expect(kept.map((p) => p.ordinal)).toEqual(['01', '01.10']);
  });
});
