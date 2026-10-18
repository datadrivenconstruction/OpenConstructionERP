// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import type { CostControlRow } from '../api';
import { CostControlTable } from '../CostControlTable';

function row(over: Partial<CostControlRow>): CostControlRow {
  return {
    key: 'x',
    kind: 'cost_line',
    code: '',
    description: '',
    account_id: null,
    status: 'active',
    budget: '0',
    estimate: '0',
    planned: '0',
    awarded: '0',
    changes: '0',
    committed: '0',
    measured: '0',
    certified: '0',
    invoiced: '0',
    paid: '0',
    pending_changes: '0',
    forecast: '0',
    forecast_source: 'none',
    automatic_forecast: '0',
    automatic_source: 'none',
    variance: '0',
    variance_pct: null,
    override: null,
    forecast_method: 'best_available',
    method_origin: 'project',
    method_applied: true,
    method_comment: '',
    ...over,
  };
}

describe('CostControlTable', () => {
  it('adds group subtotals as exact decimals and shows the allowance inside its account', () => {
    const onOpen = vi.fn();
    render(
      <CostControlTable
        axis="cost_line"
        currency="EUR"
        totals={{ planned: '3006.20' }}
        accounts={[{ id: 'a1', code: '330', name: '330', title: 'External walls', parent_id: null }]}
        rows={[
          row({ key: 'l1', code: 'CL-1', description: 'Wall A', account_id: 'a1', planned: '1000.40' }),
          row({ key: 'l2', code: 'CL-2', description: 'Wall B', account_id: 'a1', planned: '1000.40' }),
          row({ key: 'allowance:a1', kind: 'allowance', code: '330', account_id: 'a1', planned: '1000.40' }),
          row({ key: 'l3', code: 'CL-3', description: 'Loose', planned: '5' }),
        ]}
        onOpenLine={onOpen}
      />,
    );
    // Group title is code plus title, not code plus the code-as-name.
    const header = screen.getByText('330 External walls').closest('tr')!;
    // The subtotal carries the two lines and the allowance: 3 x 1000.40 = 3001.20.
    expect(within(header).getAllByText(/3[,.\s\u00a0\u202f]?001/).length).toBeGreaterThan(0);
    // The allowance is labelled and cannot be opened like a cost line.
    const allowance = screen.getByTestId('cost-control-row-allowance:a1');
    expect(allowance).toHaveTextContent(/Allowance on the account/);
    expect(allowance).not.toHaveAttribute('role', 'button');
    // A line on no account sits in the suspense group.
    expect(screen.getByText(/No account \(suspense\)/)).toBeInTheDocument();
  });
});
