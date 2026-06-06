// @ts-nocheck
/**
 * Tests for the Last Planner task-picker connectivity work (CONN-31 / CONN-32).
 *
 * Verifies:
 *   - the Add-commitment modal offers a task picker (fetchTasks by project)
 *     instead of a raw UUID field, and submits the picked task's UUID as
 *     ``task_ref``
 *   - the Constraints tab exposes a "New constraint" action, opens a modal
 *     with the same task picker, and POSTs createConstraint with the picked
 *     task UUID
 *   - the constraints empty state no longer points at a non-existent
 *     "look-ahead detail view" dead end
 *
 * Network is stubbed via ``vi.mock`` on ``./api``, ``@/features/tasks/api``
 * and ``@/features/projects/api``. React Query retries are disabled.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    listMasterSchedules: vi.fn(),
    listPhasePlans: vi.fn(),
    listLookAheads: vi.fn(),
    listConstraints: vi.fn(),
    createConstraint: vi.fn(),
    listWeeklyPlans: vi.fn(),
    listCommitments: vi.fn(),
    createCommitment: vi.fn(),
    listBaselines: vi.fn(),
    baselineDelta: vi.fn(),
    currentTasksForMaster: vi.fn(),
  };
});

vi.mock('@/features/tasks/api', () => ({
  fetchTasks: vi.fn(),
}));

vi.mock('@/features/projects/api', () => ({
  projectsApi: {
    list: vi.fn().mockResolvedValue([{ id: 'p1', name: 'Test Project' }]),
  },
}));

import {
  listMasterSchedules,
  listLookAheads,
  listConstraints,
  createConstraint,
  listWeeklyPlans,
  listCommitments,
  createCommitment,
  listBaselines,
} from './api';
import { fetchTasks } from '@/features/tasks/api';
import { ScheduleAdvancedPage } from './ScheduleAdvancedPage';

const masterSchedule = {
  id: 'ms1',
  project_id: 'p1',
  name: 'Master',
  planned_start: '2026-06-01',
  planned_finish: '2026-12-31',
  status: 'active',
  notes: '',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

const lookAhead = {
  id: 'la1',
  master_schedule_id: 'ms1',
  period_start: '2026-06-01',
  period_end: '2026-07-13',
  window_weeks: 6,
  generated_at: null,
  status: 'draft',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

const weekPlan = {
  id: 'wk1',
  master_schedule_id: 'ms1',
  week_start_date: '2026-06-01',
  week_end_date: '2026-06-07',
  generated_at: null,
  facilitator_id: null,
  status: 'draft',
  ppc_percent: 0,
  notes: '',
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
};

const sampleTask = {
  id: '11111111-2222-3333-4444-555555555555',
  project_id: 'p1',
  title: 'Pour ground-floor slab',
  description: null,
  task_type: 'task',
  status: 'open',
  priority: 'normal',
  responsible_id: null,
  assigned_to: null,
  assigned_to_name: null,
  due_date: null,
  checklist: [],
  checklist_progress: 0,
  created_by: null,
  meeting_id: null,
  metadata: {},
  created_at: '2026-05-01T00:00:00Z',
  updated_at: '2026-05-01T00:00:00Z',
  completed_at: null,
  is_overdue: false,
};

function renderPage() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/schedule-advanced']}>
        <ScheduleAdvancedPage />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('Last Planner task pickers', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (listMasterSchedules as any).mockResolvedValue([masterSchedule]);
    (listLookAheads as any).mockResolvedValue([lookAhead]);
    (listConstraints as any).mockResolvedValue([]);
    (listWeeklyPlans as any).mockResolvedValue([weekPlan]);
    (listCommitments as any).mockResolvedValue([]);
    (listBaselines as any).mockResolvedValue([]);
    (fetchTasks as any).mockResolvedValue([sampleTask]);
  });

  it('Add-commitment modal uses a task picker, not a raw UUID field', async () => {
    renderPage();
    const weeklyTab = await screen.findByRole('tab', { name: /weekly plan/i });
    fireEvent.click(weeklyTab);

    const addBtn = await screen.findByRole('button', { name: /add commitment/i });
    fireEvent.click(addBtn);

    // The picker placeholder replaces the old UUID input.
    const picker = await screen.findByPlaceholderText(/search project tasks/i);
    expect(picker).toBeInTheDocument();
    // The legacy raw-UUID placeholder must be gone.
    expect(
      screen.queryByPlaceholderText('00000000-0000-0000-0000-000000000000'),
    ).not.toBeInTheDocument();
  });

  it('submits createCommitment with the picked task UUID', async () => {
    (createCommitment as any).mockResolvedValue({ id: 'c1' });
    renderPage();
    fireEvent.click(await screen.findByRole('tab', { name: /weekly plan/i }));
    fireEvent.click(await screen.findByRole('button', { name: /add commitment/i }));

    const picker = await screen.findByPlaceholderText(/search project tasks/i);
    fireEvent.focus(picker);
    // Task option appears (loaded via fetchTasks by project).
    const option = await screen.findByText('Pour ground-floor slab');
    fireEvent.click(option);

    const createBtns = screen.getAllByRole('button', { name: /^create$/i });
    fireEvent.click(createBtns[createBtns.length - 1]);

    await waitFor(() => {
      expect(createCommitment).toHaveBeenCalledWith(
        expect.objectContaining({
          week_plan_id: 'wk1',
          task_ref: sampleTask.id,
        }),
      );
    });
  });

  it('Constraints tab exposes a New constraint action and modal', async () => {
    renderPage();
    fireEvent.click(await screen.findByRole('tab', { name: /constraints/i }));

    // "New constraint" action present (toolbar + empty-state CTA) once the
    // look-ahead auto-selects and the constraints query resolves empty.
    const newBtns = await screen.findAllByRole('button', { name: /new constraint/i });
    expect(newBtns.length).toBeGreaterThan(0);

    // Empty-state copy no longer references the dead "look-ahead detail view".
    expect(
      screen.queryByText(/look-ahead detail view/i),
    ).not.toBeInTheDocument();

    fireEvent.click(newBtns[0]);

    // Modal opens with the task picker.
    expect(
      await screen.findByPlaceholderText(/search project tasks/i),
    ).toBeInTheDocument();
  });

  it('submits createConstraint with the picked task UUID', async () => {
    (createConstraint as any).mockResolvedValue({ id: 'cn1' });
    renderPage();
    fireEvent.click(await screen.findByRole('tab', { name: /constraints/i }));
    const newBtns = await screen.findAllByRole('button', { name: /new constraint/i });
    fireEvent.click(newBtns[0]);

    const picker = await screen.findByPlaceholderText(/search project tasks/i);
    fireEvent.focus(picker);
    fireEvent.click(await screen.findByText('Pour ground-floor slab'));

    const createBtns = screen.getAllByRole('button', { name: /^create$/i });
    fireEvent.click(createBtns[createBtns.length - 1]);

    await waitFor(() => {
      expect(createConstraint).toHaveBeenCalledWith(
        expect.objectContaining({
          look_ahead_id: 'la1',
          task_ref: sampleTask.id,
        }),
      );
    });
  });
});
