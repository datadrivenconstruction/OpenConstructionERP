// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The unlock host, driven through TrainerSlot the way the app mounts it:
// which unlocks it celebrates, in what order, and how `seen` is posted.

import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
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
import { TrainerSlot } from './TrainerSlot';
import type { TrainerMe } from './types';
import { unlockModalPropsFor, unseenUnlocks } from './UnlockHost';
import { __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only: every wait below first awaits the thing it depends on (the
// lazy chunk, the query settling), so under a loaded full run it does not
// race the default 1 s.
const BACKSTOP = { timeout: 5000 };

/** Task 2 has just passed: Bid Management opened and is not seen yet. */
function afterTask2(): TrainerMe {
  const me = structuredClone(meFixture);
  me.tasks = me.tasks.map((t) => {
    if (t.n === 2) return { ...t, status: 'passed' as const };
    if (t.n === 3) return { ...t, status: 'not_started' as const, target: { route: '/bid-management', anchor: null } };
    return t;
  });
  me.unlocks = me.unlocks.map((u) =>
    u.lock_id === 'bid_management'
      ? { ...u, state: 'open' as const, opened_at: '2026-10-05T10:00:00Z', tiles: [{ title: 'Bid packages', text: 'Send it out.' }] }
      : u,
  );
  me.progress = { ...me.progress, done: 2 };
  return me;
}

function withSeen(me: TrainerMe, lockId: string): TrainerMe {
  return { ...me, unlocks: me.unlocks.map((u) => (u.lock_id === lockId ? { ...u, seen: true } : u)) };
}

function seed(me: TrainerMe) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: true });
  client.setQueryData(trainerKeys.me(), me);
}

async function mount() {
  const view = render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/boq/b1']}>
        <TrainerSlot />
      </MemoryRouter>
    </QueryClientProvider>,
  );
  await act(async () => {
    await Promise.all([import('./TaskDock'), import('./UnlockHost')]);
  });
  return view;
}

function seenPosts(): string[] {
  return api.apiPost.mock.calls.map(([path]) => path as string);
}

// TrainerSlot suspends on two lazy chunks, the dock (heavy) and the host:
// transform both once up front.
beforeAll(async () => {
  await Promise.all([import('./TaskDock'), import('./UnlockHost')]);
}, 60_000);

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
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
  document.body.style.overflow = '';
});

describe('unlockModalPropsFor', () => {
  it('a module unlock: its label, the next task, and the module route', () => {
    const me = afterTask2();
    const unlock = me.unlocks.find((u) => u.lock_id === 'bid_management')!;
    expect(unlockModalPropsFor(me, unlock)).toMatchObject({
      unlock: { lockId: 'bid_management', kind: 'module', label: 'Bid Management', openedByTask: 2 },
      contentLang: 'en-GB',
      progress: { done: 2, total: 5 },
      rings: { numbers: false, trace: true, explain: false },
      week: { done: 1, goal: 3 },
      next: { n: 3, taskId: 't3-tender', to: '/bid-management' },
      goThere: '/bid-management',
    });
  });

  it('a panel unlock goes to the panel on the opening task\'s page', () => {
    const unlock = meFixture.unlocks.find((u) => u.lock_id === 'boq.markups_panel')!;
    const props = unlockModalPropsFor(meFixture, unlock);
    expect(props?.goThere).toBe('/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel');
    expect(props?.next).toMatchObject({ n: 2, to: '/boq/7a4c1f0e-2b3d-4e5f-8a9b-0c1d2e3f4a5b#boq-markups-panel' });
  });

  it('a locked next task is never a button target', () => {
    const me = afterTask2();
    me.tasks = me.tasks.map((t) => (t.n === 3 ? { ...t, status: 'locked' as const } : t));
    const unlock = me.unlocks.find((u) => u.lock_id === 'bid_management')!;
    expect(unlockModalPropsFor(me, unlock)?.next).toBeNull();
  });

  it('the badge takes the course badge title and offers no next task', () => {
    const unlock = { ...meFixture.unlocks.find((u) => u.lock_id === 'badge:fx-quillmere-1')!, state: 'open' as const };
    expect(unlockModalPropsFor(meFixture, unlock)).toMatchObject({
      unlock: { kind: 'badge', label: 'Quillmere Depot: bill to variation' },
      next: null,
      goThere: null,
    });
  });

  it('only open, unseen unlocks, in course order', () => {
    const me = afterTask2();
    me.unlocks = me.unlocks.map((u) => (u.lock_id === 'variations' ? { ...u, state: 'open' as const } : u));
    me.unlocks.reverse();
    expect(unseenUnlocks(me).map((u) => u.lock_id)).toEqual(['bid_management', 'variations']);
  });
});

