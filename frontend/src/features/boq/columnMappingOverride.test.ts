// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import { changedColumns, chooseColumn, columnMappingField } from './columnMappingOverride';

// What the importer read a Hungarian bill as: the material and fee halves of
// the rate both show under "unit_rate", which the dropdown cannot tell apart.
const READ = {
  '0': 'ordinal',
  '1': 'classification',
  '2': 'description',
  '3': 'quantity',
  '4': 'unit',
  '5': 'unit_rate',
  '6': 'unit_rate',
};

describe('column mapping override', () => {
  it('sends nothing when the user changed nothing', () => {
    expect(changedColumns(READ, { ...READ })).toEqual({});
    expect(columnMappingField(READ, { ...READ })).toBeNull();
  });

  it('sends only the column the user changed, so the split rate is left as the importer read it', () => {
    const chosen = chooseColumn(READ, '5', '');
    expect(columnMappingField(READ, chosen)).toBe('{"5":""}');
  });

  it('names a column the importer left unmapped once the user maps it', () => {
    expect(changedColumns({ '4': 'unit' }, chooseColumn({ '4': 'unit' }, '3', 'quantity'))).toEqual({ '3': 'quantity' });
  });

  it('takes a field away from the column that had it, and sends both', () => {
    const chosen = chooseColumn(READ, '1', 'quantity');
    expect(chosen['3']).toBe('');
    expect(changedColumns(READ, chosen)).toEqual({ '1': 'quantity', '3': '' });
  });

  it('choosing one rate column leaves both halves of the split out', () => {
    const chosen = chooseColumn({ ...READ, '7': '' }, '7', 'unit_rate');
    expect(changedColumns(READ, chosen)).toEqual({ '5': '', '6': '', '7': 'unit_rate' });
  });

  it('leaving a column out never clears another one', () => {
    const chosen = chooseColumn(READ, '2', '');
    expect(Object.values(chosen).filter((v) => v === '')).toHaveLength(1);
  });
});
