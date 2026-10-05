// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// TrainerSlot: always mounted, null unless a course is active, and the owner
// of the trainer reset when the signed-in user changes.

import type { ReactNode } from 'react';
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, cleanup, render, screen, waitFor } from '@testing-library/react';
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

// Count the imports of the dock chunk: off and no-enrolment must never load it.
const dock = vi.hoisted(() => ({ loads: 0 }));
vi.mock('./TaskDock', () => {
  dock.loads += 1;
  return { TaskDock: () => <div data-testid="task-dock" /> };
});

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
import { TRAINER_MODE_STORAGE_KEY, __resetTrainerCacheOwnerForTests } from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

// Backstop only: every wait below first awaits the thing it depends on (the
// lazy chunk, the query settling), so under a loaded full run it does not
// race the default 1 s.
const BACKSTOP = { timeout: 5000 };

// The unlock host is a real lazy chunk: transform it once up front. The dock
// is not preloaded here, because the tests count its loads.
beforeAll(async () => {
  await import('./UnlockHost');
}, 60_000);

function wrap(node: ReactNode) {
  return (
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/boq/b1']}>{node}</MemoryRouter>
    </QueryClientProvider>
  );
}

function seed(academy: boolean, me?: unknown) {
  client.setQueryData(SYSTEM_STATUS_QUERY_KEY, { academy_mode: academy });
  if (me !== undefined) client.setQueryData(trainerKeys.me(), me);
}

function expectNoRequests() {
  expect(api.apiGet).not.toHaveBeenCalled();
  expect(api.apiPost).not.toHaveBeenCalled();
  expect(api.apiPut).not.toHaveBeenCalled();
}

async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 20));
  });
}

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
});

describe('TrainerSlot', () => {
  // These run before the enrolled case: the dock module is loaded once per file.
  it('a normal install renders nothing and asks nothing', async () => {
    seed(false);
    const view = render(wrap(<TrainerSlot />));
    await settle();
    expect(view.container.innerHTML).toBe('');
    expectNoRequests();
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBeNull();
    expect(dock.loads).toBe(0);
  });

  it('signed out: nothing, and not even the status is asked', async () => {
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    const view = render(wrap(<TrainerSlot />));
    await settle();
    expect(view.container.innerHTML).toBe('');
    expectNoRequests();
  });

  it('an academy box without an enrolment renders nothing and does not load the dock', async () => {
    seed(true, null);
    const view = render(wrap(<TrainerSlot />));
    await settle();
    expect(view.container.innerHTML).toBe('');
    expect(dock.loads).toBe(0);
  });

  it('a failed /me renders nothing', async () => {
    seed(true);
    api.apiGet.mockRejectedValue(new ApiError(503, 'Unavailable', undefined));
    const view = render(wrap(<TrainerSlot />));
    await waitFor(() => expect(api.apiGet).toHaveBeenCalled(), BACKSTOP);
    await settle();
    expect(view.container.innerHTML).toBe('');
    expect(dock.loads).toBe(0);
  });

  it('enrolled: mounts the task dock, and with nothing new no dialog', async () => {
    expect(dock.loads).toBe(0);
    seed(true, meFixture);
    render(wrap(<TrainerSlot />));
    // Resolve both lazy chunks the Suspense waits for, then let React commit.
    await act(async () => {
      await Promise.all([import('./TaskDock'), import('./UnlockHost')]);
    });
    expect(await screen.findByTestId('task-dock', {}, BACKSTOP)).toBeInTheDocument();
    expect(dock.loads).toBe(1);
    await settle();
    expect(screen.queryByRole('dialog')).toBeNull();
  });

  it('a different user in the same tab resets the trainer UI state, even with the trainer off', async () => {
    seed(false);
    render(wrap(<TrainerSlot />));
    act(() => {
      useTrainerUiStore.getState().openTask('t2-markups');
      useTrainerUiStore.getState().markCelebrated('bid_management');
    });
    act(() => {
      useAuthStore.setState({ userId: 'user-b' });
    });
    await waitFor(() => expect(useTrainerUiStore.getState().celebrated).toEqual([]), BACKSTOP);
    expect(useTrainerUiStore.getState().dockTaskId).toBeNull();
  });
});
