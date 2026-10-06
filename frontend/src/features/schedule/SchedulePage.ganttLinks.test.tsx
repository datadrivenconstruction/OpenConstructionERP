// @ts-nocheck
/**
 * Linking activities by dragging on the Gantt, as wired on the schedule page.
 *
 * The chart only reports "link A to B as FS" or "remove the link A to B"; the
 * page turns that into the same relationship calls the dependency form makes,
 * then reschedules so the bars move. The chart is replaced here by two buttons
 * that fire exactly those callbacks, so what is under test is the wiring.
 *
 * A cycle is refused by the server with a 400 whose detail is English prose.
 * The page has to show it in the reader's language instead of that prose.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { ApiError } from '@/shared/lib/api';

const state = vi.hoisted(() => ({
  created: [] as any[],
  deleted: [] as string[],
  rescheduled: 0,
  failCreate: null as unknown,
}));

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual<typeof import('react-i18next')>('react-i18next');
  const t = (key: string, a?: unknown, b?: unknown) => {
    const opts = (typeof a === 'object' && a ? a : typeof b === 'object' && b ? b : {}) as Record<string, unknown>;
    const text = typeof a === 'string' ? a : typeof opts.defaultValue === 'string' ? opts.defaultValue : key;
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, k) => String(opts[k] ?? ''));
  };
  return { ...actual, useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: async () => {} } }) };
});

const base = {
  start_date: '2026-05-04',
  end_date: '2026-05-08',
  duration_days: 5,
  progress_pct: 0,
  status: 'not_started',
  color: '#0071e3',
  boq_position_ids: [],
  activity_type: 'task',
  parent_id: null,
};

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  const known = {
    getGantt: async () => ({
      activities: [
        { ...base, id: 'a', name: 'Excavate', wbs_code: '1', dependencies: [] },
        { ...base, id: 'b', name: 'Pour', wbs_code: '2', dependencies: [{ activity_id: 'a', type: 'FS', lag_days: 0 }] },
      ],
      summary: { total_activities: 2, completed: 0, in_progress: 0, delayed: 0 },
    }),
    createRelationship: async (_scheduleId: string, body: any) => {
      if (state.failCreate) throw state.failCreate;
      state.created.push(body);
      return { id: 'r-new', ...body };
    },
    deleteRelationshipBetween: async (_scheduleId: string, predecessorId: string, successorId: string) => {
      state.deleted.push(`${predecessorId}->${successorId}`);
    },
    reschedule: async () => {
      state.rescheduled += 1;
      return [];
    },
  };
  const scheduleApi = new Proxy(known, {
    get: (target, prop) => (prop in target ? target[prop] : async () => []),
  });
  return { ...actual, scheduleApi };
});

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, apiGet: vi.fn(async () => ({})) };
});
vi.mock('@/features/bim/api', () => ({ fetchBIMModels: vi.fn(async () => ({ items: [] })) }));
vi.mock('@/features/resources/api', () => ({
  listAssignmentsForActivity: vi.fn(async () => []),
  listResources: vi.fn(async () => ({ items: [], total: 0, offset: 0, limit: 500 })),
}));
vi.mock('@/features/schedule-advanced/api', () => ({ listCalendars: vi.fn(async () => []) }));
vi.mock('@/shared/ui', async () => {
  const actual = await vi.importActual<typeof import('@/shared/ui')>('@/shared/ui');
  return {
    ...actual,
    GanttChart: ({ onCreateLink, onDeleteLink }: any) => (
      <div data-testid="svg-gantt">
        {onCreateLink && (
          <button type="button" onClick={() => onCreateLink('b', 'a', 'SS')}>
            fake-link
          </button>
        )}
        {onDeleteLink && (
          <button type="button" onClick={() => onDeleteLink('a', 'b')}>
            fake-unlink
          </button>
        )}
      </div>
    ),
  };
});

import { ScheduleDetail } from './SchedulePage';

const SCHEDULE = {
  id: 'sch',
  project_id: 'p1',
  name: 'Main schedule',
  description: '',
  start_date: '2026-05-01',
  end_date: '2026-09-30',
  status: 'draft',
  created_at: '2026-05-01',
  updated_at: '2026-05-01',
};

// The first mount of ScheduleDetail in a worker is the slow step: under a
// loaded machine it alone outran the 5 s asyncUtilTimeout (the first test
// failed at 6.2 s inside its first findByRole), while every wait after it
// only runs the mocks' microtasks. So the mount is awaited once, here, with
// the whole test's budget, and no test races its own first render.
const MOUNT_TIMEOUT_MS = 15_000;

async function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScheduleDetail schedule={SCHEDULE} projectId="p1" onBack={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await screen.findByTestId('svg-gantt', {}, { timeout: MOUNT_TIMEOUT_MS });
  return view;
}

beforeEach(() => {
  state.created = [];
  state.deleted = [];
  state.rescheduled = 0;
  state.failCreate = null;
  useToastStore.setState({ toasts: [] });
  // Linking needs schedule.update (EDITOR); the viewer case sets its own role.
  useAuthStore.setState({ userRole: 'editor' });
});

describe('SchedulePage Gantt links', () => {
  it('creates the relationship the drag described and reschedules', async () => {
    await renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'fake-link' }));

    await waitFor(() => expect(state.created).toHaveLength(1));
    expect(state.created[0]).toEqual({
      predecessor_id: 'b',
      successor_id: 'a',
      relationship_type: 'SS',
      lag_days: 0,
    });
    await waitFor(() => expect(state.rescheduled).toBe(1));
  });

  it('shows a cycle refusal in the reader language, not the server prose', async () => {
    state.failCreate = new ApiError(400, 'Bad Request', {
      detail: {
        error: 'schedule_dependency_cycle',
        message: 'Adding this dependency would create a circular reference. Check the dependency chain for cycles.',
      },
    });
    await renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'fake-link' }));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast.type).toBe('error');
    expect(toast.title).toBe('This link would make the schedule loop back on itself, so it was not added.');
    expect(state.rescheduled).toBe(0);
  });

  it('shows the cross-schedule 404 in the reader language too', async () => {
    state.failCreate = new ApiError(404, 'Not Found', {
      detail: { error: 'schedule_activity_not_in_schedule', message: 'Activity not found in this schedule.' },
    });
    await renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'fake-link' }));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    expect(useToastStore.getState().toasts[0].title).toBe('Both activities must belong to this schedule.');
  });

  it('removes a link by its pair of activities', async () => {
    await renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'fake-unlink' }));

    await waitFor(() => expect(state.deleted).toEqual(['a->b']));
    await waitFor(() => expect(state.rescheduled).toBe(1));
  });

  it('gives a viewer no link handles and no arrow menu', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    await renderDetail();

    expect(screen.queryByRole('button', { name: 'fake-link' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'fake-unlink' })).toBeNull();
  });
});