describe('UnlockHost', () => {
  it('nothing to celebrate: nothing rendered, nothing posted', async () => {
    seed(meFixture);
    await mount();
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(screen.queryByRole('dialog')).toBeNull();
    expect(api.apiPost).not.toHaveBeenCalled();
  });

  it('celebrates a new unlock, and posts `seen` once on close', async () => {
    seed(afterTask2());
    api.apiPost.mockResolvedValue(undefined);
    api.apiGet.mockImplementation(async (path: string) => {
      if (path === '/v1/trainer/me') return withSeen(afterTask2(), 'bid_management');
      throw new Error(`unexpected GET ${path}`);
    });
    await mount();
    const dialog = await screen.findByRole('dialog', { name: 'Bid Management' }, BACKSTOP);
    expect(dialog).toHaveTextContent('New module open');
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('dialog')).toBeNull();
    await waitFor(() => expect(api.apiGet).toHaveBeenCalledWith('/v1/trainer/me'), BACKSTOP);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 20));
    });
    expect(seenPosts()).toEqual(['/v1/trainer/unlocks/bid_management/seen']);
    expect(useTrainerUiStore.getState().celebrated).toEqual(['bid_management']);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('shows two unlocks one at a time, in course order', async () => {
    const me = afterTask2();
    me.unlocks = me.unlocks.map((u) => (u.lock_id === 'contracts.progress_claims' ? { ...u, state: 'open' as const } : u));
    seed(me);
    // A small server: a `seen` POST is recorded, and `/me` reports it.
    let server = me;
    api.apiPost.mockImplementation(async (path: string) => {
      const lockId = path.split('/')[4]!;
      server = withSeen(server, lockId);
    });
    api.apiGet.mockImplementation(async () => server);
    await mount();
    expect(await screen.findByRole('dialog', { name: 'Bid Management' }, BACKSTOP)).toBeInTheDocument();
    expect(screen.getAllByRole('dialog')).toHaveLength(1);
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(await screen.findByRole('dialog', { name: 'Progress claims' }, BACKSTOP)).toBeInTheDocument();
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull(), BACKSTOP);
    expect(seenPosts()).toEqual([
      '/v1/trainer/unlocks/bid_management/seen',
      '/v1/trainer/unlocks/contracts.progress_claims/seen',
    ]);
  });

  it('a failed `seen` POST is retried once on the next load, then left alone, and never re-shown', async () => {
    seed(afterTask2());
    api.apiPost.mockRejectedValue(new ApiError(503, 'Unavailable', undefined));
    // The server never records it: every reload still says unseen.
    api.apiGet.mockImplementation(async () => afterTask2());
    await mount();
    await screen.findByRole('dialog', { name: 'Bid Management' }, BACKSTOP);
    fireEvent.keyDown(document, { key: 'Escape' });
    await waitFor(() => expect(api.apiPost).toHaveBeenCalledTimes(2), BACKSTOP);
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 100));
    });
    expect(api.apiPost).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('an unlock celebrated earlier in the session is not shown again', async () => {
    useTrainerUiStore.getState().markCelebrated('bid_management');
    seed(afterTask2());
    api.apiPost.mockResolvedValue(undefined);
    api.apiGet.mockImplementation(async () => withSeen(afterTask2(), 'bid_management'));
    await mount();
    // It is still unseen on the server, so the host posts it once more.
    await waitFor(() => expect(seenPosts()).toEqual(['/v1/trainer/unlocks/bid_management/seen']), BACKSTOP);
    expect(screen.queryByRole('dialog')).toBeNull();
  });
});
