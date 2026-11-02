// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, it, expect } from 'vitest';
import {
  currentLevels,
  documentOrder,
  isNumbering,
  isOrdinalPrefix,
  ordinalDepth,
  recurringLines,
  suggestLevels,
} from './boqStructure';

const row = (id: string, ordinal: string, unit = 'm3', extra: Partial<{ parent_id: string | null; sort_order: number; quantity: number; unit_rate: number; description: string }> = {}) => ({
  id,
  ordinal,
  unit,
  parent_id: null,
  sort_order: 0,
  quantity: unit === 'section' ? 0 : 1,
  unit_rate: 0,
  description: id,
  ...extra,
});

describe('numbering', () => {
  it.each([
    ['1', 1],
    ['1.2', 2],
    ['01.02.003', 3],
    ['A.1', 2],
    ['IV.3', 2],
    ['2.', 1],
    ['Béton', 0],
    ['m3', 0],
    ['', 0],
  ])('%s has depth %s', (ord, depth) => {
    expect(ordinalDepth(ord)).toBe(depth);
  });

  it('reads chapter prefixes segment by segment', () => {
    expect(isOrdinalPrefix('1.2', '1.2.3')).toBe(true);
    expect(isOrdinalPrefix('1.2', '1.20')).toBe(false);
    expect(isOrdinalPrefix('1', '1')).toBe(false);
    expect(isNumbering('Gros oeuvre')).toBe(false);
  });
});

describe('levels', () => {
  it('walks the tree in document order and reports section depth', () => {
    const rows = [
      row('line', '1.1.1', 'm3', { parent_id: 'sub', sort_order: 0 }),
      row('sub', '1.1', 'section', { parent_id: 'chap', sort_order: 0 }),
      row('chap', '1', 'section', { sort_order: 0 }),
      row('tail', '2', 'm2', { sort_order: 1 }),
    ];
    const ordered = documentOrder(rows);
    expect(ordered.map((r) => r.id)).toEqual(['chap', 'sub', 'line', 'tail']);
    expect(currentLevels(ordered)).toEqual([1, 2, 0, 0]);
  });

  it('suggests titles from the numbering of a flat pasted bill', () => {
    // A French DPGF pasted flat: chapter lines came in as pcs x 1 items.
    const flat = [
      row('a', '1', 'pcs'),
      row('b', '1.1', 'pcs'),
      row('c', '1.1.1', 'm3'),
      row('d', '1.1.2', 'm2'),
      row('e', '2', ''),
      row('f', '2.1', 'kg'),
    ];
    expect(suggestLevels(flat)).toEqual([1, 2, 0, 0, 1, 0]);
  });
});

describe('recurringLines', () => {
  it('groups the same description and unit and flags drifting rates', () => {
    const lines = recurringLines([
      { id: '1', description: 'Béton C25/30', unit: 'm3', quantity: 10, unit_rate: 110 },
      { id: '2', description: 'béton  C25/30', unit: 'M3', quantity: 4, unit_rate: 125 },
      { id: '3', description: 'Béton C25/30', unit: 'm2', quantity: 4, unit_rate: 125 },
      { id: '4', description: 'Coffrage', unit: 'm2', quantity: 4, unit_rate: 30 },
      { id: '5', description: 'Coffrage', unit: 'm2', quantity: 2, unit_rate: 30 },
      { id: '6', description: 'Bâtiment A', unit: 'section', quantity: 0, unit_rate: 0 },
    ]);
    expect(lines.map((l) => [l.description, l.ids, l.drifting])).toEqual([
      ['Béton C25/30', ['1', '2'], true],
      ['Coffrage', ['4', '5'], false],
    ]);
  });
});
