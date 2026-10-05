// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { act, renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn(), apiPost: vi.fn(), apiPut: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { ApiError } from '@/shared/lib/api';
import { useAuthStore } from '@/stores/useAuthStore';
import { attemptPassFixture } from './__fixtures__/attemptPass';
import { meFixture } from './__fixtures__/me';
import { readbackFixture } from './__fixtures__/readback';
import { taskFixture } from './__fixtures__/task';
import {
  trainerKeys,
  useCheckTrainerTask,
  useMarkUnlockSeen,
  useRevealTrainerHint,
  useSaveTrainerAnswers,
  useTrainerMe,
  useTrainerReadback,
  useTrainerTask,
} from './queries';
import type { AnswersSaved, TaskView, TrainerMe } from './types';

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function routeGet(status: unknown) {
  api.apiGet.mockImplementation(async (path: string) => {
    if (path === '/system/status') return status;
    if (path === '/v1/trainer/me') return meFixture;
    if (path === '/v1/trainer/tasks/t2-markups') return taskFixture;
    if (path === '/v1/trainer/tasks/t2-markups/readback') return readbackFixture;
    throw new Error(`unexpected GET ${path}`);
  });
}

const trainerCalls = () => api.apiGet.mock.calls.filter(([p]) => String(p).startsWith('/v1/trainer/'));

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  api.apiPost.mockReset();
  api.apiPut.mockReset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
});
afterEach(() => {
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
});

describe('trainer queries stay idle outside academy mode', () => {
  it.each([
    ['academy_mode false', { academy_mode: false }],
    ['academy_mode absent', { demo_mode: false }],
    ['a non-object body', []],
  ])('%s: no trainer request at all', async (_label, status) => {
    routeGet(status);
    const { result } = renderHook(
      () => ({ me: useTrainerMe(), task: useTrainerTask('t2-markups'), rb: useTrainerReadback('t2-markups') }),
      { wrapper },
    );
    await waitFor(() => expect(client.getQueryState(['system-status'])?.status).toBe('success'));
    expect(result.current.me.fetchStatus).toBe('idle');
    expect(trainerCalls()).toEqual([]);
  });

  it('without a session nothing runs, not even the status', () => {
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    routeGet({ academy_mode: true });
    renderHook(() => useTrainerMe(), { wrapper });
    expect(api.apiGet).not.toHaveBeenCalled();
  });
});

describe('trainer queries in academy mode', () => {
  it('loads /me, the task and the readback under the design keys', async () => {
    routeGet({ academy_mode: true });
    const { result } = renderHook(
      () => ({ me: useTrainerMe(), task: useTrainerTask('t2-markups'), rb: useTrainerReadback('t2-markups') }),
      { wrapper },
    );
    await waitFor(() => expect(result.current.rb.isSuccess).toBe(true));
    await waitFor(() => expect(result.current.task.isSuccess).toBe(true));
    expect(result.current.me.data).toBe(meFixture);
    expect(client.getQueryData(['trainer', 'me'])).toBe(meFixture);
    expect(client.getQueryData(['trainer', 'task', 't2-markups'])).toBe(taskFixture);
    expect(client.getQueryData(['trainer', 'readback', 't2-markups'])).toBe(readbackFixture);
  });

  it('reads a /me 404 as data null, not as an error', async () => {
    api.apiGet.mockImplementation(async (path: string) => {
      if (path === '/system/status') return { academy_mode: true };
      throw new ApiError(404, 'Not Found', { detail: 'no enrolment' });
    });
    const { result } = renderHook(() => useTrainerMe(), { wrapper });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(result.current.data).toBeNull();
  });

  it('a task query without an id stays idle', async () => {
    routeGet({ academy_mode: true });
    const { result } = renderHook(() => useTrainerTask(null), { wrapper });
    await waitFor(() => expect(client.getQueryState(['system-status'])?.status).toBe('success'));
    expect(result.current.fetchStatus).toBe('idle');
  });

  it('the readback is always stale, refetches on focus, and fails quietly', () => {
    routeGet({ academy_mode: true });
    renderHook(() => useTrainerReadback('t2-markups'), { wrapper });
    const query = client.getQueryCache().find({ queryKey: trainerKeys.readback('t2-markups') });
    const options = query?.options as { staleTime?: number; refetchOnWindowFocus?: boolean } | undefined;
    expect(options?.staleTime).toBe(0);
    expect(options?.refetchOnWindowFocus).toBe(true);
    expect(query?.meta).toEqual({ suppressGlobalErrorToast: true });
  });
});

