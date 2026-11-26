import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';
import type { CvrLine, CvrWbsFigures, CvrWbsNode } from './api';

const fetchMock = vi.fn();
vi.mock('./api', () => ({
  fetchCvrWbsRollup: (...args: unknown[]) => fetchMock(...args),
}));

import { WbsRollupCard, visibleNodes } from './WbsRollupCard';

function fig(cost: string, margin = '0'): CvrWbsFigures {
  return {
    budget_cost: '0', committed_cost: '0', cost_to_date: cost, value_to_date: '0',
    forecast_cost: cost, forecast_value: '0', margin_to_date: '0', forecast_margin: margin, forecast_margin_pct: '0',
  };
}

function node(id: string, parent: string | null, code: string, depth: number, cost: string, lineIds: string[] = [], children = 0): CvrWbsNode {
  return {
    id, parent_id: parent, code, name: `Name ${code}`, depth, child_count: children,
    line_ids: lineIds, line_count: lineIds.length, positions: 0, own: fig(cost), total: fig(cost),
  };
}

const NODES = [
  node('n1', null, '1', 0, '90000', [], 2),
  node('n11', 'n1', '1.1', 1, '30000', ['L11']),
  node('n12', 'n1', '1.2', 1, '60000', ['L12']),
];

function wrap(el: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{el}</QueryClientProvider>);
}

describe('visibleNodes', () => {
  it('shows only roots until a parent is opened', () => {
    expect(visibleNodes(NODES, new Set()).map((n) => n.code)).toEqual(['1']);
    expect(visibleNodes(NODES, new Set(['n1'])).map((n) => n.code)).toEqual(['1', '1.1', '1.2']);
  });

  it('keeps a grandchild hidden when its parent is closed', () => {
    const deep = [...NODES, node('n121', 'n12', '1.2.1', 2, '1')];
    expect(visibleNodes(deep, new Set(['n1'])).map((n) => n.code)).toEqual(['1', '1.1', '1.2']);
    expect(visibleNodes(deep, new Set(['n12'])).map((n) => n.code)).toEqual(['1']);
  });
});

describe('WbsRollupCard', () => {
  beforeEach(() => fetchMock.mockReset());

  it('drills down from the parent to its children and to the lines behind them', async () => {
    fetchMock.mockResolvedValue({
      report_id: 'r', project_id: 'p', period: '2026-11', currency: 'EUR', line_count: 3, wbs_count: 3,
      nodes: NODES,
      unallocated: node('', null, '', 0, '1000', ['LX']),
      totals: fig('91000'),
      findings: [],
    });
    const lines = [{ id: 'L11', cost_code: '1.1', description: 'Substructure line', cost_to_date: '30000', value_to_date: '0' }] as CvrLine[];
    wrap(<WbsRollupCard reportId="r" lines={lines} />);
    fireEvent.click(screen.getByRole('button', { name: /CVR by WBS/i }));

    expect(await screen.findByTestId('wbs-row-1')).toBeInTheDocument();
    expect(screen.queryByTestId('wbs-row-1.1')).not.toBeInTheDocument();
    expect(screen.getByTestId('wbs-row-unallocated')).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith('r');

    fireEvent.click(within(screen.getByTestId('wbs-row-1')).getByRole('button', { name: /elements beneath/i }));
    const child = screen.getByTestId('wbs-row-1.1');
    fireEvent.click(within(child).getByRole('button', { name: /Lines: 1/i }));
    expect(within(screen.getByTestId('wbs-own-lines')).getByText('Substructure line')).toBeInTheDocument();
  });

  it('asks for a spine fill when the report has no lines', async () => {
    fetchMock.mockResolvedValue({
      report_id: 'r', project_id: 'p', period: '2026-11', currency: 'EUR', line_count: 0, wbs_count: 0,
      nodes: [], unallocated: node('', null, '', 0, '0'), totals: fig('0'), findings: [],
    });
    wrap(<WbsRollupCard reportId="r" lines={[]} />);
    fireEvent.click(screen.getByRole('button', { name: /CVR by WBS/i }));
    expect(await screen.findByText(/No cost heads to roll up/i)).toBeInTheDocument();
  });
});
