// @ts-nocheck
/**
 * Creating an activity inside a section, on the schedule page itself.
 *
 * The server used to append a new child at the bottom of the flat order, and
 * the page rendered that order as it came. The fake server here does the same
 * (the new row comes back last), so the tests prove the page files it inside
 * its section on its own, in the Table view and in the Gantt view that opens
 * by default. In the Table view the section is collapsed first: creating into
 * it has to open it, or the new row is made out of sight.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';
import { useAuthStore } from '@/stores/useAuthStore';

const state = vi.hoisted(() => ({ activities: [] as any[], created: [] as any[] }));

// The queries below read the English labels, so render each string from the
// default the page passes rather than from whatever the shared setup loaded.
vi.mock('react-i18next', async () => {
  const actual = await vi.importActual<typeof import('react-i18next')>('react-i18next');
  const t = (key: string, a?: unknown, b?: unknown) => {
    const opts = (typeof a === 'object' && a ? a : typeof b === 'object' && b ? b : {}) as Record<string, unknown>;
    const text = typeof a === 'string' ? a : typeof opts.defaultValue === 'string' ? opts.defaultValue : key;
    return text.replace(/\{\{\s*(\w+)\s*\}\}/g, (_m, k) => String(opts[k] ?? ''));
  };
  return { ...actual, useTranslation: () => ({ t, i18n: { language: 'en', changeLanguage: async () => {} } }) };
});

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  const known = {
    getGantt: async () => ({
      activities: state.activities,
      summary: { total_activities: state.activities.length, completed: 0, in_progress: 0, delayed: 0 },
    }),
    suggestWbsCode: async (_scheduleId: string, parentId?: string) => ({ wbs_code: parentId === 's1' ? '1.2' : '3' }),
    createActivity: async (_scheduleId: string, body: any) => {
      const row = {
        id: 'new1',
        name: body.name,
        wbs_code: body.wbs_code,
        start_date: body.start_date,
        end_date: body.end_date,
        duration_days: 5,
        progress_pct: 0,
        activity_type: body.activity_type,
        parent_id: body.parent_id ?? null,
        dependencies: [],
        status: 'not_started',
        color: '#0071e3',
        boq_position_ids: [],
      };
      state.created.push(body);
      // Appended at the end, the way the flat server order used to return it.
      state.activities = [...state.activities, row];
      return row;
    },
  };
  // Anything else the page asks for on mount answers empty.
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
  // The SVG chart is replaced by its row order, which is what is under test.
  return {
    ...actual,
    GanttChart: ({ activities }: { activities: Array<{ id: string }> }) => (
      <ol data-testid="svg-gantt">
        {activities.map((a) => (
          <li key={a.id} data-testid="svg-gantt-row">
            {a.id}
          </li>
        ))}
      </ol>
    ),
  };
});

import { ScheduleDetail } from './SchedulePage';

const base = {
  start_date: '2026-05-04',
  end_date: '2026-05-08',
  duration_days: 5,
  progress_pct: 0,
  dependencies: [],
  status: 'not_started',
  color: '#0071e3',
  boq_position_ids: [],
};
const SEED = [
  { ...base, id: 's1', name: 'Earthworks', wbs_code: '1', activity_type: 'summary', parent_id: null },
  { ...base, id: 'c1', name: 'Excavate', wbs_code: '1.1', activity_type: 'task', parent_id: 's1' },
  { ...base, id: 'o1', name: 'Structure', wbs_code: '2', activity_type: 'task', parent_id: null },
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

function renderDetail() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScheduleDetail schedule={SCHEDULE} projectId="p1" onBack={vi.fn()} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

async function createUnderSection() {
  fireEvent.click(screen.getAllByRole('button', { name: /Add Activity/i })[0]);
  const dialog = await screen.findByRole('dialog');
  const d = within(dialog);
  fireEvent.change(d.getByLabelText(/Activity Name/i), { target: { value: 'Backfill' } });
  fireEvent.change(d.getByDisplayValue('Top level (no parent)'), { target: { value: 's1' } });
  // The section's next code is filled in, and stays editable.
  await waitFor(() => expect((d.getByLabelText(/WBS Code/i) as HTMLInputElement).value).toBe('1.2'));
  fireEvent.change(d.getByLabelText(/Start Date/i), { target: { value: '2026-05-11' } });
  fireEvent.change(d.getByLabelText(/End Date/i), { target: { value: '2026-05-15' } });
  fireEvent.click(d.getByRole('button', { name: /Create Activity/i }));
  await waitFor(() => expect(state.created).toHaveLength(1));
  expect(state.created[0]).toMatchObject({ parent_id: 's1', wbs_code: '1.2' });
}

describe('ScheduleDetail: a new activity lands inside its section', () => {
  beforeEach(() => {
    // Adding activities is editor work; a viewer is not offered the button.
    useAuthStore.setState({ userRole: 'editor' });
    state.activities = SEED.map((a) => ({ ...a }));
    state.created = [];
  });

  it('in the Table view, opening the collapsed section it went into', async () => {
    renderDetail();
    fireEvent.click(await screen.findByRole('button', { name: /^Table$/ }));
    fireEvent.click(await screen.findByTestId('grid-toggle-s1'));
    expect(screen.queryByTestId('grid-row-c1')).toBeNull();

    await createUnderSection();

    await screen.findByTestId('grid-row-new1');
    const order = screen.getAllByTestId(/^grid-row-/).map((el) => el.getAttribute('data-testid'));
    expect(order).toEqual(['grid-row-s1', 'grid-row-c1', 'grid-row-new1', 'grid-row-o1']);
    expect(screen.getByTestId('grid-toggle-s1')).toHaveAttribute('aria-expanded', 'true');
  });

  it('in the Gantt view, which opens by default', async () => {
    renderDetail();
    await screen.findByTestId('svg-gantt');

    await createUnderSection();

    await waitFor(() =>
      expect(screen.getAllByTestId('svg-gantt-row').map((el) => el.textContent)).toEqual(['s1', 'c1', 'new1', 'o1']),
    );
  });
});
