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
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    scheduleApi: {
      updateActivity: vi.fn(),
      reschedule: vi.fn(),
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

// The shared setup stubs ``useNavigate`` with a throwaway spy, so a click-through
// assertion needs its own handle on the navigate the component actually calls.
const navigateSpy = vi.hoisted(() => vi.fn());
vi.mock('react-router-dom', async () => {
  const actual = await vi.importActual<typeof import('react-router-dom')>('react-router-dom');
  return {
    ...actual,
    useNavigate: () => navigateSpy,
    useParams: () => ({}),
    useSearchParams: () => [new URLSearchParams(), vi.fn()],
  };
});

import { scheduleApi } from './api';
import { listAssignmentsForActivity, listResources } from '@/features/resources/api';
import { listCalendars } from '@/features/schedule-advanced/api';
import { ActivityGrid } from './ActivityGrid';

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

/* ── Delivery column (work-requests / team-standup integration) ─────────
   The grid is handed a prebuilt index rather than fetching anything itself,
   so these cases are about what it *renders* and where a chip *goes*. The
   modules being absent is modelled the way the page models it: no `delivery`
   prop at all, which is what `useDeliveryData` produces on a 404. */

const REQ = {
  id: 'req-1',
  reference: 'WR-WKS-000001',
  title: 'MCC-2 build',
  project_id: 'p1',
  department: 'workshop',
  department_name: 'Workshop',
  stage_name: 'Build',
  status: 'in_progress',
  quoted_hours: 180,
  hours_logged: 70,
  is_late: true,
  days_late: 12,
  schedule_activity_id: 'a1',
};

const TASK = {
  id: 'task-1',
  title: 'Chase the MCC-2 gear',
  project_id: 'p1',
  stage_id: 'doing',
  waiting_on: 'Acme Holdings',
};

function deliveryProp(overrides = {}) {
  return {
    index: {
      a1: {
        requests: [REQ],
        tasks: [TASK],
        indirectTaskIds: new Set(),
        quotedHours: 180,
        loggedHours: 70,
        lateRequests: 1,
        lateTasks: 0,
        blockedTasks: 1,
        atRisk: true,
      },
      a2: {
        requests: [],
        tasks: [],
        indirectTaskIds: new Set(),
        quotedHours: 0,
        loggedHours: 0,
        lateRequests: 0,
        lateTasks: 0,
        blockedTasks: 0,
        atRisk: false,
      },
    },
    doneStages: new Set(['done']),
    today: '2026-09-03',
    departmentColour: () => '#7c3aed',
    onOpenLinks: vi.fn(),
    ...overrides,
  };
}

describe('ActivityGrid delivery column', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('shows a chip per linked request and task on the right row', () => {
    renderGrid({ delivery: deliveryProp() });
    expect(screen.getByTestId('delivery-request-req-1')).toHaveTextContent('WR-WKS-000001');
    expect(screen.getByTestId('delivery-task-task-1')).toHaveTextContent('Chase the MCC-2 gear');
    // The activity with nothing attached gets the cell, not the chips.
    expect(screen.getByTestId('delivery-cell-a2')).toBeInTheDocument();
    expect(screen.queryByTestId('delivery-summary-a2')).not.toBeInTheDocument();
  });

  it('rolls hours and counts up on the activity', () => {
    renderGrid({ delivery: deliveryProp() });
    const summary = screen.getByTestId('delivery-summary-a1').textContent;
    expect(summary).toContain('70/180 h');
  });

  it('flags the row when an attachment is late or blocked', () => {
    renderGrid({ delivery: deliveryProp() });
    expect(screen.getByTestId('grid-row-a1')).toHaveAttribute('data-delivery-risk', 'true');
    expect(screen.getByTestId('grid-row-a2')).not.toHaveAttribute('data-delivery-risk');
  });

  it('opens the record a chip names', () => {
    renderGrid({ delivery: deliveryProp() });
    fireEvent.click(screen.getByTestId('delivery-request-req-1'));
    expect(navigateSpy).toHaveBeenCalledWith('/work-requests/req-1');
    fireEvent.click(screen.getByTestId('delivery-task-task-1'));
    expect(navigateSpy).toHaveBeenCalledWith('/team-standup');
  });

  it('asks the page to open the link picker for that activity', () => {
    const delivery = deliveryProp();
    renderGrid({ delivery });
    fireEvent.click(screen.getByTestId('delivery-link-a1'));
    expect(delivery.onOpenLinks).toHaveBeenCalledWith('a1');
  });

  it('hides the whole column when neither module answered', () => {
    renderGrid();
    expect(screen.queryByText('Delivery')).not.toBeInTheDocument();
    expect(screen.queryByTestId('delivery-cell-a1')).not.toBeInTheDocument();
    expect(screen.queryByTestId('col-grip-delivery')).not.toBeInTheDocument();
    // And the grid it replaced still works exactly as before.
    expect(screen.getByTestId('grid-row-a1')).toBeInTheDocument();
  });
});

