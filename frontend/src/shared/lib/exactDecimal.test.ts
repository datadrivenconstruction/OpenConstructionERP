// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { subtractDecimalStrings } from './exactDecimal';

describe('exact invoice decimal subtraction', () => {
  it.each([
    ['10.000', '0.001', '9.999'],
    ['0.30', '0.10', '0.20'],
    ['1000', '1', '999'],
    ['9007199254740993.01', '0.01', '9007199254740993.00'],
    ['100.0000', '0.0100', '99.9900'],
    ['1', '0.000001', '0.999999'],
    ['1', '0.000000000000000001', '0.999999999999999999'],
    ['1.00', '1.000', '0.000'],
    ['-0.00', '0', '0.00'],
    ['1.20', '2.30', '-1.10'],
    ['-1.20', '-2.30', '1.10'],
    ['-1.20', '2.30', '-3.50'],
    ['00010.00', '0001.0', '9.00'],
  ])('%s minus %s is exactly %s', (left, right, expected) => {
    expect(subtractDecimalStrings(left, right)).toBe(expected);
  });

  it.each(['', ' ', '1,00', '1.2oops', 'Infinity', 'NaN', '0x10', '1e3', '+1', '.5', '1.', ' 1', '1\n'])(
    'does not invent an amount for invalid operand %j', (invalid) => {
      expect(subtractDecimalStrings(invalid, '1')).toBeNull();
      expect(subtractDecimalStrings('1', invalid)).toBeNull();
    },
  );
});
