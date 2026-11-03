// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

import { Snapshot4DView } from './Snapshot4DView';
import { scheduleApi } from './api';

vi.mock('./api', () => ({
  scheduleApi: { getSnapshot: vi.fn(), getSnapshotCost: vi.fn() },
}));
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn().mockResolvedValue({ items: [] }) }));

const SNAPSHOT = {
  schedule_id: 's1',
  as_of_date: '2026-03-14',
  model_version_id: null,
  elements: { e1: 'in_progress', e2: 'not_started' },
};

const COST = {
  schedule_id: 's1',
  as_of_date: '2026-03-14',
  model_version_id: null,
  currency: 'EUR',
  has_cost_data: true,
  totals: { pv: '600.00', ev: '500.00', ac: '550.00', bac: '1000.00' },
  spi: 0.83,
  cpi: 0.91,
  by_status: { in_progress: { elements: 1, planned_cost: '700.00' }, not_started: { elements: 1, planned_cost: '300.00' } },
  elements: {},
  elements_total: 2,
  other_elements_cost: '0.00',
  unlinked_cost: '0.00',
  coverage_pct: 100,
  coverage_low: false,
};

function renderIt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Snapshot4DView
          scheduleId="s1"
          projectId="p1"
          scheduleStart="2026-01-01"
          scheduleEnd="2026-12-31"
        />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Snapshot4DView cost strip', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows PV/EV/AC, the indices and a link to 5D at the date', async () => {
    scheduleApi.getSnapshot.mockResolvedValue(SNAPSHOT);
    scheduleApi.getSnapshotCost.mockResolvedValue(COST);
    renderIt();
    const strip = await screen.findByTestId('snapshot-cost-strip');
    expect(strip.textContent).toContain('SPI 0.83');
    expect(strip.textContent).toContain('CPI 0.91');
    const link = strip.querySelector('a');
    expect(link.getAttribute('href')).toMatch(/^\/5d\?date=\d{4}-\d{2}-\d{2}$/);
  });

  it('hides the strip when the schedule carries no cost data', async () => {
    scheduleApi.getSnapshot.mockResolvedValue(SNAPSHOT);
    scheduleApi.getSnapshotCost.mockResolvedValue({ ...COST, has_cost_data: false });
    renderIt();
    await waitFor(() => expect(scheduleApi.getSnapshotCost).toHaveBeenCalled());
    await screen.findByText(/element\(s\)|elements/i);
    expect(screen.queryByTestId('snapshot-cost-strip')).toBeNull();
  });

  it('refetches the cost when the data date changes', async () => {
    scheduleApi.getSnapshot.mockResolvedValue(SNAPSHOT);
    scheduleApi.getSnapshotCost.mockResolvedValue(COST);
    renderIt();
    await screen.findByTestId('snapshot-cost-strip');
    const before = scheduleApi.getSnapshotCost.mock.calls.length;
    const dates = screen.getAllByLabelText(/Data date/i);
    const input = dates.find((el) => el.getAttribute('type') === 'date');
    fireEvent.change(input, { target: { value: '2026-06-01' } });
    await waitFor(() => expect(scheduleApi.getSnapshotCost.mock.calls.length).toBeGreaterThan(before));
    expect(scheduleApi.getSnapshotCost.mock.calls.at(-1)[1].asOfDate).toBe('2026-06-01');
  });
});
