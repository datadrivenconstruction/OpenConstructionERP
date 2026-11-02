// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, it, expect } from 'vitest';
import { parseRows } from './ExcelPasteModal';

/**
 * parseRows is the pasted-clipboard parser behind the Excel paste modal.
 * These tests pin the honesty behaviour from issue #347: a cell that is not
 * a usable number, and a line without a description, must be counted and
 * reported rather than silently read as zero or dropped.
 */
describe('parseRows', () => {
  it('returns empty diagnostics for empty input', () => {
    expect(parseRows('')).toEqual({
      rows: [],
      detectedHeaders: [],
      skippedEmpty: 0,
      invalidNumbers: 0,
      reviewCells: [],
    });
  });

  it('detects a header row and parses the data below it', () => {
    const out = parseRows('Description\tUnit\tQty\tRate\nConcrete\tm3\t120\t185.00');
    expect(out.rows).toHaveLength(1);
    expect(out.rows[0]).toMatchObject({
      description: 'Concrete',
      unit: 'm3',
      quantity: 120,
      unit_rate: 185,
    });
    expect(out.detectedHeaders).toContain('description');
    expect(out.invalidNumbers).toBe(0);
    expect(out.skippedEmpty).toBe(0);
  });

  it('falls back to positional order when there is no header row', () => {
    const out = parseRows('Excavation\tm3\t50\t12.5');
    expect(out.rows).toHaveLength(1);
    expect(out.rows[0]).toMatchObject({
      description: 'Excavation',
      unit: 'm3',
      quantity: 50,
      unit_rate: 12.5,
    });
  });

  it('reads a European 1.234,56 grouping', () => {
    const out = parseRows('Rebar\tkg\t1.234,56\t1,45');
    expect(out.rows[0]?.quantity).toBeCloseTo(1234.56);
    expect(out.rows[0]?.unit_rate).toBeCloseTo(1.45);
    expect(out.invalidNumbers).toBe(0);
  });

  it('reads a US 1,234.56 grouping', () => {
    const out = parseRows('Formwork\tm2\t1,234.56\t22.00');
    expect(out.rows[0]?.quantity).toBeCloseTo(1234.56);
    expect(out.invalidNumbers).toBe(0);
  });

  it('counts an unreadable number and keeps a safe default instead of silent zero', () => {
    const out = parseRows('Description\tQty\nWall\tN/A');
    expect(out.rows).toHaveLength(1);
    // The bad quantity is not read as 0; it keeps the visible default (1) and
    // the modal warns the user via the invalidNumbers count.
    expect(out.rows[0]?.quantity).toBe(1);
    expect(out.invalidNumbers).toBe(1);
  });

  it('counts a line that has data but no description as skipped', () => {
    const out = parseRows('Description\tQty\n\t50');
    expect(out.rows).toHaveLength(0);
    expect(out.skippedEmpty).toBe(1);
  });

  it('does not flag empty numeric cells - they take the documented default', () => {
    // Quantity blank -> 1, rate blank -> 0, and neither counts as invalid.
    const out = parseRows('Description\tUnit\tQty\tRate\nDoor\tpcs\t\t');
    expect(out.rows[0]).toMatchObject({ quantity: 1, unit_rate: 0 });
    expect(out.invalidNumbers).toBe(0);
  });

  it('reports several problems across a mixed paste', () => {
    const raw = [
      'Description\tUnit\tQty\tRate',
      'Concrete\tm3\t10\t100', // clean
      'Steel\tkg\tzzz\t5', // bad quantity
      '\tm2\t4\t9', // no description
    ].join('\n');
    const out = parseRows(raw);
    expect(out.rows).toHaveLength(2);
    expect(out.invalidNumbers).toBe(1);
    expect(out.skippedEmpty).toBe(1);
  });
});

describe('parseRows - market number spellings (issue 554)', () => {
  const H = 'Description\tUnit\tQty\tRate\n';
  const one = (line: string, locale: string | null = 'fr-FR') => parseRows(H + line, locale);

  it.each([
    ['1 250,00', 1250],
    ['1 250.00', 1250],
    ['0,250', 0.25],
    ['1.234,56', 1234.56],
    ['1,234.56', 1234.56],
    ['1\u00A0250,00', 1250],
    ['1\u202F250,00', 1250],
    ["12'500.50", 12500.5],
  ])('rate %s reads as %s', (rate, expected) => {
    expect(one(`Concrete\tm3\t1\t${rate}`).rows[0]!.unit_rate).toBe(expected);
  });

  it('a lone separator before three digits follows the number locale', () => {
    expect(one('Concrete\tm3\t1,250\t10', 'fr-FR').rows[0]!.quantity).toBe(1.25);
    expect(one('Concrete\tm3\t1,250\t10', 'en-US').rows[0]!.quantity).toBe(1250);
  });

  it('the column decides before the locale when its other cells prove the mark', () => {
    const out = parseRows(H + 'A\tm3\t1,250\t1\nB\tm3\t2.5\t1', 'fr-FR');
    expect(out.rows[0]!.quantity).toBe(1250);
    expect(out.reviewCells).toEqual([]);
  });

  it('a column that proves both marks flags its ambiguous cells for review', () => {
    const out = parseRows(H + 'A\tm3\t1,250\t1\nB\tm3\t2.5\t1\nC\tm3\t2,5\t1', 'fr-FR');
    expect(out.reviewCells).toEqual(['0:quantity']);
  });

  it('with no locale an ambiguous cell is flagged, never silently read', () => {
    expect(one('Concrete\tm3\t1.250\t10', null).reviewCells).toEqual(['0:quantity']);
  });
});

describe('parseRows - tender bills pasted as they are (issue 554)', () => {
  it('recognises DPGF headings and ignores the total column', () => {
    const raw = 'N°\tDésignation\tU\tQté\tPU HT\tMontant HT\n1.1\tBéton C25/30\tm3\t2,625\t120,00\t315,00';
    const out = parseRows(raw, 'fr-FR');
    expect(out.rows[0]).toMatchObject({ ordinal: '1.1', description: 'Béton C25/30', unit: 'm3', quantity: 2.625, unit_rate: 120, level: 0 });
    expect(out.detectedHeaders).not.toContain('total');
  });

  it('a chapter line is a heading, not a pcs x 1 item, and the widest line sets the columns', () => {
    const raw = ['1\tGros oeuvre', '1.1\tFondations', '1.1.1\tBéton\tm3\t2,5\t120', '2\tCharpente'].join('\n');
    const out = parseRows(raw, 'fr-FR');
    expect(out.rows.map((r) => [r.ordinal, r.level])).toEqual([
      ['1', 1],
      ['1.1', 2],
      ['1.1.1', 0],
      ['2', 1],
    ]);
    expect(out.rows[0]).toMatchObject({ unit: '', quantity: 0, unit_rate: 0 });
    expect(out.rows[2]).toMatchObject({ description: 'Béton', unit: 'm3', quantity: 2.5, unit_rate: 120 });
  });

  it('without numbering the first column stays the description', () => {
    const out = parseRows('Excavation\tm3\t50\t12.5\nBackfill\tm3\t20\t8');
    expect(out.rows[0]).toMatchObject({ ordinal: '01', description: 'Excavation', level: 0 });
  });
});
