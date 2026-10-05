// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// What a client reads in the payment-plan card: amounts in the currency's own
// minor units, a date that moved said in words with the original beside it,
// and the server's verdict on what is overdue. The card computes none of these
// itself, so each test hands it the server's answer and checks it is shown,
// not re-derived.

import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, cleanup, screen, waitFor, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiMocks = vi.hoisted(() => ({
  listMyProjects: vi.fn(),
  listProjectPaymentPlans: vi.fn(),
}));
vi.mock('../api', async (importOriginal) => ({ ...(await importOriginal<typeof import('../api')>()), ...apiMocks }));

const { PaymentPlanCard } = await import('../PaymentPlanCard');
import type { PortalPaymentPlan, PortalPaymentPlanLine } from '../api';

function withQuery(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

function line(id: string, extra: Partial<PortalPaymentPlanLine> = {}): PortalPaymentPlanLine {
  return {
    id,
    sequence: 1,
    label: `Instalment ${id}`,
    amount: '1234.5',
    percent_of_contract: null,
    status: 'upcoming',
    milestone_name: null,
    forecast_due_date: '2026-11-02',
    original_due_date: '2026-11-02',
    days_moved: 0,
    days_until: 28,
    days_overdue: null,
    ...extra,
  };
}

function plan(currency: string, lines: PortalPaymentPlanLine[], extra: Partial<PortalPaymentPlan> = {}): PortalPaymentPlan {
  return {
    contract_id: `ct-${currency}`,
    contract_title: `Contract in ${currency}`,
    currency,
    contract_total: '10000',
    paid_total: '2500',
    outstanding_total: '7500',
    lines,
    ...extra,
  };
}

function oneProject(items: PortalPaymentPlan[]) {
  apiMocks.listMyProjects.mockResolvedValue([{ id: 'p-1', name: 'Garden House', project_code: null }]);
  apiMocks.listProjectPaymentPlans.mockResolvedValue({ items });
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe('the client payment plan card', () => {
  it('prints euro amounts with two decimals', async () => {
    oneProject([plan('EUR', [line('a')])]);
    withQuery(<PaymentPlanCard />);
    expect(await screen.findByText('Instalment a')).toBeTruthy();
    expect(document.body.textContent).toMatch(/1,234\.50/);
    expect(document.body.textContent).toMatch(/7,500\.00/);
  });

  it('prints yen with no decimals', async () => {
    oneProject([plan('JPY', [line('a', { amount: '150000' })], { contract_total: '600000', paid_total: '0', outstanding_total: '600000' })]);
    withQuery(<PaymentPlanCard />);
    await screen.findByText('Instalment a');
    const text = document.body.textContent ?? '';
    expect(text).toMatch(/150,000/);
    expect(text).not.toMatch(/150,000\.00/);
    expect(text).not.toMatch(/600,000\.00/);
  });

  it('prints Kuwaiti dinar with three decimals', async () => {
    oneProject([plan('KWD', [line('a', { amount: '1234.567' })])]);
    withQuery(<PaymentPlanCard />);
    await screen.findByText('Instalment a');
    expect(document.body.textContent).toMatch(/1,234\.567/);
    expect(document.body.textContent).toMatch(/7,500\.000/);
  });

  it('says how far a date moved, singular and plural, and shows the original date', async () => {
    oneProject([
      plan('EUR', [
        line('a', { days_moved: 1, original_due_date: '2026-11-01' }),
        line('b', { days_moved: 14, original_due_date: '2026-10-19' }),
        line('c', { days_moved: -3 }),
        line('d', { days_moved: 0 }),
      ]),
    ]);
    withQuery(<PaymentPlanCard />);
    expect(await screen.findByText('Moved 1 day later')).toBeTruthy();
    expect(screen.getByText('Moved 14 days later')).toBeTruthy();
    expect(screen.getByText('Moved 3 days earlier')).toBeTruthy();
    expect(screen.getAllByText('Originally due')).toHaveLength(3);
    // A line that did not move says nothing about moving.
    expect(screen.queryByText(/Moved 0/)).toBeNull();
  });

  it('shows overdue only where the server says so, with the days it counted', async () => {
    oneProject([
      plan('EUR', [
        line('late', { status: 'overdue', days_overdue: 5, forecast_due_date: '2026-09-30' }),
        // Past its date but not reached: the server says upcoming, and so does the card.
        line('waiting', { status: 'upcoming', forecast_due_date: '2026-09-01', days_until: -34 }),
      ]),
    ]);
    withQuery(<PaymentPlanCard />);
    expect(await screen.findByText('5 days overdue')).toBeTruthy();
    expect(screen.getAllByText('Overdue')).toHaveLength(1);
    expect(screen.getByText('Upcoming')).toBeTruthy();
  });

  it('names the contract when a project has more than one plan', async () => {
    oneProject([plan('EUR', [line('a')]), plan('USD', [line('b')])]);
    withQuery(<PaymentPlanCard />);
    expect(await screen.findByText('Contract in EUR')).toBeTruthy();
    expect(screen.getByText('Contract in USD')).toBeTruthy();
  });

  it('says the plan could not be loaded and offers a retry', async () => {
    apiMocks.listMyProjects.mockResolvedValue([{ id: 'p-1', name: 'Garden House', project_code: null }]);
    apiMocks.listProjectPaymentPlans.mockRejectedValueOnce(new Error('Request failed (500)'));
    withQuery(<PaymentPlanCard />);
    expect(await screen.findByRole('alert')).toBeTruthy();
    expect(screen.getByText('Your payment plan could not be loaded.')).toBeTruthy();

    apiMocks.listProjectPaymentPlans.mockResolvedValueOnce({ items: [plan('EUR', [line('a')])] });
    fireEvent.click(screen.getByText('Retry'));
    expect(await screen.findByText('Instalment a')).toBeTruthy();
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull());
  });

  it('renders nothing when no plan is shared', async () => {
    oneProject([]);
    const { container } = withQuery(<PaymentPlanCard />);
    await waitFor(() => expect(apiMocks.listProjectPaymentPlans).toHaveBeenCalled());
    expect(container.textContent).toBe('');
  });
});
