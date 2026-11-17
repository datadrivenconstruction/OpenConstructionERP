// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({
  getRevisions: vi.fn(),
  getSnapshots: vi.fn(),
  getSnapshot: vi.fn(),
  compareSnapshots: vi.fn(),
  restoreSnapshot: vi.fn(),
  deleteSnapshot: vi.fn(),
  createSnapshot: vi.fn(),
  getActivity: vi.fn(),
  restorePositionField: vi.fn(),
}));

vi.mock('./api', () => ({ boqApi: api }));

import { VersionHistoryDrawer } from './VersionHistoryDrawer';

function rev(label: string, id: string, extra: Record<string, unknown> = {}) {
  return {
    boq_id: id,
    number: Number(label.slice(1)),
    label,
    number_is_derived: false,
    name: `Main estimate (${label})`,
    status: 'draft',
    is_locked: false,
    parent_id: null,
    created_at: '2026-11-01T10:00:00Z',
    created_by: null,
    created_by_name: null,
    grand_total: '1500.00',
    delta_vs_parent: null,
    is_current: false,
    ...extra,
  };
}

const lineage = {
  boq_id: 'r1',
  root_id: 'r0',
  current_in_lineage: true,
  previous_id: 'r0',
  next_id: 'r2',
  revisions: [
    rev('R0', 'r0'),
    rev('R1', 'r1', { is_current: true, parent_id: 'r0', grand_total: '1700.00', delta_vs_parent: '200.00' }),
    rev('R2', 'r2', { parent_id: 'r1', grand_total: '1200.00', delta_vs_parent: '-500.00', created_by_name: 'Dana Field' }),
  ],
};

function renderDrawer(props: Partial<Parameters<typeof VersionHistoryDrawer>[0]> = {}) {
  const onOpenRevision = vi.fn();
  const onCompareRevisions = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <VersionHistoryDrawer
        boqId="r1"
        isOpen
        onClose={() => {}}
        onOpenRevision={onOpenRevision}
        onCompareRevisions={onCompareRevisions}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onOpenRevision, onCompareRevisions };
}

beforeEach(() => {
  Object.values(api).forEach((fn) => fn.mockReset());
  api.getRevisions.mockResolvedValue(lineage);
  api.getSnapshots.mockResolvedValue([]);
});

describe('Revisions tab', () => {
  it('lists the whole lineage, marks the current revision and steps to its neighbours', async () => {
    const { onOpenRevision } = renderDrawer({ initialTab: 'revisions' });
    const current = await screen.findByTestId('revision-R1');
    expect(current).toHaveAttribute('aria-current', 'true');
    expect(screen.getByTestId('revision-R0')).toBeInTheDocument();
    expect(within(screen.getByTestId('revision-R2')).getByText(/Dana Field/)).toBeInTheDocument();

    fireEvent.click(screen.getByRole('button', { name: /Previous/ }));
    expect(onOpenRevision).toHaveBeenLastCalledWith('r0');
    fireEvent.click(screen.getByRole('button', { name: /Next/ }));
    expect(onOpenRevision).toHaveBeenLastCalledWith('r2');
  });

  it('hands two ticked revisions to the compare, older first', async () => {
    const { onCompareRevisions } = renderDrawer({ initialTab: 'revisions' });
    await screen.findByTestId('revision-R2');
    fireEvent.click(within(screen.getByTestId('revision-R2')).getByRole('checkbox'));
    fireEvent.click(within(screen.getByTestId('revision-R0')).getByRole('checkbox'));
    fireEvent.click(screen.getByRole('button', { name: /^Compare$/ }));
    expect(onCompareRevisions).toHaveBeenCalledWith('r0', 'r2');
  });

  it('says so when the lineage cannot be loaded', async () => {
    api.getRevisions.mockRejectedValue(new Error('boom'));
    renderDrawer({ initialTab: 'revisions' });
    expect(await screen.findByRole('alert')).toHaveTextContent('Failed to load revisions.');
  });

  it('is not offered when the host gives no way to navigate', async () => {
    renderDrawer({ onOpenRevision: undefined, onCompareRevisions: undefined });
    await waitFor(() => expect(api.getSnapshots).toHaveBeenCalled());
    expect(screen.queryByRole('button', { name: /Revisions/ })).not.toBeInTheDocument();
  });
});

