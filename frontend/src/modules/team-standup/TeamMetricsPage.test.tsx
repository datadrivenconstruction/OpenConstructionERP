// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// The metrics page must survive a backend that does not serve the
// endpoint yet (404 -> honest empty state, never a crash) and must render
// people / jobs / modules from a payload.
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi, beforeEach } from 'vitest';

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';

import TeamMetricsPage from './TeamMetricsPage';
import type { TeamMetrics } from './metricsApi';

const fetchTeamMetrics = vi.fn();
vi.mock('./metricsApi', () => ({
  fetchTeamMetrics: (...args: unknown[]) => fetchTeamMetrics(...args),
}));

const isoDay = (d: Date) => `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
const TODAY = isoDay(new Date());
const YESTERDAY = isoDay(new Date(Date.now() - 86_400_000));
const NOW_ISO = new Date(Date.now() - 60_000).toISOString();

const PAYLOAD: TeamMetrics = {
  window_days: 30,
  people: [
    {
      user_id: 'u1',
      name: 'Sam Rivera',
      tasks_completed: 3,
      tasks_open: 2,
      tasks_overdue: 1,
      avg_days_to_close: 4.5,
      standups_posted: 8,
      blockers_raised: 1,
      seconds_by_module: { 'team-standup': 3600, rfi: 600 },
      seconds_by_job: [{ project_id: 'p1', code: 'J0001', name: 'Northbank - Plant upgrade', seconds: 3000 }],
      today: { first_seen: '2026-09-02T00:02:00+00:00', last_seen: NOW_ISO, online: true },
    },
    {
      user_id: 'u2',
      name: 'Lee Okafor',
      tasks_completed: 0,
      tasks_open: 1,
      tasks_overdue: 0,
      avg_days_to_close: null,
      standups_posted: 1,
      blockers_raised: 0,
      seconds_by_module: {},
      seconds_by_job: [],
      today: { first_seen: '2026-09-01T22:00:00+00:00', last_seen: '2026-09-02T01:00:00+00:00', online: false },
    },
  ],
  attendance: [
    {
      user_id: 'u1',
      name: 'Sam Rivera',
      day: TODAY,
      first_seen: '2026-09-02T00:02:00+00:00',
      last_seen: NOW_ISO,
      logins: ['2026-09-02T00:02:00+00:00'],
      logouts: [],
      ends: [],
      active_seconds: 24_300,
      still_on: true,
    },
    {
      user_id: 'u2',
      name: 'Lee Okafor',
      day: TODAY,
      first_seen: '2026-09-01T22:00:00+00:00',
      last_seen: '2026-09-02T01:00:00+00:00',
      logins: ['2026-09-01T22:00:00+00:00', '2026-09-01T23:30:00+00:00'],
      logouts: ['2026-09-02T01:00:00+00:00'],
      ends: ['2026-09-02T01:00:00+00:00'],
      active_seconds: 3_600,
      still_on: false,
    },
    {
      user_id: 'u2',
      name: 'Lee Okafor',
      day: YESTERDAY,
      first_seen: '2026-09-01T00:00:00+00:00',
      last_seen: '2026-09-01T06:00:00+00:00',
      logins: ['2026-09-01T00:00:00+00:00'],
      logouts: [],
      ends: [],
      active_seconds: 0,
      still_on: false,
    },
  ],
  jobs: [
    {
      project_id: 'p1',
      code: 'J0001',
      name: 'Northbank - Plant upgrade',
      open_tasks: 2,
      completed: 3,
      overdue: 1,
      seconds_total: 3000,
      people: [{ user_id: 'u1', name: 'Sam Rivera', seconds: 3000 }],
    },
  ],
  modules: [
    { module_key: 'team-standup', seconds: 3600 },
    { module_key: 'rfi', seconds: 600 },
  ],
};

function mount() {
  return render(
    <MemoryRouter initialEntries={['/team-standup/metrics']}>
      <TeamMetricsPage />
    </MemoryRouter>,
  );
}

describe('TeamMetricsPage', () => {
  beforeEach(() => {
    fetchTeamMetrics.mockReset();
    localStorage.clear();
    // The page is manager-and-above; every test below reads it as one.
    useAuthStore.setState({ userRole: 'manager' });
  });

  it('shows the not-available state on a 404 instead of crashing', async () => {
    fetchTeamMetrics.mockRejectedValue(new ApiError(404, 'Not Found', undefined));
    mount();
    expect(await screen.findByText(/Metrics are not available on this server yet/i)).toBeTruthy();
    expect(fetchTeamMetrics).toHaveBeenCalledWith(30);
  });

  it('renders people, jobs and modules from the payload and switches the window', async () => {
    fetchTeamMetrics.mockResolvedValue(PAYLOAD);
    mount();
    // Sam is in People and in Attendance.
    expect((await screen.findAllByText('Sam Rivera')).length).toBe(2);
    expect(screen.getAllByText('J0001').length).toBeGreaterThan(0);
    expect(screen.getByText('Northbank - Plant upgrade')).toBeTruthy();
    expect(screen.getByText('4.5')).toBeTruthy();
    // Legend under People + the module row: at least twice. 'rfi' is a
    // route slug; a reader must never see the slug.
    expect(screen.getAllByText('RFI').length).toBeGreaterThanOrEqual(2);
    expect(screen.queryByText('rfi')).toBeNull();
    expect(screen.queryByText('team-standup')).toBeNull();
    // No "no presence" empty state when presence exists.
    expect(screen.queryByText(/No presence recorded yet/i)).toBeNull();

    fireEvent.click(screen.getByRole('button', { name: '7d' }));
    await waitFor(() => expect(fetchTeamMetrics).toHaveBeenLastCalledWith(7));
  });

  it('right-click on a person offers "Open their tasks"', async () => {
    fetchTeamMetrics.mockResolvedValue(PAYLOAD);
    mount();
    const cell = (await screen.findAllByText('Sam Rivera'))[0] as HTMLElement; // the People row
    fireEvent.contextMenu(cell);
    expect(screen.getByRole('menu')).toBeTruthy();
    expect(screen.getByText(/Open their tasks/i)).toBeTruthy();
  });

  it('explains that presence starts now when there is none', async () => {
    fetchTeamMetrics.mockResolvedValue({ ...PAYLOAD, modules: [], jobs: [], people: [], attendance: [] });
    mount();
    expect(await screen.findByText(/No presence recorded yet/i)).toBeTruthy();
  });

  it('renders the attendance table with an online dot and a still-on pill', async () => {
    fetchTeamMetrics.mockResolvedValue(PAYLOAD);
    mount();
    await screen.findByText('Attendance');
    // Sam is online: a dot beside the name in People, a "still on" pill in Attendance.
    const dots = screen.getAllByRole('img', { name: 'Online now' });
    expect(dots.length).toBe(1);
    expect(dots[0]?.getAttribute('title')).toMatch(/last seen 1m ago/);
    expect(screen.getByText('1 online')).toBeTruthy();
    expect(screen.getByText('still on')).toBeTruthy();
    // Lee signed out: a time in "Logged out", never a pill; two logins.
    const rows = screen.getAllByRole('row');
    const leeToday = rows.find((r) => {
      const cells = Array.from(r.querySelectorAll('td')).map((c) => c.textContent?.trim());
      // The name cell is prefixed by the avatar initials ("LO").
      return !!cells[0]?.endsWith('Lee Okafor') && cells[4] === '1:00 h';
    });
    expect(leeToday).toBeTruthy();
    const leeCells = Array.from(leeToday!.querySelectorAll('td')).map((c) => c.textContent?.trim());
    expect(leeCells[5]).toBe('2');
    expect(leeCells[6]).not.toContain('still on');
    expect(leeCells[6]).toMatch(/\d/);
    // Active reads as a duration with its unit, and a day with no
    // recorded time is an em-dash, not a 0:00 that looks like a reading.
    expect(screen.getByText('6:45 h')).toBeTruthy();
    expect(screen.queryByText('0:00 h')).toBeNull();
  });

  it('is honest when the backend predates attendance (no attendance key)', async () => {
    const { attendance: _drop, ...older } = PAYLOAD;
    fetchTeamMetrics.mockResolvedValue({ ...older, people: older.people.map(({ today: _t, ...p }) => p) });
    mount();
    expect(await screen.findByText(/No attendance recorded in this window/i)).toBeTruthy();
    expect(screen.getByText(/running backend predates this/i)).toBeTruthy();
    expect(screen.queryAllByRole('img', { name: 'Online now' })).toHaveLength(0);
  });

  it('shows a calm managers-only panel to a viewer and never calls the API', async () => {
    useAuthStore.setState({ userRole: 'viewer' });
    fetchTeamMetrics.mockResolvedValue(PAYLOAD);
    mount();
    expect(await screen.findByText(/This page is for managers/i)).toBeTruthy();
    expect(fetchTeamMetrics).not.toHaveBeenCalled();
    // No dashboard, no error, no attendance leaked into the markup.
    expect(screen.queryByText('Attendance')).toBeNull();
    expect(screen.queryByText('Sam Rivera')).toBeNull();
    expect(screen.getByRole('button', { name: /Open Team Standup/i })).toBeTruthy();
  });

  it('shows the same panel when the server says 403 (a stale role)', async () => {
    // The stored role still says manager; the server has demoted them.
    fetchTeamMetrics.mockRejectedValue(new ApiError(403, 'Forbidden', undefined));
    mount();
    expect(await screen.findByText(/This page is for managers/i)).toBeTruthy();
    expect(screen.queryByText(/did not load/i)).toBeNull();
  });

  it('right-click on an attendance row offers "Copy times" and copies a line', async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    fetchTeamMetrics.mockResolvedValue(PAYLOAD);
    mount();
    const pill = await screen.findByText('still on');
    fireEvent.contextMenu(pill.closest('tr') as HTMLElement);
    expect(screen.getByRole('menu')).toBeTruthy();
    fireEvent.click(screen.getByText(/Copy times/i));
    await waitFor(() => expect(writeText).toHaveBeenCalledTimes(1));
    const line = writeText.mock.calls[0]?.[0] as string;
    expect(line).toContain('Sam Rivera');
    expect(line).toContain('active 6:45 h');
    expect(line).toContain('still on');
    expect(await screen.findByText('Times copied')).toBeTruthy();
  });
});
