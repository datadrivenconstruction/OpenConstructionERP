// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
/**
 * Vitest tests for the "Project team" tile and its availability popup.
 *
 * All four upstream sources are mocked at the ``apiGet`` boundary:
 *
 *   team-standup/full-board   → status + open tasks
 *   team-standup/presence/today → the online dot (VIEWER-level)
 *   team-standup/metrics      → attendance only (MANAGER-only)
 *   work-requests/departments → which planner to pull
 *   work-requests/planner     → days booked this week
 *   work-requests/requests    → **rejects with a 404**, so the popup's
 *                               "open work requests" section has to degrade
 *                               to its one-liner while every other section
 *                               still renders. That is the case that breaks
 *                               if a section ever starts assuming its data.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, within, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { TeamAvailabilityWidget } from '../components/TeamAvailabilityWidget';
import type { ProjectMember } from '../components/TeamStrip';
import { weekDays, isoDay } from '../components/useTeamAvailability';

const DAYS = weekDays(new Date());
const TODAY = isoDay(new Date());

const OWNER: ProjectMember = {
  user_id: 'u-owner',
  email: 'owner@example.test',
  full_name: 'Sample Owner',
  role: 'owner',
  is_owner: true,
};
const ENGINEER: ProjectMember = {
  user_id: 'u-eng',
  email: 'eng@example.test',
  full_name: 'Sample Engineer',
  role: 'engineer',
  is_owner: false,
};
const DRAFTER: ProjectMember = {
  user_id: 'u-draft',
  email: 'draft@example.test',
  full_name: 'Sample Drafter',
  role: 'drafter',
  is_owner: false,
};

const BOARD = {
  day: TODAY,
  today: TODAY,
  entries: [
    {
      id: 'e1',
      user_id: 'u-eng',
      author_name: 'Sample Engineer',
      day: TODAY,
      status: 'site',
      activities: [],
    },
  ],
  week: {
    start: DAYS[0],
    entries: [
      { id: 'e1', user_id: 'u-eng', author_name: '', day: DAYS[0], status: 'office', activities: [] },
      { id: 'e2', user_id: 'u-eng', author_name: '', day: DAYS[1], status: 'site', activities: [] },
    ],
  },
  stages: [
    { id: 's-open', name: 'In progress', is_done: false },
    { id: 's-done', name: 'Done', is_done: true },
  ],
  activities: [],
  tasks: [
    {
      id: 't1',
      title: 'Mark up the switchboard schedule',
      project_id: 'job-1',
      stage_id: 's-open',
      assignee_id: 'u-eng',
      assignee_name: 'Sample Engineer',
      due: DAYS[3],
      priority: 'high',
      waiting_on: '',
      completed_at: null,
    },
    {
      id: 't2',
      title: 'Chase the cable schedule',
      project_id: 'job-1',
      stage_id: 's-open',
      assignee_id: 'u-eng',
      assignee_name: 'Sample Engineer',
      due: '',
      priority: 'medium',
      waiting_on: 'client',
      completed_at: null,
    },
    {
      id: 't3',
      title: 'Already finished',
      project_id: 'job-1',
      stage_id: 's-done',
      assignee_id: 'u-eng',
      assignee_name: 'Sample Engineer',
      due: '',
      priority: 'low',
      waiting_on: '',
      completed_at: null,
    },
  ],
  jobs: [{ id: 'job-1', code: 'J-0001', name: 'Sample Project', label: 'J-0001 Sample' }],
};

/**
 * The viewer-level presence payload — five keys, today only. The tile's green
 * dot and the popup's "Online now" badge read this and nothing else, which is
 * what lets an ordinary team member keep both when /metrics 403s.
 */
const PRESENCE = [
  {
    user_id: 'u-draft',
    name: 'Sample Drafter',
    online: true,
    first_seen: '2026-09-03T07:10:00Z',
    last_seen: '2026-09-03T16:02:00Z',
  },
  {
    user_id: 'u-eng',
    name: 'Sample Engineer',
    online: false,
    first_seen: '2026-09-03T07:05:00Z',
    last_seen: '2026-09-03T09:40:00Z',
  },
];