describe('Snapshots tab', () => {
  const snaps = [
    { id: 's2', boq_id: 'r1', name: 'After review', created_at: '2026-11-02T10:00:00Z', created_by: null, grand_total: 1200, position_count: 1 },
    { id: 's1', boq_id: 'r1', name: 'Issued', created_at: '2026-11-01T10:00:00Z', created_by: null, grand_total: 1500, position_count: 2 },
  ];

  it('views a snapshot read-only without restoring it', async () => {
    api.getSnapshots.mockResolvedValue(snaps);
    api.getSnapshot.mockResolvedValue({
      ...snaps[1],
      snapshot_data: { positions: [{ ordinal: '1', description: 'Slab', unit: 'm3', quantity: 10, unit_rate: 100, total: 1000, sort_order: 0 }], markups: [] },
    });
    renderDrawer();
    const view = await screen.findAllByRole('button', { name: /View/ });
    fireEvent.click(view[1]!);
    expect(await screen.findByText('Slab')).toBeInTheDocument();
    expect(api.getSnapshot).toHaveBeenCalledWith('r1', 's1');
    expect(api.restoreSnapshot).not.toHaveBeenCalled();
  });

  it('compares two ticked snapshots, older as the base, and lists only differences', async () => {
    api.getSnapshots.mockResolvedValue(snaps);
    api.compareSnapshots.mockResolvedValue({
      snapshot_a: snaps[1],
      snapshot_b: snaps[0],
      added: [],
      removed: [{ ordinal: '2', description: 'Walls', change_type: 'removed', fields: { quantity: 5, unit_rate: 100, total: 500 } }],
      changed: [{ ordinal: '1', description: 'Slab', change_type: 'changed', fields: { quantity: { old: 10, new: 12 } } }],
      summary: {
        total_a: '1500', total_b: '1200', total_change_amount: '-300', total_change_percent: -20,
        positions_added: 0, positions_removed: 1, positions_changed: 1,
      },
    });
    renderDrawer();
    const boxes = await screen.findAllByRole('checkbox');
    fireEvent.click(boxes[0]!);
    fireEvent.click(boxes[1]!);
    fireEvent.click(screen.getByRole('button', { name: /^Compare$/ }));
    expect(await screen.findAllByTestId('snapdiff-changed')).toHaveLength(1);
    expect(screen.getAllByTestId('snapdiff-removed')).toHaveLength(1);
    expect(api.compareSnapshots).toHaveBeenCalledWith('r1', 's1', 's2');
    expect(api.restoreSnapshot).not.toHaveBeenCalled();
  });
});

describe('Field history tab', () => {
  function entry(id: string, user: { user_id: string | null; user_name?: string }) {
    return {
      id,
      boq_id: 'r1',
      action: 'position_updated',
      description: 'Updated position',
      details: { quantity: { old: 10, new: 12 } },
      created_at: '2026-11-03T10:00:00Z',
      target_type: 'position',
      target_id: 'p1',
      ...user,
    };
  }

  it('names the recorded author, never invents one, and pages past the first 50', async () => {
    api.getActivity
      .mockResolvedValueOnce({
        activities: [entry('a1', { user_id: 'u1', user_name: 'Dana Field' }), entry('a2', { user_id: null })],
        total: 3,
      })
      .mockResolvedValueOnce({ activities: [entry('a3', { user_id: 'u9' })], total: 3 });
    renderDrawer();
    fireEvent.click(screen.getByRole('button', { name: /Field history/ }));
    expect(await screen.findByText('Dana Field')).toBeInTheDocument();
    expect(screen.getByText('Author not recorded')).toBeInTheDocument();
    expect(api.getActivity).toHaveBeenLastCalledWith('r1', { offset: 0, limit: 50 });

    fireEvent.click(screen.getByRole('button', { name: /Show more/ }));
    expect(await screen.findByText('Unknown user')).toBeInTheDocument();
    expect(api.getActivity).toHaveBeenLastCalledWith('r1', { offset: 2, limit: 50 });
    await waitFor(() => expect(screen.queryByRole('button', { name: /Show more/ })).not.toBeInTheDocument());
  });
});