describe('trainer mutations', () => {
  function seed() {
    client.setQueryData(trainerKeys.me(), meFixture);
    client.setQueryData(trainerKeys.task('t2-markups'), taskFixture);
    client.setQueryData(trainerKeys.readback('t2-markups'), readbackFixture);
  }
  const invalidated = (key: readonly unknown[]) => client.getQueryState(key)?.isInvalidated === true;

  it('saving answers writes the new revision into the task and refreshes /me', async () => {
    seed();
    const saved: AnswersSaved = { task_id: 't2-markups', revision: 9, answers: [] };
    api.apiPut.mockResolvedValue(saved);
    const { result } = renderHook(() => useSaveTrainerAnswers('t2-markups'), { wrapper });
    await act(() => result.current.mutateAsync({ answers: [], revision: taskFixture.answers_revision }));
    const task = client.getQueryData<TaskView>(trainerKeys.task('t2-markups'));
    expect(task?.answers_revision).toBe(9);
    expect(task?.answers).toEqual([]);
    expect(invalidated(trainerKeys.me())).toBe(true);
    expect(invalidated(trainerKeys.task('t2-markups'))).toBe(true);
  });

  it('a stale revision (409) refetches the task', async () => {
    seed();
    api.apiPut.mockRejectedValue(new ApiError(409, 'Conflict', { detail: 'stale' }));
    const { result } = renderHook(() => useSaveTrainerAnswers('t2-markups'), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ answers: [], revision: 1 }).catch(() => undefined);
    });
    expect(invalidated(trainerKeys.task('t2-markups'))).toBe(true);
  });

  it('a check stores the attempt and refreshes /me, the task and the readback', async () => {
    seed();
    api.apiPost.mockResolvedValue(attemptPassFixture);
    const { result } = renderHook(() => useCheckTrainerTask('t2-markups'), { wrapper });
    await act(() => result.current.mutateAsync({ client_attempt_id: 'a-1', revision: 3 }));
    expect(api.apiPost).toHaveBeenCalledWith('/v1/trainer/tasks/t2-markups/check', {
      client_attempt_id: 'a-1',
      revision: 3,
    });
    expect(client.getQueryData<TaskView>(trainerKeys.task('t2-markups'))?.last_attempt).toEqual(attemptPassFixture);
    expect(invalidated(trainerKeys.me())).toBe(true);
    expect(invalidated(trainerKeys.task('t2-markups'))).toBe(true);
    expect(invalidated(trainerKeys.readback('t2-markups'))).toBe(true);
  });

  it('a check refused with 409 (locked or stale) refreshes /me and the task', async () => {
    seed();
    api.apiPost.mockRejectedValue(new ApiError(409, 'Conflict', { detail: 'locked' }));
    const { result } = renderHook(() => useCheckTrainerTask('t2-markups'), { wrapper });
    await act(async () => {
      await result.current.mutateAsync({ client_attempt_id: 'a-2', revision: 3 }).catch(() => undefined);
    });
    expect(invalidated(trainerKeys.me())).toBe(true);
    expect(invalidated(trainerKeys.task('t2-markups'))).toBe(true);
  });

  it('revealing a hint refetches the task', async () => {
    seed();
    api.apiPost.mockResolvedValue(undefined);
    const { result } = renderHook(() => useRevealTrainerHint('t2-markups'), { wrapper });
    await act(() => result.current.mutateAsync());
    expect(api.apiPost).toHaveBeenCalledWith('/v1/trainer/tasks/t2-markups/hints/reveal');
    expect(invalidated(trainerKeys.task('t2-markups'))).toBe(true);
  });

  it('marking an unlock seen flips it in the /me cache before the POST answers', async () => {
    seed();
    let release: () => void = () => undefined;
    api.apiPost.mockImplementation(() => new Promise<void>((r) => (release = () => r())));
    const { result } = renderHook(() => useMarkUnlockSeen(), { wrapper });
    act(() => result.current.mutate('bid_management'));
    await waitFor(() => {
      const me = client.getQueryData<TrainerMe>(trainerKeys.me());
      expect(me?.unlocks.find((u) => u.lock_id === 'bid_management')?.seen).toBe(true);
    });
    const me = client.getQueryData<TrainerMe>(trainerKeys.me());
    // Only the named unlock flips; the one already seen stays seen, the rest stay unseen.
    expect(me?.unlocks.filter((u) => u.seen).map((u) => u.lock_id)).toEqual(['boq.markups_panel', 'bid_management']);
    expect(api.apiPost).toHaveBeenCalledWith('/v1/trainer/unlocks/bid_management/seen');
    await act(async () => release());
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(invalidated(trainerKeys.me())).toBe(true);
  });

  it('no trainer mutation sets a mutationKey (the global cache would flush every trainer query)', async () => {
    api.apiPost.mockResolvedValue(attemptPassFixture);
    api.apiPut.mockResolvedValue({ task_id: 't', revision: 1, answers: [] });
    const { result } = renderHook(
      () => ({
        save: useSaveTrainerAnswers('t'),
        check: useCheckTrainerTask('t'),
        hint: useRevealTrainerHint('t'),
        seen: useMarkUnlockSeen(),
      }),
      { wrapper },
    );
    await act(async () => {
      await result.current.save.mutateAsync({ answers: [], revision: 0 });
      await result.current.check.mutateAsync({ client_attempt_id: 'x', revision: 1 });
      await result.current.hint.mutateAsync();
      await result.current.seen.mutateAsync('variations');
    });
    const all = client.getMutationCache().getAll();
    expect(all).toHaveLength(4);
    for (const mutation of all) {
      expect(mutation.options.mutationKey).toBeUndefined();
      expect(mutation.meta).toEqual({ suppressGlobalErrorToast: true });
    }
  });
});
