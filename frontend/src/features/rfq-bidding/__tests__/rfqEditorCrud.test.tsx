// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The RFQ editor must let the user change the header, the scope lines and the
// contacts the RFQ goes to. Lines are editable on a draft only; invitees stay
// editable after the RFQ is out.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  fetchRFQs: vi.fn(),
  updateRFQ: vi.fn(),
  addScopeLine: vi.fn(),
  updateScopeLine: vi.fn(),
  deleteScopeLine: vi.fn(),
  fetchContacts: vi.fn(),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...a: unknown[]) => mocks.fetchRFQs(...a),
    updateRFQ: (...a: unknown[]) => mocks.updateRFQ(...a),
    addScopeLine: (...a: unknown[]) => mocks.addScopeLine(...a),
    updateScopeLine: (...a: unknown[]) => mocks.updateScopeLine(...a),
    deleteScopeLine: (...a: unknown[]) => mocks.deleteScopeLine(...a),
  };
});

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: (...a: unknown[]) => mocks.fetchContacts(...a),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { useAuthStore } from '@/stores/useAuthStore';
import { RFQBiddingPage } from '../RFQBiddingPage';
import type { RFQ, ScopeLine } from '../api';

function line(n: number): ScopeLine {
  return {
    id: `l${n}`,
    rfq_id: 'a',
    line_no: n,
    code: null,
    description: `Ductwork ${n}`,
    unit: 'm2',
    quantity: '10',
    is_optional: false,
    cost_line_id: null,
    notes: null,
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
  };
}

function rfq(status: RFQ['status']): RFQ {
  return {
    id: 'a',
    project_id: 'proj-1',
    rfq_number: 'RFQ-1',
    title: 'Concrete a',
    description: null,
    scope_of_work: null,
    submission_deadline: null,
    currency_code: 'EUR',
    status,
    issued_to_contacts: ['c-1'],
    evaluation_method: 'lowest_price',
    technical_weight: '0',
    require_full_scope: true,
    lines: [line(1)],
    bids: [],
    created_at: '2026-11-01T00:00:00Z',
    updated_at: '2026-11-01T00:00:00Z',
  };
}

const CONTACTS = [
  { id: 'c-1', contact_type: 'supplier', company_name: 'Alpha Supply' },
  { id: 'c-2', contact_type: 'subcontractor', company_name: 'Beta Subcontract' },
  { id: 'c-3', contact_type: 'client', company_name: 'Gamma Client' },
];

function serve(status: RFQ['status']) {
  const items = [rfq(status)];
  mocks.fetchRFQs.mockResolvedValue({ items, total: 1, offset: 0, limit: 50 });
}

beforeEach(() => {
  mocks.updateRFQ.mockResolvedValue(rfq('draft'));
  mocks.addScopeLine.mockResolvedValue(line(2));
  mocks.updateScopeLine.mockResolvedValue(line(1));
  mocks.deleteScopeLine.mockResolvedValue(undefined);
  mocks.fetchContacts.mockImplementation((f?: { contact_type?: string }) =>
    Promise.resolve({
      items: CONTACTS.filter((c) => !f?.contact_type || c.contact_type === f.contact_type),
      total: CONTACTS.length,
    }),
  );
  useAuthStore.setState({ userRole: 'editor' });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

async function openEditor() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <RFQBiddingPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByText('Concrete a');
  fireEvent.click(screen.getByRole('button', { name: 'Edit RFQ' }));
  await screen.findByTestId('rfq-lines');
}

describe('RFQ editor', () => {
  it('lists vendor contacts, leaves out clients, and saves the picked invitees', async () => {
    serve('draft');
    await openEditor();
    await screen.findByText('Beta Subcontract');
    expect(screen.getByText('Alpha Supply')).toBeTruthy();
    expect(screen.queryByText('Gamma Client')).toBeNull();

    const beta = screen.getByText('Beta Subcontract').closest('label')!.querySelector('input')!;
    fireEvent.click(beta);
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() =>
      expect(mocks.updateRFQ).toHaveBeenCalledWith(
        'a',
        expect.objectContaining({ issued_to_contacts: ['c-1', 'c-2'] }),
      ),
    );
  });

  it('filters the picker by contact type through the contacts query', async () => {
    serve('draft');
    await openEditor();
    fireEvent.change(screen.getByLabelText('Contact type'), { target: { value: 'subcontractor' } });
    await waitFor(() =>
      expect(mocks.fetchContacts).toHaveBeenCalledWith(expect.objectContaining({ contact_type: 'subcontractor' })),
    );
  });

  it('adds, changes and deletes scope lines on a draft', async () => {
    serve('draft');
    await openEditor();

    fireEvent.change(screen.getByLabelText('New line description'), { target: { value: 'AHU' } });
    fireEvent.change(screen.getByLabelText('New line unit'), { target: { value: 'pcs' } });
    fireEvent.change(screen.getByLabelText('New line quantity'), { target: { value: '3' } });
    fireEvent.click(screen.getByRole('button', { name: 'Add line' }));
    await waitFor(() =>
      expect(mocks.addScopeLine).toHaveBeenCalledWith('a', { description: 'AHU', unit: 'pcs', quantity: '3' }),
    );

    const row = screen.getByTestId('rfq-line-row');
    fireEvent.change(row.querySelector('input')!, { target: { value: 'Ductwork, level 1' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save line' }));
    await waitFor(() =>
      expect(mocks.updateScopeLine).toHaveBeenCalledWith('a', 'l1', {
        description: 'Ductwork, level 1',
        unit: 'm2',
        quantity: '10',
      }),
    );

    fireEvent.click(screen.getByRole('button', { name: 'Delete line' }));
    await waitFor(() => expect(mocks.deleteScopeLine).toHaveBeenCalledWith('a', 'l1'));
  });

  it('shows the lines read-only once the RFQ is out, invitees still editable', async () => {
    serve('published');
    await openEditor();
    expect(screen.queryByRole('button', { name: 'Add line' })).toBeNull();
    expect(screen.queryByTestId('rfq-line-row')).toBeNull();
    expect(screen.getByText('Ductwork 1')).toBeTruthy();
    await screen.findByText('Beta Subcontract');
  });
});
