// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Issuing an RFQ is one way: once issued it is no longer a draft and the server
// refuses to delete it. The Issue button fired on one click, and it did so for
// an RFQ with no scope lines, leaving an undeletable record vendors could not
// price. It now asks first and is not offered for an empty scope.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, cleanup, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({ fetchRFQs: vi.fn(), issueRFQ: vi.fn() }));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...args: unknown[]) => mocks.fetchRFQs(...args),
    issueRFQ: (...args: unknown[]) => mocks.issueRFQ(...args),
  };
});

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: () => Promise.resolve({ items: [], total: 0 }),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { RFQBiddingPage } from '../RFQBiddingPage';
import type { RFQ } from '../api';

function draft(id: string, lines: unknown[]): RFQ {
  return {
    id,
    project_id: 'proj-1',
    rfq_number: `RFQ-${id}`,
    title: `Draft ${id}`,
    description: null,
    scope_of_work: null,
    submission_deadline: '2026-10-15',
    currency_code: 'EUR',
    status: 'draft',
    issued_to_contacts: [],
    evaluation_method: 'lowest_price',
    technical_weight: '0',
    require_full_scope: true,
    lines: lines as RFQ['lines'],
    bids: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
  };
}

const RFQS = [draft('r-scoped', [{ id: 'l-1', description: 'Slab', quantity: '10', unit: 'm3' }]), draft('r-empty', [])];

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({ items: RFQS, total: RFQS.length, offset: 0, limit: 50 });
  mocks.issueRFQ.mockResolvedValue({ ...RFQS[0], status: 'issued' });
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

async function issueButtonOf(title: string): Promise<HTMLButtonElement> {
  const heading = await screen.findByText(title);
  let row: HTMLElement | null = heading;
  while (row && !within(row).queryByRole('button', { name: /^Issue$/ })) row = row.parentElement;
  if (!row) throw new Error(`no Issue button near ${title}`);
  return within(row).getByRole('button', { name: /^Issue$/ }) as HTMLButtonElement;
}

describe('Issuing an RFQ', () => {
  it('is not offered for an RFQ without scope lines', async () => {
    mountPage();
    const button = await issueButtonOf('Draft r-empty');
    expect(button.disabled).toBe(true);
    expect(button.title).toBe('Add at least one scope line before issuing');
  });

  it('asks first and does nothing when cancelled', async () => {
    mountPage();
    fireEvent.click(await issueButtonOf('Draft r-scoped'));
    const dialog = await screen.findByRole('alertdialog');
    expect(within(dialog).getByText('Issue this RFQ?')).toBeTruthy();
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(mocks.issueRFQ).not.toHaveBeenCalled();
  });

  it('issues once confirmed', async () => {
    mountPage();
    fireEvent.click(await issueButtonOf('Draft r-scoped'));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Issue' }));
    await waitFor(() => expect(mocks.issueRFQ).toHaveBeenCalledWith('r-scoped'));
  });
});
