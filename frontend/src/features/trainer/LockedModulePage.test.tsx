// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The locked module page: what it says, the path it draws, where its buttons
// go, and its error and loading states.

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
import { LockedModulePage, nextActionTask, openingTaskFor, taskHref } from './LockedModulePage';
import { trainerKeys } from './queries';
import type { TrainerMe } from './types';
import { __resetTrainerCacheOwnerForTests, useTrainerMode } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only: every wait below first awaits the thing it depends on (the
// lazy chunk, the query settling), so under a loaded full run it does not
// race the default 1 s.
const BACKSTOP = { timeout: 5000 };

function Where() {
  const location = useLocation();
  return <div data-testid="where">{`${location.pathname}${location.hash}`}</div>;
}

function Harness({ lockId }: { lockId: string | null }) {
  const mode = useTrainerMode();
  return <LockedModulePage lockId={lockId} mode={mode} />;
}

function renderPage(lockId: string | null) {
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/variations']}>
        <Routes>
          <Route path="*" element={<Harness lockId={lockId} />} />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

function seed(me?: TrainerMe | null) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: true });
  if (me !== undefined) client.setQueryData(trainerKeys.me(), me);
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  api.apiPost.mockReset();
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

describe('helpers', () => {
  it('finds the opening task by `opens`, else by the unlock row', () => {
    expect(openingTaskFor(meFixture, 'variations')?.n).toBe(4);
    const me = structuredClone(meFixture);
    me.tasks = me.tasks.map((t) => (t.opens === 'variations' ? { ...t, opens: 'something_else' } : t));
    expect(openingTaskFor(me, 'variations')?.n).toBe(4);
    expect(openingTaskFor(meFixture, 'nope')).toBeNull();
  });

  it('the button goes to the opening task when it can be worked on', () => {
    // Task 2 went back to "needs another look" while task 4 is already open.
    const tasks = meFixture.tasks.map((t) =>
      t.n === 4 ? { ...t, status: 'not_started' as const, target: { route: '/contracts', anchor: null } } : t,
    );
    expect(nextActionTask(tasks, 4)?.id).toBe('t4-valuation');
  });

  it('else the first earlier task neither passed nor locked', () => {
    expect(nextActionTask(meFixture.tasks, 4)?.id).toBe('t2-markups');
    const allLocked = meFixture.tasks.map((t) => ({ ...t, status: 'locked' as const, target: null }));
    expect(nextActionTask(allLocked, 4)).toBeNull();
  });

  it('adds the anchor to the route once', () => {
    expect(taskHref({ target: { route: '/boq/1', anchor: 'boq-markups-panel' } })).toBe('/boq/1#boq-markups-panel');
    expect(taskHref({ target: { route: '/boq/1#x', anchor: 'boq-markups-panel' } })).toBe('/boq/1#x');
    expect(taskHref({ target: { route: '/boq/1', anchor: null } })).toBe('/boq/1');
    expect(taskHref({ target: null })).toBeNull();
  });
});

describe('LockedModulePage', () => {
  it('names the module and the task that opens it, in plain words', () => {
    seed(meFixture);
    renderPage('variations');
    expect(screen.getByRole('heading', { level: 1, name: 'Variations opens after task 4' })).toBeInTheDocument();
    expect(screen.getByText('Finish task 4, Value the first claim, and this opens.')).toBeInTheDocument();
    expect(
      screen.getByText('Your project and everything you entered stay as they are while a module is locked.'),
    ).toBeInTheDocument();
  });

  it('draws the path from task 1 to the opening task, then the module', () => {
    seed(meFixture);
    renderPage('variations');
    const path = screen.getByRole('list', { name: 'Your path to this module' });
    const items = within(path).getAllByRole('listitem');
    // The circle is aria-hidden; the label (with its status for screen readers) is the last child.
    expect(items.map((li) => li.lastElementChild?.textContent)).toEqual([
      'Task 1, Verified',
      'Task 2, Needs another look',
      'Task 3, Locked',
      'Task 4, Locked',
      'Variations, Locked',
    ]);
    expect(items[1]).toHaveAttribute('aria-current', 'step');
    // The module label is course text: it carries the course language.
    expect(within(items[4]!).getByText('Variations')).toHaveAttribute('lang', 'en-GB');
  });

  it('"Go to task" opens the task to do now, in the right place, with the dock', () => {
    seed(meFixture);
    renderPage('variations');
    const go = screen.getByRole('link', { name: 'Go to task 2' });
    expect(go).toHaveAttribute('href', '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');
    fireEvent.click(go);
    expect(screen.getByTestId('where')).toHaveTextContent('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');
    expect(useTrainerUiStore.getState()).toMatchObject({ dockTaskId: 't2-markups', dockOpen: true });
  });

  it('"Course map" goes to the course map', () => {
    seed(meFixture);
    renderPage('variations');
    fireEvent.click(screen.getByRole('link', { name: 'Course map' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/academy');
  });

  it('shows the course reason when the opening task has one', () => {
    seed(meFixture);
    renderPage('contracts.progress_claims');
    expect(screen.getByRole('heading', { name: 'Progress claims opens after task 3' })).toBeInTheDocument();
    expect(screen.getByText('Opens when task 2 passes.')).toHaveAttribute('lang', 'en-GB');
  });

  it('draws no dead button when no task can be opened', () => {
    const me = structuredClone(meFixture);
    me.tasks = me.tasks.map((t) => ({ ...t, status: 'locked' as const, target: null }));
    seed(me);
    renderPage('variations');
    expect(screen.queryByRole('link', { name: /Go to task/ })).toBeNull();
    expect(screen.getByRole('link', { name: 'Course map' })).toBeInTheDocument();
  });

  it('a badge or unknown lock id draws nothing', () => {
    seed(meFixture);
    renderPage('badge:fx-quillmere-1');
    expect(screen.queryByRole('heading')).toBeNull();
    cleanup();
    seed(meFixture);
    renderPage('no_such_lock');
    expect(screen.queryByRole('heading')).toBeNull();
  });

  it('error variant: says nothing is lost, retries, and recovers', async () => {
    seed();
    let fail = true;
    api.apiGet.mockImplementation(async (path: string) => {
      if (path !== '/v1/trainer/me') throw new Error(`unexpected GET ${path}`);
      if (fail) throw new ApiError(503, 'Unavailable', undefined);
      return meFixture;
    });
    renderPage(null);
    await waitFor(() => expect(client.getQueryState(trainerKeys.me())?.status).toBe('error'), BACKSTOP);
    const alert = await screen.findByRole('alert', {}, BACKSTOP);
    expect(alert).toHaveTextContent('Your course did not load');
    expect(alert).toHaveTextContent('Nothing you entered is lost.');
    expect(screen.getByRole('link', { name: 'Course map' })).toHaveAttribute('href', '/academy');
    fail = false;
    fireEvent.click(within(alert).getByRole('button'));
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledTimes(2), BACKSTOP);
    await waitFor(() => expect(screen.queryByRole('alert')).toBeNull(), BACKSTOP);
  });

  it('loading: a spinner, not the module', () => {
    seed();
    api.apiGet.mockImplementation(() => new Promise(() => {}));
    renderPage('variations');
    expect(screen.getByRole('status')).toHaveTextContent('Loading your course');
  });
});
