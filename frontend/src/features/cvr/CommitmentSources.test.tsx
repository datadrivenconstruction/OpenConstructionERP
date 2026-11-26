import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import type { ReactNode } from 'react';

const fetchMock = vi.fn();
vi.mock('./api', () => ({
  fetchCommitmentSources: (...args: unknown[]) => fetchMock(...args),
}));

import { CommitmentSources } from './CommitmentSources';

function wrap(node: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('CommitmentSources', () => {
  beforeEach(() => fetchMock.mockReset());

  it('says why there is nothing when the line has no cost line, without asking the server', () => {
    wrap(<CommitmentSources projectId="p" positionId="x" onCostSpine={false} />);
    expect(screen.getByText(/no cost line/i)).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('offers the next step when nothing is committed yet', async () => {
    fetchMock.mockResolvedValue({ currency: 'EUR', boq_position_id: 'x', cost_line_id: 'c', sources: [] });
    wrap(<CommitmentSources projectId="p" positionId="x" onCostSpine />);
    expect(await screen.findByRole('link', { name: /open procurement/i })).toHaveAttribute('href', '/procurement');
  });

  it('links each order and subcontract to its own record', async () => {
    fetchMock.mockResolvedValue({
      currency: 'EUR',
      boq_position_id: 'x',
      cost_line_id: 'c',
      sources: [
        {
          kind: 'purchase_order', document_id: 'po1', document_number: 'PO-0001', document_title: '',
          status: 'issued', line_id: 'i1', description: 'Ready-mix concrete', committed_qty: '120.0000',
          committed_value: '19200.00', received_qty: '0.0000', received_value: '0.00',
        },
        {
          kind: 'subcontract', document_id: 'k1', document_number: 'SC-7', document_title: 'Formwork',
          status: 'active', line_id: 'l1', description: 'Formwork', committed_qty: '1.0000',
          committed_value: '5000.00', received_qty: '0.0000', received_value: '0.00',
        },
      ],
    });
    wrap(<CommitmentSources projectId="p" positionId="x" onCostSpine />);
    expect(await screen.findByRole('link', { name: 'PO-0001' })).toHaveAttribute('href', '/procurement?po=po1');
    expect(screen.getByRole('link', { name: 'SC-7' })).toHaveAttribute('href', '/contracts/k1');
    expect(fetchMock).toHaveBeenCalledWith('p', 'x');
  });
});
