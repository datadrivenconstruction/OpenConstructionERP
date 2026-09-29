// @ts-nocheck
/**
 * Table view sections and assignee.
 *
 * The harness wires the grid the way ``SchedulePage`` does: collapsed rows are
 * removed from ``activities`` and the section set is read from the whole
 * schedule. Before that, a collapsed section lost its chevron together with
 * its children and could not be expanded again.
 */
import { useMemo, useState } from 'react';
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return { ...actual, scheduleApi: { updateActivity: vi.fn(), reschedule: vi.fn() } };
});
vi.mock('@/features/resources/api', () => ({
  listAssignmentsForActivity: vi.fn(),
  listResources: vi.fn(),
}));
vi.mock('@/features/schedule-advanced/api', () => ({ listCalendars: vi.fn() }));
vi.mock('@/features/contacts/api', () => ({ fetchContacts: vi.fn() }));

import { scheduleApi } from './api';
import { listAssignmentsForActivity, listResources } from '@/features/resources/api';
import { listCalendars } from '@/features/schedule-advanced/api';
import { fetchContacts } from '@/features/contacts/api';
import { ActivityGrid } from './ActivityGrid';
import { hideCollapsed, parentIdsOf } from './activityTree';

const base = {
  start_date: '2024-01-01',
  end_date: '2024-01-05',
  duration_days: 5,
  progress_pct: 0,
  dependencies: [],
};
const SECTION = { ...base, id: 's1', name: 'Earthworks', wbs_code: '1', activity_type: 'summary', parent_id: null };
const CHILD = { ...base, id: 'c1', name: 'Excavate', wbs_code: '1.1', activity_type: 'task', parent_id: 's1' };
const OTHER = {
  ...base,
  id: 'o1',
  name: 'Walls',
  wbs_code: '2',
  activity_type: 'task',
  parent_id: null,
  assignee_id: 'k2',
  // Resolved by the server; k2 is deliberately not in the fetched contacts
  // page below, the way a colleague's pick or the 201st contact is not.
  assignee_name: 'Site Crew GmbH',
};
const ALL = [SECTION, CHILD, OTHER];

function Harness() {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const visible = useMemo(() => hideCollapsed(ALL, collapsed), [collapsed]);
  const sections = useMemo(() => parentIdsOf(ALL), []);
  return (
    <ActivityGrid
      scheduleId="s"
      projectId=""
      activities={visible}
      sectionIds={sections}
      collapsedIds={collapsed}
      onToggleCollapse={(id) =>
        setCollapsed((prev) => {
          const next = new Set(prev);
          if (next.has(id)) next.delete(id);
          else next.add(id);
          return next;
        })
      }
      onEditDependencies={vi.fn()}
      onAddActivity={vi.fn()}
    />
  );
}

function renderHarness() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Harness />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ActivityGrid sections and assignee', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (scheduleApi.updateActivity as any).mockResolvedValue({ id: 'o1' });
    (listCalendars as any).mockResolvedValue([]);
    (listResources as any).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 500 });
    (listAssignmentsForActivity as any).mockResolvedValue([]);
    (fetchContacts as any).mockResolvedValue({
      items: [{ id: 'k1', first_name: 'Ana', last_name: 'Lopez', company_name: null, primary_email: null }],
      total: 500,
    });
  });

  it('collapses a section and expands it again', () => {
    renderHarness();
    expect(screen.getByTestId('grid-row-c1')).toBeInTheDocument();

    fireEvent.click(screen.getByTestId('grid-toggle-s1'));
    expect(screen.queryByTestId('grid-row-c1')).toBeNull();

    // The chevron must still be there to bring the children back.
    const toggle = screen.getByTestId('grid-toggle-s1');
    expect(toggle).toHaveAttribute('aria-expanded', 'false');
    fireEvent.click(toggle);
    expect(screen.getByTestId('grid-row-c1')).toBeInTheDocument();
  });

  it('shows a stored assignee missing from the fetched contacts by its server name', async () => {
    renderHarness();
    const input = screen.getByTestId('grid-assignee-o1-input') as HTMLInputElement;
    expect(input.value).toBe('Site Crew GmbH');
  });

  it('writes a picked contact and a cleared cell through the PATCH', async () => {
    renderHarness();
    const input = screen.getByTestId('grid-assignee-o1-input');
    fireEvent.focus(input);
    fireEvent.click(await screen.findByTestId('grid-assignee-o1-option-contact-k1'));
    await waitFor(() => expect(scheduleApi.updateActivity).toHaveBeenCalledWith('o1', { assignee_id: 'k1' }));

    // Typing alone saves nothing.
    (scheduleApi.updateActivity as any).mockClear();
    fireEvent.change(screen.getByTestId('grid-assignee-c1-input'), { target: { value: 'An' } });
    expect(scheduleApi.updateActivity).not.toHaveBeenCalled();

    fireEvent.click(within(screen.getByTestId('grid-row-o1')).getByRole('button', { name: /Clear/i }));
    await waitFor(() => expect(scheduleApi.updateActivity).toHaveBeenCalledWith('o1', { assignee_id: null }));
  });

  it('moves a row into a section, never into its own subtree', async () => {
    renderHarness();
    const own = screen.getByTestId('grid-section-s1') as HTMLSelectElement;
    // A section is not offered as its own parent.
    expect([...own.options].map((o) => o.value)).toEqual(['']);

    const other = screen.getByTestId('grid-section-o1') as HTMLSelectElement;
    expect([...other.options].map((o) => o.value)).toEqual(['', 's1']);
    fireEvent.change(other, { target: { value: 's1' } });
    await waitFor(() => expect(scheduleApi.updateActivity).toHaveBeenCalledWith('o1', { parent_id: 's1' }));

    const child = screen.getByTestId('grid-section-c1') as HTMLSelectElement;
    expect(child.value).toBe('s1');
    fireEvent.change(child, { target: { value: '' } });
    await waitFor(() => expect(scheduleApi.updateActivity).toHaveBeenCalledWith('c1', { parent_id: null }));
  });
});
