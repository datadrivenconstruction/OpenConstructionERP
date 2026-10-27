// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import {
  columnTotals,
  compareCells,
  parseDisplayedNumber,
  startTableEnhancer,
  toTsv,
} from '../tableEnhancer';
import { writeTablePrefs } from '../tablePrefs';

describe('parseDisplayedNumber', () => {
  it.each([
    ['1,234.50', 1234.5],
    ['1.234,50', 1234.5],
    ['1 234,5 m3', 1234.5],
    ['12,5', 12.5],
    ['1,250', 1250],
    ['-12 %', -12],
    ['(450.00)', -450],
    ['EUR 1.000.000', 1000000],
    ['− 3', -3],
  ])('%s -> %d', (raw, value) => {
    expect(parseDisplayedNumber(raw)).toBeCloseTo(value);
  });

  it.each(['', 'Concrete C30/37', 'Wall 2 of 3', '2026-10-27', 'n/a'])('%s is not a number', (raw) => {
    expect(parseDisplayedNumber(raw)).toBeNull();
  });
});

describe('table helpers', () => {
  it('sorts numbers by value, before text', () => {
    const cells = ['10', '9', 'abc', '1,000.00'];
    expect([...cells].sort((a, b) => compareCells(a, b, 'en'))).toEqual(['9', '10', '1,000.00', 'abc']);
  });

  it('totals numeric columns and skips the first and text columns', () => {
    const rows = [
      ['01', 'Concrete', '10.00', 'm3'],
      ['02', 'Formwork', '2.50', 'm2'],
      ['03', 'Rebar', '', 't'],
    ];
    expect(columnTotals(rows)).toEqual([null, null, 12.5, null]);
  });

  it('writes tab-separated text', () => {
    expect(toTsv([['a', 'b'], ['1', '2']])).toBe('a\tb\n1\t2');
  });
});

describe('startTableEnhancer', () => {
  it('adds a totals row and filters rows in spreadsheet mode', async () => {
    document.body.innerHTML = `<table><thead><tr><th>Code</th><th>Qty</th></tr></thead>
      <tbody><tr><td>A</td><td>2</td></tr><tr><td>B</td><td>3</td></tr></tbody></table>`;
    writeTablePrefs({ excel: true, keyboard: false });
    const stop = startTableEnhancer();
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const foot = document.querySelector('tfoot[data-oe-total]');
    expect(foot?.textContent).toContain('5');
    const th = document.querySelectorAll('th')[1]!;
    th.click();
    expect(th.getAttribute('aria-sort')).toBe('ascending');
    stop();
    writeTablePrefs({ excel: false, keyboard: false });
  });
});
