// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, expect, it } from 'vitest';
import { scopeKeyFor } from '../listViewsApi';
import { applyTableState, columnKeys, readTableState, startTableEnhancer } from '../tableEnhancer';
import { writeTablePrefs } from '../tablePrefs';

describe('scopeKeyFor', () => {
  it('replaces ids so one view serves every project', () => {
    expect(scopeKeyFor('/projects/3f2b8c1e-1a2b-4c3d-8e9f-001122334455/boq')).toBe('projects/:id/boq');
    expect(scopeKeyFor('/invoices/42')).toBe('invoices/:id');
    expect(scopeKeyFor('/')).toBe('home');
  });
});

describe('table view state', () => {
  it('round-trips sort, filters, widths and hidden columns by header text', async () => {
    document.body.innerHTML = `<table><thead><tr><th>Code</th><th>Item</th><th>Qty</th></tr></thead>
      <tbody><tr><td>01</td><td>Concrete</td><td>5</td></tr><tr><td>02</td><td>Rebar</td><td>2</td></tr></tbody></table>`;
    writeTablePrefs({ excel: true, keyboard: false });
    const stop = startTableEnhancer();
    await new Promise((r) => requestAnimationFrame(() => r(null)));
    const table = document.querySelector('table')!;
    expect(columnKeys(table)).toEqual(['Code', 'Item', 'Qty']);
    applyTableState(table, {
      filters: { Item: 'con' },
      columns: ['Code', 'Qty'],
      widths: { Qty: 120 },
      sort: { key: 'Qty', dir: 'desc' },
    });
    expect(readTableState(table)).toEqual({
      filters: { Item: 'con' },
      columns: ['Code', 'Qty'],
      widths: { Qty: 120 },
      sort: { key: 'Qty', dir: 'desc' },
    });
    const rows = Array.from(table.tBodies[0]!.rows);
    expect(rows.filter((r) => !r.hasAttribute('data-oe-hidden')).map((r) => r.cells[0]!.textContent)).toEqual(['01']);
    expect(table.querySelector('th:nth-child(2)')?.hasAttribute('data-oe-col-hidden')).toBe(true);
    stop();
    writeTablePrefs({ excel: false, keyboard: false });
  });
});
