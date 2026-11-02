// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
import { describe, it, expect } from 'vitest';
import { parseRows } from './ExcelPasteModal';

/** Whole tender bills as they come off a spreadsheet clipboard (issue 554). */

const DPGF = [
  'N°\tDésignation\tU\tQté\tPU HT\tMontant HT',
  '1\tGROS OEUVRE\t\t\t\t',
  '1.1\tTerrassements\t\t\t\t',
  '1.1.1\tFouille en rigole\tm3\t12,500\t18,50\t231,25',
  '1.1.2\tRemblai compacté\tm3\t1 250,000\t9,80\t12 250,00',
  '1.2\tFondations\t\t\t\t',
  '1.2.1\tBéton de propreté C12/15\tm3\t2,625\t120,00\t315,00',
  '2\tCHARPENTE\t\t\t\t',
  '2.1\tFerme en bois lamellé\tU\t4\t1 850,00\t7 400,00',
].join('\n');

describe('French DPGF as pasted from Excel', () => {
  const out = parseRows(DPGF, 'fr-FR');

  it('keeps every line, in order, with the chapter depth from the numbering', () => {
    expect(out.rows.map((r) => [r.ordinal, r.level])).toEqual([
      ['1', 1],
      ['1.1', 2],
      ['1.1.1', 0],
      ['1.1.2', 0],
      ['1.2', 2],
      ['1.2.1', 0],
      ['2', 1],
      ['2.1', 0],
    ]);
    expect(out.invalidNumbers).toBe(0);
    expect(out.skippedEmpty).toBe(0);
  });

  it('reads quantities to three decimals and thousands with spaces', () => {
    const q = Object.fromEntries(out.rows.map((r) => [r.ordinal, r.quantity]));
    expect(q['1.1.1']).toBe(12.5);
    expect(q['1.1.2']).toBe(1250);
    expect(q['1.2.1']).toBe(2.625);
    const rate = Object.fromEntries(out.rows.map((r) => [r.ordinal, r.unit_rate]));
    expect(rate['2.1']).toBe(1850);
  });

  it('ignores the total column: the figures are recomputed', () => {
    expect(out.detectedHeaders.sort()).toEqual(['description', 'ordinal', 'quantity', 'unit', 'unit_rate']);
    expect(out.rows.every((r) => r.quantity * r.unit_rate < 1e6)).toBe(true);
  });

  it('chapter lines carry no unit, quantity or rate', () => {
    for (const r of out.rows.filter((x) => x.level > 0)) {
      expect(r).toMatchObject({ unit: '', quantity: 0, unit_rate: 0 });
    }
  });

  it('the same quantity gives the same figure under an English reader locale when the column proves the mark', () => {
    // 12,500 is ambiguous alone, but the column holds 1 250,000: a comma is decimal here.
    const en = parseRows(DPGF, 'en-US');
    expect(en.rows.find((r) => r.ordinal === '1.1.1')!.quantity).toBe(12.5);
  });
});

describe('German LV (Leistungsverzeichnis)', () => {
  const LV = [
    'Pos.\tBezeichnung\tMenge\tEinheit\tEP\tGesamtpreis',
    '01\tRohbauarbeiten\t\t\t\t',
    '01.01\tErdarbeiten\t\t\t\t',
    '01.01.0010\tBaugrube ausheben\t1.250,000\tm3\t12,40\t15.500,00',
    '01.01.0020\tBodenabtransport\t980,5\tm3\t21,75\t21.325,88',
    '01.02\tBeton\t\t\t\t',
    '01.02.0010\tFundament C25/30\t42,125\tm3\t189,00\t7.961,63',
  ].join('\n');

  it('reads dotted thousands, comma decimals and column order Menge before Einheit', () => {
    const out = parseRows(LV, 'de-DE');
    expect(out.rows.map((r) => r.level)).toEqual([1, 2, 0, 0, 2, 0]);
    expect(out.rows[2]).toMatchObject({ ordinal: '01.01.0010', unit: 'm3', quantity: 1250, unit_rate: 12.4 });
    expect(out.rows[3]).toMatchObject({ quantity: 980.5, unit_rate: 21.75 });
    expect(out.rows[5]).toMatchObject({ quantity: 42.125, unit_rate: 189 });
    expect(out.detectedHeaders).not.toContain('total');
  });

  it('a headerless LV with Pos. numbers and no unit on chapter lines still nests', () => {
    const raw = ['01\tRohbau', '01.01\tErdarbeiten', '01.01.0010\tBaugrube\tm3\t10,5\t12,40'].join('\n');
    const out = parseRows(raw, 'de-DE');
    expect(out.rows.map((r) => r.level)).toEqual([1, 2, 0]);
    expect(out.rows[2]).toMatchObject({ unit: 'm3', quantity: 10.5, unit_rate: 12.4 });
  });

  it('GAEB headings OZ, Kurztext and ME are recognised', () => {
    const raw = 'OZ\tKurztext\tMenge\tME\tEP\tGP\n01.01.0010\tBaugrube\t10,5\tm3\t12,40\t130,20';
    const out = parseRows(raw, 'de-DE');
    expect(out.detectedHeaders.sort()).toEqual(['description', 'ordinal', 'quantity', 'unit', 'unit_rate']);
    expect(out.rows[0]).toMatchObject({ ordinal: '01.01.0010', description: 'Baugrube', unit: 'm3', quantity: 10.5 });
  });
});

