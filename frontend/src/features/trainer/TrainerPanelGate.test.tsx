// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The panel gate (first use: the BOQ markups panel) and the locked panel card.

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
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
import { TrainerPanelGate } from './TrainerPanelGate';
import type { TrainerMe } from './types';
import { __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only: every wait below first awaits the thing it depends on (the
// lazy chunk, the query settling), so under a loaded full run it does not
// race the default 1 s.
const BACKSTOP = { timeout: 5000 };

function Panel() {
  return (
    <div id="boq-markups-panel" className="panel">
      <h3>Markups</h3>
      <button type="button">Add markup</button>
    </div>
  );
}

function Where() {
  const location = useLocation();
  return <div data-testid="where">{`${location.pathname}${location.hash}`}</div>;
}

function tree(path: string, lockId = 'boq.markups_panel') {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Routes>
          <Route
            path="*"
            element={
              <div data-testid="host">
                <TrainerPanelGate lockId={lockId}>
                  <Panel />
                </TrainerPanelGate>
              </div>
            }
          />
        </Routes>
        <Where />
      </MemoryRouter>
    </QueryClientProvider>
  );
}

function plainHtml(): string {
  const view = render(
    <div data-testid="host">
      <Panel />
    </div>,
  );
  const html = view.getByTestId('host').innerHTML;
  view.unmount();
  return html;
}

function seed(academy: boolean, me?: TrainerMe | null) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: academy });
  if (me !== undefined) client.setQueryData(trainerKeys.me(), me);
}

function withMarkupsLocked(): TrainerMe {
  const me = structuredClone(meFixture);
  me.unlocks = me.unlocks.map((u) => (u.lock_id === 'boq.markups_panel' ? { ...u, state: 'locked' as const } : u));
  me.tasks = me.tasks.map((t) => (t.n === 1 ? { ...t, status: 'in_progress' as const } : t));
  return me;
}

let scrollSpy: ReturnType<typeof vi.fn>;

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
  localStorage.clear();
  __resetTrainerCacheOwnerForTests();
  useTrainerUiStore.getState().reset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
  scrollSpy = vi.fn();
  Element.prototype.scrollIntoView = scrollSpy as unknown as Element['scrollIntoView'];
});
afterEach(() => {
  cleanup();
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
  vi.unstubAllGlobals();
});

async function flushFrames() {
  await act(async () => {
    await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
  });
}

