// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { afterEach, describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import { usePreferencesStore } from '@/stores/usePreferencesStore';
import type { Ticket } from '../api';

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return { ...actual, fetchTickets: vi.fn() };
});

import { fetchTickets } from '../api';
import { HaulTicketsPage } from '../HaulTicketsPage';

function ticket(over: Partial<Ticket>): Ticket {
  return {
    id: crypto.randomUUID(),
    project_id: 'p1',
    ticket_number: 'T-1',
    haul_type: 'aggregates',
    direction: 'in',
    ticket_date: '2026-10-30',
    origin: '',
    destination: '',
    material_name: 'Gravel',
    unit: 't',
    gross_t: null,
    tare_t: null,
    net_t: '231.000',
    volume_m3: null,
    loads: 0,
    quantity: '231.000',
    haulier_name: 'Kies AG',
    plate: '',
    driver_name: '',
    rate_basis: 't',
    rate: '5',
    currency: 'EUR',
    amount: '1140.00',
    status: 'verified',
    reject_reason: '',
    receiver_name: '',
    has_signature: false,
    findings: [],
    ...over,
  };
}

describe('HaulTicketsPage', () => {
  afterEach(() => usePreferencesStore.setState({ numberLocale: 'auto' }));

  it('totals tonnes and loads apart and writes rows in the reader locale', async () => {
    usePreferencesStore.setState({ numberLocale: 'de-DE' });
    useProjectContextStore.setState({ activeProjectId: 'p1', activeProjectName: 'Riverside' });
    vi.mocked(fetchTickets).mockResolvedValue({
      items: [
        ticket({ ticket_number: 'T-1', net_t: '672.000', amount: '1140.00' }),
        ticket({ ticket_number: 'T-2', unit: 'load', net_t: null, loads: 88, amount: '0.00' }),
      ],
      total: 2,
      offset: 0,
      limit: 50,
    });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter>
          <HaulTicketsPage />
        </MemoryRouter>
      </QueryClientProvider>,
    );
    const row = (await screen.findByText('T-1')).closest('tr')!;
    expect(row).toHaveTextContent('672');
    expect(row).toHaveTextContent('1.140,00');
    expect(row).not.toHaveTextContent('2026-10-30');
    const totals = screen.getByTestId('haul-totals');
    expect(totals).toHaveTextContent('Tonnes: 672');
    expect(totals).toHaveTextContent('Loads: 88');
    expect(totals).not.toHaveTextContent('760');
  });
});
