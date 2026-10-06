// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// An imported deduction line carries no price: its amount is taken off by the
// bill's deductions markup line. The rate cell says so, with the line's own
// signed rate, so a rate of zero does not read as a price nobody entered.

import type { ICellRendererParams } from 'ag-grid-community';
import { render } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { UnitRateCellRenderer } from './cellRenderers';

const t = (k: string, o?: Record<string, string | number>) => {
  const template = (o?.defaultValue as string) ?? k;
  return template.replace(/{{(\w+)}}/g, (_, name: string) => String(o?.[name] ?? ''));
};

function renderRate(metadata: Record<string, unknown>) {
  const params = {
    data: { id: 'p1', unit: 'pcs', quantity: 2, unit_rate: 0, metadata },
    value: 0,
    context: { t, locale: 'en-US', currencyCode: 'EUR' },
  } as unknown as ICellRendererParams;
  return render(<UnitRateCellRenderer {...params} />);
}

describe('the rate cell of a deduction line', () => {
  it('shows the signed rate and a deduction badge', () => {
    const { getByTestId } = renderRate({
      deduction: true,
      deduction_unit_rate: '-50.00',
      deduction_quantity: '2.00',
      deduction_amount: '-100.0000',
    });
    const cell = getByTestId('boq-deduction-rate-p1');
    expect(cell.textContent).toContain('Deduction');
    expect(cell.textContent).toContain('-50.00');
    expect(cell.getAttribute('title')).toContain('-100.00');
  });

  it('leaves an ordinary unpriced line as it was', () => {
    const { queryByTestId, container } = renderRate({});
    expect(queryByTestId('boq-deduction-rate-p1')).toBeNull();
    expect(container.textContent).toBe('0.00');
  });
});
