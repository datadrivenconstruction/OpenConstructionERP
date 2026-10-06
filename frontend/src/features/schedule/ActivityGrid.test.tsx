// @ts-nocheck
/**
 * Smoke tests for the editable activity grid (schedule "Table" view).
 *
 * Network is stubbed via ``vi.mock`` on the schedule ``./api`` module. We assert
 * that inline edits write through ``updateActivity`` with the right body: a name
 * edit sends just the name; a start edit shifts the end by the same number of
 * calendar days (moving the bar, preserving the span); an end edit sends just
 * the end; and an end that falls before the start is rejected client-side (no
 * PATCH). We also assert the Reschedule button calls ``reschedule`` and the
 * predecessors / add cells fire their callbacks so the parent can open the
 * shared dependency editor / add-activity modal.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    scheduleApi: {
      updateActivity: vi.fn(),
      reschedule: vi.fn(),
      deleteActivity: vi.fn(),
    },
  };
});

// The Resources column reads the resources module, and the calendar picker
// reads schedule-advanced. Both are gated on ``projectId``, which most of these
// cases do not pass, but the modules are imported either way.
vi.mock('@/features/resources/api', () => ({
  listAssignmentsForActivity: vi.fn(),
  listResources: vi.fn(),
}));

vi.mock('@/features/schedule-advanced/api', () => ({
  listCalendars: vi.fn(),
}));

import { scheduleApi } from './api';
import { listAssignmentsForActivity, listResources } from '@/features/resources/api';
import { listCalendars } from '@/features/schedule-advanced/api';
import { ActivityGrid } from './ActivityGrid';
import { useAuthStore } from '@/stores/useAuthStore';

const A = {
  id: 'a1',
  name: 'Foundation',
  wbs_code: '01',
  start_date: '2024-01-01',
  end_date: '2024-01-05',
  duration_days: 5,
  progress_pct: 0,
  activity_type: 'task',
  dependencies: [],
};
const B = {
  id: 'a2',
  name: 'Walls',
  wbs_code: '02',
  start_date: '2024-01-08',
  end_date: '2024-01-12',
  duration_days: 5,
  progress_pct: 40,
  activity_type: 'task',
  dependencies: [{ activity_id: 'a1', type: 'FS', lag_days: 0 }],
};
const ACTIVITIES = [A, B];

function renderGrid(props = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const merged = {
    scheduleId: 's1',
    activities: ACTIVITIES,
    onEditDependencies: vi.fn(),
    onAddActivity: vi.fn(),
    ...props,
  };
  const utils = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ActivityGrid {...merged} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  return { ...utils, props: merged };
}

describe('ActivityGrid', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (scheduleApi.updateActivity as any).mockResolvedValue({ id: 'a1' });
    (scheduleApi.reschedule as any).mockResolvedValue([]);
    (listCalendars as any).mockResolvedValue([]);
    (listResources as any).mockResolvedValue({
      items: [
        { id: 'r1', code: 'CREW-A', name: 'Crew A' },
        { id: 'r2', code: 'EXC-1', name: 'Excavator 1' },
      ],
      total: 2,
      offset: 0,
      limit: 500,
    });
    (listAssignmentsForActivity as any).mockResolvedValue([]);
  });

  it('renders one row per activity', () => {
    renderGrid();
    expect(screen.getByTestId('activity-grid')).toBeInTheDocument();
    expect(screen.getByTestId('grid-row-a1')).toBeInTheDocument();
    expect(screen.getByTestId('grid-row-a2')).toBeInTheDocument();
  });

  it('commits a name edit as just the name', async () => {
    renderGrid();
    const input = screen.getByTestId('grid-name-a1');
    fireEvent.change(input, { target: { value: 'Footings' } });
    fireEvent.blur(input);
    await waitFor(() =>
      expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', { name: 'Footings' }),
    );
  });

  it('does not PATCH when a name is unchanged', () => {
    renderGrid();
    const input = screen.getByTestId('grid-name-a1');
    fireEvent.blur(input);
    expect(scheduleApi.updateActivity).not.toHaveBeenCalled();
  });

  it('shifts the end by the same delta when the start moves', async () => {
    renderGrid();
    const start = screen.getByTestId('grid-start-a1');
    // 2024-01-01 -> 2024-01-03 is +2 days, so the 2024-01-05 end becomes 2024-01-07.
    fireEvent.change(start, { target: { value: '2024-01-03' } });
    fireEvent.blur(start);
    await waitFor(() =>
      expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', {
        start_date: '2024-01-03',
        end_date: '2024-01-07',
      }),
    );
  });

  it('commits an end edit as just the end', async () => {
    renderGrid();
    const end = screen.getByTestId('grid-end-a1');
    fireEvent.change(end, { target: { value: '2024-01-09' } });
    fireEvent.blur(end);
    await waitFor(() =>
      expect(scheduleApi.updateActivity).toHaveBeenCalledWith('a1', { end_date: '2024-01-09' }),
    );
  });

  it('rejects an end before the start without PATCHing', () => {
    renderGrid();
    const end = screen.getByTestId('grid-end-a1');
    fireEvent.change(end, { target: { value: '2023-12-30' } });
    fireEvent.blur(end);
    expect(scheduleApi.updateActivity).not.toHaveBeenCalled();
  });

  it('recomputes dates via reschedule', async () => {
    renderGrid();
    fireEvent.click(screen.getByTestId('grid-reschedule'));
    await waitFor(() => expect(scheduleApi.reschedule).toHaveBeenCalledWith('s1'));
  });

  it('opens the dependency editor for a row', () => {
    const { props } = renderGrid();
    fireEvent.click(screen.getByTestId('grid-deps-a1'));
    expect(props.onEditDependencies).toHaveBeenCalledWith('a1');
  });

  it('asks the parent to add an activity', () => {
    const { props } = renderGrid();
    fireEvent.click(screen.getByTestId('grid-add-activity'));
    expect(props.onAddActivity).toHaveBeenCalled();
  });

  // ── Resources column (#191) ─────────────────────────────────────────────

  it('asks who is booked on each row, scoped to the project', async () => {
    renderGrid({ projectId: 'p1' });
    await waitFor(() => expect(listAssignmentsForActivity).toHaveBeenCalledTimes(2));
    expect(listAssignmentsForActivity).toHaveBeenCalledWith('a1', { project_id: 'p1' });
    expect(listAssignmentsForActivity).toHaveBeenCalledWith('a2', { project_id: 'p1' });
  });

  it('names the resources booked on an activity', async () => {
    (listAssignmentsForActivity as any).mockImplementation(async (id: string) =>
      id === 'a1'
        ? [
            { id: 'as1', resource_id: 'r1', status: 'confirmed' },
            { id: 'as2', resource_id: 'r2', status: 'proposed' },
          ]
        : [],
    );
    renderGrid({ projectId: 'p1' });
    await waitFor(() =>
      expect(screen.getByTestId('grid-resources-a1').textContent).toContain('Crew A'),
    );
    expect(screen.getByTestId('grid-resources-a1').textContent).toContain('Excavator 1');
    // The row nobody is booked on says so rather than borrowing a name.
    await waitFor(() =>
      expect(screen.getByTestId('grid-resources-a2').textContent).toBe('-'),
    );
  });

  it('leaves a cancelled booking out of the column', async () => {
    (listAssignmentsForActivity as any).mockImplementation(async (id: string) =>
      id === 'a1' ? [{ id: 'as1', resource_id: 'r1', status: 'cancelled' }] : [],
    );
    renderGrid({ projectId: 'p1' });
    await waitFor(() =>
      expect(screen.getByTestId('grid-resources-a1').textContent).toBe('-'),
    );
  });

  it('admits a booking whose resource the register did not return', async () => {
    (listAssignmentsForActivity as any).mockImplementation(async (id: string) =>
      id === 'a1' ? [{ id: 'as1', resource_id: 'r-gone', status: 'confirmed' }] : [],
    );
    renderGrid({ projectId: 'p1' });
    await waitFor(() =>
      expect(screen.getByTestId('grid-resources-a1').textContent).toContain(
        'Unnamed resource',
      ),
    );
  });

  it('claims nothing about bookings when there is no project to scope them', () => {
    renderGrid();
    expect(listAssignmentsForActivity).not.toHaveBeenCalled();
    expect(screen.getByTestId('grid-resources-a1').textContent).toBe('');
  });
});

describe('ActivityGrid delete', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    useAuthStore.setState({ userRole: 'editor' });
    (scheduleApi.deleteActivity as any).mockResolvedValue(undefined);
    (listCalendars as any).mockResolvedValue([]);
    (listResources as any).mockResolvedValue({ items: [], total: 0, offset: 0, limit: 500 });
    (listAssignmentsForActivity as any).mockResolvedValue([]);
  });

  it('asks before deleting a row and deletes only on confirm', async () => {
    renderGrid();
    fireEvent.click(screen.getByTestId('grid-delete-a1'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Foundation');
    expect(scheduleApi.deleteActivity).not.toHaveBeenCalled();

    fireEvent.click(within(dialog).getByRole('button', { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByRole('alertdialog')).toBeNull());
    expect(scheduleApi.deleteActivity).not.toHaveBeenCalled();

    fireEvent.click(screen.getByTestId('grid-delete-a1'));
    const again = await screen.findByRole('alertdialog');
    fireEvent.click(within(again).getByRole('button', { name: /^delete$/i }));
    await waitFor(() => expect(scheduleApi.deleteActivity).toHaveBeenCalledWith('a1', false));
  });

  const S = { ...A, id: 's1', name: 'Earthworks', activity_type: 'summary' };
  const SUB = { ...A, id: 'sub', name: 'Trenches', activity_type: 'summary', parent_id: 's1' };
  const C1 = { ...A, id: 'k1', name: 'Dig', parent_id: 'sub' };
  const C2 = { ...B, id: 'k2', name: 'Fill', parent_id: 's1' };

  it('offers a viewer no delete, which the server would refuse', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    renderGrid({ activities: [S, SUB, C1, C2], allActivities: [S, SUB, C1, C2] });
    expect(await screen.findByTestId('grid-deps-s1')).toBeInTheDocument();
    expect(screen.queryByTestId('grid-delete-s1')).toBeNull();
  });

  it('asks whether a section goes with its activities, counted at every depth', async () => {
    renderGrid({ activities: [S, SUB, C1, C2], allActivities: [S, SUB, C1, C2] });
    fireEvent.click(screen.getByTestId('grid-delete-s1'));
    const dialog = await screen.findByRole('alertdialog');
    expect(dialog).toHaveTextContent('Earthworks');
    expect(dialog).toHaveTextContent(/move up one level/);
    expect(within(dialog).getByTestId('activity-delete-with-children')).toHaveTextContent('3');
    fireEvent.click(within(dialog).getByTestId('activity-delete-with-children'));
    await waitFor(() => expect(scheduleApi.deleteActivity).toHaveBeenCalledWith('s1', true));
  });

  it('deletes only the section when its activities are kept', async () => {
    renderGrid({ activities: [S, SUB, C1, C2], allActivities: [S, SUB, C1, C2] });
    fireEvent.click(screen.getByTestId('grid-delete-s1'));
    const dialog = await screen.findByRole('alertdialog');
    fireEvent.click(within(dialog).getByTestId('activity-delete-keep-children'));
    await waitFor(() => expect(scheduleApi.deleteActivity).toHaveBeenCalledWith('s1', false));
  });
});
