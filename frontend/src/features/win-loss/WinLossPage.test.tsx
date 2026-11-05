import { describe, it, expect, vi, afterEach, beforeEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { WinLossPage } from './WinLossPage';
import { winLossApi, type BidOutcome, type LedgerSummary } from './api';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, second?: string | { defaultValue?: string }) =>
      typeof second === 'string' ? second : (second?.defaultValue ?? key),
  }),
}));
vi.mock('@/shared/ui/PageHeader', () => ({
  PageHeader: ({ actions }: { actions?: React.ReactNode }) => <div>{actions}</div>,
}));

const group = (key: string, won: number, lost: number, rate: string | null) => ({
  key,
  submitted: won + lost,
  won,
  lost,
  hit_rate_pct: rate,
  won_value: '1000',
});

const summary: LedgerSummary = {
  currency: 'EUR',
  currencies: ['EUR'],
  submitted: 3,
  won: 1,
  lost: 2,
  open: 0,
  hit_rate_pct: '33.3',
  won_value: '1000',
  left_on_table: '90',
  left_on_table_wins: 1,
  avg_gap_to_winner_pct: '8.0',
  avg_competitors: '4.0',
  by_client: [group('Acme', 1, 1, '50.0')],
  by_trade: [group('steel', 0, 1, '0.0')],
  by_size: [group('medium', 1, 2, '33.3')],
};

const entry: BidOutcome = {
  id: 'e1',
  title: 'Hall A',
  client_name: 'Acme',
  trade: 'steel',
  submitted_on: null,
  outcome: 'lost',
  currency: 'EUR',
  our_price: '1100',
  winning_price: '1000',
  second_price: null,
  competitor_count: 3,
  lost_reason: null,
  notes: '',
  size_band: 'medium',
  left_on_table: null,
  left_on_table_pct: null,
  gap_to_winner: '100',
  gap_to_winner_pct: '10.0',
  warnings: [],
};

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <WinLossPage />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.spyOn(winLossApi, 'summary').mockResolvedValue(summary);
  vi.spyOn(winLossApi, 'list').mockResolvedValue([entry]);
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe('WinLossPage', () => {
  it('shows the hit rate and the groups, and switches the grouping', async () => {
    renderPage();
    await screen.findByTestId('winloss-cards');
    expect(screen.getByText('33.3%')).toBeTruthy();
    expect(screen.getByTestId('winloss-groups').textContent).toContain('Acme');
    fireEvent.click(screen.getByRole('button', { name: 'Trade' }));
    expect(screen.getByTestId('winloss-groups').textContent).toContain('steel');
  });

  it('lists the entry with its gap to the winner', async () => {
    renderPage();
    const table = await screen.findByTestId('winloss-entries');
    expect(table.textContent).toContain('Hall A');
    expect(table.textContent).toContain('-');
  });

  it('asks for a reason only on a lost bid and saves the new entry', async () => {
    const create = vi.spyOn(winLossApi, 'create').mockResolvedValue({ ...entry, warnings: [] });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: /Record a bid/ }));
    const form = await screen.findByTestId('winloss-form');
    expect(screen.queryByText('Main reason')).toBeNull();
    const inputs = form.querySelectorAll('input');
    fireEvent.change(inputs[0]!, { target: { value: 'Bridge' } });
    fireEvent.change(form.querySelectorAll('select')[0]!, { target: { value: 'lost' } });
    expect(screen.getByText('Main reason')).toBeTruthy();
    fireEvent.change(form.querySelector('input[type="number"]') as HTMLInputElement, {
      target: { value: '500' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() => expect(create).toHaveBeenCalled());
    expect(create.mock.calls[0]![0]).toMatchObject({ title: 'Bridge', outcome: 'lost', our_price: '500' });
  });

  it('shows the validation warnings that come back after a save', async () => {
    vi.spyOn(winLossApi, 'update').mockResolvedValue({
      ...entry,
      warnings: [
        { rule_id: 'bid_outcome.lost_reason_recorded', severity: 'warning', message: 'Lost bid Hall A has no reason', suggestion: null },
      ],
    });
    renderPage();
    fireEvent.click(await screen.findByRole('button', { name: 'Hall A' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Save' }));
    const box = await screen.findByTestId('winloss-warnings');
    expect(box.textContent).toContain('has no reason');
  });
});
