// @ts-nocheck
/**
 * Smoke tests for the guided forensic delay analysis panel (T2.2).
 *
 * Network is stubbed via ``vi.mock`` on the schedule-advanced api module.
 * React Query retries are disabled so errors surface immediately. The panel
 * lists analyses (useQuery), creates one (useMutation), then shows the selected
 * analysis with its events and - after compute - the headline result + windows.
 */
import { describe, expect, it, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/features/schedule-advanced/api', () => ({
  listDelayAnalyses: vi.fn(),
  getDelayAnalysis: vi.fn(),
  createDelayAnalysis: vi.fn(),
  addDelayEvent: vi.fn(),
  autoDelayFragnet: vi.fn(),
  computeDelayAnalysis: vi.fn(),
  fetchDelayValidation: vi.fn(),
  issueDelayAnalysis: vi.fn(),
  raiseEotClaim: vi.fn(),
}));

import {
  listDelayAnalyses,
  getDelayAnalysis,
  createDelayAnalysis,
  computeDelayAnalysis,
  fetchDelayValidation,
} from '@/features/schedule-advanced/api';
import { ScheduleDelayPanel } from './ScheduleDelayPanel';

const LIST = [
  {
    id: 'd1',
    project_id: 'p1',
    schedule_id: 's1',
    method: 'windows',
    name: 'Window 3 - foundation delay',
    status: 'draft',
    total_entitlement_days: 0,
    window_count: 0,
    issued_at: null,
  },
];

const DRAFT_DETAIL = {
  id: 'd1',
  project_id: 'p1',
  schedule_id: 's1',
  method: 'windows',
  name: 'Window 3 - foundation delay',
  description: '',
  oos_mode: 'retained_logic',
  data_date: null,
  apportionment_method: 'malmaison',
  status: 'draft',
  window_count: 0,
  total_entitlement_days: 0,
  concurrent_days: 0,
  result_json: {},
  issued_at: null,
  issued_by: null,
  signature_sha256: null,
  eot_claim_id: null,
  events: [
    {
      id: 'e1',
      analysis_id: 'd1',
      code: '',
      title: 'Late design release for foundations',
      description: '',
      root_cause: '',
      responsibility: 'employer',
      risk_event_category: 'design',
      is_concurrent: false,
      concurrency_group: '',
      is_pacing: false,
      insert_at_activity_ref: 'a1',
      event_start: null,
      event_end: null,
      start_workday: 10,
      end_workday: 25,
      fragnets: [],
    },
  ],
  windows: [],
};

const COMPUTED_DETAIL = {
  ...DRAFT_DETAIL,
  status: 'computed',
  window_count: 1,
  total_entitlement_days: 12,
  concurrent_days: 3,
  windows: [
    {
      id: 'w1',
      sequence_order: 0,
      window_start: null,
      window_end: null,
      finish_at_open: 100,
      finish_at_close: 115,
      gross_slip_days: 15,
      employer_days: 12,
      contractor_days: 0,
      neutral_days: 0,
      concurrent_days: 3,
      net_entitlement_days: 12,
      narrative: 'Employer-caused design delay drives the window.',
    },
  ],
};

