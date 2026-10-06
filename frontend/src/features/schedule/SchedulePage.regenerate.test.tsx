// @ts-nocheck
/**
 * Generating into a populated schedule, and deleting schedules and activities.
 *
 * A tester reported that generating from a BOQ "always errors": the deep link
 * opened the first schedule of the project, which already had activities, and
 * the server refused with a 409 shown as raw English. The page now asks what
 * to do (replace, or generate into a new schedule), says every refusal from
 * its code in the reader's language, and shows a plan that cannot fit the
 * window plainly. Schedules are archived from the header and list; only an
 * administrator can permanently delete an archive after an impact confirmation.
 * Individual activities can still be deleted from the Gantt side panel.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useToastStore } from '@/stores/useToastStore';
import { useAuthStore } from '@/stores/useAuthStore';
import { ApiError } from '@/shared/lib/api';

const state = vi.hoisted(() => ({
  activities: [] as any[],
  generateCalls: [] as any[],
  generateFail: [] as unknown[],
  created: [] as any[],
  deletedSchedules: [] as string[],
  archivedSchedules: [] as string[],
  restoredSchedules: [] as string[],
  archiveFail: false,
  listCalls: [] as string[],
  deletedActivities: [] as string[],
  cleared: 0,
  record: null as any,
  schedules: [] as any[],
  ganttCalls: [] as string[],
  baselines: [] as any[],
  previewCalls: [] as any[],
  previewFail: [] as unknown[],
  preview: null as any,
  payments: 0,
  cascades: [] as boolean[],
  deleteBlocked: false,
}));

const PREVIEW = {
  boq_id: 'b1',
  boq_name: 'Bill of works',
  boq_estimate_type: null,
  activity_count: 86,
  positions_scheduled: 70,
  lump_sum_positions: 2,
  summary_count: 14,
  estimated_count: 12,
  skipped_count: 3,
  note_counts: {},
  crews: 2,
  compressed_pct: null,
  fits: true,
  planned_start: '2026-05-04',
  planned_end: '2026-10-20',
  requested_end: '2026-10-31',
  warnings: [],
  existing_activity_count: 0,
  existing_started_count: 0,
  notes: [
    {
      position_id: 'p9',
      ordinal: '02.4',
      description: 'Scavo di sbancamento',
      note: 'estimated_from_unit',
      days: 107,
      basis: { unit: 'm3', rate: 4, hours: 3400, gang: 4, hours_per_day: 8 },
    },
    { position_id: 'p10', ordinal: '02.5', description: 'Trasporto a discarica', note: 'skipped_zero_qty' },
  ],
};

vi.mock('react-i18next', async () => {
  const actual = await vi.importActual<typeof import('react-i18next')>('react-i18next');
  const { default: en } = await import('@/app/locales/en');
  const t = (key: string, a?: unknown, b?: unknown) => {
    const opts = (typeof a === 'object' && a ? a : typeof b === 'object' && b ? b : {}) as Record<string, unknown>;
    const text = typeof a === 'string' ? a : typeof opts.defaultValue === 'string' ? opts.defaultValue : en.translation[key] ?? key;
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, k) => String(opts[k] ?? ''));
  };
  return { ...actual, useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: async () => {} } }) };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  const known = {
    getGantt: async (id: string) => {
      state.ganttCalls.push(id);
      return {
        activities: state.activities,
        summary: { total_activities: state.activities.length, completed: 0, in_progress: 0, delayed: 0 },
      };
    },
    getSchedule: async (id: string) => state.record ?? { id, metadata_: {} },
    updateSchedule: async () => ({}),
    generateFromBOQ: async (scheduleId: string, boqId: string, options: any = {}) => {
      state.generateCalls.push({
        scheduleId,
        boqId,
        days: options.totalProjectDays,
        startDate: options.startDate,
        replace: !!options.replace,
        workers: options.workersPerPosition,
      });
      if (state.generateFail.length) throw state.generateFail.shift();
      return [];
    },
    previewGenerateFromBOQ: async (scheduleId: string, boqId: string, options: any = {}) => {
      state.previewCalls.push({
        scheduleId,
        boqId,
        days: options.totalProjectDays,
        startDate: options.startDate,
        workers: options.workersPerPosition,
      });
      if (state.previewFail.length) throw state.previewFail.shift();
      return state.preview ?? PREVIEW;
    },
    getDeleteImpact: async (id: string) => ({
      activity_count: state.activities.length,
      baseline_count: state.baselines.filter((b: any) => b.schedule_id === id).length,
      payment_milestone_count: state.payments,
      can_delete: !state.deleteBlocked,
      blocked_reason: state.deleteBlocked ? 'permission_denied' : null,
    }),
    createSchedule: async (body: any) => {
      state.created.push(body);
      return { ...body, id: 'sch2', status: 'draft', description: '', created_at: '', updated_at: '' };
    },
    deleteSchedule: async (id: string) => {
      state.deletedSchedules.push(id);
    },
    archiveSchedule: async (id: string) => {
      if (state.archiveFail) throw new Error('Archive failed');
      state.archivedSchedules.push(id);
      state.schedules = state.schedules.map(s => s.id === id ? { ...s, status: 'archived' } : s);
    },
    restoreSchedule: async (id: string) => {
      state.restoredSchedules.push(id);
      const schedule = state.schedules.find(s => s.id === id) ?? state.record ?? SCHEDULE;
      const status = schedule.metadata_?._schedule_archive?.previous_status ?? 'draft';
      return { ...schedule, status, metadata_: { _schedule_archive: { restore_used_fallback: !schedule.metadata_?._schedule_archive } } };
    },
    purgeSchedule: async (id: string) => {
      state.deletedSchedules.push(id);
      state.schedules = state.schedules.filter(s => s.id !== id);
    },
    deleteActivity: async (id: string, cascade = false) => {
      state.deletedActivities.push(id);
      state.cascades.push(cascade);
    },
    clearActivities: async () => {
      state.cleared += 1;
      return { deleted: state.activities.length };
    },
    listSchedules: async (_projectId: string, options: any = {}) => {
      const filter = options.archiveState ?? 'current';
      state.listCalls.push(filter);
      const items = state.schedules.filter(s => filter === 'all' || (s.status === 'archived') === (filter === 'archived'));
      const offset = options.offset ?? 0;
      return { items: items.slice(offset, offset + (options.limit ?? 50)), total: items.length };
    },
    listBaselines: async () => state.baselines,
  };
  const scheduleApi = new Proxy(known, {
    get: (target, prop) => (prop in target ? target[prop] : async () => []),
  });
  return { ...actual, scheduleApi };
});

vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return {
    ...actual,
    apiGet: vi.fn(async (url: string) =>
      url.includes('/v1/boq/boqs') ? [{ id: 'b1', name: 'Bill of works', status: 'draft' }] : {},
    ),
  };
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
    GanttChart: ({ activities, onActivityClick }: any) => (
      <div data-testid="svg-gantt">
        {activities.map((a: any) => (
          <button key={a.id} type="button" onClick={() => onActivityClick?.(a.id)}>
            {`open-${a.id}`}
          </button>
        ))}
      </div>
    ),
  };
});

import { ScheduleDetail, ProjectSchedules } from './SchedulePage';

const base = {
  start_date: '2026-05-04',
  end_date: '2026-05-08',
  duration_days: 5,
  progress_pct: 0,
  dependencies: [],
  status: 'not_started',
  color: '#0071e3',
  boq_position_ids: [],
  activity_type: 'task',
  parent_id: null,
};
const THREE = [
  { ...base, id: 's1', name: 'Earthworks', wbs_code: '1', activity_type: 'summary' },
  { ...base, id: 'c1', name: 'Excavate', wbs_code: '1.1', parent_id: 's1' },
  { ...base, id: 'c2', name: 'Backfill', wbs_code: '1.2', parent_id: 's1' },
];

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

function wrap(node: any) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{node}</MemoryRouter>
    </QueryClientProvider>,
  );
}

function renderDetail(props: Record<string, unknown> = {}) {
  const onOpenSchedule = vi.fn();
  const onBack = vi.fn();
  wrap(
    <ScheduleDetail
      schedule={{ ...SCHEDULE, ...(props.schedule ?? {}) }}
      projectId="p1"
      onBack={onBack}
      onOpenSchedule={onOpenSchedule}
      generateBoqId={props.generateBoqId}
      onConsumeGenerateBoq={vi.fn()}
    />,
  );
  return { onOpenSchedule, onBack };
}

async function previewFromDeepLink() {
  const end = await screen.findByTestId('generate-end-date');
  fireEvent.change(end, { target: { value: '2026-10-31' } });
  fireEvent.click(screen.getByRole('button', { name: 'Check the plan' }));
  return screen.findByTestId('generation-preview');
}

async function generateFromDeepLink() {
  await previewFromDeepLink();
  fireEvent.click(screen.getByRole('button', { name: 'Create the plan' }));
}

const conflict = () =>
  new ApiError(409, 'Conflict', {
    detail: {
      error: 'schedule_has_activities',
      message: 'This schedule already has 12 activities.',
      activity_count: 12,
      started_count: 3,
    },
  });

beforeEach(() => {
  state.activities = [];
  state.generateCalls = [];
  state.generateFail = [];
  state.created = [];
  state.deletedSchedules = [];
  state.archivedSchedules = [];
  state.restoredSchedules = [];
  state.archiveFail = false;
  state.listCalls = [];
  state.deletedActivities = [];
  state.cleared = 0;
  state.record = null;
  state.schedules = [];
  state.ganttCalls = [];
  state.baselines = [];
  state.previewCalls = [];
  state.previewFail = [];
  state.preview = null;
  state.payments = 0;
  state.cascades = [];
  state.deleteBlocked = false;
  useToastStore.setState({ toasts: [] });
  useAuthStore.setState({ userRole: 'editor' });
});

describe('generating from a BOQ', () => {
  it('reads Regenerate once the schedule has activities', async () => {
    state.activities = THREE;
    renderDetail();
    expect(await screen.findByRole('button', { name: 'Regenerate from BOQ' })).toBeInTheDocument();
  });

  it('reads Generate on an empty schedule', async () => {
    renderDetail();
    expect((await screen.findAllByRole('button', { name: 'Generate from BOQ' })).length).toBeGreaterThan(0);
    expect(screen.queryByRole('button', { name: 'Regenerate from BOQ' })).toBeNull();
  });

  it('shows what would be written and writes nothing until Create', async () => {
    renderDetail({ generateBoqId: 'b1' });
    const panel = await previewFromDeepLink();
    expect(panel).toHaveTextContent('86 activities: 70 positions in 14 sections');
    expect(panel).toHaveTextContent('12 durations are estimates');
    expect(panel).toHaveTextContent('3 rows left out');
    expect(panel).toHaveTextContent(/inside the end date you asked for/);
    expect(panel).toHaveTextContent('107 working days: about 3400 hours at 4 h per m3, for a gang of 4');
    expect(panel).toHaveTextContent('Left out: no quantity');
    expect(state.previewCalls[0]).toMatchObject({ scheduleId: 'sch', boqId: 'b1', startDate: '2026-05-01', days: 184 });
    expect(state.generateCalls).toHaveLength(0);

    fireEvent.click(screen.getByRole('button', { name: 'Create the plan' }));
    await waitFor(() => expect(state.generateCalls).toHaveLength(1));
    expect(state.generateCalls[0]).toMatchObject({ startDate: '2026-05-01', days: 184, replace: false });
  });

  it('generates without an end date and says the plan takes what the work needs', async () => {
    state.preview = { ...PREVIEW, requested_end: null };
    renderDetail({ generateBoqId: 'b1' });
    await screen.findByTestId('generate-end-date');
    expect(screen.getByText(/No end date: the plan takes as long as the work needs/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Check the plan' }));
    expect(await screen.findByTestId('generation-preview')).toHaveTextContent(/No end date was given/);
    expect(state.previewCalls[0].days).toBeUndefined();
  });

  it('offers to replace the activities already there, from the preview', async () => {
    state.preview = { ...PREVIEW, existing_activity_count: 12, existing_started_count: 3 };
    renderDetail({ generateBoqId: 'b1' });
    await previewFromDeepLink();
    expect(screen.getByText(/This schedule already has 12 activities/)).toBeInTheDocument();
    expect(screen.getByText(/3 of them have progress recorded/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Replace them and create the plan' }));
    await waitFor(() => expect(state.generateCalls).toHaveLength(1));
    expect(state.generateCalls[0]).toMatchObject({ scheduleId: 'sch', boqId: 'b1', replace: true });
  });

  it('labels a budget bill so it is not mistaken for a bill to build from', async () => {
    state.preview = { ...PREVIEW, boq_estimate_type: 'budget' };
    renderDetail({ generateBoqId: 'b1' });
    expect(await previewFromDeepLink()).toHaveTextContent(/saved as a budget estimate/);
  });

  it('labels a bill of mostly lump sums even when nobody saved it as a budget', async () => {
    state.preview = { ...PREVIEW, positions_scheduled: 9, lump_sum_positions: 9 };
    renderDetail({ generateBoqId: 'b1' });
    const panel = await previewFromDeepLink();
    expect(panel).toHaveTextContent('9 of its 9 positions are lump sums');
    expect(panel).not.toHaveTextContent(/saved as a budget estimate/);
  });

  it('says nothing about lump sums on a bill with quantities', async () => {
    renderDetail({ generateBoqId: 'b1' });
    expect(await previewFromDeepLink()).not.toHaveTextContent(/lump sums\. Each becomes one bar/);
  });

  it('asks before replacing a populated schedule and replaces on request', async () => {
    // Someone filled the schedule between the preview and the click.
    state.generateFail = [conflict()];
    renderDetail({ generateBoqId: 'b1' });
    await generateFromDeepLink();

    const dialog = await screen.findByRole('dialog', { name: /already has activities/i });
    expect(dialog).toHaveTextContent('This schedule already has 12 activities.');
    expect(dialog).toHaveTextContent('3 of them have progress recorded');
    fireEvent.click(within(dialog).getByRole('button', { name: 'Replace them' }));

    await waitFor(() => expect(state.generateCalls).toHaveLength(2));
    expect(state.generateCalls[1]).toMatchObject({ scheduleId: 'sch', boqId: 'b1', replace: true });
    await waitFor(() =>
      expect(useToastStore.getState().toasts.some((toast) => toast.type === 'success')).toBe(true),
    );
  });

  it('can generate into a new schedule instead and opens it', async () => {
    state.generateFail = [conflict()];
    const { onOpenSchedule } = renderDetail({ generateBoqId: 'b1' });
    await generateFromDeepLink();

    const dialog = await screen.findByRole('dialog', { name: /already has activities/i });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create a new schedule' }));

    await waitFor(() => expect(onOpenSchedule).toHaveBeenCalledTimes(1));
    expect(state.created).toHaveLength(1);
    expect(state.created[0].project_id).toBe('p1');
    expect(state.generateCalls[1]).toMatchObject({ scheduleId: 'sch2', boqId: 'b1', replace: false });
    expect(onOpenSchedule.mock.calls[0][0].id).toBe('sch2');
  });

  it('archives the new schedule when generation fails and says the data was kept', async () => {
    state.generateFail = [
      conflict(),
      new ApiError(422, 'Unprocessable', {
        detail: { error: 'boq_has_no_positions', message: 'BOQ has no positions to schedule' },
      }),
    ];
    const { onOpenSchedule } = renderDetail({ generateBoqId: 'b1' });
    await generateFromDeepLink();
    const dialog = await screen.findByRole('dialog', { name: /already has activities/i });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Create a new schedule' }));

    await waitFor(() => expect(state.archivedSchedules).toEqual(['sch2']));
    expect(state.deletedSchedules).toEqual([]);
    expect(useToastStore.getState().toasts.some(t => /archived.*kept/.test(t.message ?? t.title))).toBe(true);
    expect(state.created).toHaveLength(1);
    expect(onOpenSchedule).not.toHaveBeenCalled();
  });

  it('cancel leaves the schedule as it was', async () => {
    state.generateFail = [conflict()];
    renderDetail({ generateBoqId: 'b1' });
    await generateFromDeepLink();
    const dialog = await screen.findByRole('dialog', { name: /already has activities/i });
    fireEvent.click(within(dialog).getByRole('button', { name: 'Cancel' }));
    await waitFor(() => expect(screen.queryByRole('dialog', { name: /already has activities/i })).toBeNull());
    expect(state.generateCalls).toHaveLength(1);
  });

  it('says an empty bill in the reader language, not the server English', async () => {
    state.previewFail = [
      new ApiError(422, 'Unprocessable', {
        detail: { error: 'boq_has_no_positions', message: 'BOQ has no positions to schedule' },
      }),
    ];
    renderDetail({ generateBoqId: 'b1' });
    const end = await screen.findByTestId('generate-end-date');
    fireEvent.change(end, { target: { value: '2026-10-31' } });
    fireEvent.click(screen.getByRole('button', { name: 'Check the plan' }));

    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast.type).toBe('error');
    expect(toast.message).toMatch(/nothing to schedule/);
    expect(toast.message).not.toContain('BOQ has no positions to schedule');
  });

  it('shows plainly when the plan does not fit the requested window', async () => {
    state.activities = THREE;
    state.record = {
      ...SCHEDULE,
      metadata_: {
        boq_generation: {
          generated_at: '2026-10-05T10:00:00Z',
          warnings: [{ code: 'plan_exceeds_window', planned_end: '2027-03-01', requested_end: '2026-10-31' }],
        },
      },
    };
    renderDetail();

    const banner = await screen.findByTestId('generation-warning');
    expect(banner).toHaveTextContent(/does not fit/);
    expect(banner).toHaveTextContent(/2027/);
    expect(banner).toHaveTextContent(/2026/);
    fireEvent.click(within(banner).getByRole('button', { name: 'Dismiss' }));
    await waitFor(() => expect(screen.queryByTestId('generation-warning')).toBeNull());
  });

  it('says how much durations were shortened to fit', async () => {
    state.activities = THREE;
    state.record = {
      ...SCHEDULE,
      metadata_: { boq_generation: { generated_at: 'x', warnings: [{ code: 'durations_shortened', percent: 25 }] } },
    };
    renderDetail();
    expect(await screen.findByTestId('generation-warning')).toHaveTextContent(/25%/);
  });
});

describe('deleting', () => {
  it('archives an active schedule after confirmation that its data is kept', async () => {
    state.activities = THREE;
    const { onBack } = renderDetail({ schedule: { status: 'active' } });

    fireEvent.click(await screen.findByRole('button', { name: 'Archive Main schedule' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('activities, baselines and links will be kept');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Archive' }));

    await waitFor(() => expect(state.archivedSchedules).toEqual(['sch']));
    expect(state.deletedSchedules).toEqual([]);
    await waitFor(() => expect(onBack).toHaveBeenCalled());
  });

  it('deletes an activity from the Gantt panel after a confirmation', async () => {
    state.activities = THREE;
    renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'open-c1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete activity' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('Excavate');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Delete' }));

    await waitFor(() => expect(state.deletedActivities).toEqual(['c1']));
  });

  it('asks whether a section goes with its activities or keeps them one level up', async () => {
    state.activities = THREE;
    renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'open-s1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete activity' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('Earthworks');
    expect(confirm).toHaveTextContent(/holds 2 activities/);
    expect(confirm).toHaveTextContent(/move up one level/);
    fireEvent.click(within(confirm).getByRole('button', { name: 'Cancel' }));
    expect(state.deletedActivities).toEqual([]);

    fireEvent.click(await screen.findByRole('button', { name: 'Delete activity' }));
    const again = await screen.findByRole('alertdialog');
    fireEvent.click(within(again).getByRole('button', { name: 'Delete with its 2 activities' }));
    await waitFor(() => expect(state.deletedActivities).toEqual(['s1']));
    expect(state.cascades).toEqual([true]);
  });

  it('keeps a section\'s activities when asked to', async () => {
    state.activities = THREE;
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: 'open-s1' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Delete activity' }));
    const confirm = await screen.findByRole('alertdialog');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Keep the activities (they move up a level)' }));
    await waitFor(() => expect(state.deletedActivities).toEqual(['s1']));
    expect(state.cascades).toEqual([false]);
  });

  it('names affected payment instalments only for an admin permanent delete', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    state.activities = THREE;
    state.payments = 2;
    renderDetail({ schedule: { status: 'archived' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Permanently delete Main schedule' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent(/2 contract payment instalments follow its milestones/);
  });

  it('shows a viewer the plan without the buttons the server would refuse', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    state.activities = THREE;
    renderDetail();
    expect(await screen.findByTestId('svg-gantt')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Regenerate from BOQ' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Clear all activities' })).toBeNull();
    expect(screen.queryByRole('button', { name: 'Archive Main schedule' })).toBeNull();
  });

  it('opens no generate dialog for a viewer who follows a BOQ link', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    state.activities = THREE;
    renderDetail({ generateBoqId: 'b1' });
    expect(await screen.findByTestId('svg-gantt')).toBeInTheDocument();
    expect(screen.queryByTestId('generate-end-date')).toBeNull();
  });

  it('names the instalments a replace carries over and the ones it lets go', async () => {
    state.preview = { ...PREVIEW, existing_activity_count: 12, instalments_relinked: 2, instalments_unlinked: 1 };
    renderDetail({ generateBoqId: 'b1' });
    await previewFromDeepLink();
    const lines = screen.getAllByTestId('replace-instalments').map((p) => p.textContent);
    expect(lines).toEqual([
      '2 contract payment instalments move to the same milestone in the new plan.',
      '1 contract payment instalments lose their milestone and go back to their contract dates.',
    ]);
  });

  it('says how many workers it assumed and writes the plan with that number', async () => {
    state.preview = {
      ...PREVIEW,
      workers_per_position: 4,
      workers_assumed: true,
      positions_without_workers: 60,
      fitted_window: { days: 184, end: '2026-10-31', default: false },
    };
    renderDetail({ generateBoqId: 'b1' });
    const preview = await previewFromDeepLink();
    expect(state.previewCalls[0].workers).toBeUndefined();
    expect(preview).toHaveTextContent(
      'Assumed: at least 4 workers per position where the bill gives no crew (60 positions), the fewest that fit your end date.',
    );
    fireEvent.click(screen.getByRole('button', { name: 'Create the plan' }));
    await waitFor(() => expect(state.generateCalls).toHaveLength(1));
    expect(state.generateCalls[0].workers).toBe(4);
  });

  it('names the default window the workers were fitted to when no end date was given', async () => {
    state.preview = {
      ...PREVIEW,
      requested_end: null,
      workers_per_position: 5,
      workers_assumed: true,
      positions_without_workers: 60,
      fitted_window: { days: 365, end: '2027-04-30', default: true },
    };
    renderDetail({ generateBoqId: 'b1' });
    await screen.findByTestId('generate-end-date');
    fireEvent.click(screen.getByRole('button', { name: 'Check the plan' }));
    const preview = await screen.findByTestId('generation-preview');
    expect(preview).toHaveTextContent(/the fewest that fit a default window of 365 days, to .+\. No end date was given/);
  });

  it('does not call the most workers the fewest that fit when the plan still runs long', async () => {
    state.preview = {
      ...PREVIEW,
      requested_end: null,
      workers_per_position: 20,
      workers_assumed: true,
      positions_without_workers: 60,
      fitted_window: { days: 365, end: '2027-04-30', default: true, fits: false },
    };
    renderDetail({ generateBoqId: 'b1' });
    await screen.findByTestId('generate-end-date');
    fireEvent.click(screen.getByRole('button', { name: 'Check the plan' }));
    const preview = await screen.findByTestId('generation-preview');
    expect(preview).toHaveTextContent('20 workers per position where the bill gives no crew (60 positions), the most the plan assumes. Even so the work runs past a default window of 365 days.');
    expect(preview).not.toHaveTextContent('the fewest that fit');
  });

  it('says the most workers fit the end date only shortened, not that the work does not fit', async () => {
    state.preview = {
      ...PREVIEW,
      workers_per_position: 20,
      workers_assumed: true,
      positions_without_workers: 60,
      fits: true,
      compressed_pct: 78,
      warnings: [{ code: 'durations_shortened', percent: 78 }],
      fitted_window: { days: 150, end: '2026-10-31', default: false, fits: false },
    };
    renderDetail({ generateBoqId: 'b1' });
    const preview = await previewFromDeepLink();
    expect(preview).toHaveTextContent(
      '20 workers per position where the bill gives no crew (60 positions), the most the plan assumes. Even with them the work fits your end date only with shorter durations.',
    );
    expect(preview).toHaveTextContent('every duration was shortened to 78% of its estimate');
    expect(preview).not.toHaveTextContent('does not fit your end date');
    expect(preview).not.toHaveTextContent('the fewest that fit');
  });

  it('asks again with the workers a person types in', async () => {
    state.preview = { ...PREVIEW, workers_per_position: 7, workers_assumed: false, positions_without_workers: 60 };
    renderDetail({ generateBoqId: 'b1' });
    fireEvent.change(await screen.findByTestId('generate-workers'), { target: { value: '7' } });
    const preview = await previewFromDeepLink();
    expect(state.previewCalls[0].workers).toBe(7);
    expect(preview).toHaveTextContent('At least 7 workers per position where the bill gives no crew (60 positions), as you set it.');
    fireEvent.click(screen.getByRole('button', { name: 'Create the plan' }));
    await waitFor(() => expect(state.generateCalls).toHaveLength(1));
    expect(state.generateCalls[0].workers).toBe(7);
  });

  it('refuses workers outside one to twenty', async () => {
    renderDetail({ generateBoqId: 'b1' });
    fireEvent.change(await screen.findByTestId('generate-workers'), { target: { value: '25' } });
    expect(screen.getByText('Enter a whole number from 1 to 20.')).toBeInTheDocument();
    expect(screen.getByTestId('generate-preview')).toBeDisabled();
  });

  it('starts from the workers the last generation was asked for', async () => {
    state.record = {
      id: 'sch',
      metadata_: { boq_generation: { generated_at: 'x', workers_per_position: 9, workers_assumed: false } },
    };
    renderDetail({ generateBoqId: 'b1' });
    await waitFor(() => expect(screen.getByTestId('generate-workers')).toHaveValue(9));
  });

  it('says a plan past the end date is already at half, not shortened to fit', async () => {
    state.preview = {
      ...PREVIEW,
      crews: 4,
      compressed_pct: 50,
      fits: false,
      planned_end: '2027-03-01',
      warnings: [{ code: 'plan_exceeds_window', planned_end: '2027-03-01', requested_end: '2026-10-31', percent: 50 }],
    };
    renderDetail({ generateBoqId: 'b1' });
    const preview = await previewFromDeepLink();
    expect(preview).toHaveTextContent('Every duration is already cut to half of its estimate');
    expect(preview).not.toHaveTextContent('To fit the dates you asked for');
  });

  it('clears all activities after a confirmation that counts them', async () => {
    state.activities = THREE;
    renderDetail();

    fireEvent.click(await screen.findByRole('button', { name: 'Clear all activities' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('3 activities');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Clear all' }));
    await waitFor(() => expect(state.cleared).toBe(1));
  });
});

describe('schedule list', () => {
  const PROJECT = { id: 'p1', name: 'Tower', description: '', region: 'DACH', currency: 'EUR' };

  it('reaches archives beyond the first page and recovers after deleting the last card', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    state.schedules = Array.from({ length: 51 }, (_, index) => ({
      ...SCHEDULE, id: `s${index}`, name: `Archive ${index}`, status: 'archived',
    }));
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} />);
    fireEvent.change(await screen.findByRole('combobox', { name: 'Schedule view' }), { target: { value: 'archived' } });
    expect(await screen.findByText('Archive 0')).toBeInTheDocument();
    expect(screen.queryByText('Archive 50')).toBeNull();
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    expect(await screen.findByText('Archive 50')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Next page' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Permanently delete Archive 50' }));
    fireEvent.click(within(await screen.findByRole('alertdialog')).getByRole('button', { name: 'Delete permanently' }));
    expect(await screen.findByText('Archive 0')).toBeInTheDocument();
    expect(screen.queryByText('Archive 50')).toBeNull();
  });

  it('archives a schedule from its card without opening it', async () => {
    state.schedules = [{ ...SCHEDULE, status: 'completed' }];
    state.activities = THREE;
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Archive Main schedule' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent('activities, baselines and links will be kept');
    fireEvent.click(within(confirm).getByRole('button', { name: 'Archive' }));
    await waitFor(() => expect(state.archivedSchedules).toEqual(['sch']));
    expect(state.deletedSchedules).toEqual([]);
    // The card's button does not also open the schedule.
    expect(screen.queryByRole('button', { name: /Back to schedules/ })).toBeNull();
  });

  it('says baselines are kept when an editor archives their schedule', async () => {
    state.schedules = [{ ...SCHEDULE, status: 'active' }];
    state.activities = THREE;
    state.baselines = [
      { id: 'bl1', schedule_id: 'sch', project_id: 'p1', name: 'Contract' },
      { id: 'bl2', schedule_id: 'sch', project_id: 'p1', name: 'Rebaseline' },
      { id: 'bl3', schedule_id: 'other', project_id: 'p1', name: 'Other schedule' },
    ];
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} />);

    fireEvent.click(await screen.findByRole('button', { name: 'Archive Main schedule' }));
    const confirm = await screen.findByRole('alertdialog');
    expect(confirm).toHaveTextContent(/baselines and links will be kept/);
  });

  it('rechecks permanent-delete permission before offering an admin confirmation', async () => {
    useAuthStore.setState({ userRole: 'admin' });
    state.schedules = [{ ...SCHEDULE, status: 'archived' }];
    state.activities = THREE;
    state.baselines = [{ id: 'bl1', schedule_id: 'sch', project_id: 'p1', name: 'Contract' }];
    state.deleteBlocked = true;
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} />);

    fireEvent.change(await screen.findByRole('combobox', { name: 'Schedule view' }), { target: { value: 'archived' } });
    fireEvent.click(await screen.findByRole('button', { name: 'Permanently delete Main schedule' }));
    await waitFor(() => expect(useToastStore.getState().toasts).toHaveLength(1));
    const toast = useToastStore.getState().toasts[0];
    expect(toast.type).toBe('warning');
    expect(toast.message).toMatch(/Only an administrator can permanently delete/);
    expect(screen.queryByRole('alertdialog')).toBeNull();
    expect(state.deletedSchedules).toEqual([]);
  });

  it('lets the reader choose the schedule a BOQ deep link generates into', async () => {
    state.schedules = [
      { ...SCHEDULE, id: 'sA', name: 'Schedule A' },
      { ...SCHEDULE, id: 'sB', name: 'Schedule B' },
    ];
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} generateBoqId="b1" onConsumeGenerateBoq={vi.fn()} />);

    const chooser = await screen.findByRole('dialog', { name: /Which schedule/i });
    // Nothing was opened behind the reader's back.
    expect(state.ganttCalls).toEqual([]);
    fireEvent.click(within(chooser).getByRole('button', { name: /Schedule B/ }));

    expect(await screen.findByRole('heading', { name: 'Schedule B' })).toBeInTheDocument();
    await waitFor(() => expect(state.ganttCalls).toContain('sB'));
  });

  it('offers a new schedule from the chooser', async () => {
    state.schedules = [{ ...SCHEDULE, id: 'sA', name: 'Schedule A' }];
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} generateBoqId="b1" onConsumeGenerateBoq={vi.fn()} />);

    const chooser = await screen.findByRole('dialog', { name: /Which schedule/i });
    fireEvent.click(within(chooser).getByRole('button', { name: 'New schedule' }));
    const create = await screen.findByRole('dialog', { name: 'Create Schedule' });
    expect(within(create).getByLabelText(/Schedule Name/)).toHaveValue('Construction schedule');
  });

  it('lets a BOQ deep link choose an existing schedule beyond the first page', async () => {
    state.schedules = Array.from({ length: 51 }, (_, index) => ({
      ...SCHEDULE, id: `target-${index}`, name: `Target ${index}`,
    }));
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} generateBoqId="b1" onConsumeGenerateBoq={vi.fn()} />);
    const chooser = await screen.findByRole('dialog', { name: /Which schedule/i });
    expect(within(chooser).queryByRole('button', { name: /Target 50/ })).toBeNull();
    fireEvent.click(within(chooser).getByRole('button', { name: 'Next page' }));
    fireEvent.click(await within(chooser).findByRole('button', { name: /Target 50/ }));
    expect(await screen.findByRole('heading', { name: 'Target 50' })).toBeInTheDocument();
    await waitFor(() => expect(state.ganttCalls).toContain('target-50'));
  });

  it('opens a prefilled new schedule when the project has none', async () => {
    wrap(<ProjectSchedules project={PROJECT} onBack={vi.fn()} generateBoqId="b1" onConsumeGenerateBoq={vi.fn()} />);
    const create = await screen.findByRole('dialog', { name: 'Create Schedule' });
    expect(within(create).getByLabelText(/Schedule Name/)).toHaveValue('Construction schedule');
  });
});
