// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * parseDecimalInput - the strict, locale-aware parser behind every numeric
 * cell editor in the BOQ grid. The German-keyboard cases are the point:
 * `48,60` must parse to 48.6, never 4860.
 */
import { describe, it, expect } from 'vitest';
import { parseDecimalInput, normalizeDecimalSeparators } from './parseDecimal';

describe('parseDecimalInput - plain dot decimals (canonical)', () => {
  it.each([
    ['48.60', 48.6],
    ['0.5', 0.5],
    ['.5', 0.5],
    ['42', 42],
    ['0', 0],
    ['1000', 1000],
    ['  100.50  ', 100.5],
    ['-3.25', -3.25],
    ['+7.5', 7.5],
    ['1e3', 1000],
    ['1.5e2', 150],
  ])('parses %s -> %d', (raw, expected) => {
    expect(parseDecimalInput(raw)).toBeCloseTo(expected, 10);
  });
});

describe('parseDecimalInput - comma decimals (de and friends)', () => {
  it.each([
    ['48,60', 48.6],
    ['1,5', 1.5],
    ['0,5', 0.5],
    ['0,500', 0.5],
    ['12345,678', 12345.678],
    ['-3,25', -3.25],
  ])('parses %s -> %d', (raw, expected) => {
    expect(parseDecimalInput(raw)).toBeCloseTo(expected, 10);
  });
});

describe('parseDecimalInput - thousands separators', () => {
  it.each([
    ['1.234,56', 1234.56],
    ['1,234.56', 1234.56],
    ['12.345.678,90', 12345678.9],
    ['12,345,678.90', 12345678.9],
    ['1,000', 1000],
    ['1,234,567', 1234567],
    ['1.234.567', 1234567],
    ['1 234,56', 1234.56],
    ['1 234 567.89', 1234567.89],
    ['1 234,56', 1234.56],
    ['1 234,56', 1234.56],
  ])('parses %s -> %d', (raw, expected) => {
    expect(parseDecimalInput(raw)).toBeCloseTo(expected, 10);
  });

  it('keeps a single dot as the decimal point even with three digits after', () => {
    // `1.234` typed into the grid has always meant one-point-two-three-four;
    // dot-thousands only collapse in unambiguous multi-group shapes.
    expect(parseDecimalInput('1.234')).toBeCloseTo(1.234, 10);
  });
});

describe('parseDecimalInput - garbage stays garbage', () => {
  it.each([
    [''],
    ['   '],
    ['abc'],
    ['10abc'],
    ['abc10'],
    ['10.5x'],
    ['48,,60'],
    ['1,2,3'],
    ['1.2.3'],
    ['1,23.4,5'],
    ['-'],
    ['+'],
    ['.'],
    [','],
    ['=1+2'],
    ['0x10'],
    ['Infinity'],
    ['NaN'],
    ['1/2'],
  ])('rejects %j', (raw) => {
    expect(parseDecimalInput(raw)).toBeNull();
  });

  it('never truncates a partial prefix the way parseFloat would', () => {
    // parseFloat('10.5x') === 10.5 - the exact silent corruption this parser
    // exists to refuse.
    expect(parseDecimalInput('10.5x')).toBeNull();
  });
});

describe('normalizeDecimalSeparators', () => {
  it('leaves canonical input untouched', () => {
    expect(normalizeDecimalSeparators('48.60')).toBe('48.60');
  });
  it('converts a decimal comma', () => {
    expect(normalizeDecimalSeparators('48,60')).toBe('48.60');
  });
  it('collapses mixed separators by last-wins', () => {
    expect(normalizeDecimalSeparators('1.234,56')).toBe('1234.56');
    expect(normalizeDecimalSeparators('1,234.56')).toBe('1234.56');
  });
  it('maps the unicode minus to ASCII', () => {
    expect(parseDecimalInput('−5')).toBe(-5);
  });
});
