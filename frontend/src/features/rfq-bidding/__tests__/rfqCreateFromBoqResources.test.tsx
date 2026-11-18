// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The create dialog can take its scope from BOQ resources: filter by category,
// search, select all shown, and the picked keys go to the server, which turns
// them into scope lines. An empty pick cannot be submitted.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, cleanup, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const mocks = vi.hoisted(() => ({
  fetchRFQs: vi.fn(),
  createRFQ: vi.fn(),
  fetchProjectBoqs: vi.fn(),
  fetchBoqResources: vi.fn(),
}));

vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    fetchRFQs: (...args: unknown[]) => mocks.fetchRFQs(...args),
    createRFQ: (...args: unknown[]) => mocks.createRFQ(...args),
    fetchProjectBoqs: (...args: unknown[]) => mocks.fetchProjectBoqs(...args),
    fetchBoqResources: (...args: unknown[]) => mocks.fetchBoqResources(...args),
  };
});

vi.mock('@/features/contacts/api', () => ({
  fetchContacts: () => Promise.resolve({ items: [], total: 0 }),
}));

vi.mock('@/shared/hooks/useActiveProjectId', () => ({
  useActiveProjectId: () => 'proj-1',
}));

import { RFQBiddingPage } from '../RFQBiddingPage';

const RESOURCES = [
  { key: 'k-labour', name: 'Mason', code: null, category: 'labor', unit: 'h', quantity: '20.0000', position_count: 1 },
  { key: 'k-conc', name: 'Concrete C30/37', code: 'C30', category: 'material', unit: 'm3', quantity: '15.0000', position_count: 2 },
  { key: 'k-rebar', name: 'Rebar B500', code: null, category: 'material', unit: 't', quantity: '1.2000', position_count: 2 },
];

beforeEach(() => {
  mocks.fetchRFQs.mockResolvedValue({ items: [], total: 0, offset: 0, limit: 50 });
  mocks.createRFQ.mockImplementation(() => new Promise(() => {}));
  mocks.fetchProjectBoqs.mockResolvedValue([{ id: 'boq-1', name: 'Main BOQ' }]);
  mocks.fetchBoqResources.mockResolvedValue(RESOURCES);
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

async function openDialogInBoqMode() {
  mountPage();
  fireEvent.click((await screen.findAllByRole('button', { name: /New RFQ/ }))[0]!);
  fireEvent.change(await screen.findByPlaceholderText(/Concrete supply for Block A/), {
    target: { value: 'Concrete package' },
  });
  fireEvent.click(screen.getByRole('radio', { name: /From BOQ resources/ }));
  await screen.findByText('Concrete C30/37');
}

function submitButton(): HTMLButtonElement {
  return screen.getByRole('button', { name: /^Create RFQ$/ }) as HTMLButtonElement;
}

describe('Creating an RFQ from BOQ resources', () => {
  it('lists the BOQ resources and cannot be submitted with nothing picked', async () => {
    await openDialogInBoqMode();
    expect(mocks.fetchBoqResources).toHaveBeenCalledWith('boq-1');
    expect(screen.getByText('Mason')).toBeTruthy();
    expect(submitButton().disabled).toBe(true);
  });

  it('filters by category, selects all shown and sends the picked keys', async () => {
    await openDialogInBoqMode();
    fireEvent.click(screen.getByRole('button', { name: /^Material/ }));
    expect(screen.queryByText('Mason')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: /Select all shown/ }));
    expect(screen.getByTestId('rfq-boq-selected-count').textContent).toMatch(/2/);
    expect(submitButton().disabled).toBe(false);

    fireEvent.click(submitButton());
    await waitFor(() => expect(mocks.createRFQ).toHaveBeenCalled());
    const payload = mocks.createRFQ.mock.calls[0]![0];
    expect(payload).toMatchObject({ project_id: 'proj-1', title: 'Concrete package', boq_id: 'boq-1' });
    expect([...payload.boq_resource_keys].sort()).toEqual(['k-conc', 'k-rebar']);
  });

  it('finds a resource by its code', async () => {
    await openDialogInBoqMode();
    fireEvent.change(screen.getByRole('searchbox'), { target: { value: 'c30' } });
    expect(screen.getByText('Concrete C30/37')).toBeTruthy();
    expect(screen.queryByText('Rebar B500')).toBeNull();
  });

  it('sends no BOQ fields for an empty scope', async () => {
    mountPage();
    fireEvent.click((await screen.findAllByRole('button', { name: /New RFQ/ }))[0]!);
    fireEvent.change(await screen.findByPlaceholderText(/Concrete supply for Block A/), {
      target: { value: 'Ductwork' },
    });
    fireEvent.click(submitButton());
    await waitFor(() => expect(mocks.createRFQ).toHaveBeenCalled());
    const payload = mocks.createRFQ.mock.calls[0]![0];
    expect(payload.boq_resource_keys).toBeUndefined();
    expect(payload.boq_id).toBeUndefined();
  });
});