describe('Spanish and Italian headings', () => {
  it('reads a presupuesto', () => {
    const raw = 'Partida\tDescripción\tUd\tCantidad\tPrecio unitario\tImporte\n01.01\tHormigón HA-25\tm3\t12,5\t95,00\t1.187,50';
    expect(parseRows(raw, 'es-ES').rows[0]).toMatchObject({ ordinal: '01.01', unit: 'm3', quantity: 12.5, unit_rate: 95 });
  });

  it('reads a computo metrico', () => {
    const raw = 'Art.\tDescrizione\tUM\tQuantità\tPrezzo unitario\tImporto\nA.01\tCalcestruzzo\tm3\t12,5\t95,00\t1.187,50';
    expect(parseRows(raw, 'it-IT').rows[0]).toMatchObject({ ordinal: 'A.01', unit: 'm3', quantity: 12.5, unit_rate: 95 });
  });
});

describe('edge cases of a pasted bill', () => {
  const H = 'Description\tUnit\tQty\tRate\n';

  it('a zero quantity or rate stays zero, not the blank-cell default', () => {
    const r = parseRows(`${H}Item\tm\t0\t0`, 'en-US').rows[0]!;
    expect(r.quantity).toBe(0);
    expect(r.unit_rate).toBe(0);
  });

  it('a negative quantity (a deduction) keeps its sign', () => {
    expect(parseRows(`${H}Deduction\tm2\t-12,5\t10`, 'fr-FR').rows[0]!.quantity).toBe(-12.5);
    expect(parseRows(`${H}Deduction\tm2\t(12.5)\t10`, 'en-US').rows[0]!.quantity).toBe(-12.5);
  });

  it('currency signs and unit suffixes are stripped in several currencies', () => {
    const rate = (s: string, loc: string) => parseRows(`${H}A\tm\t1\t${s}`, loc).rows[0]!.unit_rate;
    expect(rate('1 250,00 €', 'fr-FR')).toBe(1250);
    expect(rate('$1,250.50', 'en-US')).toBe(1250.5);
    expect(rate("CHF 1'250.50", 'de-CH')).toBe(1250.5);
    expect(rate('1 250,00 zł', 'pl-PL')).toBe(1250);
  });

  it('a big bill parses all its lines', () => {
    const lines = Array.from({ length: 5000 }, (_, i) => `Item ${i}\tm3\t${i + 1},500\t${i % 90},25`);
    const out = parseRows(H + lines.join('\n'), 'fr-FR');
    expect(out.rows).toHaveLength(5000);
    expect(out.rows[4999]!.quantity).toBe(5000.5);
  });

  it('a large figure keeps all its digits', () => {
    expect(parseRows(`${H}A\tm\t1\t123 456 789,25`, 'fr-FR').rows[0]!.unit_rate).toBe(123456789.25);
  });

  it('Arabic-Indic digits under an Arabic locale are read, not dropped', () => {
    const out = parseRows(`${H}بند\tm2\t١٢٫٥\t١٠`, 'ar-EG');
    expect(out.rows[0]!.description).toBe('بند');
    expect(out.rows[0]!.quantity).toBe(12.5);
    expect(out.rows[0]!.unit_rate).toBe(10);
  });

  it('Windows line endings do not leak into the last cell', () => {
    const out = parseRows(`${H}A\tm3\t2,5\t10\r\nB\tm3\t3\t11\r\n`, 'fr-FR');
    expect(out.rows.map((r) => r.unit_rate)).toEqual([10, 11]);
    expect(out.invalidNumbers).toBe(0);
  });

  it('only chapter lines and no figures anywhere stay ordinary positions', () => {
    const out = parseRows('Foundations\nWalls\nRoof', 'en-US');
    expect(out.rows.every((r) => r.level === 0)).toBe(true);
  });
});
