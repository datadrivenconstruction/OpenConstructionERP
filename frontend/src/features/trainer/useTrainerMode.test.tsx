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
import { meFixture } from './__fixtures__/me';
import {
  TRAINER_MODE_STORAGE_KEY,
  __resetTrainerCacheOwnerForTests,
  readCachedAcademyFlag,
  resolveTrainerMode,
  useTrainerMode,
  writeCachedAcademyFlag,
} from './useTrainerMode';
import { useTrainerUiStore } from './useTrainerUiStore';

let client: QueryClient;

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function serve(status: unknown, me: unknown | (() => unknown)) {
  api.apiGet.mockImplementation(async (path: string) => {
    if (path === '/system/status') {
      if (status instanceof Error) throw status;
      return status;
    }
    if (path === '/v1/trainer/me') {
      const value = typeof me === 'function' ? (me as () => unknown)() : me;
      if (value instanceof Error) throw value;
      return value;
    }
    throw new Error(`unexpected GET ${path}`);
  });
}

beforeEach(() => {
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  api.apiGet.mockReset();
  localStorage.clear();
  __resetTrainerCacheOwnerForTests();
  useTrainerUiStore.getState().reset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
});
afterEach(() => {
  client.clear();
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
});

describe('resolveTrainerMode', () => {
  const base = { signedIn: true, statusSettled: true, statusFlag: true, cachedFlag: false, meStatus: 'success' as const, me: meFixture };

  it('status not settled: the cached flag decides between off and checking', () => {
    expect(resolveTrainerMode({ ...base, statusSettled: false })).toEqual({ state: 'off', academyMode: false, known: false });
    expect(resolveTrainerMode({ ...base, statusSettled: false, cachedFlag: true })).toEqual({
      state: 'checking',
      academyMode: true,
      known: false,
    });
  });

  it('signed out is off and settled, whatever the cache says', () => {
    expect(resolveTrainerMode({ ...base, signedIn: false, statusSettled: false, cachedFlag: true })).toEqual({
      state: 'off',
      academyMode: false,
      known: true,
    });
  });

  it('a settled flag off wins over the cache', () => {
    expect(resolveTrainerMode({ ...base, statusFlag: false, cachedFlag: true }).state).toBe('off');
  });

  it('walks the enrolment states', () => {
    expect(resolveTrainerMode({ ...base, meStatus: 'pending', me: undefined }).state).toBe('loading');
    expect(resolveTrainerMode({ ...base, meStatus: 'error', me: undefined }).state).toBe('error');
    expect(resolveTrainerMode({ ...base, me: null }).state).toBe('none');
    expect(resolveTrainerMode(base).state).toBe('enrolled');
  });

  it('a failed background refetch keeps the course that is on screen', () => {
    expect(resolveTrainerMode({ ...base, meStatus: 'error' }).state).toBe('enrolled');
  });
});

describe('the cached flag', () => {
  it('round-trips and removes the key when off', () => {
    writeCachedAcademyFlag(true);
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBe('1');
    expect(readCachedAcademyFlag()).toBe(true);
    writeCachedAcademyFlag(false);
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBeNull();
    expect(readCachedAcademyFlag()).toBe(false);
  });

  it('survives storage that throws', () => {
    const get = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    const set = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked');
    });
    try {
      expect(readCachedAcademyFlag()).toBe(false);
      expect(() => writeCachedAcademyFlag(true)).not.toThrow();
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });
});

describe('useTrainerMode', () => {
  it('normal install: off, no trainer request, and no key written', async () => {
    serve({ academy_mode: false }, meFixture);
    const setItem = vi.spyOn(Storage.prototype, 'setItem');
    try {
      const { result } = renderHook(() => useTrainerMode(), { wrapper });
      await waitFor(() => expect(result.current.known).toBe(true));
      expect(result.current).toMatchObject({ state: 'off', academyMode: false, active: false, me: null });
      expect(api.apiGet.mock.calls.map(([p]) => p)).toEqual(['/system/status']);
      expect(setItem).not.toHaveBeenCalled();
      expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBeNull();
    } finally {
      setItem.mockRestore();
    }
  });

  it('enrolled learner: active with the course, and the flag mirrored', async () => {
    serve({ academy_mode: true }, meFixture);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.state).toBe('enrolled'));
    expect(result.current).toMatchObject({ academyMode: true, known: true, active: true });
    expect(result.current.me).toBe(meFixture);
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBe('1');
  });

  it('academy box without an enrolment: none, nothing active', async () => {
    serve({ academy_mode: true }, new ApiError(404, 'Not Found', { detail: 'no enrolment' }));
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.state).toBe('none'));
    expect(result.current).toMatchObject({ academyMode: true, active: false, me: null });
  });

  it('a failed /me is an error state, and refetch recovers', async () => {
    let fail = true;
    serve({ academy_mode: true }, () => (fail ? new ApiError(503, 'Unavailable', undefined) : meFixture));
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.state).toBe('error'));
    fail = false;
    act(() => result.current.refetch());
    await waitFor(() => expect(result.current.state).toBe('enrolled'));
  });

  it('a failed status fails open and keeps the cached flag for the next visit', async () => {
    writeCachedAcademyFlag(true);
    serve(new ApiError(500, 'boom', undefined), meFixture);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    expect(result.current.state).toBe('checking');
    await waitFor(() => expect(result.current.known).toBe(true));
    expect(result.current.state).toBe('off');
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBe('1');
  });

  it('the box leaving academy mode clears the cached flag', async () => {
    writeCachedAcademyFlag(true);
    serve({ academy_mode: false }, meFixture);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.known).toBe(true));
    expect(localStorage.getItem(TRAINER_MODE_STORAGE_KEY)).toBeNull();
  });

  it('signed out: off, even with a cached flag the status cannot confirm', () => {
    writeCachedAcademyFlag(true);
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    serve({ academy_mode: true }, meFixture);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    expect(result.current).toMatchObject({ state: 'off', known: true, academyMode: false });
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('a different user in the same tab never sees the previous course', async () => {
    const otherCourse = { ...meFixture, course: { ...meFixture.course, id: 'other-course' } };
    let current: unknown = meFixture;
    serve({ academy_mode: true }, () => current);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.me?.course.id).toBe('fx-quillmere-1'));
    act(() => {
      useTrainerUiStore.getState().openTask('t2-markups');
      useTrainerUiStore.getState().setDraft('t2-markups', 'overheads_amount', '3,581');
      useTrainerUiStore.getState().markCelebrated('boq.markups_panel');
    });

    current = otherCourse;
    act(() => useAuthStore.setState({ userId: 'user-b' }));
    await waitFor(() => expect(result.current.me?.course.id).toBe('other-course'));
    expect(useTrainerUiStore.getState()).toMatchObject({ drafts: {}, celebrated: [], dockTaskId: null });
  });

  it('never touches the UI language or the view mode', async () => {
    serve({ academy_mode: true }, meFixture);
    const { result } = renderHook(() => useTrainerMode(), { wrapper });
    await waitFor(() => expect(result.current.state).toBe('enrolled'));
    expect(api.apiPost).not.toHaveBeenCalled();
    expect(api.apiPut).not.toHaveBeenCalled();
  });
});
