// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Component tests for the contingency card on the risk register and the note
// under a Contingency line in the finance budget.
//
//   * a manager confirms an occurred risk's drawdown: the dialog prefills the
//     proposed amount and posts it against the proposed line, nothing earlier;
//   * an editor sees the pending risk but is not offered the button the
//     backend would refuse;
//   * a confirmed drawdown can be reversed through a confirmation;
//   * the finance note shows drawn and left for a Contingency line only.
//
// The test setup's i18n mock renders each label's English defaultValue.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiDelete: vi.fn(),
}));

import * as api from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { ContingencyCard } from './ContingencyCard';
import { ContingencyBudgetNote } from './ContingencyBudgetNote';
import type { ContingencyPosition } from './contingency';

const getMock = vi.mocked(api.apiGet);
const postMock = vi.mocked(api.apiPost);
const deleteMock = vi.mocked(api.apiDelete);

const PROJECT = 'p-1';

function position(overrides: Partial<ContingencyPosition> = {}): ContingencyPosition {
  return {
    currency: 'EUR',
    emv: '1500.00',
    p50: '0.00',
    p80: '3000.00',
    percentile_method: 'exact',
    emv_by_currency: { EUR: '1500.00' },
    allocated: '10000.00',
    drawn: '0.00',
    remaining: '10000.00',
    coverage_gap: '8500.00',
    state: 'covered',
    active_risk_count: 1,
    excluded_closed_count: 0,
    excluded_drawn_count: 0,
    unconverted_emv: {},
    missing_fx_rates: [],
    lines: [
      { budget_id: 'L1', wbs_id: 'CT', currency: 'EUR', allocated: '10000.00', drawn: '0.00', remaining: '10000.00', converted: true },
    ],
    drawdowns: [],
    pending: [
      {
        risk_id: 'r-7',
        risk_code: 'R-007',
        risk_title: 'Ground water',
        impact_cost: '2500.00',
        currency: 'EUR',
        proposed_amount: '2500.00',
        proposed_currency: 'EUR',
        proposed_budget_id: 'L1',
      },
    ],
    ...overrides,
  };
}

function renderCard() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <ContingencyCard projectId={PROJECT} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe('ContingencyCard', () => {
  it('lets a manager confirm the proposed drawdown, and only on confirm', async () => {
    useAuthStore.setState({ userRole: 'manager' });
    getMock.mockResolvedValue(position());
    postMock.mockResolvedValue(position({ pending: [], drawn: '2500.00', remaining: '7500.00' }));
    renderCard();

    expect(await screen.findByTestId('risk-contingency-card')).toBeInTheDocument();
    expect(getMock).toHaveBeenCalledWith(`/v1/risk/projects/${PROJECT}/contingency`);
    expect(screen.getByText('Ground water')).toBeInTheDocument();
    // Showing the pending risk draws nothing.
    expect(postMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole('button', { name: 'Confirm drawdown' }));
    const dialog = await screen.findByRole('dialog');
    const amount = within(dialog).getByLabelText(/^Amount \(EUR\)/) as HTMLInputElement;
    expect(amount.value).toBe('2500');
    fireEvent.change(amount, { target: { value: '2300.5' } });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Confirm drawdown' }));

    await waitFor(() => expect(postMock).toHaveBeenCalledTimes(1));
    expect(postMock).toHaveBeenCalledWith(`/v1/risk/projects/${PROJECT}/contingency/drawdowns/r-7`, {
      amount: '2300.5',
      budget_id: 'L1',
      note: '',
    });
  });

  it('does not offer the drawdown to an editor', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    getMock.mockResolvedValue(position());
    renderCard();

    expect(await screen.findByText('Ground water')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm drawdown' })).not.toBeInTheDocument();
    expect(screen.getByText('A manager confirms the drawdown')).toBeInTheDocument();
  });

  it('keeps the confirm button off when the amount is not a positive number', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    getMock.mockResolvedValue(position());
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: 'Confirm drawdown' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByLabelText(/^Amount \(EUR\)/), { target: { value: '0' } });
    expect(within(dialog).getByRole('button', { name: 'Confirm drawdown' })).toBeDisabled();
  });

  it('reverses a confirmed drawdown after a confirmation', async () => {
    useAuthStore.setState({ userRole: 'manager' });
    getMock.mockResolvedValue(
      position({
        pending: [],
        drawn: '2300.00',
        remaining: '7700.00',
        drawdowns: [
          {
            risk_id: 'r-7',
            risk_code: 'R-007',
            risk_title: 'Ground water',
            budget_id: 'L1',
            amount: '2300.00',
            currency: 'EUR',
            confirmed_by: 'u-1',
            confirmed_at: '2026-10-01T09:00:00+00:00',
            note: 'dewatering',
          },
        ],
      }),
    );
    // apiDelete defaults its response type to void; this route answers with the position.
    deleteMock.mockResolvedValue(position() as unknown as Awaited<ReturnType<typeof api.apiDelete>>);
    renderCard();

    fireEvent.click(await screen.findByRole('button', { name: /Reverse/ }));
    expect(deleteMock).not.toHaveBeenCalled();
    const confirm = await screen.findAllByRole('button', { name: 'Reverse' });
    const dialogButton = confirm[confirm.length - 1];
    if (!dialogButton) throw new Error('the reverse confirmation did not open');
    fireEvent.click(dialogButton);
    await waitFor(() =>
      expect(deleteMock).toHaveBeenCalledWith(`/v1/risk/projects/${PROJECT}/contingency/drawdowns/r-7`),
    );
  });

  it('says so when the finance budget has no contingency line', async () => {
    useAuthStore.setState({ userRole: 'manager' });
    getMock.mockResolvedValue(position({ lines: [], allocated: '0.00', remaining: '0.00', state: 'no_allocation' }));
    renderCard();

    expect(await screen.findByText(/^The finance budget has no contingency line yet/)).toBeInTheDocument();
    expect(screen.getByText('Needs a contingency line')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Confirm drawdown' })).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Open finance budget/ })).toHaveAttribute('href', '/finance?tab=budgets');
  });
});

describe('ContingencyBudgetNote', () => {
  function renderNote(category: string, metadata: Record<string, unknown>) {
    return render(
      <MemoryRouter>
        <ContingencyBudgetNote category={category} metadata={metadata} revised="10000" original="10000" currency="EUR" />
      </MemoryRouter>,
    );
  }

  it('shows drawn and the link back for a Contingency line', () => {
    renderNote('Contingency', { 'contingency_drawdown:risk:1': { amount: '2300.00' } });
    expect(screen.getByTestId('contingency-drawn')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Risk register/ })).toHaveAttribute('href', '/risks');
  });

  it('renders nothing for another category', () => {
    const { container } = renderNote('material', { 'contingency_drawdown:risk:1': { amount: '2300.00' } });
    expect(container).toBeEmptyDOMElement();
  });

  it('omits the drawn figure while nothing is drawn', () => {
    renderNote('contingency', { notes: 'x' });
    expect(screen.queryByTestId('contingency-drawn')).not.toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Risk register/ })).toBeInTheDocument();
  });
});
