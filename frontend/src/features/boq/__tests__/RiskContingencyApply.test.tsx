// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Monte Carlo -> contingency in the estimate:
 *   1. Nothing is written until the estimator confirms; the confirm sends the
 *      percentile and the amount the estimator saw.
 *   2. A stale applied line says so and offers undo.
 */

// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { RiskContingencyApply } from '../RiskContingencyApply';
import { boqApi } from '../api';

vi.mock('../api', () => ({
  boqApi: {
    getRiskContingency: vi.fn(),
    applyRiskContingency: vi.fn(),
    undoRiskContingency: vi.fn(),
  },
}));

const SUGGESTION = {
  percentile: 80,
  amount: '12500.00',
  pct_of_base: 12.5,
  base_total: '100000.00',
  budget: '112500.00',
  below_base: false,
  iterations: 5000,
  seed: 42,
  optimistic_pct: 15,
  pessimistic_pct: 25,
  correlation: 0.2,
  convergence_status: 'converged',
  convergence_margin_pct: 0.3,
  prob_within_base: 22,
  confidence: 0.9,
  fingerprint: 'abc',
};

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <RiskContingencyApply boqId="b1" correlation={0.2} fmt={new Intl.NumberFormat('en-US')} />
    </QueryClientProvider>,
  );
}

describe('RiskContingencyApply', () => {
  beforeEach(() => vi.clearAllMocks());

  it('writes only after confirm, with the previewed amount', async () => {
    boqApi.getRiskContingency.mockResolvedValue({ suggestion: SUGGESTION, applied: null, stale: false });
    boqApi.applyRiskContingency.mockResolvedValue({ suggestion: SUGGESTION, applied: null, stale: false });
    renderIt();
    const apply = await screen.findByRole('button', { name: /Apply P80 contingency/ });
    await waitFor(() => expect(apply).not.toBeDisabled());
    fireEvent.click(apply);
    expect(boqApi.applyRiskContingency).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(boqApi.applyRiskContingency).toHaveBeenCalledWith(
        'b1',
        expect.objectContaining({ percentile: 80, correlation: 0.2, expected_amount: '12500.00' }),
      ),
    );
  });

  it('flags a stale applied line and offers undo', async () => {
    boqApi.getRiskContingency.mockResolvedValue({
      suggestion: SUGGESTION,
      applied: {
        markup_id: 'm1',
        name: 'Risk contingency P80',
        is_active: true,
        line_amount: '11000.00',
        percentile: 80,
        amount: '11000.00',
        seed: 42,
        iterations: 5000,
        applied_at: '2026-11-01T10:00:00Z',
        applied_by_email: 'est@example.com',
        can_undo_to_previous: false,
      },
      stale: true,
      drift_amount: '1500.00',
      drift_pct: 13.6,
    });
    boqApi.undoRiskContingency.mockResolvedValue({ suggestion: null, applied: null, stale: false });
    renderIt();
    const box = await screen.findByTestId('risk-contingency-applied');
    expect(box.textContent).toContain('Line totals changed');
    expect(box.textContent).toContain('+1,500');
    fireEvent.click(screen.getByRole('button', { name: /Remove/ }));
    await waitFor(() => expect(boqApi.undoRiskContingency).toHaveBeenCalledWith('b1'));
  });

  it('can apply as a percentage and warns about another contingency line', async () => {
    boqApi.getRiskContingency.mockResolvedValue({
      suggestion: SUGGESTION,
      applied: null,
      stale: false,
      other_contingency: ['Manual contingency'],
    });
    boqApi.applyRiskContingency.mockResolvedValue({ suggestion: SUGGESTION, applied: null, stale: false });
    renderIt();
    const apply = await screen.findByRole('button', { name: /Apply P80 contingency/ });
    await waitFor(() => expect(apply).not.toBeDisabled());
    fireEvent.click(apply);
    expect(screen.getByTestId('risk-contingency-double-count').textContent).toContain('Manual contingency');
    fireEvent.click(screen.getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: 'Confirm' }));
    await waitFor(() =>
      expect(boqApi.applyRiskContingency).toHaveBeenCalledWith(
        'b1',
        expect.objectContaining({ percentile: 80, mode: 'percentage' }),
      ),
    );
  });
});
