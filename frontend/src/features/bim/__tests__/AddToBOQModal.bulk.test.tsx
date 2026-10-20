// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Linking a category of 370 beams fired 370 sequential POSTs, offered only
// "count" (the viewer's skeleton rows carry no quantities) and dead-ended
// when the project had no bid schedule.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  create: vi.fn(),
  addPosition: vi.fn(),
  createLinksBulk: vi.fn(),
  byIds: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock('@/features/boq/api', () => ({
  boqApi: {
    list: (...a: unknown[]) => mocks.list(...a),
    get: (...a: unknown[]) => mocks.get(...a),
    create: (...a: unknown[]) => mocks.create(...a),
    addPosition: (...a: unknown[]) => mocks.addPosition(...a),
  },
}));

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiPost: (...a: unknown[]) => mocks.apiPost(...a),
}));

vi.mock('../api', () => ({
  createLinksBulk: (...a: unknown[]) => mocks.createLinksBulk(...a),
  fetchBIMElementsByIds: (...a: unknown[]) => mocks.byIds(...a),
  resolveElementUUID: (_modelId: string, el: { id: string }) => Promise.resolve(el.id),
}));

import AddToBOQModal, { availableQuantityKinds } from '../AddToBOQModal';
import type { BIMElementData } from '@/shared/ui/BIMViewer';

/** Skeleton row as the viewer hands it over: no quantities. */
const skeleton = (id: string) =>
  ({ id, name: `Beam ${id}`, element_type: 'Structural Framing', quantities: {}, properties: {} }) as unknown as BIMElementData;

const beams = Array.from({ length: 150 }, (_, i) => skeleton(`b${i}`));

beforeEach(() => {
  mocks.list.mockResolvedValue([{ id: 'boq-a', name: 'Shell', is_locked: false }]);
  mocks.get.mockResolvedValue({ id: 'boq-a', positions: [] });
  mocks.addPosition.mockResolvedValue({ id: 'pos-new' });
  mocks.createLinksBulk.mockResolvedValue({ created: 150, skipped: 0 });
  mocks.apiPost.mockResolvedValue([]);
  mocks.byIds.mockImplementation((_m: string, ids: string[]) =>
    Promise.resolve({ items: ids.map((id) => ({ ...skeleton(id), quantities: { Length: 2 } })), total: ids.length }),
  );
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderModal(elements: BIMElementData[] = beams) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AddToBOQModal projectId="p-1" modelId="m-1" elements={elements} onClose={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe('AddToBOQModal bulk linking', () => {
  it('creates the position and links the whole selection with one request', async () => {
    renderModal();
    const kinds = await screen.findByTestId('add-to-boq-qty-kinds');
    // Full rows arrive in chunks of 100; the beams carry length, so the form
    // moves to it on its own.
    await waitFor(() =>
      expect(within(kinds).getByRole('radio', { name: 'Length' }).getAttribute('aria-checked')).toBe('true'),
    );
    expect(mocks.byIds).toHaveBeenCalledTimes(2);
    await screen.findByDisplayValue('300.000');
    fireEvent.click(screen.getByText('Create position and link'));
    await waitFor(() => expect(mocks.createLinksBulk).toHaveBeenCalledTimes(1));
    expect(mocks.createLinksBulk.mock.calls[0]![1]).toHaveLength(150);
    const pos = mocks.addPosition.mock.calls[0]![0] as { unit: string; quantity: number };
    expect(pos.unit).toBe('m');
    expect(pos.quantity).toBe(300);
  });

  it('lets the user switch the quantity to count', async () => {
    renderModal();
    const kinds = await screen.findByTestId('add-to-boq-qty-kinds');
    await waitFor(() => expect(within(kinds).getByRole('radio', { name: 'Length' })).toBeTruthy());
    fireEvent.click(within(kinds).getByRole('radio', { name: 'Count' }));
    await screen.findByDisplayValue('150.000');
    fireEvent.click(screen.getByText('Create position and link'));
    await waitFor(() => expect(mocks.addPosition).toHaveBeenCalled());
    const pos = mocks.addPosition.mock.calls[0]![0] as { unit: string; quantity: number };
    expect(pos.unit).toBe('pcs');
    expect(pos.quantity).toBe(150);
  });

  it('offers to create a bid schedule when the project has none', async () => {
    const created = { id: 'boq-new', name: 'Bid schedule', is_locked: false };
    mocks.list.mockResolvedValueOnce([]).mockResolvedValue([created]);
    mocks.create.mockResolvedValue(created);
    renderModal([skeleton('x1')]);
    const create = await screen.findByTestId('add-to-boq-create-boq');
    fireEvent.click(create);
    await waitFor(() => expect(mocks.create).toHaveBeenCalledWith({ project_id: 'p-1', name: 'Bid schedule' }));
    await waitFor(() => expect(screen.queryByTestId('add-to-boq-create-boq')).toBeNull());
  });
});

describe('availableQuantityKinds', () => {
  it('always offers count and adds the measures the elements carry', () => {
    const rows = [
      { id: 'a', quantities: { area_m2: 4, volume_m3: 1 } },
      { id: 'b', quantities: {} },
    ] as unknown as BIMElementData[];
    expect(availableQuantityKinds(rows).map((k) => k.unit)).toEqual(['pcs', 'm2', 'm3']);
    expect(availableQuantityKinds([{ id: 'c' } as BIMElementData]).map((k) => k.unit)).toEqual(['pcs']);
  });
});
