// Page-level tests for the Inspections register: states, filters, create, start/record, guarded actions.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const m = vi.hoisted(() => ({
  fetchInspections: vi.fn(),
  createInspection: vi.fn(),
  completeInspection: vi.fn(),
  updateInspection: vi.fn(),
  deleteInspection: vi.fn(),
  createNcrFromInspection: vi.fn(),
  addToast: vi.fn(),
}));

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  fetchInspections: m.fetchInspections,
  createInspection: m.createInspection,
  completeInspection: m.completeInspection,
  updateInspection: m.updateInspection,
  deleteInspection: m.deleteInspection,
  createNcrFromInspection: m.createNcrFromInspection,
}));
// Online path of the offline-aware writers: send straight through.
vi.mock('@/features/field/offlineWrite', () => ({
  createOrQueue: async (o: { payload: unknown; send: (b: unknown) => Promise<unknown> }) => o.send(o.payload),
  updateOrQueue: async (o: {
    patch: unknown;
    base: { version: number | null };
    send: (b: unknown, v: number | null) => Promise<unknown>;
  }) => o.send(o.patch, o.base.version),
}));
vi.mock('@/shared/lib/offline/useOfflineSync', () => ({ useOfflineRecords: () => [] }));
vi.mock('@/features/field/SyncStatusPill', () => ({ SyncStatusPill: () => null }));
vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: vi.fn(async () => [{ id: 'p1', name: 'Tower A' }]),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (sel: (s: { addToast: typeof m.addToast }) => unknown) => sel({ addToast: m.addToast }),
    { getState: () => ({ addToast: m.addToast }) },
  ),
}));

import { InspectionsPage } from '../InspectionsPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import type { Inspection } from '../api';

function insp(over: Partial<Inspection>): Inspection {
  return {
    id: 'i1',
    project_id: 'p1',
    inspection_number: 'INS-001',
    title: 'Slab pour check',
    inspection_type: 'concrete',
    inspector: 'Eva',
    date: '2026-03-01',
    location: 'Level 2',
    result: null,
    status: 'scheduled',
    checklist: [],
    notes: '',
    created_by: null,
    version: 1,
    created_at: '2026-03-01T00:00:00Z',
    updated_at: '2026-03-01T00:00:00Z',
    ...over,
  };
}
const page = (items: Inspection[], total = items.length) => ({ items, total, offset: 0, limit: 100 });

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <InspectionsPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const expandRow = (title: string) =>
  fireEvent.click(within(screen.getByText(title).closest('[role="button"]') as HTMLElement).getByText(title));

