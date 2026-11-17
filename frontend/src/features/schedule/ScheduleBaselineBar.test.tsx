// @ts-nocheck
/**
 * Baselines in the Gantt toolbar: the approved one is preselected, saving
 * captures on the server, a saved version can be approved, and the PDF
 * export sends the chosen baseline and paper.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('./api', async () => {
  const actual = await vi.importActual<typeof import('./api')>('./api');
  return {
    ...actual,
    scheduleApi: {
      ...actual.scheduleApi,
      listBaselines: vi.fn(),
      captureBaseline: vi.fn(),
      approveBaseline: vi.fn(),
      downloadGanttPdf: vi.fn(),
    },
  };
});

import { scheduleApi } from './api';
import { ScheduleBaselineBar } from './ScheduleBaselineBar';

const row = (over) => ({
  id: 'b0',
  schedule_id: 's1',
  project_id: 'p1',
  name: 'B0',
  baseline_date: '2026-01-05',
  snapshot_data: { activities: [] },
  is_active: false,
  created_by: null,
  created_at: '2026-01-05T00:00:00Z',
  updated_at: '2026-01-05T00:00:00Z',
  ...over,
});

const B0 = row({ id: 'b0', name: 'B0', is_active: true, metadata_: { approval: { approved_at: '2026-01-05T09:00:00' } } });
const B1 = row({ id: 'b1', name: 'B1', created_at: '2026-02-01T00:00:00Z' });
const OTHER = row({ id: 'x', schedule_id: 's2', name: 'Other schedule B0' });

function renderBar(props = {}) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const onBaselineChange = vi.fn();
  const onUserSelect = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ScheduleBaselineBar
        scheduleId="s1"
        projectId="p1"
        canEdit
        onBaselineChange={onBaselineChange}
        onUserSelect={onUserSelect}
        {...props}
      />
    </QueryClientProvider>,
  );
  return { onBaselineChange, onUserSelect };
}

beforeEach(() => {
  vi.mocked(scheduleApi.listBaselines).mockReset().mockResolvedValue([B1, OTHER, B0]);
  vi.mocked(scheduleApi.captureBaseline).mockReset();
  vi.mocked(scheduleApi.approveBaseline).mockReset();
  vi.mocked(scheduleApi.downloadGanttPdf).mockReset().mockResolvedValue(undefined);
});

describe('ScheduleBaselineBar', () => {
  it('preselects the approved baseline of this schedule only', async () => {
    const { onBaselineChange } = renderBar();
    const select = await screen.findByLabelText('Baseline to compare against');
    await waitFor(() => expect(select).toHaveValue('b0'));
    expect(onBaselineChange).toHaveBeenLastCalledWith(B0);
    expect(screen.queryByText(/Other schedule/)).toBeNull();
    // B0 is approved: nothing to approve.
    expect(screen.queryByRole('button', { name: /Approve$/ })).toBeNull();
  });

  it('approves a saved version on request', async () => {
    vi.mocked(scheduleApi.approveBaseline).mockResolvedValue({ ...B1, is_active: true });
    const { onUserSelect } = renderBar();
    const select = await screen.findByLabelText('Baseline to compare against');
    await waitFor(() => expect(select).toHaveValue('b0'));
    fireEvent.change(select, { target: { value: 'b1' } });
    expect(onUserSelect).toHaveBeenCalled();
    fireEvent.click(await screen.findByRole('button', { name: /Approve$/ }));
    await waitFor(() => expect(scheduleApi.approveBaseline).toHaveBeenCalledWith('s1', 'b1'));
  });

  it('saves the live plan as an approved baseline with its reason', async () => {
    vi.mocked(scheduleApi.captureBaseline).mockResolvedValue(row({ id: 'b2', name: 'B2' }));
    renderBar();
    fireEvent.click(await screen.findByRole('button', { name: /Save baseline/ }));
    fireEvent.change(screen.getByLabelText('Reason, e.g. approved variation (optional)'), {
      target: { value: 'Variation 12' },
    });
    fireEvent.click(screen.getByRole('button', { name: 'Save' }));
    await waitFor(() =>
      expect(scheduleApi.captureBaseline).toHaveBeenCalledWith('s1', {
        name: undefined,
        note: 'Variation 12',
        approve: true,
      }),
    );
  });

  it('hides editing for a reader without schedule.update', async () => {
    renderBar({ canEdit: false });
    await screen.findByLabelText('Baseline to compare against');
    expect(screen.queryByRole('button', { name: /Save baseline/ })).toBeNull();
  });

  it('exports the PDF with the chosen baseline and paper', async () => {
    renderBar();
    const select = await screen.findByLabelText('Baseline to compare against');
    await waitFor(() => expect(select).toHaveValue('b0'));
    fireEvent.change(screen.getByLabelText('Paper size'), { target: { value: 'A4' } });
    fireEvent.click(screen.getByRole('button', { name: /Export PDF/ }));
    await waitFor(() =>
      expect(scheduleApi.downloadGanttPdf).toHaveBeenCalledWith('s1', { baselineId: 'b0', paper: 'A4' }),
    );
    fireEvent.change(select, { target: { value: '__none__' } });
    fireEvent.click(screen.getByRole('button', { name: /Export PDF/ }));
    await waitFor(() =>
      expect(scheduleApi.downloadGanttPdf).toHaveBeenLastCalledWith('s1', { baselineId: null, paper: 'A4' }),
    );
  });
});
