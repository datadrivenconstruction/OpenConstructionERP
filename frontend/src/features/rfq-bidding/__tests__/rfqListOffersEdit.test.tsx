// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFQ list offered delete but no way to correct a title, description or due
// date. Edit opens the RFQ dialog prefilled and saves through the PATCH, for the
// roles the server lets update an RFQ.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ fetchRFQs: vi.fn(), updateRFQ: vi.fn() }));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...args: unknown[]) => mocks.fetchRFQs(...args),
    updateRFQ: (...args: unknown[]) => mocks.updateRFQ(...args),
  };
});

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: () => Promise.resolve({ items: [], total: 0 }),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { useAuthStore } from '@/stores/useAuthStore';
import { RFQBiddingPage } from '../RFQBiddingPage';
import type { RFQ } from '../api';

function rfq(id: string, status: RFQ['status']): RFQ {
  return {
    id,
    project_id: 'proj-1',
    rfq_number: `RFQ-${id}`,
    title: `Concrete ${id}`,
    description: 'C30/37 for the slab',
    scope_of_work: null,
    submission_deadline: '2026-12-15',
    currency_code: 'EUR',
    status,
    issued_to_contacts: [],
    evaluation_method: 'lowest_price',
    technical_weight: '0',
    require_full_scope: true,
    lines: [],
    bids: [],
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
  };
}

beforeEach(() => {
  const items = [rfq('a', 'issued'), rfq('b', 'awarded')];
  mocks.fetchRFQs.mockResolvedValue({ items, total: items.length, offset: 0, limit: 50 });
  mocks.updateRFQ.mockImplementation((id: string, p: Partial<RFQ>) => Promise.resolve({ ...rfq(id, 'issued'), ...p }));
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function mountPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RFQBiddingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('RFQ list edit action', () => {
  it('opens the dialog prefilled and saves the header through the PATCH', async () => {
    useAuthStore.setState({ userRole: 'editor' });
    mountPage();
    await screen.findByText('Concrete a');

    // Offered on the open RFQ, not on the awarded one.
    const edits = screen.getAllByRole('button', { name: 'Edit RFQ' });
    expect(edits).toHaveLength(1);
    fireEvent.click(edits[0]!);

    const title = await screen.findByDisplayValue('Concrete a');
    expect(screen.getByDisplayValue('2026-12-15')).toBeTruthy();
    fireEvent.change(title, { target: { value: 'Concrete a, revised' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(mocks.updateRFQ).toHaveBeenCalledWith('a', {
        title: 'Concrete a, revised',
        description: 'C30/37 for the slab',
        submission_deadline: '2026-12-15',
      }),
    );
  });

  it('is not offered to a viewer', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    mountPage();
    await screen.findByText('Concrete a');
    expect(screen.queryByRole('button', { name: 'Edit RFQ' })).toBeNull();
  });
});
