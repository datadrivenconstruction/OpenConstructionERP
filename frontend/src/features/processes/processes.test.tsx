// @ts-nocheck
/**
 * Background services: header health dot, panel actions, read-only view for
 * non-admins, first-run wizard and the module banner. The API is stubbed so
 * the suite runs offline.
 */

import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, fireEvent, waitFor, within } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { MemoryRouter } from 'react-router-dom';

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, apiGet: vi.fn(), apiPost: vi.fn() };
});

let role = 'admin';
vi.mock('@/stores/useAuthStore', () => ({
  useAuthStore: (sel) => sel({ userRole: role }),
}));

import { ApiError, apiGet, apiPost } from '@/shared/lib/api';
import { overallHealth, processesForModules } from './api';
import { ProcessesButton } from './ProcessesButton';
import { ProcessesPanel } from './ProcessesPanel';
import { ProcessesWizard } from './ProcessesWizard';
import { ModuleProcessesNotice } from './ModuleProcessesNotice';
import { useProcessesUi } from './useProcessesUi';

function proc(over) {
  return {
    id: 'vector_db',
    name_key: '',
    purpose_key: '',
    off_impact_key: '',
    category: 'vector_index',
    modules: ['costs'],
    start_mode: 'lazy',
    default_enabled: false,
    ram_mb_estimate: 400,
    ram_mb_actual: null,
    status: 'disabled',
    enabled: false,
    required: false,
    stoppable: true,
    env_locked: false,
    last_error: null,
    restart_count: 0,
    next_retry_at: null,
    started_at: null,
    log_tail: [],
    ...over,
  };
}

function snapshot(processes, extra = {}) {
  return { processes, total_ram_mb_estimate: 600, process_rss_mb: null, first_run_done: true, ...extra };
}

function renderWith(ui) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  role = 'admin';
  vi.mocked(apiGet).mockReset();
  vi.mocked(apiPost).mockReset();
  useProcessesUi.setState({ panelOpen: false, wizardOpen: false, focusId: null });
});

describe('overallHealth', () => {
  it('ranks error over busy over ok, and nothing running is idle', () => {
    expect(overallHealth([proc({ status: 'running' }), proc({ status: 'error' })])).toBe('error');
    expect(overallHealth([proc({ status: 'running' }), proc({ status: 'starting' })])).toBe('busy');
    expect(overallHealth([proc({ status: 'idle' }), proc({ status: 'disabled' })])).toBe('ok');
    expect(overallHealth([proc({ status: 'disabled' })])).toBe('idle');
  });

  it('includes required services whatever modules are picked', () => {
    const req = proc({ id: 'core', required: true, modules: [] });
    const bim = proc({ id: 'bim', modules: ['bim'] });
    expect(processesForModules([req, bim], []).map((p) => p.id)).toEqual(['core']);
    expect(processesForModules([req, bim], ['bim']).map((p) => p.id)).toEqual(['core', 'bim']);
  });
});

describe('ProcessesButton', () => {
  it('shows the running count and a red dot when a service errored', async () => {
    vi.mocked(apiGet).mockResolvedValue(
      snapshot([proc({ id: 'a', status: 'running', enabled: true }), proc({ id: 'b', status: 'error', enabled: true })]),
    );
    renderWith(<ProcessesButton />);
    const btn = await screen.findByTestId('header-processes');
    await waitFor(() => expect(btn).toHaveAttribute('data-health', 'error'));
    expect(btn).toHaveTextContent('1');
    fireEvent.click(btn);
    expect(useProcessesUi.getState().panelOpen).toBe(true);
  });

  it('stays out of the header on a server without the processes API', async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(404, 'Not Found', null));
    const { container } = renderWith(<ProcessesButton />);
    await waitFor(() => expect(vi.mocked(apiGet)).toHaveBeenCalled());
    await waitFor(() => expect(container.querySelector('[data-testid="header-processes"]')).toBeNull());
  });
});