const NAMES = { a1: 'Foundation', a2: 'Structure' };

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <ScheduleDelayPanel scheduleId="s1" projectId="p1" activitiesById={NAMES} />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe('ScheduleDelayPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    (fetchDelayValidation as any).mockResolvedValue({ results: [], failed: 0 });
  });

  it('renders the analyses list and the create form', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    renderPanel();

    // List row renders.
    const list = await screen.findByTestId('delay-analysis-list');
    expect(list.textContent).toMatch(/Window 3/);

    // Create form is present (name input + create button).
    expect(screen.getByText(/New analysis/i)).toBeInTheDocument();
    expect(screen.getByPlaceholderText(/foundation delay/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /create analysis/i })).toBeInTheDocument();
  });

  it('creates a new analysis via the mutation and selects it', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    (createDelayAnalysis as any).mockResolvedValue(DRAFT_DETAIL);
    (getDelayAnalysis as any).mockResolvedValue(DRAFT_DETAIL);
    renderPanel();

    await screen.findByTestId('delay-analysis-list');

    fireEvent.change(screen.getByPlaceholderText(/foundation delay/i), {
      target: { value: 'New forensic analysis' },
    });
    fireEvent.click(screen.getByRole('button', { name: /create analysis/i }));

    await waitFor(() => {
      expect(createDelayAnalysis).toHaveBeenCalledTimes(1);
    });
    // After create the panel auto-selects the new analysis and loads its detail.
    expect(await screen.findByTestId('delay-events')).toBeInTheDocument();
    expect(createDelayAnalysis).toHaveBeenCalledWith(
      'p1',
      expect.objectContaining({ name: 'New forensic analysis', schedule_id: 's1' }),
    );
  });

  it('shows the headline result and per-window attribution after compute', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    // First detail load = draft; after compute the query refetches the computed one.
    (getDelayAnalysis as any)
      .mockResolvedValueOnce(DRAFT_DETAIL)
      .mockResolvedValue(COMPUTED_DETAIL);
    (computeDelayAnalysis as any).mockResolvedValue(COMPUTED_DETAIL);
    renderPanel();

    // Select the analysis from the list.
    fireEvent.click(await screen.findByText(/Window 3/));

    // Draft loaded - the events table is visible.
    await screen.findByTestId('delay-events');
    expect(screen.getByText(/Late design release/i)).toBeInTheDocument();

    // Run the analysis.
    fireEvent.click(screen.getByRole('button', { name: /run analysis/i }));

    await waitFor(() => {
      expect(computeDelayAnalysis).toHaveBeenCalledTimes(1);
    });

    // Headline result + window attribution render.
    const result = await screen.findByTestId('delay-result');
    expect(result.textContent).toMatch(/12/); // total entitlement days
    const windows = await screen.findByTestId('delay-windows');
    expect(windows.textContent).toMatch(/Employer-caused design delay/);
  });

  it('surfaces a recovery card when the list call fails', async () => {
    (listDelayAnalyses as any).mockRejectedValue(new Error('boom'));
    renderPanel();
    await waitFor(() => {
      expect(screen.getByRole('button', { name: /retry|try again/i })).toBeInTheDocument();
    });
  });

  it('cuts windows by snapshot by default and sends the chosen cut on compute', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    (getDelayAnalysis as any).mockResolvedValue(DRAFT_DETAIL);
    (computeDelayAnalysis as any).mockResolvedValue(COMPUTED_DETAIL);
    renderPanel();
    fireEvent.click(await screen.findByText(/Window 3/));
    const cut = (await screen.findByTestId('delay-window-mode')) as HTMLSelectElement;
    expect(cut.value).toBe('snapshot');
    fireEvent.change(cut, { target: { value: 'month' } });
    fireEvent.click(screen.getByRole('button', { name: /run analysis/i }));
    await waitFor(() => {
      expect(computeDelayAnalysis).toHaveBeenCalledWith('d1', undefined, 'month');
    });
  });

  it('says in plain words when delay was concurrent and flags a window without a snapshot', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    (getDelayAnalysis as any).mockResolvedValue({
      ...COMPUTED_DETAIL,
      result_json: { concurrency: { present: true, days: 3 }, windows: [{ no_snapshot: true }] },
    });
    renderPanel();
    fireEvent.click(await screen.findByText(/Window 3/));
    const note = await screen.findByTestId('delay-concurrent-note');
    expect(note.textContent).toMatch(/same time/i);
    expect(note.textContent).toMatch(/3/);
    expect((await screen.findByTestId('delay-windows')).textContent).toMatch(/No schedule snapshot/);
    expect(screen.getByText(/not an expert opinion/i)).toBeInTheDocument();
  });

  it('lists the failed checks above the result', async () => {
    (listDelayAnalyses as any).mockResolvedValue(LIST);
    (getDelayAnalysis as any).mockResolvedValue(COMPUTED_DETAIL);
    (fetchDelayValidation as any).mockResolvedValue({
      failed: 1,
      results: [
        {
          rule_id: 'delay_analysis.fragnet_cycle',
          passed: false,
          severity: 'error',
          message: 'The fragnet of event D-1 creates a logic loop, so the schedule cannot be calculated',
          element_ref: 'e1',
          details: { message_key: 'schedule.delay.rules.fragnet_cycle', event: 'D-1' },
        },
        { rule_id: 'delay_analysis.no_baseline', passed: true, severity: 'warning', message: 'OK', element_ref: 'd1', details: {} },
      ],
    });
    renderPanel();
    fireEvent.click(await screen.findByText(/Window 3/));
    const box = await screen.findByTestId('delay-checks');
    expect(box.textContent).toMatch(/logic loop/);
    expect(box.querySelectorAll('li')).toHaveLength(1);
  });
});