describe('InspectionsPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
    m.fetchInspections.mockResolvedValue(page([]));
  });

  it('shows the empty state and opens the create dialog from it', async () => {
    renderPage();
    expect(await screen.findByText('No inspections yet')).toBeInTheDocument();
    expect(m.fetchInspections).toHaveBeenCalledWith(expect.objectContaining({ project_id: 'p1' }));
    fireEvent.click(screen.getAllByRole('button', { name: /New Inspection/ }).at(-1)!);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('lists inspections with number, title and register total in the stats', async () => {
    m.fetchInspections.mockResolvedValue(
      page(
        [
          insp({ id: 'a', inspection_number: 'INS-001', title: 'Slab pour check' }),
          insp({ id: 'b', inspection_number: 'INS-002', title: 'Fire door check', result: 'pass', status: 'completed' }),
          insp({ id: 'c', inspection_number: 'INS-003', title: 'Riser pressure test', result: 'fail', status: 'failed' }),
        ],
        40,
      ),
    );
    renderPage();
    expect(await screen.findByText('INS-002')).toBeInTheDocument();
    expect(screen.getByText('Fire door check')).toBeInTheDocument();
    // "Total" tile reads the server count (40), not the 3 rows held.
    expect(screen.getByText('40')).toBeInTheDocument();
  });

  it('shows a recovery card and reloads on retry when the register cannot load', async () => {
    m.fetchInspections.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    const retry = await screen.findByRole('button', { name: /retry|try again/i });
    m.fetchInspections.mockResolvedValue(page([insp({ title: 'Loaded after retry' })]));
    fireEvent.click(retry);
    expect(await screen.findByText('Loaded after retry')).toBeInTheDocument();
  });

  it('filters by search text (title or inspector) and reports no match', async () => {
    m.fetchInspections.mockResolvedValue(
      page([
        insp({ id: 'a', title: 'Slab pour check', inspector: 'Eva' }),
        insp({ id: 'b', inspection_number: 'INS-002', title: 'Fire door check', inspector: 'Omar' }),
      ]),
    );
    renderPage();
    await screen.findByText('Slab pour check');
    const search = screen.getByLabelText('Search inspections...');
    fireEvent.change(search, { target: { value: 'omar' } });
    expect(screen.queryByText('Slab pour check')).not.toBeInTheDocument();
    expect(screen.getByText('Fire door check')).toBeInTheDocument();
    fireEvent.change(search, { target: { value: 'zzz' } });
    expect(await screen.findByText('No matching inspections')).toBeInTheDocument();
  });

  it('asks the server for the chosen status and type', async () => {
    m.fetchInspections.mockResolvedValue(page([insp({})]));
    renderPage();
    await screen.findByText('Slab pour check');
    fireEvent.change(screen.getByLabelText('All Statuses'), { target: { value: 'in_progress' } });
    await waitFor(() =>
      expect(m.fetchInspections).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'in_progress' })),
    );
    fireEvent.change(screen.getByLabelText('All Types'), { target: { value: 'electrical' } });
    await waitFor(() =>
      expect(m.fetchInspections).toHaveBeenLastCalledWith(
        expect.objectContaining({ status: 'in_progress', type: 'electrical' }),
      ),
    );
  });

  it('keeps Create disabled until a title is typed, then posts the new inspection', async () => {
    m.createInspection.mockResolvedValue(insp({ id: 'new', title: 'Rebar check' }));
    renderPage();
    await screen.findByText('No inspections yet');
    fireEvent.click(screen.getAllByRole('button', { name: /New Inspection/ }).at(-1)!);
    const dialog = await screen.findByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: /Create Inspection/ });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByPlaceholderText(/Foundation Concrete Pour/), {
      target: { value: 'Rebar check' },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(m.createInspection).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: 'p1', title: 'Rebar check' }),
      ),
    );
    await waitFor(() => expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' })));
    await waitFor(() => expect(screen.queryByRole('dialog')).not.toBeInTheDocument());
  });

  it('toasts the server message and keeps the dialog when create fails', async () => {
    m.createInspection.mockRejectedValue(new Error('Duplicate number'));
    renderPage();
    await screen.findByText('No inspections yet');
    fireEvent.click(screen.getAllByRole('button', { name: /New Inspection/ }).at(-1)!);
    const dialog = await screen.findByRole('dialog');
    fireEvent.change(within(dialog).getByPlaceholderText(/Foundation Concrete Pour/), { target: { value: 'X' } });
    fireEvent.click(within(dialog).getByRole('button', { name: /Create Inspection/ }));
    await waitFor(() =>
      expect(m.addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error', message: 'Duplicate number' }),
      ),
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('starts a scheduled inspection (status transition to in_progress)', async () => {
    m.fetchInspections.mockResolvedValue(page([insp({ id: 'a', status: 'scheduled', version: 3 })]));
    m.updateInspection.mockResolvedValue(insp({ id: 'a', status: 'in_progress' }));
    renderPage();
    await screen.findByText('Slab pour check');
    expandRow('Slab pour check');
    fireEvent.click(await screen.findByRole('button', { name: /Start Inspection/ }));
    await waitFor(() => expect(m.updateInspection).toHaveBeenCalledWith('a', { status: 'in_progress' }, 3));
  });

  it('records a failed result through the Pass / Partial / Fail picker', async () => {
    m.fetchInspections.mockResolvedValue(page([insp({ id: 'a', status: 'in_progress' })]));
    m.completeInspection.mockResolvedValue(insp({ id: 'a', status: 'failed', result: 'fail' }));
    renderPage();
    await screen.findByText('Slab pour check');
    expandRow('Slab pour check');
    expect(screen.queryByRole('button', { name: /Start Inspection/ })).not.toBeInTheDocument();
    fireEvent.click(await screen.findByRole('button', { name: /Record Result/ }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: /^Fail/ }));
    fireEvent.click(within(dialog).getByRole('button', { name: 'Record Result' }));
    await waitFor(() => expect(m.completeInspection).toHaveBeenCalledWith('a', 'fail'));
    await waitFor(() =>
      expect(m.addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'success', message: expect.stringContaining('failed') }),
        expect.anything(),
      ),
    );
  });

  it('offers follow-ups only on failed or partial results and locks editing of finished ones', async () => {
    m.fetchInspections.mockResolvedValue(
      page([
        insp({ id: 'ok', inspection_number: 'INS-010', title: 'Passed one', status: 'completed', result: 'pass' }),
        insp({ id: 'bad', inspection_number: 'INS-011', title: 'Failed one', status: 'failed', result: 'fail' }),
      ]),
    );
    renderPage();
    await screen.findByText('Passed one');
    expandRow('Passed one');
    expect(screen.queryByRole('button', { name: /Create NCR/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Record Result/ })).not.toBeInTheDocument();
    expect(screen.getByTitle('Completed or failed inspections cannot be edited')).toBeDisabled();
    expandRow('Failed one');
    expect(await screen.findByRole('button', { name: /Create NCR/ })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Create Punchlist Item/ })).toBeInTheDocument();
  });

  it('deletes only after confirmation', async () => {
    m.fetchInspections.mockResolvedValue(page([insp({ id: 'a' })]));
    m.deleteInspection.mockResolvedValue(undefined);
    renderPage();
    await screen.findByText('Slab pour check');
    expandRow('Slab pour check');
    fireEvent.click(await screen.findByTitle('Delete'));
    expect(m.deleteInspection).not.toHaveBeenCalled();
    const btns = await screen.findAllByRole('button', { name: 'Delete' });
    fireEvent.click(btns[btns.length - 1]!);
    await waitFor(() => expect(m.deleteInspection).toHaveBeenCalledWith('a'));
  });

  it('does not query and prompts for a project when none is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null } as never);
    const { fetchProjectList } = await import('@/shared/lib/projectList');
    (fetchProjectList as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    renderPage();
    await waitFor(() => expect(screen.queryByText('No inspections yet')).not.toBeInTheDocument());
    expect(m.fetchInspections).not.toHaveBeenCalled();
  });
});