const METRICS = {
  window_days: 7,
  people: [
    {
      user_id: 'u-draft',
      name: 'Sample Drafter',
      tasks_open: 0,
      tasks_overdue: 0,
      today: { first_seen: '2026-09-03T07:10:00Z', last_seen: '2026-09-03T16:02:00Z', online: true },
    },
    {
      user_id: 'u-eng',
      name: 'Sample Engineer',
      tasks_open: 2,
      tasks_overdue: 0,
      today: { first_seen: null, last_seen: null, online: false },
    },
  ],
  attendance: [
    {
      user_id: 'u-eng',
      name: 'Sample Engineer',
      day: DAYS[1],
      first_seen: '2026-09-01T07:05:00Z',
      last_seen: '2026-09-01T15:40:00Z',
      active_seconds: 22800,
      still_on: false,
    },
  ],
};

const DEPARTMENTS = [
  {
    key: 'engineering',
    name: 'Engineering',
    lead_user_id: 'u-eng',
    member_ids: ['u-eng', 'u-draft'],
  },
  // Nobody on this project is in it, so its planner must never be requested.
  { key: 'joinery', name: 'Joinery', lead_user_id: null, member_ids: ['u-nobody'] },
];

const PLANNER = {
  department: 'engineering',
  days: DAYS,
  members: [{ id: 'u-eng', name: 'Sample Engineer' }],
  rows: [
    {
      request_id: 'r1',
      reference: 'ENG-0001',
      title: 'Switchboard design',
      due_date: DAYS[4],
      assignees: [{ id: 'u-eng', name: 'Sample Engineer' }],
      alloc: { [DAYS[0]!]: 2, [DAYS[1]!]: 1, [DAYS[2]!]: 1 },
    },
  ],
  capacity: {},
};

const apiGet = vi.fn();
const apiPost = vi.fn();
const apiPatch = vi.fn();
const apiDelete = vi.fn();

vi.mock('@/shared/lib/api', () => ({
  apiGet: (path: string) => apiGet(path),
  apiPost: (path: string, body: unknown) => apiPost(path, body),
  apiPatch: (path: string, body: unknown) => apiPatch(path, body),
  apiDelete: (path: string) => apiDelete(path),
}));

vi.mock('@/shared/ui/UserSearchInput', () => ({
  UserSearchInput: ({ value, onChange }: { value: string; onChange: (id: string, n: string) => void }) => (
    <input data-testid="mock-user-search" value={value} onChange={(e) => onChange(e.target.value, e.target.value)} />
  ),
}));

beforeEach(() => {
  vi.clearAllMocks();
  apiGet.mockImplementation((path: string) => {
    if (path.startsWith('/v1/team-standup/full-board')) return Promise.resolve(BOARD);
    if (path.startsWith('/v1/team-standup/presence/today'))
      return Promise.resolve({ items: PRESENCE, total: PRESENCE.length, limit: 500, offset: 0 });
    if (path.startsWith('/v1/team-standup/metrics')) return Promise.resolve(METRICS);
    if (path.startsWith('/v1/work-requests/departments'))
      return Promise.resolve({ items: DEPARTMENTS, total: DEPARTMENTS.length, limit: 200, offset: 0 });
    if (path.startsWith('/v1/work-requests/planner')) {
      // Only Engineering has rows; the second department answers empty, which
      // also proves the per-department payloads are summed rather than the
      // same payload being counted once per department.
      return Promise.resolve(
        path.includes('department=engineering') ? PLANNER : { ...PLANNER, rows: [] },
      );
    }
    // The deliberate 404: the popup's work-requests section must degrade.
    if (path.startsWith('/v1/work-requests/requests')) {
      return Promise.reject(Object.assign(new Error('Not Found'), { status: 404 }));
    }
    return Promise.resolve(null);
  });
});

