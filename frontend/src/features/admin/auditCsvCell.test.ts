import { describe, it, expect } from 'vitest';
import { toCsvCell } from './AuditLogPage';

describe('toCsvCell', () => {
  it('defuses spreadsheet formulas in recorded text', () => {
    expect(toCsvCell('=HYPERLINK("http://x")')).toBe(`"'=HYPERLINK(""http://x"")"`);
    expect(toCsvCell('@SUM(A1)')).toBe(`'@SUM(A1)`);
    expect(toCsvCell('+1')).toBe(`'+1`);
  });
  it('leaves numbers and plain text alone', () => {
    expect(toCsvCell(-5)).toBe('-5');
    expect(toCsvCell('Wall')).toBe('Wall');
  });
});
