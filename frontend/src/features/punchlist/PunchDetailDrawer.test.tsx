// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// After "Mark Resolved" the drawer kept offering "Mark Resolved" until the
// refetch of the item came back, while the success toast had already said the
// item was resolved. On a slow server that window was long enough to click the
// stale button again. The transition's own response is the item as it now
// stands, so the drawer paints from it at once; the refetch here never answers,
// which is the slow server taken to its limit.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { PunchItem } from './api';

const base: PunchItem = {
  id: 'item-1',
  project_id: 'project-1',
  title: 'Touch up paint at stair 2',
  description: '',
  priority: 'medium',
  status: 'in_progress',
  category: null,
  assigned_to: null,
  assigned_to_name: null,
  due_date: null,
  document_id: null,
  page: null,
  location_x: null,
  location_y: null,
  photos: [],
  trade: null,
  resolution_notes: null,
  verified_by: null,
  verified_by_name: null,
  metadata: {},
  created_by: null,
  created_at: '2026-09-01T00:00:00Z',
  updated_at: '2026-09-01T00:00:00Z',
  resolved_at: null,
  verified_at: null,
  reopen_history: [],
  rework_cost: null,
  rework_cost_currency: '',
};

const fetchPunchItem = vi.fn();
const transitionPunchStatus = vi.fn();

vi.mock('./api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('./api')>();
  return {
    ...actual,
    fetchPunchItem: (...args: unknown[]) => fetchPunchItem(...args),
    transitionPunchStatus: (...args: unknown[]) => transitionPunchStatus(...args),
  };
});

vi.mock('./PunchPhotoGallery', () => ({ PunchPhotoGallery: () => null }));

import { PunchDetailDrawer } from './PunchDetailDrawer';

describe('PunchDetailDrawer after a transition', () => {
  beforeEach(() => {
    fetchPunchItem.mockReset();
    transitionPunchStatus.mockReset();
  });

  it('shows the next actions from the response, without waiting for the refetch', async () => {
    // The first read answers; every read after the transition hangs.
    fetchPunchItem.mockResolvedValueOnce(base).mockImplementation(() => new Promise(() => {}));
    transitionPunchStatus.mockResolvedValue({ ...base, status: 'resolved' });

    const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={qc}>
        <PunchDetailDrawer
          itemId={base.id}
          projectId={base.project_id}
          initialItem={base}
          projectCurrency=""
          onClose={() => {}}
        />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(fetchPunchItem).toHaveBeenCalledTimes(1));
    fireEvent.click(await screen.findByRole('button', { name: /Mark Resolved/i }));

    expect(await screen.findByRole('button', { name: /Verify/i })).toBeTruthy();
    expect(screen.queryByRole('button', { name: /Mark Resolved/i })).toBeNull();
  });
});
