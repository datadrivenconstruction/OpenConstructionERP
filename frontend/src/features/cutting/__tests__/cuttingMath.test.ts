// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  colourForRef,
  groupBars,
  nextRef,
  oversizePieces,
  parsePastedPieces,
  pieceCount,
  positiveDecimal,
  toNum,
  uniqueRefs,
} from '../cuttingMath';
import type { CuttingStock, LinearBar } from '../api';

const stock = (ref: string, length: string, width: string | null = null): CuttingStock => ({
  ref,
  label: '',
  length_mm: length,
  width_mm: width,
  unit_cost: '0',
  available: null,
  is_offcut: false,
  inventory_item_id: null,
});

describe('cuttingMath', () => {
  it('reads decimal strings with a comma or a dot', () => {
    expect(toNum('12,5')).toBe(12.5);
    expect(toNum('abc')).toBe(0);
    expect(positiveDecimal('3000,5')).toBe('3000.5');
    expect(positiveDecimal('-1')).toBeNull();
    expect(positiveDecimal('0')).toBeNull();
  });

  it('parses tab separated spreadsheet rows and skips a header', () => {
    const rows = parsePastedPieces('Mark\tLength\tQty\nA1\t4000\t5\tColumn bar\nA2\t3000\t2', 'linear');
    expect(rows).toEqual([
      { ref: 'A1', label: 'Column bar', length_mm: '4000', width_mm: null, quantity: 5, rotatable: true },
      { ref: 'A2', label: '', length_mm: '3000', width_mm: null, quantity: 2, rotatable: true },
    ]);
  });

  it('parses sheet rows with a width column', () => {
    const rows = parsePastedPieces('P1;1200;600;2;Door leaf', 'sheet');
    expect(rows[0]).toMatchObject({ ref: 'P1', length_mm: '1200', width_mm: '600', quantity: 2, label: 'Door leaf' });
  });

  it('makes refs unique and finds the next free ref', () => {
    const rows = uniqueRefs([{ ref: 'A' }, { ref: 'A' }, { ref: 'B' }]);
    expect(rows.map((r) => r.ref)).toEqual(['A', 'A.2', 'B']);
    expect(nextRef([{ ref: 'P1' }, { ref: 'P3' }], 'P')).toBe('P4');
  });

  it('flags pieces that fit no stock after trim, allowing sheet rotation', () => {
    const pieces = [
      { ref: 'OK', label: '', length_mm: '5900', width_mm: null, quantity: 1, rotatable: true },
      { ref: 'LONG', label: '', length_mm: '6000', width_mm: null, quantity: 1, rotatable: true },
    ];
    expect(oversizePieces('linear', pieces, [stock('S', '6000')], '50')).toEqual(['LONG']);
    const sheetPieces = [{ ref: 'T', label: '', length_mm: '1000', width_mm: '2000', quantity: 1, rotatable: true }];
    expect(oversizePieces('sheet', sheetPieces, [stock('S', '2500', '1250')], '0')).toEqual([]);
    expect(pieceCount(pieces)).toBe(2);
  });

  it('gives one mark one colour on every call', () => {
    expect(colourForRef('A1')).toBe(colourForRef('A1'));
    expect(colourForRef('A1')).toMatch(/^hsl\(\d+ 62% 62%\)$/);
  });

  it('groups identical bar patterns', () => {
    const bar = (index: number, cuts: string[]): LinearBar => ({
      index,
      stock_ref: 'S',
      stock_label: '',
      length_mm: '6000',
      is_offcut: false,
      inventory_item_id: null,
      cost: '0',
      cuts: cuts.map((c, i) => ({ ref: c, label: '', length_mm: '2000', offset_mm: String(i * 2000) })),
      remnant_mm: '0',
      offcut_mm: '0',
      scrap_mm: '0',
    });
    const groups = groupBars([bar(1, ['A', 'A', 'B']), bar(2, ['A', 'A', 'B']), bar(3, ['C'])]);
    expect(groups.map((g) => g.count)).toEqual([2, 1]);
  });
});