/* ── Resizable columns ─────────────────────────────────────────────────── */

function colWidth(key) {
  const col = document.querySelector('col[data-col="' + key + '"]');
  return col ? parseInt(col.style.width, 10) : Number.NaN;
}

function dragGrip(key, by) {
  const grip = screen.getByTestId('col-grip-' + key);
  fireEvent.mouseDown(grip, { clientX: 100 });
  fireEvent.mouseMove(document, { clientX: 100 + by });
  fireEvent.mouseUp(document, { clientX: 100 + by });
}

describe('ActivityGrid column widths', () => {
  beforeEach(() => {
    window.localStorage.clear();
  });

  it('starts every column at its default width', () => {
    renderGrid();
    expect(colWidth('name')).toBe(280);
    expect(colWidth('wbs')).toBe(76);
  });

  it('resizes a column by dragging its grip', () => {
    renderGrid();
    dragGrip('name', 60);
    expect(colWidth('name')).toBe(340);
    // Its neighbours are untouched - a drag widens one column, not the table's
    // idea of every column.
    expect(colWidth('wbs')).toBe(76);
  });

  it('never lets a drag squeeze a column under its minimum', () => {
    renderGrid();
    dragGrip('wbs', -500);
    expect(colWidth('wbs')).toBe(56);
  });

  it('shows a guideline while a drag is live and drops it on release', () => {
    renderGrid();
    const grip = screen.getByTestId('col-grip-name');
    fireEvent.mouseDown(grip, { clientX: 100 });
    fireEvent.mouseMove(document, { clientX: 180 });
    expect(screen.getByTestId('col-resize-guide')).toBeInTheDocument();
    fireEvent.mouseUp(document, { clientX: 180 });
    expect(screen.queryByTestId('col-resize-guide')).not.toBeInTheDocument();
  });

  it('persists a width and restores it on the next mount', () => {
    const first = renderGrid();
    dragGrip('name', 60);
    expect(window.localStorage.getItem('oe.schedule.grid-cols.s1')).toContain('340');
    first.unmount();
    renderGrid();
    expect(colWidth('name')).toBe(340);
  });

  it('keeps one schedule’s widths out of another’s', () => {
    const first = renderGrid();
    dragGrip('name', 60);
    first.unmount();
    renderGrid({ scheduleId: 's2' });
    expect(colWidth('name')).toBe(280);
  });

  it('auto-fits a column to its widest cell on a double-click', () => {
    renderGrid();
    dragGrip('wbs', 200);
    expect(colWidth('wbs')).toBe(276);
    fireEvent.doubleClick(screen.getByTestId('col-grip-wbs'));
    // Back down to the floor: "01" and "02" need nothing like 276px.
    expect(colWidth('wbs')).toBe(56);
  });

  it('offers reset and fit-all on a right-click of the header', () => {
    renderGrid();
    dragGrip('name', 60);
    fireEvent.contextMenu(screen.getByTestId('activity-grid').querySelector('thead tr'));
    expect(screen.getByTestId('col-header-menu')).toBeInTheDocument();
    fireEvent.click(screen.getByTestId('col-menu-reset'));
    expect(colWidth('name')).toBe(280);
    expect(window.localStorage.getItem('oe.schedule.grid-cols.s1')).toBeNull();
  });

  it('fits every column at once from the header menu', () => {
    renderGrid();
    dragGrip('wbs', 200);
    fireEvent.contextMenu(screen.getByTestId('activity-grid').querySelector('thead tr'));
    fireEvent.click(screen.getByTestId('col-menu-fit-all'));
    expect(colWidth('wbs')).toBe(56);
    expect(screen.queryByTestId('col-header-menu')).not.toBeInTheDocument();
  });

  it('gives the delivery column a grip of its own once it is shown', () => {
    renderGrid({ delivery: deliveryProp() });
    expect(colWidth('delivery')).toBe(210);
    dragGrip('delivery', 40);
    expect(colWidth('delivery')).toBe(250);
  });
});