describe('ProcessesPanel', () => {
  it('groups rows, toggles and restarts through the API', async () => {
    vi.mocked(apiGet).mockResolvedValue(
      snapshot([
        proc(),
        proc({ id: 'llm', category: 'ai_model', status: 'running', enabled: true }),
      ]),
    );
    // The first call hangs so the optimistic "starting" state stays visible.
    vi.mocked(apiPost).mockReturnValueOnce(new Promise(() => {})).mockResolvedValue({});
    useProcessesUi.setState({ panelOpen: true });
    renderWith(<ProcessesPanel />);

    const row = await screen.findByTestId('process-row-vector_db');
    expect(screen.getByText('AI models')).toBeInTheDocument();
    expect(screen.getByText('Search indexes')).toBeInTheDocument();

    fireEvent.click(within(row).getByTestId('process-toggle'));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/vector_db/enable'));
    await waitFor(() => expect(within(row).getByTestId('process-status')).toHaveAttribute('data-status', 'starting'));

    const llm = screen.getByTestId('process-row-llm');
    fireEvent.click(within(llm).getByTestId('process-restart'));
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/llm/restart'));
  });

  it('shows the last error and log lines in the details', async () => {
    vi.mocked(apiGet).mockResolvedValue(
      snapshot([proc({ status: 'error', enabled: true, last_error: { message: 'model file missing', at: null }, log_tail: ['loading weights'] })]),
    );
    useProcessesUi.setState({ panelOpen: true });
    renderWith(<ProcessesPanel />);
    fireEvent.click(await screen.findByTestId('process-expand'));
    expect(screen.getByText('model file missing')).toBeInTheDocument();
    expect(screen.getByText('loading weights')).toBeInTheDocument();
  });

  it('locks the switch of a service the server config decides', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ status: 'running', enabled: true, env_locked: true })]));
    useProcessesUi.setState({ panelOpen: true });
    renderWith(<ProcessesPanel />);
    expect(await screen.findByTestId('process-toggle')).toBeDisabled();
    expect(screen.queryByTestId('process-restart')).toBeNull();
  });

  it('is read-only for a non-admin', async () => {
    role = 'editor';
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ status: 'running', enabled: true })]));
    useProcessesUi.setState({ panelOpen: true });
    renderWith(<ProcessesPanel />);
    expect(await screen.findByTestId('process-toggle')).toBeDisabled();
    expect(screen.queryByTestId('process-restart')).toBeNull();
    expect(screen.getByTestId('processes-readonly')).toBeInTheDocument();
    expect(screen.queryByTestId('processes-minimal')).toBeNull();
  });

  it('closes on Escape', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()]));
    useProcessesUi.setState({ panelOpen: true });
    renderWith(<ProcessesPanel />);
    await screen.findByTestId('processes-panel');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(useProcessesUi.getState().panelOpen).toBe(false);
  });
});

describe('ProcessesWizard', () => {
  it('opens on first run, sums memory for the picked modules and starts them', async () => {
    vi.mocked(apiGet).mockResolvedValue(
      snapshot(
        [proc(), proc({ id: 'bim_conv', modules: ['bim'], ram_mb_estimate: 300 })],
        { first_run_done: false },
      ),
    );
    vi.mocked(apiPost).mockResolvedValue(snapshot([]));
    renderWith(<ProcessesWizard />);
    await screen.findByTestId('processes-wizard');
    fireEvent.click(screen.getByTestId('wizard-module-costs').querySelector('input'));
    await waitFor(() => expect(screen.getByTestId('wizard-total')).toHaveTextContent('400 MB'));
    fireEvent.click(screen.getByTestId('wizard-start'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/processes/first-run', { module_ids: ['costs'], start_now: true }),
    );
  });

  it('is not offered to a non-admin', async () => {
    role = 'viewer';
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()], { first_run_done: false }));
    renderWith(<ProcessesWizard />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(screen.queryByTestId('processes-wizard')).toBeNull();
  });
});

describe('ModuleProcessesNotice', () => {
  it('renders nothing when the services of the module run', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ status: 'running', enabled: true })]));
    const { container } = renderWith(<ModuleProcessesNotice moduleId="costs" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(container.querySelector('[data-testid^="module-processes-notice"]')).toBeNull();
  });

  it('turns an off service on in one click', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()]));
    vi.mocked(apiPost).mockResolvedValue({});
    renderWith(<ModuleProcessesNotice moduleId="costs" />);
    const btn = await screen.findByTestId('module-processes-turn-on');
    expect(btn).toHaveTextContent('400 MB');
    fireEvent.click(btn);
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/vector_db/enable'));
  });

  it('stays hidden when the API is admin-only for this user', async () => {
    vi.mocked(apiGet).mockRejectedValue(new ApiError(403, 'Forbidden', null));
    const { container } = renderWith(<ModuleProcessesNotice moduleId="costs" />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(container.querySelector('[data-testid^="module-processes-notice"]')).toBeNull();
  });

  it('tells a non-admin to ask an administrator', async () => {
    role = 'editor';
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()]));
    renderWith(<ModuleProcessesNotice moduleId="costs" />);
    await screen.findByTestId('module-processes-notice-costs');
    expect(screen.queryByTestId('module-processes-turn-on')).toBeNull();
  });
});
