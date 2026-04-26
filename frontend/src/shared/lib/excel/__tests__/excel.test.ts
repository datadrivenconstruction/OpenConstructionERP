/**
 * Excel migration smoke tests — exceljs replacement for xlsx (SheetJS).
 *
 * These tests verify the three core flows we use in the app:
 *   1. Export — produce a valid .xlsx (zip) buffer with the OOXML magic.
 *   2. Import — parse a workbook back into JS values.
 *   3. Round-trip — export then re-import a workbook with mixed types.
 *
 * They are intentionally library-direct: no React, no DOM, no app code,
 * so they validate the exceljs API surface we depend on.
 */

import { describe, it, expect } from 'vitest';
import ExcelJS from 'exceljs';

/** OOXML / xlsx files are zip archives → start with "PK\x03\x04". */
function hasZipMagic(buf: ArrayBuffer): boolean {
  const view = new Uint8Array(buf);
  return view.length >= 4 && view[0] === 0x50 && view[1] === 0x4b && view[2] === 0x03 && view[3] === 0x04;
}

describe('excel migration: exceljs replaces xlsx', () => {
  it('test_excel_export_produces_valid_xlsx', async () => {
    const wb = new ExcelJS.Workbook();
    const ws = wb.addWorksheet('Sheet1');
    ws.addRow(['No.', 'Description', 'Quantity', 'Unit Rate', 'Total']);
    ws.addRow(['1.001', 'Concrete C30/37', 100, 150, 15000]);

    const buf = (await wb.xlsx.writeBuffer()) as ArrayBuffer;
    expect(buf.byteLength).toBeGreaterThan(0);
    // OOXML zip magic — the first four bytes of every valid .xlsx.
    expect(hasZipMagic(buf)).toBe(true);
  });

  it('test_excel_import_parses_simple_sheet', async () => {
    // Build a tiny workbook with known values, then re-load it.
    const writer = new ExcelJS.Workbook();
    const w = writer.addWorksheet('Data');
    w.addRow(['ordinal', 'description', 'quantity']);
    w.addRow(['1.001', 'Steel beam HEB 200', 12.5]);
    w.addRow(['1.002', 'Anchor bolts M16', 240]);
    const buf = (await writer.xlsx.writeBuffer()) as ArrayBuffer;

    const reader = new ExcelJS.Workbook();
    await reader.xlsx.load(buf);
    const sheet = reader.getWorksheet('Data');
    expect(sheet).toBeDefined();

    const rows: unknown[][] = [];
    sheet!.eachRow((row) => {
      // row.values is 1-indexed; drop the leading null/undefined slot.
      const values = row.values as unknown[];
      rows.push(values.slice(1));
    });

    expect(rows.length).toBe(3);
    expect(rows[0]).toEqual(['ordinal', 'description', 'quantity']);
    expect(rows[1]?.[0]).toBe('1.001');
    expect(rows[1]?.[1]).toBe('Steel beam HEB 200');
    expect(rows[1]?.[2]).toBe(12.5);
    expect(rows[2]?.[2]).toBe(240);
  });

  it('test_excel_round_trip', async () => {
    // Mixed types: string, number, date, formula-as-text.
    const refDate = new Date(Date.UTC(2026, 3, 25, 12, 0, 0));

    const writer = new ExcelJS.Workbook();
    const w = writer.addWorksheet('Mixed');
    w.addRow(['kind', 'value']);
    w.addRow(['string', 'BOQ Position']);
    w.addRow(['number', 1234.5]);
    w.addRow(['date', refDate]);
    // Formula stored as plain text — emulates how we ship "=A1+B1"-style
    // hint strings in description columns without any calc engine.
    w.addRow(['formula-as-text', '=SUM(B2:B3)']);

    const buf = (await writer.xlsx.writeBuffer()) as ArrayBuffer;
    expect(hasZipMagic(buf)).toBe(true);

    const reader = new ExcelJS.Workbook();
    await reader.xlsx.load(buf);
    const sheet = reader.getWorksheet('Mixed');
    expect(sheet).toBeDefined();

    // Pull cell values out (1-based row + col).
    const stringVal = sheet!.getRow(2).getCell(2).value;
    const numberVal = sheet!.getRow(3).getCell(2).value;
    const dateVal = sheet!.getRow(4).getCell(2).value;
    const formulaVal = sheet!.getRow(5).getCell(2).value;

    expect(stringVal).toBe('BOQ Position');
    expect(numberVal).toBe(1234.5);
    // ExcelJS returns a Date for date-typed cells.
    expect(dateVal).toBeInstanceOf(Date);
    expect((dateVal as Date).getUTCFullYear()).toBe(2026);
    // String values that look like formulas are kept verbatim (no calc).
    expect(formulaVal).toBe('=SUM(B2:B3)');
  });
});
