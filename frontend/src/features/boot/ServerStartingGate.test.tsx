// @ts-nocheck
/**
 * The setup screen while the server is still starting: it names the phase,
 * opens the app by itself once health answers 200, comes back when an API call
 * says the server is starting, and fails open when health cannot be reached.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import { render, screen, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

import { ServerStartingGate, BOOT_POLL_MS } from './ServerStartingGate';
import { parseBootBody, reportIfServerStarting, useServerBootStore } from '@/stores/useServerBootStore';

function starting(phase = 'Database', step = 3) {
  return {
    status: 503,
    ok: false,
    json: async () => ({
      status: 'starting',
      boot: { status: 'starting', phase, step, steps: 9, elapsed_seconds: 42, phase_elapsed_seconds: 10 },
    }),
  };
}
const healthy = { status: 200, ok: true, json: async () => ({ status: 'healthy' }) };

function renderGate() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <ServerStartingGate>
        <div data-testid="app">app</div>
      </ServerStartingGate>
    </QueryClientProvider>,
  );
}

describe('ServerStartingGate', () => {
  beforeEach(() => {
    useServerBootStore.setState({ phase: 'checking', boot: null });
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  it('renders the app at once when the server is ready', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(healthy));
    renderGate();
    expect(await screen.findByTestId('app')).toBeTruthy();
    expect(screen.queryByTestId('server-starting-screen')).toBeNull();
  });

  it('shows the phase while starting and opens the app when ready', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(starting('Modules', 4)).mockResolvedValue(healthy);
    vi.stubGlobal('fetch', fetchMock);
    renderGate();
    expect(await screen.findByTestId('server-starting-screen')).toBeTruthy();
    expect(screen.getByTestId('server-starting-phase').textContent).toBe('Loading modules');
    expect(screen.getByText('Step 4 of 9')).toBeTruthy();
    expect(screen.queryByTestId('app')).toBeNull();
    // The next poll answers 200.
    expect(await screen.findByTestId('app', {}, { timeout: BOOT_POLL_MS + 2000 })).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('fails open when health cannot be reached', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new TypeError('offline')));
    renderGate();
    expect(await screen.findByTestId('app')).toBeTruthy();
  });

  it('shows the failure instead of polling for ever', async () => {
    const fetchMock = vi.fn().mockResolvedValue({
      status: 503,
      ok: false,
      json: async () => ({
        status: 'failed',
        boot: { status: 'failed', phase: 'Database', step: 3, steps: 9, elapsed_seconds: 5, phase_elapsed_seconds: 1 },
      }),
    });
    vi.stubGlobal('fetch', fetchMock);
    renderGate();
    expect(await screen.findByText('The server could not start')).toBeTruthy();
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('comes back when an API call reports the server is starting', async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(healthy).mockResolvedValue(starting('Routing', 9));
    vi.stubGlobal('fetch', fetchMock);
    renderGate();
    expect(await screen.findByTestId('app')).toBeTruthy();
    act(() => {
      reportIfServerStarting(503, {
        code: 'server_starting',
        boot: { status: 'starting', phase: 'Routing', step: 9, steps: 9, elapsed_seconds: 1, phase_elapsed_seconds: 1 },
      });
    });
    await waitFor(() => expect(screen.getByTestId('server-starting-screen')).toBeTruthy());
    expect(screen.getByTestId('server-starting-phase').textContent).toBe('Finishing');
  });
});

describe('parseBootBody', () => {
  it('reads only the server-starting 503', () => {
    const boot = { status: 'starting', phase: 'Database', step: 3, steps: 9, elapsed_seconds: 1, phase_elapsed_seconds: 1 };
    expect(parseBootBody(503, { boot })?.phase).toBe('Database');
    expect(parseBootBody(500, { boot })).toBeNull();
    expect(parseBootBody(503, { detail: 'maintenance' })).toBeNull();
    expect(parseBootBody(503, 'Service Unavailable')).toBeNull();
  });
});
