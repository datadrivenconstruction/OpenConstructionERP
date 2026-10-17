// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { addDecimalStrings, subtractDecimalStrings, sumDecimalStrings, sumMoneyStrings } from './exactDecimal';

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

describe('exact decimal sums', () => {
  it.each([
    ['0.10', '0.20', '0.30'],
    ['9007199254740993.01', '0.01', '9007199254740993.02'],
    ['1.5', '-2.25', '-0.75'],
    ['100', '0.001', '100.001'],
  ])('%s plus %s is exactly %s', (left, right, expected) => {
    expect(addDecimalStrings(left, right)).toBe(expected);
  });

  it('sums a list at the widest scale and an empty list to zero', () => {
    expect(sumDecimalStrings(['0.1', '0.2', '0.3'])).toBe('0.6');
    expect(sumDecimalStrings(['33.34', '33.33', '33.33'])).toBe('100.00');
    expect(sumDecimalStrings([])).toBe('0');
  });

  it('refuses a sum with an unreadable operand', () => {
    expect(sumDecimalStrings(['1', '1e3'])).toBeNull();
    expect(addDecimalStrings('1', '')).toBeNull();
  });

  it('display sums treat missing figures as zero', () => {
    expect(sumMoneyStrings(['0.10', null, undefined, 'x', '0.20'])).toBe('0.30');
  });
});
