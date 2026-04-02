// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { detectColumns, parseSpreadsheetData } from './excelImport';

describe('detectColumns', () => {
  it('should detect English headers', () => {
    const mapping = detectColumns(['No.', 'Description', 'Unit', 'Quantity', 'Rate', 'Total']);
    expect(mapping.ordinal).toBeDefined();
    expect(mapping.description).toBeDefined();
    expect(mapping.unit).toBeDefined();
    expect(mapping.quantity).toBeDefined();
    expect(mapping.unitRate).toBeDefined();
    expect(mapping.total).toBeDefined();
  });

  it('should detect German headers', () => {
    const mapping = detectColumns(['Pos', 'Bezeichnung', 'Einheit', 'Menge', 'Einheitspreis', 'Gesamtpreis']);
    expect(mapping.ordinal).toBeDefined();
    expect(mapping.description).toBeDefined();
    expect(mapping.unit).toBeDefined();
    expect(mapping.quantity).toBeDefined();
    expect(mapping.unitRate).toBeDefined();
    expect(mapping.total).toBeDefined();
  });

  it('should detect French headers', () => {
    const mapping = detectColumns(['Ref', 'Désignation', 'Unité', 'Quantité', 'Prix unitaire', 'Montant']);
    expect(mapping.ordinal).toBeDefined();
    expect(mapping.description).toBeDefined();
    expect(mapping.unit).toBeDefined();
    expect(mapping.quantity).toBeDefined();
  });

  it('should handle section/classification columns', () => {
    const mapping = detectColumns(['Item', 'Description', 'Unit', 'Qty', 'Rate', 'Total', 'NRM', 'Section']);
    expect(mapping.classification).toBeDefined();
    expect(mapping.section).toBeDefined();
  });

  it('should return empty mapping for unknown headers', () => {
    const mapping = detectColumns(['Foo', 'Bar', 'Baz']);
    expect(mapping.ordinal).toBeUndefined();
    expect(mapping.description).toBeUndefined();
  });
});

describe('parseSpreadsheetData', () => {
  it('should parse basic CSV rows', () => {
    const rows = [
      ['No.', 'Description', 'Unit', 'Quantity', 'Rate', 'Total'],
      ['1', 'Concrete foundation', 'm3', '50', '120.00', '6000.00'],
      ['2', 'Steel reinforcement', 'kg', '2000', '1.50', '3000.00'],
      ['3', 'Formwork', 'm2', '100', '25.00', '2500.00'],
    ];
    const mapping = { ordinal: '0', description: '1', unit: '2', quantity: '3', unitRate: '4', total: '5' };
    const result = parseSpreadsheetData(rows, mapping);

    expect(result.positions.length).toBe(3);
    expect(result.errors.length).toBe(0);
    expect(result.positions[0].description).toBe('Concrete foundation');
    expect(result.positions[0].unit).toBe('m3');
    expect(result.positions[0].quantity).toBe(50);
    expect(result.positions[0].unitRate).toBe(120);
    expect(result.positions[0].total).toBe(6000);
  });

  it('should skip empty rows', () => {
    const rows = [
      ['No.', 'Description', 'Unit', 'Qty'],
      ['1', 'Item A', 'm', '10'],
      ['', '', '', ''],
      ['2', 'Item B', 'm2', '20'],
    ];
    const mapping = { ordinal: '0', description: '1', unit: '2', quantity: '3' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.positions.length).toBe(2);
  });

  it('should skip rows without description', () => {
    const rows = [
      ['No.', 'Description', 'Unit', 'Qty'],
      ['1', '', 'm', '10'],
      ['2', 'Valid item', 'm2', '20'],
    ];
    const mapping = { ordinal: '0', description: '1', unit: '2', quantity: '3' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.positions.length).toBe(1);
  });

  it('should handle comma-formatted numbers', () => {
    const rows = [
      ['No.', 'Description', 'Qty', 'Rate'],
      ['1', 'Item', '1.500,00', '25,50'],
    ];
    const mapping = { ordinal: '0', description: '1', quantity: '2', unitRate: '3' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.positions[0].quantity).toBeCloseTo(1500, 0);
  });

  it('should compute total when not provided', () => {
    const rows = [
      ['Desc', 'Qty', 'Rate'],
      ['Item A', '10', '5.00'],
    ];
    const mapping = { description: '0', quantity: '1', unitRate: '2' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.positions[0].total).toBe(50);
  });

  it('should return error for empty file', () => {
    const rows = [['No.', 'Description']];
    const mapping = { ordinal: '0', description: '1' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.positions.length).toBe(0);
    expect(result.errors.length).toBeGreaterThan(0);
  });

  it('should include metadata with totals', () => {
    const rows = [
      ['Desc', 'Qty', 'Rate'],
      ['A', '10', '5'],
      ['B', '20', '3'],
    ];
    const mapping = { description: '0', quantity: '1', unitRate: '2' };
    const result = parseSpreadsheetData(rows, mapping);
    expect(result.metadata?.positionCount).toBe(2);
    expect(result.metadata?.totalValue).toBe(110); // 50 + 60
  });
});
