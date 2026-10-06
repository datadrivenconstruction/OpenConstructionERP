// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// "Link from model" in the BOQ editor opens the BIM page for one position.
// When the user then links the elements they picked, the dialog has to land
// on that BOQ (not the project's first one) and offer that position first,
// even for a bulk selection, which otherwise opens on "Create new position".

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  get: vi.fn(),
  createLink: vi.fn(),
  apiPost: vi.fn(),
}));

vi.mock('@/features/boq/api', () => ({
  boqApi: { list: (...a: unknown[]) => mocks.list(...a), get: (...a: unknown[]) => mocks.get(...a) },
}));

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiPost: (...a: unknown[]) => mocks.apiPost(...a),
}));

vi.mock('../api', () => ({
  createLink: (...a: unknown[]) => mocks.createLink(...a),
  resolveElementUUID: (_modelId: string, el: { id: string }) => Promise.resolve(el.id),
}));

import AddToBOQModal from '../AddToBOQModal';
import type { BIMElementData } from '@/shared/ui/BIMViewer';

const el = (id: string) =>
  ({ id, name: `Wall ${id}`, element_type: 'Walls', quantities: { area_m2: 10 }, properties: {} }) as unknown as BIMElementData;

beforeEach(() => {
  mocks.list.mockResolvedValue([
    { id: 'boq-a', name: 'Shell', is_locked: false },
    { id: 'boq-b', name: 'Finishes', is_locked: false },
  ]);
  mocks.get.mockImplementation((id: string) =>
    Promise.resolve({
      id,
      positions:
        id === 'boq-b'
          ? [
              { id: 'pos-1', ordinal: '02.010', description: 'Plaster', unit: 'm2', quantity: 0, parent_id: null },
              { id: 'pos-2', ordinal: '02.020', description: 'Paint', unit: 'm2', quantity: 0, parent_id: null },
            ]
          : [{ id: 'pos-x', ordinal: '01.010', description: 'Concrete', unit: 'm3', quantity: 0, parent_id: null }],
    }),
  );
  mocks.createLink.mockResolvedValue({});
  mocks.apiPost.mockResolvedValue([]);
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function renderModal(props: Partial<Parameters<typeof AddToBOQModal>[0]> = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AddToBOQModal projectId="p-1" modelId="m-1" elements={[el('e1'), el('e2')]} onClose={vi.fn()} {...props} />
    </QueryClientProvider>,
  );
}

describe('AddToBOQModal with a target position', () => {
  it('opens on the target BOQ and offers the target position first, for a bulk selection', async () => {
    renderModal({ initialBoqId: 'boq-b', targetPositionId: 'pos-2' });
    const target = await screen.findByTestId('add-to-boq-target-position');
    expect(target.textContent).toContain('02.020');
    expect(mocks.get).toHaveBeenCalledWith('boq-b');
    fireEvent.click(target);
    await waitFor(() => expect(mocks.createLink).toHaveBeenCalledTimes(2));
    expect(mocks.createLink.mock.calls.every((c) => c[0].boq_position_id === 'pos-2')).toBe(true);
  });

  it('keeps the old behaviour without a target', async () => {
    renderModal();
    await waitFor(() => expect(mocks.list).toHaveBeenCalled());
    expect(screen.queryByTestId('add-to-boq-target-position')).toBeNull();
  });
});
