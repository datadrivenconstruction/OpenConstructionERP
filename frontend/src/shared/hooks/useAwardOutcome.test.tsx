// DDC-CWICR-OE: DataDrivenConstruction · OpenConstructionERP
// Copyright (c) 2026 Artem Boiko / DataDrivenConstruction
//
// The award lookup answers three different things and the screens draw them
// differently: found (link to the record), absent (the whole register was
// read and nothing carries the stamp) and unknown (the read failed, or the
// register is longer than the page that was read). The difference that
// matters is between the last two: a truncated register that does not show
// the stamp has not shown that the record does not exist.

import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
import type { ReactNode } from 'react';
import { renderHook, waitFor, act } from '@testing-library/react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';

const apiGetMock = vi.fn();

vi.mock('@/shared/lib/api', async (importOriginal) => {
  const actual = await importOriginal<typeof import('@/shared/lib/api')>();
  return { ...actual, apiGet: (url: string) => apiGetMock(url) };
});

import { useAwardOutcome } from './useAwardOutcome';

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function route(contracts: unknown, orders: unknown): void {
  apiGetMock.mockImplementation((url: string) => {
    if (url.startsWith('/v1/contracts/contracts/')) {
      return contracts instanceof Error ? Promise.reject(contracts) : Promise.resolve(contracts);
    }
    if (url.startsWith('/v1/procurement/')) {
      return orders instanceof Error ? Promise.reject(orders) : Promise.resolve(orders);
    }
    return Promise.resolve([]);
  });
}

const page = (items: unknown[], total = items.length) => ({ items, total, offset: 0, limit: 200 });
const KEYS = { tender_package_id: 'tp-1' };

beforeEach(() => {
  apiGetMock.mockReset();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('useAwardOutcome', () => {
  it('finds the stamped contract and order', async () => {
    route(
      page([{ id: 'ct-1', code: 'C-1', status: 'draft', metadata: { tender_package_id: 'tp-1' } }]),
      page([{ id: 'po-1', po_number: 'PO-1', status: 'draft', metadata: { tender_package_id: 'tp-1' } }]),
    );
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('found'));
    await waitFor(() => expect(result.current.order.state).toBe('found'));
    const contract = result.current.contract;
    expect(contract.state === 'found' && contract.record.id).toBe('ct-1');
  });

  it('reads a whole register without the stamp as absent', async () => {
    route(page([{ id: 'ct-1', code: 'C-1', status: 'draft', metadata: {} }]), page([]));
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('absent'));
    await waitFor(() => expect(result.current.order.state).toBe('absent'));
  });

  it('reads a truncated register without the stamp as unknown, not absent', async () => {
    route(page([{ id: 'ct-1', code: 'C-1', status: 'draft', metadata: {} }], 350), page([]));
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('unknown'));
  });

  it('still finds the stamp on a truncated register when the page holds it', async () => {
    route(page([{ id: 'ct-1', code: 'C-1', status: 'draft', metadata: { tender_package_id: 'tp-1' } }], 350), page([]));
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('found'));
  });

  it('reads a failed read and a body that is not a page as unknown', async () => {
    route(Object.assign(new Error('forbidden'), { status: 403 }), [{ id: 'po-1' }]);
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('unknown'));
    await waitFor(() => expect(result.current.order.state).toBe('unknown'));
  });

  it('picks up a draft that lands after the first read', async () => {
    // The award subscribers run detached after the award commits, so the read
    // made the moment the package flips to awarded usually misses the draft.
    let contractReads = 0;
    apiGetMock.mockImplementation((url: string) => {
      if (url.startsWith('/v1/contracts/contracts/')) {
        contractReads += 1;
        const items =
          contractReads === 1
            ? []
            : [{ id: 'ct-late', code: 'C-LATE', status: 'draft', metadata: { tender_package_id: 'tp-1' } }];
        return Promise.resolve(page(items));
      }
      return Promise.resolve(page([]));
    });
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, true), { wrapper });

    await waitFor(() => expect(result.current.contract.state).toBe('absent'));
    await waitFor(() => expect(result.current.contract.state).toBe('found'), { timeout: 6000 });
    expect(contractReads).toBe(2);
  }, 10_000);

  it('gives the next award of a project its own re-reads', async () => {
    // One client for the whole session, with the app's two minutes of
    // freshness, as in main.tsx. The first award's draft never appears (its
    // module is not installed), so its lookup spends every re-read. The next
    // award on the same project must still read, and keep reading until its
    // own draft lands, instead of inheriting a spent budget from a cache
    // entry the two awards shared.
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: 120_000 } } });
    const shared = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{children}</QueryClientProvider>
    );

    let secondAwardLanded = false;
    let contractReads = 0;
    apiGetMock.mockImplementation((url: string) => {
      if (url.startsWith('/v1/contracts/contracts/')) {
        contractReads += 1;
        const items = secondAwardLanded
          ? [{ id: 'ct-2', code: 'C-2', status: 'draft', metadata: { tender_package_id: 'tp-2' } }]
          : [];
        return Promise.resolve(page(items));
      }
      return Promise.resolve(page([]));
    });

    const first = renderHook(() => useAwardOutcome('proj-1', { tender_package_id: 'tp-1' }, true), {
      wrapper: shared,
    });
    await waitFor(() => expect(first.result.current.contract.state).toBe('absent'));
    for (let i = 0; i < 6; i += 1) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(3000);
      });
    }
    const spent = contractReads;
    expect(spent).toBe(5);
    first.unmount();

    // The second package flips to awarded: the lookup turns on.
    let awarded = false;
    const second = renderHook(() => useAwardOutcome('proj-1', { tender_package_id: 'tp-2' }, awarded), {
      wrapper: shared,
    });
    awarded = true;
    second.rerender();
    await waitFor(() => expect(contractReads).toBe(spent + 1));
    expect(second.result.current.contract.state).toBe('absent');

    secondAwardLanded = true;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(3000);
    });
    await waitFor(() => expect(second.result.current.contract.state).toBe('found'));
  }, 20_000);

  it('fetches nothing before the award', async () => {
    route(page([]), page([]));
    const { result } = renderHook(() => useAwardOutcome('proj-1', KEYS, false), { wrapper });

    expect(result.current.contract.state).toBe('unknown');
    expect(apiGetMock).not.toHaveBeenCalled();
  });
});
