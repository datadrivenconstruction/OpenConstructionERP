// @ts-nocheck
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./interopApi', async () => {
  const actual = await vi.importActual<typeof import('./interopApi')>('./interopApi');
  return {
    ...actual,
    interopApi: {
      ...actual.interopApi,
      listProfiles: vi.fn(),
      getScheduleProfile: vi.fn(),
      createProfile: vi.fn(),
      updateProfile: vi.fn(),
      deleteProfile: vi.fn(),
      assignScheduleProfile: vi.fn(),
      previewRecalculation: vi.fn(),
      applyRecalculation: vi.fn(),
    },
  };
});

import { DEFAULT_PROFILE_SETTINGS, interopApi } from './interopApi';
import { SchedulingProfilesPanel } from './SchedulingProfilesPanel';

const PROFILE = {
  id: 'p1',
  project_id: 'proj',
  name: 'Working-day lags',
  description: '',
  is_default: true,
  ...DEFAULT_PROFILE_SETTINGS,
  lag_calendar: 'project',
};

const RESULT = {
  schedule_id: 's1',
  applied: false,
  profile_id: 'p1',
  profile_name: 'Working-day lags',
  source: 'project_default',
  settings: PROFILE,
  data_date: null,
  current_finish: '2026-05-12',
  new_finish: '2026-05-20',
  changed_count: 1,
  critical_count: 2,
  out_of_sequence_count: 0,
  open_end_count: 1,
  setting_effects: { lag_calendar: 1 },
  activities: [
    {
      activity_id: 'a1',
      activity_code: 'A1',
      name: 'Pour',
      current_start: '2026-05-04',
      current_end: '2026-05-08',
      new_start: '2026-05-04',
      new_end: '2026-05-08',
      start_shift_days: 0,
      finish_shift_days: 0,
      total_float: 0,
      was_critical: true,
      is_critical: true,
      completed: false,
      started: false,
      out_of_sequence: false,
      on_longest_path: true,
      open_start: true,
      open_finish: false,
      changed_by: [],
    },
    {
      activity_id: 'a2',
      activity_code: 'A2',
      name: 'Strip formwork',
      current_start: '2026-05-11',
      current_end: '2026-05-12',
      new_start: '2026-05-19',
      new_end: '2026-05-20',
      start_shift_days: 8,
      finish_shift_days: 8,
      total_float: 0,
      was_critical: true,
      is_critical: true,
      completed: false,
      started: false,
      out_of_sequence: false,
      on_longest_path: true,
      open_start: false,
      open_finish: true,
      changed_by: ['lag_calendar'],
    },
  ],
};

function renderPanel(canEdit = true) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SchedulingProfilesPanel scheduleId="s1" projectId="proj" canEdit={canEdit} />
    </QueryClientProvider>,
  );
}

describe('SchedulingProfilesPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    interopApi.listProfiles.mockResolvedValue([PROFILE]);
    interopApi.getScheduleProfile.mockResolvedValue({
      schedule_id: 's1',
      profile_id: 'p1',
      profile_name: 'Working-day lags',
      source: 'project_default',
      settings: PROFILE,
    });
  });

  it('lists the project profiles', async () => {
    renderPanel();
    expect(await screen.findAllByText('Working-day lags')).not.toHaveLength(0);
  });

  it('previews a recalculation and shows which setting moved an activity', async () => {
    interopApi.previewRecalculation.mockResolvedValue(RESULT);
    renderPanel();
    fireEvent.click(screen.getByTestId('profile-preview'));
    await screen.findByTestId('recalc-result');
    expect(screen.getByText('Strip formwork')).toBeInTheDocument();
    expect(screen.queryByText('Pour')).not.toBeInTheDocument();
    expect(screen.getAllByText(/Lag calendar/).length).toBeGreaterThan(0);
    expect(screen.getByText('+8')).toBeInTheDocument();
  });

  it('creates a profile from the editor', async () => {
    interopApi.createProfile.mockResolvedValue({ ...PROFILE, id: 'p2', name: 'Override' });
    renderPanel();
    await screen.findAllByText('Working-day lags');
    fireEvent.click(screen.getByText(/Add profile/));
    fireEvent.change(screen.getByTestId('profile-name'), { target: { value: 'Override' } });
    fireEvent.change(screen.getByTestId('profile-progress_mode'), { target: { value: 'progress_override' } });
    fireEvent.click(screen.getByTestId('profile-save'));
    await waitFor(() =>
      expect(interopApi.createProfile).toHaveBeenCalledWith(
        'proj',
        expect.objectContaining({ name: 'Override', progress_mode: 'progress_override' }),
      ),
    );
  });

  it('assigns a profile to the schedule', async () => {
    interopApi.assignScheduleProfile.mockResolvedValue({});
    renderPanel();
    await screen.findAllByText('Working-day lags');
    fireEvent.change(screen.getByTestId('profile-assign'), { target: { value: 'p1' } });
    await waitFor(() => expect(interopApi.assignScheduleProfile).toHaveBeenCalledWith('s1', 'p1'));
  });

  it('hides editing for a viewer', async () => {
    renderPanel(false);
    await screen.findAllByText('Working-day lags');
    expect(screen.queryByText(/Add profile/)).not.toBeInTheDocument();
    expect(screen.getByTestId('profile-assign')).toBeDisabled();
  });
});