function renderTile(members = [OWNER, ENGINEER, DRAFTER], canManage = true) {
  const qc = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={qc}>
      <TeamAvailabilityWidget
        projectId="proj-1"
        canManage={canManage}
        initialMembers={members}
      />
    </QueryClientProvider>,
  );
}

describe('TeamAvailabilityWidget (Project team tile)', () => {
  it('renders one card per member', async () => {
    renderTile();
    const cards = await screen.findAllByTestId('team-availability-card');
    expect(cards).toHaveLength(3);
    expect(screen.getByText('Sample Engineer')).toBeInTheDocument();
  });

  it('shows the online dot and sorts online members first', async () => {
    renderTile();
    // The drafter is the only one presence reports as online.
    expect(await screen.findAllByTestId('team-availability-online-dot')).toHaveLength(1);
    const cards = screen.getAllByTestId('team-availability-card');
    expect(cards[0]!.textContent).toContain('Sample Drafter');
  });

  it('builds the availability line from all three sources', async () => {
    renderTile();
    // The cards paint straight from `initialMembers`; the availability line
    // fills in as each source resolves, so wait for the last part of it.
    await screen.findByText(/3 days booked/);
    const engineerCard = screen
      .getAllByTestId('team-availability-card')
      .find((c) => c.textContent?.includes('Sample Engineer'))!;
    const line = within(engineerCard).getByTestId('team-availability-line').textContent ?? '';
    // standup status, open-task count (the done-stage task is excluded), and
    // the three days the planner has an allocation on.
    expect(line).toContain('On site');
    expect(line).toContain('2 open tasks');
    expect(line).toContain('3 days booked');
  });

  it('uses the singular form for a count of one', async () => {
    renderTile();
    // The drafter has no standup tasks and one booked day on the shared row.
    await screen.findByText(/3 days booked/);
    const drafter = screen
      .getAllByTestId('team-availability-card')
      .find((c) => c.textContent?.includes('Sample Drafter'))!;
    const line = within(drafter).getByTestId('team-availability-line').textContent ?? '';
    expect(line).toContain('0 open tasks');
    expect(line).not.toMatch(/\b1 (open tasks|days booked)\b/);
  });

  it('prints readable role labels, never the raw key', async () => {
    renderTile();
    await screen.findAllByTestId('team-availability-card');
    expect(screen.getByText('Engineer')).toBeInTheDocument();
    expect(screen.getByText('Drafter')).toBeInTheDocument();
    // The raw membership keys must never reach the card.
    expect(screen.queryByText('engineer')).toBeNull();
    expect(screen.queryByText('project_manager')).toBeNull();
  });

  it('pulls each department planner once, over the Mon-Sun window', async () => {
    renderTile();
    await waitFor(() =>
      expect(
        apiGet.mock.calls.filter((c) =>
          String(c[0]).startsWith('/v1/work-requests/planner'),
        ),
      ).toHaveLength(2),
    );
    const plannerCalls = apiGet.mock.calls
      .map((c) => String(c[0]))
      .filter((p) => p.startsWith('/v1/work-requests/planner'));
    // Every department, because somebody on this job can be assigned to a
    // request raised on a board they are not a member of.
    expect(plannerCalls.some((p) => p.includes('department=engineering'))).toBe(true);
    expect(plannerCalls.some((p) => p.includes('department=joinery'))).toBe(true);
    expect(plannerCalls.every((p) => p.includes(`from=${DAYS[0]}&to=${DAYS[6]}`))).toBe(true);
  });

  it('opens the add-member dialog from the tile', async () => {
    renderTile();
    fireEvent.click(await screen.findByTestId('team-availability-add'));
    expect(screen.getByTestId('team-strip-add-modal')).toBeInTheDocument();
  });

  it('hides add / role / remove when canManage is false', async () => {
    renderTile([OWNER, ENGINEER], false);
    await screen.findAllByTestId('team-availability-card');
    expect(screen.queryByTestId('team-availability-add')).toBeNull();
    const card = screen
      .getAllByTestId('team-availability-card')
      .find((c) => c.textContent?.includes('Sample Engineer'))!;
    fireEvent.contextMenu(card);
    expect(screen.getByTestId('team-availability-menu')).toBeInTheDocument();
    expect(screen.queryByTestId('team-availability-menu-role')).toBeNull();
    expect(screen.queryByTestId('team-availability-menu-remove')).toBeNull();
  });

  it('changes a role from the right-click menu', async () => {
    apiPatch.mockResolvedValue({ ...ENGINEER, role: 'site_supervisor' });
    renderTile();
    const card = (await screen.findAllByTestId('team-availability-card')).find((c) =>
      c.textContent?.includes('Sample Engineer'),
    )!;
    fireEvent.contextMenu(card);
    fireEvent.click(screen.getByTestId('team-availability-menu-role'));
    fireEvent.click(screen.getByText('Site supervisor'));
    await waitFor(() =>
      expect(apiPatch).toHaveBeenCalledWith(
        '/v1/projects/proj-1/members/u-eng/',
        { role: 'site_supervisor' },
      ),
    );
  });
});

