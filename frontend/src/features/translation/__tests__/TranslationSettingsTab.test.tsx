// @ts-nocheck
// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

/**
 * Unit tests for TranslationSettingsTab.
 *
 * Strategy: stub the ``./api`` module so the network layer is fully
 * deterministic, then drive the tab through the user-visible flows:
 *   - empty / populated / loading states
 *   - MUSE form fires the right mutation body
 *   - IATE local-path form fires the right mutation
 *   - IATE URL form rejects out-of-allowlist URLs client-side
 *   - polling refresh while in-flight tasks present
 *   - error states surface user-readable error toasts
 */

import {
  describe,
  expect,
  it,
  vi,
  beforeEach,
  afterEach,
} from 'vitest';
import {
  render,
  screen,
  fireEvent,
  waitFor,
  cleanup,
} from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

// Mock the api module BEFORE importing the component so the queries
// hooks pick up the spies.  Re-export ``isIateUrlAllowed`` /
// ``IATE_ALLOWED_PREFIXES`` from the real module — those are pure
// constants and we want to test the same client-side check.
vi.mock('../api', async () => {
  const actual = await vi.importActual<typeof import('../api')>('../api');
  return {
    ...actual,
    getTranslationStatus: vi.fn(),
    triggerLookupDownload: vi.fn(),
    translateOne: vi.fn(),
  };
});

// Mock the toast store so we can assert toast invocations.  The
// component reads it via ``useToastStore((s) => s.addToast)`` so the
// mock must behave like a Zustand hook: callable as a selector and
// also exposing ``getState()`` for non-hook call sites.  Use
// ``vi.hoisted`` so the spy is available inside the hoisted
// ``vi.mock`` factory AND inside the test bodies.
const { addToastSpy } = vi.hoisted(() => ({ addToastSpy: vi.fn() }));
vi.mock('@/stores/useToastStore', () => {
  const toastState = { addToast: addToastSpy };
  const useToastStore = Object.assign(
    (selector?: (s: typeof toastState) => unknown) =>
      typeof selector === 'function' ? selector(toastState) : toastState,
    { getState: () => toastState },
  );
  return { useToastStore };
});

import { getTranslationStatus, triggerLookupDownload } from '../api';
import { TranslationSettingsTab } from '../TranslationSettingsTab';
import type { StatusResponse } from '../types';

/* ── Fixtures ──────────────────────────────────────────────────────────── */

function makeStatus(over: Partial<StatusResponse> = {}): StatusResponse {
  return {
    dictionaries: { muse: [], iate: [] },
    cache: { rows: 0, hits: 0 },
    in_flight: [],
    ...over,
  };
}

function renderTab(opts: { disablePolling?: boolean } = {}) {
  // ``refetchInterval`` is part of the per-hook config; tests that
  // explicitly want to disable polling pass ``disablePolling`` so the
  // default polling test can still observe the 5 s tick.
  const client = new QueryClient({
    defaultOptions: {
      queries: opts.disablePolling
        ? { retry: false, refetchInterval: false }
        : { retry: false },
      mutations: { retry: false },
    },
  });
  return render(
    <QueryClientProvider client={client}>
      <TranslationSettingsTab projectId="proj-1" />
    </QueryClientProvider>,
  );
}

/* ── Tests ─────────────────────────────────────────────────────────────── */

