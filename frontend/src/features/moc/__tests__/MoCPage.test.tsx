// Page-level tests for the Management of Change register: states, filters, create, FSM transitions, guarded actions.
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

const m = vi.hoisted(() => ({
  fetchMoCEntries: vi.fn(),
  createMoCEntry: vi.fn(),
  updateMoCEntry: vi.fn(),
  deleteMoCEntry: vi.fn(),
  transitionMoCEntry: vi.fn(),
  addMoCImpact: vi.fn(),
  deleteMoCImpact: vi.fn(),
  createVR: vi.fn(),
  addToast: vi.fn(),
}));

vi.mock('../api', async (orig) => ({
  ...(await orig<typeof import('../api')>()),
  fetchMoCEntries: m.fetchMoCEntries,
  createMoCEntry: m.createMoCEntry,
  updateMoCEntry: m.updateMoCEntry,
  deleteMoCEntry: m.deleteMoCEntry,
  transitionMoCEntry: m.transitionMoCEntry,
  addMoCImpact: m.addMoCImpact,
  deleteMoCImpact: m.deleteMoCImpact,
}));
vi.mock('@/features/variations/api', async (orig) => ({
  ...(await orig<typeof import('@/features/variations/api')>()),
  createVR: m.createVR,
}));
vi.mock('@/features/claims-evidence', () => ({
  ProvabilityGauge: () => null,
  EvidenceThreadPanel: () => null,
}));
vi.mock('@/shared/lib/projectList', () => ({
  fetchProjectList: vi.fn(async () => [{ id: 'p1', name: 'Tower A' }]),
}));
vi.mock('@/stores/useToastStore', () => ({
  useToastStore: Object.assign(
    (sel: (s: { addToast: typeof m.addToast }) => unknown) => sel({ addToast: m.addToast }),
    { getState: () => ({ addToast: m.addToast }) },
  ),
}));

import { MoCPage } from '../MoCPage';
import { useProjectContextStore } from '@/stores/useProjectContextStore';
import type { MoCEntry } from '../api';

function moc(over: Partial<MoCEntry>): MoCEntry {
  return {
    id: 'm1',
    project_id: 'p1',
    code: 'MOC-001',
    title: 'Switch to precast stairs',
    description: 'Faster erection',
    change_category: 'design',
    risk_level: 'medium',
    proposed_by: null,
    proposed_at: null,
    reviewed_by: null,
    reviewed_at: null,
    review_notes: '',
    decided_by: null,
    decided_at: null,
    decision_notes: '',
    implemented_by: null,
    implemented_at: null,
    cost_impact: '0',
    schedule_delta_days: 0,
    currency: 'EUR',
    status: 'proposed',
    variation_request_id: null,
    variation_order_id: null,
    change_order_id: null,
    metadata: {},
    impacts: [],
    ...over,
  };
}

function renderPage() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>
        <MoCPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}
const expandRow = (title: string) => fireEvent.click(screen.getByText(title));