describe('trainer off: identical behaviour', () => {
  it('a normal install renders the panel with the same DOM and asks nothing', () => {
    const expected = plainHtml();
    seed(false);
    render(tree('/boq/b1#boq-markups-panel'));
    expect(screen.getByTestId('host').innerHTML).toBe(expected);
    expect(api.apiGet).not.toHaveBeenCalled();
    expect(api.apiPost).not.toHaveBeenCalled();
    expect(api.apiPut).not.toHaveBeenCalled();
  });

  it('does not scroll on a hash when the trainer is off', async () => {
    seed(false);
    render(tree('/boq/b1#boq-markups-panel'));
    await flushFrames();
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it('signed out: the panel, and not even the status is asked', () => {
    const expected = plainHtml();
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    render(tree('/boq/b1'));
    expect(screen.getByTestId('host').innerHTML).toBe(expected);
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('no enrolment on an academy box: the panel', () => {
    seed(true, null);
    render(tree('/boq/b1'));
    expect(screen.getByRole('button', { name: 'Add markup' })).toBeInTheDocument();
  });
});

describe('trainer on', () => {
  it('a closed panel lock shows the locked card under the panel id', () => {
    seed(true, withMarkupsLocked());
    render(tree('/boq/b1'));
    expect(screen.queryByRole('button', { name: 'Add markup' })).toBeNull();
    const card = screen.getByTestId('trainer-locked-panel');
    expect(card).toHaveAttribute('id', 'boq-markups-panel');
    expect(screen.getByRole('heading', { level: 2, name: 'Markups opens after task 1' })).toBeInTheDocument();
  });

  it('the card buttons work: "Go to task" with the dock, and "Course map"', () => {
    seed(true, withMarkupsLocked());
    render(tree('/boq/b1'));
    fireEvent.click(screen.getByRole('link', { name: 'Go to task 1' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b');
    expect(useTrainerUiStore.getState().dockTaskId).toBe('t1-direct-cost');
    cleanup();
    seed(true, withMarkupsLocked());
    render(tree('/boq/b1'));
    fireEvent.click(screen.getByRole('link', { name: 'Course map' }));
    expect(screen.getByTestId('where')).toHaveTextContent('/academy');
  });

  it('an open panel renders as is and scrolls to the hash once', async () => {
    seed(true, meFixture);
    const view = render(tree('/boq/b1#boq-markups-panel'));
    expect(screen.getByRole('button', { name: 'Add markup' })).toBeInTheDocument();
    await flushFrames();
    expect(scrollSpy).toHaveBeenCalledTimes(1);
    expect(scrollSpy).toHaveBeenCalledWith({ behavior: 'smooth', block: 'start' });
    view.rerender(tree('/boq/b1#boq-markups-panel'));
    await flushFrames();
    expect(scrollSpy).toHaveBeenCalledTimes(1);
  });

  it('scrolls without animation under reduced motion', async () => {
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query.includes('reduce'), media: query }));
    seed(true, meFixture);
    render(tree('/boq/b1#boq-markups-panel'));
    await flushFrames();
    expect(scrollSpy).toHaveBeenCalledWith({ behavior: 'auto', block: 'start' });
  });

  it('no hash, no scroll', async () => {
    seed(true, meFixture);
    render(tree('/boq/b1'));
    await flushFrames();
    expect(scrollSpy).not.toHaveBeenCalled();
  });

  it('while the course loads, a placeholder holds the place, not the panel', () => {
    seed(true);
    api.apiGet.mockImplementation(() => new Promise(() => {}));
    render(tree('/boq/b1'));
    expect(screen.queryByRole('button', { name: 'Add markup' })).toBeNull();
    expect(screen.getByTestId('trainer-panel-pending')).toHaveAttribute('id', 'boq-markups-panel');
  });

  it('a failed course load shows the error card with Retry', async () => {
    seed(true);
    api.apiGet.mockRejectedValue(new ApiError(503, 'Unavailable', undefined));
    render(tree('/boq/b1'));
    await waitFor(() => expect(client.getQueryState(trainerKeys.me())?.status).toBe('error'), BACKSTOP);
    expect(await screen.findByRole('alert', {}, BACKSTOP)).toHaveTextContent('Your course did not load');
    expect(screen.getByTestId('trainer-locked-panel')).toHaveAttribute('id', 'boq-markups-panel');
    // The card reads the course from the gate: mounting it must not refetch
    // the failed `/me` (a refetch flips it to loading, which unmounts the
    // card, which would mount again: a request loop).
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(api.apiGet).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('a badge or unknown lock id renders the children: a registry bug, not a learner state', () => {
    seed(true, meFixture);
    render(tree('/boq/b1', 'badge:fx-quillmere-1'));
    expect(screen.getByRole('button', { name: 'Add markup' })).toBeInTheDocument();
    cleanup();
    seed(true, meFixture);
    render(tree('/boq/b1', 'no_such_lock'));
    expect(screen.getByRole('button', { name: 'Add markup' })).toBeInTheDocument();
  });

  it('the tab gate without an anchor locks the claims table', () => {
    seed(true, meFixture);
    render(tree('/contracts', 'contracts.progress_claims'));
    expect(screen.queryByRole('button', { name: 'Add markup' })).toBeNull();
    expect(screen.getByTestId('trainer-locked-panel')).not.toHaveAttribute('id');
    expect(screen.getByRole('heading', { name: 'Progress claims opens after task 3' })).toBeInTheDocument();
  });
});
