// @ts-nocheck
/**
 * The progress-rigor panel against the responses the backend really sends.
 *
 * The fixtures copy the field names of ProgressResultResponse,
 * PercentTypePreviewResponse, ActivityProgressStateResponse and
 * PlannedValueResponse in backend/app/modules/schedule/progress_schemas.py.
 * The panel used to read an ``activity`` wrapper none of them has, so it sat on
 * "Loading" forever and a type change or a suspend blanked it. It also sent
 * ``type`` where the server wants ``percent_complete_type`` and called a
 * preview route and a data-date route that did not exist.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', () => ({
  scheduleApi: {
    updateProgressTyped: vi.fn(),
    previewPercentType: vi.fn(),
    setPercentType: vi.fn(),
    suspendActivity: vi.fn(),
    resumeActivity: vi.fn(),
    listSteps: vi.fn(),
    createStep: vi.fn(),
    updateStep: vi.fn(),
    deleteStep: vi.fn(),
    getPlannedValue: vi.fn(),
    advanceDataDate: vi.fn(),
  },
}));

import { scheduleApi } from './api';
import { ProgressRigorPanel } from './ProgressRigorPanel';

// ProgressResultResponse: flat, units as Decimal strings.
const TYPED = {
  activity_id: 'a1',
  percent_complete_type: 'units',
  percent_complete: 25.0,
  remaining_duration: 6,
  forecast_finish: '2026-05-15',
  status: 'in_progress',
  evm_warnings: [],
  installed_units: '25',
  budgeted_units: '100',
  suspended_at: null,
  suspend_reason: null,
};

// ActivityProgressStateResponse: what suspend / resume answer with.
const SUSPENDED = {
  id: 'a1',
  schedule_id: 's1',
  status: 'suspended',
  progress_pct: 25.0,
  percent_complete_type: 'units',
  remaining_duration: 6,
  start_date: '2026-05-04',
  end_date: '2026-05-15',
  calendar_id: null,
  suspended_at: '2026-05-08',
  resumed_at: null,
  suspend_reason: 'Rain',
};

// PlannedValueResponse: money as strings.
const PV = {
  schedule_id: 's1',
  as_of: '2026-05-08',
  planned_value: '1000.00',
  earned_value: '500.00',
  budget_at_completion: '4000.00',
  activity_count: 1,
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProgressRigorPanel
        scheduleId="s1"
        activities={[{ id: 'a1', name: 'Pour slab' }]}
        currency="EUR"
        dataDate="2026-05-08"
      />
    </QueryClientProvider>,
  );
}

function typeButton(label: string) {
  return screen.getByRole('button', { name: new RegExp(label) });
}

describe('ProgressRigorPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    scheduleApi.updateProgressTyped.mockResolvedValue(TYPED);
    scheduleApi.listSteps.mockResolvedValue([]);
    scheduleApi.getPlannedValue.mockResolvedValue(PV);
  });

  it('leaves the loading state and prefills the stored units', async () => {
    renderPanel();

    const budgeted = await screen.findByLabelText('Budgeted');
    expect(budgeted.value).toBe('100');
    expect(screen.getByLabelText('Installed').value).toBe('25');
    expect(typeButton('Units').getAttribute('aria-pressed')).toBe('true');
    expect(screen.getByText(/Forecast finish/).textContent).toMatch(/2026-05-15/);
  });

  it('previews a type on hover without committing it', async () => {
    scheduleApi.previewPercentType.mockResolvedValue({
      activity_id: 'a1',
      percent_complete_type: 'physical',
      evm_warnings: ['physical_manual_pct_is_subjective'],
    });
    renderPanel();
    await screen.findByLabelText('Budgeted');

    fireEvent.mouseEnter(typeButton('Physical'));

    expect(await screen.findByText(/percent is subjective/)).toBeTruthy();
    expect(scheduleApi.previewPercentType).toHaveBeenCalledWith('a1', 'physical');
    expect(scheduleApi.setPercentType).not.toHaveBeenCalled();
    expect(typeButton('Units').getAttribute('aria-pressed')).toBe('true');
  });

  it('keeps the view when a type change answers with only the type and warnings', async () => {
    scheduleApi.setPercentType.mockResolvedValue({
      activity_id: 'a1',
      percent_complete_type: 'duration',
      evm_warnings: [],
    });
    renderPanel();
    await screen.findByLabelText('Budgeted');

    fireEvent.click(typeButton('Duration'));

    await waitFor(() => expect(typeButton('Duration').getAttribute('aria-pressed')).toBe('true'));
    expect(scheduleApi.setPercentType).toHaveBeenCalledWith('a1', 'duration');
    expect(screen.queryByText('Loading…')).toBeNull();
  });

  it('keeps the view and shows the suspension after a suspend', async () => {
    vi.spyOn(window, 'prompt').mockReturnValue('Rain');
    scheduleApi.suspendActivity.mockResolvedValue(SUSPENDED);
    renderPanel();
    await screen.findByLabelText('Budgeted');

    fireEvent.click(screen.getByRole('button', { name: /Suspend/ }));

    expect(await screen.findByText(/Suspended since 2026-05-08/)).toBeTruthy();
    expect(screen.getByText(/Rain/)).toBeTruthy();
    expect(screen.getByRole('button', { name: /Resume/ })).toBeTruthy();
    // The state answer has no units; the ones already shown stay.
    expect(screen.getByLabelText('Budgeted').value).toBe('100');
  });

  it('sends percent_complete_type and leaves a blank quantity out instead of zeroing it', async () => {
    renderPanel();
    const budgeted = await screen.findByLabelText('Budgeted');

    fireEvent.change(budgeted, { target: { value: '' } });
    fireEvent.change(screen.getByLabelText('Installed'), { target: { value: '30' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => expect(scheduleApi.updateProgressTyped).toHaveBeenCalledTimes(2));
    const body = scheduleApi.updateProgressTyped.mock.calls[1][1];
    expect(body).toEqual({ percent_complete_type: 'units', installed_units: 30 });
    expect('type' in body).toBe(false);
  });

  it('advances the data date through the schedule update', async () => {
    scheduleApi.advanceDataDate.mockResolvedValue({ id: 's1', data_date: '2026-05-08' });
    renderPanel();
    await screen.findByLabelText('Budgeted');

    fireEvent.click(screen.getByRole('button', { name: /Advance/ }));

    await waitFor(() => expect(scheduleApi.advanceDataDate).toHaveBeenCalledWith('s1', '2026-05-08'));
  });
});
