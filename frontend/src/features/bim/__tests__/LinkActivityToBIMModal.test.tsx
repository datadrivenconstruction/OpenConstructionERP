// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// Linking BIM elements to a schedule activity.
//
// The dialog merged the new element ids into the activity it had cached and
// PATCHed the whole list back, which the server stores as given. Linking A and
// then B to the same activity inside the cache lifetime sent [B] the second
// time and erased A. It now sends only the new ids with mode "add", and the
// server merges them into what it has stored.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, fireEvent, waitFor, cleanup } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const mocks = vi.hoisted(() => ({ apiGet: vi.fn(), updateActivityBIMLinks: vi.fn() }));

vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: (...args: unknown[]) => mocks.apiGet(...args),
}));

vi.mock('../api', () => ({
  updateActivityBIMLinks: (...args: unknown[]) => mocks.updateActivityBIMLinks(...args),
}));

import LinkActivityToBIMModal from '../LinkActivityToBIMModal';

const ACTIVITY = {
  id: 'act-1',
  schedule_id: 'sch-1',
  name: 'Pour slab',
  start_date: '2026-05-04',
  end_date: '2026-05-15',
  status: 'not_started',
  percent_complete: 0,
  // What the cached list says: no links yet, although the server may have some.
  bim_element_ids: [],
};

beforeEach(() => {
  mocks.apiGet.mockImplementation((url: string) =>
    Promise.resolve(
      url.includes('/activities/')
        ? { items: [ACTIVITY], total: 1 }
        : { items: [{ id: 'sch-1', project_id: 'p-1', name: 'Main' }], total: 1 },
    ),
  );
  mocks.updateActivityBIMLinks.mockResolvedValue({});
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function linkOnce(client: QueryClient, elementId: string) {
  const onClose = vi.fn();
  const view = render(
    <QueryClientProvider client={client}>
      <LinkActivityToBIMModal
        projectId="p-1"
        elements={[{ id: elementId } as never]}
        onClose={onClose}
      />
    </QueryClientProvider>,
  );
  return { view, onClose };
}

describe('LinkActivityToBIMModal', () => {
  it('sends only the new ids and lets the server merge them', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 120_000 } } });

    const first = linkOnce(client, 'el-A');
    fireEvent.click(await screen.findByText('Pour slab'));
    await waitFor(() => expect(first.onClose).toHaveBeenCalled());
    first.view.unmount();

    const second = linkOnce(client, 'el-B');
    fireEvent.click(await screen.findByText('Pour slab'));
    await waitFor(() => expect(second.onClose).toHaveBeenCalled());

    expect(mocks.updateActivityBIMLinks.mock.calls).toEqual([
      ['act-1', ['el-A'], 'add'],
      ['act-1', ['el-B'], 'add'],
    ]);
  });

  it('drops the cached activities after a link', async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const spy = vi.spyOn(client, 'invalidateQueries');

    const { onClose } = linkOnce(client, 'el-A');
    fireEvent.click(await screen.findByText('Pour slab'));
    await waitFor(() => expect(onClose).toHaveBeenCalled());

    expect(spy).toHaveBeenCalledWith({ queryKey: ['activities-for-bim-link'] });
  });
});
