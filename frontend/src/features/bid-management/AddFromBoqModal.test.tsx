// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Scope lines could only be typed by hand, so a bid package said nothing about
// which bill positions it priced, and neither did the contract an award drafted
// from it. The modal sends position ids, and the server copies each position
// with its link.

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { AddFromBoqModal, isSectionRow } from './AddFromBoqModal';

vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn(),
  apiPost: vi.fn(),
  apiPatch: vi.fn(),
  apiDelete: vi.fn(),
  getErrorMessage: (e: unknown) => String(e),
}));

import { apiGet, apiPost } from '@/shared/lib/api';

const mockGet = vi.mocked(apiGet);
const mockPost = vi.mocked(apiPost);

const POSITIONS = [
  { id: 'sec', ordinal: '01', description: 'Concrete', unit: '', quantity: 0, unit_rate: 0 },
  { id: 'wall', ordinal: '01.001', description: 'Wall C30/37', unit: 'm3', quantity: 12.5 },
  { id: 'slab', ordinal: '01.002', description: 'Slab', unit: 'm2', quantity: 80 },
];

function renderModal(linked: string[] = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onClose = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <AddFromBoqModal packageId="pkg-1" projectId="p1" linkedPositionIds={linked} onClose={onClose} />
    </QueryClientProvider>,
  );
  return { onClose };
}

beforeEach(() => {
  mockGet.mockReset();
  mockPost.mockReset();
  mockGet.mockImplementation(async (url: string) => {
    if (url.startsWith('/v1/boq/boqs/?project_id=')) return [{ id: 'b1', name: 'Bill' }];
    if (url === '/v1/boq/boqs/b1') return { positions: POSITIONS };
    throw new Error(`unexpected GET ${url}`);
  });
});

describe('AddFromBoqModal', () => {
  it('sends the picked positions to the package', async () => {
    mockPost.mockResolvedValue([{ id: 'line-1' }]);
    const { onClose } = renderModal();

    await userEvent.click(await screen.findByText('Wall C30/37'));
    await userEvent.click(screen.getByRole('button', { name: /Add selected/ }));

    await waitFor(() =>
      expect(mockPost).toHaveBeenCalledWith(
        '/v1/bid-management/bid-packages/pkg-1/lines/from-boq',
        { position_ids: ['wall'] },
      ),
    );
    await waitFor(() => expect(onClose).toHaveBeenCalled());
  });

  it('does not offer section headers, and a linked position cannot be picked again', async () => {
    renderModal(['slab']);

    await screen.findByText('Wall C30/37');
    expect(screen.queryByText('Concrete')).toBeNull();
    const slab = screen.getByText('Slab').closest('label')!.querySelector('input')!;
    expect(slab.disabled).toBe(true);
    expect(isSectionRow(POSITIONS[0]!)).toBe(true);
    expect(isSectionRow(POSITIONS[1]!)).toBe(false);
  });
});