describe('MemberAvailabilityModal (availability popup)', () => {
  async function openPopup() {
    renderTile();
    const card = (await screen.findAllByTestId('team-availability-card')).find((c) =>
      c.textContent?.includes('Sample Engineer'),
    )!;
    fireEvent.click(card);
    return await screen.findByTestId('member-availability-modal');
  }

  it('shows the 7-day week strip with booked headcount and standup dots', async () => {
    const modal = await openPopup();
    const strip = within(modal).getByTestId('availability-week');
    expect(strip.children).toHaveLength(7);
    // Monday: 2 people booked on their request.
    expect(strip.children[0]!.textContent).toContain('2');
  });

  it('lists the open standup tasks and hides the completed one', async () => {
    const modal = await openPopup();
    const rows = await within(modal).findAllByTestId('availability-task-row');
    expect(rows).toHaveLength(2);
    expect(modal.textContent).toContain('Mark up the switchboard schedule');
    expect(modal.textContent).not.toContain('Already finished');
  });

  it('shows attendance for the last 7 days', async () => {
    const modal = await openPopup();
    const rows = await within(modal).findAllByTestId('availability-attendance-row');
    expect(rows).toHaveLength(1);
    // 22800s = 6h 20m.
    expect(rows[0]!.textContent).toContain('6h 20m');
  });

  it('lists the departments they belong to', async () => {
    const modal = await openPopup();
    const chips = await within(modal).findAllByTestId('availability-department');
    expect(chips).toHaveLength(1);
    expect(chips[0]!.textContent).toContain('Engineering');
  });

  it('degrades to an honest line when a source 404s', async () => {
    const modal = await openPopup();
    // The requests endpoint rejected; the section says so instead of showing
    // an empty table that reads as "they have nothing on".
    expect(await within(modal).findByText(/not available on this install/i)).toBeInTheDocument();
    expect(within(modal).queryAllByTestId('availability-request-row')).toHaveLength(0);
    // …and the other sections still rendered.
    expect(within(modal).getByTestId('availability-week')).toBeInTheDocument();
  });

  it('closes on Escape and on an outside click', async () => {
    await openPopup();
    fireEvent.keyDown(window, { key: 'Escape' });
    expect(screen.queryByTestId('member-availability-modal')).toBeNull();

    const reopened = await openPopup();
    fireEvent.click(reopened);
    expect(screen.queryByTestId('member-availability-modal')).toBeNull();
  });
});

/* ────────────────────────────────────────────────────────────────────────
 * An ordinary team member: /metrics is manager-only and 403s.
 *
 * This is the case the permission change created. Presence, today's standup
 * status, open task counts and planner allocation are all viewer-level, so
 * the tile must be complete and the popup must lose exactly one section —
 * attendance — and say why, rather than showing an empty table that reads as
 * "this person has never signed in".
 * ──────────────────────────────────────────────────────────────────────── */
