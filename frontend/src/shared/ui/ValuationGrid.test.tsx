import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

import { ValuationGrid, type ValuationGridData } from './ValuationGrid';

const fig = (value: string | null, source: 'stored' | 'computed' | 'missing', field: string | null) => ({
  value,
  source,
  field,
});

/* Footings: submitted 20 (2400 recorded), assessed 18 and certified 15 at 120. */
const GRID: ValuationGridData = {
  source_kind: 'progress_claim',
  source_id: 'c2',
  document_number: 'PC-2',
  status: 'submitted',
  currency: 'USD',
  note: '',
  rows: [
    {
      id: 'l2',
      label: '03.10 Footings',
      unit: 'm3',
      rate: '120',
      rate_source: 'contract_line.unit_rate',
      stages: {
        submitted: { qty: fig('20', 'stored', 'submitted_qty'), amount: fig('2400', 'stored', 'period_completed_value') },
        assessed: { qty: fig('18', 'stored', 'assessed_qty'), amount: fig('2160.00', 'computed', 'contract_line.unit_rate') },
        certified: { qty: fig('15', 'stored', 'certified_qty'), amount: fig(null, 'missing', null) },
      },
      cumulative_certified_qty: '45',
      prior_cumulative: '4000',
      cumulative: '3800',
      cumulative_field: 'cumulative_completed_value',
      findings: [{ rule_id: 'valuation.cumulative_not_decreasing', severity: 'warning', message: 'Line dropped' }],
    },
  ],
  totals: { submitted: '2400', assessed: '2160.00', certified: null },
};

function wrap(node: ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={qc}>{node}</QueryClientProvider>);
}

describe('ValuationGrid', () => {
  it('shows each amount with its source and flags the drop', async () => {
    wrap(<ValuationGrid queryKey={['vg', 1]} fetchGrid={() => Promise.resolve(GRID)} saveNote={vi.fn()} />);
    expect(await screen.findByText('03.10 Footings')).toBeTruthy();
    const sources = Array.from(document.querySelectorAll('[data-source]')).map((n) => n.getAttribute('data-source'));
    expect(sources).toEqual(['stored', 'computed', 'missing']);
    expect(screen.getByTestId('valuation-grid-finding').getAttribute('title')).toBe('Line dropped');
    expect(screen.getByTestId('valuation-grid-note')).toBeTruthy();
  });

  it('says so honestly when there are no lines', async () => {
    wrap(
      <ValuationGrid
        queryKey={['vg', 2]}
        fetchGrid={() => Promise.resolve({ ...GRID, rows: [], totals: { submitted: null, assessed: null, certified: null } })}
      />,
    );
    expect(await screen.findByText('No lines to value yet')).toBeTruthy();
    expect(screen.queryByTestId('valuation-grid-note')).toBeNull();
  });
});
