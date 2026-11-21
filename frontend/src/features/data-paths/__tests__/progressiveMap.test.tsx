import { describe, expect, it, vi } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const pending: Array<(v: unknown) => void> = [];
vi.mock('@/shared/lib/api', () => ({
  apiGet: vi.fn((url: string) =>
    url.includes('project_id')
      ? new Promise((resolve) => pending.push(resolve)) // the project's counts take seconds
      : Promise.resolve({ modules: [{ name: 'oe_boq' }], edges: [], health: [] }),
  ),
}));

const { usePlatformMapProgressive } = await import('../api');

const wrapper = ({ children }: { children: ReactNode }) => (
  <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{children}</QueryClientProvider>
);

describe('data paths drawer map', () => {
  it('draws the map at once and fills in the project numbers when they land', async () => {
    const { result } = renderHook(() => usePlatformMapProgressive('p1'), { wrapper });
    await waitFor(() => expect(result.current.data).toBeTruthy());
    expect(result.current.isLoading).toBe(false);
    expect(result.current.countsLoading).toBe(true);
    pending.forEach((r) => r({ modules: [{ name: 'oe_boq', count: 7 }], edges: [], health: [] }));
    await waitFor(() => expect(result.current.countsLoading).toBe(false));
    expect((result.current.data?.modules[0] as { count?: number }).count).toBe(7);
  });
});
