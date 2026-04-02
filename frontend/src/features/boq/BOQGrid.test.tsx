// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { evaluateFormula } from './grid/cellEditors';
import { getColumnDefs } from './grid/columnDefs';
import { parseClipboardNumber } from './BOQGrid';

describe('evaluateFormula', () => {
  it('should evaluate simple addition', () => {
    expect(evaluateFormula('2 + 3')).toBe(5);
  });

  it('should evaluate multiplication', () => {
    expect(evaluateFormula('2 * 3.5 * 12')).toBe(84);
  });

  it('should evaluate complex expressions', () => {
    expect(evaluateFormula('(10 + 5) * 2')).toBe(30);
  });

  it('should return null for invalid expressions', () => {
    expect(evaluateFormula('hello')).toBeNull();
    expect(evaluateFormula('')).toBeNull();
  });

  it('should return null for negative results', () => {
    expect(evaluateFormula('-5')).toBeNull();
  });

  it('should return null for Infinity', () => {
    expect(evaluateFormula('1 / 0')).toBeNull();
  });

  it('should round to 2 decimal places', () => {
    expect(evaluateFormula('10 / 3')).toBe(3.33);
  });

  it('should reject expressions with invalid characters', () => {
    expect(evaluateFormula('2 + alert(1)')).toBeNull();
    expect(evaluateFormula('require("fs")')).toBeNull();
  });
});

describe('getColumnDefs', () => {
  const mockT = (key: string, opts?: Record<string, string>) => opts?.defaultValue || key;
  const mockFmt = new Intl.NumberFormat('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  const context = { currencySymbol: '€', fmt: mockFmt, t: mockT };

  it('should return 9 columns (drag handle + checkbox + 7 data columns)', () => {
    const defs = getColumnDefs(context);
    expect(defs).toHaveLength(9);
  });

  it('should have drag handle as the first column', () => {
    const defs = getColumnDefs(context);
    const dragCol = defs[0];
    expect(dragCol.colId).toBe('_drag');
    expect(dragCol.width).toBe(30);
    expect(dragCol.editable).toBe(false);
    expect(dragCol.sortable).toBe(false);
    expect(dragCol.resizable).toBe(false);
    expect(typeof dragCol.rowDrag).toBe('function');
  });

  it('should have checkbox selection as the second column', () => {
    const defs = getColumnDefs(context);
    const checkboxCol = defs[1];
    expect(checkboxCol.colId).toBe('_checkbox');
    expect(checkboxCol.width).toBe(36);
    expect(checkboxCol.editable).toBe(false);
    expect(checkboxCol.headerCheckboxSelection).toBe(true);
    expect(typeof checkboxCol.checkboxSelection).toBe('function');
  });

  it('should have ordinal, description, unit, quantity, unit_rate, total, actions fields', () => {
    const defs = getColumnDefs(context);
    const fields = defs.map((d) => d.field ?? d.colId);
    expect(fields).toContain('ordinal');
    expect(fields).toContain('description');
    expect(fields).toContain('unit');
    expect(fields).toContain('quantity');
    expect(fields).toContain('unit_rate');
    expect(fields).toContain('total');
    expect(fields).toContain('_actions');
  });

  it('should have total as non-editable', () => {
    const defs = getColumnDefs(context);
    const totalCol = defs.find((d) => d.field === 'total');
    expect(totalCol?.editable).toBe(false);
  });

  it('should have actions as non-sortable and non-filterable', () => {
    const defs = getColumnDefs(context);
    const actionsCol = defs.find((d) => d.field === '_actions');
    expect(actionsCol?.sortable).toBe(false);
    expect(actionsCol?.filter).toBe(false);
    expect(actionsCol?.editable).toBe(false);
  });

  it('should have description with flex', () => {
    const defs = getColumnDefs(context);
    const descCol = defs.find((d) => d.field === 'description');
    expect(descCol?.flex).toBe(1);
    expect(descCol?.minWidth).toBe(260);
  });

  it('should use formulaCellEditor for quantity', () => {
    const defs = getColumnDefs(context);
    const qtyCol = defs.find((d) => d.field === 'quantity');
    expect(qtyCol?.cellEditor).toBe('formulaCellEditor');
  });

  it('should use agSelectCellEditor for unit', () => {
    const defs = getColumnDefs(context);
    const unitCol = defs.find((d) => d.field === 'unit');
    expect(unitCol?.cellEditor).toBe('agSelectCellEditor');
  });
});

describe('parseClipboardNumber', () => {
  it('should parse a simple integer', () => {
    expect(parseClipboardNumber('42')).toBe(42);
  });

  it('should parse a decimal with period', () => {
    expect(parseClipboardNumber('3.14')).toBeCloseTo(3.14);
  });

  it('should parse a decimal with comma (European format)', () => {
    expect(parseClipboardNumber('3,14')).toBeCloseTo(3.14);
  });

  it('should parse thousand-separated with period decimal (US format)', () => {
    expect(parseClipboardNumber('1,234.56')).toBeCloseTo(1234.56);
  });

  it('should parse thousand-separated with comma decimal (European format)', () => {
    expect(parseClipboardNumber('1.234,56')).toBeCloseTo(1234.56);
  });

  it('should strip leading currency symbol (Euro)', () => {
    expect(parseClipboardNumber('€42.50')).toBeCloseTo(42.5);
  });

  it('should strip leading currency symbol (Dollar)', () => {
    expect(parseClipboardNumber('$1,234.56')).toBeCloseTo(1234.56);
  });

  it('should strip leading currency symbol (Pound)', () => {
    expect(parseClipboardNumber('£99.99')).toBeCloseTo(99.99);
  });

  it('should handle whitespace around the value', () => {
    expect(parseClipboardNumber('  100.50  ')).toBeCloseTo(100.5);
  });

  it('should return NaN for non-numeric strings', () => {
    expect(parseClipboardNumber('hello')).toBeNaN();
  });

  it('should return NaN for empty string', () => {
    expect(parseClipboardNumber('')).toBeNaN();
  });

  it('should handle "1,000" as thousand separator (3-digit after comma)', () => {
    expect(parseClipboardNumber('1,000')).toBe(1000);
  });

  it('should handle "1,5" as decimal (less than 3 digits after comma)', () => {
    expect(parseClipboardNumber('1,5')).toBeCloseTo(1.5);
  });

  it('should handle large numbers with both separators', () => {
    expect(parseClipboardNumber('1,234,567.89')).toBeCloseTo(1234567.89);
  });
});
