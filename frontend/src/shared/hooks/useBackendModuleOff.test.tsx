// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction

import type { ReactNode } from 'react';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { renderHook, waitFor } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const api = vi.hoisted(() => ({ apiGet: vi.fn() }));
vi.mock('@/shared/lib/api', async (importOriginal) => ({
  ...(await importOriginal<typeof import('@/shared/lib/api')>()),
  apiGet: (...a: unknown[]) => api.apiGet(...a),
}));

import { useBackendModuleOff } from './useBackendModuleOff';

let client: QueryClient;
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  api.apiGet.mockReset();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe('useBackendModuleOff', () => {
  it('reads the shared catalogue and reports only a disabled optional module as off', async () => {
    api.apiGet.mockResolvedValue([
      { name: 'oe_bim_hub', enabled: false, is_core: false },
      { name: 'oe_boq', enabled: false, is_core: true },
      { name: 'oe_clash', enabled: true, is_core: false },
    ]);
    const { result } = renderHook(() => useBackendModuleOff(), { wrapper });
    await waitFor(() => expect(result.current('oe_bim_hub')).toBe(true));
    expect(api.apiGet).toHaveBeenCalledWith('/v1/modules/');
    expect(result.current('oe_boq')).toBe(false);
    expect(result.current('oe_clash')).toBe(false);
    expect(result.current('oe_not_listed')).toBe(false);
  });

  it('fails open while loading and when the catalogue cannot be read', async () => {
    api.apiGet.mockImplementation(() => Promise.reject(new Error('HTTP 500')));
    const { result } = renderHook(() => useBackendModuleOff(), { wrapper });
    expect(result.current('oe_bim_hub')).toBe(false);
    await waitFor(() => expect(client.getQueryState(['system-modules'])?.status).toBe('error'));
    expect(result.current('oe_bim_hub')).toBe(false);
  });
});
