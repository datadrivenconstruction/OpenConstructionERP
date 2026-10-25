import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import type { ReactNode } from 'react';

const apiGet = vi.fn();
vi.mock('@/shared/lib/api', () => ({ apiGet: (...a: unknown[]) => apiGet(...a) }));

import { usePartnerPack } from '../usePartnerPack';
import { useAuthStore } from '@/stores/useAuthStore';

function wrapper({ children }: { children: ReactNode }) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{children}</QueryClientProvider>;
}

describe('usePartnerPack', () => {
  beforeEach(() => apiGet.mockReset().mockResolvedValue({ active: false }));

  it('does not ask for the active pack before sign-in', async () => {
    useAuthStore.setState({ isAuthenticated: false });
    renderHook(() => usePartnerPack(), { wrapper });
    await new Promise((r) => setTimeout(r, 20));
    expect(apiGet).not.toHaveBeenCalled();
  });

  it('asks once signed in', async () => {
    useAuthStore.setState({ isAuthenticated: true });
    renderHook(() => usePartnerPack(), { wrapper });
    await waitFor(() => expect(apiGet).toHaveBeenCalledWith('/v1/partner-pack/current'));
  });
});