describe('MoCPage', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useProjectContextStore.setState({ activeProjectId: 'p1' } as never);
    m.fetchMoCEntries.mockResolvedValue([]);
  });

  it('shows the empty state and opens the create form from its action', async () => {
    renderPage();
    expect(await screen.findByText('No change requests yet')).toBeInTheDocument();
    expect(m.fetchMoCEntries).toHaveBeenCalledWith('p1', undefined);
    fireEvent.click(screen.getAllByRole('button', { name: /New change request/ }).at(-1)!);
    expect(await screen.findByRole('dialog')).toBeInTheDocument();
  });

  it('lists change requests with code, title, risk and status', async () => {
    m.fetchMoCEntries.mockResolvedValue([
      moc({ id: 'a', code: 'MOC-001', title: 'Switch to precast stairs', risk_level: 'high' }),
      moc({ id: 'b', code: 'MOC-002', title: 'Add fire damper', status: 'accepted' }),
    ]);
    renderPage();
    expect(await screen.findByText('MOC-002')).toBeInTheDocument();
    expect(screen.getByText('Switch to precast stairs')).toBeInTheDocument();
    expect(screen.getByText('Switch to precast stairs').closest('div')!).toHaveTextContent('High');
    expect(screen.getByText('Add fire damper').closest('div')!).toHaveTextContent('Accepted');
  });

  it('shows a recovery card and reloads on retry when the register cannot load', async () => {
    m.fetchMoCEntries.mockRejectedValueOnce(new Error('boom'));
    renderPage();
    const retry = await screen.findByRole('button', { name: /retry|try again/i });
    m.fetchMoCEntries.mockResolvedValue([moc({ title: 'Loaded after retry' })]);
    fireEvent.click(retry);
    expect(await screen.findByText('Loaded after retry')).toBeInTheDocument();
  });

  it('narrows by search text, risk and category on the client', async () => {
    m.fetchMoCEntries.mockResolvedValue([
      moc({ id: 'a', code: 'MOC-001', title: 'Precast stairs', risk_level: 'high', change_category: 'design' }),
      moc({ id: 'b', code: 'MOC-002', title: 'Fire damper', risk_level: 'low', change_category: 'safety' }),
    ]);
    renderPage();
    await screen.findByText('Precast stairs');
    fireEvent.change(screen.getByLabelText('Search changes...'), { target: { value: 'damper' } });
    expect(screen.queryByText('Precast stairs')).not.toBeInTheDocument();
    expect(screen.getByText('Fire damper')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Search changes...'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('All risk levels'), { target: { value: 'high' } });
    expect(screen.queryByText('Fire damper')).not.toBeInTheDocument();
    expect(screen.getByText('Precast stairs')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('All risk levels'), { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('All categories'), { target: { value: 'safety' } });
    expect(screen.queryByText('Precast stairs')).not.toBeInTheDocument();
    expect(screen.getByText('Fire damper')).toBeInTheDocument();
  });

  it('asks the server for the chosen status and shows the no-match state', async () => {
    renderPage();
    await screen.findByText('No change requests yet');
    fireEvent.change(screen.getByLabelText('All statuses'), { target: { value: 'accepted' } });
    await waitFor(() => expect(m.fetchMoCEntries).toHaveBeenLastCalledWith('p1', 'accepted'));
    expect(await screen.findByText('No matching change requests')).toBeInTheDocument();
  });

  it('keeps Create disabled without a title, then posts the new request', async () => {
    m.createMoCEntry.mockResolvedValue(moc({ id: 'new' }));
    renderPage();
    await screen.findByText('No change requests yet');
    fireEvent.click(screen.getAllByRole('button', { name: /New change request/ }).at(-1)!);
    const dialog = await screen.findByRole('dialog');
    const submit = within(dialog).getByRole('button', { name: /Create change request/ });
    expect(submit).toBeDisabled();
    fireEvent.change(within(dialog).getByPlaceholderText(/Switch facade cladding/), {
      target: { value: 'Relocate riser' },
    });
    expect(submit).toBeEnabled();
    fireEvent.click(submit);
    await waitFor(() =>
      expect(m.createMoCEntry).toHaveBeenCalledWith(
        expect.objectContaining({ project_id: 'p1', title: 'Relocate riser' }),
      ),
    );
    await waitFor(() => expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' })));
  });

  it('offers only the next legal transition per status and hides edit/delete after proposal', async () => {
    m.fetchMoCEntries.mockResolvedValue([
      moc({ id: 'a', title: 'Proposed one', status: 'proposed' }),
      moc({ id: 'b', code: 'MOC-002', title: 'Reviewed one', status: 'reviewed' }),
      moc({ id: 'c', code: 'MOC-003', title: 'Done one', status: 'implemented' }),
    ]);
    renderPage();
    await screen.findByText('Proposed one');

    expandRow('Proposed one');
    expect(await screen.findByRole('button', { name: 'Review' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Accept' })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Edit/ })).toBeInTheDocument();
    expandRow('Proposed one');

    expandRow('Reviewed one');
    expect(await screen.findByRole('button', { name: 'Accept' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Decline' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Delete/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Edit/ })).not.toBeInTheDocument();
    expandRow('Reviewed one');

    expandRow('Done one');
    await waitFor(() => expect(screen.getByText('Done one')).toBeInTheDocument());
    for (const name of ['Review', 'Accept', 'Decline', 'Implement']) {
      expect(screen.queryByRole('button', { name })).not.toBeInTheDocument();
    }
  });

  it('sends the transition with the audit note after confirming in the dialog', async () => {
    m.fetchMoCEntries.mockResolvedValue([moc({ id: 'a', title: 'Reviewed one', status: 'reviewed' })]);
    m.transitionMoCEntry.mockResolvedValue(moc({ id: 'a', status: 'accepted' }));
    renderPage();
    await screen.findByText('Reviewed one');
    expandRow('Reviewed one');
    fireEvent.click(await screen.findByRole('button', { name: 'Accept' }));
    const dialog = await screen.findByRole('dialog');
    expect(m.transitionMoCEntry).not.toHaveBeenCalled();
    fireEvent.change(within(dialog).getByPlaceholderText('Add a short note for the audit trail...'), {
      target: { value: 'Approved by PM' },
    });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Accept' }));
    await waitFor(() => expect(m.transitionMoCEntry).toHaveBeenCalledWith('a', 'accept', 'Approved by PM'));
    await waitFor(() => expect(m.addToast).toHaveBeenCalledWith(expect.objectContaining({ type: 'success' })));
  });

  it('surfaces the server message and keeps the dialog when a transition is rejected', async () => {
    m.fetchMoCEntries.mockResolvedValue([moc({ id: 'a', title: 'Proposed one', status: 'proposed' })]);
    m.transitionMoCEntry.mockRejectedValue(new Error('Invalid transition'));
    renderPage();
    await screen.findByText('Proposed one');
    expandRow('Proposed one');
    fireEvent.click(await screen.findByRole('button', { name: 'Review' }));
    const dialog = await screen.findByRole('dialog');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Review' }));
    await waitFor(() =>
      expect(m.addToast).toHaveBeenCalledWith(
        expect.objectContaining({ type: 'error', message: 'Invalid transition' }),
      ),
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('offers a variation request only for accepted changes not yet linked', async () => {
    m.fetchMoCEntries.mockResolvedValue([
      moc({ id: 'a', title: 'Accepted free', status: 'accepted' }),
      moc({ id: 'b', code: 'MOC-002', title: 'Accepted linked', status: 'accepted', variation_request_id: 'vr1' }),
    ]);
    renderPage();
    await screen.findByText('Accepted free');
    expandRow('Accepted free');
    expect(await screen.findByRole('button', { name: /Create Variation Request/ })).toBeInTheDocument();
    expandRow('Accepted free');
    await waitFor(() => expect(screen.queryByRole('button', { name: /Create Variation Request/ })).not.toBeInTheDocument());
    expandRow('Accepted linked');
    expect(await screen.findByRole('button', { name: 'Implement' })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Create Variation Request/ })).not.toBeInTheDocument();
  });

  it('deletes a proposed request only after confirmation', async () => {
    m.fetchMoCEntries.mockResolvedValue([moc({ id: 'a', title: 'Proposed one' })]);
    m.deleteMoCEntry.mockResolvedValue(undefined);
    renderPage();
    await screen.findByText('Proposed one');
    expandRow('Proposed one');
    fireEvent.click(await screen.findByRole('button', { name: /Delete/ }));
    expect(m.deleteMoCEntry).not.toHaveBeenCalled();
    const btns = await screen.findAllByRole('button', { name: 'Delete' });
    fireEvent.click(btns[btns.length - 1]!);
    await waitFor(() => expect(m.deleteMoCEntry).toHaveBeenCalledWith('a'));
  });

  it('does not query and disables New when no project is selected', async () => {
    useProjectContextStore.setState({ activeProjectId: null } as never);
    const { fetchProjectList } = await import('@/shared/lib/projectList');
    (fetchProjectList as unknown as ReturnType<typeof vi.fn>).mockResolvedValueOnce([]);
    renderPage();
    await waitFor(() => expect(screen.getByRole('button', { name: /New change request/ })).toBeDisabled());
    expect(m.fetchMoCEntries).not.toHaveBeenCalled();
  });
});