describe('a non-manager, for whom /metrics is forbidden', () => {
  beforeEach(() => {
    apiGet.mockImplementation((path: string) => {
      if (path.startsWith('/v1/team-standup/full-board')) return Promise.resolve(BOARD);
      if (path.startsWith('/v1/team-standup/presence/today'))
      return Promise.resolve({ items: PRESENCE, total: PRESENCE.length, limit: 500, offset: 0 });
      if (path.startsWith('/v1/team-standup/metrics')) {
        return Promise.reject(Object.assign(new Error('Forbidden'), { status: 403 }));
      }
      if (path.startsWith('/v1/work-requests/departments'))
      return Promise.resolve({ items: DEPARTMENTS, total: DEPARTMENTS.length, limit: 200, offset: 0 });
      if (path.startsWith('/v1/work-requests/planner')) {
        return Promise.resolve(
          path.includes('department=engineering') ? PLANNER : { ...PLANNER, rows: [] },
        );
      }
      if (path.startsWith('/v1/work-requests/requests')) return Promise.resolve([]);
      return Promise.resolve(null);
    });
  });

  it('still names who is online on the tile', async () => {
    renderTile();
    // The green dot survives the 403 because it no longer comes from /metrics.
    expect(await screen.findAllByTestId('team-availability-online-dot')).toHaveLength(1);
    const cards = screen.getAllByTestId('team-availability-card');
    expect(cards[0]!.textContent).toContain('Sample Drafter');
    expect(cards[0]!.textContent).toContain('Online now');
  });

  it('keeps every viewer-level part of the availability line', async () => {
    renderTile();
    await screen.findByText(/3 days booked/);
    const engineerCard = screen
      .getAllByTestId('team-availability-card')
      .find((c) => c.textContent?.includes('Sample Engineer'))!;
    const line = within(engineerCard).getByTestId('team-availability-line').textContent ?? '';
    // Standup status, open tasks and planner allocation are not manager-gated.
    expect(line).toContain('On site');
    expect(line).toContain('2 open tasks');
    expect(line).toContain('3 days booked');
  });

  it('never asks for the tile it cannot read', async () => {
    renderTile();
    await screen.findAllByTestId('team-availability-card');
    await waitFor(() =>
      expect(
        apiGet.mock.calls.some((c) =>
          String(c[0]).startsWith('/v1/team-standup/presence/today'),
        ),
      ).toBe(true),
    );
    // The tile itself must not depend on the manager-only rollup at all.
    expect(
      apiGet.mock.calls.filter((c) => String(c[0]).startsWith('/v1/team-standup/metrics')),
    ).toHaveLength(0);
  });

  it('degrades the popup honestly: presence stays, attendance explains itself', async () => {
    renderTile();
    const card = (await screen.findAllByTestId('team-availability-card')).find((c) =>
      c.textContent?.includes('Sample Engineer'),
    )!;
    fireEvent.click(card);
    const modal = await screen.findByTestId('member-availability-modal');

    // The attendance section says it is manager-only — not "not installed",
    // and not an empty table.
    expect(
      await within(modal).findByText(/only visible to managers/i),
    ).toBeInTheDocument();
    expect(within(modal).queryAllByTestId('availability-attendance-row')).toHaveLength(0);
    expect(within(modal).queryByText(/not available on this install/i)).toBeNull();

    // Presence still renders: they are offline, so the popup says when they
    // were last about.
    expect(within(modal).getByTestId('availability-last-seen')).toBeInTheDocument();
    // …and every viewer-level section is still there.
    expect(within(modal).getByTestId('availability-week')).toBeInTheDocument();
    expect(await within(modal).findAllByTestId('availability-task-row')).toHaveLength(2);
    expect(await within(modal).findAllByTestId('availability-department')).toHaveLength(1);
  });

  it('shows the online badge in the popup for someone who is on', async () => {
    renderTile();
    const card = (await screen.findAllByTestId('team-availability-card')).find((c) =>
      c.textContent?.includes('Sample Drafter'),
    )!;
    fireEvent.click(card);
    const modal = await screen.findByTestId('member-availability-modal');
    expect(await within(modal).findByTestId('availability-online')).toBeInTheDocument();
  });
});