describe('TranslationSettingsTab', () => {
  beforeEach(() => {
    vi.mocked(getTranslationStatus).mockReset();
    vi.mocked(triggerLookupDownload).mockReset();
    addToastSpy.mockReset();
  });

  afterEach(() => {
    cleanup();
  });

  it('renders the empty-state when no dictionaries are downloaded', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());

    renderTab();

    expect(await screen.findByTestId('translation-dict-empty')).toBeInTheDocument();
  });

  it('renders cache stats when the status query resolves', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(
      makeStatus({ cache: { rows: 42, hits: 137 } }),
    );

    renderTab();

    // The stats node first renders "Loading…" while the query is
    // pending, then transitions to the summary template.  The shared
    // ``react-i18next`` test mock returns ``defaultValue`` verbatim
    // (no interpolation), so we assert on the unresolved template
    // string rather than the rendered numbers.
    await waitFor(() => {
      const stats = screen.getByTestId('translation-cache-stats');
      expect(stats.textContent).toMatch(/cached translations/i);
    });
  });

  it('renders the dictionary table when entries are present', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(
      makeStatus({
        dictionaries: {
          muse: [
            {
              pair: 'en-de',
              path: '/x/muse/en-de.tsv',
              size_bytes: 4_500_000,
              modified_at: Math.floor(Date.now() / 1000) - 3600,
            },
          ],
          iate: [
            {
              pair: 'en-fr',
              path: '/x/iate/en-fr.tsv',
              size_bytes: 12_300_000,
              modified_at: Math.floor(Date.now() / 1000) - 86_400,
            },
          ],
        },
      }),
    );

    renderTab();

    expect(
      await screen.findByTestId('translation-dict-row-muse-en-de'),
    ).toBeInTheDocument();
    expect(screen.getByTestId('translation-dict-row-iate-en-fr')).toBeInTheDocument();
  });

  it('MUSE form fires triggerLookupDownload with the selected preset pair', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());
    vi.mocked(triggerLookupDownload).mockResolvedValue({
      task_id: 't1',
      kind: 'muse',
      status: 'queued',
    });

    renderTab();

    // Wait for the form to mount (status query resolves).
    await screen.findByTestId('translation-muse-form');

    fireEvent.click(screen.getByTestId('translation-muse-submit'));

    await waitFor(() => {
      expect(triggerLookupDownload).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(triggerLookupDownload).mock.calls[0][0]).toEqual({
      kind: 'muse',
      source_lang: 'en',
      target_lang: 'de',
    });
  });

  it('MUSE form posts custom-typed pair when the "Other" option is chosen', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());
    vi.mocked(triggerLookupDownload).mockResolvedValue({
      task_id: 't2',
      kind: 'muse',
      status: 'queued',
    });

    renderTab();

    const select = (await screen.findByTestId(
      'translation-muse-preset',
    )) as HTMLSelectElement;
    fireEvent.change(select, { target: { value: '__custom__' } });

    fireEvent.change(screen.getByTestId('translation-muse-custom-src'), {
      target: { value: 'cs' },
    });
    fireEvent.change(screen.getByTestId('translation-muse-custom-tgt'), {
      target: { value: 'sk' },
    });

    fireEvent.click(screen.getByTestId('translation-muse-submit'));

    await waitFor(() => {
      expect(triggerLookupDownload).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(triggerLookupDownload).mock.calls[0][0]).toEqual({
      kind: 'muse',
      source_lang: 'cs',
      target_lang: 'sk',
    });
  });

  it('IATE local-path form fires the right mutation body', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());
    vi.mocked(triggerLookupDownload).mockResolvedValue({
      task_id: 't3',
      kind: 'iate',
      status: 'queued',
    });

    renderTab();

    const localInput = (await screen.findByTestId(
      'translation-iate-local-input',
    )) as HTMLInputElement;
    fireEvent.change(localInput, {
      target: { value: '/home/me/IATE_export.tbx' },
    });

    fireEvent.click(screen.getByTestId('translation-iate-local-submit'));

    await waitFor(() => {
      expect(triggerLookupDownload).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(triggerLookupDownload).mock.calls[0][0]).toEqual({
      kind: 'iate',
      local_tbx_path: '/home/me/IATE_export.tbx',
    });
  });

  it('IATE URL form rejects URLs outside the allowlist client-side', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());

    renderTab();

    const urlInput = (await screen.findByTestId(
      'translation-iate-url-input',
    )) as HTMLInputElement;
    fireEvent.change(urlInput, {
      target: { value: 'http://evil.example.com/iate.tbx.zip' },
    });

    // The submit button should be disabled and an inline error visible.
    const submit = screen.getByTestId('translation-iate-url-submit') as HTMLButtonElement;
    expect(submit.disabled).toBe(true);
    expect(
      screen.getByText(/must start with one of the allowed prefixes/i),
    ).toBeInTheDocument();

    // Even if the user clicks anyway, the mutation must NOT fire.
    fireEvent.click(submit);
    expect(triggerLookupDownload).not.toHaveBeenCalled();
  });

  it('IATE URL form accepts an allowlisted iate.europa.eu URL', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());
    vi.mocked(triggerLookupDownload).mockResolvedValue({
      task_id: 't4',
      kind: 'iate',
      status: 'queued',
    });

    renderTab();

    const urlInput = (await screen.findByTestId(
      'translation-iate-url-input',
    )) as HTMLInputElement;
    fireEvent.change(urlInput, {
      target: { value: 'https://iate.europa.eu/exports/IATE_export.tbx.zip' },
    });

    fireEvent.click(screen.getByTestId('translation-iate-url-submit'));

    await waitFor(() => {
      expect(triggerLookupDownload).toHaveBeenCalledTimes(1);
    });
    expect(vi.mocked(triggerLookupDownload).mock.calls[0][0]).toEqual({
      kind: 'iate',
      url: 'https://iate.europa.eu/exports/IATE_export.tbx.zip',
    });
  });

  it('renders the in-flight tasks card when a task is running', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(
      makeStatus({
        in_flight: [
          {
            task_id: 'abc123',
            kind: 'muse',
            status: 'running',
            progress: 0.42,
          },
        ],
      }),
    );

    renderTab();

    expect(await screen.findByTestId('translation-tasks-section')).toBeInTheDocument();
    const taskRow = screen.getByTestId('translation-task-abc123');
    expect(taskRow).toBeInTheDocument();
    expect(taskRow.textContent).toMatch(/42/);
  });

  it('exposes adaptive polling via useTranslationStatus (5 s while tasks running)', async () => {
    // Mixing fake timers with React Query's scheduler is brittle across
    // versions, so we drive the public surface instead: import the hook
    // and assert the ``refetchInterval`` callback returns 5 000 ms when
    // any in-flight task is queued/running, and 30 000 ms when the
    // queue is empty.  The hook's behaviour is what the spec actually
    // promises; the underlying timer is React Query's job.
    const { useTranslationStatus } = await import('../queries');
    const { renderHook } = await import('@testing-library/react');
    const client = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    vi.mocked(getTranslationStatus).mockResolvedValue(
      makeStatus({
        in_flight: [
          {
            task_id: 't',
            kind: 'muse',
            status: 'running',
            progress: 0.1,
          },
        ],
      }),
    );

    const wrapper = ({ children }: { children: React.ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );
    const { result } = renderHook(() => useTranslationStatus(), { wrapper });

    await waitFor(() => {
      expect(result.current.data?.in_flight.length).toBe(1);
    });

    // React Query's Query object exposes its options on
    // ``query.options``; we re-derive the same predicate the hook
    // uses to confirm 5 s vs 30 s.
    const observers = client.getQueryCache().getAll();
    const query = observers.find((q) =>
      q.queryKey[0] === 'translation' && q.queryKey[1] === 'status',
    );
    expect(query).toBeTruthy();
    const interval = (query!.options.refetchInterval as
      | ((q: { state: { data: unknown } }) => number)
      | undefined)?.({
      state: { data: result.current.data },
    });
    expect(interval).toBe(5_000);

    // Now flip to an empty queue and re-evaluate.
    const idleInterval = (query!.options.refetchInterval as
      | ((q: { state: { data: unknown } }) => number)
      | undefined)?.({
      state: { data: { ...result.current.data!, in_flight: [] } },
    });
    expect(idleInterval).toBe(30_000);
  });

  it('surfaces a user-readable error toast when the download trigger fails', async () => {
    vi.mocked(getTranslationStatus).mockResolvedValue(makeStatus());
    vi.mocked(triggerLookupDownload).mockRejectedValue(
      new Error('500: internal server error'),
    );

    renderTab();

    await screen.findByTestId('translation-muse-form');

    fireEvent.click(screen.getByTestId('translation-muse-submit'));

    await waitFor(() => {
      expect(addToastSpy).toHaveBeenCalled();
    });
    const lastCall = addToastSpy.mock.calls[addToastSpy.mock.calls.length - 1][0];
    expect(lastCall.type).toBe('error');
    expect(String(lastCall.message)).toMatch(/internal server error/i);
  });

  it('surfaces an error banner when the status query itself fails', async () => {
    vi.mocked(getTranslationStatus).mockRejectedValue(
      new Error('network down'),
    );

    renderTab();

    expect(
      await screen.findByTestId('translation-status-error'),
    ).toBeInTheDocument();
    // The shared ``react-i18next`` test mock returns ``defaultValue``
    // verbatim (no interpolation), so we assert on the template body
    // rather than the interpolated error text.
    expect(screen.getByRole('alert').textContent).toMatch(
      /Could not load dictionary status/i,
    );
  });
});
