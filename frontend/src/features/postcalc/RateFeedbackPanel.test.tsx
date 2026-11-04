// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import type { RateProposal } from './rateFeedbackApi';

vi.mock('./rateFeedbackApi', () => ({
  fetchRateProposals: vi.fn(),
  refreshRateProposals: vi.fn(),
  confirmRateProposal: vi.fn(),
  rejectRateProposal: vi.fn(),
}));

import { confirmRateProposal, fetchRateProposals, rejectRateProposal } from './rateFeedbackApi';
import { RateFeedbackPanel, confidenceTone } from './RateFeedbackPanel';

const proposal: RateProposal = {
  id: 'p1',
  cost_item_id: 'c1',
  cost_item_code: 'C-1',
  cost_item_description: 'Concrete C30',
  unit: 'm3',
  current_rate: '100',
  suggested_rate: '120',
  variance_pct: '20.00',
  current_hours_per_unit: '2.5',
  observed_hours_per_unit: '3.5',
  hours_variance_pct: '40.00',
  project_count: 3,
  line_count: 4,
  total_quantity: '40',
  spread_pct: null,
  confidence: '0.6000',
  status: 'pending',
  warnings: [],
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RateFeedbackPanel />
    </QueryClientProvider>,
  );
}

describe('RateFeedbackPanel', () => {
  beforeEach(() => vi.clearAllMocks());

  it('applies nothing until the estimator confirms a row', async () => {
    vi.mocked(fetchRateProposals).mockResolvedValue([proposal]);
    renderPanel();
    await screen.findByTestId('rf-row');
    expect(confirmRateProposal).not.toHaveBeenCalled();
  });

  it('confirms with the estimator rate when one is typed', async () => {
    vi.mocked(fetchRateProposals).mockResolvedValue([proposal]);
    vi.mocked(confirmRateProposal).mockResolvedValue({ ...proposal, status: 'accepted' });
    renderPanel();
    await screen.findByTestId('rf-row');
    fireEvent.change(screen.getByRole('spinbutton'), { target: { value: '110' } });
    fireEvent.click(screen.getByRole('button', { name: /confirm/i }));
    await waitFor(() => expect(confirmRateProposal).toHaveBeenCalledWith('p1', '110'));
  });

  it('rejects a row without confirming it', async () => {
    vi.mocked(fetchRateProposals).mockResolvedValue([proposal]);
    vi.mocked(rejectRateProposal).mockResolvedValue({ ...proposal, status: 'rejected' });
    renderPanel();
    await screen.findByTestId('rf-row');
    fireEvent.click(screen.getByRole('button', { name: /reject/i }));
    await waitFor(() => expect(rejectRateProposal).toHaveBeenCalledWith('p1'));
    expect(confirmRateProposal).not.toHaveBeenCalled();
  });

  it('shows no table when nothing deviates', async () => {
    vi.mocked(fetchRateProposals).mockResolvedValue([]);
    renderPanel();
    await waitFor(() => expect(vi.mocked(fetchRateProposals)).toHaveBeenCalled());
    expect(screen.queryByRole('table')).toBeNull();
  });

  it('never paints a thin sample green', () => {
    expect(confidenceTone('0.2')).toBe('error');
    expect(confidenceTone('0.5')).toBe('warning');
    expect(confidenceTone('0.9')).toBe('success');
  });
});
