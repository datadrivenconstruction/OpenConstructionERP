// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  coerceSearchValue,
  columnLabel,
  formatReadAs,
  mapSearchHitsToElementIds,
  parseSearchNumber,
  pickIdColumn,
} from '../propertySearch';

const ELEMENTS = [
  { id: 'uuid-1', mesh_ref: '312001', stable_id: 'guid-1' },
  { id: 'uuid-2', mesh_ref: null, stable_id: 'guid-2' },
  { id: 'uuid-3' },
];

describe('mapSearchHitsToElementIds', () => {
  it('translates a Revit ElementId through mesh_ref, not as a viewer id', () => {
    const out = mapSearchHitsToElementIds([{ id: 312001 }], 'id', ELEMENTS);
    expect(out).toEqual({ elementIds: ['uuid-1'], rowCount: 1, unmatchedCount: 0 });
  });

  it('falls back to stable_id, then to the database id', () => {
    const out = mapSearchHitsToElementIds([{ id: 'guid-2' }, { id: 'uuid-3' }], 'id', ELEMENTS);
    expect(out.elementIds).toEqual(['uuid-2', 'uuid-3']);
  });

  it('uses a stable_id column when the id column does not resolve', () => {
    const out = mapSearchHitsToElementIds([{ ID: '777', stable_id: 'guid-1' }], 'ID', ELEMENTS);
    expect(out.elementIds).toEqual(['uuid-1']);
  });

  it('counts rows with no element and reports each element once', () => {
    const out = mapSearchHitsToElementIds(
      [{ id: '312001' }, { id: '312001' }, { id: '404' }, { id: null }],
      'id',
      ELEMENTS,
    );
    expect(out).toEqual({ elementIds: ['uuid-1'], rowCount: 4, unmatchedCount: 2 });
  });
});

describe('pickIdColumn', () => {
  it('prefers the plain id column and knows the converter variants', () => {
    expect(pickIdColumn([{ name: 'category', type: 'string' }, { name: 'id', type: 'string' }])).toBe('id');
    expect(pickIdColumn([{ name: 'Element ID', type: 'string' }])).toBe('Element ID');
    expect(pickIdColumn([{ name: 'category', type: 'string' }])).toBeNull();
  });

  it('falls back to stable_id, the only id a retried sidecar carries', () => {
    // The Parquet retry rebuilds the sidecar from database rows and writes no
    // "id" column; without this fallback such a model cannot be searched.
    expect(pickIdColumn([{ name: 'stable_id', type: 'string' }, { name: 'area', type: 'string' }])).toBe('stable_id');
    expect(pickIdColumn([{ name: 'stable_id', type: 'string' }, { name: 'id', type: 'string' }])).toBe('id');
    const out = mapSearchHitsToElementIds([{ stable_id: 'guid-2' }], 'stable_id', ELEMENTS);
    expect(out.elementIds).toEqual(['uuid-2']);
  });
});

describe('columnLabel', () => {
  it('shows the stored header and falls back to the key', () => {
    expect(columnLabel({ name: 'phase created', type: 'string', label: 'Phase Created' })).toBe('Phase Created');
    expect(columnLabel({ name: 'phase created', type: 'string' })).toBe('phase created');
    expect(columnLabel({ name: 'phase created', type: 'string', label: '  ' })).toBe('phase created');
  });
});

describe('coerceSearchValue', () => {
  it('sends numbers for numeric comparators, accepting a decimal comma', () => {
    expect(coerceSearchValue('>', '12,5')).toBe(12.5);
    expect(coerceSearchValue('<=', ' 4 ')).toBe(4);
    expect(coerceSearchValue('>', 'big')).toBe('big');
  });

  it('sends text for equality and contains so the server compares as text and number', () => {
    expect(coerceSearchValue('=', '8')).toBe('8');
    expect(coerceSearchValue('LIKE', 'Prog')).toBe('Prog');
  });

  it('reads a comparison number in the reader convention', () => {
    // An Italian "1.500" is fifteen hundred and "1.234,56" a grouped decimal;
    // the old reader sent 1.5 and the text "1.234,56" respectively.
    expect(coerceSearchValue('>', '1.500', 'it-IT')).toBe(1500);
    expect(coerceSearchValue('>', '1.234,56', 'it-IT')).toBe(1234.56);
  });
});

describe('parseSearchNumber', () => {
  // [typed, locale, value, ambiguous]
  const TABLE: [string, string, number, boolean][] = [
    // Forms that read one way in every locale.
    ['1.234,56', 'it-IT', 1234.56, false],
    ['1.234,56', 'en-US', 1234.56, false],
    ['1,234.56', 'it-IT', 1234.56, false],
    ['1,234.56', 'de-DE', 1234.56, false],
    ['12,5', 'en-US', 12.5, false],
    ['12.5', 'it-IT', 12.5, false],
    ['0,500', 'en-US', 0.5, false],
    ['1.2345', 'it-IT', 1.2345, false],
    ['1.234.567', 'en-US', 1234567, false],
    ['1 234,5', 'fr-FR', 1234.5, false],
    ['1 234,5', 'fr-FR', 1234.5, false],
    ['1500', 'it-IT', 1500, false],
    ['-4', 'it-IT', -4, false],
    ['2.5e3', 'en-US', 2500, false],
    // "1.500" / "1,500": the locale decides, and says so.
    ['1.500', 'it-IT', 1500, true],
    ['1.500', 'de-DE', 1500, true],
    ['1.500', 'en-US', 1.5, true],
    ['1,500', 'en-US', 1500, true],
    ['1,500', 'it-IT', 1.5, true],
    ['1,500', 'fr-FR', 1.5, true],
    ['-1.500', 'it-IT', -1500, true],
    ['−1.500', 'it-IT', -1500, true],
  ];

  it.each(TABLE)('reads %j in %s as %d (ambiguous: %s)', (typed, locale, value, ambiguous) => {
    expect(parseSearchNumber(typed, locale)).toEqual({ value, ambiguous });
  });

  it('refuses what is not a number', () => {
    for (const typed of ['', 'big', '10abc', '1.23.4', '0x10', 'Infinity', '1,2,3']) {
      expect(parseSearchNumber(typed, 'it-IT')).toBeNull();
    }
  });

  it('survives a locale tag Intl rejects', () => {
    expect(parseSearchNumber('1,500', 'not a locale!')).toEqual({ value: 1500, ambiguous: true });
  });
});

describe('formatReadAs', () => {
  it('writes the reading so it cannot be misread again', () => {
    expect(formatReadAs(1500, 'it-IT')).toBe('1500');
    expect(formatReadAs(1.5, 'it-IT')).toBe('1,5');
    expect(formatReadAs(1500, 'en-US')).toBe('1500');
    expect(formatReadAs(1234.5678, 'en-US')).toBe('1234.5678');
  });
});
