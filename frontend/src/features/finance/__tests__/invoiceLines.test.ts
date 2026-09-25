// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect } from 'vitest';
import {
  editLine,
  editorLinesFromInvoice,
  invoiceTotals,
  linesToPayload,
  newEditorLine,
  vatChoices,
} from '../invoiceLines';

function line(rate: string, vat: string, qty = '1') {
  let l = newEditorLine(null);
  l = editLine(l, 'quantity', qty);
  l = editLine(l, 'unit_rate', rate);
  return editLine(l, 'vat_rate', vat);
}

describe('invoiceTotals', () => {
  it('rounds VAT per line and adds lines into Net, VAT and Gross', () => {
    const totals = invoiceTotals([line('0.33', '19', '3'), line('1000', '7')]);
    // 0.99 * 19% = 0.1881 -> 0.19 on its own line.
    expect(totals).toEqual({ subtotal: 1000.99, tax: 70.19, total: 1071.18 });
  });

  it('reads comma-free canonical numbers only, never parseFloat', () => {
    expect(invoiceTotals([line('9,000', '0')]).subtotal).toBe(0);
  });
});

describe('linesToPayload', () => {
  it('keeps an explicit 0 and sends an empty rate as null', () => {
    const body = linesToPayload([line('100', '0'), line('50', '')], 'Invoice line');
    expect(body.map((l) => l.vat_rate)).toEqual(['0', null]);
    expect(body[0]?.description).toBe('Invoice line');
  });

  it('drops lines that carry no money', () => {
    expect(linesToPayload([line('', '19'), line('10', '19')], 'x')).toHaveLength(1);
  });
});

describe('editorLinesFromInvoice', () => {
  it('keeps the links of a stored line and its own amount', () => {
    const [loaded] = editorLinesFromInvoice(
      [{ description: 'Claim 3', quantity: '1', unit_rate: '10', amount: '12.50', vat_rate: '20.00', cost_line_id: 'cl-1', wbs_id: 'w', cost_category: 'labor', sort_order: 4 }],
      {},
      '19',
    );
    expect(loaded?.vat_rate).toBe('20');
    expect(loaded?.vat_touched).toBe(true);
    const [sent] = linesToPayload([loaded!], 'x');
    expect(sent).toMatchObject({ cost_line_id: 'cl-1', wbs_id: 'w', cost_category: 'labor', sort_order: 4, amount: '12.50' });
  });

  it('opens a lump-sum invoice as one line reproducing its stored tax', () => {
    const lines = editorLinesFromInvoice([], { subtotal: '1000.00', tax: '190.00' }, '25');
    expect(lines).toHaveLength(1);
    expect(invoiceTotals(lines)).toEqual({ subtotal: 1000, tax: 190, total: 1190 });
  });
});

describe('vatChoices', () => {
  it('offers national rates highest first and takes the marked default', () => {
    const { options, defaultRate } = vatChoices([
      { rate_pct: '13.00' },
      { rate_pct: '25.00', is_default: true },
      { rate_pct: '5.00' },
      { rate_pct: '0.00' },
      { rate_pct: '8.00', subdivision_code: 'HR-01' },
    ]);
    expect(options).toEqual(['25', '13', '5', '0']);
    expect(defaultRate).toBe('25');
  });

  it('falls back to the highest rate and to nothing for an unknown country', () => {
    expect(vatChoices([{ rate_pct: '7' }, { rate_pct: '19' }]).defaultRate).toBe('19');
    expect(vatChoices(undefined)).toEqual({ options: [], defaultRate: null });
  });
});
