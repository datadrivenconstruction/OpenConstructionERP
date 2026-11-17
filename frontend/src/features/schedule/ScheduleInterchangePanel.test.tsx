// @ts-nocheck
/**
 * Smoke tests for the schedule interchange panel (T1.1).
 *
 * ``./api`` exports the ``scheduleApi`` object; we stub ``exportSchedule``,
 * ``cleanPreviewSchedule`` and ``importSchedule`` on it while keeping the real
 * types. Each section drives a mutation on demand, so the panel mounts with no
 * network calls and we trigger them via the buttons.
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
      ...actual.scheduleApi,
      exportSchedule: vi.fn(),
      cleanPreviewSchedule: vi.fn(),
      importSchedule: vi.fn(),
      exportMspXml: vi.fn(),
      exportCsv: vi.fn(),
      importMspXml: vi.fn(),
      previewMspXml: vi.fn(),
      importXer: vi.fn(),
    },
  };
});

import { scheduleApi } from './api';
import { ScheduleInterchangePanel } from './ScheduleInterchangePanel';

const PREVIEW = {
  schedule_id: 's1',
  actions: [
    {
      code: 'drop_dangling_relationship',
      target: 'rel:a1->a9',
      detail: 'Dropped a link to an activity that does not exist.',
    },
  ],
  stats: {
    activities: 12,
    relationships: 11,
    lead_count: 2,
    hard_constraint_count: 1,
    activities_missing_predecessor: 3,
    activities_missing_successor: 0,
    relationships_dropped_dangling: 1,
  },
};

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScheduleInterchangePanel scheduleId="s1" projectId="p1" />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ScheduleInterchangePanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('mounts and renders the export button', () => {
    renderPanel();
    expect(screen.getByRole('button', { name: /^export$/i })).toBeInTheDocument();
  });

  it('renders all three section headings', () => {
    renderPanel();
    expect(screen.getByText(/Export schedule/i)).toBeInTheDocument();
    expect(screen.getByText(/Schedule health check/i)).toBeInTheDocument();
    expect(screen.getByText(/Import schedule/i)).toBeInTheDocument();
  });

  it('runs the health check and renders a returned action and stat', async () => {
    (scheduleApi.cleanPreviewSchedule as any).mockResolvedValue(PREVIEW);
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: /check health/i }));

    await waitFor(() =>
      expect(scheduleApi.cleanPreviewSchedule).toHaveBeenCalledWith('s1'),
    );

    // A returned action's detail renders…
    expect(
      await screen.findByText(/Dropped a link to an activity that does not exist\./i),
    ).toBeInTheDocument();
    // …its code badge renders…
    expect(screen.getByText('drop_dangling_relationship')).toBeInTheDocument();
    // …and a highlighted stat tile renders its label.
    expect(screen.getByText(/Missing predecessor/i)).toBeInTheDocument();
  });

  it('export button triggers the export api', async () => {
    (scheduleApi.exportSchedule as any).mockResolvedValue({
      schedule_id: 's1',
      document: { format: 'oce-schedule', activities: [], relationships: [] },
    });
    renderPanel();

    fireEvent.click(screen.getByRole('button', { name: /^export$/i }));
    await waitFor(() => expect(scheduleApi.exportSchedule).toHaveBeenCalledWith('s1'));
  });

  it('MS Project XML export button calls exportMspXml (#205)', async () => {
    (scheduleApi.exportMspXml as any).mockResolvedValue(undefined);
    renderPanel();

    fireEvent.click(screen.getByTestId('schedule-export-msp-xml'));
    await waitFor(() =>
      expect(scheduleApi.exportMspXml).toHaveBeenCalledWith(
        's1',
        expect.stringMatching(/\.xml$/),
      ),
    );
  });

  it('an .xml file is checked first and imported only after a clean check', async () => {
    (scheduleApi.previewMspXml as any).mockResolvedValue({
      filename: 'plan.xml', name: 'Plan', minutes_per_day: 480, task_count: 1, summary_count: 0,
      milestone_count: 0, link_count: 0, calendar_count: 0, baseline_task_count: 0,
      start: '2026-05-04', finish: '2026-05-08', error_count: 0, warning_count: 0, can_apply: true,
      issues: [], calendars: [],
      tasks: [{ uid: '1', name: 'Walls', wbs: '1', outline_level: 1, parent_uid: null, start: '2026-05-04',
        finish: '2026-05-08', duration_days: 5, percent_complete: 0, activity_type: 'task',
        baseline_start: null, baseline_finish: null, predecessor_count: 0 }],
    });
    (scheduleApi.importMspXml as any).mockResolvedValue({
      activities_imported: 3,
      relationships_imported: 2,
      calendars_imported: 0,
      warnings: [],
    });
    renderPanel();

    const input = screen.getByTestId('schedule-vendor-file-input');
    const file = new File(['<Project/>'], 'plan.xml', { type: 'application/xml' });
    fireEvent.change(input, { target: { files: [file] } });
    expect(screen.getByTestId('schedule-vendor-import')).toBeDisabled();
    fireEvent.click(screen.getByTestId('schedule-vendor-preview'));
    expect(await screen.findByText('1 Walls')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByTestId('schedule-vendor-import')).not.toBeDisabled());
    fireEvent.click(screen.getByTestId('schedule-vendor-import'));

    await waitFor(() =>
      expect(scheduleApi.importMspXml).toHaveBeenCalledWith('s1', file),
    );
    expect(scheduleApi.importXer).not.toHaveBeenCalled();
  });

  it('an .xml file with errors cannot be imported', async () => {
    (scheduleApi.previewMspXml as any).mockResolvedValue({
      filename: 'plan.xml', name: '', minutes_per_day: 480, task_count: 1, summary_count: 0,
      milestone_count: 0, link_count: 0, calendar_count: 0, baseline_task_count: 0, start: null,
      finish: null, error_count: 1, warning_count: 0, can_apply: false, calendars: [], tasks: [],
      issues: [{ rule_id: 'schedule_mspdi_import.task_dates', code: 'missing_dates', severity: 'error',
        ref: '1', message: 'Task 1 "Walls" has no start or finish date.' }],
    });
    renderPanel();
    const file = new File(['<Project/>'], 'plan.xml', { type: 'application/xml' });
    fireEvent.change(screen.getByTestId('schedule-vendor-file-input'), { target: { files: [file] } });
    fireEvent.click(screen.getByTestId('schedule-vendor-preview'));
    expect(await screen.findByText(/has no start or finish date/)).toBeInTheDocument();
    expect(screen.getByTestId('schedule-vendor-import')).toBeDisabled();
    expect(scheduleApi.importMspXml).not.toHaveBeenCalled();
  });

  it('importing a .xer file routes to importXer (#205)', async () => {
    (scheduleApi.importXer as any).mockResolvedValue({
      activities_imported: 5,
      relationships_imported: 4,
      calendars_imported: 1,
      warnings: ['Calendar 2 was approximated.'],
    });
    renderPanel();

    const input = screen.getByTestId('schedule-vendor-file-input');
    const file = new File(['ERMHDR'], 'plan.xer', { type: 'text/plain' });
    fireEvent.change(input, { target: { files: [file] } });
    fireEvent.click(screen.getByTestId('schedule-vendor-import'));

    await waitFor(() =>
      expect(scheduleApi.importXer).toHaveBeenCalledWith('s1', file),
    );
    // The warning surfaces in the result panel.
    expect(
      await screen.findByText(/Calendar 2 was approximated\./i),
    ).toBeInTheDocument();
  });
});
