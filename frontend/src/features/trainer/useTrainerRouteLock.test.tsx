// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The route gate: what `P` renders for each trainer state and route.

import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

vi.mock('react-i18next', () => ({
  useTranslation: () => ({
    t: (key: string, opts?: Record<string, unknown>) => {
      const template = typeof opts?.defaultValue === 'string' ? opts.defaultValue : key;
      return template.replace(/\{\{(\w+)\}\}/g, (_, name: string) => String(opts?.[name] ?? ''));
    },
    i18n: { language: 'en', changeLanguage: vi.fn() },
  }),
  Trans: ({ children }: { children: ReactNode }) => children,
  initReactI18next: { type: '3rdParty', init: () => {} },
}));

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ApiError } from '@/shared/lib/api';
import { SYSTEM_STATUS_QUERY_KEY } from '@/shared/hooks/useSystemStatus';
import { useAuthStore } from '@/stores/useAuthStore';
import { meFixture } from './__fixtures__/me';
import { trainerKeys } from './queries';
import { TrainerRouteOutcome, useTrainerRouteLock, type TrainerRouteLock } from './useTrainerRouteLock';
import { TRAINER_MODE_STORAGE_KEY, __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only: every wait below first awaits the thing it depends on (the
// lazy chunk, the query settling), so under a loaded full run it does not
// race the default 1 s.
const BACKSTOP = { timeout: 5000 };
const seen: Array<TrainerRouteLock | null> = [];

function Probe() {
  const lock = useTrainerRouteLock();
  seen.push(lock);
  if (lock) return <TrainerRouteOutcome outcome={lock} />;
  return <div data-testid="page">module page</div>;
}

function Where() {
  const location = useLocation();
  return <div data-testid="where">{location.pathname}</div>;
}

function tree(path: string) {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route path="/academy" element={<div data-testid="map">course map</div>} />
          <Route path="*" element={<Probe />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function renderAt(path: string) {
  return render(tree(path));
}

/** Seed the shared status and, optionally, `/me`, so nothing is fetched. */
function seed(academy: boolean, me?: unknown) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: academy });
  if (me !== undefined) client.setQueryData(trainerKeys.me(), me);
}

function serveMe(me: () => unknown) {
  api.apiGet.mockImplementation(async (path: string) => {
    if (path === '/v1/trainer/me') {
      const value = me();
      if (value instanceof Error) throw value;
      return value;
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

function lastLock() {
  return seen[seen.length - 1];
}

beforeAll(async () => {
  await import('./LockedModulePage');
}, 60_000);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  seen.length = 0;
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
  localStorage.clear();
  __resetTrainerCacheOwnerForTests();
  useTrainerUiStore.getState().reset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
});
afterEach(() => {
  cleanup();
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
});

describe('trainer off', () => {
  it('a normal install renders every route unchanged and asks nothing', () => {
    seed(false);
    for (const path of ['/variations', '/bid-management', '/dashboard', '/boq']) {
      const view = renderAt(path);
      expect(screen.getByTestId('page')).toBeInTheDocument();
      expect(lastLock()).toBeNull();
      view.unmount();
    }
    expect(api.apiGet).not.toHaveBeenCalled();
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it('signed out: null, and not even the status is asked', () => {
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    localStorage.setItem(TRAINER_MODE_STORAGE_KEY, '1');
    renderAt('/variations');
    expect(lastLock()).toBeNull();
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('an academy box without an enrolment locks nothing and keeps the dashboard', async () => {
    seed(true, null);
    renderAt('/variations');
    expect(screen.getByTestId('page')).toBeInTheDocument();
    cleanup();
    renderAt('/dashboard');
    expect(screen.getByTestId('page')).toBeInTheDocument();
    expect(lastLock()).toBeNull();
  });
});

describe('while the course loads', () => {
  it('a gated route waits with a spinner; an open route renders at once', () => {
    seed(true);
    serveMe(() => new Promise(() => {}));
    renderAt('/variations');
    expect(lastLock()).toEqual({ kind: 'pending' });
    expect(screen.getByRole('status')).toHaveTextContent('Loading your course');
    expect(screen.queryByTestId('page')).toBeNull();
    cleanup();
    renderAt('/boq/abc');
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });

  it('the dashboard waits too, so a learner never sees it flash', () => {
    seed(true);
    serveMe(() => new Promise(() => {}));
    renderAt('/dashboard');
    expect(lastLock()).toEqual({ kind: 'pending' });
  });

  it('checking: the cached flag holds a gated route until the status answers', () => {
    localStorage.setItem(TRAINER_MODE_STORAGE_KEY, '1');
    api.apiGet.mockImplementation(() => new Promise(() => {}));
    renderAt('/projects/p1/variations');
    expect(lastLock()).toEqual({ kind: 'pending' });
  });
});

describe('when /me fails', () => {
  it('a gated route shows the error state with a working retry; an open route renders', async () => {
    seed(true);
    let fail = true;
    serveMe(() => (fail ? new ApiError(503, 'Unavailable', undefined) : meFixture));
    renderAt('/variations');
    await waitFor(() => expect(lastLock()).toEqual({ kind: 'error' }), BACKSTOP);
    await act(async () => {
      await import('./LockedModulePage');
    });
    const alert = await screen.findByRole('alert', {}, BACKSTOP);
    expect(alert).toHaveTextContent('Your course did not load');
    // Showing the error page must not refetch the failed `/me` by itself.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(api.apiGet).toHaveBeenCalledTimes(1);
    fail = false;
    screen.getByRole('button', { name: /retry/i }).click();
    await screen.findByRole('heading', { name: 'Variations opens after task 4' }, BACKSTOP);
  });

  it('an open route is not touched by the failure', async () => {
    seed(true);
    serveMe(() => new ApiError(503, 'Unavailable', undefined));
    renderAt('/boq');
    await waitFor(() => expect(api.apiGet).toHaveBeenCalled(), BACKSTOP);
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });
});

describe('enrolled', () => {
  it('a closed module lock replaces the page, with or without the project prefix', async () => {
    seed(true, meFixture);
    renderAt('/variations');
    expect(lastLock()).toEqual({ kind: 'locked', lockId: 'variations' });
    expect(await screen.findByRole('heading', { name: 'Variations opens after task 4' }, BACKSTOP)).toBeInTheDocument();
    expect(screen.queryByTestId('page')).toBeNull();
    cleanup();
    renderAt('/projects/p1/bid-management/');
    expect(lastLock()).toEqual({ kind: 'locked', lockId: 'bid_management' });
  });

  it('the claim detail route takes the most specific closed lock', () => {
    seed(true, meFixture);
    renderAt('/projects/p1/contracts/claims/c9');
    expect(lastLock()).toEqual({ kind: 'locked', lockId: 'contracts.progress_claims' });
  });

  it('a lock the course does not list is open', () => {
    seed(true, meFixture);
    renderAt('/contracts');
    expect(lastLock()).toBeNull();
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });

  it('an opened lock renders the module', () => {
    const me = structuredClone(meFixture);
    me.unlocks = me.unlocks.map((u) => (u.lock_id === 'variations' ? { ...u, state: 'open' as const } : u));
    seed(true, me);
    renderAt('/variations');
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });

  it('out-of-course routes are never locked', () => {
    seed(true, meFixture);
    renderAt('/finance');
    expect(lastLock()).toBeNull();
  });

  it('the dashboard sends the learner to the course map', async () => {
    seed(true, meFixture);
    renderAt('/dashboard');
    expect(await screen.findByTestId('map', {}, BACKSTOP)).toBeInTheDocument();
    expect(screen.getByTestId('where')).toHaveTextContent('/academy');
  });

  it('a project dashboard is not the landing page and stays', () => {
    seed(true, meFixture);
    renderAt('/projects/p1/dashboard');
    expect(screen.getByTestId('page')).toBeInTheDocument();
  });

  it('keeps one outcome object across re-renders', () => {
    seed(true, meFixture);
    const view = renderAt('/variations');
    const first = lastLock();
    const renders = seen.length;
    view.rerender(tree('/variations'));
    expect(seen.length).toBeGreaterThan(renders);
    expect(lastLock()).toBe(first);
  });
});
