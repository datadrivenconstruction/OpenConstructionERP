// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock('@/shared/lib/api', async () => {
  const actual = await vi.importActual<typeof import('@/shared/lib/api')>('@/shared/lib/api');
  return { ...actual, ...api };
});

import { useAuthStore } from '@/stores/useAuthStore';
import { SYSTEM_STATUS_QUERY_KEY, academyModeFrom, demoModeFrom, useSystemStatus } from './useSystemStatus';

function wrapperFor(client: QueryClient) {
  return ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function newClient() {
  return new QueryClient({ defaultOptions: { queries: { retry: false } } });
}

beforeEach(() => {
  api.apiGet.mockReset();
  useAuthStore.setState({ isAuthenticated: true, userId: 'user-a', accessToken: null });
});
afterEach(() => {
  useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
});

describe('academyModeFrom', () => {
  it('is on only for academy_mode: true', () => {
    expect(academyModeFrom({ academy_mode: true })).toBe(true);
  });

  it('is off for an absent, false or non-boolean flag', () => {
    expect(academyModeFrom({})).toBe(false);
    expect(academyModeFrom({ academy_mode: false })).toBe(false);
    expect(academyModeFrom({ academy_mode: 'true' })).toBe(false);
    expect(academyModeFrom({ academy_mode: 1 })).toBe(false);
  });

  it('is off for a body that is not an object (component tests answer [])', () => {
    expect(academyModeFrom([])).toBe(false);
    expect(academyModeFrom([{ academy_mode: true }])).toBe(false);
    expect(academyModeFrom(null)).toBe(false);
    expect(academyModeFrom(undefined)).toBe(false);
    expect(academyModeFrom('academy_mode')).toBe(false);
  });

  it('reads demo_mode by the same rules', () => {
    expect(demoModeFrom({ demo_mode: true })).toBe(true);
    expect(demoModeFrom([])).toBe(false);
  });
});

describe('useSystemStatus', () => {
  it('uses the shared key and the /system/status path', async () => {
    api.apiGet.mockResolvedValue({ academy_mode: true });
    const client = newClient();
    const { result } = renderHook(() => useSystemStatus(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(result.current.isSuccess).toBe(true));
    expect(SYSTEM_STATUS_QUERY_KEY).toEqual(['system-status']);
    expect(api.apiGet).toHaveBeenCalledTimes(1);
    expect(api.apiGet).toHaveBeenCalledWith('/system/status');
    expect(client.getQueryData(['system-status'])).toEqual({ academy_mode: true });
  });

  it('adds no request when another observer already filled the key', async () => {
    const client = newClient();
    client.setQueryData(['system-status'], { demo_mode: false, academy_mode: true });
    const { result } = renderHook(() => useSystemStatus(), { wrapper: wrapperFor(client) });
    expect(academyModeFrom(result.current.data)).toBe(true);
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('shares one request with an existing observer declared like DemoBanner', async () => {
    api.apiGet.mockResolvedValue({ demo_mode: true });
    const client = newClient();
    const { result } = renderHook(
      () => {
        const banner = useQuery({
          queryKey: ['system-status'],
          queryFn: () => api.apiGet('/system/status') as Promise<{ demo_mode?: boolean }>,
          retry: false,
          staleTime: Infinity,
        });
        const status = useSystemStatus();
        return { banner, status };
      },
      { wrapper: wrapperFor(client) },
    );
    await waitFor(() => expect(result.current.status.isSuccess).toBe(true));
    expect(api.apiGet).toHaveBeenCalledTimes(1);
    expect(result.current.banner.data).toEqual({ demo_mode: true });
  });

  it('stays idle without a session, because the endpoint is signed-in only', async () => {
    useAuthStore.setState({ isAuthenticated: false, userId: null, accessToken: null });
    const { result } = renderHook(() => useSystemStatus(), { wrapper: wrapperFor(newClient()) });
    expect(result.current.fetchStatus).toBe('idle');
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('honours an extra enabled gate', () => {
    const { result } = renderHook(() => useSystemStatus({ enabled: false }), { wrapper: wrapperFor(newClient()) });
    expect(result.current.fetchStatus).toBe('idle');
    expect(api.apiGet).not.toHaveBeenCalled();
  });

  it('does not retry a failed status', async () => {
    api.apiGet.mockRejectedValue(new Error('down'));
    const client = new QueryClient();
    const { result } = renderHook(() => useSystemStatus(), { wrapper: wrapperFor(client) });
    await waitFor(() => expect(result.current.isError).toBe(true));
    expect(api.apiGet).toHaveBeenCalledTimes(1);
    expect(academyModeFrom(result.current.data)).toBe(false);
  });
});
