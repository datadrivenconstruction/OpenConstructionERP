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
import { overallHealth, processesForModules, resetEnsured } from './api';
import { ProcessesButton } from './ProcessesButton';
import { ProcessesPanel } from './ProcessesPanel';
import { ModuleProcessesNotice } from './ModuleProcessesNotice';
import { useProcessesUi } from './useProcessesUi';
import { useToastStore } from '@/stores/useToastStore';

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
  vi.mocked(apiPost).mockResolvedValue({});
  resetEnsured();
  useProcessesUi.setState({ panelOpen: false, wizardOpen: false, focusId: null, startWatch: [] });
  useToastStore.setState({ toasts: [], history: [] });
});

const toastTitles = () => useToastStore.getState().toasts.map((x) => x.title);

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
    expect(screen.queryByTestId('processes-profile-choose-minimal')).toBeNull();
  });

  describe('profiles', () => {
    const core = (over) => proc({ id: 'core', required: true, default_enabled: true, enabled: true, ram_mb_estimate: 100, ...over });
    const search = (over) => proc({ id: 'search', default_enabled: true, ram_mb_estimate: 400, ...over });
    const heavy = (over) => proc({ id: 'heavy', ram_mb_estimate: 3000, ...over });

    async function open(list) {
      vi.mocked(apiGet).mockResolvedValue(snapshot(list));
      useProcessesUi.setState({ panelOpen: true });
      renderWith(<ProcessesPanel />);
      await screen.findByTestId('processes-profiles');
    }

    it('marks the balanced profile and sums memory per profile', async () => {
      await open([core(), search({ enabled: true }), heavy()]);
      expect(screen.getByTestId('processes-profile-recommended')).toHaveAttribute('data-active', 'true');
      expect(screen.getByTestId('processes-profile-minimal')).toHaveAttribute('data-active', 'false');
      expect(screen.getByTestId('processes-profile-minimal')).toHaveTextContent('100 MB');
      expect(screen.getByTestId('processes-profile-recommended')).toHaveTextContent('500 MB');
      expect(screen.getByTestId('processes-profile-all')).toHaveTextContent('3.4 GB');
      expect(screen.queryByTestId('processes-profile-custom')).toBeNull();
    });

    it('shows Custom when the mix matches no profile', async () => {
      await open([core(), search({ enabled: false }), heavy({ enabled: true })]);
      expect(screen.getByTestId('processes-profile-custom')).toBeInTheDocument();
      for (const id of ['minimal', 'recommended', 'all']) {
        expect(screen.getByTestId(`processes-profile-${id}`)).toHaveAttribute('data-active', 'false');
      }
    });

    it('applies a profile and tells the user', async () => {
      await open([core(), search({ enabled: true }), heavy()]);
      fireEvent.click(screen.getByTestId('processes-profile-choose-minimal'));
      await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/preset', { preset: 'minimal' }));
      await waitFor(() => expect(toastTitles()).toContain('Profile applied'));
    });

    it('reports a failed apply', async () => {
      await open([core(), search({ enabled: true }), heavy()]);
      vi.mocked(apiPost).mockRejectedValueOnce(new Error('boom'));
      fireEvent.click(screen.getByTestId('processes-profile-choose-minimal'));
      await waitFor(() => expect(toastTitles()).toContain('Could not apply the profile'));
    });

    it('asks before turning on more than the server budget', async () => {
      await open([core(), search({ enabled: true }), heavy()]);
      fireEvent.click(screen.getByTestId('processes-profile-choose-all'));
      expect(apiPost).not.toHaveBeenCalled();
      expect(screen.getByRole('alert')).toHaveTextContent('3.4 GB');
      fireEvent.click(screen.getByTestId('processes-profile-cancel'));
      expect(apiPost).not.toHaveBeenCalled();
      fireEvent.click(screen.getByTestId('processes-profile-choose-all'));
      fireEvent.click(screen.getByTestId('processes-profile-confirm'));
      await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/preset', { preset: 'all' }));
    });

    it('applies all at once when it fits the budget', async () => {
      await open([core(), search({ enabled: true }), heavy({ ram_mb_estimate: 200 })]);
      fireEvent.click(screen.getByTestId('processes-profile-choose-all'));
      await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/preset', { preset: 'all' }));
    });

    it('is read-only for a non-admin but still shows the active profile', async () => {
      role = 'editor';
      await open([core(), search({ enabled: true }), heavy()]);
      expect(screen.getByTestId('processes-profile-recommended')).toHaveAttribute('data-active', 'true');
      expect(screen.queryByTestId('processes-profile-choose-minimal')).toBeNull();
      expect(screen.queryByTestId('processes-profile-choose-all')).toBeNull();
    });

    it('keeps locked services as they are and says how many', async () => {
      await open([core(), search({ enabled: false, env_locked: true }), heavy()]);
      expect(screen.getByTestId('processes-profile-locked')).toHaveTextContent('1');
      expect(screen.getByTestId('processes-profile-recommended')).toHaveAttribute('data-active', 'true');
      expect(screen.getByTestId('processes-profile-recommended')).toHaveTextContent('100 MB');
    });
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
        [
          proc(),
          proc({ id: 'bim_conv', modules: ['bim'], ram_mb_estimate: 300 }),
          proc({ id: 'kpi', category: 'scheduler', modules: ['reporting'], ram_mb_estimate: 5 }),
        ],
        { first_run_done: false },
      ),
    );
    vi.mocked(apiPost).mockResolvedValue(snapshot([]));
    // The header button offers the choice and lazy-loads the wizard.
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    // Light loops start ticked, anything with a model or an index does not.
    await waitFor(() => expect(screen.getByTestId('wizard-module-reporting').querySelector('input')).toBeChecked());
    expect(screen.getByTestId('wizard-module-costs').querySelector('input')).not.toBeChecked();
    expect(screen.getByTestId('wizard-module-costs')).toHaveTextContent('+400 MB');
    // Unticked means no AI for the module, not no module.
    expect(screen.getByTestId('wizard-module-costs')).toHaveTextContent('works without it');
    expect(screen.getByTestId('wizard-total')).toHaveTextContent('5 MB');
    fireEvent.click(screen.getByTestId('wizard-module-costs').querySelector('input'));
    await waitFor(() => expect(screen.getByTestId('wizard-total')).toHaveTextContent('405 MB'));
    fireEvent.click(screen.getByTestId('wizard-start'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/processes/first-run', {
        module_ids: expect.arrayContaining(['costs', 'reporting']),
        start_now: true,
      }),
    );
  });

  it('offers ready-made profiles and marks the one that matches the ticks', async () => {
    vi.mocked(apiGet).mockResolvedValue(
      snapshot(
        [
          proc({ id: 'emb', category: 'ai_model', modules: ['search', 'costs'], ram_mb_estimate: 450 }),
          proc({ id: 'rank', category: 'ai_model', modules: ['costs'], ram_mb_estimate: 800 }),
          proc({ id: 'kpi', category: 'scheduler', modules: ['reporting'], ram_mb_estimate: 5 }),
        ],
        { first_run_done: false },
      ),
    );
    vi.mocked(apiPost).mockResolvedValue(snapshot([]));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    const ticked = (id) => screen.getByTestId(`wizard-module-${id}`).querySelector('input').checked;
    // The first-run ticks are the balanced profile.
    await waitFor(() => expect(screen.getByTestId('wizard-preset-balanced')).toHaveAttribute('aria-pressed', 'true'));
    expect(screen.getByTestId('wizard-preset-search')).toHaveTextContent('455 MB');
    fireEvent.click(screen.getByTestId('wizard-preset-speed'));
    expect(ticked('reporting')).toBe(false);
    expect(screen.getByTestId('wizard-total')).toHaveTextContent('0 MB');
    fireEvent.click(screen.getByTestId('wizard-preset-search'));
    expect([ticked('reporting'), ticked('search'), ticked('costs')]).toEqual([true, true, false]);
    fireEvent.click(screen.getByTestId('wizard-preset-features'));
    expect(screen.getByTestId('wizard-total')).toHaveTextContent('1.2 GB');
    // A tick by hand leaves the profiles: none is marked.
    fireEvent.click(screen.getByTestId('wizard-module-reporting').querySelector('input'));
    expect(screen.getByTestId('wizard-preset-custom')).toBeInTheDocument();
    expect(screen.getByTestId('wizard-preset-features')).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(screen.getByTestId('wizard-start'));
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/processes/first-run', {
        module_ids: expect.arrayContaining(['search', 'costs']),
        start_now: true,
      }),
    );
  });

  it('closes at once and does not wait for the services to start', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ id: 'kpi', modules: ['reporting'] })], { first_run_done: false }));
    // The server never answers: the wizard must be gone anyway.
    vi.mocked(apiPost).mockImplementation(() => new Promise(() => {}));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('wizard-start'));
    expect(screen.queryByTestId('processes-wizard')).toBeNull();
    expect(useProcessesUi.getState().wizardOpen).toBe(false);
    await waitFor(() =>
      expect(apiPost).toHaveBeenCalledWith('/v1/processes/first-run', expect.objectContaining({ start_now: true })),
    );
  });

  it('follows the started services from the header and says when they are ready', async () => {
    const emb = { id: 'emb', category: 'ai_model', modules: ['costs'], start_mode: 'boot' };
    vi.mocked(apiGet)
      .mockResolvedValueOnce(snapshot([proc(emb)], { first_run_done: false }))
      .mockResolvedValue(snapshot([proc({ ...emb, enabled: true, status: 'running' })]));
    vi.mocked(apiPost).mockResolvedValue(snapshot([proc({ ...emb, enabled: true, status: 'idle', queued: true })]));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('wizard-start'));
    await waitFor(() => expect(toastTitles()).toContain('Starting services in the background'));
    await waitFor(() => expect(toastTitles()).toContain('Background services are ready'), { timeout: 5000 });
    expect(useProcessesUi.getState().startWatch).toEqual([]);
  });

  it('names a service that failed to start and retries it on request', async () => {
    const emb = { id: 'emb', category: 'ai_model', modules: ['costs'], start_mode: 'boot' };
    vi.mocked(apiGet)
      .mockResolvedValueOnce(snapshot([proc(emb)], { first_run_done: false }))
      .mockResolvedValue(
        snapshot([proc({ ...emb, enabled: true, status: 'error', last_error: { message: 'model missing', at: null } })]),
      );
    vi.mocked(apiPost).mockResolvedValue(snapshot([proc({ ...emb, enabled: true, status: 'starting' })]));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('wizard-start'));
    let failed;
    await waitFor(() => {
      failed = useToastStore.getState().toasts.find((x) => x.type === 'error');
      expect(failed).toBeTruthy();
    }, { timeout: 5000 });
    expect(failed.title).toContain('could not start');
    expect(failed.message).toBe('model missing');
    expect(toastTitles()).not.toContain('Background services are ready');
    failed.action.onClick();
    await waitFor(() => expect(apiPost).toHaveBeenCalledWith('/v1/processes/emb/restart'));
  });

  it('offers a retry when the answer could not be sent', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ id: 'kpi', modules: ['reporting'] })], { first_run_done: false }));
    vi.mocked(apiPost).mockRejectedValueOnce(new Error('offline')).mockResolvedValue(snapshot([]));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('processes-wizard', {}, { timeout: 5000 });
    fireEvent.click(screen.getByTestId('wizard-later'));
    let failed;
    await waitFor(() => {
      failed = useToastStore.getState().toasts.find((x) => x.type === 'error');
      expect(failed).toBeTruthy();
    });
    failed.action.onClick();
    await waitFor(() => expect(vi.mocked(apiPost).mock.calls.filter((c) => c[0] === '/v1/processes/first-run')).toHaveLength(2));
  });

  it('is not offered to a non-admin', async () => {
    role = 'viewer';
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()], { first_run_done: false }));
    renderWith(<ProcessesButton />);
    await screen.findByTestId('header-processes');
    expect(useProcessesUi.getState().wizardOpen).toBe(false);
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

  it('asks the server once to prepare the module, without waiting on it', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc({ enabled: true, status: 'idle', queued: true })]));
    const first = renderWith(<ModuleProcessesNotice moduleId="costs" />);
    const note = await screen.findByTestId('module-processes-notice-costs');
    expect(note).toHaveAttribute('data-state', 'preparing');
    expect(screen.queryByTestId('module-processes-turn-on')).toBeNull();
    first.unmount();
    renderWith(<ModuleProcessesNotice moduleId="costs" />);
    await screen.findByTestId('module-processes-notice-costs');
    const ensures = vi.mocked(apiPost).mock.calls.filter(([u]) => String(u).startsWith('/v1/processes/ensure'));
    expect(ensures).toEqual([['/v1/processes/ensure?module=costs']]);
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

  it('leaves out services another notice on the page speaks for', async () => {
    vi.mocked(apiGet).mockResolvedValue(snapshot([proc()]));
    const { container } = renderWith(<ModuleProcessesNotice moduleId="costs" exclude={['vector_db']} />);
    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    await new Promise((r) => setTimeout(r, 50));
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
